#!/usr/bin/env python3
"""Offline tests for Jarvis craving support (away loop J3). No network, no lights, no real 'say'.
   python3 away/jarvis-craving/test_craving.py        -> last line 'ALL n PASSED' or FAIL lines, exit 1"""
import ast, datetime as dt, hashlib, importlib, json, os, shutil, socket, subprocess, sys, tempfile

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
import craving as c

class Clock:
    t = dt.datetime(2026, 11, 20, 21, 0)
clock = Clock()
c._now = lambda: clock.t

class FakeProc:
    def __init__(self, args):
        self.args, self.dead = args, False
    def poll(self):
        return 0 if self.dead else None
    def terminate(self):
        self.dead = True
started = []
def runner(args):
    p = FakeProc(args)
    started.append(p)
    return p

def reset():
    c.STATE.update(offer_until=None, last_reason=None, count=None)
    del started[:]

tmp = tempfile.mkdtemp()
qf = os.path.join(tmp, 'quit.json')
def write_quit(d):
    with open(qf, 'w') as f:
        json.dump(d, f)

S = {'voice': 'Moira'}

# ---- 1. what counts as a craving (and what doesn't)
for t in ["Jarvis, I'm craving", "i'm craving", "craving", "I'm having a craving", "having a craving right now",
          "craving really bad", "I'm craving weed", "craving a joint", "I have an urge to smoke", "cravings again",
          "I really want to smoke", "i want to get high", "I need a joint", "I'm craving, help me", "Hey Siri, craving."]:
    ok((c.parse(t) or {}).get('kind') == 'craving', 'craving: %r' % t)
for t in ["I'm craving pizza", "craving tacos and a burrito", "I ate a craving bar", "remind me at 9 if I'm craving",
          "10 minute timer for the craving", "I want to watch a movie", "smoke machine", "light show", "", "jarvis"]:
    ok((c.parse(t) or {}).get('kind') != 'craving', 'not craving: %r' % t)
for t in ['how many days clean', 'how long have I been clean', "what's my streak", 'days clean?', 'how long since I quit']:
    ok((c.parse(t) or {}).get('kind') == 'streak', 'streak: %r' % t)
ok(c.parse('stop counting') == {'kind': 'stop'} and c.parse('stop the breathing count') == {'kind': 'stop'}, 'stop phrases')
reset()
for t in ['yes', 'no', 'yeah please', 'no thanks']:
    ok(c.parse(t) is None, '%r means nothing without an offer' % t)

# ---- 2. streak
write_quit({'start': '2026-11-20', 'reasons': []})
ok(c.streak_line(c.load_quit(qf), clock.t.date()) == "Day one. You're doing it.", 'day one')
write_quit({'start': '2026-11-19'})
ok(c.streak_line(c.load_quit(qf), clock.t.date()) == '1 day clean.', '1 day (singular)')
write_quit({'start': '2026-11-13'})
ok(c.streak_line(c.load_quit(qf), clock.t.date()) == '7 days clean. One full week.', 'week milestone')
write_quit({'start': '2026-11-15'})
ok(c.streak_line(c.load_quit(qf), clock.t.date()) == '5 days clean.', '5 days, no milestone')
for bad in [{'start': '2026-12-01'}, {'start': 'last week'}, {'start': ''}, {}, ['x']]:
    write_quit(bad)
    ok(c.streak_line(c.load_quit(qf), clock.t.date()) == '', 'no streak for %r' % (bad,))
ok(c.load_quit(os.path.join(tmp, 'missing.json')) == {}, 'missing quit.json is fine')
with open(qf, 'w') as f:
    f.write('{broken')
ok(c.load_quit(qf) == {}, 'broken quit.json is fine')

# ---- 3. the craving reply
reset()
write_quit({'start': '2026-11-15', 'reasons': ['Eat without getting sick.', 'Clear head for producing', '  ']})
calls = []
rig = lambda p: calls.append(p)
r = c.handle({'kind': 'craving'}, S, rig, path=qf, runner=runner)
ok(r.startswith('5 days clean. Your reason: '), 'reply leads with streak + reason: %r' % r)
ok('in for 4, hold for 7, out for 8' in r and r.endswith('Want the calm look? Say yes.'), 'reply has 4-7-8 + offer')
ok(calls == [], 'a craving never touches the lights')
ok(len(r) < 220, 'reply is short (%d chars)' % len(r))
ok(not any(w in r.lower() for w in ('should', 'must', 'doctor', 'health', 'cure', 'withdrawal', 'chs')), 'not preachy, no medical words')
ok(len(started) == 1 and started[0].args[:3] == ['/usr/bin/say', '-v', 'Moira'], 'count spoken on the Mac with Moira')
seen = []
for i in range(12):
    c.handle({'kind': 'craving'}, S, rig, path=qf, runner=runner)
    seen.append(c.STATE['last_reason'])
ok(all(a != b for a, b in zip(seen, seen[1:])), 'never the same reason twice in a row')
ok(set(seen) == {'Eat without getting sick', 'Clear head for producing'}, 'blank reasons skipped, dots tidied')
ok(sum(1 for p in started if not p.dead) == 1, 'saying it again stops the old count: one voice only')

reset()
write_quit({})
r = c.handle({'kind': 'craving'}, S, rig, path=qf, runner=runner)
ok(any(e in r for e in c.ENCOURAGE) and 'jarvis/quit.json' in r, 'no quit.json yet: kind line + where to add it')
reset()
r = c.handle({'kind': 'craving'}, dict(S, craving_count='off'), rig, path=qf, runner=runner)
ok(started == [] and 'Three rounds' in r, "craving_count 'off' -> no Mac voice, reply counts instead")
reset()
r = c.handle({'kind': 'craving'}, S, rig, path=qf, runner=lambda a: (_ for _ in ()).throw(OSError('no say')))
ok('Three rounds' in r, 'say missing -> still a calm reply')

# ---- 4. the count itself
sc = c.count_script(lead_ms=0)
secs = c.script_seconds(sc)
ok(50 <= secs <= 75, 'count is about a minute (%.0f s)' % secs)
ok(sc.count('Hold') == 3 and sc.count('Out, slowly') == 3 and sc.count(' In ') == 3, 'three rounds of 4-7-8')
ok(' four ' in sc and ' seven ' in sc and ' eight ' in sc and 'nine' not in sc, 'counts reach 4, 7 and 8')
ok(c.count_script().startswith('[[slnc 12000]]'), 'lead-in so Siri finishes first')
reset()
c.handle({'kind': 'craving'}, dict(S, craving_lead_ms=3000), rig, path=qf, runner=runner)
ok(started[0].args[3].startswith('[[slnc 3000]]'), 'craving_lead_ms setting')
ok(c.handle({'kind': 'stop'}, S, path=qf) == 'Okay, stopped counting.' and started[0].dead, 'stop counting')
ok(c.handle({'kind': 'stop'}, S, path=qf) == "I'm not counting right now.", 'stop when nothing runs')
real = subprocess.Popen
got = []
subprocess.Popen = lambda *a, **k: got.append((a, k)) or FakeProc(a[0])
try:
    reset()
    c.start_count(S)
finally:
    subprocess.Popen = real
ok(got and got[0][1].get('start_new_session') is True, 'Popen never blocks (new session)')

# ---- 5. yes / no to the calm look
reset(); calls = []
c.handle({'kind': 'craving'}, S, rig, path=qf, runner=runner)
clock.t += dt.timedelta(minutes=4)
ok(c.parse('yes please') == {'kind': 'yes'}, 'yes within 5 minutes is ours')
ok(c.handle(c.parse('yes please'), S, rig, path=qf) == 'Calm look on. Breathe with it.' and calls == ['breathe'], 'yes -> breathe look, once')
ok(c.parse('yes') is None, 'a second yes is not ours any more')
c.handle({'kind': 'craving'}, S, rig, path=qf, runner=runner)
clock.t += dt.timedelta(minutes=6)
ok(c.parse('yes') is None, 'yes after 6 minutes is not ours')
c.handle({'kind': 'craving'}, S, rig, path=qf, runner=runner)
ok(c.handle(c.parse('no thanks'), S, rig, path=qf).startswith('Okay, lights stay') and calls == ['breathe'], 'no -> lights untouched')
ok(c.parse('yes') is None, 'after no, yes is not ours')
calls = []
c.handle({'kind': 'craving'}, S, rig, path=qf, runner=runner)
c.handle({'kind': 'yes'}, dict(S, craving_look='redglow'), rig, path=qf)
c.handle({'kind': 'craving'}, S, rig, path=qf, runner=runner)
c.handle({'kind': 'yes'}, dict(S, craving_look='rm -rf; x'), rig, path=qf)
ok(calls == ['redglow', 'breathe'], 'craving_look setting; odd names fall back to breathe')
r = c.handle({'kind': 'yes'}, S, lambda p: (_ for _ in ()).throw(KeyError(p)), path=qf)
ok('keep breathing' in r, 'rig down -> kind message, no crash')
reset()
ok(c.handle({'kind': 'streak'}, S, path=qf).startswith("I don't have your start date"), 'streak with no date')
write_quit({'start': '2026-11-11'})
ok(c.handle({'kind': 'streak'}, S, path=qf).endswith('days clean.'), 'streak with a date')

# ---- 6. module hygiene
tree = ast.parse(open(os.path.join(HERE, 'craving.py')).read())
mods = {n.name.split('.')[0] for x in ast.walk(tree) if isinstance(x, ast.Import) for n in x.names}
mods |= {x.module.split('.')[0] for x in ast.walk(tree) if isinstance(x, ast.ImportFrom)}
ok(mods <= {'datetime', 'json', 'os', 'random', 're', 'subprocess'}, 'imports: %s' % mods)
src = open(os.path.join(HERE, 'craving.py')).read()
ok('urllib' not in src and '192.168' not in src and '7040' not in src, 'craving.py has no network code')

# ---- 7. installer on a COPY of the live files (live files never touched)
def digest(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()
live = [os.path.join(RIG, p) for p in ('jarvis/jarvis.py', 'selftest.py', '.gitignore')]
before = [digest(p) for p in live]
root = tempfile.mkdtemp()
os.makedirs(os.path.join(root, 'jarvis'))
for f in os.listdir(os.path.join(RIG, 'jarvis')):
    if f.endswith('.py') or f in ('jarvis.json', 'meals.json'):
        shutil.copy2(os.path.join(RIG, 'jarvis', f), os.path.join(root, 'jarvis', f))
for f in sorted(set(x for x in os.listdir(RIG) if x.endswith('.py')) | {'.gitignore', 'light_schedule.json'}):
    if os.path.isfile(os.path.join(RIG, f)):   # the rig's own .py modules (test_jarvis imports some); never secrets
        shutil.copy2(os.path.join(RIG, f), os.path.join(root, f))
sys.path.insert(0, HERE)
import apply_patches as ap
import io, contextlib
out = io.StringIO()
with contextlib.redirect_stdout(out):
    ap.main(root)
ok(out.getvalue().count('patched') == 3 and 'created' in out.getvalue(), 'installer patches 3 files + makes quit.json')
ok(json.load(open(os.path.join(root, 'jarvis', 'quit.json'))) == {'start': '', 'reasons': []}, 'quit.json starts empty')
with open(os.path.join(root, 'jarvis', 'quit.json'), 'w') as f:
    json.dump({'start': '2026-11-15', 'reasons': ['Producing with a clear head']}, f)
snap = {f: open(os.path.join(root, f)).read() for f in ('jarvis/jarvis.py', 'selftest.py', '.gitignore', 'jarvis/quit.json')}
out = io.StringIO()
with contextlib.redirect_stdout(out):
    ap.main(root)
ok(out.getvalue().count('already patched') == 3 and 'kept' in out.getvalue(), 'second run says already + keeps quit.json')
ok(all(open(os.path.join(root, f)).read() == t for f, t in snap.items()), 'second run changes nothing')
ok(os.path.exists(os.path.join(root, 'jarvis', 'jarvis.py.bak-nov15-craving')), 'backup made')
ok('jarvis/quit.json' in open(os.path.join(root, '.gitignore')).read(), 'quit.json gitignored')
# a changed live file -> STOP, nothing written
root2 = tempfile.mkdtemp()
shutil.copytree(os.path.join(root, 'jarvis'), os.path.join(root2, 'jarvis'))
for f in ('selftest.py', '.gitignore'):
    shutil.copy2(os.path.join(RIG, f), os.path.join(root2, f))
shutil.copy2(os.path.join(RIG, 'jarvis', 'jarvis.py'), os.path.join(root2, 'jarvis', 'jarvis.py'))
jp = os.path.join(root2, 'jarvis', 'jarvis.py')
t = open(jp).read().replace("    if r:\n        return {'action': 'reminder', 'value': r}\n", "    if r: return {'action': 'reminder', 'value': r}\n")
open(jp, 'w').write(t)
snap2 = {f: open(os.path.join(root2, f)).read() for f in ('jarvis/jarvis.py', 'selftest.py', '.gitignore')}
try:
    with contextlib.redirect_stdout(io.StringIO()):
        ap.main(root2)
    stopped = False
except SystemExit as e:
    stopped = 'STOP' in str(e)
ok(stopped and all(open(os.path.join(root2, f)).read() == x for f, x in snap2.items()), 'changed file -> STOP, nothing written')

# the patched Jarvis, end to end (fake rig, fake say)
sys.path.insert(0, os.path.join(root, 'jarvis'))
for m in ('jarvis', 'craving', 'reminders', 'brief'):
    sys.modules.pop(m, None)
real = subprocess.Popen
spoke = []
subprocess.Popen = lambda *a, **k: spoke.append(a[0]) or FakeProc(a[0])
try:
    j = importlib.import_module('jarvis')
    cv = sys.modules['craving']
    cv._now = lambda: clock.t
    s = j.settings()
    route = {"Jarvis, I'm craving": 'craving', 'I really want to smoke': 'craving', 'how many days clean': 'craving',
             "I'm craving pizza": None, 'calm': 'breathe', 'chill': 'breathe', 'breathe': 'breathe',
             'purple': 'color', 'log 268.4': 'weight', 'remind me at 9 to breathe': 'reminder', 'yes': None}
    for t, want in route.items():
        got = (j.by_rules(t) or {}).get('action')
        ok(got == want, 'patched route %r -> %r (want %r)' % (t, got, want))
    ok(len(j.understand_all("Jarvis, I'm craving, help me", s)) == 1, "'craving, help me' is one thing, not help too")
    rc = []
    r = j.handle("Jarvis, I'm craving", s, rig=lambda p: rc.append(p), confirm=False)
    ok('Producing with a clear head' in r and rc == [], 'patched handle: reason spoken, lights untouched: %r' % r)
    ok(any(a[0] == '/usr/bin/say' for a in spoke), 'patched handle starts the Mac count')
    ok(j.by_rules('yes')['action'] == 'craving', 'yes routes to the calm look right after')
    r = j.handle('yes', s, rig=lambda p: rc.append(p), confirm=False, voice_yes=True)
    ok(rc == ['breathe'] and 'Calm look on' in r, 'patched handle: yes -> breathe')
    ok("'I'm craving'" in j.do({'action': 'help'}, s, lambda p: None), 'help line mentions it')
    ok('craving' not in j.ACTIONS, 'the model can never pick craving (not in the allowlist)')
finally:
    subprocess.Popen = real

# old Jarvis tests still pass on the patched copy (network blocked in the child too)
blk = tempfile.mkdtemp()
open(os.path.join(blk, 'sitecustomize.py'), 'w').write(
    "import socket\ndef _n(*a, **k):\n    raise OSError('network blocked in test')\nsocket.socket.connect = _n\nsocket.create_connection = _n\n")
env = dict(os.environ, PYTHONPATH=blk)
t = subprocess.run([sys.executable, 'test_jarvis.py'], cwd=os.path.join(root, 'jarvis'), capture_output=True, text=True, env=env, timeout=170)
ok(t.returncode == 0, 'old test_jarvis passes on patched copy: %s' % (t.stdout + t.stderr)[-400:])
ok([digest(p) for p in live] == before, 'live files untouched')

print('ALL %d PASSED' % N[0] if not BAD else '%d FAILED of %d' % (len(BAD), N[0]))
sys.exit(1 if BAD else 0)
