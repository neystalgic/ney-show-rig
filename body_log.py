#!/usr/bin/env python3
# =============================================================================
# BODY LOG -- Michael's 2027 body plan data (Nov 13). Plain CSVs on the Desktop, his to open in Numbers/Excel:
#   Weight Log.csv    Date, Weight (lb), Notes                         (already existed)
#   Food Log.csv      Date, Time, Item, Calories, Protein (g), Source   (Jarvis: "log burger, 900 calories, 55 protein")
#   Activity Log.csv  Date, Active kcal, Steps, Exercise min, Sleep h   (the nightly iPhone/Watch sync, later)
# Nov 14 (v2): + Resting kcal, HR, HRV, VO2max columns; summary() adds the daily deficit, adaptive burn, HR check.
# summary() feeds the phone's Body page and Jarvis's "how am I doing today".
# =============================================================================
import csv, datetime as dt, os

DESK = os.path.expanduser('~/Desktop')
WEIGHT = os.path.join(DESK, 'Weight Log.csv')
FOOD = os.path.join(DESK, 'Food Log.csv')
ACTIVITY = os.path.join(DESK, 'Activity Log.csv')
HEADERS = {FOOD: ['Date', 'Time', 'Item', 'Calories', 'Protein (g)', 'Source'],
           ACTIVITY: ['Date', 'Active kcal', 'Resting kcal', 'Steps', 'Exercise min', 'Sleep h', 'Resting HR', 'HRV ms', 'VO2max']}


def _append(path, row):
    new = not os.path.exists(path)
    with open(path, 'a', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADERS[path])
        w.writerow(row)


def add_food(item, kcal=None, protein=None, source='Jarvis', when=None):
    when = when or dt.datetime.now()
    _append(FOOD, [when.date().isoformat(), when.strftime('%H:%M'), item.strip()[:80],
                   '' if kcal is None else int(round(kcal)), '' if protein is None else int(round(protein)), source])


FIELDS = {'active_kcal': 'Active kcal', 'resting_kcal': 'Resting kcal', 'steps': 'Steps', 'exercise_min': 'Exercise min', 'sleep_h': 'Sleep h',
          'resting_hr': 'Resting HR', 'hrv': 'HRV ms', 'vo2max': 'VO2max'}


def add_activity(day, **vals):
    """One row per day (a later sync for the same day fills in / replaces its numbers)."""
    rows = {r['Date']: r for r in _rows(ACTIVITY) if r.get('Date')}
    row = rows.get(day, {'Date': day})
    for k, col in FIELDS.items():
        v = vals.get(k)
        if v not in (None, ''):
            try:
                row[col] = round(float(v), 1)
            except (TypeError, ValueError):
                pass
    rows[day] = row
    with open(ACTIVITY, 'w', newline='') as f:
        w = csv.DictWriter(f, HEADERS[ACTIVITY], extrasaction='ignore')
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r['Date']))
    return row


def _rows(path):
    try:
        with open(path, newline='') as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def today(day=None):
    day = day or dt.date.today().isoformat()
    meals = [r for r in _rows(FOOD) if r.get('Date') == day]
    kcal = sum(_num(r.get('Calories')) or 0 for r in meals)
    pro = sum(_num(r.get('Protein (g)')) or 0 for r in meals)
    return {'date': day, 'meals': len(meals), 'calories': int(kcal), 'protein': int(pro),
            'unknown': sum(1 for r in meals if _num(r.get('Calories')) is None)}


# --- Nov 14 (Health Report v2): numbers for the deficit + the resting-burn estimate ------------------------
HEIGHT_CM = 190.5          # 6'3"
BIRTH_YEAR = 1999          # "born ~1999", so the age (and the estimate) is approximate
DEFICIT_GOAL = 500         # kcal/day; the page turns the deficit green at or above this
LB_KCAL = 3500             # kcal in a pound of body weight (the usual rule of thumb)
ADAPTIVE_MIN_DAYS = 14     # days of complete food logs before the adaptive burn is shown


def _d(s):
    return dt.date.fromisoformat(s)


def resting_estimate(weight_lb, on=None):
    """Mifflin-St Jeor for a man: 10 x kg + 6.25 x cm - 5 x age + 5. Only used when the Watch sent no Resting kcal."""
    if not weight_lb:
        return None
    age = (on or dt.date.today()).year - BIRTH_YEAR
    return int(round(10 * weight_lb * 0.45359237 + 6.25 * HEIGHT_CM - 5 * age + 5))


def _deficits(days_list, food, act, weights, fallback_w):
    """Real daily deficit = (Active kcal + Resting kcal from the Watch) - calories eaten.
    Needs a food log AND the Watch's active kcal for that day. Missing Resting kcal -> estimate, flagged resting_est.
    A day with a meal logged without calories is flagged partial (left out of the averages)."""
    out, last_w = {}, None
    for d in days_list:
        if d in weights:
            last_w = weights[d]
        f, a = food.get(d), act.get(d) or {}
        active = a.get('Active kcal')
        if not f or active is None:
            continue
        resting, est = a.get('Resting kcal'), False
        if resting is None:
            resting, est = resting_estimate(last_w or fallback_w, _d(d)), True
        if resting is None:
            continue
        burn = active + resting
        out[d] = {'burn': int(round(burn)), 'eaten': int(round(f['calories'])), 'deficit': int(round(burn - f['calories'])),
                  'resting_est': est, 'partial': f.get('unknown', 0) > 0}
    return out


def _adaptive(days_list, food, avg7):
    """The truest maintenance number: average eaten + (weight drop in lb/day x 3500), over up to the last
    28 days of complete food logs, using the 7-day-average weight so single weigh-ins don't swing it."""
    food_days = [d for d in days_list if d in food and not food[d].get('unknown')]
    if len(food_days) < ADAPTIVE_MIN_DAYS:
        return {'kcal': None, 'need_days': ADAPTIVE_MIN_DAYS - len(food_days)}
    window = food_days[-28:]
    eaten = sum(food[d]['calories'] for d in window) / len(window)
    wd = [d for d in days_list if d in avg7 and d >= window[0]]
    span = (_d(wd[-1]) - _d(wd[0])).days if len(wd) >= 2 else 0
    if span < ADAPTIVE_MIN_DAYS - 1:
        return {'kcal': None, 'need_days': ADAPTIVE_MIN_DAYS - 1 - span}
    drop = (avg7[wd[0]] - avg7[wd[-1]]) / span
    return {'kcal': int(round(eaten + drop * LB_KCAL)), 'eaten': int(round(eaten)),
            'lb_per_week': round(drop * 7, 2), 'days': len(window)}


def _hr_check(days_list, act):
    """Latest resting HR vs the average of the 7 days before it (the Health Sync usually posts yesterday)."""
    hr_days = [d for d in days_list if (act.get(d) or {}).get('Resting HR') is not None]
    if not hr_days:
        return None
    d = hr_days[-1]
    hr = act[d]['Resting HR']
    prev = [act[x]['Resting HR'] for x in hr_days[:-1] if 0 < (_d(d) - _d(x)).days <= 7]
    avg = round(sum(prev) / len(prev), 1) if prev else None
    return {'date': d, 'hr': hr, 'avg7': avg, 'diff': (round(hr - avg, 1) if avg is not None else None)}


def summary(days=60):
    """Everything the Body page draws: daily weight (+7-day average), daily food, daily activity, weekly table.
    v2 (Nov 14): + daily deficit (+7-day average), adaptive burn, resting HR vs 7-day average, and
    resting HR / HRV / sleep / deficit in the weekly table. All the v1 keys are unchanged."""
    start = dt.date.today() - dt.timedelta(days=days - 1)
    weights, all_w = {}, []
    for r in _rows(WEIGHT):
        w = _num(r.get('Weight (lb)'))
        if w and r.get('Date'):
            all_w.append((r['Date'], w))
            if r['Date'] >= start.isoformat():
                weights[r['Date']] = w
    food, act = {}, {}
    for r in _rows(FOOD):
        if r.get('Date', '') >= start.isoformat():
            d = food.setdefault(r['Date'], {'calories': 0, 'protein': 0, 'meals': 0, 'unknown': 0})
            d['calories'] += _num(r.get('Calories')) or 0
            d['protein'] += _num(r.get('Protein (g)')) or 0
            d['meals'] += 1
            if _num(r.get('Calories')) is None:
                d['unknown'] += 1
    for r in _rows(ACTIVITY):
        if r.get('Date', '') >= start.isoformat():
            act[r['Date']] = {k: _num(r.get(k)) for k in FIELDS.values()}
    days_list = [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]
    avg7, wins = {}, []
    for d in days_list:
        if d in weights:
            wins.append((d, weights[d]))
        recent = [w for dd, w in wins if (dt.date.fromisoformat(d) - dt.date.fromisoformat(dd)).days < 7]
        if recent:
            avg7[d] = round(sum(recent) / len(recent), 1)
    latest_w = max(all_w)[1] if all_w else None
    deficit = _deficits(days_list, food, act, weights, latest_w)
    def_avg7 = {}
    for d in days_list:
        recent = [v['deficit'] for dd, v in deficit.items() if not v['partial'] and 0 <= (_d(d) - _d(dd)).days < 7]
        if recent:
            def_avg7[d] = int(round(sum(recent) / len(recent)))
    weeks = {}
    for d in days_list:
        wk = dt.date.fromisoformat(d) - dt.timedelta(days=dt.date.fromisoformat(d).weekday())
        b = weeks.setdefault(wk.isoformat(), {'week_of': wk.isoformat(), 'cal': [], 'pro': [], 'w': [], 'active': [], 'steps': [],
                                               'rhr': [], 'hrv': [], 'sleep': [], 'def': []})
        if d in food:
            b['cal'].append(food[d]['calories']); b['pro'].append(food[d]['protein'])
        if d in weights:
            b['w'].append(weights[d])
        if d in act:
            for key, col in (('active', 'Active kcal'), ('steps', 'Steps'), ('rhr', 'Resting HR'), ('hrv', 'HRV ms'), ('sleep', 'Sleep h')):
                if act[d].get(col) is not None:
                    b[key].append(act[d][col])
        if d in deficit and not deficit[d]['partial']:
            b['def'].append(deficit[d]['deficit'])
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else None
    avg1 = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    weekly = [{'week_of': b['week_of'], 'avg_calories': avg(b['cal']), 'avg_protein': avg(b['pro']),
               'avg_weight': (round(sum(b['w']) / len(b['w']), 1) if b['w'] else None),
               'avg_active_kcal': avg(b['active']), 'avg_steps': avg(b['steps']), 'days_logged': len(b['cal']),
               'avg_deficit': avg(b['def']), 'avg_resting_hr': avg1(b['rhr']), 'avg_hrv': avg(b['hrv']), 'avg_sleep': avg1(b['sleep'])}
              for b in weeks.values() if b['cal'] or b['w'] or b['active'] or b['rhr'] or b['sleep']]
    first = min(weights.items()) if weights else None
    last = max(weights.items()) if weights else None
    return {'days': days_list, 'weight': weights, 'weight_avg7': avg7, 'food': food, 'activity': act,
            'weekly': weekly[::-1], 'today': today(),
            'change': (round(last[1] - first[1], 1) if first and last else None), 'start': first, 'latest': last,
            # v2 additions
            'deficit': deficit, 'deficit_avg7': def_avg7, 'deficit_goal': DEFICIT_GOAL,
            'adaptive': _adaptive(days_list, food, avg7), 'hr_check': _hr_check(days_list, act),
            'resting_est_today': resting_estimate(latest_w)}
