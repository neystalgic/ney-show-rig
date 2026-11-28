"""NEY SCULPTURE -- an abstract colour sculpture for the projector wall, driven live by the rig (Nov 28).

Michael (Nov 28): Unreal visuals, first look = "abstract colour sculpture": large, slow 3D forms of light and colour
(no sacred geometry) that BLOOM on the hits, FRACTURE when a drop lands and MELT in breakdowns, in the same colours
the lights are playing (the Max show's palettes, the rainbow show's ROY G BIV -- whatever the room is doing).

Run in Unreal on the Zephyrus (the room-twin project):  Tools > Execute Python Script... > pick this file.
  * builds its OWN level  /Game/Ney/NeySculpture  (the room twin's level is not touched)
  * pauses the room-twin live link while it runs (that one would rebuild the room in any level you open)
  * listens to the Mac's beat feed (beat_sender.py -> UDP 7700 -- the same feed as the Beat Deck)
  * 40 glowing shards in 10 groups -- group k = fixture k of the wave (Head 1, Head 2, Play, Spot 2, Head 3, Top Lamp,
    the other 1A bulb, Shade, Head 4, Spot 1), so the cascades on the lights carry on through the sculpture
  * a soft core that breathes with the sub, five coloured lights that glow in the virtual haze
For the projector: click in the viewport, press G (game view, no icons) and F11 (fills the screen).

Console (Output Log > Python):
  import ney_sculpture as sc
  sc.status()        what it hears + what it's doing
  sc.demo(True)      plays a built-in song (no rig needed) -- sc.demo(False) back to the rig
  sc.haze(0.6)       virtual haze 0..1     sc.glow(1.5) brighter / dimmer shards     sc.exposure(1) whole picture
  sc.stop() / sc.start()
  sc.room()          back to the room twin (opens it + restarts its live link)
Nothing here changes the real room: it only LISTENS to the beat feed.
"""
import math
import os
import random
import socket
import struct
import sys
import time

try:
    import unreal
except ImportError:                       # tests / outside Unreal
    unreal = None

PORT = 7700
LEVEL = '/Game/Ney/NeySculpture'
MAT = '/Game/Ney/M_NeyGlow'
TAG = 'neysculpt'
N_FIX = 10
PER = 4
CENTRE = (0.0, 0.0, 200.0)
CAM_POS = (-1150.0, 0.0, 230.0)
PURPLE = (0.45, 0.0, 1.0)
RB = [(1.0, 0.0, 0.0), (1.0, 0.35, 0.0), (1.0, 0.82, 0.0), (0.0, 1.0, 0.12), (0.0, 0.43, 1.0), (0.24, 0.0, 1.0),
      (0.67, 0.0, 1.0)]

S = sys.modules.setdefault('_ney_sculpt_state', type(sys)('_ney_sculpt_state'))
for _k, _v in dict(tick=None, sock=None, feed=None, sc=None, shards=[], core=None, lights=[], fog=None, run=False,
                   demo=False, gain=1.0, haze=0.5, bias=0.0, ppv=None, err='', frames=0, t0=0.0).items():
    if not hasattr(S, _k):
        setattr(S, _k, _v)


def log(msg):
    if unreal is not None:
        unreal.log('[NEY sculpture] ' + msg)
    else:
        print('[NEY sculpture] ' + msg)


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


# ================================================================================ the beat feed (OSC over UDP)
def osc_decode(pkt):
    """One OSC message -> (address, [args]). Bundles -> a list of messages via osc_messages()."""
    def string(i):
        j = pkt.index(b'\0', i)
        return pkt[i:j].decode('utf-8', 'replace'), (j // 4 + 1) * 4
    addr, i = string(0)
    tags, i = string(i)
    out = []
    for t in tags[1:]:
        if t == 'i':
            out.append(struct.unpack('>i', pkt[i:i + 4])[0]); i += 4
        elif t == 'f':
            out.append(struct.unpack('>f', pkt[i:i + 4])[0]); i += 4
        elif t == 's':
            s_, i = string(i); out.append(s_)
        else:
            break
    return addr, out


def osc_messages(pkt):
    if pkt.startswith(b'#bundle'):
        out, i = [], 16
        while i + 4 <= len(pkt):
            n = struct.unpack('>i', pkt[i:i + 4])[0]
            out += osc_messages(pkt[i + 4:i + 4 + n])
            i += 4 + n
        return out
    try:
        return [osc_decode(pkt)]
    except (ValueError, struct.error, IndexError):
        return []


class Feed:
    """What the rig is doing right now, from /ney/* (beat_sender.py)."""
    def __init__(self):
        self.kick = self.snare = self.hats = self.level = self.drop = 0.0
        self.section, self.colour = 'quiet', (0.45, 0.0, 1.0)
        self.bands = dict(sub=0.0, low=0.0, mid=0.0, high=0.0)
        self.fix, self.fix_t = {}, -99.0
        self.blackout, self.tempo, self.beat = 0, 120.0, 0.0
        self.t_last, self.packets = -99.0, 0

    def handle(self, addr, a, now):
        self.t_last = now
        self.packets += 1
        try:
            if addr in ('/ney/kick', '/ney/snare', '/ney/hats', '/ney/level', '/ney/drop') and a:
                setattr(self, addr[5:], clamp(float(a[0])))
            elif addr == '/ney/section' and a:
                self.section = str(a[0])
            elif addr == '/ney/colour' and len(a) >= 3:
                self.colour = tuple(clamp(float(x)) for x in a[:3])
            elif addr.startswith('/ney/band/') and a:
                self.bands[addr[10:]] = clamp(float(a[0]))
            elif addr == '/ney/fix' and len(a) >= 5:
                self.fix[int(a[0])] = (clamp(float(a[1])), clamp(float(a[2])), clamp(float(a[3])), clamp(float(a[4])))
                self.fix_t = now
            elif addr == '/ney/blackout' and a:
                self.blackout = int(a[0])
            elif addr == '/ney/tempo' and a:
                self.tempo = max(40.0, min(240.0, float(a[0])))
            elif addr == '/ney/beat' and a:
                self.beat = clamp(float(a[0]))
        except (TypeError, ValueError):
            pass

    def poll(self, sock, now):
        n = 0
        while sock is not None and n < 600:
            try:
                pkt, _ = sock.recvfrom(4096)
            except (BlockingIOError, socket.timeout, OSError):
                break
            for addr, a in osc_messages(pkt):
                self.handle(addr, a, now)
            n += 1
        return n

    def live(self, now):
        return now - self.t_last < 2.0


class Demo:
    """A built-in song for previews without the rig: groove (a cascade per kick through the 10 fixtures), a
    breakdown (purple, quiet), a drop (fire / ice, everything on the kick) -- 16 bars each at 124 BPM."""
    PALS = [[(1.0, 0.0, 0.55), (0.0, 0.9, 1.0)], [(1.0, 0.0, 0.0), (1.0, 0.3, 0.0), (1.0, 0.5, 0.0)],
            [(0.0, 0.85, 1.0), (0.0, 0.3, 1.0), (0.35, 0.0, 1.0)], RB]

    def feed(self, f, now):
        bps = 124.0 / 60.0
        beats = now * bps
        bar = int(beats // 4)
        part = ['groove', 'groove', 'breakdown', 'drop'][(bar // 16) % 4]
        frac = beats - math.floor(beats)
        kn = int(math.floor(beats))
        pal = self.PALS[(bar // 16) % len(self.PALS)]
        hit = math.exp(-frac / 0.18)
        f.section = part if not (part == 'drop' and (bar % 64) >= 50) else 'groove'
        f.kick = 0.0 if part == 'breakdown' else hit
        f.snare = hit if (kn % 2 == 1 and part != 'breakdown') else 0.0
        f.drop = 1.0 if (part == 'drop' and bar % 16 == 0) else 0.0
        f.level = 0.3 if part == 'breakdown' else 0.8
        f.bands = dict(sub=0.2 if part == 'breakdown' else 0.4 + 0.5 * hit, low=0.5 * hit, mid=0.4, high=0.3 + 0.3 * (frac < 0.5))
        f.colour = pal[0] if part != 'breakdown' else PURPLE
        for i in range(N_FIX):
            if part == 'breakdown':
                lv = 0.25 + 0.2 * math.sin(now * 0.8 + i * 0.6)
            elif part == 'drop':
                lv = hit
            else:
                pos = kn % (2 * N_FIX - 2)
                pos = pos if pos < N_FIX else 2 * N_FIX - 2 - pos
                age = abs(i - pos) + frac * 3.0
                lv = math.exp(-age / 1.2)
            f.fix[i] = pal[(kn + i) % len(pal)] + (clamp(lv),) if part != 'breakdown' else PURPLE + (clamp(lv),)
        f.fix_t = f.t_last = now
        f.blackout = 0


# ================================================================================ the sculpture (pure maths)
class Sculpt:
    """40 shards in 10 groups (one per wave fixture) around a breathing core. update() -> frames to draw."""
    def __init__(self, n_fix=N_FIX, per=PER, seed=7):
        rng = random.Random(seed)
        self.items = []
        for g in range(n_fix):
            a0 = 2 * math.pi * g / n_fix
            for k in range(per):
                a = a0 + rng.uniform(-0.35, 0.35)
                r = rng.uniform(90.0, 260.0)
                z = rng.uniform(-210.0, 260.0)
                home = (r * math.cos(a), r * math.sin(a), z)
                self.items.append(dict(g=g, home=home, a=a, r=r, size=rng.uniform(0.35, 0.7),
                                       length=rng.uniform(1.6, 3.4), tilt=rng.uniform(-35.0, 35.0),
                                       spin=rng.uniform(-14.0, 14.0), ph=rng.uniform(0, 2 * math.pi),
                                       drift=rng.uniform(8.0, 30.0)))
        self.n_fix = n_fix
        self.lv = [0.0] * n_fix
        self.col = [PURPLE] * n_fix
        self.explode = self.melt = 0.0
        self.yaw = 0.0
        self.sec_prev = 'quiet'
        self.drop_prev = 0.0
        self.sub = 0.0
        self.core_kick = 0.0
        self.fractures = 0

    def update(self, f, dt, now, live=True):
        dt = clamp(dt, 0.0, 0.1)
        # --- song shape: a drop LANDING fractures it, a breakdown melts it
        landed = (f.section == 'drop' and self.sec_prev != 'drop') or (f.drop > 0.6 and self.drop_prev <= 0.6)
        if landed and live:
            self.explode = 1.0
            self.fractures += 1
            self.melt *= 0.15                       # the drop bursts out in full colour (no purple hangover)
        self.sec_prev, self.drop_prev = f.section, f.drop
        self.explode *= math.exp(-dt / 1.4)
        want_melt = 1.0 if (f.section in ('breakdown', 'quiet') or not live) else 0.0
        self.melt += (want_melt - self.melt) * (1.0 - math.exp(-dt / (2.5 if want_melt > self.melt else 0.6)))
        self.sub += (f.bands.get('sub', 0.0) - self.sub) * (1.0 - math.exp(-dt / 0.12))
        self.core_kick = max(f.kick, self.core_kick * math.exp(-dt / 0.2))
        # --- each group follows its fixture (fast attack, soft release); no fixtures heard -> the kick + lamp colour
        fresh = now - f.fix_t < 1.0
        for g in range(self.n_fix):
            if fresh and g in f.fix:
                r, gg, b, l = f.fix[g]
                tgt, c = l, (r, gg, b)
            else:
                tgt, c = 0.25 + 0.75 * f.kick if live else 0.15, f.colour
            if f.blackout:
                tgt = 0.0
            k = 1.0 - math.exp(-dt / (0.03 if tgt > self.lv[g] else 0.25))
            self.lv[g] += (tgt - self.lv[g]) * k
            if max(c) > 0.02:
                self.col[g] = mix(self.col[g], c, 1.0 - math.exp(-dt / 0.05))
        energy = clamp(0.25 + f.level)
        self.yaw = (self.yaw + dt * (4.0 + 10.0 * energy) * (1.0 - 0.7 * self.melt)) % 360.0
        out = []
        e, m = self.explode, self.melt
        cy, sy = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
        for it in self.items:
            g = it['g']
            lv = self.lv[g]
            hx, hy, hz = it['home']
            hz += it['drift'] * math.sin(now * 0.35 + it['ph'])                      # slow float
            # melt: sink + thin + stretch down; fracture: fly outward from the centre
            hz = hz * (1.0 - 0.55 * m) - 150.0 * m
            d = math.sqrt(hx * hx + hy * hy + hz * hz) or 1.0
            push = 520.0 * e
            x, y, z = hx + hx / d * push, hy + hy / d * push, hz + hz / d * push
            x, y = x * cy - y * sy, x * sy + y * cy
            bloom = 1.0 + 0.55 * lv
            sx = it['size'] * bloom * (1.0 - 0.45 * m)
            sz = it['size'] * it['length'] * bloom * (1.0 + 1.3 * m)
            spin = it['spin'] * (1.0 + 25.0 * e)
            rot = (it['tilt'] * (1.0 - 0.8 * m) + 40.0 * e * math.sin(it['ph']),
                   math.degrees(it['a']) + self.yaw + spin * now, spin * now * 0.5)
            c = mix(self.col[g], PURPLE, 0.6 * m)
            glow = (0.12 + 7.0 * lv * lv + 1.2 * self.sub) * (1.0 + 1.5 * e)
            out.append(dict(pos=(CENTRE[0] + x, CENTRE[1] + y, CENTRE[2] + z), rot=rot, scale=(sx, sx, sz),
                            col=c, glow=glow))
        avg = tuple(sum(self.col[g][i] * (0.2 + self.lv[g]) for g in range(self.n_fix)) /
                    max(1e-6, sum(0.2 + self.lv[g] for g in range(self.n_fix))) for i in range(3))
        core = dict(pos=CENTRE, scale=(2.2 + 1.2 * self.sub,) * 3, col=mix(avg, PURPLE, 0.5 * m),
                    glow=0.08 + 0.6 * self.sub + 1.4 * self.core_kick * (1.0 - m))
        lights = []
        for j, g in enumerate((0, 2, 4, 6, 8)):
            a = 2 * math.pi * j / 5 + math.radians(self.yaw)
            lights.append(dict(pos=(CENTRE[0] + 260 * math.cos(a), CENTRE[1] + 260 * math.sin(a), CENTRE[2] + 60 * math.sin(now * 0.3 + j)),
                               col=mix(self.col[g], PURPLE, 0.6 * m), lv=clamp(0.1 + self.lv[g])))
        return out, core, lights


# ================================================================================ Unreal
def _sub(cls):
    return unreal.get_editor_subsystem(cls)


def _actors():
    return _sub(unreal.EditorActorSubsystem).get_all_level_actors()


def _material():
    """Unlit, additive, glowing edges (fresnel) -- parameters Color + Glow."""
    if unreal.EditorAssetLibrary.does_asset_exist(MAT):
        return unreal.EditorAssetLibrary.load_asset(MAT)
    try:
        unreal.EditorAssetLibrary.make_directory('/Game/Ney')
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset('M_NeyGlow', '/Game/Ney', unreal.Material,
                                                                       unreal.MaterialFactoryNew())
        for k, v in (('blend_mode', unreal.BlendMode.BLEND_ADDITIVE), ('shading_model', unreal.MaterialShadingModel.MSM_UNLIT),
                     ('two_sided', True)):
            try:
                mat.set_editor_property(k, v)
            except Exception as e:
                log('material %s: %s' % (k, e))
        MEL = unreal.MaterialEditingLibrary
        col = MEL.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -700, -100)
        col.set_editor_property('parameter_name', 'Color')
        col.set_editor_property('default_value', unreal.LinearColor(0.45, 0.0, 1.0, 1.0))
        glow = MEL.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -700, 100)
        glow.set_editor_property('parameter_name', 'Glow')
        glow.set_editor_property('default_value', 1.0)
        fres = MEL.create_material_expression(mat, unreal.MaterialExpressionFresnel, -700, 250)
        try:
            fres.set_editor_property('exponent', 2.5)
        except Exception:
            pass
        add = MEL.create_material_expression(mat, unreal.MaterialExpressionAdd, -450, 250)
        add.set_editor_property('const_b', 0.08)      # mostly glowing edges: overlaps stay colourful
        m1 = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -450, 0)
        m2 = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -250, 100)
        MEL.connect_material_expressions(fres, '', add, 'A')
        MEL.connect_material_expressions(col, '', m1, 'A')
        MEL.connect_material_expressions(glow, '', m1, 'B')
        MEL.connect_material_expressions(m1, '', m2, 'A')
        MEL.connect_material_expressions(add, '', m2, 'B')
        MEL.connect_material_property(m2, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        MEL.recompile_material(mat)
        unreal.EditorAssetLibrary.save_loaded_asset(mat)
        log('made the glow material ' + MAT)
        return mat
    except Exception as e:
        log('could not make the glow material (%s) -- using the plain one' % e)
        return unreal.EditorAssetLibrary.load_asset('/Engine/BasicShapes/BasicShapeMaterial')


def _open_level():
    les = _sub(unreal.LevelEditorSubsystem)
    if unreal.EditorAssetLibrary.does_asset_exist(LEVEL):
        les.load_level(LEVEL)
    else:
        les.new_level(LEVEL)
        log('made a new level ' + LEVEL)


def _pause_twin():
    tw = sys.modules.get('ney_unreal_live')
    if tw is not None:
        try:
            tw.stop()
            log('room-twin live link paused (sc.room() brings it back)')
        except Exception:
            pass


def _clear():
    for a in _actors():
        try:
            if a.actor_has_tag(TAG):
                _sub(unreal.EditorActorSubsystem).destroy_actor(a)
        except Exception:
            pass


def _spawn(cls, pos, label):
    a = _sub(unreal.EditorActorSubsystem).spawn_actor_from_class(cls, unreal.Vector(*pos))
    a.set_actor_label(label)
    a.tags = [unreal.Name(TAG)]
    return a


def _shape(mesh, mat, pos, label):
    a = _spawn(unreal.StaticMeshActor, pos, label)
    c = a.static_mesh_component
    c.set_mobility(unreal.ComponentMobility.MOVABLE)
    c.set_static_mesh(mesh)
    try:
        c.set_editor_property('cast_shadow', False)
    except Exception:
        pass
    mid = c.create_dynamic_material_instance(0, mat)
    return dict(actor=a, mid=mid)


def build():
    """The level: black, a little virtual haze, bloom, the shards, the core, the lights, the camera."""
    _clear()
    mat = _material()
    sphere = unreal.EditorAssetLibrary.load_asset('/Engine/BasicShapes/Sphere')
    S.sc = Sculpt()
    S.shards = [_shape(sphere, mat, CENTRE, 'NEY Shard %02d' % i) for i in range(len(S.sc.items))]
    S.core = _shape(sphere, mat, CENTRE, 'NEY Core')
    S.lights = []
    for j in range(5):
        a = _spawn(unreal.PointLight, CENTRE, 'NEY Glow %d' % (j + 1))
        c = a.get_component_by_class(unreal.PointLightComponent)
        c.set_mobility(unreal.ComponentMobility.MOVABLE)
        for fn, v in (('set_attenuation_radius', 1400.0), ('set_volumetric_scattering_intensity', 3.0),
                      ('set_source_radius', 30.0), ('set_intensity', 0.0)):
            try:
                getattr(c, fn)(v)
            except Exception:
                pass
        try:
            c.set_editor_property('cast_shadows', False)
        except Exception:
            pass
        S.lights.append(c)
    S.fog = _spawn(unreal.ExponentialHeightFog, (0, 0, -400), 'NEY Haze')
    haze(S.haze)
    ppv = _spawn(unreal.PostProcessVolume, (0, 0, 0), 'NEY Look')
    ppv.set_editor_property('unbound', True)
    st = ppv.get_editor_property('settings')
    for k, v in (('bloom_intensity', 2.2), ('bloom_threshold', 0.2),
                 ('auto_exposure_method', unreal.AutoExposureMethod.AEM_HISTOGRAM),     # fixed exposure: a dark
                 ('auto_exposure_min_brightness', 0.0), ('auto_exposure_max_brightness', 0.0),   # room must stay dark
                 ('auto_exposure_bias', S.bias), ('auto_exposure_apply_physical_camera_exposure', False),
                 ('vignette_intensity', 0.55), ('scene_fringe_intensity', 0.6), ('film_grain_intensity', 0.15)):
        try:
            st.set_editor_property('override_' + k, True)
            st.set_editor_property(k, v)
        except Exception:
            pass
    ppv.set_editor_property('settings', st)
    S.ppv = ppv
    view()
    try:
        ps = unreal.get_default_object(unreal.EditorPerformanceSettings)
        ps.set_editor_property('throttle_cpu_when_not_foreground', False)
    except Exception:
        pass
    try:
        _sub(unreal.LevelEditorSubsystem).save_current_level()
    except Exception:
        pass
    log('built: %d shards, core, 5 lights, haze, look' % len(S.shards))


def view():
    """The viewport looks at the sculpture from the projector's point of view."""
    p = unreal.Vector(*CAM_POS)
    t = unreal.Vector(*CENTRE)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
        p, unreal.MathLibrary.make_rot_from_x(unreal.Vector(t.x - p.x, t.y - p.y, t.z - p.z)))


def haze(level=None):
    if level is not None:
        S.haze = clamp(float(level))
    if S.fog is None:
        return
    c = S.fog.component
    for k, v in (('fog_density', 0.01 + 0.05 * S.haze), ('fog_height_falloff', 0.001), ('volumetric_fog', S.haze > 0),
                 ('volumetric_fog_extinction_scale', 0.5 + 6.0 * S.haze), ('fog_max_opacity', 1.0),
                 ('fog_inscattering_color', unreal.LinearColor(0, 0, 0, 1))):
        try:
            c.set_editor_property(k, v)
        except Exception:
            pass


def exposure(bias=0.0):
    """sc.exposure(1) brighter picture, sc.exposure(-1) darker (whole stops)."""
    S.bias = float(bias)
    if getattr(S, 'ppv', None) is None:
        return
    st = S.ppv.get_editor_property('settings')
    st.set_editor_property('override_auto_exposure_bias', True)
    st.set_editor_property('auto_exposure_bias', S.bias)
    S.ppv.set_editor_property('settings', st)
    log('exposure %+.1f' % S.bias)


def glow(g=1.0):
    S.gain = max(0.0, float(g))
    log('glow x%.2f' % S.gain)


def _tick(dt):
    try:
        now = time.time()
        f = S.feed
        if S.demo:
            Demo().feed(f, now)
        else:
            f.poll(S.sock, now)
        live = S.demo or f.live(now)
        shards, core, lights = S.sc.update(f, dt, now, live)
        V, R = unreal.Vector, unreal.Rotator
        for sh, fr in zip(S.shards, shards):
            a = sh['actor']
            p, r, s = fr['pos'], fr['rot'], fr['scale']
            a.set_actor_location_and_rotation(V(*p), R(roll=r[2], pitch=r[0], yaw=r[1]), False, True)
            a.set_actor_scale3d(V(*s))
            if sh['mid'] is not None:
                c = fr['col']
                sh['mid'].set_vector_parameter_value('Color', unreal.LinearColor(c[0], c[1], c[2], 1.0))
                sh['mid'].set_scalar_parameter_value('Glow', fr['glow'] * S.gain)
        if S.core:
            S.core['actor'].set_actor_scale3d(V(*core['scale']))
            if S.core['mid'] is not None:
                c = core['col']
                S.core['mid'].set_vector_parameter_value('Color', unreal.LinearColor(c[0], c[1], c[2], 1.0))
                S.core['mid'].set_scalar_parameter_value('Glow', core['glow'] * S.gain)
        for lc, fr in zip(S.lights, lights):
            lc.set_world_location(V(*fr['pos']), False, True)
            c = fr['col']
            lc.set_light_color(unreal.LinearColor(c[0], c[1], c[2], 1.0), True)
            lc.set_intensity(60000.0 * fr['lv'] * S.gain)
        S.frames += 1
        S.err = ''
    except Exception as e:
        if str(e) != S.err:
            S.err = str(e)
            unreal.log_warning('[NEY sculpture] ' + S.err)


def _listen():
    if S.sock is not None:
        return
    s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s_.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s_.bind(('0.0.0.0', PORT))
    except OSError as e:
        log('port %d is busy (%s) -- is the Beat Deck blueprint playing? The demo still works.' % (PORT, e))
        s_.close()
        return
    s_.setblocking(False)
    S.sock = s_
    log('listening for the rig on UDP %d' % PORT)


def start():
    if S.tick is not None:
        log('already running -- ' + status(True))
        return
    _pause_twin()
    _open_level()
    build()
    S.feed = Feed()
    _listen()
    S.t0 = time.time()
    S.tick = unreal.register_slate_post_tick_callback(_tick)
    log('running. Click the viewport, press G then F11 for the projector. sc.demo(True) = preview without the rig.')


def stop():
    if S.tick is not None:
        unreal.unregister_slate_post_tick_callback(S.tick)
        S.tick = None
    if S.sock is not None:
        try:
            S.sock.close()
        except Exception:
            pass
        S.sock = None
    log('stopped')


def demo(on=True):
    S.demo = bool(on)
    log('demo ' + ('ON (built-in song)' if on else 'OFF (following the rig)'))


def status(quiet=False):
    f = S.feed
    if f is None:
        msg = 'not started -- sc.start()'
    else:
        now = time.time()
        msg = '%s | %d frames | %s, section %s, %d fixtures heard | fractures %d | melt %.2f%s' % (
            'DEMO' if S.demo else ('hearing the rig' if f.live(now) else 'NOT hearing the rig (Mac beat_sender / firewall?)'),
            S.frames, '%d packets' % f.packets, f.section, len(f.fix), S.sc.fractures if S.sc else 0,
            S.sc.melt if S.sc else 0.0, (' | error: ' + S.err) if S.err else '')
    if not quiet:
        log(msg)
    return msg


def room(level=None):
    """Back to the room twin: open its level and restart its live link."""
    stop()
    if level:
        _sub(unreal.LevelEditorSubsystem).load_level(level)
    else:
        log('open the room level from the Content Browser, then:  import ney_unreal_live as ney; ney.start()')
        return
    try:
        import ney_unreal_live
        ney_unreal_live.start()
    except Exception as e:
        log('room twin did not start: %s' % e)


def _install(src):
    """Copy this file into Content/Python so  import ney_sculpture  works in the console."""
    try:
        d = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()), 'Python')
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, 'ney_sculpture.py')
        if src and os.path.abspath(src) != os.path.abspath(dst):
            with open(src, encoding='utf-8') as fi, open(dst, 'w', encoding='utf-8') as fo:
                fo.write(fi.read())
        if d not in sys.path:
            sys.path.append(d)
    except Exception as e:
        log('could not copy into Content/Python: %s' % e)


if __name__ == '__main__' and unreal is not None:
    _install(globals().get('__file__'))
    sys.modules.setdefault('ney_sculpture', sys.modules[__name__])
    start()
