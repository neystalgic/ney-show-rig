"""Installs Jarvis reminders + timers (away loop J2, Nov 15). Run from the Hue Rig folder:

  python3 away/jarvis-reminders/apply_patches.py

  * copies reminders.py -> jarvis/reminders.py
  * jarvis/jarvis.py   : 'reminder' action -- word rules only, checked FIRST so "remind me to log my weight" is a
                         reminder, not a weight; "remind me to X and Y" stays one reminder; help line mentions it
  * rig_control.py     : one 'jarvis-reminders' thread that says due reminders on the Mac (Moira), every 15 s
  * selftest.py        : runs the reminders tests + a read-only check that nothing is stuck unsaid
  * .gitignore         : jarvis/reminders.json (+ .tmp)
Every anchor is checked BEFORE anything is written: if one file changed, it stops and writes nothing.
Safe to run twice (the second time says 'already'). Backs each changed file up as <file>.bak-nov15-reminders.
"""
import filecmp, os, re, shutil, sys

MARK = 'Nov 15: reminders + timers'
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reminders.py')


def _one(text, anchor, new, name):
    if text.count(anchor) != 1:
        raise SystemExit('STOP: %s changed (anchor not found exactly once: %r). Nothing written.' % (name, anchor[:70]))
    return text.replace(anchor, new)


def patch_jarvis(t):
    if MARK in t:
        return t, 'already patched'
    imp = 'import argparse, datetime as dt, json, os, re, subprocess, sys, urllib.error, urllib.request\n'
    t = _one(t, imp, imp + """_JD = os.path.dirname(os.path.abspath(__file__))   # Nov 15: reminders + timers live next to this file
if _JD not in sys.path:
    sys.path.insert(0, _JD)
try:
    import reminders as _reminders
except Exception:
    _reminders = None
""", 'jarvis.py imports')
    w = "    'weight':      None,                      # logs a weight, needs a number\n"
    t = _one(t, w, w + "    'reminder':    None,                      # reminders + timers (jarvis/reminders.py)\n", 'jarvis.py ACTIONS')
    n = """    if not re.sub(r'[^a-z0-9]', '', t):
        return {'action': 'nothing', 'value': None}
"""
    t = _one(t, n, n + """    r = _reminders.parse(t) if _reminders else None   # reminders/timers first: "remind me to log my weight"
    if r:
        return {'action': 'reminder', 'value': r}
""", 'jarvis.py by_rules')
    sp = "    pieces = [p for p in re.split(r'\\s*(?:,|\\band then\\b|\\bthen\\b|\\band\\b|\\balso\\b)\\s*', text) if p.strip()]\n"
    t = _one(t, sp, """    if _reminders and _reminders.parse(text):         # "remind me to X and Y" stays ONE reminder
        i = understand(text, s, post)
        i['heard'] = text
        return [i]
""" + sp, 'jarvis.py understand_all')
    rg = '    rig = rig or (lambda p: _rig(p, s))\n'
    t = _one(t, rg, rg + """    if a == 'reminder':                              # never touches the lights
        if not _reminders:
            return "Reminders aren't installed on this Mac yet."
        return _reminders.handle(v if isinstance(v, dict) else _reminders.parse(str(v or '')))
""", 'jarvis.py do')
    t2 = re.sub(r'(my usual meals|saved meals),? and status\.', r'\1, reminders and timers, and status.', t, count=1)
    if t2 == t:
        t2 = re.sub(r' and status\.(["\']\))', r' reminders and timers, and status.\1', t, count=1)
    return t2, 'patched'


def patch_rig(t):
    if MARK in t:
        return t, 'already patched'
    a = "    threading.Thread(target=_jarvis_warm, name='jarvis-warm', daemon=True).start()\n"
    return _one(t, a, a + """
    def _reminders():                               # Nov 15: reminders + timers -- the Mac says them (jarvis/reminders.py)
        jd = os.path.join(HERE, 'jarvis')
        if jd not in sys.path:
            sys.path.insert(0, jd)
        time.sleep(20)
        try:
            import reminders
            reminders.loop()                        # every 15 s; never raises; missed ones said once on wake
        except Exception as e:
            print('reminders thread stopped:', e, flush=True)
    threading.Thread(target=_reminders, name='jarvis-reminders', daemon=True).start()
""", 'rig_control.py (jarvis-warm thread line)'), 'patched'


def patch_selftest(t):
    if MARK in t:
        return t, 'already patched'
    m = re.search(r'\nSUITES = \[.*?\n\]\n', t, re.S)
    if not m:
        raise SystemExit('STOP: selftest.py SUITES list not found. Nothing written.')
    end = m.end() - 2
    t = t[:end] + """    ('Jarvis reminders + timers', 'away/jarvis-reminders/test_reminders.py',   # Nov 15: reminders + timers
     [('jarvis/reminders.py', 'away/jarvis-reminders/reminders.py')]),
""" + t[end:]
    t = _one(t, '\ndef main', '''
def reminders_check():                              # Nov 15: reminders + timers -- read-only
    path = os.path.join(HERE, 'jarvis', 'reminders.json')
    if not os.path.exists(path):
        return res('Automations', 'Jarvis reminders', 'ok', 'none set')
    try:
        with open(path) as f:
            items = json.load(f).get('items', [])
        late = [i for i in items if time.time() - time.mktime(time.strptime(i['due'][:19], '%Y-%m-%dT%H:%M:%S')) > 600]
    except Exception as e:
        return res('Automations', 'Jarvis reminders', 'fail', 'reminders.json unreadable (%s)' % e.__class__.__name__)
    if late:
        return res('Automations', 'Jarvis reminders', 'warn',
                   '%d overdue by 10+ min -- is the jarvis-reminders thread in rig_control running?' % len(late))
    return res('Automations', 'Jarvis reminders', 'ok', '%d set, none overdue' % len(items))


def main''', 'selftest.py def main')
    return _one(t, '    automations()\n', '    automations()\n    reminders_check()\n', 'selftest.py main()'), 'patched'


def patch_gitignore(t):
    add = [l for l in ('jarvis/reminders.json', 'jarvis/reminders.json.tmp') if l not in t.split('\n')]
    if not add:
        return t, 'already patched'
    return t.rstrip('\n') + '\n' + '\n'.join(add) + '\n', 'patched'


PLAN = [('jarvis/jarvis.py', patch_jarvis), ('rig_control.py', patch_rig), ('selftest.py', patch_selftest),
        ('.gitignore', patch_gitignore)]


def main(root='.'):
    out = []
    for rel, fn in PLAN:                             # 1. check everything first
        with open(os.path.join(root, rel)) as f:
            new, what = fn(f.read())
        if rel.endswith('.py'):
            compile(new, rel, 'exec')                # refuse to write something that doesn't parse
        out.append((rel, new, what))
    dst = os.path.join(root, 'jarvis', 'reminders.py')    # 2. then write
    if not (os.path.exists(dst) and filecmp.cmp(SRC, dst, shallow=False)):
        if os.path.exists(dst):
            shutil.copy2(dst, dst + '.bak-nov15-reminders')
        shutil.copy2(SRC, dst)
        print('jarvis/reminders.py: installed')
    else:
        print('jarvis/reminders.py: already installed')
    for rel, new, what in out:
        if what == 'patched':
            p = os.path.join(root, rel)
            shutil.copy2(p, p + '.bak-nov15-reminders')
            with open(p, 'w') as f:
                f.write(new)
        print('%s: %s' % (rel, what))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
