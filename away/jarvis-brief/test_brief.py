"""Offline tests for the Jarvis morning briefing (away/jarvis-brief). No network, no lights, no Mac voice.
python3 test_brief.py   -> prints PASS/FAIL lines and 'N/N passed'."""
import datetime as dt, json, os, shutil, socket, subprocess, sys, tempfile, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)


def _no_net(*a, **k):
    raise AssertionError('network call attempted')
socket.socket.connect = _no_net                      # any real network use fails the test run
socket.create_connection = _no_net

import brief, jarvis as j, apply_rig_patch as arp

RESULTS = []


def check(name, cond, info=''):
    RESULTS.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  -> ' + str(info)[:300]))


NOW = dt.datetime(2026, 11, 16, 7, 5)                 # Monday 7:05 am, alarm just went off
Y = '2026-11-15'
S = {'voice': 'Moira', 'brief_mac': True, 'protein_goal': None}


def fake_summary(**over):
    s = {'activity': {Y: {'Sleep h': 7.5, 'Resting HR': 58, 'Active kcal': 700, 'Resting kcal': 2100}},
         'hr_check': {'date': Y, 'hr': 58, 'avg7': 60.4, 'diff': -2.4},
         'weight_avg7': {'2026-11-08': 270.0, '2026-11-12': 269.0, Y: 268.6},
         'latest': (Y, 268.4),
         'food': {Y: {'calories': 2150, 'protein': 165, 'meals': 3, 'unknown': 0}},
         'deficit': {Y: {'burn': 2800, 'eaten': 2150, 'deficit': 650, 'resting_est': False, 'partial': False}}}
    s.update(over)
    return s


# --- 1. the full brief ------------------------------------------------------------------------------------------
t = brief.build(fake_summary(), S, NOW)
check('greets in the morning', t.startswith('Good morning, Michael.'), t)
check('sleep in hours + minutes', 'You slept 7 hours 30 minutes.' in t, t)
check('resting HR vs the week', 'Resting heart rate 58, 2.4 under your weekly average.' in t, t)
check('weight trend over the week', 'Weight trend is down 1.4 pounds this week, now 268.6.' in t, t)
check('eaten vs burned + deficit + protein', 'Yesterday you ate 2150 and burned 2800, a 650 calorie deficit and 165 grams of protein.' in t, t)
check('on-target nudge', t.endswith('Right on target. Keep it rolling.'), t)
check('about 20 seconds (<= 70 words)', len(t.split()) <= brief.MAX_WORDS, len(t.split()))
check('no preachy words', not any(w in t.lower() for w in ('should', 'must', 'bad', 'failed', 'too much')), t)

# --- 2. edge cases ----------------------------------------------------------------------------------------------
e = brief.build({}, S, NOW)
check('no data at all -> friendly setup line', e.startswith("I don't have any health numbers yet"), e)
t = brief.build(fake_summary(activity={Y: {'Sleep h': 5.2}}), S, NOW)
check('short night -> go-easy nudge (beats the deficit line)', 'You slept 5 hours 12 minutes.' in t and 'Short night' in t, t)
t = brief.build(fake_summary(activity={Y: {'Sleep h': 7}}), S, NOW)
check('whole hours say no minutes', 'You slept 7 hours.' in t, t)
over = {Y: {'burn': 2600, 'eaten': 2900, 'deficit': -300, 'resting_est': False, 'partial': False}}
t = brief.build(fake_summary(deficit=over, food={Y: {'calories': 2900, 'protein': 120, 'meals': 4, 'unknown': 0}}), S, NOW)
check('over day: "calories over" + kind fresh-start line', '300 calories over' in t and 'Fresh start today' in t, t)
small = {Y: {'burn': 2600, 'eaten': 2400, 'deficit': 200, 'resting_est': True, 'partial': True}}
t = brief.build(fake_summary(deficit=small), S, NOW)
check('estimated resting burn + partial day are said', 'estimated resting burn' in t and 'not counting a meal without numbers' in t, t)
check('small deficit -> encouraging', 'Every bit counts' in t, t)
t = brief.build(fake_summary(food={}, deficit={}), S, NOW)
check('no food yesterday is said plainly', 'No food logged yesterday.' in t and 'Have a good one.' in t, t)
t = brief.build(fake_summary(deficit={}), S, NOW)
check('food but no Watch burn yet', 'Yesterday you ate 2150 calories and 165 grams of protein. No burn numbers' in t, t)
t = brief.build(fake_summary(hr_check={'date': Y, 'hr': 61, 'avg7': None, 'diff': None}), S, NOW)
check('first HR reading (no average yet)', 'Resting heart rate 61.' in t, t)
t = brief.build(fake_summary(hr_check={'date': Y, 'hr': 60, 'avg7': 60.3, 'diff': -0.3}), S, NOW)
check('HR on average', 'right on your weekly average' in t, t)
t = brief.build(fake_summary(weight_avg7={'2026-11-08': 268.7, Y: 268.6}), S, NOW)
check('weight steady', 'Weight is holding steady around 268.6.' in t, t)
t = brief.build(fake_summary(weight_avg7={'2026-11-14': 269.0, Y: 268.6}), S, NOW)
check('under a week of weights -> last weigh-in', 'Last weigh-in 268.4 pounds.' in t, t)
t = brief.build(fake_summary(weight_avg7={'2026-11-08': 267.0, Y: 268.0}), S, NOW)
check('weight up 1 pound (singular)', 'up 1 pound this week' in t, t)
t = brief.build(fake_summary(food={Y: {'calories': 2150, 'protein': 110, 'meals': 3, 'unknown': 0}}),
                dict(S, protein_goal=180), NOW)
check('protein goal set + low -> gentle protein line', 'A bit more protein today would round it out.' in t, t)
t = brief.build(fake_summary(food={Y: {'calories': 2150, 'protein': 110, 'meals': 3, 'unknown': 0}}), S, NOW)
check('no protein goal -> never nags about protein', 'protein today' not in t, t)
t = brief.build(fake_summary(), S, dt.datetime(2026, 11, 16, 15, 0))
check('afternoon greeting', t.startswith("Here's your brief, Michael."), t)
t = brief.build(fake_summary(activity={'2026-11-10': {'Sleep h': 8}}), S, NOW)
check('old sleep is not read as last night', 'You slept' not in t, t)

# --- 3. after the Health Sync -----------------------------------------------------------------------------------
st = os.path.join(tempfile.mkdtemp(), 'spoken.txt')
said = []
spk = lambda text, voice: said.append((text, voice))
row = {'Date': Y, 'Steps': 9000, 'Sleep h': 7.5}
check('empty row -> nothing added', brief.after_sync({'Date': Y, 'Steps': None}, S, NOW, spk, st, fake_summary()) == '' and not said)
r = brief.after_sync(row, S, NOW, spk, st, fake_summary())
check('sync reply carries the brief', r.startswith(' Good morning, Michael.'), r)
check('Mac speaks it once, Moira', len(said) == 1 and said[0][1] == 'Moira' and said[0][0] == r.strip(), said)
brief.after_sync(row, S, NOW + dt.timedelta(minutes=3), spk, st, fake_summary())
check('second sync the same morning stays quiet on the Mac', len(said) == 1, said)
st2 = os.path.join(tempfile.mkdtemp(), 'spoken.txt')
r = brief.after_sync(row, S, dt.datetime(2026, 11, 16, 14, 0), spk, st2, fake_summary())
check('afternoon sync: text yes, Mac voice no', r and len(said) == 1, said)
brief.after_sync(row, S, dt.datetime(2026, 11, 16, 4, 30), spk, st2, fake_summary())
check('before 5 am: Mac stays quiet', len(said) == 1, said)
brief.after_sync(row, dict(S, brief_mac=False), NOW, spk, st2, fake_summary())
check('brief_mac false: Mac never speaks', len(said) == 1, said)
brief.after_sync(row, S, NOW + dt.timedelta(days=1), spk, st, fake_summary())
check('next morning speaks again', len(said) == 2, said)
real_popen, calls = subprocess.Popen, []
subprocess.Popen = lambda *a, **k: calls.append((a, k))
brief._say('hi', 'Moira')
subprocess.Popen = real_popen
check('voice is a non-blocking say (own session)', calls and calls[0][0][0] == ['/usr/bin/say', '-v', 'Moira', 'hi']
      and calls[0][1].get('start_new_session'), calls)

# --- 4. real body_log on temp CSVs (read-only import of the live module) -------------------------------------------
sys.path.insert(0, RIG)
import body_log as BL
d = tempfile.mkdtemp()
keep = (BL.WEIGHT, BL.FOOD, BL.ACTIVITY)
BL.WEIGHT, BL.FOOD, BL.ACTIVITY = (os.path.join(d, n) for n in ('w.csv', 'f.csv', 'a.csv'))
try:
    today = dt.date.today()
    with open(BL.WEIGHT, 'w') as f:
        f.write('Date,Weight (lb)\n' + ''.join('%s,%s\n' % (today - dt.timedelta(days=k), 270 - (10 - k) * 0.2)
                                             for k in range(10, 0, -1)))
    yd = (today - dt.timedelta(days=1)).isoformat()
    with open(BL.FOOD, 'w') as f:
        f.write('Date,Time,Item,Calories,Protein (g),Source\n%s,12:00,bowl,1200,80,Jarvis\n%s,19:00,steak,900,70,Jarvis\n' % (yd, yd))
    with open(BL.ACTIVITY, 'w') as f:
        hdr = ['Date'] + list(BL.FIELDS.values())
        f.write(','.join(hdr) + '\n')
        for k in range(8, 0, -1):
            dd = (today - dt.timedelta(days=k)).isoformat()
            vals = {'Active kcal': 650, 'Resting kcal': 2150, 'Sleep h': 7.25, 'Resting HR': 60 if k > 1 else 57}
            f.write(','.join([dd] + [str(vals.get(c, '')) for c in hdr[1:]]) + '\n')
    real = brief.build(BL.summary(), S, dt.datetime.combine(today, dt.time(7, 0)))
    check('real summary: sleep, HR, weight, deficit all present',
          'You slept 7 hours 15 minutes.' in real and 'Resting heart rate 57, 3 under' in real and 'Weight trend is down' in real
          and 'ate 2100 and burned 2800, a 700 calorie deficit and 150 grams of protein' in real, real)
    check('real summary: <= 70 words', len(real.split()) <= brief.MAX_WORDS, len(real.split()))
finally:
    BL.WEIGHT, BL.FOOD, BL.ACTIVITY = keep

# --- 5. Jarvis copy: "brief me" ----------------------------------------------------------------------------------
for said_text in ('brief me', 'Jarvis, brief me', 'morning briefing', 'give me my daily brief', 'catch me up',
                  'how did I sleep', 'health report'):
    check('"%s" -> brief' % said_text, (j.by_rules(said_text) or {}).get('action') == 'brief', j.by_rules(said_text))
for said_text, want in (('good morning', 'morning'), ('how am I doing', 'today'), ('status', 'status'),
                        ('goodnight', 'night'), ('I ate a banana', 'food'), ('what can you do', 'help')):
    check('"%s" still -> %s' % (said_text, want), (j.by_rules(said_text) or {}).get('action') == want, j.by_rules(said_text))
check('brief is on the allowlist (model fallback)', 'brief' in j.ACTIONS and '- brief:' in j.SYSTEM)
fake = lambda content: (lambda url, body, t: {'message': {'content': json.dumps(content)}})
check('model may pick brief', (j.by_model('tell me about my health', dict(j.DEFAULTS), fake({'action': 'brief'})) or {}).get('action') == 'brief')
keep_b = j._brief
j._brief = lambda: type('B', (), {'brief': staticmethod(lambda: 'Good morning, Michael. Test.')})
check('do(brief) speaks the brief', j.do({'action': 'brief'}, dict(j.DEFAULTS), rig=lambda p: '{}') == 'Good morning, Michael. Test.')
j._brief = lambda: (_ for _ in ()).throw(OSError('no logs'))
check('do(brief) with unreadable logs -> calm message', 'OSError' in j.do({'action': 'brief'}, dict(j.DEFAULTS), rig=lambda p: '{}'))
j._brief = keep_b
check('help mentions brief me', 'brief me' in j.do({'action': 'help'}, dict(j.DEFAULTS), rig=lambda p: '{}'))

# old Jarvis suites still pass against this copy (run in a temp copy so nothing real is touched)
for suite in ('jarvis/test_jarvis.py', 'away/jarvis-meals/test_jarvis.py'):
    tmp = tempfile.mkdtemp()
    jd = os.path.join(tmp, os.path.dirname(suite))     # same layout as the real suite (its paths count dirs up)
    os.makedirs(jd)
    for fn in ('jarvis.py', 'brief.py'):
        shutil.copy(os.path.join(HERE, fn), jd)
    shutil.copy(os.path.join(RIG, suite), os.path.join(jd, 'test_jarvis.py'))
    for fn in ('body_log.py', 'light_schedule.py'):
        shutil.copy(os.path.join(RIG, fn), tmp)
    p = subprocess.run([sys.executable, 'test_jarvis.py'], cwd=jd, capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, HOME=tmp))
    check('old suite %s passes on the new jarvis.py' % suite, p.returncode == 0, (p.stdout + p.stderr)[-300:])

# --- 6. rig_control patch ---------------------------------------------------------------------------------------
live = open(os.path.join(RIG, 'rig_control.py')).read()
if arp.MARK in live:                     # already deployed (Nov 14): check the LIVE file instead of re-patching it
    check('deployed: live rig_control has the brief patch exactly once', live.count(arp.MARK) == 1)
    compile(live, 'rig_control.py', 'exec')
    check('deployed: live rig_control compiles', True)
    check('deployed: patch is idempotent on live', arp.patch(live) == (live, 'already patched'))
else:
    new, what = arp.patch(live)
    check('patch applies to the live rig_control.py text', what == 'patched' and new.count(arp.MARK) == 1)
    compile(new, 'rig_control.py', 'exec')
    check('patched rig_control compiles', True)
    check('patch is idempotent', arp.patch(new) == (new, 'already patched'))
    try:
        arp.patch(live.replace(arp.ANCHOR, ''))
        check('changed rig_control -> patch refuses', False)
    except SystemExit as ex:
        check('changed rig_control -> patch refuses', 'STOP' in str(ex))
    check('shipped rig_control.py copy == patch(live)', open(os.path.join(HERE, 'rig_control.py')).read() == new)


def run_handler(brief_mod):
    """Runs the patched lines of the /body/activity handler with a fake request and a fake brief module."""
    src = 'def handler(self, day, got, row, HERE):\n' + textwrap.indent(textwrap.dedent(arp.PATCH), '    ')
    ns = {'os': os, 'sys': sys}
    exec(src, ns)
    sys.modules['brief'] = brief_mod
    try:
        fake_self = type('R', (), {'reply': lambda self, code, text: (code, text)})()
        return ns['handler'](fake_self, Y, '9000 Steps', {'Date': Y, 'Steps': 9000}, '/nowhere')
    finally:
        sys.modules.pop('brief', None)


ok_mod = type(sys)('brief'); ok_mod.after_sync = lambda row: ' Good morning, Michael.'
bad_mod = type(sys)('brief'); bad_mod.after_sync = lambda row: 1 / 0
check('sync reply + brief', run_handler(ok_mod) == (200, 'Health synced for %s: 9000 Steps. Good morning, Michael.' % Y))
check('brief crash -> sync reply unchanged', run_handler(bad_mod) == (200, 'Health synced for %s: 9000 Steps.' % Y))

# --- 7. hygiene -------------------------------------------------------------------------------------------------
txt = ''.join(open(os.path.join(HERE, f)).read() for f in ('brief.py', 'DEPLOY.txt') if os.path.exists(os.path.join(HERE, f)))
check('no addresses, tokens or secrets in the new files', not any(x in txt for x in ('192.168.', 'X-Token:', 'hue_config.json', '100.')), '')
check('DEPLOY.txt exists and ends with the selftest', os.path.exists(os.path.join(HERE, 'DEPLOY.txt'))
      and 'selftest.py --quiet' in open(os.path.join(HERE, 'DEPLOY.txt')).read())
check('selftest copy runs the briefing suite', "away/jarvis-brief/test_brief.py" in open(os.path.join(HERE, 'selftest.py')).read())

print('%d/%d passed' % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
