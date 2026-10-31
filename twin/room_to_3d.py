"""Room plot -> 3D grey-box (glTF .glb) for Unreal / any 3D tool, plus a fixtures JSON.

Axes in the plot: x east, y south, feet. Output: metres, glTF convention (Y up):
    X = east, Y = up, Z = south.   Unreal's glTF importer converts to its own axes.
Usage: python3 room_to_3d.py room.json out_dir
"""
import json, math, os, sys
import numpy as np
import trimesh

FT = 0.3048
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
plan = json.load(open(src))
room = plan['room']
CEIL = 93 / 12.0
WALL_T = 0.35  # ft

# default heights (ft) when the plot has none
DEFAULT_H = {
    'Blue couch': 32 / 12, 'Gray couch': 32 / 12, 'Coffee table': 18 / 12, 'Pouf': 17 / 12,
    'Fridge': 68 / 12, 'Stove + microwave': 36 / 12, 'Kitchen counter': 36 / 12, 'Water heater': CEIL,
    'White desk · Zephyrus': 30 / 12, 'Studio desk': 30 / 12, 'Fireplace': 42 / 12, 'Poly D': 34 / 12,
    'Roli': 40 / 12, 'Optoma': 30 / 12, 'Paper lamp': 60 / 12, 'Cloud projector': 50 / 12,
    'Laser bar (parked)': 6 / 12, 'Floor lamp': 60 / 12, 'Elektrons + Evil Pet': 33 / 12, 'Push 2': 34 / 12,
}
COL = {'wall': [210, 210, 205, 255], 'floor': [120, 110, 100, 255], 'furniture': [190, 185, 172, 255],
       'head': [194, 65, 12, 255], 'lamp': [124, 58, 237, 255], 'decor': [15, 118, 110, 255],
       'opening': [111, 159, 191, 140], 'wallart': [90, 96, 110, 255],
       'eyes': [212, 55, 44, 70], 'reflect': [37, 99, 235, 80], 'screen': [161, 98, 7, 80], 'fan': [147, 51, 234, 60]}


def to3(x, y, z):  # plot feet -> glTF metres
    return [x * FT, z * FT, y * FT]


def box(name, cx, cy, w, d, z0, z1, rot_deg, color):
    m = trimesh.creation.box(extents=[w * FT, max(0.01, (z1 - z0)) * FT, d * FT])
    T = np.eye(4)
    a = math.radians(rot_deg or 0)
    # plot rotation is clockwise on screen (y down) == about the glTF up axis, negative
    R = trimesh.transformations.rotation_matrix(-a, [0, 1, 0])
    T = trimesh.transformations.translation_matrix(to3(cx, cy, (z0 + z1) / 2)) @ R
    m.apply_transform(T)
    m.visual.face_colors = color
    return name, m


meshes = []
# floor
poly = room['poly']
xs, ys = [p[0] for p in poly], [p[1] for p in poly]
from shapely.geometry import Polygon  # noqa: E402
verts2d, faces = trimesh.creation.triangulate_polygon(Polygon(poly))
fl = trimesh.Trimesh(vertices=[[p[0] * FT, 0.0, p[1] * FT] for p in verts2d], faces=faces[:, ::-1], process=False)
fl.visual.face_colors = COL['floor']
meshes.append(('Floor', fl))
# ceiling (thin, so beams have something to hit in previs)
cl = trimesh.Trimesh(vertices=[[p[0] * FT, CEIL * FT, p[1] * FT] for p in verts2d], faces=faces, process=False)
cl.visual.face_colors = [235, 235, 230, 255]
meshes.append(('Ceiling', cl))
# walls: one thin box per polygon edge
for i in range(len(poly)):
    (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 0.05:
        continue
    ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
    meshes.append(box(f'Wall {i + 1}', (x1 + x2) / 2, (y1 + y2) / 2, L, WALL_T, 0, CEIL, ang, COL['wall']))

fixtures = []
for it in plan['items']:
    k, lab = it['kind'], it.get('label', it['id'])
    x, y, w, h, rot = it['x'], it['y'], it.get('w', 1), it.get('h', 1), it.get('rot', 0)
    if k == 'furniture':
        top = it.get('z') or DEFAULT_H.get(lab, 2.5)
        meshes.append(box(lab, x, y, w, h, 0, top, rot, COL['furniture']))
    elif k == 'head':
        z = it.get('z', 3.0)
        meshes.append(box(lab, x, y, 0.75, 0.75, z - 0.45, z + 0.45, 0, COL['head']))
        fixtures.append({'name': lab, 'dmx_address': it.get('addr'), 'mode': '14ch Betopper LM70S',
                         'position_m': to3(x, y, z), 'plot_ft': [x, y, z],
                         'pan0_heading_deg_plot': rot, 'pan_turns': 'ccw' if it.get('flip') else 'cw'})
    elif k == 'lamp':
        c = trimesh.creation.cylinder(radius=0.25 * FT, height=1.0 * FT)
        c.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
        c.apply_translation(to3(x, y, 0.5)); c.visual.face_colors = COL['lamp']; meshes.append((lab, c))
    elif k == 'decor':
        if it.get('cat') == 'fan':
            d = trimesh.creation.cylinder(radius=(w / 2) * FT, height=0.08 * FT)
            d.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
            d.apply_translation(to3(x, y, CEIL - 1.0))
        else:   # clouds / balloons: hang ~14 in below the ceiling until measured
            d = trimesh.creation.icosphere(subdivisions=2, radius=0.45 * FT)
            d.apply_translation(to3(x, y, CEIL - 14 / 12))
        d.visual.face_colors = COL['decor']; meshes.append((lab, d))
    elif k == 'opening':
        top = 6.67 if 'door' in lab.lower() else CEIL
        meshes.append(box(lab, x, y, w, h, 0, top, rot, COL['opening']))
    elif k == 'wallart':
        meshes.append(box(lab, x, y, w, max(h, 0.1), 3.0, 6.0, rot, COL['wallart']))
    elif k == 'unsafe':
        lo = it.get('zlo') if it.get('zlo') is not None else 0.0
        hi = it.get('zhi') if it.get('zhi') is not None else CEIL
        meshes.append(box('UNSAFE ' + lab, x, y, w, h, lo, hi, rot, COL.get(it.get('cat'), [255, 0, 0, 70])))

scene = trimesh.Scene()
seen = {}
for name, m in meshes:
    n = name
    if n in seen:
        seen[n] += 1; n = f'{name} {seen[name]}'
    else:
        seen[n] = 1
    scene.add_geometry(m, node_name=n, geom_name=n)
scene.export(os.path.join(out, 'ney_room.glb'))
json.dump({'units': 'metres; X east, Y up, Z south (glTF)', 'ceiling_m': CEIL * FT, 'fixtures': fixtures},
          open(os.path.join(out, 'ney_fixtures.json'), 'w'), indent=1)
print('meshes', len(meshes), 'fixtures', len(fixtures))
