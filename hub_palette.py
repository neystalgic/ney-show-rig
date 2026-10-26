# =============================================================================
# HUE HUB -- the room's PALETTE (colour theory)
#
# Setting 'palette' picks how the room is coloured:
#   'sync'      EVERY BULB THE SAME COLOUR, fading together round the whole rainbow (a full
#               turn every sync_period seconds, default 60). Brightness rests at sync_base
#               (default 30%) and is pushed up by the sound on one Scarlett input (sync_ch,
#               default input 2) by up to sync_boost (default +45%). The Play floor lamp
#               shows the same colour with its two rainbow neighbours either side.
#   'lava'      (default) EVERY BULB TOGETHER, walking the rainbow in order -- red, orange,
#               yellow, green, blue, indigo, violet, red ... one step a bar, gliding into the
#               next over the first half of the bar. The wall is a lava-lamp rainbow centred on
#               that same colour, and a gradient lamp (the Play floor lamp, once it has zones)
#               shows the wall's rainbow across its zones. Brightness is calm: steady, a soft
#               swell on the 1 and a little lift from the kick.
#   'spectrum'  the earlier gradient: music-driven brightness, centred on the played step a chromatic rainbow GRADIENT across the room, left to right.
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

import collections
import math

SPAN = {'quiet': 90.0, 'breakdown': 120.0, 'groove': 220.0, 'drop': 330.0}   # degrees of the wheel
MODES = ('sync', 'lava', 'spectrum', 'triad', 'degree')
LAVA_SPAN = {'quiet': 240.0, 'breakdown': 180.0, 'groove': 270.0, 'drop': 360.0}
LAVA_WALL_SPAN = 270.0           # how much rainbow the wall (and the floor lamp's zones) spreads round the room colour
# the rainbow in order, as OKLCH hues of the degree colours: red orange yellow green blue indigo violet
RAINBOW_HUES = [29.2, 39.9, 96.1, 142.9, 263.2, 276.6, 303.5]


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
        m = self.hub.state['settings'].get('palette', 'lava')
        return m if m in MODES else 'lava'

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

    def lava_hue(self, beats):
        """The whole room's colour: one step of the rainbow per bar (red, orange, yellow, green,
        blue, indigo, violet, red ...), gliding into the next over the first half of the bar."""
        bar = beats / 4.0
        step = math.floor(bar)
        f = bar - step
        g = min(1.0, f / 0.5)
        g = g * g * (3 - 2 * g)
        a = RAINBOW_HUES[int(step) % 7]
        b = RAINBOW_HUES[(int(step) + 1) % 7]
        return (a + ((b - a) % 360.0) * g) % 360.0, f

    def render_lava(self, cols, beats, now, dt, section='groove', kick=0.0):
        segs = self.hub.rig.segs
        n = len(segs)
        if n == 0:
            return cols
        live = self.hub.live
        hue, f = self.lava_hue(beats)
        swell = 0.5 + 0.5 * math.cos(2 * math.pi * f)      # soft breath, fullest on the 1
        master = max(0.0, min(1.0, live.get('master', 1.0)))
        punch = max(0.0, min(1.0, live.get('a_amt', 0.7)))
        v = master * (0.74 + 0.14 * swell + 0.12 * kick * punch)
        out = []
        for i, c in enumerate(cols):
            sg = segs[i]
            k = sg.get('of', 1)
            if k > 1:                                       # a gradient lamp: the wall's rainbow, zone by zone
                h = hue + ((sg.get('index', 0) + 0.5) / k - 0.5) * LAVA_WALL_SPAN
            else:                                           # every bulb together: the room's colour
                h = hue
            out.append(tuple(x * v for x in vivid(h % 360.0)))
        return out

    def sync_hue(self, now):
        """The whole room's colour. With sync_from / sync_to (OKLCH hue degrees) it sways back and
        forth inside that range (e.g. 255 -> 310 = deep blue to deep purple), otherwise the full rainbow."""
        st = self.hub.state['settings']
        period = max(5.0, float(st.get('sync_period', 60.0)))
        lo, hi = st.get('sync_from'), st.get('sync_to')
        if lo is None or hi is None:
            return ((now / period) * 360.0) % 360.0
        ph = (now / period) % 1.0
        tri = 0.5 - 0.5 * math.cos(2 * math.pi * ph)        # a smooth sway: lo -> hi -> lo each period
        return (float(lo) + ((float(hi) - float(lo)) % 360.0) * tri) % 360.0

    def sync_colour(self, now, offset=0.0):
        """sync_scheme 'deep' = deep blues and purples swaying slowly; otherwise the hue from sync_hue."""
        st = self.hub.state['settings']
        if st.get('sync_scheme') == 'deep':
            period = max(5.0, float(st.get('sync_period', 60.0)))
            tri = 0.5 - 0.5 * math.cos(2 * math.pi * ((now / period) % 1.0))
            return deep_colour(tri + offset)
        return vivid((self.sync_hue(now) + offset * 360.0) % 360.0)

    def sync_spread(self):
        st = self.hub.state['settings']
        lo, hi = st.get('sync_from'), st.get('sync_to')
        return 60.0 if lo is None or hi is None else min(60.0, ((float(hi) - float(lo)) % 360.0) * 0.5)

    def render_sync(self, cols, now, dt, rms):
        """All bulbs one colour, fading round the rainbow; brightness = rest + the input's loudness."""
        st = self.hub.state['settings']
        db = 20.0 * math.log10(max(rms, 1e-6))
        lo_db = float(st.get('sync_floor_db', -48.0))           # at or below this = silence = dark
        hi_db = float(st.get('sync_top_db', -12.0))             # at or above this = full light
        lvl = max(0.0, min(1.0, (db - lo_db) / max(1.0, hi_db - lo_db)))
        env = getattr(self, 'sync_env', 0.0)
        att = max(0.01, float(st.get('sync_attack', 0.7)))      # seconds to swell up (slow: voices don't flash)
        rel = max(0.01, float(st.get('sync_release', 1.6)))     # seconds to sink back
        k = 1.0 - math.exp(-dt / (att if lvl > env else rel))
        env += (lvl - env) * k
        if lvl <= 0.0 and env < 0.01:
            env = 0.0                                          # true silence = truly dark
        self.sync_env = env
        base = max(0.0, min(1.0, float(st.get('sync_base', 0.30))))
        boost = max(0.0, min(1.0, float(st.get('sync_boost', 0.45))))
        v = max(0.0, min(1.0, base + boost * env))
        self.sync_v = v
        c = self.sync_colour(now)
        self.sync_c = c
        # SYNC BUFFER: the streamed bulbs wait sync_delay seconds so they land together with the Play
        # floor lamp, which is driven outside the stream and needs that long to catch up.
        d = max(0.0, float(st.get('sync_delay', 0.3)))
        hist = getattr(self, 'sync_hist', None)
        if hist is None:
            hist = self.sync_hist = collections.deque()
        hist.append((now, v, c))
        while len(hist) > 1 and hist[1][0] <= now - d:
            hist.popleft()
        _, vd, cd = hist[0]
        return [tuple(x * vd for x in cd) for _ in cols]

DEEP = [(0.0, 0.10, 1.0), (0.22, 0.0, 1.0), (0.48, 0.0, 1.0), (0.62, 0.0, 0.85)]   # deep blue -> indigo -> purple -> plum


def deep_colour(t):
    """t 0..1 along deep blue -> indigo -> purple -> plum (all fully saturated: nothing washes out)."""
    t = max(0.0, min(1.0, t)) * (len(DEEP) - 1)
    i = min(len(DEEP) - 2, int(t))
    f = t - i
    f = f * f * (3 - 2 * f)
    return tuple(a + (b - a) * f for a, b in zip(DEEP[i], DEEP[i + 1]))
