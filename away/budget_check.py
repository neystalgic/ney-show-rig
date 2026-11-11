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
       'STOP_AFTER_FAILED_RUNS': '2', 'QUIET_HOURS': '01-11'}

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
    starts = [dt.datetime.fromisoformat(r['start']) for r in rs if r.get('start')]
    day = sum(1 for s in starts if s.date() == t.date())
    week = sum(1 for s in starts if t - s < dt.timedelta(days=7))
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
