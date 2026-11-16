#!/usr/bin/env python3
"""Offline test (Nov 15): a hub that has just started gets the grace period before 'frozen' can restart it;
a hub that froze AFTER the grace still gets restarted."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_watchdog as w

fails = []
clock = [1000.0]
w.time.time = lambda: clock[0]
restarts = []
w.restart = lambda why, *a, **k: restarts.append(why)
running = [False]
w.hub_running = lambda: running[0]


def dead(*a, **k):
    raise OSError('not answering')


w.hub_live = dead
w.settings = lambda: dict(w.DEFAULTS)
w.log = lambda msg: None
w.STATE.update(grace_until=0.0, restarts=[], dead_since=None, was_running=False, busy_since=None, restarting=False)
tick = lambda: w._tick(lambda: False, None, None, None)

tick()                                  # hub not running yet
running[0] = True                       # someone (rig_control) starts it; it takes 70 s to connect
for _ in range(14):
    clock[0] += 5
    tick()
if restarts:
    fails.append('restarted during start-up grace: %s' % restarts)
clock[0] += 200                         # long after the grace, still not answering -> a real freeze
for _ in range(12):
    clock[0] += 5
    tick()
if not restarts or 'frozen' not in restarts[0]:
    fails.append('a real freeze after the grace was not restarted: %s' % restarts)
print('hub_watchdog tests: %s' % ('ALL PASSED' if not fails else 'FAILED ' + '; '.join(fails)))
sys.exit(1 if fails else 0)
