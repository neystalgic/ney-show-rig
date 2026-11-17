#!/usr/bin/env python3
# Offline test for apply_patches.py (Nov 17): runs it on TEMP COPIES of the live files, never the real ones.
# Run:  python3 away/spot-power/test_apply_patches.py
import hashlib, io, os, py_compile, shutil, sys, tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import apply_patches as ap

PASS, FAIL = [], []
FILES = ('rig_control.py', 'rig_health.py', 'selftest.py')


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print('FAIL', name)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def temp_root():
    t = tempfile.mkdtemp()
    for f in FILES:
        shutil.copy2(os.path.join(ROOT, f), t)
    return t


def run(root):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ap.main(root)
    return rc, buf.getvalue()


before = {f: sha(os.path.join(ROOT, f)) for f in FILES}
t = temp_root()
rc, out = run(t)
check('applies cleanly (rc 0)', rc == 0)
rcx = open(os.path.join(t, 'rig_control.py')).read()
check('import added once', rcx.count('import spot_power ') == 1)
check('watcher started once', rcx.count('    spot_power.start()\n') == 1)
check('after_look hook once', rcx.count('spot_power.after_look(look)') == 1)
check('status next to head_power everywhere', rcx.count('spot_power=spot_power.status()') == rcx.count('head_power=head_power.status()') >= 1)
rh = open(os.path.join(t, 'rig_health.py')).read()
check('health row Spots', rh.count("row('Spots'") == 1 and rh.index("row('Spots'") < rh.index('# beat sender'))
st = open(os.path.join(t, 'selftest.py')).read()
check('selftest suite line', st.count('away/spot-power/test_spot_power.py') == 1)
check('spot_power.py copied', open(os.path.join(t, 'spot_power.py')).read() == open(os.path.join(HERE, 'spot_power.py')).read())
for f in FILES + ('spot_power.py',):
    try:
        py_compile.compile(os.path.join(t, f), doraise=True); ok = True
    except py_compile.PyCompileError as e:
        ok = False; print(e)
    check('%s compiles after patch' % f, ok)
check('backups written', all(any(n.startswith(f + '.bak-') for n in os.listdir(t)) for f in FILES))
# selftest SUITES still parses as a list with our entry last
ns = {}
src = st[st.index('SUITES = ['):st.index('\n\n\ndef suites():')]
exec(src, ns)
check('SUITES parses, spot power last', ns['SUITES'][-1][1] == 'away/spot-power/test_spot_power.py')
snap = {f: sha(os.path.join(t, f)) for f in FILES}
rc2, out2 = run(t)
check('second run is harmless', rc2 == 0 and snap == {f: sha(os.path.join(t, f)) for f in FILES} and 'already' in out2)
# a changed file -> STOP, nothing touched
t2 = temp_root()
p = os.path.join(t2, 'rig_health.py')
open(p, 'w').write(open(p).read().replace('    # beat sender\n', '    # beat sender v2\n'))
snap2 = {f: sha(os.path.join(t2, f)) for f in FILES}
rc3, out3 = run(t2)
check('STOP when an anchor is missing', rc3 == 1 and 'STOP' in out3)
check('STOP touches nothing', snap2 == {f: sha(os.path.join(t2, f)) for f in FILES}
      and not os.path.exists(os.path.join(t2, 'spot_power.py')))
check('live files unchanged', before == {f: sha(os.path.join(ROOT, f)) for f in FILES})
print('%d/%d passed' % (len(PASS), len(PASS) + len(FAIL)))
sys.exit(1 if FAIL else 0)
