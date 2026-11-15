# =============================================================================
# HUE HUB -- the HEAD RELAY (a chase for the light show)          Nov 15, away loop
#
# One head at a time is lit. It fades in, makes one smooth sweep (a pan arc with a
# small tilt dip) in the room's colour, fades out -- and the next head takes over:
#     1 -> 2 -> 3 -> 4, back 3 -> 2, then a skip pattern 1 -> 3 -> 2 -> 4, and round again.
# The hand-off lands on the bar line: every 2 bars, or every bar when the energy is high
# (Michael finds faster colour changes distracting). The colour is picked at each hand-off
# and held for the whole turn. The Hue lamps nearest the lit head glow in that colour and
# the rest dim, so the light "travels" round the room.
#
# Setting dmx_pattern (desk > Setup, POST /api op=setting, or "Jarvis, head relay"):
#   'normal'  (default) the heads dance as before -- the relay is off
#   'show'    the show uses the relay in grooves and breakdowns; drops dance + strobe as usual
#   'relay'   the relay runs whenever music plays, except in drops
# Optional settings: chase_arc (degrees, default 50), chase_dip (degrees, default 8),
#   chase_dim (how bright the far lamps stay, default 0.2), chase_spots (true = the two spots
#   keep their normal show; default false = dark while the relay runs), chase_fast_energy
#   (energy at which hand-offs come every bar, default 0.75), chase_head_xy {"0": [x, y], ...}
#   and chase_lamps {"0": ["Lamp name", ...]} to say which lamps sit near which head.
#
# Safety: nothing here talks to the network. It only proposes aims and levels; hub_dmx still
# applies each head's lean cap, pan window and avoid zones, and the DMX node has the last
# word. The relay never strobes, never runs in movie mode, blackout or rest, and a scene you
# pick yourself (dmx_cue) wins over it.
# =============================================================================

import colorsys
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_DEG_S = 35.0                 # same as hub_dmx: the fastest a beam may swing
# Where the heads sit, in the Hue entertainment area's x/y (the same frame as hub_lamps.json).
# ESTIMATED from Aim Map / Room Measurements (Head 4 by the lamp behind the desk, the Play floor
# lamp on Head 2's shelf) -- check by eye and fix with setting chase_head_xy if a lamp looks wrong.
DEFAULT_HEAD_XY = {0: (-0.6, -0.8), 1: (0.7, -0.8), 2: (1.0, 0.5), 3: (-0.9, 0.9)}


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def relay_order(n):
    """The order the heads take turns in (indexes into the relay heads): forward, back, then a skip
    pattern -- never the same head twice in a row."""
    if n <= 1:
        return [0] * max(1, n)
    fwd = list(range(n))
    back = fwd[-2:0:-1]                                   # 4 heads: 3, 2  (the ends aren't repeated)
    skip = fwd[0::2] + fwd[1::2]                          # 4 heads: 1, 3, 2, 4
    out = []
    for x in fwd + back + skip:
        if not out or out[-1] != x:
            out.append(x)
    if len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return out


def load_lamps(path=None):
    """{channel: (x, y, name)} from hub_lamps.json (missing file -> {})."""
    try:
        with open(path or os.path.join(HERE, 'hub_lamps.json')) as f:
            d = json.load(f)
    except Exception:
        return {}
    out = {}
    for l in d.get('lamps', []):
        for sg in l.get('segments', []):
            try:
                out[int(sg['channel'])] = (float(sg['x']), float(sg['y']), l.get('name', ''))
            except (KeyError, TypeError, ValueError):
                pass
    return out


class Chase:
    def __init__(self, hub, lamps=None):
        self.hub = hub
        self.lamp_xy = load_lamps() if lamps is None else lamps
        self.relay_heads = [0, 1, 2, 3]                   # node head indexes that take part (not the spots)
        self.active = False
        self.idx = 0                                      # which turn we are on (into relay_order)
        self.t0 = self.t1 = None                          # this turn's start / end, in beats
        self.rgb = None                                   # the colour, picked at each hand-off
        self.v = 0.6                                      # how bright the room is right now (from the lamps)
        self.bps = 2.0                                    # beats a second (measured)
        self._b = self._t = None
        self._cache = (None, None)

    def settings(self):
        return self.hub.state['settings']

    # ---- when it runs -------------------------------------------------------------------------
    def wanted(self, pmode):
        s = self.settings()
        mode = str(s.get('dmx_pattern', 'normal') or 'normal')
        if mode not in ('show', 'relay'):
            return False
        if pmode == 'sync' or s.get('movie') or getattr(self.hub, 'blackout', False) or not s.get('dmx_on', True):
            return False
        if not str(s.get('dmx_host', '') or '').strip():
            return False                                  # no heads connected: the lamps stay as they were
        cue = s.get('dmx_cue')
        if isinstance(cue, dict) and cue.get('a'):
            return False                                  # a scene Michael picked wins
        section = getattr(getattr(self.hub, 'audioshow', None), 'section', 'groove')
        if mode == 'show':                                # the music show only (not lava / ambient)
            return pmode in ('music', None) and section in ('groove', 'breakdown')   # verses / builds, never a drop
        return section != 'drop'

    def turn_beats(self):
        s = self.settings()
        bpb = int(s.get('beats_per_bar', 4) or 4)
        try:
            fast = float(s.get('energy', 0.6)) >= float(s.get('chase_fast_energy', 0.75))
        except (TypeError, ValueError):
            fast = False
        return bpb * (1 if fast else 2), bpb

    # ---- the clock ----------------------------------------------------------------------------
    def step(self, now, beats, pmode, heads=None):
        """Advance the relay. Returns None when it is off, else
        {'heads': {node index: {'level', 'p', 'way', 'arc'}}, 'rgb', 'v', 'head', 'turn', 'new'}.
        Safe to call more than once per frame (same `now` -> same answer)."""
        if self._cache[0] == now:
            return self._cache[1]
        if heads is not None:
            rh = [i for i, h in enumerate(heads) if h.get('type') != 'focus17']
            if rh != self.relay_heads:
                self.relay_heads, self.idx = rh, 0
        if self._b is not None and now > self._t:         # measure the tempo from the beat clock
            r = (beats - self._b) / (now - self._t)
            if 0.5 < r < 5.0:
                self.bps += (r - self.bps) * clamp((now - self._t) / 2.0)
        self._b, self._t = beats, now
        on = self.wanted(pmode) and bool(self.relay_heads)
        new = False
        if not on:
            self.active, out = False, None
            self._cache = (now, out)
            return out
        per, bpb = self.turn_beats()
        if not self.active or self.t0 is None or beats < self.t0 - 1.0 or beats - self.t1 > 4 * per:
            self.active, new = True, True                 # (re)start: this turn runs to the bar line after next
            self.t0 = beats
            self.t1 = math.floor(beats / bpb) * bpb + bpb + (per - bpb)
            if self.t1 - self.t0 < bpb * 0.75:
                self.t1 += bpb
            self.rgb = None
        while beats >= self.t1:                            # HAND-OFF on the bar line
            self.idx += 1
            self.t0, self.t1 = self.t1, self.t1 + per
            new = True
        if new:
            self.rgb = None                               # pick this turn's colour from the lamps
        order = relay_order(len(self.relay_heads))
        cur = self.relay_heads[order[self.idx % len(order)]]
        nxt = self.relay_heads[order[(self.idx + 1) % len(order)]]
        way = 1.0 if self.idx % 2 == 0 else -1.0
        p = clamp((beats - self.t0) / max(1e-6, self.t1 - self.t0))
        span = max(1e-6, self.t1 - self.t0)
        fb = min(float(self.settings().get('chase_fade_beats', 0.5) or 0.5), span / 4.0) / span
        level = smooth(p / fb) * smooth((1.0 - p) / fb)    # fade in, hold, fade out -- 0 on the bar line itself
        secs = span / max(0.5, self.bps)
        try:
            arc = float(self.settings().get('chase_arc', 50.0))
        except (TypeError, ValueError):
            arc = 50.0
        arc = clamp(arc, 0.0, 0.9 * MAX_DEG_S * secs * 2.0 / math.pi)   # the eased sweep stays under the speed cap
        hs = {}
        for i in self.relay_heads:
            if i == cur:
                hs[i] = dict(level=level, p=p, way=way, arc=arc)
            elif i == nxt:
                hs[i] = dict(level=0.0, p=0.0, way=-way, arc=arc)   # dark: already turning to where it starts
            else:
                hs[i] = dict(level=0.0, p=0.0, way=way, arc=arc)
        out = dict(heads=hs, rgb=self.rgb, v=self.v, head=cur, turn=self.idx, new=new, p=p)
        self._cache = (now, out)
        return out

    # ---- aims (hub_dmx applies the caps on top) -----------------------------------------------
    def theta(self, cv, lean_max):
        """Lean from straight up: most of the head's allowed lean, dipping a little mid-sweep."""
        s = self.settings()
        try:
            dip = clamp(float(s.get('chase_dip', 8.0)), 0.0, 20.0)
        except (TypeError, ValueError):
            dip = 8.0
        base = lean_max * 0.85
        return clamp(base - min(dip, base * 0.5) * math.sin(math.pi * cv['p']), 0.0, lean_max)

    def pan(self, cv, pmin, pmax):
        """Pan (16-bit): an eased arc across the middle of the head's pan window, inside the window."""
        e = 0.5 - 0.5 * math.cos(math.pi * cv['p'])
        half16 = min((pmax - pmin) / 2.0, cv['arc'] / 2.0 / 540.0 * 65535.0)
        mid = (pmin + pmax) / 2.0
        return clamp(mid + cv['way'] * (e - 0.5) * 2.0 * half16, pmin, pmax)

    # ---- the lamps follow ---------------------------------------------------------------------
    def near(self, head):
        """Channels of the lamps beside a head: setting chase_lamps (names) or the nearest by x/y."""
        s = self.settings()
        names = (s.get('chase_lamps') or {}).get(str(head)) if isinstance(s.get('chase_lamps'), dict) else None
        if names:
            return {ch for ch, (_, _, nm) in self.lamp_xy.items() if nm in names}
        xy = (s.get('chase_head_xy') or {}).get(str(head)) if isinstance(s.get('chase_head_xy'), dict) else None
        try:
            hx, hy = (float(xy[0]), float(xy[1])) if xy else DEFAULT_HEAD_XY.get(head, (0.0, 0.0))
        except (TypeError, ValueError, IndexError):
            hx, hy = DEFAULT_HEAD_XY.get(head, (0.0, 0.0))
        d = {ch: math.hypot(x - hx, y - hy) for ch, (x, y, _) in self.lamp_xy.items()}
        if not d:
            return set()
        best = min(d.values())
        return {ch for ch, v in d.items() if v <= best * 1.35 + 0.05}

    def lamps(self, cols, channels, now, beats, pmode):
        """cols in streaming order (one per channel, before the flicker protection) -> the relay's lamps."""
        z = self.step(now, beats, pmode)
        if not cols:
            return cols
        self.v = max(max(c) for c in cols)                # the music's brightness right now
        if not z:
            return cols
        if self.rgb is None:                              # the hand-off: hold the brightest lamp's colour
            c = max(cols, key=lambda c_: max(c_))
            h, sat, v = colorsys.rgb_to_hsv(*[clamp(x) for x in c])
            self.rgb = colorsys.hsv_to_rgb(h, sat, 1.0) if v > 0.004 else None
            z['rgb'] = self.rgb
        if self.rgb is None:
            return cols
        h, sat, _ = colorsys.rgb_to_hsv(*self.rgb)
        dim = clamp(float(self.settings().get('chase_dim', 0.2)))
        lvl = z['heads'][z['head']]['level']
        glow = self.near(z['head'])
        v = max(self.v, 0.3)
        return [colorsys.hsv_to_rgb(h, sat, v * (dim + (1.0 - dim) * (lvl if ch in glow else 0.0)))
                for ch in channels]

    def describe(self, z):
        return 'relay: head %d lit (turn %d, %.0f%%)' % (z['head'] + 1, z['turn'], 100 * z['p']) if z else 'relay off'
