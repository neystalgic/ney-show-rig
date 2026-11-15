"""Installs Jarvis craving support (away loop J3, Nov 15). Run from the Hue Rig folder:

  python3 away/jarvis-craving/apply_patches.py

  * copies craving.py -> jarvis/craving.py
  * jarvis/quit.json   : created ONLY if missing, empty ({"start": "", "reasons": []}) -- you fill it in
  * jarvis/jarvis.py   : 'craving' action -- word rules only (the model can't pick it), checked right after
                         reminders and BEFORE the looks, so "I'm craving" isn't the 'calm' look and
                         "I'm craving pizza" is left alone; "I'm craving, help me" stays one thing; help line
  * selftest.py        : runs the craving tests
  * .gitignore         : jarvis/quit.json (your reasons stay off git and GitHub)
Every anchor is checked BEFORE anything is written: if one file changed, it stops and writes nothing.
Safe to run twice (the second time says 'already'). Backs each changed file up as <file>.bak-nov15-craving.
"""
import json, os, shutil, sys

MARK = 'Nov 15: craving support'
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'craving.py')


def _one(text, anchor, new, name):
    if text.count(anchor) != 1:
        raise SystemExit('STOP: %s changed (anchor not found exactly once: %r). Nothing written.' % (name, anchor[:70]))
    return text.replace(anchor, new)


def patch_jarvis(t):
    if MARK in t:
        return t, 'already patched'
    imp = "try:\n    import reminders as _reminders\nexcept Exception:\n    _reminders = None\n"
    t = _one(t, imp, imp + "try:\n    import craving as _craving                   # Nov 15: craving support\n"
                          "except Exception:\n    _craving = None\n", 'jarvis.py imports')
    r = "    if r:\n        return {'action': 'reminder', 'value': r}\n"
    t = _one(t, r, r + "    c = _craving.parse(t) if _craving else None      # craving / yes-to-the-calm-look / streak\n"
                       "    if c:\n        return {'action': 'craving', 'value': c}\n", 'jarvis.py by_rules')
    u = "    if _reminders and _reminders.parse(text):         # \"remind me to X and Y\" stays ONE reminder\n"
    t = _one(t, u, "    if _craving and _craving.parse(text):             # \"I'm craving, help me\" stays ONE thing\n"
                   "        i = understand(text, s, post)\n        i['heard'] = text\n        return [i]\n" + u,
             'jarvis.py understand_all')
    d = "        return _reminders.handle(v if isinstance(v, dict) else _reminders.parse(str(v or '')))\n"
    t = _one(t, d, d + "    if a == 'craving':                               # lights only if he says yes\n"
                       "        if not _craving:\n            return \"Craving support isn't installed on this Mac yet.\"\n"
                       "        return _craving.handle(v, s, rig)\n", 'jarvis.py do')
    h = "brief me, reminders and timers, and status.\")"
    t = _one(t, h, "brief me, reminders and timers, 'I'm craving', and status.\")", 'jarvis.py help line')
    return t, 'patched'


def patch_selftest(t):
    if MARK in t:
        return t, 'already patched'
    a = "     [('jarvis/reminders.py', 'away/jarvis-reminders/reminders.py')]),\n"
    return _one(t, a, a + "    ('Jarvis craving support', 'away/jarvis-craving/test_craving.py',   # Nov 15: craving support\n"
                          "     [('jarvis/craving.py', 'away/jarvis-craving/craving.py')]),\n", 'selftest.py SUITES'), 'patched'


def patch_gitignore(t):
    if 'jarvis/quit.json' in t:
        return t, 'already patched'
    a = 'jarvis/reminders.json.tmp\n'
    return _one(t, a, a + 'jarvis/quit.json\n', '.gitignore'), 'patched'


def main(root='.'):
    files = {'jarvis/jarvis.py': patch_jarvis, 'selftest.py': patch_selftest, '.gitignore': patch_gitignore}
    new = {}
    for name, fn in files.items():                       # 1. check every anchor first; nothing written yet
        with open(os.path.join(root, name)) as f:
            old = f.read()
        text, said = fn(old)
        new[name] = (old, text, said)
    if 'jarvis/jarvis.py' in new:                         # 2. the new jarvis.py must at least compile
        compile(new['jarvis/jarvis.py'][1], 'jarvis.py', 'exec')
    for name, (old, text, said) in new.items():           # 3. write (backup first)
        if text != old:
            p = os.path.join(root, name)
            shutil.copy2(p, p + '.bak-nov15-craving')
            with open(p, 'w') as f:
                f.write(text)
        print('%-18s %s' % (name, said))
    dst = os.path.join(root, 'jarvis', 'craving.py')
    shutil.copy2(SRC, dst)
    print('jarvis/craving.py  copied')
    q = os.path.join(root, 'jarvis', 'quit.json')
    if not os.path.exists(q):
        with open(q, 'w') as f:
            json.dump({'start': '', 'reasons': []}, f, indent=1)
        print('jarvis/quit.json   created (empty -- add your start date + reasons)')
    else:
        print('jarvis/quit.json   kept (already there)')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
