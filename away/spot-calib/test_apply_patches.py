#!/usr/bin/env python3
# Offline test for apply_patches.py: runs it on TEMP COPIES of calib.py + selftest.py (live files never touched).
import hashlib, io, os, shutil, sys, tempfile, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import apply_patches as ap
fails = []
def check(n, ok):
    print(('ok   ' if ok else 'FAIL ') + n)
    ok or fails.append(n)
live_before = {f: hashlib.sha256(open(os.path.join(ROOT, f), 'rb').read()).hexdigest() for f in ('calib.py', 'selftest.py')}
def run(root):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ap.main(root)
    return rc, buf.getvalue()
t = tempfile.mkdtemp(prefix='spotapply_')
for f in ('calib.py', 'selftest.py'):
    shutil.copy2(os.path.join(ROOT, f), os.path.join(t, f))
rc, out = run(t)
check('first run ok', rc == 0)
check('calib.py now the new copy', ap.sha(os.path.join(t, 'calib.py')) == ap.sha(os.path.join(HERE, 'calib.py')))
check('backups written', any(n.startswith('calib.py.bak-') for n in os.listdir(t)) and any(n.startswith('selftest.py.bak-') for n in os.listdir(t)))
s = open(os.path.join(t, 'selftest.py')).read()
check('suite line added once', s.count('away/spot-calib/test_spot_calib.py') == 1)
compile(s, 'selftest.py', 'exec')
check('patched selftest.py compiles', True)
rc, out = run(t)
check('second run harmless', rc == 0 and 'already' in out and open(os.path.join(t, 'selftest.py')).read().count('spot-calib/test_spot') == 1)
t2 = tempfile.mkdtemp(prefix='spotapply2_')
for f in ('calib.py', 'selftest.py'):
    shutil.copy2(os.path.join(ROOT, f), os.path.join(t2, f))
open(os.path.join(t2, 'calib.py'), 'a').write('\n# Michael edited this later\n')
rc, out = run(t2)
check('changed calib.py -> STOP, nothing touched', rc == 1 and 'STOP' in out and not any('.bak-' in n for n in os.listdir(t2)))
check('live files untouched', live_before == {f: hashlib.sha256(open(os.path.join(ROOT, f), 'rb').read()).hexdigest() for f in ('calib.py', 'selftest.py')})
print('%d failed' % len(fails))
sys.exit(1 if fails else 0)
