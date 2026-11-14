#!/usr/bin/env python3
# Offline tests for cal_core.py + PLAN.txt (away loop, Nov 14). No network: sockets are blocked.
#   cd ~/"Touchdesigner Designs/Hue Rig/away/calendar" && python3 test_cal_core.py
import datetime as dt, json, os, re, socket, sys

def _no_net(*a, **k):
    raise RuntimeError('network blocked in tests')
socket.socket = _no_net
socket.create_connection = _no_net

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cal_core as C

TZ = dt.timezone(dt.timedelta(hours=-5))          # a fixed zone so results never depend on the machine
ok = bad = 0
def check(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL %s\n   got:  %r\n   want: %r' % (name, got, want))

def ev(title, s, e, **extra):
    d = {'summary': title, 'start': {'dateTime': s}, 'end': {'dateTime': e}}
    d.update(extra)
    return d

# A fake events.list 'items' reply (singleEvents=true), Sat Nov 14 - Fri Nov 20, 2026.
ITEMS = [
    ev('Work', '2026-11-14T15:00:00-05:00', '2026-11-14T20:00:00-05:00'),
    ev('Dentist', '2026-11-14T10:30:00-05:00', '2026-11-14T11:15:00-05:00'),
    {'summary': 'Mom birthday', 'start': {'date': '2026-11-14'}, 'end': {'date': '2026-11-15'}},
    ev('Workout', '2026-11-15T08:00:00-05:00', '2026-11-15T09:00:00-05:00'),
    ev('Work - camp', '2026-11-16T20:30:00Z', '2026-11-17T01:15:00Z'),          # 3:30-8:15 pm local, given in UTC
    ev('Cancelled thing', '2026-11-14T12:00:00-05:00', '2026-11-14T13:00:00-05:00', status='cancelled'),
    ev('Declined party', '2026-11-14T21:00:00-05:00', '2026-11-14T23:00:00-05:00',
       attendees=[{'self': True, 'responseStatus': 'declined'}]),
    {'summary': 'Broken', 'start': {'dateTime': 'not a time'}, 'end': {}},
    'garbage',
]
E = C.load_events(ITEMS, TZ)
NOW = dt.datetime(2026, 11, 14, 9, 0, tzinfo=TZ)

# --- loading ---
check('load skips cancelled/declined/broken', [x['title'] for x in E],
      ['Mom birthday', 'Dentist', 'Work', 'Workout', 'Work - camp'])
check('Z time converted to local', C.speak_time(E[-1]['start']), '3:30 pm')
check('all-day flagged', E[0]['all_day'], True)
check('empty reply', C.load_events(None, TZ), [])

# --- what counts as a shift ---
check('Work is a shift', C.is_shift(E[2]), True)
check('Work - camp is a shift', C.is_shift(E[4]), True)
check('Workout is NOT a shift', C.is_shift(E[3]), False)
check('all-day never a shift', C.is_shift({'title': 'Work conference', 'all_day': True}), False)
check('custom words', C.is_shift({'title': 'Camp Kids', 'all_day': False}, ('camp',)), True)

# --- spoken times ---
t = lambda h, m: dt.datetime(2026, 11, 14, h, m, tzinfo=TZ)
check('noon', C.speak_time(t(12, 0)), 'noon')
check('midnight', C.speak_time(t(0, 0)), 'midnight')
check('3:30 pm', C.speak_time(t(15, 30)), '3:30 pm')
check('9 am', C.speak_time(t(9, 0)), '9 am')

# --- "what's my day" ---
check('today', C.say_day(E, NOW.date(), NOW),
      'You have 3 things today: Mom birthday (all day); Dentist, 10:30 am to 11:15 am; Work, 3 pm to 8 pm.')
check('tomorrow', C.say_day(E, dt.date(2026, 11, 15), NOW), 'You have 1 thing tomorrow: Workout, 8 am to 9 am.')
check('weekday, empty', C.say_day(E, dt.date(2026, 11, 18), NOW), 'Nothing on your calendar on Wednesday.')
many = C.load_events([ev('E%d' % i, '2026-11-19T%02d:00:00-05:00' % i, '2026-11-19T%02d:30:00-05:00' % i)
                      for i in range(8, 15)], TZ)
check('more than 5 -> "and N more"', C.say_day(many, dt.date(2026, 11, 19), NOW).endswith('; and 2 more.'), True)

# --- "when do I work" ---
check('later today', C.say_next_shift(E, NOW), 'You work today, 3 pm to 8 pm.')
check('on shift now', C.say_next_shift(E, t(16, 0)), "You're on shift now, until 8 pm.")
check('next is Monday', C.say_next_shift(E, t(21, 0)), 'Your next shift is Monday, 3:30 pm to 8:15 pm.')
check('tomorrow', C.say_next_shift(E, dt.datetime(2026, 11, 15, 12, 0, tzinfo=TZ)), 'You work tomorrow, 3:30 pm to 8:15 pm.')
check('none in 7 days', C.say_next_shift(E, dt.datetime(2026, 11, 17, 9, 0, tzinfo=TZ)),
      'No shifts on your calendar in the next 7 days.')

# --- the away loop's snapshot: times only, no titles ---
snap = C.shift_snapshot(E, NOW)
blob = json.dumps(snap)
check('snapshot has 2 shifts', len(snap['shifts']), 2)
check('snapshot carries no titles', any(w in blob for w in ('Dentist', 'Work', 'Mom', 'camp')), False)

# --- WORK_HOURS for budget_check ---
check('shift day', C.work_hours_for(snap, NOW), '01-09,15-20')
mon = dt.datetime(2026, 11, 16, 9, 0, tzinfo=TZ)
check('odd minutes round outward', C.work_hours_for(C.shift_snapshot(E, mon), mon), '01-09,15-21')
check('day off = sleep only', C.work_hours_for(snap, dt.datetime(2026, 11, 15, 9, 0, tzinfo=TZ)), '01-09')
mk = lambda s, e: {'fetched': NOW.isoformat(), 'shifts': [[s, e]]}
check('morning shift joins sleep', C.work_hours_for(mk('2026-11-14T07:00-05:00', '2026-11-14T12:00-05:00'), NOW), '01-12')
check('overnight shift clipped to today', C.work_hours_for(mk('2026-11-14T22:00-05:00', '2026-11-15T02:00-05:00'), NOW),
      '01-09,22-24')
check('stale snapshot -> fixed hours', C.work_hours_for(snap, NOW + dt.timedelta(hours=40)), '01-09,15-20')
check('future-dated snapshot -> fixed hours', C.work_hours_for(snap, NOW - dt.timedelta(hours=3)), '01-09,15-20')
check('missing -> fixed hours', C.work_hours_for(None, NOW), '01-09,15-20')
check('garbage -> fixed hours', C.work_hours_for({'fetched': 'x', 'shifts': 1}, NOW), '01-09,15-20')
check('custom fallback', C.work_hours_for({}, NOW, fallback='15-20'), '15-20')
# the string must parse exactly the way budget_check.py parses WORK_HOURS today
spans = [[int(x) for x in w.split('-')] for w in C.work_hours_for(snap, NOW).split(',') if w.strip()]
work = lambda h: any(a <= h < z for a, z in spans)
check('budget_check parse', [h for h in range(24) if work(h)], list(range(1, 9)) + list(range(15, 20)))

# --- PLAN.txt covers what the backlog line asked for, and holds no secrets ---
plan = open(os.path.join(HERE, 'PLAN.txt')).read()
for need in ('installed app', 'service account', 'calendar.events.readonly', '~/.ney_secrets', 'never git',
             "what's my day", 'when do I work', 'WORK_HOURS', 'EFFORT', 'In production', '7 days'):
    check('plan mentions %r' % need, need.lower() in plan.lower(), True)
check('plan has no key-like strings', re.search(r'(AIza[0-9A-Za-z_-]{20,}|GOCSPX-|ya29\.|1//0[0-9A-Za-z_-]{20,})', plan), None)
check('no .md files here', [f for f in os.listdir(HERE) if f.endswith('.md')], [])

print('%d/%d passed' % (ok, ok + bad))
sys.exit(1 if bad else 0)
