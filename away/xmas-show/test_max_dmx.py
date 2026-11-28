#!/usr/bin/env python3
"""hub_dmx with the MAX show (Nov 25): the director's strobe hits go through every existing guard --
strobe cone, strobe_max_hz per head, guest mode, movie, blackout. Fake hub, fake socket, no network."""
import json, os, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))     # the Hue Rig folder (hub_chase etc.)
sys.path.insert(0, HERE)
import hub_dmx as hd_  # noqa: E402

FAILS, PASSES = [], [0]


def check(name, ok, detail=''):
    if ok:
        PASSES[0] += 1
    else:
        FAILS.append(name)
        print('FAIL', name, detail)


class Sock:
    def __init__(self):
        self.sent = []

    def sendto(self, b, addr):
        self.sent.append(bytes(b))


class Show:
    section = 'groove'
    env = {}


class Hub:
    def __init__(self, **s):
        base = dict(dmx_host='192.168.1.80', dmx_on=True, dmx_level=0.75, strobe_max_hz=3.0, dmx_pattern='max')
        base.update(s)
        self.state = {'settings': base}
        self.live = {'master': 1.0}
        self.blackout = False
        self.audioshow = Show()
        self.audio = None
        self.t_motion = 0.0


class Dir:
    """Stands in for the director: a max frame whose hit id changes `rate` times a second."""
    def __init__(self, rate=16.0, lean=0.3, burst=False, act='max', white=False):
        self.rate, self.lean, self.burst, self.act, self.white = rate, lean, burst, act, white

    def step(self, now, beats, pmode, heads):
        hid = int(now * self.rate)
        hs = {i: dict(level=0.5, u=0.5, lean=self.lean, rgb=(1.0, 0.0, 0.0), flash=hid, white=self.white) for i in range(4)}
        sp = {i: dict(level=0.5, flash=hid, white=self.white, fx=dict(color=22, gobo=0)) for i in (4, 5)}
        return dict(heads=hs, zones=[], spots=sp, full=True, rgb=(1, 0, 0), v=1.0, act=self.act, burst=self.burst,
                    burst_rgbw=(0.0, 0.0, 0.0, 1.0) if self.burst else None)

    def theta(self, cv, lean_max):
        return cv['lean'] * lean_max

    def pan(self, cv, pmin, pmax):
        return pmin + cv['u'] * (pmax - pmin)


HEADS = [dict(addr=a, tilt_up=32768, tilt_dir=1, tilt_max_deg=80.0, pan_min=0, pan_max=65535, motor_speed=0, calibrated=True)
         for a in (1, 15, 29, 43)] + [dict(addr=a, type='focus17', tilt_up=32768, tilt_dir=1, tilt_max_deg=80.0, pan_min=0,
                                           pan_max=65535, calibrated=True) for a in (101, 120)]


def make(hub, d):
    o = hd_.Heads.__new__(hd_.Heads)
    o.__init__.__func__  # (not called: no thread, no real socket)
    o.hub, o.sock, o.seq, o.t_send = hub, Sock(), 0, 0.0
    o.node_cfg, o.node_status, o.status, o.ip = {'heads': [dict(h) for h in HEADS], 'universe': 0}, None, 'off', '192.168.1.80'
    o.st = []
    o.mv_fast = o.mv_slow = o.mv_bri = 0.0
    o.k_prev, o.k_last, o.k_target, o.k_tm = 0.0, -10.0, 0.0, 0.0
    o.turn_i, o.turn_t, o.turn_phrase = 0, -10.0, None
    o.turn_n, o.wall_t = 0, -10.0
    o.sweep_t, o.sweep_n, o.sweep_amp = -10.0, 0, 0.0
    o.sec_prev, o.phrase_prev, o.last_flash, o.flashes = '', None, -10.0, 0
    o.chase, o.run = d, True
    o._guest_c = (1e18, False)                      # guest mode off (cached)
    return o


def play(o, secs=4.0, pmode='music'):
    t0 = getattr(o, '_t_last', 1000.0)
    t, flashes, white = t0, {i: 0 for i in range(6)}, 0
    prev = {i: st.get('flash_t') for i, st in enumerate(getattr(o, 'st', []) or [])}
    bursts = 0
    while t < t0 + secs:
        o.frame(t, 0.025, (t - 1000.0) * 2.0, [(1.0, 0.0, 0.0)] * 5, pmode)
        for i, st in enumerate(o.st):
            ft = st.get('flash_t')
            if ft is not None and ft != prev.get(i):
                prev[i] = ft
                flashes[i] += 1
                white += 1 if st.get('white') else 0
        bursts += 1 if getattr(o, 'flash_mode', False) else 0
        t += 0.025
    o._t_last = t
    return flashes, white, bursts


o = make(Hub(), Dir())
f, w, _ = play(o)
check('hits fire on every head + spot', all(v > 0 for v in f.values()), f)
check('never faster than strobe_max_hz (3/s) per head', all(v <= 3 * 4 + 1 for v in f.values()), f)
o = make(Hub(strobe_max_hz=8.0), Dir())
f8, _, _ = play(o)
check('strobe_max_hz 8 allows more, still capped', all(9 * 4 >= v > 3 * 4 + 1 for v in f8.values()), f8)
o = make(Hub(strobe_max_hz=50.0), Dir(rate=40.0))
f50, _, _ = play(o)
check('the hub cap of 8/s holds even if someone sets 50', all(v <= 8 * 4 + 1 for v in f50.values()), f50)
o = make(Hub(dmx_lean_cap=85.0), Dir(lean=0.95))
play(o, secs=4.0)                               # let the heads tip out past the cone first
fc, _, _ = play(o)
heads_only = {i: v for i, v in fc.items() if i < 4}
check('heads outside the strobe cone never flash', all(v == 0 for v in heads_only.values()), fc)
o = make(Hub(), Dir())
o._guest_c = (1e18, True)
fg, _, bg = play(o)
check('guest mode: no hits at all', all(v == 0 for v in fg.values()), fg)
o = make(Hub(), Dir(burst=True))
o._guest_c = (1e18, True)
_, _, bg = play(o)
check('guest mode: no burst', bg == 0, bg)
o = make(Hub(movie=True), Dir())
fm, _, _ = play(o)
check('movie: no hits', all(v == 0 for v in fm.values()), fm)
h = Hub()
o = make(h, Dir())
h.blackout = True
fb, _, _ = play(o)
check('blackout: no hits', all(v == 0 for v in fb.values()), fb)
o = make(Hub(), Dir(act='rainbow'))
fr, _, br = play(o)
check('the rainbow show never strobes (unchanged)', all(v == 0 for v in fr.values()) and br == 0, (fr, br))
o = make(Hub(), Dir(burst=True))
_, _, bb = play(o, secs=1.0)
check('a drop burst uses the heads\' own strobe', bb > 0 and o.flash_master >= 135 and o.flash_rgbw == (0.0, 0.0, 0.0, 1.0))
data = o.sock.sent[-1][18:]
check('burst: head master channel in the strobe range', 135 <= data[5] <= 239, data[5])
o = make(Hub(), Dir(white=True))
fw, ww, _ = play(o)
check('mono + white hits are white', ww > 0)
# guest-mode file reading
tmp = tempfile.mkdtemp()
try:
    shutil.copy(os.path.join(HERE, 'hub_dmx.py'), tmp)
    sys.path.insert(0, tmp)
    import importlib.util
    spec = importlib.util.spec_from_file_location('hub_dmx_tmp', os.path.join(tmp, 'hub_dmx.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    g = m.Heads.__new__(m.Heads)
    check('no guest file = not guest', g._guest() is False)
    json.dump({'guest': True}, open(os.path.join(tmp, 'guest_mode.json'), 'w'))
    g._guest_c = None
    check('guest file on = guest', g._guest() is True)
    open(os.path.join(tmp, 'guest_mode.json'), 'w').write('{broken')
    g._guest_c = None
    check('unreadable guest file = treated as guest (safe side)', g._guest() is True)
finally:
    shutil.rmtree(tmp)
print('max dmx tests: %d passed, %d failed' % (PASSES[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
