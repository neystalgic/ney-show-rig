"""Installs CONTENT MODE (away loop W5, Nov 17). Michael runs this; the loop never does.
Run from the Hue Rig folder:

  python3 away/content-mode/apply_patches.py --check     # dry run: checks every anchor, writes nothing
  python3 away/content-mode/apply_patches.py             # installs

  * copies content_mode.py -> content_mode.py (rig folder), content_words.py -> jarvis/content_words.py,
    content_mode.json -> content_mode.json (only if there isn't one yet: your edits are kept)
  * jarvis/jarvis.py : imports content_words; word rule checked right after reminders, BEFORE the looks
                       (so 'content mode' never falls through to 'flash'); do() hands it to content_words.handle()
  * rig_control.py   : ask_jarvis rig(): 'content:{json}' -> content_mode.rig_side();
                       apply(): any other look ends content mode first; start-up: content_mode.boot()
  * hub_dmx.py       : the two "never white" floors and the strobe hit honour the new hub setting content_white
                       (False unless content mode is on, so nothing changes otherwise)
  * hue_hub.py       : content_white=bool added to the allowed settings
Every anchor is checked BEFORE anything is written: if one file changed, it stops and writes nothing.
Works before or after the jarvis-show install (same anchors, both insert next to them). Safe to run twice.
Backs each changed file up as <file>.bak-nov17-content.
"""
import os, shutil, sys

MARK = 'Nov 17: content mode'
HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = '.bak-nov17-content'


def _one(text, anchor, new, name):
    if text.count(anchor) != 1:
        raise SystemExit('STOP: %s changed (anchor not found exactly once: %r). Nothing written.' % (name, anchor[:70]))
    return text.replace(anchor, new)


def patch_jarvis(t):
    if MARK in t:
        return t, 'already patched'
    imp = "try:\n    import reminders as _reminders\nexcept Exception:\n    _reminders = None\n"
    t = _one(t, imp, imp + "try:\n    import content_words as _content            # Nov 17: content mode\n"
                          "except Exception:\n    _content = None\n", 'jarvis.py imports')
    r = "    if r:\n        return {'action': 'reminder', 'value': r}\n"
    t = _one(t, r, r + "    cw = _content.parse(t) if _content else None     # content mode (word rules only)\n"
                       "    if cw:\n        return {'action': 'content', 'value': cw}\n", 'jarvis.py by_rules')
    d = "    if a == 'save_meal':\n"
    t = _one(t, d, "    if a == 'content':                               # content mode: the rig decides + answers\n"
                   "        if not _content:\n            return \"Content mode isn't installed on this Mac yet.\"\n"
                   "        return _content.handle(v, rig)\n" + d, 'jarvis.py do')
    return t, 'patched'


def patch_rig_control(t):
    if MARK in t:
        return t, 'already patched'
    a = "        if p not in LOOKS:\n            raise KeyError(p)\n        JOBS.put(lambda: apply(p))\n"
    t = _one(t, a, "        if p.startswith('content:'):              # Nov 17: content mode (away/content-mode)\n"
                   "            import content_mode\n"
                   "            return content_mode.rig_side(p, sys.modules[__name__])\n" + a,
             'rig_control.py ask_jarvis rig()')
    ap = "def apply(look):\n"
    t = _one(t, ap, ap + "    try:                                            # content mode: any other look ends it first\n"
                         "        import content_mode\n"
                         "        content_mode.look_changed(sys.modules[__name__], look)\n"
                         "    except Exception as e:\n"
                         "        STATE['last_error'] = 'content mode end: %s' % e\n", 'rig_control.py apply()')
    w = "    hub_watchdog.start(lambda: STATE['busy'], _wd_stop, _wd_start, _wd_restore)\n"
    t = _one(t, w, w + "    try:                                            # content mode never survives a restart\n"
                       "        import content_mode\n"
                       "        content_mode.boot(sys.modules[__name__])\n"
                       "    except Exception:\n"
                       "        pass\n", 'rig_control.py start-up')
    return t, 'patched'


def patch_hub_dmx(t):
    if MARK in t:
        return t, 'already patched'
    a = "            ss = max(ss, 0.55)                                  # never white\n"
    t = _one(t, a, "            ss = ss if s.get('content_white') else max(ss, 0.55)   # never white (Nov 17: content mode allows it)\n",
             'hub_dmx.py colour floor')
    b = "                        ss = max(ss, 0.55)          # never white\n"
    t = _one(t, b, "                        ss = ss if s.get('content_white') else max(ss, 0.55)   # never white (content mode allows it)\n",
             'hub_dmx.py show-mode floor')
    c = "                r, g, b = self.match(colorsys.hsv_to_rgb(hh, max(ss, 0.7), 1.0), s)\n                w = 0.0\n"
    t = _one(t, c, c + "                if s.get('content_white'):                   # content mode: the hit is pure white\n"
                       "                    r, g, b, w = 0.0, 0.0, 0.0, 1.0\n", 'hub_dmx.py strobe hit')
    return t, 'patched'


def patch_hue_hub(t):
    if 'content_white=bool' in t:
        return t, 'already patched'
    a = "strobe_max_hz=float, strobe_test=bool,"
    return _one(t, a, a + " content_white=bool,", 'hue_hub.py settings list'), 'patched'


FILES = [('jarvis/jarvis.py', patch_jarvis), ('rig_control.py', patch_rig_control),
         ('hub_dmx.py', patch_hub_dmx), ('hue_hub.py', patch_hue_hub)]


def main(argv):
    check = '--check' in argv
    rig = argv[argv.index('--rig') + 1] if '--rig' in argv else os.path.dirname(os.path.dirname(HERE))
    new = {}
    for rel, fn in FILES:                         # 1) every anchor checked first; nothing written yet
        path = os.path.join(rig, rel)
        with open(path) as f:
            old = f.read()
        text, how = fn(old)
        compile(text, path, 'exec')               # the patched file must still be valid Python
        new[rel] = (path, old, text, how)
        print('%-18s %s' % (rel, how))
    if check:
        print('CHECK ONLY: all anchors found, nothing written.')
        return 0
    for rel, (path, old, text, how) in new.items():   # 2) write, each with a backup
        if text != old:
            shutil.copy2(path, path + STAMP)
            with open(path, 'w') as f:
                f.write(text)
    shutil.copy2(os.path.join(HERE, 'content_mode.py'), os.path.join(rig, 'content_mode.py'))
    shutil.copy2(os.path.join(HERE, 'content_words.py'), os.path.join(rig, 'jarvis', 'content_words.py'))
    cfg = os.path.join(rig, 'content_mode.json')
    if not os.path.exists(cfg):
        shutil.copy2(os.path.join(HERE, 'content_mode.json'), cfg)
    print('INSTALLED. Backups: *%s. Now reload rig_control and restart the hub (see DEPLOY.txt).' % STAMP)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
