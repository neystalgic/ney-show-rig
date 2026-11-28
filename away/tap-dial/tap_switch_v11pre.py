#!/usr/bin/env python3
# =============================================================================
# TAP DIAL v7 (Michael, Nov 17): taps never switch anything on or off -- only HOLDS do.
#            TAP                                        HOLD
#   1 COLOUR next colour for EVERYTHING that's on:      lamps on / off (ROY G BIV + pink)
#            lamps, heads (whatever they're doing) and
#            spot beams (nearest colour-wheel slot; UV
#            modes stay UV) -- red, orange, yellow,
#            blue, green, violet, indigo, pink
#   2 HEADS  next heads mode (glow, lamp colour,        heads plugs on / off
#            rainbow, sweep)
#   3 SPOTS  next spot mode (UV tapestry, UV scan,      spot plugs on / off
#            6 gobos)
#   4 SCENES next scene: Studio work, Movie, Night sky, RAINBOW: first hold = All-out rainbow, each hold after
#            Chill, Show, All-out rainbow, Rainbow wave, that = the next rainbow (wave, bounce, loop)
#            Rainbow bounce, Rainbow loop, Rainbow       -- uses only what's on, nothing switched
#            steps (all in sync) -- each scene
#            uses ONLY what is already on
# RAINBOW WAVES (v10) use Michael's zones (1A 1B | 2A 2B | 3A from the front door): every zone's lamps, heads and
# spots share the zone's colour; wave = door -> studio, bounce = there and back, loop = round the room.
#   DIAL     brightness of everything that's on
# No double taps (every tap counts, no waiting). A group that's off ignores its taps and is left out of scenes.
# Heads, spots and lamps are independent layers (heads + spots: this module's own DMX, no Hue Hub); only the Movie and
# Show scenes use the hub. Buttons never speak. Aim mode (calibration) only while bridge/tap_aim.json exists.
# Setup in the Hue app: leave every button + the dial with NO action. Log: bridge/outbox/tap_dial.txt
# =============================================================================
import colorsys, json, math, os, queue, socket, threading, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'tap_switch.json')
DIAL_FILE = os.path.join(HERE, 'dial.json')          # ambient_fade.py reads it (intensity 0-1)
LOG = os.path.join(HERE, 'bridge', 'outbox', 'tap_dial.txt')

SCENES = ['studio', 'movie', 'nightsky', 'chill', 'show', 'rainbow', 'rwave', 'rbounce', 'rloop', 'rsteps']
RAINBOWS = ['rainbow', 'rwave', 'rbounce', 'rloop', 'rsteps']   # hold 4 steps through these
STEP_S = 2.0                                          # rainbow steps: a new colour every 2 s (snap, then hold)
STEP_GOBOS = [16, 32, 48, 64, 80, 96]
SCENE_NAMES = {'studio': 'Studio work', 'movie': 'Movie', 'nightsky': 'Night sky', 'chill': 'Chill', 'show': 'Show',
               'rainbow': 'All-out rainbow', 'rwave': 'Rainbow wave', 'rbounce': 'Rainbow bounce', 'rloop': 'Rainbow loop', 'rsteps': 'Rainbow steps'}
ZONES_DEFAULT = {'1A': {'heads': [3], 'lamps': ['Top Lamp', 'Hue color lamp 2'], 'spots': [2]},
                 '1B': {'heads': [2], 'lamps': ['Hue Play floor lamp large 1']},
                 '2A': {'heads': [4], 'lamps': ['Floor Shade'], 'spots': [1]},
                 '2B': {'heads': [1], 'lamps': []},
                 '3A': {'heads': [], 'lamps': ['Hue color lamp 1', 'Behind Desk']}}
WAVE_T = {'rwave': 20.0, 'rbounce': 40.0, 'rloop': 20.0, 'rsteps': 16.0, 'rall': 20.0, 'rsync': 120.0}
NOPINK_TOP = 275.0     # Michael, Nov 17: no pink in rainbow modes (the spots can't follow) -- rainbows go red..violet
                       # and back (ROYGBIV, VIBGYOR) instead of wrapping through magenta / pink
RAINBOW_COLOURS = 7    # rainbow steps use ROY G BIV (pink stays on button 1 only)
PURPLE = (110, 0, 255)
WHEEL_SLOT = {'red': 22, 'orange': 22, 'yellow': 67, 'blue': 37, 'green': 52, 'violet': 97, 'indigo': 97, 'pink': 82}
HUE_COLOURS = [('red', (255, 0, 0)), ('orange', (255, 90, 0)), ('yellow', (255, 210, 0)), ('green', (0, 255, 30)),
               ('blue', (0, 110, 255)), ('indigo', (60, 0, 255)), ('violet', (170, 0, 255)), ('pink', (255, 30, 150))]   # ROY G BIV + pink
HEAD_MODES = ['glow', 'colour', 'rainbow', 'sweep']
SPOT_MODES = ['uv', 'uvscan', 'gobo16', 'gobo32', 'gobo48', 'gobo64', 'gobo80', 'gobo96']
SHOW_MODES = ['auto', 'wave', 'loop', 'call', 'pulse', 'split', 'orbit', 'relay']
DEFAULTS = {'enabled': True, 'device_id': None, 'show_modes': SHOW_MODES, 'rainbow_s': 60,
            'double_window': 0.45,     # seconds between the two presses of a double tap (bridge timestamps)
            'settle': 0.2,             # after a release arrives, wait this long for a 2nd press (the bridge sends
                                       # the release + any 2nd press together, ~0.9 s after the first press)
            'dial_step': 0.001,        # brightness per dial step (the dial sends ~300 steps per flick)
            'dial_min': 0.05, 'morning_ends': 10, 'morning_starts': 5,
            'dial_reverse': False}     # True if the dial ever feels backwards (right must always = up)

# Ceiling aims per spot (az = the spot's own pan angle, lean = degrees from straight up). Picked clear of each
# spot's avoid zones and walls in the node config; the node clamps anything else anyway.
SPOT_AIM = {4: {'az': 90.0, 'lean': 22.0, 'drift': 12.0, 'drift_s': 45.0},
            5: {'az': 200.0, 'lean': 22.0, 'drift': 12.0, 'drift_s': 50.0}}
SLOT_VIOLET, SLOT_PINK = 97, 82                       # Focus Spot colour wheel (nearest to purple)
UV_TAPESTRY = {4: {'az': 197.0, 'lean': 40.0, 'drift': 0.0, 'drift_s': 45.0},     # tapestry centres, calibrated
               5: {'az': 191.2, 'lean': 67.0, 'drift': 0.0, 'drift_s': 45.0}}     # with Michael Nov 17 (Tap Dial)
# the tapestry's corners per spot, as Michael steered them (pan16, tilt16), in order round the edge
UV_CORNERS = {4: [(30780, 46966), (27132, 48056), (20729, 45857), (16162, 38217)],   # art+door, door+kitchen, projector, studio
              5: [(24068, 51594), (26837, 49960), (21342, 47228), (21341, 51594)]}   # art+door, kitchen, mirror, studio
UV_SCAN_S = 32.0                                      # one lap of the four corners
SPOT_LOOK = {'uv': dict(uv=True, gobo=0, focus=128, breathe=0, aim=UV_TAPESTRY),
             'uvscan': dict(uv=True, gobo=0, focus=128, breathe=0, aim=UV_TAPESTRY, scan=True),
             'rainbowgobo': dict(uv=False, gobo=32, focus=150, breathe=40, aim=SPOT_AIM, wheel=True, fast=True),
             'zonewave': dict(uv=False, gobo=48, focus=150, breathe=40, aim=SPOT_AIM, zone=True),
             'zonesteps': dict(uv=False, gobo=48, focus=150, breathe=0, aim=SPOT_AIM, zone=True, gobo_steps=True)}
for _g in (16, 32, 48, 64, 80, 96):
    SPOT_LOOK['gobo%d' % _g] = dict(uv=False, gobo=_g, focus=150, breathe=40, aim=SPOT_AIM)


def _hub_fx(name):
    """The same ceiling look as hub spot_fx (used while the hub runs: dance / relay / show)."""
    L = SPOT_LOOK[name]
    aim = L['aim']
    fx = dict(hold=dict(aim[4]), hold_when='always', hold_head=4, level=1.0, gobo=L['gobo'], focus=L['focus'],
              breathe=L['breathe'], breathe_s=16, color=SLOT_VIOLET)
    if L['uv']:
        fx.update(uv=1.0, uv_only=True, uv_steady=True)
    fx['per_head'] = {'5': dict(hold=dict(aim[5]), hold_head=5)}
    return fx


SPOT_FX = {k: _hub_fx(k) for k in SPOT_MODES}

STATE = {'device': None, 'last': 'dormant: no Tap Dial found yet', 'source': None, 'intensity': 1.0, 'fill': None,
         'lamp_rgb': (110, 0, 255), 'lamp_rainbow': False, 'lamp_base': 100.0, 'pose': {}, 'head_rgb': (110, 0, 255),
         'scene': -1, 'colour': None, 'wave': None,
         'idx': {1: -1, 2: -1, 3: -1, 4: -1}, 'applying': False, 'seen_look': None, 'lag': None,
         'layers': {'heads': None, 'spots': None}, 'sending': False, 'node': None}
_now = time.time                                      # tests swap in a fake clock
RC = {'mod': None}                                    # rig_control (the running module), given to start()


def log(msg):
    STATE['last'] = msg
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 200000:
            os.replace(LOG, LOG + '.old')
        with open(LOG, 'a') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


def settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS) as f:
            got = json.load(f)
        if isinstance(got, dict):
            s.update({k: v for k, v in got.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def bridge_ts(text):
    for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError):
            continue
    return None


# ---------------------------------------------------------------- gestures (pure)
class Gestures:
    """Single vs double tap from the bridge's own press timestamps. A press becomes a SINGLE once released and
    `settle` s passed with no second press; a second initial_press within `window` s (bridge time) = DOUBLE."""

    def __init__(self, window=0.45, settle=0.45, doubles=True):
        self.window, self.settle, self.p = window, settle, {}
        self.doubles = doubles                           # v7: False = no double taps, a tap acts on its release

    def event(self, n, ev, ts, now):
        out = []
        p = self.p.get(n)
        if ev == 'initial_press':
            if self.doubles and p and not p['held'] and not p.get('spent') and ts is not None and p['ts'] is not None \
                    and 0 <= ts - p['ts'] <= self.window:
                out.append(('double', n))
                self.p[n] = dict(ts=None, rel=None, held=False, spent=True, born=now)
            else:
                self.p[n] = dict(ts=ts, rel=None, held=False, spent=False, born=now)
        elif ev in ('long_press', 'repeat'):
            if p and not p['held'] and not p.get('spent'):
                p['held'] = True
                out.append(('hold', n))                    # v6: a hold is its own action (fires once)
            elif p:
                p['held'] = True
        elif ev == 'short_release':
            if p:
                if p.get('spent'):
                    del self.p[n]
                else:
                    p['rel'] = now
            else:
                self.p[n] = dict(ts=ts, rel=now, held=False, spent=False, born=now)
        elif ev == 'long_release':
            self.p.pop(n, None)
        return out

    def due(self, now):
        out = []
        for n, p in list(self.p.items()):
            if p.get('spent') or p['held']:
                if now - p['born'] > 5.0:
                    del self.p[n]
                continue
            if p['rel'] is not None and (not self.doubles or now - p['rel'] >= self.settle):
                del self.p[n]
                out.append(('single', n))
            elif p['rel'] is None and now - p['born'] > 5.0:
                del self.p[n]
        return out


def coalesce(jobs):
    """Presses that piled up while something slow ran: a double drops the singles of that button before it,
    and several singles of one button become one job that skips ahead. -> [(kind, n, skips)]"""
    out = []
    for kind, n in jobs:
        if kind == 'hold':
            out = [j for j in out if not (j[1] == n and j[0] == 'single')]
            out.append(('hold', n, 0))
        elif kind == 'double':
            out = [j for j in out if j[1] != n]
            out.append(('double', n, 0))
        else:
            for i, j in enumerate(out):
                if j[1] == n and j[0] == 'single':
                    out[i] = ('single', n, j[2] + 1)
                    break
            else:
                out.append(('single', n, 0))
    return out


class Dial:
    def __init__(self):
        self.acc = 0

    def event(self, direction, steps):
        try:
            steps = int(steps)
        except (TypeError, ValueError):
            return
        self.acc += steps if direction == 'clock_wise' else -steps

    def take(self):
        a, self.acc = self.acc, 0
        return a


def parse(batch, buttons, rotary):
    out = []
    for msg in batch if isinstance(batch, list) else []:
        for r in (msg or {}).get('data') or []:
            rid = r.get('id')
            if r.get('type') == 'button' and rid in buttons:
                rep = (r.get('button') or {}).get('button_report') or {}
                ev = rep.get('event') or (r.get('button') or {}).get('last_event')
                if ev:
                    out.append(('button', buttons[rid], ev, bridge_ts(rep.get('updated'))))
            elif r.get('type') == 'relative_rotary' and rid in rotary:
                rr = r.get('relative_rotary') or {}
                rep = rr.get('rotary_report') or rr.get('last_event') or {}
                rot = rep.get('rotation') or {}
                if rot.get('steps'):
                    out.append(('dial', rot.get('direction'), rot.get('steps')))
    out.sort(key=lambda e: (e[3] or 0) if e[0] == 'button' else 0)
    return out


# ---------------------------------------------------------------- DMX layers (heads glow + spots on the ceiling)
def zones():
    """Michael's zone map (zones_calibration.json 'groups'), else the built-in copy."""
    try:
        g = json.load(open(os.path.join(HERE, 'zones_calibration.json'))).get('groups')
        if isinstance(g, dict) and g:
            return g
    except (OSError, ValueError):
        pass
    return ZONES_DEFAULT


def _col_row(zid):
    import re
    m = re.match(r'^\s*(\d+)\s*([A-Za-z])', str(zid))
    return (int(m.group(1)), m.group(2).upper()) if m else (2, 'A')


def loop_order(zs):
    """Round the room: out along the A wall (1A 2A 3A), back along the B wall (2B 1B)."""
    a = sorted([z for z in zs if _col_row(z)[1] == 'A'], key=lambda z: _col_row(z)[0])
    b = sorted([z for z in zs if _col_row(z)[1] != 'A'], key=lambda z: -_col_row(z)[0])
    return a + b


def nopink(deg):
    """A full trip round the wheel (0-360) -> red..violet..red, never through pink / magenta."""
    x = (deg % 360.0) / 360.0
    return NOPINK_TOP * (2.0 * x if x <= 0.5 else 2.0 - 2.0 * x)


def zone_hue(kind, zid, t, zs=None):
    return nopink(_zone_hue_raw(kind, zid, t, zs))


def _zone_hue_raw(kind, zid, t, zs=None):
    """The colour (hue, degrees) of zone zid at time t for rainbow wave / bounce / loop."""
    col = _col_row(zid)[0]
    if kind == 'rwave':                                # door -> studio: each column 100 deg behind the one before
        return (360.0 * t / WAVE_T[kind] - 100.0 * (col - 1)) % 360.0
    if kind == 'rbounce':                              # a colour front sweeping 1 -> 3 -> 1
        x = (t / 8.0) % 2.0
        c = 1.0 + 2.0 * (x if x <= 1.0 else 2.0 - x)
        return (360.0 * t / WAVE_T[kind] + 110.0 * abs(col - c)) % 360.0
    if kind == 'rsync':                                # every zone the same colour, slow
        return (360.0 * t / WAVE_T[kind]) % 360.0
    if kind in ('rloop', 'rall'):                      # round the room
        order = loop_order(list(zs or zones()))
        k = order.index(zid) if zid in order else 0
        return (360.0 * t / WAVE_T[kind] - 360.0 * k / max(1, len(order))) % 360.0
    return 0.0


def zone_rgb(kind, zid, t, zs=None):
    """The zone's colour. Waves fade through the whole wheel; STEPS snap through Michael's 8 colours with EVERYTHING
    in sync (Michael, Nov 17: steps don't use the zones -- the whole room is one colour at a time)."""
    if kind == 'rsteps':
        return HUE_COLOURS[int(t / STEP_S) % RAINBOW_COLOURS][1]
    return _hue_rgb(zone_hue(kind, zid, t, zs))


def fixture_zone_rgb(kind, t, zs=None):
    """{node index: rgb} for every head (1-4 -> 0-3) and spot (1-2 -> 4-5) in a zone."""
    zs = zs or zones()
    out = {}
    for zid, z in zs.items():
        rgb = zone_rgb(kind, zid, t, zs)
        for h in z.get('heads') or []:
            out[int(h) - 1] = rgb
        for sp in z.get('spots') or []:
            out[3 + int(sp)] = rgb
    return out


def wheel_slot(rgb):
    """Nearest Focus Spot colour-wheel slot (never white) -- same table as hub_dmx.focus_out."""
    import colorsys as _c
    h, sat, _ = _c.rgb_to_hsv(*[x / 255.0 for x in rgb])
    deg = h * 360.0
    if sat < 0.35 or 262 <= deg < 292:
        return 97
    if deg >= 345 or deg < 20:
        return 22
    if deg < 75:
        return 67
    if deg < 190:
        return 52
    if deg < 262:
        return 37
    return 82


def _hue_rgb(deg):
    r, g, b = colorsys.hsv_to_rgb((deg % 360.0) / 360.0, 1.0, 1.0)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


HEAD_PERIOD = {'glow': 90.0, 'colour': 60.0, 'rainbow': 60.0, 'sweep': 24.0, 'rainbow_sweep': 16.0, 'zonewave': 45.0}
HEAD_LEVEL = {'glow': 0.35, 'colour': 0.5, 'rainbow': 0.5, 'sweep': 0.45, 'rainbow_sweep': 0.75, 'pose': 0.45, 'clouds': 0.35,
              'zonewave': 0.7}
WHEEL = [22, 67, 52, 37, 97]                           # red, yellow, green, blue, violet (no white, no pink)
POSE_HOLD_S = 20.0                                     # clouds: each aim held this long (then a smooth move)
SPOT_PERIOD = 40.0


def roam(h, t, period, phase, tdeg):
    """FULL RANGE (Michael, Nov 17: "every head and spot should be able to provide a full range of motion"):
    the whole pan window (up to a full circle) back and forth, leaning 30-80 deg from straight up and back.
    The node still applies the no-go zones he designated. -> (pan16, tilt16)"""
    lo = int(h.get('pan_min', 0))
    hi = min(int(h.get('pan_max', 65535)), lo + int(360.0 / 540.0 * 65535.0))
    pan = int(lo + (hi - lo) * (0.5 + 0.5 * math.sin(2 * math.pi * (t / period + phase))))
    lmax = min(80.0, float(h.get('tilt_max_deg', 85.0)))
    lean = 30.0 + (lmax - 30.0) * (0.5 + 0.5 * math.sin(2 * math.pi * (t / (period * 0.37) + phase)))
    tilt = int(max(0, min(65535, int(h.get('tilt_up', 32768)) + int(h.get('tilt_dir', 1)) * lean / tdeg * 65535.0)))
    return pan, tilt


def frame(heads, layers, t, inten, targets, mmin=8, mmax=134):
    """One DMX universe (bytearray 512) for the layers. heads = node config list; targets = 'Coffee table' aims.
    Heads not in a layer stay at 0 (dark). Pure: tested on its own."""
    data = bytearray(512)
    inten = max(0.0, min(1.0, inten))
    hmode = layers.get('heads')
    hue = 274.0 + 10.0 * math.sin(2 * math.pi * t / 240.0)          # violet -> purple (264-284 deg), slow drift
    lamp_rgb = layers.get('lamp_rgb') or (110, 0, 255)
    if layers.get('lamp_rainbow'):
        lamp_rgb = _hue_rgb(360.0 * t / float(layers.get('rainbow_s') or 60))
    for i, h in enumerate(heads):
        a = int(h.get('addr', 0)) - 1
        if h.get('type') == 'focus17':
            mode = layers.get('spots')
            if mode not in SPOT_LOOK or a < 0 or a + 17 > 512 or i not in SPOT_AIM:
                continue
            L = SPOT_LOOK[mode]
            if L.get('scan') and i in UV_CORNERS:            # UV round the tapestry's four corners, smooth
                cs = UV_CORNERS[i]
                x = (t / UV_SCAN_S) % 1.0 * len(cs)
                k = int(x)
                e = 0.5 - 0.5 * math.cos(math.pi * (x - k))
                (p0, t0_), (p1, t1_) = cs[k], cs[(k + 1) % len(cs)]
                p16, tilt = int(p0 + (p1 - p0) * e), int(t0_ + (t1_ - t0_) * e)
            elif L['uv']:                                      # UV tapestry: a target, held still
                aim = L['aim'][i]
                p16 = int(max(int(h.get('pan_min', 0)), min(int(h.get('pan_max', 65535)), aim['az'] / 540.0 * 65535.0)))
                lean = min(aim['lean'], float(h.get('tilt_max_deg', 85.0)))
                tilt = int(max(0, min(65535, int(h.get('tilt_up', 32768)) + int(h.get('tilt_dir', 1)) * lean / 240.0 * 65535.0)))
            else:                                              # gobos: the full range, both spots in step
                p16, tilt = roam(h, t, SPOT_PERIOD * (0.45 if L.get('fast') else 1.0), 0.0, 240.0)
            foc = L['focus'] + L['breathe'] * math.sin(2 * math.pi * t / 16.0)
            data[a], data[a + 1], data[a + 2], data[a + 3] = p16 >> 8, p16 & 255, tilt >> 8, tilt & 255
            if L.get('zone') and i in (layers.get('zone_rgb') or {}):   # rainbow waves: the spot's zone colour
                data[a + 4] = wheel_slot(layers['zone_rgb'][i])
            elif layers.get('slot') is not None:                 # button 1: the spots match the colour
                data[a + 4] = int(layers['slot'])
            elif L.get('wheel'):
                data[a + 4] = WHEEL[int(t / 1.5) % len(WHEEL)]
            else:
                data[a + 4] = SLOT_VIOLET if math.sin(2 * math.pi * t / 120.0) >= 0 else SLOT_PINK
            data[a + 5] = L['gobo']
            if L.get('gobo_steps'):                            # rainbow steps: a new gobo with every colour step
                data[a + 5] = STEP_GOBOS[int(float(layers.get('abs_t', t)) / STEP_S) % len(STEP_GOBOS)]
            data[a + 7] = int(max(0, min(255, foc)))
            if L['uv']:
                uv = int(round(255 * inten))
                data[a + 10], data[a + 11] = (12, uv) if uv else (0, 0)
            else:
                m = int(round(255 * 0.85 * inten))
                data[a + 8], data[a + 9] = (12, m) if m else (0, 0)
            data[a + 15] = int(h.get('motor_speed', 0))
        else:
            if hmode not in HEAD_LEVEL or a < 0 or a + 14 > 512:
                continue
            if hmode in ('pose', 'clouds'):                    # saved aims (scenes): hold each, then glide to the next
                aims = (layers.get('pose') or {}).get(i) or (layers.get('pose') or {}).get(str(i))
                if not aims:
                    continue                                   # no aim for this head in this scene: it stays dark
                if len(aims) == 1:
                    pan, tilt = aims[0]
                else:
                    x = (t / POSE_HOLD_S + i * 0.37) % len(aims)
                    k = int(x)
                    f = x - k
                    e = 0.0 if f < 0.6 else 0.5 - 0.5 * math.cos(math.pi * (f - 0.6) / 0.4)
                    (p0, q0), (p1, q1) = aims[k], aims[(k + 1) % len(aims)]
                    pan, tilt = int(p0 + (p1 - p0) * e), int(q0 + (q1 - q0) * e)
            else:
                pan, tilt = roam(h, t, HEAD_PERIOD[hmode], 0.0 if hmode in ('sweep', 'rainbow_sweep') else i / 4.0, 180.0)
            data[a], data[a + 1], data[a + 2], data[a + 3] = pan >> 8, pan & 255, tilt >> 8, tilt & 255
            data[a + 4] = int(h.get('motor_speed', 0))
            lvl = HEAD_LEVEL[hmode] * inten
            data[a + 5] = int(round(mmin + lvl * (mmax - mmin))) if inten > 0.01 else 0
            if hmode == 'zonewave':
                rgb = (layers.get('zone_rgb') or {}).get(i) or PURPLE      # its zone's colour in the wave
            elif layers.get('rgb') is not None and hmode not in ('rainbow', 'rainbow_sweep'):
                rgb = tuple(layers['rgb'])                         # button 1: the heads match the colour
            elif hmode == 'colour':
                rgb = lamp_rgb
            elif hmode == 'rainbow':
                rgb = _hue_rgb(nopink(360.0 * t / 60.0))              # all four heads the same colour, in sync
            elif hmode == 'rainbow_sweep':
                rgb = _hue_rgb(nopink(360.0 * t / 12.0 + 70.0 * i))   # all-out: fast, each head its own colour
            elif hmode in ('pose', 'clouds'):
                rgb = tuple(layers.get('head_rgb') or PURPLE)
            else:
                rgb = _hue_rgb(hue + 4 * i)
            data[a + 6], data[a + 7], data[a + 8] = rgb
    return data


def _node():
    import hub_dmx as hd
    st = json.load(open(os.path.join(HERE, 'hub_state.json')))['settings']
    tg = (st.get('head_targets') or {}).get('Coffee table') or {}
    for h_ in [x.strip() for x in str(st.get('dmx_host') or '192.168.1.80').split(',') if x.strip()]:
        try:
            import urllib.request
            ip = socket.getaddrinfo(h_, hd.ARTNET_PORT, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
            cfg = json.loads(urllib.request.urlopen('http://%s:%d/config' % (ip, hd.NODE_PORT), timeout=2).read())
            return ip, cfg, tg
        except Exception:
            continue
    raise OSError('DMX node not reachable')


def _someone_else_drives_dmx():
    """The hub, the ambient 'heads on' glow or a calibration run own the DMX -> the layers stand aside."""
    if _hub_alive():
        return 'hub'
    m = rc()
    try:
        out = m.sh('pgrep -fl "calib.py|ambient_fade.py.* heads" || true', timeout=3)
    except Exception:
        out = ''
    return 'other' if out.strip() else None


def sender():
    import hub_dmx as hd
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    node, seq, check_t, busy, t0 = None, 0, 0.0, None, time.time()
    while True:
        lay = STATE['layers']
        want = lay.get('heads') in HEAD_LEVEL or lay.get('spots') in SPOT_LOOK
        now = time.time()
        if want and now - check_t > 1.5:
            check_t, busy = now, _someone_else_drives_dmx()
        if not want or busy:
            STATE['sending'] = False
            time.sleep(0.2)
            continue
        if node is None:
            try:
                node = _node()
                STATE['node'] = node[0]
            except Exception as e:
                STATE['node'] = 'not reachable (%s)' % e.__class__.__name__
                time.sleep(5)
                continue
        ip, cfg, tg = node
        try:
            col = STATE.get('colour')
            lay2 = dict(lay, lamp_rgb=STATE['lamp_rgb'], lamp_rainbow=STATE['lamp_rainbow'], rainbow_s=60,
                        pose=STATE['pose'], head_rgb=STATE['head_rgb'],
                        rgb=col[1] if col else None, slot=WHEEL_SLOT.get(col[0]) if col else None)
            if STATE.get('wave') and ('zonewave' == lay.get('heads') or lay.get('spots') in ('zonewave', 'zonesteps')):
                lay2['zone_rgb'] = fixture_zone_rgb(STATE['wave'], time.time())
                lay2['abs_t'] = time.time()
            data = frame(cfg['heads'], lay2, now - t0, STATE['intensity'], tg, hd.MASTER_MIN, hd.MASTER_MAX)
            sock.sendto(hd.artdmx(seq, int(cfg.get('universe', 0)), data), (ip, hd.ARTNET_PORT))
            STATE['sending'] = True
        except Exception:
            node = None
        seq += 1
        time.sleep(1.0 / 25.0)


# ---------------------------------------------------------------- bridge
def _hs():
    import sys
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import hue_stream
    return hue_stream


def find_switch(hs, cfg, s):
    dev = s.get('device_id')
    if not dev:
        for d in hs.v2(cfg, 'device').get('data', []):
            name = ((d.get('metadata') or {}).get('name') or '').lower()
            prod = ((d.get('product_data') or {}).get('product_name') or '').lower()
            if 'tap' in name or 'tap' in prod:
                dev = d['id']
                break
    if not dev:
        return None, {}, set()
    buttons = {b['id']: int((b.get('metadata') or {}).get('control_id', 0))
               for b in hs.v2(cfg, 'button').get('data', []) if (b.get('owner') or {}).get('rid') == dev}
    rotary = {r['id'] for r in hs.v2(cfg, 'relative_rotary').get('data', []) if (r.get('owner') or {}).get('rid') == dev}
    return dev, buttons, rotary


def stream(cfg, handle):
    import http.client, ssl
    conn = http.client.HTTPSConnection(cfg['ip'], 443, context=ssl._create_unverified_context(), timeout=300)
    try:
        conn.request('GET', '/eventstream/clip/v2',
                     headers={'hue-application-key': cfg['username'], 'Accept': 'text/event-stream'})
        r = conn.getresponse()
        if r.status != 200:
            raise OSError('event stream HTTP %d' % r.status)
        STATE['source'] = 'event stream'
        while True:
            line = r.readline()
            if not line:
                raise OSError('event stream closed')
            line = line.strip()
            if line.startswith(b'data:'):
                try:
                    handle(json.loads(line[5:].decode('utf-8', 'replace')))
                except ValueError:
                    continue
    finally:
        conn.close()


# ---------------------------------------------------------------- actions
JOBS = queue.Queue()


def rc():
    return RC['mod']


def _hub_alive():
    try:
        return rc().hub_up()
    except Exception:
        return False


def _apply(look):
    m = rc()
    STATE['applying'] = True
    try:
        m.apply(look)
    finally:
        STATE['seen_look'] = m.STATE.get('look')
        STATE['applying'] = False
    err = m.STATE.get('last_error')
    if err:
        raise RuntimeError(err)


def _mark(look):
    """Record a tap-only change as the rig's current look (no lamp change)."""
    m = rc()
    m.STATE.update(look=look, since=time.strftime('%H:%M'))
    STATE['seen_look'] = look


def _plugs_on(pw):
    on = (pw.STATE.get('on') or {})
    return bool(on) and any(on.values())


def _lamps_parallel(m, body):
    """Every lamp at once (one thread each), so they change together. Plugs are never touched."""
    hs = _hs()
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        cfg = hs.load_config()
        ids = [l['id'] for l in hs.v2(cfg, 'light').get('data', []) if 'dimming' in l and not m.head_power.is_plug(l)]
    finally:
        os.chdir(cwd)
    ts_ = [threading.Thread(target=lambda i=i: hs.v2(cfg, 'light/' + i, 'PUT', body), daemon=True) for i in ids]
    for t in ts_:
        t.start()
    for t in ts_:
        t.join(2.0)


def _lamps_free():
    """The lamps take a colour only when nothing else is driving them: stop the rainbow fade / a show."""
    m = rc()
    STATE['wave'] = None
    m.stop_ambient()
    try:
        starting = m.running('hue_hub.py')
    except Exception:
        starting = False
    if _hub_alive() or starting:
        m.stop_hub()                                   # the show held the lamps; heads/spots layers carry on
        if STATE['layers'].get('heads') == 'hub':
            STATE['layers']['heads'] = None


def _lights():
    """(hue_stream, cfg, [colour lamps]) -- smart plugs are never touched."""
    hs = _hs()
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        cfg = hs.load_config()
        lamps = [l for l in hs.v2(cfg, 'light').get('data', []) if 'dimming' in l and not rc().head_power.is_plug(l)]
    finally:
        os.chdir(cwd)
    return hs, cfg, lamps


def lamps_on():
    try:
        return any((l.get('on') or {}).get('on') for l in _lights()[2])
    except Exception:
        return True


def _stop_hub():
    m = rc()
    try:
        starting = m.running('hue_hub.py')            # a hub still starting up (not answering yet) counts too
    except Exception:
        starting = False
    if _hub_alive() or starting:
        m.stop_hub()
        if STATE['layers'].get('heads') == 'hub':
            STATE['layers']['heads'] = None


def _lamp_set(rgb, bri=100.0):
    """Every lamp the same colour at once (lamps only)."""
    m = rc()
    _lamps_free()
    x, y = _hs().rgb_to_xyb(*[v / 255.0 for v in rgb])[:2]
    STATE['lamp_rgb'], STATE['lamp_rainbow'], STATE['lamp_base'] = tuple(rgb), False, float(bri)
    _lamps_parallel(m, {'on': {'on': True}, 'dimming': {'brightness': max(1.0, bri * STATE['intensity'])},
                        'color': {'xy': {'x': x, 'y': y}}, 'dynamics': {'duration': 400}})


def lamp_colour(name, rgb):
    _lamp_set(rgb, 100.0)
    _mark('tap_colour_' + name)


def _ambient(bri, turn, spread, *extra):
    """A moving lamp look (ambient_fade); the dial reaches it through dial.json."""
    m = rc()
    _lamps_free()
    STATE['lamp_rainbow'], STATE['lamp_base'] = True, None
    m.start_ambient(bri, turn, spread, *extra)
    if STATE['intensity'] < 0.999:
        _write_dial(STATE['intensity'])


def _lamp_wave(kind):
    _lamps_free()
    STATE['wave'], STATE['lamp_base'], STATE['lamp_rainbow'] = kind, None, True


def lamp_wave_tick(t=None, push=None):
    """One update of the lamps for a rainbow wave: each lamp in its zone's colour (the gradient lamp gets a little
    rainbow of its own). Returns {lamp name: body} (push=None sends them)."""
    kind = STATE.get('wave')
    if not kind:
        return {}
    t = time.time() if t is None else t
    zs = zones()
    zone_of = {nm: zid for zid, z in zs.items() for nm in (z.get('lamps') or [])}
    hs, cfg, lamps = _lights()
    bodies = {}
    bri = max(1.0, {'rsync': 80.0}.get(kind, 100.0) * STATE['intensity'])
    for l in lamps:
        nm = (l.get('metadata') or {}).get('name', l['id'])
        if not (l.get('on') or {}).get('on'):
            continue                                   # a lamp that's off stays off
        zid = zone_of.get(nm, '2A')
        steps = kind == 'rsteps'
        body = {'dimming': {'brightness': bri}, 'dynamics': {'duration': 250 if steps else 1100}}
        xy = lambda d: hs.rgb_to_xyb(*[v / 255.0 for v in _hue_rgb(d)])[:2]
        if steps:
            x, y = hs.rgb_to_xyb(*[v / 255.0 for v in zone_rgb(kind, zid, t, zs)])[:2]
            body['color'] = {'xy': {'x': x, 'y': y}}
        elif 'gradient' in l:
            deg = zone_hue(kind, zid, t, zs)
            body['gradient'] = {'points': [{'color': {'xy': {'x': x, 'y': y}}} for x, y in
                                           [xy(max(0.0, min(NOPINK_TOP, deg - 50 + 25 * j))) for j in range(5)]]}
        else:
            x, y = xy(zone_hue(kind, zid, t, zs))
            body['color'] = {'xy': {'x': x, 'y': y}}
        bodies[nm] = (l['id'], body)
    if push is None:
        ts_ = [threading.Thread(target=lambda i=i, b=b: hs.v2(cfg, 'light/' + i, 'PUT', b), daemon=True)
               for i, b in bodies.values()]
        for th in ts_:
            th.start()
        for th in ts_:
            th.join(2.0)
    return {k: v[1] for k, v in bodies.items()}


def lamp_wave_loop():
    while True:
        try:
            if STATE.get('wave') and STATE.get('lamp_rainbow'):
                lamp_wave_tick(time.time() + (0.05 if STATE['wave'] == 'rsteps' else 0.0))
        except Exception as e:
            log('lamp wave: %s' % e.__class__.__name__)
        if STATE.get('wave') == 'rsteps':              # land each update right on the step
            time.sleep(STEP_S - (time.time() % STEP_S) + 0.01)
        else:
            time.sleep(1.0)


def lamps_toggle():
    m = rc()
    hs, cfg, lamps = _lights()
    if any((l.get('on') or {}).get('on') for l in lamps):
        _lamps_free()
        _lamps_parallel(m, {'on': {'on': False}, 'dynamics': {'duration': 600}})
        _mark('tap_lamps_off')
        return 'lamps OFF'
    _lamp_set(STATE.get('lamp_rgb') or PURPLE, STATE.get('lamp_base') or 100.0)
    _mark('tap_lamps_on')
    return 'lamps ON'


def _heads_power(on):
    hp = rc().head_power
    if on and not _plugs_on(hp):
        hp.request_on(quiet=True)
        STATE['heads_off_at'] = 0.0
    elif not on:
        STATE['layers']['heads'] = None
        if _plugs_on(hp):
            hp.request_off(why='tap dial')
            STATE['heads_off_at'] = _now()


def _spots_power(on):
    sp = rc().spot_power
    if on:
        try:
            sp.STATE['hold_until'] = 0.0
        except Exception:
            pass
        if not _plugs_on(sp):
            sp.request_on(quiet=True, why='tap dial')
        STATE['spots_off_at'] = 0.0
    else:
        STATE['layers']['spots'] = None
        if _hub_alive():
            rc().hub_setting('spot_fx', {})
        if _plugs_on(sp):
            sp.request_off(why='tap dial')
            STATE['spots_off_at'] = _now()
        try:
            sp.STATE['hold_until'] = sp._now() + sp.settings()['manual_hold_min'] * 60
        except Exception:
            pass


def heads_toggle():
    if _plugs_on(rc().head_power):
        _heads_power(False)
        STATE['idx'][2] = -1
        return 'heads OFF'
    _heads_power(True)
    STATE['idx'][2] = 0
    STATE['layers']['heads'] = HEAD_MODES[0]
    return 'heads ON (glow)'


def spots_toggle():
    if _plugs_on(rc().spot_power):
        _spots_power(False)
        STATE['idx'][3] = -1
        return 'spots OFF'
    _spots_power(True)
    STATE['idx'][3] = 0
    _spots_to(SPOT_MODES[0])
    return 'spots ON (UV tapestry)'


def _spots_to(mode):
    STATE['layers']['spots'] = mode
    if _hub_alive() and mode in SPOT_FX:
        rc().hub_setting('spot_fx', SPOT_FX[mode])


def _targets(*names, cloud=False):
    """Per head, the first saved aim found in names (or every cloud aim) -> {head index: [(pan, tilt), ...]}"""
    try:
        tg = json.load(open(os.path.join(HERE, 'hub_state.json')))['settings'].get('head_targets') or {}
    except (OSError, ValueError, KeyError):
        tg = {}
    out = {}
    for i in range(4):
        if cloud:
            aims = [(int(v[str(i)]['pan']), int(v[str(i)]['tilt'])) for k, v in sorted(tg.items())
                    if isinstance(v, dict) and str(i) in v and (v[str(i)].get('cloud') or k.lower().startswith('cloud'))]
        else:
            aims = []
            for nm in names:
                v = (tg.get(nm) or {}).get(str(i))
                if v:
                    aims = [(int(v['pan']), int(v['tilt']))]
                    break
        if aims:
            out[i] = aims
    return out


def _pose(mode, aims, rgb):
    STATE['pose'], STATE['head_rgb'] = aims, tuple(rgb)
    STATE['layers']['heads'] = mode


def scene(name):
    """v7: a scene changes what each group DOES -- only the groups already on; nothing is switched on or off."""
    m = rc()
    L, H, S = lamps_on(), _plugs_on(m.head_power), _plugs_on(m.spot_power)
    STATE['idx'].update({2: -1, 3: -1})
    STATE['colour'] = None                             # a scene brings its own colours (button 1 overrides again)
    if name in ('movie', 'show') and L:                # these two need the hub (it drives the lamps)
        m.stop_ambient()
        if name == 'movie':
            m.movie_lights('movie')
            m.hub_vibe('dreamy', 0.2)
            m.hub_setting('spot_fx', dict(m.SPOT_FX_UV_SKY, hold_when='always', uv_steady=True) if S else {})
            STATE['layers'].update(heads='hub' if H else None, spots=None)
        else:
            if not _hub_alive():
                m.start_hub('music')
            m.hub_setting('show_lock', '')
            m.hub_setting('dmx_pattern', 'modes')
            m.hub_setting('dmx_strobe', 'off')
            m.hub_setting('dmx_on', True)
            m.hub_setting('spot_fx', {})
            STATE['layers'].update(heads='hub' if H else None, spots=None)
        _mark('tap_scene_' + name)
        return SCENE_NAMES[name]
    _stop_hub()                                        # every other scene runs without the hub
    STATE['wave'] = name if name in WAVE_T else None   # heads + spots follow the zone wave even with the lamps off
    plan = {'studio': (lambda: _lamp_set(PURPLE, 60.0),
                       lambda: _pose('pose', _targets('Above studio desk', 'UV tapestry', 'Mountain tapestry', 'Studio clouds'), (90, 0, 255)),
                       'uv'),
            'movie': (None, lambda: _pose('pose', _targets('UV tapestry'), (40, 0, 120)), 'uv'),          # lamps off: no hub
            'nightsky': (lambda: _lamp_set((60, 0, 255), 25.0),
                         lambda: _pose('clouds', _targets(cloud=True), (60, 90, 255)), 'uvscan'),
            'chill': (lambda: _lamp_wave('rsync'), lambda: STATE['layers'].update(heads='glow'), 'gobo48'),
            'show': (None, lambda: STATE['layers'].update(heads='sweep'), 'gobo32'),                       # lamps off: no hub
            'rainbow': (lambda: _lamp_wave('rall'), lambda: STATE['layers'].update(heads='rainbow_sweep'), 'rainbowgobo'),
            'rwave': (lambda: _lamp_wave('rwave'), lambda: STATE['layers'].update(heads='zonewave'), 'zonewave'),
            'rbounce': (lambda: _lamp_wave('rbounce'), lambda: STATE['layers'].update(heads='zonewave'), 'zonewave'),
            'rloop': (lambda: _lamp_wave('rloop'), lambda: STATE['layers'].update(heads='zonewave'), 'zonewave'),
            'rsteps': (lambda: _lamp_wave('rsteps'), lambda: STATE['layers'].update(heads='zonewave'), 'zonesteps')}[name]
    lamp_fn, head_fn, spot_mode = plan
    if L and lamp_fn:
        lamp_fn()
        if name in WAVE_T:
            STATE['wave'] = name
    elif not L:
        m.stop_ambient()
    if H:
        head_fn()
    else:
        STATE['layers']['heads'] = None
    if S:
        _spots_to(spot_mode)
    else:
        STATE['layers']['spots'] = None
    _mark('tap_scene_' + name)
    return SCENE_NAMES[name] + ('' if (L and H and S) else ' (%s)' % ', '.join(
        n for n, on in (('lamps', L), ('heads', H), ('spots', S)) if on) if (L or H or S) else ' (everything is off)')


def home_light():
    """HOLD 4: the home colour on the lamps -- blue in the morning, purple in the day, red after bedtime.
    v7: nothing is switched on or off (lamps that are off stay off; heads + spots keep what they're doing)."""
    m = rc()
    s = settings()
    if not lamps_on():
        return 'home colour: lamps are off (hold 1 turns them on)'
    h = time.localtime().tm_hour + time.localtime().tm_min / 60.0
    bed = 23.0
    try:
        hh, mm = str(m.light_schedule.status().get('night') or '23:00').split(':')
        bed = int(hh) + int(mm) / 60.0
    except Exception:
        pass
    _stop_hub()
    if s['morning_starts'] <= h < s['morning_ends']:
        _lamp_set((0, 70, 255), 60.0)
        what = 'home: morning blue'
    elif s['morning_ends'] <= h < bed:
        _lamp_set(PURPLE, 100.0)
        what = 'home: purple'
    else:
        _lamp_set((255, 0, 0), 12.0)
        what = 'home: red for bed'
    STATE['idx'][4] = -1
    _mark('tap_home')
    return what


def back_to_purple():
    m = rc()
    STATE['layers'].update(heads=None, spots=None)
    STATE['lamp_rgb'], STATE['lamp_rainbow'], STATE['lamp_base'] = PURPLE, False, 100.0
    _apply('purple')
    _heads_power(False)
    _spots_power(False)


def _next(n, size, skips=0):
    STATE['idx'][n] = (STATE['idx'][n] + 1 + skips) % size
    return STATE['idx'][n]


# ---------------------------------------------------------------- AIM MODE (calibration with the Tap Dial)
# While bridge/tap_aim.json exists ({"fixture": 5, ...}) the Tap Dial steers the calibration dot (calib.py nodeaim
# follows bridge/calib_aim.json):  DIAL = turn (pan)   1 = tilt one way   2 = tilt the other way (double = big step)
# 3 = SAVE this spot (bridge/outbox/aim_saves.txt)   4 double = leave aim mode.  Michael steers; nothing is guessed.
AIM_FLAG = os.path.join(HERE, 'bridge', 'tap_aim.json')
AIM_FILE = os.path.join(HERE, 'bridge', 'calib_aim.json')
AIM_SAVES = os.path.join(HERE, 'bridge', 'outbox', 'aim_saves.txt')
AIM_PAN_PER_STEP = 0.25 / 540.0 * 65535.0            # 0.25 deg of turn per dial step
AIM_TILT_STEP = 2.0                                   # degrees per tap (x3 on a double tap)


def aim_mode():
    try:
        with open(AIM_FLAG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _aim_get():
    with open(AIM_FILE) as f:
        a = json.load(f)
    return dict(a, pan=int(a['pan']), tilt=int(a['tilt']))


def _aim_put(a):
    a['pan'] = int(max(0, min(65535, a['pan'])))
    a['tilt'] = int(max(0, min(65535, a['tilt'])))
    tmp = AIM_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(a, f)
    os.replace(tmp, AIM_FILE)
    return a


def aim_turn(steps):
    a = _aim_get()
    a['pan'] += steps * AIM_PAN_PER_STEP
    return _aim_put(a)


def aim_button(n, kind, am):
    tdeg = 240.0 if int(am.get('fixture', 1)) >= 5 else 180.0
    a = _aim_get()
    if n in (1, 2):
        step = AIM_TILT_STEP * (3 if kind == 'double' else 1) * (1 if n == 1 else -1)
        a['tilt'] += step / tdeg * 65535.0
        _aim_put(a)
        return 'aim tilt %+g deg -> pan %d tilt %d' % (step, a['pan'], a['tilt'])
    if n == 3:
        line = '%s fixture %s pan %d tilt %d\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), am.get('fixture'), a['pan'], a['tilt'])
        with open(AIM_SAVES, 'a') as f:
            f.write(line)
        return 'aim SAVED ' + line.strip()
    if n == 4 and kind == 'double':
        try:
            os.replace(AIM_FLAG, AIM_FLAG + '.off')
        except OSError:
            pass
        return 'aim mode off'
    return 'aim mode: nothing on that press'


def single(n, skips=0, s=None):
    m = rc()
    if n == 1:                                         # v8: one colour for everything that's on
        L, H, S = lamps_on(), _plugs_on(m.head_power), _plugs_on(m.spot_power)
        if not (L or H or S):
            return 'everything is off (hold 1, 2 or 3 to switch something on)'
        name, rgb = HUE_COLOURS[_next(1, len(HUE_COLOURS), skips)]
        was_show = STATE['layers'].get('heads') == 'hub' or _hub_alive()
        _stop_hub()
        if L:
            lamp_colour(name, rgb)
        else:
            m.stop_ambient()
            _mark('tap_colour_' + name)
        STATE['colour'] = (name, tuple(rgb))
        if H and STATE['layers'].get('heads') not in HEAD_LEVEL:
            STATE['layers']['heads'] = 'glow'           # the show had them: keep them moving, in the colour
        if S and (STATE['layers'].get('spots') not in SPOT_LOOK or was_show and STATE['layers'].get('spots') is None):
            STATE['layers']['spots'] = 'gobo32'
        return 'colour %s (%s)' % (name, ', '.join(g for g, on in (('lamps', L), ('heads', H), ('spots', S)) if on))
    if n == 2:
        if not _plugs_on(m.head_power) or _now() - STATE.get('heads_off_at', 0.0) < 15.0:
            return 'heads are off (hold 2 turns them on)'
        if STATE['layers'].get('heads') not in HEAD_MODES:
            STATE['idx'][2] = -1
        mode = HEAD_MODES[_next(2, len(HEAD_MODES), skips)]
        if STATE['layers'].get('heads') == 'hub':
            _stop_hub()                                # heads leave the show for their own mode
        STATE['layers']['heads'] = mode
        return 'heads ' + mode
    if n == 3:
        if not _plugs_on(m.spot_power) or _now() - STATE.get('spots_off_at', 0.0) < 15.0:
            return 'spots are off (hold 3 turns them on)'
        if STATE['layers'].get('spots') not in SPOT_MODES:
            STATE['idx'][3] = -1
        mode = SPOT_MODES[_next(3, len(SPOT_MODES), skips)]
        _spots_to(mode)
        return 'spots ' + mode
    if n == 4:
        return 'scene ' + scene(SCENES[_next(4, len(SCENES), skips)])
    return None


def double(n):
    """v7: no double taps (kept so old queued jobs can't fail)."""
    return single(n)


def hold(n):
    """v7: HOLD 1-3 = that group on / off (the only way anything is switched). HOLD 4 = home colour."""
    if n == 1:
        r = lamps_toggle()
        STATE['idx'][1] = -1
        return r
    if n == 2:
        return heads_toggle()
    if n == 3:
        return spots_toggle()
    if n == 4:                                         # v10: rainbow shortcut -- first hold All-out, then the waves
        cur = SCENES[STATE['idx'][4]] if 0 <= STATE['idx'][4] < len(SCENES) else None
        nxt = RAINBOWS[(RAINBOWS.index(cur) + 1) % len(RAINBOWS)] if cur in RAINBOWS else 'rainbow'
        STATE['idx'][4] = SCENES.index(nxt)
        return 'scene ' + scene(nxt)
    return None


# ---------------------------------------------------------------- dial = brightness of everything that's on
def _write_dial(v):
    try:
        if v >= 0.999:
            if os.path.exists(DIAL_FILE):
                os.remove(DIAL_FILE)
            return
        with open(DIAL_FILE, 'w') as f:
            json.dump({'intensity': round(v, 3), 't': round(_now(), 1)}, f)
    except OSError:
        pass


def apply_intensity(v):
    """Heads + spots layers read STATE['intensity'] every frame; this sends it to the lamps / the show. Never raises."""
    m = rc()
    try:
        if _hub_alive():
            m.hub_api({'op': 'live', 'key': 'master', 'value': round(v, 3)})
            return 'hub'
        _write_dial(v)
        if m.running('ambient_fade.py'):
            return 'ambient'
        if STATE.get('lamp_base') is None:
            return 'layers'                            # night light / looks from elsewhere: lamps left alone
        _lamps_parallel(m, {'dimming': {'brightness': max(1.0, round(STATE['lamp_base'] * v, 1))}, 'dynamics': {'duration': 300}})
        return 'lamps'
    except Exception as e:
        log('dial: %s' % e.__class__.__name__)
        return 'failed'


def turn(steps, s=None):
    s = s or settings()
    v = max(float(s['dial_min']), min(1.0, STATE['intensity'] + steps * float(s['dial_step'])))
    if abs(v - STATE['intensity']) < 1e-6:
        return None
    STATE['intensity'] = v
    return apply_intensity(v)


def look_watch():
    """A look from anywhere else (Jarvis, console, schedule): tap layers stand down, the dial goes back to full."""
    m = rc()
    look = m.STATE.get('look')
    if STATE['applying'] or look == STATE['seen_look']:
        return False
    STATE['seen_look'] = look
    changed = False
    if STATE['layers'].get('heads') or STATE['layers'].get('spots'):
        STATE['layers'].update(heads=None, spots=None)
        STATE['idx'].update({2: -1, 3: -1, 4: -1})
        changed = True
    if STATE['intensity'] < 0.999:
        STATE['intensity'] = 1.0
        _write_dial(1.0)
        if _hub_alive():
            try:
                m.hub_api({'op': 'live', 'key': 'master', 'value': 1.0})
            except Exception:
                pass
        changed = True
    STATE['lamp_base'] = None
    STATE['wave'] = None
    if changed:
        log('look "%s" from elsewhere -- tap layers off, dial back to full' % look)
    return changed


# ---------------------------------------------------------------- threads
def worker():
    while True:
        jobs = [JOBS.get()]
        time.sleep(0.05)
        while True:                                     # everything that piled up meanwhile, collapsed
            try:
                jobs.append(JOBS.get_nowait())
            except queue.Empty:
                break
        for kind, n, skips in (coalesce(jobs) if not aim_mode() else [(k, b, 0) for k, b in jobs]):
            t0 = time.time()
            try:
                am = aim_mode()
                what = aim_button(n, kind, am) if am else (single(n, skips) if kind == 'single' else
                                                            hold(n) if kind == 'hold' else double(n))
                log('button %d %s -> %s (%.1f s)' % (n, kind, what, time.time() - t0))
            except Exception as e:
                log('button %d %s failed: %s: %s' % (n, kind, e.__class__.__name__, e))


DIALQ = {'acc': 0, 'ev': threading.Event()}


def dial_worker():
    while True:
        DIALQ['ev'].wait()
        DIALQ['ev'].clear()
        steps, DIALQ['acc'] = DIALQ['acc'], 0
        if steps:
            log('  dial %s %+d steps -> brightness %.0f%%' % (DIALQ.get('last_dir'), steps,
                100 * max(0.05, min(1.0, STATE['intensity'] + steps * float(settings()['dial_step'])))))
            if aim_mode():
                try:
                    aim_turn(steps)
                except Exception as e:
                    log('aim turn: %s' % e.__class__.__name__)
            else:
                turn(steps)
        time.sleep(0.08 if aim_mode() else 0.25)        # aim mode: smooth; lights: ~4 updates a second


def run(s, hs, cfg):
    dev, buttons, rotary = find_switch(hs, cfg, s)
    if not dev:
        STATE['last'] = 'dormant: no Tap Dial found yet'
        time.sleep(30)
        return
    if STATE['device'] != dev:
        STATE['device'] = dev
        log('found the Tap Dial (%d buttons, %s)' % (len(buttons), 'dial' if rotary else 'no dial'))
    g = Gestures(float(s['double_window']), float(s['settle']), doubles=False)
    lock = threading.Lock()

    def handle(batch):
        now = _now()
        with lock:
            for e in parse(batch, buttons, rotary):
                if e[0] == 'button':
                    if e[3]:
                        STATE['lag'] = round(now - e[3], 2)
                    log('  event b%d %s (bridge->here %s s)' % (e[1], e[2], STATE['lag']))
                    for act in g.event(e[1], e[2], e[3], now):
                        JOBS.put(act)
                else:
                    up = (e[1] == 'clock_wise') != bool(s.get('dial_reverse'))     # right = up, always
                    DIALQ['acc'] += e[2] if up else -e[2]
                    DIALQ['last_dir'] = 'right' if e[1] == 'clock_wise' else 'left'
                    DIALQ['ev'].set()

    stop = threading.Event()

    def ticker():
        while not stop.is_set():
            with lock:
                for act in g.due(_now()):
                    JOBS.put(act)
            time.sleep(0.03)
    threading.Thread(target=ticker, daemon=True).start()
    try:
        stream(cfg, handle)
    finally:
        stop.set()


def watch():
    log('tap dial v3 watcher started')
    for f in (worker, dial_worker, sender, lamp_wave_loop):
        threading.Thread(target=f, name='tap-' + f.__name__, daemon=True).start()

    def looks():
        while True:
            try:
                look_watch()
            except Exception:
                pass
            time.sleep(1.0)
    threading.Thread(target=looks, daemon=True).start()
    fails = 0
    while True:
        s = settings()
        if not s['enabled']:
            STATE['last'], STATE['source'] = 'disabled in tap_switch.json', None
            STATE['layers'].update(heads=None, spots=None)
            time.sleep(2)
            continue
        try:
            hs = _hs()
            run(s, hs, hs.load_config())
            fails = 0
        except TimeoutError:
            STATE['source'] = None
            continue
        except Exception as e:
            fails += 1
            STATE['source'] = None
            STATE['last'] = 'event stream dropped (%s) -- reconnecting' % e.__class__.__name__
            time.sleep(min(30, 2 * fails))


TAP_LOOKS = {}                                        # v4: tap changes are recorded with _mark (names only)


def start(on_press=None, module=None):
    if module is None:
        log('no rig_control module given -- Tap Dial not started')
        return
    RC['mod'] = module
    try:                                                # the heads glow isn't a 'quiet room' for head_power
        module.head_power.KEEP_LIT.append(lambda: STATE['layers'].get('heads') in HEAD_MODES and STATE['sending'])
    except AttributeError:
        pass
    for k, v in TAP_LOOKS.items():
        module.LOOKS.setdefault(k, v)
    STATE['seen_look'] = module.STATE.get('look')
    threading.Thread(target=watch, name='tap-dial', daemon=True).start()


def status():
    return dict(device=STATE['device'], last=STATE['last'], source=STATE['source'],
                fill=None if STATE['fill'] is None else int(round(STATE['fill'])), lag_s=STATE['lag'],
                layers=dict(STATE['layers']),
                sending=STATE['sending'], node=STATE['node'],
                next={'hue': STATE['idx'][1] + 1, 'heads': STATE['idx'][2] + 1, 'spots': STATE['idx'][3] + 1,
                      'show': STATE['idx'][4] + 1})
