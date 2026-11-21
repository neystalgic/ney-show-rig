#!/usr/bin/env python3
"""The hub's start lock: a second hub started while one holds the lock stands down (exit 0) within ~10 s."""
import os, subprocess, sys, tempfile, time, textwrap, fcntl
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'hue_hub.py')).read()
i = src.index('    import fcntl\n    global _HUB_LOCK'); j = src.index("    host = '0.0.0.0'")
block = textwrap.dedent(src[i:j])
d = tempfile.mkdtemp()
prog = os.path.join(d, 'lock_probe.py')   # NOT hue_hub.py: the self-test's 'is the hub running' check (pgrep) must not see it
open(prog, 'w').write('import os, sys, time\ndef say(m): print(m, flush=True)\n' + block + 'print("RUNNING", flush=True)\ntime.sleep(float(sys.argv[1]))\n')
ok = []
a = subprocess.Popen([sys.executable, prog, '15'], stdout=subprocess.PIPE, text=True)
time.sleep(1.0)
t0 = time.time()
b = subprocess.run([sys.executable, prog, '0'], capture_output=True, text=True, timeout=30)
ok.append(('second hub stands down while the first runs', b.returncode == 0 and 'stands down' in b.stdout and 9 < time.time() - t0 < 13))
a.kill(); a.wait()
c = subprocess.run([sys.executable, prog, '0'], capture_output=True, text=True, timeout=30)
ok.append(('after the first is gone (lock released by the OS), a new hub runs', 'RUNNING' in c.stdout))
for n, v in ok:
    print(('PASS ' if v else 'FAIL ') + n)
print('hub lock tests: %d passed, %d failed' % (sum(v for _, v in ok), sum(not v for _, v in ok)))
sys.exit(0 if all(v for _, v in ok) else 1)
