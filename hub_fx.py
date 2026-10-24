# =============================================================================
# HUE HUB -- the FREESTYLE RACK: eight light effects for Push 2's top knobs
#
# Each knob is an effect you turn IN: 0 = off, more = more. They stack, they all
# run on the beat clock (the Digitakt / Live tempo), and everything still ends in
# the flicker protection, so no knob can flash faster than the Flicker Guard.
#
#   1 STROBE   white flashes on the grid: every bar > half bar > every beat
#   2 PRISM    a rainbow laid across the room that rolls round on the beat
#   3 ORBIT    a comet runs round the room. Centre = off, right = clockwise,
#              left = counter-clockwise; further out = faster (on the grid)
#   4 BREATHE  the room breathes in and out over two bars; past halfway it
#              becomes a wave that rolls from lamp to lamp
#   5 PUMP     sidechain: every beat ducks the lamps and they swell back
#   6 ECHO     every kick fires a pulse that bounces lamp to lamp, like a delay
#   7 CHORD    the lamps split into the notes of the chord -- root, third, fifth,
#              seventh, each in its own degree colour (what you hold, or the
#              chord the audio brain hears)
#   8 SPARKLE  hats throw glitter onto random lamps and gradient zones
#
# Hold SHIFT on Push to get the classic knobs back (brightness, effect, speed ...).
# =============================================================================

import math
import random
import time

try:
    import hub_livemidi as hl
except Exception:
    hl = None
try:
    import hub_brain
except Exception:
    hub_brain = None

FX_KEYS = ('fx_strobe', 'fx_prism', 'fx_orbit', 'fx_breathe', 'fx_pump', 'fx_echo', 'fx_chord', 'fx_sparkle')
FX_DEFAULTS = dict(fx_strobe=0.0, fx_prism=0.0, fx_orbit=0.5, fx_breathe=0.0, fx_pump=0.0, fx_echo=0.0,
                   fx_chord=0.0, fx_sparkle=0.0)
WHITE = (1.0, 1.0, 1.0)
RAINBOW = [(1.0, 0.0, 0.0), (1.0, 0.38, 0.0), (1.0, 0.85, 0.0), (0.0, 1.0, 0.1), (0.0, 0.3, 1.0),
           (0.29, 0.0, 1.0), (0.62, 0.0, 1.0)]


def _cl(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _hue(c):
    """The colour of a lamp at full brightness (white if it's dark)."""
    m = max(c)
    return tuple(x / m for x in c) if m > 0.03 else (0.7, 0.7, 0.7)


def _rainbow(x):
    n = len(RAINBOW)
    i = int(math.floor(x)) % n
    f = x - math.floor(x)
    return _mix(RAINBOW[i], RAINBOW[(i + 1) % n], f * f * (3 - 2 * f))


def strobe_division(amt, bps, guard):
    """Beats between flashes for the knob position, halved until it's within the guard."""
    if amt < 0.02:
        return None
    div = 4.0 if amt < 0.34 else 2.0 if amt < 0.67 else 1.0
    while bps / div > guard * 0.95 and div < 16:
        div *= 2.0
    return div


def orbit_rate(v, bps, guard):
    """Knob 0-1 (0.5 = off) -> (direction, turns of the room per beat)."""
    off = v - 0.5
    if abs(off) < 0.04:
        return 0, 0.0
    mag = (abs(off) - 0.04) / 0.46
    rate = [0.125, 0.25, 0.5, 1.0][min(3, int(mag * 4))]
    while rate * bps > guard * 0.95 and rate > 1 / 64:
        rate /= 2.0
    return (1 if off > 0 else -1), rate


class LightFX:
    def __init__(self, hub):
        self.hub = hub
        self.k_prev = 0.0
        self.h_prev = 0.0
        self.echoes = []          # wall time of each kick that fired an echo
        self.sparks = {}          # segment index -> (start time, strength)
        self.last_spark = -1

    def amounts(self):
        L = self.hub.live
        return {k: float(L.get(k, FX_DEFAULTS[k])) for k in FX_KEYS}

    def label(self, key, v):
        """What the knob is doing, in words (shown on the desk / Push messages)."""
        tempo = float(self.hub.live.get('tempo', 120.0))
        g = float(self.hub.live.get('guard', 2.0))
        if key == 'fx_strobe':
            d = strobe_division(v, tempo / 60.0, g)
            return 'Strobe off' if d is None else 'Strobe every %s' % (
                {4.0: 'bar', 2.0: 'half bar', 1.0: 'beat'}.get(d, '%g beats' % d))
        if key == 'fx_orbit':
            s, r = orbit_rate(v, tempo / 60.0, g)
            return 'Orbit off' if s == 0 else 'Orbit %s, a lap every %g beats' % (
                'clockwise' if s > 0 else 'counter-clockwise', 1.0 / r)
        names = dict(fx_prism='Prism', fx_breathe='Breathe', fx_pump='Pump', fx_echo='Echo',
                      fx_chord='Chord', fx_sparkle='Sparkle')
        return '%s %d%%' % (names.get(key, key), round(v * 100))

    # ---- the chord the room shows: what you hold, else what the brain hears ----
    def chord_colours(self):
        if hl is None:
            return []
        st = self.hub.state['settings']
        root, scale = int(st.get('deg_root', 0) or 0), str(st.get('deg_scale', 'minor') or 'minor')
        pcs = []
        lm = getattr(self.hub, 'ableton', None)
        if lm is not None:
            notes = sorted({n for (ch, n) in list(lm.held.keys()) if ch not in (15, getattr(hl, 'HEARD_CH', 1))})
            pcs = []
            for n in notes:
                if n % 12 not in pcs:
                    pcs.append(n % 12)
        if len(pcs) < 2 and hub_brain is not None and getattr(self.hub, 'audio', None) is not None:
            br = getattr(self.hub.audio, 'brain', None)
            if br is not None:
                r, minor = hub_brain.parse_chord(br.state.get('stable'))
                if r is not None:
                    pcs = [r, (r + (3 if minor else 4)) % 12, (r + 7) % 12]
        out = []
        for pc in pcs[:4]:
            d, half = hl.degree_of(pc + 60, root, scale)
            d %= 7
            out.append(hl.DEG_RGB[d] if half == 0.0 else _mix(hl.DEG_RGB[d], hl.DEG_RGB[(d + 1) % 7], 0.5))
        return out

    def render(self, cols, beats, tempo, now):
        a = self.amounts()
        on = {k: v for k, v in a.items() if (abs(v - 0.5) >= 0.04 if k == 'fx_orbit' else v >= 0.02)}
        env = getattr(getattr(self.hub, 'audioshow', None), 'env', None) or {}
        kick, hats = float(env.get('kick', 0.0)), float(env.get('hats', 0.0))
        k_edge = kick > 0.55 >= self.k_prev
        h_edge = hats > 0.5 >= self.h_prev
        self.k_prev, self.h_prev = kick, hats
        if not on:
            self.echoes, self.sparks = [], {}
            return cols
        segs = self.hub.rig.segs
        n = len(segs)
        if n == 0:
            return cols
        N = float(n)
        tempo = max(40.0, float(tempo))
        bps = tempo / 60.0
        guard = float(self.hub.live.get('guard', 2.0))
        ords = [s.get('ord', i) for i, s in enumerate(segs)]
        out = [tuple(c) for c in cols]

        # ---- colour layers ----
        amt = on.get('fx_chord', 0.0)
        if amt:
            tones = self.chord_colours()
            if tones:
                out = [_mix(c, tuple(x * max(max(c), 0.25 * amt) for x in tones[ords[i] % len(tones)]), amt)
                       for i, c in enumerate(out)]
        amt = on.get('fx_prism', 0.0)
        if amt:
            roll = beats / 8.0 * 7.0                      # once round the rainbow every two bars
            out = [_mix(c, tuple(x * max(max(c), 0.3 * amt) for x in _rainbow(roll + ords[i] * 7.0 / N)), amt)
                   for i, c in enumerate(out)]

        # ---- movement / level layers ----
        if 'fx_orbit' in on:
            sgn, rate = orbit_rate(a['fx_orbit'], bps, guard)
            if sgn:
                depth = min(1.0, abs(a['fx_orbit'] - 0.5) * 2.4)
                head = (beats * rate * N) % N
                res = []
                for i, c in enumerate(out):
                    d = (head - ords[i]) % N if sgn > 0 else (ords[i] - head) % N
                    b = math.exp(-d / 1.1)
                    lvl = max(c)
                    res.append(tuple(x * (lvl * (1 - depth) + max(lvl, 0.55) * depth * b) for x in _hue(c)))
                out = res
        amt = on.get('fx_breathe', 0.0)
        if amt:
            wave = max(0.0, amt - 0.5) * 2.0
            res = []
            for i, c in enumerate(out):
                ph = (beats / 8.0 - wave * 0.5 * ords[i] / N) % 1.0
                s = 0.5 + 0.5 * math.cos(2 * math.pi * ph)        # full on the downbeat of every 2 bars
                res.append(tuple(x * (1 - min(1.0, amt * 1.4) * 0.92 * (1 - s)) for x in c))
            out = res
        amt = on.get('fx_pump', 0.0)
        if amt:
            ph = beats % 1.0
            duck = math.exp(-ph / 0.28)                    # dip on the beat, swell back before the next
            m = 1 - amt * 0.92 * duck
            out = [tuple(x * m for x in c) for c in out]

        # ---- hits on top ----
        amt = on.get('fx_echo', 0.0)
        if amt:
            if k_edge and (not self.echoes or now - self.echoes[-1] > 0.2):
                self.echoes.append(now)
            hop = 0.5 / bps                                 # an eighth note per lamp
            fb = 0.35 + 0.6 * amt
            hops = int(N * (1 + 2 * amt))
            self.echoes = [t for t in self.echoes if now - t < hop * (hops + 2)]
            add = [0.0] * n
            for t0 in self.echoes:
                h = int((now - t0) / hop)
                if h < hops:
                    tgt = h % n
                    k = (fb ** h) * math.exp(-((now - t0) - h * hop) / 0.16)
                    for i in range(n):
                        if ords[i] == tgt:
                            add[i] = max(add[i], k)
            out = [tuple(_cl(x + (y * 0.85 + 0.15) * add[i] * amt) for x, y in zip(c, _hue(c)))
                   for i, c in enumerate(out)]
        else:
            self.echoes = []
        amt = on.get('fx_sparkle', 0.0)
        if amt:
            if h_edge:
                for _ in range(1 + int(amt * 2.2)):
                    j = random.randrange(n)
                    if n > 1 and j == self.last_spark:
                        j = (j + 1 + random.randrange(n - 1)) % n
                    self.last_spark = j
                    self.sparks[j] = (now, 0.55 + 0.45 * amt)
            res = []
            for i, c in enumerate(out):
                t0, s = self.sparks.get(i, (-10.0, 0.0))
                k = s * math.exp(-(now - t0) / 0.14)
                res.append(tuple(_cl(x + (0.6 * y + 0.4) * k) for x, y in zip(c, _hue(c))) if k > 0.01 else c)
            out = res
        else:
            self.sparks = {}

        # ---- the strobe goes last: it owns the room while it's in ----
        amt = on.get('fx_strobe', 0.0)
        if amt:
            div = strobe_division(amt, bps, guard)
            since = ((beats % div) / bps) if div else 9.0
            if since < 0.09:
                out = [WHITE for _ in out]
            else:
                dim = 1 - min(0.9, 0.35 + amt * 0.6)
                out = [tuple(x * dim for x in c) for c in out]
        return [tuple(_cl(x) for x in c) for c in out]
