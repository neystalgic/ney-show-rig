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
#   burst    DROPS: every zone in a rainbow that steps on the beat, heads big + fast in unison, everything
#            FLASHING ON THE KICK (no timer strobe) -- the finale
# show_audio 0..1 (default 0.6): how much the music's hits drive it vs the BUILT-IN DRUMMER on the beat clock
#   (kick every beat, snare 2 + 4, hats 8ths); 2 s of silence -> the drummer alone. 'Semi audio reactive.'
# Nov 15 v2 (Michael: low reactivity, not full brightness, no zones, no switches, random strobes, no rainbows):
#   levels follow the real drum hits, normalised to the track (kick/snare/hats 0..1 relative to recent peaks);
#   everything reaches full brightness; colours walk the rainbow in sync (a step every 2 bars).
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
# RAINBOW MUSIC SHOW (Nov 18, Michael: "a complete audio reactive rainbow light show ... feel everything come alive
# in harmony to music I made myself"). Setting dmx_pattern = 'rainbow'. Built from his review scores (Nov 17: steps 10,
# chase 9, breath 8.5, ripple 8, all-out 8) and his rules: each group (lamps / heads / spots) in sync with itself,
# ROY G BIV only (no pink), SNAP + contrast (hits on the kick, real darkness between), heads jump between positions.
#   groove     a new rainbow piece every 8 bars from STEPS (colour snaps every 2 beats, everything punches on the kick),
#              CHASE (one zone per beat, the rest dark, a new colour each step) and RIPPLE (colour rolls out from the
#              studio desk toward the door, a step every 2 beats); never the same piece twice in a row
#   drop       ALL-OUT: colour snaps EVERY beat, heads jump on every beat (adjacent colour, never clashing), spots
#              throw a new gobo each beat, everything flashes on the kick -- no strobe
#   breakdown  BREATH: one colour per 2 bars, the room breathes over 4 bars, heads drift low, spots UV on the tapestry
# The visuals follow by themselves: hub_visuals sends TouchDesigner the lamps' real colours + the drums.
# POCKET (Nov 18, Michael: "a complex pocket with large dynamic shifts -- I'd like the heads and spots to snap with it"):
#   while the music is playing, the SNAPS follow his actual hits, not the beat grid -- every kick moves the colour /
#   the chase on, every snare jumps the heads, hats + snares turn the spot gobos; brightness is his drums only (no
#   built-in drummer mixed in). 2 s without hits -> the beat clock takes over so the room never dies.
import colorsys
import math
import random

import hub_chase

RB = [(1.0, 0.0, 0.0), (1.0, 0.35, 0.0), (1.0, 0.82, 0.0), (0.0, 1.0, 0.12), (0.0, 0.43, 1.0), (0.24, 0.0, 1.0),
      (0.67, 0.0, 1.0)]               # ROY G BIV -- Michael's rainbow, no pink
RB_SLOT = [22, 22, 67, 52, 37, 97, 97]   # the Focus Spot colour-wheel slot nearest each
RB_GROOVE = ['steps', 'chase', 'ripple', 'scatter']
RB_NAMES = {'scatter': 'Rainbow scatter', 'steps': 'Rainbow steps', 'chase': 'Rainbow chase', 'ripple': 'Rainbow ripple', 'allout': 'All-out rainbow',
            'breath': 'Rainbow breath'}

MODES = ['pulse', 'call', 'wave', 'loop', 'split', 'orbit', 'relay']
POOLS = {'groove': ['pulse', 'call', 'wave', 'loop', 'split', 'relay', 'orbit'],
         'breakdown': ['orbit', 'loop', 'relay', 'wave'],
         'quiet': ['orbit']}
NAMES = {'pulse': 'Pulse', 'call': 'Call & Response', 'wave': 'Wave', 'loop': 'Loop', 'split': 'Split',
         'orbit': 'Orbit', 'relay': 'Relay'}
ACTS = ['hues', 'heads', 'gobos', 'zones', 'uv', 'burst']
ACT_NAMES = {'hues': 'Hue showcase', 'heads': 'Head moment', 'gobos': 'Gobos', 'zones': 'Zone modes', 'uv': 'UV reveal',
             'burst': 'Burst (drop)'}
RAINBOW_STEP = 1.0 / 7.0          # the colour walks the rainbow: one of 7 steps every 2 bars
GOBOS = [16, 32, 48, 64, 80, 96]  # Focus Spot One gobo-wheel values (check live; setting show_gobos overrides)
UV_AIMS = {4: {'az': 197.0, 'lean': 40.0}, 5: {'az': 191.2, 'lean': 67.0}}   # tapestry centres (Nov 17, Michael)   # the stars (same as rig_control's UV sky)
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
        if section == 'drop':                                 # Nov 18: the relay steps aside in drops -> a drop that
            p = [m for m in p if m != 'relay'] or p           # drew it went dark (~1 in 5): never deal it in a drop
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
                spots = [3 + int(sp) for sp in (z.get('spots') or []) if str(sp).isdigit()]   # Spot 1/2 -> node 4/5
                if heads or chans or spots:
                    out.append(dict(id=str(zid), heads=heads, channels=chans, spots=spots))
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
        if pat not in ('modes', 'rainbow'):
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
        return 'modes'                                        # drops too: the BURST act (kick-locked, no timer strobe)

    def section(self):
        return getattr(getattr(self.hub, 'audioshow', None), 'section', 'groove') or 'groove'

    def audio_mix(self):
        try:
            return clamp(float(self.settings().get('show_audio', 0.6)))
        except (TypeError, ValueError):
            return 0.6

    def clock_hits(self, beats):
        """The built-in drummer (Michael, Nov 15: 'semi audio reactive -- not entirely reliant on the audio'):
        kick every beat, snare on 2 + 4, hats on the 8ths, from the beat clock."""
        b = beats if beats is not None else 0.0
        bi = math.floor(b)
        f = b - bi
        bpb = int(self.settings().get('beats_per_bar', 4) or 4)
        f8 = b * 2 - math.floor(b * 2)
        return dict(kick=decay(f, 0.22), snare=decay(f, 0.18) if bi % bpb in (1, 3) else 0.0, hats=0.6 * decay(f8, 0.1))

    def env(self, beats=None, now=None):
        """Drum hits 0..1: the music's own hits (normalised to this track's recent peaks) blended with the
        built-in drummer by show_audio (1 = audio only, 0 = clock only, default 0.6). If the music goes quiet
        for 2 s the drummer carries the show alone."""
        a = self.audio_hits()
        w = self.audio_mix()
        if beats is None or w >= 1.0:
            return a
        c = self.clock_hits(beats)
        loud = max(a.values())
        t = now if now is not None else getattr(self, '_t_now', 0.0)
        if loud > 0.2:
            self._heard_t = t
        if t - getattr(self, '_heard_t', -99.0) > 2.0:
            w = 0.0
        return {k: clamp(w * a[k] + (1.0 - w) * c[k]) for k in a}

    def audio_hits(self):
        """Drum hits 0..1, normalised to this track's recent peaks (so every song reaches full range)."""
        e = getattr(getattr(self.hub, 'audioshow', None), 'env', None) or {}
        pk = getattr(self, '_peaks', None)
        if pk is None:
            pk = self._peaks = dict(kick=0.3, snare=0.3, hats=0.3)
        out = {}
        for k in ('kick', 'snare', 'hats'):
            v = clamp(float(e.get(k, 0.0) or 0.0))
            pk[k] = max(v, pk[k] * 0.9985, 0.15)       # a slowly falling peak (~10 s at 60 fps)
            out[k] = clamp(v / pk[k])
        return out

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
        if section == 'drop':
            return 'burst'
        if section == 'breakdown':                            # the dark acts build the tension before a drop
            cands = [a for a in (['uv', 'gobos'] if has_spots else []) + ['hues'] if a != last]
            if last != 'uv' and has_spots and self.rng.random() < 0.6:
                return 'uv'
            return self.rng.choice(cands or ['hues'])
        if section == 'quiet' and self.audio_mix() >= 1.0:
            return 'hues'
        groove = ['zones', 'hues', 'zones', 'heads', 'zones'] + (['gobos'] if has_spots else [])   # zones lead
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
        sec = self.section()
        flip = (sec == 'drop') != (self.act == 'burst') and not (lock in ACTS or lock in MODES)
        if self.mode is None or phrase != self.phrase or locked or flip:
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
        # Nov 19 BUG FIX (Michael: "the spots aren't doing a damn thing"): the lamps call step() first each frame
        # WITHOUT the fixture list and the DMX call hit that cached frame, so the director never learned there were
        # spots -- they never got a single cue. Learn the fixtures BEFORE the cache, and redo a frame that was
        # built before the spots were known.
        if heads is not None:
            hi = [i for i, h in enumerate(heads) if h.get('type') != 'focus17']
            sp = [i for i, h in enumerate(heads) if h.get('type') == 'focus17']
            if sp != self.spots_i:
                self.spots_i, self._cache = sp, (None, None)
            if hi != self.heads_i:
                self.heads_i, self._zone_cache, self._cache = hi, None, (None, None)
        if self._cache[0] == now:
            return self._cache[1]
        self._t_now = now
        w = self.wanted(pmode)
        if w == 'relay':
            out = self.chase.step(now, beats, pmode, heads)
            self._cache, self.last, self.active = (now, out), out, out is not None
            return out
        if w is None or not self.heads_i:
            self.active, self.last = False, None
            self._cache = (now, None)
            return None
        if self.pattern() == 'rainbow':
            out = self.rainbow_frame(beats, now)
            self._cache, self.last, self.active = (now, out), out, True
            return out
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
        if self.hue_t is None or bar - self.hue_t >= 2:   # the rainbow walk: one step every 2 bars, in sync
            if self.hue_t is not None:
                self.hue = (self.hue + RAINBOW_STEP) % 1.0
            self.hue_t = bar
        e, en = self.env(beats, now), self.energy()
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
                lvl = 0.08 + 0.92 * e['kick']
                lean = 0.85 if (int(math.floor(beats)) + r) % 2 == 0 else 0.45
                u = 0.5 + 0.12 * (1 if bar % 2 == 0 else -1) * (1 if r % 2 == 0 else -1)
            elif self.mode == 'call':
                a = side == 0
                hit = e['kick'] if a else e['snare']
                lvl = 0.06 + 0.94 * hit
                lean = 0.4 + 0.5 * hit
                u = 0.5 + 0.25 * math.sin(2 * math.pi * beats / (16.0 / sp)) * (1 if a else -1)
                hue = self.hue if a else self.hue + 0.5
            elif self.mode == 'wave':
                wseq = self.wave_seq(cols)
                on = wseq[beat_i % len(wseq)] == col
                lvl = (0.4 + 0.6 * max(e['kick'], decay(frac, 0.3 / sp))) if on else 0.03 + 0.12 * e['kick']
                lean = 0.85 if on else 0.5
                u = 0.5 + 0.3 * math.sin(2 * math.pi * beats / (16.0 / sp))
                hue = self.hue + cols.index(col) / float(max(1, len(cols)))     # a rainbow down the room
            elif self.mode == 'loop':
                if zone['id'] in loop:
                    on = loop[beat_i % len(loop)] == zone['id']
                    lvl = (0.4 + 0.6 * max(e['kick'], decay(frac, 0.3 / sp))) if on else 0.03 + 0.1 * e['kick']
                    lean = 0.8 if on else 0.45
                    u = 0.5 + 0.3 * math.sin(2 * math.pi * (beats / (8.0 / sp)) + loop.index(zone['id']) * math.pi / 2)
                    hue = self.hue + loop.index(zone['id']) / float(max(1, len(loop)))   # a rainbow round the loop
                else:                                         # outside the loop (the studio): pulses on the kick
                    lvl = 0.1 + 0.9 * e['kick']
                    lean, u, hue = 0.5, 0.5, self.hue + 0.5
            elif self.mode == 'split':
                if side == 0:                                 # south wall: warm, big + slow on the bass
                    lvl = 0.06 + 0.94 * e['kick']
                    lean = 0.6 + 0.3 * math.sin(2 * math.pi * beats / (8.0 / sp))
                    u = 0.5 + 0.3 * math.sin(2 * math.pi * beats / (16.0 / sp) + r)
                    hue = self.hue
                else:                                         # north wall: cool, small + quick on the hats
                    lvl = 0.06 + 0.94 * max(e['hats'], e['snare'])
                    lean = 0.55 + 0.15 * math.sin(2 * math.pi * beats / (2.0 / sp))
                    u = 0.5 + 0.1 * math.sin(2 * math.pi * beats / (2.0 / sp) + r)
                    hue = self.hue + 0.33
            elif self.mode == 'orbit':
                k = (0.6 + 0.8 * en) * sp
                ph = 2 * math.pi * beats / (16.0 / k) + r * math.pi / 2.0
                lvl = 0.3 + 0.7 * max(e['kick'], 0.5 * e['snare'])
                lean = 0.55 + 0.3 * math.cos(ph)
                u = 0.5 + 0.35 * math.sin(ph)
                hue = self.hue + r / float(n)                 # the heads circle in rainbow order
            rgb = hsv(hue, 0.9, 1.0)
            zout.append(dict(id=zone['id'], level=clamp(lvl), rgb=rgb, channels=zone['channels']))
            for h in zone['heads']:
                hs[h] = dict(level=clamp(lvl), lean=clamp(lean), u=clamp(u), rgb=rgb, zone=r)
        for h in self.heads_i:                                # a head in no zone stays dark
            hs.setdefault(h, dict(level=0.0, lean=0.5, u=0.5, rgb=hsv(self.hue), zone=None))
        out = dict(heads=hs, zones=zout, rgb=hsv(self.hue), v=self.v, head=None, turn=self.phrase, new=False, p=0.0,
                   full=True, mode=self.mode, act='zones', bar=bar, phrase_bar=bar % self.bars_per_phrase(), bib=bib)
        self._cache, self.last, self.active = (now, out), out, True
        return out

    # -------------------------------------------------------------------------- the featured acts
    def act_frame(self, beats, bar, bpb):
        if self.hue_t is None or bar - self.hue_t >= 2:      # the rainbow walk, like the modes
            if self.hue_t is not None:
                self.hue = (self.hue + RAINBOW_STEP) % 1.0
            self.hue_t = bar
        act = self.act
        e = self.env(beats, getattr(self, '_t_now', None))
        zl = self.zone_list()
        loop = self.loop_order(zl)
        seq = loop + [z['id'] for z in zl if z['id'] not in loop]
        frac = beats - math.floor(beats)
        beat_i = int(math.floor(beats)) - (self.phrase or 0) * self.bars_per_phrase() * bpb
        dark = dict(level=0.0, lean=0.5, u=0.5, rgb=hsv(self.hue))
        hs = {h: dict(dark) for h in self.heads_i}
        zout, spots, floor = [], {}, 0.0
        if act == 'hues':                                    # a full rainbow across the zones, every lamp hitting on the kick,
            n_ = max(1, len(zl))                             # the rainbow turning one zone each bar
            for r, zone in enumerate(zl):
                on = seq[beat_i % len(seq)] == zone['id'] if seq else False
                lvl = 0.12 + 0.88 * max(e['kick'], decay(frac, 0.35) if on else 0.0)
                zout.append(dict(id=zone['id'], level=clamp(lvl), rgb=hsv(self.hue + (r + bar) / float(n_), 1.0),
                                 channels=zone['channels']))
        elif act == 'heads':                                 # lamps low; the four heads together, sharp + on the beat
            for zone in zl:
                zout.append(dict(id=zone['id'], level=0.08, rgb=hsv(self.hue), channels=zone['channels']))
            step = int(math.floor(beats)) // 2                # a new position every 2 beats, all heads at once
            lvl = 0.15 + 0.85 * max(e['kick'], e['snare'])
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
                spots[i] = dict(level=0.9, fx=dict(gobo=g, gobo_rot=0, breathe=50, breathe_s=8.0, uv=0, uv_only=False))   # static: rotating wheels drift apart
        elif act == 'burst':                                 # DROP: everything, rainbow stepping on the beat, flashing on the kick
            n_ = max(1, len(zl))
            step_ = int(math.floor(beats))
            flash = max(e['kick'], 0.6 * e['snare'])
            for r, zone in enumerate(zl):
                zout.append(dict(id=zone['id'], level=clamp(0.1 + 0.9 * flash), rgb=hsv(self.hue + (r + step_) / float(n_), 1.0),
                                 channels=zone['channels']))
            hstep = step_ % 2
            for k_, h in enumerate(self.heads_i):
                hs[h] = dict(level=clamp(0.1 + 0.9 * flash), lean=0.85 if hstep == 0 else 0.4, u=0.15 if hstep == 0 else 0.85,
                             rgb=hsv(self.hue + (k_ + step_) / float(max(1, len(self.heads_i))), 1.0), fast=True)
            for i in self.spots_i:
                spots[i] = dict(level=clamp(0.1 + 0.9 * e['kick']), fx=dict(gobo=0, uv=0, uv_only=False))
        elif act == 'uv':                                    # total dark + UV on the stars (the drop bursts after it)
            for zone in zl:
                zout.append(dict(id=zone['id'], level=0.0, rgb=hsv(self.hue), channels=zone['channels']))
            for i in self.spots_i:
                aim = UV_AIMS.get(i, {'az': 180, 'lean': 50})
                spots[i] = dict(level=0.85, fx=dict(hold=dict(aim, drift=0), hold_when='always', hold_head=i, uv=1.0,
                                                    uv_only=True, gobo=0, focus=128))
        return dict(heads=hs, zones=zout, spots=spots, lamp_floor=floor, full=True, rgb=hsv(self.hue), v=self.v, head=None,
                    turn=self.phrase, new=False, p=0.0, mode=self.mode, act=act, bar=bar,
                    phrase_bar=bar % self.bars_per_phrase())

    # -------------------------------------------------------------------------- the rainbow music show
    # -------------------------------------------------------------------------- THE WAVE ORDER (Nov 19)
    # Michael: "the wave is only cool when things go precisely 1 by 1" -- the fixtures in the frame he films from
    # (facing the studio), every lamp its own fixture (Top Lamp and the other 1A bulb apart), in this order:
    CHASE_SEQ = ['Head 1', 'Head 2', 'Play', 'Spot 2', 'Head 3', 'Top Lamp', 'Hue color lamp 2', 'Floor Shade', 'Head 4',
                 'Spot 1']

    def chase_seq(self):
        """-> [(kind, key, lamp channels)]: ('h', head index), ('s', spot node index), ('l', lamp name, [channels]).
        Setting chase_seq overrides the order. Names that aren't in the rig are skipped."""
        want = self.settings().get('chase_seq') or self.CHASE_SEQ
        key = (repr(want), tuple(self.heads_i), tuple(self.spots_i), tuple(sorted(self.lamp_xy)))
        c = getattr(self, '_seq_cache', None)
        if c and c[0] == key:
            return c[1]
        by_name = {}
        for ch, (_, _, nm) in self.lamp_xy.items():
            by_name.setdefault(nm, []).append(ch)
        out = []
        for item in want:
            t = str(item).strip()
            low = t.lower()
            if low.startswith('head ') and low[5:].isdigit():
                h = int(low[5:]) - 1
                if h in self.heads_i:
                    out.append(('h', h, []))
            elif low.startswith('spot ') and low[5:].isdigit():
                i = 3 + int(low[5:])
                if i in self.spots_i:
                    out.append(('s', i, []))
            else:
                nm = next((n for n in by_name if n.lower() == low), None) or next((n for n in by_name if low in n.lower()), None)
                if nm:
                    out.append(('l', nm, by_name[nm]))
        self._seq_cache = (key, out)
        return out

    SLOT_RGB = {22: (1.0, 0.0, 0.0), 67: (1.0, 0.82, 0.0), 52: (0.0, 1.0, 0.12), 37: (0.0, 0.43, 1.0),
                97: (0.67, 0.0, 1.0), 82: (1.0, 0.2, 0.6)}

    def fixture_states(self, z=None):
        """Nov 19 (the visualizer mirrors the room): every fixture of the wave, in Michael's order ->
        [{'name', 'kind', 'rgb', 'level'}] from the newest frame (any piece, not only the chase)."""
        z = z if z is not None else self.last
        out = []
        if not z or z.get('act') != 'rainbow':
            return out
        lamp_lv = {}
        for zo in z.get('zones') or []:
            for ch in zo.get('channels') or []:
                if zo.get('level', 0.0) >= lamp_lv.get(ch, (0.0, None))[0]:
                    lamp_lv[ch] = (zo.get('level', 0.0), zo.get('rgb'))
        names = {'h': 'Head %d', 's': 'Spot %d'}
        for kind, key, chans in self.chase_seq():
            if kind == 'l':
                lv, c = max((lamp_lv.get(ch, (0.0, None)) for ch in chans), key=lambda x: x[0], default=(0.0, None))
                out.append(dict(name=key, kind='lamp', rgb=list(c or (0, 0, 0)), level=round(clamp(lv), 3)))
            elif kind == 'h':
                cv = (z.get('heads') or {}).get(key) or {}
                out.append(dict(name=names['h'] % (key + 1), kind='head', rgb=list(cv.get('rgb') or (0, 0, 0)),
                                level=round(clamp(cv.get('level', 0.0)), 3)))
            else:
                sp = (z.get('spots') or {}).get(key) or {}
                fx = sp.get('fx') or {}
                out.append(dict(name=names['s'] % (key - 3), kind='spot', rgb=list(self.SLOT_RGB.get(fx.get('color'), (0.6, 0.0, 1.0))),
                                level=round(clamp(sp.get('level', 0.0)), 3)))
        return out

    # -------------------------------------------------------------------------- SCATTER (Nov 19)
    # Michael: "I want each small transient to affect a DIFFERENT light, including the heads and the spots."
    # Every transient (kick, snare, hat -- the small ones too) lights ONE fixture: a lamp zone, a single head or a
    # single spot, dealt from a shuffled deck so the next hit always lands somewhere else. Every hit is the NEXT
    # colour in ROY G BIV. Each fixture flares and dies away on its own (lamps a little slower than the DMX), so a
    # busy pocket leaves a moving trail around the room. Heads hold still (calm); only light moves.
    def scatter(self, zl, now, live, bn, e):
        st = self.__dict__.setdefault('_sc', dict(prev=None, deck=[], last=None, ci=-1, fx={}, bn=None))
        pool = [('z', z['id']) for z in zl] + [('h', h) for h in self.heads_i] + [('s', i) for i in self.spots_i]
        if live:
            tr = (getattr(self, '_pk', None) or {}).get('tr') or {}
            cur = sum(int(tr.get(k, 0)) for k in ('kick', 'snare', 'hats'))
            new = 0 if st['prev'] is None else max(0, min(6, cur - st['prev']))
            st['prev'] = cur
            amp = max(0.45, max(float(e.get(k, 0.0)) for k in ('kick', 'snare', 'hats')))
        else:                                               # silence: one hit a beat on the clock
            new = 1 if (st['bn'] is not None and bn != st['bn']) else 0
            st['bn'], st['prev'] = bn, None
            amp = 0.8
        for _ in range(new):
            if not st['deck']:
                st['deck'] = [f for f in pool if f != st['last']]
                self.rng.shuffle(st['deck'])
            f = st['deck'].pop(0)
            if f not in pool:
                continue
            st['ci'] = (st['ci'] + 1) % len(RB)
            st['last'] = f
            st['fx'][f] = (now, (st['ci'] + getattr(self, '_coff', 0)) % len(RB), clamp(amp))
        st['fx'] = {f: v for f, v in st['fx'].items() if f in pool and now - v[0] < 2.0}

        def lvl(f, tau):
            v = st['fx'].get(f)
            if not v:
                return 0.0, None
            return v[2] * math.exp(-max(0.0, now - v[0]) / tau), v[1]
        zout, hs, spots = [], {}, {}
        for z in zl:
            l_, c = lvl(('z', z['id']), 0.35)
            zout.append(dict(id=z['id'], level=clamp(l_), rgb=RB[c] if c is not None else RB[max(0, st['ci']) % len(RB)],
                             channels=z['channels']))
        for h in self.heads_i:
            l_, c = lvl(('h', h), 0.2)
            hs[h] = dict(level=clamp(l_), u=0.5, lean=0.6, rgb=RB[c] if c is not None else RB[0])
        for i in self.spots_i:
            l_, c = lvl(('s', i), 0.2)
            c = c if c is not None else 0
            spots[i] = dict(level=clamp(l_), fx=dict(gobo=GOBOS[c % len(GOBOS)], color=RB_SLOT[c], gobo_rot=0, uv=0,
                                                     uv_only=False, breathe=0))
        return zout, hs, spots, 0.0

    def vj(self):
        """Nov 18: VJ ON THE MUSIC (Tap Dial hold 4) -- setting rb_vj = {piece, freeze, hit: {kind, t, n}}. The music
        keeps driving every hit; Michael's dial picks the piece, his taps add moments on top."""
        v = self.settings().get('rb_vj')
        return v if isinstance(v, dict) else {}

    def rb_pick(self, sec, phrase):
        """The piece for this phrase: drops = all-out, breakdowns / quiet = breath, grooves = a shuffled favourite."""
        p = str(self.vj().get('piece') or '')
        if p in RB_NAMES:                                    # VJ: Michael's pick wins, whatever the section
            return p
        if sec == 'drop':
            return 'allout'
        if sec in ('breakdown', 'quiet'):
            return 'breath'
        lock = str(self.settings().get('show_lock', '') or '').strip().lower()
        if lock in RB_GROOVE:
            return lock
        last = getattr(self, 'rb_sub', None)
        fav = str(self.settings().get('rb_favourite', 'chase') or '').strip().lower()
        if fav in RB_GROOVE and self.settings().get('rb_fav_always', False):   # Nov 19 eve: "it's only on one mode" ->
                                                                             # chase every other phrase, the rest between
            return fav                                     # Nov 19, Michael: THE ONE he loves (Nov 18 noon) -- every groove
        if fav in RB_GROOVE and last != fav:               # Nov 18, Michael: "colour to colour, one fixture at a time on
            return fav                                     # the transients -- super professional": chase every other phrase
        bag = [m for m in getattr(self, 'rb_bag', []) if m != last and m != fav]
        if not bag:
            bag = [m for m in RB_GROOVE if m != last and m != fav]
            self.rng.shuffle(bag)
        nxt = bag.pop(0)
        self.rb_bag = bag
        return nxt

    def pocket(self, now):
        """His pocket: onsets of the music's own kick / snare / hats, counted.
        Levels are normalised to a SLOW peak (~30 s), so a quiet verse after a loud drop stays quiet (the dynamics
        survive) while its hits still snap. An onset = a fresh rise of 0.22+ above the dip since the last hit, so
        quiet hits snap too but a decaying tail never does. -> (counts, live) -- live = music heard in the last 2 s."""
        env = getattr(getattr(self.hub, 'audioshow', None), 'env', None) or {}
        st = getattr(self, '_pk', None)
        if st is None:
            z = dict(kick=0.0, snare=0.0, hats=0.0)
            st = self._pk = dict(pk=dict(kick=0.3, snare=0.3, hats=0.3), lo=dict(z), last=dict(kick=-9.0, snare=-9.0, hats=-9.0),
                                 n=dict(kick=0, snare=0, hats=0), heard=-99.0, t=now, a=dict(z))
        dt = clamp(now - st['t'], 0.0, 1.0)
        st['t'] = now
        fall = math.exp(-dt / 30.0)
        a = {}
        for k in ('kick', 'snare', 'hats'):
            raw = clamp(float(env.get(k, 0.0) or 0.0))
            st['pk'][k] = max(raw, st['pk'][k] * fall, 0.12)
            v = a[k] = clamp(raw / st['pk'][k])
            if raw > 0.02:
                st['heard'] = now
            if v > 0.12 and v - st['lo'][k] > 0.22 and now - st['last'][k] > 0.09:   # a fresh hit
                st['n'][k] += 1
                st['last'][k] = now
                st['lo'][k] = v
            elif now - st['last'][k] < 0.15:                  # still the attack of that hit: no double fire
                st['lo'][k] = v
            else:
                st['lo'][k] = min(st['lo'][k], v)
        # the song's DYNAMICS: raw loudness against its loudest moment of the last ~half minute. The hit detector is
        # scale-free (a quiet verse still snaps) -- this is what keeps that verse dimmer than the drop.
        f = getattr(getattr(self.hub, 'audioshow', None), 'feat', None) or {}
        db = f.get('db') if isinstance(f, dict) else None
        dyn = 1.0
        if isinstance(db, (int, float)) and db > -100.0:
            st['dbpk'] = max(db, st.get('dbpk', db) - 0.6 * dt)       # loudest recent moment, sinking 0.6 dB a second
            dyn = clamp(1.0 + (db - st['dbpk']) / 20.0)               # 20 dB under the peak -> the floor
        st['dyn'] = dyn
        st['a'] = a
        # the SNAPS: tight = every hit heard (before the lamps' flicker governor), loose = only the big, lamp-grade
        # hits. No audio input object (tests / no sound card) -> the onsets counted above.
        # default LOOSE (Nov 18, live test: the raw detector heard ~5 'snares' a second in Michael's track -- synth
        # stabs -- so the big moves follow the clean, lamp-grade hits; 'pocket tight' opts into every hit)
        feel = str(self.settings().get('pocket_feel', 'loose') or 'loose').lower()
        au = getattr(self.hub, 'audio', None)
        src = None
        if feel == 'loose':
            src = getattr(getattr(self.hub, 'audioshow', None), 'counts', None)
        elif au is not None:
            src = getattr(au, 'pocket_hits', None)
        if isinstance(src, dict) and all(isinstance(src.get(k), int) for k in ('kick', 'snare', 'hats')):
            n = dict(kick=src['kick'], snare=src['snare'], hats=src['hats'])
        else:
            n = st['n']
        # the DMX punch: the heads + spots flash on EVERY hit (tight), the lamps stay on the governed envelope
        d = dict(a)
        last = getattr(au, 'pocket_last', None) if feel != 'loose' else None
        if isinstance(last, dict):
            for k in ('kick', 'snare', 'hats'):
                t0, s0 = last.get(k, (-100.0, 0.0))
                age = now - t0
                if 0.0 <= age < 1.0:
                    d[k] = max(d[k], clamp(0.65 + 0.35 * s0) * math.exp(-age / 0.12))
        st['d'] = d
        # SCATTER (Nov 19): every small transient, heard before any lamp governor -- one fixture each
        raw = getattr(au, 'pocket_hits', None) if au is not None else None
        st['tr'] = dict(raw) if isinstance(raw, dict) and all(isinstance(raw.get(k), int) for k in ('kick', 'snare', 'hats')) \
            else dict(st['n'])
        return n, now - st['heard'] < 2.0

    # -------------------------------------------------------------------------- glitches (Nov 18)
    # Michael: "react to the glitches in my music to give off the impression of sentience". hub_glitch hears them;
    # the room answers -- rarely, and on purpose:
    #   gap      (the music drops out)       -> the whole room holds its breath: dark until the sound comes back
    #   stutter  (a beat repeat / stutter)   -> time stops: every fixture freezes on the frame it was on
    #   crush    (a noise / bitcrush burst)  -> one fixture NOTICES: a single lamp zone flares white for 0.35 s
    #   jump     (a hard cut, a tape stop)   -> the rainbow SKIPS: the colours jump three steps on and carry on there
    def glitch(self, now):
        if str(self.settings().get('glitch_on', True)).lower() in ('false', '0', 'off'):
            return {}
        au = getattr(self.hub, 'audio', None)
        g = getattr(getattr(au, 'an', None), 'glitch', None)
        st = getattr(self, '_gl', None)
        if st is None:
            st = self._gl = dict(shift=0, seen=0, crush_until=-1.0, crush_zone=None, frozen=None)
        evs = list(getattr(au, 'glitch_events', None) or [])
        for i, (t, kind, s_, d_) in enumerate(evs):
            key = (t, kind)
            if key in st.setdefault('done', set()):
                continue
            st['done'].add(key)
            if now - t > 1.0:
                continue                                     # old news (e.g. right after a restart)
            if kind == 'jump':
                st['cut_until'] = t + 0.25                   # Nov 18 eve: the rainbow ORDER is sacred -> a cut, not a skip
            elif kind == 'crush':
                st['crush_until'] = t + 0.35
                st['crush_zone'] = None                      # picked when drawn
        if len(st.get('done', ())) > 200:
            st['done'] = set(list(st['done'])[-50:])
        gap = bool(g is not None and g.gap)
        stut = bool(g is not None and g.stutter)
        if not stut:
            st['frozen'] = None
        cut = now < st.get('cut_until', -1.0)
        nowk = 'gap' if (gap or cut) else 'stutter' if stut else 'crush' if now < st['crush_until'] else None
        return dict(shift=0, gap=gap or cut, stutter=stut, crush=now < st['crush_until'], now=nowk)

    def vj_look(self, vj, now, zout, hs, spots, floor):
        import copy
        st = self.__dict__.setdefault('_vjs', dict(frozen=None, skip_seen=None, shift=0))
        hit = vj.get('hit') if isinstance(vj.get('hit'), dict) else {}
        kind = hit.get('kind')
        try:
            age = now - float(hit.get('t', -99.0))
        except (TypeError, ValueError):
            age = 99.0
        if vj.get('freeze'):                                 # tap 4: the whole room holds this frame
            if st['frozen'] is None:
                st['frozen'] = copy.deepcopy((zout, hs, spots, floor))
            return copy.deepcopy(st['frozen'])
        st['frozen'] = None
        if kind == 'colour' and 0.0 <= age < 1.0:            # tap 1: everything flashes the colour of the moment
            c = next((zo['rgb'] for zo in zout if zo.get('level', 0.0) > 0.01), zout[0]['rgb'] if zout else RB[0])
            for zo in zout:
                zo['rgb'], zo['level'] = c, 1.0
            for cv in hs.values():
                cv['rgb'], cv['level'] = c, 1.0
            for sp in spots.values():
                sp['level'] = 1.0
                if isinstance(sp.get('fx'), dict) and not sp['fx'].get('uv_only'):
                    sp['fx']['color'] = RB_SLOT[RB.index(c)] if c in RB else sp['fx'].get('color')
        elif kind in ('cut', 'blink') and 0.0 <= age < (0.5 if kind == 'cut' else 0.8):
            dark = kind == 'cut' or (age < 0.18 or 0.36 <= age < 0.54)   # tap 2: a cut to black / entry: two blinks
            if dark:
                for zo in zout:
                    zo['level'] = 0.0
                for d_ in list(hs.values()) + list(spots.values()):
                    d_['level'] = 0.0
                floor = 0.0
        return zout, hs, spots, floor

    def glitch_look(self, gl, zout, hs, spots, floor):
        import copy
        st = self._gl
        if gl.get('gap'):                                    # holds its breath
            for zo in zout:
                zo['level'] = 0.0
            for d_ in list(hs.values()) + list(spots.values()):
                d_['level'] = 0.0
            return zout, hs, spots, 0.0
        if gl.get('stutter'):                                # time stops
            if st.get('frozen') is None:
                st['frozen'] = copy.deepcopy((zout, hs, spots, floor))
            return copy.deepcopy(st['frozen'])
        if gl.get('crush') and zout:                         # one fixture notices
            if st.get('crush_zone') is None:
                dark = [i for i, zo in enumerate(zout) if zo.get('level', 0.0) < 0.2]
                st['crush_zone'] = self.rng.choice(dark or list(range(len(zout))))
            zo = zout[st['crush_zone'] % len(zout)]
            zo['rgb'], zo['level'] = (1.0, 1.0, 1.0), 1.0
        return zout, hs, spots, floor

    def pivot(self, h, kn, sn):
        """Nov 18 (Michael: "up to 90 degree turns and pivots on the heads with the 808, the kick and the clap -- to
        personify the movement of my song"): every head moves as one body round its saved UV-tapestry aim --
        CLAP / snare = a 90 degree turn (45 either side, flipping each clap), KICK = a tilt pivot (nod down / up),
        808 = the weight: while the low end rings the heads sink further. SNAP moves (full motor speed, no glide).
        -> {pan16, lean, snap} or None (no saved aim for this head)."""
        if not self.settings().get('pocket_pivots', False) or \
                str(self.settings().get('pocket_moves', 'snap') or 'snap').lower() != 'snap':   # Nov 18: OFF (too snappy)
            return None                                      # unless asked for (setting pocket_pivots = true)
        try:
            c = float(((self.settings().get('head_targets') or {}).get('UV tapestry') or {})[str(h)]['pan'])
        except (KeyError, TypeError, ValueError):
            return None
        turn = float(self.settings().get('pocket_turn_deg', 45.0) or 45.0)
        pan16 = c + (turn if sn % 2 == 0 else -turn) / 540.0 * 65535.0
        f = getattr(getattr(self.hub, 'audioshow', None), 'feat', None) or {}
        lv = f.get('level') if isinstance(f, dict) else None
        sub = clamp(float(lv.get('sub', lv.get('kick', 0.0)) or 0.0)) if isinstance(lv, dict) else 0.0   # the 808 band
        lean = (0.35 if kn % 2 == 0 else 0.8) + 0.15 * sub
        return dict(pan16=pan16, lean=clamp(lean, 0.0, 0.95), snap=True)

    def rainbow_frame(self, beats, now):
        bpb = int(self.settings().get('beats_per_bar', 4) or 4)
        bar = int(math.floor(beats / bpb))
        phrase = bar // self.bars_per_phrase()
        sec = self.section()
        vj = self.vj()
        key = (phrase, sec == 'drop', sec in ('breakdown', 'quiet'), vj.get('piece'))
        if getattr(self, 'rb_key', None) != key:
            self.rb_key = key
            self.rb_sub = self.rb_pick(sec, phrase)
            self.history = (self.history + [self.rb_sub])[-6:]
        sub = self.rb_sub
        bn = int(math.floor(beats))
        frac = beats - bn
        cnt, live = self.pocket(now)
        gl = {}                                             # Nov 19: glitch reactions DELETED (Michael) -- the lights
                                                            # never react to glitches; the detector only feeds Unreal
        hit = (vj.get('hit') or {}) if isinstance(vj.get('hit'), dict) else {}
        if hit.get('kind') == 'skip' and hit.get('t') != getattr(self, '_vj_skip_t', None):
            self._vj_skip_t = hit.get('t')                  # tap 3: the rainbow steps ONE colour on (in ROY G BIV order)
            self._coff = getattr(self, '_coff', 0) + 1
        if live:                                            # HIS pocket: hits + snaps come from the music itself
            e = self._pk['a']
            kick = e['kick']
            ed = self._pk.get('d') or e                     # heads + spots: punch on every hit (tight)
            kn, sn, hn = cnt['kick'], cnt['snare'], cnt['snare'] + cnt['hats'] // 2
        else:                                               # silence: the beat clock keeps the room alive
            e = self.clock_hits(beats)
            kick = max(e['kick'], decay(frac, 0.22))
            kn = sn = hn = bn
            ed = dict(e, kick=kick)
        dk, ds = ed['kick'], ed['snare']
        self.rb_live = live
        coff = getattr(self, '_coff', 0)                    # Nov 18 eve: the rainbow keeps ROY G BIV order, always
        zl = self.zone_list()
        loop = self.loop_order(zl)
        g = self.grid(zl)
        hs, zout, spots = {}, [], {}
        floor = 0.08
        heads_lit = {}
        if sub == 'scatter':
            zout, hs, spots, floor = self.scatter(zl, now, live, bn, e)
        elif sub == 'steps':                                  # everything one colour, snapping every 2nd kick
            ci = (kn // 2 + coff) % len(RB)
            lvl = 0.3 + 0.7 * kick
            for zone in zl:
                zout.append(dict(id=zone['id'], level=clamp(lvl), rgb=RB[ci], channels=zone['channels']))
            pos = [(0.15, 0.8), (0.5, 0.45), (0.85, 0.8), (0.5, 0.65)][(sn if live else bar) % 4]   # heads jump on the snare
            for h in self.heads_i:
                hs[h] = dict(level=clamp(0.25 + 0.75 * max(dk, ds)), u=pos[0], lean=pos[1], rgb=RB[ci], fast=True)
            for i in self.spots_i:
                spots[i] = dict(level=clamp(0.35 + 0.65 * max(dk, ds)), fx=dict(gobo=GOBOS[hn % len(GOBOS)],
                                color=RB_SLOT[ci], gobo_rot=0, uv=0, uv_only=False, breathe=0))
        elif sub == 'chase' and len(self.chase_seq()) >= 3:
            # Nov 19 (Michael): THE WAVE, PRECISELY ONE BY ONE through every fixture in the studio frame, in his order,
            # there and back: one fixture per kick, everything else dark, the next ROY G BIV colour each step
            floor = 0.0
            seq = self.chase_seq()
            n = len(seq)
            per = 2 * n - 2 if (n > 1 and self.settings().get('chase_bounce', True)) else n
            p_ = kn % per
            f = seq[p_ if p_ < n else per - p_]
            ci = (kn + coff) % len(RB)
            for kind, key, chans in seq:
                if kind == 'l':
                    zout.append(dict(id='L:' + key, level=clamp(0.55 + 0.45 * kick) if f[1] == key else 0.0, rgb=RB[ci],
                                     channels=chans))
            for h in self.heads_i:
                on = f[0] == 'h' and f[1] == h
                hs[h] = dict(level=clamp(0.3 + 0.7 * max(dk, ds)) if on else 0.0, u=(0.15, 0.85, 0.35, 0.65)[(kn + sn) % 4],
                             lean=0.9 if (kn + sn) % 2 == 0 else 0.6, rgb=RB[ci], fast=True)
            for i in self.spots_i:
                on = f[0] == 's' and f[1] == i
                spots[i] = dict(level=clamp(0.3 + 0.7 * max(dk, ds)) if on else 0.0,
                                fx=dict(gobo=GOBOS[hn % len(GOBOS)], color=RB_SLOT[ci], gobo_rot=0, uv=0, uv_only=False, breathe=0))
        elif sub == 'chase':                                # one zone per beat, the rest dark, a new colour each step
            floor = 0.0
            on_id = loop[kn % len(loop)] if loop else None   # one zone per KICK
            ci = (kn + coff) % len(RB)
            for zone in zl:
                on = zone['id'] == on_id
                zout.append(dict(id=zone['id'], level=clamp(0.55 + 0.45 * kick) if on else 0.0, rgb=RB[ci],
                                 channels=zone['channels']))
                for h in zone['heads']:
                    heads_lit[h] = on
            for k, h in enumerate(self.heads_i):
                on = heads_lit.get(h, False)
                # Nov 18 snap: the lit head punches on every hit (dark-ish between) and SNAPS to a new spot on
                # every kick and snare -- no glides
                hs[h] = dict(level=clamp(0.3 + 0.7 * max(dk, ds)) if on else 0.0, u=(0.15, 0.85, 0.35, 0.65)[(kn + sn) % 4],
                             lean=0.9 if (kn + sn) % 2 == 0 else 0.6, rgb=RB[ci], fast=True)
            for j, i in enumerate(self.spots_i):
                zid = next((z['id'] for z in zl if i in (z.get('spots') or [])), None)
                on = zid == on_id if zid else (kn % 4 == 0)
                # Nov 19 (Michael: "all the light fixtures"): the spots also ANSWER every snare -- the two take turns,
                # in the colour of the moment -- so they dance as much as the lamps and heads (call and response)
                turn = live and self.spots_i and self.spots_i[sn % len(self.spots_i)] == i
                lvl_ = clamp(0.3 + 0.7 * max(dk, ds)) if on else 0.0
                if turn:
                    lvl_ = max(lvl_, clamp(ds))
                spots[i] = dict(level=lvl_, fx=dict(gobo=GOBOS[hn % len(GOBOS)], color=RB_SLOT[ci], gobo_rot=0, uv=0,
                                                    uv_only=False, breathe=0))
        elif sub == 'ripple':                               # colour rolls out from the studio desk toward the door
            step = kn // 2
            cols = sorted({c for c, _ in g})
            far = max(cols) if cols else 3
            for r, zone in enumerate(zl):
                col = g[r][0]
                ci = (step + coff - (far - col)) % len(RB)
                lvl = 0.35 + 0.65 * kick
                zout.append(dict(id=zone['id'], level=clamp(lvl), rgb=RB[ci], channels=zone['channels']))
                for h in zone['heads']:
                    hs[h] = dict(level=clamp(0.3 + 0.7 * max(dk, ds)), u=0.5 + 0.3 * math.sin(2 * math.pi * beats / 16.0 + col),
                                 lean=0.75 if (sn % 2 == 0) else 0.5, rgb=RB[ci], fast=True)
            ci0 = (step + coff) % len(RB)
            for i in self.spots_i:
                spots[i] = dict(level=clamp(0.3 + 0.7 * max(dk, ds)), fx=dict(gobo=48, color=RB_SLOT[ci0], gobo_rot=0, uv=0,
                                                                         uv_only=False, breathe=40, breathe_s=8.0))
        elif sub == 'allout':                               # DROP: snap every beat, flash on the kick
            floor = 0.0
            ci = (kn + coff) % len(RB)
            flash = max(e['kick'], 0.6 * e['snare']) if live else max(e['kick'], 0.6 * e['snare'], decay(frac, 0.18))
            dflash = max(dk, 0.8 * ds) if live else flash   # heads + spots: every hit, full contrast (Nov 18 snap)
            lo = 0.04 if live else 0.1                      # the drop: real darkness between the hits
            for zone in zl:
                zout.append(dict(id=zone['id'], level=clamp(lo + (1.0 - lo) * flash), rgb=RB[ci], channels=zone['channels']))
            hc = (ci + 1) % len(RB)                         # heads one step along: always a neighbouring colour
            for h in self.heads_i:
                hs[h] = dict(level=clamp(0.05 + 0.95 * dflash), u=0.15 if (kn + sn) % 2 == 0 else 0.85,
                             lean=0.85 if (kn + sn) % 2 == 0 else 0.4, rgb=RB[hc], fast=True)
            for i in self.spots_i:
                spots[i] = dict(level=clamp(0.05 + 0.95 * dflash), fx=dict(gobo=GOBOS[(kn + hn) % len(GOBOS)], color=RB_SLOT[ci],
                                                                            gobo_rot=0, uv=0, uv_only=False, breathe=0))
        else:                                               # BREATH (breakdowns): calm, the room breathes
            ci = (bar // 2) % len(RB)
            br = 0.5 - 0.5 * math.cos(2 * math.pi * beats / (4.0 * bpb))
            for zone in zl:
                zout.append(dict(id=zone['id'], level=clamp(0.15 + 0.85 * br), rgb=RB[ci], channels=zone['channels']))
            for h in self.heads_i:
                hs[h] = dict(level=clamp(0.1 + 0.4 * br), u=0.5 + 0.35 * math.sin(2 * math.pi * beats / (8.0 * bpb)),
                             lean=0.35 + 0.2 * br, rgb=RB[ci])
            for i in self.spots_i:
                aim = UV_AIMS.get(i, {'az': 180, 'lean': 50})
                spots[i] = dict(level=0.85, fx=dict(hold=dict(aim, drift=0), hold_when='always', hold_head=i, uv=1.0,
                                                    uv_only=True, uv_steady=True, gobo=0, focus=128))
        for h in self.heads_i:
            hs.setdefault(h, dict(level=0.0, lean=0.5, u=0.5, rgb=RB[0]))
        if live and sub != 'breath':                       # BANDS (Nov 18): lows = the heads' body, mids = the spots'
            f_ = getattr(getattr(self.hub, 'audioshow', None), 'feat', None) or {}
            bl = f_.get('level') if isinstance(f_, dict) else None
            if isinstance(bl, dict):
                su_, lo_, mi_, hi_ = (clamp(float(bl.get(k, 0.0) or 0.0)) for k in ('sub', 'low', 'mid', 'high'))
                for zo in zout:                              # sub (the 808): the lit lamps swell with it
                    if zo.get('level', 0.0) > 0.0:
                        zo['level'] = max(zo['level'], 0.2 + 0.5 * su_)
                # Nov 19: restored exactly as it ran Nov 18 noon (the chase Michael loves): lows = the lit heads'
                # body, mids = the lit spots'
                for h in self.heads_i:
                    if hs[h].get('level', 0.0) > 0.0:
                        hs[h]['level'] = max(hs[h]['level'], 0.2 + 0.5 * lo_)
                for i in spots:
                    if spots[i].get('level', 0.0) > 0.0:
                        spots[i]['level'] = max(spots[i]['level'], 0.2 + 0.5 * mi_)
                        fx_ = spots[i].get('fx')
                        if isinstance(fx_, dict) and not fx_.get('uv_only'):   # highs: the gobo edge sharpens with the air
                            fx_['focus'] = int(90 + 80 * hi_)
        if str(self.settings().get('pocket_moves', 'snap') or 'snap').lower() != 'snap':
            # CALM (default, Nov 18, Michael: "avoid unnecessary movement from the heads -- the snappiness adds noise"):
            # the heads HOLD one position per phrase and glide (quiet motor speed) only when the phrase changes;
            # the hits play through colour + brightness, one fixture at a time -- never through motion
            pos = [(0.3, 0.7), (0.7, 0.7), (0.5, 0.55), (0.4, 0.8)][phrase % 4]
            for h in self.heads_i:
                cv = hs[h]
                cv['u'], cv['lean'] = pos[0] + 0.05 * (h - 1.5), pos[1]
                cv.pop('fast', None)
                cv.pop('snap', None)
                cv.pop('pan16', None)
        if live and sub in ('steps', 'chase', 'ripple', 'allout'):   # his pocket moves the heads: turns + pivots
            for h in self.heads_i:
                pv = self.pivot(h, kn, sn)
                if pv:
                    hs[h].update(pv)
        if live:                                            # the song's dynamics: a quiet verse is a dimmer room
            m = 0.3 + 0.7 * self._pk.get('dyn', 1.0)
            for zo in zout:
                zo['level'] = clamp(zo['level'] * m)
            for d_ in list(hs.values()) + list(spots.values()):
                d_['level'] = clamp(d_.get('level', 0.0) * m)
        if self.settings().get('spot_scan', True):          # Nov 19: the spots are RAINBOW SPOTLIGHTS THAT SCAN THE ROOM
            for sp in spots.values():                       # (hub_dmx sweeps them; breath keeps its UV on the tapestry)
                if isinstance(sp.get('fx'), dict) and not sp['fx'].get('uv_only'):
                    sp['fx']['scan'] = True
        if vj:                                              # VJ moments on top of the music
            zout, hs, spots, floor = self.vj_look(vj, now, zout, hs, spots, floor)
        cur = zout[0]['rgb'] if zout else RB[0]
        return dict(heads=hs, zones=zout, spots=spots, lamp_floor=floor, full=True, rgb=cur, v=self.v, head=None,
                    turn=phrase, new=False, p=0.0, mode='rb_' + sub, act='rainbow', bar=bar,
                    phrase_bar=bar % self.bars_per_phrase(), rb=sub, rb_name=RB_NAMES.get(sub, sub), pocket=live,
                    glitch=gl.get('now'))

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
        v = 1.0 if z.get('full') else max(self.v, 0.35)      # v2: full brightness, the drums set the level
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
        label = z.get('rb_name') if a == 'rainbow' else NAMES.get(m, m) if a == 'zones' else ACT_NAMES.get(a, a)
        return '%s (bar %d of %d)' % (label, z.get('phrase_bar', 0) + 1, self.bars_per_phrase())

    def status(self):
        z = self.last
        _audio = self.audio_mix()
        _heads = {str(h + 1): [round(cv.get('level', 0), 2), round(cv.get('u', -1), 2), round(cv.get('lean', -1), 2)]
                  for h, cv in ((z or {}).get('heads') or {}).items()}
        a = (z or {}).get('act', 'zones')
        return dict(on=bool(z), pattern=self.pattern(), act=a if z else None, act_name=ACT_NAMES.get(a, '') if z else '',
                    acts=[dict(id=x, name=ACT_NAMES[x]) for x in ACTS], acts_on=self.acts_on(), audio_mix=_audio, head_out=_heads,
                    mode=(z or {}).get('mode'), name=(z or {}).get('rb_name', '') if a == 'rainbow' else
                    NAMES.get((z or {}).get('mode'), '') if a == 'zones' else ACT_NAMES.get(a, ''),
                    bar=(z or {}).get('phrase_bar', 0) + 1 if z else 0, bars=self.bars_per_phrase(),
                    lock=str(self.settings().get('show_lock', '') or ''), speed=self.speed(),
                    history=list(self.history[-4:]), section=self.section(),
                    zones=[dict(id=z['id'], heads=[h + 1 for h in z['heads']], lamps=len(z['channels'])) for z in self.zone_list()], modes=[dict(id=m, name=NAMES[m]) for m in MODES])
