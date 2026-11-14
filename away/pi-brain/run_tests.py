#!/usr/bin/env python3
# Runs this folder's tests offline (sockets blocked). jarvis.py is borrowed read-only from pi/brain/ (as on the Pi).
import os, runpy, socket, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
sys.path.append(os.path.join(HERE, '..', '..', 'pi', 'brain'))      # only for jarvis.py -- this folder's copies win


def _blocked(*a, **k):
    raise OSError('network blocked in tests')
socket.socket.connect = _blocked
socket.create_connection = _blocked
for t in ('test_looks.py', 'test_brain.py'):
    print('==', t)
    try:
        runpy.run_path(t, run_name='__main__')
    except SystemExit as e:
        if e.code:
            sys.exit(e.code)
print('ALL TESTS PASSED')
