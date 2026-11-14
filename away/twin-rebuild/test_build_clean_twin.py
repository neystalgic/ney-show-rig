#!/usr/bin/env python3
"""Offline test for build_clean_twin.py. No network; the real plot + fixtures files are only
read (checked by hash), and every build in this test writes to a throwaway temp folder."""
import hashlib
import json
import math
import os
import socket
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_clean_twin as bt  # noqa: E402


def _no_net(*a, **k):
    raise RuntimeError("network blocked in tests")


socket.socket.connect = _no_net
socket.create_connection = _no_net
failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def sha(p):
    with open(p, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read_glb(path):
    b = open(path, 'rb').read()
    magic, ver, total = struct.unpack('<4sII', b[:12])
    jl, jt = struct.unpack('<I4s', b[12:20])
    gl = json.loads(b[20:20 + jl])
    bl, btag = struct.unpack('<I4s', b[20 + jl:28 + jl])
    binb = b[28 + jl:28 + jl + bl]
    return magic, ver, total, len(b), jt, btag, gl, binb


def accessor(gl, binb, i):
    a = gl['accessors'][i]
    v = gl['bufferViews'][a['bufferView']]
    k = {'VEC3': 3, 'SCALAR': 1}[a['type']]
    fmt = {5126: 'f', 5125: 'I'}[a['componentType']]
    off = v['byteOffset'] + a.get('byteOffset', 0)
    assert off + a['count'] * k * 4 <= len(binb), 'accessor past end of buffer'
    vals = struct.unpack('<%d%s' % (a['count'] * k, fmt), binb[off:off + a['count'] * k * 4])
    return [vals[j:j + k] for j in range(0, len(vals), k)] if k > 1 else list(vals)


# ---------------------------------------------------------------- 1. real plot, temp output
plot, fix = bt.DEF_PLOT, bt.DEF_FIX
before = (sha(plot), sha(fix))
tmp = tempfile.mkdtemp(prefix='twin_test_')
r = bt.build(plot, fix, tmp)
check('real repo plot + fixtures unchanged (read only)', (sha(plot), sha(fix)) == before)
check('output only in the temp folder', os.path.dirname(r['glb']) == tmp and os.path.dirname(r['parts']) == tmp)
magic, ver, total, size, jt, btag, gl, binb = read_glb(r['glb'])
check('glb header: magic glTF, version 2, length matches file', magic == b'glTF' and ver == 2 and total == size)
check('glb chunks: JSON then BIN', jt == b'JSON' and btag == b'BIN\x00')
check('buffer length matches BIN chunk', gl['buffers'][0]['byteLength'] == len(binb))
check('no textures / images (no baked scan)', 'images' not in gl and 'textures' not in gl)
check('scan never mentioned in the model', 'scan' not in json.dumps(gl).lower().replace('no scan', ''))

ok_idx, ok_wind, ok_minmax, ok_norm = True, True, True, True
world = {}
for n in gl['nodes']:
    if 'mesh' not in n:
        continue
    t = n.get('translation', [0, 0, 0])
    lo, hi = [1e9] * 3, [-1e9] * 3
    for p in gl['meshes'][n['mesh']]['primitives']:
        pos = accessor(gl, binb, p['attributes']['POSITION'])
        nrm = accessor(gl, binb, p['attributes']['NORMAL'])
        idx = accessor(gl, binb, p['indices'])
        a = gl['accessors'][p['attributes']['POSITION']]
        if any(abs(a['min'][k] - min(v[k] for v in pos)) > 1e-4 or abs(a['max'][k] - max(v[k] for v in pos)) > 1e-4
               for k in range(3)):
            ok_minmax = False
        if max(idx) >= len(pos) or len(idx) % 3:
            ok_idx = False
        for v in nrm:
            if abs(math.sqrt(sum(c * c for c in v)) - 1) > 1e-3:
                ok_norm = False
        for j in range(0, len(idx), 3):
            A, B, C = pos[idx[j]], pos[idx[j + 1]], pos[idx[j + 2]]
            fn = bt.cross(bt.sub(B, A), bt.sub(C, A))
            avg = [sum(nrm[idx[j + q]][k] for q in range(3)) for k in range(3)]
            if bt.dot(fn, avg) <= 0:
                ok_wind = False
        for v in pos:
            for k in range(3):
                lo[k] = min(lo[k], v[k] + t[k]); hi[k] = max(hi[k], v[k] + t[k])
    world[n['name']] = (lo, hi)
check('indices valid, whole triangles', ok_idx)
check('every triangle faces the way its normals say (no inside-out faces)', ok_wind)
check('normals are unit length', ok_norm)
check('POSITION min/max correct', ok_minmax)

ceil_m = 93 / 12 * bt.FT
check('ceiling at 93 in (2.362 m)', abs(world['Ceiling'][0][1] - ceil_m) < 1e-4 and abs(world['Ceiling'][1][1] - ceil_m) < 1e-4)
check('floor at 0', abs(world['Floor'][0][1]) < 1e-6 and abs(world['Floor'][1][1]) < 1e-6)
plan = json.load(open(plot))
poly = plan['room']['poly']
floor_area = 0.0
fn = [n for n in gl['nodes'] if n['name'] == 'Floor'][0]
for p in gl['meshes'][fn['mesh']]['primitives']:
    pos, idx = accessor(gl, binb, p['attributes']['POSITION']), accessor(gl, binb, p['indices'])
    for j in range(0, len(idx), 3):
        A, B, C = pos[idx[j]], pos[idx[j + 1]], pos[idx[j + 2]]
        floor_area += 0.5 * math.sqrt(sum(c * c for c in bt.cross(bt.sub(B, A), bt.sub(C, A))))
check('floor area = room outline area (%.2f m2)' % floor_area,
      abs(floor_area - abs(bt.signed_area(poly)) * bt.FT ** 2) < 1e-3)

xs, ys = [p[0] * bt.FT for p in poly], [p[1] * bt.FT for p in poly]
m = 0.25
outside = [k for k, (lo, hi) in world.items() if not k.startswith('Wall') and
           (lo[0] < min(xs) - m or hi[0] > max(xs) + m or lo[2] < min(ys) - m or hi[2] > max(ys) + m
            or lo[1] < -1e-6 or hi[1] > ceil_m + 1e-4)]
check('every object inside the room box, floor to ceiling %s' % (outside or ''), not outside)
wall_in = [n['name'] for n in gl['nodes'] if 'mesh' in n and n['name'].startswith('Wall ') and
           bt.inside(poly, n['translation'][0] / bt.FT, n['translation'][2] / bt.FT, margin=0.1)]
check('walls sit OUTSIDE the room line (inside faces exact) %s' % (wall_in or ''), not wall_in)
walls = [k for k in world if k.startswith('Wall')]
check('one wall per outline edge (%d)' % len(walls), len(walls) == len(poly))
fixtures = json.load(open(fix))['fixtures']
heads_ok = True
for f in fixtures:
    n = [x for x in gl['nodes'] if x['name'] == f['name'] + ' beam origin']
    if not n or any(abs(a - b) > 1e-5 for a, b in zip(n[0]['translation'], f['position_m'])):
        heads_ok = False
    lo, hi = world.get(f['name'], ([9] * 3, [-9] * 3))
    if not all(lo[k] - 1e-6 <= f['position_m'][k] <= hi[k] + 1e-6 for k in range(3)):
        heads_ok = False
check('4 heads + beam origins exactly at ney_fixtures.json positions', heads_ok and len(fixtures) == 4)
names = [n['name'] for n in gl['nodes']]
check('node names unique', len(names) == len(set(names)))
for g in bt.GROUPS + ['NeyRoom_v2']:
    if g not in names:
        check('group node %s' % g, False)
mats = {mm['name']: mm for mm in gl['materials']}
dark = all(0.2126 * mats[k]['pbrMetallicRoughness']['baseColorFactor'][0] +
           0.7152 * mats[k]['pbrMetallicRoughness']['baseColorFactor'][1] +
           0.0722 * mats[k]['pbrMetallicRoughness']['baseColorFactor'][2] < 0.2
           and mats[k]['pbrMetallicRoughness']['roughnessFactor'] >= 0.85
           for k in ('wall', 'ceiling', 'floor', 'furniture', 'fabric_gray', 'fabric_blue', 'curtain'))
check('walls / floor / ceiling / furniture are dark + matte', dark)
scr = [n for n in gl['nodes'] if n['name'] == 'Projection screen']
check('projection screen present with the screen material',
      bool(scr) and gl['meshes'][scr[0]['mesh']]['primitives'][0]['material'] == list(bt.MATERIALS).index('screen'))
lo, hi = world['Projection screen']
check('screen bottom 48 in off the floor (measured)', abs(lo[1] - 4 * bt.FT) < 1e-4)
gray = [n for n in gl['nodes'] if n['name'] == 'Gray couch'][0]
check('gray couch has seat + back (taller at the back wall)', gl['meshes'][gray['mesh']]['primitives'][0]['attributes']
      and len(accessor(gl, binb, gl['meshes'][gray['mesh']]['primitives'][0]['indices'])) == 2 * 36)
gb_lo, gb_hi = world['Gray couch']
check('gray couch back reaches 32 in', abs(gb_hi[1] - 32 / 12 * bt.FT) < 1e-4)
rows = open(r['parts']).read().splitlines()
check('parts list has a row per object + left-out rows', len(rows) == 1 + len(r['objects']) + len(r['left_out']))
check('cloud projector (outside the outline) listed as left out',
      any(i == 'f-cloudproj' for _, i, _ in r['left_out']))
check('guessed heights are flagged in the parts list', sum('GUESS' in x for x in rows) > 10)
r2 = bt.build(plot, fix, tempfile.mkdtemp(prefix='twin_test2_'))
check('two builds are byte-identical', sha(r['glb']) == sha(r2['glb']))

# ---------------------------------------------------------------- 2. a small fake room
fake_plan = {'room': {'ceiling': 8.0, 'poly': [[0, 0], [10, 0], [10, 6], [5, 6], [5, 10], [0, 10]]},
             'items': [
                 {'id': 'f-gray', 'kind': 'furniture', 'label': 'Couch', 'x': 2, 'y': 8, 'w': 3, 'h': 2},
                 {'id': 'd-c1', 'kind': 'decor', 'label': 'Cloud', 'x': 2, 'y': 2, 'w': 1, 'h': 1},
                 {'id': 'd-c2', 'kind': 'decor', 'label': 'Cloud', 'x': 3, 'y': 2, 'w': 1, 'h': 1},
                 {'id': 'o-bed', 'kind': 'opening', 'label': 'Door', 'x': 7, 'y': 0.15, 'w': 3, 'h': 0.3},
                 {'id': 'x1', 'kind': 'spaceship', 'label': 'Mystery', 'x': 1, 'y': 1},
                 {'id': 'f-far', 'kind': 'furniture', 'label': 'In the L notch', 'x': 8, 'y': 9},
                 {'id': 'u-x', 'kind': 'unsafe', 'label': 'Eye level', 'x': 2, 'y': 8},
                 {'id': 'd-p', 'kind': 'decor', 'label': 'Cloud spot (planned)', 'x': 2, 'y': 2}]}
fake_fix = {'fixtures': [{'name': 'Head 9', 'position_m': [0.5, 0.8, 0.5]}]}
fd = tempfile.mkdtemp(prefix='twin_fake_')
fp, ff = os.path.join(fd, 'plot.json'), os.path.join(fd, 'fix.json')
json.dump(fake_plan, open(fp, 'w')); json.dump(fake_fix, open(ff, 'w'))
rf = bt.build(fp, ff, os.path.join(fd, 'out'))
fnames = [o.name for o in rf['objects']]
check('fake: duplicate labels get numbered (Cloud, Cloud 2)', 'Cloud' in fnames and 'Cloud 2' in fnames)
check('fake: unknown kind left out with a reason', any(i == 'x1' and 'unknown' in w for _, i, w in rf['left_out']))
check('fake: item in the L-shaped notch (outside) left out', any(i == 'f-far' for _, i, _ in rf['left_out']))
check('fake: safety zones + planned spots are not objects', 'Eye level' not in fnames and not any('planned' in n for n in fnames))
check('fake: door is 80 in tall', abs(rf['objects'][[o.name for o in rf['objects']].index('Door')].info['top_ft'] - 80 / 12) < 1e-9)
check('fake: L room gets 6 walls, 4 tris per floor', sum(n.startswith('Wall') for n in fnames) == 6 and
      rf['objects'][0].triangles() == 4)
check('fake: head 9 built from fixtures', 'Head 9' in fnames)

# ---------------------------------------------------------------- 3. helpers
L = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
tr = bt.triangulate(L)
area = sum(abs(bt.signed_area([L[a], L[b], L[c]])) for a, b, c in tr)
check('ear clipping: concave L keeps its area', len(tr) == 4 and abs(area - abs(bt.signed_area(L))) < 1e-9)
tr2 = bt.triangulate(list(reversed(L)))
check('ear clipping: works clockwise too', len(tr2) == 4)
col = [(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)]
tr3 = bt.triangulate(col)
check('ear clipping: straight-line points handled', abs(sum(abs(bt.signed_area([col[a], col[b], col[c]])) for a, b, c in tr3) - 12) < 1e-9)
check('inside(): centre in, far point out, near-wall point in',
      bt.inside(L, 0.5, 0.5) and not bt.inside(L, 3, 3) and bt.inside(L, 4.3, 0.5))
try:
    socket.create_connection(('192.168.1.2', 80))
    check('network is blocked', False)
except RuntimeError:
    check('network is blocked', True)

print('\n%d FAIL' % len(failures) if failures else '\nALL PASSED')
sys.exit(1 if failures else 0)
