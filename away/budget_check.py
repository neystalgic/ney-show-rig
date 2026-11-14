#!/usr/bin/env python3
"""Gate for the Rig away loop. Usage:
   python3 away/budget_check.py start          -> prints GO or SKIP <reason>; GO records the run
   python3 away/budget_check.py end ok|failed|blocked "<task>"
Reads 'Rig Usage Budget.txt', keeps a ledger in away/runs.csv. No network, no secrets."""
import csv, os, sys, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUDGET = os.path.join(ROOT, 'Rig Usage Budget.txt')
LEDGER = os.path.join(HERE, 'runs.csv')
DEF = {'PAUSE': 'no', 'MAX_RUNS_PER_DAY': '4', 'MAX_RUNS_PER_WEEK': '20',
       'STOP_AFTER_FAILED_RUNS': '2', 'QUIET_HOURS': '01-11', 'IDLE_MINUTES': '20', 'WORK_HOURS': '15-20', 'OFF_HOURS_MAX_RUNS': '3'}

def budget():
    b = dict(DEF)
    try:
        for line in open(BUDGET):
            line = line.split('#')[0]
            if '=' in line:
                k, v = line.split('=', 1)
                b[k.strip().upper()] = v.strip()
    except OSError:
        pass
    return b

def rows():
    try:
        return list(csv.DictReader(open(LEDGER)))
    except OSError:
        return []

def write(rs):
    with open(LEDGER, 'w', newline='') as f:
        w = csv.DictWriter(f, ['start', 'end', 'result', 'task'])
        w.writeheader(); w.writerows(rs)

def now():
    # local time of the Mac's timezone (Los Angeles); the VM may be UTC
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('America/Los_Angeles')).replace(tzinfo=None)
    except Exception:
        return dt.datetime.now()

def busy(mins, clock=None):
    """Why Michael looks active right now, or '' if he's idle.
    Active = touched the Mac's keyboard/mouse, edited code, or committed in the last `mins` minutes."""
    import json, subprocess, time
    clock = clock or time.time()
    try:   # written every minute by rig_control's idle-watch thread
        d = json.load(open(os.path.join(ROOT, 'bridge', 'idle.json')))
        if clock - d['at'] < 300 and d['hid_idle_s'] < mins * 60:
            return 'Michael is at the Mac (idle %d min)' % (d['hid_idle_s'] // 60)
    except (OSError, ValueError, KeyError):
        pass
    newest = 0
    for sub in ('', 'jarvis', 'pi/brain', 'pi'):
        try:
            for f in os.listdir(os.path.join(ROOT, sub)):
                if f.endswith(('.py', '.html', '.applescript')):
                    newest = max(newest, os.path.getmtime(os.path.join(ROOT, sub, f)))
        except OSError:
            pass
    if clock - newest < mins * 60:
        return 'project code edited %d min ago' % ((clock - newest) // 60)
    try:
        ct = int(subprocess.run(['git', '-C', ROOT, 'log', '-1', '--format=%ct', '--invert-grep', '--grep=^Away loop'],
                                capture_output=True, text=True, timeout=10).stdout.strip() or 0)
        if clock - ct < mins * 60:
            return 'commit %d min ago' % ((clock - ct) // 60)
    except Exception:
        pass
    return ''

def start():
    b, rs, t = budget(), rows(), now()
    if b['PAUSE'].lower().startswith('y'):
        return 'SKIP paused in Rig Usage Budget.txt'
    try:
        a, z = [int(x) for x in b['QUIET_HOURS'].split('-')]
        if a <= t.hour < z:
            return 'SKIP quiet hours %s' % b['QUIET_HOURS']
    except ValueError:
        pass
    force = os.path.join(ROOT, 'bridge', 'away_force_once')   # Michael-approved test run: skip the idle gate once
    forced = False
    try:
        forced = open(force).read().strip() == 'go'
        if forced:
            open(force, 'w').write('used %s' % t.isoformat(timespec='minutes'))
    except OSError:
        pass
    why = '' if forced else busy(int(b['IDLE_MINUTES']))
    if why:
        return 'SKIP Michael is active: %s' % why
    starts = [dt.datetime.fromisoformat(r['start']) for r in rs if r.get('start')]
    day = sum(1 for s in starts if s.date() == t.date())
    week = sum(1 for s in starts if t - s < dt.timedelta(days=7))
    try:   # Michael's away block is the main shift; idle runs outside it can't eat its slots
        wa, wz = [int(x) for x in b['WORK_HOURS'].split('-')]
        if not (wa <= t.hour < wz):
            off = sum(1 for s in starts if s.date() == t.date() and not (wa <= s.hour < wz))
            if off >= int(b['OFF_HOURS_MAX_RUNS']):
                return 'SKIP saving runs for work hours %s (off-hours cap %s reached)' % (b['WORK_HOURS'], b['OFF_HOURS_MAX_RUNS'])
    except ValueError:
        pass
    if day >= int(b['MAX_RUNS_PER_DAY']):
        return 'SKIP daily cap %s reached' % b['MAX_RUNS_PER_DAY']
    if week >= int(b['MAX_RUNS_PER_WEEK']):
        return 'SKIP weekly cap %s reached' % b['MAX_RUNS_PER_WEEK']
    n = int(b['STOP_AFTER_FAILED_RUNS'])
    last = [r['result'] for r in rs if r.get('result')][-n:]
    if n and len(last) == n and all(x in ('failed', 'blocked', '') for x in last):
        return 'SKIP last %d runs failed or were blocked -- needs Michael (reset: add an ok line or clear away/runs.csv)' % n
    if rs and not rs[-1].get('end'):
        rs[-1]['end'] = t.isoformat(timespec='minutes'); rs[-1]['result'] = 'failed'   # previous run never closed
    rs.append({'start': t.isoformat(timespec='minutes'), 'end': '', 'result': '', 'task': ''})
    write(rs)
    return 'GO run %d today, %d this week' % (day + 1, week + 1)

def end(result, task):
    rs = rows()
    if rs and not rs[-1].get('end'):
        rs[-1].update(end=now().isoformat(timespec='minutes'), result=result, task=task[:120])
        write(rs)
    return 'recorded %s' % result

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'end':
        print(end(sys.argv[2] if len(sys.argv) > 2 else 'ok', sys.argv[3] if len(sys.argv) > 3 else ''))
    else:
        print(start())
