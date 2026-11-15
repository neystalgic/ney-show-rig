# cook_audit.py -- READ-ONLY "who is cooking?" check for the TouchDesigner tidy-up (away/td-tidy, Nov 15).
#
# It only LOOKS: it reads each operator's cook counter and cook time, waits while you count to three, reads
# them again and prints which top-level pieces of /project1 cooked, grouped as INPUT / DECKS / MIXER / OUTPUT /
# SYSTEM. It changes nothing: no parameters, no positions, no wires, no storage, no saving.
#
# In TouchDesigner's Textport (Dialogs > Textport and DATs), paste these one at a time:
#   exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/away/td-tidy/cook_audit.py').read())
#   a = snap()
#        ... wait ~3 seconds, with the show playing the way you normally run it ...
#   report(a)
#
# What to look for: under DECKS, only the deck that is on screen (plus any overlay/layer you have up)
# should say COOKING. Every other deck that cooks is wasted frame time -- note its name for phase C.

import os, time
import importlib.util as _ilu

_HERE = '/Users/michaelney/Touchdesigner Designs/Hue Rig/away/td-tidy'
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                                   # exec() in the Textport has no __file__
    pass

_spec = _ilu.spec_from_file_location('tidy_map', os.path.join(_HERE, 'tidy_map.py'))
tidy_map = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(tidy_map)


def _num(o, attr):
    try:
        v = getattr(o, attr)
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


def _kids(o):
    try:
        return list(o.findChildren())
    except Exception:
        return []


def snap(root=None):
    """Read cook counters for every top-level operator under /project1 (and everything inside it)."""
    if root is None:
        root = op('/project1')                      # noqa: F821 -- 'op' exists inside TouchDesigner
    out = {'t': time.time(), 'ops': {}}
    for c in root.children:
        inside = [c] + _kids(c)
        out['ops'][c.name] = {'cooks': sum(_num(x, 'totalCooks') for x in inside),
                              'cpu_ms': sum(_num(x, 'cpuCookTime') for x in inside),
                              'gpu_ms': sum(_num(x, 'gpuCookTime') for x in inside)}
    return out


def compare(a, b):
    """Rows of (group, name, cooks during the gap, cpu ms, gpu ms, sleepable) -- pure, so it can be tested."""
    rows = []
    for name, after in b['ops'].items():
        before = a['ops'].get(name, {'cooks': after['cooks']})
        n = max(0, int(after['cooks'] - before['cooks']))
        rows.append((tidy_map.classify(name), name, n, after['cpu_ms'], after['gpu_ms'], tidy_map.sleepable(name)))
    order = {g: v['order'] for g, v in tidy_map.GROUPS.items()}
    rows.sort(key=lambda r: (order.get(r[0], 9), -r[2], r[1]))
    return rows


def report(a, root=None, printer=print):
    b = snap(root)
    gap = max(0.001, b['t'] - a['t'])
    rows = compare(a, b)
    printer('COOK AUDIT -- %.1f s window (read-only; nothing was changed)' % gap)
    group = None
    wasted = []
    for g, name, n, cpu, gpu, can_sleep in rows:
        if g != group:
            group = g
            printer('-- %s' % g)
        state = 'COOKING' if n else 'idle'
        printer('   %-20s %-7s %5d cooks   cpu %.2f ms  gpu %.2f ms' % (name, state, n, cpu, gpu))
        if g == 'DECKS' and n and can_sleep:
            wasted.append(name)
    unsorted = [r[1] for r in rows if r[0] == 'UNSORTED']
    if len(wasted) > 1:
        printer('DECKS cooking right now: %s -- only the one on screen should. Send this list to Claude.' % ', '.join(wasted))
    else:
        printer('DECKS: OK -- at most one sleepable deck is cooking.')
    if unsorted:
        printer('UNSORTED (tell Claude which box): %s' % ', '.join(unsorted))
    return {'rows': rows, 'decks_cooking': wasted, 'unsorted': unsorted}
