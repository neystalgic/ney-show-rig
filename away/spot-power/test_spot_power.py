#!/usr/bin/env python3
# Offline test for spot_power.py (Nov 17): fake Hue bridge, fake DMX node, fake hub, fake clock, fake voice.
# The network is blocked for the whole run -- any real request fails the test.
# Run:  python3 away/spot-power/test_spot_power.py
import hashlib, json, os, socket, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print('FAIL', name)


def _blocked(*a, **k):
    raise AssertionError('network call attempted')


socket.socket.connect = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked


# ---------------------------------------------------------------- fakes
class Bridge:
    def __init__(self, lights):
        self.lights = lights          # list of v2 light dicts
        self.puts = []

    def v2(self, cfg, path, method='GET', body=None):
        if method == 'GET' and path == 'light':
            return {'data': self.lights}
        if method == 'PUT':
            lid = path.split('/', 1)[1]
            self.puts.append((lid, body['on']['on']))
            for l in self.lights:
                if l['id'] == lid:
                    l['on'] = {'on': body['on']['on']}
            return {}
        raise AssertionError('unexpected bridge call %s %s' % (method, path))


def plug(lid, name, on=False, **extra):
    d = {'id': lid, 'metadata': {'name': name, 'archetype': 'plug'}, 'on': {'on': on}}
    d.update(extra)
    return d


def node(spot_master=0, spot_uv=0, error=None):
    heads = [dict(name='Head %d' % i, type='lm70s', master=255) for i in range(1, 5)]
    heads += [dict(name='Spot 1', type='focus17', master=spot_master, uv=spot_uv),
              dict(name='Spot 2', type='focus17', master=0, uv=0)]
    return dict(heads=heads, error=error)


class Clock:
    t = 1000000.0

    def __call__(self):
        return self.t


def setup(lights, settings=None):
    import spot_power as sp
    tmp = tempfile.mkdtemp()
    sp.SETTINGS = os.path.join(tmp, 'spot_power.json')
    sp.LOG = os.path.join(tmp, 'spot_power.log')
    if settings:
        json.dump(settings, open(sp.SETTINGS, 'w'))
    br = Bridge(lights)
    sys.modules['hue_stream'] = types.SimpleNamespace(load_config=lambda: {}, v2=br.v2)
    clk = Clock()
    sp._now = clk
    said = []
    sp.SAY = lambda text, voice: said.append((text, voice))
    env = {'node': node(), 'show': {}}
    sp.node_status = lambda: env['node']
    sp.hub_show = lambda: env['show']
    sp.STATE.update(plugs={}, on={}, node=None, dark_since=None, lost_since=None, warm_until=0.0, off_at=0.0,
                    hold_until=0.0, fan_said=False, why_on=None, busy=False)
    return sp, br, clk, said, env


def lit(sp):
    return {n: on for n, (_, on) in sp.find_plugs().items()}


LIVE = [os.path.join(ROOT, f) for f in ('rig_control.py', 'rig_health.py', 'selftest.py', 'head_power.py')]
before = {p: hashlib.sha256(open(p, 'rb').read()).hexdigest() for p in LIVE if os.path.exists(p)}

# 1. dormant without plugs; lamps and other plugs are never switched
sp, br, clk, said, env = setup([plug('h1', 'Head 1'), {'id': 'L1', 'metadata': {'name': 'Spot 1'}, 'on': {'on': False},
                                                       'dimming': {'brightness': 50}}, plug('m', 'Mac')])
sp._tick()
check('dormant with no Spot plugs', sp.STATE['last'].startswith('dormant') and not br.puts)
check('lamp named Spot 1 is not a plug', sp.find_plugs() == {})
check('request_on dormant is quiet', sp.request_on(quiet=True) == '')

# 2. find + name rules
sp, br, clk, said, env = setup([plug('a', 'Spot 1'), plug('b', ' spot 2 '), plug('c', 'Spot 3'), plug('d', 'Spot 1 projector'),
                                plug('e', 'Head 2'), plug('f', 'Scarlett')])
check('finds Spot 1 + Spot 2 only', sorted(sp.find_plugs()) == [1, 2])
check('never a projector/Scarlett/Head plug', set(lid for lid, _ in sp.find_plugs().values()) == {'a', 'b'})

# 3. a spot look powers them on (node up), fan reminder once, other plugs untouched
r = sp.after_look('uvstars')
check('uvstars powers on', lit(sp) == {1: True, 2: True} and 'powering up' in r)
check('only spot plugs switched', set(l for l, _ in br.puts) == {'a', 'b'})
check('fan reminder said once', said == [(sp.FAN_LINE, 'Moira')])
sp._tick(); sp._tick()
check('fan reminder not repeated', len(said) == 1)

# 4. node down -> ON refused
sp, br, clk, said, env = setup([plug('a', 'Spot 1'), plug('b', 'Spot 2')])
env['node'] = None
r = sp.request_on()
check('ON refused with node down', 'DMX node first' in r and not br.puts)
env['node'] = node(error='enttec unplugged')
check('ON refused with node error', 'DMX node first' in sp.request_on() and not br.puts)
env['show'] = {'on': True, 'act': 'gobos'}
sp._tick()
check('watcher never powers on with node in error', not br.puts)

# 5. watcher: act gobos/uv/burst powers on; zones does not
for act, want in (('zones', False), ('hues', False), ('gobos', True), ('uv', True), ('burst', True)):
    sp, br, clk, said, env = setup([plug('a', 'Spot 1'), plug('b', 'Spot 2')])
    env['show'] = {'on': True, 'act': act}
    sp._tick()
    check('act %s -> on=%s' % (act, want), lit(sp) == {1: want, 2: want})
sp, br, clk, said, env = setup([plug('a', 'Spot 1'), plug('b', 'Spot 2')])
env['show'] = {'on': False, 'act': 'gobos'}
sp._tick()
check('show off -> act ignored', not br.puts)
env['show'] = {}
env['node'] = node(spot_uv=180)
sp._tick()
check('node sending UV to a spot -> on', lit(sp) == {1: True, 2: True} and sp.STATE['why_on'] == 'spot lit')

# 6. idle: dark for spot_idle_min -> off; warm-up and activity reset the timer
sp, br, clk, said, env = setup([plug('a', 'Spot 1'), plug('b', 'Spot 2')], {'spot_idle_min': 10})
env['show'] = {'on': True, 'act': 'uv'}
sp._tick()
check('on by act', lit(sp) == {1: True, 2: True})
env['show'] = {'on': True, 'act': 'zones'}
clk.t += 5; sp._tick()
check('warm-up: no dark timer yet', sp.STATE['dark_since'] is None)
clk.t += 30; sp._tick()
start = sp.STATE['dark_since']
check('dark timer starts after warm-up', start == clk.t)
clk.t += 9 * 60; sp._tick()
check('still on after 9 dark min', lit(sp) == {1: True, 2: True})
env['show'] = {'on': True, 'act': 'gobos'}
clk.t += 30; sp._tick()
check('act resets the dark timer', sp.STATE['dark_since'] is None and lit(sp)[1])
env['show'] = {'on': True, 'act': 'zones'}
clk.t += 5; sp._tick()
clk.t += 10 * 60 - 1; sp._tick()
check('on at 9:59 dark', lit(sp)[1])
clk.t += 2; sp._tick()
check('off after 10 dark min', lit(sp) == {1: False, 2: False})
check('fan flag resets when Spot 2 goes off', sp.STATE['fan_said'] is False)

# 7. min_off_s: no instant re-power after an off
env['show'] = {'on': True, 'act': 'uv'}
clk.t += 10; sp._tick()
check('no re-power within min_off_s', lit(sp) == {1: False, 2: False})
clk.t += 60; sp._tick()
check('re-power after min_off_s', lit(sp) == {1: True, 2: True})
check('fan reminder again on the next power-on', len(said) == 2)

# 8. node lost -> off after node_lost_s
sp, br, clk, said, env = setup([plug('a', 'Spot 1', on=True), plug('b', 'Spot 2', on=True)], {'node_lost_s': 30})
sp._tick()
env['node'] = None
clk.t += 5; sp._tick()
check('node lost: still on at 0 s', lit(sp)[1])
clk.t += 31; sp._tick()
check('node lost 30 s -> off', lit(sp) == {1: False, 2: False})
check('Spot 2 seen on at start -> reminder', said == [(sp.FAN_LINE, 'Moira')])

# 9. switched off by hand -> left off for manual_hold_min; a spot look still wins
sp, br, clk, said, env = setup([plug('a', 'Spot 1'), plug('b', 'Spot 2')], {'manual_hold_min': 30})
env['show'] = {'on': True, 'act': 'uv'}
sp._tick()
for l in br.lights:
    l['on'] = {'on': False}               # Michael turns them off in the Hue app
clk.t += 100; sp._tick()
check('hand-off detected', sp.STATE['hold_until'] > clk.t and lit(sp) == {1: False, 2: False})
clk.t += 20 * 60; sp._tick()
check('watcher respects hand-off for 30 min', lit(sp) == {1: False, 2: False})
check('status shows the hand-off hold', 'hand_off_for_s' in sp.status())
r = sp.after_look('showuv')
check('a spot look overrides the hand-off', lit(sp) == {1: True, 2: True})

# 10. off looks power down (synchronous here), other looks leave them
sp, br, clk, said, env = setup([plug('a', 'Spot 1', on=True), plug('b', 'Spot 2', on=True)])
sp.STATE['on'] = {1: True, 2: True}
sp.after_look('rainbow')
check('rainbow leaves spots alone', not br.puts)
r = sp.request_off(wait=0, why='night', background=False)
check('request_off switches both off', lit(sp) == {1: False, 2: False} and 'off' in r)
clk.t += 5; sp._tick()
check('our own off is not taken as a hand-off', sp.STATE['hold_until'] == 0.0)
check('night is an off look', 'night' in sp.OFF_LOOKS and 'off' in sp.OFF_LOOKS and 'rest' in sp.OFF_LOOKS)
check('spot looks', sp.SPOT_LOOKS == {'uvstars', 'movieuv', 'moviechill', 'showuv'})

# 11. settings: disabled, fan reminder off, custom voice, after_look never raises
sp, br, clk, said, env = setup([plug('a', 'Spot 1'), plug('b', 'Spot 2')], {'enabled': False})
check('disabled: request_on refuses', 'switched off' in sp.request_on())
sp._tick()
check('disabled: watcher idle', not br.puts and 'disabled' in sp.STATE['last'])
sp, br, clk, said, env = setup([plug('b', 'Spot 2')], {'fan_reminder': False})
sp.request_on()
check('fan reminder can be muted', said == [] and lit(sp) == {2: True})
sp, br, clk, said, env = setup([plug('b', 'Spot 2')], {'voice': 'Daniel'})
sp.request_on()
check('custom voice', said == [(sp.FAN_LINE, 'Daniel')])
sp, br, clk, said, env = setup([plug('a', 'Spot 1')])
sys.modules['hue_stream'] = types.SimpleNamespace(load_config=lambda: {}, v2=lambda *a, **k: _blocked())
check('bridge down: request_on returns a message', 'Hue Bridge' in sp.request_on())
try:
    sp.after_look('uvstars'); sp.after_look('off'); ok = True
except Exception:
    ok = False
check('after_look never raises', ok)

# 12. spots_lit only looks at Focus Spots (lit heads do not count)
check('heads lit alone != spots lit', sp.spots_lit(node()) is False)
check('spot dimmer counts', sp.spots_lit(node(spot_master=10)) is True)
check('empty status', sp.spots_lit(None) is False and sp.spots_lit({}) is False)

after = {p: hashlib.sha256(open(p, 'rb').read()).hexdigest() for p in before}
check('live files unchanged', before == after)
print('%d/%d passed' % (len(PASS), len(PASS) + len(FAIL)))
sys.exit(1 if FAIL else 0)
