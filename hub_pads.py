# =============================================================================
# HUE HUB -- PLAY mode: Push 2's 64 pads as a light instrument
#
#   columns (left to right)   red  orange  yellow  green  cyan  blue  violet  pink
#   rows (bottom to top)
#     1  wash      the whole room in this colour while you hold the pad
#     2  glow      the same, but swells in and fades out slowly
#     3  hit       one punch of colour that fades out (fire it on the beat)
#     4  pulse     pulses in this colour on the beat while held
#     5  chase     this colour runs across the room, once a bar
#     6  sparkle   random lamps flare in this colour
#     7  sweep     this colour fills the room from left to right
#     8  (top)     MULTI-COLOUR: rainbow, fire, sunset, aurora, ocean, golden
#                  (golden-angle colours), galaxy, confetti -- the colours are
#                  spread across the room and drift along it
#
#   PATTERNS (desk > Pads, off for now): when off, rows 1-7 don't make patterns --
#   every pad is simply its column's colour (held / latched); the top row still
#   plays its multi-colour effects.
#
#   Each ROW also picks the sacred geometry the TouchDesigner visuals show
#   (see hub_visuals.py): wash flower of life, glow golden angle, hit
#   Metatron's cube, pulse Chladni, chase Sri Yantra, sweep tesseract,
#   sparkle reaction-diffusion, top row ALL of them blended together.
#
#   LATCH (on by default): the last pad you pushed keeps playing after you let
#   go, until you push another pad. Hits play over it without replacing it.
#   "All pads off" (desk) or Delete (Push 2) clears it.
#
#   how hard you hit    = how bright it starts
#   pressure (press in) = a little brighter / fuller while you hold (Pressure on the
#                         desk's Pads tab sets how much; resting a finger does nothing)
#   touch strip         = bends the colour of everything you're playing
#   knobs (PLAY mode)   1 Master  2 Colour  3 Vibrance  4 Pad level  5 Attack
#                       6 Release  7 Pad speed  8 Spread
#
# Everything still goes through the flicker protection: however fast you
# play, no lamp flashes more often than the Flicker Guard allows.
# =============================================================================

import colorsys
import math
import random
import time

import hub_geometry as geo

GEO_OFFSET = 100                     # GEOMETRY-mode pads are notes 136-199 inside the engine

COLUMNS = [('red', (1.0, 0.0, 0.0)), ('orange', (1.0, 0.31, 0.0)), ('yellow', (1.0, 0.82, 0.0)),
           ('green', (0.0, 1.0, 0.12)), ('cyan', (0.0, 0.88, 1.0)), ('blue', (0.0, 0.25, 1.0)),
           ('violet', (0.54, 0.0, 1.0)), ('pink', (1.0, 0.16, 0.6))]
ROWS = ['wash', 'glow', 'hit', 'pulse', 'chase', 'sparkle', 'sweep']
RAINBOW = [(1.0, 0.0, 0.0), (1.0, 0.38, 0.0), (1.0, 0.85, 0.0), (0.0, 1.0, 0.05), (0.0, 0.3, 1.0),
           (0.28, 0.0, 1.0), (0.7, 0.0, 1.0)]
# top row: multi-colour effects (name, the colours, the colour the pad shows on Push)
MULTI = [('rainbow', RAINBOW, (1.0, 0.0, 0.0)),
         ('fire', [(1.0, 0.0, 0.0), (1.0, 0.25, 0.0), (1.0, 0.5, 0.0), (1.0, 0.75, 0.05), (1.0, 0.35, 0.0)],
          (1.0, 0.31, 0.0)),
         ('sunset', [(1.0, 0.8, 0.0), (1.0, 0.45, 0.0), (1.0, 0.1, 0.25), (0.75, 0.0, 0.6), (0.4, 0.0, 1.0)],
          (1.0, 0.82, 0.0)),
         ('aurora', [(0.0, 1.0, 0.25), (0.0, 1.0, 0.7), (0.0, 0.6, 1.0), (0.5, 0.0, 1.0), (0.0, 1.0, 0.45)],
          (0.0, 1.0, 0.12)),
         ('ocean', [(0.0, 0.88, 1.0), (0.0, 0.5, 1.0), (0.0, 1.0, 0.75), (0.1, 0.2, 1.0), (0.4, 0.9, 1.0)],
          (0.0, 0.88, 1.0)),
         ('golden', None, (0.0, 0.25, 1.0)),           # golden-angle colours, starting from blue
         ('galaxy', [(0.54, 0.0, 1.0), (1.0, 0.0, 0.8), (0.15, 0.1, 1.0), (0.8, 0.3, 1.0), (1.0, 0.2, 0.5)],
          (0.54, 0.0, 1.0)),
         ('confetti', None, (1.0, 0.16, 0.6))]          # every lamp a different bright colour, new each beat
MULTI_NAMES = [m[0] for m in MULTI]
PAD_DEFAULTS = dict(p_patterns=0.0, p_latch=1.0, p_pressure=0.3, p_level=1.0, p_attack=0.03, p_release=0.4, p_speed=1.0, p_spread=0.5)


def pad_info(note):
    """(effect, colour name, rgb) of a pad note 36-99."""
    row, col = (note - 36) // 8, (note - 36) % 8
    if row == 7:
        name, _, rgb = MULTI[col]
        return name, name, rgb
    name, rgb = COLUMNS[col]
    return ROWS[row], name, rgb


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _smooth01(x):
    x = _clamp(x)
    return x * x * (3 - 2 * x)


def _hsv_mix(a, b, t):
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


def _bend(rgb, amount):
    if abs(amount) < 1e-3:
        return rgb
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb((h + amount) % 1.0, s, v)


class Voice:
    def __init__(self, note, vel, now, beats):
        self.note = note
        if note >= 36 + GEO_OFFSET:
            self.form, self.name, self.kind, self.rgb = geo.geo_pad(note - GEO_OFFSET)
            self.effect = 'geo'
        else:
            self.effect, self.name, self.rgb = pad_info(note)
        self.vel = (vel / 127.0) ** 0.7
        self.pressure = 0.0
        self.t_on = now
        self.b_on = beats
        self.t_off = None
        self.level_at_off = 0.0
        self.seed = random.randint(0, 1 << 30)
        self.latched = False


class Pads:
    ONE_SHOT = {'hit'}

    def __init__(self, hub):
        self.hub = hub
        self.voices = {}
        self.bend = 0.0                # -1 .. 1 from the touch strip
        self.chan_pressure = 0.0
        self.freeze_held = False
        self.frozen = None
        self.touch = None

    # -- input --
    def latch_on(self):
        return self.hub.live.get('p_latch', 1.0) >= 0.5

    def note_on(self, note, vel, now, beats):
        if vel <= 0:
            return self.note_off(note, now)
        nv = Voice(note, vel, now, beats)
        if nv.effect in ROWS and self.hub.live.get('p_patterns', 0.0) < 0.5:
            nv.effect = 'wash'                         # Patterns off: rows 1-7 are just their colour
        self.touch = (now, note)                      # the visuals follow it: row = geometry, column = its shape
        if nv.effect not in self.ONE_SHOT:             # a new pad replaces the one that was latched
            for v in list(self.voices.values()):
                if v.latched:
                    self._release(v, now)
        self.voices[note] = nv
        if nv.effect == 'freeze':
            self.freeze_held = True

    def _release(self, v, now):
        if v.t_off is not None:
            return
        v.level_at_off = self.envelope(v, now)
        v.t_off = now
        v.latched = False
        if v.effect == 'freeze':
            self.freeze_held = any(x.effect == 'freeze' and x.t_off is None for x in self.voices.values() if x is not v)

    def note_off(self, note, now):
        v = self.voices.get(note)
        if not v or v.t_off is not None or v.latched:
            return
        newest = max((x for x in self.voices.values() if x.effect not in self.ONE_SHOT),
                     key=lambda x: x.t_on, default=None)
        if self.latch_on() and v is newest:
            v.latched = True                           # the last pad pushed stays on
            v.pressure = 0.0
            return
        self._release(v, now)

    def release_all(self, now, keep_latched=True):
        """Let go of every pad (switching Push modes); the latched one keeps playing."""
        for v in list(self.voices.values()):
            if not (keep_latched and v.latched):
                self._release(v, now)

    def pressure(self, value, note=None):
        # just resting a finger on a pad does nothing; Pressure (desk > Pads) sets how much the rest counts
        amount = _clamp(self.hub.live.get('p_pressure', 0.3))
        p = amount * _clamp((value / 127.0 - 0.3) / 0.7)
        if note is None:
            self.chan_pressure = p
            for v in self.voices.values():
                if v.t_off is None and not v.latched:
                    v.pressure = p
        elif note in self.voices:
            self.voices[note].pressure = p

    def pitch(self, value):
        self.bend = _clamp(value / 8192.0, -1.0, 1.0)

    def panic(self):
        """All pads off: everything (the latched pad too) fades out by Release."""
        self.release_all(time.time(), keep_latched=False)

    def latched(self):
        return [v for v in self.voices.values() if v.latched]

    def release_latched(self, now):
        for v in list(self.voices.values()):
            if v.latched:
                self._release(v, now)

    # -- shaping --
    def envelope(self, v, now):
        live = self.hub.live
        att = max(0.005, live.get('p_attack', 0.03)) * (6.0 if v.effect == 'glow' else 1.0)
        rel = max(0.02, live.get('p_release', 0.4)) * (4.0 if v.effect == 'glow' else 1.0)
        if v.effect in self.ONE_SHOT:
            return math.exp(-(now - v.t_on) / max(0.12, rel * 0.9))
        if v.t_off is None:
            return _clamp((now - v.t_on) / att)
        return v.level_at_off * math.exp(-(now - v.t_off) / rel)

    def active(self):
        return bool(self.voices)

    def geo_voices(self):
        return [v for v in self.voices.values() if v.effect == 'geo']

    def geo_spin(self):
        """The touch strip turns the geometry while a geometry pad is held."""
        return self.bend * math.pi if any(v.t_off is None for v in self.geo_voices()) else 0.0

    def palette(self, v, n):
        return geo.harmony(v.kind, v.rgb, n) if v.kind else [v.rgb] * n

    def geo_state(self, n):
        held = [v for v in self.geo_voices() if v.t_off is None]
        if not held:
            return None
        v = max(held, key=lambda x: x.t_on)
        pal = self.palette(v, max(2, n))
        return v.form, pal[0], pal[-1]

    def render(self, cols, beats, now):
        """Lay everything being played over the look's colours."""
        if not self.voices:
            self.frozen = None
            return cols
        if self.freeze_held:
            if self.frozen is None or len(self.frozen) != len(cols):
                self.frozen = list(cols)
            cols = list(self.frozen)
        else:
            self.frozen = None
        live = self.hub.live
        segs = self.hub.rig.segs
        n = max(1, len(segs))
        level_k = live.get('p_level', 1.0)
        spd = live.get('p_speed', 1.0)
        spread = _clamp(live.get('p_spread', 0.5))
        bend = self.bend * 0.25                                   # up to a quarter turn of the colour wheel
        out = list(cols)
        dead = []
        for note, v in sorted(self.voices.items(), key=lambda kv: kv[1].t_on):
            env = self.envelope(v, now)
            if v.t_off is not None and env < 0.004:
                dead.append(note)
                continue
            if v.effect in self.ONE_SHOT and env < 0.004:
                dead.append(note)
                continue
            # how hard you play sets BRIGHTNESS only, never the colour: a red pad is red on every lamp
            bright = _clamp((0.45 + 0.55 * max(v.vel, v.pressure)) * level_k * (1.0 + 0.5 * v.pressure))
            if v.effect == 'geo':                                 # sacred geometry pad
                order = sorted(range(len(segs)), key=lambda i: segs[i]['rank'])
                pal = self.palette(v, n)
                own = [None] * len(segs)
                for r, i in enumerate(order):
                    own[i] = pal[r]
                sp = _clamp(0.3 + 0.7 * max(spread, v.pressure))
                shape = geo.form(v.form, segs, beats * spd * 0.5, self.hub.geo_rot, own, sp)
                for i in range(len(segs)):
                    bb, gc = shape[i]
                    k = _clamp(bb * env)
                    if k > 0.002:
                        out[i] = _hsv_mix(out[i], tuple(c * bright for c in (gc or own[i])), k)
                continue
            rgb = _bend(v.rgb, bend)
            # BPM SYNC: the speed snaps to musical steps (x1/16 ... x4 of the beat), and if that would flash faster
            # than the Flicker Guard allows at this tempo, it halves (still on the grid) until it's safe.
            vs = self.synced_speed(spd, v.effect)
            b = (beats - v.b_on) * vs                             # beats since the pad went down
            t_beat = beats * vs
            rnd = random.Random(v.seed + int(math.floor(t_beat * 2)))
            if v.effect == 'confetti':
                rr = random.Random(v.seed + int(math.floor(t_beat)))
            for i, s in enumerate(segs):
                r = s['rank']
                pos = (r + 0.5) / n
                a = 1.0
                col = rgb
                e = v.effect
                if e == 'pulse':
                    a = math.exp(-(t_beat % 1.0) / (0.12 + 0.25 * spread))
                elif e == 'chase':
                    head = (t_beat * 0.25) % 1.0
                    d = abs(head - pos)
                    d = min(d, 1 - d) * n
                    a = math.exp(-d * d / (0.3 + 3.0 * spread))
                elif e == 'sparkle':
                    on = rnd.random() < (0.15 + 0.5 * spread)
                    a = (math.exp(-((t_beat * 2) % 1.0) / 0.3) if on else 0.0)
                elif e == 'sweep':
                    edge = _clamp(b)                              # fills the room over one beat
                    a = _clamp((edge - pos) / (0.05 + 0.3 * spread) + 0.5)
                elif e == 'confetti':                            # a different bright colour per lamp, each beat
                    hue = (rr.random() + i * 0.618) % 1.0
                    col = colorsys.hsv_to_rgb((hue + bend) % 1.0, 1.0, 1.0)
                elif e == 'golden':                              # golden-angle steps round the wheel, drifting
                    h0 = colorsys.rgb_to_hsv(*v.rgb)[0]
                    step = math.floor(t_beat * 0.5)
                    hue = h0 + (r + step) * geo.GOLDEN_ANGLE / 360.0
                    col = colorsys.hsv_to_rgb((hue + bend) % 1.0, 1.0, 1.0)
                elif e in MULTI_NAMES:                           # the colours spread across the room, drifting
                    pal = MULTI[MULTI_NAMES.index(e)][1]
                    m = len(pal)
                    x = (r / max(1, n) * m) + t_beat * 0.25 * (2.0 if e == 'fire' else 1.0)
                    j = int(math.floor(x)) % m
                    col = _bend(_hsv_mix(pal[j], pal[(j + 1) % m], _smooth01(x % 1.0)), bend)
                k = _clamp(a * env)                              # how much of the lamp this pad covers
                if k <= 0.002:
                    continue
                out[i] = _hsv_mix(out[i], tuple(c * bright for c in col), k)
        for note in dead:
            self.voices.pop(note, None)
        return out

    CYCLES_PER_BEAT = {'pulse': 1.0, 'chase': 0.25, 'sparkle': 2.0, 'confetti': 1.0}

    def synced_speed(self, spd, effect):
        s = 2.0 ** round(math.log(max(1.0 / 16, min(4.0, spd)), 2))
        per_beat = self.CYCLES_PER_BEAT.get(effect, 0.0)
        if per_beat > 0:
            try:
                tempo = float(self.hub.clock[1]) or 120.0
            except Exception:
                tempo = 120.0
            guard = max(0.5, float(self.hub.live.get('guard', 2.0)))
            while per_beat * (tempo / 60.0) * s > guard and s > 1.0 / 16:
                s /= 2.0
        return s

    def describe(self):
        held = [v for v in self.voices.values() if v.t_off is None]
        lat = 'latched: ' if held and all(v.latched for v in held) else ''
        return lat + ', '.join(('%s %s' % (v.name, v.form)) if v.effect == 'geo' else
                         ('%s %s' % (v.name, v.effect) if v.name != v.effect else v.effect) for v in held)
