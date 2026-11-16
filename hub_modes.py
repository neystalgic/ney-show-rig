# =============================================================================
# HUE HUB -- the SHOW DIRECTOR: modes + zones + a new pattern every 8 bars     Nov 15, live with Michael
#
# Michael: "different modes that react differently with colour, head speed and rhythm, then go to a
# different audio-reactive but equally sick pattern every 8 bars ... zones, each doing something different."
#
# ZONES: Michael's calibrated map (setting show_zones, Nov 15: 1A, 1B, 2A, 2B, 3A numbered from the front door; a zone
# can be lamps only or a head only). Without it: one zone per head, lamps by the nearest head, left -> right.
#
# MODES (each one: colour behaviour + head motion + what part of the beat drives it)
#   pulse      one colour room-wide; every zone hits on the KICK; heads snap between two leans
#   call       call & response ACROSS the room: row A (south wall) answers the kick, row B (north wall) the snare
#   wave       down the room: column 1 (1A+1B) -> 2 (2A+2B) -> 3 (3A), one column per beat
#   loop       round the living room: 1A -> 2A -> 2B -> 1B -> 1A (setting show_loop), one zone per beat
#   directions: show_wave = bounce (default: 1-2-3-2-1) | forward | back | alternate (flips each phrase)
#               show_loop_dir = alternate (default, flips each phrase) | ccw (1A-2A-2B-1B) | cw (1A-1B-2B-2A)
#   split      row A (south) warm + big on the bass, row B (north) cool + quick on the hi-hats
#   orbit      heads trace slow circles out of phase; colour drifts; speed follows the energy
#   relay      one head at a time sweeps and hands off on the bar (hub_chase.py)
# Drops are NOT a mode here: in a drop the director steps aside and the normal show dances (+ strobe,
# sparingly) -- then a new mode starts after it.
#
# ACTS (Nov 15, Michael: "a firework show -- every element gets its moment, everything only for the finale"):
#   hues     Hue showcase: heads dark, each zone its own colour from across the palette, a soft chase round the room
#   heads    Head moment: lamps down to 8%, all four heads in UNISON -- sharp sweeps that snap on the beat
#   gobos    Gobos: heads + lamps near dark, the two spots throw slowly turning gobos, focus breathing
#   zones    the zone MODES below (wave, loop, call & response ...)
#   uv       UV reveal: total dark, only the spots' UV on the stars -- breakdowns only, so the drop BURSTS
#   (drop)   the burst / finale: the director steps aside, the full show + strobe take the drop
# ORDER: a shuffle bag, not a fixed cycle -- every act gets a turn before any repeats, the order changes each
# round, never the same act twice in a row; breakdowns pick from the dark acts (uv, gobos, hues).
# show_acts = false -> modes only.  show_lock may also name an act.  show_gobos = list of gobo-wheel values.
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
import random

import hub_chase

MODES = ['pulse', 'call', 'wave', 'loop', 'split', 'orbit', 'relay']
POOLS = {'groove': ['pulse', 'call', 'wave', 'loop', 'split', 'relay', 'orbit'],
         'breakdown': ['orbit', 'loop', 'relay', 'wave'],
         'quiet': ['orbit']}
NAMES = {'pulse': 'Pulse', 'call': 'Call & Response', 'wave': 'Wave', 'loop': 'Loop', 'split': 'Split',
         'orbit': 'Orbit', 'relay': 'Relay'}
ACTS = ['hues', 'heads', 'gobos', 'zones', 'uv']
ACT_NAMES = {'hues': 'Hue showcase', 'heads': 'Head moment', 'gobos': 'Gobos', 'zones': 'Zone modes', 'uv': 'UV reveal'}
GOBOS = [16, 32, 48, 64, 80, 96]  # Focus Spot One gobo-wheel values (check live; setting show_gobos overrides)
UV_AIMS = {4: {'az': 192, 'lean': 46}, 5: {'az': 180, 'lean': 65}}   # the stars (same as rig_control's UV sky)
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
        self.spots_i = []
        self.rng = random.Random()
        self.act = None
        self.act_bag = []
        self.act_hist = []
        self.mode_bag = []
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
        """{lamp channel: head index} (nearest head; chase_lamps names win) and the heads in room order.
        (Used by the fallback when no calibrated map exists.)"""
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

    def zone_list(self):
        """The zones in order: [{'id', 'heads': [node index], 'channels': [lamp channel]}].
        Setting show_zones (Michael's calibrated map, Nov 15) = {"order": ["1A", ...],
        "zones": {"1A": {"heads": [3], "lamps": ["Top Lamp", ...]}}} with heads numbered 1-4 like the room.
        Without it: one zone per head, left -> right, lamps by nearest head."""
        cfg = self.settings().get('show_zones')
        if isinstance(cfg, dict) and isinstance(cfg.get('zones'), dict) and cfg.get('order'):
            key = ('map', repr(cfg), tuple(self.heads_i))
            if self._zone_cache and self._zone_cache[0] == key:
                return self._zone_cache[1]
            by_name = {}
            for ch, (_, _, nm) in self.lamp_xy.items():
                by_name.setdefault(nm, []).append(ch)
            out = []
            for zid in cfg['order']:
                z = cfg['zones'].get(zid) or {}
                heads = [int(h) - 1 for h in (z.get('heads') or []) if str(h).isdigit() and int(h) - 1 in self.heads_i]
                chans = [c for nm in (z.get('lamps') or []) for c in by_name.get(nm, [])]
                if heads or chans:
                    out.append(dict(id=str(zid), heads=heads, channels=chans))
            if out:
                self._zone_cache = (key, out)
                return out
        lz, order = self.zones()
        return [dict(id='Head %d' % (h + 1), heads=[h], channels=[c for c, o in lz.items() if o == h]) for h in order]

    def grid(self, zl):
        """Zone ids like '2A' -> (column 2, row 'A'). Rows: A = south wall (gray couch), B = north (projector).
        Zones without that shape get their own column, row A."""
        import re
        out = []
        for k, z in enumerate(zl):
            m = re.match(r'^\s*(\d+)\s*([A-Za-z])\s*$', str(z['id']))
            out.append((int(m.group(1)), m.group(2).upper()) if m else (k, 'A' if k % 2 == 0 else 'B'))
        return out

    def direction(self, key, default, allowed):
        v = str(self.settings().get(key, default) or default).strip().lower()
        return v if v in allowed else default

    def wave_seq(self, cols):
        d = self.direction('show_wave', 'bounce', ('bounce', 'forward', 'back', 'alternate'))
        if d == 'alternate':
            d = 'forward' if (self.phrase or 0) % 2 == 0 else 'back'
        if d == 'back':
            return list(reversed(cols))
        if d == 'bounce' and len(cols) > 2:
            return cols + cols[-2:0:-1]                    # 1, 2, 3, 2 -> 1, 2, 3, 2 ...
        return list(cols)

    def loop_dir(self):
        d = self.direction('show_loop_dir', 'alternate', ('alternate', 'ccw', 'cw'))
        if d == 'alternate':
            d = 'ccw' if (self.phrase or 0) % 2 == 0 else 'cw'
        return d

    def loop_order(self, zl):
        ids = [z['id'] for z in zl]
        want = self.settings().get('show_loop')
        if isinstance(want, str):
            want = [x.strip() for x in want.split(',')]
        if not isinstance(want, list) or not want:
            g = self.grid(zl)
            cols = sorted({c for c, _ in g})
            a = [zl[i]['id'] for c in cols for i, (c2, r) in enumerate(g) if c2 == c and r == 'A']
            b = [zl[i]['id'] for c in reversed(cols) for i, (c2, r) in enumerate(g) if c2 == c and r == 'B']
            if a and b:                                   # out along the south wall, back along the north wall
                lastc = max(c for c, r in g if r == 'B')
                a = [zid for zid in a if self.grid([dict(id=zid)])[0][0] <= lastc]
            want = a + b
        out = [z for z in want if z in ids] or ids
        if self.loop_dir() == 'cw' and len(out) > 2:       # same start, the other way round
            out = [out[0]] + out[:0:-1]
        return out

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
        self.mode_bag = [m for m in self.mode_bag if m in pool]
        if not [m for m in self.mode_bag if m not in avoid]:
            bag = list(pool)                                  # a fresh, shuffled round of every mode
            self.rng.shuffle(bag)
            self.mode_bag = bag
        for m in self.mode_bag:
            if m not in avoid:
                self.mode_bag.remove(m)
                return m
        options = [m for m in pool if m != self.mode] or pool
        return self.rng.choice(options) if options else 'orbit'

    def acts_on(self):
        v = self.settings().get('show_acts', True)
        return v not in (False, 'false', 'off', 0, '0')

    def pick_act(self, section):
        lock = str(self.settings().get('show_lock', '') or '').strip().lower()
        if lock in ACTS:
            return lock
        if lock in MODES or not self.acts_on():
            return 'zones'
        has_spots = bool(self.spots_i)
        last = self.act_hist[-1] if self.act_hist else None
        if section == 'breakdown':                            # the dark acts build the tension before a drop
            cands = [a for a in (['uv', 'gobos'] if has_spots else []) + ['hues'] if a != last]
            if last != 'uv' and has_spots and self.rng.random() < 0.6:
                return 'uv'
            return self.rng.choice(cands or ['hues'])
        if section == 'quiet':
            return 'hues'
        groove = ['hues', 'heads', 'zones', 'zones'] + (['gobos'] if has_spots else [])
        self.act_bag = [a for a in self.act_bag if a in groove]
        if not [a for a in self.act_bag if a != last]:
            bag = list(groove)                                # every act once (zones twice: it has the most variety)
            self.rng.shuffle(bag)
            self.act_bag = bag
        for a in self.act_bag:
            if a != last:
                self.act_bag.remove(a)
                return a
        return 'zones'

    def tick_phrase(self, beats):
        bpb = int(self.settings().get('beats_per_bar', 4) or 4)
        bar = int(math.floor(beats / bpb))
        phrase = bar // self.bars_per_phrase()
        lock = str(self.settings().get('show_lock', '') or '').strip().lower()
        locked = (lock in MODES and (lock != self.mode or self.act != 'zones')) or (lock in ACTS and lock != self.act)
        if self.mode is None or phrase != self.phrase or locked:
            sec = self.section()
            act = self.pick_act(sec)
            self.act_hist = (self.act_hist + [act])[-6:]
            new = self.pick(sec) if act == 'zones' else self.mode
            if act == 'zones' and new != self.mode:
                self.history.append(new)
                self.history = self.history[-6:]
            self.act, self.mode, self.phrase = act, (new or 'orbit'), phrase
            self.hue_t = None
        return bar, bpb

    # -------------------------------------------------------------------------- one frame
    def step(self, now, beats, pmode, heads=None):
        if self._cache[0] == now:
            return self._cache[1]
        if heads is not None:
            hi = [i for i, h in enumerate(heads) if h.get('type') != 'focus17']
            self.spots_i = [i for i, h in enumerate(heads) if h.get('type') == 'focus17']
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
        if self.act != 'zones':
            out = self.act_frame(beats, bar, bpb)
            self._cache, self.last, self.active = (now, out), out, True
            return out
        if self.mode == 'relay':
            self.chase.forced = True                          # the relay runs on its own clock for this phrase
            zl_ = self.zone_list()
            byid = {z['id']: z for z in zl_}
            lo = self.loop_order(zl_)
            order = [h for zid in lo for h in byid[zid]['heads']] + [h for z in zl_ if z['id'] not in lo for h in z['heads']]
            if order and order != self.chase.relay_heads:     # hand-offs follow the zones from the front door
                self.chase.relay_heads, self.chase.idx = order, 0
            try:
                out = self.chase.step(now, beats, pmode, None if order else heads)
            finally:
                self.chase.forced = False
            if out:
                out = dict(out, mode='relay', act='zones', bar=bar, phrase_bar=bar % self.bars_per_phrase())
            self._cache, self.last, self.active = (now, out), out, out is not None
            return out
        # colour: one change per 2 bars at most (Michael: faster colour changes are distracting)
        if self.hue_t is None or bar - self.hue_t >= 2:
            if self.hue_t is not None:
                self.hue = (self.hue + (0.12 if self.mode in ('orbit', 'wave') else 0.2)) % 1.0
            self.hue_t = bar
        e, en = self.env(), self.energy()
        sp = self.speed()
        zl = self.zone_list()
        n = max(1, len(zl))
        frac = beats - math.floor(beats)
        bib = int(math.floor(beats)) % bpb                    # beat in bar
        hs, zout = {}, []
        g = self.grid(zl)
        cols = sorted({c for c, _ in g})
        loop = self.loop_order(zl)
        beat_i = int(math.floor(beats)) - (self.phrase or 0) * self.bars_per_phrase() * bpb   # beats into this phrase
        for r, zone in enumerate(zl):
            col, row = g[r]
            side = 0 if row == 'A' else 1                     # south wall (A) / north wall (B)
            lvl, lean, u, hue = 0.6, 0.6, 0.5, self.hue
            if self.mode == 'pulse':
                lvl = 0.2 + 0.8 * e['kick']
                lean = 0.85 if (int(math.floor(beats)) + r) % 2 == 0 else 0.45
                u = 0.5 + 0.12 * (1 if bar % 2 == 0 else -1) * (1 if r % 2 == 0 else -1)
            elif self.mode == 'call':
                a = side == 0
                hit = e['kick'] if a else e['snare']
                lvl = 0.12 + 0.88 * hit
                lean = 0.4 + 0.5 * hit
                u = 0.5 + 0.25 * math.sin(2 * math.pi * beats / (16.0 / sp)) * (1 if a else -1)
                hue = self.hue if a else self.hue + 0.5
            elif self.mode == 'wave':
                wseq = self.wave_seq(cols)
                on = wseq[beat_i % len(wseq)] == col
                lvl = 0.12 + 0.88 * (decay(frac, 0.45 / sp) if on else 0.0) + 0.25 * e['kick'] * (0 if on else 1)
                lean = 0.85 if on else 0.5
                u = 0.5 + 0.3 * math.sin(2 * math.pi * beats / (16.0 / sp))
                hue = self.hue + 0.08 * cols.index(col)
            elif self.mode == 'loop':
                if zone['id'] in loop:
                    on = loop[beat_i % len(loop)] == zone['id']
                    lvl = 0.1 + 0.9 * (decay(frac, 0.5 / sp) if on else 0.0)
                    lean = 0.8 if on else 0.45
                    u = 0.5 + 0.3 * math.sin(2 * math.pi * (beats / (8.0 / sp)) + loop.index(zone['id']) * math.pi / 2)
                    hue = self.hue + 0.06 * loop.index(zone['id'])
                else:                                         # outside the loop (the studio): a soft kick glow
                    lvl = 0.1 + 0.4 * e['kick']
                    lean, u, hue = 0.5, 0.5, self.hue + 0.5
            elif self.mode == 'split':
                if side == 0:                                 # south wall: warm, big + slow on the bass
                    lvl = 0.25 + 0.75 * e['kick']
                    lean = 0.6 + 0.3 * math.sin(2 * math.pi * beats / (8.0 / sp))
                    u = 0.5 + 0.3 * math.sin(2 * math.pi * beats / (16.0 / sp) + r)
                    hue = self.hue
                else:                                         # north wall: cool, small + quick on the hats
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
            rgb = hsv(hue, 0.9, 1.0)
            zout.append(dict(id=zone['id'], level=clamp(lvl), rgb=rgb, channels=zone['channels']))
            for h in zone['heads']:
                hs[h] = dict(level=clamp(lvl), lean=clamp(lean), u=clamp(u), rgb=rgb, zone=r)
        for h in self.heads_i:                                # a head in no zone stays dark
            hs.setdefault(h, dict(level=0.0, lean=0.5, u=0.5, rgb=hsv(self.hue), zone=None))
        out = dict(heads=hs, zones=zout, rgb=hsv(self.hue), v=self.v, head=None, turn=self.phrase, new=False, p=0.0,
                   mode=self.mode, act='zones', bar=bar, phrase_bar=bar % self.bars_per_phrase(), bib=bib)
        self._cache, self.last, self.active = (now, out), out, True
        return out

    # -------------------------------------------------------------------------- the featured acts
    def act_frame(self, beats, bar, bpb):
        if self.hue_t is None or bar - self.hue_t >= 2:      # colour holds 2 bars, like the modes
            if self.hue_t is not None:
                self.hue = (self.hue + 0.15) % 1.0
            self.hue_t = bar
        act = self.act
        e = self.env()
        zl = self.zone_list()
        loop = self.loop_order(zl)
        seq = loop + [z['id'] for z in zl if z['id'] not in loop]
        frac = beats - math.floor(beats)
        beat_i = int(math.floor(beats)) - (self.phrase or 0) * self.bars_per_phrase() * bpb
        dark = dict(level=0.0, lean=0.5, u=0.5, rgb=hsv(self.hue))
        hs = {h: dict(dark) for h in self.heads_i}
        zout, spots, floor = [], {}, 0.0
        if act == 'hues':                                    # every zone its own colour; a soft chase round the room
            for r, zone in enumerate(zl):
                on = seq[beat_i % len(seq)] == zone['id'] if seq else False
                lvl = 0.35 + 0.65 * (decay(frac, 0.6) if on else 0.25 * e['kick'])
                zout.append(dict(id=zone['id'], level=clamp(lvl), rgb=hsv(self.hue + 0.17 * r, 0.95), channels=zone['channels']))
        elif act == 'heads':                                 # lamps low; the four heads together, sharp + on the beat
            for zone in zl:
                zout.append(dict(id=zone['id'], level=0.08, rgb=hsv(self.hue), channels=zone['channels']))
            step = int(math.floor(beats)) // 2                # a new position every 2 beats, all heads at once
            lvl = 0.35 + 0.65 * max(e['kick'], decay(frac, 0.3))
            lean = 0.85 if (int(math.floor(beats)) // 4) % 2 == 0 else 0.45
            u = 0.2 if step % 2 == 0 else 0.8
            for h in self.heads_i:
                hs[h] = dict(level=clamp(lvl), lean=lean, u=u, rgb=hsv(self.hue), fast=True)
        elif act == 'gobos':                                 # the spots throw turning gobos; everything else near dark
            for zone in zl:
                zout.append(dict(id=zone['id'], level=0.06, rgb=hsv(self.hue), channels=zone['channels']))
            gl = self.settings().get('show_gobos') or GOBOS
            try:
                g = int(gl[(bar // 2) % len(gl)])
            except (TypeError, ValueError, IndexError, ZeroDivisionError):
                g = GOBOS[0]
            for i in self.spots_i:
                spots[i] = dict(level=0.9, fx=dict(gobo=g, gobo_rot=140, breathe=50, breathe_s=8.0, uv=0, uv_only=False))
        elif act == 'uv':                                    # total dark + UV on the stars (the drop bursts after it)
            for zone in zl:
                zout.append(dict(id=zone['id'], level=0.0, rgb=hsv(self.hue), channels=zone['channels']))
            for i in self.spots_i:
                aim = UV_AIMS.get(i, {'az': 180, 'lean': 50})
                spots[i] = dict(level=0.85, fx=dict(hold=dict(aim, drift=0), hold_when='always', hold_head=i, uv=1.0,
                                                    uv_only=True, gobo=0, focus=128))
        return dict(heads=hs, zones=zout, spots=spots, lamp_floor=floor, rgb=hsv(self.hue), v=self.v, head=None,
                    turn=self.phrase, new=False, p=0.0, mode=self.mode, act=act, bar=bar,
                    phrase_bar=bar % self.bars_per_phrase())

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
        if z.get('act', 'zones') == 'zones' and z.get('mode', 'relay') == 'relay':
            self.chase.forced = self.pattern() == 'modes'
            try:
                return self.chase.lamps(cols, channels, now, beats, pmode)
            finally:
                self.chase.forced = False
        zmap = {ch: zo for zo in z.get('zones', []) for ch in zo['channels']}
        v = max(self.v, 0.35)
        dim = float(z.get('lamp_floor', 0.15))
        out = []
        for ch in channels:
            zo = zmap.get(ch)
            if zo is None:
                out.append(hsv(self.hue, 0.9, v * dim))
                continue
            hh, ss, _ = colorsys.rgb_to_hsv(*zo['rgb'])
            out.append(colorsys.hsv_to_rgb(hh, max(ss, 0.55), v * (dim + (1.0 - dim) * zo['level'])))
        return out

    def describe(self, z=None):
        z = z if z is not None else self.last
        if not z:
            return 'modes off' if self.pattern() == 'modes' else self.chase.describe(None)
        m = z.get('mode', 'relay')
        a = z.get('act', 'zones')
        label = NAMES.get(m, m) if a == 'zones' else ACT_NAMES.get(a, a)
        return '%s (bar %d of %d)' % (label, z.get('phrase_bar', 0) + 1, self.bars_per_phrase())

    def status(self):
        z = self.last
        a = (z or {}).get('act', 'zones')
        return dict(on=bool(z), pattern=self.pattern(), act=a if z else None, act_name=ACT_NAMES.get(a, '') if z else '',
                    acts=[dict(id=x, name=ACT_NAMES[x]) for x in ACTS], acts_on=self.acts_on(),
                    mode=(z or {}).get('mode'), name=NAMES.get((z or {}).get('mode'), '') if a == 'zones' else ACT_NAMES.get(a, ''),
                    bar=(z or {}).get('phrase_bar', 0) + 1 if z else 0, bars=self.bars_per_phrase(),
                    lock=str(self.settings().get('show_lock', '') or ''), speed=self.speed(),
                    history=list(self.history[-4:]), section=self.section(),
                    zones=[dict(id=z['id'], heads=[h + 1 for h in z['heads']], lamps=len(z['channels'])) for z in self.zone_list()], modes=[dict(id=m, name=NAMES[m]) for m in MODES])
