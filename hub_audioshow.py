# =============================================================================
# HUE HUB -- the audio light show (the gear plays the lamps)
#
# Built like a club rig: the MUSIC drives the brightness, and the look, your
# pads and Ableton give the COLOURS (so a dim look no longer means a dim show).
#   between hits  a solid, coloured room (how solid follows the loudness)
#   kick    the room PUNCHES to full and settles back (smooth, never a strobe)
#   snare   its lamps (default: every other lamp) flip to the room's ACCENT
#           colour and light up
#   hats    one lamp at a time SHIMMERS, paler and brighter
#   colours step round the room every bar (4 kicks) and on every drop; a
#           one-colour room becomes two-tone with its accent ("Colour moves")
#   drops   no kick for a few seconds while the music plays = BREAKDOWN: the
#           room goes low and pale, and the snare rolls of the build lift it.
#           Kick back = the DROP: full brightness, full colour, new colour
#           placement, and the visuals burst.
#   colour  optional: bassy sound warmer, bright sound cooler (off by default)
# Each has an amount on the desk (Audio tab); "Audio show" scales them all.
# Everything still goes through the flicker protection afterwards: however
# fast the drums run, no lamp changes more often than the Flicker Guard allows
# (never above 3 a second -- the photosensitive-epilepsy limit).
# =============================================================================

import collections
import colorsys
import math
import random

DEFAULT_VOICES = dict(
    kick=dict(color='look', zones='all'),          # 'look' = keep each lamp's own colour, just pump it
    snare=dict(color='accent', zones='odd'),       # 'accent' = the room's second colour
    hats=dict(color='look', zones='all'),          # 'look' on hats = a paler shimmer of the lamp's colour
)
DECAY = dict(kick=0.20, snare=0.30, hats=0.16)     # how long each hit rings (seconds)
ATTACK = dict(kick=0.035, snare=0.05, hats=0.04)   # how fast it rises: a quick swell, never a hard edge
ZONES = ['all', 'odd', 'even', 'left', 'right', 'centre', 'edges']
SHOW_DEFAULTS = dict(a_amt=0.85, a_kick=0.5, a_snare=0.45, a_hats=0.35, a_follow=0.3, a_colour=0.0, a_drop=0.7,
                     a_move=0.6, a_spread=0.5)
# PATTERNS -- how a hit travels through the room (your lamps' places and order: desk > Setup)
KICK_PATTERNS = ['auto', 'pump', 'ripple', 'implode', 'wave_lr', 'wave_rl', 'wave_up', 'bounce', 'spin', 'chase']
SNARE_PATTERNS = ['auto', 'zones', 'burst', 'sides', 'chase']
AUTO_KICK = ['pump', 'ripple', 'bounce', 'chase', 'spin', 'implode', 'wave_lr']     # one per phrase, in turn
AUTO_SNARE = ['zones', 'burst', 'sides', 'zones', 'burst', 'chase', 'sides']
PRO_CUES = ['pulse', 'pass', 'pingpong', 'relay', 'chase', 'wipe', 'rings', 'wheel', 'sweep', 'mirror',
            'columns']                                    # 'auto': one per phrase, in turn
BREAK_AFTER = 3.0         # seconds without a kick (music still playing) before it counts as a breakdown
DROP_MIN = 4.0            # a breakdown at least this long makes the kick's return a DROP


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _hex(h):
    h = (h or '#ffffff').lstrip('#')
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return (1.0, 1.0, 1.0)


def _mix(a, b, t):
    """hue-aware mix (keeps colours vivid instead of going grey through the middle)"""
    if t <= 0:
        return tuple(a)
    if t >= 1:
        return tuple(b)
    ha, sa, va = colorsys.rgb_to_hsv(*[_clamp(x) for x in a])
    hb, sb, vb = colorsys.rgb_to_hsv(*[_clamp(x) for x in b])
    if sa < 0.02 or va < 0.02:
        ha = hb
    if sb < 0.02 or vb < 0.02:
        hb = ha
    dh = ((hb - ha + 0.5) % 1.0) - 0.5
    return colorsys.hsv_to_rgb((ha + dh * t) % 1.0, sa + (sb - sa) * t, va + (vb - va) * t)


def hub_room_colours(cols):
    """the two main colours of what is playing underneath (look, pads, Ableton), full strength"""
    try:
        import hub_visuals
        return hub_visuals.room_colours(cols)
    except Exception:
        return None


def _hue(c):
    return colorsys.rgb_to_hsv(*[_clamp(x) for x in c])[0]


def _gap(a, b):
    return abs(((a - b + 0.5) % 1.0) - 0.5)


class AudioShow:
    def __init__(self, hub):
        self.hub = hub
        self.raw = dict(kick=0.0, snare=0.0, hats=0.0)
        self.hit = dict(kick=[-10.0, 0.0], snare=[-10.0, 0.0], hats=[-10.0, 0.0])   # last hit: (time, peak)
        self.env = dict(kick=0.0, snare=0.0, hats=0.0)      # what the lamps follow: a smooth swell of raw
        self.spark = {}                 # zone index -> [raw, smooth] shimmer envelope
        self.counts = dict(kick=0, snare=0, hats=0)
        self.silent_for = 10.0
        self.feat = None
        self.gate = 0.0                 # 0 = no music (the show steps back), 1 = playing
        self.last_kick = -100.0
        self.music_t = 0.0              # seconds of music so far
        self.brk = 0.0                  # 0 = groove, 1 = deep in a breakdown (glides)
        self.brk_since = None           # when the current breakdown started
        self.drop = 0.0                 # 1 at the drop, rings out over a few seconds (the visuals burst)
        self.drops = 0
        self.section = 'quiet'
        self.pal = []                   # each lamp's colour from the look / pads (full strength)
        self.cur = []                   # what each lamp shows now (glides to its place in the colour rotation)
        self.rot = 0                    # the colours step round the room every 4 kicks (one bar)
        self.kick_n = 0
        self.snare_n = 0
        self.recent = dict(kick=collections.deque(maxlen=6), snare=collections.deque(maxlen=6))  # (t, peak, n, pattern)
        self.phrase_kicks = 0
        self.auto_i = 0                 # which pattern 'auto' is on (changes every phrase and on every drop)
        self.prog_on = False            # the programmed show is running (tempo locked)
        self.prog_phrase = None
        self.cue_now = '-'
        self.lvl_slow = 0.0             # loudness over the last few seconds
        self.pulse_every = 1
        self.bar_now = 0
        self.vis_i = 0                  # which visual the music has picked (moves every N bars and on drops)
        self.snare_t = -100.0
        self.ca = (1.0, 0.45, 0.1)
        self.cb = (0.35, 0.2, 1.0)

    def voices(self):
        v = self.hub.state['settings'].get('a_voices') or {}
        out = {}
        for k, d in DEFAULT_VOICES.items():
            out[k] = dict(d)
            out[k].update(v.get(k) or {})
        return out

    def members(self, zones, segs):
        n = len(segs)
        if zones == 'all' or n == 0:
            return set(range(n))
        if isinstance(zones, list):
            return {i for i, s in enumerate(segs) if s['key'] in zones}
        r = {i: s['rank'] for i, s in enumerate(segs)}
        u = {i: s.get('u', 0.5) for i, s in enumerate(segs)}
        if zones == 'odd':
            return {i for i in r if r[i] % 2 == 1}
        if zones == 'even':
            return {i for i in r if r[i] % 2 == 0}
        if zones == 'left':
            return {i for i in u if u[i] < 0.5}
        if zones == 'right':
            return {i for i in u if u[i] >= 0.5}
        if zones == 'centre':
            return {i for i in u if abs(u[i] - 0.5) < 0.25}
        if zones == 'edges':
            return {i for i in u if abs(u[i] - 0.5) >= 0.25}
        return set(range(n))

    def _sections(self, now, dt, playing, kicked):
        """groove / breakdown / drop, from when the kick drops out and comes back"""
        if kicked:
            if self.brk_since is not None and now - self.brk_since >= DROP_MIN - BREAK_AFTER:
                self.drop = 1.0                                   # the kick is back after a breakdown: DROP
                self.rot += 1                                     # ...with a new colour placement
                self.kick_n = 0
                self.auto_i += 1                                  # ...and a new pattern
                self.vis_i += 1                                   # ...and a new visual, straight away
                self.phrase_kicks = 0
                self.drops += 1
            self.brk_since = None
            self.last_kick = now
        if playing:
            self.music_t += dt
        no_kick = now - self.last_kick
        in_break = playing and self.music_t > 2.0 and no_kick > BREAK_AFTER
        if in_break and self.brk_since is None:
            self.brk_since = now
        if not playing:
            self.brk_since = None
        tgt = 1.0 if in_break else 0.0
        tau = 2.0 if tgt > self.brk else 0.3                     # sink in slowly, snap back on the drop (smoothly)
        self.brk += (tgt - self.brk) * (1.0 - math.exp(-dt / tau))
        self.drop *= math.exp(-dt / 1.6)
        if not playing and self.gate < 0.05:
            self.section = 'quiet'
        elif self.drop > 0.25:
            self.section = 'drop'
        elif self.brk > 0.5:
            self.section = 'breakdown'
        else:
            self.section = 'groove'

    def render(self, cols, now, dt):
        h = self.hub
        a = h.audio
        live = h.live
        if a is None:
            return cols
        hits = a.poll(now)
        f = a.features()
        self.feat = f
        segs = h.rig.segs
        voices = self.voices()
        kicked = False
        for k, s in hits:
            if k not in self.raw:
                continue
            pk = 0.65 + 0.35 * s                            # every real hit lands big; harder hits a bit bigger
            self.hit[k] = [now, max(pk, self._shape(k, now))]
            self.counts[k] += 1
            kicked = kicked or k == 'kick'
            if k == 'kick':
                self.kick_n += 1
                if self.kick_n % 4 == 0:
                    self.rot += 1
                vb = int(h.state['settings'].get('a_vis_bars', 2) or 2)
                if not self.prog_on and self.kick_n % (4 * vb) == 0:
                    self.vis_i += 1
                self.phrase_kicks += 1
                bars = int(h.state['settings'].get('a_phrase', 8) or 8)
                if self.phrase_kicks >= 4 * bars and not self.prog_on:   # (the programmed show counts real bars)
                    self.phrase_kicks = 0
                    self.auto_i += 1
                self.recent['kick'].append((now, pk, self.kick_n, self.pattern('kick')))
            if k == 'snare':
                self.snare_n += 1
                self.recent['snare'].append((now, pk, self.snare_n, self.pattern('snare')))
            if k == 'hats':
                mem = sorted(self.members(voices['hats']['zones'], segs)) or list(range(len(segs)))
                if mem:
                    i = random.choice(mem)
                    self.spark[i] = [now, pk]
        for k in self.raw:
            self.env[k] = self._shape(k, now)
            self.raw[k] = self.env[k]
        for i in list(self.spark):
            t0, pk = self.spark[i]
            if now - t0 > 1.0:
                del self.spark[i]
        playing = f is not None and not f['silent'] and f['level']['level'] > 0.05
        self.silent_for = 0.0 if playing else self.silent_for + dt
        tgt = 1.0 if self.silent_for < 1.5 else 0.0               # music stopped: fade the show out
        self.gate += (tgt - self.gate) * (1.0 - math.exp(-dt / (0.15 if tgt > self.gate else 1.0)))
        self._sections(now, dt, playing, kicked)
        amt = _clamp(live.get('a_amt', 0.8)) * self.gate
        if amt < 0.005 or not h.state['settings'].get('audio_on', True):
            return cols
        lvl_now = f['level']['level'] if f else 0.0
        # Breathe follows how loud the music is over a few seconds -- the phrase, not each kick (a per-beat
        # wobble between the hits would make the lights look nervous and eat the flicker allowance)
        self.lvl_slow += (lvl_now - self.lvl_slow) * (1.0 - math.exp(-dt / 1.5))
        lvl = self.lvl_slow
        bright = f['bright'] if f else 0.5
        if h.state['settings'].get('a_style', 'programmed') == 'programmed':
            prog = self._programmed(cols, now, dt, hits, amt, lvl)
            if prog is not None:
                return prog
        else:
            self.prog_on = False
        kick_m = self.members(voices['kick']['zones'], segs)
        snare_m = self.members(voices['snare']['zones'], segs)

        def colour(name):
            return name if name in ('look', 'accent') else _hex(name)
        kick_c, snare_c, hats_c = (colour(voices[k]['color']) for k in ('kick', 'snare', 'hats'))
        k_amt, s_amt, h_amt = live.get('a_kick', 0.5), live.get('a_snare', 0.45), live.get('a_hats', 0.35)
        fol, col_amt = live.get('a_follow', 0.3), live.get('a_colour', 0.0)
        d_amt = _clamp(live.get('a_drop', 0.7))
        mst = 0.0 if h.blackout else _clamp(live.get('master', 1.0))      # accents never outshine Master
        # the room's two main colours (what the visuals use too): the accent is whichever is further round
        vis = getattr(h, 'visuals', None)
        room = [(vis.ca, vis.cb)] if vis is not None else []
        brk = self.brk * d_amt

        def accent(full0, m, floor):
            """the room's accent for a lamp: whichever of the room's two colours is further round the wheel"""
            hue0 = _hue(full0)
            sc = None
            if room:
                ca, cb = room[0]
                sc = cb if _gap(_hue(cb), hue0) >= _gap(_hue(ca), hue0) else ca
            if sc is None or _gap(_hue(sc), hue0) < 0.08:               # one-colour room: its neighbour on the wheel
                sc = colorsys.hsv_to_rgb((hue0 + 0.12) % 1.0, 0.85, 1.0)
            return tuple(v * max(m, floor * mst) for v in sc)
        # ---- the music drives the brightness; the look, the pads and Ableton give the COLOURS ----
        n = len(cols)
        self._update_pal(cols, segs, dt)
        order = sorted(range(n), key=lambda j: segs[j].get('ord', segs[j]['rank'])) if len(segs) == n else list(range(n))
        rank = {j: r for r, j in enumerate(order)}
        mv = _clamp(live.get('a_move', 0.6))
        rot = int(self.rot) if mv > 0.02 else 0
        uniform = n < 2 or max(_gap(_hue(self.pal[j]), _hue(self.pal[order[0]])) for j in order) < 0.06
        kc = 1.0 - math.exp(-dt / 0.12)                    # colour moves glide (a bar's change, never a snap)
        for i in range(n):
            want = self.pal[order[(rank[i] + rot) % n]]
            if uniform and mv > 0.02 and (rank[i] + rot) % 2 == 1:     # one-colour room: two-tone with its accent
                want = _mix(want, accent(want, 1.0, 1.0), 0.5 * mv)
            self.cur[i] = _mix(self.cur[i], want, kc)
        ks = min(1.0, 0.4 + 1.2 * k_amt)                   # 50% = full punch
        ss_ = min(1.0, 0.3 + 1.2 * s_amt)
        hs_ = min(1.0, 0.3 + 1.2 * h_amt)
        es = self.env['snare']
        floor = 0.36 * (1.0 - 0.5 * fol * (1.0 - lvl))     # between hits: a solid, coloured room
        dl = self.drop * d_amt
        geo_ = self.geometry(segs, n)
        beat = 60.0 / max(40.0, (h.clock[1] if getattr(h, 'clock', None) else 120.0) or 120.0)
        travel = min(0.45, (0.12 + 0.5 * _clamp(live.get('a_spread', 0.5))) * beat)   # how long a ripple takes
        out = []
        for i, c in enumerate(cols):
            c0 = tuple(c)
            col = self.cur[i]
            ek = self.lamp_env('kick', i, now, geo_, travel, kick_m)
            es = self.lamp_env('snare', i, now, geo_, travel * 0.7, snare_m)
            if i in kick_m and k_amt > 0:                  # kick: the room PUNCHES to full and settles back
                b = floor + (1.0 - floor) * ek * ks
                if kick_c == 'accent':
                    col = _mix(col, accent(col, 1.0, 1.0), ek * 0.5)
                elif isinstance(kick_c, tuple):
                    col = _mix(col, kick_c, ek * 0.6)
            else:
                b = floor + (1.0 - floor) * 0.3
            if s_amt > 0 and es > 0.01:                     # snare: its lamps flip to the accent and light up
                b = max(b, floor + (1.0 - floor) * es * ss_)
                if snare_c == 'accent':
                    col = _mix(col, accent(col, 1.0, 1.0), es * ss_)
                elif isinstance(snare_c, tuple):
                    col = _mix(col, snare_c, es * ss_)
            sp = self.spark.get(i)
            e_h = self._shape('hats', now, *sp) if sp else 0.0
            if e_h > 0.01 and h_amt > 0:                   # hats: one lamp at a time shimmers, paler and brighter
                b = max(b, floor + (1.0 - floor) * e_h * hs_ * 0.85)
                hh, sv, _ = colorsys.rgb_to_hsv(*col)
                hc = colorsys.hsv_to_rgb(hh, sv * 0.45, 1.0) if not isinstance(hats_c, tuple) else hats_c
                col = _mix(col, hc, e_h * hs_ * 0.7)
            if brk > 0.005:                                # breakdown: low and pale; snare rolls of the build lift it
                bb = 0.18 + 0.55 * max(es * ss_, lvl * 0.3)
                b = b * (1.0 - brk) + bb * brk
                hh, sv, vv = colorsys.rgb_to_hsv(*col)
                col = colorsys.hsv_to_rgb(hh, sv * (1.0 - 0.3 * brk), vv)
            if dl > 0.005:                                 # the drop: full brightness, full colour, ringing out
                b = max(b, dl)
            if col_amt > 0:
                hh, sv, vv = colorsys.rgb_to_hsv(*col)
                if sv > 0.05:
                    col = colorsys.hsv_to_rgb((hh + (bright - 0.5) * 0.25 * col_amt) % 1.0, sv, vv)
            x = tuple(_clamp(v * b * mst) for v in col)
            out.append(tuple(cv + (xv - cv) * amt for cv, xv in zip(c0, x)))
        return out

    # ------------------------------------------------------------------------------------------
    # PROGRAMMED: like a lighting operator with the show on a beat grid. Everything is quantised to the
    # tempo the hub has locked onto -- the lamps move together, or in clean steps (rings and columns on
    # 16ths, chases on 8ths), in two colours held for a whole phrase, and the cue changes on phrase
    # boundaries and drops. Nothing random, nothing triggered late by a detector.
    # ------------------------------------------------------------------------------------------
    def _programmed(self, cols, now, dt, hits, amt, lvl):
        h = self.hub
        a = h.audio
        bt = getattr(a, 'beat', None)
        if bt is None or bt.period is None or bt.conf < 0.45:
            self.prog_on = False
            return None                                  # not locked yet: the reactive show plays meanwhile
        self.prog_on = True
        live = h.live
        segs = h.rig.segs
        n = len(cols)
        self._update_pal(cols, segs, dt)
        lead = float(h.state['calibration'].get('lamp_delay', 60.0)) / 1000.0
        for k, s_ in hits:
            if k == 'snare':
                self.snare_t = now
        # which beats carry the snare (2 and 4): the tracker hears it, and that places beat 1 of the bar
        backbeat = bt.backbeat
        b = bt.phase(now + lead)                         # in beats; sent early so the bulbs land ON the beat
        one = (1 - backbeat) % 2 if backbeat is not None else 0
        bb = b - one                                     # beats since a "one"
        beat_i = int(math.floor(bb))
        frac = bb - beat_i
        bar_pos = beat_i % 4
        if beat_i // 4 != self.bar_now:                  # a new bar: the visuals move on every N bars
            vb = int(h.state['settings'].get('a_vis_bars', 2) or 2)
            if (beat_i // 4) % vb == 0:
                self.vis_i += 1
        self.bar_now = beat_i // 4
        bars = int(h.state['settings'].get('a_phrase', 8) or 8)
        phrase = beat_i // (4 * bars)
        if self.prog_phrase is None:
            self.prog_phrase = phrase
        if phrase != self.prog_phrase:                   # a new phrase: auto moves to the next cue
            self.prog_phrase = phrase
            self.auto_i += 1
        # the cue
        cue = h.state['settings'].get('a_cue', 'auto')
        sec = self.section
        four = bool(getattr(a, 'grid_on', False))
        if cue == 'auto':
            cue = PRO_CUES[self.auto_i % len(PRO_CUES)]
        self.cue_now = 'breakdown' if sec == 'breakdown' else cue
        # the two colours: from the look / pads / Ableton (what's playing underneath), held steady
        rc = hub_room_colours(cols)
        if rc is not None:
            k_ = 1.0 - math.exp(-dt / 0.6)
            self.ca = _mix(self.ca, rc[0], k_)
            self.cb = _mix(self.cb, rc[1], k_)
        A, B = self.ca, self.cb
        if self.auto_i % 2 == 1 and h.state['settings'].get('a_cue', 'auto') == 'auto':
            A, B = B, A                                  # every other phrase the two colours trade places
        ks = min(1.0, 0.45 + 1.1 * _clamp(live.get('a_kick', 0.5)))
        s_amt = _clamp(live.get('a_snare', 0.45))
        d_amt = _clamp(live.get('a_drop', 0.7))
        fol = _clamp(live.get('a_follow', 0.3))
        mst = 0.0 if h.blackout else _clamp(live.get('master', 1.0))
        floor = 0.30 * (1.0 - 0.5 * fol * (1.0 - lvl))

        # Pulses are shaped to suit the flicker protection rather than fight it: a quick swell, a short hold at
        # the top (the guard needs that long before the light may turn round), then the decay. If the tempo is
        # too fast for a full pulse on every beat within the Flicker Guard, it pulses on 1 and 3 (or on 1).
        per = bt.period
        gap = getattr(h.lim, 'gap', 0.28)
        m = 1 if per >= 2 * gap + 0.025 else (2 if 2 * per >= 2 * gap + 0.025 else 4)
        hold = gap + 0.01
        tau = max(0.05, 0.38 * (m * per - hold))
        self.pulse_every = m

        def env_s(ts):                                   # seconds since this lamp's pulse
            if ts < 0:
                return 0.0
            if ts < 0.03:
                y = ts / 0.03
                return y * y * (3 - 2 * y)
            if ts < hold:
                return 1.0
            return math.exp(-(ts - hold) / tau)

        def pulse(offset_beats=0.0, every=1):
            """this lamp's pulse: on every m-th beat (on the "one"), shifted by offset (in beats)"""
            span = m * every
            return env_s(((bb - offset_beats) % span) * per)

        if four:
            kick = pulse()
        else:
            kick = max([self._shape('kick', now, t, pk) for t, pk, _, _ in self.recent['kick']] + [0.0])
        self.env['kick'] = kick
        snare = 0.0                                      # the snare: a colour accent on 2 and 4 (whole room)
        if (backbeat is not None and m == 1 and bar_pos % 2 == 1 and now - self.snare_t < 4.0
                and self.section != 'breakdown' and self.cue_now == 'pulse'):   # (only where it moves with the pulse)
            snare = env_s(frac * per) * s_amt
        self.env['snare'] = snare
        geo_ = self.geometry(segs, n)
        # --- colours that travel: a palette laid round the room in your order -------------------------
        # (the look's own colours if it has several, otherwise a loop from colour A to B and back)
        order = sorted(range(n), key=lambda j: geo_[j]['o'])
        own_cols = [self.pal[j] for j in order] if len(self.pal) == n else []
        hues = sorted(_hue(c) for c in own_cols)
        varied = len(own_cols) >= 3 and sum(1 for x, y in zip(hues, hues[1:] + [hues[0] + 1.0]) if y - x > 0.06) >= 3
        if varied:
            P = own_cols
        else:
            P = [_mix(A, B, 0.5 - 0.5 * math.cos(2 * math.pi * k / max(1, n))) for k in range(n)]
        hb = _hue(B) if _gap(_hue(A), _hue(B)) > 0.05 else (_hue(A) + 0.1) % 1.0
        C = colorsys.hsv_to_rgb(((_hue(A) + hb) / 2.0 + (0.5 if abs(_hue(A) - hb) > 0.5 else 0.0)) % 1.0, 0.9, 1.0)
        step = beat_i // m if four else self.kick_n       # one hand-off per pulse (per kick when not on the grid)
        ts_step = ((bb % m) * per) if four else max(0.0, now - (self.recent['kick'][-1][0] if self.recent['kick'] else now))
        hand = min(1.0, ts_step / 0.12)
        hand = hand * hand * (3 - 2 * hand)               # the hand-off: a quick, smooth crossfade with the pulse
        bar = beat_i // 4
        in_bar = bb - bar * 4
        wipe_dt = min(0.25, 3.0 / max(1, n))              # wipe: one lamp per 16th (faster with many zones)
        W = [A, B, C]
        rings = max(1, int(math.ceil(n / 2.0)))
        out = []
        for i in range(n):
            g = geo_[i]
            o = g['o']
            I, mb = floor, 0.0
            own = None
            if self.cue_now == 'pass':                   # every colour moves on one bulb with every pulse
                I = floor + (1 - floor) * ks * kick
                own = _mix(P[(o - (step - 1)) % n], P[(o - step) % n], hand)
            elif self.cue_now == 'relay':                # one bulb in colour B, handed on bulb to bulb on the beat
                I = floor + (1 - floor) * ks * kick
                head, prev = step % n, (step - 1) % n
                w = hand if o == head else ((1.0 - hand) if o == prev else 0.0)
                own = _mix(A, B, w)
                I = max(I, floor + (1 - floor) * 0.75 * w)
            elif self.cue_now == 'wipe':                 # each bar a new colour wipes across the room, bulb by bulb
                I = floor + (1 - floor) * ks * kick
                x = (in_bar - o * wipe_dt) / 0.2
                y = _clamp(x)
                y = y * y * (3 - 2 * y)
                own = _mix(W[(bar - 1) % 3], W[bar % 3], y)
                if 0 <= x <= 2.5:
                    I = max(I, floor + (1 - floor) * 0.6 * math.exp(-x / 1.2))
            elif self.cue_now == 'mirror':               # colours pass outward from the middle, both ways at once
                I = floor + (1 - floor) * ks * kick
                r = int(round(abs(o - (n - 1) / 2.0)))
                Pr = [_mix(A, B, 0.5 - 0.5 * math.cos(2 * math.pi * k / max(2, rings))) for k in range(rings)]
                own = _mix(Pr[(r - (step - 1)) % rings], Pr[(r - step) % rings], hand)
            elif self.cue_now == 'wheel':                # the colours turn round the room, once every 2 bars
                I = floor + (1 - floor) * ks * kick
                pos = (o / float(max(1, n)) + bb / 8.0) % 1.0
                own = _mix(A, B, 0.5 - 0.5 * math.cos(2 * math.pi * pos))
            elif self.cue_now == 'breakdown':
                # slow: a soft wave across the room over two bars, the colours drifting from one to the other
                w = 0.5 - 0.5 * math.cos(2 * math.pi * (bb / 8.0 - g['on'] * 0.5))
                I = 0.16 + 0.26 * w + 0.25 * self.env['snare'] + 0.1 * lvl
                mb = 0.5 - 0.5 * math.cos(2 * math.pi * bb / 16.0)
            elif self.cue_now == 'pulse':                 # the whole room, every beat, together
                I = floor + (1 - floor) * ks * kick
            elif self.cue_now == 'pingpong':             # left half, then right half, in turn
                side = 0 if g['u'] < 0.5 else 1
                I = floor + (1 - floor) * ks * (pulse(side * m, 2) if four else kick)
                mb = float(side)
            elif self.cue_now == 'chase':                # a light runs through your order on the 8ths
                pos = (bb * 2.0) % n
                dist = (pos - g['o']) % n
                head = math.exp(-dist * 1.6)
                I = floor + (1 - floor) * max(0.35 * ks * kick, head)
                mb = head
            elif self.cue_now == 'rings':                # from the middle out, one ring per 16th
                ring = min(2, int(g['d'] * 2.999))
                I = floor + (1 - floor) * ks * (pulse(ring * 0.25) if four else kick)
                mb = 1.0 if ring == 1 else 0.0
            elif self.cue_now == 'columns':              # left to right, one column per 16th; back the next beat
                col = min(2, int(g['u'] * 2.999))
                if (beat_i // m) % 2 == 1:
                    col = 2 - col
                I = floor + (1 - floor) * ks * (pulse(col * 0.25) if four else kick)
                mb = col / 2.0
            elif self.cue_now == 'sweep':                # a soft band crossing the room over a bar, and back
                p = (bb / 4.0) % 2.0
                p = p if p <= 1.0 else 2.0 - p
                band = math.exp(-((g['u'] - p) / 0.22) ** 2)
                I = floor + (1 - floor) * min(1.0, 0.5 * ks * kick + 0.75 * band)
                mb = band
            # snare: the whole room leans to colour B on 2 and 4
            mb = _clamp(mb + (1.0 - mb) * snare * 0.8 if mb < 0.5 else mb - mb * snare * 0.8)
            # the drop: everything full, in colour A, ringing out over a bar
            dl = self.drop * d_amt
            if dl > 0.005:
                I = max(I, dl)
                mb *= (1.0 - dl)
            col = own if own is not None else _mix(A, B, mb)
            x = tuple(_clamp(v * I * mst) for v in col)
            c0 = tuple(cols[i])
            out.append(tuple(cv + (xv - cv) * amt for cv, xv in zip(c0, x)))
        return out

    def pattern(self, k):
        """the pattern a kick / snare plays right now ('auto' steps through them phrase by phrase)"""
        st = self.hub.state['settings']
        p = st.get('a_pat' if k == 'kick' else 'a_spat', 'auto')
        if p == 'auto':
            lst = AUTO_KICK if k == 'kick' else AUTO_SNARE
            return lst[self.auto_i % len(lst)]
        return p

    def geometry(self, segs, n):
        """each lamp zone's place in the room, normalised: across (u), up (v), distance and angle from the
        ripple's centre, and its place in your order"""
        if len(segs) != n or n == 0:
            return [dict(u=0.5, v=0.5, d=0.0, a=0.0, o=0, on=0.0) for _ in range(n)]
        us = [sg['u'] for sg in segs]
        vs = [sg['v'] for sg in segs]
        u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
        org = self.hub.state['settings'].get('a_origin', 'centre')
        ox, oy = sum(us) / n, sum(vs) / n
        for sg in segs:
            if org == sg['key'] or org == sg['key'].split('#')[0]:
                ox, oy = sg['u'], sg['v']
                break
        else:
            if org == 'left':
                ox, oy = u0, sum(vs) / n
            elif org == 'right':
                ox, oy = u1, sum(vs) / n
        ds = [math.hypot(sg['u'] - ox, sg['v'] - oy) for sg in segs]
        dm = max(ds) or 1.0
        order = sorted(range(n), key=lambda j: segs[j].get('ord', segs[j]['rank']))
        pos = {j: r for r, j in enumerate(order)}
        out = []
        for j, sg in enumerate(segs):
            out.append(dict(u=(sg['u'] - u0) / ((u1 - u0) or 1.0), v=(sg['v'] - v0) / ((v1 - v0) or 1.0),
                            d=ds[j] / dm, a=(math.atan2(sg['v'] - oy, sg['u'] - ox) / (2 * math.pi)) % 1.0,
                            o=pos[j], on=pos[j] / max(1, n - 1)))
        return out

    def lamp_env(self, k, i, now, geo_, travel, members):
        """this lamp's envelope for the recent kicks / snares, each travelling through the room its way"""
        g = geo_[i]
        n = len(geo_)
        best = 0.0
        for t, pk, num, pat in self.recent[k]:
            w, dly = 1.0, 0.0
            if pat == 'pump' or pat == 'zones':
                w = 1.0 if (k == 'kick' or i in members) else 0.0
            elif pat in ('ripple', 'burst'):
                dly = g['d'] * travel
            elif pat == 'implode':
                dly = (1.0 - g['d']) * travel
            elif pat == 'wave_lr':
                dly = g['u'] * travel
            elif pat == 'wave_rl':
                dly = (1.0 - g['u']) * travel
            elif pat == 'wave_up':
                dly = g['v'] * travel
            elif pat == 'bounce':
                dly = (g['u'] if num % 2 == 0 else 1.0 - g['u']) * travel
            elif pat == 'spin':
                dly = ((g['a'] + num * 0.125) % 1.0) * travel
            elif pat == 'chase':                          # one lamp per hit, in your order
                step = num % n
                gap = min(abs(g['o'] - step), n - abs(g['o'] - step))
                w = 1.0 if gap == 0 else (0.3 if gap == 1 else 0.12)
            elif pat == 'sides':
                w = 1.0 if (g['u'] < 0.5) == (num % 2 == 0) else 0.0
            if w <= 0:
                continue
            e = w * self._shape(k, now - dly, t, pk)
            if e > best:
                best = e
        return best

    def _shape(self, k, now, t0=None, pk=None):
        """a hit's envelope: a quick smooth rise (ATTACK) to its peak, then an exponential ring-out (DECAY)"""
        if t0 is None:
            t0, pk = self.hit[k]
        age = now - t0
        if age < 0:
            return 0.0
        a = ATTACK[k]
        if age < a:
            x = age / a
            return pk * x * x * (3 - 2 * x)
        return pk * math.exp(-(age - a) / DECAY[k])

    def _update_pal(self, cols, segs, dt):
        """each lamp's colour from what plays underneath (look, pads, Ableton), whenever it is lit enough to tell"""
        h = self.hub
        n = len(cols)
        if len(self.pal) != n:
            look = h.look(h.active) or {}
            canvas, fill = look.get('canvas', {}), look.get('fill', '#ffaa55')
            self.pal = [self._full(_hex(canvas.get(sg['key'], fill))) for sg in segs][:n]
            self.pal += [(1.0, 0.6, 0.3)] * (n - len(self.pal))
            self.cur = list(self.pal)
        kp = 1.0 - math.exp(-dt / 0.25)
        for i, c in enumerate(cols):
            if max(c) > 0.06:
                self.pal[i] = _mix(self.pal[i], self._full(c), kp)

    @staticmethod
    def _full(c):
        m = max(c)
        return tuple(_clamp(v / m) for v in c) if m > 1e-6 else (1.0, 1.0, 1.0)

    def snapshot(self):
        a = self.hub.audio
        f = self.feat
        return dict(status=a.status if a else 'off', midi=(a.midi_name if a else None),
                    notes=(a.notes_seen() if a else {}), clock=(a.clock_info() if a else None),
                    heard=(a.tempo_info() if a else None),
                    kick=round(self.env['kick'], 3), snare=round(self.env['snare'], 3), hats=round(self.env['hats'], 3),
                    level=round(f['level']['level'], 3) if f else 0, synth=round(f['level']['synth'], 3) if f else 0,
                    low=round(f['level']['kick'], 3) if f else 0, high=round(f['level']['hats'], 3) if f else 0,
                    bright=round(f['bright'], 3) if f else 0.5, gate=round(self.gate, 2), counts=self.counts,
                    section=self.section, pattern=self.pattern('kick'), spattern=self.pattern('snare'),
                    style=('programmed' if self.prog_on else 'reactive'), cue=self.cue_now, brk=round(self.brk, 3), drop=round(self.drop, 3), drops=self.drops)
