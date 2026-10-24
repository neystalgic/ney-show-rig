# =============================================================================
# HUE HUB -- the room's PALETTE (colour theory)
#
# Setting 'palette' picks how the room is coloured:
#   'spectrum'  (default) a chromatic rainbow GRADIENT across the room, left to right.
#               - hues are spaced evenly to the EYE (OKLCH, a perceptual colour space),
#                 not evenly in numbers, so no colour hogs the room and none gets skipped
#               - blends travel round the colour wheel (never through grey or brown)
#               - the music steers it: the step you play is the centre of the gradient
#                 (1 = red, 2 = orange ... the same degree colours), and the song section
#                 sets how wide it spreads: quiet / breakdown = analogous (neighbouring
#                 hues, calm), groove = wide, drop = the whole rainbow
#               - with no notes it drifts slowly round the wheel, one turn every 16 bars
#   'triad'     the step's colour plus its third and fifth (1 = red + yellow + blue)
#   'degree'    the original rule: the whole room is the step's colour (1 red, 2 orange ...)
# Brightness always stays with the music; this only decides the colours.
# =============================================================================

import math

SPAN = {'quiet': 90.0, 'breakdown': 120.0, 'groove': 220.0, 'drop': 330.0}   # degrees of the wheel
MODES = ('spectrum', 'triad', 'degree')


# ---- OKLab / OKLCH (Bjorn Ottosson's perceptual colour space) ----
def _to_lin(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _to_srgb(v):
    v = max(0.0, v)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def rgb_to_oklch(c):
    r, g, b = (_to_lin(max(0.0, min(1.0, x))) for x in c)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360.0


def oklch_to_rgb_lin(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


_HUE_CACHE = {}


def vivid(h):
    """The most vivid colour of hue h (OKLCH degrees) the screen / bulbs can show, full strength."""
    k = int(round(h % 360.0)) % 360
    if k in _HUE_CACHE:
        return _HUE_CACHE[k]
    best = (1.0, 1.0, 1.0)
    for L in (0.55, 0.62, 0.7, 0.78, 0.86, 0.93):          # find the strongest in-gamut chroma at this hue
        lo, hi = 0.0, 0.4
        for _ in range(18):
            mid = (lo + hi) / 2
            rgb = oklch_to_rgb_lin(L, mid, k)
            if min(rgb) >= -1e-4 and max(rgb) <= 1.0001:
                lo = mid
            else:
                hi = mid
        rgb = oklch_to_rgb_lin(L, lo, k)
        c = tuple(_to_srgb(x) for x in rgb)
        m = max(c) or 1.0
        c = tuple(max(0.0, min(1.0, x / m)) for x in c)
        if best == (1.0, 1.0, 1.0) or (max(c) - min(c)) > (max(best) - min(best)) + 1e-3:
            best = c
    _HUE_CACHE[k] = best
    return best


def _angdiff(a, b):
    return (b - a + 180.0) % 360.0 - 180.0


class Palette:
    def __init__(self, hub):
        self.hub = hub
        self.centre = None        # where the gradient is centred (OKLCH hue)
        self.span = 180.0
        self.last_note_hue = None
        self.last_note_t = -100.0

    def mode(self):
        m = self.hub.state['settings'].get('palette', 'spectrum')
        return m if m in MODES else 'spectrum'

    def note(self, rgb, now):
        """A played step's colour -> the gradient's centre."""
        self.last_note_hue = rgb_to_oklch(rgb)[2]
        self.last_note_t = now

    def render(self, cols, beats, now, dt, section='groove'):
        segs = self.hub.rig.segs
        n = len(segs)
        if n == 0:
            return cols
        drift = (beats / 64.0) * 360.0                       # a turn every 16 bars when nobody plays
        playing = self.last_note_hue is not None and now - self.last_note_t < 8.0
        want = (self.last_note_hue if playing else 29.0) + (0.0 if playing else drift)   # 29 = OKLCH red
        if self.centre is None:
            self.centre = want
        k = 1.0 - math.exp(-dt / (0.25 if playing else 1.0))   # glide round the wheel, never jump
        self.centre = (self.centre + _angdiff(self.centre, want) * k) % 360.0
        ws = SPAN.get(section, 220.0)
        self.span += (ws - self.span) * (1.0 - math.exp(-dt / 2.0))
        ords = [s.get('ord', i) for i, s in enumerate(segs)]
        N = max(1, n - 1)
        out = []
        for i, c in enumerate(cols):
            pos = ords[i] / N - 0.5 if n > 1 else 0.0          # -0.5 (left of the room) .. +0.5 (right)
            hue = (self.centre + pos * self.span) % 360.0
            v = max(0.0, min(1.0, max(c)))
            out.append(tuple(x * v for x in vivid(hue)))
        return out
