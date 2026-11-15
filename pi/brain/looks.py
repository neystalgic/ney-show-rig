#!/usr/bin/env python3
# =============================================================================
# PI LOOKS -- Rig 2.0 Phase 1a (away loop, Nov 14). The calm looks the Pi runs while the Mac is asleep,
# made to match the Mac's rig_control looks exactly (same colours, brightness, fade times, same breathing).
#   static looks : purple, purplenight, nightlight, night, morning, cozy, bright, off   (one fade, done)
#   ambient looks: rainbow (every lamp the SAME colour, breathing -- Michael's rainbow), breathe, breathe_slow,
#                  rainbowroom, upbeat, redglow, movieglow                               (a background loop)
# The ambient maths is ambient_fade.py's, ported: same wheel (WHEEL below, made by make_wheel.py from
# hub_palette.vivid + hue_stream.rgb_to_xyb), same breath shape, same 1.25 s / 2 s steps aimed at where the colour
# will be when the bulb's fade ends, gradient lamps get 5 points.
# Lamps only. Smart plugs are never switched; heads and spots are never touched from the Pi (they stay the Mac's).
# Nothing blocks: ambient looks run in one daemon thread; starting any look (or stop()) ends the old loop.
# Hue calls go through the hue(method, path, body) function the brain passes in (Pi's own key) -- easy to fake.
# =============================================================================
import copy, math, threading, time

PURPLE, RED, SKY = (0.27, 0.12), (0.69, 0.30), (0.22, 0.27)


def _on(bri, xy=None, mirek=None, ms=800):
    b = {'on': {'on': True}, 'dimming': {'brightness': float(bri)}}
    if xy:
        b['color'] = {'xy': {'x': xy[0], 'y': xy[1]}}
    if mirek:
        b['color_temperature'] = {'mirek': mirek}
    b['dynamics'] = {'duration': ms}
    return b


# name -> (spoken reply, Hue body)  -- numbers copied from rig_control.LOOKS (Nov 14)
STATIC = {
    'purple': ('Purple, full brightness.', _on(100, PURPLE, ms=800)),
    'purplenight': ('Purple night light. Sleep well.', _on(15, PURPLE, ms=3000)),
    'nightlight': ('Red night light.', _on(12, RED, ms=2500)),
    'night': ('Night mode: red night light. The Mac is asleep, so the heads are left as they are.', _on(12, RED, ms=2500)),
    'morning': ('Morning blue.', _on(60, SKY, ms=8000)),
    'cozy': ('Cozy.', _on(60, mirek=370, ms=1500)),
    'bright': ('Bright white.', _on(100, mirek=200, ms=600)),
    'off': ('Lights off.', {'on': {'on': False}, 'dynamics': {'duration': 1500}}),
}


def _amb(bri, turn, spread, breath=0.0, bri_lo=None, hue_lo=None, hue_hi=None):
    """Same arguments, same defaults as ambient_fade.py (and rig_control.start_ambient)."""
    return dict(bri=float(bri), turn=float(turn), spread=float(spread), breath=float(breath),
                bri_lo=float(bri) * 0.35 if bri_lo is None else float(bri_lo), hue_lo=hue_lo, hue_hi=hue_hi)


# name -> (spoken reply, ambient settings) -- the start_ambient(...) arguments in rig_control.LOOKS (Nov 14)
AMBIENT = {
    'rainbow': ('Rainbow breathing, every lamp in sync.', _amb(75, 90, 0, 10, 22)),
    'breathe': ('Calm breathing colours.', _amb(70, 300, 140, 10, 22)),
    'breathe_slow': ('Slow breathing colours.', _amb(65, 420, 140, 16, 18)),
    'rainbowroom': ('Rainbow across the room.', _amb(70, 120, 240)),
    'upbeat': ('Upbeat: bright rainbow drifting across the room.', _amb(90, 150, 240)),
    'redglow': ('Red glow: purples, pinks and reds, dim.', _amb(40, 120, 50, 0, 0, 315, 365)),
    'movieglow': ('Movie glow, lamps only -- the heads need the Mac.', _amb(30, 90, 0, 0, 0, 255, 350)),
}

# Hue xy of the Mac's colour wheel every 5 degrees (made by make_wheel.py -- rerun it if hub_palette changes)
WHEEL = [
    (0.5076, 0.2375), (0.5393, 0.2537), (0.5709, 0.2700), (0.6025, 0.2861), (0.6338, 0.3021), (0.6500, 0.3183),
    (0.6472, 0.3331), (0.6201, 0.3541), (0.5975, 0.3715), (0.5784, 0.3863), (0.5618, 0.3991), (0.5470, 0.4105),
    (0.5336, 0.4208), (0.5212, 0.4304), (0.5096, 0.4394), (0.4984, 0.4480), (0.4876, 0.4563), (0.4770, 0.4645),
    (0.4663, 0.4727), (0.4555, 0.4811), (0.4444, 0.4897), (0.4327, 0.4987), (0.4203, 0.5083), (0.4069, 0.5186),
    (0.3923, 0.5299), (0.3761, 0.5424), (0.3577, 0.5566), (0.3366, 0.5729), (0.3120, 0.5919), (0.2909, 0.5916),
    (0.2681, 0.5777), (0.2394, 0.5753), (0.2136, 0.5514), (0.2089, 0.4921), (0.2051, 0.4489), (0.2019, 0.4155),
    (0.1992, 0.3883), (0.1967, 0.3654), (0.1945, 0.3456), (0.1925, 0.3279), (0.1905, 0.3118), (0.1887, 0.2968),
    (0.1869, 0.2827), (0.1851, 0.2691), (0.1833, 0.2558), (0.1814, 0.2425), (0.1795, 0.2290), (0.1775, 0.2150),
    (0.1752, 0.2003), (0.1728, 0.1843), (0.1699, 0.1664), (0.1665, 0.1455), (0.1620, 0.1188), (0.1644, 0.1065),
    (0.1702, 0.1041), (0.1758, 0.1013), (0.1801, 0.0954), (0.1870, 0.0931), (0.1944, 0.0907), (0.2025, 0.0881),
    (0.2113, 0.0849), (0.2259, 0.0924), (0.2425, 0.1010), (0.2611, 0.1106), (0.2819, 0.1213), (0.3048, 0.1331),
    (0.3299, 0.1461), (0.3568, 0.1599), (0.3851, 0.1745), (0.4147, 0.1897), (0.4451, 0.2053), (0.4761, 0.2213),
]
MAX_PUTS_PER_S = 10.0          # the Hue bridge's comfortable average rate for single-light commands (tests check it)


def looks():
    """Every look the Pi can run alone."""
    return sorted(set(STATIC) | set(AMBIENT))


# ---------------------------------------------------------------- pure maths (no lights, easy to test)
def wheel_xy(h):
    """Hue xy for hue h (degrees), smoothly between the 5-degree table entries."""
    h = (h % 360.0) / 5.0
    i = int(h) % len(WHEEL)
    f = h - int(h)
    a, b = WHEEL[i], WHEEL[(i + 1) % len(WHEEL)]
    return (round(a[0] + (b[0] - a[0]) * f, 4), round(a[1] + (b[1] - a[1]) * f, 4))


def breath_level(t, breath):
    """0..1: a calm breath -- 40% of the time breathing in (rising), 60% breathing out (falling), eased."""
    ph = (t % breath) / breath
    k = ph / 0.4 if ph < 0.4 else 1.0 - (ph - 0.4) / 0.6
    return 0.5 - 0.5 * math.cos(math.pi * k)


def step_s(spec):
    return 1.25 if spec['breath'] else 2.0


def base_hue(spec, t):
    if spec['hue_lo'] is not None and spec['hue_hi'] is not None:      # drift lo -> hi -> lo, one round trip per turn
        return spec['hue_lo'] + (spec['hue_hi'] - spec['hue_lo']) * (0.5 - 0.5 * math.cos(2 * math.pi * t / spec['turn']))
    return (t / spec['turn']) * 360.0


def frame(spec, t, gradient):
    """The bodies to send at time t (seconds since the look started), one per lamp in room order.
    gradient: a list of True/False per lamp (True = gradient lamp, gets 5 points). Aims where the colour will be
    when the bulb's fade ends, like ambient_fade.py."""
    st = step_s(spec)
    ta = t + st
    base = base_hue(spec, ta)
    bri = spec['bri_lo'] + (spec['bri'] - spec['bri_lo']) * breath_level(ta, spec['breath']) if spec['breath'] else spec['bri']
    n = len(gradient)
    out = []
    for i, grad in enumerate(gradient):
        h = base + spec['spread'] * (i / max(1, n - 1) - 0.5)
        body = {'on': {'on': True}, 'dimming': {'brightness': round(bri, 2)}, 'dynamics': {'duration': int(st * 1000)}}
        if grad:
            pts = [wheel_xy(h + (j / 4.0 - 0.5) * (spec['spread'] / max(1, n - 1)) * 2) for j in range(5)]
            body['gradient'] = {'points': [{'color': {'xy': {'x': x, 'y': y}}} for x, y in pts]}
        else:
            x, y = wheel_xy(h)
            body['color'] = {'xy': {'x': x, 'y': y}}
        out.append(body)
    return out


def lamp_order(hue, is_plug):
    """[(light id, is gradient)] left to right as the lamps stand in the 'Music area' (as ambient_fade.py does).
    No Music area? every lamp, sorted by name. Plugs and on/off-only devices are always left out."""
    lights = {l['id']: l for l in hue('GET', 'light').get('data', [])}
    ok = lambda rid: rid in lights and not is_plug(lights[rid])
    order = []
    try:
        areas = [a for a in hue('GET', 'entertainment_configuration').get('data', [])
                 if (a.get('metadata') or {}).get('name') == 'Music area']
        if areas:
            ents = {e['id']: e for e in hue('GET', 'entertainment').get('data', [])}
            spots = []
            for sl in areas[0]['locations']['service_locations']:
                rr = ents.get(sl['service']['rid'], {}).get('renderer_reference', {})
                if rr.get('rtype') == 'light' and ok(rr.get('rid')) and sl.get('positions'):
                    spots.append((sum(p['x'] for p in sl['positions']) / len(sl['positions']), rr['rid']))
            order = [rid for _, rid in sorted(spots)]
    except Exception:
        order = []
    if not order:
        order = sorted((rid for rid in lights if ok(rid)), key=lambda r: ((lights[r].get('metadata') or {}).get('name') or '', r))
    return [(rid, bool(lights[rid].get('gradient'))) for rid in order]


# ---------------------------------------------------------------- the engine
class Engine:
    """run(name) starts a look (ends any running ambient loop first); stop() ends the loop. Never blocks."""

    def __init__(self, hue, lamps, is_plug, log=print, clock=time.time, sleep=time.sleep):
        self.hue, self.lamps, self.is_plug, self.log = hue, lamps, is_plug, log
        self.clock, self.sleep = clock, sleep
        self.gen = 0
        self.look = None
        self.thread = None

    def stop(self):
        self.gen += 1

    def run(self, name):
        """Returns the spoken reply, or None if the Pi can't do this look alone (shows, movies, heads)."""
        if name in STATIC:
            self.stop()
            self.lamps(copy.deepcopy(STATIC[name][1]))      # a copy: the table never changes
            self.look = name
            return STATIC[name][0]
        if name in AMBIENT:
            self.stop()
            gen = self.gen
            self.look = name
            self.thread = threading.Thread(target=self._loop, args=(gen, AMBIENT[name][1]), name='pi-look-' + name, daemon=True)
            self.thread.start()
            return AMBIENT[name][0]
        return None

    def _alive(self, gen):
        return self.gen == gen

    def _wait(self, secs, gen):
        """Sleep in small slices so a new look takes over within ~0.1 s."""
        end = self.clock() + secs
        while self._alive(gen):
            left = end - self.clock()
            if left <= 0:
                return True
            self.sleep(min(0.1, left))
        return False

    def _loop(self, gen, spec, max_frames=None):
        try:
            order = lamp_order(self.hue, self.is_plug)
        except Exception as e:
            self.log('pi look: lamp list failed (%s) -- look not started' % e.__class__.__name__)
            return 0
        if not order:
            self.log('pi look: no lamps found')
            return 0
        try:                                                     # stop any built-in Hue effect first (as the Mac does)
            for rid, _ in order:
                self.hue('PUT', 'light/%s' % rid, {'effects_v2': {'action': {'effect': 'no_effect'}}})
        except Exception:
            pass
        st = step_s(spec)
        gap = 0.12 if spec['spread'] else 0.02                  # the Mac's gaps: all-one-colour goes back to back so they move together
        t0, frames, errors = self.clock(), 0, 0
        while self._alive(gen) and (max_frames is None or frames < max_frames):
            started = self.clock()
            bodies = frame(spec, started - t0, [g for _, g in order])
            for (rid, _), body in zip(order, bodies):
                if not self._alive(gen):
                    return frames
                try:
                    self.hue('PUT', 'light/%s' % rid, body)
                    errors = 0
                except Exception as e:
                    errors += 1
                    if errors in (1, 20):
                        self.log('pi look: %s failed (%s)' % (rid, e.__class__.__name__))
                if not self._wait(gap, gen):
                    return frames
            frames += 1
            if not self._wait(max(0.0, st - (self.clock() - started)), gen):
                return frames
            if errors >= 40:                                     # bridge gone: back off instead of hammering it
                self._wait(30, gen)
        return frames
