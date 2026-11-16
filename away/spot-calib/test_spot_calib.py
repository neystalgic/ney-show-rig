#!/usr/bin/env python3
# Offline test for away/spot-calib/calib.py (Nov 16). NO network: sockets, getaddrinfo and urlopen are blocked,
# hub_dmx / hue_stream are fakes, the clock is fake, every file lives in a temp folder. Run: python3 test_spot_calib.py
import hashlib, importlib.util, json, os, socket, sys, tempfile, types, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FAILS, PASSES = [], [0]


def check(name, ok):
    if ok:
        PASSES[0] += 1
    else:
        FAILS.append(name)
        print('FAIL', name)


# ---- block the network before anything is imported --------------------------------------------------------------
class NoNet(Exception):
    pass


def _blocked(*a, **k):
    raise NoNet('network blocked in tests')


socket.socket = _blocked
socket.getaddrinfo = _blocked
urllib.request.urlopen = _blocked

# ---- fake hub_dmx / hue_stream -----------------------------------------------------------------------------------
fhd = types.ModuleType('hub_dmx')
fhd.ARTNET_PORT, fhd.NODE_PORT, fhd.MASTER_MIN, fhd.MASTER_MAX = 6454, 7060, 8, 134
fhd.artdmx = lambda seq, uni, data: b'Art-Net\0' + bytes(10) + bytes(data)     # 18-byte header + 512 data
sys.modules['hub_dmx'] = fhd
fhs = types.ModuleType('hue_stream')
fhs.load_config = _blocked
fhs.v2 = _blocked
sys.modules['hue_stream'] = fhs


def sha(p):
    try:
        return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    except OSError:
        return None


LIVE = [os.path.join(ROOT, 'calib.py'), os.path.join(ROOT, 'bridge', 'calib_aim.json'), os.path.join(ROOT, 'hub_dmx.py')]
before = [sha(p) for p in LIVE]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


new = load(os.path.join(HERE, 'calib.py'), 'calib_new')
old = load(os.path.join(ROOT, 'calib.py'), 'calib_live')     # only to compare head bytes; main() never runs

TMP = tempfile.mkdtemp(prefix='spotcalib_')
for m in (new, old):
    m.STOP = os.path.join(TMP, 'calib.stop')
    m.LOG = os.path.join(TMP, 'calib.txt')
new.AIM = os.path.join(TMP, 'calib_aim.json')

HEADS = [dict(addr=1 + 14 * k, pan_min=2000, pan_max=60000, tilt_up=32768, tilt_dir=1, motor_speed=10) for k in range(4)]
SPOTS = [dict(type='focus17', addr=57, pan_min=0, pan_max=65535, tilt_up=30000, tilt_dir=1, motor_speed=20, calibrated=True),
         dict(type='focus17', addr=74, pan_min=0, pan_max=65535, tilt_up=30000, tilt_dir=-1, motor_speed=20)]
SETTINGS = {'spot_fx': {'hold': {'az': 192, 'lean': 46}, 'hold_head': 4,
                        'per_head': {'5': {'hold': {'az': 180, 'lean': 65}, 'hold_head': 5, 'uv_only': True}}}}
new.settings = lambda: SETTINGS


class FakeSock:
    def __init__(self):
        self.sent = []

    def sendto(self, pkt, addr):
        self.sent.append((pkt, addr))


def rig(mod, fixtures):
    h = object.__new__(mod.Heads)
    h.ip, h.heads, h.uni, h.seq, h.sock = 'fake-node', fixtures, 0, 0, FakeSock()
    return h


def frame(h, k=-1):
    return h.sock.sent[k][0][18:]


class Clock:
    def __init__(self, hooks=None):
        self.t, self.hooks = 1000.0, dict(hooks or {})

    def time(self):
        return self.t

    def strftime(self, fmt):
        return 'fake'

    def sleep(self, s):
        self.t += s
        for at in sorted(list(self.hooks)):
            if self.t >= at:
                self.hooks.pop(at)()


FIX = HEADS + SPOTS

# 1. heads: byte-for-byte the same as the live calib.py
for want in ({0: (30000, 20000, 0.8)}, {2: (1000, 70000, 1.5), 3: (65000, -5, 0.0)}):
    a, b = rig(new, FIX), rig(old, [dict(x) for x in HEADS])
    a.send(want)
    b.send(want)
    check('head bytes same as live %s' % sorted(want), frame(a) == frame(b))

# 2. spot 1 layout (17 ch at addr 57 -> a = 56)
h = rig(new, FIX)
h.send({4: (40000, 33000, 0.6, {})})
d = frame(h)
check('frame is 512 bytes', len(d) == 512)
blk = list(d[56:73])
check('spot pan/tilt bytes', blk[0:4] == [40000 >> 8, 40000 & 255, 33000 >> 8, 33000 & 255])
check('spot colour slot 97', blk[4] == 97)
check('spot open beam: gobo 0, rot 0', blk[5] == 0 and blk[6] == 0)
check('spot focus default 128', blk[7] == 128)
check('spot shutter open 12 (never strobe)', blk[8] == 12)
check('spot dimmer 60% = 153', blk[9] == 153)
check('spot UV off', blk[10] == 0 and blk[11] == 0)
check('spot motor speed a+15', blk[15] == 20)
check('nothing sent to other fixtures (spot 1)', all(v == 0 for k, v in enumerate(d) if not 56 <= k < 73))
check('no 14-ch head bytes on a spot (a+5 is gobo, not master)', blk[5] == 0 and blk[6:9] != [110, 0, 255])

# 3. spot 2 (addr 74) + only that block
h = rig(new, FIX)
h.send({5: (100, 200, 0.6, {'gobo': 40, 'gobo_rot': 300, 'focus': -5, 'color': 'x'})})
d = frame(h)
blk = list(d[73:90])
check('spot 2 lands at addr 74', blk[0:4] == [0, 100, 0, 200])
check('extras pass + clamp (gobo 40, rot 255, focus 0, bad colour -> 97)', blk[4:8] == [97, 40, 255, 0])
check('nothing sent to other fixtures (spot 2)', all(v == 0 for k, v in enumerate(d) if not 73 <= k < 90))

# 4. UV only
h = rig(new, FIX)
h.send({4: (1, 2, 0.6, {'uv': 1.0, 'uv_only': True})})
blk = list(frame(h)[56:73])
check('UV-only: dimmer 0 + shutter closed', blk[9] == 0 and blk[8] == 0)
check('UV-only: UV shutter 12 + UV 255', blk[10] == 12 and blk[11] == 255)
h.send({4: (1, 2, 0.6, {'uv': 0.5})})
blk = list(frame(h)[56:73])
check('UV + beam together when not uv_only', blk[9] == 153 and blk[11] == 128)

# 5. white guard + a chosen slot
h = rig(new, FIX)
h.send({4: (1, 2, 0.6, {'color': 0})})
check('white slot 0 -> 97', frame(h)[56 + 4] == 97)
h.send({4: (1, 2, 0.6, {'color': 14})})
check('white slot 14 -> 97', frame(h)[56 + 4] == 97)
h.send({4: (1, 2, 0.6, {'color': 82})})
check('chosen slot 82 kept', frame(h)[56 + 4] == 82)
h.send({4: (1, 2, 0.0, {})})
blk = list(frame(h)[56:73])
check('level 0 -> dimmer 0, shutter closed', blk[8] == 0 and blk[9] == 0)

# 6. out of range / bad indexes are skipped
h = rig(new, FIX + [dict(type='focus17', addr=500)])
h.send({6: (1, 2, 0.6, {}), 9: (1, 2, 0.6), -1: (1, 2, 0.6)})
check('spot running off the universe + unknown indexes skipped', all(v == 0 for v in frame(h)))
h = rig(new, FIX)
h.send({4: (1, 2, 0.6)})                                  # 3-tuple (old 'aim N' form) still works for a spot
check('3-tuple on a spot = open purple-ish beam', list(frame(h)[60:62]) == [97, 0])

# 7. spot index + saved aims
h = rig(new, FIX)
check('Spot 1 = fixture index 4', new.spot_index(h, 1) == 4)
check('Spot 2 = fixture index 5', new.spot_index(h, 2) == 5)
try:
    new.spot_index(h, 3)
    check('Spot 3 refused', False)
except SystemExit:
    check('Spot 3 refused', True)
check('spots found by type, not position', new.spot_index(rig(new, [SPOTS[0]] + HEADS), 1) == 0)
p, t = new.spot_saved(h, 5)
check('Spot 2 saved aim from per_head hold (az 180)', abs(p - 180 / 540.0 * 65535) < 1)
check('Spot 2 tilt uses its tilt_dir -1 + 240 deg', abs(t - (30000 - 65 / 240.0 * 65535)) < 1)
p, t = new.spot_saved(h, 4)
check('Spot 1 saved aim from shared hold (az 192, lean 46)', abs(p - 192 / 540.0 * 65535) < 1 and abs(t - (30000 + 46 / 240.0 * 65535)) < 1)
az, lean = h.spot_deg(4, p, t)
check('az/lean round trip', abs(az - 192) < 0.01 and abs(lean - 46) < 0.01)
new.settings = lambda: {}
p, t = new.spot_saved(h, 4)
check('no saved hold -> middle of the pan window, 30 deg lean', abs(p - 32767.5) < 1 and abs(t - (30000 + 30 / 240.0 * 65535)) < 1)
new.settings = lambda: SETTINGS

# 8. 'spot N' mode with a fake clock
open(new.LOG, 'w').close()
new.time = Clock()
h = rig(new, FIX)
new.spot(h, 2, secs=2.0)
check('spot mode sends ~25 frames a second', 45 <= len(h.sock.sent) <= 55)
check('spot mode only ever lights Spot 2', all(all(v == 0 for k, v in enumerate(pk[18:]) if not 73 <= k < 90) for pk, _ in h.sock.sent))
check('spot mode dimmer 60%', all(pk[18 + 73 + 9] == 153 for pk, _ in h.sock.sent))
check('spot mode packets go only to the fake node', {ad for _, ad in h.sock.sent} == {('fake-node', 6454)})
logtxt = open(new.LOG).read()
check('Spot 2 -> ceiling fan reminder in the log', 'ceiling fan OFF' in logtxt)
open(new.LOG, 'w').close()
new.time = Clock()
new.spot(rig(new, FIX), 1, secs=0.5)
check('Spot 1 -> no fan reminder', 'ceiling fan' not in open(new.LOG).read())

# 9. 'aimspot N' follows the aim file; half-written file keeps the last good aim; az/lean form
json.dump({'pan': 20000, 'tilt': 31000, 'gobo': 30, 'focus': 200}, open(new.AIM, 'w'))
def nudge():
    json.dump({'az': 90, 'lean': 20, 'uv': 0.4}, open(new.AIM, 'w'))
def corrupt():
    open(new.AIM, 'w').write('{"pan": 1')
new.time = Clock({1001.0: nudge, 1002.0: corrupt})
h = rig(new, FIX)
new.follow_spot(h, 1, secs=3.0)
f0, f1, f2 = frame(h, 5), frame(h, 30), frame(h, -1)
check('aimspot first aim from file', list(f0[56:60]) == [20000 >> 8, 20000 & 255, 31000 >> 8, 31000 & 255])
check('aimspot gobo/focus from file', f0[56 + 5] == 30 and f0[56 + 7] == 200)
p90, t20 = h.spot_aim(4, 90, 20)
check('aimspot follows az/lean nudge', (f1[56] << 8 | f1[57]) == int(p90) and (f1[58] << 8 | f1[59]) == int(t20))
check('nudge dropped the old gobo, UV 0.4 on', f1[56 + 5] == 0 and f1[56 + 11] == 102)
check('half-written file keeps the last good aim', f2[56:73] == f1[56:73])
check('aimspot never lights another fixture', all(all(v == 0 for k, v in enumerate(pk[18:]) if not 56 <= k < 73) for pk, _ in h.sock.sent))
check('aimspot logs az/lean to save', 'az 90.0, lean 20.0' in open(new.LOG).read())

# 10. 'uvaim N': dimmer 0 every frame, UV on
json.dump({'pan': 20000, 'tilt': 31000}, open(new.AIM, 'w'))
new.time = Clock()
h = rig(new, FIX)
new.follow_spot(h, 2, uv_only=True, secs=1.0)
check('uvaim: every frame dimmer 0 + shutter closed', all(pk[18 + 73 + 9] == 0 and pk[18 + 73 + 8] == 0 for pk, _ in h.sock.sent))
check('uvaim: UV full by default', all(pk[18 + 73 + 11] == 255 for pk, _ in h.sock.sent))
os.remove(new.AIM)
new.time = Clock()
h = rig(new, FIX)
new.follow_spot(h, 1, secs=0.5)
check('no aim file -> holds the saved aim', len(h.sock.sent) > 5 and frame(h)[56 + 9] == 153)

# 11. calib.stop stops early
open(new.STOP, 'w').close()
new.time = Clock()
h = rig(new, FIX)
new.follow_spot(h, 1, secs=10.0)
new.spot(h, 1, secs=10.0)
check('calib.stop -> nothing sent', len(h.sock.sent) == 0)
os.remove(new.STOP)

# 12. channel meanings match the live hub_dmx.focus_out (parse only)
src = open(os.path.join(ROOT, 'hub_dmx.py')).read()
for line in ("data[a + 4] = slot", "data[a + 5] = gobo", "data[a + 6] = grot", "data[a + 8] = 12 if m > 0 else 0",
             "data[a + 9] = m", "data[a + 10] = 12 if uv > 0 else 0", "data[a + 11] = uv",
             "data[a + 15] = int(clamp(int(hd.get('motor_speed', 0)), 0, 255))", "/ 240.0 * 65535.0", "/ 540.0 * 65535.0"):
    check('hub_dmx.focus_out has: %s' % line, line in src)

# 13. the network really is blocked, live files untouched
try:
    socket.socket()
    check('socket blocked', False)
except NoNet:
    check('socket blocked', True)
check('live calib.py / calib_aim.json / hub_dmx.py unchanged', [sha(p) for p in LIVE] == before)

print('%d passed, %d failed' % (PASSES[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
