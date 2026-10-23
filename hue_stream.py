#!/usr/bin/env python3
# =============================================================================
# BOTANICA HUE HELPER -- pairs with your Hue Bridge and streams colours from
# TouchDesigner to the lights, 50 times a second, through Hue Entertainment.
#
# Runs in Terminal with the Mac's own Python (3.12), NOT inside TouchDesigner.
# TouchDesigner's hue_rig component sends it colours over this computer only
# (UDP 127.0.0.1:7010); this script passes them on to the bridge.
#
# One-time install (Terminal):
#     python3 -m pip install --user python-mbedtls
#
# Then, from the Hue Rig folder:
#     python3 hue_stream.py pair        press the bridge's round button first
#     python3 hue_stream.py areas       list Entertainment areas, write the lamp list
#     python3 hue_stream.py scan        every lamp, its model, gradient zones (for the Hue Hub)
#     python3 hue_stream.py colours     every lamp shows the rainbow -- compare with TouchDesigner
#     python3 hue_stream.py test        flash each lamp in turn, to check the order
#     python3 hue_stream.py check       a guided 90-second bulb test (colours, fades,
#                                       dimming, speed) -- is this brand good enough?
#     python3 hue_stream.py run         stream from TouchDesigner (Ctrl+C to stop)
#
# Options:  --ip 192.168.x.x   use this bridge address (otherwise it's found
#                              automatically, or remembered from pairing)
#           --area "Name"      which Entertainment area (default: the first)
#           --port 7010        where TouchDesigner sends to
#
# Settings are saved next to this script in hue_config.json (bridge address
# and the two keys the bridge gives you). Keep that file private -- the keys
# let anything on your network control the lights.
# =============================================================================

import argparse
import json
import math
import os
import socket
import ssl
import struct
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, 'hue_config.json')
LAMPS_CSV = os.path.join(HERE, 'hue_lamps.csv')
CIPHER = 'TLS-PSK-WITH-AES-128-GCM-SHA256'


# ---- small helpers -------------------------------------------------------------
def say(*a):
    print(*a, flush=True)


def load_config():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG, 'w') as f:
        json.dump(cfg, f, indent=2)
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass


def http(method, url, body=None, key=None, timeout=5):
    """HTTPS to the bridge (its certificate is self-signed, so not verified)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    if key:
        req.add_header('hue-application-key', key)
    ctx = ssl._create_unverified_context()
    # the bridge is on your own network: never send this through a proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=ctx))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or 'null')


def discover():
    say('Looking for your Hue Bridge ...')
    try:
        # python.org's Python on macOS often has no certificate list of its own;
        # certifi (installed alongside python-mbedtls) provides one
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen('https://discovery.meethue.com/', timeout=6, context=ctx) as r:
            found = json.loads(r.read().decode())
        if found:
            ip = found[0]['internalipaddress']
            say('  found it at', ip)
            return ip
    except Exception as e:
        say('  automatic search failed (%s)' % e)
    say('  Find the address in the Hue app: Settings > Bridges > (your bridge) > IP address,')
    say('  then run this again with  --ip 192.168.x.x')
    sys.exit(1)


def bridge_ip(args, cfg):
    return args.ip or cfg.get('ip') or discover()


def v2(cfg, path, method='GET', body=None):
    return http(method, 'https://%s/clip/v2/resource/%s' % (cfg['ip'], path), body, key=cfg['username'])


# ---- pair ------------------------------------------------------------------------
def cmd_pair(args):
    cfg = load_config()
    ip = bridge_ip(args, cfg)
    say('\nPress the big round button on top of the Hue Bridge now.')
    say('Waiting up to 60 seconds ...')
    for _ in range(30):
        try:
            res = http('POST', 'https://%s/api' % ip,
                       {'devicetype': 'botanica#touchdesigner', 'generateclientkey': True})
        except Exception as e:
            say('  could not reach the bridge at %s (%s)' % (ip, e))
            if 'No route to host' in str(e) or 'Errno 65' in str(e):
                say('  Most likely macOS is blocking Terminal from your home network:')
                say('  System Settings > Privacy & Security > Local Network > turn Terminal ON,')
                say('  then quit Terminal (Cmd+Q), reopen it and run this again.')
                say('  Also check the Mac is on the same Wi-Fi as the bridge (not a guest network or VPN).')
            sys.exit(1)
        item = res[0] if isinstance(res, list) and res else {}
        if 'success' in item:
            cfg.update(ip=ip, username=item['success']['username'],
                       clientkey=item['success']['clientkey'])
            save_config(cfg)
            say('\nPaired. Saved to', CONFIG)
            say('Next:  python3 hue_stream.py areas')
            return
        time.sleep(2)
    say('\nThe button wasn\'t pressed in time -- run pair again.')
    sys.exit(1)


# ---- entertainment areas ----------------------------------------------------------------
def need_pairing(cfg):
    if not cfg.get('username') or not cfg.get('clientkey'):
        say('Not paired yet -- run:  python3 hue_stream.py pair')
        sys.exit(1)


def get_areas(cfg):
    return v2(cfg, 'entertainment_configuration').get('data', [])


def pick_area(cfg, name):
    areas = get_areas(cfg)
    if not areas:
        say('No Entertainment areas yet. In the Hue app: Settings > Entertainment areas > Add.')
        sys.exit(1)
    if name:
        for a in areas:
            if a.get('metadata', {}).get('name', '').lower() == name.lower():
                return a
        say('No Entertainment area called "%s". These exist:' % name)
        for a in areas:
            say('   ', a.get('metadata', {}).get('name'))
        sys.exit(1)
    return areas[0]


def lamp_table(cfg, area):
    """One row per channel: channel id, lamp name, v1 light id, position on
    the picture (u across, v up, 0-1), from the area's own layout."""
    ents = {e['id']: e for e in v2(cfg, 'entertainment').get('data', [])}
    devs = {d['id']: d for d in v2(cfg, 'device').get('data', [])}
    rows = []
    for ch in sorted(area.get('channels', []), key=lambda c: c['channel_id']):
        name, v1 = 'channel %d' % ch['channel_id'], ''
        try:
            rid = ch['members'][0]['service']['rid']
            dev = devs.get(ents[rid]['owner']['rid'], {})
            name = dev.get('metadata', {}).get('name', name)
            v1 = (dev.get('id_v1') or '').split('/')[-1]
        except Exception:
            pass
        pos = ch.get('position', {})
        u = (float(pos.get('x', 0.0)) + 1.0) / 2.0          # left (-1) .. right (1)
        v = (float(pos.get('z', 0.0)) + 1.0) / 2.0          # floor (-1) .. ceiling (1)
        rows.append(dict(channel=ch['channel_id'], name=name, v1=v1,
                         u=round(min(max(u, 0), 1), 3), v=round(min(max(v, 0), 1), 3)))
    return rows


def write_lamps(rows):
    with open(LAMPS_CSV, 'w') as f:
        f.write('channel\tname\tv1\tu\tv\n')
        for r in rows:
            f.write('%d\t%s\t%s\t%.3f\t%.3f\n' % (r['channel'], r['name'].replace('\t', ' '),
                                               r['v1'], r['u'], r['v']))


def cmd_areas(args):
    cfg = load_config()
    need_pairing(cfg)
    areas = get_areas(cfg)
    if not areas:
        say('No Entertainment areas yet. In the Hue app: Settings > Entertainment areas > Add.')
        return
    say('Entertainment areas:')
    for a in areas:
        say('  ', a.get('metadata', {}).get('name'), '(%d lights)' % len(a.get('channels', [])))
    area = pick_area(cfg, args.area)
    rows = lamp_table(cfg, area)
    write_lamps(rows)
    cfg['area'] = area['id']
    cfg['area_name'] = area.get('metadata', {}).get('name')
    save_config(cfg)
    say('\nUsing "%s". Lamps, in TouchDesigner\'s order:' % cfg['area_name'])
    for r in rows:
        say('   %d  %-22s  across %.2f  up %.2f' % (r['channel'], r['name'], r['u'], r['v']))
    say('\nWrote', LAMPS_CSV, '-- the hue_rig component reads this.')
    say('Next:  python3 hue_stream.py test   (or  run)')



# ---- scan: every lamp, its model, and how many colours it can show at once --------------
HUB_LAMPS = os.path.join(HERE, 'hub_lamps.json')


def lamp_layout(cfg, area):
    """The lamps in an Entertainment area, each with its channels (segments).
    A gradient lamp that the area splits into zones has several channels."""
    ents = {e['id']: e for e in v2(cfg, 'entertainment').get('data', [])}
    devs = {d['id']: d for d in v2(cfg, 'device').get('data', [])}
    try:
        lights = {l.get('owner', {}).get('rid'): l for l in v2(cfg, 'light').get('data', [])}
    except Exception:
        lights = {}
    lamps, by_rid = [], {}
    for ch in sorted(area.get('channels', []), key=lambda c: c['channel_id']):
        mem = (ch.get('members') or [{}])[0]
        rid = mem.get('service', {}).get('rid', 'ch%d' % ch['channel_id'])
        pos = ch.get('position', {})
        seg = dict(channel=ch['channel_id'], index=int(mem.get('index', 0)),
                   x=float(pos.get('x', 0.0)), y=float(pos.get('y', 0.0)), z=float(pos.get('z', 0.0)))
        if rid not in by_rid:
            ent = ents.get(rid, {})
            dev = devs.get(ent.get('owner', {}).get('rid'), {})
            light = lights.get(dev.get('id'), {})
            pd = dev.get('product_data', {})
            grad = light.get('gradient') or {}
            lamp = dict(rid=rid, name=dev.get('metadata', {}).get('name', 'channel %d' % ch['channel_id']),
                        product=pd.get('product_name', ''), model=pd.get('model_id', ''),
                        v1=(dev.get('id_v1') or '').split('/')[-1],
                        gradient_points=int(grad.get('points_capable', 0) or 0),
                        max_segments=int((ent.get('segments') or {}).get('max_segments', 1) or 1),
                        segments=[])
            by_rid[rid] = lamp
            lamps.append(lamp)
        by_rid[rid]['segments'].append(seg)
    for lamp in lamps:
        lamp['segments'].sort(key=lambda s: s['index'])
    return lamps


def cmd_scan(args):
    cfg = load_config()
    if args.ip:
        cfg['ip'] = args.ip
    need_pairing(cfg)
    area = pick_area(cfg, args.area)
    lamps = lamp_layout(cfg, area)
    name = area.get('metadata', {}).get('name')
    say('Entertainment area "%s": %d lamps, %d channels\n' % (name, len(lamps), sum(len(l['segments']) for l in lamps)))
    tips = []
    for i, l in enumerate(lamps, 1):
        n = len(l['segments'])
        can = max(l['gradient_points'], l['max_segments'])
        kind = 'gradient, up to %d colours at once' % can if can > 1 else 'one colour at a time'
        say('  %d. %-28s %s' % (i, l['name'], l['product'] or l['model'] or '(unknown model)'))
        say('       %s -- your area gives it %d channel%s%s' % (
            kind, n, '' if n == 1 else 's', ' (each one its own colour)' if n > 1 else ''))
        if can > 1 and n == 1:
            tips.append(l['name'])
    with open(HUB_LAMPS, 'w') as f:
        json.dump({'area': area['id'], 'area_name': name, 'lamps': lamps}, f, indent=1)
    cfg['area'], cfg['area_name'] = area['id'], name
    save_config(cfg)
    say('\nWrote %s -- the Hue Hub reads this.' % HUB_LAMPS)
    if tips:
        say('\nThese can show several colours but your area only gives them one channel:')
        for t in tips:
            say('   -', t)
        say('In the Hue app, remove the lamp from the Entertainment area and add it again (or make a')
        say('new area) -- the app then splits gradient lamps into zones. Run this scan again after.')

# ---- streaming ----------------------------------------------------------------------------
GAMUT_C = ((0.6915, 0.3083), (0.17, 0.70), (0.1532, 0.0475))    # what Hue colour bulbs can show


def _closest_on_segment(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ax + dx * t, ay + dy * t


def _in_gamut(p, g=GAMUT_C):
    def side(a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    s1, s2, s3 = side(g[0], g[1]), side(g[1], g[2]), side(g[2], g[0])
    return (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0)


D65 = (0.3127, 0.3290)
VIVID = 0.5          # 0 = exact screen colours; 1 = fully saturated colours use the bulbs' deepest version


def _edge_along(p, w=D65, g=GAMUT_C):
    """Where the line from white through p leaves the bulbs' colour range."""
    dx, dy = p[0] - w[0], p[1] - w[1]
    best = None
    for i in range(3):
        ax, ay = g[i]
        bx, by = g[(i + 1) % 3]
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        u = ((ax - w[0]) * ey - (ay - w[1]) * ex) / den        # along the ray
        v = ((ax - w[0]) * dy - (ay - w[1]) * dx) / den        # along the edge
        if u > 1e-9 and -1e-9 <= v <= 1 + 1e-9 and (best is None or u < best):
            best = u
    return best                                                # p = w + d*1, edge = w + d*best


def rgb_to_xyb(r, g, b):
    """Screen colour (0-1, as TouchDesigner / the desk / Push show it) -> Hue (x, y, brightness).
    The standard sRGB recipe (undo the screen gamma, sRGB -> XYZ), so the hue on
    the bulb is the hue on the screen. Fully saturated colours are then pushed
    towards the bulbs' own most vivid version (VIVID), and anything the bulbs
    can't show is brought inside their range along the same hue, never sideways.
    Brightness follows the brightest channel: a dim colour stays the same colour."""
    r, g, b = (max(0.0, min(1.0, v)) for v in (r, g, b))
    bri = max(r, g, b)
    if bri <= 1e-5:
        return D65[0], D65[1], 0.0
    n = (r / bri, g / bri, b / bri)
    lin = [((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in n]
    X = lin[0] * 0.4124 + lin[1] * 0.3576 + lin[2] * 0.1805
    Y = lin[0] * 0.2126 + lin[1] * 0.7152 + lin[2] * 0.0722
    Z = lin[0] * 0.0193 + lin[1] * 0.1192 + lin[2] * 0.9505
    tot = X + Y + Z
    if tot <= 1e-9:
        return D65[0], D65[1], 0.0
    p = (X / tot, Y / tot)
    d = math.hypot(p[0] - D65[0], p[1] - D65[1])
    if d > 1e-6:
        edge = _edge_along(p)
        if edge is not None:
            t = 1.0 / edge                                     # 0 = white, 1 = on the bulbs' edge
            sat = 1.0 - min(n)                                 # 1 = fully saturated screen colour
            if t < 1.0 and VIVID > 0:
                t = t + (1.0 - t) * VIVID * sat ** 3
            t = min(t, 1.0)
            k = t * edge
            p = (D65[0] + (p[0] - D65[0]) * k, D65[1] + (p[1] - D65[1]) * k)
    return p[0], p[1], bri


def huestream_packet(seq, area_id, channels, space='xy'):
    """HueStream v2 message: header, colour space, area id, then 7 bytes per
    channel (id + three 16-bit values: x, y, brightness -- or R, G, B)."""
    out = bytearray(b'HueStream')
    out += bytes([0x02, 0x00, seq & 0xFF, 0x00, 0x00, 0x01 if space == 'xy' else 0x00, 0x00])
    out += area_id.encode('ascii')
    for ch, (r, g, b) in channels:
        vals = rgb_to_xyb(r, g, b) if space == 'xy' else (r, g, b)
        out += struct.pack('>BHHH', ch & 0xFF, *(int(max(0.0, min(1.0, v)) * 65535) for v in vals))
    return bytes(out)


def open_dtls(ip, username, clientkey, port=2100, attempts=6):
    """Encrypted UDP link to the bridge. Each attempt uses a fresh socket and a
    short timeout, so one lost packet doesn't stall the whole handshake."""
    try:
        from mbedtls import tls
    except ImportError:
        say('Missing the DTLS library. In Terminal run:')
        say('    python3 -m pip install --user python-mbedtls')
        sys.exit(1)
    conf = tls.DTLSConfiguration(
        validate_certificates=False,
        ciphers=[CIPHER],
        lowest_supported_version=tls.DTLSVersion.DTLSv1_2,
        highest_supported_version=tls.DTLSVersion.DTLSv1_2,
        pre_shared_key=(username, bytes.fromhex(clientkey)),
        handshake_timeout_min=0.5, handshake_timeout_max=4.0)
    last = None
    for attempt in range(1, attempts + 1):
        raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        raw.settimeout(2.0)
        try:
            raw.connect((ip, port))
            dtls = tls.ClientContext(conf).wrap_socket(raw, server_hostname=None)
            deadline = time.time() + 4.0
            while True:
                try:
                    dtls.do_handshake()
                    break
                except (tls.WantReadError, tls.WantWriteError):
                    if time.time() > deadline:
                        raise TimeoutError('handshake took too long')
                    continue
            if attempt > 1:
                say('  (connected on attempt %d)' % attempt)
            return dtls
        except Exception as e:                       # timeout, refused, TLS error
            last = e
            try:
                raw.close()
            except Exception:
                pass
            say('  encrypted connection attempt %d of %d failed (%s) -- retrying'
                % (attempt, attempts, type(e).__name__))
            time.sleep(0.6)
    raise ConnectionError('could not open the encrypted stream to the bridge (%s)' % last)


class Streamer:
    def __init__(self, cfg, area_name=None, space='xy'):
        self.cfg = cfg
        self.space = space
        need_pairing(cfg)
        area = pick_area(cfg, area_name or cfg.get('area_name'))
        self.area_id = area['id']
        self.channels = sorted(c['channel_id'] for c in area.get('channels', []))
        self.name = area.get('metadata', {}).get('name')
        self.seq = 0
        self.sock = None

    def status(self):
        try:
            d = v2(self.cfg, 'entertainment_configuration/%s' % self.area_id).get('data', [{}])[0]
            return d.get('status'), d.get('active_streamer')
        except Exception as e:
            return 'unknown (%s)' % e, None

    def start(self):
        res = v2(self.cfg, 'entertainment_configuration/%s' % self.area_id, 'PUT', {'action': 'start'})
        errs = (res or {}).get('errors') or []
        if errs:
            say('  the bridge said: ' + '; '.join(str(e.get('description', e)) for e in errs))
        time.sleep(0.5)                              # give the bridge a moment to open the stream
        try:
            self.sock = open_dtls(self.cfg['ip'], self.cfg['username'], self.cfg['clientkey'])
        except ConnectionError as e:
            st, who = self.status()
            say('\nCould not start streaming: %s' % e)
            say('  Entertainment area "%s" status: %s' % (self.name, st))
            say('  Things to check:')
            say('   - Close the Hue Sync app / any TV or game sync that might be using the lights.')
            say('   - In the Hue app, open the Entertainment area once (Settings > Entertainment')
            say('     areas > %s) so it is fully set up, then try again.' % self.name)
            say('   - Make sure the bridge has finished updating (Hue app > Settings > Software update).')
            try:
                v2(self.cfg, 'entertainment_configuration/%s' % self.area_id, 'PUT', {'action': 'stop'})
            except Exception:
                pass
            sys.exit(1)

    def send(self, colours):
        pairs = list(zip(self.channels, colours))
        self.sock.send(huestream_packet(self.seq, self.area_id, pairs, self.space))
        self.seq = (self.seq + 1) & 0xFF

    def stop(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            try:
                v2(self.cfg, 'entertainment_configuration/%s' % self.area_id, 'PUT', {'action': 'stop'})
            except Exception:
                pass


FEELINGS = [((1.00, 0.62, 0.30), (0.85, 0.50, 0.55), (1.00, 0.88, 0.70)),    # nostalgia
            ((1.00, 0.80, 0.45), (0.40, 0.82, 0.80), (0.75, 0.95, 1.00)),    # hope
            ((1.00, 0.25, 0.75), (0.55, 0.30, 1.00), (1.00, 0.80, 0.30))]    # triumph


def cmd_test(args):
    cfg = load_config()
    if args.ip:
        cfg['ip'] = args.ip
    s = Streamer(cfg, args.area, args.colour)
    say('Testing "%s": each lamp lights up in turn, in TouchDesigner\'s order.' % s.name)
    s.start()
    try:
        n = len(s.channels)
        t0, shown = time.time(), -1
        while time.time() - t0 < 4.0 * n + 6:
            t = time.time() - t0
            if t < 4.0 * n:
                k = int(t // 4)
                cols = [(0.0, 0.0, 0.0)] * n
                cols[k] = FEELINGS[2][0]
                if k != shown:
                    say('   lamp %d of %d (channel %d) is lit' % (k + 1, n, s.channels[k]))
                    shown = k
            else:                                                # then the three feelings
                f = FEELINGS[min(int((t - 4.0 * n) // 2), 2)]
                cols = [f[i % 3] for i in range(n)]
            s.send(cols)
            time.sleep(0.02)
    finally:
        s.stop()
    say('Done.')


# ---- check: a guided test, to decide if these bulbs are good enough ---------------------
def _hold(s, seconds, fn, speed):
    """Stream fn(t) -> list of colours for `seconds` (scaled by speed)."""
    t0 = time.time()
    while True:
        t = (time.time() - t0) * speed
        if t >= seconds:
            break
        s.send(fn(t))
        time.sleep(0.02)


def cmd_check(args):
    cfg = load_config()
    if args.ip:
        cfg['ip'] = args.ip
    s = Streamer(cfg, args.area, args.colour)
    n = len(s.channels)
    sp = max(args.speed, 0.01)
    same = lambda c: (lambda t: [c] * n)
    score = []

    def step(title, look_for):
        say('\n' + title)
        say('   look for: ' + look_for)
        score.append(title)

    say('BULB CHECK for "%s" (%d lamps) -- about 90 seconds.' % (s.name, n))
    say('Watch the lamps and note anything that fails. Ctrl+C stops at any time.')
    s.start()
    try:
        step('1. WHICH LAMP IS WHICH', 'each lamp lights alone, in turn (the order TouchDesigner uses)')
        for k in range(n):
            say('   lamp %d of %d' % (k + 1, n))
            _hold(s, 2.5, lambda t, k=k: [(1, 1, 1) if i == k else (0, 0, 0) for i in range(n)], sp)

        step('2. THE THREE FEELINGS', 'rich colour, both lamps matching each other')
        for fname, f in zip(('nostalgia', 'hope', 'triumph'), FEELINGS):
            for cname, c in zip(('colour A', 'colour B', 'accent'), f):
                say('   %-9s %s' % (fname, cname))
                _hold(s, 3, same(c), sp)

        step('3. DEEP COLOURS (the hard ones)',
             'a true deep VIOLET and BLUE -- not washed-out lavender or white-ish. '
             'This is where cheap bulbs fail; Hue should pass.')
        for cname, c in (('deep violet', (0.45, 0.0, 1.0)), ('deep blue', (0.0, 0.0, 1.0)),
                         ('magenta', (1.0, 0.0, 1.0)), ('pure red', (1.0, 0.0, 0.0)),
                         ('pure green', (0.0, 1.0, 0.0))):
            say('   ' + cname)
            _hold(s, 3, same(c), sp)

        step('4. SMOOTH FADE', 'amber fading up and down with NO visible steps or flicker')
        _hold(s, 8, lambda t: [tuple(x * (0.5 - 0.5 * math.cos(t / 8 * 2 * math.pi)) for x in FEELINGS[0][0])] * n, sp)

        step('5. VERY DIM', 'a soft glow that stays steady at the lowest levels (no flicker, no '
             'switching off) -- matters for nostalgia moments')
        for lvl in (0.08, 0.04, 0.02):
            say('   %d%%' % round(lvl * 100))
            _hold(s, 3, same(tuple(x * lvl for x in FEELINGS[0][2])), sp)

        step('6. SPEED', 'the two lamps swapping cleanly in time; at the fastest step a little '
             'blur is normal (Hue updates about 25 times a second). Mild flashing ahead.')
        for hz in (1, 2, 4):
            say('   %d swap%s a second' % (hz, '' if hz == 1 else 's'))
            _hold(s, 4, lambda t, hz=hz: [FEELINGS[2][0] if (int(t * hz) + i) % 2 == 0 else (0, 0, 0)
                                         for i in range(n)], sp)

        step('7. A TASTE OF THE SHOW', 'a slow wash from nostalgia through hope to triumph')
        def wash(t):
            st = min(t / 12 * 2, 2.0)
            k = int(min(st, 1.999))
            fr = st - k
            out = []
            for i in range(n):
                a = FEELINGS[k][i % 2]
                b = FEELINGS[min(k + 1, 2)][i % 2]
                out.append(tuple(x + (y - x) * fr for x, y in zip(a, b)))
            return out
        _hold(s, 12, wash, sp)
    except KeyboardInterrupt:
        say('\nStopped early.')
    finally:
        s.stop()
    say('\nDONE. The lamps are back under normal Hue control.')
    say('If 2 (feelings), 3 (deep violet / blue) and 4 (smooth fade) looked right,')
    say('these bulbs are good for the show -- open the rest.')


# ---- flicker protection (identical copy in hue_engine.py and hue_stream.py) ----------
class FlashLimiter:
    """Lets the lamps react instantly -- a drop, a kick, a scene change --
    but never lets them FLASH faster than `max_flashes` times a second
    (capped at 3, the photosensitive-epilepsy limit).

    A flash is a big change one way and then back again (dark-bright-dark,
    or red-blue-red). For every lamp its red, green, blue and brightness --
    and the brightness of the room as a whole -- may only turn round like
    that once every 1 / (2 x max_flashes) seconds, so flashes can never
    bunch up. Changes that keep going the same way (fades, a single hit, a
    scene change) are always free. Something that isn't allowed to turn
    round yet simply holds close to where it is for a moment."""
    THR = 0.08                                   # what counts as a big change (linear light)

    def __init__(self, max_flashes=2.0):
        self.set_rate(max_flashes)
        self.n = -1
        self.held = False

    def set_rate(self, max_flashes):
        self.f = max(0.5, min(3.0, float(max_flashes)))
        self.gap = 1.0 / (2.0 * self.f) + 0.03   # shortest time between two turn-rounds

    @staticmethod
    def lin(v):
        return max(0.0, min(1.0, v)) ** 2.2

    @staticmethod
    def unlin(v):
        return max(0.0, min(1.0, v)) ** (1 / 2.2)

    @staticmethod
    def lum(c):
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    @classmethod
    def sig(cls, c):          # what is watched per lamp: R, G, B, brightness, and the bulb's own level
        return (c[0], c[1], c[2], cls.lum(c), max(c[0], c[1], c[2]))

    def _reset(self, lt):
        self.n = len(lt)
        self.y = [list(c) for c in lt]
        self.trk = [[{'ext': v, 'dir': 0, 'last': -1e9} for v in self.sig(c)] for c in lt]
        r = sum(self.lum(c) for c in lt) / max(1, self.n)
        self.room = {'ext': r, 'dir': 0, 'last': -1e9}

    @classmethod
    def _rev(cls, st, x):
        """None, or (new_dir, bound) if moving a watched value to x turns it round."""
        if st['dir'] >= 0 and x < st['ext'] - cls.THR:
            return -1, st['ext'] - cls.THR * 0.98
        if st['dir'] <= 0 and x > st['ext'] + cls.THR:
            return 1, st['ext'] + cls.THR * 0.98
        return None

    @classmethod
    def _book(cls, st, x, now):
        """Update a watched value. A turn counts as 'still happening' until it
        has swung twice the threshold, so whatever size of change someone
        measures, turn-rounds stay at least `gap` apart."""
        r = cls._rev(st, x)
        if r is not None:
            st['pext'], st['dir'], st['ext'], st['last'] = st['ext'], r[0], x, now
            return True
        moved = (st['dir'] > 0 and x > st['ext']) or (st['dir'] < 0 and x < st['ext'])
        if moved:
            st['ext'] = x
            if abs(x - st.get('pext', x)) < 2 * cls.THR:
                st['last'] = now
        return False

    def _ok(self, i, c, now):
        """True if showing colour c on lamp i turns nothing round too soon."""
        for st, v in zip(self.trk[i], self.sig(c)):
            if now - st['last'] < self.gap and self._rev(st, v) is not None:
                return False
        return True

    @staticmethod
    def _limit(p, t, bound):
        """largest share (0..1) of the way from p to t that stays inside bound"""
        if abs(t - p) < 1e-12:
            return 1.0
        return max(0.0, min(1.0, (bound - p) / (t - p)))

    def step(self, targets, now):
        lt = [[self.lin(v) for v in c[:3]] for c in targets]
        if len(lt) != self.n:
            self._reset(lt)
            return [tuple(self.unlin(v) for v in c) for c in lt]

        # 1. each lamp: may it turn round now? if not, go only part of the way
        self.held = False
        cand = []
        for i, (p, t) in enumerate(zip(self.y, lt)):
            a = 1.0
            for k, (st, ps, ts) in enumerate(zip(self.trk[i], self.sig(p), self.sig(t))):
                if now - st['last'] >= self.gap:
                    continue
                r = self._rev(st, ts)
                if r is not None:
                    if k < 4:                            # these change in a straight line
                        a = min(a, self._limit(ps, ts, r[1]))
                    else:                                # the bulb level (max of R, G, B) doesn't: search
                        lo, hi = 0.0, 1.0
                        for _ in range(14):
                            m = (lo + hi) / 2
                            v = self.sig([x + (y - x) * m for x, y in zip(p, t)])[k]
                            if (v >= r[1]) if r[0] < 0 else (v <= r[1]):
                                lo = m
                            else:
                                hi = m
                        a = min(a, lo)
            self.held = self.held or a < 0.999
            cand.append([x + (y - x) * a for x, y in zip(p, t)])

        # 2. the room as a whole (all lamps added up): same rule
        a = 1.0
        if now - self.room['last'] < self.gap:
            rp = sum(self.lum(c) for c in self.y) / self.n
            rt = sum(self.lum(c) for c in cand) / self.n
            r = self._rev(self.room, rt)
            if r is not None:
                a = self._limit(rp, rt, r[1])
                self.held = self.held or a < 0.999
        out = [[x + (y - x) * a for x, y in zip(p, c)] for p, c in zip(self.y, cand)]

        # 2b. the bulb level (max of R, G, B) can dip part-way between two colours (red -> blue),
        # so check every lamp where it actually lands, and pull it back if that would be a turn
        for _ in range(4):
            bad = False
            for i, c in enumerate(out):
                if self._ok(i, c, now):
                    continue
                bad = True
                p, lo, hi = self.y[i], 0.0, 1.0
                for _ in range(16):
                    m = (lo + hi) / 2
                    if self._ok(i, [x + (y - x) * m for x, y in zip(p, c)], now):
                        lo = m
                    else:
                        hi = m
                out[i] = [x + (y - x) * lo for x, y in zip(p, c)]
                self.held = True
            if now - self.room['last'] < self.gap and \
                    self._rev(self.room, sum(self.lum(c) for c in out) / self.n) is not None:
                bad = True
                rp = sum(self.lum(c) for c in self.y) / self.n
                rt = sum(self.lum(c) for c in out) / self.n
                r = self._rev(self.room, rt)
                k = self._limit(rp, rt, r[1])
                out = [[x + (y - x) * k for x, y in zip(p, c)] for p, c in zip(self.y, out)]
                self.held = True
            if not bad:
                break
        else:
            if any(not self._ok(i, c, now) for i, c in enumerate(out)) or (
                    now - self.room['last'] < self.gap and
                    self._rev(self.room, sum(self.lum(c) for c in out) / self.n) is not None):
                out = [list(c) for c in self.y]          # can't settle it: hold everything this frame

        # 3. book-keeping with what the lamps really show
        for i, c in enumerate(out):
            for st, v in zip(self.trk[i], self.sig(c)):
                self._book(st, v, now)
        self._book(self.room, sum(self.lum(c) for c in out) / self.n, now)
        self.y = out
        return [tuple(self.unlin(v) for v in c) for c in out]
# ---- end of flicker protection ---------------------------------------------------------


def cmd_run(args):
    cfg = load_config()
    if args.ip:
        cfg['ip'] = args.ip
    s = Streamer(cfg, args.area, args.colour)
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(('127.0.0.1', args.port))
    rx.settimeout(0.02)
    say('Streaming to "%s" (%d lamps). Listening for TouchDesigner on 127.0.0.1:%d'
        % (s.name, len(s.channels), args.port))
    say('Ctrl+C to stop (the lights go back to normal Hue control).')
    safe = FlashLimiter(args.max_flashes)
    say('Flicker protection on: no lamp can flash more than %g times a second.' % safe.f)
    s.start()
    cols = [(0.0, 0.0, 0.0)] * len(s.channels)
    last_rx, last_tx, warned = time.time(), 0.0, False
    start_rx = last_rx
    owner, seen, others_warned = None, set(), 0.0   # follow ONE TouchDesigner: the newest one
    try:
        while True:
            try:
                data, addr = rx.recvfrom(65535)
                now = time.time()
                if addr not in seen:                     # a project just started (or was updated)
                    seen.add(addr)
                    if owner is not None:
                        say('  A new TouchDesigner sender appeared (port %d) -- following it now.' % addr[1])
                    owner = addr
                elif addr != owner:
                    if now - last_rx < 1.0:
                        if now - others_warned > 10.0:
                            say('  NOTE: two TouchDesigner projects are sending colours. Following port %d,'
                                ' ignoring port %d. Close the other project or set its hue_rig'
                                ' "Send to the Lights" off.' % (owner[1], addr[1]))
                            others_warned = now
                        continue
                    say('  Following TouchDesigner on port %d now.' % addr[1])
                    owner = addr
                if warned or last_rx == start_rx:
                    say('  Receiving colours from TouchDesigner (port %d).' % addr[1])
                msg = json.loads(data.decode())
                got = msg.get('c', [])
                cols = [tuple(float(x) for x in c[:3]) for c in got][:len(s.channels)]
                cols += [(0.0, 0.0, 0.0)] * (len(s.channels) - len(cols))
                last_rx, warned = time.time(), False
            except socket.timeout:
                pass
            except (ValueError, KeyError, TypeError):
                pass
            now = time.time()
            if now - last_rx > 3.0 and not warned:
                say('  (nothing from TouchDesigner for 3 s -- holding the last colours)')
                warned = True
            if now - last_tx >= 0.02:                            # 50 messages a second
                s.send(safe.step(cols, now))
                last_tx = now
    except KeyboardInterrupt:
        say('\nStopping ...')
    finally:
        s.stop()
        say('Stopped.')


# ---- colours: compare TouchDesigner's colours with the real lamps ---------------------------
SWATCHES = [('red', (1.0, 0.0, 0.0)), ('orange', (1.0, 0.5, 0.0)), ('yellow', (1.0, 0.9, 0.0)),
            ('green', (0.0, 1.0, 0.0)), ('cyan', (0.0, 1.0, 1.0)), ('blue', (0.0, 0.0, 1.0)),
            ('violet', (0.55, 0.0, 1.0)), ('magenta', (1.0, 0.0, 1.0)), ('pink', (1.0, 0.4, 0.7)),
            ('warm white', (1.0, 0.75, 0.45)), ('white', (1.0, 1.0, 1.0))]


def cmd_colours(args):
    cfg = load_config()
    if args.ip:
        cfg['ip'] = args.ip
    s = Streamer(cfg, args.area, args.colour)
    say('Colour check on "%s" (%s colour): every lamp shows the same colour for 3 s.'
        % (s.name, 'precise xy' if args.colour == 'xy' else 'plain RGB'))
    say('Compare with the same colour on a TouchDesigner Constant TOP.')
    s.start()
    try:
        for name, c in SWATCHES:
            say('   %-10s  (%.2f, %.2f, %.2f)' % (name, c[0], c[1], c[2]))
            t0 = time.time()
            while (time.time() - t0) * args.speed < 3.0:
                s.send([c] * len(s.channels))
                time.sleep(0.02)
    finally:
        s.stop()
    say('Done.')


def main():
    ap = argparse.ArgumentParser(description='Botanica Hue helper')
    ap.add_argument('command', choices=['pair', 'areas', 'scan', 'test', 'check', 'run', 'colours'])
    ap.add_argument('--ip')
    ap.add_argument('--area')
    ap.add_argument('--port', type=int, default=7010)
    ap.add_argument('--max-flashes', type=float, default=3.0,
                    help='flicker protection: most flashes per second a lamp may make (0.5-3, default 3;'
                         ' the Flicker Guard in TouchDesigner sets the show value, up to this)')
    ap.add_argument('--colour', choices=['xy', 'rgb'], default='xy',
                    help='how colours are sent: xy = precise (default), rgb = the old way')
    ap.add_argument('--speed', type=float, default=1.0, help=argparse.SUPPRESS)   # for testing
    args = ap.parse_args()
    {'pair': cmd_pair, 'areas': cmd_areas, 'test': cmd_test, 'check': cmd_check,
     'run': cmd_run, 'colours': cmd_colours, 'scan': cmd_scan}[args.command](args)


if __name__ == '__main__':
    main()
