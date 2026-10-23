# =============================================================================
# HUE RIG -- engine (lives in the Execute DAT "engine" inside hue_rig)
#
# Every frame:
#   1. works out the "look" (Mode, colours, timing, each lamp's role)
#   2. gives every lamp a colour, cross-fading when a cue is fired
#   3. smooths it, then the flicker protection makes sure no lamp -- and not
#      the room as a whole -- flashes faster than the Flicker Guard allows
#   4. shows it on the preview and sends it to the lights
# =============================================================================

import colorsys
import json
import math
import os
import socket
import ssl
import threading
import time
import urllib.request

import numpy as np

_S = {'lamps': None, 'lamps_key': None, 'prev': None, 'sock': None, 'direct': None,
      'last_t': None, 'lim': None, 'held': 0.0, 'fade': None, 'cues_key': None, 'cues': [],
      'ppal': None, 'energy': None, 'slow': None}

FEEL = [((1.00, 0.62, 0.30), (0.85, 0.50, 0.55), (1.00, 0.88, 0.70)),   # nostalgia
        ((1.00, 0.80, 0.45), (0.40, 0.82, 0.80), (0.75, 0.95, 1.00)),   # hope
        ((1.00, 0.25, 0.75), (0.55, 0.30, 1.00), (1.00, 0.80, 0.30))]   # triumph

ROLES = ['mode', 'wash', 'beat', 'fixed', 'off']

# the rainbow, tuned for Hue bulbs (blue, indigo and violet pulled apart so you can tell them apart)
RAINBOW = [('red', (1.00, 0.00, 0.00)), ('orange', (1.00, 0.38, 0.00)), ('yellow', (1.00, 0.85, 0.00)),
           ('green', (0.00, 1.00, 0.05)), ('blue', (0.00, 0.30, 1.00)), ('indigo', (0.28, 0.00, 1.00)),
           ('violet', (0.70, 0.00, 1.00))]


def rainbow_at(x):
    """Colour at position x along the rainbow (0 = red, 1 = orange, ... wraps after violet).
    Between two colours it blends round the colour wheel for the last quarter step."""
    n = len(RAINBOW)
    i = int(math.floor(x)) % n
    f = x - math.floor(x)
    a, b = RAINBOW[i][1], RAINBOW[(i + 1) % n][1]
    k = max(0.0, (f - 0.75) / 0.25)
    return hsv_mix(a, b, k * k * (3 - 2 * k))


def rainbow_show(t, rank, n):
    """A looping rainbow light show on the clock t (1 step = 1 beat at Rate 1):
       part 1 (16 steps)  the spectrum spread across the room, scrolling one lamp per step
       part 2 (16 steps)  the whole room one colour, next colour every 2 steps, soft pulse
       part 3 (16 steps)  each colour sweeps across the room, left to right
    """
    part = int(math.floor(t / 16.0)) % 3
    if part == 0:
        return rainbow_at(t + rank * 7.0 / max(n, 7)), 'spectrum'
    if part == 1:
        c = rainbow_at(t / 2.0)
        pulse = 0.8 + 0.2 * math.exp(-((t / 2.0) % 1.0) / 0.25)   # a soft swell as each colour lands
        return scale(c, pulse), 'together'
    step = t / 2.0                                   # one colour per sweep
    i = int(math.floor(step))
    head = step - i                                  # 0..1 across the room
    pos = (rank + 0.5) / max(n, 1)
    new, old = RAINBOW[i % 7][1], RAINBOW[(i - 1) % 7][1]
    edge = max(0.0, min(1.0, (head - pos) / 0.18 + 0.5))   # the colour edge passes this lamp
    return hsv_mix(old, new, edge * edge * (3 - 2 * edge)), 'sweep'
CUE_PAGES = ('Look', 'Lamps')
CUE_SKIP = {'Kick', 'Flickerguard', 'Palettepath', 'Blackout', 'Clockpath'}   # never stored in a cue


def _skip_in_cue(name):
    # lamp positions describe the room, not the look
    return name in CUE_SKIP or (name[:1] == 'L' and name[-4:-1] == 'pos')


# ---- flicker protection (identical copy in hue_engine.py and hue_stream.py) ----------
class FlashLimiter:
    """Lets the lamps react instantly -- a drop, a kick, a scene change --
    but never lets them FLASH faster than `max_flashes` times a second
    (capped at 3, the photosensitive-epilepsy limit).

    A flash is a big change one way and then back again (dark-bright-dark,
    or red-blue-red). For every lamp its red, green, blue and brightness --
    and the brightness of the room as a whole -- may only turn round like
    that once every 1 / (2 x max_flashes) seconds, so flashes can never
    bunch up. Changes that keep going the same way (fades, a single hit, a
    scene change) are always free. Something that isn't allowed to turn
    round yet simply holds close to where it is for a moment."""
    THR = 0.08                                   # what counts as a big change (linear light)

    def __init__(self, max_flashes=2.0):
        self.set_rate(max_flashes)
        self.n = -1
        self.held = False

    def set_rate(self, max_flashes):
        self.f = max(0.5, min(3.0, float(max_flashes)))
        self.gap = 1.0 / (2.0 * self.f) + 0.03   # shortest time between two turn-rounds

    @staticmethod
    def lin(v):
        return max(0.0, min(1.0, v)) ** 2.2

    @staticmethod
    def unlin(v):
        return max(0.0, min(1.0, v)) ** (1 / 2.2)

    @staticmethod
    def lum(c):
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    @classmethod
    def sig(cls, c):                             # what is watched per lamp: R, G, B, brightness
        return (c[0], c[1], c[2], cls.lum(c))

    def _reset(self, lt):
        self.n = len(lt)
        self.y = [list(c) for c in lt]
        self.trk = [[{'ext': v, 'dir': 0, 'last': -1e9} for v in self.sig(c)] for c in lt]
        r = sum(self.lum(c) for c in lt) / max(1, self.n)
        self.room = {'ext': r, 'dir': 0, 'last': -1e9}

    @classmethod
    def _rev(cls, st, x):
        """None, or (new_dir, bound) if moving a watched value to x turns it round."""
        if st['dir'] >= 0 and x < st['ext'] - cls.THR:
            return -1, st['ext'] - cls.THR * 0.98
        if st['dir'] <= 0 and x > st['ext'] + cls.THR:
            return 1, st['ext'] + cls.THR * 0.98
        return None

    @classmethod
    def _book(cls, st, x, now):
        """Update a watched value. A turn counts as 'still happening' until it
        has swung twice the threshold, so whatever size of change someone
        measures, turn-rounds stay at least `gap` apart."""
        r = cls._rev(st, x)
        if r is not None:
            st['pext'], st['dir'], st['ext'], st['last'] = st['ext'], r[0], x, now
            return True
        moved = (st['dir'] > 0 and x > st['ext']) or (st['dir'] < 0 and x < st['ext'])
        if moved:
            st['ext'] = x
            if abs(x - st.get('pext', x)) < 2 * cls.THR:
                st['last'] = now
        return False

    @staticmethod
    def _limit(p, t, bound):
        """largest share (0..1) of the way from p to t that stays inside bound"""
        if abs(t - p) < 1e-12:
            return 1.0
        return max(0.0, min(1.0, (bound - p) / (t - p)))

    def step(self, targets, now):
        lt = [[self.lin(v) for v in c[:3]] for c in targets]
        if len(lt) != self.n:
            self._reset(lt)
            return [tuple(self.unlin(v) for v in c) for c in lt]

        # 1. each lamp: may it turn round now? if not, go only part of the way
        self.held = False
        cand = []
        for i, (p, t) in enumerate(zip(self.y, lt)):
            a = 1.0
            for st, ps, ts in zip(self.trk[i], self.sig(p), self.sig(t)):
                if now - st['last'] >= self.gap:
                    continue
                r = self._rev(st, ts)
                if r is not None:
                    a = min(a, self._limit(ps, ts, r[1]))
            self.held = self.held or a < 0.999
            cand.append([x + (y - x) * a for x, y in zip(p, t)])

        # 2. the room as a whole (all lamps added up): same rule
        a = 1.0
        if now - self.room['last'] < self.gap:
            rp = sum(self.lum(c) for c in self.y) / self.n
            rt = sum(self.lum(c) for c in cand) / self.n
            r = self._rev(self.room, rt)
            if r is not None:
                a = self._limit(rp, rt, r[1])
                self.held = self.held or a < 0.999
        out = [[x + (y - x) * a for x, y in zip(p, c)] for p, c in zip(self.y, cand)]

        # 3. book-keeping with what the lamps really show
        for i, c in enumerate(out):
            for st, v in zip(self.trk[i], self.sig(c)):
                self._book(st, v, now)
        self._book(self.room, sum(self.lum(c) for c in out) / self.n, now)
        self.y = out
        return [tuple(self.unlin(v) for v in c) for c in out]
# ---- end of flicker protection ---------------------------------------------------------

# ---- lamps ------------------------------------------------------------------------
def read_lamps(path, virtual_count):
    """[{'name','channel','v1','u','v'}] from the helper's hue_lamps.csv, or
    evenly spaced virtual lamps when there's no file yet."""
    lamps = []
    if path and os.path.exists(path):
        with open(path) as f:
            rows = [l.rstrip('\n').split('\t') for l in f if l.strip()]
        for r in rows[1:]:
            try:
                lamps.append(dict(channel=int(r[0]), name=r[1], v1=r[2],
                                  u=float(r[3]), v=float(r[4])))
            except (ValueError, IndexError):
                continue
    if not lamps:
        n = max(1, int(virtual_count))
        lamps = [dict(channel=i, name='virtual %d' % (i + 1), v1='', u=(i + 0.5) / n, v=0.5)
                 for i in range(n)]
    return lamps[:16]


def lamps_for(comp):
    path = comp.par.Lampsfile.eval()
    try:
        mtime = os.path.getmtime(path) if path and os.path.exists(path) else 0
    except OSError:
        mtime = 0
    key = (path, mtime, int(comp.par.Virtuallamps.eval()), comp.fetch('reload', 0, storeDefault=True))
    if key != _S['lamps_key']:
        _S['lamps'] = read_lamps(path, comp.par.Virtuallamps.eval())
        _S['lamps_key'] = key
        _S['prev'] = None
    return _S['lamps']


# ---- the look ---------------------------------------------------------------------
def palette(comp):
    """(A, B, accent) -- from the Feeling Palette if following it, else the
    three colours on the Look page."""
    if comp.par.Usepalette.eval():
        p = op(comp.par.Palettepath.eval())
        if p is not None and hasattr(p.par, 'Outar'):
            g = lambda n: tuple(getattr(p.par, n + c).eval() for c in 'rgb')
            return g('Outa'), g('Outb'), g('Outc')
    g = lambda n: tuple(getattr(comp.par, n + c).eval() for c in 'rgb')
    return g('Colora'), g('Colorb'), g('Accent')


def _par(comp, name, default):
    p = getattr(comp.par, name, None)
    return default if p is None else p.eval()


def read_look(comp, n_lamps):
    """Everything that decides the colours, as plain values (so an old look
    can keep running while a cue fades in)."""
    L = {k: _par(comp, k, d) for k, d in (
        ('Mode', 'palette'), ('Intensity', 1.0), ('Maxbright', 1.0), ('Rate', 0.5), ('Sync', 0),
        ('Bpm', 120.0), ('Saturate', 1.3), ('Spread', 0.6), ('Gain', 1.4),
        ('Colorsfrom', 'palette'), ('Picturehits', 0.0), ('Together', 0.0))}
    L['pal'] = palette(comp)
    slots = []
    for i in range(1, n_lamps + 1):
        role = _par(comp, 'L%drole' % i, 'mode')
        col = tuple(_par(comp, 'L%dcolor%s' % (i, c), d) for c, d in zip('rgb', (1.0, 0.88, 0.7)))
        pos = None
        if hasattr(comp.par, 'L%dposx' % i):
            pos = (_par(comp, 'L%dposx' % i, 0.5), _par(comp, 'L%dposy' % i, 0.5))
        slots.append((role if role in ROLES else 'mode', col, _par(comp, 'L%dbright' % i, 1.0), pos))
    L['slots'] = slots
    return L


def show_beats(comp, now):
    """(beats, tempo): from show_clock when following it, else from the BPM above.
    'Lights Ahead' makes the lamps run a little early to make up for the
    time the bridge and bulbs take to change."""
    ahead = _par(comp, 'Ahead', 0.0) / 1000.0
    if _par(comp, 'Useclock', 0):
        clk = op(_par(comp, 'Clockpath', '/project1/show_clock'))
        if clk is not None and hasattr(clk.par, 'Beats'):
            tempo = clk.par.Tempo.eval() or 120.0
            return clk.par.Beats.eval() + ahead * tempo / 60.0, tempo
    tempo = _par(comp, 'Bpm', 120.0)
    return (now + ahead) * tempo / 60.0, tempo


def picture_info(arr):
    """(left colour, right colour, accent colour, brightness) of the picture."""
    if arr is None or arr.size == 0:
        return None
    rgb = np.clip(arr[:, :, :3].astype(np.float32), 0.0, 1.0)
    w = rgb.shape[1]
    mx = rgb.max(axis=2)
    sat = mx - rgb.min(axis=2)
    def vivid(block, smx, ssat):
        # the colour of the most vivid quarter of an area (plain averages go grey)
        score = (ssat * 0.7 + smx * 0.3).reshape(-1)
        flat = block.reshape(-1, 3)
        k = max(1, flat.shape[0] // 4)
        idx = np.argpartition(score, -k)[-k:]
        c = flat[idx].mean(axis=0)
        m = float(c.max())
        return tuple(float(x) / m for x in c) if m > 0.02 else (0.0, 0.0, 0.0)
    h = w // 2
    left = vivid(rgb[:, :h], mx[:, :h], sat[:, :h])
    right = vivid(rgb[:, h:], mx[:, h:], sat[:, h:])
    flat = rgb.reshape(-1, 3)
    score = (sat * mx).reshape(-1)
    k = max(1, flat.shape[0] // 40)
    acc = flat[np.argpartition(score, -k)[-k:]].mean(axis=0)
    m = float(acc.max())
    accent = tuple(float(x) / m for x in acc) if m > 0.02 else (1.0, 1.0, 1.0)
    energy = float((0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]).mean())
    return left, right, accent, energy


def picture_palette_and_hits(arr, dt):
    """Smoothed picture colours, and a 'hit' (0..1) whenever the picture jumps in brightness."""
    info = picture_info(arr)
    if info is None:
        _S['ppal'] = None
        return None, 0.0
    a = 1.0 - math.exp(-dt / 0.35)
    pal = info[:3]
    if _S['ppal'] is None:
        _S['ppal'] = pal
    _S['ppal'] = tuple(mix(p, q, a) for p, q in zip(_S['ppal'], pal))
    e = info[3]
    if _S['slow'] is None:
        _S['slow'] = e
    _S['slow'] += (e - _S['slow']) * (1.0 - math.exp(-dt / 0.6))
    hit = max(0.0, min(1.0, (e - _S['slow']) * 8.0))
    return _S['ppal'], hit


# ---- colour maths -------------------------------------------------------------------
def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def scale(c, k):
    return tuple(x * k for x in c)


def saturate(c, amount):
    m = sum(c) / 3.0
    return tuple(max(0.0, m + (x - m) * amount) for x in c)


def sample_picture(arr, u, v, spread):
    """Average colour of the downsampled picture around (u, v)."""
    if arr is None or arr.size == 0:
        return (0.0, 0.0, 0.0)
    h, w = arr.shape[0], arr.shape[1]
    x, y = u * (w - 1), v * (h - 1)                 # numpyArray rows start at the bottom
    r = max(0, int(round(spread * 6)))
    x0, x1 = int(max(0, x - r)), int(min(w - 1, x + r)) + 1
    y0, y1 = int(max(0, y - r)), int(min(h - 1, y + r)) + 1
    block = arr[y0:y1, x0:x1, :3].reshape(-1, 3)
    mean = block.mean(axis=0)
    peak = block[int(block.sum(axis=1).argmax())]   # the brightest spot in the area
    c = mean * 0.4 + peak * 0.6                     # so thin bars and sparks still light the lamp
    return (float(c[0]), float(c[1]), float(c[2]))


def mode_colour(mode, i, n, rank, u, v, t, pal, kick, arr, L, spread_ph=1.0):
    A, B, C = pal
    if mode == 'rainbow':                            # the rainbow show (red .. violet)
        c, _ = rainbow_show(t, rank, n)
        return mix(c, (1.0, 1.0, 1.0), kick * 0.3)
    if mode == 'sample' and arr is None:             # nothing wired in: breathe the palette instead
        mode = 'palette'
    if mode == 'sample':                             # pairs with any Mapper Pack picture
        c = saturate(sample_picture(arr, u, v, L['Spread']), L['Saturate'])
        return scale(c, L['Gain'] * (1.0 + 0.6 * kick))
    if mode == 'chase':                              # pairs with mp_line_sweep / mp_edge_chase
        head = t % 1.0
        d = abs(head - (rank + 0.5) / n)
        d = min(d, 1.0 - d) * n                      # distance from the head, in lamps
        k = math.exp(-d * d * 1.6)                   # about one lamp wide, full brightness at the head
        c = scale(hsv_mix(A, B, rank / max(n - 1, 1)), 0.08 + 0.92 * k)
        return mix(c, C, kick * 0.6)
    if mode == 'flash':                              # pairs with mp_strobe
        k = max(math.exp(-(t % 1.0) / 0.12), kick)
        return mix(scale(A, 0.15), C, k)
    if mode == 'ripple':                             # pairs with mp_grid_pulse (ripple) / mp_tunnel
        d = math.hypot(u - 0.5, v - 0.5) * 1.6
        k = math.exp(-((t - d) % 1.0) / 0.18)
        c = scale(hsv_mix(A, B, min(d, 1.0)), 0.1 + 0.9 * k)
        return mix(c, C, kick * 0.5)
    base = (A, B, C)[rank % 3]                       # 'palette': breathing feeling colours
    k = 0.7 + 0.3 * math.sin(2 * math.pi * (t * 0.25 + spread_ph * rank / max(n, 1)))
    return mix(scale(base, k), C, kick * 0.7)


def shared_colour(cols):
    """One colour that stands for a group of colours WITHOUT going grey: the
    average hue (weighted by how vivid each colour is), their average
    vividness and brightness. (Averaging red and cyan in RGB gives grey.)"""
    hx = hy = sw = 0.0
    ss = vs = 0.0
    for c in cols:
        h, s_, v = colorsys.rgb_to_hsv(*[max(0.0, min(1.0, x)) for x in c])
        w = s_ * v + 1e-6
        hx += math.cos(2 * math.pi * h) * w
        hy += math.sin(2 * math.pi * h) * w
        sw += w
        ss += s_
        vs += v
    n = max(1, len(cols))
    h = (math.atan2(hy, hx) / (2 * math.pi)) % 1.0
    return colorsys.hsv_to_rgb(h, ss / n, vs / n)


def keep_brightness(colour, like):
    """colour, at the brightness of `like` -- so lamps share a colour but keep their own movement."""
    h, s_, _ = colorsys.rgb_to_hsv(*[max(0.0, min(1.0, x)) for x in colour])
    return colorsys.hsv_to_rgb(h, s_, max(0.0, min(1.0, max(like))))


def hsv_mix(a, b, t):
    """Blend two colours through the colour wheel instead of through grey."""
    if t <= 0:
        return tuple(a)
    if t >= 1:
        return tuple(b)
    ha, sa, va = colorsys.rgb_to_hsv(*[max(0.0, min(1.0, x)) for x in a])
    hb, sb, vb = colorsys.rgb_to_hsv(*[max(0.0, min(1.0, x)) for x in b])
    if sa < 0.02 or va < 0.02:                       # grey/black has no hue: take the other's
        ha = hb
    if sb < 0.02 or vb < 0.02:
        hb = ha
    dh = ((hb - ha + 0.5) % 1.0) - 0.5               # the short way round the wheel
    return colorsys.hsv_to_rgb((ha + dh * t) % 1.0, sa + (sb - sa) * t, va + (vb - va) * t)


def lamp_colours(L, lamps, now, kick, arr=None, beats=None, ppal=None, phit=0.0):
    """One colour per lamp for look L. Each lamp's role decides what it does."""
    if beats is None:
        beats = now * L['Bpm'] / 60.0
    t = (beats if L['Sync'] else now) * L['Rate']
    pal = ppal if (L['Colorsfrom'] == 'picture' and ppal is not None) else L['pal']
    kick = max(kick, phit * L['Picturehits'])
    tog = max(0.0, min(1.0, L['Together']))
    n = len(lamps)
    slots = [L['slots'][i] if i < len(L['slots']) else ('mode', (1.0, 0.88, 0.7), 1.0, None)
             for i in range(n)]
    pos = [s[3] if s[3] is not None else (lp['u'], lp['v']) for s, lp in zip(slots, lamps)]
    order = sorted(range(n), key=lambda i: (pos[i][0], pos[i][1], i))
    rank = {i: k for k, i in enumerate(order)}
    spread_ph = 1.0 - tog                            # Togetherness: lamps breathe in step
    out = []
    for i in range(n):
        role, own, bright, _ = slots[i]
        u, v = pos[i]
        if role == 'off':
            c = (0.0, 0.0, 0.0)
        elif role == 'fixed':                        # the lamp's own colour, steady
            c = own
        elif role == 'wash':                         # slow breathing feeling colour, ignores Mode
            base = (pal[0], pal[1], pal[2])[i % 3]
            c = scale(base, 0.65 + 0.35 * math.sin(2 * math.pi * (now * 0.07 + spread_ph * rank[i] / max(n, 1))))
        elif role == 'beat':                         # dim, hits its own colour on the beat / kick
            k = max(math.exp(-(t % 1.0) / 0.12), kick)
            c = scale(own, 0.06 + 0.94 * k)
        else:                                        # 'mode': follows the Mode on the Look page
            c = mode_colour(L['Mode'], i, n, rank[i], u, v, t, pal, kick, arr, L, spread_ph)
        out.append((role, c, bright))
    # Togetherness: lamps that follow the Mode lean towards one shared colour
    follow = [c for r, c, _ in out if r == 'mode']
    if follow and tog > 0:
        shared = shared_colour(follow)
        out = [(r, hsv_mix(c, keep_brightness(shared, c), tog) if r == 'mode' else c, b) for r, c, b in out]
    return [tuple(min(L['Maxbright'], max(0.0, x * L['Intensity'] * b)) for x in c) for _, c, b in out]


def smooth(prev, target, amount, dt, kick=0.0):
    """Smoothing: 0 = instant, 1 = slow washes. Fades up quicker than down."""
    if prev is None or len(prev) != len(target):
        return [tuple(c) for c in target]
    rise = (0.005 + 0.4 * amount * amount) * (1.0 - 0.9 * kick)
    fall = 0.02 + 1.0 * amount
    a_up = 1.0 - math.exp(-dt / max(rise, 1e-3))
    a_dn = 1.0 - math.exp(-dt / max(fall, 1e-3))
    return [tuple(x + (y - x) * (a_up if y > x else a_dn) for x, y in zip(p, q))
            for p, q in zip(prev, target)]


# ---- cues -----------------------------------------------------------------------------
def cue_pars(comp):
    return [p for p in comp.customPars
            if p.page.name in CUE_PAGES and not _skip_in_cue(p.name) and not p.isPulse
            and p.style not in ('Str', 'File', 'Header')]


def load_cues(comp):
    path = _par(comp, 'Cuesfile', '')
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        key = (path, 0)
    if key != _S['cues_key']:
        _S['cues_key'] = key
        try:
            with open(path) as f:
                _S['cues'] = json.load(f).get('cues', [])
        except (OSError, ValueError):
            _S['cues'] = []
        names = [c['name'] for c in _S['cues']] or ['(none yet)']
        try:
            comp.par.Cue.menuNames = names
            comp.par.Cue.menuLabels = names
        except Exception:
            pass
    return _S['cues']


def save_cue(comp):
    name = (_par(comp, 'Cuename', '') or '').strip() or 'cue %d' % (len(load_cues(comp)) + 1)
    vals = {}
    for p in cue_pars(comp):
        v = p.eval()
        vals[p.name] = v if isinstance(v, (int, float, str, bool)) else str(v)
    cues = [c for c in load_cues(comp) if c['name'] != name]   # same name = replace it
    old = [c['name'] for c in load_cues(comp)]
    entry = {'name': name, 'values': vals}
    if name in old:
        cues.insert(old.index(name), entry)
    else:
        cues.append(entry)
    path = _par(comp, 'Cuesfile', '')
    with open(path, 'w') as f:
        json.dump({'cues': cues}, f, indent=1)
    load_cues(comp)
    try:
        comp.par.Cue = name
    except Exception:
        pass
    return name


def go_cue(comp, name, n_lamps):
    cues = {c['name']: c for c in load_cues(comp)}
    if name not in cues:
        return False
    _S['fade'] = {'from': read_look(comp, n_lamps), 't0': time.time(),
                  'dur': max(0.0, float(_par(comp, 'Fade', 2.0)))}
    for pname, v in cues[name]['values'].items():
        p = getattr(comp.par, pname, None)
        if p is None or p.mode != ParMode.CONSTANT:  # leave linked / exported parameters alone
            continue
        try:
            p.val = v
        except Exception:
            pass
    try:
        comp.par.Cue = name
    except Exception:
        pass
    return True


def handle_cue_requests(comp, n_lamps):
    reqs = comp.fetch('cue_reqs', [], storeDefault=True)
    if not reqs:
        return ''
    comp.store('cue_reqs', [])
    msg = ''
    for what in reqs:
        names = [c['name'] for c in load_cues(comp)]
        cur = _par(comp, 'Cue', '')
        if what == 'save':
            try:
                msg = 'Saved cue "%s"' % save_cue(comp)
            except OSError as e:
                msg = 'Could not save the cue: %s' % e
        elif what in ('go', 'next', 'prev') and names:
            k = names.index(cur) if cur in names else -1
            if what == 'next':
                k = (k + 1) % len(names)
            elif what == 'prev':
                k = (k - 1) % len(names)
            else:
                k = max(k, 0)
            go_cue(comp, names[k], n_lamps)
            msg = 'Cue "%s"' % names[k]
        elif what.startswith('go:'):
            msg = ('Cue "%s"' % what[3:]) if go_cue(comp, what[3:], n_lamps) else 'No cue called "%s"' % what[3:]
    comp.store('cue_msg', (msg, time.time()))
    return msg


def rgb_to_xy_bri(r, g, b):
    """Philips' recipe: gamma, then wide-gamut RGB -> XYZ -> xy."""
    def gam(c):
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    r, g, b = gam(r), gam(g), gam(b)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    s = X + Y + Z
    if s <= 1e-6:
        return (0.3227, 0.329), 0
    return (round(X / s, 4), round(Y / s, 4)), int(round(min(1.0, max(r, g, b)) * 254))


# ---- sending --------------------------------------------------------------------------
def send_stream(port, cols):
    if _S['sock'] is None:
        _S['sock'] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg = json.dumps({'c': [[round(x, 4) for x in c] for c in cols]}).encode()
    try:
        _S['sock'].sendto(msg, ('127.0.0.1', int(port)))
    except OSError:
        pass


class Direct(threading.Thread):
    """Sends to the bridge's normal API in the background, ~10 changes a
    second in total (the bridge's limit), newest colour first."""
    def __init__(self, ip, user):
        super().__init__(daemon=True)
        self.ip, self.user = ip, user
        self.latest, self.sent, self.alive = {}, {}, True
        self.ctx = ssl._create_unverified_context()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPSHandler(context=self.ctx))
        self.error = ''

    def run(self):
        while self.alive:
            todo = [k for k, v in list(self.latest.items()) if self.sent.get(k) != v]
            if not todo:
                time.sleep(0.02)
                continue
            for lid in todo:
                (xy, bri) = self.latest[lid]
                body = {'on': bri > 0, 'transitiontime': 1}
                if bri > 0:
                    body.update(bri=max(1, bri), xy=list(xy))
                req = urllib.request.Request('https://%s/api/%s/lights/%s/state' % (self.ip, self.user, lid),
                                             data=json.dumps(body).encode(), method='PUT')
                try:
                    self.opener.open(req, timeout=2).read()
                    self.sent[lid] = (xy, bri)
                    self.error = ''
                except Exception as e:
                    self.error = str(e)[:120]
                time.sleep(0.1)


def send_direct(comp, lamps, cols):
    cfgpath = comp.par.Configfile.eval()
    d = _S['direct']
    if d is None:
        try:
            cfg = json.load(open(cfgpath))
            d = _S['direct'] = Direct(cfg['ip'], cfg['username'])
            d.start()
        except Exception as e:
            status(comp, 'Direct: no hue_config.json yet -- run the helper pair step first')
            return
    for L, c in zip(lamps, cols):
        if L.get('v1'):
            xy, bri = rgb_to_xy_bri(*c)
            # only bother the bridge with visible changes
            old = d.latest.get(L['v1'])
            if old is None or abs(old[1] - bri) > 4 or abs(old[0][0] - xy[0]) + abs(old[0][1] - xy[1]) > 0.01:
                d.latest[L['v1']] = (xy, bri)
    status(comp, 'Direct to bridge' + (' -- ' + d.error if d.error else ''))


def stop_direct():
    if _S['direct'] is not None:
        _S['direct'].alive = False
        _S['direct'] = None


def status(comp, text):
    comp.store('status', text)
    try:
        if comp.par.Status.eval() != text:
            comp.par.Status = text
    except Exception:
        pass


# ---- every frame ----------------------------------------------------------------------
def onFrameEnd(frame):
    comp = parent()
    lamps = lamps_for(comp)
    n = len(lamps)
    load_cues(comp)
    handle_cue_requests(comp, n)

    now = absTime.seconds
    dt = 1 / 60.0 if _S['last_t'] is None else now - _S['last_t']
    if not 0.0 < dt < 0.25:
        dt = 1 / 60.0
    _S['last_t'] = now

    look = read_look(comp, n)
    kick = _par(comp, 'Kick', 0.0)
    arr = None
    fade = _S['fade']
    looks = [look] + ([fade['from']] if fade else [])
    if any(l['Mode'] == 'sample' or l['Colorsfrom'] == 'picture' or l['Picturehits'] > 0 for l in looks):
        try:
            arr = op('small').numpyArray(delayed=True)
        except Exception:
            arr = None
        if arr is not None and float(arr[:, :, :3].max()) < 0.02:
            arr = None                               # black = nothing wired into hue_rig
        _S['nopic'] = arr is None
    else:
        _S['nopic'] = False
    ppal, phit = picture_palette_and_hits(arr, dt)
    beats, tempo = show_beats(comp, now)
    target = lamp_colours(look, lamps, now, kick, arr, beats, ppal, phit)
    if fade:                                         # cross-fade from the previous look
        k = 1.0 if fade['dur'] <= 0 else min(1.0, (time.time() - fade['t0']) / fade['dur'])
        k = k * k * (3 - 2 * k)
        old = lamp_colours(fade['from'], lamps, now, kick, arr, beats, ppal, phit)
        target = [hsv_mix(a, b, k) for a, b in zip(old, target)]
        if k >= 1.0:
            _S['fade'] = None
    if _par(comp, 'Blackout', 0):
        target = [(0.0, 0.0, 0.0)] * n

    cols = smooth(_S['prev'], target, _par(comp, 'Smooth', 0.3), dt, kick)
    _S['prev'] = cols

    # flicker protection: the last word before the preview and the lights
    guard = _par(comp, 'Flickerguard', 2.0)
    if _S['lim'] is None:
        _S['lim'] = FlashLimiter(guard)
    lim = _S['lim']
    lim.set_rate(guard)
    cols = lim.step(cols, time.time())
    _S['held'] = _S['held'] * 0.97 + (0.03 if lim.held else 0.0)

    # preview data: row 0 = position, row 1 = colour
    data = np.zeros((2, 16, 4), dtype=np.float32)
    for i, (L, c) in enumerate(zip(lamps[:16], cols)):
        p = look['slots'][i][3] if i < len(look['slots']) and look['slots'][i][3] is not None else (L['u'], L['v'])
        data[0, i] = (p[0], p[1], 1.0, 1.0)
        data[1, i] = (c[0], c[1], c[2], 1.0)
    comp.store('lampdata', data)
    try:
        op('lampdata').cook(force=True)
    except Exception:
        pass

    t_out = op('lamp_colours')
    if t_out is not None:
        t_out.clear()
        t_out.appendRow(['lamp', 'role', 'r', 'g', 'b'])
        for i, (L, c) in enumerate(zip(lamps, cols)):
            role = look['slots'][i][0] if i < len(look['slots']) else 'mode'
            t_out.appendRow([L['name'], role] + ['%.3f' % x for x in c])

    note = ''
    msg = comp.fetch('cue_msg', ('', 0), storeDefault=True)
    if msg[0] and time.time() - msg[1] < 4:
        note = ' | ' + msg[0]
    elif _S['fade']:
        note = ' | fading to cue'
    elif _S.get('nopic'):
        note = ' | no picture wired into hue_rig -- using palette colours'
    elif _S['held'] > 0.3:
        note = ' | Flicker Guard is softening fast changes'

    if not _par(comp, 'Active', 1):
        status(comp, 'Off (preview only)' + note)
        stop_direct()
        return
    transport = comp.par.Transport.eval()
    if transport == 'stream':
        send_stream(comp.par.Port.eval(), cols)
        status(comp, 'Streaming to the helper on port %d' % comp.par.Port.eval() + note)
        stop_direct()
    elif transport == 'direct':
        send_direct(comp, lamps, cols)
    else:
        status(comp, 'Preview only' + note)
        stop_direct()
    return
