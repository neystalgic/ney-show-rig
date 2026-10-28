#!/usr/bin/env python3
"""NEY DMX NODE -- runs on the Zephyrus (white desk), drives the Enttec Open DMX USB.

    Hue Hub (Mac)  --Art-Net over Wi-Fi / Tailscale-->  this node  --USB-->  Enttec  --DMX-->  4 moving heads

The node is the LAST word on safety, whatever sends it data:
  * the heads' built-in strobe is never used (master channel kept in 8-134 dimming, or 0 = off)
  * auto / sound programs, colour macros and the reset channel are locked off
  * every head's tilt stays inside its calibrated window (beams above head height), pan inside its window
  * a head that hasn't been calibrated stays DARK (it can still move, for calibration)
  * flash guard: no head can turn round brighter/darker more than 3 times a second
  * channels past the 4 heads (the laser bar, later) stay at 0 until it has a profile
  * if the hub goes quiet for 2 s the heads fade to dark over 2 s and hold their position

Run:   python dmx_node.py                (finds the Enttec through the FTDI D2XX driver)
       python dmx_node.py --serial COM4  (through the FTDI virtual COM port instead; /dev/cu.usbserial-* on a Mac)
       python dmx_node.py --sim          (no hardware: everything else works, for testing)
Phone page (calibration + live view):  http://<this computer>:7060/
"""
import argparse
import json
import os
import socket
import struct
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import ipaddress
import math

HERE = os.path.dirname(os.path.abspath(__file__))                  # ...\NeyDMX\app
ROOT = os.path.dirname(HERE) if os.path.basename(HERE).lower() == 'app' else HERE
CFG_DIR = os.path.join(ROOT, 'config')
CFG_PATH = os.path.join(CFG_DIR, 'heads_config.json')              # your calibration lives here
OLD_CFGS = [os.path.join(HERE, 'heads_config.json'), os.path.join(ROOT, 'heads_config.json')]
ARTNET_PORT = 6454
HTTP_PORT = 7060

# ---------------------------------------------------------------- the fixture
# Betopper LM70S, 14-channel mode (offsets from the head's start address)
LM70S_14 = dict(pan=0, pan_fine=1, tilt=2, tilt_fine=3, speed=4, master=5, r=6, g=7, b=8, w=9,
                preset=10, preset_speed=11, auto=12, reset=13)
FOOTPRINT = 14
PAN_DEG, TILT_DEG = 540.0, 180.0
MASTER_MIN, MASTER_MAX = 8, 134          # dimming range; 135-239 is the built-in strobe -- never

DEFAULT_HEADS = [
    dict(name='Head 1 (white desk side table)', addr=1),
    dict(name='Head 2 (kitchen cube shelf)', addr=15),
    dict(name='Head 3 (couch corner table)', addr=29),
    dict(name='Head 4 (rolly desk)', addr=43),
]
HEAD_DEFAULTS = dict(calibrated=False,
                     tilt_up=32768,        # 16-bit tilt value where the beam points straight up (calibrate!)
                     tilt_dir=1,           # +1 / -1: which way more tilt leans the beam over
                     tilt_max_deg=35.0,    # how far from straight up the beam may lean (keeps it above heads)
                     pan_min=0, pan_max=65535,  # allowed pan window (16-bit)
                     motor_speed=0,        # fixture's own pan/tilt speed channel (the hub already moves slowly)
                     max_level=1.0,        # brightness cap for this head (0..1)
                     avoid=[])             # directions the beam must never lean toward: [{az, width}] in pan degrees
AVOID_LEAN = 4.0          # inside an avoid zone the beam may lean at most this far from straight up (degrees)


def in_avoid(h, pan16, lean_deg):
    """Is a beam at this pan, leaning lean_deg (+ = the head's lean direction), pointing into an avoid zone?"""
    if abs(lean_deg) <= AVOID_LEAN:
        return False
    az = (pan16 * PAN_DEG / 65535.0 + (180.0 if lean_deg < 0 else 0.0)) % 360.0
    return any(abs((az - float(z['az']) + 180.0) % 360.0 - 180.0) < float(z['width']) / 2.0 for z in h.get('avoid') or [])


def load_cfg():
    if not os.path.exists(CFG_PATH):                                  # bring over the calibration from the old layout
        for old in OLD_CFGS:
            if os.path.exists(old):
                os.makedirs(CFG_DIR, exist_ok=True)
                with open(old) as f, open(CFG_PATH, 'w') as g:
                    g.write(f.read())
                break
    try:
        with open(CFG_PATH) as f:
            c = json.load(f)
    except Exception:
        c = {}
    heads = c.get('heads') or [dict(h) for h in DEFAULT_HEADS]
    for h in heads:
        for k, v in HEAD_DEFAULTS.items():
            h.setdefault(k, v)
    c['heads'] = heads
    c.setdefault('universe', 0)
    c.setdefault('fps', 30)
    return c


def save_cfg(c):
    os.makedirs(CFG_DIR, exist_ok=True)
    tmp = CFG_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(c, f, indent=1)
    os.replace(tmp, CFG_PATH)


def tilt_window(h):
    span = h['tilt_max_deg'] / TILT_DEG * 65535.0
    return max(0, int(h['tilt_up'] - span)), min(65535, int(h['tilt_up'] + span))


# ---------------------------------------------------------------- flash guard (per head, master + R G B)
class Guard:
    """A value may turn round (up-then-down or down-then-up by a big step) at most 3 times a second."""
    THR = 20                          # a 'big' change in DMX units
    GAP = 1.0 / 6.0 + 0.03            # 3 flashes/s = 6 turn-rounds/s

    def __init__(self):
        self.st = {}

    def step(self, key, v, now):
        s = self.st.get(key)
        if s is None:
            self.st[key] = dict(out=v, ext=v, dir=0, last=-1e9)
            return v
        d = v - s['ext']
        if abs(d) >= self.THR:
            nd = 1 if d > 0 else -1
            if s['dir'] != 0 and nd != s['dir'] and now - s['last'] < self.GAP:
                return s['out']          # not allowed to turn round yet: hold
            if nd != s['dir']:
                s['last'] = now
            s['dir'], s['ext'] = nd, v
        elif (s['dir'] > 0 and v > s['ext']) or (s['dir'] < 0 and v < s['ext']):
            s['ext'] = v
        s['out'] = v
        return v


# ---------------------------------------------------------------- outputs
class SimOut:
    name = 'simulation (no Enttec)'

    def send(self, frame):
        pass


class D2xxOut:
    """Enttec Open DMX USB through FTDI's D2XX driver (Windows default)."""
    def __init__(self):
        import ftd2xx  # pip install ftd2xx  (needs FTDI's D2XX driver -- Windows installs it for you)
        n = ftd2xx.listDevices() or []
        if not n:
            raise RuntimeError('no FTDI device found -- is the Enttec plugged in?')
        self.d = ftd2xx.open(0)
        self.d.resetDevice()
        self.d.setBaudRate(250000)
        self.d.setDataCharacteristics(8, 2, 0)      # 8 bits, 2 stop bits, no parity
        self.d.setFlowControl(0, 0, 0)
        self.d.clrRts()
        self.d.purge(1 | 2)
        self.name = 'Enttec Open DMX USB (D2XX: %s)' % (n[0].decode(errors='ignore') if isinstance(n[0], bytes) else n[0])

    def send(self, frame):
        self.d.setBreakOn()
        time.sleep(0.0002)
        self.d.setBreakOff()
        self.d.write(bytes([0]) + bytes(frame))


class SerialOut:
    """Enttec Open DMX USB through the FTDI virtual COM port (pyserial). Works on Windows, Mac and Linux."""
    def __init__(self, port):
        import serial  # pip install pyserial
        self.s = serial.Serial(port, 250000, bytesize=8, parity='N', stopbits=2, timeout=0)
        self.name = 'Enttec Open DMX USB (serial %s)' % port

    def send(self, frame):
        self.s.break_condition = True
        time.sleep(0.0002)
        self.s.break_condition = False
        self.s.write(bytes([0]) + bytes(frame))
        self.s.flush()


# ---------------------------------------------------------------- the node
class Node:
    def __init__(self, out, allow_any=False):
        self.out = out
        self.cfg = load_cfg()
        self.lock = threading.Lock()
        self.inbuf = bytearray(512)          # last frame from the hub (before safety)
        self.outbuf = bytearray(512)         # what actually goes to the Enttec
        self.last_rx = 0.0
        self.rx_from = ''
        self.rx_count = 0
        self.fade = 1.0                      # watchdog fade (1 = hub alive)
        self.guard = Guard()
        self.calib = {}                      # head index -> dict(pan, tilt, until)
        self.allow_any = allow_any
        self.err = ''
        self.sent_frames = 0

    # who may send us DMX: this computer, the home network, Tailscale
    def allowed(self, ip):
        if self.allow_any:
            return True
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return a.is_loopback or a.is_private or a in ipaddress.ip_network('100.64.0.0/10')

    def rx_loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', ARTNET_PORT))
        while True:
            data, (ip, _) = s.recvfrom(1024)
            if len(data) < 18 or data[:8] != b'Art-Net\x00' or not self.allowed(ip):
                continue
            op = struct.unpack('<H', data[8:10])[0]
            if op != 0x5000:
                continue
            uni = data[14] | ((data[15] & 0x7F) << 8)
            n = min(512, struct.unpack('>H', data[16:18])[0])
            if uni != int(self.cfg.get('universe', 0)):
                continue
            with self.lock:
                self.inbuf[:n] = data[18:18 + n]
                self.last_rx = time.time()
                self.rx_from = ip
                self.rx_count += 1

    def safe_frame(self, now):
        """Apply every safety rule to the hub's frame and return what may go to the fixtures."""
        out = bytearray(512)
        alive = now - self.last_rx < 2.0
        target = 1.0 if alive else 0.0
        self.fade += max(-0.5 / self.cfg['fps'], min(1.0 / self.cfg['fps'], target - self.fade))   # out over 2 s
        for i, h in enumerate(self.cfg['heads']):
            a = int(h['addr']) - 1
            if a < 0 or a + FOOTPRINT > 512:
                continue
            src = self.inbuf[a:a + FOOTPRINT]
            ch = LM70S_14
            pan = (src[ch['pan']] << 8) | src[ch['pan_fine']]
            tilt = (src[ch['tilt']] << 8) | src[ch['tilt_fine']]
            master = src[ch['master']]
            rgbw = [src[ch[k]] for k in ('r', 'g', 'b', 'w')]
            cal = self.calib.get(i)
            if cal and now < cal['until']:                 # calibration: you're steering it from the phone
                pan, tilt = cal['pan'], cal['tilt']
                master, rgbw = MASTER_MIN + 30, [0, 90, 255, 0]   # soft blue, dim -- never white
            elif cal:
                self.calib.pop(i, None)
            else:
                if not h['calibrated']:
                    master = 0                                 # uncalibrated heads stay dark
                if not alive:                                  # no hub: point straight up, keep the last pan
                    tilt = int(h['tilt_up'])
                    pan = (self.outbuf[a + ch['pan']] << 8) | self.outbuf[a + ch['pan_fine']]
                lo, hi = tilt_window(h)
                tilt = max(lo, min(hi, tilt))
                pan = max(int(h['pan_min']), min(int(h['pan_max']), pan))
                lean = (tilt - int(h['tilt_up'])) * int(h['tilt_dir']) * TILT_DEG / 65535.0
                if in_avoid(h, pan, lean):              # toward the projection etc.: pull the beam back up
                    lim = AVOID_LEAN * 65535.0 / TILT_DEG
                    tilt = int(h['tilt_up'] + math.copysign(lim, tilt - int(h['tilt_up'])))
            # master: off, or the dimming range -- never the strobe range
            if master < MASTER_MIN:
                master = 0
            else:
                lvl = (min(master, MASTER_MAX) - MASTER_MIN) / float(MASTER_MAX - MASTER_MIN)
                lvl *= max(0.0, min(1.0, float(h.get('max_level', 1.0)))) * (1.0 if cal else self.fade)
                master = 0 if lvl <= 0.004 else int(round(MASTER_MIN + lvl * (MASTER_MAX - MASTER_MIN)))
            master = self.guard.step((i, 'm'), master, now)
            rgbw = [self.guard.step((i, k), v, now) for k, v in zip('rgbw', rgbw)]
            o = out[a:a + FOOTPRINT]
            o[ch['pan']], o[ch['pan_fine']] = pan >> 8, pan & 255
            o[ch['tilt']], o[ch['tilt_fine']] = tilt >> 8, tilt & 255
            o[ch['speed']] = max(0, min(255, int(h.get('motor_speed', 0))))
            o[ch['master']] = master
            for k, v in zip(('r', 'g', 'b', 'w'), rgbw):
                o[ch[k]] = v
            o[ch['preset']] = 0          # no colour macros (they can flash)
            o[ch['preset_speed']] = 0
            o[ch['auto']] = 0            # no auto / sound-active programs
            o[ch['reset']] = 0           # never reset mid-show
            out[a:a + FOOTPRINT] = o
        return out                       # everything else (laser bar etc.) stays 0

    def tx_loop(self):
        period = 1.0 / max(10, min(44, self.cfg['fps']))
        while True:
            t = time.time()
            with self.lock:
                frame = self.safe_frame(t)
                self.outbuf = frame
            try:
                self.out.send(frame)
                self.sent_frames += 1
                self.err = ''
            except Exception as e:
                self.err = str(e)
                time.sleep(1.0)
            time.sleep(max(0.0, period - (time.time() - t)))

    def status(self):
        now = time.time()
        heads = []
        for i, h in enumerate(self.cfg['heads']):
            a = int(h['addr']) - 1
            o = self.outbuf[a:a + FOOTPRINT]
            ch = LM70S_14
            heads.append(dict(name=h['name'], addr=h['addr'], calibrated=h['calibrated'],
                              pan=(o[ch['pan']] << 8) | o[ch['pan_fine']], tilt=(o[ch['tilt']] << 8) | o[ch['tilt_fine']],
                              master=o[ch['master']], rgbw=[o[ch[k]] for k in ('r', 'g', 'b', 'w')],
                              calibrating=i in self.calib))
        return dict(output=self.out.name, error=self.err, hub_alive=now - self.last_rx < 2.0,
                    hub=self.rx_from, frames_in=self.rx_count, frames_out=self.sent_frames,
                    last_in_s=round(now - self.last_rx, 1) if self.last_rx else None, fade=round(self.fade, 2), heads=heads)


def make_handler(node):
    page = os.path.join(HERE, 'node_page.html')
    desk = os.path.join(HERE, 'heads_desk.html')

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype='application/json'):
            b = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if not node.allowed(self.client_address[0]):
                return self.send(403, '{"error":"not allowed"}')
            p = self.path.split('?')[0]
            if p == '/status':
                with node.lock:
                    return self.send(200, json.dumps(node.status()))
            if p == '/config':
                with node.lock:
                    return self.send(200, json.dumps(node.cfg))
            if p in ('/', '/index.html', '/desk', '/desk.html'):
                with open(desk if p.startswith('/desk') else page, 'rb') as f:
                    return self.send(200, f.read(), 'text/html; charset=utf-8')
            return self.send(404, '{"error":"not found"}')

        def do_POST(self):
            if not node.allowed(self.client_address[0]):
                return self.send(403, '{"error":"not allowed"}')
            n = min(int(self.headers.get('Content-Length', 0) or 0), 20000)
            try:
                b = json.loads(self.rfile.read(n) or b'{}')
                i = int(b.get('head', -1))
            except Exception:
                return self.send(400, '{"error":"bad json"}')
            p = self.path.split('?')[0]
            with node.lock:
                heads = node.cfg['heads']
                if not 0 <= i < len(heads):
                    return self.send(400, '{"error":"no such head"}')
                h = heads[i]
                if p == '/calib':            # steer a head (dim soft blue) for the next 60 s
                    if b.get('stop'):
                        node.calib.pop(i, None)
                    else:
                        node.calib[i] = dict(pan=max(0, min(65535, int(b['pan']))), tilt=max(0, min(65535, int(b['tilt']))),
                                             until=time.time() + 60)
                    return self.send(200, '{"ok":true}')
                if p == '/head':             # save calibration values for one head
                    for k, lo, hi in (('tilt_up', 0, 65535), ('pan_min', 0, 65535), ('pan_max', 0, 65535),
                                      ('tilt_max_deg', 0, 60), ('motor_speed', 0, 255), ('max_level', 0, 1), ('addr', 1, 499)):
                        if k in b:
                            h[k] = max(lo, min(hi, float(b[k]) if k in ('tilt_max_deg', 'max_level') else int(b[k])))
                    if 'tilt_dir' in b:
                        h['tilt_dir'] = 1 if int(b['tilt_dir']) >= 0 else -1
                    if isinstance(b.get('avoid'), list):
                        h['avoid'] = [dict(az=float(z['az']) % 360.0, width=max(5.0, min(180.0, float(z.get('width', 60)))))
                                      for z in b['avoid'][:6] if isinstance(z, dict) and 'az' in z]
                    if 'calibrated' in b:
                        h['calibrated'] = bool(b['calibrated'])
                    if h['pan_min'] > h['pan_max']:
                        h['pan_min'], h['pan_max'] = h['pan_max'], h['pan_min']
                    save_cfg(node.cfg)
                    return self.send(200, json.dumps(h))
            return self.send(404, '{"error":"not found"}')
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true', help='no hardware')
    ap.add_argument('--serial', default='', help='use the FTDI virtual COM port (e.g. COM4, /dev/cu.usbserial-XXXX)')
    a = ap.parse_args()
    if a.sim:
        out = SimOut()
    elif a.serial:
        out = SerialOut(a.serial)
    else:
        out = D2xxOut()
    node = Node(out)
    if not os.path.exists(CFG_PATH):
        save_cfg(node.cfg)
    threading.Thread(target=node.rx_loop, daemon=True).start()
    threading.Thread(target=node.tx_loop, daemon=True).start()
    print('Ney DMX node: %s' % out.name)
    print('  listening for the hub (Art-Net) on UDP %d, universe %d' % (ARTNET_PORT, node.cfg['universe']))
    print('  Heads Desk (computer): http://%s:%d/desk   phone page: http://%s:%d/' % (socket.gethostname(), HTTP_PORT, socket.gethostname(), HTTP_PORT))
    print('  calibration file: %s' % CFG_PATH)
    ThreadingHTTPServer(('0.0.0.0', HTTP_PORT), make_handler(node)).serve_forever()


if __name__ == '__main__':
    main()
