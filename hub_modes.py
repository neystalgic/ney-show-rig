# =============================================================================
# HUE HUB -- the SHOW DIRECTOR: modes + zones + a new pattern every 8 bars     Nov 15, live with Michael
#
# Michael: "different modes that react differently with colour, head speed and rhythm, then go to a
# different audio-reactive but equally sick pattern every 8 bars ... zones, each doing something different."
#
# ZONES come from where things sit (the same x/y frame as hub_lamps.json): each head is a zone and every
# Hue lamp belongs to the head nearest it. Left -> right across the room (by x) is the "room order".
#
# MODES (each one: colour behaviour + head motion + what part of the beat drives it)
#   pulse      one colour room-wide; every zone hits on the KICK; heads snap between two leans
#   call       call & response: zones A/B in opposite colours, A answers the kick, B the snare
#   wave       a ripple across the room, one zone per beat, colours graded left -> right
#   split      bass zones (left) warm + slow, hi-hat zones (right) cool + quick
#   orbit      heads trace slow circles out of phase; colour drifts; speed follows the energy
#   relay      one head at a time sweeps and hands off on the bar (hub_chase.py)
# Drops are NOT a mode here: in a drop the director steps aside and the normal show dances (+ strobe,
# sparingly) -- then a new mode starts after it.
#
# THE DIRECTOR: on every 8-bar line (setting show_bars) it picks the next mode for the section
# (groove / breakdown), never the same one twice in a row and never one of the last two.
# Setting dmx_pattern = 'modes' turns it on ('relay' = relay only, 'normal' = off).
# show_lock = a mode name holds that mode; '' = auto. show_speed 0.5-2 scales head speed.
# show_pool = comma list to limit which modes auto may pick.
#
# Safety: no network here. It only proposes levels, leans and pan positions; hub_dmx still applies every
# head's lean cap, pan window, avoid zones and speed limit, never strobes for a mode, and the DMX node
# has the last word.
# =============================================================================
import colorsys
import math

import hub_chase

MODES = ['pulse', 'call', 'wave', 'split', 'orbit', 'relay']
POOLS = {'groove': ['pulse', 'call', 'wave', 'split', 'relay', 'orbit'],
         'breakdown': ['orbit', 'relay', 'wave'],
         'quiet': ['orbit']}
NAMES = {'pulse': 'Pulse', 'call': 'Call & Response', 'wave': 'Wave', 'split': 'Split',
         'orbit': 'Orbit', 'relay': 'Relay'}
PURPLE = 0.78                     # hue used when the lamps give no colour


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def hsv(h, s=1.0, v=1.0):
    return colorsys.hsv_to_rgb(h % 1.0, clamp(max(s, 0.55)), clamp(v))   # never white


def decay(frac, tau=0.35):
    """1 on the beat, falling away over the beat."""
    return math.exp(-max(0.0, frac) / max(1e-3, tau))


class _Relay(hub_chase.Chase):
    """The relay, switchable on by the director for a phrase (without touching the shared settings)."""
    forced = False

    def wanted(self, pmode):
        if self.forced:
            sec = getattr(getattr(self.hub, 'audioshow', None), 'section', 'groove')
            return sec != 'drop'
        return hub_chase.Chase.wanted(self, pmode)


class Director:
    """Drop-in for hub_chase.Chase inside hub_dmx / hue_hub: step(), theta(), pan(), lamps(), describe()."""

    def __init__(self, hub, lamps=None):
        self.hub = hub
        self.chase = _Relay(hub, lamps)
        self.lamp_xy = self.chase.lamp_xy
        self.heads_i = [0, 1, 2, 3]
        self.mode = None
        self.phrase = None
        self.history = []
        self.hue = PURPLE
        self.hue_t = None             # bar when the colour last changed
        self.v = 0.6
        self.active = False
        self.last = None              # last step() result
        self._cache = (None, None)
        self._zone_cache = None

    # -------------------------------------------------------------------------- settings
    def settings(self):
        return self.hub.state['settings']

    def pattern(self):
        return str(self.settings().get('dmx_pattern', 'normal') or 'normal')

    def speed(self):
        try:
            return clamp(float(self.settings().get('show_speed', 1.0)), 0.5, 2.0)
        except (TypeError, ValueError):
            return 1.0

    def bars_per_phrase(self):
        try:
            return max(1, int(float(self.settings().get('show_bars', 8))))
        except (TypeError, ValueError):
            return 8

    def pool(self, section):
        p = list(POOLS.get(section, POOLS['groove']))
        want = str(self.settings().get('show_pool', '') or '').strip()
        if want:
            keep = [m for m in (x.strip() for x in want.split(',')) if m in MODES]
            p = [m for m in p if m in keep] or keep or p
        return p

    # -------------------------------------------------------------------------- zones
    def head_xy(self, i):
        s = self.settings()
        xy = (s.get('chase_head_xy') or {}).get(str(i)) if isinstance(s.get('chase_head_xy'), dict) else None
        try:
            return (float(xy[0]), float(xy[1])) if xy else hub_chase.DEFAULT_HEAD_XY.get(i, (0.0, 0.0))
        except (TypeError, ValueError, IndexError):
            return hub_chase.DEFAULT_HEAD_XY.get(i, (0.0, 0.0))

    def zones(self):
        """{lamp channel: head index} (nearest head; chase_lamps names win) and the heads in room order."""
        key = (tuple(self.heads_i), repr(self.settings().get('chase_head_xy')), repr(self.settings().get('chase_lamps')))
        if self._zone_cache and self._zone_cache[0] == key:
            return self._zone_cache[1], self._zone_cache[2]
        s = self.settings()
        named = s.get('chase_lamps') if isinstance(s.get('chase_lamps'), dict) else {}
        lz = {}
        for ch, (x, y, nm) in self.lamp_xy.items():
            owner = next((int(h) for h, names in named.items() if nm in (names or [])), None)
            if owner is None and self.heads_i:
                owner = min(self.heads_i, key=lambda h: math.hypot(x - self.head_xy(h)[0], y - self.head_xy(h)[1]))
            lz[ch] = owner
        order = sorted(self.heads_i, key=lambda h: self.head_xy(h)[0])
        self._zone_cache = (key, lz, order)
        return lz, order

    # -------------------------------------------------------------------------- when it runs
    def wanted(self, pmode):
        pat = self.pattern()
        if pat in ('show', 'relay'):
            return 'relay'                                    # the old relay settings keep working as before
        if pat != 'modes':
            return None
        s = self.settings()
        if pmode == 'sync' or s.get('movie') or getattr(self.hub, 'blackout', False) or not s.get('dmx_on', True):
            return None
        if not str(s.get('dmx_host', '') or '').strip():
            return None
        cue = s.get('dmx_cue')
        if isinstance(cue, dict) and cue.get('a'):
            return None                                       # a scene Michael picked wins
        if pmode not in ('music', None):
            return None
        if self.section() == 'drop':
            return None                                       # drops: the normal show dances (strobe only there)
        return 'modes'

    def section(self):
        return getattr(getattr(self.hub, 'audioshow', None), 'section', 'groove') or 'groove'

    def env(self):
        e = getattr(getattr(self.hub, 'audioshow', None), 'env', None) or {}
        return {k: clamp(float(e.get(k, 0.0) or 0.0)) for k in ('kick', 'snare', 'hats')}

    def energy(self):
        try:
            return clamp(float(self.settings().get('energy', 0.6)))
        except (TypeError, ValueError):
            return 0.6

    # -------------------------------------------------------------------------- the director
    def pick(self, section):
        lock = str(self.settings().get('show_lock', '') or '').strip().lower()
        if lock in MODES:
            return lock
        pool = self.pool(section)
        avoid = set(self.history[-2:])
        options = [m for m in pool if m not in avoid] or [m for m in pool if m != self.mode] or pool
        n = len(self.history)                                 # deterministic rotation through what's allowed
        return options[(n * 7 + len(options)) % len(options)] if options else 'orbit'

    def tick_phrase(self, beats):
        bpb = int(self.settings().get('beats_per_bar', 4) or 4)
        bar = int(math.floor(beats / bpb))
        phrase = bar // self.bars_per_phrase()
        lock = str(self.settings().get('show_lock', '') or '').strip().lower()
        if self.mode is None or phrase != self.phrase or (lock in MODES and lock != self.mode):
            new = self.pick(self.section())
            if new != self.mode:
                self.history.append(new)
                self.history = self.history[-6:]
            self.mode, self.phrase = new, phrase
            self.hue_t = None
        return bar, bpb

    # -------------------------------------------------------------------------- one frame
    def step(self, now, beats, pmode, heads=None):
        if self._cache[0] == now:
            return self._cache[1]
        if heads is not None:
            hi = [i for i, h in enumerate(heads) if h.get('type') != 'focus17']
            if hi != self.heads_i:
                self.heads_i, self._zone_cache = hi, None
        w = self.wanted(pmode)
        if w == 'relay':
            out = self.chase.step(now, beats, pmode, heads)
            self._cache, self.last, self.active = (now, out), out, out is not None
            return out
        if w is None or not self.heads_i:
            self.active, self.last = False, None
            self._cache = (now, None)
            return None
        bar, bpb = self.tick_phrase(beats)
        if self.mode == 'relay':
            self.chase.forced = True                          # the relay runs on its own clock for this phrase
            try:
                out = self.chase.step(now, beats, pmode, heads)
            finally:
                self.chase.forced = False
            if out:
                out = dict(out, mode='relay', bar=bar, phrase_bar=bar % self.bars_per_phrase())
            self._cache, self.last, self.active = (now, out), out, out is not None
            return out
        # colour: one change per 2 bars at most (Michael: faster colour changes are distracting)
        if self.hue_t is None or bar - self.hue_t >= 2:
            if self.hue_t is not None:
                self.hue = (self.hue + (0.12 if self.mode in ('orbit', 'wave') else 0.2)) % 1.0
            self.hue_t = bar
        e, en = self.env(), self.energy()
        sp = self.speed()
        lz, order = self.zones()
        rank = {h: order.index(h) for h in order}
        n = max(1, len(order))
        frac = beats - math.floor(beats)
        bib = int(math.floor(beats)) % bpb                    # beat in bar
        hs = {}
        for h in self.heads_i:
            r = rank.get(h, 0)
            side = 0 if r < n / 2.0 else 1                    # left half / right half of the room
            lvl, lean, u, hue = 0.6, 0.6, 0.5, self.hue
            if self.mode == 'pulse':
                lvl = 0.2 + 0.8 * e['kick']
                lean = 0.85 if (int(math.floor(beats)) + r) % 2 == 0 else 0.45
                u = 0.5 + 0.12 * (1 if bar % 2 == 0 else -1) * (1 if r % 2 == 0 else -1)
            elif self.mode == 'call':
                a = r % 2 == 0
                hit = e['kick'] if a else e['snare']
                lvl = 0.12 + 0.88 * hit
                lean = 0.4 + 0.5 * hit
                u = 0.5 + 0.25 * math.sin(2 * math.pi * beats / (16.0 / sp)) * (1 if a else -1)
                hue = self.hue if a else self.hue + 0.5
            elif self.mode == 'wave':
                on = (int(math.floor(beats)) % n) == r
                lvl = 0.12 + 0.88 * (decay(frac, 0.45 / sp) if on else 0.0) + 0.25 * e['kick'] * (0 if on else 1)
                lean = 0.85 if on else 0.5
                u = 0.5 + 0.3 * math.sin(2 * math.pi * beats / (16.0 / sp))
                hue = self.hue + 0.08 * r
            elif self.mode == 'split':
                if side == 0:                                 # bass side: warm, big + slow
                    lvl = 0.25 + 0.75 * e['kick']
                    lean = 0.6 + 0.3 * math.sin(2 * math.pi * beats / (8.0 / sp))
                    u = 0.5 + 0.3 * math.sin(2 * math.pi * beats / (16.0 / sp) + r)
                    hue = self.hue
                else:                                         # hi-hat side: cool, small + quick
                    lvl = 0.2 + 0.8 * max(e['hats'], 0.5 * e['snare'])
                    lean = 0.55 + 0.15 * math.sin(2 * math.pi * beats / (2.0 / sp))
                    u = 0.5 + 0.1 * math.sin(2 * math.pi * beats / (2.0 / sp) + r)
                    hue = self.hue + 0.33
            elif self.mode == 'orbit':
                k = (0.6 + 0.8 * en) * sp
                ph = 2 * math.pi * beats / (16.0 / k) + r * math.pi / 2.0
                lvl = 0.45 + 0.35 * en + 0.2 * e['kick']
                lean = 0.55 + 0.3 * math.cos(ph)
                u = 0.5 + 0.35 * math.sin(ph)
                hue = self.hue + 0.05 * math.sin(2 * math.pi * beats / 64.0) + 0.04 * r
            hs[h] = dict(level=clamp(lvl), lean=clamp(lean), u=clamp(u), rgb=hsv(hue, 0.9, 1.0), zone=r)
        out = dict(heads=hs, rgb=hsv(self.hue), v=self.v, head=None, turn=self.phrase, new=False, p=0.0,
                   mode=self.mode, bar=bar, phrase_bar=bar % self.bars_per_phrase(), bib=bib)
        self._cache, self.last, self.active = (now, out), out, True
        return out

    # -------------------------------------------------------------------------- aims (hub_dmx caps them)
    def theta(self, cv, lean_max):
        if 'lean' in cv:
            return clamp(cv['lean'], 0.0, 1.0) * lean_max
        return self.chase.theta(cv, lean_max)

    def pan(self, cv, pmin, pmax):
        if 'u' in cv:
            return clamp(pmin + clamp(cv['u']) * (pmax - pmin), pmin, pmax)
        return self.chase.pan(cv, pmin, pmax)

    # -------------------------------------------------------------------------- the lamps follow their zone
    def lamps(self, cols, channels, now, beats, pmode):
        z = self.step(now, beats, pmode)
        if not cols:
            return cols
        self.v = max(max(c) for c in cols)
        self.chase.v = self.v
        if not z:
            return cols
        if z.get('mode', 'relay') == 'relay':
            self.chase.forced = self.pattern() == 'modes'
            try:
                return self.chase.lamps(cols, channels, now, beats, pmode)
            finally:
                self.chase.forced = False
        lz, _ = self.zones()
        v = max(self.v, 0.35)
        dim = 0.15
        out = []
        for ch in channels:
            hv = z['heads'].get(lz.get(ch))
            if hv is None:
                out.append(hsv(self.hue, 0.9, v * dim))
                continue
            hh, ss, _ = colorsys.rgb_to_hsv(*hv['rgb'])
            out.append(colorsys.hsv_to_rgb(hh, max(ss, 0.55), v * (dim + (1.0 - dim) * hv['level'])))
        return out

    def describe(self, z=None):
        z = z if z is not None else self.last
        if not z:
            return 'modes off' if self.pattern() == 'modes' else self.chase.describe(None)
        m = z.get('mode', 'relay')
        return '%s (bar %d of %d)' % (NAMES.get(m, m), z.get('phrase_bar', 0) + 1, self.bars_per_phrase())

    def status(self):
        z = self.last
        return dict(on=bool(z), pattern=self.pattern(), mode=(z or {}).get('mode'), name=NAMES.get((z or {}).get('mode'), ''),
                    bar=(z or {}).get('phrase_bar', 0) + 1 if z else 0, bars=self.bars_per_phrase(),
                    lock=str(self.settings().get('show_lock', '') or ''), speed=self.speed(),
                    history=list(self.history[-4:]), section=self.section(), modes=[dict(id=m, name=NAMES[m]) for m in MODES])
