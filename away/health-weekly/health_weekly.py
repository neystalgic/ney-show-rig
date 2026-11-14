#!/usr/bin/env python3
# =============================================================================
# HEALTH WEEKLY -- Michael's weekly spreadsheet (Nov 14). Michael chose "Both" on Nov 13: the phone's Body page
# AND a plain spreadsheet he can open in Numbers/Excel.
# Writes "Health Report Weekly.csv" on the Desktop, next to the three logs body_log reads:
#   one row per week (Monday start), oldest at the top, the current week marked "so far".
# All the numbers come from body_log.summary() (v2: deficit, resting HR, HRV, sleep), so the page and the
# spreadsheet always agree. This file only adds: weight change vs last week, average resting + total burn,
# and how many days used the estimated resting burn.
#   python3 health_weekly.py            -> writes the CSV, prints where
#   python3 health_weekly.py --print    -> prints the rows, writes nothing
# rig_control can call start_sunday_writer() once: a small daemon thread that rewrites the CSV every Sunday
# evening (and once at start-up if this week's copy is missing). It never blocks and never touches the lights.
# =============================================================================
import csv, datetime as dt, os, sys, threading, time

import body_log                                    # needs body_log v2 (Health Report v2) for deficit/HR/HRV/sleep

OUT_NAME = 'Health Report Weekly.csv'
SUNDAY_HOUR = 20           # Sunday 8 pm: the week's food + weigh-ins are in (the Watch posts yesterday's numbers)
CHECK_EVERY_S = 30 * 60    # the Sunday thread looks at the clock every 30 minutes
MAX_DAYS = 730             # never read more than two years of logs

COLUMNS = ['Week of', 'Days logged', 'Avg weight (lb)', 'Change (lb)', 'Avg kcal eaten', 'Avg protein (g)',
           'Avg active kcal', 'Avg resting kcal', 'Avg burn kcal', 'Avg deficit', 'Est. resting days',
           'Avg steps', 'Avg resting HR', 'Avg HRV ms', 'Avg sleep h', 'Note']


def out_path():
    return os.path.join(os.path.dirname(body_log.WEIGHT), OUT_NAME)


def _first_day():
    """The earliest date in any of the three logs (so the sheet covers the whole history)."""
    dates = [r.get('Date', '') for p in (body_log.WEIGHT, body_log.FOOD, body_log.ACTIVITY) for r in body_log._rows(p)]
    dates = [d for d in dates if len(d) == 10 and d[4] == '-']
    return min(dates) if dates else None


def _week_of(d):
    day = dt.date.fromisoformat(d)
    return (day - dt.timedelta(days=day.weekday())).isoformat()


def _avg(xs, nd=0):
    if not xs:
        return ''
    v = round(sum(xs) / len(xs), nd)
    return int(v) if nd == 0 else v


def rows(today=None):
    """One dict per week, oldest first, keyed by COLUMNS. Empty string = no data that week.
    (body_log.summary() always counts back from the real today; `today` only picks the 'so far' week.)"""
    if not hasattr(body_log, 'resting_estimate'):
        raise RuntimeError('body_log is v1 -- deploy Health Report v2 first (away/health-report-v2/DEPLOY.txt)')
    today = today or dt.date.today()
    first = _first_day()
    if not first:
        return []
    days = min(MAX_DAYS, max(1, (today - dt.date.fromisoformat(first)).days + 1))
    s = body_log.summary(days=days)
    extra = {}                                       # per week: Watch resting kcal, total burn, estimated days
    for d in s['days']:
        b = extra.setdefault(_week_of(d), {'rest': [], 'burn': [], 'est': 0})
        rest = (s['activity'].get(d) or {}).get('Resting kcal')
        if rest is not None:
            b['rest'].append(rest)
        df = s['deficit'].get(d)
        if df and not df['partial']:
            b['burn'].append(df['burn'])
            b['est'] += 1 if df['resting_est'] else 0
    this_week = _week_of(today.isoformat())
    out, prev_w = [], None
    for w in sorted(s['weekly'], key=lambda r: r['week_of']):
        e = extra.get(w['week_of'], {'rest': [], 'burn': [], 'est': 0})
        aw = w['avg_weight']
        change = round(aw - prev_w, 1) if (aw is not None and prev_w is not None) else ''
        if aw is not None:
            prev_w = aw
        blank = lambda v: '' if v is None else v
        out.append({'Week of': w['week_of'], 'Days logged': w['days_logged'], 'Avg weight (lb)': blank(aw),
                    'Change (lb)': change, 'Avg kcal eaten': blank(w['avg_calories']),
                    'Avg protein (g)': blank(w['avg_protein']), 'Avg active kcal': blank(w['avg_active_kcal']),
                    'Avg resting kcal': _avg(e['rest']), 'Avg burn kcal': _avg(e['burn']),
                    'Avg deficit': blank(w['avg_deficit']), 'Est. resting days': e['est'] if e['burn'] else '',
                    'Avg steps': blank(w['avg_steps']), 'Avg resting HR': blank(w['avg_resting_hr']),
                    'Avg HRV ms': blank(w['avg_hrv']), 'Avg sleep h': blank(w['avg_sleep']),
                    'Note': 'so far' if w['week_of'] == this_week else ''})
    return out


def write(path=None, today=None):
    """Rewrite the whole sheet (it is rebuilt from the logs each time, so it can't drift). Returns (path, rows)."""
    path = path or out_path()
    data = rows(today)
    tmp = path + '.tmp'
    with open(tmp, 'w', newline='') as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(data)
    os.replace(tmp, path)                            # swap in one step: Numbers never sees a half-written file
    return path, len(data)


def _due(now, path):
    """True on Sunday from SUNDAY_HOUR if the sheet wasn't written since then; any day if it's missing or
    older than this week's Monday (e.g. the Mac was off on Sunday evening)."""
    try:
        written = dt.datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return True
    monday = dt.datetime.combine(now.date() - dt.timedelta(days=now.weekday()), dt.time())
    if written < monday - dt.timedelta(hours=24 - SUNDAY_HOUR):            # missed last Sunday's 8 pm run
        return True
    if now.weekday() == 6 and now.hour >= SUNDAY_HOUR:
        return written < now.replace(hour=SUNDAY_HOUR, minute=0, second=0, microsecond=0)
    return False


def tick(now=None, path=None, log=print):
    """One look at the clock: write if due. Never raises (a bad log line must not take rig_control down)."""
    now, path = now or dt.datetime.now(), path or out_path()
    try:
        if _due(now, path):
            p, n = write(path, now.date())
            log('health_weekly: wrote %d weeks to %s' % (n, os.path.basename(p)))
            return True
    except Exception as e:
        log('health_weekly: skipped (%s)' % e)
    return False


def start_sunday_writer():
    def loop():
        while True:
            tick()
            time.sleep(CHECK_EVERY_S)
    threading.Thread(target=loop, name='health-weekly', daemon=True).start()


if __name__ == '__main__':
    if '--print' in sys.argv:
        print(','.join(COLUMNS))
        for r in rows():
            print(','.join(str(r[c]) for c in COLUMNS))
    else:
        p, n = write()
        print('wrote %d weeks -> %s' % (n, p))
