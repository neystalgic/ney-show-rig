#!/usr/bin/env python3
# =============================================================================
# BODY LOG -- Michael's 2027 body plan data (Nov 13). Plain CSVs on the Desktop, his to open in Numbers/Excel:
#   Weight Log.csv    Date, Weight (lb), Notes                         (already existed)
#   Food Log.csv      Date, Time, Item, Calories, Protein (g), Source   (Jarvis: "log burger, 900 calories, 55 protein")
#   Activity Log.csv  Date, Active kcal, Steps, Exercise min, Sleep h   (the nightly iPhone/Watch sync, later)
# summary() feeds the phone's Body page and Jarvis's "how am I doing today".
# =============================================================================
import csv, datetime as dt, os

DESK = os.path.expanduser('~/Desktop')
WEIGHT = os.path.join(DESK, 'Weight Log.csv')
FOOD = os.path.join(DESK, 'Food Log.csv')
ACTIVITY = os.path.join(DESK, 'Activity Log.csv')
HEADERS = {FOOD: ['Date', 'Time', 'Item', 'Calories', 'Protein (g)', 'Source'],
           ACTIVITY: ['Date', 'Active kcal', 'Steps', 'Exercise min', 'Sleep h']}


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


def add_activity(day, active_kcal='', steps='', exercise_min='', sleep_h=''):
    rows = [r for r in _rows(ACTIVITY) if r.get('Date') != day]          # one row per day: newest wins
    rows.append({'Date': day, 'Active kcal': active_kcal, 'Steps': steps, 'Exercise min': exercise_min, 'Sleep h': sleep_h})
    with open(ACTIVITY, 'w', newline='') as f:
        w = csv.DictWriter(f, HEADERS[ACTIVITY])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r['Date']))


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


def summary(days=60):
    """Everything the Body page draws: daily weight (+7-day average), daily food, daily activity, weekly table."""
    start = dt.date.today() - dt.timedelta(days=days - 1)
    weights = {}
    for r in _rows(WEIGHT):
        w = _num(r.get('Weight (lb)'))
        if w and r.get('Date', '') >= start.isoformat():
            weights[r['Date']] = w
    food, act = {}, {}
    for r in _rows(FOOD):
        if r.get('Date', '') >= start.isoformat():
            d = food.setdefault(r['Date'], {'calories': 0, 'protein': 0, 'meals': 0})
            d['calories'] += _num(r.get('Calories')) or 0
            d['protein'] += _num(r.get('Protein (g)')) or 0
            d['meals'] += 1
    for r in _rows(ACTIVITY):
        if r.get('Date', '') >= start.isoformat():
            act[r['Date']] = {k: _num(r.get(k)) for k in ('Active kcal', 'Steps', 'Exercise min', 'Sleep h')}
    days_list = [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]
    avg7, wins = {}, []
    for d in days_list:
        if d in weights:
            wins.append((d, weights[d]))
        recent = [w for dd, w in wins if (dt.date.fromisoformat(d) - dt.date.fromisoformat(dd)).days < 7]
        if recent:
            avg7[d] = round(sum(recent) / len(recent), 1)
    weeks = {}
    for d in days_list:
        wk = dt.date.fromisoformat(d) - dt.timedelta(days=dt.date.fromisoformat(d).weekday())
        b = weeks.setdefault(wk.isoformat(), {'week_of': wk.isoformat(), 'cal': [], 'pro': [], 'w': [], 'active': [], 'steps': []})
        if d in food:
            b['cal'].append(food[d]['calories']); b['pro'].append(food[d]['protein'])
        if d in weights:
            b['w'].append(weights[d])
        if d in act:
            if act[d].get('Active kcal') is not None: b['active'].append(act[d]['Active kcal'])
            if act[d].get('Steps') is not None: b['steps'].append(act[d]['Steps'])
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else None
    weekly = [{'week_of': b['week_of'], 'avg_calories': avg(b['cal']), 'avg_protein': avg(b['pro']),
               'avg_weight': (round(sum(b['w']) / len(b['w']), 1) if b['w'] else None),
               'avg_active_kcal': avg(b['active']), 'avg_steps': avg(b['steps']), 'days_logged': len(b['cal'])}
              for b in weeks.values() if b['cal'] or b['w'] or b['active']]
    first = min(weights.items()) if weights else None
    last = max(weights.items()) if weights else None
    return {'days': days_list, 'weight': weights, 'weight_avg7': avg7, 'food': food, 'activity': act,
            'weekly': weekly[::-1], 'today': today(),
            'change': (round(last[1] - first[1], 1) if first and last else None), 'start': first, 'latest': last}
