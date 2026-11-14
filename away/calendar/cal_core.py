#!/usr/bin/env python3
# =============================================================================
# CAL CORE (away/calendar prototype, Nov 14) -- the OFFLINE half of the Google Calendar plan.
# Pure functions: no network, no secrets, no files. The fetcher (not built yet -- see PLAN.txt)
# hands these the 'items' list from Google's events.list reply (singleEvents=true), and these
# turn it into what Jarvis says and what the away loop needs:
#   load_events                   Google items -> simple dicts (skips cancelled / declined / odd ones)
#   say_day                       "what's my day" / "what do I have tomorrow"
#   say_next_shift                "when do I work"
#   shift_snapshot                shift TIMES only (no titles) -> bridge/calendar/shifts.json
#   work_hours_for                the WORK_HOURS string budget_check.py would use today
# =============================================================================
import datetime as dt, re

SHIFT_WORDS = ('work', 'shift')   # Michael sets the real words in jarvis/calendar.json (see PLAN.txt)
MAX_SAY = 5                       # Jarvis reads at most 5 events out loud, then "and N more"


def local_tz():
    return dt.datetime.now().astimezone().tzinfo


def _when(d, tz):
    """Google gives {'dateTime': '2026-11-14T15:00:00-05:00'} or {'date': '2026-11-14'} for all-day."""
    if 'dateTime' in d:
        return dt.datetime.fromisoformat(d['dateTime'].replace('Z', '+00:00')).astimezone(tz), False
    return dt.datetime.combine(dt.date.fromisoformat(d['date']), dt.time(0), tz), True


def load_events(items, tz=None):
    tz = tz or local_tz()
    out = []
    for it in items or []:
        if not isinstance(it, dict) or it.get('status') == 'cancelled':
            continue
        if any(a.get('self') and a.get('responseStatus') == 'declined' for a in it.get('attendees') or []):
            continue                                        # you said no -> not part of your day
        try:
            s, all_day = _when(it['start'], tz)
            e, _ = _when(it['end'], tz)
        except (KeyError, ValueError, TypeError, AttributeError):
            continue                                        # one odd event never breaks the rest
        out.append({'title': (it.get('summary') or 'Busy').strip(), 'start': s, 'end': e, 'all_day': all_day})
    out.sort(key=lambda ev: ev['start'])
    return out


def is_shift(ev, words=SHIFT_WORDS):
    """Timed events whose title has a shift word as a whole word ('Work', 'Shift - camp'; not 'Workout')."""
    t = ev['title'].lower()
    return not ev['all_day'] and any(re.search(r'\b%s\b' % re.escape(w.lower()), t) for w in words)


def day_events(events, day):
    out = []
    for ev in events:
        a = dt.datetime.combine(day, dt.time(0), ev['start'].tzinfo)
        if ev['start'] < a + dt.timedelta(days=1) and ev['end'] > a:
            out.append(ev)
    return out


def speak_time(t):
    if (t.hour, t.minute) == (12, 0):
        return 'noon'
    if (t.hour, t.minute) == (0, 0):
        return 'midnight'
    h = t.hour % 12 or 12
    return ('%d' % h if t.minute == 0 else '%d:%02d' % (h, t.minute)) + (' am' if t.hour < 12 else ' pm')


def _span(ev):
    return '%s to %s' % (speak_time(ev['start']), speak_time(ev['end']))


def _which(day, now):
    if day == now.date():
        return 'today'
    if day == now.date() + dt.timedelta(days=1):
        return 'tomorrow'
    return 'on ' + day.strftime('%A')


def say_day(events, day, now):
    evs, which = day_events(events, day), _which(day, now)
    if not evs:
        return 'Nothing on your calendar %s.' % which
    parts = [ev['title'] + (' (all day)' if ev['all_day'] else ', ' + _span(ev)) for ev in evs[:MAX_SAY]]
    more = '' if len(evs) <= MAX_SAY else '; and %d more' % (len(evs) - MAX_SAY)
    return 'You have %d thing%s %s: %s%s.' % (len(evs), '' if len(evs) == 1 else 's', which, '; '.join(parts), more)


def next_shift(events, now, words=SHIFT_WORDS, days=7):
    for ev in events:
        if is_shift(ev, words) and ev['end'] > now and ev['start'] < now + dt.timedelta(days=days):
            return ev
    return None


def say_next_shift(events, now, words=SHIFT_WORDS, days=7):
    ev = next_shift(events, now, words, days)
    if not ev:
        return 'No shifts on your calendar in the next %d days.' % days
    if ev['start'] <= now:
        return "You're on shift now, until %s." % speak_time(ev['end'])
    w = _which(ev['start'].date(), now)
    if w.startswith('on '):
        return 'Your next shift is %s, %s.' % (w[3:], _span(ev))
    return 'You work %s, %s.' % (w, _span(ev))


def shift_snapshot(events, now, words=SHIFT_WORDS, days=7):
    """What the away loop gets: shift start/end times ONLY -- no titles, no other events."""
    return {'fetched': now.isoformat(timespec='minutes'),
            'shifts': [[ev['start'].isoformat(timespec='minutes'), ev['end'].isoformat(timespec='minutes')]
                       for ev in events if is_shift(ev, words) and ev['end'] > now - dt.timedelta(days=1)
                       and ev['start'] < now + dt.timedelta(days=days)]}


def _spans(text):
    return [[int(x) for x in w.split('-')] for w in text.split(',') if w.strip()]


def work_hours_for(snapshot, now, sleep='01-09', fallback='01-09,15-20', max_age_h=36):
    """Today's away hours = your sleep window + today's shift hours (start rounded down, end rounded up).
    Missing, stale or broken snapshot -> the fixed WORK_HOURS (fallback), so the loop never stalls on Google."""
    try:
        fetched = dt.datetime.fromisoformat(snapshot['fetched'])
        if now - fetched > dt.timedelta(hours=max_age_h) or fetched - now > dt.timedelta(hours=1):
            return fallback
        spans = _spans(sleep)
        a = dt.datetime.combine(now.date(), dt.time(0), now.tzinfo)
        b = a + dt.timedelta(days=1)
        for s, e in snapshot['shifts']:
            s, e = dt.datetime.fromisoformat(s).astimezone(now.tzinfo), dt.datetime.fromisoformat(e).astimezone(now.tzinfo)
            if e <= a or s >= b:
                continue
            s, e = max(s, a), min(e, b)
            end_h = 24 if e == b else e.hour + (1 if (e.minute or e.second) else 0)
            spans.append([s.hour, end_h])
    except (KeyError, TypeError, ValueError, AttributeError):
        return fallback
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return ','.join('%02d-%02d' % (s, e) for s, e in merged) or fallback
