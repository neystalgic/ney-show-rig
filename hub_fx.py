# =============================================================================
# HUE HUB -- the FREESTYLE RACK: eight light effects for Push 2's top knobs
#
# Each knob sits on its own musical grid -- the knob only sets HOW MUCH, never how
# fast -- so everything lands on the beat. 0 (all the way left) = off. They stack,
# and everything still ends in the flicker protection.
#
#   1 PUNCH    1 bar      the 1 of every bar slams the room up in its own colour, then it
#                         sinks back (the knob = how hard). Never white.
#   2 PRISM    1/2 note   a rainbow across the room that steps round every half note
#   3 ORBIT    1/4 note   a comet hops one lamp every beat. Centre = off,
#                         right = clockwise, left = counter-clockwise (further = darker room)
#   4 SPARKLE  1/8 note   glitter: a random lamp lights on every eighth note
#   5 PUMP     1/4 note   sidechain: every beat ducks the lamps and they swell back
#   6 ECHO     1/2 + 1/8  on every half note a pulse bounces lamp to lamp in eighths
#   7 BREATHE  2 bars     the room breathes in and out; past halfway it becomes a wave
#   8 CHORD    the chord  the lamps split into the chord's notes, each in its degree colour
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
RAINBOW = [(1.0, 0.0, 0.0), (1.0, 0.38, 0.0), (1.0, 0.85, 0.0), (0.0, 1.0, 0.1), (0.0, 0.3, 1.0),
           (0.29, 0.0, 1.0), (0.62, 0.0, 1.0)]


def _cl(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


ROOM = [(1.0, 0.0, 0.0)]           # the room's colour right now (for lamps that are dark)


def _hue(c):
    """The colour of a lamp at full brightness (the room's colour if it's dark -- never white)."""
    m = max(c)
    return tuple(x / m for x in c) if m > 0.03 else ROOM[0]


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
        self.k_prev = None        # the last half note that fired an echo
        self.h_prev = None        # the last eighth note that threw sparkle
        self.echoes = []          # beat each echo set off on
        self.sparks = {}          # segment index -> (start time, strength)
        self.last_spark = -1

    def amounts(self):
        L = self.hub.live
        return {k: float(L.get(k, FX_DEFAULTS[k])) for k in FX_KEYS}

    def label(self, key, v):
        """What the knob is doing, in words."""
        if key == 'fx_orbit':
            if abs(v - 0.5) < 0.04:
                return 'Orbit off'
            return 'Orbit %s %d%%' % ('clockwise' if v > 0.5 else 'counter-clockwise', round(abs(v - 0.5) * 200))
        names = dict(fx_strobe='Punch (bar)', fx_prism='Prism (1/2)', fx_sparkle='Sparkle (1/8)',
                     fx_pump='Pump (1/4)', fx_echo='Echo (1/2 + 1/8)', fx_breathe='Breathe (2 bars)',
                     fx_chord='Chord')
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
        lit = [c for c in out if max(c) > 0.03]
        if lit:                                           # the room's colour = its brightest lamp's colour
            b = max(lit, key=max)
            ROOM[0] = tuple(x / max(b) for x in b)

        # ---- colour layers ----
        amt = on.get('fx_chord', 0.0)
        if amt:
            tones = self.chord_colours()
            if tones:
                out = [_mix(c, tuple(x * max(max(c), 0.25 * amt) for x in tones[ords[i] % len(tones)]), amt)
                       for i, c in enumerate(out)]
        amt = on.get('fx_prism', 0.0)
        if amt:
            step = beats / 2.0                            # one colour step every half note,
            j = math.floor(step)                          # a quick slide onto the beat
            roll = j + min(1.0, (step - j) / 0.12)
            out = [_mix(c, tuple(x * max(max(c), 0.3 * amt) for x in _rainbow(roll + ords[i] * 7.0 / N)), amt)
                   for i, c in enumerate(out)]

        # ---- movement / level layers ----
        if 'fx_orbit' in on:
            off = a['fx_orbit'] - 0.5
            sgn = 1 if off > 0 else -1
            depth = min(1.0, (abs(off) - 0.04) / 0.46 * 1.1)
            head = (beats % N)                            # one lamp per beat (quarter notes)
            res = []
            for i, c in enumerate(out):
                d = (head - ords[i]) % N if sgn > 0 else (ords[i] - (N - head)) % N
                b = math.exp(-d / 0.7)
                lvl = max(c)
                res.append(tuple(x * (lvl * (1 - depth) + max(lvl, 0.55) * depth * b) for x in _hue(c)))
            out = res
        amt = on.get('fx_breathe', 0.0)
        if amt:
            wave = max(0.0, amt - 0.5) * 2.0
            res = []
            for i, c in enumerate(out):
                ph = (beats / 8.0 - wave * 0.5 * ords[i] / N) % 1.0
                s_ = 0.5 + 0.5 * math.cos(2 * math.pi * ph)       # full on the downbeat of every 2 bars
                res.append(tuple(x * (1 - min(1.0, amt * 1.4) * 0.92 * (1 - s_)) for x in c))
            out = res
        amt = on.get('fx_pump', 0.0)
        if amt:
            ph = beats % 1.0
            duck = math.exp(-ph / 0.28)                    # dip on the beat, swell back before the next
            m = 1 - amt * 0.92 * duck
            out = [tuple(x * m for x in c) for c in out]

        # ---- hits on top, all on the grid ----
        amt = on.get('fx_echo', 0.0)
        if amt:
            hb = math.floor(beats / 2.0)                   # every half note a new pulse sets off
            if hb != self.k_prev:
                self.k_prev = hb
                self.echoes.append(hb * 2.0)
            fb = 0.35 + 0.6 * amt
            hops = int(N * (1 + 2 * amt))
            self.echoes = [b0 for b0 in self.echoes if beats - b0 < 0.5 * (hops + 2)]
            add = [0.0] * n
            for b0 in self.echoes:
                h = int((beats - b0) / 0.5)                # an eighth note per lamp
                if 0 <= h < hops:
                    k = (fb ** h) * math.exp(-((beats - b0) - h * 0.5) / bps / 0.16)
                    for i in range(n):
                        if ords[i] == h % n:
                            add[i] = max(add[i], k)
            out = [tuple(_cl(x + y * add[i] * amt) for x, y in zip(c, _hue(c)))
                   for i, c in enumerate(out)]
        else:
            self.echoes = []
        amt = on.get('fx_sparkle', 0.0)
        if amt:
            e8 = math.floor(beats * 2.0)                   # every eighth note
            if e8 != self.h_prev:
                self.h_prev = e8
                for _ in range(1 + int(amt * 1.6)):
                    j = random.randrange(n)
                    if n > 1 and j == self.last_spark:
                        j = (j + 1 + random.randrange(n - 1)) % n
                    self.last_spark = j
                    self.sparks[j] = (now, 0.4 + 0.6 * amt)
            res = []
            for i, c in enumerate(out):
                t0, s_ = self.sparks.get(i, (-10.0, 0.0))
                k = s_ * math.exp(-(now - t0) / 0.14)
                res.append(tuple(_cl(x + y * k) for x, y in zip(c, _hue(c))) if k > 0.01 else c)
            out = res
        else:
            self.sparks = {}

        # ---- the bar punch goes last ----
        amt = on.get('fx_strobe', 0.0)
        if amt:
            ph = (beats % 4.0) / 4.0                       # the 1 of every bar: up to full, in its colour,
            env_ = math.exp(-ph / 0.18)                    # then it sinks back over the bar
            res = []
            for c in out:
                hc = _hue(c)
                lvl = max(c)
                top = lvl + (1.0 - lvl) * env_            # the punch, in the lamp's own colour
                low = lvl * (1 - 0.55 * amt)               # the rest of the bar sits lower, so it hits
                res.append(tuple(x * (low + (top - low) * env_ * amt / max(amt, 1e-6)) for x in hc))
            out = [_mix(c, r_, amt) for c, r_ in zip(out, res)]
        return [tuple(_cl(x) for x in c) for c in out]
