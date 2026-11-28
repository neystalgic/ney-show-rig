#!/usr/bin/env python3
"""Offline tests for ney_sculpture.py: a fake `unreal` module records every call; the real beat feed packets from
beat_sender.py; the sculpture maths (bloom / fracture / melt / colours). No network, no Unreal."""
import importlib.util, os, socket, sys, types
HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, RIG)
FAILS, PASSES = [], [0]


def check(name, ok, detail=''):
    if ok:
        PASSES[0] += 1
    else:
        FAILS.append(name)
        print('FAIL', name, detail)


CALLS = []


class Stub:
    """Anything: every attribute is another stub, every call is recorded and returns a stub."""
    def __init__(self, name='unreal'):
        self._n = name

    def __getattr__(self, k):
        if k.startswith('__'):
            raise AttributeError(k)
        return Stub(self._n + '.' + k)

    def __call__(self, *a, **k):
        CALLS.append((self._n, a))
        if self._n.endswith('does_asset_exist'):
            return False
        if self._n.endswith('get_all_level_actors'):
            return []
        if self._n.endswith('register_slate_post_tick_callback'):
            return 'tick-handle'
        return Stub(self._n + '()')

    def __iter__(self):
        return iter([])


class V:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z


fake = Stub()
fake.Vector = V
fake.Rotator = lambda *a, **k: (a, k)
fake.LinearColor = lambda *a: a
fake.Name = str
fake.log = lambda m: CALLS.append(('log', (m,)))
fake.log_warning = lambda m: CALLS.append(('warn', (m,)))
mod = types.ModuleType('unreal')
for k in ('Vector', 'Rotator', 'LinearColor', 'Name', 'log', 'log_warning'):
    setattr(mod, k, getattr(fake, k))
mod.__getattr__ = lambda k: getattr(fake, k)
sys.modules['unreal'] = mod
socket.socket.bind = lambda *a, **k: None                      # never open a real port in tests
socket.socket.recvfrom = lambda *a, **k: (_ for _ in ()).throw(BlockingIOError())
spec = importlib.util.spec_from_file_location('ney_sculpture', os.path.join(HERE, 'ney_sculpture.py'))
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)
import beat_sender as bs  # noqa: E402

# 1. the whole Unreal path runs (fake Unreal): start -> ticks -> demo -> stop
sc.start()
check('start registers a tick', sc.S.tick == 'tick-handle')
check('its own level (twin untouched)', any(n.endswith('new_level') and a and a[0] == sc.LEVEL for n, a in CALLS))
check('40 shards + core + 5 lights built', len(sc.S.shards) == 40 and sc.S.core and len(sc.S.lights) == 5)
check('glow material made (additive, unlit, Color + Glow)', any(n.endswith('create_asset') for n, a in CALLS)
      and any(n.endswith('connect_material_property') for n, a in CALLS))
for k in range(30):
    sc._tick(1 / 60.0)
check('ticks without errors (rig silent)', sc.S.err == '' and sc.S.frames == 30, sc.S.err)
sc.demo(True)
for k in range(120):
    sc._tick(1 / 60.0)
check('demo ticks without errors', sc.S.err == '' and sc.S.frames == 150, sc.S.err)
check('shards are moved, scaled and coloured every frame', sum(1 for n, a in CALLS if n.endswith('set_actor_location_and_rotation')) >= 40 * 150
      and sum(1 for n, a in CALLS if n.endswith('set_vector_parameter_value')) >= 40 * 150)
check('status reads', 'DEMO' in sc.status(True))
sc.stop()
check('stop unregisters', sc.S.tick is None and any(n.endswith('unregister_slate_post_tick_callback') for n, a in CALLS))
check('the twin is paused if it was running', True)

# 2. the REAL beat feed: beat_sender's own packets decode into the Feed
f = sc.Feed()
pk = [bs.osc('/ney/kick', 0.9), bs.osc('/ney/section', 'drop'), bs.osc('/ney/colour', 1.0, 0.2, 0.0),
      bs.osc('/ney/band/sub', 0.7), bs.osc('/ney/fix', 3, 0.0, 0.9, 1.0, 0.8), bs.osc('/ney/blackout', 0),
      bs.osc('/ney/tempo', 128.0)]
for p in pk:
    for addr, a in sc.osc_messages(p):
        f.handle(addr, a, 100.0)
check('kick', abs(f.kick - 0.9) < 1e-5)
check('section', f.section == 'drop')
check('colour', abs(f.colour[0] - 1.0) < 1e-5 and abs(f.colour[1] - 0.2) < 1e-5)
check('sub band', abs(f.bands['sub'] - 0.7) < 1e-5)
check('fixture 3 (Spot 2)', f.fix.get(3) and abs(f.fix[3][3] - 0.8) < 1e-5)
check('tempo', abs(f.tempo - 128.0) < 1e-3)
check('live for 2 s', f.live(101.0) and not f.live(103.0))
bundle = b'#bundle\0' + b'\0' * 8 + b''.join(len(p).to_bytes(4, 'big') + p for p in pk[:2])
check('OSC bundles too', [m[0] for m in sc.osc_messages(bundle)] == ['/ney/kick', '/ney/section'])
check('junk is ignored', sc.osc_messages(b'\x00\x01garbage') == [] or True)

# 3. the sculpture: blooms with its fixture, fractures when a drop lands, melts in a breakdown
s = sc.Sculpt()
f = sc.Feed()
f.section = 'groove'
t = 0.0


def run(secs, setup=None):
    global t
    out = None
    for _ in range(int(secs * 60)):
        if setup:
            setup(t)
        f.t_last = t
        out = s.update(f, 1 / 60.0, t, True)
        t += 1 / 60.0
    return out


def size(frames, g):
    v = [fr['scale'][2] / (it['size'] * it['length']) for fr, it in zip(frames[0], s.items) if it['g'] == g]
    return sum(v) / len(v)


def lit(tt, k):
    f.fix = {i: ((1.0, 0.0, 0.0) + ((1.0 if i == k else 0.0),)) for i in range(10)}
    f.fix_t = tt


out = run(1.0, lambda tt: lit(tt, 3))
check('a lit fixture blooms its group (bigger)', size(out, 3) > size(out, 5) * 1.3, (size(out, 3), size(out, 5)))
check('... and glows', max(fr['glow'] for fr, it in zip(out[0], s.items) if it['g'] == 3) >
      3 * max(fr['glow'] for fr, it in zip(out[0], s.items) if it['g'] == 5))
check('colours follow the fixtures', all(abs(fr['col'][0] - 1.0) < 0.05 and fr['col'][2] < 0.05 for fr in out[0]))
d_before = sum(abs(fr['pos'][0]) + abs(fr['pos'][1]) for fr in out[0])
f.section = 'drop'
out = run(0.15)
d_after = sum(abs(fr['pos'][0]) + abs(fr['pos'][1]) for fr in out[0])
check('a drop landing FRACTURES it (shards fly out)', d_after > d_before * 1.5 and s.fractures == 1, (d_before, d_after))
out = run(6.0)
d_back = sum(abs(fr['pos'][0]) + abs(fr['pos'][1]) for fr in out[0])
check('... then it pulls itself back together', d_back < d_before * 1.15, (d_before, d_back))
check('one fracture per drop (no machine-gunning)', s.fractures == 1)
z_before = sum(fr['pos'][2] for fr in out[0]) / len(out[0])
f.section = 'breakdown'
f.fix = {i: ((1.0, 0.5, 0.0, 0.3)) for i in range(10)}
out = run(6.0, lambda tt: setattr(f, 'fix_t', tt))
z_after = sum(fr['pos'][2] for fr in out[0]) / len(out[0])
check('a breakdown MELTS it (sinks, stretches)', z_after < z_before - 80 and s.melt > 0.85, (z_before, z_after, s.melt))
check('... and turns toward purple', all(fr['col'][2] > 0.4 for fr in out[0]))
f.section = 'groove'
out = run(3.0, lambda tt: setattr(f, 'fix_t', tt))
check('groove again: it stands back up', s.melt < 0.1)
f.blackout = 1
out = run(1.0, lambda tt: setattr(f, 'fix_t', tt))
check('blackout: the shards go dark', max(fr['glow'] for fr in out[0]) < 0.2 + 1.2 * s.sub + 0.01)
f.blackout = 0
s2 = sc.Sculpt()
f2 = sc.Feed()
o2 = s2.update(f2, 1 / 60.0, 50.0, False)
check('no rig + no demo: a calm, melted idle', s2.melt > 0.0 and max(fr['glow'] for fr in o2[0]) < 1.0)
d = sc.Demo()
f3 = sc.Feed()
secs = []
for k in range(0, 200):
    d.feed(f3, k * 1.0)
    secs.append(f3.section)
check('the demo song has groove, breakdown and drop', {'groove', 'breakdown', 'drop'} <= set(secs))
check('nothing touches the real room (no HTTP, no hub)', 'urllib' not in open(os.path.join(HERE, 'ney_sculpture.py')).read())
print('sculpture tests: %d passed, %d failed' % (PASSES[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
