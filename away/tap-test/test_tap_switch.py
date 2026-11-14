#!/usr/bin/env python3
# Offline tests for the Tap Switch Mini (away/tap-test, Nov 14). No switch, no bridge, no lights, no network:
# tap_dryrun.py's fake bridge + fake clock stand in. Run:  python3 test_tap_switch.py
import ast, os, socket, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _no_network(*a, **k):
    raise AssertionError('tests must not touch the network')


socket.socket = _no_network
socket.create_connection = _no_network

import tap_dryrun as D

RIG_CONTROL = os.path.normpath(os.path.join(HERE, '..', '..', 'rig_control.py'))
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print('FAIL %s %s' % (name, detail))


def looks_in_rig_control():
    """The LOOKS keys in rig_control.py, read as text (never imported, so nothing starts)."""
    tree = ast.parse(open(RIG_CONTROL).read())
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'LOOKS' for t in node.targets) \
                and isinstance(node.value, ast.Dict):
            keys |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript) \
                and getattr(node.targets[0].value, 'id', '') == 'LOOKS':
            sl = node.targets[0].slice
            if isinstance(sl, ast.Constant):
                keys.add(sl.value)
    return keys


# 1. Michael's layout: 1 show, 2 movie (UV), 3 cycle, 4 night
r = D.Rig()
check('switch found by name', r.m.STATE['device'] == D.TAP_ID)
for n, want in ((1, 'show'), (2, 'movieuv'), (4, 'night')):
    r.tap(n)
    got = r.take()
    check('button %d tap -> %s' % (n, want), got == [want], got)
r.tap(3)
check('button 3 tap -> first cycle look', r.take() == [D.Rig().m.CYCLE[0]])

# 2. every look the switch can ask for really exists in rig_control (else rig_control's _tap drops it silently)
looks = looks_in_rig_control()
check('rig_control LOOKS read', len(looks) > 20, len(looks))
wanted = set(r.m.BUTTONS.values()) - {'cycle'} | set(r.m.CYCLE)
check('every button + cycle look is in rig_control.LOOKS', wanted <= looks, wanted - looks)
src = open(RIG_CONTROL).read()
check('rig_control wires the switch to apply()', 'tap_switch.start(_tap)' in src and 'if look in LOOKS' in src)

# 3. button 3 walks the cycle in order and wraps round
r = D.Rig()
for _ in range(len(r.m.CYCLE) + 2):
    r.tap(3)
got = r.take()
check('cycle order + wrap', got == r.m.CYCLE + r.m.CYCLE[:2], got)
check('status shows next cycle step', r.m.status()['cycle_next'] == 2, r.m.status())

# 4. THE FIX: a hold is one press = one action (live copy fired twice -> button 3 skipped a look)
for n, want in ((1, ['show']), (2, ['movieuv']), (4, ['night'])):
    r = D.Rig(); r.hold(n)
    check('hold button %d -> once' % n, r.take() == want)
r = D.Rig(); r.tap(3); r.hold(3); r.tap(3)
got = r.take()
check('button 3: tap, hold, tap = three steps in a row', got == r.m.CYCLE[:3], got)
r = D.Rig(); r.hold(3, repeats=12)                  # ~10 s hold, longer than HOLD_MAX_S, repeats keep it held
check('a very long hold still = one step', len(r.take()) == 1)
live = D.Rig(D.LIVE); live.tap(1); live.take(); live.hold(1)
live_double = len(live.take())
check('dry run reproduces the live double-fire (documents bug 1)', live_double == 2, live_double)
live = D.Rig(D.LIVE); live.quick_tap(4)
check('dry run reproduces the live swallowed first quick tap (documents bug 2)', live.take() == [])
r = D.Rig(); r.quick_tap(4)
check('fixed: first-ever quick tap of a never-pressed button counts', r.take() == ['night'])
r = D.Rig(); r.tap(4)
check('fixed: first-ever normal tap counts once', r.take() == ['night'])

# 5. presses that fall between two polls still count, exactly once
r = D.Rig(); r.quick_tap(2)
check('quick tap (only short_release seen) -> once', r.take() == ['movieuv'])
r = D.Rig()
r.bridge.report(4, 'initial_press'); r.bridge.report(4, 'long_press'); r.poll(); r.wait(0.8)
r.bridge.report(4, 'repeat'); r.poll(); r.wait(0.5); r.bridge.report(4, 'long_release'); r.poll()
check('hold whose start was missed -> once', r.take() == ['night'])
r = D.Rig()                                          # fast double tap on button 3
r.bridge.report(3, 'initial_press'); r.poll(); r.wait(0.2)
r.bridge.report(3, 'short_release'); r.bridge.report(3, 'initial_press'); r.poll(); r.wait(0.2)
r.bridge.report(3, 'short_release'); r.poll()
got = r.take()
check('fast double tap on 3 = two steps', got == r.m.CYCLE[:2], got)
r = D.Rig(); r.tap(1); r.wait(10); r.tap(1)
check('same button twice, 10 s apart = twice', r.take() == ['show', 'show'])
r = D.Rig()
r.bridge.report(1, 'initial_press'); r.bridge.report(4, 'initial_press'); r.poll(); r.wait(0.3)
r.bridge.report(1, 'short_release'); r.bridge.report(4, 'short_release'); r.poll()
check('two buttons at once -> both, once each', sorted(r.take()) == ['night', 'show'])

# 6. things that must NOT act
b = D.FakeBridge(); b.report(1, 'short_release')     # pressed before rig_control started
r = D.Rig(bridge=b); r.poll(); r.wait(1); r.poll()
check('old press from before start-up ignored', r.take() == [])
r = D.Rig(); r.bridge.report(2, 'long_release'); r.poll()
check('a stray long_release alone does nothing', r.take() == [])
b = D.FakeBridge()
b.buttons[5] = {'id': 'btn-x', 'owner': {'rid': 'some-dimmer'}, 'metadata': {'control_id': 1}, 'button': {}}
r = D.Rig(bridge=b)
b.buttons[5]['button'] = {'button_report': {'event': 'initial_press', 'updated': 'x1'}}
r.poll()
check("another switch's button ignored", r.take() == [])

# 7. finding the switch
r = D.Rig(bridge=D.FakeBridge(present=False)); r.tap(1)
check('no switch -> dormant, nothing happens', r.take() == [] and 'dormant' in r.m.status()['last'])
r = D.Rig(bridge=D.FakeBridge(name='Couch remote', product='Hue tap switch mini'))
check('found by product name', r.m.STATE['device'] == D.TAP_ID)
r = D.Rig(bridge=D.FakeBridge(name='Couch remote', product='Some button'), settings={'device_id': D.TAP_ID})
r.tap(4)
check('device_id in tap_switch.json wins', r.take() == ['night'])

# 8. tap_switch.json settings
r = D.Rig(settings={'enabled': False}); r.tap(1)
check('enabled: false -> nothing', r.take() == [] and 'disabled' in r.m.status()['last'])
r = D.Rig(settings={'buttons': {'1': 'cozy', '2': 'cycle', '3': 'off', '4': 'nightlight'}, 'cycle': ['breathe', 'upbeat']})
for n in (1, 2, 2, 2, 3, 4):
    r.tap(n)
got = r.take()
check('custom buttons + cycle', got == ['cozy', 'breathe', 'upbeat', 'breathe', 'off', 'nightlight'], got)

# 9. robustness + safety
r = D.Rig(); hs = r.m._hs(); real = hs.v2
def _offline(*a, **k):
    raise OSError('bridge offline')
hs.v2 = _offline
try:
    r.poll(); outage_raised = False
except OSError:
    outage_raised = True                             # watch() catches this, logs, waits 2 s
hs.v2 = real; r.tap(2)
check('bridge outage: next press after it comes back works', outage_raised and r.take() == ['movieuv'])
r = D.Rig(); r.bridge.report(1, None); r.poll()
check('old bridge with no event name still acts once', r.take() == ['show'])
r = D.Rig()
for n in (1, 2, 3, 4):
    r.tap(n); r.hold(n)
check('bridge only ever READ (no writes)', all(c[0] == 'GET' for c in r.bridge.calls) and r.bridge.calls)
fixed, livem = D.Rig().m, D.Rig(D.LIVE).m
check('fixed copy keeps the live layout + cycle', (fixed.BUTTONS, fixed.CYCLE) == (livem.BUTTONS, livem.CYCLE))
check('fixed copy keeps the live public functions',
      all(hasattr(fixed, f) for f in ('poll', 'watch', 'start', 'status', 'settings', 'find_device')))

print('%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
