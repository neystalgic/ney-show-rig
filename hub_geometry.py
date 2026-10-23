# =============================================================================
# HUE HUB -- sacred geometry for the lamps
#
# Each FORM turns the room into a figure: every lamp (and every zone of a
# gradient lamp) sits at its place in the room, and the figure decides how
# bright it is -- and for some forms, which colour it takes.
#
#   golden       phyllotaxis: one lamp lights per step, chosen by the golden
#                ratio, each new one 137.5 degrees further round the colour wheel
#   flower       Seed / Flower of Life: a centre and a ring breathing in
#                six-fold symmetry
#   yantra       Sri Yantra: upward and downward triangles (your colour and its
#                opposite) interlocking, the bindu (centre) pulsing
#   metatron     a point of light travelling the lines of Metatron's Cube
#   chladni      Chladni plate patterns: the lamps on the vibrating parts glow,
#                a new mode every 4 cycles
#   spiral       a golden spiral turning through the room
#   tetrahedron, cube, tesseract
#                the solid rotating through the room; its corners light the
#                lamps they pass (front corners brighter)
#
# HARMONIES pick colours by sacred numbers: golden-angle steps, triads (3),
# hexads (6), opposites, neighbours, and Fibonacci shades of one colour.
# =============================================================================

import colorsys
import math

PHI = (1 + 5 ** 0.5) / 2
GOLDEN_ANGLE = 137.50776405
FORMS = ['golden', 'flower', 'yantra', 'metatron', 'chladni', 'spiral', 'tetrahedron', 'cube', 'tesseract']
CHLADNI_MODES = [(1, 2), (1, 3), (2, 3), (1, 4), (3, 4), (2, 5), (3, 5), (4, 5)]
HARMONIES = ['golden', 'triad', 'hexad', 'opposite', 'analogous', 'fibonacci']


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def polar(s):
    """angle (radians) and distance of a lamp from the middle of the room."""
    dx, dy = (s['u'] - 0.5) * 1.6, s['v'] - 0.5          # rooms are wider than they are tall
    return math.atan2(dy, dx), math.hypot(dx, dy)


def chladni_mode(t):
    i = int(math.floor(t / 4.0))
    a, b = CHLADNI_MODES[i % len(CHLADNI_MODES)], CHLADNI_MODES[(i + 1) % len(CHLADNI_MODES)]
    f = (t / 4.0) % 1.0
    k = _clamp((f - 0.8) / 0.2)                          # morph into the next mode at the end
    return a, b, k * k * (3 - 2 * k), (-1 if i % 2 else 1)


def _solid(name):
    if name == 'tetrahedron':
        return [(1, 1, 1, 0), (1, -1, -1, 0), (-1, 1, -1, 0), (-1, -1, 1, 0)]
    if name == 'cube':
        return [(x, y, z, 0) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    return [(x, y, z, w) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1) for w in (-1, 1)]


def _rot(a, b, ang):
    c, s = math.cos(ang), math.sin(ang)
    return a * c - b * s, a * s + b * c


def solid_points(name, rot, t):
    """2D positions (room 0-1) and front/back weight of the rotating solid's corners."""
    out = []
    for x, y, z, w in _solid(name):
        if name == 'tesseract':
            x, w = _rot(x, w, t * 0.9)                    # the 4D turn
            y, z = _rot(y, z, t * 0.45)
            k = 2.2 / (3.0 - w)                           # 4D -> 3D perspective
            x, y, z = x * k, y * k, z * k
        x, z = _rot(x, z, rot)
        y, z = _rot(y, z, rot * 0.6)
        size = 0.17 if name != 'tesseract' else 0.13
        out.append((0.5 + x * size / 1.6, 0.5 + y * size * 1.0, 0.5 + 0.5 * _clamp(z / 1.8, -1, 1)))
    return out


def form(name, segs, t, rot, base, spread=0.5):
    """Per lamp zone: (brightness 0-1, colour or None = keep the zone's own colour).
    t = cycles (beat-locked), rot = rotation in radians, base = the zones' own colours."""
    n = max(1, len(segs))
    out = []
    if name == 'golden':
        by_angle = sorted(range(n), key=lambda i: polar(segs[i])[0])
        step = int(math.floor(t))
        h0 = colorsys.rgb_to_hsv(*base[0])[0] if base else 0.0
        lit = {}
        for k in range(step - 5, step + 1):               # the last few seeds, fading
            i = by_angle[int(math.floor(((k * (1 / PHI)) % 1.0) * n))]
            age = t - k
            b = math.exp(-age / (0.5 + 1.2 * spread))
            if b > lit.get(i, (0, None))[0]:
                hue = (h0 + k * GOLDEN_ANGLE / 360.0) % 1.0
                lit[i] = (b, colorsys.hsv_to_rgb(hue, 1.0, 1.0))
        return [lit.get(i, (0.0, None)) for i in range(n)]
    if name == 'metatron':
        nodes = [(0.0, 0.0)]
        for ring, rad in ((0, 0.22), (1, 0.42)):
            for j in range(6):
                a = rot + j * math.pi / 3 + (math.pi / 6 if ring else 0)
                nodes.append((rad * math.cos(a), rad * math.sin(a)))
        path = [0, 1, 8, 3, 10, 5, 12, 0, 2, 9, 4, 11, 6, 7]   # through the centre, inner and outer stars
        x = (t * 2) % len(path)
        i = int(math.floor(x))
        f = x - i
        a, b = nodes[path[i]], nodes[path[(i + 1) % len(path)]]
        px, py = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        sig = 0.12 + 0.25 * spread
        for s in segs:
            dx, dy = (s['u'] - 0.5) * 1.6, s['v'] - 0.5
            d2 = (dx - px) ** 2 + (dy - py) ** 2
            glow = max(math.exp(-((dx - nx) ** 2 + (dy - ny) ** 2) / 0.01) for nx, ny in nodes) * 0.15
            out.append((max(math.exp(-d2 / (sig * sig)), glow), None))
        return out
    if name in ('tetrahedron', 'cube', 'tesseract'):
        pts = solid_points(name, rot, t)
        sig = 0.10 + 0.2 * spread
        for s in segs:
            b = 0.0
            for px, py, w in pts:
                d2 = ((s['u'] - px) * 1.6) ** 2 + (s['v'] - py) ** 2
                b = max(b, (0.35 + 0.65 * w) * math.exp(-d2 / (sig * sig)))
            out.append((b, None))
        return out
    if name == 'chladni':
        (n1, m1), (n2, m2), k, sign = chladni_mode(t)
        for s in segs:
            x, y = s['u'], s['v']
            def plate(nn, mm):
                return abs(math.cos(nn * math.pi * x) * math.cos(mm * math.pi * y)
                           + sign * math.cos(mm * math.pi * x) * math.cos(nn * math.pi * y)) / 2.0
            v = plate(n1, m1) * (1 - k) + plate(n2, m2) * k
            out.append((_clamp(v) ** (0.6 + spread), None))
        return out
    for i, s in enumerate(segs):
        ang, r = polar(s)
        if name == 'flower':
            if r < 0.14:
                b = 0.5 + 0.5 * math.cos(2 * math.pi * t + math.pi)
            else:
                j = math.floor(((ang - rot) / (2 * math.pi) * 6) % 6)
                b = 0.5 + 0.5 * math.cos(2 * math.pi * (t - j / 6.0))
            out.append((b, None))
        elif name == 'yantra':
            if r < 0.14:                                  # the bindu
                out.append((math.exp(-(t % 1.0) / 0.25), (1.0, 0.95, 0.85)))
                continue
            up = math.sin(3 * (ang - rot)) >= 0
            wu = 0.5 + 0.5 * math.cos(math.pi * t)
            c = base[i]
            if not up:
                h, sv, vv = colorsys.rgb_to_hsv(*c)
                c = colorsys.hsv_to_rgb((h + 0.5) % 1.0, max(sv, 0.6), max(vv, 0.6))
            out.append((wu if up else 1 - wu, c))
        elif name == 'spiral':
            ph = (ang - rot) / (2 * math.pi) * 2 - math.log(r + 0.05) / math.log(PHI) * 0.25 - t
            b = 0.5 + 0.5 * math.cos(2 * math.pi * ph)
            out.append((b ** (1.0 + 2.0 * (1 - spread)), None))
        else:
            out.append((1.0, None))
    return out


def harmony(kind, base_rgb, n):
    """n colours from one base colour, by sacred numbers."""
    h, s, v = colorsys.rgb_to_hsv(*base_rgb)
    s, v = max(s, 0.55), max(v, 0.6)
    out = []
    for i in range(n):
        if kind == 'golden':
            c = colorsys.hsv_to_rgb((h + i * GOLDEN_ANGLE / 360.0) % 1.0, s, v)
        elif kind == 'triad':
            c = colorsys.hsv_to_rgb((h + (i % 3) / 3.0) % 1.0, s, v)
        elif kind == 'hexad':
            c = colorsys.hsv_to_rgb((h + (i % 6) / 6.0) % 1.0, s, v)
        elif kind == 'opposite':
            c = colorsys.hsv_to_rgb((h + (i % 2) * 0.5) % 1.0, s, v)
        elif kind == 'analogous':
            off = ((i % 5) - 2) * 25.0 / 360.0
            c = colorsys.hsv_to_rgb((h + off) % 1.0, s, v)
        else:                                             # fibonacci shades: 1, 1/phi, 1/phi^2 ...
            k = PHI ** -(i % 4)
            c = colorsys.hsv_to_rgb(h, s * (0.6 + 0.4 * k), v * (0.35 + 0.65 * k))
        out.append(c)
    return out


# Push 2 GEOMETRY mode: columns = forms, rows (bottom to top) = colour harmonies
GEO_COLUMNS = ['golden', 'flower', 'yantra', 'metatron', 'chladni', 'spiral', 'cube', 'tesseract']
GEO_ROWS = [('white light', None, (1.0, 0.86, 0.66)),
            ('golden', 'golden', (1.0, 0.0, 0.0)),
            ('triad', 'triad', (1.0, 0.25, 0.0)),
            ('hexad', 'hexad', (0.6, 0.0, 1.0)),
            ('opposite', 'opposite', (0.0, 0.35, 1.0)),
            ('warm', 'analogous', (1.0, 0.35, 0.05)),
            ('cool', 'analogous', (0.0, 0.7, 1.0)),
            ('fibonacci', 'fibonacci', (0.55, 0.0, 1.0))]


def geo_pad(note):
    """(form, row name, harmony kind, base colour) of a GEOMETRY-mode pad 36-99."""
    row, col = (note - 36) // 8, (note - 36) % 8
    name, kind, base = GEO_ROWS[row]
    return GEO_COLUMNS[col], name, kind, base
