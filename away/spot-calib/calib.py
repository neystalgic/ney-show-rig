#!/usr/bin/env python3
# =============================================================================
# CALIBRATION HELPER (Nov 15) -- no music needed. Drives the heads straight to the DMX node (Art-Net) and the
# Hue lamps (bridge v2), the same way ambient_fade.py does. The node still enforces every head's pan window,
# lean cap and avoid zones, and fades + parks the heads when this stops sending.
#
#   python3 calib.py zones        each zone in turn (7 s): its head lit purple on its Coffee-table aim, its lamps
#                                 bright purple, every other lamp dim -- twice round. Checks the zone map.
#   python3 calib.py sweep N      head N (1-4) alone, at the show's own lean cap, sweeping its whole pan window
#                                 slowly there and back (~40 s) -- shows the widest the show can ever aim it.
#   python3 calib.py target NAME  every head on a saved target (e.g. "Coffee table") for 20 s.
#   python3 calib.py spot N       FOCUS SPOT N (1 or 2) alone: open beam (no gobo), colour slot 97 (deep blue-violet,
#                                 never white), dimmer 60%, on its saved aim (the hub's spot_fx hold for that spot).
#   python3 calib.py aimspot N    live aiming: Spot N follows bridge/calib_aim.json -- {pan, tilt} (16-bit) or
#                                 {az, lean} (degrees, the same numbers spot_fx 'hold' uses), plus optional color,
#                                 gobo, gobo_rot, focus (0-255) and uv (0-1). Logs az/lean to save into spot_fx.
#   python3 calib.py uvaim N      the same, UV only (white/colour beam dark, dimmer 0) -- for aiming the UV wash.
#   (Nov 16) Each fixture gets ITS OWN channel layout: LM70S heads 14 ch, Focus Spots ('type': 'focus17') 17 ch,
#   the same bytes hub_dmx.focus_out writes. Spot 2 on -> ceiling fan off (AGENTS rule; the log says so).
#   touch calib.stop              stops it early.
# Ends with every lamp purple (Michael's default).
# =============================================================================
import json, math, os, socket, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hub_dmx as hd                       # ARTNET_PORT, NODE_PORT, MASTER_MIN/MAX, artdmx()
import hue_stream as hs

STOP = os.path.join(HERE, 'calib.stop')
LOG = os.path.join(HERE, 'bridge', 'outbox', 'calib.txt')
AIM = os.path.join(HERE, 'bridge', 'calib_aim.json')
SPOT_SLOT = 97                             # Focus Spot colour wheel: deep blue-violet, the nearest slot to purple
SPOT_WHITE_BELOW = 15                      # wheel slots 0-14 = open / white -- calibration never shows white
SPOT_LEVEL = 0.6                           # spots light at 60% dimmer while calibrating
PURPLE_XY = (0.27, 0.12)
PURPLE_RGB = (110, 0, 255)
ZONE_NAMES = ['Desk (Head 1)', 'Kitchen (Head 2)', 'Couch (Head 3)', 'Studio corner (Head 4)']
DEFAULT_LAMPS = {'0': ['Behind Desk'], '1': ['Floor Shade', 'Hue Play floor lamp large 1'],
                 '2': ['Hue color lamp 1'], '3': ['Top Lamp', 'Hue color lamp 2']}


def log(msg):
    line = '%s %s' % (time.strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    try:
        with open(LOG, 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass


def settings():
    try:
        return json.load(open(os.path.join(HERE, 'hub_state.json')))['settings']
    except Exception:
        return {}


def node():
    s = settings()
    for h_ in [x.strip() for x in str(s.get('dmx_host') or '192.168.1.80').split(',') if x.strip()]:
        try:
            ip = socket.getaddrinfo(h_, hd.ARTNET_PORT, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
            cfg = json.loads(urllib.request.urlopen('http://%s:%d/config' % (ip, hd.NODE_PORT), timeout=2).read())
            return ip, cfg
        except Exception:
            continue
    raise OSError('DMX node not reachable')


class Heads:
    def __init__(self):
        self.ip, cfg = node()
        self.heads, self.uni = cfg['heads'], int(cfg.get('universe', 0))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0

    def send(self, want):
        """want: {fixture index: (pan16, tilt16, level 0-1[, extras])}; every other fixture dark.
        Each fixture gets its own layout: LM70S heads 14 ch, Focus Spots ('type': 'focus17') 17 ch.
        extras (spots only, all optional): color, gobo, gobo_rot, focus, uv (0-1), uv_only."""
        data = bytearray(512)
        for i, w in want.items():
            if not 0 <= i < len(self.heads):
                continue
            pan, tilt, lvl = w[0], w[1], w[2]
            ex = w[3] if len(w) > 3 and isinstance(w[3], dict) else {}
            h = self.heads[i]
            a = int(h['addr']) - 1
            spot = h.get('type') == 'focus17'
            if a < 0 or a + (17 if spot else 14) > 512:
                continue
            pan = int(max(int(h.get('pan_min', 0)), min(int(h.get('pan_max', 65535)), pan)))
            tilt = int(max(0, min(65535, tilt)))
            data[a], data[a + 1], data[a + 2], data[a + 3] = pan >> 8, pan & 255, tilt >> 8, tilt & 255
            if spot:
                spot_channels(data, a, h, lvl, ex)
                continue
            data[a + 4] = int(h.get('motor_speed', 0))
            data[a + 5] = int(round(hd.MASTER_MIN + max(0.0, min(1.0, lvl)) * (hd.MASTER_MAX - hd.MASTER_MIN)))
            data[a + 6], data[a + 7], data[a + 8] = PURPLE_RGB
        try:
            self.sock.sendto(hd.artdmx(self.seq, self.uni, data), (self.ip, hd.ARTNET_PORT))
        except OSError:
            pass
        self.seq += 1

    def tilt_for(self, i, lean_deg):
        h = self.heads[i]
        return int(h.get('tilt_up', 32768)) + int(h.get('tilt_dir', 1)) * lean_deg / 180.0 * 65535.0

    # FOCUS SPOTS use the hub's own spot maths (hub_dmx.focus_out): 540 deg of pan, 240 deg of tilt
    def spot_aim(self, i, az, lean):
        h = self.heads[i]
        tilt = int(h.get('tilt_up', 32768)) + int(h.get('tilt_dir', 1)) * float(lean) / 240.0 * 65535.0
        return (float(az) % 360.0) / 540.0 * 65535.0, max(0.0, min(65535.0, tilt))

    def spot_deg(self, i, pan, tilt):
        h = self.heads[i]
        lean = (float(tilt) - int(h.get('tilt_up', 32768))) * int(h.get('tilt_dir', 1)) / 65535.0 * 240.0
        return float(pan) / 65535.0 * 540.0, lean


def byte(v, default):
    try:
        return int(max(0, min(255, int(v))))
    except (TypeError, ValueError):
        return default


def spot_channels(data, a, h, lvl, ex):
    """FOCUS SPOT channels after pan/tilt (same meaning as hub_dmx.focus_out): a+4 colour slot, a+5 gobo,
    a+6 gobo rotation, a+7 focus, a+8 shutter (12 = open -- never strobe), a+9 dimmer, a+10 UV shutter,
    a+11 UV, a+15 motor speed. uv_only = beam dark (dimmer 0, shutter closed), UV on."""
    lvl = max(0.0, min(1.0, float(lvl)))
    m = 0 if lvl < 0.004 else int(round(lvl * 255))
    try:
        uv = max(0.0, min(1.0, float(ex.get('uv', 0) or 0)))
    except (TypeError, ValueError):
        uv = 0.0
    uvb = 0 if uv < 0.004 else int(round(uv * 255))
    if ex.get('uv_only'):
        m = 0
    slot = byte(ex.get('color'), SPOT_SLOT)
    if slot < SPOT_WHITE_BELOW:                    # open / white part of the wheel: use the purple-ish slot instead
        slot = SPOT_SLOT
    data[a + 4] = slot
    data[a + 5] = byte(ex.get('gobo'), 0)
    data[a + 6] = byte(ex.get('gobo_rot'), 0)
    data[a + 7] = byte(ex.get('focus'), 128)
    data[a + 8] = 12 if m > 0 else 0
    data[a + 9] = m
    data[a + 10] = 12 if uvb > 0 else 0
    data[a + 11] = uvb
    data[a + 15] = byte(h.get('motor_speed'), 0)


class Lamps:
    def __init__(self):
        cwd = os.getcwd()
        os.chdir(HERE)
        try:
            self.cfg = hs.load_config()
            self.ids = {l['metadata']['name']: l['id'] for l in hs.v2(self.cfg, 'light').get('data', [])
                        if 'color' in l and 'metadata' in l}
        finally:
            os.chdir(cwd)

    def set(self, names_bright, others=4.0, bright=100.0):
        for name, rid in self.ids.items():
            b = bright if name in names_bright else others
            try:
                hs.v2(self.cfg, 'light/' + rid, 'PUT', {'on': {'on': True}, 'dimming': {'brightness': b},
                                                       'color': {'xy': {'x': PURPLE_XY[0], 'y': PURPLE_XY[1]}},
                                                       'dynamics': {'duration': 300}})
            except Exception as e:
                log('lamp %s: %s' % (name, e.__class__.__name__))
            time.sleep(0.11)                       # the bridge allows ~10 commands a second

    def all_purple(self):
        self.set(set(self.ids), bright=100.0)


def hold(heads, want, secs):
    end = time.time() + secs
    while time.time() < end and not os.path.exists(STOP):
        heads.send(want)
        time.sleep(1.0 / 25.0)


def zones(heads, lamps):
    s = settings()
    zl = s.get('chase_lamps') if isinstance(s.get('chase_lamps'), dict) else DEFAULT_LAMPS
    tg = (s.get('head_targets') or {}).get('Coffee table') or {}
    for rnd in range(2):
        for i in range(4):
            if os.path.exists(STOP):
                return
            names = set(zl.get(str(i)) or [])
            t = tg.get(str(i)) or {}
            pan, tilt = float(t.get('pan', (heads.heads[i].get('pan_min', 0) + heads.heads[i].get('pan_max', 65535)) / 2)), \
                float(t.get('tilt', heads.tilt_for(i, 30.0)))
            log('ZONE %s: head %d lit, lamps %s' % (ZONE_NAMES[i], i + 1, ', '.join(sorted(names)) or '(none)'))
            lamps.set(names)
            hold(heads, {i: (pan, tilt, 0.8)}, 7.0)


def sweep(heads, n):
    i = n - 1
    h = heads.heads[i]
    s = settings()
    lean = min(float(h.get('tilt_max_deg', 35.0)), float(s.get('dmx_lean_cap', 45.0))) * 0.95
    pmin, pmax = int(h.get('pan_min', 0)), int(h.get('pan_max', 65535))
    tilt = heads.tilt_for(i, lean)
    log('SWEEP head %d (%s): lean %.0f deg (the show cap), pan %d -> %d and back' % (n, h.get('name'), lean, pmin, pmax))
    # start upright-ish at the left end, then sweep at <= 20 deg/s (slower than the show's 35)
    span_deg = (pmax - pmin) / 65535.0 * 540.0
    secs = max(12.0, span_deg / 20.0)
    hold(heads, {i: (pmin, heads.tilt_for(i, 10.0), 0.0)}, 3.0)          # dark move to the start
    hold(heads, {i: (pmin, tilt, 0.8)}, 2.0)
    for a, b in ((pmin, pmax), (pmax, pmin)):
        t0 = time.time()
        while time.time() - t0 < secs and not os.path.exists(STOP):
            p = (time.time() - t0) / secs
            e = 0.5 - 0.5 * math.cos(math.pi * p)
            heads.send({i: (a + (b - a) * e, tilt, 0.8)})
            time.sleep(1.0 / 25.0)
        log('  head %d reached the %s end of its window' % (n, 'right' if b == pmax else 'left'))


def spot_index(heads, n):
    """Spot N = the Nth 'focus17' fixture in the node list (Spot 1 = fixture index 4, Spot 2 = 5)."""
    spots = [i for i, h in enumerate(heads.heads) if h.get('type') == 'focus17']
    if not 1 <= n <= len(spots):
        raise SystemExit('no Spot %d in the node config (%d spot(s) found)' % (n, len(spots)))
    return spots[n - 1]


def spot_saved(heads, i):
    """A spot's saved aim (pan16, tilt16): its spot_fx 'hold' (per_head first, then the shared hold when hold_head
    is this spot), else the middle of its pan window at a 30 deg lean."""
    fx = settings().get('spot_fx') or {}
    fx = fx if isinstance(fx, dict) else {}
    ph = (fx.get('per_head') or {}).get(str(i))
    hold_ = None
    if isinstance(ph, dict) and isinstance(ph.get('hold'), dict):
        hold_ = ph['hold']
    elif isinstance(fx.get('hold'), dict) and int(fx.get('hold_head', 4)) == i:
        hold_ = fx['hold']
    try:
        return heads.spot_aim(i, float(hold_['az']), float(hold_.get('lean', 30.0)))
    except (TypeError, KeyError, ValueError):
        h = heads.heads[i]
        mid = (int(h.get('pan_min', 0)) + int(h.get('pan_max', 65535))) / 2.0
        return mid, heads.spot_aim(i, 0.0, 30.0)[1]


def fan_note(heads, i, n):
    if n == 2:
        log('  SPOT 2 IS ON -- ceiling fan OFF please (and switch it off by hand when done)')


def spot(heads, n, secs=900.0):
    i = spot_index(heads, n)
    pan, tilt = spot_saved(heads, i)
    az, lean = heads.spot_deg(i, pan, tilt)
    log('SPOT %d (fixture %d): open beam, colour slot %d, dimmer %d%% on its saved aim (az %.0f, lean %.0f)'
        % (n, i + 1, SPOT_SLOT, SPOT_LEVEL * 100, az, lean))
    fan_note(heads, i, n)
    hold(heads, {i: (pan, tilt, SPOT_LEVEL, {})}, secs)


def follow_spot(heads, n, uv_only=False, secs=900.0):
    """Spot N follows calib_aim.json ({pan, tilt} or {az, lean} + optional color/gobo/gobo_rot/focus/uv).
    Starts on its saved aim; a missing or half-written file keeps the last good aim."""
    i = spot_index(heads, n)
    pan, tilt = spot_saved(heads, i)
    cur, last = (pan, tilt, {}), None
    log('%s spot %d (fixture %d): follows calib_aim.json' % ('UVAIM' if uv_only else 'AIMSPOT', n, i + 1))
    fan_note(heads, i, n)
    end = time.time() + secs
    while time.time() < end and not os.path.exists(STOP):
        try:
            a = json.load(open(AIM))
            if 'az' in a:
                p, t = heads.spot_aim(i, float(a['az']), float(a.get('lean', 30.0)))
            else:
                p, t = float(a['pan']), float(a['tilt'])
            cur = (p, t, {k: a[k] for k in ('color', 'gobo', 'gobo_rot', 'focus', 'uv') if k in a})
        except Exception:
            pass
        p, t, ex = cur
        ex = dict(ex)
        if uv_only:
            ex['uv'] = ex.get('uv', 1.0)
            ex['uv_only'] = True
        if (p, t, sorted(ex.items())) != last:
            az, lean = heads.spot_deg(i, p, t)
            log('  spot %d -> pan %d, tilt %d (az %.1f, lean %.1f) %s' % (n, p, t, az, lean,
                ' '.join('%s=%s' % kv for kv in sorted(ex.items()))))
            last = (p, t, sorted(ex.items()))
        heads.send({i: (p, t, SPOT_LEVEL, ex)})
        time.sleep(1.0 / 25.0)


def target(heads, name):
    tg = (settings().get('head_targets') or {}).get(name) or {}
    want = {int(k): (float(v['pan']), float(v['tilt']), float(v.get('level', 0.8))) for k, v in tg.items()
            if str(k).isdigit() and int(k) < 4}
    log('TARGET %s: heads %s' % (name, ', '.join(str(k + 1) for k in sorted(want)) or 'none saved'))
    hold(heads, want, 20.0)


def main(argv):
    try:
        os.remove(STOP)
    except OSError:
        pass
    open(LOG, 'w').close()
    if not argv:
        print(__doc__ or 'usage: calib.py zones | sweep N | head N | aim N | target NAME | lamp NAME | spot N | aimspot N | uvaim N')
        return 2
    wait = 0.0
    if '--wait' in argv:
        k = argv.index('--wait')
        wait = float(argv[k + 1])
        argv = argv[:k] + argv[k + 2:]
    if wait > 0:
        log('waiting %.0f s for the heads to power up and reset' % wait)
        time.sleep(wait)
    heads, lamps = Heads(), Lamps()
    try:
        if argv[0] == 'zones':
            zones(heads, lamps)
        elif argv[0] == 'sweep':
            sweep(heads, int(argv[1]))
        elif argv[0] == 'head':                      # one head lit on its Coffee-table aim + its zone's lamps (zones_calibration.json)
            n = int(argv[1])
            try:
                cal = json.load(open(os.path.join(HERE, 'zones_calibration.json')))
                zid, grp = next((z, g) for z, g in cal['groups'].items() if n in g.get('heads', []))
            except Exception:
                zid, grp = '?', {}
            t = ((settings().get('head_targets') or {}).get('Coffee table') or {}).get(str(n - 1)) or {}
            pan = float(t.get('pan', (heads.heads[n - 1].get('pan_min', 0) + heads.heads[n - 1].get('pan_max', 65535)) / 2))
            tilt = float(t.get('tilt', heads.tilt_for(n - 1, 30.0)))
            log('HEAD %d (zone %s): lit on its coffee-table aim; zone lamps %s' % (n, zid, ', '.join(grp.get('lamps', [])) or '(none)'))
            lamps.set(set(grp.get('lamps', [])), others=1.0)
            hold(heads, {n - 1: (pan, tilt, 0.8)}, 900.0)          # stays lit until the next step (calib.stop)
        elif argv[0] == 'spot':                      # Focus Spot N lit on its saved aim (open, purple-ish, 60%)
            spot(heads, int(argv[1]))
        elif argv[0] in ('aimspot', 'uvaim'):        # live aiming of a Focus Spot (uvaim = UV only)
            follow_spot(heads, int(argv[1]), uv_only=argv[0] == 'uvaim')
            return 0
        elif argv[0] == 'aim':                       # live aiming: head N follows bridge/calib_aim.json {pan, tilt} (Claude nudges it)
            n = int(argv[1])
            ap = AIM
            log('AIM head %d: follows calib_aim.json' % n)
            end, last = time.time() + 900, None
            while time.time() < end and not os.path.exists(STOP):
                try:
                    a = json.load(open(ap))
                    want = (float(a['pan']), float(a['tilt']))
                except Exception:
                    want = last
                if want:
                    if want != last:
                        log('  head %d -> pan %d, tilt %d' % (n, want[0], want[1]))
                        last = want
                    heads.send({n - 1: (want[0], want[1], 0.8)})
                time.sleep(1.0 / 25.0)
            return 0
        elif argv[0] == 'lamp':                      # one Hue lamp bright purple, every other lamp nearly off
            name = ' '.join(argv[1:])
            log('LAMP %s on, the rest dim' % name)
            lamps.set({name}, others=1.0)
            end = time.time() + 900
            while time.time() < end and not os.path.exists(STOP):
                time.sleep(0.2)
            return 0
        elif argv[0] == 'target':
            target(heads, ' '.join(argv[1:]))
    finally:
        log('done -- heads fading out and parking, lamps back to purple')
        lamps.all_purple()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
