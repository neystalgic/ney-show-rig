#!/usr/bin/env python3
# =============================================================================
# Offline test for the Health weekly spreadsheet (Nov 14). Fake CSVs in a temp folder -- never touches the
# real Desktop logs, never opens a network connection (sockets are blocked while it runs).
#   python3 test_health_weekly.py
# Uses the Health Report v2 copy of body_log (away/health-report-v2/body_log.py), which the sheet needs.
# =============================================================================
import csv, datetime as dt, hashlib, importlib.util, os, shutil, socket, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))


def _no_network(*a, **k):
    raise RuntimeError('test tried to use the network')
socket.socket = _no_network
socket.create_connection = _no_network


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def point_at(m, folder):
    m.WEIGHT, m.FOOD, m.ACTIVITY = (os.path.join(folder, n) for n in ('Weight Log.csv', 'Food Log.csv', 'Activity Log.csv'))


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


fails = []
def check(name, ok, got=None):
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else '  (got %r)' % (got,)))
    if not ok:
        fails.append(name)


T = dt.date.today()
M = T - dt.timedelta(days=T.weekday())                  # this week's Monday
iso = lambda d: d.isoformat()
live_before = sha(os.path.join(ROOT, 'body_log.py'))
tmp = tempfile.mkdtemp(prefix='health-weekly-test-')
try:
    v2 = load(os.path.join(ROOT, 'away', 'health-report-v2', 'body_log.py'), 'body_log')
    point_at(v2, tmp)
    sys.modules['body_log'] = v2
    hw = load(os.path.join(HERE, 'health_weekly.py'), 'health_weekly')

    # --- empty logs ---
    check('empty logs -> no rows', hw.rows() == [])
    p, n = hw.write()
    check('empty logs -> header-only sheet', n == 0 and open(p).read().strip() == ','.join(hw.COLUMNS))
    check('sheet sits next to the logs (not the real Desktop)', p == os.path.join(tmp, 'Health Report Weekly.csv'), p)

    # --- fake history: an old weigh-in, two full weeks, today ---
    A = [M - dt.timedelta(days=14 - i) for i in range(7)]       # week A: Watch sends resting kcal
    B = [M - dt.timedelta(days=7 - i) for i in range(7)]        # week B: no resting kcal -> estimate
    old = M - dt.timedelta(days=35)
    with open(v2.WEIGHT, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Date', 'Weight (lb)', 'Notes'])
        w.writerow([iso(old), 275, ''])
        for d in A: w.writerow([iso(d), 270, ''])
        for d in B: w.writerow([iso(d), 268, ''])
    with open(v2.FOOD, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Date', 'Time', 'Item', 'Calories', 'Protein (g)', 'Source'])
        for d in A: w.writerow([iso(d), '12:00', 'meal', 2500, 150, 'test'])
        for d in B: w.writerow([iso(d), '12:00', 'meal', 2400, 160, 'test'])
        w.writerow([iso(B[2]), '21:00', 'mystery snack', '', '', 'test'])   # partial day: left out of deficit
        w.writerow([iso(T), '09:00', 'breakfast', 2000, 100, 'test'])
    with open(v2.ACTIVITY, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Date', 'Active kcal', 'Resting kcal', 'Steps', 'Exercise min', 'Sleep h', 'Resting HR', 'HRV ms', 'VO2max'])
        for d in A: w.writerow([iso(d), 800, 2100, 9000, 30, 7.5, 60, 45, 38])
        for d in B: w.writerow([iso(d), 900, '', 10000, 30, 7.0, 58, 50, 38])

    r = hw.rows()
    weeks = [x['Week of'] for x in r]
    check('4 weeks, oldest first', weeks == [iso(old - dt.timedelta(days=old.weekday())), iso(M - dt.timedelta(days=14)),
                                            iso(M - dt.timedelta(days=7)), iso(M)], weeks)
    o, a, b, c = r if len(r) == 4 else ({},) * 4
    check('old week: weight only', o.get('Avg weight (lb)') == 275 and o.get('Days logged') == 0 and o.get('Change (lb)') == '', o)
    check('week A: change vs old weigh-in = -5.0', a.get('Change (lb)') == -5.0, a.get('Change (lb)'))
    check('week A: food', (a.get('Avg kcal eaten'), a.get('Avg protein (g)'), a.get('Days logged')) == (2500, 150, 7), a)
    check('week A: burn 800 + 2100', (a.get('Avg active kcal'), a.get('Avg resting kcal'), a.get('Avg burn kcal')) == (800, 2100, 2900), a)
    check('week A: deficit 400, no estimates', (a.get('Avg deficit'), a.get('Est. resting days')) == (400, 0), a)
    check('week A: steps / HR / HRV / sleep', (a.get('Avg steps'), a.get('Avg resting HR'), a.get('Avg HRV ms'), a.get('Avg sleep h')) == (9000, 60.0, 45, 7.5), a)
    est = [900 + v2.resting_estimate(268, d) for d in B if d != B[2]]
    exp_burn = int(round(sum(est) / 6))
    exp_def = int(round(sum(e - 2400 for e in est) / 6))
    check('week B: change -2.0', b.get('Change (lb)') == -2.0, b.get('Change (lb)'))
    check('week B: no Watch resting kcal -> blank', b.get('Avg resting kcal') == '', b.get('Avg resting kcal'))
    check('week B: burn uses the estimate, partial day left out', b.get('Avg burn kcal') == exp_burn, (b.get('Avg burn kcal'), exp_burn))
    check('week B: deficit matches body_log', b.get('Avg deficit') == exp_def, (b.get('Avg deficit'), exp_def))
    check('week B: 6 estimated days', b.get('Est. resting days') == 6, b.get('Est. resting days'))
    check('week B: HRV / sleep', (b.get('Avg HRV ms'), b.get('Avg sleep h')) == (50, 7.0), b)
    check('this week marked so far', c.get('Note') == 'so far' and c.get('Avg kcal eaten') == 2000, c)
    check('this week: no weigh-in -> blank change', c.get('Change (lb)') == '' and c.get('Avg weight (lb)') == '', c)
    check('only this week says so far', [x['Note'] for x in r[:3]] == ['', '', ''])

    # --- the file itself ---
    p, n = hw.write()
    with open(p, newline='') as f:
        back = list(csv.DictReader(f))
    check('write: 4 rows, header = COLUMNS', n == 4 and len(back) == 4 and list(back[0].keys()) == hw.COLUMNS)
    check('write: values round-trip', back[1]['Avg deficit'] == '400' and back[2]['Change (lb)'] == '-2.0', back[1:3])
    check('write: no .tmp left behind', not os.path.exists(p + '.tmp'))
    check('write: logs untouched', sum(1 for _ in open(v2.FOOD)) == 1 + 7 + 7 + 2)

    # --- Sunday timing ---
    def at(path, when):
        ts = when.timestamp(); os.utime(path, (ts, ts))
    sun = dt.datetime(2026, 11, 15, 21, 0)                   # a Sunday
    check('2026-11-15 is a Sunday', sun.weekday() == 6)
    miss = os.path.join(tmp, 'nope.csv')
    check('due: missing file', hw._due(sun, miss))
    at(p, dt.datetime(2026, 11, 15, 19, 0)); check('due: Sunday 9 pm, written 7 pm', hw._due(sun, p))
    at(p, dt.datetime(2026, 11, 15, 20, 10)); check('not due: Sunday 9 pm, written 8:10 pm', not hw._due(sun, p))
    at(p, dt.datetime(2026, 11, 9, 8, 0)); check('not due: Sunday 7 pm, written Monday', not hw._due(sun.replace(hour=19), p))
    at(p, dt.datetime(2026, 11, 15, 20, 30)); check('not due: Wednesday after a Sunday write', not hw._due(dt.datetime(2026, 11, 18, 12), p))
    at(p, dt.datetime(2026, 11, 14, 12, 0)); check('due: Monday after a missed Sunday', hw._due(dt.datetime(2026, 11, 16, 9), p))

    # --- tick never raises ---
    msgs = []
    at(p, dt.datetime(2026, 11, 1, 12, 0))
    check('tick writes when due', hw.tick(sun, p, msgs.append) and 'wrote 4 weeks' in msgs[-1], msgs)
    at(p, dt.datetime(2026, 11, 15, 20, 30))                # as if that write happened at 8:30 pm Sunday
    check('tick quiet when not due', hw.tick(sun, p, msgs.append) is False)
    real = hw.body_log.summary
    hw.body_log.summary = lambda days=60: 1 / 0
    at(p, dt.datetime(2026, 11, 1, 12, 0))
    check('tick survives a broken log', hw.tick(sun, p, msgs.append) is False and 'skipped' in msgs[-1], msgs[-1:])
    hw.body_log.summary = real

    # --- v1 body_log gives a clear message ---
    v1 = load(os.path.join(ROOT, 'body_log.py'), 'body_log_v1')
    hw.body_log = v1 if not hasattr(v1, 'resting_estimate') else hw.body_log
    if hw.body_log is v1:
        try:
            hw.rows(); check('v1 body_log -> clear error', False, 'no error')
        except RuntimeError as e:
            check('v1 body_log -> clear error', 'Health Report v2' in str(e), str(e))
    else:
        print('SKIP v1 check (live body_log is already v2)')
    hw.body_log = v2

    # --- Sunday thread: one daemon thread, started once ---
    made = []
    class FakeThread:
        def __init__(self, target=None, name=None, daemon=None): made.append((name, daemon)); self.t = target
        def start(self): made.append('started')
    real_thread = hw.threading.Thread
    hw.threading.Thread = FakeThread
    hw.start_sunday_writer()
    hw.threading.Thread = real_thread
    check('start_sunday_writer: one daemon thread', made == [('health-weekly', True), 'started'], made)

    check('live body_log.py unchanged', sha(os.path.join(ROOT, 'body_log.py')) == live_before)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n%d failed' % len(fails) if fails else '\nALL PASSED')
sys.exit(1 if fails else 0)
