#!/usr/bin/env python3
# =============================================================================
# TAP DIAL v4 -- Michael's exact layout (Nov 16, late):
#   1  tap     HUE COLOUR  every lamp, in sync: red, orange, yellow, blue, green, violet, indigo, pink, (round again)
#      double              rainbow: every lamp fading through the rainbow in sync
#   2  tap     HEADS       (only while the heads are on) next heads-only mode: glow, lamp colour, rainbow, sweep
#      double              heads plugs ON (starts on glow) / OFF
#   3  tap     SPOTS       (only while the spots are on) next spot mode: UV on the tapestry first, then the gobos
#      double              spot plugs ON (starts on UV tapestry) / OFF
#   4  tap     SHOW        light show: first tap = auto, then lock wave, loop, call, pulse, split, orbit, relay, auto
#      double              back to normal: lamps purple, heads + spots off
#   DIAL                   volume of the FILL MONITOR only (MIDI CC 104 ch16 -> map it to the fill track's volume
#                          in Ableton once). Nothing else.
# Heads, spots and lamps are independent: heads + spots run from this module's own DMX layers (no Hue Hub), so
# changing one never touches the others. Only the show (button 4) uses the hub. Buttons never speak.
# Setup in the Hue app: leave every button + the dial with NO action. Log: bridge/outbox/tap_dial.txt
# =============================================================================
import colorsys, json, math, os, queue, socket, threading, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'tap_switch.json')
DIAL_FILE = os.path.join(HERE, 'dial.json')          # ambient_fade.py reads it (intensity 0-1)
LOG = os.path.join(HERE, 'bridge', 'outbox', 'tap_dial.txt')

HUE_COLOURS = [('red', (255, 0, 0)), ('orange', (255, 90, 0)), ('yellow', (255, 210, 0)), ('blue', (0, 110, 255)),
               ('green', (0, 255, 30)), ('violet', (170, 0, 255)), ('indigo', (60, 0, 255)), ('pink', (255, 30, 150))]
HEAD_MODES = ['glow', 'colour', 'rainbow', 'sweep']
SPOT_MODES = ['uv', 'uvscan', 'gobo16', 'gobo32', 'gobo48', 'gobo64', 'gobo80', 'gobo96']
STATE_FILE = os.path.join(HERE, 'tap_state.json')    # remembers the fill volume (not secret)
FILL_CC = 104                                         # MIDI CC on channel 16 -> the fill track's volume in Ableton
SHOW_MODES = ['auto', 'wave', 'loop', 'call', 'pulse', 'split', 'orbit', 'relay']
DEFAULTS = {'enabled': True, 'device_id': None, 'show_modes': SHOW_MODES, 'rainbow_s': 60,
            'double_window': 0.45,     # seconds between the two presses of a double tap (bridge timestamps)
            'settle': 0.2,             # after a release arrives, wait this long for a 2nd press (the bridge sends
                                       # the release + any 2nd press together, ~0.9 s after the first press)
            'fill_step': 0.3,          # fill volume (MIDI 0-127) per dial step
            'fill_start': 100}

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
             'uvscan': dict(uv=True, gobo=0, focus=128, breathe=0, aim=UV_TAPESTRY, scan=True)}
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
         'lamp_rgb': (110, 0, 255), 'lamp_rainbow': False,
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

    def __init__(self, window=0.45, settle=0.45):
        self.window, self.settle, self.p = window, settle, {}

    def event(self, n, ev, ts, now):
        out = []
        p = self.p.get(n)
        if ev == 'initial_press':
            if p and not p['held'] and not p.get('spent') and ts is not None and p['ts'] is not None \
                    and 0 <= ts - p['ts'] <= self.window:
                out.append(('double', n))
                self.p[n] = dict(ts=None, rel=None, held=False, spent=True, born=now)
            else:
                self.p[n] = dict(ts=ts, rel=None, held=False, spent=False, born=now)
        elif ev in ('long_press', 'repeat'):
            if p:
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
            if p['rel'] is not None and now - p['rel'] >= self.settle:
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
        if kind == 'double':
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
def _hue_rgb(deg):
    r, g, b = colorsys.hsv_to_rgb((deg % 360.0) / 360.0, 1.0, 1.0)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


HEAD_PERIOD = {'glow': 90.0, 'colour': 60.0, 'rainbow': 60.0, 'sweep': 24.0}   # seconds for one full sweep
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
                p16, tilt = roam(h, t, SPOT_PERIOD, 0.0, 240.0)
            foc = L['focus'] + L['breathe'] * math.sin(2 * math.pi * t / 16.0)
            data[a], data[a + 1], data[a + 2], data[a + 3] = p16 >> 8, p16 & 255, tilt >> 8, tilt & 255
            data[a + 4] = SLOT_VIOLET if math.sin(2 * math.pi * t / 120.0) >= 0 else SLOT_PINK
            data[a + 5] = L['gobo']
            data[a + 7] = int(max(0, min(255, foc)))
            if L['uv']:
                uv = int(round(255 * inten))
                data[a + 10], data[a + 11] = (12, uv) if uv else (0, 0)
            else:
                m = int(round(255 * 0.85 * inten))
                data[a + 8], data[a + 9] = (12, m) if m else (0, 0)
            data[a + 15] = int(h.get('motor_speed', 0))
        else:
            if hmode not in HEAD_MODES or a < 0 or a + 14 > 512:
                continue
            pan, tilt = roam(h, t, HEAD_PERIOD[hmode], 0.0 if hmode == 'sweep' else i / 4.0, 180.0)
            data[a], data[a + 1], data[a + 2], data[a + 3] = pan >> 8, pan & 255, tilt >> 8, tilt & 255
            data[a + 4] = int(h.get('motor_speed', 0))
            lvl = {'glow': 0.35, 'colour': 0.5, 'rainbow': 0.5, 'sweep': 0.45}[hmode] * inten
            data[a + 5] = int(round(mmin + lvl * (mmax - mmin))) if inten > 0.01 else 0
            if hmode == 'colour':
                rgb = lamp_rgb
            elif hmode == 'rainbow':
                rgb = _hue_rgb(360.0 * t / 60.0)                      # all four heads the same colour, in sync
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
        want = lay.get('heads') in HEAD_MODES or lay.get('spots') in SPOT_LOOK
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
            lay2 = dict(lay, lamp_rgb=STATE['lamp_rgb'], lamp_rainbow=STATE['lamp_rainbow'], rainbow_s=settings()['rainbow_s']) \
                if lay.get('heads') == 'colour' else lay
            data = frame(cfg['heads'], lay2, now - t0, 1.0, tg, hd.MASTER_MIN, hd.MASTER_MAX)
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
    m.stop_ambient()
    if _hub_alive():
        m.stop_hub()                                   # the show held the lamps; heads/spots layers carry on
        if STATE['layers'].get('heads') == 'hub':
            STATE['layers']['heads'] = None
        STATE['idx'][4] = -1


def lamp_colour(name, rgb):
    m = rc()
    _lamps_free()
    x, y = _hs().rgb_to_xyb(*[v / 255.0 for v in rgb])[:2]
    _lamps_parallel(m, {'on': {'on': True}, 'dimming': {'brightness': 100.0}, 'color': {'xy': {'x': x, 'y': y}},
                        'dynamics': {'duration': 400}})
    STATE['lamp_rgb'], STATE['lamp_rainbow'] = rgb, False
    _mark('tap_colour_' + name)


def lamp_rainbow():
    m = rc()
    _lamps_free()
    m.start_ambient(100, int(settings()['rainbow_s']), 0)    # every lamp the same colour, rainbow order, in sync
    STATE['lamp_rainbow'] = True
    _mark('tap_rainbow')


def heads_toggle():
    m = rc()
    hp = m.head_power
    if _plugs_on(hp):
        STATE['layers']['heads'] = None
        STATE['idx'][2] = -1
        hp.request_off(why='tap dial')
        STATE['heads_off_at'] = _now()
        return 'heads OFF'
    hp.request_on(quiet=True)                          # the node fades them in after their reset sweep
    STATE['heads_off_at'] = 0.0
    STATE['idx'][2] = 0
    STATE['layers']['heads'] = HEAD_MODES[0]
    return 'heads ON (glow)'


def spots_toggle():
    m = rc()
    sp = m.spot_power
    if _plugs_on(sp):
        STATE['layers']['spots'] = None
        STATE['idx'][3] = -1
        if _hub_alive():
            m.hub_setting('spot_fx', {})
        sp.request_off(why='tap dial')
        STATE['spots_off_at'] = _now()
        try:                                           # stay off: no auto power-on until a double tap turns them on
            sp.STATE['hold_until'] = sp._now() + sp.settings()['manual_hold_min'] * 60
        except Exception:
            pass
        return 'spots OFF'
    try:
        sp.STATE['hold_until'] = 0.0
    except Exception:
        pass
    sp.request_on(quiet=True, why='tap dial')
    STATE['spots_off_at'] = 0.0
    STATE['idx'][3] = 0
    _spots_to(SPOT_MODES[0])
    return 'spots ON (UV tapestry)'


def _spots_to(mode):
    STATE['layers']['spots'] = mode
    if _hub_alive():
        rc().hub_setting('spot_fx', SPOT_FX[mode])


def show_on():
    m = rc()
    STATE['layers']['heads'] = 'hub' if STATE['layers'].get('heads') else None
    _apply('modes')
    sp = STATE['layers'].get('spots')
    m.hub_setting('spot_fx', SPOT_FX[sp] if sp in SPOT_FX else {})


def back_to_purple():
    m = rc()
    STATE['layers'].update(heads=None, spots=None)
    STATE['lamp_rgb'], STATE['lamp_rainbow'] = (110, 0, 255), False
    _apply('purple')
    m.head_power.request_off(why='tap dial purple')
    try:
        m.spot_power.request_off(why='tap dial purple')
    except Exception:
        pass


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
    s = s or settings()
    m = rc()
    if n == 1:
        name, rgb = HUE_COLOURS[_next(1, len(HUE_COLOURS), skips)]
        lamp_colour(name, rgb)
        return 'lamps ' + name
    if n == 2:
        if not _plugs_on(m.head_power) or _now() - STATE.get('heads_off_at', 0.0) < 15.0:
            return 'heads are off (double tap 2 turns them on)'
        mode = HEAD_MODES[_next(2, len(HEAD_MODES), skips)]
        STATE['layers']['heads'] = mode
        if _hub_alive() and m.STATE.get('look') == 'modes':
            _lamps_free()                                  # heads leave the show for their own mode
        return 'heads ' + mode
    if n == 3:
        if not _plugs_on(m.spot_power) or _now() - STATE.get('spots_off_at', 0.0) < 15.0:
            return 'spots are off (double tap 3 turns them on)'
        mode = SPOT_MODES[_next(3, len(SPOT_MODES), skips)]
        _spots_to(mode)
        return 'spots ' + mode
    if n == 4:
        lst = s.get('show_modes') or SHOW_MODES
        if STATE['idx'][4] < 0 or m.STATE.get('look') != 'modes' or not _hub_alive():
            STATE['idx'][4] = skips % len(lst)
            show_on()
            mode = lst[STATE['idx'][4]]
            if mode != 'auto':
                m.hub_setting('show_lock', mode)
            return 'show ' + mode
        mode = lst[_next(4, len(lst), skips)]
        m.hub_setting('show_lock', '' if mode == 'auto' else mode)
        return 'show ' + mode
    return None


def double(n):
    if n == 1:
        lamp_rainbow()
        return 'lamps rainbow fade'
    if n == 2:
        return heads_toggle()
    if n == 3:
        return spots_toggle()
    if n == 4:
        STATE['idx'].update({1: -1, 2: -1, 3: -1, 4: -1})
        back_to_purple()
        return 'back to normal (purple, heads + spots off)'
    return None


# ---------------------------------------------------------------- dial = fill monitor volume
def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(d):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(d, f)
    except OSError:
        pass


def turn(steps, s=None):
    """Dial -> the fill monitor's volume: MIDI CC 104 (0-127) on channel 16 over the IAC bus to Ableton."""
    s = s or settings()
    if STATE['fill'] is None:
        STATE['fill'] = float(_load_state().get('fill', s['fill_start']))
    v = max(0.0, min(127.0, STATE['fill'] + steps * float(s['fill_step'])))
    if int(round(v)) == int(round(STATE['fill'])):
        STATE['fill'] = v
        return None
    STATE['fill'] = v
    _save_state(dict(_load_state(), fill=round(v, 1)))
    try:
        rc()._cc(FILL_CC, int(round(v)), 'fill volume')
    except Exception as e:
        log('fill volume: %s' % e.__class__.__name__)
        return None
    return int(round(v))


def look_watch():
    """A look from anywhere else (Jarvis, console, schedule): the tap layers stand down."""
    m = rc()
    look = m.STATE.get('look')
    if STATE['applying'] or look == STATE['seen_look']:
        return False
    STATE['seen_look'] = look
    if STATE['layers'].get('heads') or STATE['layers'].get('spots'):
        STATE['layers'].update(heads=None, spots=None)
        STATE['idx'].update({2: -1, 3: -1, 4: -1})
        log('look "%s" from elsewhere -- tap layers off' % look)
        return True
    return False


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
                what = aim_button(n, kind, am) if am else (single(n, skips) if kind == 'single' else double(n))
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
    g = Gestures(float(s['double_window']), float(s['settle']))
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
                    DIALQ['acc'] += e[2] if e[1] == 'clock_wise' else -e[2]
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
    for f in (worker, dial_worker, sender):
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
