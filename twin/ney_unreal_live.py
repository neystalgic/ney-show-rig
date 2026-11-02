"""NEY live link for Unreal -- the four virtual heads follow the real ones.

Run ONCE in Unreal:  Tools > Execute Python Script... > pick this file.
After that it starts by itself every time the project opens (it installs
Content/Python/init_unreal.py, which Unreal runs on startup).

What it does
  * finds the imported room (ney_room.glb plot + ney_room_scan.glb LiDAR scan)
  * hides the gray plot model (the scan is the real room) -- just hidden, nothing deleted
  * hides the outdoor sun / sky / clouds and dims the sky light so the room is dark
  * turns on volumetric fog (virtual haze -- the real room stays hazer-free) so beams show
  * adds 4 spotlights "NEY Head 1-4" at the real heads' spots
  * reads the DMX node (Zephyrus, port 7060 /status -- the same page the hub reads)
    and copies each head's real, post-safety pan / tilt / dimmer / colour, live

Console commands (Output Log, Python):
  import ney_unreal_live as ney
  ney.status()       what it's doing
  ney.demo(True)     slow sweep without the node (False = back to live)
  ney.show_plot()    show the gray plot model again   / ney.hide_plot()
  ney.stop()         stop the live link               / ney.start()
  ney.restore()      undo the room darkening + unhide everything
"""
import json, math, os, struct, sys, threading, time, urllib.request
import unreal

TWIN = os.path.expanduser('~/Touchdesigner Designs/Hue Rig/twin')
if not os.path.isdir(TWIN):
    TWIN = os.path.dirname(os.path.abspath(__file__))
NODE_HOSTS = ['192.168.1.79', 'zephyrus']          # LAN first, Tailscale fallback (same as the hub)
NODE_PORT = 7060
PAN_DEG, TILT_DEG = 540.0, 180.0                     # Betopper LM70S
MASTER_MIN, MASTER_MAX = 8, 134
BEAM_HALF = 6.5                                      # degrees (outer cone half-angle)
CANDELA = 6000.0                                     # virtual brightness at full
LENS_CM = 18.0                                       # light sits this far out along the beam (clears the scanned head mesh)
TAG = 'ney'
INIT_MARK = '# NEY auto-start'

S = sys.modules.setdefault('_ney_live_state', type(sys)('_ney_live_state'))
for k, v in dict(tick=None, thread=None, run=False, status=None, cfg=None, host=None, err='', polls=0,
                 last_ok=0.0, demo=False, world=None, heads=[], map=None, log_t=0.0, cur={}).items():
    if not hasattr(S, k):
        setattr(S, k, v)


def log(msg):
    unreal.log('[NEY] ' + msg)


def _actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()


def _norm(s):
    return ''.join(ch for ch in s.lower() if ch.isalnum())


def _glb_names(path):
    try:
        b = open(path, 'rb').read()
        n = struct.unpack('<I', b[12:16])[0]
        return [x.get('name', '') for x in json.loads(b[20:20 + n]).get('nodes', [])]
    except Exception:
        return []


# ---------------------------------------------------------------- room mapping (glTF metres -> Unreal cm)
FLOOR_C = (2.8956, 1.6629)          # ney_room.glb Floor centre (x, z) metres
FLOOR_E = (4.1148, 1.9312)          # half-extents


def find_mapping():
    """Work out how the GLB landed in Unreal from where the plot's Floor ended up."""
    best = None
    for a in _actors():
        if not _norm(a.get_actor_label()).startswith('floor'):
            continue
        o, e = a.get_actor_bounds(False)
        for swap in (False, True):
            ex, ey = (e.y, e.x) if swap else (e.x, e.y)
            err = abs(ex - FLOOR_E[0] * 100) + abs(ey - FLOOR_E[1] * 100)
            if best is None or err < best[0]:
                best = (err, swap, o)
    if best is None or best[0] > 60:
        log('could not find the plot Floor -- assuming the standard glTF import (X east, Y south, Z up)')
        return dict(swap=False, sx=1, sy=1, off=(0.0, 0.0, 0.0))
    _, swap, o = best
    cx, cy = (o.y, o.x) if swap else (o.x, o.y)
    # sign: the floor centre is at +x, +z in glTF; if it landed negative, that axis is mirrored
    sx = 1 if cx >= 0 or abs(cx) < 50 else -1
    sy = 1 if cy >= 0 or abs(cy) < 50 else -1
    off = (cx - sx * FLOOR_C[0] * 100, cy - sy * FLOOR_C[1] * 100, o.z)
    return dict(swap=swap, sx=sx, sy=sy, off=off)


def to_ue(m, x, y, z, point=True):
    """glTF (x east, y up, z south) -> unreal.Vector"""
    a, b = m['sx'] * x * 100, m['sy'] * z * 100
    if point:
        a, b = a + m['off'][0], b + m['off'][1]
    ux, uy = (b, a) if m['swap'] else (a, b)
    return unreal.Vector(ux, uy, y * 100 + (m['off'][2] if point else 0))


# ---------------------------------------------------------------- scene setup
def _hide(a, on=True):
    try:
        a.set_is_temporarily_hidden_in_editor(on)
        a.set_actor_hidden_in_game(on)
    except Exception:
        pass


def hide_plot(on=True):
    names = {_norm(n) for n in _glb_names(os.path.join(TWIN, 'ney_room.glb')) if n}
    n = 0
    for a in _actors():
        if a.actor_has_tag(TAG):
            continue
        lab = _norm(a.get_actor_label())
        if lab in names or lab.rstrip('0123456789') in names:
            _hide(a, on)
            n += 1
    log(('hid ' if on else 'showed ') + str(n) + ' plot pieces')


def show_plot():
    hide_plot(False)


def darken_room():
    for a in _actors():
        if a.actor_has_tag(TAG):
            continue
        if isinstance(a, (unreal.DirectionalLight, unreal.SkyAtmosphere)) or 'volumetriccloud' in _norm(a.get_class().get_name()):
            _hide(a, True)
        elif isinstance(a, unreal.SkyLight):
            try:
                c = a.light_component
                c.set_intensity(0.08)
                c.recapture_sky()
            except Exception:
                pass
    fog = None
    for a in _actors():
        if isinstance(a, unreal.ExponentialHeightFog):
            fog = a
            break
    if fog is None:
        fog = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
            unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0))
        fog.set_actor_label('NEY Haze (virtual)')
        fog.tags = [unreal.Name(TAG)]
    c = fog.component
    for k, v in (('fog_density', 0.05), ('fog_height_falloff', 0.001), ('volumetric_fog', True),
                 ('volumetric_fog_scattering_distribution', 0.5), ('volumetric_fog_extinction_scale', 1.0),
                 ('volumetric_fog_albedo', unreal.Color(255, 255, 255, 255)), ('fog_max_opacity', 1.0)):
        try:
            c.set_editor_property(k, v)
        except Exception:
            pass
    try:
        z = S.map['off'][2] if S.map else 0.0
        fog.set_actor_location(unreal.Vector(0, 0, z - 50), False, True)
    except Exception:
        pass
    try:   # keep updating when the editor isn't the front window
        ps = unreal.get_default_object(unreal.EditorPerformanceSettings)
        ps.set_editor_property('throttle_cpu_when_not_foreground', False)
    except Exception:
        pass


def restore():
    stop()
    for a in _actors():
        if a.actor_has_tag(TAG):
            continue
        _hide(a, False)
        if isinstance(a, unreal.SkyLight):
            try:
                a.light_component.set_intensity(1.0)
                a.light_component.recapture_sky()
            except Exception:
                pass
    log('room back to normal (NEY heads + haze left in place; delete them by hand if you want)')


def build_heads():
    fx = json.load(open(os.path.join(TWIN, 'ney_fixtures.json')))['fixtures']
    have = {a.get_actor_label(): a for a in _actors() if a.actor_has_tag(TAG) and isinstance(a, unreal.SpotLight)}
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    heads = []
    for i, f in enumerate(fx):
        lab = 'NEY ' + f['name']
        p = to_ue(S.map, *f['position_m'])
        a = have.get(lab) or sub.spawn_actor_from_class(unreal.SpotLight, p)
        a.set_actor_label(lab)
        a.tags = [unreal.Name(TAG)]
        c = a.spot_light_component
        for fn, v in (('set_mobility', unreal.ComponentMobility.MOVABLE),):
            try:
                getattr(c, fn)(v)
            except Exception:
                pass
        try:
            c.set_editor_property('intensity_units', unreal.LightUnits.CANDELAS)
        except Exception:
            pass
        c.set_inner_cone_angle(BEAM_HALF * 0.55)
        c.set_outer_cone_angle(BEAM_HALF)
        c.set_attenuation_radius(1500.0)
        try:
            c.set_volumetric_scattering_intensity(3.0)
        except Exception:
            pass
        c.set_intensity(0.0)
        heads.append(dict(actor=a, comp=c, pos=p, rot0=float(f.get('pan0_heading_deg_plot', 0)),
                          sgn=-1 if f.get('pan_turns') == 'ccw' else 1, name=f['name']))
    S.heads = heads
    log('virtual heads ready: ' + ', '.join(h['name'] for h in heads))


def setup():
    S.map = find_mapping()
    log('room mapping ' + json.dumps(S.map))
    hide_plot(True)
    darken_room()
    build_heads()
    try:
        S.world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_name()
    except Exception:
        S.world = None


# ---------------------------------------------------------------- reading the node
def _poller():
    k = 0
    while S.run:
        hosts = ([S.host] if S.host else []) + [h for h in NODE_HOSTS if h != S.host]
        ok = False
        for h in hosts:
            try:
                base = 'http://%s:%d/' % (h, NODE_PORT)
                if S.cfg is None or k % 100 == 0:
                    S.cfg = json.loads(urllib.request.urlopen(base + 'config', timeout=1.5).read())
                S.status = json.loads(urllib.request.urlopen(base + 'status', timeout=1.0).read())
                S.host, S.last_ok, S.err, ok = h, time.time(), '', True
                S.polls += 1
                break
            except Exception as e:
                S.err = '%s: %s' % (h, e)
        k += 1
        time.sleep(0.05 if ok else 2.0)


def _aim(h, cfgh, pan16, tilt16):
    """node pan/tilt -> direction in Unreal (same maths as the node's safety layer)"""
    tu = float(cfgh.get('tilt_up', 32768))
    td = 1 if int(cfgh.get('tilt_dir', 1)) >= 0 else -1
    lean = (tilt16 - tu) * td * TILT_DEG / 65535.0
    az = pan16 * PAN_DEG / 65535.0 + (180.0 if lean < 0 else 0.0)
    lean = abs(lean)
    th = math.radians(h['rot0'] + h['sgn'] * az)          # plot heading: x east, y south
    s = math.sin(math.radians(lean))
    return to_ue(S.map, s * math.cos(th), math.cos(math.radians(lean)), s * math.sin(th), point=False)


def _tick(dt):
    try:
        if not S.heads:
            return
        try:
            w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_name()
            if S.world and w != S.world:      # another level opened -- rebuild there
                setup()
        except Exception:
            pass
        now = time.time()
        live = S.status and now - S.last_ok < 3.0 and not S.demo
        for i, h in enumerate(S.heads):
            if S.demo:
                d = unreal.Vector(math.cos(now * 0.4 + i) * 0.6, math.sin(now * 0.4 + i) * 0.6, 0.8)
                lvl, col = 0.8, (0.3 + 0.7 * (i % 2), 0.1, 1.0)
            elif live and i < len(S.status.get('heads', [])):
                st = S.status['heads'][i]
                cfgh = (S.cfg or {}).get('heads', [{}] * 4)[i] if S.cfg else {}
                d = _aim(h, cfgh, st['pan'], st['tilt'])
                m = st.get('master', 0)
                lvl = 0.0 if m < MASTER_MIN else min(1.0, (m - MASTER_MIN) / float(MASTER_MAX - MASTER_MIN))
                r, g, b, wh = [v / 255.0 for v in st.get('rgbw', [0, 0, 0, 0])]
                col = (min(1, r + wh), min(1, g + wh), min(1, b + wh))
            else:
                d, lvl, col = unreal.Vector(0, 0, 1), 0.0, (0, 0, 0)
            peak = max(col) if max(col) > 0 else 0.0
            # smooth a little so 20 updates/s look like the real motors
            prev = S.cur.get(i)
            if prev:
                k = min(1.0, dt * 12.0)
                d = unreal.Vector(prev.x + (d.x - prev.x) * k, prev.y + (d.y - prev.y) * k, prev.z + (d.z - prev.z) * k)
            S.cur[i] = d
            n = math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z) or 1.0
            u = unreal.Vector(d.x / n, d.y / n, d.z / n)
            p = h['pos']
            loc = unreal.Vector(p.x + u.x * LENS_CM, p.y + u.y * LENS_CM, p.z + u.z * LENS_CM)
            h['actor'].set_actor_location_and_rotation(loc, unreal.MathLibrary.make_rot_from_x(u), False, True)
            h['comp'].set_intensity(CANDELA * lvl * peak)
            if peak > 0:
                h['comp'].set_light_color(unreal.LinearColor(col[0] / peak, col[1] / peak, col[2] / peak, 1.0), True)
        if now - S.log_t > 60:
            S.log_t = now
            log(status(quiet=True))
    except Exception as e:
        if time.time() - S.log_t > 10:
            S.log_t = time.time()
            unreal.log_warning('[NEY] tick error: %s' % e)


# ---------------------------------------------------------------- controls
def status(quiet=False):
    age = time.time() - S.last_ok if S.last_ok else None
    s = ('demo sweep' if S.demo else ('LIVE from node %s' % S.host if age is not None and age < 3 else
         'waiting for the DMX node (Zephyrus) -- ' + (S.err or 'no answer yet')))
    s += ' | updates: %d' % S.polls
    if not quiet:
        log(s)
    return s


def demo(on=True):
    S.demo = bool(on)
    status()


def start():
    if S.tick is not None:
        log('already running -- ' + status(quiet=True))
        return
    setup()
    S.run = True
    S.thread = threading.Thread(target=_poller, daemon=True)
    S.thread.start()
    S.tick = unreal.register_slate_post_tick_callback(_tick)
    log('live link started')


def stop():
    S.run = False
    if S.tick is not None:
        unreal.unregister_slate_post_tick_callback(S.tick)
        S.tick = None
    log('live link stopped')


def install_autostart():
    d = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()), 'Python')
    f = os.path.join(d, 'init_unreal.py')
    body = (INIT_MARK + ' -- starts the NEY live link (virtual heads follow the real ones).\n'
            'import os, sys\n'
            'p = os.path.expanduser(%r)\n'
            'if p not in sys.path:\n    sys.path.append(p)\n'
            'try:\n    import ney_unreal_live\n    ney_unreal_live.start()\n'
            'except Exception as e:\n    import unreal\n    unreal.log_warning("[NEY] live link did not start: %%s" %% e)\n') % TWIN
    if os.path.exists(f) and INIT_MARK not in open(f).read():
        log('a different init_unreal.py already exists -- left it alone: ' + f)
        return
    os.makedirs(d, exist_ok=True)
    open(f, 'w').write(body)
    log('auto-start installed: ' + f)


if __name__ == '__main__':
    if TWIN not in sys.path:
        sys.path.append(TWIN)
    import importlib
    import ney_unreal_live as _m
    importlib.reload(_m)
    _m.install_autostart()
    _m.stop()
    _m.start()
