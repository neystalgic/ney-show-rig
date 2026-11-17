"""Installs the Jarvis show phrases (away loop W3, Nov 17). Michael runs this; the loop never does.
Run from the Hue Rig folder:

  python3 away/jarvis-show/apply_patches.py

  * copies show_words.py -> jarvis/show_words.py
  * jarvis/jarvis.py : 'show_set' action -- word rules only (the model can't pick it), checked right after
                       reminders and BEFORE the looks; do() hands it to show_words.handle(); help line
  * rig_control.py   : 3 lines in ask_jarvis's rig(): 'show_status' + 'show:{json}' -> show_words.rig_side()
                       (same allowlist as POST /show/set, narrowed to show_lock/wave/loop_dir/acts/audio)
  * selftest.py      : runs the show-phrase tests
Every anchor is checked BEFORE anything is written: if one file changed, it stops and writes nothing.
Works before or after the craving / workout installs (different anchors, or appends after the same line).
Safe to run twice (the second time says 'already'). Backs each changed file up as <file>.bak-nov17-show.
"""
import os, shutil, sys

MARK = 'Nov 17: show phrases'
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'show_words.py')
STAMP = '.bak-nov17-show'


def _one(text, anchor, new, name):
    if text.count(anchor) != 1:
        raise SystemExit('STOP: %s changed (anchor not found exactly once: %r). Nothing written.' % (name, anchor[:70]))
    return text.replace(anchor, new)


def patch_jarvis(t):
    if MARK in t:
        return t, 'already patched'
    imp = "try:\n    import reminders as _reminders\nexcept Exception:\n    _reminders = None\n"
    t = _one(t, imp, imp + "try:\n    import show_words as _show                   # Nov 17: show phrases\n"
                          "except Exception:\n    _show = None\n", 'jarvis.py imports')
    r = "    if r:\n        return {'action': 'reminder', 'value': r}\n"
    t = _one(t, r, r + "    sw = _show.parse(t) if _show else None           # lock wave / auto / what's playing\n"
                       "    if sw:\n        return {'action': 'show_set', 'value': sw}\n", 'jarvis.py by_rules')
    d = "    if a == 'save_meal':\n"
    t = _one(t, d, "    if a == 'show_set':                              # show director settings (never strobes)\n"
                   "        if not _show:\n            return \"Show phrases aren't installed on this Mac yet.\"\n"
                   "        return _show.handle(v, rig)\n" + d, 'jarvis.py do')
    h = "I'm producing, no dimming until midnight, "          # (craving + workout patch other parts of this line)
    t = _one(t, h, "I'm producing, show controls like lock gobos, auto or what's playing, no dimming until midnight, ",
             'jarvis.py help line')
    return t, 'patched'


def patch_rig_control(t):
    if MARK in t:
        return t, 'already patched'
    a = "        if p not in LOOKS:\n            raise KeyError(p)\n        JOBS.put(lambda: apply(p))\n"
    return _one(t, a, "        if p == 'show_status' or p.startswith('show:'):   # Nov 17: show phrases (away/jarvis-show)\n"
                      "            import show_words\n"
                      "            return show_words.rig_side(p, hub_up, hub_setting, HERE)\n" + a,
                'rig_control.py ask_jarvis rig()'), 'patched'


def patch_selftest(t):
    if MARK in t:
        return t, 'already patched'
    a = "     [('jarvis/reminders.py', 'away/jarvis-reminders/reminders.py')]),\n"
    return _one(t, a, a + "    ('Jarvis show phrases', 'away/jarvis-show/test_show_words.py',   # Nov 17: show phrases\n"
                          "     [('jarvis/show_words.py', 'away/jarvis-show/show_words.py')]),\n", 'selftest.py SUITES'), 'patched'


def main(root='.'):
    files = {'jarvis/jarvis.py': patch_jarvis, 'rig_control.py': patch_rig_control, 'selftest.py': patch_selftest}
    new = {}
    for name, fn in files.items():                       # 1. check every anchor first; nothing written yet
        with open(os.path.join(root, name)) as f:
            old = f.read()
        text, said = fn(old)
        new[name] = (old, text, said)
    for name in ('jarvis/jarvis.py', 'rig_control.py'):   # 2. the new files must at least compile
        compile(new[name][1], name, 'exec')
    for name, (old, text, said) in new.items():           # 3. write (backup first)
        if text != old:
            p = os.path.join(root, name)
            shutil.copy2(p, p + STAMP)
            with open(p, 'w') as f:
                f.write(text)
        print('%-18s %s' % (name, said))
    dst = os.path.join(root, 'jarvis', 'show_words.py')
    if os.path.exists(dst) and not os.path.exists(dst + STAMP):
        shutil.copy2(dst, dst + STAMP)
    shutil.copy2(SRC, dst)
    print('jarvis/show_words.py copied')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else '.'))
