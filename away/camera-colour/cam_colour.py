#!/usr/bin/env python3
# =============================================================================
# CAM COLOUR -- the MacBook camera feeds Movie mode WITHOUT TouchDesigner (Nov 17).
#
# Why: the border-colour tracking (Movie mode, source "camera") used to come
# from TouchDesigner's movie_in. With TD closed the hub just says "waiting for
# the picture". This little script does movie_in's job on its own:
#   camera -> crop to the projection -> shrink to 32 x 20 -> the hub's feed port
# (127.0.0.1:7011), in exactly the message TD's hue_feed sends, 5 times a second.
# The hub then does what it always did: each lamp takes the colour of the
# picture around where it sits (the border, like an ambilight).
#
# Rules it follows:
#   - the camera runs ONLY while the hub says Movie mode is on AND the source is
#     "camera" (asks the hub's /api/live every 2 s, in its own thread) -- so the
#     camera light is off the rest of the time
#   - stays quiet while TouchDesigner is open (TD's movie_in owns the feed then;
#     two feeders would make the hub flip between them)
#   - camera stops 3 s after the gate closes; camera lost -> retries every 5 s
#   - nothing here blocks: the camera is read in its own thread, the hub check in
#     another, the send is one UDP packet to this Mac
#   - it never touches the lights itself; the hub decides everything
#
# Camera: ffmpeg (AVFoundation) if it's installed, else OpenCV (cv2) if that is.
# Neither? It prints the one install line and stops.
# Settings (not secret): cam_colour.json next to this file (all optional):
#   device "0" (ffmpeg -list_devices / cv2 index), crop [x0, y0, x1, y1] as
#   0-1 fractions of the camera view (trim it to just the screen), every_s 0.2,
#   mirror false, size [32, 20], feed_port 7011, desk_port 7020.
#
#   python3 cam_colour.py            run (Ctrl+C stops)
#   python3 cam_colour.py --check    which camera backend, the device list, one test frame
# =============================================================================
import argparse
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONF_PATH = os.path.join(HERE, 'cam_colour.json')
DEFAULTS = dict(device='0', crop=[0.0, 0.0, 1.0, 1.0], every_s=0.2, mirror=False, size=[32, 20],
                feed_port=7011, desk_port=7020, gate_every_s=2.0, stop_after_s=3.0, retry_s=5.0)
FFMPEG_SPOTS = ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg']
INSTALL_LINE = 'brew install ffmpeg        (or:  python3 -m pip install --user opencv-python)'


def say(text):
    print(time.strftime('%H:%M:%S ') + text, flush=True)


def load_conf(path=CONF_PATH):
    conf = dict(DEFAULTS)
    try:
        with open(path) as f:
            conf.update(json.load(f))
    except (OSError, ValueError):
        pass
    c = [float(v) for v in (conf.get('crop') or [0, 0, 1, 1])][:4]
    x0, y0, x1, y1 = [min(1.0, max(0.0, v)) for v in (c + [0, 0, 1, 1][len(c):])]
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:                # a crop that leaves nothing: use the whole view
        x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
    conf['crop'] = [x0, y0, x1, y1]
    gw, gh = [max(2, min(128, int(v))) for v in conf.get('size') or [32, 20]]
    conf['size'] = [gw, gh]
    conf['every_s'] = max(0.05, float(conf.get('every_s', 0.2)))
    conf['device'] = str(conf.get('device', '0'))
    return conf


# ---- the picture maths (no camera needed) --------------------------------------------------------
def crop_px(w, h, crop):
    """The crop fractions as whole pixels (x, y, width, height), at least 1 x 1."""
    x0, y0, x1, y1 = crop
    x, y = int(round(x0 * w)), int(round(y0 * h))
    cw, ch = max(1, int(round(x1 * w)) - x), max(1, int(round(y1 * h)) - y)
    return x, y, min(cw, w - x), min(ch, h - y)


def shrink(rgb, w, h, gw, gh, crop=(0.0, 0.0, 1.0, 1.0), mirror=False):
    """rgb = w*h*3 bytes, top row first. Crops, then averages blocks (like hue_downsample.glsl) down to
    gw x gh. Returns the flat list of 0-255 ints the hub expects (top row first, r g b per cell)."""
    cx, cy, cw, ch = crop_px(w, h, crop)
    out = []
    for gy in range(gh):
        ya, yb = cy + gy * ch // gh, cy + max(gy * ch // gh + 1, (gy + 1) * ch // gh)
        for gx in range(gw):
            sx = gw - 1 - gx if mirror else gx
            xa, xb = cx + sx * cw // gw, cx + max(sx * cw // gw + 1, (sx + 1) * cw // gw)
            r = g = b = n = 0
            for yy in range(ya, min(yb, h)):
                row = yy * w * 3
                for xx in range(xa, min(xb, w)):
                    i = row + xx * 3
                    r += rgb[i]
                    g += rgb[i + 1]
                    b += rgb[i + 2]
                    n += 1
            n = max(1, n)
            out += [(r + n // 2) // n, (g + n // 2) // n, (b + n // 2) // n]
    return out


def feed_message(grid, gw, gh):
    """Exactly what TD's hue_feed sends (minus the beat: the hub keeps its own clock with TD closed)."""
    return {'beats': None, 'grid': grid, 'w': int(gw), 'h': int(gh), 'source': 'camera (cam_colour)'}


def border_summary(grid, gw, gh):
    """Average colour of each edge (for --check and the status line)."""
    def avg(cells):
        n = max(1, len(cells))
        return '#%02x%02x%02x' % tuple(sum(grid[(y * gw + x) * 3 + k] for x, y in cells) // n for k in range(3))
    return dict(top=avg([(x, 0) for x in range(gw)]), bottom=avg([(x, gh - 1) for x in range(gw)]),
                left=avg([(0, y) for y in range(gh)]), right=avg([(gw - 1, y) for y in range(gh)]))


# ---- cameras ---------------------------------------------------------------------------------------
def find_ffmpeg(which=shutil.which, exists=os.path.exists):
    p = which('ffmpeg')
    if p:
        return p
    for s in FFMPEG_SPOTS:                               # launchd / Finder runs don't see Homebrew's PATH
        if exists(s):
            return s
    return None


def ffmpeg_cmd(exe, conf):
    """ffmpeg crops + shrinks itself (area average), so Python only ever sees 32 x 20 pixels."""
    gw, gh = conf['size']
    x0, y0, x1, y1 = conf['crop']
    vf = 'fps=%g,crop=iw*%.4f:ih*%.4f:iw*%.4f:ih*%.4f,scale=%d:%d:flags=area' % (
        1.0 / conf['every_s'], x1 - x0, y1 - y0, x0, y0, gw, gh)
    if conf.get('mirror'):
        vf += ',hflip'
    return [exe, '-hide_banner', '-loglevel', 'error', '-f', 'avfoundation', '-framerate', '30',
            '-i', '%s:none' % conf['device'], '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']


class FfmpegCam:
    name = 'ffmpeg (AVFoundation)'

    def __init__(self, exe, conf, popen=subprocess.Popen, clock=time.time):
        self.exe, self.conf, self.popen, self.clock = exe, conf, popen, clock
        self.proc, self.latest, self.t = None, None, 0.0
        self.error = ''

    def start(self):
        self.proc = self.popen(ffmpeg_cmd(self.exe, self.conf), stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        gw, gh = self.conf['size']
        need = gw * gh * 3
        while True:
            buf = b''
            while len(buf) < need:
                chunk = proc.stdout.read(need - len(buf))
                if not chunk:
                    self.error = 'camera stream ended (camera busy, unplugged, or permission refused?)'
                    return
                buf += chunk
            self.latest, self.t = list(buf), self.clock()

    def frame(self):
        """(grid, age_s) of the newest picture, or (None, None)."""
        if self.latest is None:
            return None, None
        return self.latest, self.clock() - self.t

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None
        self.latest = None


class Cv2Cam:
    name = 'OpenCV'

    def __init__(self, cv2, conf, clock=time.time, sleep=time.sleep):
        self.cv2, self.conf, self.clock, self.sleep = cv2, conf, clock, sleep
        self.cap, self.latest, self.t, self.run, self.error = None, None, 0.0, False, ''

    def start(self):
        dev = self.conf['device']
        self.cap = self.cv2.VideoCapture(int(dev) if dev.isdigit() else dev)
        self.run = True
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        gw, gh = self.conf['size']
        while self.run:
            ok, img = self.cap.read()
            if not ok or img is None:
                self.error = 'camera gave no picture (busy, unplugged, or permission refused?)'
                self.run = False
                return
            h, w = img.shape[:2]
            x, y, cw, ch = crop_px(w, h, self.conf['crop'])
            img = self.cv2.resize(img[y:y + ch, x:x + cw], (gw, gh), interpolation=self.cv2.INTER_AREA)
            if self.conf.get('mirror'):
                img = img[:, ::-1]
            img = self.cv2.cvtColor(img, self.cv2.COLOR_BGR2RGB)
            self.latest, self.t = [int(v) for v in img.reshape(-1)], self.clock()
            self.sleep(self.conf['every_s'])

    def frame(self):
        if self.latest is None:
            return None, None
        return self.latest, self.clock() - self.t

    def alive(self):
        return self.run

    def stop(self):
        self.run = False
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap, self.latest = None, None


def pick_backend(conf, which=shutil.which, exists=os.path.exists, importer=importlib.import_module):
    """A camera object, or (None, why). ffmpeg first (no Python packages needed), then OpenCV."""
    exe = find_ffmpeg(which, exists)
    if exe:
        return FfmpegCam(exe, conf), ''
    try:
        return Cv2Cam(importer('cv2'), conf), ''
    except ImportError:
        return None, 'no camera reader on this Mac: neither ffmpeg nor OpenCV is installed. Michael: ' + INSTALL_LINE


# ---- the gate: is Movie mode on with the camera as its source? --------------------------------------
def td_running(run=subprocess.run):
    try:
        return run(['pgrep', '-xq', 'TouchDesigner'], timeout=2).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def hub_wants_camera(desk_port, opener=urllib.request.urlopen):
    """(True/False, reason) from the hub's /api/live (this Mac only, 0.8 s timeout)."""
    try:
        with opener('http://127.0.0.1:%d/api/live' % desk_port, timeout=0.8) as r:
            live = json.loads(r.read().decode())
    except Exception:
        return False, 'hub not answering'
    mv = live.get('movie') or {}
    if not mv.get('on'):
        return False, 'Movie mode is off'
    if mv.get('src') != 'camera':
        return False, 'Movie mode source is %s, not camera' % mv.get('src')
    return True, 'Movie mode on, source camera'


class Gate:
    """Checks the hub + TouchDesigner every gate_every_s in its own thread; the main loop just reads .open."""

    def __init__(self, conf, ask=None, td=None, clock=time.time):
        self.conf, self.clock = conf, clock
        self.ask = ask or (lambda: hub_wants_camera(conf['desk_port']))
        self.td = td or td_running
        self.open, self.reason, self.t = False, 'starting', -1e9

    def check(self):
        if self.td():
            self.open, self.reason = False, 'TouchDesigner is open (its movie_in feeds the hub)'
        else:
            self.open, self.reason = self.ask()
        self.t = self.clock()
        return self.open

    def loop(self, sleep=time.sleep):
        while True:
            self.check()
            sleep(self.conf['gate_every_s'])


# ---- the main loop -----------------------------------------------------------------------------------
class Runner:
    def __init__(self, conf, gate, make_cam, sock=None, clock=time.time, log=say):
        self.conf, self.gate, self.make_cam, self.clock, self.log = conf, gate, make_cam, clock, log
        self.sock = sock
        self.cam, self.closed_t, self.retry_t, self.sent, self.status = None, None, -1e9, 0, ''

    def _status(self, text):
        if text != self.status:
            self.status = text
            self.log(text)

    def step(self):
        """One tick (every every_s). Returns True if a picture went to the hub."""
        now = self.clock()
        if not self.gate.open:
            if self.cam is not None:
                if self.closed_t is None:
                    self.closed_t = now
                if now - self.closed_t >= self.conf['stop_after_s']:
                    self.cam.stop()
                    self.cam = None
                    self._status('camera off -- ' + self.gate.reason)
            else:
                self._status('idle -- ' + self.gate.reason)
            return False
        self.closed_t = None
        if self.cam is not None and not self.cam.alive():
            self._status('camera lost: %s -- retrying in %ds' % (self.cam.error or '?', self.conf['retry_s']))
            self.cam.stop()
            self.cam, self.retry_t = None, now
        if self.cam is None:
            if now - self.retry_t < self.conf['retry_s']:
                return False
            self.cam, why = self.make_cam()
            if self.cam is None:
                self._status(why)
                self.retry_t = now
                return False
            self.cam.start()
            self._status('camera on (%s) -- %s' % (self.cam.name, self.gate.reason))
        grid, age = self.cam.frame()
        if grid is None or age > 1.0:                    # the hub drops a picture older than 1 s anyway
            return False
        gw, gh = self.conf['size']
        msg = feed_message(grid, gw, gh)
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.sendto(json.dumps(msg, separators=(',', ':')).encode(), ('127.0.0.1', self.conf['feed_port']))
        except OSError as e:
            self._status('send failed: %s' % e)
            return False
        self.sent += 1
        self._status('sending the camera picture to the hub (%dx%d, %.0f per second)' % (gw, gh, 1 / self.conf['every_s']))
        return True


def check(conf):
    cam, why = pick_backend(conf)
    if cam is None:
        print(why)
        return 2
    print('camera reader: %s' % cam.name)
    if isinstance(cam, FfmpegCam):
        print('devices (use the number as "device" in cam_colour.json):')
        subprocess.run([cam.exe, '-hide_banner', '-f', 'avfoundation', '-list_devices', 'true', '-i', ''], timeout=10)
    print('grabbing one frame (macOS may ask to allow the camera for Terminal the first time) ...')
    cam.start()
    t0 = time.time()
    while time.time() - t0 < 8:
        grid, age = cam.frame()
        if grid is not None:
            gw, gh = conf['size']
            print('ok -- edge colours: %s' % border_summary(grid, gw, gh))
            cam.stop()
            return 0
        if not cam.alive():
            break
        time.sleep(0.1)
    print('no picture: %s' % (cam.error or 'timed out'))
    cam.stop()
    return 1


def main():
    ap = argparse.ArgumentParser(description='MacBook camera -> Movie mode, without TouchDesigner')
    ap.add_argument('--check', action='store_true', help='backend, device list and one test frame, then exit')
    a = ap.parse_args()
    conf = load_conf()
    if a.check:
        sys.exit(check(conf))
    gate = Gate(conf)
    threading.Thread(target=gate.loop, daemon=True).start()
    run = Runner(conf, gate, lambda: pick_backend(conf))
    say('cam_colour: waiting for Movie mode with source "camera" (Ctrl+C stops)')
    try:
        while True:
            run.step()
            time.sleep(conf['every_s'])
    except KeyboardInterrupt:
        if run.cam is not None:
            run.cam.stop()
        say('stopped')


if __name__ == '__main__':
    main()
