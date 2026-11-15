#!/usr/bin/env python3
# =============================================================================
# JARVIS REMINDERS + TIMERS (Nov 15, away loop task J2) -- jarvis/reminders.py
#
#   "remind me at 9 to take my meds"        "remind me in 20 minutes to check the oven"
#   "remind me tomorrow at 7 to call mum"   "10 minute timer" / "set a timer for an hour"
#   "what are my reminders" / "how long left on my timer"
#   "cancel the 9 o'clock" / "cancel my timer" / "cancel the meds reminder" / "cancel all reminders"
#
# Stored in jarvis/reminders.json (plain JSON, gitignored -- edit or empty it by hand any time).
# rig_control runs loop() in a small thread: every 15 s it says anything that is due on the Mac
# (say, voice Moira). Each one is taken off the list BEFORE it is spoken, so it is said once.
# If the Mac was asleep when one was due, it is said once on wake: "Earlier, at 9 pm: ...".
# Nothing here touches the lights, and nothing blocks: 'say' runs in its own process.
# =============================================================================
import datetime as dt, json, os, re, subprocess, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, 'reminders.json')
MAX_ITEMS = 50          # a typo can't fill the file
LATE_S = 120            # spoken more than 2 min after it was due -> said as "Earlier, at ..."
MAX_DAYS = 14           # reminders up to two weeks ahead
LOCK = threading.Lock()  # the /ask thread and the speaker thread both write the file

# --- numbers and durations -------------------------------------------------------------------------------------------
WORDS = {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
         'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'fifteen': 15, 'twenty': 20, 'twenty five': 25,
         'thirty': 30, 'forty': 40, 'forty five': 45, 'fifty': 50, 'sixty': 60, 'ninety': 90, 'a couple of': 2,
         'a couple': 2, 'a few': 3, 'half an': 0.5, 'half a': 0.5}
_NUM = r'(?:\d+(?:\.\d+)?|%s)' % '|'.join(sorted(map(re.escape, WORDS), key=len, reverse=True))
_UNIT = r'(?:hours?|hrs?|minutes?|mins?|seconds?|secs?)'
PIECE = re.compile(r'(?P<n>%s)[\s-]*(?P<u>%s)\b' % (_NUM, _UNIT))
DUR = r'%s[\s-]*%s\b(?:\s*(?:,|and)?\s*(?:%s[\s-]*%s\b|and a half|a half))*' % (_NUM, _UNIT, _NUM, _UNIT)
UNIT_S = {'h': 3600, 'm': 60, 's': 1}


def _n(word):
    return float(word) if re.match(r'\d', word) else WORDS[word]


def duration(text):
    """'1 hour and 30 minutes' -> 5400 seconds; 'an hour and a half' -> 5400; None if no duration."""
    total, last = 0, None
    for m in PIECE.finditer(text):
        last = UNIT_S[m.group('u')[0]]
        total += _n(m.group('n')) * last
    if last is None:
        return None
    if re.search(r'\band a half\b', text):
        total += last / 2
    return int(round(total))


def say_duration(secs, unit_word=False):
    """5400 -> '1 hour and 30 minutes' (or '1 hour 30 minute' for '... timer')."""
    h, rest = divmod(int(secs), 3600)
    m, s = divmod(rest, 60)
    parts = []
    for n, name in ((h, 'hour'), (m, 'minute'), (s, 'second')):
        if n:
            parts.append('%d %s%s' % (n, name, '' if n == 1 or unit_word else 's'))
    return (' ' if unit_word else ' and ').join(parts) or ('0 second' if unit_word else '0 seconds')


# --- clock times -----------------------------------------------------------------------------------------------------
_AP = r'(?P<ap>a\.?\s?m\.?|p\.?\s?m\.?)'
CLOCK_AT = re.compile(r'\b(?:at|for|by)\s+(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?:%s|o.?clock)?(?![\d:])' % _AP)
CLOCK_AP = re.compile(r'\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?:%s|o.?clock)' % _AP)
CLOCK_HM = re.compile(r'\b(?P<h>\d{1,2}):(?P<m>\d{2})\b')
NOON = re.compile(r'\b(?:at\s+)?(?P<w>noon|midday|midnight)\b')
DAY_RE = re.compile(r'\b(?P<d>tomorrow(?: morning| afternoon| evening| night)?|tonight|this (?:morning|afternoon|evening))\b')


def find_clock(t):
    """-> (span, (hour, minute, 'am'|'pm'|None)) or None. A bare number needs 'at' or am/pm/o'clock, so
    'remind me to buy 2 eggs' is not a time."""
    m = NOON.search(t)
    if m:
        return m.span(), ((12 if m.group('w') != 'midnight' else 0), 0, 'pm' if m.group('w') != 'midnight' else 'am')
    for rx in (CLOCK_AT, CLOCK_AP, CLOCK_HM):
        m = rx.search(t)
        if m:
            h, mi = int(m.group('h')), int(m.group('m') or 0)
            ap = (m.groupdict().get('ap') or '').replace('.', '').replace(' ', '')[:2] or None
            if h > 23 or mi > 59 or (ap and not 1 <= h <= 12):
                continue
            return m.span(), (h, mi, ap)
    return None


def resolve(clock, now, day=None):
    """(9, 0, None) at 20:15 -> today 21:00. Without am/pm the NEXT 9 o'clock wins; 'tomorrow' without am/pm
    means 7-11 morning, 12 noon, 1-6 afternoon/evening. 'tonight'/'evening' -> pm, 'morning' -> am."""
    h, mi, ap = clock
    day = day or ''
    if not ap and 1 <= h <= 12:
        if re.search(r'tonight|evening|night|afternoon', day):
            ap = 'am' if (h == 12 and 'night' in day) else 'pm'
        elif 'morning' in day:
            ap = 'am'
        elif day.startswith('tomorrow'):
            ap = 'am' if 7 <= h <= 11 else 'pm'
        elif 1 <= h <= 5 and now.hour >= 6:          # "at 2" said in the day means 2 pm, not 2 am
            ap = 'pm'
    if ap:
        h = h % 12 + (12 if ap == 'pm' else 0)
    base = now.replace(second=0, microsecond=0)
    if day.startswith('tomorrow'):
        base += dt.timedelta(days=1)
    hours = [h] if (ap or h == 0 or h > 12) else [h % 12, h % 12 + 12]
    options = []
    for add in (0, 1):
        for hh in hours:
            c = base.replace(hour=hh, minute=mi) + dt.timedelta(days=add)
            if c > now:
                options.append(c)
    return min(options)


def say_time(when, now):
    """21:00 today -> '9 pm'; 7:30 tomorrow -> 'tomorrow at 7:30 am'."""
    if when.hour == 12 and when.minute == 0:
        clock = 'noon'
    elif when.hour == 0 and when.minute == 0:
        clock = 'midnight'
    else:
        h12 = when.hour % 12 or 12
        clock = ('%d' % h12 if not when.minute else '%d:%02d' % (h12, when.minute)) + (' am' if when.hour < 12 else ' pm')
    days = (when.date() - now.date()).days
    if days == 0 or (days == 1 and clock == 'midnight'):
        return clock
    if days == 1:
        return 'tomorrow at ' + clock
    return '%s at %s' % (when.strftime('%A'), clock)


# --- understanding ---------------------------------------------------------------------------------------------------
SWAP = {'my': 'your', 'me': 'you', 'i': 'you', "i'm": "you're", 'im': "you're", 'myself': 'yourself',
        'mine': 'yours', 'am': 'are', "i've": "you've", "i'll": "you'll"}
LIST_RE = re.compile(r"\b(what|which|any|list|read|tell me|do i have|check)\b.*\b(reminders?|timers?)\b"
                     r"|\b(how (long|much time)|time) (is )?(left|remaining)\b|\bwhen.?s my (timer|reminder)\b")
CANCEL_RE = re.compile(r"^(?:can you |please )?(cancel|delete|remove|clear|stop|forget|drop|scrap|never mind)\b")
TIMER_RE = re.compile(r'\btimers?\b')
REMIND_RE = re.compile(r'\bremind (me|us)\b|\b(set|add|make|create) (a |an )?(reminder|alarm)\b|^reminder\b')
LABEL_RE = re.compile(r'\b(?:for|called|named)\s+(?:the |my |a )?(?P<label>[a-z][a-z \']{1,30}?)\s*$')


def _clean(text):
    t = text.lower().strip()
    t = re.sub(r'^(hey |ok |okay )?(jarvis|siri|ney)[,.!]?\s*', '', t)
    t = re.sub(r'[!?]+$|\.$', '', t).strip()
    t = re.sub(r'\s+please$', '', t)
    return t.replace('’', "'")


def _task(rest):
    """'to take my meds' -> 'take your meds'."""
    r = re.sub(r'^\s*(?:,|that|about|to|i need to|i have to|i should|i gotta|i must|for|of)\b\s*', '', rest.strip(' ,.'))
    r = re.sub(r'^\s*(?:to|that)\b\s*', '', r)
    r = re.sub(r'\s+', ' ', r).strip(' ,.')
    r = re.sub(r"\b(i'm|i've|i'll|im|myself|mine|my|me|i|am)\b", lambda m: SWAP[m.group(1)], r)
    return r


def parse(text):
    """A sentence -> {'op': 'add'|'timer'|'list'|'cancel', ...} or None (not about reminders/timers).
    Only plain data (JSON-friendly); the time is worked out in handle(), when 'now' is known."""
    t = _clean(text)
    if not t:
        return None
    is_timer, is_remind = bool(TIMER_RE.search(t)), bool(REMIND_RE.search(t)) or bool(re.search(r'\breminders?\b', t))
    by_time = bool(re.match(r'^(?:can you |please )?(cancel|delete|remove|forget|scrap)\b', t)) and bool(find_clock(t))
    if not (is_timer or is_remind or by_time):          # "cancel the 9 o'clock" counts too
        return None
    if CANCEL_RE.search(t):
        kind = 'timer' if is_timer and not is_remind else ('reminder' if is_remind and not is_timer else None)
        c = find_clock(t)
        words = [w for w in re.findall(r"[a-z']{3,}", t) if w not in STOP]
        return {'op': 'cancel', 'kind': kind, 'all': bool(re.search(r'\ball\b|\beverything\b|\bclear (my |the |all )?(reminders|timers)\b', t)),
                'clock': list(c[1]) if c else None,
                'minutes': bool(re.search(r'\d:\d{2}', t)), 'secs': duration(t), 'words': words}
    if LIST_RE.search(t):
        return {'op': 'list'}
    if is_timer and not REMIND_RE.search(t):
        secs = duration(t)
        label = None
        m = re.search(DUR, t)
        tail = t[m.end():] if m else t
        lm = LABEL_RE.search(tail.replace('timer', ' ').strip())
        if lm and not re.match(r'^(the |a |an )?(next )?\d', lm.group('label')):
            label = lm.group('label').strip()
        else:                                    # "10 minute pasta timer"
            pm = re.search(r'(?:%s)[\s-]+(?P<label>[a-z]+)[\s-]+timer' % DUR, t)
            if pm and pm.group('label') not in ('long', 'more', 'and'):
                label = pm.group('label')
        return {'op': 'timer', 'secs': secs, 'label': label}
    # a reminder: find WHEN, the rest is WHAT
    m = REMIND_RE.search(t)
    body = t[m.end():] if m else t
    when = {'secs': None, 'clock': None, 'day': None}
    dm = re.search(r'\bin\s+(?P<d>%s)' % DUR, body)
    if dm:
        when['secs'] = duration(dm.group('d'))
        body = body[:dm.start()] + ' ' + body[dm.end():]
    else:
        c = find_clock(body)
        if c:
            when['clock'] = list(c[1])
            body = body[:c[0][0]] + ' ' + body[c[0][1]:]
    dy = DAY_RE.search(body)
    if dy:
        when['day'] = dy.group('d')
        body = body[:dy.start()] + ' ' + body[dy.end():]
    return dict(op='add', text=_task(body), **when)


STOP = {'cancel', 'delete', 'remove', 'clear', 'stop', 'forget', 'drop', 'scrap', 'never', 'mind', 'the', 'reminder',
        'reminders', 'timer', 'timers', 'my', 'that', 'this', 'one', 'clock', "o'clock", 'please', 'about', 'for',
        'all', 'and', 'can', 'you', 'minute', 'minutes', 'hour', 'hours', 'second', 'seconds', 'tomorrow', 'tonight'}


# --- the file --------------------------------------------------------------------------------------------------------
def load(path=None):
    try:
        with open(path or FILE) as f:
            items = json.load(f).get('items', [])
        return [i for i in items if isinstance(i, dict) and 'due' in i]
    except (OSError, ValueError, AttributeError):
        return []


def save(items, path=None):
    path = path or FILE
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'_note': 'Jarvis reminders + timers. Safe to edit or empty by hand.', 'items': items}, f, indent=1)
    os.replace(tmp, path)


def _due(i):
    return dt.datetime.fromisoformat(i['due'])


def _describe(i, now):
    if i['kind'] == 'timer':
        left = max(0, int((_due(i) - now).total_seconds()))
        name = ('%s timer' % i['label']) if i.get('label') else ('%s timer' % say_duration(i['secs'], True))
        return '%s, %s left' % (name, say_duration(left - left % 60 if left >= 120 else left))
    return '%s, %s' % (say_time(_due(i), now), i['text'] or 'your reminder')


# --- doing -----------------------------------------------------------------------------------------------------------
HOWTO = "Say it like 'remind me at 9 to take my meds', 'remind me in 20 minutes to check the oven', or '10 minute timer'."


def handle(intent, now=None, path=None):
    """Runs a parsed reminder intent and returns what Jarvis says."""
    now = now or dt.datetime.now()
    if not isinstance(intent, dict) or intent.get('op') not in ('add', 'timer', 'list', 'cancel'):
        return HOWTO
    with LOCK:
        items = sorted(load(path), key=_due)
        op = intent['op']
        if op == 'list':
            if not items:
                return 'No reminders or timers right now.'
            rs = [i for i in items if i['kind'] == 'reminder']
            ts = [i for i in items if i['kind'] == 'timer']
            out = []
            if rs:
                out.append('%s: %s.' % ('One reminder' if len(rs) == 1 else '%d reminders' % len(rs),
                                        '; '.join(_describe(i, now) for i in rs)))
            if ts:
                out.append('%s: %s.' % ('One timer' if len(ts) == 1 else '%d timers' % len(ts),
                                        '; '.join(_describe(i, now) for i in ts)))
            return ' '.join(out)
        if op == 'cancel':
            return _cancel(intent, items, now, path)
        if len(items) >= MAX_ITEMS:
            return "You already have %d reminders and timers -- that's my limit. Cancel a few first." % len(items)
        if op == 'timer':
            secs = intent.get('secs')
            if not secs:
                return "How long? Say it like '10 minute timer'."
            if not 5 <= secs <= 24 * 3600:
                return 'Timers can be from 5 seconds to 24 hours.'
            due = now + dt.timedelta(seconds=secs)
            items.append(dict(id=_next_id(items), kind='timer', secs=secs, label=intent.get('label'),
                              text='', due=due.isoformat(timespec='seconds'), set=now.isoformat(timespec='seconds')))
            save(items, path)
            name = ('%s timer for %s' % (intent['label'].capitalize(), say_duration(secs))) if intent.get('label') \
                else '%s timer' % say_duration(secs, True).capitalize()
            return '%s, starting now. It ends at %s.' % (name, say_time(due, now))
        # add a reminder
        if intent.get('secs'):
            due = now + dt.timedelta(seconds=intent['secs'])
            said = 'in %s' % say_duration(intent['secs'])
        elif intent.get('clock'):
            due = resolve(tuple(intent['clock']), now, intent.get('day'))
            st = say_time(due, now)
            said = ('at ' + st) if (due.date() - now.date()).days == 0 or st == 'midnight' else st
        else:
            return ('When should I remind you%s? %s' % (' (%s)' % intent['day'] if intent.get('day') else '', HOWTO))
        if due - now > dt.timedelta(days=MAX_DAYS):
            return "That's more than two weeks away -- put it in your calendar instead."
        what = intent.get('text') or ''
        items.append(dict(id=_next_id(items), kind='reminder', text=what, due=due.isoformat(timespec='seconds'),
                          set=now.isoformat(timespec='seconds')))
        save(items, path)
        if intent.get('secs'):
            said = '%s (%s)' % (said, say_time(due, now))
        return ("Okay, I'll remind you %s to %s." % (said, what)) if what else ("Okay, I'll give you a reminder %s." % said)


def _next_id(items):
    return max([i.get('id', 0) for i in items] + [0]) + 1


def _cancel(intent, items, now, path):
    kind = intent.get('kind')
    pool = [i for i in items if not kind or i['kind'] == kind]
    noun = kind or 'reminder or timer'
    if not pool:
        return "You don't have any %ss to cancel." % noun if kind else 'No reminders or timers to cancel.'
    if intent.get('all'):
        keep = [i for i in items if i not in pool]
        save(keep, path)
        return 'Cancelled %s.' % ('all %d %ss' % (len(pool), kind) if kind else 'all %d reminders and timers' % len(pool))
    hits = pool
    c = intent.get('clock')
    if c:
        h, mi, ap = c
        def at(i):
            d = _due(i)
            hour_ok = d.hour == (h % 12 + (12 if ap == 'pm' else 0)) if ap else d.hour % 12 == h % 12
            return hour_ok and (not intent.get('minutes') or d.minute == mi)
        hits = [i for i in hits if at(i)]
    if intent.get('secs') and kind == 'timer':
        hits = [i for i in hits if i.get('secs') == intent['secs']] or hits
    words = [w for w in intent.get('words') or [] if not re.match(r'\d', w)]
    if words:                                    # "cancel the meds reminder" / "cancel the pasta timer"
        worded = [i for i in hits if set(words) & set(re.findall(r"[a-z']{3,}", '%s %s' % (i.get('text') or '', i.get('label') or '')))]
        if worded:
            hits = worded
        elif not c:
            hits = []
    if not hits:
        return "I couldn't find that one. " + _list_short(items, now)
    if len(hits) > 1:
        return 'You have %d that match: %s. Say which one, or "cancel all %ss".' % (
            len(hits), '; '.join(_describe(i, now) for i in hits), kind or 'reminder')
    gone = hits[0]
    save([i for i in items if i is not gone], path)
    if gone['kind'] == 'timer':
        return 'Cancelled the %s.' % _describe(gone, now).split(',')[0]
    return 'Cancelled your reminder for %s%s.' % (say_time(_due(gone), now), (': ' + gone['text']) if gone.get('text') else '')


def _list_short(items, now):
    return 'You have: %s.' % '; '.join(_describe(i, now) for i in items) if items else 'You have none set.'


# --- speaking (rig_control thread) -----------------------------------------------------------------------------------
def pop_due(now=None, path=None):
    """Takes everything that is due off the list (saved first, so each is said ONCE) and returns the sentence."""
    now = now or dt.datetime.now()
    with LOCK:
        items = load(path)
        due = sorted([i for i in items if _due(i) <= now], key=_due)
        if not due:
            return ''
        save([i for i in items if i not in due], path)
    out = []
    for i in due:
        late = (now - _due(i)).total_seconds() > LATE_S
        if i['kind'] == 'timer':
            name = ('%s timer' % i['label']) if i.get('label') else ('%s timer' % say_duration(i['secs'], True))
            out.append(('Your %s finished at %s.' % (name, say_time(_due(i), _due(i)))) if late else ('Your %s is done.' % name))
        else:
            what = (i.get('text') or 'this is your reminder').rstrip('.')
            out.append(('Earlier, at %s: %s.' % (say_time(_due(i), _due(i)), what)) if late else ('Reminder: %s.' % what))
    if len(due) > 1 and any((now - _due(i)).total_seconds() > LATE_S for i in due):
        out.insert(0, 'While the Mac was asleep:')
    return ' '.join(out)


def _say(text, voice):
    try:
        subprocess.Popen(['/usr/bin/say', '-v', voice, text], start_new_session=True)   # never blocks
    except OSError:
        pass


def _voice():
    try:
        with open(os.path.join(HERE, 'jarvis.json')) as f:
            return json.load(f).get('reminder_voice') or 'Moira'
    except (OSError, ValueError, AttributeError):
        return 'Moira'


def tick(now=None, path=None, speak=None):
    text = pop_due(now, path)
    if text:
        (speak or _say)(text, _voice())
    return text


def loop(every=15, path=None, speak=None, sleep=time.sleep, rounds=None):
    """rig_control's thread. Never dies: a bad file or a failed 'say' is skipped and tried next round."""
    n = 0
    while rounds is None or n < rounds:
        try:
            tick(path=path, speak=speak)
        except Exception as e:
            try:
                with open('/tmp/jarvis.log', 'a') as f:
                    f.write('%s reminders: %r\n' % (dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), e))
            except OSError:
                pass
        n += 1
        sleep(every)


if __name__ == '__main__':          # python3 jarvis/reminders.py  -> what's set right now
    print(handle({'op': 'list'}))
