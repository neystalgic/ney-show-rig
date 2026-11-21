#!/usr/bin/env python3
# =============================================================================
# TAP DIAL v3 (Nov 17, after Michael's first try: "too slow, wrong looks, double taps misfire, dial off").
#   1  tap     HUE     next Hue-lamp look (purple, rainbow, rainbow room, upbeat, movie glow, red glow, slow breathing)
#                      -- only the lamps change; heads/spots glow modes keep going
#      double          purple
#   2  tap     HEADS   glow (slow purple drift, instant) -> dance (to the music) -> relay (one at a time)
#      double          heads park + power off
#   3  tap     SPOTS   UV -> gobo -> soft colour wash, all on the CEILING (never eye level), instant
#      double          spots off (plugs off, held off 30 min unless a spot mode is picked again)
#   4  tap     SHOW    first tap = the light show on auto, then each tap locks the next mode (wave, loop, call,
#                      pulse, split, orbit, relay), then back to auto
#      double          back to regular purple: lamps purple, heads + spots off, dial back to full
#   DIAL               brightness of everything that's on (show master / lamps / heads + spots glow)
#
# v3 changes: the glow + ceiling modes no longer start the Hue Hub (that was the 30-90 s wait) -- this module
# sends the heads/spots their DMX itself (LAYERS, Art-Net to the node, which still enforces every safety limit),
# and only the music modes (dance, relay, show) use the hub, started WITHOUT a light-area switch (the old 'chill'
# vibe forced a hub restart). Presses that pile up while something slow runs collapse into one. The dial has its
# own thread (it used to stall the buttons) and moves twice as far per turn. Log: bridge/outbox/tap_dial.txt
# Setup in the Hue app: leave every button + the dial with NO action.
# =============================================================================
import colorsys, json, math, os, queue, socket, threading, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'tap_switch.json')
DIAL_FILE = os.path.join(HERE, 'dial.json')          # ambient_fade.py reads it (intensity 0-1)
LOG = os.path.join(HERE, 'bridge', 'outbox', 'tap_dial.txt')

HUE_LOOKS = ['purple', 'rainbow', 'rainbowroom', 'upbeat', 'movieglow', 'redglow', 'breathe_slow']
HEAD_MODES = ['glow', 'dance', 'relay']
SPOT_MODES = ['uv', 'gobo', 'wash']
SHOW_MODES = ['auto', 'wave', 'loop', 'call', 'pulse', 'split', 'orbit', 'relay']
DEFAULTS = {'enabled': True, 'device_id': None, 'hue_looks': HUE_LOOKS, 'show_modes': SHOW_MODES,
            'double_window': 0.45,     # seconds between the two presses of a double tap (bridge timestamps)
            'settle': 0.2,             # after a release arrives, wait this long for a 2nd press (the bridge sends
                                       # the release + any 2nd press together, ~0.9 s after the first press)
            'dial_step': 0.004,        # intensity per dial step
            'dial_min': 0.05}

# Ceiling aims per spot (az = the spot's own pan angle, lean = degrees from straight up). Picked clear of each
# spot's avoid zones and walls in the node config; the node clamps anything else anyway.
SPOT_AIM = {4: {'az': 90.0, 'lean': 22.0, 'drift': 12.0, 'drift_s': 45.0},
            5: {'az': 200.0, 'lean': 22.0, 'drift': 12.0, 'drift_s': 50.0}}
SLOT_VIOLET, SLOT_PINK = 97, 82                       # Focus Spot colour wheel (nearest to purple)
SPOT_LOOK = {'uv': dict(uv=True, gobo=0, focus=128, breathe=0),
             'gobo': dict(uv=False, gobo=48, focus=150, breathe=60),
             'wash': dict(uv=False, gobo=0, focus=40, breathe=30)}


def _hub_fx(name):
    """The same ceiling look as hub spot_fx (used while the hub runs: dance / relay / show)."""
    L = SPOT_LOOK[name]
    fx = dict(hold=dict(SPOT_AIM[4]), hold_when='always', hold_head=4, level=1.0, gobo=L['gobo'], focus=L['focus'],
              breathe=L['breathe'], breathe_s=16, color=SLOT_VIOLET)
    if L['uv']:
        fx.update(uv=1.0, uv_only=True, uv_steady=True)
    fx['per_head'] = {'5': dict(hold=dict(SPOT_AIM[5]), hold_head=5)}
    return fx


SPOT_FX = {k: _hub_fx(k) for k in SPOT_MODES}

STATE = {'device': None, 'last': 'dormant: no Tap Dial found yet', 'source': None, 'intensity': 1.0,
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


def frame(heads, layers, t, inten, targets, mmin=8, mmax=134):
    """One DMX universe (bytearray 512) for the layers. heads = node config list; targets = 'Coffee table' aims.
    Heads not in a layer stay at 0 (dark). Pure: tested on its own."""
    data = bytearray(512)
    inten = max(0.0, min(1.0, inten))
    hue = 274.0 + 10.0 * math.sin(2 * math.pi * t / 240.0)          # violet -> purple (264-284 deg), slow drift
    for i, h in enumerate(heads):
        a = int(h.get('addr', 0)) - 1
        if h.get('type') == 'focus17':
            mode = layers.get('spots')
            if mode not in SPOT_LOOK or a < 0 or a + 17 > 512 or i not in SPOT_AIM:
                continue
            L, aim = SPOT_LOOK[mode], SPOT_AIM[i]
            az = aim['az'] + aim['drift'] * math.sin(2 * math.pi * t / aim['drift_s'])
            p16 = int(max(int(h.get('pan_min', 0)), min(int(h.get('pan_max', 65535)), az / 540.0 * 65535.0)))
            lean = min(aim['lean'], float(h.get('tilt_max_deg', 30.0)))
            tilt = int(max(0, min(65535, int(h.get('tilt_up', 32768)) + int(h.get('tilt_dir', 1)) * lean / 240.0 * 65535.0)))
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
            if layers.get('heads') != 'glow' or a < 0 or a + 14 > 512:
                continue
            tt = targets.get(str(i))
            if not tt:
                continue
            pan = int(tt['pan'] + 12.0 / 540.0 * 65535.0 * math.sin(2 * math.pi * (t / 150.0 + i / 4.0)))
            pan = max(int(h.get('pan_min', 0)), min(int(h.get('pan_max', 65535)), pan))
            tilt = int(tt['tilt'])
            data[a], data[a + 1], data[a + 2], data[a + 3] = pan >> 8, pan & 255, tilt >> 8, tilt & 255
            data[a + 4] = int(h.get('motor_speed', 0))
            data[a + 5] = int(round(mmin + 0.35 * inten * (mmax - mmin))) if inten > 0.01 else 0
            data[a + 6], data[a + 7], data[a + 8] = _hue_rgb(hue + 4 * i)
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
        want = lay.get('heads') == 'glow' or lay.get('spots') in SPOT_LOOK
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
            data = frame(cfg['heads'], lay, now - t0, STATE['intensity'], tg, hd.MASTER_MIN, hd.MASTER_MAX)
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


def music_hub():
    """Dance / relay: the hub, started on the music palette (no light-area switch = no restart)."""
    m = rc()
    if not _hub_alive():
        m.stop_ambient()
        m.start_hub('music')
        m.hub_vibe('dreamy', 0.5)
    m.hub_setting('dmx_strobe', 'off')
    m.hub_setting('dmx_on', True)
    sp = STATE['layers'].get('spots')
    m.hub_setting('spot_fx', SPOT_FX[sp] if sp in SPOT_FX else {})


def heads_on():
    try:
        hp = rc().head_power
        on = hp.STATE.get('on') or {}
        if not (on and all(on.values())):
            hp.request_on(quiet=True)                 # the node fades them in after their reset sweep
    except Exception as e:
        log('head power: %s' % e.__class__.__name__)


def spots_on(why):
    try:
        rc().spot_power.request_on(quiet=True, why=why)
    except Exception as e:
        log('spot power: %s' % e.__class__.__name__)


def heads_mode(mode):
    m = rc()
    heads_on()
    if mode == 'glow':
        if _hub_alive():
            _apply('purple')                          # leave the music show: lamps purple, hub off
        STATE['layers']['heads'] = 'glow'
        _mark('tap_heads_glow')
        return
    STATE['layers']['heads'] = 'hub'
    music_hub()
    m.hub_setting('dmx_pattern', 'normal' if mode == 'dance' else 'show')
    _mark('tap_heads_' + mode)


def heads_off():
    STATE['layers']['heads'] = None
    rc().head_power.request_off(why='tap dial')


def spots_mode(mode):
    STATE['layers']['spots'] = mode
    spots_on('tap ' + mode)
    if _hub_alive():
        rc().hub_setting('spot_fx', SPOT_FX[mode])
    _mark('tap_spots_' + mode)


def spots_off():
    m = rc()
    STATE['layers']['spots'] = None
    if _hub_alive():
        m.hub_setting('spot_fx', {})
    sp = m.spot_power
    sp.request_off(why='tap dial')
    try:
        sp.STATE['hold_until'] = sp._now() + sp.settings()['manual_hold_min'] * 60
    except Exception:
        pass


def show_on():
    m = rc()
    STATE['layers']['heads'] = 'hub'
    _apply('modes')
    sp = STATE['layers'].get('spots')
    m.hub_setting('spot_fx', SPOT_FX[sp] if sp in SPOT_FX else {})


def back_to_purple():
    m = rc()
    if _hub_alive():
        try:
            m.hub_api({'op': 'live', 'key': 'master', 'value': 1.0})
        except Exception:
            pass
    STATE['intensity'] = 1.0
    STATE['layers'].update(heads=None, spots=None)
    _write_dial(1.0)
    _apply('purple')
    m.head_power.request_off(why='tap dial purple')
    try:
        m.spot_power.request_off(why='tap dial purple')
    except Exception:
        pass


def _next(n, size, skips=0):
    STATE['idx'][n] = (STATE['idx'][n] + 1 + skips) % size
    return STATE['idx'][n]


def single(n, skips=0, s=None):
    s = s or settings()
    m = rc()
    if n == 1:
        lst = s.get('hue_looks') or HUE_LOOKS
        look = lst[_next(1, len(lst), skips)]
        if look == m.STATE.get('look') and len(lst) > 1:
            look = lst[_next(1, len(lst))]
        if STATE['layers'].get('heads') == 'hub':
            STATE['layers']['heads'] = None           # the lamp look stops the music show; glow modes keep going
            STATE['idx'][2] = -1
        STATE['idx'][4] = -1
        _apply(look)
        return look
    if n == 2:
        mode = HEAD_MODES[_next(2, len(HEAD_MODES), skips)]
        STATE['idx'][4] = -1
        heads_mode(mode)
        return 'heads ' + mode
    if n == 3:
        mode = SPOT_MODES[_next(3, len(SPOT_MODES), skips)]
        spots_mode(mode)
        return 'spots ' + mode
    if n == 4:
        lst = s.get('show_modes') or SHOW_MODES
        if STATE['idx'][4] < 0 or m.STATE.get('look') != 'modes' or not _hub_alive():
            STATE['idx'][4] = skips % len(lst)
            STATE['idx'][2] = -1
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
        STATE['idx'][1] = 0
        if STATE['layers'].get('heads') == 'hub':
            STATE['layers']['heads'] = None
        STATE['idx'][4] = -1
        _apply('purple')
        return 'purple'
    if n == 2:
        STATE['idx'][2] = -1
        heads_off()
        _mark('tap_heads_off')
        return 'heads off'
    if n == 3:
        STATE['idx'][3] = -1
        spots_off()
        _mark('tap_spots_off')
        return 'spots off'
    if n == 4:
        STATE['idx'].update({1: 0, 2: -1, 3: -1, 4: -1})
        back_to_purple()
        return 'regular purple'
    return None


# ---------------------------------------------------------------- dial
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


def _lamps_parallel(m, body):
    """All lamps at once (one thread each) -- a sequential sweep took ~0.6 s and made the dial feel laggy."""
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


def apply_intensity(v):
    """Send the dial's intensity to whatever is running (the layers read STATE directly). Never raises."""
    m = rc()
    try:
        if _hub_alive():
            m.hub_api({'op': 'live', 'key': 'master', 'value': round(v, 3)})
            return 'hub'
        _write_dial(v)
        if m.running('ambient_fade.py'):
            return 'ambient'
        if m.STATE.get('look') in ('off', 'rest', 'night', 'nightlight', 'purplenight'):
            return 'layers'                           # lamps off / night light: the dial doesn't wake them
        _lamps_parallel(m, {'dimming': {'brightness': max(1.0, round(100.0 * v, 1))}, 'dynamics': {'duration': 300}})
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
    """A look from anywhere else (Jarvis, console, schedule): the tap layers stand down, the dial goes to full."""
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
        for kind, n, skips in coalesce(jobs):
            t0 = time.time()
            try:
                what = single(n, skips) if kind == 'single' else double(n)
                log('button %d %s -> %s (%.1f s)' % (n, kind, what, time.time() - t0))
                if STATE['intensity'] < 0.999:
                    apply_intensity(STATE['intensity'])
            except Exception as e:
                log('button %d %s failed: %s: %s' % (n, kind, e.__class__.__name__, e))


DIALQ = {'acc': 0, 'ev': threading.Event()}


def dial_worker():
    while True:
        DIALQ['ev'].wait()
        DIALQ['ev'].clear()
        steps, DIALQ['acc'] = DIALQ['acc'], 0
        if steps:
            turn(steps)
        time.sleep(0.25)                                # at most ~4 updates a second


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


TAP_LOOKS = {k: ('Tap Dial: ' + k[4:].replace('_', ' '), (lambda: None)) for k in
             ['tap_heads_glow', 'tap_heads_dance', 'tap_heads_relay', 'tap_heads_off',
              'tap_spots_uv', 'tap_spots_gobo', 'tap_spots_wash', 'tap_spots_off']}   # names only (status/restore)


def start(on_press=None, module=None):
    if module is None:
        log('no rig_control module given -- Tap Dial not started')
        return
    RC['mod'] = module
    try:                                                # the heads glow isn't a 'quiet room' for head_power
        module.head_power.KEEP_LIT.append(lambda: STATE['layers'].get('heads') == 'glow' and STATE['sending'])
    except AttributeError:
        pass
    for k, v in TAP_LOOKS.items():
        module.LOOKS.setdefault(k, v)
    STATE['seen_look'] = module.STATE.get('look')
    threading.Thread(target=watch, name='tap-dial', daemon=True).start()


def status():
    return dict(device=STATE['device'], last=STATE['last'], source=STATE['source'],
                intensity=round(STATE['intensity'], 2), lag_s=STATE['lag'], layers=dict(STATE['layers']),
                sending=STATE['sending'], node=STATE['node'],
                next={'hue': STATE['idx'][1] + 1, 'heads': STATE['idx'][2] + 1, 'spots': STATE['idx'][3] + 1,
                      'show': STATE['idx'][4] + 1})
