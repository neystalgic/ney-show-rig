#!/usr/bin/env python3
# Offline tests for cam_colour.py -- no camera, no hub, no network.
# Real sockets and URL opening are blocked for the whole run; the camera, hub, TouchDesigner
# check and clock are fakes. Saved frames (frames/*.ppm) stand in for the camera.
#   python3 test_cam_colour.py
import ast
import colorsys
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)


def _no_net(*a, **k):
    raise AssertionError('test tried to use the network')


socket.socket = _no_net
socket.create_connection = _no_net
urllib.request.urlopen = _no_net

import cam_colour as cc   # noqa: E402

PASS = FAIL = 0


def ok(cond, what):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print('FAIL:', what)


# ---- saved frames -------------------------------------------------------------------------------
FR = os.path.join(HERE, 'frames')


def write_ppm(path, w, h, px):
    with open(path, 'wb') as f:
        f.write(b'P6\n%d %d\n255\n' % (w, h))
        f.write(bytes(px))


def read_ppm(path):
    with open(path, 'rb') as f:
        data = f.read()
    parts, i = [], 0
    while len(parts) < 4:                       # P6 w h max, whitespace separated
        while data[i:i + 1].isspace():
            i += 1
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        parts.append(data[i:j])
        i = j
    i += 1
    w, h = int(parts[1]), int(parts[2])
    return w, h, list(data[i:i + w * h * 3])


def make_frames():
    """A camera view 160 x 120: the projection sits in the middle (x 20-140, y 15-105), dark room around it.
    Projected picture: left third purple, middle green, right third blue; top band red."""
    os.makedirs(FR, exist_ok=True)
    w, h = 160, 120
    px = []
    for y in range(h):
        for x in range(w):
            if not (20 <= x < 140 and 15 <= y < 105):
                c = (10, 10, 12)                                  # the wall around the screen
            elif y < 15 + 15:
                c = (230, 20, 20)                                 # top band red
            elif x < 60:
                c = (140, 40, 220)                                # purple
            elif x < 100:
                c = (30, 200, 60)
            else:
                c = (20, 60, 230)
            px += c
    write_ppm(os.path.join(FR, 'projection_160x120.ppm'), w, h, px)
    write_ppm(os.path.join(FR, 'black_160x120.ppm'), w, h, [0] * (w * h * 3))


if not os.path.exists(os.path.join(FR, 'projection_160x120.ppm')):
    make_frames()
W, H, PIC = read_ppm(os.path.join(FR, 'projection_160x120.ppm'))
_, _, BLACK = read_ppm(os.path.join(FR, 'black_160x120.ppm'))
CROP = [20 / 160, 15 / 120, 140 / 160, 105 / 120]


def cell(grid, gw, x, y):
    i = (y * gw + x) * 3
    return tuple(grid[i:i + 3])


def near(a, b, tol=6):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


# ---- 1. settings ----------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, 'c.json')
    c = cc.load_conf(p)                                            # missing file -> defaults
    ok(c['size'] == [32, 20] and c['crop'] == [0, 0, 1, 1] and c['every_s'] == 0.2, 'defaults')
    ok(c['feed_port'] == 7011 and c['desk_port'] == 7020, 'ports match hue_hub FEED_PORT / DESK_PORT')
    open(p, 'w').write('{not json')
    ok(cc.load_conf(p)['size'] == [32, 20], 'broken json -> defaults')
    json.dump(dict(crop=[0.5, 0.5, 0.52, 0.9], size=[999, 1], every_s=0, device=1), open(p, 'w'))
    c = cc.load_conf(p)
    ok(c['crop'] == [0, 0, 1, 1], 'a crop leaving nothing -> whole view')
    ok(c['size'] == [128, 2] and c['every_s'] == 0.05 and c['device'] == '1', 'size/rate/device clamped')
    json.dump(dict(crop=[-1, 0.1, 2, 0.9]), open(p, 'w'))
    ok(cc.load_conf(p)['crop'] == [0.0, 0.1, 1.0, 0.9], 'crop clamped to 0-1')

# hub constants really are what we think
src = open(os.path.join(RIG, 'hue_hub.py')).read()
ok('FEED_PORT = 7011' in src and 'DESK_PORT = 7020' in src, 'hue_hub ports unchanged')

# ---- 2. picture maths on the saved frames --------------------------------------------------------
ok(cc.crop_px(160, 120, CROP) == (20, 15, 120, 90), 'crop_px')
ok(cc.crop_px(10, 10, [0.95, 0.95, 1, 1]) == (10, 10, 0, 0) or cc.crop_px(10, 10, [0.95, 0.95, 1, 1])[2] >= 0,
   'crop_px never negative')
g = cc.shrink(PIC, W, H, 32, 20, CROP)
ok(len(g) == 32 * 20 * 3 and all(isinstance(v, int) and 0 <= v <= 255 for v in g), 'grid shape + 0-255 ints')
ok(near(cell(g, 32, 0, 10), (140, 40, 220)), 'left edge purple: %s' % (cell(g, 32, 0, 10),))
ok(near(cell(g, 32, 31, 10), (20, 60, 230)), 'right edge blue: %s' % (cell(g, 32, 31, 10),))
ok(near(cell(g, 32, 16, 19), (30, 200, 60)), 'bottom middle green')
ok(near(cell(g, 32, 5, 0), (230, 20, 20)), 'top band red')
gm = cc.shrink(PIC, W, H, 32, 20, CROP, mirror=True)
ok(near(cell(gm, 32, 0, 10), (20, 60, 230)) and near(cell(gm, 32, 31, 10), (140, 40, 220)), 'mirror flips sides')
gu = cc.shrink(PIC, W, H, 32, 20)                                # uncropped: the dark wall shows at the edges
ok(near(cell(gu, 32, 0, 10), (10, 10, 12)), 'no crop -> wall at the edge (why the crop setting exists)')
ok(max(cc.shrink(BLACK, W, H, 32, 20, CROP)) == 0, 'black frame -> all zero')
tiny = cc.shrink([255, 0, 0] * 4, 2, 2, 32, 20)                  # camera smaller than the grid: no crash
ok(len(tiny) == 32 * 20 * 3 and cell(tiny, 32, 31, 19) == (255, 0, 0), 'upscale safe')
b = cc.border_summary(g, 32, 20)
lh = colorsys.rgb_to_hsv(*[int(b['left'][i:i + 2], 16) / 255 for i in (1, 3, 5)])[0] * 360
ok(270 <= lh <= 300 and b['top'] == '#e61414', 'border summary: left purple (with a bit of the red band), top red: %s' % b)

# ---- 3. the message is exactly what the hub's feed_listener reads ------------------------------------
msg = cc.feed_message(g, 32, 20)
wire = json.loads(json.dumps(msg, separators=(',', ':')))
ok(wire['beats'] is None and wire['w'] == 32 and wire['h'] == 20 and len(wire['grid']) == 1920, 'message fields')
ok(len(json.dumps(msg, separators=(',', ':')).encode()) < 65535, 'fits one UDP packet (hub reads 65535)')
fl = src[src.index('def feed_listener'):src.index('# ---- the desk')]
for needle in ("msg['grid'], int(msg['w']), int(msg['h'])", "msg.get('grid')", "'beats' in msg"):
    ok(needle in fl, 'hub feed_listener still reads: %s' % needle)

# run the hub's REAL movie_cols (lifted out of hue_hub.py, no imports of the hub) on our grid
tree = ast.parse(src)
fn = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'movie_cols':
        fn = node
ok(fn is not None, 'found movie_cols in hue_hub.py')
if fn is not None:
    ns = dict(time=time, math=math, colorsys=colorsys, clamp=lambda v, a=0.0, b=1.0: max(a, min(b, v)))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'hue_hub.movie_cols', 'exec'), ns)

    class FakeHub:
        pass
    hb = FakeHub()
    hb.feed = dict(grid=wire['grid'], gw=wire['w'], gh=wire['h'], t=time.time())
    hb.live, hb.movie_prev, hb.movie_status = {}, None, ''

    class Rig:
        segs = [dict(u=0.02, v=0.5), dict(u=0.98, v=0.5), dict(u=0.5, v=0.98), dict(u=0.5, v=0.02)]
    hb.rig = Rig()
    cols = ns['movie_cols'](hb, 0.2)
    hue = [colorsys.rgb_to_hsv(*c)[0] * 360 for c in cols]
    ok(260 <= hue[0] <= 290, 'left lamp follows purple (hue %.0f)' % hue[0])
    ok(215 <= hue[1] <= 235, 'right lamp follows blue (hue %.0f)' % hue[1])
    ok(hue[2] <= 30 or hue[2] >= 345, 'top lamp (v high = top) follows the red band (hue %.0f; the patch also sees a row below it)' % hue[2])
    ok(120 <= hue[3] <= 150, 'bottom lamp follows green (hue %.0f)' % hue[3])
    ok(hb.movie_status.startswith('following the picture (32x20)'), 'hub status: %s' % hb.movie_status)

# ---- 4. ffmpeg command (and, if this machine has ffmpeg, run the same filter on a saved frame) ----------
conf = cc.load_conf('/nonexistent')
conf['crop'] = CROP
cmd = cc.ffmpeg_cmd('/x/ffmpeg', conf)
ok(cmd[cmd.index('-f') + 1] == 'avfoundation' and '0:none' in cmd, 'avfoundation, video only (no mic)')
ok(cmd[-5:] == ['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], 'raw rgb24 to stdout')
vf = cmd[cmd.index('-vf') + 1]
ok(vf.startswith('fps=5,crop=') and vf.endswith('scale=32:20:flags=area'), 'filter: %s' % vf)
conf2 = dict(conf, mirror=True)
ok(cc.ffmpeg_cmd('/x/ffmpeg', conf2)[cmd.index('-vf') + 1].endswith(',hflip'), 'mirror -> hflip')
real = shutil.which('ffmpeg')
if real:
    out = subprocess.run([real, '-hide_banner', '-loglevel', 'error', '-i', os.path.join(FR, 'projection_160x120.ppm'),
                          '-vf', vf.split(',', 1)[1], '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         capture_output=True, timeout=30).stdout
    fg = list(out)
    ok(len(fg) == 1920, 'ffmpeg filter output size %d' % len(fg))
    if len(fg) == 1920:
        ok(near(cell(fg, 32, 0, 10), (140, 40, 220), 10) and near(cell(fg, 32, 31, 10), (20, 60, 230), 10),
           'ffmpeg crop+area-scale matches the Python shrink (%s %s)' % (cell(fg, 32, 0, 10), cell(fg, 32, 31, 10)))
else:
    print('(no ffmpeg here: skipped the real-filter check)')

# ---- 5. backend choice --------------------------------------------------------------------------------
def no_import(name):
    raise ImportError(name)


cam, why = cc.pick_backend(conf, which=lambda n: None, exists=lambda p: p == '/opt/homebrew/bin/ffmpeg')
ok(isinstance(cam, cc.FfmpegCam) and cam.exe == '/opt/homebrew/bin/ffmpeg', 'finds Homebrew ffmpeg off PATH')
cam, why = cc.pick_backend(conf, which=lambda n: None, exists=lambda p: False, importer=lambda n: object())
ok(isinstance(cam, cc.Cv2Cam), 'falls back to OpenCV')
cam, why = cc.pick_backend(conf, which=lambda n: None, exists=lambda p: False, importer=no_import)
ok(cam is None and 'brew install ffmpeg' in why, 'neither -> install line for Michael')


# FfmpegCam reading from a fake ffmpeg process (bytes from the saved frame)
class FakeOut:
    def __init__(self, data, step=700):
        self.data, self.step = data, step

    def read(self, n):
        n = min(n, self.step)
        b, self.data = self.data[:n], self.data[n:]
        return b


class FakeProc:
    def __init__(self, data):
        self.stdout, self.code = FakeOut(data), None

    def poll(self):
        return self.code

    def terminate(self):
        self.code = -15


procs = []


def fake_popen(cmd, **kw):
    procs.append((cmd, kw))
    return FakeProc(bytes(g) * 2)


fc = cc.FfmpegCam('/x/ffmpeg', conf, popen=fake_popen, clock=lambda: 100.0)
fc.start()
for _ in range(50):
    if fc.error:
        break
    time.sleep(0.02)
grid, age = fc.frame()
ok(grid == g and age == 0.0, 'FfmpegCam assembles chunks into whole frames')
ok('ended' in fc.error, 'stream end noticed: %s' % fc.error)
ok(procs[0][1]['stdin'] == subprocess.DEVNULL and procs[0][1]['stderr'] == subprocess.DEVNULL, 'no pipes left to block')
fc.stop()
ok(fc.frame() == (None, None), 'stop clears the picture')

# ---- 6. the gate ----------------------------------------------------------------------------------------
class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body.encode()


seen = []


def opener_for(live):
    def op(url, timeout):
        seen.append((url, timeout))
        return Resp(json.dumps(live))
    return op


ok(cc.hub_wants_camera(7020, opener_for(dict(movie=dict(on=True, src='camera'))))[0], 'movie on + camera -> open')
ok(seen[0] == ('http://127.0.0.1:7020/api/live', 0.8), 'asks only this Mac, short timeout')
ok(not cc.hub_wants_camera(7020, opener_for(dict(movie=dict(on=False, src='camera'))))[0], 'movie off -> shut')
r = cc.hub_wants_camera(7020, opener_for(dict(movie=dict(on=True, src='capture'))))
ok(not r[0] and 'capture' in r[1], 'other source -> shut')
ok(not cc.hub_wants_camera(7020, opener_for({}))[0], 'old hub without movie -> shut')
ok(cc.hub_wants_camera(7020, _no_net) == (False, 'hub not answering'), 'hub down -> shut, no crash')
ok(cc.td_running(run=lambda *a, **k: subprocess.CompletedProcess(a, 0)) is True, 'pgrep found TD')
ok(cc.td_running(run=lambda *a, **k: subprocess.CompletedProcess(a, 1)) is False, 'pgrep no TD')


def boom(*a, **k):
    raise OSError('no pgrep')


ok(cc.td_running(run=boom) is False, 'pgrep missing -> treat as closed')

gate = cc.Gate(conf, ask=lambda: (True, 'Movie mode on, source camera'), td=lambda: True)
ok(gate.check() is False and 'TouchDesigner' in gate.reason, 'TD open -> stay quiet')

# ---- 7. the runner with a fake clock, camera and socket ---------------------------------------------------
T = [1000.0]


class FakeCam:
    name = 'fake'
    made = 0

    def __init__(self):
        FakeCam.made += 1
        self.on, self.dead, self.error, self.age = False, False, '', 0.1

    def start(self):
        self.on = True

    def frame(self):
        return (g, self.age) if self.on else (None, None)

    def alive(self):
        return self.on and not self.dead

    def stop(self):
        self.on = False


class FakeSock:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


class FakeGate:
    open, reason = False, 'Movie mode is off'


cams = []


def make_cam():
    c = FakeCam()
    cams.append(c)
    return c, ''


logs = []
fg8, fs = FakeGate(), FakeSock()
rn = cc.Runner(conf, fg8, make_cam, sock=fs, clock=lambda: T[0], log=logs.append)
ok(rn.step() is False and not cams and logs[-1].startswith('idle'), 'gate shut: camera never starts')
fg8.open, fg8.reason = True, 'Movie mode on, source camera'
ok(rn.step() is True and len(cams) == 1 and cams[0].on, 'gate open: camera on + first picture sent')
data, addr = fs.sent[-1]
ok(addr == ('127.0.0.1', 7011) and json.loads(data)['grid'] == g, 'sent to 127.0.0.1:7011 only')
for _ in range(10):
    T[0] += 0.2
    rn.step()
ok(len(fs.sent) == 11 and len(cams) == 1, '5 per second, one camera')
cams[0].age = 1.5
ok(rn.step() is False, 'stale picture (>1 s) not sent')
cams[0].age = 0.1
fg8.open, fg8.reason = False, 'Movie mode is off'
T[0] += 1.0
rn.step()
ok(cams[0].on and rn.cam is not None, 'gate shut: camera kept 3 s (no flapping)')
fg8.open = True
T[0] += 0.2
ok(rn.step() is True and len(cams) == 1, 'reopened within 3 s: same camera')
fg8.open = False
T[0] += 0.2
rn.step()
T[0] += 3.1
rn.step()
ok(not cams[0].on and rn.cam is None and logs[-1].startswith('camera off'), 'gate shut 3 s: camera off')
n_before = len(fs.sent)
T[0] += 5
rn.step()
ok(len(fs.sent) == n_before, 'nothing sent while shut')
fg8.open = True
T[0] += 0.2
rn.step()
ok(len(cams) == 2, 'reopen: camera back')
cams[1].dead, cams[1].error = True, 'camera stream ended'
T[0] += 0.2
ok(rn.step() is False and 'camera lost' in logs[-1], 'camera lost noticed')
T[0] += 1
rn.step()
ok(len(cams) == 2, 'waits retry_s before trying again')
T[0] += 5
rn.step()
ok(len(cams) == 3 and cams[2].on, 'retried after 5 s')

rn2 = cc.Runner(conf, fg8, lambda: (None, 'no camera reader on this Mac'), sock=FakeSock(), clock=lambda: T[0],
                log=logs.append)
ok(rn2.step() is False and logs[-1].startswith('no camera reader'), 'no backend -> says why, no crash')


class BadSock:
    def sendto(self, *a):
        raise OSError('nope')


rn3 = cc.Runner(conf, fg8, make_cam, sock=BadSock(), clock=lambda: T[0], log=logs.append)
ok(rn3.step() is False and logs[-1].startswith('send failed'), 'send error logged, keeps running')
n = len(logs)
rn.step()
rn.step()
ok(len(logs) == n, 'status lines only on change (no log spam)')

# ---- 8. no live file touched, no secrets ------------------------------------------------------------------
code = open(os.path.join(HERE, 'cam_colour.py')).read()
for bad in ('hue_config', 'rig_control.token', '192.168.', '100.', '7040', '7060'):
    ok(bad not in code, 'cam_colour.py never mentions %s' % bad)

print('%d passed, %d failed' % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
