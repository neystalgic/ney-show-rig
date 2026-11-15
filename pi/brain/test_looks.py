#!/usr/bin/env python3
# Offline tests for looks.py (Pi calm looks). No lights, no network: sockets are blocked, the Hue bridge is a fake.
#   python3 test_looks.py
import ast, os, socket, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)


def _blocked(*a, **k):
    raise OSError('network blocked in tests')
socket.socket.connect = _blocked
socket.create_connection = _blocked

import looks as L

PASS, FAIL = [], []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    if not ok:
        print('FAIL', name, detail)


# ---------------------------------------------------------------- 1. same numbers as the Mac's rig_control.LOOKS
src = os.path.join(RIG, 'rig_control.py')
if os.path.exists(src):
    tree = ast.parse(open(src).read())
    mac = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'LOOKS' for t in node.targets) and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                name = ast.literal_eval(k)
                for c in ast.walk(v):
                    if isinstance(c, ast.Call) and getattr(c.func, 'id', '') == 'hue_lights':
                        mac[name] = ('static', ast.literal_eval(c.args[0]))
                    if isinstance(c, ast.Call) and getattr(c.func, 'id', '') == 'start_ambient':
                        mac[name] = ('ambient', [ast.literal_eval(a) for a in c.args])
    for name, (_, body) in L.STATIC.items():
        if name == 'night':              # rig_control's night_mode() is a function -- same body as nightlight
            check('night = nightlight body', body == L.STATIC['nightlight'][1])
            continue
        check('static %s matches the Mac' % name, mac.get(name) == ('static', body), '%s vs %s' % (mac.get(name), body))
    for name, (_, spec) in L.AMBIENT.items():
        kind, args = mac.get(name, (None, []))
        args = [a for a in args if a != 'heads']
        want = L._amb(*args) if kind == 'ambient' else None
        check('ambient %s matches the Mac' % name, spec == want, '%s vs %s' % (spec, want))
    calm_mac = {n for n, (k, _) in mac.items() if k == 'ambient'} | {n for n, (k, _) in mac.items() if k == 'static'}
    check('every Mac calm look exists on the Pi', calm_mac <= set(L.looks()), calm_mac - set(L.looks()))
else:
    print('(rig_control.py not here -- Mac comparison skipped, e.g. on the Pi)')

# ---------------------------------------------------------------- 2. the wheel is the Mac's wheel
try:
    import make_wheel
    w = make_wheel.wheel()
    check('wheel table = hub_palette + hue_stream', w == L.WHEEL, 'rerun make_wheel.py')
except ImportError:
    print('(hub_palette not here -- wheel comparison skipped)')
check('wheel has 72 entries', len(L.WHEEL) == 72)
check('wheel_xy on the table', L.wheel_xy(0) == L.WHEEL[0] and L.wheel_xy(360) == L.WHEEL[0] and L.wheel_xy(725) == L.WHEEL[1])
mid = L.wheel_xy(2.5)
check('wheel_xy halfway', abs(mid[0] - (L.WHEEL[0][0] + L.WHEEL[1][0]) / 2) < 1e-3)
check('wheel_xy wraps 357.5', abs(L.wheel_xy(357.5)[0] - (L.WHEEL[71][0] + L.WHEEL[0][0]) / 2) < 1e-3)
check('xy always in range', all(0 < c < 1 for h in range(0, 720, 7) for c in L.wheel_xy(h + 0.3)))

# ---------------------------------------------------------------- 3. breathing shape = ambient_fade.py's
check('breath starts low', L.breath_level(0, 10) < 1e-9)
check('breath peaks at 40%', abs(L.breath_level(4, 10) - 1) < 1e-9)
check('breath back low at the end', L.breath_level(9.999, 10) < 1e-4)
check('breath in 0..1', all(0 <= L.breath_level(t / 10.0, 10) <= 1 for t in range(300)))

# ---------------------------------------------------------------- 4. frames
rb = L.AMBIENT['rainbow'][1]
bris = []
for t in range(0, 100):
    f = L.frame(rb, t * 0.5, [False] * 6 + [True])
    xys = {(b['color']['xy']['x'], b['color']['xy']['y']) for b in f if 'color' in b}
    if len(xys) != 1:
        check('rainbow: every lamp the same colour', False, xys)
        break
    g = f[-1]['gradient']['points']
    if {(p['color']['xy']['x'], p['color']['xy']['y']) for p in g} != xys:
        check('rainbow: gradient lamp the same colour too', False)
        break
    bris.append(f[0]['dimming']['brightness'])
else:
    check('rainbow: every lamp the same colour (and gradient lamp)', True)
check('rainbow breathes 22..75', min(bris) < 23 and max(bris) > 74 and all(21.99 <= b <= 75.01 for b in bris), (min(bris), max(bris)))
check('rainbow fade = 1.25 s step', L.frame(rb, 0, [False])[0]['dynamics']['duration'] == 1250)
check('rainbow goes round in 90 s', abs(L.base_hue(rb, 90) - 360) < 1e-9)
room = L.frame(L.AMBIENT['rainbowroom'][1], 5, [False] * 5)
check('rainbowroom: lamps differ', len({(b['color']['xy']['x'], b['color']['xy']['y']) for b in room}) == 5)
check('rainbowroom: steady 70%, 2 s fades', all(b['dimming']['brightness'] == 70 and b['dynamics']['duration'] == 2000 for b in room))
rg = L.AMBIENT['redglow'][1]
hs = [L.base_hue(rg, t) for t in range(0, 240)]
check('redglow stays 315..365 (purple-pink-red)', min(hs) >= 315 - 1e-9 and max(hs) <= 365 + 1e-9)
check('one lamp is fine', len(L.frame(L.AMBIENT['breathe'][1], 3, [True])) == 1)


# ---------------------------------------------------------------- fake Hue bridge
class Bridge:
    def __init__(self, area=True, fail=False):
        self.puts, self.fail = [], fail
        self.lights = [
            {'id': 'L1', 'metadata': {'name': 'Couch lamp'}, 'dimming': {}},
            {'id': 'L2', 'metadata': {'name': 'Desk lamp'}, 'dimming': {}},
            {'id': 'L3', 'metadata': {'name': 'Play gradient'}, 'dimming': {}, 'gradient': {'points_capable': 5}},
            {'id': 'P1', 'metadata': {'name': 'Head 1 plug', 'archetype': 'plug'}, 'on': {}},
            {'id': 'P2', 'metadata': {'name': 'Spot 2'}, 'dimming': {}},
        ]
        self.area = area

    def __call__(self, method, path, body=None, timeout=5):
        if method == 'GET' and path == 'light':
            return {'data': self.lights}
        if method == 'GET' and path == 'entertainment_configuration':
            if not self.area:
                return {'data': []}
            locs = [{'service': {'rid': 'E%d' % i}, 'positions': [{'x': x, 'y': 0, 'z': 0}]}
                    for i, x in ((1, 0.5), (2, -0.8), (3, 0.1), (4, -0.2))]
            return {'data': [{'metadata': {'name': 'Music area'}, 'locations': {'service_locations': locs}}]}
        if method == 'GET' and path == 'entertainment':
            return {'data': [{'id': 'E1', 'renderer_reference': {'rtype': 'light', 'rid': 'L1'}},
                             {'id': 'E2', 'renderer_reference': {'rtype': 'light', 'rid': 'L2'}},
                             {'id': 'E3', 'renderer_reference': {'rtype': 'light', 'rid': 'L3'}},
                             {'id': 'E4', 'renderer_reference': {'rtype': 'light', 'rid': 'P2'}}]}
        if method == 'PUT':
            if self.fail and 'effects_v2' not in body:
                raise OSError('bridge gone')
            self.puts.append((path, body))
            return {}
        raise AssertionError('unexpected call %s %s' % (method, path))


import re
PLUG = re.compile(r'^\s*(head|spot|plug)\b', re.I)
is_plug = lambda l: (l.get('metadata') or {}).get('archetype') == 'plug' or bool(PLUG.match((l.get('metadata') or {}).get('name') or '')) or 'dimming' not in l

# ---------------------------------------------------------------- 5. lamp order
check('order = Music area left to right, no plugs/spots', L.lamp_order(Bridge(), is_plug) == [('L2', False), ('L3', True), ('L1', False)],
      L.lamp_order(Bridge(), is_plug))
check('no Music area -> every lamp by name', [r for r, _ in L.lamp_order(Bridge(area=False), is_plug)] == ['L1', 'L2', 'L3'])


# ---------------------------------------------------------------- 6. engine loop with a fake clock
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


br, ck, logs = Bridge(), Clock(), []
e = L.Engine(br, lamps=lambda b: br.puts.append(('ALL', b)), is_plug=is_plug, log=logs.append, clock=ck, sleep=ck.sleep)
n = e._loop(e.gen, rb, max_frames=40)
lamp_puts = [(p, b) for p, b in br.puts if 'effects_v2' not in b]
check('40 frames sent', n == 40 and len(lamp_puts) == 120, (n, len(lamp_puts)))
check('effects stopped first', all('effects_v2' in b for _, b in br.puts[:3]))
check('plugs and spots never touched', not any(('P1' in p or 'P2' in p) for p, _ in br.puts))
elapsed = ck.t - 1000.0
check('about one frame per 1.25 s', 49 <= elapsed <= 51.5, elapsed)
check('average rate under the bridge limit', len(lamp_puts) / elapsed <= L.MAX_PUTS_PER_S, len(lamp_puts) / elapsed)
fb = [b['dimming']['brightness'] for p, b in lamp_puts if p == 'light/L1']
check('loop breathes', min(fb) < 30 and max(fb) > 70, (min(fb), max(fb)))
# bridge down: logs once, keeps trying slowly, never crashes
bad, ck2, logs2 = Bridge(fail=True), Clock(), []
e2 = L.Engine(bad, lamps=lambda b: None, is_plug=is_plug, log=logs2.append, clock=ck2, sleep=ck2.sleep)
e2._loop(e2.gen, rb, max_frames=30)
check('bridge down: few log lines', 1 <= len(logs2) <= 4, logs2)
check('bridge down: backs off', ck2.t - 1000 > 60, ck2.t - 1000)

# ---------------------------------------------------------------- 7. engine threads (real time, a fraction of a second)
br3 = Bridge()
static_sent = []
e3 = L.Engine(br3, lamps=static_sent.append, is_plug=is_plug, log=lambda m: None)
check('rainbow starts', e3.run('rainbow') == L.AMBIENT['rainbow'][0] and e3.thread.is_alive())
time.sleep(0.3)
check('rainbow is sending', any('dimming' in b for _, b in br3.puts))
check('a show is not a Pi look (and leaves the rainbow running)', e3.run('show') is None and e3.thread.is_alive())
old = e3.thread
t0 = time.time()
check('purple replies', e3.run('purple') == 'Purple, full brightness.')
old.join(1.0)
check('old loop ends quickly when a new look starts', not old.is_alive() and time.time() - t0 < 0.5, time.time() - t0)
check('purple body', static_sent[-1]['color']['xy'] == {'x': 0.27, 'y': 0.12} and static_sent[-1]['dimming']['brightness'] == 100.0)
static_sent[-1]['dimming']['brightness'] = 1.0
check('static bodies are copies (table safe)', L.STATIC['purple'][1]['dimming']['brightness'] == 100.0)
e3.run('breathe'); t = e3.thread; e3.stop(); t.join(1.0)
check('stop() ends the loop', not t.is_alive())
check('morning fades over 8 s like the Mac', L.STATIC['morning'][1]['dynamics']['duration'] == 8000)
check('night red 12%', L.STATIC['night'][1]['dimming']['brightness'] == 12.0 and L.STATIC['night'][1]['color']['xy'] == {'x': 0.69, 'y': 0.30})

print('looks tests: %d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
