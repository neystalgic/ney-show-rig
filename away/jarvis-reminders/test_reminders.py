#!/usr/bin/env python3
"""Offline tests for Jarvis reminders + timers (away loop J2, Nov 15). Fake clock, temp files, sockets blocked.
   python3 away/jarvis-reminders/test_reminders.py        -> last line 'ALL n PASSED' or FAIL lines, exit 1"""
import ast, datetime as dt, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)


def _no_net(*a, **k):
    raise RuntimeError('network blocked in tests')
socket.socket.connect = _no_net
socket.create_connection = _no_net

import reminders as r

N, BAD = [0], []
def ok(cond, what):
    N[0] += 1
    if not cond:
        BAD.append(what)
        print('FAIL', what)

T = tempfile.mkdtemp()
P = os.path.join(T, 'r.json')
D = dt.datetime
EVE = D(2026, 11, 15, 20, 15)          # Sunday evening

# ---------- 1. understanding
cases = {
    'remind me at 9 to take my meds': dict(op='add', text='take your meds', clock=[9, 0, None]),
    'Jarvis, remind me in 20 minutes to check the oven': dict(op='add', text='check the oven', secs=1200),
    'remind me in an hour and a half to stretch': dict(op='add', secs=5400, text='stretch'),
    'remind me in half an hour to call back': dict(secs=1800, text='call back'),
    'remind me tomorrow at 7 to call my mum': dict(text='call your mum', clock=[7, 0, None], day='tomorrow'),
    'remind me to buy 2 eggs at 6pm': dict(text='buy 2 eggs', clock=[6, 0, 'pm']),
    'remind me at 9:30 p.m. that I have a call': dict(text='you have a call', clock=[9, 30, 'pm']),
    'remind me tonight at 11 to lock the door': dict(day='tonight', clock=[11, 0, None]),
    'remind me at noon to eat': dict(clock=[12, 0, 'pm'], text='eat'),
    'remind me to log my weight 270 at 8 am': dict(op='add', clock=[8, 0, 'am']),
    'remind me to take the bins out and lock up in 5 minutes': dict(text='take the bins out and lock up', secs=300),
    'set a reminder for 21:00 to stretch': dict(clock=[21, 0, None], text='stretch'),
    '10 minute timer': dict(op='timer', secs=600, label=None),
    'set a timer for 10 minutes': dict(op='timer', secs=600),
    'start a 25 minute pasta timer': dict(op='timer', secs=1500, label='pasta'),
    'set a timer for 10 minutes for the pasta': dict(op='timer', secs=600, label='pasta'),
    'timer for 90 seconds': dict(op='timer', secs=90),
    'set a timer for one hour': dict(op='timer', secs=3600),
    'timer': dict(op='timer', secs=None),
    'what are my reminders': dict(op='list'), 'what are my timers': dict(op='list'),
    'how long left on my timer': dict(op='list'), 'do i have any reminders': dict(op='list'),
    "cancel the 9 o'clock": dict(op='cancel', clock=[9, 0, None]),
    'cancel my timer': dict(op='cancel', kind='timer'), 'cancel all reminders': dict(op='cancel', all=True),
    'cancel the meds reminder': dict(op='cancel', kind='reminder', words=['meds']),
    'clear my timers': dict(op='cancel', kind='timer', all=True),
}
for said, want in cases.items():
    got = r.parse(said) or {}
    ok(all(got.get(k) == v for k, v in want.items()), 'parse %r -> %s (want %s)' % (said, got, want))
for said in ['movie night', 'log 268.4', 'I ate a banana', 'stop the stars', 'turn the uv off', 'goodnight',
             'no dimming until 1 am', 'status', 'blue at 40 percent', '', 'jarvis']:
    ok(r.parse(said) is None, 'not a reminder: %r -> %s' % (said, r.parse(said)))

# ---------- 2. times
def res(clock, now, day=None):
    return r.resolve(tuple(clock), now, day)
ok(res([9, 0, None], EVE) == D(2026, 11, 15, 21, 0), 'at 9 in the evening = 9 pm')
ok(res([9, 0, None], D(2026, 11, 15, 8, 0)) == D(2026, 11, 15, 9, 0), 'at 9 at 8 am = 9 am')
ok(res([9, 0, None], D(2026, 11, 15, 22, 0)) == D(2026, 11, 16, 9, 0), 'at 9 at 10 pm = 9 am tomorrow')
ok(res([7, 0, None], EVE, 'tomorrow') == D(2026, 11, 16, 7, 0), 'tomorrow at 7 = 7 am')
ok(res([3, 0, None], EVE, 'tomorrow') == D(2026, 11, 16, 15, 0), 'tomorrow at 3 = 3 pm')
ok(res([11, 0, None], EVE, 'tonight') == D(2026, 11, 15, 23, 0), 'tonight at 11 = 11 pm')
ok(res([2, 0, None], D(2026, 11, 15, 10, 0)) == D(2026, 11, 15, 14, 0), 'at 2 in the morning-time day = 2 pm')
ok(res([1, 0, None], D(2026, 11, 16, 0, 30)) == D(2026, 11, 16, 1, 0), 'at 1 said at 00:30 = 1 am')
ok(res([12, 0, 'am'], EVE) == D(2026, 11, 16, 0, 0), 'midnight = next 00:00')
ok(res([21, 30, None], EVE) == D(2026, 11, 15, 21, 30), '21:30 24-hour')
ok(res([8, 0, 'pm'], EVE) == D(2026, 11, 16, 20, 0), '8 pm already passed -> tomorrow')
ok(r.say_time(D(2026, 11, 15, 21, 0), EVE) == '9 pm' and r.say_time(D(2026, 11, 16, 7, 30), EVE) == 'tomorrow at 7:30 am'
   and r.say_time(D(2026, 11, 16, 0, 0), EVE) == 'midnight' and r.say_time(D(2026, 11, 18, 12, 0), EVE) == 'Wednesday at noon',
   'say_time')
ok(r.duration('an hour and a half') == 5400 and r.duration('2 hours 15 minutes') == 8100 and r.duration('ninety seconds') == 90
   and r.duration('nothing') is None, 'duration')
ok(r.say_duration(5400) == '1 hour and 30 minutes' and r.say_duration(600, True) == '10 minute', 'say_duration')

# ---------- 3. doing (fake clock, temp file)
H = lambda said, now=EVE: r.handle(r.parse(said), now, P)
ok(H('remind me at 9 to take my meds') == "Okay, I'll remind you at 9 pm to take your meds.", 'add at 9')
ok(H('remind me in 20 minutes to check the oven') == "Okay, I'll remind you in 20 minutes (8:35 pm) to check the oven.", 'add in 20')
ok(H('remind me tomorrow at 7 to call my mum') == "Okay, I'll remind you tomorrow at 7 am to call your mum.", 'add tomorrow')
ok(H('10 minute timer') == '10 minute timer, starting now. It ends at 8:25 pm.', 'timer')
ok(H('set a timer for 10 minutes for the pasta').startswith('Pasta timer for 10 minutes'), 'labelled timer')
ok('How long' in H('timer') and 'When should I remind you' in H('remind me to stretch'), 'asks when missing')
ok('5 seconds to 24 hours' in H('set a timer for 30 hours'), 'timer cap')
ok('two weeks' in r.handle({'op': 'add', 'text': 'x', 'secs': 20 * 86400}, EVE, P), '14 day cap')
ok(r.handle(None, EVE, P) == r.HOWTO and r.handle({'op': 'rm -rf'}, EVE, P) == r.HOWTO, 'bad intent -> how-to')
lst = H('what are my reminders')
ok(lst.startswith('3 reminders: 8:35 pm, check the oven; 9 pm, take your meds; tomorrow at 7 am, call your mum.')
   and '2 timers' in lst and 'pasta timer, 10 minutes left' in lst, 'list: %s' % lst)
ok(len(json.load(open(P))['items']) == 5, 'survives a restart: file has 5 items')
ok(H("cancel the 9 o'clock") == 'Cancelled your reminder for 9 pm: take your meds.', 'cancel by time')
ok(H('cancel the pasta timer') == 'Cancelled the pasta timer.', 'cancel timer by label')
ok(H('cancel my timer') == 'Cancelled the 10 minute timer.', 'cancel the only timer')
ok(H('cancel my timer') == "You don't have any timers to cancel.", 'no timers left')
ok('2 that match' in H('cancel my reminder'), 'ambiguous cancel asks which')
ok(H('cancel the mum reminder') == 'Cancelled your reminder for tomorrow at 7 am: call your mum.', 'cancel by word')
ok(H('cancel the dentist reminder').startswith("I couldn't find that one. You have: 8:35 pm, check the oven"), 'cancel miss')
ok(H("cancel the 4 o'clock").startswith("I couldn't find"), 'cancel wrong time')
H('remind me at 10 to sleep'); H('remind me at 11 to sleep more')
ok(H('cancel all reminders') == 'Cancelled all 3 reminders.' and H('what are my reminders') == 'No reminders or timers right now.', 'cancel all')
for k in range(r.MAX_ITEMS):
    r.handle({'op': 'timer', 'secs': 60 + k}, EVE, P)
ok("that's my limit" in H('10 minute timer'), 'max items')
r.save([], P)

# ---------- 4. speaking: once, on time vs missed while asleep
H('remind me in 20 minutes to check the oven'); H('10 minute timer'); H('remind me at 9 to take my meds')
ok(r.pop_due(EVE + dt.timedelta(minutes=5), P) == '', 'nothing due yet')
ok(r.pop_due(EVE + dt.timedelta(minutes=10, seconds=10), P) == 'Your 10 minute timer is done.', 'timer done on time')
ok(r.pop_due(EVE + dt.timedelta(minutes=11), P) == '', 'said once only')
asleep = r.pop_due(D(2026, 11, 16, 7, 0), P)
ok(asleep == 'While the Mac was asleep: Earlier, at 8:35 pm: check the oven. Earlier, at 9 pm: take your meds.', 'missed: %s' % asleep)
ok(r.load(P) == [], 'all spoken -> list empty')
H('remind me in 1 minute to breathe')
said = []
ok(r.tick(EVE + dt.timedelta(minutes=1, seconds=5), P, lambda t, v: said.append((t, v))) == 'Reminder: breathe.'
   and said == [('Reminder: breathe.', 'Moira')], 'tick speaks with Moira: %s' % said)
open(P, 'w').write('{broken')
ok(r.load(P) == [] and r.pop_due(EVE, P) == '', 'broken file -> empty, no crash')
naps = []
r.loop(every=15, path=P, speak=lambda t, v: 1 / 0, sleep=naps.append, rounds=2)
H('remind me in 1 minute to x')
r.loop(every=15, path=P, speak=lambda t, v: 1 / 0, sleep=naps.append, rounds=1)   # say fails -> logged, loop lives
ok(naps == [15, 15, 15], 'loop never dies, sleeps 15 s')
calls = []
real = subprocess.Popen
subprocess.Popen = lambda *a, **k: calls.append((a, k))
r._say('hi', 'Moira')
subprocess.Popen = real
ok(calls and calls[0][0][0] == ['/usr/bin/say', '-v', 'Moira', 'hi'] and calls[0][1].get('start_new_session'), 'say never blocks')

# ---------- 5. safety: no network, no lights, small imports
src = open(os.path.join(HERE, 'reminders.py')).read()
mods = {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
ok(mods <= {'datetime', 'json', 'os', 're', 'subprocess', 'threading', 'time'}, 'imports: %s' % mods)
ok(not any(x in src for x in ('urllib', 'socket', '192.168', '7040', 'rig(', 'token')), 'no network / rig / token in reminders.py')

# ---------- 6. the installer, on the live files AND on the morning-briefing copies (whichever is deployed first)
sys.path.insert(0, HERE)
import apply_patches as ap
bases = [('live', os.path.join(RIG, 'jarvis', 'jarvis.py'), os.path.join(RIG, 'selftest.py')),
         ('after J1 brief', os.path.join(RIG, 'away', 'jarvis-brief', 'jarvis.py'), os.path.join(RIG, 'away', 'jarvis-brief', 'selftest.py'))]
CHECK = r'''
import sys, os, json, datetime as dt
sys.path.insert(0, os.getcwd())
import jarvis as j, reminders as r
s = dict(j.DEFAULTS); calls = []
rig = lambda p: (calls.append(p), json.dumps({'look': 'x'}))[1]
a = lambda t: (j.by_rules(t) or {}).get('action')
out = {
 'rem': a('remind me to log my weight 270 at 8 am'), 'timers': a('what are my timers'), 'weight': a('log 268.4'),
 'movie': a('movie night'), 'show': a('show mode'), 'later': a('no dimming until midnight'), 'cancel': a("cancel the 9 o'clock"),
 'one': j.understand_all('remind me in 10 minutes to check the oven and take the bins out', s),
 'said': j.handle('remind me in 10 minutes to check the oven and take the bins out', s, rig=rig),
 'help': j.do({'action': 'help'}, s, rig), 'model': j.do({'action': 'reminder', 'value': None}, s, rig),
 'calls': calls, 'items': [i['text'] for i in r.load()],
}
print(json.dumps(out))
'''
for name, jv, st in bases:
    if not os.path.exists(jv):
        ok(False, 'missing base ' + jv); continue
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, 'jarvis'))
    shutil.copy(jv, os.path.join(root, 'jarvis', 'jarvis.py'))
    for extra in ('meals.json', 'jarvis.json', 'test_jarvis.py'):
        if os.path.exists(os.path.join(RIG, 'jarvis', extra)):
            shutil.copy(os.path.join(RIG, 'jarvis', extra), os.path.join(root, 'jarvis', extra))
    if 'brief' in name:
        shutil.copy(os.path.join(RIG, 'away', 'jarvis-brief', 'brief.py'), os.path.join(root, 'jarvis', 'brief.py'))
    for f in os.listdir(RIG):                        # the small top-level modules the old tests import (no configs)
        if f.endswith('.py'):
            shutil.copy(os.path.join(RIG, f), os.path.join(root, f))
    shutil.copy(st, os.path.join(root, 'selftest.py'))
    shutil.copy(os.path.join(RIG, '.gitignore'), os.path.join(root, '.gitignore'))
    ap.main(root)
    ap.main(root)                                    # twice: second run changes nothing
    jp = open(os.path.join(root, 'jarvis', 'jarvis.py')).read()
    ok(jp.count(ap.MARK) == 1 and jp.count("if a == 'reminder':") == 1, '%s: jarvis patched once' % name)
    ok('reminders and timers' in jp, '%s: help line mentions reminders' % name)
    rc = open(os.path.join(root, 'rig_control.py')).read()
    ok(rc.count("name='jarvis-reminders'") == 1 and rc.index('jarvis-reminders') > rc.index("name='jarvis-warm'"), '%s: rig thread added' % name)
    compile(rc, 'rig_control.py', 'exec')
    gi = open(os.path.join(root, '.gitignore')).read().split('\n')
    ok('jarvis/reminders.json' in gi and gi.count('jarvis/reminders.json') == 1, '%s: gitignore' % name)
    if ap.MARK not in open(os.path.join(RIG, 'rig_control.py')).read():     # (after deploy the live files are already patched)
        ok(os.path.exists(os.path.join(root, 'rig_control.py.bak-nov15-reminders')), '%s: backup made' % name)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    p = subprocess.run([sys.executable, '-c', CHECK], cwd=os.path.join(root, 'jarvis'), capture_output=True, text=True, env=env)
    try:
        o = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        ok(False, '%s: patched jarvis check crashed: %s' % (name, (p.stderr or p.stdout)[-400:])); continue
    ok(o['rem'] == 'reminder' and o['timers'] == 'reminder' and o['cancel'] == 'reminder', '%s: reminder phrases route' % name)
    ok(o['weight'] == 'weight' and o['movie'] == 'movienight' and o['show'] == 'show' and o['later'] == 'later', '%s: old phrases unchanged %s' % (name, o))
    ok(len(o['one']) == 1 and o['one'][0]['action'] == 'reminder', '%s: "X and Y" stays one reminder' % name)
    ok(o['said'].startswith("Okay, I'll remind you in 10 minutes") and o['calls'] == [] and
       o['items'] == ['check the oven and take the bins out'], '%s: handle -> reminder saved, rig untouched: %s' % (name, o['said']))
    ok(o['model'] == r.HOWTO, '%s: empty model value -> how-to' % name)
    if os.path.exists(os.path.join(root, 'jarvis', 'test_jarvis.py')):
        t = subprocess.run([sys.executable, 'test_jarvis.py'], cwd=os.path.join(root, 'jarvis'), capture_output=True, text=True, env=env, timeout=200)
        ok(t.returncode == 0, '%s: old Jarvis tests pass on the patched copy: %s' % (name, (t.stdout + t.stderr)[-300:]))
    # selftest: suite listed + read-only check
    sp = os.path.join(root, 'selftest.py')
    stx = open(sp).read()
    ok("away/jarvis-reminders/test_reminders.py" in stx and stx.count('    reminders_check()\n') == 1, '%s: selftest suite + check' % name)
    spec = importlib.util.spec_from_file_location('st_' + name.replace(' ', '_'), sp)
    st_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(st_mod)
    st_mod.HERE = root
    rj = os.path.join(root, 'jarvis', 'reminders.json')
    levels = []
    for content in (None, {'items': [{'due': (D.now() + dt.timedelta(hours=1)).isoformat(timespec='seconds')}]},
                    {'items': [{'due': (D.now() - dt.timedelta(hours=1)).isoformat(timespec='seconds')}]}, '{bad'):
        if content is None:
            os.path.exists(rj) and os.rename(rj, rj + '.gone')
        else:
            open(rj, 'w').write(content if isinstance(content, str) else json.dumps(content))
        del st_mod.RESULTS[:]
        st_mod.reminders_check()
        levels.append(st_mod.RESULTS[-1]['level'])
    ok(levels == ['ok', 'ok', 'warn', 'fail'], '%s: selftest reminders check levels %s' % (name, levels))

# refuses (and writes nothing) when a live file changed under it
root = tempfile.mkdtemp(); os.makedirs(os.path.join(root, 'jarvis'))
shutil.copy(os.path.join(RIG, 'jarvis', 'jarvis.py'), os.path.join(root, 'jarvis', 'jarvis.py'))
open(os.path.join(root, 'rig_control.py'), 'w').write('print("someone changed me")\n')
shutil.copy(os.path.join(RIG, 'selftest.py'), os.path.join(root, 'selftest.py'))
shutil.copy(os.path.join(RIG, '.gitignore'), os.path.join(root, '.gitignore'))
before = open(os.path.join(root, 'jarvis', 'jarvis.py')).read()
try:
    ap.main(root); stopped = False
except SystemExit as e:
    stopped = 'STOP' in str(e)
ok(stopped and open(os.path.join(root, 'jarvis', 'jarvis.py')).read() == before
   and not os.path.exists(os.path.join(root, 'jarvis', 'reminders.py')), 'patcher stops cleanly, writes nothing')

print('FAIL %d of %d' % (len(BAD), N[0]) if BAD else 'ALL %d PASSED' % N[0])
sys.exit(1 if BAD else 0)
