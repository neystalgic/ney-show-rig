#!/usr/bin/env python3
# =============================================================================
# RIG SELF-TEST (Nov 14) -- "is every automation actually working?"
#
# Michael: "I want everything tested in this phase... I don't want to waste time with broken loops."
# One command, safe to run any time: it NEVER changes the room (no looks, no heads, no plugs, no hub
# restarts, no food/weight rows). It only runs the offline test suites and asks things "are you OK?".
#
#   python3 selftest.py            -> report on screen, exit 1 if anything FAILED
#   python3 selftest.py --quiet    -> just the summary line
# Results also go to bridge/outbox/selftest.json + selftest.txt (Rig Health shows the summary).
# Runs on the Mac (rig_control does it daily + on "selftest" through the Claude bridge).
# =============================================================================
import csv, datetime as dt, filecmp, json, os, subprocess, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'bridge', 'outbox')
DESK = os.path.expanduser('~/Desktop')
RESULTS = []


def res(group, name, level, detail):
    """level: ok | warn | fail | skip"""
    RESULTS.append({'group': group, 'name': name, 'level': level, 'detail': str(detail)[:300]})


def token():
    try:
        return open(os.path.join(HERE, 'rig_control.token')).read().strip()
    except OSError:
        return ''


def get(url, timeout=6.0, data=None):
    req = urllib.request.Request(url, data=data, headers={'X-Token': token()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def mac_base():
    """rig_control directly when we're on the Mac, else through the Pi front door."""
    for base in ('http://127.0.0.1:7040', 'http://192.168.1.80:7041'):
        try:
            if get(base + '/status', 3)[0] == 200:
                return base
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- 1. offline test suites
SUITES = [  # (name, test file, [(live file, the copy that test exercises)])
    ('Jarvis (commands, food, saved meals)', 'jarvis/test_jarvis.py', []),
    ('Pi brain (schedule failover, front door)', 'pi/brain/test_brain.py', []),
    ('Pi calm looks (covers when the Mac sleeps)', 'pi/brain/test_looks.py', []),
    ('Health Report v2', 'away/health-report-v2/test_health_report.py',
     [('body_log.py', 'away/health-report-v2/body_log.py'), ('body.html', 'away/health-report-v2/body.html')]),
    ('Weekly health sheet', 'away/health-weekly/test_health_weekly.py',
     [('health_weekly.py', 'away/health-weekly/health_weekly.py')]),
    ('Health Sync endpoint + setup sheet', 'away/health-sync-setup/test_health_sync_setup.py', []),
    ('Saved meals (deployed copy)', 'away/jarvis-meals/test_jarvis.py', []),   # jarvis.py moved on: see the briefing line
    ('Jarvis morning briefing', 'away/jarvis-brief/test_brief.py',
     [('jarvis/brief.py', 'away/jarvis-brief/brief.py')]),   # jarvis.py moved on (reminders patch): test_jarvis covers it
    ('Jarvis reminders + timers', 'away/jarvis-reminders/test_reminders.py',   # Nov 15: reminders + timers
     [('jarvis/reminders.py', 'away/jarvis-reminders/reminders.py')]),
]


def suites():
    for name, test, pairs in SUITES:
        path = os.path.join(HERE, test)
        if not os.path.exists(path):
            res('Code tests', name, 'warn', 'test file missing: ' + test)
            continue
        drift = [live for live, copy in pairs if os.path.exists(os.path.join(HERE, copy))
                 and not filecmp.cmp(os.path.join(HERE, live), os.path.join(HERE, copy), shallow=False)]
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, path], cwd=os.path.dirname(path), capture_output=True, text=True,
                               timeout=240)
            ok = p.returncode == 0
            outl = (p.stdout + p.stderr).strip().splitlines()
            bad = [l for l in outl if l.startswith(('FAIL', 'Traceback', 'AssertionError')) or ' FAIL' in l[:12]]
            tail = (outl or [''])[-1] if ok else ' | '.join((bad or outl[-3:])[:4])
        except subprocess.TimeoutExpired:
            ok, tail = False, 'timed out after 240 s'
        detail = '%s (%.0f s)' % (tail, time.time() - t0)
        if ok and drift:
            res('Code tests', name, 'warn', 'tests pass, but the LIVE %s differs from the tested copy' % ', '.join(drift))
        else:
            res('Code tests', name, 'ok' if ok else 'fail', detail)
    # the away loop's gate (shift hours, caps, idle) -- pure logic, fake clock
    try:
        sys.path.insert(0, os.path.join(HERE, 'away'))
        import importlib, tempfile
        b = importlib.import_module('budget_check')
        keep = (b.LEDGER, b.busy, b.now, b.budget)
        try:
            b.LEDGER = os.path.join(tempfile.mkdtemp(), 'runs.csv')
            b.busy = lambda m: ''
            b.write([])
            real = keep[3]()
            b.budget = lambda: real
            spans = [[int(x) for x in w.split('-')] for w in real['WORK_HOURS'].split(',') if w.strip()]
            h = spans[0][0]
            b.now = lambda: dt.datetime(2030, 1, 7, h, 3)
            r = b.start()
            res('Code tests', 'Away loop gate (budget_check)', 'ok' if r.startswith('GO') else 'fail',
                'work-hours run at %02d:03 -> %s' % (h, r))
        finally:
            b.LEDGER, b.busy, b.now, b.budget = keep
    except Exception as e:
        res('Code tests', 'Away loop gate (budget_check)', 'fail', '%s: %s' % (e.__class__.__name__, e))


# ---------------------------------------------------------------- 2. live services (read-only)
def services():
    try:
        st = json.loads(get('http://192.168.1.80:7060/status', 4)[1])
        res('Live', 'Pi DMX node', 'fail' if st.get('error') else 'ok', st.get('error') or st.get('output', '')[:60])
    except Exception as e:
        res('Live', 'Pi DMX node', 'fail', 'not answering (%s)' % e.__class__.__name__)
    try:
        code = get('http://192.168.1.80:7041/status', 6)[0]
        res('Live', 'Pi front door (phone shortcuts)', 'ok' if code == 200 else 'fail', 'HTTP %d' % code)
    except Exception as e:
        res('Live', 'Pi front door (phone shortcuts)', 'fail', 'not answering (%s)' % e.__class__.__name__)
    base = mac_base()
    if not base:
        res('Live', 'Rig control (Mac)', 'fail', 'not answering directly or through the Pi')
        return
    res('Live', 'Rig control (Mac)', 'ok', 'answering')
    try:
        rows = json.loads(get(base + '/health.json', 8)[1])
        rows = rows.get('checks', rows) if isinstance(rows, dict) else rows
        for r in rows or []:
            lvl = {'ok': 'ok', 'idle': 'ok', 'warn': 'warn', 'down': 'fail'}.get(r.get('level'), 'warn')
            if r.get('name') in ('Self-test',):
                continue
            res('Rig Health page', r.get('name'), lvl, r.get('detail'))
    except Exception as e:
        res('Live', 'Rig Health page', 'fail', '%s' % e.__class__.__name__)
    try:
        b = json.loads(get(base + '/body.json', 10)[1])
        need = {'deficit', 'today', 'weekly', 'activity'}
        miss = need - set(b)
        res('Live', 'Health Report data (/body.json)', 'fail' if miss else 'ok',
            'missing ' + ', '.join(sorted(miss)) if miss else 'v2 fields present')
    except Exception as e:
        res('Live', 'Health Report data (/body.json)', 'fail', e.__class__.__name__)
    try:   # read-only question: Jarvis must answer without logging or changing anything
        q = urllib.parse.urlencode({'text': 'what are my usuals'})
        code, body = get(base + '/ask?' + q, 40)
        txt = body.decode('utf8', 'replace')
        res('Live', 'Jarvis answers (/ask)', 'ok' if code == 200 and txt.strip() else 'fail', txt[:80])
    except Exception as e:
        res('Live', 'Jarvis answers (/ask)', 'fail', e.__class__.__name__)


# ---------------------------------------------------------------- 3. automations (are they really running?)
def _age_h(path):
    try:
        return (time.time() - os.path.getmtime(path)) / 3600.0
    except OSError:
        return None


def automations():
    now = time.time()
    # away loop: last run closed OK, and not silent during a work shift while Michael is away
    try:
        rows = list(csv.DictReader(open(os.path.join(HERE, 'away', 'runs.csv'))))
        real = [r for r in rows if 'manual gate check' not in r.get('task', '')]
        last = real[-1] if real else None
        bad = [r for r in real[-3:] if r.get('result') in ('failed', 'blocked')]
        if not last:
            res('Automations', 'Away loop', 'warn', 'no runs logged yet')
        else:
            started = dt.datetime.fromisoformat(last['start'])
            sys.path.insert(0, os.path.join(HERE, 'away'))
            import budget_check as bc
            b = bc.budget()
            t = bc.now()
            spans = [[int(x) for x in w.split('-')] for w in b['WORK_HOURS'].split(',') if w.strip()]
            in_shift = any(a <= t.hour < z for a, z in spans)
            idle = ''
            try:
                idle = bc.busy(int(b['IDLE_MINUTES']))
            except Exception:
                pass
            gap_h = (t - started).total_seconds() / 3600.0
            open_run = not last.get('end') and gap_h > 1
            if bad or open_run:
                res('Automations', 'Away loop', 'fail', 'recent failed/unfinished run: %s' % (bad or [last])[-1])
            elif b['PAUSE'].lower().startswith('y'):
                res('Automations', 'Away loop', 'warn', 'paused in Rig Usage Budget.txt')
            elif in_shift and not idle and gap_h > 2.2:
                res('Automations', 'Away loop', 'fail', 'silent: in a work shift, Michael idle, last run %.1f h ago' % gap_h)
            else:
                res('Automations', 'Away loop', 'ok', 'last run %s (%s) -- %s' % (last['start'], last.get('result') or 'running',
                                                                                last.get('task', '')[:50]))
    except Exception as e:
        res('Automations', 'Away loop', 'fail', '%s: %s' % (e.__class__.__name__, e))
    # idle watcher feeding the loop's gate
    try:
        d = json.load(open(os.path.join(HERE, 'bridge', 'idle.json')))
        age = now - d['at']
        res('Automations', 'Idle watcher (for the away loop)', 'ok' if age < 300 else 'fail', 'updated %.0f s ago' % age)
    except Exception as e:
        res('Automations', 'Idle watcher (for the away loop)', 'fail', e.__class__.__name__)
    # hourly backup to GitHub
    try:
        ct = int(subprocess.run(['git', '-C', HERE, 'log', '-1', '--format=%ct', 'origin/main'],
                                capture_output=True, text=True, timeout=15).stdout.strip())
        age = (now - ct) / 3600.0
        res('Automations', 'Hourly backup (GitHub)', 'ok' if age < 3 else 'fail', 'last push %.1f h ago' % age)
    except Exception as e:
        res('Automations', 'Hourly backup (GitHub)', 'warn', 'could not read (%s)' % e.__class__.__name__)
    # light schedule actually fires every day
    a = _age_h(os.path.join(HERE, 'light_schedule_done.json'))
    res('Automations', 'Light schedule (wind-down / night / sunrise)',
        'ok' if a is not None and a < 26 else ('warn' if a is None else 'fail'),
        'last fired %.1f h ago' % a if a is not None else 'no record yet')
    # Sunday weekly sheet
    wk = os.path.join(DESK, 'Health Report Weekly.csv')
    a = _age_h(wk)
    today = dt.date.today()
    last_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    due = dt.datetime.combine(last_sun, dt.time(20, 30)).timestamp()
    if a is None:
        res('Automations', 'Weekly health sheet (Sun 8 pm)', 'warn' if now < due + 3600 or today < dt.date(2026, 11, 16)
            else 'fail', 'not written yet (first run Sun Nov 15, 8 pm)')
    else:
        stale = os.path.getmtime(wk) < due - 3600 and now > due
        res('Automations', 'Weekly health sheet (Sun 8 pm)', 'fail' if stale else 'ok', 'written %.0f h ago' % a)
    # morning Health Sync from the iPhone
    try:
        rows = list(csv.DictReader(open(os.path.join(DESK, 'Activity Log.csv'))))
        days = {r.get('Date') for r in rows}
        yday = (today - dt.timedelta(days=1)).isoformat()
        if yday in days:
            res('Automations', 'Health Sync (iPhone, at alarm)', 'ok', 'yesterday synced')
        else:
            res('Automations', 'Health Sync (iPhone, at alarm)', 'fail' if days else 'warn',
                'no row for %s' % yday + ('' if days else ' -- shortcut not set up yet'))
    except OSError:
        res('Automations', 'Health Sync (iPhone, at alarm)', 'warn', 'no Activity Log yet -- shortcut not set up')


# ---------------------------------------------------------------- report
def reminders_check():                              # Nov 15: reminders + timers -- read-only
    path = os.path.join(HERE, 'jarvis', 'reminders.json')
    if not os.path.exists(path):
        return res('Automations', 'Jarvis reminders', 'ok', 'none set')
    try:
        with open(path) as f:
            items = json.load(f).get('items', [])
        late = [i for i in items if time.time() - time.mktime(time.strptime(i['due'][:19], '%Y-%m-%dT%H:%M:%S')) > 600]
    except Exception as e:
        return res('Automations', 'Jarvis reminders', 'fail', 'reminders.json unreadable (%s)' % e.__class__.__name__)
    if late:
        return res('Automations', 'Jarvis reminders', 'warn',
                   '%d overdue by 10+ min -- is the jarvis-reminders thread in rig_control running?' % len(late))
    return res('Automations', 'Jarvis reminders', 'ok', '%d set, none overdue' % len(items))


def main():
    t0 = time.time()
    suites()
    services()
    automations()
    reminders_check()
    n = {k: sum(1 for r in RESULTS if r['level'] == k) for k in ('ok', 'warn', 'fail')}
    summary = 'SELFTEST %s: %d ok, %d warn, %d FAIL (%.0f s)' % (time.strftime('%Y-%m-%d %H:%M'), n['ok'], n['warn'],
                                                               n['fail'], time.time() - t0)
    lines = [summary, '']
    for g in dict.fromkeys(r['group'] for r in RESULTS):
        lines.append(g)
        for r in RESULTS:
            if r['group'] == g:
                lines.append('  %-5s %-42s %s' % (r['level'].upper(), r['name'], r['detail']))
        lines.append('')
    text = '\n'.join(lines)
    try:
        os.makedirs(OUT, exist_ok=True)
        json.dump({'summary': summary, 'counts': n, 'at': time.time(), 'results': RESULTS},
                  open(os.path.join(OUT, 'selftest.json'), 'w'), indent=1)
        open(os.path.join(OUT, 'selftest.txt'), 'w').write(text + '\n')
    except OSError:
        pass
    print(summary if '--quiet' in sys.argv else text)
    return 1 if n['fail'] else 0


if __name__ == '__main__':
    sys.exit(main())
