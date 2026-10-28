#!/usr/bin/env python3
# =============================================================================
# HUE HUB -- the brain of the Botanica light show
#
# One program in Terminal that:
#   - knows every lamp, and every colour zone of the gradient floor lamps
#   - plays LOOKS: colours you paint lamp by lamp (zone by zone), plus a
#     motion (still, breathe, pulse, chase, wave, sparkle, drift, rainbow,
#     picture) that keeps time with Ableton
#   - takes live control from the Light Desk (browser or inside TouchDesigner)
#     and from Push 2 (pads = looks, knobs = live)
#   - plays SONGS: which look at which bar, following the beat
#   - streams to the bulbs 50 times a second, in exact colours, through the
#     flicker protection (no lamp can flash more than 3 times a second)
#
# TouchDesigner only feeds it the picture and the beat (the hue_feed component).
#
#   python3 hue_hub.py                 start (Ctrl+C stops, lights go back to normal)
#   python3 hue_hub.py --rehearse      no bulbs: just the desk and its preview
#   python3 hue_hub.py --phone         also open the desk to phones on your Wi-Fi
#
# The desk:  http://localhost:7020
# Everything you make (looks, songs, lamp places) is saved in hub_state.json.
# =============================================================================

import argparse
import collections
import colorsys
import copy
import json
import math
import os
import random
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hue_stream as hs                                     # noqa: E402  (bridge, colours, flicker protection)
import hub_pads                                             # noqa: E402  (Push 2 PLAY mode: the light instrument)
import hub_visuals                                          # noqa: E402  (what the TD visuals follow)
import hub_audioshow                                        # noqa: E402  (the gear plays the lamps)
import hub_geometry as geo                                  # noqa: E402  (sacred geometry forms + harmonies)
import hub_fx                                               # noqa: E402  (Push's freestyle light effects)
import hub_palette                                          # noqa: E402  (the room's colours: spectrum / triad / degree)
import hub_gradlamp                                         # noqa: E402  (the Play floor lamp's gradient, outside the stream)
import hub_dmx                                              # noqa: E402  (the moving heads, through the Zephyrus' Enttec)
import hub_vibes                                            # noqa: E402  (one-tap auto shows for the Light Desk)

STATE_PATH = os.path.join(HERE, 'hub_state.json')
DESK_PATH = os.path.join(HERE, 'desk.html')                 # the classic desk (at /classic while the Light Desk takes over)
LIGHT_DESK_PATH = os.path.join(HERE, 'light_desk.html')     # the Light Desk: lamps + moving heads in one
TOKEN_PATH = os.path.join(HERE, 'rig_control.token')        # phones / other computers need this key once
FEED_PORT = 7011
DESK_PORT = 7020
FPS = 50.0

MOTIONS = ['still', 'breathe', 'pulse', 'chase', 'wave', 'sparkle', 'drift', 'rainbow', 'picture'] + geo.FORMS
TD_SYNC_PORT = 7012                                         # the hub's geometry clock -> TouchDesigner
SPEEDS = [('4 bars', 1 / 16.0), ('2 bars', 1 / 8.0), ('1 bar', 0.25), ('2 beats', 0.5), ('1 beat', 1.0),
          ('1/2 beat', 2.0)]


def say(*a):
    print(*a, flush=True)


# ---- colour helpers ------------------------------------------------------------------------
def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def hex_rgb(h):
    h = (h or '#000000').lstrip('#')
    if len(h) != 6:
        return (0.0, 0.0, 0.0)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_hex(c):
    return '#%02x%02x%02x' % tuple(int(round(clamp(v) * 255)) for v in c[:3])


def scale(c, k):
    return (c[0] * k, c[1] * k, c[2] * k)


def hsv_mix(a, b, t):
    """Blend two colours round the colour wheel (never through grey)."""
    if t <= 0:
        return tuple(a)
    if t >= 1:
        return tuple(b)
    ha, sa, va = colorsys.rgb_to_hsv(*[clamp(x) for x in a])
    hb, sb, vb = colorsys.rgb_to_hsv(*[clamp(x) for x in b])
    if sa < 0.02 or va < 0.02:
        ha = hb
    if sb < 0.02 or vb < 0.02:
        hb = ha
    dh = ((hb - ha + 0.5) % 1.0) - 0.5
    return colorsys.hsv_to_rgb((ha + dh * t) % 1.0, sa + (sb - sa) * t, va + (vb - va) * t)


def smoothstep(k):
    k = clamp(k)
    return k * k * (3 - 2 * k)


RAINBOW = [('red', (1.00, 0.00, 0.00)), ('orange', (1.00, 0.38, 0.00)), ('yellow', (1.00, 0.85, 0.00)),
           ('green', (0.00, 1.00, 0.05)), ('blue', (0.00, 0.30, 1.00)), ('indigo', (0.28, 0.00, 1.00)),
           ('violet', (0.70, 0.00, 1.00))]


def rainbow_at(x):
    n = len(RAINBOW)
    i = int(math.floor(x)) % n
    f = x - math.floor(x)
    return hsv_mix(RAINBOW[i][1], RAINBOW[(i + 1) % n][1], smoothstep((f - 0.75) / 0.25))


def SEND_AHEAD_BEATS(hub):
    """How far ahead the floor lamp is told (it fades over half a second to get there)."""
    return 0.5 * hub.live.get('tempo', 120.0) / 60.0 / 2.0


def hub_livemidi_deg(d):
    """The colour of scale step d (0 = the 1, wraps round the 7 steps)."""
    try:
        import hub_livemidi
        return hub_livemidi.DEG_RGB[d % 7]
    except Exception:
        return (1.0, 0.0, 0.0)


# ---- lamps -----------------------------------------------------------------------------------
class Rig:
    """Every lamp and its colour zones ('segments'), in streaming order."""

    def __init__(self, lamps, settings):
        self.lamps = []
        seen = set()
        for l in lamps:
            key = l['name']
            n = 2
            while key in seen:
                key = '%s (%d)' % (l['name'], n)
                n += 1
            seen.add(key)
            segs = l['segments']
            xs = [s.get('x', 0.0) for s in segs]
            zs = [s.get('z', 0.0) for s in segs]
            place = [clamp((sum(xs) / len(xs) + 1) / 2), clamp((sum(zs) / len(zs) + 1) / 2)]
            axis = 'across' if len(segs) > 1 and (max(xs) - min(xs)) > (max(zs) - min(zs)) else 'up'
            saved = settings.get(key, {})
            self.lamps.append(dict(key=key, name=l['name'], product=l.get('product', ''),
                                   capable=max(l.get('gradient_points', 0), l.get('max_segments', 1), 1),
                                   channels=[s['channel'] for s in segs],
                                   place=list(saved.get('place', place)), axis=saved.get('axis', axis),
                                   order=saved.get('order'), cap=clamp(float(saved.get('cap', 1.0)), 0.05, 1.0)))
        self.channels = sorted(c for l in self.lamps for c in l['channels'])
        self.layout()

    def layout(self):
        """Where every segment sits (0-1 across, 0-1 up) and its order across the room."""
        self.segs = []
        for li, l in enumerate(self.lamps):
            k = len(l['channels'])
            for si, ch in enumerate(l['channels']):
                f = (si / (k - 1) - 0.5) if k > 1 else 0.0
                u, v = l['place']
                if l['axis'] == 'up':
                    v = clamp(v + f * 0.5)
                else:
                    u = clamp(u + f * 0.25)
                self.segs.append(dict(key='%s#%d' % (l['key'], si), lamp=li, index=si, of=k, ch=ch, u=u, v=v))
        order = sorted(range(len(self.segs)), key=lambda i: (self.segs[i]['u'], self.segs[i]['v']))
        for r, i in enumerate(order):
            self.segs[i]['rank'] = r
        # your order (desk > Setup > Set the order) for chases and colour moves; otherwise left to right
        big = len(self.lamps) + 1
        order = sorted(range(len(self.segs)), key=lambda i: (
            self.lamps[self.segs[i]['lamp']].get('order') if self.lamps[self.segs[i]['lamp']].get('order') is not None
            else big, self.segs[i]['rank']))
        for r, i in enumerate(order):
            self.segs[i]['ord'] = r
        self.by_ch = {s['ch']: i for i, s in enumerate(self.segs)}

    def describe(self):
        return [dict(key=l['key'], name=l['name'], product=l['product'], capable=l['capable'],
                     place=l['place'], axis=l['axis'], order=l.get('order'), cap=l.get('cap', 1.0),
                     segs=['%s#%d' % (l['key'], i) for i in range(len(l['channels']))]) for l in self.lamps]


def virtual_lamps():
    names = ['Behind Desk', 'Floor Shade', 'Top Lamp', 'Hue Play floor lamp large 1', 'Hue color lamp 1',
             'Hue color lamp 2']
    out, ch = [], 0
    for i, n in enumerate(names):
        k = 3 if 'Floor' in n else 1
        segs = []
        for j in range(k):
            segs.append(dict(channel=ch, index=j, x=-0.9 + 1.8 * i / 5, z=(j - (k - 1) / 2) * 0.8 if k > 1 else 0))
            ch += 1
        out.append(dict(name=n, product='(rehearsal lamp)', gradient_points=k, max_segments=k, segments=segs))
    return out


# ---- the show's state ------------------------------------------------------------------------------
def default_looks():
    W, R, O, Y, P, V, T = '#ffbf73', '#ff1e14', '#ff6a00', '#ffd400', '#ff5a9e', '#8a3cff', '#19d2c8'
    return [
        dict(id='warm', name='Warm Home', fill=W, motion='still', speed=0.25, depth=0.5, together=0.5,
             level=0.8, pichits=0.0, canvas={}),
        dict(id='calm', name='Calm', fill='#ff9e4d', motion='breathe', speed=1 / 16.0, depth=0.35, together=0.8,
             level=0.7, pichits=0.0, canvas={}, paint_by_lamp=['#ff9e4d', '#d97f8c', '#ffe0b3']),
        dict(id='sunset', name='Sunset', fill='#ff5a1e', motion='breathe', speed=1 / 8.0, depth=0.2, together=0.3,
             level=0.9, pichits=0.0, canvas={}, gradient=[R, O, Y], paint_by_lamp=[P, '#ff3c28', V]),
        dict(id='groove', name='Groove', fill=T, motion='chase', speed=0.25, depth=0.85, together=0.0,
             level=0.9, pichits=0.0, canvas={}, paint_by_lamp=[T, V, P]),
        dict(id='drop', name='Drop', fill=R, motion='pulse', speed=0.5, depth=0.8, together=1.0,
             level=1.0, pichits=0.6, canvas={}, gradient=[R, V, R], paint_by_lamp=[R, V, P]),
        dict(id='picture', name='Wall Colours', fill='#ffffff', motion='picture', speed=0.25, depth=1.0,
             together=0.0, level=0.9, pichits=0.4, canvas={}),
        dict(id='rainbow', name='Rainbow', fill='#ffffff', motion='rainbow', speed=1.0, depth=1.0, together=0.0,
             level=1.0, pichits=0.0, canvas={}),
        dict(id='outro', name='Outro', fill='#ffbf73', motion='breathe', speed=1 / 16.0, depth=0.2, together=1.0,
             level=0.35, pichits=0.0, canvas={}),
    ]


DEFAULT_LIVE = dict(master=1.0, speed=1.0, smooth=0.25, fade=2.0, tint=0.0, sat=1.0, depth=1.0, guard=2.0,
                    tempo=120.0, movie_bri=1.0, movie_speed=0.25, movie_sat=1.2,
                    **hub_pads.PAD_DEFAULTS, **hub_audioshow.SHOW_DEFAULTS, **hub_fx.FX_DEFAULTS)


SETTINGS_DEFAULT = dict(beats_per_bar=4, iac_on=True, iac_port='IAC', iac_map='pads', iac_looks=True, iac_mpe=True,
                        audio_on=True, audio_in='Scarlett', audio_ch='1,2', audio_sens=1.0,
                        trig_on=True, trig_port='Scarlett', trig_map={'1': 'kick', '2': 'snare', '3': 'hats', '4': 'hats'},
                        a_voices={}, gear_clock=True, a_pat='auto', a_spat='auto', a_origin='centre', a_phrase=8,
                        a_style='programmed', a_cue='auto', a_vis_bars=2, movie=False, movie_src='capture')

CAL_DEFAULT = dict(light_r=1.0, light_g=1.0, light_b=1.0, push_r=1.0, push_g=1.0, push_b=1.0,
                   push_gamma=2.2, push_bright=1.0, proof=True, vivid=1.0,
                   lamp_delay=60.0, held_white=False)


def new_state():
    return dict(version=1, looks=default_looks(), songs=[], lamps={}, live=dict(DEFAULT_LIVE),
                settings=dict(SETTINGS_DEFAULT), active='warm', calibration=dict(CAL_DEFAULT))


def _xyz(x, y):
    return (x / y, 1.0, (1.0 - x - y) / y)


def _inv3(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return ((( e * i - f * h) / det, -(b * i - c * h) / det, (b * f - c * e) / det),
            (-(d * i - f * g) / det, (a * i - c * g) / det, -(a * f - c * d) / det),
            (( d * h - e * g) / det, -(a * h - b * g) / det, (a * e - b * d) / det))


def _mul(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def _primaries_matrix(prims, white):
    """RGB (with these primaries, white = 1,1,1) -> XYZ."""
    cols = [_xyz(*p) for p in prims]
    m = tuple(tuple(cols[j][i] for j in range(3)) for i in range(3))
    sw = _mul(_inv3(m), _xyz(*white))
    return tuple(tuple(m[i][j] * sw[j] for j in range(3)) for i in range(3))


XYZ_TO_SRGB = _inv3(((0.4124, 0.3576, 0.1805), (0.2126, 0.7152, 0.0722), (0.0193, 0.1192, 0.9505)))
# Push 2's pad LEDs and the Hue bulbs both make colour from red, green and blue LEDs with very
# similar primaries, so a pad is driven in those same primaries: same colour point, same mix.
XYZ_TO_LED = _inv3(_primaries_matrix(hs.GAMUT_C, hs.D65))


def xy_to_rgb(x, y, bri):
    """A Hue colour point back to screen RGB (inverse sRGB), clipped to what a screen can show."""
    if bri <= 1e-5 or y <= 1e-6:
        return (0.0, 0.0, 0.0)
    lin = [max(0.0, v) for v in _mul(XYZ_TO_SRGB, _xyz(x, y))]
    m = max(lin) or 1.0
    enc = [(1.055 * (v / m) ** (1 / 2.4) - 0.055) if v / m > 0.0031308 else 12.92 * v / m for v in lin]
    return tuple(clamp(v * bri) for v in enc)


def xy_to_led(x, y, bri, curve=2.2):
    """A Hue colour point as LED drive levels (0-1) for Push 2's pads (their PWM is linear)."""
    if bri <= 1e-5 or y <= 1e-6:
        return (0.0, 0.0, 0.0)
    lin = [max(0.0, v) for v in _mul(XYZ_TO_LED, _xyz(x, y))]
    m = max(lin) or 1.0
    return tuple(clamp(v / m * bri ** curve) for v in lin)


def proof(c):
    """The colour as a Hue bulb can really show it (deep cyans and greens come out paler)."""
    x, y, bri = hs.rgb_to_xyb(*c[:3])
    return xy_to_rgb(x, y, bri)


def bake_starter_canvas(state, rig):
    """Starter looks give lamps colours by position (and gradient lamps a gradient)."""
    for look in state['looks']:
        if look['canvas']:
            continue
        lamp_cols = look.pop('paint_by_lamp', None)
        grad = look.pop('gradient', None)
        order = sorted(range(len(rig.lamps)), key=lambda i: rig.lamps[i]['place'][0])
        for r, li in enumerate(order):
            l = rig.lamps[li]
            base = lamp_cols[r % len(lamp_cols)] if lamp_cols else look['fill']
            k = len(l['channels'])
            for si in range(k):
                if k > 1 and grad:
                    c = grad[min(len(grad) - 1, int(si * len(grad) / k))]
                else:
                    c = base
                look['canvas']['%s#%d' % (l['key'], si)] = c


STARTER_CUES = {'calm', 'picture', 'groove', 'drop', 'rainbow', 'outro'}
OLD_MODES = {'palette': 'breathe', 'sample': 'picture', 'chase': 'chase', 'flash': 'pulse', 'ripple': 'wave',
             'rainbow': 'rainbow'}


def import_old_cues(state, rig):
    """Your own cues from the old hue_rig become looks (the starter ones already have new versions)."""
    path = os.path.join(HERE, 'hue_cues.json')
    try:
        with open(path) as f:
            cues = json.load(f).get('cues', [])
    except (OSError, ValueError):
        return []
    try:
        with open(hs.LAMPS_CSV) as f:
            names = [l.split('\t')[1] for l in f.read().splitlines()[1:] if l.strip()]
    except (OSError, IndexError):
        names = []
    made = []
    for cue in cues:
        if cue.get('name') in STARTER_CUES:
            continue
        v = cue.get('values', {})
        g = lambda n, d: tuple(float(v.get(n + c, x)) for c, x in zip('rgb', d))
        pal = [g('Colora', (1, .62, .3)), g('Colorb', (.85, .5, .55)), g('Accent', (1, .88, .7))]
        lk = dict(id='old_%s' % len(made), name='%s (old)' % cue.get('name', 'cue'),
                  motion=OLD_MODES.get(v.get('Mode', 'palette'), 'breathe'),
                  speed=float(v.get('Rate', 0.25)) if v.get('Sync') else 0.25,
                  depth=0.4, together=float(v.get('Together', 0.0)), level=float(v.get('Intensity', 1.0)),
                  pichits=float(v.get('Picturehits', 0.0)), fill=rgb_hex(pal[0]), canvas={})
        lk['speed'] = min(SPEEDS, key=lambda s: abs(s[1] - lk['speed']))[1]
        for i, name in enumerate(names, 1):
            lamp = next((l for l in rig.lamps if l['name'] == name), None)
            if lamp is None:
                continue
            role = v.get('L%drole' % i, 'mode')
            own = g('L%dcolor' % i, (1, .88, .7))
            col = (0, 0, 0) if role == 'off' else own if role in ('fixed', 'beat') else pal[(i - 1) % 3]
            col = scale(col, float(v.get('L%dbright' % i, 1.0)))
            for si in range(len(lamp['channels'])):
                lk['canvas']['%s#%d' % (lamp['key'], si)] = rgb_hex(col)
        state['looks'].append(lk)
        made.append(lk['name'])
    return made


# ---- the engine ----------------------------------------------------------------------------------------
class Hub:
    def __init__(self, args):
        self.args = args
        self.lock = threading.RLock()
        self.state = self.load_state()
        self.live = self.state['live']
        self.streamer = None
        self.bridge_status = 'not connected'
        self.rig = None
        self.cfg = None
        self.area_name = ''
        fresh = not os.path.exists(STATE_PATH)
        self.build_rig()
        bake_starter_canvas(self.state, self.rig)
        if fresh:
            made = import_old_cues(self.state, self.rig)
            if made:
                say('Brought over your own cues from hue_rig as looks: ' + ', '.join(made))
        # clock
        self.int_beats = 0.0
        self.offset = 0.0
        self.taps = []
        self.feed = dict(beats=None, tempo=None, t=0.0, grid=None, gw=0, gh=0, source='', addr=None)
        self.t_motion = 0.0
        self.last = time.time()
        # look playback
        self.active = self.state.get('active') or self.state['looks'][0]['id']
        self.fade = None                     # dict(from_look, t0, dur)
        self.blackout = False
        self.hold = False
        self.hit_t = -10.0
        self.song = None                     # dict(id, start, section)
        self.prev = None
        self.lim = hs.FlashLimiter(self.live.get('guard', 2.0))
        self.out = [(0.0, 0.0, 0.0)] * len(self.rig.channels)
        self.slow_energy = None
        self.phit = 0.0
        self.dirty = False
        self.dirty_t = 0.0
        self.held = 0.0
        self.crowd, self.crowd_t = 0.0, -10.0   # crowd motion from the Osmo (TouchDesigner osmo_fx)
        self.push = None
        self.ableton = None                     # Ableton's MIDI through the IAC Driver (hub_livemidi.py)
        self.relay = None                       # the show's MIDI out to the Zephyrus (hub_relay.py)
        self.td_msg = None                      # the last message TouchDesigner got (the relay reads it)
        self.audio = None                       # the gear's sound through the Scarlett (hub_audio.py)
        self.audioshow = hub_audioshow.AudioShow(self)
        self.fx = hub_fx.LightFX(self)
        self.palette = hub_palette.Palette(self)
        self.gradlamp = hub_gradlamp.GradLamp(self)
        self.dmx = hub_dmx.Heads(self)          # the moving heads (setting dmx_host = the Zephyrus)
        self.movie_prev = None                  # Movie mode: the lamps' colours from the picture (smoothed)
        self.movie_status = 'off'
        self.message = ('', 0.0)
        self.sparkle_seed = None
        self.sparkle = []
        self.pads = hub_pads.Pads(self)
        self.geo_rot = 0.0
        self.td_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.visuals = hub_visuals.Visuals(self)
        self.proof_fn = proof
        self.td_last = 0.0
        self.calib_test = None
        self.sync_test = False
        self.push_test = None                     # the sync test colour as Push should show it (delayed)
        self.out_hist = collections.deque(maxlen=40)  # (time, lamp colours) for lining Push / TD up with the bulbs
        self.td_queue = collections.deque()
        self.clock = (0.0, self.live.get('tempo', 120.0), '')
        self.song_view = None

    # -- the geometry clock for TouchDesigner (sacred geometry visuals in step with the lamps) --
    def lamp_delay(self):
        """How long the bulbs take to show a colour (bridge -> Zigbee at 25 updates a second -> lamp).
        Push and TouchDesigner wait this long so all three change together (Setup > Timing)."""
        return clamp(self.state['calibration'].get('lamp_delay', 60.0), 0.0, 250.0) / 1000.0

    def out_at(self, t):
        """What the lamps were sent at time t (the newest frame not after t)."""
        best = None
        for tt, o in self.out_hist:
            if tt <= t:
                best = o
            else:
                break
        return best if best is not None else self.out

    def push_follow(self, now):
        """Push shows the sync test colour when the bulbs do."""
        if self.push is None:
            return
        want = None
        if self.sync_test:
            o = self.out_at(now - self.lamp_delay())
            want = tuple(o[0]) if o else None
        if want != self.push_test:
            self.push_test = want
            try:
                self.push.refresh(force=True)
            except Exception:
                pass

    def send_td_sync(self, now):
        if now - self.td_last >= 1 / 60.0:                 # as often as TouchDesigner draws
            self.td_last = now
            try:
                with self.lock:
                    msg = self.visuals.step(now)
                    self.td_msg = msg
                # TouchDesigner draws it on its next frame: send one frame (1/60 s) early
                self.td_queue.append((now + max(0.0, self.lamp_delay() - 1 / 60.0), json.dumps(msg, separators=(',', ':')).encode()))
            except Exception as e:
                if not getattr(self, '_td_warned', False):
                    self._td_warned = True
                    print('TouchDesigner sync: %s' % e)
        while self.td_queue and (self.td_queue[0][0] <= now or len(self.td_queue) > 40):
            _, data = self.td_queue.popleft()
            try:
                self.td_sock.sendto(data, ('127.0.0.1', TD_SYNC_PORT))
            except Exception:
                pass

    # -- colour matching --
    def calib_light(self, c):
        k = self.state['calibration']
        return (c[0] * k.get('light_r', 1.0), c[1] * k.get('light_g', 1.0), c[2] * k.get('light_b', 1.0))

    def push_colour(self, rgb255):
        """A colour (0-255) as Push 2's pads should get it so the pad looks like the lamp: the same
        Hue colour point the lamp gets, mixed from the pad's red/green/blue LEDs, then the pads'
        own balance from Setup > Colour match."""
        k = self.state['calibration']
        hs.VIVID = k.get('vivid', 1.0)
        x, y, bri = hs.rgb_to_xyb(*(v / 255.0 for v in rgb255))
        led = xy_to_led(x, y, bri, k.get('push_gamma', 2.2))
        bal = (k.get('push_r', 1.0), k.get('push_g', 1.0), k.get('push_b', 1.0))
        return tuple(max(0, min(255, int(round(255 * v * b * k.get('push_bright', 1.0))))) for v, b in zip(led, bal))

    # -- persistence --
    def load_state(self):
        try:
            with open(STATE_PATH) as f:
                st = json.load(f)
            base = new_state()
            for k, v in base.items():
                st.setdefault(k, v)
            for k, v in DEFAULT_LIVE.items():
                st['live'].setdefault(k, v)
            for k, v in CAL_DEFAULT.items():
                st.setdefault('calibration', {}).setdefault(k, v)
            for k, v in SETTINGS_DEFAULT.items():
                st.setdefault('settings', {}).setdefault(k, v)
            return st
        except (OSError, ValueError):
            return new_state()

    def save_soon(self):
        self.dirty = True
        self.dirty_t = time.time()
        self.rev = getattr(self, 'rev', 0) + 1            # tells the desk to reload

    def save_now(self):
        with self.lock:
            st = copy.deepcopy(self.state)
            st['active'] = self.active
            st['lamps'] = {l['key']: dict(place=l['place'], axis=l['axis'], order=l.get('order'), cap=l.get('cap', 1.0))
                           for l in self.rig.lamps}
        tmp = STATE_PATH + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(st, f, indent=1)
        os.replace(tmp, STATE_PATH)
        self.dirty = False

    # -- lamps / bridge --
    def build_rig(self):
        lamps = None
        if not self.args.rehearse:
            try:
                self.cfg = hs.load_config()
                if self.args.ip:
                    self.cfg['ip'] = self.args.ip
                hs.need_pairing(self.cfg)
                area = hs.pick_area(self.cfg, self.args.area or self.wanted_area() or self.cfg.get('area_name'))
                self.area_name = area.get('metadata', {}).get('name', '')
                lamps = hs.lamp_layout(self.cfg, area)
            except SystemExit:
                say('Could not reach the bridge (see above) -- rehearsal mode: desk and preview only.')
                self.args.rehearse = True
            except Exception as e:
                say('Could not read the lamps from the bridge (%s) -- rehearsal mode.' % e)
                self.args.rehearse = True
        if lamps is None:
            try:
                with open(hs.HUB_LAMPS) as f:
                    lamps = json.load(f)['lamps']
                say('Rehearsal: using the lamps from hub_lamps.json')
            except (OSError, ValueError, KeyError):
                lamps = virtual_lamps()
                say('Rehearsal: using 6 practice lamps')
        self.rig = Rig(lamps, self.state.get('lamps', {}))

    def wanted_area(self):
        """Movie / sync mode streams EVERY lamp, floor lamp included, in one area (setting 'movie_area',
        default "Music area") so they all land on the same frame. Other modes use the show's area."""
        st = self.state['settings']
        if st.get('palette') in ('sync', 'music') and st.get('movie_area', 'Music area'):
            return st.get('movie_area', 'Music area')
        return None

    def connect(self):
        if self.args.rehearse:
            self.bridge_status = 'rehearsal (no bulbs)'
            return
        self.last_connect = time.time()
        try:
            st = hs.Streamer(self.cfg, self.area_name or None, 'xy')
            if sorted(st.channels) != self.rig.channels:
                say('Note: the area changed since the lamps were read -- restart the hub.')
            st.start()
            self.streamer = st                       # only once it's fully ready
            self.bridge_status = 'streaming to "%s"' % self.area_name
            say('Lights: %s' % self.bridge_status)
        except SystemExit:
            self.streamer = None
            self.bridge_status = 'not connected -- trying again every 5 s (see Terminal)'
        except Exception as e:
            self.streamer = None
            self.bridge_status = 'not connected (%s) -- trying again every 5 s' % e
        finally:
            self.connecting = False

    def reconnect_soon(self, now):
        """The bridge dropped us (another program took the stream, Wi-Fi blip...): try again."""
        if self.args.rehearse or self.streamer is not None or getattr(self, 'connecting', False):
            return
        if now - getattr(self, 'last_connect', 0.0) < 5.0:
            return
        self.connecting = True
        threading.Thread(target=self.connect, daemon=True).start()

    def disconnect(self):
        if self.streamer is not None:
            try:
                self.streamer.stop()
            except Exception:
                pass
            self.streamer = None

    # -- looks --
    def look(self, lid):
        for l in self.state['looks']:
            if l['id'] == lid:
                return l
        return None

    def go(self, lid, fade=None):
        with self.lock:
            if self.look(lid) is None:
                return False
            if lid != self.active:
                dur = self.live['fade'] if fade is None else fade
                self.fade = dict(frm=copy.deepcopy(self.look(self.active)), t0=time.time(), dur=max(0.0, dur))
                self.active = lid
                self.save_soon()
            if self.push:
                self.push.refresh()
            return True

    def note(self, text):
        self.message = (text, time.time())

    # -- clock --
    def beats_now(self, now, dt):
        f = self.feed
        tempo = self.live.get('tempo', 120.0)
        g = (self.audio.clock(now) if self.audio is not None and self.state['settings'].get('gear_clock', True)
             else None)
        hc = (self.audio.heard_clock(now) if g is None and self.audio is not None
              and self.state['settings'].get('gear_clock', True) else None)
        if g is not None:                               # the gear's MIDI clock (Digitakt): the lights play in its time
            b, tempo = g
            self.int_beats = b
            src = 'gear MIDI clock (%.1f BPM)' % tempo
        elif hc is not None:                            # no clock: the tempo the hub HEARS in the music
            b, tempo = hc
            self.int_beats = b
            src = 'heard in the music (%.1f BPM)' % tempo
        elif f['beats'] is not None and now - f['t'] < 1.0:
            tempo = f['tempo'] or tempo
            b = f['beats'] + (now - f['t']) * tempo / 60.0
            self.int_beats = b                          # keep the internal clock in step for a smooth hand-over
            src = f['source'] or 'TouchDesigner'
        else:
            self.int_beats += dt * tempo / 60.0
            b = self.int_beats
            src = 'internal (%.1f BPM)' % tempo
        if b is None or tempo is None:                  # a source without a beat yet: keep the internal clock going
            self.int_beats += dt * (tempo or 120.0) / 60.0
            b, tempo, src = self.int_beats, tempo or 120.0, 'internal (%.1f BPM)' % (tempo or 120.0)
        return b + self.offset, tempo, src

    def tap(self):
        now = time.time()
        self.taps = [t for t in self.taps if now - t < 2.5] + [now]
        if len(self.taps) >= 2:
            gaps = [b - a for a, b in zip(self.taps, self.taps[1:])]
            self.live['tempo'] = clamp(60.0 / (sum(gaps) / len(gaps)), 40.0, 240.0)
        self.int_beats = float(round(self.int_beats))

    def downbeat(self):
        bpb = self.state['settings'].get('beats_per_bar', 4)
        b = self.clock[0]
        self.offset += round(b / bpb) * bpb - b

    # -- songs --
    def song_obj(self, sid):
        for s in self.state['songs']:
            if s['id'] == sid:
                return s
        return None

    def song_start(self, sid, when='next', section=0):
        s = self.song_obj(sid)
        if not s:
            return False
        bpb = self.state['settings'].get('beats_per_bar', 4)
        b = self.clock[0]
        nb = math.ceil(b / bpb - 1e-6) * bpb if when == 'next' else math.floor(b / bpb) * bpb
        secs = sorted(s.get('sections', []), key=lambda x: x['bar'])
        bar = secs[section]['bar'] if secs and 0 <= section < len(secs) else 1
        self.song = dict(id=sid, start=nb - (bar - 1) * bpb, section=-1)
        return True

    def song_tick(self, beats):
        if not self.song:
            return None
        s = self.song_obj(self.song['id'])
        if not s or not s.get('sections'):
            self.song = None
            return None
        bpb = self.state['settings'].get('beats_per_bar', 4)
        secs = sorted(s['sections'], key=lambda x: x['bar'])
        length = max(int(s.get('length', 0) or 0), secs[-1]['bar'] + 3)
        pos = (beats - self.song['start']) / bpb           # bars since bar 1
        if pos >= length:
            if s.get('loop'):
                self.song['start'] += length * bpb
                pos -= length
            else:
                self.song = None
                return None
        bar = int(math.floor(pos)) + 1
        idx = -1
        for i, sec in enumerate(secs):
            if sec['bar'] <= bar:
                idx = i
        if idx >= 0 and idx != self.song['section'] and pos >= 0:
            self.song['section'] = idx
            sec = secs[idx]
            tempo = self.clock[1] or 120.0
            fade_s = float(sec.get('fade', 1.0)) * 60.0 / tempo
            self.go(sec['look'], fade=fade_s)
        return dict(id=s['id'], name=s['name'], bar=bar, beat=(beats - self.song['start']) % bpb + 1,
                    pos=pos, section=idx, length=length)

    # -- picture from TouchDesigner --
    def picture_at(self, u, v, r=1):
        f = self.feed
        g = f['grid']
        if not g or time.time() - f['t'] > 1.0:
            return None
        w, h = f['gw'], f['gh']
        x, y = int(round(u * (w - 1))), int(round((1 - v) * (h - 1)))
        acc, best, bv, n = [0.0, 0.0, 0.0], None, -1, 0
        for yy in range(max(0, y - r), min(h, y + r + 1)):
            for xx in range(max(0, x - r), min(w, x + r + 1)):
                i = (yy * w + xx) * 3
                c = (g[i] / 255.0, g[i + 1] / 255.0, g[i + 2] / 255.0)
                acc = [a + b for a, b in zip(acc, c)]
                n += 1
                if sum(c) > bv:
                    bv, best = sum(c), c
        mean = [a / n for a in acc]
        return tuple(m * 0.4 + b * 0.6 for m, b in zip(mean, best))

    def movie_cols(self, dt):
        """Each lamp zone's colour from the picture around where it sits (left lamps take the left of the
        picture, and so on), averaged over a patch like an ambilight, a little richer, and smoothed so the
        lamps follow the film without twitching. None if TouchDesigner isn't sending a picture."""
        f = self.feed
        g = f['grid']
        if not g or time.time() - f['t'] > 1.0:
            self.movie_status = 'waiting for the picture from TouchDesigner (movie_in)'
            return self.movie_prev
        w, hgt = f['gw'], f['gh']
        rx, ry = max(1, int(w * 0.14)), max(1, int(hgt * 0.16))
        sat = self.live.get('movie_sat', 1.2)
        bri = self.live.get('movie_bri', 1.0)
        out = []
        for sg in self.rig.segs:
            x, y = int(round(sg['u'] * (w - 1))), int(round((1 - sg['v']) * (hgt - 1)))
            acc, n, best, bv = [0.0, 0.0, 0.0], 0, (0.0, 0.0, 0.0), -1.0
            for yy in range(max(0, y - ry), min(hgt, y + ry + 1)):
                for xx in range(max(0, x - rx), min(w, x + rx + 1)):
                    i = (yy * w + xx) * 3
                    c = (g[i] / 255.0, g[i + 1] / 255.0, g[i + 2] / 255.0)
                    acc[0] += c[0]
                    acc[1] += c[1]
                    acc[2] += c[2]
                    n += 1
                    if sum(c) > bv:
                        bv, best = sum(c), c
            mean = [a / max(1, n) for a in acc]
            c = [m * 0.7 + b * 0.3 for m, b in zip(mean, best)]
            hh, ss, vv = colorsys.rgb_to_hsv(*[clamp(v) for v in c])
            out.append(colorsys.hsv_to_rgb(hh, clamp(ss * sat), clamp(vv * bri)))
        k = 1.0 - math.exp(-dt / max(0.03, self.live.get('movie_speed', 0.25)))
        if self.movie_prev is None or len(self.movie_prev) != len(out):
            self.movie_prev = out
        else:
            self.movie_prev = [tuple(p + (q - p) * k for p, q in zip(pc, qc)) for pc, qc in zip(self.movie_prev, out)]
        self.movie_status = 'following the picture (%dx%d)' % (w, hgt)
        return self.movie_prev

    def picture_energy(self, dt):
        g = self.feed['grid']
        if not g or time.time() - self.feed['t'] > 1.0:
            self.phit = 0.0
            return
        e = sum(g) / (255.0 * len(g))
        if self.slow_energy is None:
            self.slow_energy = e
        self.slow_energy += (e - self.slow_energy) * (1 - math.exp(-dt / 0.6))
        self.phit = clamp((e - self.slow_energy) * 8.0)

    # -- one look, rendered --
    def render(self, look, t, now):
        segs = self.rig.segs
        n = max(1, len(segs))
        fill = hex_rgb(look.get('fill', '#ffffff'))
        canvas = look.get('canvas', {})
        motion = look.get('motion', 'still')
        depth = clamp(look.get('depth', 0.5) * self.live.get('depth', 1.0))
        tog = clamp(look.get('together', 0.0))
        level = look.get('level', 1.0)
        base = [hex_rgb(canvas[s['key']]) if s['key'] in canvas else fill for s in segs]
        shape = geo.form(motion, segs, t, self.geo_rot, base, clamp(look.get('together', 0.5))) \
            if motion in geo.FORMS else None
        by_rank = sorted(range(len(segs)), key=lambda i: segs[i]['rank'])
        out = []
        if motion == 'sparkle':
            step = int(math.floor(t * 2))
            if self.sparkle_seed != step:
                rnd = random.Random(step * 7919)
                self.sparkle = [rnd.random() < 0.35 for _ in segs]
                self.sparkle_seed = step
        for i, s in enumerate(segs):
            c = base[i]
            r = s['rank']
            ph = (r / n) * (1 - tog)
            if motion == 'breathe':
                c = scale(c, 1 - depth * 0.5 * (1 - math.cos(2 * math.pi * (t + ph))))
            elif motion == 'pulse':
                f = (t + ph) % 1.0
                c = scale(c, (1 - depth) + depth * math.exp(-f / 0.18))
            elif motion == 'chase':
                d = abs((t % 1.0) - (r + 0.5) / n)
                d = min(d, 1 - d) * n
                c = scale(c, (1 - depth) + depth * math.exp(-d * d * 1.6))
            elif motion == 'wave':
                d = math.hypot(s['u'] - 0.5, s['v'] - 0.5) * 1.6
                c = scale(c, (1 - depth) + depth * math.exp(-((t - d) % 1.0) / 0.2))
            elif motion == 'sparkle':
                f = (t * 2) % 1.0
                k = math.exp(-f / 0.3) if self.sparkle[i] else 0.0
                c = scale(c, (1 - depth) + depth * k)
            elif motion == 'drift':
                x = t * 2 + r                              # colours slide across the room
                a_i, b_i = int(math.floor(x)) % n, (int(math.floor(x)) + 1) % n
                c = hsv_mix(base[by_rank[a_i]], base[by_rank[b_i]], smoothstep((x % 1.0 - 0.6) / 0.4))
            elif motion == 'rainbow':
                part = int(math.floor(t / 16.0)) % 3
                if part == 0:
                    c = rainbow_at(t + r * 7.0 / max(n, 7))
                elif part == 1:
                    c = scale(rainbow_at(t / 2.0), 0.8 + 0.2 * math.exp(-((t / 2.0) % 1.0) / 0.25))
                else:
                    step = t / 2.0
                    j = int(math.floor(step))
                    edge = smoothstep(((step - j) - (r + 0.5) / n) / 0.18 + 0.5)
                    c = hsv_mix(RAINBOW[(j - 1) % 7][1], RAINBOW[j % 7][1], edge)
            elif shape is not None:                       # sacred geometry
                b, gc = shape[i]
                c = scale(gc if gc is not None else c, (1 - depth) + depth * b)
            elif motion == 'picture':
                p = self.picture_at(s['u'], s['v'])
                if p is not None:
                    c = hsv_mix(c, p, depth) if max(p) > 0.02 else scale(c, 1 - depth)
            if look.get('pichits', 0) > 0 and self.phit > 0:
                k = self.phit * look['pichits']
                m_ = max(c)                              # a hit brightens the lamp IN ITS OWN COLOUR (never white)
                if m_ > 0.02:
                    c = scale(c, min(1.0, m_ * (1 + k)) / m_)
            out.append(tuple(clamp(x * level) for x in c))
        return out

    # -- one frame --
    def frame(self):
        now = time.time()
        dt = clamp(now - self.last, 0.0, 0.25)
        self.last = now
        with self.lock:
            beats, tempo, src = self.beats_now(now, dt)
            self.clock = (beats, tempo, src)
            song = self.song_tick(beats)
            look = self.look(self.active) or self.state['looks'][0]
            sp = look.get('speed', 0.25)
            ls = self.live.get('speed', 1.0)
            if not self.hold:
                self.t_motion += dt * tempo / 60.0 * sp * ls
                if abs(ls - 1.0) < 0.02:                   # stay locked to the beat
                    err = ((beats * sp - self.t_motion + 0.5) % 1.0) - 0.5
                    self.t_motion += err * min(1.0, dt * 2.0)
            self.picture_energy(dt)
            self.geo_rot = self.t_motion * math.pi / 2 + self.pads.geo_spin()    # a quarter turn per cycle
            cols = self.render(look, self.t_motion, now)
            if self.fade:
                k = 1.0 if self.fade['dur'] <= 0 else (now - self.fade['t0']) / self.fade['dur']
                if k >= 1.0:
                    self.fade = None
                else:
                    old = self.render(self.fade['frm'], self.t_motion, now)
                    cols = [hsv_mix(a, b, smoothstep(k)) for a, b in zip(old, cols)]
            # the pads you're playing on Push 2 (or the desk's Pads tab), on top of the look
            # live: Colour (turns the look round the wheel) and Vibrance -- the LOOK only
            tint, sat = self.live.get('tint', 0.0) / 360.0, self.live.get('sat', 1.0)
            if abs(tint) > 1e-4 or abs(sat - 1) > 1e-3:
                res = []
                for c in cols:
                    h, s_, v = colorsys.rgb_to_hsv(*c)
                    res.append(colorsys.hsv_to_rgb((h + tint) % 1.0, clamp(s_ * sat), v))
                cols = res
            # the pads go on top AFTER that, so a red pad is red on the lamps whatever Colour is set to
            cols = self.pads.render(cols, beats, now)
            # hit, master, blackout
            hit = math.exp(-(now - self.hit_t) / 0.25) if now - self.hit_t < 2 else 0.0
            if hit > 0.01:
                cols = [tuple(x + (1 - x) * hit * 0.8 for x in c) for c in cols]
            m = 0.0 if self.blackout else self.live.get('master', 1.0)
            cols = [scale(c, m) for c in cols]
            if self.sync_test:                                # Setup > Timing: red / blue, one change a second
                self.calib_test = (1.0, 0.0, 0.0) if int(now) % 2 == 0 else (0.0, 0.25, 1.0)
            if self.calib_test is not None:                   # Setup > Colour match: every lamp one test colour
                cols = [self.calib_test] * len(cols)
            # smoothing (fades up quicker than down), then flicker protection
            sm = self.live.get('smooth', 0.25)
            if self.prev is not None and len(self.prev) == len(cols):
                rise = 0.005 + 0.4 * sm * sm
                fall = 0.02 + 1.0 * sm
                if self.blackout:
                    fall = max(fall, 0.4)
                au, ad = 1 - math.exp(-dt / rise), 1 - math.exp(-dt / fall)
                ac = 1 - math.exp(-dt / 0.02)          # colour: always quick, whatever Smoothing is set to
                # Smoothing softens BRIGHTNESS (up quicker than down); the COLOUR changes at once and at
                # full strength, so a new pad's colour arrives straight away instead of through a dim mix
                sm_cols = []
                for pc, qc in zip(self.prev, cols):
                    m0, m1 = max(pc), max(qc)
                    m = m0 + (m1 - m0) * (au if m1 > m0 else ad)
                    n1 = [x / m1 for x in qc] if m1 > 1e-6 else None
                    n0 = [x / m0 for x in pc] if m0 > 1e-6 else n1
                    if n1 is None:
                        n1 = n0
                    if n0 is None:
                        sm_cols.append(tuple(qc))
                        continue
                    n = [p + (q - p) * ac for p, q in zip(n0, n1)]
                    mm = max(n) or 1.0
                    sm_cols.append(tuple(x / mm * m for x in n))
                cols = sm_cols
            self.prev = cols
            # the gear: kick / snare / hats / loudness from the Scarlett (hub_audio + hub_audioshow).
            # It goes on AFTER Smoothing -- Smoothing softens look and pad changes, the drums keep their
            # punch -- and BEFORE the flicker protection, which still limits everything.
            aud = self.audioshow.render(cols, now, dt)
            if not self.blackout and self.calib_test is None:
                cols = aud
            # CROWD: movement the Osmo sees (TouchDesigner osmo_fx posts it) lifts the lamps' brightness.
            # Before the flicker protection, so it is still limited like everything else.
            if time.time() - getattr(self, 'crowd_t', -10.0) < 2.0 and not self.blackout and self.calib_test is None:
                k = self.crowd * self.live.get('crowd_amt', 0.6)
                if k > 0.005:
                    res = []
                    for c in cols:
                        m0 = max(c)
                        res.append(tuple(x * (m0 + (1 - m0) * k) / m0 for x in c) if m0 > 0.02 else c)
                    cols = res
            # MOVIE MODE: the lamps take the colours of the picture (PC / PS5 / this Mac / a camera, through
            # TouchDesigner's movie_in) -- around the screen like an ambilight. Only while Movie mode is on.
            self.pic_on = False
            if self.state['settings'].get('movie') and self.calib_test is None and not self.state['settings'].get('intermission'):
                mc = self.movie_cols(dt)
                self.pic_on = mc is not None                    # the picture is driving the lamps: palettes stand aside
                if mc is not None:
                    mst = 0.0 if self.blackout else self.live.get('master', 1.0)
                    cols = [scale(c, mst) for c in mc]
            # DEGREES -> COLOURS: the step you just played colours EVERY lamp (the music still drives how
            # bright each one is). Lasts while the note's pad is held / latched; "all pads off" hands back.
            lm = self.ableton
            drgb = getattr(lm, 'deg_rgb', None) if lm is not None else None
            pmode = self.palette.mode()          # 'spectrum' (rainbow gradient) / 'triad' / 'degree' (1 = red ...)
            playing = drgb is not None and self.state['settings'].get('iac_map') == 'degree' and self.pads.active()
            if playing:
                self.palette.note(drgb, now)
            if pmode == 'sync' and not self.blackout and self.calib_test is None and not self.pic_on:
                ch = int(self.state['settings'].get('sync_ch', 2))
                rms = float(getattr(self.audio, 'ch_rms', {}).get(ch, 0.0)) if self.audio is not None else 0.0
                cols = self.palette.render_sync(cols, now, dt, rms)
            elif pmode == 'music' and not self.blackout and self.calib_test is None and not self.pic_on:
                # the Scarlett's TOTAL sound: every channel it hears (setting music_ch, default all) combined
                chr_ = dict(getattr(self.audio, 'ch_rms', {}) or {}) if self.audio is not None else {}
                want = str(self.state['settings'].get('music_ch', 'all'))
                chans = list(chr_) if want == 'all' else [int(c) for c in want.split(',') if c.strip().isdigit()]
                tot = math.sqrt(sum(float(chr_.get(c_, 0.0)) ** 2 for c_ in chans))
                cols = self.palette.render_music(cols, now, dt, tot)
            elif pmode == 'lava' and not self.blackout and self.calib_test is None and not self.pic_on:
                cols = self.palette.render_lava(cols, beats, now, dt, getattr(self.audioshow, 'section', 'groove'),
                                                kick=float(getattr(self.audioshow, 'env', {}).get('kick', 0.0)))
            elif pmode == 'spectrum' and not self.blackout and self.calib_test is None and not self.pic_on:
                cols = self.palette.render(cols, beats, now, dt, getattr(self.audioshow, 'section', 'groove'))
            elif playing and not self.blackout and self.calib_test is None:
                ld = getattr(lm, 'last_degree', None)
                if pmode == 'triad' and ld is not None and float(ld) == int(ld):
                    # the room plays the TRIAD on the step: the step's colour leads, its third and fifth
                    # colour the lamps between (1 = red + yellow + blue, 2 = orange + green + indigo ...)
                    d0 = int(ld) - 1
                    tri = [hub_livemidi_deg(d0), hub_livemidi_deg(d0 + 2), hub_livemidi_deg(d0), hub_livemidi_deg(d0 + 4)]
                    res = []
                    for i_, c_ in enumerate(cols):
                        r_ = self.rig.segs[i_].get('ord', i_) if i_ < len(self.rig.segs) else i_
                        hd, sd, _ = colorsys.rgb_to_hsv(*tri[r_ % 4])
                        res.append(colorsys.hsv_to_rgb(hd, sd, max(clamp(x) for x in c_)))
                    cols = res
                else:
                    hd, sd, _ = colorsys.rgb_to_hsv(*drgb)
                    cols = [colorsys.hsv_to_rgb(hd, sd, max(clamp(x) for x in c_)) for c_ in cols]
            # FREESTYLE RACK: Push's top knobs (strobe, prism, orbit, breathe, pump, echo, chord, sparkle)
            if not self.blackout and self.calib_test is None:
                try:
                    cols = self.fx.render(cols, beats, tempo, now)
                except Exception as e:
                    if now - getattr(self, '_fx_err_t', 0.0) > 10.0:
                        self._fx_err_t = now
                        say('Light FX: %s' % e)
            # PER-LAMP CAP: lamps near the projection never go above their cap (the music still moves them)
            # (not in sync / movie mode: there every bulb must match exactly -- a capped bulb dips below
            #  its lowest dim level at a different moment and looks out of sync)
            caps = [self.rig.lamps[sg['lamp']].get('cap', 1.0) for sg in self.rig.segs]
            if pmode not in ('sync', 'music') and any(k < 0.999 for k in caps):
                cols = [scale(c_, k) if k < 0.999 else c_ for c_, k in zip(cols, caps)]
            idt = getattr(self, 'ident', None)
            if idt is not None:
                if time.time() < idt[1]:
                    cols = [(0.8, 0.8, 0.8) if self.rig.lamps[sg['lamp']]['key'] == idt[0] else (0.0, 0.0, 0.0)
                            for sg in self.rig.segs]
                else:
                    self.ident = None
            # music mode runs the flicker protection at its ceiling (3 flashes/s) so every kick up to ~180 BPM lands
            self.lim.set_rate(3.0 if pmode == 'music' else self.live.get('guard', 2.0))
            hs.VIVID = self.state['calibration'].get('vivid', 1.0)
            # streaming order = sorted channel ids
            ordered = [cols[self.rig.by_ch[ch]] for ch in self.rig.channels]
            ordered = self.lim.step(ordered, now)
            try:
                self.grad_frame(beats, pmode)
            except Exception as e:
                if now - getattr(self, '_gl_err_t', 0.0) > 30.0:
                    self._gl_err_t = now
                    say('Floor lamp gradient: %s' % e)
            try:                                  # the moving heads follow the lamps AFTER the flicker protection
                self.dmx.frame(now, dt, beats, ordered, pmode)
            except Exception as e:
                if now - getattr(self, '_dmx_err_t', 0.0) > 30.0:
                    self._dmx_err_t = now
                    say('Moving heads: %s' % e)
            self.held = self.held * 0.97 + (0.03 if self.lim.held else 0.0)
            self.out = ordered
            self.out_hist.append((now, ordered))
            self.song_view = song
        if self.streamer is not None:
            try:
                self.streamer.send([self.calib_light(c) for c in ordered])
            except Exception as e:
                self.bridge_status = 'lost the bridge (%s) -- reconnecting' % e
                say('Lights: lost the bridge (%s) -- reconnecting in 5 s' % e)
                try:
                    self.streamer.sock.close()
                except Exception:
                    pass
                self.streamer = None
                self.last_connect = now
        else:
            self.reconnect_soon(now)
        self.send_td_sync(now)
        self.push_follow(now)
        if self.dirty and now - self.dirty_t > 1.0:
            try:
                self.save_now()
            except OSError as e:
                say('Could not save hub_state.json: %s' % e)

    def grad_frame(self, beats, pmode):
        """The Play floor lamp's gradient (hub_gradlamp): the wall's rainbow in lava mode, else the room."""
        gl = getattr(self, 'gradlamp', None)
        if gl is None:
            return
        gname = self.state['settings'].get('grad_lamp', 'Hue Play floor lamp large 1')
        if any(l.get('name') == gname for l in self.rig.lamps):
            return                                # it's in the stream: it gets its colour with every other bulb
        cap = clamp(float(self.state['settings'].get('grad_cap', 0.75)), 0.05, 1.0)
        if self.blackout:
            gl.update([], 0.0, on=False)
            return
        master = clamp(self.live.get('master', 1.0))
        if pmode == 'sync':                       # movie / sync: exactly the room's colour and brightness
            gl.every = 0.2
            gl.fade = 0.12                            # short fade: lands on the hit instead of smearing it
            c = getattr(self.palette, 'sync_c', None)
            if c is None:
                return
            # The floor lamp only gets ~5 updates a second (it's outside the stream), so it can't sample
            # every syllable. Send it the PEAK of the last update window, so it lights on the same hits
            # the streamed bulbs do instead of catching a random moment between them.
            now_ = time.time()
            pk = getattr(self, '_grad_peak', None)
            if pk is None:
                pk = self._grad_peak = collections.deque()
            pk.append((now_, getattr(self.palette, 'sync_v', 0.0)))
            while pk and pk[0][0] < now_ - gl.every:
                pk.popleft()
            v_ = max(v for _, v in pk)
            gl.update([c] * 5, v_, on=v_ > 0.02)                 # same level as every bulb; silence = fully dark
            return
        gl.fade = None
        gl.every = 0.5
        if pmode == 'lava':
            hue, f = self.palette.lava_hue(beats + 2.0 * SEND_AHEAD_BEATS(self))
            cols5 = [hub_palette.vivid((hue + (j / 4.0 - 0.5) * hub_palette.LAVA_WALL_SPAN) % 360.0) for j in range(5)]
            gl.update(cols5, master * 0.85 * cap)
        else:
            segs = sorted(range(len(self.rig.segs)), key=lambda i: self.rig.segs[i].get('rank', i))
            room = [self.out[self.rig.channels.index(self.rig.segs[i]['ch'])] for i in segs] if self.out else []
            if not room:
                return
            pick = [room[int(round(j * (len(room) - 1) / 4.0))] for j in range(5)]
            bri = max(max(c) for c in pick)
            gl.update([tuple(x / max(max(c), 1e-3) for x in c) for c in pick], bri * cap)

    def pi_heartbeat(self):
        """Every 10 s tell the Ney Pi (setting pi_url) we're alive -- it alerts your phone if we go quiet."""
        url = self.state['settings'].get('pi_url', '')
        now = time.time()
        if not url or now - getattr(self, '_pi_t', 0.0) < 10.0:
            return
        self._pi_t = now
        beat = dict(t=now, bridge=self.bridge_status, feed=(now - self.feed['t'] < 3.0),
                    audio=(self.audio.status if self.audio is not None else 'off'),
                    push=(self.push.status if self.push else 'off'),
                    heads=(self.dmx.describe() if getattr(self, 'dmx', None) else 'off'),
                    brain=(self.audio.brain.snapshot() if self.audio is not None and getattr(self.audio, 'brain', None)
                           is not None else None))

        def send():
            try:
                import urllib.request
                rq = urllib.request.Request(url, data=json.dumps(beat).encode(),
                                            headers={'Content-Type': 'application/json'})
                urllib.request.urlopen(rq, timeout=3).read()
            except Exception:
                pass
        threading.Thread(target=send, daemon=True).start()

    def code_changed(self, now):
        """New code in the Hue Rig folder (an update)? True once it has settled and compiles cleanly."""
        if now - getattr(self, 'code_t', 0.0) < 2.0:
            return False
        self.code_t = now
        st = code_stamp()
        if not hasattr(self, 'code0'):
            self.code0, self.code_seen = st, None
            return False
        if st == self.code0:
            return False
        if st != self.code_seen:                       # still being written: wait for it to settle
            self.code_seen = st
            return False
        here = os.path.dirname(os.path.abspath(__file__))
        for f in CODE_FILES:
            try:
                with open(os.path.join(here, f), encoding='utf-8') as fh:
                    compile(fh.read(), f, 'exec')
            except OSError:
                pass
            except SyntaxError as e:
                say('New code in %s has an error (%s) -- carrying on with the old code.' % (f, e))
                self.code0 = st
                return False
        return True

    def run(self):
        period = 1.0 / FPS
        while True:
            t0 = time.time()
            try:
                self.frame()
                if self.push:
                    self.push.poll()
                if self.ableton:
                    self.ableton.poll()
                    self.pi_heartbeat()
                    if getattr(self, 'livekey', None) is not None:
                        self.livekey.poll()
                    br = getattr(self.audio, 'brain', None) if self.audio is not None else None
                    if br is not None:
                        for root, minor, strength in br.poll():          # chords heard in the mix -> MIDI ch 2
                            self.ableton.send_heard(root, minor, strength)
                if self.relay:
                    self.relay.poll(t0)
            except Exception as e:                       # never let one bad frame stop the show
                say('frame error: %s: %s' % (type(e).__name__, e))
                key = '%s: %s' % (type(e).__name__, e)
                if key not in getattr(self, '_tb_seen', set()):   # the full trace, once per kind of error
                    import traceback
                    self._tb_seen = getattr(self, '_tb_seen', set()) | {key}
                    say(traceback.format_exc())
                time.sleep(0.5)
            if self.code_changed(t0) or getattr(self, 'area_reload', False):
                raise Reload()
            time.sleep(max(0.0, period - (time.time() - t0)))

    # -- what the desk sees --
    def snapshot(self):
        with self.lock:
            b, tempo, src = getattr(self, 'clock', (0.0, 120.0, ''))
            bpb = self.state['settings'].get('beats_per_bar', 4)
            msg = self.message[0] if time.time() - self.message[1] < 4 else ''
            show = proof if self.state['calibration'].get('proof', True) else (lambda c: c)
            return dict(cols={str(ch): rgb_hex(show(c)) for ch, c in zip(self.rig.channels, self.out)},
                        calib_test=rgb_hex(self.calib_test) if self.calib_test is not None else None,
                        sync_test=self.sync_test,
                        clock=dict(beats=b, tempo=tempo, source=src, bar=int(math.floor(b / bpb)) + 1,
                                   beat=int(math.floor(b)) % bpb + 1),
                        active=self.active, fading=self.fade is not None, blackout=self.blackout,
                        hold=self.hold, bridge=self.bridge_status, guard_active=self.held > 0.3,
                        crowd=round(self.crowd, 3) if time.time() - getattr(self, 'crowd_t', -10.0) < 2.0 else None,
                        feed=(time.time() - self.feed['t'] < 1.0), picture=bool(self.feed['grid']) and (
                            time.time() - self.feed['t'] < 1.0),
                        song=self.song_view if hasattr(self, 'song_view') else None,
                        push=self.push.status if self.push else 'off', live=self.live, message=msg,
                        ableton=self.ableton.describe() if self.ableton else 'off',
                        relay=self.relay.describe() if self.relay else 'off',
                        heads=self.dmx.describe() if getattr(self, 'dmx', None) else 'off',
                        vibe=self.state['settings'].get('vibe'), energy=self.state['settings'].get('energy', 0.6),
                        palette=self.state['settings'].get('palette'),
                        intermission=bool(self.state['settings'].get('intermission')), pic_driving=bool(getattr(self, 'pic_on', False)),
                        picture_on=bool(self.state['settings'].get('movie')),
                        level=round(float(getattr(self.palette, 'music_env', 0.0) or 0.0), 3),
                        audio=self.audioshow.snapshot(),
                        live_key=(self.livekey.status if getattr(self, 'livekey', None) is not None else 'off'),
                        brain=(self.audio.brain.snapshot() if self.audio is not None and getattr(self.audio, 'brain', None)
                               is not None else 'off (install Essentia: Install Audio Brain.command)'),
                        movie=dict(on=bool(self.state['settings'].get('movie')), status=self.movie_status,
                                   src=self.state['settings'].get('movie_src', 'capture')),
                        pads=sorted(n for n, v in self.pads.voices.items() if v.t_off is None),
                        rev=getattr(self, 'rev', 0),
                        push_sel=sorted(self.push.sel) if self.push and self.push.mode == 'paint' else [])

    def full_state(self):
        with self.lock:
            return dict(rig=self.rig.describe(), segs=[dict(key=s['key'], ch=s['ch'], u=s['u'], v=s['v'],
                                                            lamp=s['lamp'], index=s['index'], of=s['of'])
                                                       for s in self.rig.segs],
                        looks=self.state['looks'], songs=self.state['songs'], live=self.live,
                        calibration=self.state['calibration'],
                        pad_colours={n: rgb_hex(proof(hub_pads.pad_info(n)[2])) for n in range(36, 100)},
                        geo_pads={n: dict(form=geo.geo_pad(n)[0], row=geo.geo_pad(n)[1],
                                          colours=[rgb_hex(proof(x)) for x in
                                                   (geo.harmony(geo.geo_pad(n)[2], geo.geo_pad(n)[3], 3)
                                                    if geo.geo_pad(n)[2] else [geo.geo_pad(n)[3]])])
                                  for n in range(36, 100)},
                        geo_forms=geo.FORMS, harmonies=geo.HARMONIES,
                        settings=self.state['settings'], motions=MOTIONS,
                        speeds=[dict(label=a, value=b) for a, b in SPEEDS], active=self.active,
                        area=self.area_name,
                        vibes=[dict(id=k, label=hub_vibes.VIBES[k]['label'], blurb=hub_vibes.VIBES[k]['blurb'],
                                    colours=hub_vibes.VIBES[k]['colours'], heads=hub_vibes.VIBES[k]['heads'])
                               for k in hub_vibes.ORDER])

    # -- commands from the desk / Push --
    def command(self, c):
        op = c.get('op')
        with self.lock:
            if op == 'go':
                return self.go(c['look'], c.get('fade'))
            if op == 'look.save':
                lk = c['look']
                lk.setdefault('id', 'look%d' % int(time.time() * 1000))
                lk.setdefault('canvas', {})
                for k, v in dict(fill='#ffffff', motion='still', speed=0.25, depth=0.5, together=0.0, level=1.0,
                                 pichits=0.0, name='New look').items():
                    lk.setdefault(k, v)
                for i, l in enumerate(self.state['looks']):
                    if l['id'] == lk['id']:
                        self.state['looks'][i] = lk
                        break
                else:
                    self.state['looks'].append(lk)
                self.save_soon()
                if self.push:
                    self.push.refresh()
                return lk['id']
            if op == 'look.duplicate':
                src = self.look(c['id'])
                if not src:
                    return False
                lk = copy.deepcopy(src)
                lk['id'] = 'look%d' % int(time.time() * 1000)
                lk['name'] = c.get('name') or (src['name'] + ' copy')
                self.state['looks'].insert(self.state['looks'].index(src) + 1, lk)
                self.save_soon()
                return lk['id']
            if op == 'look.delete':
                if len(self.state['looks']) <= 1:
                    return False
                self.state['looks'] = [l for l in self.state['looks'] if l['id'] != c['id']]
                if self.active == c['id']:
                    self.go(self.state['looks'][0]['id'])
                self.save_soon()
                return True
            if op == 'look.move':
                lk = self.look(c['id'])
                if not lk:
                    return False
                self.state['looks'].remove(lk)
                self.state['looks'].insert(int(clamp(c['to'], 0, len(self.state['looks']))), lk)
                self.save_soon()
                if self.push:
                    self.push.refresh()
                return True
            if op == 'harmony':
                lk = self.look(c['look'])
                if not lk:
                    return False
                keys = c.get('keys') or [s['key'] for s in sorted(self.rig.segs, key=lambda s: s['rank'])]
                rank = {s['key']: s['rank'] for s in self.rig.segs}
                keys = sorted(keys, key=lambda k: rank.get(k, 0))
                for k, col in zip(keys, geo.harmony(c['kind'], hex_rgb(c['base']), len(keys))):
                    lk['canvas'][k] = rgb_hex(col)
                self.save_soon()
                if self.push:
                    self.push.refresh()
                return True
            if op == 'paint':
                lk = self.look(c['look'])
                if not lk:
                    return False
                cols = c['colors'] if 'colors' in c else [c['color']] * len(c['keys'])
                for k, col in zip(c['keys'], cols):
                    lk['canvas'][k] = col
                self.save_soon()
                return True
            if op == 'crowd':                                  # Osmo movement, many times a second: not saved
                self.crowd, self.crowd_t = clamp(float(c['value']), 0, 1), time.time()
                return True
            if op == 'live':
                k = c['key']
                lim = dict(master=(0, 1), speed=(0.25, 4), smooth=(0, 1), fade=(0, 30), tint=(-180, 180),
                           sat=(0, 1.5), depth=(0, 2), guard=(0.5, 3), tempo=(40, 240),
                           p_level=(0, 1.5), p_attack=(0.005, 2), p_release=(0.02, 4), p_speed=(0.25, 4),
                           p_spread=(0, 1), p_latch=(0, 1), p_pressure=(0, 1), p_patterns=(0, 1),
                           a_amt=(0, 1), a_kick=(0, 1), a_snare=(0, 1), a_hats=(0, 1), a_follow=(0, 1),
                           a_colour=(0, 1), a_drop=(0, 1), a_move=(0, 1), a_spread=(0, 1),
                           crowd_amt=(0, 1), movie_bri=(0, 1.5), movie_speed=(0.03, 1.5), movie_sat=(0.5, 2.0),
                           **{fk: (0, 1) for fk in hub_fx.FX_KEYS}).get(k)
                if k == 'p_latch' and float(c['value']) < 0.5:
                    self.pads.release_latched(time.time())     # latch off: let the latched pad fade
                if lim is None:
                    return False
                self.live[k] = clamp(float(c['value']), *lim)
                self.save_soon()
                return True
            if op == 'vibe':                         # Light Desk > Perform: one tap = a whole auto show
                name = c.get('name', self.state['settings'].get('vibe', 'dreamy'))
                if name not in hub_vibes.VIBES:
                    return False
                e = clamp(float(c.get('energy', self.state['settings'].get('energy', 0.6))))
                st_, lv_ = hub_vibes.recipe(name, e)
                st = self.state['settings']
                old_pal = st.get('palette')
                if name == st.get('vibe'):              # same vibe, new energy: keep the Colour knob where it is
                    lv_.pop('tint', None)
                st.update(st_)
                st['vibe'], st['energy'] = name, e
                st['dmx_on'] = bool(hub_vibes.VIBES[name]['heads'])
                for k_, v_ in lv_.items():
                    self.live[k_] = v_
                self.blackout = (name == 'rest')
                if st.get('palette') != old_pal and not self.args.rehearse and not self.args.area:
                    want = self.wanted_area() or (self.cfg or {}).get('area_name')
                    if want and want != self.area_name:
                        say('Switching the lights to "%s" -- restarting the hub (a few seconds)...' % want)
                        self.area_reload = True
                self.save_soon()
                return dict(vibe=name, energy=e)
            if op == 'blackout':
                self.blackout = (not self.blackout) if c.get('on') is None else bool(c['on'])
                return self.blackout
            if op == 'hold':
                self.hold = (not self.hold) if c.get('on') is None else bool(c['on'])
                return self.hold
            if op == 'pad':                                  # the desk's Pads tab
                n = int(c['note'])
                if not (36 <= n <= 99 or 36 + hub_pads.GEO_OFFSET <= n <= 99 + hub_pads.GEO_OFFSET):
                    return False
                if c.get('on', True):
                    self.pads.note_on(int(c['note']), int(c.get('vel', 100)), time.time(), self.clock[0])
                else:
                    self.pads.note_off(int(c['note']), time.time())
                return True
            if op == 'calib':
                k = c['key']
                lim = dict(light_r=(0.3, 1), light_g=(0.3, 1), light_b=(0.3, 1), push_r=(0.2, 1), push_g=(0.2, 1),
                           push_b=(0.2, 1), push_gamma=(1, 3), push_bright=(0.2, 1), vivid=(0, 1),
                           lamp_delay=(0, 250)).get(k)
                if k in ('proof', 'held_white'):
                    self.state['calibration'][k] = bool(c['value'])
                elif lim is None:
                    return False
                else:
                    self.state['calibration'][k] = clamp(float(c['value']), *lim)
                self.save_soon()
                if self.push:
                    self.push.palette = {}
                    self.push.refresh(force=True)
                return True
            if op == 'sync.test':
                self.sync_test = bool(c.get('on', not self.sync_test))
                if not self.sync_test:
                    self.calib_test = None
                return True
            if op == 'setting':                          # desk > Setup > Ableton
                k, v = c.get('key'), c.get('value')
                kinds = dict(iac_on=bool, iac_port=str, iac_map=str, brain_on=bool, heard_on=bool, pi_url=str, key_from_live=bool, deg_root=int, deg_scale=str, deg_home=int, deg_effect=str, palette=str, sync_ch=int, sync_base=float, sync_boost=float, sync_period=float, sync_from=float, sync_to=float, sync_scheme=str, sync_attack=float, sync_release=float, sync_floor_db=float, sync_top_db=float, sync_delay=float, movie_area=str, iac_looks=bool, iac_mpe=bool,
                             audio_on=bool, audio_in=str, audio_ch=str, audio_sens=float, trig_on=bool, trig_port=str,
                             trig_map=dict, a_voices=dict, gear_clock=bool, a_pat=str, a_spat=str, a_origin=str,
                             a_phrase=int, a_style=str, a_cue=str, a_vis_bars=int,
                             movie=bool, movie_src=str,
                             relay_on=bool, relay_port=str, relay_build_bars=float, relay_diffuse=float,
                             relay_diffuse_bars=float, dmx_host=str, dmx_level=float, dmx_move=float,
                             music_ch=str, music_floor_db=float, music_top_db=float, music_attack=float,
                             music_release=float, music_base=float, music_boost=float, music_period=float,
                             music_spread=float, music_hold=bool, dmx_on=bool, dmx_strobe=str,
                             music_sat=float, music_idle=float, sync_idle=float, dmx_movie=bool, dmx_movie_level=float,
                             intermission=bool, intermission_level=float, heads_pending=dict)
                if k not in kinds or (k == 'iac_map' and v not in ('pads', 'wheel', 'degree')) or (
                        k == 'deg_scale' and not str(v).strip()) or (
                        k == 'deg_effect' and v not in ('wash', 'glow', 'hit', 'pulse', 'chase', 'sparkle', 'sweep')) or (
                        k == 'palette' and v not in hub_palette.MODES):
                    return False
                if (k == 'a_pat' and v not in hub_audioshow.KICK_PATTERNS) or (
                        k == 'a_spat' and v not in hub_audioshow.SNARE_PATTERNS) or (
                        k == 'a_phrase' and int(v) not in (2, 4, 8, 16)) or (
                        k == 'a_style' and v not in ('programmed', 'reactive')) or (
                        k == 'movie_src' and v not in ('capture', 'screen', 'camera')) or (
                        k == 'a_vis_bars' and int(v) not in (1, 2, 4, 8)) or (
                        k == 'a_cue' and v not in ['auto'] + hub_audioshow.PRO_CUES):
                    return False
                if k == 'audio_sens':
                    v = clamp(float(v), 0.4, 2.5)
                if k in ('dmx_level', 'dmx_move'):
                    v = clamp(float(v))
                if k == 'dmx_host':
                    v = str(v).strip()[:80]
                if k == 'trig_map':
                    v = {str(ch): vo for ch, vo in v.items() if vo in ('kick', 'snare', 'hats') and str(ch).isdigit()}
                if k == 'a_voices':
                    v = {vo: dict(color=str(d.get('color', 'look'))[:16], zones=d.get('zones', 'all'))
                         for vo, d in v.items() if vo in ('kick', 'snare', 'hats') and isinstance(d, dict)}
                self.state['settings'][k] = kinds[k](v)
                if k in ('palette', 'movie_area') and not self.args.rehearse and not self.args.area:
                    want = self.wanted_area() or (self.cfg or {}).get('area_name')
                    if want and want != self.area_name:
                        say('Switching the lights to "%s" -- restarting the hub (a few seconds)...' % want)
                        self.area_reload = True
                if self.audio and k in ('audio_on', 'audio_in', 'audio_ch'):
                    self.audio.close()
                    self.audio.last_try = 0.0
                if self.audio and k in ('trig_on', 'trig_port'):
                    try:
                        if self.audio.midi:
                            self.audio.midi.close()
                    except Exception:
                        pass
                    self.audio.midi = None
                    self.audio.midi_last_try = 0.0
                self.save_soon()
                if self.ableton and k in ('iac_on', 'iac_port'):
                    self.ableton.release_all()
                    self.ableton.close()
                    self.ableton.last_try = 0.0
                return True
            if op == 'calib.test':
                self.calib_test = hex_rgb(c['color']) if c.get('color') else None
                if self.push:
                    self.push.refresh(force=True)
                return True
            if op == 'pads.panic':
                self.pads.panic()
                return True
            if op == 'hit':
                self.hit_t = time.time()
                return True
            if op == 'tap':
                self.tap()
                return True
            if op == 'downbeat':
                self.downbeat()
                return True
            if op == 'lamp.blink':                       # which lamp is which: this one white, the rest dark, 4 s
                self.ident = (str(c.get('key')), time.time() + float(c.get('secs', 4.0)))
                return True
            if op == 'lamp.order':                       # desk > Setup > Set the order: lamp keys in order
                keys = [str(k) for k in (c.get('keys') or [])]
                for l in self.rig.lamps:
                    l['order'] = keys.index(l['key']) if l['key'] in keys else None
                self.rig.layout()
                self.save_soon()
                return True
            if op == 'lamp':
                for l in self.rig.lamps:
                    if l['key'] == c['key']:
                        if 'place' in c:
                            l['place'] = [clamp(float(c['place'][0])), clamp(float(c['place'][1]))]
                        if c.get('axis') in ('up', 'across'):
                            l['axis'] = c['axis']
                        if 'cap' in c:                           # brightest this lamp may go (0.05-1), e.g. near the screen
                            l['cap'] = clamp(float(c['cap']), 0.05, 1.0)
                        self.rig.layout()
                        self.save_soon()
                        return True
                return False
            if op == 'song.save':
                sg = c['song']
                sg.setdefault('id', 'song%d' % int(time.time() * 1000))
                sg.setdefault('sections', [])
                sg['sections'] = sorted(sg['sections'], key=lambda x: int(x['bar']))
                for i, s in enumerate(self.state['songs']):
                    if s['id'] == sg['id']:
                        self.state['songs'][i] = sg
                        break
                else:
                    self.state['songs'].append(sg)
                self.save_soon()
                return sg['id']
            if op == 'song.delete':
                self.state['songs'] = [s for s in self.state['songs'] if s['id'] != c['id']]
                if self.song and self.song['id'] == c['id']:
                    self.song = None
                self.save_soon()
                return True
            if op == 'song.start':
                return self.song_start(c['id'], c.get('when', 'next'), int(c.get('section', 0)))
            if op == 'song.stop':
                self.song = None
                return True
            if op == 'song.jump':
                if not self.song:
                    return False
                return self.song_start(self.song['id'], 'next', int(c['section']))
            if op == 'connect':
                self.disconnect()
                self.last_connect = 0.0
                self.reconnect_soon(time.time())
                return 'connecting...'
        return False


# ---- TouchDesigner feed: the picture and the beat ----------------------------------------------------
def feed_listener(hub, port):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(('127.0.0.1', port))
    owner, seen, warned = None, set(), 0.0
    while True:
        data, addr = rx.recvfrom(65535)
        try:
            msg = json.loads(data.decode())
        except ValueError:
            continue
        now = time.time()
        f = hub.feed
        if addr not in seen:
            seen.add(addr)
            if owner is not None:
                say('  A new TouchDesigner feed appeared (port %d) -- following it now.' % addr[1])
            owner = addr
        elif addr != owner:
            if now - f['t'] < 1.0:
                if now - warned > 10:
                    say('  NOTE: two TouchDesigner projects are feeding the hub -- following the newest.')
                    warned = now
                continue
            owner = addr
        with hub.lock:
            if 'beats' in msg and msg['beats'] is not None:
                f['beats'] = float(msg['beats'])
                f['tempo'] = float(msg.get('tempo') or 120.0)
                f['source'] = msg.get('source', 'TouchDesigner')
            else:
                f['beats'] = None
            if msg.get('grid'):
                f['grid'], f['gw'], f['gh'] = msg['grid'], int(msg['w']), int(msg['h'])
            else:
                f['grid'] = None
            if isinstance(msg.get('vj'), dict):         # the VJ board's state, for the Zephyrus relay (optional)
                f['vj'], f['vj_t'] = msg['vj'], now
            f['t'] = now


# ---- the desk (web) ----------------------------------------------------------------------------------
def make_handler(hub):
    class Desk(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype='application/json'):
            b = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(b)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b)

        # -- who may use the desk: this Mac always; a phone / other computer once it has the key --
        def _allowed(self):
            ip = self.client_address[0]
            if ip in ('127.0.0.1', '::1') or ip.startswith('::ffff:127.'):
                return True
            try:
                with open(TOKEN_PATH) as f:
                    key = f.read().strip()
            except OSError:
                return False
            if not key:
                return False
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get('key', [''])[0] == key:
                self._set_cookie = 'ney_key=%s; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly' % key
                return True
            for part in (self.headers.get('Cookie') or '').split(';'):
                k_, _, v_ = part.strip().partition('=')
                if k_ == 'ney_key' and v_ == key:
                    return True
            return False

        def end_headers(self):
            ck = getattr(self, '_set_cookie', None)
            if ck:
                self.send_header('Set-Cookie', ck)
                self._set_cookie = None
            BaseHTTPRequestHandler.end_headers(self)

        def _proxy_heads(self, method):
            """/heads/... -> the DMX node on the Zephyrus, so the Light Desk (and your phone) only talk to the hub."""
            hst = str(hub.state['settings'].get('dmx_host', '') or '').strip()
            if not hst:
                return self._send(503, json.dumps({'error': 'no dmx_host set'}))
            sub = self.path[len('/heads'):] or '/'
            import urllib.request
            try:
                data = None
                if method == 'POST':
                    n = min(int(self.headers.get('Content-Length', 0) or 0), 20000)
                    data = self.rfile.read(n)
                ip_ = getattr(getattr(hub, 'dmx', None), 'ip', None) or hst      # IPv4: the bare name stalls ~3 s on IPv6
                rq = urllib.request.Request('http://%s:7060%s' % (ip_, sub), data=data, method=method,
                                            headers={'Content-Type': 'text/plain'})
                with urllib.request.urlopen(rq, timeout=3) as r:
                    return self._send(r.status, r.read(), r.headers.get('Content-Type', 'application/json'))
            except Exception as e:
                return self._send(502, json.dumps({'error': 'DMX node not reachable (%s)' % e.__class__.__name__}))

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if not self._allowed():
                return self._send(403, 'This desk needs its key: open the link with ?key=... once (ask Claude).', 'text/plain')
            if path.startswith('/heads/'):
                return self._proxy_heads('GET')
            if path == '/api/phone':                # the phone link (with the key) -- only shown on this Mac
                ip = self.client_address[0]
                if not (ip in ('127.0.0.1', '::1') or ip.startswith('::ffff:127.')):
                    return self._send(403, '{}')
                name = 'neystalgic'
                try:
                    import subprocess
                    out = subprocess.run(['/Applications/Tailscale.app/Contents/MacOS/Tailscale', 'status', '--json'],
                                         capture_output=True, text=True, timeout=3).stdout
                    name = (json.loads(out).get('Self', {}).get('DNSName', '') or name).split('.')[0] or name
                except Exception:
                    pass
                try:
                    with open(TOKEN_PATH) as f:
                        key = f.read().strip()
                except OSError:
                    return self._send(200, '{}')
                return self._send(200, json.dumps({'url': 'http://%s:%d/?key=%s' % (name, self.server.server_address[1], key)}))
            if path in ('/', '/desk', '/index.html', '/classic'):
                fp = DESK_PATH if path == '/classic' or not os.path.exists(LIGHT_DESK_PATH) else LIGHT_DESK_PATH
                try:
                    with open(fp, 'rb') as f:
                        return self._send(200, f.read(), 'text/html; charset=utf-8')
                except OSError:
                    return self._send(500, 'the desk page is missing next to hue_hub.py', 'text/plain')
            if path == '/api/state':
                return self._send(200, json.dumps(hub.full_state()))
            if path == '/api/live':
                return self._send(200, json.dumps(hub.snapshot()))
            if path == '/api/stream':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                try:
                    while True:
                        self.wfile.write(('data: %s\n\n' % json.dumps(hub.snapshot())).encode())
                        self.wfile.flush()
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            self._send(404, 'not found', 'text/plain')

        def do_POST(self):
            if not self._allowed():
                return self._send(403, 'not allowed', 'text/plain')
            if urllib.parse.urlparse(self.path).path.startswith('/heads/'):
                return self._proxy_heads('POST')
            if urllib.parse.urlparse(self.path).path != '/api':
                return self._send(404, 'not found', 'text/plain')
            try:
                n = int(self.headers.get('Content-Length', 0))
                c = json.loads(self.rfile.read(n) or b'{}')
                res = hub.command(c)
                return self._send(200, json.dumps({'ok': True, 'result': res}))
            except Exception as e:
                return self._send(400, json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}))

    return Desk


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()



# the hub restarts itself when its code is updated (no more running yesterday's version by mistake)
CODE_FILES = ['hue_hub.py', 'hue_stream.py', 'hub_pads.py', 'hub_push2.py', 'hub_visuals.py', 'hub_geometry.py',
              'hub_livemidi.py', 'hub_audio.py', 'hub_audioshow.py', 'hub_brain.py', 'hub_liveosc.py', 'hub_fx.py',
              'hub_palette.py', 'hub_gradlamp.py', 'hub_relay.py', 'hub_dmx.py', 'hub_vibes.py']


class Reload(Exception):
    pass


def code_stamp():
    here = os.path.dirname(os.path.abspath(__file__))
    out = {}
    for f in CODE_FILES:
        try:
            out[f] = os.path.getmtime(os.path.join(here, f))
        except OSError:
            pass
    return out


def main():
    import signal
    try:                                        # Ctrl+C always stops the hub (also after it restarted itself)
        signal.signal(signal.SIGINT, signal.default_int_handler)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Botanica Hue Hub')
    ap.add_argument('--rehearse', action='store_true', help='no bulbs: run the desk and preview only')
    ap.add_argument('--phone', action='store_true', help='also open the desk to phones on your Wi-Fi')
    ap.add_argument('--ip')
    ap.add_argument('--area')
    ap.add_argument('--no-push', action='store_true', help='do not look for Push 2')
    ap.add_argument('--desk-port', type=int, default=DESK_PORT)
    ap.add_argument('--feed-port', type=int, default=FEED_PORT)
    args = ap.parse_args()

    host = '0.0.0.0'                           # other devices need the desk key (rig_control.token) -- see _allowed
    running = False
    for _ in range(5):                         # is another hub answering? (a just-stopped one may need a moment)
        try:
            socket.create_connection(('127.0.0.1', args.desk_port), timeout=0.3).close()
            running = True
            time.sleep(1.0)
        except OSError:
            running = False
            break
    if running:
        say('The Hue Hub is already running (the desk port %d is taken).' % args.desk_port)
        say('Use that one -- or close its Terminal window first. Open the desk: http://localhost:%d'
            % args.desk_port)
        sys.exit(1)
    hub = Hub(args)
    say('Hue Hub: %d lamps, %d colour zones%s' % (len(hub.rig.lamps), len(hub.rig.channels),
                                                  (' in "%s"' % hub.area_name) if hub.area_name else ''))
    for l in hub.rig.lamps:
        k = len(l['channels'])
        say('   %-28s %s' % (l['key'], '%d zones' % k if k > 1 else ('1 zone (can do %d -- run: python3 hue_stream.py scan)'
                                                                    % l['capable'] if l['capable'] > 1 else '1 zone')))
    hub.connect()
    if hub.streamer is None:
        say('Lights: %s' % hub.bridge_status)
    if not args.no_push:
        try:
            import hub_push2
            hub.push = hub_push2.Push2(hub)
            say('Push 2: %s' % hub.push.status)
        except ImportError as e:
            say('Push 2: off (%s)' % e)
        try:
            import hub_livemidi
            hub.ableton = hub_livemidi.LiveMidi(hub)
            say('Ableton (IAC Driver): %s' % hub.ableton.status)
            import hub_liveosc
            hub.livekey = hub_liveosc.LiveKey(hub)        # the key + scale come from Live (AbletonOSC)
        except ImportError as e:
            say('Ableton (IAC Driver): off (%s)' % e)
    import hub_audio                           # the gear listens whether or not the Push is in use
    hub.audio = hub_audio.AudioIn(hub)
    say('Audio (the gear): %s' % hub.audio.status)
    try:                                       # the show's MIDI out to the Zephyrus (network session "Show")
        import hub_relay
        hub.relay = hub_relay.Relay(hub)
        say('Zephyrus relay: %s' % hub.relay.status)
    except ImportError as e:
        say('Zephyrus relay: off (%s)' % e)
    threading.Thread(target=feed_listener, args=(hub, args.feed_port), daemon=True).start()
    httpd = ThreadingHTTPServer((host, args.desk_port), make_handler(hub))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    say('Light Desk:  http://localhost:%d' % args.desk_port)
    if args.phone:
        ip = lan_ip()
        if ip:
            say('On your phone (same Wi-Fi):  http://%s:%d' % (ip, args.desk_port))
    say('TouchDesigner feed: listening on 127.0.0.1:%d.  Ctrl+C stops (lights go back to normal).' % args.feed_port)
    reload = False
    try:
        hub.run()
    except KeyboardInterrupt:
        say('\nStopping ...')
    except Reload:
        reload = True
        say('\nNew code in the Hue Rig folder -- restarting the hub with it (a few seconds) ...')
    finally:
        try:
            hub.save_now()
        except Exception:
            pass
        if hub.push:
            hub.push.close()
        def _close_parts():
            for part in (hub.relay, hub.ableton, hub.audio):
                try:
                    if part is not None:
                        part.close()
                        if getattr(part, 'midi', None) is not None:
                            part.midi.close()
                except Exception:
                    pass
        t_p = threading.Thread(target=_close_parts, daemon=True)  # MIDI / audio drivers can stall on close
        t_p.start()
        t_p.join(3.0)
        hub.disconnect()
        if not reload:
            say('Stopped. Everything is saved in hub_state.json.')
    if reload:                                          # same Terminal window, same settings, the new code
        def _close_desk():
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        t_ = threading.Thread(target=_close_desk, daemon=True)   # never let an open desk page hold the restart up
        t_.start()
        t_.join(2.0)
        time.sleep(3.0)                                 # give the bridge a moment to let go
        # a completely fresh process (macOS's MIDI and audio don't always reopen cleanly inside the same
        # one); it writes to this same Terminal window, and Ctrl+C still stops it
        import subprocess
        sys.stdout.flush()
        subprocess.Popen([sys.executable, '-u', os.path.abspath(__file__)] + sys.argv[1:],
                         cwd=os.path.dirname(os.path.abspath(__file__)))
        os._exit(0)


if __name__ == '__main__':
    main()
