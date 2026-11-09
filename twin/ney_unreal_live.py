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
  ney.ambient(0.5)   room glow brightness 0..1 (0 = dark)
  ney.haze(0.8)      virtual haze 0..1 (makes the beams visible)
  ney.check()        what each virtual head is doing (troubleshooting)
  ney.hue_pair()     press the Hue bridge button first -- then the Unreal lamps follow the real Hue lamps
  ney.go()           camera inside the room ('couch', 'door', 'studio', 'ceiling')
  ney.hue_gain(6)    brighter Unreal Hue lamps   |  ney.exposure(2) brighter picture overall
  ney.hue_list()     which Hue lamp sits where   |  ney.hue_place('Top Lamp', 'Paper lamp') to move one
  ney.view('clean')  tidy room  |  ney.view('scan') LiDAR scan  |  ney.view('plot') gray plot
  ney.restore()      undo the room darkening + unhide everything
"""
import glob, json, math, os, sys, threading, time, urllib.request
import unreal

# Everything it needs is baked in below (from ney_fixtures.json + ney_room.glb, plot v118),
# so this one file works on the Zephyrus or the Mac.
NODE_HOSTS = ['127.0.0.1', '192.168.1.79', 'zephyrus']   # same PC first, then LAN, then Tailscale
FIXTURES = [{"name": "Head 1", "position_m": [3.9133272000000003, 0.8129016, 0.5081016], "pan0_heading_deg_plot": 180, "pan_turns": "ccw"}, {"name": "Head 2", "position_m": [2.6685240000000006, 0.9653016, 0.1524], "pan0_heading_deg_plot": 180, "pan_turns": "ccw"}, {"name": "Head 3", "position_m": [1.930908, 0.8129016, 3.1638240000000004], "pan0_heading_deg_plot": 232, "pan_turns": "cw"}, {"name": "Head 4", "position_m": [4.9017936, 0.7872984000000001, 3.0732984], "pan0_heading_deg_plot": 180, "pan_turns": "cw"}]
PLOT_NAMES = ["Floor", "Ceiling", "Wall 1", "Wall 2", "Wall 3", "Wall 4", "Wall 5", "Wall 6", "Wall 7", "Wall 8", "Wall 9", "Wall 10", "Wall 11", "Wall 12", "Wall 13", "Wall 14", "Wall 15", "Kitchen counter", "Water heater", "Bedroom door", "Front door", "Sliding glass door", "Mirrored closet", "Projection screen", "Smiley neon + thermostat", "Happiness Project flag", "Good Vibes poster", "Mac Miller tapestry", "Art wall", "White desk \u00b7 Zephyrus", "Side table", "Cloud projector", "White shelf", "Gray couch", "Corner table", "Rolly desk", "Blue couch", "Coffee table", "Pouf", "Studio desk", "Poly D", "Optoma", "Fireplace", "Paper lamp", "Behind Desk", "Hue light bar", "Elektron backlight", "Hue Play floor lamp", "Hue color lamp 1", "Studio desk lamp", "Blue/white balloon", "Red/white balloon", "Orange-striped balloon", "Green/white balloon", "Cloud", "Cloud 2", "Cloud 3", "Cloud 4", "Cloud spot (planned)", "UNSAFE Mirror", "UNSAFE Glass door (curtained: safe)", "UNSAFE Screen", "Ceiling fan", "Head 1", "Head 2", "Head 3", "Head 4", "Elektrons + Evil Pet", "Floor lamp", "Laser bar (parked)", "Fridge", "Stove + microwave", "Roli", "Push 2", "UNSAFE Eye level", "UNSAFE Eye level 2", "IMAGINE poster + collage", "Coexist flag", "Papasan chair", "Gray ottoman", "Yellow balloon", "GOOD VIBES neon"]
NODE_PORT = 7060
PAN_DEG, TILT_DEG = 540.0, 180.0                     # Betopper LM70S
MASTER_MIN, MASTER_MAX = 8, 134
BEAM_HALF = 6.5                                      # degrees (outer cone half-angle)
CANDELA = 6000.0                                     # virtual brightness at full
LENS_CM = 30.0                                       # the light itself starts this far out along the beam so the scanned
                                                     # head doesn't shadow it; the head body + icon stay put
HAZE = 0.5                                           # virtual haze 0..1 -- ney.haze(0.8)
TAG = 'ney'
INIT_MARK = '# NEY auto-start'

S = sys.modules.setdefault('_ney_live_state', type(sys)('_ney_live_state'))
for k, v in dict(hue=None, hue_t=0.0, hue_err='', hue_msg='', hue_lamps={}, tick=None, thread=None, run=False, status=None, cfg=None, host=None, err='', polls=0,
                 last_ok=0.0, demo=False, world=None, heads=[], map=None, log_t=0.0, cur={}).items():
    if not hasattr(S, k):
        setattr(S, k, v)


def log(msg):
    unreal.log('[NEY] ' + msg)


def _actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()


def _norm(s):
    return ''.join(ch for ch in s.lower() if ch.isalnum())


# ---------------------------------------------------------------- room mapping (glTF metres -> Unreal cm)
FLOOR_C = (2.8956, 1.6629)          # ney_room.glb Floor centre (x, z) metres
FLOOR_E = (4.1148, 1.9312)          # half-extents


def find_mapping():
    """Work out how the GLB landed in Unreal from where the plot's Floor ended up."""
    best = None
    for a in _actors():
        if a.actor_has_tag(TAG) or not _norm(a.get_actor_label()).startswith('floor'):
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
    names = {_norm(n) for n in PLOT_NAMES if n}
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
    S.fog = fog
    haze()
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


def haze(level=None):
    """ney.haze(0.8) -- how thick the virtual haze is (0 = none, 1 = thick)."""
    global HAZE
    if level is not None:
        HAZE = max(0.0, min(1.0, float(level)))
    fog = getattr(S, 'fog', None)
    if fog is None:
        return
    c = fog.component
    for k, v in (('fog_density', 0.02 + 0.08 * HAZE), ('fog_height_falloff', 0.001), ('volumetric_fog', HAZE > 0),
                 ('volumetric_fog_scattering_distribution', 0.6), ('volumetric_fog_extinction_scale', 0.5 + 9.5 * HAZE),
                 ('volumetric_fog_albedo', unreal.Color(255, 255, 255, 255)), ('fog_max_opacity', 1.0),
                 ('fog_inscattering_luminance', unreal.LinearColor(0, 0, 0, 1)),
                 ('fog_inscattering_color', unreal.LinearColor(0, 0, 0, 1))):
        try:
            c.set_editor_property(k, v)
        except Exception:
            pass
    log('haze %.2f' % HAZE)


def _mesh(path):
    return unreal.EditorAssetLibrary.load_asset(path)


def _floor_material():
    p = '/Game/NEY/M_NEY_FloorFill'
    if unreal.EditorAssetLibrary.does_asset_exist(p):
        return _mesh(p)
    try:
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset('M_NEY_FloorFill', '/Game/NEY', unreal.Material,
                                                                      unreal.MaterialFactoryNew())
        mel = unreal.MaterialEditingLibrary
        col = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, 0)
        col.set_editor_property('constant', unreal.LinearColor(0.12, 0.10, 0.087, 1.0))   # the scan's floor colour
        mel.connect_material_property(col, '', unreal.MaterialProperty.MP_BASE_COLOR)
        r = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, 200)
        r.set_editor_property('r', 0.85)
        mel.connect_material_property(r, '', unreal.MaterialProperty.MP_ROUGHNESS)
        mel.recompile_material(mat)
        unreal.EditorAssetLibrary.save_loaded_asset(mat)
        return mat
    except Exception as e:
        unreal.log_warning('[NEY] floor material: %s' % e)
        return None


def floor_fill():
    """A flat floor just under the scan's floor so the holes in the scan don't show the void."""
    lab = 'NEY Floor fill'
    a = next((x for x in _actors() if x.get_actor_label() == lab), None)
    c1 = to_ue(S.map, -1.6, -0.004, -3.9)
    c2 = to_ue(S.map, 7.5, -0.004, 3.95)
    ctr = unreal.Vector((c1.x + c2.x) / 2, (c1.y + c2.y) / 2, c1.z)
    if a is None:
        a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_object(
            _mesh('/Engine/BasicShapes/Plane'), ctr)
        a.set_actor_label(lab)
        a.tags = [unreal.Name(TAG)]
    a.set_actor_location(ctr, False, True)
    a.set_actor_scale3d(unreal.Vector(abs(c2.x - c1.x) / 100.0, abs(c2.y - c1.y) / 100.0, 1.0))
    m = _floor_material()
    if m:
        a.static_mesh_component.set_material(0, m)


def use_clean_scan():
    """Swap in the cleaned scan (flat floor + ceiling) if ney_room_scan_clean.glb is in Downloads."""
    lab = 'NEY Scan (clean)'
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    old = [a for a in _actors() if 'scaniverse' in _norm(a.get_actor_label()) and not a.actor_has_tag(TAG)]
    new = next((a for a in _actors() if a.get_actor_label() == lab), None)
    if new is None:
        files = sorted(glob.glob(os.path.join(os.path.expanduser('~'), 'Downloads', 'ney_room_scan_clean*.glb')),
                       key=os.path.getmtime)
        if not files:
            return
        log('importing the cleaned scan: ' + files[-1])
        t = unreal.AssetImportTask()
        t.set_editor_property('filename', files[-1])
        t.set_editor_property('destination_path', '/Game/NEY_ScanClean')
        t.set_editor_property('automated', True)
        t.set_editor_property('save', True)
        t.set_editor_property('replace_existing', True)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
        paths = list(t.get_editor_property('imported_object_paths') or []) + \
            list(unreal.EditorAssetLibrary.list_assets('/Game/NEY_ScanClean', recursive=True))
        mesh = None
        for p in paths:
            o = unreal.EditorAssetLibrary.load_asset(p)
            if isinstance(o, unreal.StaticMesh):
                mesh = o
                break
        if mesh is None:
            unreal.log_warning('[NEY] cleaned scan imported but no mesh found -- keeping the old scan')
            return
        new = sub.spawn_actor_from_object(mesh, unreal.Vector(0, 0, 0))
        ref = next((a for a in old if isinstance(a, unreal.StaticMeshActor)), None)
        if ref is not None:
            new.set_actor_transform(ref.get_actor_transform(), False, True)
        new.set_actor_label(lab)
        new.tags = [unreal.Name(TAG)]
    for a in old:
        _hide(a, True)
    log('using the cleaned scan (old scan hidden, not deleted)')


def _newest(pattern):
    files = sorted(glob.glob(os.path.join(os.path.expanduser('~'), 'Downloads', pattern)), key=os.path.getmtime)
    return files[-1] if files else None


def _import(path, dest):
    t = unreal.AssetImportTask()
    t.set_editor_property('filename', path)
    t.set_editor_property('destination_path', dest)
    t.set_editor_property('automated', True)
    t.set_editor_property('save', True)
    t.set_editor_property('replace_existing', True)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    out = []
    for p in unreal.EditorAssetLibrary.list_assets(dest, recursive=True):
        o = unreal.EditorAssetLibrary.load_asset(p)
        if isinstance(o, unreal.StaticMesh):
            out.append(o)
    return out


def _ref_transform():
    """where the earlier GLB imports landed, so new pieces line up with them"""
    for a in _actors():
        if isinstance(a, unreal.StaticMeshActor) and not a.actor_has_tag(TAG) and \
                ('scaniverse' in _norm(a.get_actor_label()) or _norm(a.get_actor_label()) == 'floor'):
            return a.get_actor_transform()
    return None


def use_clean_room():
    """Build the clean room (flat walls with your art, tidy furniture) from ney_room_clean.glb in Downloads."""
    have = [a for a in _actors() if a.actor_has_tag('ney_room')]
    if have:
        return True
    f = _newest('ney_room_clean*.glb')
    if not f:
        return False
    log('building the clean room from ' + f)
    meshes = _import(f, '/Game/NEY_CleanRoom')
    if not meshes:
        unreal.log_warning('[NEY] clean room imported but no meshes found')
        return False
    ref = _ref_transform()
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for m in meshes:
        a = sub.spawn_actor_from_object(m, unreal.Vector(0, 0, 0))
        if ref is not None:
            a.set_actor_transform(ref, False, True)
        a.set_actor_label('NEY ' + m.get_name())
        a.tags = [unreal.Name(TAG), unreal.Name('ney_room')]
        try:
            a.set_folder_path('NEY Clean Room')
        except Exception:
            pass
    log('clean room built: %d pieces' % len(meshes))
    return True


ALIGN_PIECES = ('floor', 'fridge', 'graycouch', 'rollydesk', 'kitchencounter', 'bluecouch', 'coffeetable',
                'fireplace', 'studiodesk', 'waterheater', 'whiteshelf')


def _centres(clean):
    out = {}
    for a in _actors():
        lab = _norm(a.get_actor_label())
        if clean:
            if not a.actor_has_tag('ney_room'):
                continue
            lab = lab[3:] if lab.startswith('ney') else lab
        elif a.actor_has_tag(TAG):
            continue
        lab = lab.rstrip('0123456789') if lab.rstrip('0123456789') in ALIGN_PIECES else lab
        if lab not in ALIGN_PIECES:
            continue
        o, e = a.get_actor_bounds(False)
        if lab == 'floor':      # the room's floor, not some other 'Floor' in the level
            fe = min(abs(e.x - FLOOR_E[0] * 100) + abs(e.y - FLOOR_E[1] * 100),
                     abs(e.y - FLOOR_E[0] * 100) + abs(e.x - FLOOR_E[1] * 100))
            if fe > 80 or ('floor' in out and fe >= out['floor'][4]):
                continue
            out[lab] = (o.x, o.y, o.z, e.z, fe)
        elif lab not in out:
            out[lab] = (o.x, o.y, o.z, e.z, 0)
    return out


def align_clean_room():
    """Line the clean room up with the plot (which the heads + lamps are placed from), piece by piece."""
    P, C = _centres(False), _centres(True)
    keys = [k for k in ALIGN_PIECES if k in P and k in C]
    if 'floor' not in keys or len(keys) < 3:
        log('align: not enough matching pieces (%s)' % ', '.join(keys))
        return
    pc, cc = P['floor'], C['floor']
    best = None
    for swap in (False, True):
        for sx in (1, -1):
            for sy in (1, -1):
                T = ((0, sx), (sy, 0)) if swap else ((sx, 0), (0, sy))
                err = 0.0
                for k in keys:
                    dx, dy = C[k][0] - cc[0], C[k][1] - cc[1]
                    mx = pc[0] + T[0][0] * dx + T[0][1] * dy
                    my = pc[1] + T[1][0] * dx + T[1][1] * dy
                    err += math.hypot(mx - P[k][0], my - P[k][1])
                if best is None or err < best[0]:
                    best = (err, T)
    err, T = best
    err /= len(keys)
    dz = (pc[2] - pc[3]) - (cc[2] - cc[3])          # floor tops
    ident = T == ((1, 0), (0, 1))
    if ident and err < 8 and abs(dz) < 3 and math.hypot(pc[0] - cc[0], pc[1] - cc[1]) < 8:
        log('clean room already lined up (within %.0f cm)' % err)
        return
    det = T[0][0] * T[1][1] - T[0][1] * T[1][0]
    s_y = 1 if det > 0 else -1
    # T = R(yaw) * diag(1, s_y)  ->  R = T * diag(1, s_y)
    r00, r10 = T[0][0], T[1][0]
    yaw = math.degrees(math.atan2(r10, r00))
    tx = pc[0] - (T[0][0] * cc[0] + T[0][1] * cc[1])
    ty = pc[1] - (T[1][0] * cc[0] + T[1][1] * cc[1])
    M = unreal.Transform(unreal.Vector(tx, ty, dz), unreal.Rotator(0, 0, yaw), unreal.Vector(1, s_y, 1))
    try:
        M = unreal.Transform(location=unreal.Vector(tx, ty, dz), rotation=unreal.Rotator(roll=0, pitch=0, yaw=yaw),
                             scale=unreal.Vector(1, s_y, 1))
    except Exception:
        pass
    for a in _actors():
        if a.actor_has_tag('ney_room'):
            a.set_actor_transform(unreal.MathLibrary.compose_transforms(a.get_actor_transform(), M), False, True)
    log('clean room lined up with the plot (was off by %.0f cm avg, turn %.0f, mirror %s) using %s'
        % (err, yaw, s_y < 0, ', '.join(keys)))



def view(which='clean'):
    """ney.view('clean') tidy room  |  ney.view('scan') the LiDAR scan  |  ney.view('plot') the gray plot model"""
    for a in _actors():
        lab = a.get_actor_label()
        if a.actor_has_tag('ney_room'):
            _hide(a, which != 'clean')
        elif lab in ('NEY Scan (clean)', 'NEY Floor fill'):
            _hide(a, which != 'scan')
    hide_plot(which != 'plot')
    if which != 'scan':
        for a in _actors():
            if 'scaniverse' in _norm(a.get_actor_label()) and not a.actor_has_tag(TAG):
                _hide(a, True)
    elif not any(x.get_actor_label() == 'NEY Scan (clean)' for x in _actors()):
        for a in _actors():
            if 'scaniverse' in _norm(a.get_actor_label()) and not a.actor_has_tag(TAG):
                _hide(a, False)
    S.view = which
    log('view: ' + which)



def check():
    """ney.check() -- prints what each virtual head is doing (for troubleshooting)."""
    for h in S.heads:
        c = h['comp']
        out = []
        for k in ('intensity', 'intensity_units', 'mobility', 'cast_shadows', 'visible', 'affects_world',
                  'outer_cone_angle', 'light_color', 'volumetric_scattering_intensity'):
            try:
                out.append('%s=%s' % (k, c.get_editor_property(k)))
            except Exception:
                pass
        log(h['name'] + ': ' + ', '.join(out) + ' | at ' + str(h['actor'].get_actor_location()))
    status()



# ---------------------------------------------------------------- the Hue lamps (read straight from the bridge)
HUE_BRIDGE = '192.168.1.75'
FT = 0.3048
HUE_SPOTS = {    # plot spots: x ft east, y ft south, height ft of the bulb
    'Behind Desk': (18.172, 0.6, 1.0), 'Hue Play floor lamp': (5.652, -0.55, 2.6), 'Hue color lamp 1': (6.08, 10.92, 3.0),
    'Studio desk lamp': (22.74, 11.25, 3.2), 'Floor lamp': (5.25, 11.0, 5.0), 'Paper lamp': (15.652, 11.0, 5.0),
    'Elektron backlight': (21.99, 9.0, 2.6), 'Hue light bar': (5.252, -0.7, 1.0)}
HUE_GUESS = {'Behind Desk': 'Behind Desk', 'Hue Play floor lamp large 1': 'Hue Play floor lamp',
             'Hue color lamp 1': 'Hue color lamp 1', 'Hue color lamp 2': 'Studio desk lamp',
             'Floor Shade': 'Floor lamp', 'Top Lamp': 'Paper lamp'}
HUE_CANDELA = 70.0       # a Hue bulb at full is roughly 800 lumens
HUE_GAIN = 4.0           # extra so dim looks still read on screen -- ney.hue_gain(6)


def _saved(name):
    return os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir()), name)


def _hue_keyfile():
    # unreal.* may only be called on the editor thread -- work the path out once there
    if not getattr(S, 'keyfile', None):
        S.keyfile = _saved('ney_hue_key.json')
    return S.keyfile


def _hue_key():
    try:
        return json.load(open(S.keyfile))['k']
    except Exception:
        return None


def _hue_map():
    m = dict(HUE_GUESS)
    try:
        m.update(json.load(open(_saved('ney_hue_map.json'))))
    except Exception:
        pass
    return m


def hue_pair():
    """ney.hue_pair() -- press the round button on the Hue bridge, then run this within 30 s."""
    kf = _hue_keyfile()

    def go():
        body = json.dumps({'devicetype': 'ney_unreal#zephyrus'}).encode()
        for _ in range(15):
            try:
                r = json.loads(urllib.request.urlopen(urllib.request.Request(
                    'http://%s/api' % HUE_BRIDGE, data=body, method='POST'), timeout=3).read())
                ok = [x['success']['username'] for x in r if 'success' in x]
                if ok:
                    json.dump({'k': ok[0]}, open(kf, 'w'))
                    S.hue_msg = 'paired with the Hue bridge -- lamps will follow the real ones'
                    return
                S.hue_msg = 'waiting for the bridge button...'
            except Exception as e:
                S.hue_msg = 'bridge not answering: %s' % e
            time.sleep(2)
        S.hue_msg = 'pairing timed out -- press the bridge button, then run ney.hue_pair() again'
    S.hue_msg = 'pairing: press the round button on the Hue bridge now (30 s)'
    log(S.hue_msg)
    threading.Thread(target=go, daemon=True).start()


def _hue_poller():
    while S.run:
        k = _hue_key()
        if not k:
            time.sleep(3)
            continue
        try:
            d = json.loads(urllib.request.urlopen('http://%s/api/%s/lights' % (HUE_BRIDGE, k), timeout=2).read())
            if isinstance(d, list):
                S.hue_err = str(d)[:120]
            else:
                S.hue = {v['name']: v['state'] for v in d.values()}
                S.hue_t = time.time()
                S.hue_err = ''
        except Exception as e:
            S.hue_err = str(e)
        time.sleep(0.4)


def _hue_rgb(st):
    """bridge state -> (r, g, b) 0..1, full strength (brightness handled separately)"""
    if st.get('colormode') == 'ct' or 'xy' not in st:
        k = 1e6 / max(153, min(500, st.get('ct', 366)))
        t = k / 100.0
        r = 1.0 if t <= 66 else min(1, 1.292936 * (t - 60) ** -0.1332)
        g = min(1, max(0, (0.390081 * math.log(t) - 0.631841) if t <= 66 else 1.129891 * (t - 60) ** -0.0755))
        b = 1.0 if t >= 66 else (0 if t <= 19 else min(1, max(0, 0.543207 * math.log(t - 10) - 1.196254)))
        return r, g, b
    x, y = st['xy']
    y = max(y, 1e-4)
    X, Y, Z = x / y, 1.0, (1 - x - y) / y
    r = X * 1.656492 - Y * 0.354851 - Z * 0.255038
    g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152
    b = X * 0.051713 - Y * 0.121364 + Z * 1.011530
    m = max(r, g, b, 1e-6)
    return max(0, r / m), max(0, g / m), max(0, b / m)


def build_hue():
    S.hue_lamps = {}
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    have = {a.get_actor_label(): a for a in _actors() if a.actor_has_tag(TAG)}
    mp = _hue_map()
    for name, spot in mp.items():
        if spot not in HUE_SPOTS:
            continue
        x, y, h = HUE_SPOTS[spot]
        p = to_ue(S.map, x * FT, h * FT, y * FT)
        lab = 'NEY Hue ' + name
        a = have.get(lab)
        if a is None:
            a = sub.spawn_actor_from_class(unreal.PointLight, p)
            a.set_actor_label(lab)
            a.tags = [unreal.Name(TAG)]
            try:
                a.set_folder_path('NEY Hue lamps')
            except Exception:
                pass
        a.set_actor_location(p, False, True)
        c = a.point_light_component
        for fn, v in (('set_mobility', unreal.ComponentMobility.MOVABLE), ('set_attenuation_radius', 1200.0),
                      ('set_source_radius', 6.0), ('set_volumetric_scattering_intensity', 1.0),
                      ('set_cast_shadows', False)):      # the bulb sits inside its lamp shade
            try:
                getattr(c, fn)(v)
            except Exception:
                pass
        try:
            c.set_editor_property('intensity_units', unreal.LightUnits.CANDELAS)
        except Exception:
            pass
        c.set_intensity(0.0)
        S.hue_lamps[name] = c


def _hue_tick():
    live = getattr(S, 'hue', None) and time.time() - getattr(S, 'hue_t', 0) < 5
    for name, c in (getattr(S, 'hue_lamps', None) or {}).items():
        st = (S.hue or {}).get(name) if live else None
        if not st or not st.get('on') or not st.get('reachable', True):
            c.set_intensity(0.0)
            continue
        r, g, b = _hue_rgb(st)
        c.set_light_color(unreal.LinearColor(r, g, b, 1.0), False)
        c.set_intensity(HUE_CANDELA * HUE_GAIN * (st.get('bri', 254) / 254.0) ** 1.6)


def hue_list():
    """ney.hue_list() -- every Hue lamp, where it sits in Unreal, and what it's showing."""
    mp = _hue_map()
    for name, st in sorted((getattr(S, 'hue', None) or {}).items()):
        log('%-30s -> %-20s %s bri %s' % (name, mp.get(name, '(not placed)'), 'on ' if st.get('on') else 'off',
                                          st.get('bri')))
    log('spots you can use: ' + ', '.join(HUE_SPOTS))
    log(getattr(S, 'hue_msg', '') or ('Hue: ' + (getattr(S, 'hue_err', '') or 'ok')))


def hue_place(name, spot):
    """ney.hue_place('Top Lamp', 'Floor lamp') -- move a Hue lamp to a different spot (remembered)."""
    if spot not in HUE_SPOTS:
        log('unknown spot -- use one of: ' + ', '.join(HUE_SPOTS))
        return
    m = {}
    try:
        m = json.load(open(_saved('ney_hue_map.json')))
    except Exception:
        pass
    m[name] = spot
    json.dump(m, open(_saved('ney_hue_map.json'), 'w'), indent=1)
    build_hue()
    log('%s now at %s' % (name, spot))



def hue_gain(g=4.0):
    """ney.hue_gain(6) -- make the Unreal Hue lamps brighter or dimmer than real (1 = physically real)."""
    global HUE_GAIN
    HUE_GAIN = max(0.0, float(g))
    log('Hue gain %.1f' % HUE_GAIN)


def exposure(bias=1.0):
    """ney.exposure(1.5) -- like the eye adjusting to a dark room (higher = brighter picture)."""
    lab = 'NEY Exposure (dark room)'
    v = next((a for a in _actors() if a.get_actor_label() == lab), None)
    if v is None:
        v = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
            unreal.PostProcessVolume, unreal.Vector(0, 0, 0))
        v.set_actor_label(lab)
        v.tags = [unreal.Name(TAG)]
    v.set_editor_property('unbound', True)
    try:
        v.set_editor_property('priority', 10.0)
    except Exception:
        pass
    st = v.get_editor_property('settings')
    for k, val in (('auto_exposure_method', unreal.AutoExposureMethod.AEM_HISTOGRAM),
                   ('auto_exposure_min_brightness', -6.0), ('auto_exposure_max_brightness', 6.0),
                   ('auto_exposure_bias', float(bias)), ('auto_exposure_apply_physical_camera_exposure', False)):
        try:
            st.set_editor_property('override_' + k, True)
            st.set_editor_property(k, val)
        except Exception:
            pass
    v.set_editor_property('settings', st)
    log('exposure bias %.1f' % bias)


def go(where='couch'):
    """ney.go() -- put the camera inside the room.  ney.go('door') / ney.go('studio') / ney.go('couch')"""
    spots = {'couch': ((3.6, 1.5, 0.9), (3.6, 1.1, 3.6)), 'door': ((0.3, 1.6, 1.8), (7.0, 1.1, 1.9)),
             'studio': ((6.6, 1.6, 1.8), (0.0, 1.1, 1.8)), 'ceiling': ((3.5, 2.2, 1.8), (3.5, 0.0, 1.85))}
    (a, b) = spots.get(where, spots['couch'])
    p = to_ue(S.map, *a)
    t = to_ue(S.map, *b)
    d = unreal.Vector(t.x - p.x, t.y - p.y, t.z - p.z)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
        p, unreal.MathLibrary.make_rot_from_x(d))
    log('camera: ' + where)



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


AMBIENT = 0.6         # dim room glow so you can see the room (0 = pitch dark like the real room at night)


def ambient(level=None):
    """ney.ambient(0.5) -- brightness of the soft room glow (0..1)."""
    global AMBIENT
    if level is not None:
        AMBIENT = max(0.0, min(1.0, float(level)))
    have = {a.get_actor_label(): a for a in _actors() if a.actor_has_tag(TAG)}
    m = S.map or dict(swap=False, sx=1, sy=1, off=(0.0, 0.0, 0.0))
    spots = [('NEY Room glow A', 1.5, 1.6), ('NEY Room glow B', 4.5, 1.6)]   # metres east, south (room centre line)
    for lab, x, z in spots:
        a = have.get(lab)
        p = to_ue(m, x, 2.1, z)
        if a is None:
            a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(unreal.PointLight, p)
            a.set_actor_label(lab)
            a.tags = [unreal.Name(TAG)]
        else:
            a.set_actor_location(p, False, True)
        c = a.point_light_component
        for fn, v in (('set_mobility', unreal.ComponentMobility.MOVABLE), ('set_cast_shadows', False),
                      ('set_attenuation_radius', 900.0), ('set_volumetric_scattering_intensity', 0.0)):
            try:
                getattr(c, fn)(v)
            except Exception:
                pass
        try:
            c.set_editor_property('intensity_units', unreal.LightUnits.CANDELAS)
        except Exception:
            pass
        c.set_light_color(unreal.LinearColor(1.0, 0.55, 0.85, 1.0), True)      # soft pink-violet, like movie glow
        c.set_intensity(60.0 * AMBIENT)
    log('room glow %.2f' % AMBIENT)



def build_heads():
    fx = FIXTURES
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
            c.set_volumetric_scattering_intensity(8.0)
        except Exception:
            pass
        for comp in ('arrow_component', 'sprite_component'):     # the moving icon -- the body below shows the head
            try:
                a.get_editor_property(comp).set_visibility(False)
            except Exception:
                pass
        c.set_intensity(0.0)
        blab = lab + ' (body)'
        body = next((x for x in _actors() if x.get_actor_label() == blab), None)
        if body is None:
            body = sub.spawn_actor_from_object(_mesh('/Engine/BasicShapes/Cylinder'), p)
            body.set_actor_label(blab)
            body.tags = [unreal.Name(TAG)]
        body.set_actor_location(p, False, True)
        body.set_actor_scale3d(unreal.Vector(0.2, 0.2, 0.3))
        try:
            body.static_mesh_component.set_cast_shadow(False)
        except Exception:
            pass
        heads.append(dict(actor=a, comp=c, pos=p, rot0=float(f.get('pan0_heading_deg_plot', 0)),
                          sgn=-1 if f.get('pan_turns') == 'ccw' else 1, name=f['name']))
    S.heads = heads
    log('virtual heads ready: ' + ', '.join(h['name'] for h in heads))


def setup():
    S.map = find_mapping()
    log('room mapping ' + json.dumps(S.map))
    hide_plot(True)
    try:
        use_clean_scan()
    except Exception as e:
        unreal.log_warning('[NEY] clean scan: %s' % e)
    darken_room()
    ambient()
    try:
        floor_fill()
    except Exception as e:
        unreal.log_warning('[NEY] floor fill: %s' % e)
    clean = False
    try:
        clean = use_clean_room()
        if clean:
            align_clean_room()
    except Exception as e:
        unreal.log_warning('[NEY] clean room: %s' % e)
    view(getattr(S, 'view', None) or ('clean' if clean else 'scan'))
    build_heads()
    try:
        build_hue()
    except Exception as e:
        unreal.log_warning('[NEY] hue lamps: %s' % e)
    try:
        exposure()
    except Exception as e:
        unreal.log_warning('[NEY] exposure: %s' % e)
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
        try:
            _hue_tick()
        except Exception as e:
            S.hue_err = 'tick: %s' % e
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
    hue_live = getattr(S, 'hue', None) and time.time() - getattr(S, 'hue_t', 0) < 5
    s += ' | Hue: ' + ('live (%d lamps)' % len(S.hue) if hue_live else
                       (getattr(S, 'hue_msg', '') or getattr(S, 'hue_err', '') or ('not paired -- ney.hue_pair()' if not _hue_key() else 'waiting')))
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
    _hue_keyfile()
    threading.Thread(target=_hue_poller, daemon=True).start()
    if not _hue_key():
        log('Hue lamps not paired yet: press the round button on the Hue bridge, then run  py ney.hue_pair()')
    S.tick = unreal.register_slate_post_tick_callback(_tick)
    log('live link started')


def stop():
    S.run = False
    if S.tick is not None:
        unreal.unregister_slate_post_tick_callback(S.tick)
        S.tick = None
    log('live link stopped')


def install_autostart(src=None):
    d = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()), 'Python')
    os.makedirs(d, exist_ok=True)
    if src and os.path.abspath(src) != os.path.abspath(os.path.join(d, 'ney_unreal_live.py')):
        open(os.path.join(d, 'ney_unreal_live.py'), 'w', encoding='utf-8').write(open(src, encoding='utf-8').read())
    f = os.path.join(d, 'init_unreal.py')
    body = (INIT_MARK + ' -- starts the NEY live link (virtual heads follow the real ones).\n'
            'try:\n    import ney_unreal_live\n    ney_unreal_live.start()\n'
            'except Exception as e:\n    import unreal\n    unreal.log_warning("[NEY] live link did not start: %s" % e)\n')
    if os.path.exists(f) and INIT_MARK not in open(f, encoding='utf-8').read():
        log('a different init_unreal.py already exists -- left it alone: ' + f)
        return d
    open(f, 'w', encoding='utf-8').write(body)
    log('auto-start installed in ' + d)
    return d


if __name__ == '__main__':
    _src = globals().get('__file__')
    if _src and os.path.exists(_src):
        _d = install_autostart(_src)
        if _d not in sys.path:
            sys.path.append(_d)
        import importlib
        import ney_unreal_live as _m
        importlib.reload(_m)
        _m.stop()
        _m.start()
        try:
            _m.go()
        except Exception:
            pass
    else:
        log('could not see where this file lives -- running it now; auto-start not installed')
        stop()
        start()
