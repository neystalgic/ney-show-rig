#!/usr/bin/env python3
"""Offline tests for Jarvis workout mode (away loop J4). No network, no lights, nothing on the real Desktop.
   python3 away/jarvis-workout/test_workout.py        -> last line 'ALL n PASSED' or FAIL lines, exit 1"""
import ast, contextlib, csv, datetime as dt, hashlib, importlib, io, os, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(os.path.dirname(HERE))


def _no_net(*a, **k):
    raise AssertionError('network call attempted')
socket.socket.connect = _no_net
socket.create_connection = _no_net

N, BAD = [0], []
def ok(cond, what):
    N[0] += 1
    if not cond:
        BAD.append(what)
        print('FAIL:', what)

sys.path.insert(0, HERE)
import workout as w

class Clock:
    t = dt.datetime(2026, 11, 20, 18, 10)
clock = Clock()
w._now = lambda: clock.t
tmp = tempfile.mkdtemp()
w.LOG = os.path.join(tmp, 'Workout Log.csv')
REAL_DESK_LOG = os.path.expanduser('~/Desktop/Workout Log.csv')
desk_before = os.path.exists(REAL_DESK_LOG) and open(REAL_DESK_LOG, 'rb').read()

def rows():
    with open(w.LOG, newline='') as f:
        return list(csv.DictReader(f))

def reset():
    w.STATE.update(ask_until=None, ask_row=None)
    if os.path.exists(w.LOG):
        os.replace(w.LOG, w.LOG + '.old-%d' % N[0])     # tests move, never delete

def kind(t):
    return (w.parse(t) or {}).get('kind')

# ---- 1. what starts a workout (and what doesn't)
starts = {"Jarvis, starting a walk": 'walk', "I'm starting a run": 'run', "going for a walk": 'walk',
          "Hey Siri, going for a quick run.": 'run', "heading out for a hike": 'hike', "starting my workout": 'workout',
          "I'm going on a bike ride": 'bike', "going for a ride": 'bike', "let's go for a walk": 'walk',
          "I'm going running": 'run', "going hiking": 'hike', "starting a jog": 'run', "start a walk": 'walk',
          "I'm about to go for a run": 'run', "going to the gym": None, "starting a walk with the dog": 'walk',
          "going for a walk around the block": 'walk', "starting a long walk now": 'walk', "walk time": 'walk',
          "I'm off for a swim": 'swim', "starting yoga": 'yoga', "i\u2019m starting a walk": 'walk',
          "starting a gym session": 'workout', "doing a workout": 'workout'}
for t, want in starts.items():
    p = w.parse(t)
    got = p and p['kind'] == 'start' and p['what']
    ok(got == want if want else not p, 'start: %r -> %r (want %r)' % (t, got, want))
for t in ["run", "walk", "start the show", "light show", "run the light show", "remind me to go for a walk at 6",
          "set a 20 minute timer for my run", "I'm going to bed", "walk me through it", "going for a walk to the store "
          "to buy groceries and then cook dinner", "turn on the walkway lights", "I'm done", "I'm back", "7",
          "start a run of the rainbow", "purple at 50 percent", "log 268.4", "I ate a protein bar after my run",
          "how long is the movie", "yes", "no"]:
    ok(w.parse(t) is None, 'not ours: %r -> %r' % (t, w.parse(t)))

# ---- 2. what ends one
for t, want in {"done with my walk": 'walk', "Jarvis, I'm done with my run": 'run', "back from my hike": 'hike',
                "finished my workout": 'workout', "I just finished my run": 'run', "done walking": 'walk',
                "walk done": 'walk', "my run is over": 'run', "end my walk": 'walk', "stop the workout": 'workout',
                "I'm back from my walk": 'walk', "home from my bike ride": 'bike'}.items():
    p = w.parse(t)
    ok(p and p['kind'] == 'done' and p['what'] == want, 'done: %r -> %r' % (t, p))
p = w.parse("done with my run, felt like a 7")
ok(p == {'kind': 'done', 'what': 'run', 'feel': 7}, 'done + feel in one sentence: %r' % p)
p = w.parse("finished my walk and it was an 8 out of 10")
ok(p and p.get('feel') == 8, 'done + "it was an 8 out of 10": %r' % p)
ok(kind('cancel my walk') == 'cancel' and kind('never mind the run') == 'cancel', 'cancel phrases')
ok(kind('how long have I been walking') == 'howlong' and kind('how long is my run') == 'howlong', 'how long phrases')

# ---- 3. a whole walk: start -> done -> how it felt
reset()
r = w.handle(w.parse('starting a walk'))
ok(r == 'Walk started at 6:10. Enjoy it.', 'start reply: %r' % r)
ok(rows() == [{'Date': '2026-11-20', 'Start': '18:10', 'End': '', 'Minutes': '', 'Kind': 'walk', 'Feel (1-10)': '',
               'Notes': ''}], 'start row written: %r' % rows())
ok(open(w.LOG).readline().strip() == ','.join(w.HEADER), 'header row')
ok(kind("I'm back") == 'done', "'I'm back' means done while a walk is going")
ok(kind('7') is None, 'a bare number is not ours before the question')
clock.t += dt.timedelta(minutes=14)
ok(w.handle(w.parse('how long have I been walking')) == '14 minutes so far on your walk. Keep going.', 'how long')
r = w.handle(w.parse('starting a run'))
ok(r.startswith("You're already on a walk since 6:10") and len(rows()) == 1, 'second start -> already, no new row: %r' % r)
clock.t += dt.timedelta(minutes=18)
r = w.handle(w.parse('done with my walk'))
ok(r == 'Nice work. 32 minutes walk. How did it feel, 1 to 10?', 'done reply asks 1-10: %r' % r)
ok(rows()[0]['End'] == '18:42' and rows()[0]['Minutes'] == '32', 'end + minutes filled')
for t, n in [('about an 8', 8), ('8', 8), ('eight', 8), ('8 out of 10', 8), ('it was a 7', 7), ("I'd say a 6", 6),
             ('7.5', 7.5), ('ten', 10), ('felt like a 9', 9)]:
    p = w.parse(t)
    ok(p == {'kind': 'feel', 'feel': n}, 'feel %r -> %r' % (t, p))
ok(w.parse('11') is None and w.parse('0') is None and w.parse('purple at 50 percent') is None, 'only 1-10 count')
clock.t += dt.timedelta(minutes=3)
r = w.handle(w.parse('about an 8'))
ok(r.startswith('Got it, 8 out of 10') and rows()[0]['Feel (1-10)'] == '8', 'feel saved: %r' % r)
ok(w.parse('8') is None, 'after the answer a number is not ours again')
ok(kind("I'm back") is None, "'I'm back' after the walk ended is not ours")
ok(w.handle(w.parse('done with my walk')).startswith("I didn't have a walk going"), 'done twice -> nothing to close')

# ---- 4. the question times out, skip, done-with-feel, cancel, stale
reset()
w.handle(w.parse('going for a run'))
clock.t += dt.timedelta(minutes=25)
w.handle(w.parse("I'm back"))
ok(rows()[0]['Minutes'] == '25' and rows()[0]['Kind'] == 'run', "'I'm back' closes the run")
clock.t += dt.timedelta(minutes=11)
ok(w.parse('7') is None, 'number 11 min after the question is not ours')
reset()
w.handle(w.parse('starting a hike'))
clock.t += dt.timedelta(minutes=90)
w.handle(w.parse('done with my hike'))
ok(w.handle(w.parse('skip')).startswith('Okay, no score') and rows()[0]['Feel (1-10)'] == '', 'skip leaves it blank')
ok(w.parse('7') is None, 'after skip a number is not ours')
reset()
w.handle(w.parse('starting a bike ride'))
clock.t += dt.timedelta(minutes=45)
r = w.handle(w.parse('done with my bike ride, it was a 9'))
ok(r == 'Nice. 45 minutes bike ride, 9 out of 10. Logged.' and rows()[0]['Feel (1-10)'] == '9', 'done+feel: %r' % r)
ok(w.parse('7') is None, 'done+feel asks nothing after')
reset()
w.handle(w.parse('starting a walk'))
ok(w.handle(w.parse('cancel my walk')) == 'Okay, walk cancelled.' and rows()[0]['Notes'] == 'cancelled', 'cancel marks row')
ok(len(rows()) == 1 and w.open_row() is None, 'cancelled row kept, not going')
ok(w.handle(w.parse('cancel my walk')).startswith("There's no workout going"), 'cancel with nothing going')
reset()
w.handle(w.parse('starting a walk'))
clock.t += dt.timedelta(hours=7)
ok(w.open_row() is None, 'a 7-hour-old start is treated as forgotten')
ok(w.handle(w.parse('done with my walk')).startswith("I didn't have a walk going"), 'forgotten walk not closed as 7 h')
w.handle(w.parse('starting a run'))
rs = rows()
ok(len(rs) == 2 and rs[0]['Notes'] == 'no end said' and rs[1]['Kind'] == 'run' and w.open_row()['Kind'] == 'run',
   'new start notes the forgotten one: %r' % rs)
clock.t += dt.timedelta(minutes=95)
r = w.handle(w.parse('done with my run'))
ok(r.startswith('Nice work. 1 hour 35 minutes run'), 'long run reads in hours: %r' % r)
ok(w._mins(1) == '1 minute' and w._mins(120) == '2 hours' and w._mins(150) == '2 hours 30 minutes', 'minutes wording')

# ---- 5. the log is kept tidy + the week summary
reset()
with open(w.LOG, 'w', newline='') as f:
    f.write('Date,Start,End,Minutes,Kind,Feel (1-10),Notes\n2026-11-18,07:00,07:30,30,walk,6,\n'
            '2026-11-19,18:00,18:40,40,run,8,\n2026-11-19,20:00,,,walk,,cancelled\n2026-11-01,07:00,07:30,30,walk,9,\n')
ok(w.week_summary() == (2, 70, 7.0), 'week summary: %r' % (w.week_summary(),))
w.handle(w.parse('starting a walk'))
ok(len(rows()) == 5 and rows()[0]['Feel (1-10)'] == '6', 'old rows kept as they were')
ok(not os.path.exists(w.LOG + '.tmp'), 'no .tmp file left behind')
ok((os.path.exists(REAL_DESK_LOG) and open(REAL_DESK_LOG, 'rb').read()) == desk_before, 'real Desktop log untouched')

# ---- 6. module hygiene: no lights, no network
src = open(os.path.join(HERE, 'workout.py')).read()
tree = ast.parse(src)
mods = {n.name.split('.')[0] for x in ast.walk(tree) if isinstance(x, ast.Import) for n in x.names}
ok(mods <= {'csv', 'datetime', 'os', 're'}, 'imports: %s' % mods)
ok(not any(s in src for s in ('urllib', '192.168', '7040', 'subprocess', 'rig(')), 'workout.py has no network/light code')

# ---- 7. installer on a COPY of the live files (live files never touched)
def digest(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()
live = [os.path.join(RIG, p) for p in ('jarvis/jarvis.py', 'selftest.py', '.gitignore')]
before = [digest(p) for p in live]

def fresh_root():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, 'jarvis'))
    for f in os.listdir(os.path.join(RIG, 'jarvis')):
        if f.endswith('.py') or f in ('jarvis.json', 'meals.json'):
            shutil.copy2(os.path.join(RIG, 'jarvis', f), os.path.join(root, 'jarvis', f))
    for f in sorted(set(x for x in os.listdir(RIG) if x.endswith('.py')) | {'.gitignore', 'light_schedule.json'}):
        if os.path.isfile(os.path.join(RIG, f)):    # the rig's own .py modules; never secrets
            shutil.copy2(os.path.join(RIG, f), os.path.join(root, f))
    return root

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
import importlib.util
ap = load(os.path.join(HERE, 'apply_patches.py'), 'ap_workout')
root = fresh_root()
out = io.StringIO()
with contextlib.redirect_stdout(out):
    ap.main(root)
ok(out.getvalue().count('patched') == 2 and 'copied' in out.getvalue(), 'installer patches 2 files + copies workout.py')
snap = {f: open(os.path.join(root, f)).read() for f in ('jarvis/jarvis.py', 'selftest.py')}
out = io.StringIO()
with contextlib.redirect_stdout(out):
    ap.main(root)
ok(out.getvalue().count('already patched') == 2, 'second run says already')
ok(all(open(os.path.join(root, f)).read() == t for f, t in snap.items()), 'second run changes nothing')
ok(os.path.exists(os.path.join(root, 'jarvis', 'jarvis.py.bak-nov15-workout')), 'backup made')
root2 = fresh_root()
jp = os.path.join(root2, 'jarvis', 'jarvis.py')
open(jp, 'w').write(open(jp).read().replace("    if r:\n        return {'action': 'reminder', 'value': r}\n",
                                            "    if r: return {'action': 'reminder', 'value': r}\n"))
snap2 = {f: open(os.path.join(root2, f)).read() for f in ('jarvis/jarvis.py', 'selftest.py')}
try:
    with contextlib.redirect_stdout(io.StringIO()):
        ap.main(root2)
    stopped = False
except SystemExit as e:
    stopped = 'STOP' in str(e)
ok(stopped and all(open(os.path.join(root2, f)).read() == x for f, x in snap2.items())
   and not os.path.exists(os.path.join(root2, 'jarvis', 'workout.py')), 'changed file -> STOP, nothing written')
# works with the craving installer (J3, not deployed yet) in either order
cpath = os.path.join(RIG, 'away', 'jarvis-craving', 'apply_patches.py')
if os.path.exists(cpath):
    cap = load(cpath, 'ap_craving')
    for order in ((cap, ap), (ap, cap)):
        r3 = fresh_root()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                for m in order:
                    m.main(r3)
            t = open(os.path.join(r3, 'jarvis', 'jarvis.py')).read()
            both = 'Nov 15: workout mode' in t and 'Nov 15: craving support' in t
        except SystemExit as e:
            both = False
        ok(both, 'craving + workout installers both apply (%s first)' % ('craving' if order[0] is cap else 'workout'))

# the patched Jarvis, end to end (fake rig; Popen blocked so nothing speaks)
sys.path.insert(0, os.path.join(root, 'jarvis'))
for m in ('jarvis', 'workout', 'craving', 'reminders', 'brief'):
    sys.modules.pop(m, None)
real = subprocess.Popen
subprocess.Popen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Popen in test'))
try:
    j = importlib.import_module('jarvis')
    wm = sys.modules['workout']
    wm._now = lambda: clock.t
    wm.LOG = os.path.join(tempfile.mkdtemp(), 'Workout Log.csv')
    wm.STATE.update(ask_until=None, ask_row=None)
    s = j.settings()
    route = {'Jarvis, starting a walk': 'workout', 'going for a run': 'workout', 'hype': 'hype', 'purple': 'color',
             'log 268.4': 'weight', 'remind me at 9 to go for a walk': 'reminder', '7': None}
    for t, want in route.items():
        got = (j.by_rules(t) or {}).get('action')
        ok(got == want, 'patched route %r -> %r (want %r)' % (t, got, want))
    acts = [i['action'] for i in j.understand_all('starting a run and hype', s)]
    ok(sorted(acts) == ['hype', 'workout'], "'starting a run and hype' -> the run + the look he asked for: %r" % acts)
    rc = []
    r = j.handle('Jarvis, starting a walk', s, rig=lambda p: rc.append(p), confirm=False)
    ok('Walk started at' in r and rc == [], 'patched handle: walk started, lights untouched: %r' % r)
    clock.t += dt.timedelta(minutes=20)
    r = j.handle('done with my walk', s, rig=lambda p: rc.append(p), confirm=False)
    ok('How did it feel, 1 to 10?' in r and rc == [], 'patched handle: asks 1-10: %r' % r)
    ok(j.by_rules('7')['action'] == 'workout', 'a number routes to the score right after')
    r = j.handle('about a 7', s, rig=lambda p: rc.append(p), confirm=False)
    ok('7 out of 10' in r and rc == [], 'patched handle: score saved: %r' % r)
    ok(len(j.understand_all('done with my run, and it was a 7', s)) == 1, "'done ... and it was a 7' stays one thing")
    ok("workouts like 'starting a walk'" in j.do({'action': 'help'}, s, lambda p: None), 'help line mentions it')
    ok('workout' not in j.ACTIONS, 'the model can never pick workout (not in the allowlist)')
finally:
    subprocess.Popen = real

# the selftest's read-only line, with a fake HOME
st = load(os.path.join(root, 'selftest.py'), 'st_patched')
home = os.environ.get('HOME')
fake = tempfile.mkdtemp()
os.makedirs(os.path.join(fake, 'Desktop'))
os.environ['HOME'] = fake
try:
    st.RESULTS[:] = []
    st.workout_check()
    ok(st.RESULTS[-1]['level'] == 'ok' and 'no workouts' in st.RESULTS[-1]['detail'], 'selftest: no log -> ok')
    lp = os.path.join(fake, 'Desktop', 'Workout Log.csv')
    today = dt.date.today().isoformat()
    open(lp, 'w').write('Date,Start,End,Minutes,Kind,Feel (1-10),Notes\n%s,00:01,00:31,30,walk,7,\n' % today)
    st.workout_check()
    ok(st.RESULTS[-1]['level'] == 'ok' and '1 this week' in st.RESULTS[-1]['detail'], 'selftest: %r' % st.RESULTS[-1])
    open(lp, 'a').write('2026-01-02,07:00,,,run,,\n')
    st.workout_check()
    ok(st.RESULTS[-1]['level'] == 'warn', 'selftest: forgotten workout -> warn: %r' % st.RESULTS[-1])
finally:
    os.environ['HOME'] = home
ok("    workout_check()\n" in open(os.path.join(root, 'selftest.py')).read(), 'selftest main calls workout_check')

# old Jarvis tests still pass on the patched copy (network blocked in the child too)
blk = tempfile.mkdtemp()
open(os.path.join(blk, 'sitecustomize.py'), 'w').write(
    "import socket\ndef _n(*a, **k):\n    raise OSError('network blocked in test')\nsocket.socket.connect = _n\nsocket.create_connection = _n\n")
env = dict(os.environ, PYTHONPATH=blk)
t = subprocess.run([sys.executable, 'test_jarvis.py'], cwd=os.path.join(root, 'jarvis'), capture_output=True, text=True,
                   env=env, timeout=170)
ok(t.returncode == 0, 'old test_jarvis passes on patched copy: %s' % (t.stdout + t.stderr)[-400:])
ok([digest(p) for p in live] == before, 'live files untouched')

print('ALL %d PASSED' % N[0] if not BAD else '%d FAILED of %d' % (len(BAD), N[0]))
sys.exit(1 if BAD else 0)
