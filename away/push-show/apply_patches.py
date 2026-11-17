# =============================================================================
# W6 PUSH SHOW -- guarded install (away loop, Nov 17)
#
# Adds hub_showsync.py and patches hub_push2.py (SHOW pad mode on the MIX button) and hub_visuals.py
# (the visuals follow the show director). Every anchor is checked in BOTH files first: if any has moved
# it prints STOP and touches nothing. Backups: <file>.bak-2026-11-17-pushshow. Running it twice is safe.
#
#   python3 away/push-show/apply_patches.py            (patches the repo)
#   python3 away/push-show/apply_patches.py --target DIR   (patches copies in DIR -- the tests use this)
# =============================================================================
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TAG = '.bak-2026-11-17-pushshow'
MARK = 'hub_showsync'

PUSH2 = [
    ("import hub_pads\n",
     "import hub_pads\nimport hub_showsync                            # SHOW pad mode (W6, Nov 17)\n"),
    ("#   SCALE button    GEOMETRY mode",
     "#   MIX button      SHOW mode    the show director (hub_showsync.py): top row = acts + AUTO + acts on/off,\n"
     "#                                then the 7 zone modes, wave / loop direction, audio mix 0-100%\n"
     "#   SCALE button    GEOMETRY mode"),
    ("PLAY = 85\n",
     "PLAY = 85\nSHOW = 112                                       # MIX button = SHOW mode (W6: the show director on the pads)\n"
     "P_SHOW = {'on': 90, 'mid': 91, 'dim': 92}         # SHOW mode palette slots (playing / locked / rest)\n"),
    ("        if self.mode == 'paint':\n            n = len(self.sel)",
     "        if self.mode == 'show':\n"
     "            self.status = 'connected -- ' + hub_showsync.display_text(hub_showsync.status(self.hub))\n"
     "            return\n"
     "        if self.mode == 'paint':\n            n = len(self.sel)"),
    ("every = 0.05 if self.mode == 'paint' else 1.0",
     "every = 0.05 if self.mode == 'paint' else (0.25 if self.mode == 'show' else 1.0)"),
    ("        if time.time() - self.last_refresh > every:\n            self.refresh()\n",
     "        if time.time() - self.last_refresh > every:\n            self.refresh()\n"
     "            if self.mode == 'show':\n"
     "                self.set_status()                            # act / mode / bar x of 8\n"),
    ("        if msg.type == 'note_on' and msg.velocity > 0 and 36 <= msg.note <= 99:\n            row, col",
     "        if self.mode == 'show':                                         # SHOW pads -> the director's settings\n"
     "            if msg.type == 'note_on' and msg.velocity > 0 and 36 <= msg.note <= 99:\n"
     "                act = hub_showsync.pad_action(msg.note, hub_showsync.status(h), h.state['settings'])\n"
     "                if act:\n"
     "                    h.command({'op': 'setting', 'key': act[0], 'value': act[1]})\n"
     "                self.set_status()\n"
     "                self.refresh(force=True)\n"
     "                return\n"
     "            if msg.type in ('note_on', 'note_off', 'polytouch', 'aftertouch'):\n"
     "                return\n"
     "        if msg.type == 'note_on' and msg.velocity > 0 and 36 <= msg.note <= 99:\n            row, col"),
    ("        elif cc == LAYOUT:\n            self.mode = 'paint'\n            h.pads.panic()\n",
     "        elif cc == LAYOUT:\n            self.mode = 'paint'\n            h.pads.panic()\n"
     "        elif cc == SHOW:\n            self.mode = 'show'\n            h.pads.panic()\n"),
    ("            elif self.mode == 'paint':\n                live = h.out_at",
     "            elif self.mode == 'show':\n"
     "                for lvl, slot in P_SHOW.items():\n"
     "                    changed = self.set_palette(slot, hub_showsync.COLOURS[lvl]) or changed\n"
     "                st, sets = hub_showsync.status(h), h.state['settings']\n"
     "                show_idx = {n: P_SHOW.get(hub_showsync.pad_level(n, st, sets), 0) for n in range(36, 100)}\n"
     "            elif self.mode == 'paint':\n                live = h.out_at"),
    ("                    if self.mode in ('play', 'geo'):\n"
     "                        self.pad(note, WHITE if note in self.play_held else 1 + note - 36, force)\n"
     "                        continue\n",
     "                    if self.mode in ('play', 'geo'):\n"
     "                        self.pad(note, WHITE if note in self.play_held else 1 + note - 36, force)\n"
     "                        continue\n"
     "                    if self.mode == 'show':\n"
     "                        self.pad(note, show_idx.get(note, 0), force)\n"
     "                        continue\n"),
    ("SCALE: self.mode == 'geo', LAYOUT: self.mode == 'paint',",
     "SCALE: self.mode == 'geo', LAYOUT: self.mode == 'paint', SHOW: self.mode == 'show',"),
]

VISUALS = [
    ("import hue_stream as hs\n",
     "import hue_stream as hs\nimport hub_showsync                 # W6: the visuals follow the show director\n"),
    ("#   section           pumps, glows, sparkles and bursts with it\n",
     "#   section           pumps, glows, sparkles and bursts with it\n"
     "#   act, mode, hue,   the SHOW DIRECTOR (hub_showsync.py, W6): what's playing, its colour 0-1,\n"
     "#   level, kick       the zones' mean level and its kick -- and it picks the visual per act / mode\n"),
    ("        self.turn_steps = 0.0\n",
     "        self.turn_steps = 0.0\n        self.showsync = hub_showsync.Sync()\n"),
    ("        want = self.wanted_form(look)\n",
     "        want = self.wanted_form(look)\n"
     "        dform = hub_showsync.director_form(h, touch is not None and time.time() - touch[0] <= PAD_HOLD)\n"
     "        if dform:                                       # the show director picks the visual (a touched pad still wins)\n"
     "            want = dform\n"),
    ("moviesrc=h.state['settings'].get('movie_src', 'capture'))",
     "moviesrc=h.state['settings'].get('movie_src', 'capture'),\n"
     "                    **self.showsync.fields(h, now))"),
]


def main(argv):
    target = REPO
    if '--target' in argv:
        target = argv[argv.index('--target') + 1]
    plan = []
    for name, patches in (('hub_push2.py', PUSH2), ('hub_visuals.py', VISUALS)):
        path = os.path.join(target, name)
        with open(path) as f:
            src = f.read()
        if 'import ' + MARK in src:
            print('already patched: %s' % name)
            continue
        for old, _ in patches:
            if src.count(old) != 1:
                print('STOP -- nothing changed: an anchor moved in %s (found %d times):\n  %r'
                      % (name, src.count(old), old[:80]))
                return 1
        new = src
        for old, rep in patches:
            new = new.replace(old, rep, 1)
        compile(new, name, 'exec')
        plan.append((path, new))
    shutil.copy2(os.path.join(HERE, 'hub_showsync.py'), os.path.join(target, 'hub_showsync.py'))
    for path, new in plan:
        bak = path + TAG
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'w') as f:
            f.write(new)
        print('patched: %s (backup %s)' % (os.path.basename(path), os.path.basename(bak)))
    print('done -- hub_showsync.py in place')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
