"""Installs Jarvis workout mode (away loop J4, Nov 15). Run from the Hue Rig folder:

  python3 away/jarvis-workout/apply_patches.py

  * copies workout.py -> jarvis/workout.py
  * jarvis/jarvis.py   : 'workout' action -- word rules only (the model can't pick it), checked right after
                         reminders and BEFORE the looks; "done with my run, felt like a 7" stays one thing;
                         "starting a run and hype" still becomes two (workout + the look YOU asked for); help line
  * selftest.py        : runs the workout tests + a read-only "Workout log" line (forgotten open workout = warn)
Works before or after the craving installer (different anchors). Workout Log.csv lives on the Desktop, so
nothing new for .gitignore. Every anchor is checked BEFORE anything is written: if one file changed, it stops
and writes nothing. Safe to run twice. Backs each changed file up as <file>.bak-nov15-workout.
"""
import os, shutil, sys

MARK = 'Nov 15: workout mode'
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'workout.py')


def _one(text, anchor, new, name):
    if text.count(anchor) != 1:
        raise SystemExit('STOP: %s changed (anchor not found exactly once: %r). Nothing written.' % (name, anchor[:70]))
    return text.replace(anchor, new)


def patch_jarvis(t):
    if MARK in t:
        return t, 'already patched'
    imp = "try:\n    import reminders as _reminders\nexcept Exception:\n    _reminders = None\n"
    t = _one(t, imp, imp + "try:\n    import workout as _workout                   # Nov 15: workout mode\n"
                          "except Exception:\n    _workout = None\n", 'jarvis.py imports')
    r = "    if r:\n        return {'action': 'reminder', 'value': r}\n"
    t = _one(t, r, r + "    w = _workout.parse(t) if _workout else None      # starting a walk / done / how it felt\n"
                       "    if w:\n        return {'action': 'workout', 'value': w}\n", 'jarvis.py by_rules')
    u = "    if _reminders and _reminders.parse(text):         # \"remind me to X and Y\" stays ONE reminder\n"
    t = _one(t, u, "    w = _workout.parse(text) if _workout else None   # \"done with my run and it was a 7\" stays ONE thing\n"
                   "    if w and w.get('feel') is not None:\n"
                   "        return [{'action': 'workout', 'value': w, 'heard': text}]\n" + u, 'jarvis.py understand_all')
    d = "        return _reminders.handle(v if isinstance(v, dict) else _reminders.parse(str(v or '')))\n"
    t = _one(t, d, d + "    if a == 'workout':                               # never touches the lights\n"
                       "        if not _workout:\n            return \"Workout mode isn't installed on this Mac yet.\"\n"
                       "        return _workout.handle(v, s)\n", 'jarvis.py do')
    h = "log your weight or food, my usual meals, "
    t = _one(t, h, "log your weight or food, workouts like 'starting a walk', my usual meals, ", 'jarvis.py help line')
    return t, 'patched'


CHECK = '''def workout_check():                                # Nov 15: workout mode -- read-only
    path = os.path.expanduser('~/Desktop/Workout Log.csv')
    if not os.path.exists(path):
        return res('Automations', 'Workout log', 'ok', 'no workouts logged yet')
    try:
        import csv
        with open(path, newline='') as f:
            rows = list(csv.DictReader(f))
        stuck = [r for r in rows if r.get('Start') and not r.get('End') and not (r.get('Notes') or '').strip()
                 and time.time() - time.mktime(time.strptime(r['Date'] + ' ' + r['Start'], '%Y-%m-%d %H:%M')) > 6 * 3600]
        week = [r for r in rows if r.get('Minutes') and r.get('Date', '') >= time.strftime('%Y-%m-%d', time.localtime(time.time() - 7 * 86400))]
    except Exception as e:
        return res('Automations', 'Workout log', 'fail', 'Workout Log.csv unreadable (%s)' % e.__class__.__name__)
    if stuck:
        return res('Automations', 'Workout log', 'warn', "%d workout(s) never closed -- say 'done with my walk' next time" % len(stuck))
    return res('Automations', 'Workout log', 'ok', '%d this week' % len(week))


'''


def patch_selftest(t):
    if MARK in t:
        return t, 'already patched'
    a = "     [('jarvis/reminders.py', 'away/jarvis-reminders/reminders.py')]),\n"
    t = _one(t, a, a + "    ('Jarvis workout mode', 'away/jarvis-workout/test_workout.py',   # Nov 15: workout mode\n"
                       "     [('jarvis/workout.py', 'away/jarvis-workout/workout.py')]),\n", 'selftest.py SUITES')
    t = _one(t, "\ndef main():\n", "\n" + CHECK + "def main():\n", 'selftest.py main')
    t = _one(t, "    reminders_check()\n", "    reminders_check()\n    workout_check()\n", 'selftest.py main call')
    return t, 'patched'


def main(root='.'):
    files = {'jarvis/jarvis.py': patch_jarvis, 'selftest.py': patch_selftest}
    new = {}
    for name, fn in files.items():                       # 1. check every anchor first; nothing written yet
        with open(os.path.join(root, name)) as f:
            old = f.read()
        text, said = fn(old)
        compile(text, name, 'exec')                       # 2. the new files must at least compile
        new[name] = (old, text, said)
    for name, (old, text, said) in new.items():           # 3. write (backup first)
        if text != old:
            p = os.path.join(root, name)
            shutil.copy2(p, p + '.bak-nov15-workout')
            with open(p, 'w') as f:
                f.write(text)
        print('%-18s %s' % (name, said))
    shutil.copy2(SRC, os.path.join(root, 'jarvis', 'workout.py'))
    print('jarvis/workout.py  copied')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
