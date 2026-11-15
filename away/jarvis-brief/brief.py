"""Jarvis morning briefing (Nov 15, away loop -- Jarvis Status Report #2).

About 20 seconds, spoken: sleep, resting heart rate vs the week, weight trend, yesterday's eaten vs burned
(the real deficit), protein, and one friendly line to start the day. Plain, encouraging, never preachy.

Two ways in:
  * "Jarvis, brief me" (any time)            -> jarvis.do('brief') -> build(body_log.summary())
  * the iPhone Health Sync posts (alarm off) -> rig_control /body/activity -> after_sync(row)
      returns the same text (added to the Shortcut's reply, so a Speak Text step can read it on the phone)
      and the Mac says it out loud ONCE a day, only in the morning window (5:00-12:00).

Lives next to jarvis.py (jarvis/brief.py). Reads the logs only through body_log; writes nothing except a
one-line "already spoken today" note in /tmp. No network, no lights.
Settings (optional, in jarvis/jarvis.json):
  "brief_mac": false        -> never speak on the Mac after a sync (the text still goes back to the phone)
  "protein_goal": 180       -> the nudge can mention protein when it's well under this (no goal = never)
"""
import datetime as dt, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
STATE = '/tmp/jarvis_brief_spoken.txt'      # the date the Mac last spoke the brief (so it speaks once a day)
MORNING = (5, 12)                           # the Mac speaks after a sync only between 5:00 and 12:00
MAX_WORDS = 70                              # ~20-25 s at the Mac's speaking pace


def _settings():
    s = {'voice': 'Moira', 'brief_mac': True, 'protein_goal': None}
    try:
        with open(os.path.join(HERE, 'jarvis.json')) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def _body_log():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import body_log
    return body_log


def _n(x):
    """A number the way the Mac should say it: whole numbers without '.0'."""
    return ('%d' % round(x)) if abs(x - round(x)) < 0.05 else ('%.1f' % x)


def _plural(n, word):
    return '%s %s%s' % (_n(n), word, '' if _n(n) == '1' else 's')


# --- the pieces (each returns a short sentence, or '' when there's nothing to say) ---------------------------------
def _sleep(summ, yday):
    """Sleep from the newest activity row with sleep in it (the sync posts 'yesterday', so last night's sleep
    usually sits on yesterday's row). Only last-night-ish rows (yesterday or today) count."""
    act = summ.get('activity') or {}
    for d in (yday.isoformat(), (yday + dt.timedelta(days=1)).isoformat()):
        h = (act.get(d) or {}).get('Sleep h')
        if h:
            return h
    return None


def _sleep_line(h):
    if h is None:
        return ''
    whole, mins = int(h), int(round((h - int(h)) * 60))
    if mins == 60:
        whole, mins = whole + 1, 0
    return 'You slept %s%s.' % (_plural(whole, 'hour'), (' %d minutes' % mins) if mins else '')


def _hr_line(summ):
    hc = summ.get('hr_check')
    if not hc or hc.get('hr') is None:
        return ''
    hr = _n(hc['hr'])
    diff = hc.get('diff')
    if diff is None:
        return 'Resting heart rate %s.' % hr
    if abs(diff) < 1:
        return 'Resting heart rate %s, right on your weekly average.' % hr
    return 'Resting heart rate %s, %s %s your weekly average.' % (hr, _n(abs(diff)), 'under' if diff < 0 else 'over')


def _weight_line(summ):
    """7-day-average weight now vs about a week ago. Falls back to the latest weigh-in."""
    avg7 = summ.get('weight_avg7') or {}
    latest = summ.get('latest')
    if not avg7:
        return ('Last weigh-in %s pounds.' % _n(latest[1])) if latest else ''
    days = sorted(avg7)
    now_d = days[-1]
    week_ago = (dt.date.fromisoformat(now_d) - dt.timedelta(days=7)).isoformat()
    before = [d for d in days if d <= week_ago]
    if not before:
        return ('Last weigh-in %s pounds.' % _n(latest[1])) if latest else ''
    change = round(avg7[now_d] - avg7[before[-1]], 1)
    if abs(change) < 0.3:
        return 'Weight is holding steady around %s.' % _n(avg7[now_d])
    return 'Weight trend is %s %s this week, now %s.' % ('down' if change < 0 else 'up',
                                                        _plural(abs(change), 'pound'), _n(avg7[now_d]))


def _yesterday(summ, yday):
    """(eaten line, deficit number or None, protein or None) for yesterday."""
    d = yday.isoformat()
    food = (summ.get('food') or {}).get(d)
    dfc = (summ.get('deficit') or {}).get(d)
    if not food or not food.get('meals'):
        return 'No food logged yesterday.', None, None
    protein = food.get('protein') or 0
    pro = ' and %s grams of protein' % _n(protein) if protein else ''
    if dfc:
        est = ' with an estimated resting burn' if dfc.get('resting_est') else ''
        part = ', not counting a meal without numbers' if dfc.get('partial') else ''
        gap = dfc['deficit']
        if gap >= 0:
            tail = 'a %s calorie deficit' % _n(gap)
        else:
            tail = '%s calories over' % _n(-gap)
        return ('Yesterday you ate %s and burned %s%s, %s%s%s.' % (_n(dfc['eaten']), _n(dfc['burn']), est, tail, pro, part),
                gap, protein)
    return 'Yesterday you ate %s calories%s. No burn numbers from the Watch for it yet.' % (_n(food.get('calories') or 0), pro), \
        None, protein


def _nudge(sleep_h, gap, protein, goal, partial_goal=500):
    """One friendly line. Picks the most useful thing; always kind."""
    if sleep_h is not None and sleep_h < 6:
        return 'Short night, so go easy today and aim for an early bedtime.'
    if gap is not None and gap >= partial_goal:
        if goal and protein is not None and protein < goal * 0.8:
            return 'Right on target. A bit more protein today would round it out.'
        return 'Right on target. Keep it rolling.'
    if goal and protein is not None and protein < goal * 0.8:
        return 'Try to get some protein in early today.'
    if gap is not None and gap > 0:
        return 'Every bit counts. Nice work.'
    if gap is not None:
        return 'Fresh start today. You have got this.'
    return 'Have a good one.'


def build(summ, s=None, now=None):
    """The briefing text, from body_log.summary(). Never raises on missing pieces; it just leaves them out."""
    s = s or _settings()
    now = now or dt.datetime.now()
    yday = now.date() - dt.timedelta(days=1)
    sleep_h = _sleep(summ, yday)
    eaten, gap, protein = _yesterday(summ, yday)
    parts = [_sleep_line(sleep_h), _hr_line(summ), _weight_line(summ)]
    if not any(parts) and eaten.startswith('No food'):
        return ("I don't have any health numbers yet. Once the Health Sync runs after your alarm, "
                "I can brief you every morning.")
    hello = 'Good morning, Michael.' if now.hour < 12 else "Here's your brief, Michael."
    parts = [hello] + parts + [eaten, _nudge(sleep_h, gap, protein, s.get('protein_goal'))]
    text = ' '.join(p for p in parts if p)
    words = text.split()
    if len(words) > MAX_WORDS:                     # keep it ~20 s: drop the weight line first, then the nudge
        text = ' '.join(p for p in parts if p and p != parts[3])
    return text


def brief(s=None, now=None):
    """What 'Jarvis, brief me' says."""
    return build(_body_log().summary(), s, now)


def _say(text, voice):
    try:
        subprocess.Popen(['/usr/bin/say', '-v', voice, text], start_new_session=True)   # never blocks the server
    except OSError:
        pass


def after_sync(row, s=None, now=None, speak=None, state=STATE, summary=None):
    """Called by rig_control right after the Health Sync stored a row. Returns ' ' + the brief (to append to the
    Shortcut's reply), or '' if the row had no numbers. Speaks it on the Mac once a day in the morning window."""
    if not row or not any(k != 'Date' and v not in (None, '') for k, v in row.items()):
        return ''
    s = s or _settings()
    now = now or dt.datetime.now()
    text = build(summary if summary is not None else _body_log().summary(), s, now)
    today = now.date().isoformat()
    try:
        with open(state) as f:
            spoken = f.read().strip()
    except OSError:
        spoken = ''
    if s.get('brief_mac', True) and MORNING[0] <= now.hour < MORNING[1] and spoken != today:
        (speak or _say)(text, s.get('voice', 'Moira'))
        try:
            with open(state, 'w') as f:
                f.write(today)
        except OSError:
            pass
    return ' ' + text


if __name__ == '__main__':          # python3 jarvis/brief.py  -> prints today's brief (reads the logs, changes nothing)
    print(brief())
