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
        """want: {head index: (pan16, tilt16, level 0-1)}; every other head dark."""
        data = bytearray(512)
        for i, (pan, tilt, lvl) in want.items():
            h = self.heads[i]
            a = int(h['addr']) - 1
            if a < 0 or a + 14 > 512:
                continue
            pan = int(max(int(h.get('pan_min', 0)), min(int(h.get('pan_max', 65535)), pan)))
            tilt = int(max(0, min(65535, tilt)))
            data[a], data[a + 1], data[a + 2], data[a + 3] = pan >> 8, pan & 255, tilt >> 8, tilt & 255
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
        print(__doc__ or 'usage: calib.py zones | sweep N | target NAME')
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
            hold(heads, {n - 1: (pan, tilt, 0.8)}, 60.0)
        elif argv[0] == 'aim':                       # live aiming: head N follows bridge/calib_aim.json {pan, tilt} (Claude nudges it)
            n = int(argv[1])
            ap = os.path.join(HERE, 'bridge', 'calib_aim.json')
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
            end = time.time() + 120
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
