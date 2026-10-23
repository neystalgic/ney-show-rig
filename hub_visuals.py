# =============================================================================
# HUE HUB -- what the TouchDesigner visuals follow
#
# 30 times a second the hub sends TouchDesigner (UDP 127.0.0.1:7012):
#   colora / colorb   the room's two main colours, taken from what the lamps
#                     are REALLY showing right now (look, pads, hits, all of it)
#   x, zoom, turn,    where across the pads you last played (left -> right)
#   build, line       shapes the geometry: smaller -> bigger, an extra turn,
#                     partly drawn -> whole, thin -> bold lines (it glides there)
#   vcols             each visual's own two colours: on the top row every
#                     geometry in the blend takes a different lamp's colour
#   energy            0-1: how bright the room is -- the visuals swell with it
#   press             0-1: how hard you're pressing a pad
#   vis               which sacred-geometry visual matches what's playing
#                     (the geometry pad's form, or the PLAY pad's row, or the
#                     look's geometry motion)
#   rot, phase, chladni, tempo, master, guard  -- the shared geometry clock
#   akick, asnare,    the gear through the Scarlett (hub_audioshow): each drum's
#   ahats, alevel,    hit (0-1, decaying), how loud the music is, how bright it
#   abright, adrop    sounds, and the drop after a breakdown -- the geometry
#   section           pumps, glows, sparkles and bursts with it
#
# Flicker safety: build, energy, press, the drums and colours go through the same
# flicker protection as the lamps (Flicker Guard, never above 3 a second),
# and the visual can only change once every 1 / Flicker Guard seconds
# (TouchDesigner cross-fades it).
# =============================================================================

import colorsys
import math
import time

import hub_geometry as geo
import hub_pads
import hue_stream as hs

# PLAY-mode pad rows (bottom to top) -> the sacred geometry the visuals show
#   wash      flower of life        glow    golden angle      hit    Metatron's cube
#   pulse     Chladni plate         chase   Sri Yantra        sparkle reaction-diffusion
#   sweep     tesseract             top row (multi-colour)    all of them, blended
ROW_FORMS = ['flower', 'golden', 'metatron', 'chladni', 'yantra', 'reaction', 'tesseract', 'blend']
# When the music runs the show: sacred geometry and the procedural pieces (build_hue_hub_td.py) in turn
AUDIO_FORMS = ['flower', 'warp', 'golden', 'truchet', 'metatron', 'quasicrystal', 'contours', 'yantra', 'life',
               'attractor', 'chladni', 'mandala', 'harmonograph', 'tesseract', 'voronoi', 'reaction', 'kaleido']
BREAK_FORMS = ['warp', 'contours', 'harmonograph', 'reaction', 'attractor']   # breakdowns: slow and organic
PAD_HOLD = 20.0                     # a pad you touch keeps its visual this long before the music takes over


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _smooth(x):
    x = _clamp(x)
    return x * x * (3 - 2 * x)


def room_colours(cols):
    """The room's two main colours (0-1 rgb, brightest channel = 1), or None if it's dark."""
    items = []
    for c in cols:
        m = max(c)
        if m < 0.03:
            continue
        n = tuple(_clamp(x / m) for x in c)
        h, s, _ = colorsys.rgb_to_hsv(*n)
        items.append((m, s, h, n))
    if not items:
        return None
    a = max(items, key=lambda it: it[0] * (0.35 + it[1]))

    def hue_gap(it):
        return abs(((it[2] - a[2] + 0.5) % 1.0) - 0.5) * 2.0       # 0 same hue .. 1 opposite

    b = max(items, key=lambda it: it[0] * (0.15 + min(it[1], a[1]) * hue_gap(it)) if it is not a else -1)
    if b is a or (hue_gap(b) < 0.06 and abs(b[1] - a[1]) < 0.15):
        # one colour in the room: a lighter version of it for the second colour
        bb = colorsys.hsv_to_rgb(a[2], a[1] * 0.5, 1.0)
        return a[3], tuple(bb)
    return a[3], b[3]


# The visuals TouchDesigner has, in this order (same list as GEO_VISUALS in build_hue_hub_td.py):
# each one gets its own pair of colours (vcols) -- on the top row, a different lamp's colour each
VIS_ORDER = ['golden_angle', 'flower_of_life', 'metatrons_cube', 'sri_yantra', 'chladni', 'tesseract',
             'kaleidoscope', 'reaction_diffusion']


def column_shape(x):
    """Where you play across the pads (0 = left column, 1 = right) shapes the geometry:
    zoom (smaller -> bigger), turn (an extra 0-157.5 degrees), build (partly drawn -> whole),
    line (thin -> bold)."""
    return dict(zoom=0.7 + 0.7 * x, turn=157.5 * x, build=0.55 + 0.45 * x, line=0.6 + 1.2 * x)


class Visuals:
    def __init__(self, hub):
        self.hub = hub
        self.lim = hs.FlashLimiter(2.0)
        self.ca = (1.0, 0.78, 0.38)
        self.cb = (0.62, 0.36, 1.0)
        self.vcols = [(self.ca, self.cb)] * len(VIS_ORDER)
        self.seen_look = None
        self.look_t = -1.0
        self.vis = 'flower'
        self.vis_t = -10.0
        self.last = None
        self.x = 0.5                    # where across the pads you last played (glides)
        self.shape = column_shape(0.5)
        self.turn_steps = 0.0

    def audio_form(self):
        """When the music runs the show (and no pad was touched for a while): a new visual every phrase
        and on every drop, slow organic ones in breakdowns, everything blended right after a drop."""
        au = getattr(self.hub, 'audioshow', None)
        if au is None or au.gate < 0.5 or not self.hub.state['settings'].get('audio_on', True):
            return None
        if au.section == 'breakdown':
            return BREAK_FORMS[au.vis_i % len(BREAK_FORMS)]
        if au.section == 'drop':
            return 'blend'
        return AUDIO_FORMS[au.vis_i % len(AUDIO_FORMS)]

    def wanted_form(self, look):
        """The LAST pad you pushed picks the geometry (its row, or a geometry pad's form) and it
        stays until you push another pad; after a look change, the look's own geometry motion.
        With the music playing and no pad touched for PAD_HOLD seconds, the music picks."""
        touch = getattr(self.hub.pads, 'touch', None)
        if touch is None or time.time() - touch[0] > PAD_HOLD:
            af = self.audio_form()
            if af is not None:
                return af
        if touch is not None and touch[0] >= self.look_t:
            note = touch[1]
            if note >= 36 + hub_pads.GEO_OFFSET:
                return geo.geo_pad(note - hub_pads.GEO_OFFSET)[0]
            row = (note - 36) // 8
            if 0 <= row < 8:
                return ROW_FORMS[row]
        m = look.get('motion')
        return m if m in geo.FORMS else None

    def lamp_palette(self, seen):
        """The colour each lamp zone shows, in room order, as 8 colours (repeating if fewer zones)."""
        h = self.hub
        chan = {ch: i for i, ch in enumerate(h.rig.channels)}
        cols = []
        for sg in sorted(h.rig.segs, key=lambda z: z['rank']):
            k = chan.get(sg['ch'])
            if k is not None and k < len(seen):
                c = seen[k]
                m = max(c)
                cols.append(tuple(_clamp(v / m) for v in c) if m > 0.03 else None)
        cols = [c for c in cols if c is not None] or [self.ca, self.cb]
        return [cols[i % len(cols)] for i in range(len(VIS_ORDER))]

    def step(self, now):
        """The message for TouchDesigner (call with the hub's lock held)."""
        h = self.hub
        dt = 0.033 if self.last is None else _clamp(now - self.last, 0.0, 0.25)
        self.last = now
        look = h.look(h.active) or {}
        beats, tempo, _ = h.clock
        guard = _clamp(h.live.get('guard', 2.0), 0.5, 3.0)
        self.lim.set_rate(guard)
        if h.active != self.seen_look:
            self.seen_look = h.active
            self.look_t = now

        # across the pads: the column of the last PLAY pad shapes the geometry (it glides there)
        touch = getattr(h.pads, 'touch', None)
        au = getattr(h, 'audioshow', None)
        music = (touch is None or time.time() - touch[0] > PAD_HOLD) and au is not None and au.gate > 0.5
        if music:                                       # the music shapes it: a new size / turn each phrase
            target = ((au.vis_i * 3) % 8) / 7.0
        elif touch is not None and 36 <= touch[1] <= 99:
            target = ((touch[1] - 36) % 8) / 7.0
        else:
            target = self.x
        self.x += (target - self.x) * (1.0 - math.exp(-dt / 0.35))
        shape = column_shape(self.x)
        if music:                                       # ...and it turns a step (45 degrees) every bar
            bar = getattr(au, 'bar_now', 0)
            self.turn_steps += (bar * 45.0 - self.turn_steps) * (1.0 - math.exp(-dt / 0.25)) \
                if abs(bar * 45.0 - self.turn_steps) < 400 else (bar * 45.0 - self.turn_steps)
            shape['turn'] = shape['turn'] + self.turn_steps

        # the room's colours and brightness, from what the lamps really show
        out = list(h.out)
        cal = h.state['calibration']
        pf = h.proof_fn if cal.get('proof', True) else (lambda c: tuple(c))  # as the bulbs really show them
        seen = [pf(c) for c in out]
        g = h.pads.geo_state(len(h.rig.segs))
        pal = (pf(g[1]), pf(g[2])) if g else room_colours(seen)       # a geometry pad: its harmony IS the room's palette
        if pal is not None:
            def full(c):
                m = max(c) or 1.0
                return tuple(_clamp(x / m) for x in c)       # keep it a full-strength colour
            self.ca = full(pal[0])
            self.cb = full(pal[1])
        energy = sum(max(c) for c in out) / max(1, len(out))
        press = max([v.pressure for v in h.pads.voices.values() if v.t_off is None] + [0.0])

        # which visual: changes at most once every 1 / Flicker Guard seconds
        want = self.wanted_form(look)
        if want and want != self.vis and now - self.vis_t >= 1.0 / guard + 0.1:
            self.vis, self.vis_t = want, now

        # each visual's own colours: on the top row (blend) every geometry takes a different lamp's
        # colour, so the blend is as many-coloured as the room; otherwise the room's two colours
        if self.vis == 'blend':
            lp = self.lamp_palette(seen)
            want_cols = [(lp[i], lp[(i + 1) % len(lp)]) for i in range(len(VIS_ORDER))]
        else:
            want_cols = [(self.ca, self.cb)] * len(VIS_ORDER)
        kk = 1.0 - math.exp(-dt / 0.3)                        # a colour hand-over glides, never jumps
        self.vcols = [tuple(tuple(p + (q - p) * kk for p, q in zip(cur, new)) for cur, new in zip(cp, wp))
                      for cp, wp in zip(self.vcols, want_cols)]

        master = 0.0 if h.blackout else _clamp(h.live.get('master', 1.0))
        lines = [(shape['build'], _clamp(energy), _clamp(press)), self.ca, self.cb, (master, master, master),
                 (_clamp((shape['line'] - 0.6) / 1.2), _clamp((shape['zoom'] - 0.7) / 0.7), 0.0)]
        for a_, b_ in self.vcols:
            lines += [a_, b_]
        # the gear (hub_audioshow): kick / snare / hats hits and how loud + bright the music is.
        # Each is its own signal through the flicker protection, so a fast hat line can't strobe.
        au = h.audioshow
        f = au.feat
        ag = 0.0 if not h.state['settings'].get('audio_on', True) else _clamp(h.live.get('a_amt', 0.8)) * au.gate
        ak, asn, ah = (_clamp(au.env[k] * ag) for k in ('kick', 'snare', 'hats'))
        alv = _clamp((f['level']['level'] if f else 0.0) * ag)
        abr = _clamp(f['bright'] if f else 0.5)
        adr = _clamp(au.drop * ag * _clamp(h.live.get('a_drop', 0.7)))     # the drop: a burst that rings out
        lines += [(ak, ak, ak), (asn, asn, asn), (ah, ah, ah), (alv, abr, 0.0), (adr, adr, adr)]
        res = self.lim.step(lines, now)
        sig, ca, cb, mst, lz = res[:5]
        vc = res[5:5 + 2 * len(VIS_ORDER)]
        akl, asl, ahl, alb, adl = res[5 + 2 * len(VIS_ORDER):]
        vcols = [list(vc[2 * i]) + list(vc[2 * i + 1]) for i in range(len(VIS_ORDER))]

        # every lamp zone's colour as the bulb shows it right now (Shape Mapper: shapes lit like a lamp)
        chan = {ch: i for i, ch in enumerate(h.rig.channels)}
        lamps = []
        for sg in sorted(h.rig.segs, key=lambda z: z['rank']):
            k_ = chan.get(sg['ch'])
            if k_ is None or k_ >= len(seen):
                continue
            lp = h.rig.lamps[sg['lamp']] if 0 <= sg.get('lamp', -1) < len(h.rig.lamps) else {}
            label = lp.get('name', sg['key']) + (' (zone %d)' % (sg['index'] + 1) if sg.get('of', 1) > 1 else '')
            lamps.append([sg['key'], label] + [round(_clamp(v), 4) for v in seen[k_]])

        t = h.t_motion
        (n1, m1), (n2, m2), k, sign = geo.chladni_mode(t)
        return dict(t=round(now, 4), beats=beats, tempo=tempo, phase=t, rot=math.degrees(h.geo_rot) % 360.0,
                    chladni=[n1 + (n2 - n1) * k, m1 + (m2 - m1) * k, sign], step=int(math.floor(t)),
                    form=look.get('motion', 'still'), vis=self.vis,
                    build=sig[0], energy=sig[1], press=sig[2], colora=list(ca), colorb=list(cb),
                    x=round(self.x, 4), zoom=0.7 + 0.7 * lz[1], turn=shape['turn'], line=0.6 + 1.2 * lz[0],
                    vcols=[[round(v, 4) for v in c] for c in vcols],
                    lamps=lamps,
                    akick=round(akl[0], 4), asnare=round(asl[0], 4), ahats=round(ahl[0], 4),
                    alevel=round(alb[0], 4), abright=round(alb[1], 4), adrop=round(adl[0], 4),
                    section=au.section,
                    guard=guard, master=mst[0],
                    movie=bool(h.state['settings'].get('movie')), moviesrc=h.state['settings'].get('movie_src', 'capture'))
