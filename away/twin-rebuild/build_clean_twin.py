#!/usr/bin/env python3
"""Clean room twin v2 (backlog item 2): the room rebuilt as simple, tidy shapes from the
MEASURED room plot -- no LiDAR scan, no baked textures, dark matte materials so the heads'
beams and the projection are what you actually see in Unreal.

Reads (never writes):  dmx/safety/room_plot.json   and   twin/ney_fixtures.json
Writes into out_dir:   ney_room_v2.glb        metres; X east, Y up, Z south -- the SAME frame as
                                              ney_room.glb / ney_room_scan_clean.glb, so all three
                                              overlap when dropped in at the origin
                       ney_room_v2_parts.csv  every part, its size, and whether its height is
                                              measured or a guess (the tape-measure list)
Plain Python 3, nothing to install, no network.
Usage: python3 build_clean_twin.py [room_plot.json] [ney_fixtures.json] [out_dir]
"""
import csv
import json
import math
import os
import struct
import sys

FT = 0.3048
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEF_PLOT = os.path.join(REPO, 'dmx', 'safety', 'room_plot.json')
DEF_FIX = os.path.join(REPO, 'twin', 'ney_fixtures.json')
DEF_OUT = os.path.join(HERE, 'out')
WALL_T = 0.33            # ft -- walls sit OUTSIDE the room line, so the inside face is exact
EDGE_MARGIN = 0.5        # ft -- items this close to the room outline still count as inside

# Materials: base colour (linear RGB), roughness, metallic. Dark + matte on purpose.
MATERIALS = {
    'wall':        ((0.09, 0.09, 0.10), 0.95, 0.0),
    'ceiling':     ((0.16, 0.16, 0.17), 0.95, 0.0),   # a touch lighter: beam pools read on it
    'floor':       ((0.05, 0.045, 0.04), 0.90, 0.0),
    'furniture':   ((0.07, 0.07, 0.075), 0.90, 0.0),
    'fabric_gray': ((0.11, 0.11, 0.115), 1.0, 0.0),
    'fabric_blue': ((0.03, 0.045, 0.10), 1.0, 0.0),
    'door':        ((0.06, 0.05, 0.045), 0.90, 0.0),
    'curtain':     ((0.05, 0.05, 0.06), 1.0, 0.0),    # glass door, curtain closed
    'mirror':      ((0.80, 0.80, 0.80), 0.05, 1.0),   # real hazard: it WILL reflect beams
    'art':         ((0.10, 0.09, 0.10), 0.95, 0.0),
    'screen':      ((0.55, 0.55, 0.55), 0.90, 0.0),   # put the projector's MediaTexture here
    'cloud':       ((0.65, 0.65, 0.68), 1.0, 0.0),    # white-ish: the real clouds catch beams
    'balloon':     ((0.35, 0.33, 0.36), 0.80, 0.0),
    'lamp':        ((0.20, 0.10, 0.35), 0.80, 0.0),   # purple markers for the Hue lamps
    'head':        ((0.03, 0.03, 0.03), 0.60, 0.3),
}
GROUPS = ['Shell', 'Openings', 'Furniture', 'Wall art', 'Lamps', 'Hanging', 'Heads']

# Top height (ft) for plot items that have no measured height ('z') of their own. GUESSES.
DEFAULT_TOP = {
    'o-kitchen': 36 / 12, 'f-desk': 30 / 12, 'f-cloudproj': 50 / 12, 'f-gray': 32 / 12,
    'f-blue': 32 / 12, 'f-coffee': 18 / 12, 'f-pouf': 17 / 12, 'f-studio': 30 / 12,
    'f-polyd': 34 / 12, 'f-optoma': 30 / 12, 'f-fire': 42 / 12, 'f-paper': 60 / 12,
    'f-elektron': 33 / 12, 'f-h3lamp': 60 / 12, 'f-laser': 6 / 12, 'k-fridge': 68 / 12,
    'k-stove': 36 / 12, 'f-roli': 40 / 12, 'f-push': 34 / 12,
}
FULL_HEIGHT = {'o-closet', 'o-mirror'}                       # floor to ceiling
OPENING_TOP = {'o-bed': 80 / 12, 'o-entry': 80 / 12, 'o-glass': 80 / 12}  # glass: 80 x 80 in (measured)
OPENING_MAT = {'o-bed': 'door', 'o-entry': 'door', 'o-glass': 'curtain', 'o-mirror': 'mirror',
               'o-closet': 'door', 'o-kitchen': 'furniture'}
ART_Z = {'a-tapestry': (3.0, 7.0), 'a-coexist': (4.0, 7.0), 'a-smiley': (5.0, 6.5)}
LAMP_TOP = {'l-shade': 4.0, 'l-play': 4.0}
# Couches get a seat + a back; which side of the footprint the back is on (plot axes).
COUCH = {'f-gray': ('+y', 'fabric_gray'), 'f-blue': ('-x', 'fabric_blue')}


# ------------------------------------------------------------------ small vector helpers
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a):
    L = math.sqrt(dot(a, a))
    return (a[0] / L, a[1] / L, a[2] / L) if L > 1e-12 else (0.0, 1.0, 0.0)


def to3(x, y, z):
    """Plot feet (x east, y south, z up) -> glTF metres (X east, Y up, Z south)."""
    return (x * FT, z * FT, y * FT)


def rot_y(p, deg):
    """Turn a glTF point about the up axis by a PLOT rotation (clockwise on the plan)."""
    t = -math.radians(deg or 0)
    c, s = math.cos(t), math.sin(t)
    return (p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c)


# ------------------------------------------------------------------ geometry
class Obj:
    """One named object: triangles grouped by material, stored relative to its origin."""

    def __init__(self, name, group, origin, info):
        self.name, self.group, self.origin, self.info = name, group, origin, info
        self.parts = {}                       # material -> [pos], [nrm]

    def tri(self, a, b, c, want, na=None, nb=None, nc=None, mat='furniture'):
        """Add a triangle (world metres), wound so its face points along `want`."""
        fn = cross(sub(b, a), sub(c, a))
        if math.sqrt(dot(fn, fn)) < 1e-12:
            return                                     # degenerate (sphere poles etc.)
        if dot(fn, want) < 0:
            b, c, nb, nc = c, b, nc, nb
            fn = (-fn[0], -fn[1], -fn[2])
        f = norm(fn)
        pos, nrm = self.parts.setdefault(mat, ([], []))
        o = self.origin
        for p, n in ((a, na), (b, nb), (c, nc)):
            pos.append((p[0] - o[0], p[1] - o[1], p[2] - o[2]))
            nrm.append(n if n is not None else f)

    def quad(self, q, want, mat):
        self.tri(q[0], q[1], q[2], want, mat=mat)
        self.tri(q[0], q[2], q[3], want, mat=mat)

    def triangles(self):
        return sum(len(p) // 3 for p, _ in self.parts.values())


def add_box(obj, cx, cy, w, d, z0, z1, rot, mat):
    """Box from plot feet: centre (cx, cy), footprint w (x) by d (y), bottom z0 to top z1."""
    centre = to3(cx, cy, (z0 + z1) / 2)
    h = (w * FT / 2, max(0.005, (z1 - z0) * FT / 2), d * FT / 2)
    for axis in range(3):
        u, v = [k for k in range(3) if k != axis]
        for s in (-1, 1):
            corners = []
            for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p = [0.0, 0.0, 0.0]
                p[axis], p[u], p[v] = s * h[axis], su * h[u], sv * h[v]
                corners.append(p)
            n = [0.0, 0.0, 0.0]
            n[axis] = float(s)
            wn = rot_y(tuple(n), rot)
            q = [tuple(a + b for a, b in zip(rot_y(tuple(p), rot), centre)) for p in corners]
            obj.quad(q, wn, mat)


def add_ellipsoid(obj, centre, r, mat, nlat=10, nlon=16):
    """Smooth ellipsoid, centre in glTF metres, radii r = (rx, ry, rz) metres."""
    def pt(i, j):
        th, ph = math.pi * i / nlat, 2 * math.pi * j / nlon
        u = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
        p = (centre[0] + r[0] * u[0], centre[1] + r[1] * u[1], centre[2] + r[2] * u[2])
        n = norm((u[0] / r[0], u[1] / r[1], u[2] / r[2]))
        return p, n
    for i in range(nlat):
        for j in range(nlon):
            (a, na), (b, nb) = pt(i, j), pt(i + 1, j)
            (c, nc), (d, nd) = pt(i + 1, j + 1), pt(i, j + 1)
            for t in ((a, na, b, nb, c, nc), (a, na, c, nc, d, nd)):
                mid = tuple((t[0][k] + t[2][k] + t[4][k]) / 3 - centre[k] for k in range(3))
                obj.tri(t[0], t[2], t[4], mid, t[1], t[3], t[5], mat=mat)


def add_cylinder(obj, cx, cy, radius, z0, z1, mat, sides=16):
    """Upright cylinder from plot feet."""
    ring = []
    for j in range(sides):
        a = 2 * math.pi * j / sides
        ring.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    top, bot = to3(cx, cy, z1), to3(cx, cy, z0)
    for j in range(sides):
        (x1, y1), (x2, y2) = ring[j], ring[(j + 1) % sides]
        out = norm(((x1 + x2) / 2 - cx, 0.0, (y1 + y2) / 2 - cy))
        obj.quad([to3(x1, y1, z0), to3(x2, y2, z0), to3(x2, y2, z1), to3(x1, y1, z1)], out, mat)
        obj.tri(top, to3(x1, y1, z1), to3(x2, y2, z1), (0, 1, 0), mat=mat)
        obj.tri(bot, to3(x1, y1, z0), to3(x2, y2, z0), (0, -1, 0), mat=mat)


def signed_area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def _in_tri(p, a, b, c):
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    neg = d1 < -1e-12 or d2 < -1e-12 or d3 < -1e-12
    pos = d1 > 1e-12 or d2 > 1e-12 or d3 > 1e-12
    return not (neg and pos)


def triangulate(poly):
    """Ear clipping for a simple (possibly concave) polygon -> list of index triples."""
    idx = list(range(len(poly)))
    if signed_area(poly) < 0:
        idx.reverse()
    tris = []
    while len(idx) > 3:
        n, done = len(idx), False
        for k in range(n):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % n]
            a, b, c = poly[i0], poly[i1], poly[i2]
            cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cr <= 1e-12:
                continue
            if any(_in_tri(poly[j], a, b, c) for j in idx
                   if j not in (i0, i1, i2) and tuple(poly[j]) not in (tuple(a), tuple(b), tuple(c))):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            done = True
            break
        if not done:                     # only straight-line points left: drop one
            for k in range(n):
                a, b, c = poly[idx[k - 1]], poly[idx[k]], poly[idx[(k + 1) % n]]
                if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) <= 1e-12:
                    idx.pop(k)
                    break
            else:
                raise ValueError('room outline is not a simple polygon')
    tris.append(tuple(idx))
    return tris


def inside(poly, x, y, margin=EDGE_MARGIN):
    """Point in the room outline, or within `margin` ft of it."""
    hit = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
        L2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / L2))
        if math.hypot(x - (x1 + t * (x2 - x1)), y - (y1 + t * (y2 - y1))) <= margin:
            return True
    return hit


# ------------------------------------------------------------------ the room
def build_objects(plan, fixtures):
    room = plan['room']
    ceil = float(room.get('ceiling', 93 / 12))
    poly = [tuple(p) for p in room['poly']]
    objs, left_out, names = [], [], {}

    def new(label, group, origin, info):
        n = label
        names[label] = names.get(label, 0) + 1
        if names[label] > 1:
            n = f'{label} {names[label]}'
        o = Obj(n, group, origin, info)
        objs.append(o)
        return o

    # --- shell: floor, ceiling, one wall per outline edge
    tris = triangulate(poly)
    fl = new('Floor', 'Shell', (0.0, 0.0, 0.0), {'height_from': 'measured'})
    cl = new('Ceiling', 'Shell', (0.0, ceil * FT, 0.0), {'height_from': 'measured', 'top_ft': ceil})
    for a, b, c in tris:
        pa, pb, pc = poly[a], poly[b], poly[c]
        fl.tri(to3(*pa, 0), to3(*pb, 0), to3(*pc, 0), (0, 1, 0), mat='floor')
        cl.tri(to3(*pa, ceil), to3(*pb, ceil), to3(*pc, ceil), (0, -1, 0), mat='ceiling')
    ccw = signed_area(poly) > 0
    npts = len(poly)

    def convex(i):
        (ax, ay), (bx, by), (cx, cy) = poly[i - 1], poly[i], poly[(i + 1) % npts]
        cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        return cr > 0 if ccw else cr < 0
    for i in range(npts):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % npts]
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 0.05:
            continue
        dx, dy = (x2 - x1) / L, (y2 - y1) / L
        ox, oy = (dy, -dx) if ccw else (-dy, dx)          # outward normal (plot axes)
        e0 = WALL_T if convex(i) else 0.0
        e1 = WALL_T if convex((i + 1) % npts) else 0.0
        mx = (x1 + x2) / 2 + dx * (e1 - e0) / 2 + ox * WALL_T / 2
        my = (y1 + y2) / 2 + dy * (e1 - e0) / 2 + oy * WALL_T / 2
        w = new(f'Wall {i + 1}', 'Shell', to3(mx, my, ceil / 2), {'height_from': 'measured', 'top_ft': ceil})
        add_box(w, mx, my, L + e0 + e1, WALL_T, 0, ceil, math.degrees(math.atan2(dy, dx)), 'wall')

    screen_z = (4.0, ceil)
    for it in plan['items']:
        if it.get('id') == 'u-screen' and it.get('zlo') is not None:
            screen_z = (float(it['zlo']), float(it.get('zhi', ceil)))

    # --- plot items
    for it in plan['items']:
        iid, kind, label = it.get('id', ''), it.get('kind'), it.get('label', it.get('id', '?'))
        x, y = float(it['x']), float(it['y'])
        w, d, rot = float(it.get('w', 1)), float(it.get('h', 1)), float(it.get('rot', 0) or 0)
        if kind in ('unsafe', 'head') or 'planned' in label.lower():
            continue                       # safety zones aren't objects; heads come from fixtures
        if kind not in ('furniture', 'opening', 'wallart', 'lamp', 'decor'):
            left_out.append((label, iid, f'unknown kind "{kind}"'))
            continue
        if not inside(poly, x, y):
            left_out.append((label, iid, 'outside the room outline'))
            continue
        info = {'plot_id': iid, 'x_ft': x, 'y_ft': y, 'w_ft': w, 'd_ft': d}
        if kind == 'furniture' or iid in OPENING_MAT:
            if iid in FULL_HEIGHT:
                top, src = ceil, 'measured'
            elif it.get('z') is not None:
                top, src = float(it['z']), 'measured (plot)'
            else:
                top, src = DEFAULT_TOP.get(iid, 2.5), 'GUESS'
            if kind == 'opening':
                top = OPENING_TOP.get(iid, top)
                src = 'measured' if iid in ('o-glass', 'o-mirror') else 'GUESS (standard door)'
            grp = 'Openings' if kind == 'opening' or iid == 'o-closet' else 'Furniture'
            o = new(label, grp, to3(x, y, top / 2), dict(info, bottom_ft=0, top_ft=top, height_from=src))
            if iid in COUCH:
                side, mat = COUCH[iid]
                seat = min(1.5, top)
                add_box(o, x, y, w, d, 0, seat, rot, mat)
                bt = 0.6                    # back cushion depth, ft
                bx = x + (w / 2 - bt / 2) * (1 if side == '+x' else -1 if side == '-x' else 0)
                by = y + (d / 2 - bt / 2) * (1 if side == '+y' else -1 if side == '-y' else 0)
                bw, bd = (bt, d) if side in ('+x', '-x') else (w, bt)
                add_box(o, bx, by, bw, bd, seat, top, rot, mat)
            else:
                add_box(o, x, y, w, d, 0, top, rot, OPENING_MAT.get(iid, 'furniture'))
        elif kind == 'opening':
            top = OPENING_TOP.get(iid, ceil)
            o = new(label, 'Openings', to3(x, y, top / 2), dict(info, bottom_ft=0, top_ft=top,
                                                                height_from='GUESS (standard door)'))
            add_box(o, x, y, w, d, 0, top, rot, OPENING_MAT.get(iid, 'door'))
        elif kind == 'wallart':
            z0, z1 = screen_z if iid == 'a-screen' else ART_Z.get(iid, (3.5, 6.5))
            src = 'measured' if iid == 'a-screen' else 'GUESS'
            o = new(label, 'Wall art', to3(x, y, (z0 + z1) / 2), dict(info, bottom_ft=z0, top_ft=z1, height_from=src))
            add_box(o, x, y, w, max(d, 0.1), z0, z1, rot, 'screen' if iid == 'a-screen' else 'art')
        elif kind == 'lamp':
            top = LAMP_TOP.get(iid, 1.0)
            o = new(label, 'Lamps', to3(x, y, top / 2), dict(info, bottom_ft=0, top_ft=top,
                                                             height_from='GUESS (marker only)'))
            add_cylinder(o, x, y, 0.25, 0, top, 'lamp')
        elif it.get('cat') == 'fan':
            z = ceil - 1.0
            o = new(label, 'Hanging', to3(x, y, z), dict(info, bottom_ft=z - 0.08, top_ft=ceil, height_from='GUESS'))
            add_cylinder(o, x, y, w / 2, z - 0.08, z, 'furniture', sides=24)
            add_cylinder(o, x, y, 0.05, z, ceil, 'furniture', sides=8)
        elif 'balloon' in label.lower():
            z = ceil - 1.6
            o = new(label, 'Hanging', to3(x, y, z), dict(info, bottom_ft=z - 1.0, top_ft=z + 0.45, height_from='GUESS'))
            add_ellipsoid(o, to3(x, y, z), (0.45 * FT,) * 3, 'balloon')
            add_box(o, x, y, 0.25, 0.25, z - 1.0, z - 0.75, 0, 'balloon')
        else:                                   # clouds (and any other hanging decor)
            z = ceil - 1.2
            o = new(label, 'Hanging', to3(x, y, z), dict(info, bottom_ft=z - 0.35, top_ft=z + 0.4, height_from='GUESS'))
            for dx, dz, s in ((-0.35, 0.0, 0.85), (0.0, 0.1, 1.0), (0.35, 0.0, 0.8)):
                add_ellipsoid(o, to3(x + dx, y, z + dz), (0.5 * s * FT, 0.3 * s * FT, 0.4 * s * FT), 'cloud')

    # --- heads, from the fixtures file (already metres, same frame) -- positions not touched
    for f in fixtures.get('fixtures', []):
        p = tuple(float(v) for v in f['position_m'])
        o = new(f['name'], 'Heads', p, {'dmx_address': f.get('dmx_address'), 'height_from': 'measured (fixtures)',
                                        'x_ft': p[0] / FT, 'y_ft': p[2] / FT, 'top_ft': p[1] / FT})
        xf, yf, zf = p[0] / FT, p[2] / FT, p[1] / FT
        add_box(o, xf, yf, 0.65, 0.65, zf - 0.33, zf + 0.33, 0, 'head')          # head body
        add_box(o, xf, yf, 0.8, 0.8, zf - 0.5, zf - 0.33, 0, 'head')             # base
    return objs, left_out, ceil


# ------------------------------------------------------------------ glb writer
def write_glb(path, objs, fixtures):
    binbuf, views, accs, meshes, nodes = bytearray(), [], [], [], []
    mat_names = list(MATERIALS)
    materials = [{'name': n, 'pbrMetallicRoughness': {'baseColorFactor': [*c, 1.0], 'metallicFactor': m,
                                                      'roughnessFactor': r}}
                 for n, (c, r, m) in MATERIALS.items()]

    def view(data, target):
        while len(binbuf) % 4:
            binbuf.append(0)
        views.append({'buffer': 0, 'byteOffset': len(binbuf), 'byteLength': len(data), 'target': target})
        binbuf.extend(data)
        return len(views) - 1

    def vec3(vals, with_minmax):
        flat = [round(c, 6) for v in vals for c in v]
        a = {'bufferView': view(struct.pack('<%df' % len(flat), *flat), 34962), 'componentType': 5126,
             'count': len(vals), 'type': 'VEC3'}
        if with_minmax:
            a['min'] = [min(v[k] for v in vals) for k in range(3)]
            a['max'] = [max(v[k] for v in vals) for k in range(3)]
            a['min'] = [round(c, 6) for c in a['min']]
            a['max'] = [round(c, 6) for c in a['max']]
        accs.append(a)
        return len(accs) - 1

    group_nodes = {g: [] for g in GROUPS}
    for o in objs:
        prims = []
        for mat in mat_names:
            if mat not in o.parts:
                continue
            pos, nrm = o.parts[mat]
            pi, ni = vec3(pos, True), vec3(nrm, False)
            idx = list(range(len(pos)))
            iv = view(struct.pack('<%dI' % len(idx), *idx), 34963)
            accs.append({'bufferView': iv, 'componentType': 5125, 'count': len(idx), 'type': 'SCALAR'})
            prims.append({'attributes': {'POSITION': pi, 'NORMAL': ni}, 'indices': len(accs) - 1,
                          'material': mat_names.index(mat)})
        if not prims:
            continue
        meshes.append({'name': o.name, 'primitives': prims})
        nodes.append({'name': o.name, 'mesh': len(meshes) - 1,
                      'translation': [round(c, 6) for c in o.origin], 'extras': o.info})
        group_nodes[o.group].append(len(nodes) - 1)
    for f in fixtures.get('fixtures', []):      # empties at each beam origin, for Blueprints
        nodes.append({'name': f'{f["name"]} beam origin',
                      'translation': [round(float(c), 6) for c in f['position_m']]})
        group_nodes['Heads'].append(len(nodes) - 1)
    kids = []
    for g in GROUPS:
        nodes.append({'name': g, 'children': group_nodes[g]})
        kids.append(len(nodes) - 1)
    nodes.append({'name': 'NeyRoom_v2', 'children': kids,
                  'extras': {'units': 'metres; X east, Y up, Z south (same frame as ney_room.glb)',
                             'source': 'room_plot.json + ney_fixtures.json (no scan)'}})
    gl = {'asset': {'version': '2.0', 'generator': 'Ney rig build_clean_twin.py'},
          'scene': 0, 'scenes': [{'name': 'NeyRoom_v2', 'nodes': [len(nodes) - 1]}],
          'nodes': nodes, 'meshes': meshes, 'materials': materials, 'accessors': accs,
          'bufferViews': views, 'buffers': [{'byteLength': len(binbuf)}]}
    while len(binbuf) % 4:
        binbuf.append(0)
    gl['buffers'][0]['byteLength'] = len(binbuf)
    js = json.dumps(gl, separators=(',', ':')).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binbuf)
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<4sII', b'glTF', 2, total))
        fh.write(struct.pack('<I4s', len(js), b'JSON') + js)
        fh.write(struct.pack('<I4s', len(binbuf), b'BIN\x00') + bytes(binbuf))
    return gl


def write_parts(path, objs, left_out):
    cols = ['group', 'name', 'plot_id', 'x_ft', 'y_ft', 'width_ft', 'depth_ft', 'bottom_ft', 'top_ft',
            'height_from', 'triangles']
    with open(path, 'w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(cols)
        for o in objs:
            i = o.info
            r = lambda k: '' if i.get(k) is None else (round(i[k], 3) if isinstance(i[k], float) else i[k])
            wr.writerow([o.group, o.name, r('plot_id'), r('x_ft'), r('y_ft'), r('w_ft'), r('d_ft'),
                         r('bottom_ft'), r('top_ft'), r('height_from'), o.triangles()])
        for label, iid, why in left_out:
            wr.writerow(['LEFT OUT', label, iid, '', '', '', '', '', '', why, 0])


def build(plot_path=DEF_PLOT, fix_path=DEF_FIX, out_dir=DEF_OUT):
    with open(plot_path) as fh:
        plan = json.load(fh)
    with open(fix_path) as fh:
        fixtures = json.load(fh)
    objs, left_out, ceil = build_objects(plan, fixtures)
    os.makedirs(out_dir, exist_ok=True)
    glb = os.path.join(out_dir, 'ney_room_v2.glb')
    parts = os.path.join(out_dir, 'ney_room_v2_parts.csv')
    gl = write_glb(glb, objs, fixtures)
    write_parts(parts, objs, left_out)
    return {'glb': glb, 'parts': parts, 'objects': objs, 'left_out': left_out, 'ceiling_ft': ceil, 'gltf': gl}


if __name__ == '__main__':
    a = sys.argv[1:]
    r = build(*(a + [DEF_PLOT, DEF_FIX, DEF_OUT][len(a):]))
    tris = sum(o.triangles() for o in r['objects'])
    guesses = sum(1 for o in r['objects'] if 'GUESS' in str(o.info.get('height_from', '')))
    print(f"wrote {os.path.relpath(r['glb'])}  ({len(r['objects'])} objects, {tris} triangles, {os.path.getsize(r['glb'])//1024} KB)")
    print(f"wrote {os.path.relpath(r['parts'])}  ({guesses} heights are guesses -- check them with a tape measure)")
    for label, iid, why in r['left_out']:
        print(f'left out: {label} ({iid}): {why}')
