"""Clean room model for Unreal: flat walls / floor / ceiling with the real room's look
baked onto them from the LiDAR scan, and furniture as tidy shapes coloured from the scan.

Inputs : room_plot.json (the plot), ney_room_scan_clean.glb (aligned, flattened scan)
Output : ney_room_clean.glb   (metres, glTF: X east, Y up, Z south -- same frame as the others)
"""
import io, json, math, struct, sys
import numpy as np
import trimesh
from numba import njit
from PIL import Image, ImageFilter
from scipy import ndimage
from shapely.geometry import Polygon, Point

FT = 0.3048
R_WALL = 250          # texture pixels per metre on walls
R_FLOOR = 160
plan = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'room_plot.json'))
SCAN = sys.argv[2] if len(sys.argv) > 2 else 'ney_room_scan_clean.glb'
OUT = sys.argv[3] if len(sys.argv) > 3 else 'ney_room_clean.glb'
CEIL = 2.37
WALL_PAINT = (222, 216, 208)      # the walls' own off-white

# ------------------------------------------------------------------ scan
b = open(SCAN, 'rb').read()
n = struct.unpack('<I', b[12:16])[0]
J = json.loads(b[20:20 + n]); BS = 20 + n + 8
prim = J['meshes'][0]['primitives'][0]


def acc(i, dt, k):
    a = J['accessors'][i]; bv = J['bufferViews'][a['bufferView']]
    o = BS + bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    return np.frombuffer(b[o:o + a['count'] * k * np.dtype(dt).itemsize], dtype=dt).reshape(-1, k)


V = acc(prim['attributes']['POSITION'], '<f4', 3).astype(np.float64)
UV = acc(prim['attributes']['TEXCOORD_0'], '<f4', 2).astype(np.float64)
ia = J['accessors'][prim['indices']]
F = acc(prim['indices'], {5125: '<u4', 5123: '<u2'}[ia['componentType']], 1).reshape(-1, 3).astype(np.int64)
ibv = J['bufferViews'][J['images'][0]['bufferView']]
TEX = np.asarray(Image.open(io.BytesIO(b[BS + ibv.get('byteOffset', 0):BS + ibv.get('byteOffset', 0) + ibv['byteLength']])).convert('RGB'))
TH, TW = TEX.shape[:2]
C = V[F].mean(1)
N = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
N /= (np.linalg.norm(N, axis=1, keepdims=True) + 1e-12)
# make sure normals point the way the surfaces face (floor normals should point up)
fl = C[:, 1] < 0.02
if np.median(N[fl, 1]) < 0:
    N = -N
print('scan tris', len(F), 'texture', TW, TH)


@njit(cache=True)
def raster(P2, Z, T, F, sel, W, H, img, zb):
    """P2: per-vertex image xy, Z: per-vertex depth (lower wins), T: per-vertex texture px."""
    for f in sel:
        i0, i1, i2 = F[f, 0], F[f, 1], F[f, 2]
        x0, y0 = P2[i0, 0], P2[i0, 1]; x1, y1 = P2[i1, 0], P2[i1, 1]; x2, y2 = P2[i2, 0], P2[i2, 1]
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-9:
            continue
        xa = max(0, int(math.floor(min(x0, x1, x2)))); xb = min(W - 1, int(math.ceil(max(x0, x1, x2))))
        ya = max(0, int(math.floor(min(y0, y1, y2)))); yb = min(H - 1, int(math.ceil(max(y0, y1, y2))))
        for py in range(ya, yb + 1):
            for px in range(xa, xb + 1):
                cx, cy = px + 0.5, py + 0.5
                w0 = ((y1 - y2) * (cx - x2) + (x2 - x1) * (cy - y2)) / den
                w1 = ((y2 - y0) * (cx - x2) + (x0 - x2) * (cy - y2)) / den
                w2 = 1.0 - w0 - w1
                if w0 < -0.01 or w1 < -0.01 or w2 < -0.01:
                    continue
                z = w0 * Z[i0] + w1 * Z[i1] + w2 * Z[i2]
                if z >= zb[py, px]:
                    continue
                zb[py, px] = z
                tx = w0 * T[i0, 0] + w1 * T[i1, 0] + w2 * T[i2, 0]
                ty = w0 * T[i0, 1] + w1 * T[i1, 1] + w2 * T[i2, 1]
                img[py, px, 0] = tx; img[py, px, 1] = ty


TPX = np.c_[np.clip(UV[:, 0], 0, 1) * (TW - 1), np.clip(UV[:, 1], 0, 1) * (TH - 1)]


def bake(P2, Z, sel, W, H, base_col=None):
    coords = np.full((H, W, 2), -1.0)
    zb = np.full((H, W), 1e9)
    raster(P2, Z, TPX, F, np.asarray(sel, dtype=np.int64), W, H, coords, zb)
    have = coords[..., 0] >= 0
    img = np.zeros((H, W, 3), np.uint8)
    xs = coords[..., 0][have]; ys = coords[..., 1][have]
    # bilinear sample
    x0 = np.floor(xs).astype(int); y0 = np.floor(ys).astype(int)
    x1 = np.minimum(x0 + 1, TW - 1); y1 = np.minimum(y0 + 1, TH - 1)
    fx = (xs - x0)[:, None]; fy = (ys - y0)[:, None]
    s = (TEX[y0, x0] * (1 - fx) * (1 - fy) + TEX[y0, x1] * fx * (1 - fy) + TEX[y1, x0] * (1 - fx) * fy + TEX[y1, x1] * fx * fy)
    img[have] = np.clip(s, 0, 255).astype(np.uint8)
    cover = have.mean()
    if not have.any():
        return None, 0.0
    # small holes: borrow the nearest real pixel; big holes: the surface's own base colour (no streaks)
    dist, idx = ndimage.distance_transform_edt(~have, return_distances=True, return_indices=True)
    filled = img[tuple(idx)].astype(float)
    px = img[have].astype(float)
    mx, mn = px.max(1), px.min(1)
    paint = px[(mx > 150) & ((mx - mn) / np.maximum(mx, 1) < 0.15)]
    base = np.median(paint, 0) if len(paint) > 500 else (np.median(px, 0) if base_col is None else np.asarray(base_col, float))
    k = np.clip((dist - 6) / 20.0, 0, 1)[..., None]
    filled = filled * (1 - k) + base * k
    soft = np.asarray(Image.fromarray(filled.astype(np.uint8)).filter(ImageFilter.GaussianBlur(4)))
    out = np.where(have[..., None], img, soft)
    return out, cover


def jpeg(arr, q=88):
    bio = io.BytesIO(); Image.fromarray(arr).save(bio, format='JPEG', quality=q); bio.seek(0)
    return Image.open(bio)


def mat(name, color=(1, 1, 1), tex=None, metal=0.0, rough=0.85):
    return trimesh.visual.material.PBRMaterial(name=name, baseColorFactor=[*color, 1.0], baseColorTexture=tex,
                                               metallicFactor=metal, roughnessFactor=rough, doubleSided=False)


def lin(c):   # 0-255 sRGB -> 0-1 (glTF baseColorFactor is linear)
    c = np.asarray(c, float) / 255.0
    return tuple(np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4))


scene = trimesh.Scene()
used = {}


def add(name, mesh):
    k = name
    if k in used:
        used[k] += 1; k = f'{name} {used[name]}'
    else:
        used[k] = 1
    scene.add_geometry(mesh, node_name=k, geom_name=k)


# ------------------------------------------------------------------ room shell
poly_ft = plan['room']['poly']
poly = [(x * FT, y * FT) for x, y in poly_ft]          # (X east, Z south) metres
shape = Polygon(poly)
minx, minz, maxx, maxz = shape.bounds

# floor (baked top-down)
Wf, Hf = int((maxx - minx) * R_FLOOR), int((maxz - minz) * R_FLOOR)
sel = np.where((N[:, 1] > 0.6) & (C[:, 1] < 0.08))[0]
P2 = np.c_[(V[:, 0] - minx) * R_FLOOR, (V[:, 2] - minz) * R_FLOOR]
floor_img, cov = bake(P2, -V[:, 1], sel, Wf, Hf)
Image.fromarray(floor_img).save('dbg_floor.jpg')
print('floor', Wf, Hf, 'coverage %.0f%%' % (cov * 100))
v2, faces = trimesh.creation.triangulate_polygon(shape)
fv = np.c_[v2[:, 0], np.zeros(len(v2)), v2[:, 1]]
fuv = np.c_[(v2[:, 0] - minx) / (maxx - minx), (v2[:, 1] - minz) / (maxz - minz)]
fm = trimesh.Trimesh(fv, faces[:, ::-1], process=False)
# a clean wood floor reads far better than the scan's smeared one; the baked floor is kept as an option
FLOOR_BAKED = False
fm.visual = trimesh.visual.TextureVisuals(uv=fuv, material=mat('Floor', tex=jpeg(floor_img), rough=0.6)) if FLOOR_BAKED else \
    trimesh.visual.TextureVisuals(uv=fuv, material=mat('Floor', lin((122, 86, 60)), rough=0.45))
add('Floor', fm)

# ceiling (plain)
cm = trimesh.Trimesh(np.c_[v2[:, 0], np.full(len(v2), CEIL), v2[:, 1]], faces, process=False)
cm.visual = trimesh.visual.TextureVisuals(material=mat('Ceiling', lin((236, 233, 228)), rough=0.95))
add('Ceiling', cm)

# walls: one flat panel per edge, the scan's look baked on
for i in range(len(poly)):
    a = np.array(poly[i]); bb = np.array(poly[(i + 1) % len(poly)])
    L = float(np.linalg.norm(bb - a))
    if L < 0.05:
        continue
    t = (bb - a) / L
    nrm = np.array([-t[1], t[0]])
    mid = (a + bb) / 2
    if not shape.contains(Point(*(mid + nrm * 0.05))):
        nrm = -nrm
    rel = np.c_[V[:, 0] - a[0], V[:, 2] - a[1]]
    s = rel @ t; d = rel @ nrm
    cs = np.c_[C[:, 0] - a[0], C[:, 2] - a[1]]
    sc = cs @ t; dc = cs @ nrm
    facing = N[:, 0] * nrm[0] + N[:, 2] * nrm[1]
    low = C[:, 1] < 1.0      # down low only the wall itself (skips cables, stands, couch backs)
    sel = np.where((dc > -0.08) & (dc < np.where(low, 0.035, 0.10)) & (sc > -0.03) & (sc < L + 0.03) & (facing > 0.5))[0]
    W, H = max(8, int(L * R_WALL)), int(CEIL * R_WALL)
    P2 = np.c_[s * R_WALL, (CEIL - V[:, 1]) * R_WALL]
    img, cov = bake(P2, d, sel, W, H, WALL_PAINT)
    if img is None or cov < 0.12:
        img = np.full((H, W, 3), WALL_PAINT, np.uint8)
    Image.fromarray(img).save('dbg_wall_%02d.jpg' % (i + 1))
    print('wall %d  %.2f m  coverage %.0f%%' % (i + 1, L, cov * 100))
    p0 = np.array([a[0], 0, a[1]]); p1 = np.array([bb[0], 0, bb[1]])
    up = np.array([0, CEIL, 0])
    wv = np.array([p0, p1, p1 + up, p0 + up])
    wuv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)     # trimesh uv (v up); it flips to glTF on export
    wf = np.array([[0, 1, 2], [0, 2, 3]])
    m = trimesh.Trimesh(wv, wf, process=False)
    # face the room
    if np.dot(m.face_normals[0][[0, 2]], nrm) < 0:
        m = trimesh.Trimesh(wv, wf[:, ::-1], process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=wuv, material=mat('Wall %d' % (i + 1), tex=jpeg(img), rough=0.9))
    add('Wall %d' % (i + 1), m)


# ------------------------------------------------------------------ furniture
def scan_colour(cx, cz, w, d, rot, top, prefer_top=True):
    ang = math.radians(rot or 0)
    ca, sa = math.cos(ang), math.sin(ang)
    dx, dz = C[:, 0] - cx, C[:, 2] - cz
    lx = dx * ca + dz * sa; lz = -dx * sa + dz * ca
    m = (np.abs(lx) < w / 2 + 0.03) & (np.abs(lz) < d / 2 + 0.03) & (C[:, 1] > 0.03) & (C[:, 1] < top + 0.08)
    if prefer_top and (m & (N[:, 1] > 0.5)).sum() > 40:
        m &= N[:, 1] > 0.5
    if m.sum() < 10:
        return None
    uvc = UV[F[m]].mean(1)
    px = TEX[np.clip((uvc[:, 1] * (TH - 1)).astype(int), 0, TH - 1), np.clip((uvc[:, 0] * (TW - 1)).astype(int), 0, TW - 1)]
    return tuple(np.median(px, 0))


def cyl(radius, height, sections=32):
    m = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))   # trimesh cylinders run along Z
    return m


def boxm(cx, cz, w, d, y0, y1, rot):
    m = trimesh.creation.box(extents=[w, max(0.005, y1 - y0), d])
    T = trimesh.transformations.translation_matrix([cx, (y0 + y1) / 2, cz]) @ \
        trimesh.transformations.rotation_matrix(-math.radians(rot or 0), [0, 1, 0])
    m.apply_transform(T)
    return m


def local(cx, cz, rot, lx, lz):
    ang = math.radians(rot or 0)
    return cx + lx * math.cos(ang) - lz * math.sin(ang), cz + lx * math.sin(ang) + lz * math.cos(ang)


def colour_mesh(m, name, col, rough=0.8, metal=0.0):
    m.visual = trimesh.visual.TextureVisuals(material=mat(name, lin(col), rough=rough, metal=metal))
    return m


DEFAULT_H = {'Blue couch': 32, 'Gray couch': 32, 'Coffee table': 18, 'Pouf': 17, 'Fridge': 68, 'Stove + microwave': 36,
             'Kitchen counter': 36, 'Water heater': 93, 'White desk · Zephyrus': 30, 'Studio desk': 30, 'Fireplace': 42,
             'Poly D': 34, 'Roli': 40, 'Optoma': 30, 'Paper lamp': 60, 'Cloud projector': 50, 'Laser bar (parked)': 6,
             'Floor lamp': 60, 'Elektrons + Evil Pet': 33, 'Push 2': 34}
FALLBACK = {'Gray couch': (128, 126, 124), 'Blue couch': (40, 60, 130), 'Fridge': (225, 225, 222), 'White shelf': (232, 230, 226),
            'White desk · Zephyrus': (232, 230, 226), 'Coffee table': (110, 70, 45)}
TABLES = ('Coffee table', 'Side table', 'Corner table', 'White desk · Zephyrus', 'Studio desk', 'Rolly desk')
COUCHES = ('Gray couch', 'Blue couch')
ROUND = ('Pouf', 'Papasan chair', 'Floor lamp', 'Paper lamp', 'Cloud projector')
wall_lines = [((poly[i][0], poly[i][1]), (poly[(i + 1) % len(poly)][0], poly[(i + 1) % len(poly)][1])) for i in range(len(poly))]

for it in plan['items']:
    k, lab = it['kind'], it.get('label', '')
    x, z = it['x'] * FT, it['y'] * FT
    w, d, rot = it.get('w', 1) * FT, it.get('h', 1) * FT, it.get('rot', 0) or 0
    if k == 'furniture':
        top = (it.get('z') * FT) if it.get('z') else DEFAULT_H.get(lab, 30) * 0.0254
        col = scan_colour(x, z, w, d, rot, top) or FALLBACK.get(lab, (180, 176, 168))
        if lab in FALLBACK:
            col = FALLBACK[lab]
        parts = []
        if lab in COUCHES:
            seat = 17 * 0.0254; back_d = 8 * 0.0254; arm_w = 6 * 0.0254
            # back goes on the long side nearest a wall
            long_x = w >= d
            sides = [(0, d / 2), (0, -d / 2)] if long_x else [(w / 2, 0), (-w / 2, 0)]
            best = None
            for sx, sz in sides:
                px, pz = local(x, z, rot, sx, sz)
                dist = shape.exterior.distance(Point(px, pz))
                if best is None or dist < best[0]:
                    best = (dist, sx, sz)
            _, sx, sz = best
            parts.append(boxm(x, z, w, d, 0.0, seat, rot))
            if long_x:
                bx, bz = local(x, z, rot, 0, np.sign(sz) * (d / 2 - back_d / 2))
                parts.append(boxm(bx, bz, w, back_d, seat, top, rot))
                for e in (-1, 1):
                    ax, az = local(x, z, rot, e * (w / 2 - arm_w / 2), 0)
                    parts.append(boxm(ax, az, arm_w, d, seat, seat + 8 * 0.0254, rot))
            else:
                bx, bz = local(x, z, rot, np.sign(sx) * (w / 2 - back_d / 2), 0)
                parts.append(boxm(bx, bz, back_d, d, seat, top, rot))
                for e in (-1, 1):
                    ax, az = local(x, z, rot, 0, e * (d / 2 - arm_w / 2))
                    parts.append(boxm(ax, az, w, arm_w, seat, seat + 8 * 0.0254, rot))
            # cushions a touch lighter
            m = trimesh.util.concatenate(parts)
            add(lab, colour_mesh(m, lab, col, rough=0.95))
            continue
        if lab in TABLES:
            slab = 0.035
            parts.append(boxm(x, z, w, d, top - slab, top, rot))
            leg = 0.045
            for ex in (-1, 1):
                for ez in (-1, 1):
                    lx_, lz_ = local(x, z, rot, ex * (w / 2 - leg), ez * (d / 2 - leg))
                    parts.append(boxm(lx_, lz_, leg, leg, 0, top - slab, rot))
            add(lab, colour_mesh(trimesh.util.concatenate(parts), lab, col, rough=0.55))
            continue
        if lab in ROUND:
            r = min(w, d) / 2
            if lab == 'Papasan chair':
                bowl = cyl(r, 0.25, 48)
                bowl.apply_translation([x, top - 0.2, z])
                stand = cyl(r * 0.55, top - 0.32, 32)
                stand.apply_translation([x, (top - 0.32) / 2, z])
                m = trimesh.util.concatenate([bowl, stand])
            elif lab in ('Floor lamp', 'Paper lamp', 'Cloud projector'):
                pole = cyl(0.015, top, 12)
                pole.apply_translation([x, top / 2, z])
                shade = trimesh.creation.icosphere(subdivisions=3, radius=r * 0.6)
                shade.apply_translation([x, top, z])
                m = trimesh.util.concatenate([pole, shade])
                col = (238, 232, 220)
            else:
                m = cyl(r, top, 40)
                m.apply_translation([x, top / 2, z])
            add(lab, colour_mesh(m, lab, col))
            continue
        add(lab, colour_mesh(boxm(x, z, w, d, 0.0, top, rot), lab, col))
    elif k == 'lamp':
        m = cyl(0.08, 0.3, 24)
        m.apply_translation([x, 0.15, z])
        add(lab, colour_mesh(m, lab, (235, 235, 235), rough=0.4))
    elif k == 'decor':
        cat = it.get('cat')
        if cat == 'fan':
            r = w / 2
            hub = cyl(0.12, 0.15, 24); hub.apply_translation([x, CEIL - 0.25, z])
            rod = cyl(0.02, 0.2, 8); rod.apply_translation([x, CEIL - 0.1, z])
            blades = [hub, rod]
            for j in range(5):
                bl = trimesh.creation.box(extents=[r - 0.12, 0.01, 0.13])
                bl.apply_translation([(r - 0.12) / 2 + 0.12, 0, 0])
                bl.apply_transform(trimesh.transformations.rotation_matrix(j * 2 * math.pi / 5, [0, 1, 0]))
                bl.apply_translation([x, CEIL - 0.28, z])
                blades.append(bl)
            add(lab, colour_mesh(trimesh.util.concatenate(blades), lab, (120, 92, 70), rough=0.5))
            continue
        y = CEIL - 14 * 0.0254
        name = lab.lower()
        if 'cloud' in name:
            puffs = []
            for ox, oy, oz, rr in ((0, 0, 0, 0.16), (0.14, -0.02, 0.03, 0.12), (-0.14, -0.02, -0.02, 0.12), (0.05, 0.07, -0.05, 0.11)):
                p = trimesh.creation.icosphere(subdivisions=2, radius=rr); p.apply_translation([x + ox, y + oy, z + oz]); puffs.append(p)
            add(lab, colour_mesh(trimesh.util.concatenate(puffs), lab, (245, 245, 248), rough=0.9))
            continue
        colmap = {'blue': (60, 110, 220), 'red': (210, 40, 45), 'orange': (240, 130, 30), 'green': (50, 170, 80), 'yellow': (245, 210, 40)}
        col = next((v for kk, v in colmap.items() if kk in name), (230, 230, 230))
        ball = trimesh.creation.icosphere(subdivisions=3, radius=0.14); ball.apply_translation([x, y, z])
        ball.apply_scale(1.0)
        basket = trimesh.creation.box(extents=[0.07, 0.06, 0.07]); basket.apply_translation([x, y - 0.22, z])
        add(lab, colour_mesh(trimesh.util.concatenate([ball, basket]), lab, col, rough=0.5))
    elif k == 'opening' and 'mirror' in lab.lower():
        # mirrored closet doors: a real mirror, so beams bounce like they do in the room
        L = d; mx = x + 0.012
        mm = trimesh.creation.box(extents=[0.012, 80 * 0.0254, L - 0.04])
        mm.apply_translation([mx, 40 * 0.0254 + 0.01, z])
        add('Mirror (closet doors)', colour_mesh(mm, 'Mirror', (240, 240, 240), rough=0.03, metal=1.0))

scene.export(OUT)
print('wrote', OUT)
