#!/usr/bin/env python3
# =============================================================================
# TAP SWITCH DRY RUN (away loop, Nov 14) -- press the Tap Switch Mini's buttons WITHOUT a Tap Switch,
# a bridge or any lights. A fake bridge stands in for hue_stream, a fake clock stands in for time,
# and every look the switch asks for is just written down instead of run.
#
#   python3 tap_dryrun.py                -> tries the LIVE ../../tap_switch.py and this folder's fixed copy
#   python3 tap_dryrun.py some/tap_switch.py
#
# Safe any time: no network, no lights, no files changed (the switch's log goes to a temp folder).
# =============================================================================
import importlib.util, itertools, os, sys, tempfile, time as _real_time, types

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.normpath(os.path.join(HERE, '..', '..', 'tap_switch.py'))
FIXED = os.path.join(HERE, 'tap_switch.py')
TAP_ID = 'fake-tap-switch-0001'
_names = itertools.count()


class FakeClock:
    """Stands in for the time module inside tap_switch: time() only moves when we say so."""
    def __init__(self, start=1_700_000_000.0):
        self.t = start
    def time(self):
        return self.t
    def sleep(self, s):
        self.t += s
    def strftime(self, fmt, *a):
        return _real_time.strftime(fmt, _real_time.localtime(self.t))


class FakeBridge:
    """Answers the two GETs tap_switch makes (device, button). Anything else is a bug: it must only read."""
    def __init__(self, name='Tap Switch Mini', product='Hue tap switch mini', present=True, extra_devices=()):
        self.devices = [{'id': 'lamp-1', 'metadata': {'name': 'Desk lamp'}, 'product_data': {'product_name': 'Hue go'}}]
        self.devices += list(extra_devices)
        if present:
            self.devices.append({'id': TAP_ID, 'metadata': {'name': name}, 'product_data': {'product_name': product}})
        self.buttons = {n: {'id': 'btn-%d' % n, 'owner': {'rid': TAP_ID, 'rtype': 'device'},
                            'metadata': {'control_id': n}, 'button': {}} for n in (1, 2, 3, 4)}
        self.stamp = 0
        self.calls = []

    def report(self, n, event):
        """The bridge's newest event for button n (each one gets a new 'updated' stamp, like the real bridge)."""
        self.stamp += 1
        self.buttons[n]['button'] = {'button_report': {'event': event,
                                                       'updated': '2026-11-14T03:00:%06.3fZ' % (self.stamp / 1000)}}

    # --- the hue_stream functions tap_switch uses
    def load_config(self):
        return {'bridge_ip': 'fake', 'note': 'dry run'}

    def v2(self, cfg, path, method='GET', body=None):
        self.calls.append((method, path))
        if method != 'GET' or body is not None:
            raise AssertionError('the Tap Switch watcher must only READ the bridge (got %s %s)' % (method, path))
        if path == 'device':
            return {'data': list(self.devices)}
        if path == 'button':
            return {'data': list(self.buttons.values())}
        raise AssertionError('unexpected bridge path: ' + path)


class Rig:
    """Loads one copy of tap_switch.py with the fakes plugged in. presses[] = looks it asked for."""
    def __init__(self, path=FIXED, settings=None, bridge=None, poll_s=0.33):
        self.bridge = bridge or FakeBridge()
        self.clock = FakeClock()
        self.poll_s = poll_s
        self.presses = []
        tmp = tempfile.mkdtemp(prefix='tapdry-')
        spec = importlib.util.spec_from_file_location('tap_switch_dry%d' % next(_names), path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.time = self.clock                                   # fake clock
        m.LOG = os.path.join(tmp, 'tap_switch.log')           # never the real /tmp log
        m.SETTINGS = os.path.join(tmp, 'tap_switch.json')     # no settings file unless the test writes one
        if settings is not None:
            import json
            with open(m.SETTINGS, 'w') as f:
                json.dump(settings, f)
        fake = types.ModuleType('hue_stream')
        fake.load_config, fake.v2 = self.bridge.load_config, self.bridge.v2
        m._hs = lambda: fake                                  # tap_switch's own loader would import the real one
        self.m = m
        self.poll()                                           # first look: finds the switch, remembers old reports

    def poll(self):
        self.m.poll(self.presses.append)

    def wait(self, s):
        self.clock.sleep(s)

    # --- what a finger does (the watcher polls every ~0.33 s, like rig_control)
    def tap(self, n):
        self.bridge.report(n, 'initial_press'); self.poll(); self.wait(self.poll_s)
        self.bridge.report(n, 'short_release'); self.poll(); self.wait(self.poll_s)

    def quick_tap(self, n):
        """Press and release between two polls: the watcher only ever sees short_release."""
        self.bridge.report(n, 'initial_press'); self.bridge.report(n, 'short_release')
        self.poll(); self.wait(self.poll_s)

    def hold(self, n, repeats=3):
        self.bridge.report(n, 'initial_press'); self.poll(); self.wait(0.8)
        self.bridge.report(n, 'long_press'); self.poll()
        for _ in range(repeats):
            self.wait(0.8); self.bridge.report(n, 'repeat'); self.poll()
        self.wait(0.3); self.bridge.report(n, 'long_release'); self.poll(); self.wait(self.poll_s)

    def take(self):
        out, self.presses[:] = list(self.presses), []
        return out


def report(path):
    print('\n== %s' % path)
    r = Rig(path)
    print('  switch found: %s' % (r.m.STATE['device'] == TAP_ID))
    for n in (1, 2, 4):
        r.tap(n); print('  button %d tap   -> %s' % (n, r.take()))
        r.hold(n); print('  button %d hold  -> %s' % (n, r.take()))
    for _ in range(6):
        r.tap(3)
    print('  button 3 x6 taps -> %s' % r.take())
    r.hold(3); print('  button 3 hold  -> %s   (one hold should be ONE step)' % r.take())
    writes = [c for c in r.bridge.calls if c[0] != 'GET']
    print('  bridge writes: %d (must be 0)' % len(writes))


if __name__ == '__main__':
    for p in (sys.argv[1:] or [LIVE, FIXED]):
        report(p)
