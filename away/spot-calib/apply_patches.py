#!/usr/bin/env python3
# Installs the Focus Spot calibration (Nov 16). Run from the Hue Rig folder:  python3 away/spot-calib/apply_patches.py
#  1. backs up calib.py + selftest.py (<file>.bak-<date>)
#  2. replaces calib.py with away/spot-calib/calib.py -- ONLY if the live calib.py is still the version this copy was
#     built from (otherwise STOP: it changed since Nov 16, nothing is touched)
#  3. adds the spot-calib test suite to selftest.py's SUITES (read-only check; skipped if already there)
# All or nothing; running it twice is harmless.
import hashlib, os, shutil, sys, time

BASE_SHA = 'c58348d58060c26c'          # first 16 hex of sha256(calib.py) the copy was built from (Nov 16)
HERE = os.path.dirname(os.path.abspath(__file__))
ANCHOR = "     [('jarvis/reminders.py', 'away/jarvis-reminders/reminders.py')]),\n"
LINE = ("    ('Focus Spot calibration (spot / aimspot / uvaim)', 'away/spot-calib/test_spot_calib.py',   # Nov 16\n"
        "     [('calib.py', 'away/spot-calib/calib.py')]),\n")


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()[:16]


def main(root):
    live, new, st = os.path.join(root, 'calib.py'), os.path.join(HERE, 'calib.py'), os.path.join(root, 'selftest.py')
    done_calib = sha(live) == sha(new)
    if not done_calib and sha(live) != BASE_SHA:
        print('STOP: calib.py changed since this copy was built (Nov 16). Nothing touched. '
              'Compare: diff calib.py away/spot-calib/calib.py')
        return 1
    s = open(st).read()
    need_suite = 'away/spot-calib/test_spot_calib.py' not in s
    if need_suite and s.count(ANCHOR) != 1:
        print('STOP: selftest.py SUITES anchor not found (it changed). Nothing touched.')
        return 1
    stamp = time.strftime('%Y%m%d-%H%M')
    if not done_calib:
        shutil.copy2(live, live + '.bak-' + stamp)
        shutil.copy2(new, live)
        print('calib.py replaced (backup calib.py.bak-%s)' % stamp)
    else:
        print('calib.py already deployed')
    if need_suite:
        shutil.copy2(st, st + '.bak-' + stamp)
        open(st, 'w').write(s.replace(ANCHOR, ANCHOR + LINE))
        print('selftest.py: spot-calib suite added (backup selftest.py.bak-%s)' % stamp)
    else:
        print('selftest.py already has the spot-calib suite')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(HERE))))
