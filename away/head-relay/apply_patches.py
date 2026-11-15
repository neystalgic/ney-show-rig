# HEAD RELAY installer (Nov 15, away loop) -- anchored, all-or-nothing, safe to run twice.
#   python3 away/head-relay/apply_patches.py            patch the live files in the Hue Rig folder
#   python3 away/head-relay/apply_patches.py --root DIR patch copies in DIR (the test does this)
#   python3 away/head-relay/apply_patches.py --check    only say whether every anchor is found
# It adds hub_chase.py next to hub_dmx.py and small hooks to hub_dmx.py, hue_hub.py, rig_control.py,
# jarvis/jarvis.py and selftest.py. If any anchor is missing (a file changed since Nov 15) it writes NOTHING.
# Each patched file is backed up first as <file>.bak-nov15-relay.
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

DMX = [
    ("before", "        self.run = True\n        threading.Thread(target=self._poll, name='hub-dmx', daemon=True).start()\n",
     "        try:                                       # HEAD RELAY (hub_chase.py, Nov 15): one head at a time\n"
     "            import hub_chase\n"
     "            self.chase = hub_chase.Chase(hub)\n"
     "        except Exception:\n"
     "            self.chase = None\n"),
    ("after", "        data = bytearray(512)\n        hs = self.heads()\n        n = len(hs)\n",
     "        ch = getattr(self, 'chase', None)           # HEAD RELAY: one head lit at a time (dmx_pattern 'show' / 'relay')\n"
     "        cz = None\n"
     "        if ch is not None and not dark and not movie:\n"
     "            try:\n"
     "                cz = ch.step(now, beats, pmode, hs)\n"
     "            except Exception:\n"
     "                cz = None\n"
     "        if cz:                                      # the relay owns the heads: no strobe, turns, sweeps or scene rotation\n"
     "            fire, turn_deg, turning, sweep_e, cue, cue_f = False, 0.0, False, 0.0, None, 0.0\n"
     "            self.flash_mode, self.auto_cue, self.wall_t = False, None, -10.0\n"),
    ("before", "            spot = spots.get(str(i)) if isinstance(spots, dict) else None\n",
     "            cv = cz['heads'].get(i) if cz else None\n"
     "            if cv is not None:                      # HEAD RELAY: this head's lean (its avoid zones still cap it)\n"
     "                th_t = ch.theta(cv, lean_max)\n"
     "                if st['pan'] is not None:\n"
     "                    cap_ = avoid_cap(hd, st['pan'], th_t, margin=10.0)\n"
     "                    if cap_ is not None and th_t > cap_ * 0.9:\n"
     "                        th_t = cap_ * 0.9\n"),
    ("before", "            if st['pan'] is None:\n                st['pan'] = p_t\n",
     "            if cv is not None:                      # HEAD RELAY: the sweep (inside the head's pan window)\n"
     "                p_t = ch.pan(cv, pmin, pmax)\n"),
    ("after", "            lv = st['lvl'] * cue_lvl\n",
     "            if cz:                                  # HEAD RELAY: only the head whose turn it is shines, in the turn's colour\n"
     "                if cv is None:\n"
     "                    lv = lv if s.get('chase_spots') else 0.0\n"
     "                else:\n"
     "                    lv = level * max(0.3, clamp(cz['v'])) * cv['level']\n"
     "                    if cz.get('rgb'):\n"
     "                        hh, ss, _ = colorsys.rgb_to_hsv(*[clamp(x) for x in cz['rgb']])\n"
     "                        ss = max(ss, 0.55)          # never white\n"
     "                        r, g, b = self.match(colorsys.hsv_to_rgb(hh, ss, 1.0), s)\n"
     "                        w = (1.0 - ss) * 0.35\n"),
]
HUB = [
    ("replace", "dmx_unison=float, ",
     "dmx_unison=float, dmx_pattern=str, chase_arc=float, chase_dip=float, chase_dim=float, chase_spots=bool, "
     "chase_fast_energy=float, chase_fade_beats=float, chase_head_xy=dict, chase_lamps=dict, "),
    ("replace", "'hub_dmx.py', 'hub_vibes.py']", "'hub_dmx.py', 'hub_vibes.py', 'hub_chase.py']"),
    ("before", "            ordered = self.lim.step(ordered, now)\n",
     "            try:                                  # HEAD RELAY: the lamps beside the lit head glow (flicker protection after)\n"
     "                if getattr(getattr(self, 'dmx', None), 'chase', None) is not None:\n"
     "                    ordered = self.dmx.chase.lamps(ordered, self.rig.channels, now, beats, pmode)\n"
     "            except Exception as e:\n"
     "                if now - getattr(self, '_chase_err_t', 0.0) > 30.0:\n"
     "                    self._chase_err_t = now\n"
     "                    say('Head relay lamps: %s' % e)\n"),
]
RIG = [
    ("after", "    'uvoff': ('Spots back to the show (UV off the stars)', lambda: hub_setting('spot_fx', {})),\n",
     "    'relay': ('Head relay: one head at a time sweeps, then hands off round the room (grooves + breakdowns; drops as usual)',\n"
     "              lambda: hub_setting('dmx_pattern', 'show')),\n"
     "    'relayoff': ('Heads back to dancing together (relay off)', lambda: hub_setting('dmx_pattern', 'normal')),\n"),
]
JAR = [
    ("after", "    'uvoff':       'UV off the stars.',\n",
     "    'relay':       'Head relay on. One head at a time, the light travels round the room.',\n"
     "    'relayoff':    'Heads back to dancing together.',\n"),
    ("after", "RULES = [\n",
     "    (r'\\b(head ?|heads? )?(relay|chase)\\b.*\\b(off|stop|normal)\\b|\\b(stop|end|no more)\\b.*\\b(relay|chase)\\b', 'relayoff'),\n"
     "    (r'\\bhead ?relay\\b|\\b(start|turn on|do|run)\\b.*\\b(relay|chase)\\b|\\brelay (on|mode)\\b|\\bheads? (take turns|chase)\\b', 'relay'),\n"),
    ("after", "- show: full light show to the music. showuv: light show plus UV stars. flash: multicolour strobe. hype: fast bright party.\n",
     "- relay: heads take turns, one lit at a time, sweeping round the room. relayoff: heads back to dancing together.\n"),
]
SELF = [
    ("before", "\ndef main():\n",
     "def chase_check():                                  # Nov 15: head relay -- read-only\n"
     "    try:\n"
     "        import hub_chase\n"
     "        lamps = hub_chase.load_lamps(os.path.join(HERE, 'hub_lamps.json'))\n"
     "        with open(os.path.join(HERE, 'hub_state.json')) as f:\n"
     "            s = json.load(f).get('settings', {})\n"
     "    except Exception as e:\n"
     "        return res('Automations', 'Head relay', 'fail', 'hub_chase / hub_lamps.json unreadable (%s)' % e.__class__.__name__)\n"
     "    mode = s.get('dmx_pattern', 'normal')\n"
     "    if mode not in ('normal', 'show', 'relay'):\n"
     "        return res('Automations', 'Head relay', 'warn', 'dmx_pattern is %r (normal / show / relay)' % (mode,))\n"
     "    ch = hub_chase.Chase(type('H', (), {'state': {'settings': s}})(), lamps)\n"
     "    lonely = [str(i + 1) for i in range(4) if not ch.near(i)]\n"
     "    if not lamps or lonely:\n"
     "        return res('Automations', 'Head relay', 'warn', 'no lamp beside head(s) %s' % ', '.join(lonely or ['any']))\n"
     "    return res('Automations', 'Head relay', 'ok', 'pattern %s, %d lamps mapped' % (mode, len(lamps)))\n\n"),
    ("after", "    automations()\n", "    chase_check()\n"),
]
FILES = [('hub_dmx.py', DMX, 'hub_chase'), ('hue_hub.py', HUB, 'hub_chase'), ('rig_control.py', RIG, "'relayoff'"),
         (os.path.join('jarvis', 'jarvis.py'), JAR, "'relayoff'"), ('selftest.py', SELF, 'chase_check')]


def patch_text(text, patches):
    for how, anchor, new in patches:
        n = text.count(anchor)
        if n != 1:
            raise ValueError('anchor found %d times (want 1): %r' % (n, anchor[:70]))
        rep = {'before': new + anchor, 'after': anchor + new, 'replace': new}[how]
        text = text.replace(anchor, rep)
    return text


def main(argv):
    root = os.path.abspath(os.path.join(HERE, '..', '..'))
    if '--root' in argv:
        root = os.path.abspath(argv[argv.index('--root') + 1])
    check = '--check' in argv
    out, problems = {}, []
    for rel, patches, marker in FILES:
        path = os.path.join(root, rel)
        try:
            with open(path) as f:
                text = f.read()
        except OSError as e:
            problems.append('%s: cannot read (%s)' % (rel, e.__class__.__name__))
            continue
        if marker in text:
            print('  %-20s already has the head relay -- left alone' % rel)
            continue
        try:
            new = patch_text(text, patches)
            compile(new, rel, 'exec')
        except (ValueError, SyntaxError) as e:
            problems.append('%s: %s' % (rel, e))
            continue
        out[path] = new
    if problems:
        print('NOTHING CHANGED -- these files differ from what the patch expects:')
        for p in problems:
            print('  ' + p)
        return 1
    if check:
        print('OK: every anchor found (%d file(s) to patch)' % len(out))
        return 0
    for path, new in out.items():
        bak = path + '.bak-nov15-relay'
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'w') as f:
            f.write(new)
        print('  patched %s' % os.path.relpath(path, root))
    shutil.copy2(os.path.join(HERE, 'hub_chase.py'), os.path.join(root, 'hub_chase.py'))
    print('  added hub_chase.py')
    print('DONE: head relay installed. Turn it on with "Jarvis, head relay".')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
