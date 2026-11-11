#!/usr/bin/env python3
"""NEY DMX NODE -- runs on the Zephyrus (white desk), drives the Enttec Open DMX USB.

    Hue Hub (Mac)  --Art-Net over Wi-Fi / Tailscale-->  this node  --USB-->  Enttec  --DMX-->  4 moving heads

v2 (Nov 11): UNLOCKS. Michael decides how hard the rig runs. Node setting 'unlock' (POST /unlock):
  strobe -> the fixtures' own strobe is allowed (LM70S master 135-239, Focus Spot shutter / UV strobe 16-131),
            and the flash guard may go up to 25 flashes a second ('flash_hz')
  white  -> open white on the Focus Spots' colour wheel (the hub decides when to send white to the heads)
  wheels -> colour wheel spins at any speed
Still always locked: auto / sound programs, colour macros, reset (they fight the show), and every head's
calibrated geometry (tilt window, pan window, avoid zones for the mirror / screen / seated faces).

Without unlocks the node is the LAST word on safety, whatever sends it data:
  * the heads' built-in strobe is never used (master channel kept in 8-134 dimming, or 0 = off)
  * auto / sound programs, colour macros and the reset channel are locked off
  * every head's tilt stays inside its calibrated window (beams above head height), pan inside its window
  * a head that hasn't been calibrated stays DARK (it can still move, for calibration)
  * a head can be dimmed while it points nearly straight up (upright_level): Head 1's upright wash
    floods the projection wall at full brightness
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

# ADJ Focus Spot One, 17-channel mode (manual: pan 540 deg, tilt 240 deg). Gobo spot with a colour wheel + UV.
FOCUS_17 = dict(pan=0, pan_fine=1, tilt=2, tilt_fine=3, color=4, gobo=5, gobo_rot=6, focus=7, shutter=8,
                master=9, uv_strobe=10, uv=11, show=12, show_speed=13, dim_mode=14, speed=15, func=16)
TYPES = {'lm70s': dict(ch=LM70S_14, foot=14, pan_deg=540.0, tilt_deg=180.0),
         'focus17': dict(ch=FOCUS_17, foot=17, pan_deg=540.0, tilt_deg=240.0)}
SHUTTER_OPEN = 12          # Focus Spot shutter: 8-15 = open, 0-7 = closed, 16-131 = STROBE (never used)
FOCUS_BLUE = 37            # colour wheel slot used instead of open white (no white beams by default)


def ftype(h):
    return TYPES.get(h.get('type', 'lm70s'), TYPES['lm70s'])


def PD(h):
    return ftype(h)['pan_deg']


def TD(h):
    return ftype(h)['tilt_deg']
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
                     upright_level=1.0,    # brightness cap while the beam is near straight up (0..1, 1 = off)
                     upright_lean=20.0,    # 'near straight up' = leaning less than this; full again 15 deg further
                     avoid=[])             # directions the beam must never lean toward: [{az, width}] in pan degrees
AVOID_LEAN = 4.0          # inside an avoid zone the beam may lean at most this far from straight up (degrees)


def avoid_cap(h, pan16, lean_deg):
    """Largest lean allowed in this direction by the head's avoid zones (None = no zone here).
    Unsafe-area model: each zone says how far the beam may lean toward it (4 = basically upright)."""
    az = (pan16 * PD(h) / 65535.0 + (180.0 if lean_deg < 0 else 0.0)) % 360.0
    cap = None
    for z in h.get('avoid') or []:
        if abs((az - float(z['az']) + 180.0) % 360.0 - 180.0) < float(z['width']) / 2.0:
            zl = max(AVOID_LEAN, min(85.0, float(z.get('lean', AVOID_LEAN) or AVOID_LEAN)))
            cap = zl if cap is None else min(cap, zl)
    return cap


def in_avoid(h, pan16, lean_deg):
    """Is a beam at this pan, leaning lean_deg (+ = the head's lean direction), pointing into an avoid zone?"""
    if abs(lean_deg) <= AVOID_LEAN:
        return False
    az = (pan16 * PD(h) / 65535.0 + (180.0 if lean_deg < 0 else 0.0)) % 360.0
    for z in h.get('avoid') or []:                  # a zone may allow a small lean ('lean': ceiling only, above a screen)
        if abs((az - float(z['az']) + 180.0) % 360.0 - 180.0) < float(z['width']) / 2.0:
            if abs(lean_deg) > max(AVOID_LEAN, min(85.0, float(z.get('lean', AVOID_LEAN) or AVOID_LEAN))):
                return True
    return False


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
    u = c.setdefault('unlock', {})
    for k in ('strobe', 'white', 'wheels'):
        u.setdefault(k, False)
    return c


def save_cfg(c):
    os.makedirs(CFG_DIR, exist_ok=True)
    tmp = CFG_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(c, f, indent=1)
    os.replace(tmp, CFG_PATH)


def tilt_window(h):
    deg = max([float(h['tilt_max_deg'])] + [min(85.0, float(w.get('lean', 0))) for w in h.get('walls') or []])
    span = deg / TD(h) * 65535.0
    return max(0, int(h['tilt_up'] - span)), min(65535, int(h['tilt_up'] + span))


def lean_limit(h, pan16, lean_deg):
    """Max lean for the direction this beam points: the head's normal max, or more toward one of its WALLS
    (directions where its own wall is right behind it -- nobody can stand in the beam)."""
    lim = float(h['tilt_max_deg'])
    az = (pan16 * PD(h) / 65535.0 + (180.0 if lean_deg < 0 else 0.0)) % 360.0
    for w in h.get('walls') or []:
        if abs((az - float(w['az']) + 180.0) % 360.0 - 180.0) < float(w['width']) / 2.0:
            lim = max(lim, min(85.0, float(w.get('lean', 0))))
    return lim


# ---------------------------------------------------------------- flash guard (per head, master + R G B)
class Guard:
    """A value may turn round (up-then-down or down-then-up by a big step) at most flash_hz times a second
    (node setting 'flash_hz': 3 by default -- the photosensitive-epilepsy limit; Michael may raise it to 8 max)."""
    THR = 20                          # a 'big' change in DMX units
    GAP = 1.0 / 6.0 + 0.03            # 3 flashes/s = 6 turn-rounds/s
    hz = 3.0
    maxhz = 8.0                       # raised to 25 when strobe is unlocked

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
            gap = self.GAP if self.hz <= 3.0 else 1.0 / (2.0 * min(self.maxhz, self.hz)) + 0.005
            if s['dir'] != 0 and nd != s['dir'] and now - s['last'] < gap:
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
        self.s.rts = False        # the Enttec's line driver needs RTS CLEARED (D2XX does clrRts); pyserial sets it on open
        self.s.reset_output_buffer()
        self.name = 'Enttec Open DMX USB (serial %s)' % port

    def send(self, frame):
        # Linux / Mac: the FTDI chip keeps sending after flush() returns, so a BREAK sent straight away cut
        # into the end of the last frame and the heads threw every frame away (Pi, Nov 5). Proper DMX timing:
        self.s.break_condition = True
        time.sleep(0.0012)                    # BREAK (DMX needs >= 88 us; longer is fine)
        self.s.break_condition = False
        time.sleep(0.0001)                    # mark-after-break
        self.s.write(bytes([0]) + bytes(frame))
        self.s.flush()
        time.sleep(0.024)                     # 513 bytes at 250 kbaud = 22.6 ms on the wire: let it finish


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
        self.fx_state = {}                   # Focus Spot colour-wheel guard
        self.demo = {}                       # head index -> start time of the Focus Spot showcase
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

    DEMO_LEN = 90.0

    def demo_frame(self, h, t):
        """A 90 s Focus Spot showcase, CEILING ONLY: every value still goes through the safety rules after this
        (tilt window, no-go zones, colour + flash guards, no strobe / white)."""
        def tilt_at(lean):
            return int(h['tilt_up'] + int(h['tilt_dir']) * lean / TD(h) * 65535.0)

        def pan_at(deg):
            return max(0, min(65535, int(32768 + deg / PD(h) * 65535.0)))
        up = 0.6 * 255
        fade = min(1.0, t / 3.0, max(0.0, (self.DEMO_LEN - t) / 3.0))
        col = [15 + 7, 75 + 7, 30 + 7, 90 + 7, 45 + 7, 60 + 7]          # red, pink, blue, navy, green, yellow
        d = dict(pan=pan_at(0), tilt=tilt_at(0), master=int(up * fade), uv=0,
                 fx=dict(color=FOCUS_BLUE, gobo=15, gobo_rot=0, focus=128))
        fx = d['fx']
        if t < 10:                                     # sharpen: the gobo pulls into focus straight overhead
            fx['focus'] = int(40 + 180 * min(1.0, t / 8.0))
        elif t < 25:                                   # slow circles on the ceiling, gobo turning
            a = (t - 10) / 15.0 * 2 * math.pi
            d['pan'], d['tilt'] = pan_at(60 * math.sin(a)), tilt_at(22 * math.cos(a))
            fx.update(gobo=25, gobo_rot=170, focus=200, color=col[0])
        elif t < 40:                                   # colour + gobo steps (one change every 2.5 s)
            k = int((t - 25) / 2.5)
            fx.update(color=col[k % len(col)], gobo=10 * (1 + k % 6) + 5, gobo_rot=0, focus=200)
            d['tilt'] = tilt_at(15)
            d['pan'] = pan_at(-40 + 16 * k)
        elif t < 55:                                   # gobo wheel scrolling + counter-rotation, wide slow sweep
            a = (t - 40) / 15.0 * 2 * math.pi
            d['pan'], d['tilt'] = pan_at(90 * math.sin(a / 2)), tilt_at(28)
            fx.update(gobo=180, gobo_rot=210, color=col[2], focus=190)
        elif t < 65:                                   # focus breathing: crisp -> soft -> crisp
            fx.update(gobo=45, gobo_rot=175, color=col[1],
                      focus=int(128 + 100 * math.cos((t - 55) / 10.0 * 2 * math.pi)))
            d['tilt'] = tilt_at(10)
        elif t < 75:                                   # UV only: posters + tapestries glow
            d['master'], d['uv'] = 0, int(0.7 * 255 * fade)
            d['tilt'] = tilt_at(25)
            d['pan'] = pan_at(30 * math.sin((t - 65) / 10.0 * 2 * math.pi))
        else:                                          # slow colour-wheel spin, gobo 6, drifting home
            fx.update(color=180, gobo=65, gobo_rot=200, focus=200)
            d['tilt'] = tilt_at(12 * max(0.0, (self.DEMO_LEN - t) / 15.0))
        return d

    def focus_fx(self, i, h, fx, now):
        """Focus Spot colour / gobo rules: no open white (unless allow_white), the colour wheel only spins
        slowly, and fixed colour changes at most flash_hz a second (a wheel snapping colours is a flicker too)."""
        c = int(fx.get('color', FOCUS_BLUE))
        un = self.cfg.get('unlock', {})
        if c < 15 and not (h.get('allow_white') or un.get('white')):
            c = FOCUS_BLUE
        if not un.get('wheels'):
            if 128 <= c < 170:                   # clockwise spin, fast..slow -> slow half only
                c = 170
            elif c > 213:                        # counter-clockwise, slow..fast -> slow half only
                c = 213
        st = self.fx_state.setdefault(i, dict(color=c, t=0.0))
        gap = 1.0 / max(1.0, float(self.cfg.get('flash_hz', 3.0)))
        if c != st['color'] and c < 128 and st['color'] < 128 and now - st['t'] < gap:
            c = st['color']                      # too soon after the last colour snap: hold
        elif c != st['color']:
            st['color'], st['t'] = c, now
        return dict(color=c, gobo=int(fx.get('gobo', 0)), gobo_rot=int(fx.get('gobo_rot', 0)),
                    focus=int(fx.get('focus', 128)))

    def safe_frame(self, now):
        """Apply every safety rule to the hub's frame and return what may go to the fixtures."""
        out = bytearray(512)
        alive = now - self.last_rx < 2.0
        target = 1.0 if alive else 0.0
        self.fade += max(-0.5 / self.cfg['fps'], min(1.0 / self.cfg['fps'], target - self.fade))   # out over 2 s
        for i, h in enumerate(self.cfg['heads']):
            a = int(h['addr']) - 1
            ft = ftype(h)
            foot, ch, TDh = ft['foot'], ft['ch'], ft['tilt_deg']
            is_f = h.get('type') == 'focus17'
            if a < 0 or a + foot > 512:
                continue
            src = self.inbuf[a:a + foot]
            pan = (src[ch['pan']] << 8) | src[ch['pan_fine']]
            tilt = (src[ch['tilt']] << 8) | src[ch['tilt_fine']]
            master = src[ch['master']]
            rgbw = [src[ch[k]] for k in ('r', 'g', 'b', 'w')] if not is_f else [0, 0, 0, 0]
            uv = src[ch['uv']] if is_f else 0
            shut_in = src[ch['shutter']] if is_f else 0
            uvs_in = src[ch['uv_strobe']] if is_f else 0
            fx = dict(color=src[ch['color']], gobo=src[ch['gobo']], gobo_rot=src[ch['gobo_rot']],
                      focus=src[ch['focus']]) if is_f else {}
            dm = self.demo.get(i)
            if dm is not None:
                if is_f and h['calibrated'] and now - dm < self.DEMO_LEN:
                    d = self.demo_frame(h, now - dm)
                    pan, tilt, master, uv, fx = d['pan'], d['tilt'], d['master'], d['uv'], d['fx']
                else:
                    self.demo.pop(i, None)
            cal = self.calib.get(i)
            up_k = 1.0                                         # upright dimming (1 = none)
            if cal and now < cal['until']:                 # calibration: you're steering it from the phone
                pan, tilt = cal['pan'], cal['tilt']
                master, rgbw = MASTER_MIN + 30, [0, 90, 255, 0]   # soft blue, dim -- never white
                if is_f:                                       # spot: ~20 %, blue, open gobo, mid focus
                    master, uv = 50, 0
                    fx = dict(color=FOCUS_BLUE, gobo=0, gobo_rot=0, focus=int(cal.get('focus', 128)))
                    if cal.get('uv'):                          # UV look-around: UV only, no visible beam
                        master, uv = 0, int(cal['uv'])
                    if cal.get('gobo') is not None:
                        fx['gobo'] = int(cal['gobo'])
            elif cal:
                self.calib.pop(i, None)
            else:
                if not h['calibrated']:
                    master = 0                                 # uncalibrated heads stay dark
                    uv = 0
                if not alive:                                  # no hub: point straight up, keep the last pan
                    tilt = int(h['tilt_up'])
                    pan = (self.outbuf[a + ch['pan']] << 8) | self.outbuf[a + ch['pan_fine']]
                lo, hi = tilt_window(h)
                tilt = max(lo, min(hi, tilt))
                pan = max(int(h['pan_min']), min(int(h['pan_max']), pan))
                lean = (tilt - int(h['tilt_up'])) * int(h['tilt_dir']) * TDh / 65535.0
                lim_ = lean_limit(h, pan, lean)
                if abs(lean) > lim_:                    # beyond 'max lean' only toward one of its walls
                    tilt = int(h['tilt_up'] + math.copysign(lim_ / TDh * 65535.0, tilt - int(h['tilt_up'])))
                    lean = math.copysign(lim_, lean)
                cap = avoid_cap(h, pan, lean)           # toward an unsafe area: no further than that zone allows
                if cap is not None and abs(lean) > cap:
                    tilt = int(h['tilt_up'] + math.copysign(cap * 65535.0 / TDh, tilt - int(h['tilt_up'])))
                    lean = math.copysign(cap, lean)
                ul = max(0.0, min(1.0, float(h.get('upright_level', 1.0))))
                if ul < 1.0:                            # near straight up: dimmer, back to full 15 deg further over
                    x = (abs(lean) - float(h.get('upright_lean', 20.0))) / 15.0
                    up_k = ul + (1.0 - ul) * max(0.0, min(1.0, x))
            kcap = max(0.0, min(1.0, float(h.get('max_level', 1.0)))) * (1.0 if cal else self.fade * up_k)
            un = self.cfg.get('unlock', {})
            strobe_ok = bool(un.get('strobe')) and not cal
            self.guard.hz = float(self.cfg.get('flash_hz', 3.0))
            self.guard.maxhz = 25.0 if un.get('strobe') else 8.0
            if is_f:
                # Focus Spot: plain 0-255 dimmers (its strobe is a separate shutter channel, held open/closed)
                lvl = master / 255.0 * kcap
                master = 0 if lvl <= 0.004 else int(round(lvl * 255))
                ulv = uv / 255.0 * kcap
                uv = 0 if ulv <= 0.004 else int(round(ulv * 255))
                master = self.guard.step((i, 'm'), master, now)
                uv = self.guard.step((i, 'uv'), uv, now)
                fx = self.focus_fx(i, h, fx, now)
                o = out[a:a + foot]
                o[ch['pan']], o[ch['pan_fine']] = pan >> 8, pan & 255
                o[ch['tilt']], o[ch['tilt_fine']] = tilt >> 8, tilt & 255
                for k in ('color', 'gobo', 'gobo_rot', 'focus'):
                    o[ch[k]] = fx[k]
                o[ch['master']] = master
                # shutter: open / closed, or (strobe unlocked) the fixture's own strobe at the speed the hub asks
                o[ch['shutter']] = (shut_in if strobe_ok and 16 <= shut_in <= 131 else SHUTTER_OPEN) if master > 0 else 0
                o[ch['uv']] = uv
                o[ch['uv_strobe']] = (uvs_in if strobe_ok and 16 <= uvs_in <= 131 else SHUTTER_OPEN) if uv > 0 else 0
                o[ch['show']] = 0            # no built-in shows
                o[ch['show_speed']] = 0
                o[ch['dim_mode']] = 0        # standard dimmer curve
                o[ch['speed']] = max(0, min(255, int(h.get('motor_speed', 0))))
                o[ch['func']] = 0            # no reset / blackout tricks / sound-active
                out[a:a + foot] = o
                continue
            # master: off, the dimming range, or (strobe unlocked) the head's own strobe 135-239
            if strobe_ok and 135 <= master <= 239:
                rgbw = [int(round(v * kcap)) for v in rgbw]            # strobe speed in master, brightness in the colour
                rgbw = [self.guard.step((i, k), v, now) for k, v in zip('rgbw', rgbw)]
                o = out[a:a + foot]
                o[ch['pan']], o[ch['pan_fine']] = pan >> 8, pan & 255
                o[ch['tilt']], o[ch['tilt_fine']] = tilt >> 8, tilt & 255
                o[ch['speed']] = max(0, min(255, int(h.get('motor_speed', 0))))
                o[ch['master']] = master
                for k, v in zip(('r', 'g', 'b', 'w'), rgbw):
                    o[ch[k]] = v
                o[ch['preset']] = o[ch['preset_speed']] = o[ch['auto']] = o[ch['reset']] = 0
                out[a:a + foot] = o
                continue
            if master < MASTER_MIN:
                master = 0
            else:
                lvl = (min(master, MASTER_MAX) - MASTER_MIN) / float(MASTER_MAX - MASTER_MIN)
                lvl *= kcap
                master = 0 if lvl <= 0.004 else int(round(MASTER_MIN + lvl * (MASTER_MAX - MASTER_MIN)))
            master = self.guard.step((i, 'm'), master, now)
            rgbw = [self.guard.step((i, k), v, now) for k, v in zip('rgbw', rgbw)]
            o = out[a:a + foot]
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
            out[a:a + foot] = o
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
            ft = ftype(h)
            o = self.outbuf[a:a + ft['foot']]
            ch = ft['ch']
            d = dict(name=h['name'], addr=h['addr'], type=h.get('type', 'lm70s'), calibrated=h['calibrated'],
                     pan=(o[ch['pan']] << 8) | o[ch['pan_fine']], tilt=(o[ch['tilt']] << 8) | o[ch['tilt_fine']],
                     master=o[ch['master']], calibrating=i in self.calib)
            if 'r' in ch:
                d['rgbw'] = [o[ch[k]] for k in ('r', 'g', 'b', 'w')]
            else:
                d.update(color=o[ch['color']], gobo=o[ch['gobo']], focus=o[ch['focus']], uv=o[ch['uv']], rgbw=[0, 0, 0, 0])
            heads.append(d)
        return dict(output=self.out.name, error=self.err, hub_alive=now - self.last_rx < 2.0,
                    hub=self.rx_from, frames_in=self.rx_count, frames_out=self.sent_frames,
                    last_in_s=round(now - self.last_rx, 1) if self.last_rx else None, fade=round(self.fade, 2), heads=heads,
                    unlock=self.cfg.get('unlock', {}), flash_hz=self.cfg.get('flash_hz', 3.0), version='v2-nov11')


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
            if p == '/unlock':                 # node-wide unlocks (Michael's call): strobe / white / wheels / flash_hz
                with node.lock:
                    u = node.cfg.setdefault('unlock', {})
                    for k in ('strobe', 'white', 'wheels'):
                        if k in b:
                            u[k] = bool(b[k])
                    if 'flash_hz' in b:
                        node.cfg['flash_hz'] = max(1.0, min(25.0 if u.get('strobe') else 8.0, float(b['flash_hz'])))
                    save_cfg(node.cfg)
                    return self.send(200, json.dumps(dict(unlock=u, flash_hz=node.cfg.get('flash_hz', 3.0))))
            with node.lock:
                heads = node.cfg['heads']
                if p == '/head' and i == len(heads) and i < 12 and b.get('type') in TYPES and 'addr' in b:
                    nh = dict(name=str(b.get('name') or 'Fixture %d' % (i + 1))[:40], addr=int(b['addr']), type=b['type'])
                    for k, v in HEAD_DEFAULTS.items():
                        nh.setdefault(k, v if not isinstance(v, list) else list(v))
                    heads.append(nh)              # a new fixture starts uncalibrated = dark
                if not 0 <= i < len(heads):
                    return self.send(400, '{"error":"no such head"}')
                h = heads[i]
                if p == '/demo':             # Focus Spot showcase (90 s, ceiling only, needs tilt_up calibrated)
                    if b.get('stop'):
                        node.demo.pop(i, None)
                        return self.send(200, '{"ok":true}')
                    if h.get('type') != 'focus17' or not h['calibrated']:
                        return self.send(400, '{"error":"calibrate its straight-up first"}')
                    node.demo[i] = time.time()
                    return self.send(200, '{"ok":true,"seconds":%d}' % node.DEMO_LEN)
                if p == '/calib':            # steer a head (dim soft blue) for the next 60 s
                    if b.get('stop'):
                        node.calib.pop(i, None)
                    else:
                        node.calib[i] = dict(pan=max(0, min(65535, int(b['pan']))), tilt=max(0, min(65535, int(b['tilt']))),
                                             focus=max(0, min(255, int(b.get('focus', 128)))),
                                             uv=max(0, min(200, int(b.get('uv', 0) or 0))),
                                             gobo=(max(0, min(63, int(b['gobo']))) if b.get('gobo') is not None else None),
                                             until=time.time() + 60)
                    return self.send(200, '{"ok":true}')
                if p == '/head':             # save calibration values for one head
                    for k, lo, hi in (('tilt_up', 0, 65535), ('pan_min', 0, 65535), ('pan_max', 0, 65535),
                                      ('tilt_max_deg', 0, 85), ('motor_speed', 0, 255), ('max_level', 0, 1), ('addr', 1, 499),
                                      ('upright_level', 0, 1), ('upright_lean', 0, 85)):
                        if k in b:
                            h[k] = max(lo, min(hi, float(b[k]) if k in ('tilt_max_deg', 'max_level', 'upright_level',
                                                                        'upright_lean') else int(b[k])))
                    if 'tilt_dir' in b:
                        h['tilt_dir'] = 1 if int(b['tilt_dir']) >= 0 else -1
                    if isinstance(b.get('avoid'), list):
                        h['avoid'] = [dict(az=float(z['az']) % 360.0, width=max(5.0, min(180.0, float(z.get('width', 60)))),
                                           lean=max(AVOID_LEAN, min(85.0, float(z.get('lean', AVOID_LEAN) or AVOID_LEAN))))
                                      for z in b['avoid'][:16] if isinstance(z, dict) and 'az' in z]
                    if isinstance(b.get('walls'), list):
                        h['walls'] = [dict(az=float(z['az']) % 360.0, width=max(5.0, min(120.0, float(z.get('width', 60)))),
                                           lean=max(0.0, min(85.0, float(z.get('lean', 85)))))
                                      for z in b['walls'][:4] if isinstance(z, dict) and 'az' in z]
                    if 'calibrated' in b:
                        h['calibrated'] = bool(b['calibrated'])
                    if 'name' in b:
                        h['name'] = str(b['name'])[:40]
                    if b.get('type') in TYPES:
                        h['type'] = b['type']
                    if 'allow_white' in b:
                        h['allow_white'] = bool(b['allow_white'])
                    if int(h['addr']) - 1 + ftype(h)['foot'] > 512:
                        h['addr'] = 512 - ftype(h)['foot'] + 1
                    if 'flash_hz' in b:                  # node-wide: flash guard rate (3 = default, 8 = most)
                        node.cfg['flash_hz'] = max(1.0, min(25.0 if node.cfg.get('unlock', {}).get('strobe') else 8.0,
                                                            float(b['flash_hz'])))
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
