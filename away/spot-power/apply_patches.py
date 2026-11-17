#!/usr/bin/env python3
# Installs SPOT POWER (Nov 17). Run from the Hue Rig folder:  python3 away/spot-power/apply_patches.py
#  1. backs up rig_control.py, rig_health.py, selftest.py (<file>.bak-<date>)
#  2. adds spot_power.py (new file, copied from away/spot-power/)
#  3. rig_control.py: import spot_power, start its watcher next to head_power's, call spot_power.after_look(look)
#     after every look, and put spot_power.status() next to head_power.status() (status, health, bridge)
#  4. rig_health.py: a "Spots" row under "Moving heads"
#  5. selftest.py: the spot-power test suite (read-only check)
# Each patch finds an exact anchor line; if ANY anchor is missing (the file changed) it STOPS and touches nothing.
# All or nothing; running it twice is harmless.
import os, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))

RC = [  # (anchor, replacement, marker that says it's already done)
    ("import head_power                                  # Hue Smart Plugs on the moving heads (dormant until they exist)\n",
     "import head_power                                  # Hue Smart Plugs on the moving heads (dormant until they exist)\n"
     "import spot_power                                  # Hue Smart Plugs on the two Focus Spots (Nov 17, dormant until they exist)\n",
     "import spot_power"),
    ("    head_power.start()\n",
     "    head_power.start()\n    spot_power.start()\n",
     "spot_power.start()"),
    ("            LOOKS[look][1]()\n            STATE.update(look=look, since=time.strftime('%H:%M'))\n",
     "            LOOKS[look][1]()\n            spot_power.after_look(look)             # spots power on/off with their looks (Nov 17)\n"
     "            STATE.update(look=look, since=time.strftime('%H:%M'))\n",
     "spot_power.after_look(look)"),
]
RC_ALL = ("head_power=head_power.status(), ", "head_power=head_power.status(), spot_power=spot_power.status(), ",
          "spot_power=spot_power.status()")
RH = ("    # beat sender\n",
      "    # spots power (Nov 17)\n"
      "    sp = extra.get('spot_power') or {}\n"
      "    son = [k for k, v in (sp.get('on') or {}).items() if v]\n"
      "    out.append(row('Spots', 'ok' if son else 'idle', ('%d of %d on' % (len(son), len(sp.get('on') or {})))\n"
      "                   if sp.get('on') else str(sp.get('last') or 'no plugs found')))\n"
      "    # beat sender\n",
      "row('Spots'")
ST = ("]\n\n\ndef suites():",
      "    ('Spot power (Hue plugs on the Focus Spots)', 'away/spot-power/test_spot_power.py',   # Nov 17\n"
      "     [('spot_power.py', 'away/spot-power/spot_power.py')]),\n]\n\n\ndef suites():",
      "away/spot-power/test_spot_power.py")


def plan(text, patches, every=None):
    """Returns (new text, list of problems)."""
    bad = []
    for anchor, new, mark in patches:
        if mark in text:
            continue
        if text.count(anchor) != 1:
            bad.append(anchor.strip()[:60])
            continue
        text = text.replace(anchor, new)
    if every:
        anchor, new, mark = every
        if mark not in text:
            if anchor not in text:
                bad.append(anchor.strip()[:60])
            text = text.replace(anchor, new)
    return text, bad


def main(root):
    files = {'rig_control.py': (RC, RC_ALL), 'rig_health.py': ([RH], None), 'selftest.py': ([ST], None)}
    out, problems = {}, []
    for name, (patches, every) in files.items():
        p = os.path.join(root, name)
        old = open(p).read()
        new, bad = plan(old, patches, every)
        problems += ['%s: anchor not found: %s' % (name, b) for b in bad]
        out[name] = (p, old, new)
    if problems:
        print('STOP: a file changed since Nov 17. Nothing touched.\n  ' + '\n  '.join(problems))
        return 1
    stamp = time.strftime('%Y%m%d-%H%M')
    sp_live, sp_new = os.path.join(root, 'spot_power.py'), os.path.join(HERE, 'spot_power.py')
    if not os.path.exists(sp_live) or open(sp_live).read() != open(sp_new).read():
        if os.path.exists(sp_live):
            shutil.copy2(sp_live, sp_live + '.bak-' + stamp)
        shutil.copy2(sp_new, sp_live)
        print('spot_power.py installed')
    else:
        print('spot_power.py already installed')
    for name, (p, old, new) in out.items():
        if new == old:
            print('%s already patched' % name)
            continue
        shutil.copy2(p, p + '.bak-' + stamp)
        open(p, 'w').write(new)
        print('%s patched (backup %s.bak-%s)' % (name, name, stamp))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(HERE))))
