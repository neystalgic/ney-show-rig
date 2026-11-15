"""Jarvis workout mode (away loop J4, Nov 15). Lives at jarvis/workout.py once deployed.

  "Jarvis, starting a walk"   (run, jog, hike, bike ride, swim, yoga, workout / gym)
       -> writes the start time to ~/Desktop/Workout Log.csv and asks nothing. "Walk started at 6:10. Enjoy it."
  "done with my walk"  /  "back from my run"  /  "finished my hike"  /  "I'm back" (only while one is going)
       -> fills in the end time + minutes, then asks "How did it feel, 1 to 10?"
  "7" / "about an 8" / "seven out of ten" (within 10 minutes of that question)  -> the score goes in the row
       ("done with my run, felt like a 7" does both at once).   "skip" / "no" -> no score, that's fine.
  "how long have I been walking"  -> minutes so far.     "cancel my walk" -> row kept, marked cancelled.
The next Health Sync fills the Watch numbers (steps, active kcal) in Activity Log.csv as usual -- this file
only adds WHEN, WHAT and HOW IT FELT. It's a separate CSV because the Health Sync rewrites Activity Log.csv.
Never touches the lights. An energetic look only if he asks in his own words ("starting a run and hype"),
which Jarvis already splits into two things. Word rules only: the model can never pick this.
"""
import csv, datetime as dt, os, re

LOG = os.path.expanduser('~/Desktop/Workout Log.csv')
HEADER = ['Date', 'Start', 'End', 'Minutes', 'Kind', 'Feel (1-10)', 'Notes']
ASK_MIN = 10                     # a bare number means "how it felt" only for this long after the question
STALE_H = 6                      # a workout "going" for more than 6 hours was forgotten, not a 6-hour walk
STATE = {'ask_until': None, 'ask_row': None}
_now = dt.datetime.now           # tests swap this for a fake clock

# spoken word -> the kind written in the log (longest first so "bike ride" wins over "ride")
KINDS = [('bike ride', 'bike'), ('bike', 'bike'), ('biking', 'bike'), ('cycle', 'bike'), ('cycling', 'bike'),
         ('ride', 'bike'), ('walking', 'walk'), ('walk', 'walk'), ('running', 'run'), ('run', 'run'),
         ('jogging', 'run'), ('jog', 'run'), ('hiking', 'hike'), ('hike', 'hike'), ('swimming', 'swim'),
         ('swim', 'swim'), ('yoga', 'yoga'), ('work out', 'workout'), ('workout', 'workout'),
         ('gym session', 'workout'), ('gym', 'workout'), ('lift', 'workout'), ('lifting', 'workout')]
KIND_WORDS = {'walk': 'walk', 'run': 'run', 'hike': 'hike', 'bike': 'bike ride', 'swim': 'swim', 'yoga': 'yoga session',
              'workout': 'workout'}
K = '(?P<k>' + '|'.join(re.escape(w) for w, _ in KINDS) + ')'
ADJ = r'(?:(?:quick|short|long|little|easy|morning|evening|night|lunch|nice|big)\s+)?'
ART = r'(?:(?:a|an|my|the|our)\s+)?'
START_RES = [re.compile(r"^(?:i\s*am\s+|i'?m\s+|im\s+|let'?s\s+|we'?re\s+)?(?:about to\s+|gonna\s+|going to\s+)?"
                        r"(?:starting|start|beginning|begin|going for|go for|going on|go on|heading out for|"
                        r"heading out on|head out for|off for|off on|out for|doing|do|hitting the)\s+" + ART + ADJ + K +
                        r"(?P<tail>.*)$"),
             re.compile(r"^(?:i\s*am\s+|i'?m\s+|im\s+)?(?:going|off|heading out)\s+" + ADJ +
                        r"(?P<k>walking|running|jogging|hiking|biking|cycling|swimming|lifting)(?P<tail>.*)$"),
             re.compile(r"^" + ADJ + K + r"\s+(?:time|starting|started|start)(?P<tail>.*)$")]
DONE_RES = [re.compile(r"^(?:i\s*am\s+|i'?m\s+|im\s+|we'?re\s+|just\s+|all\s+)?(?:just\s+)?(?:done|finished|back|home|through)"
                       r"\s+(?:with|from)\s+" + ART + ADJ + K + r"(?P<tail>.*)$"),
            re.compile(r"^(?:i\s*am\s+|i'?m\s+|im\s+|just\s+)?(?:done|finished|stopped)\s+"
                       r"(?P<k>walking|running|jogging|hiking|biking|cycling|swimming|lifting)(?P<tail>.*)$"),
            re.compile(r"^(?:i\s+)?(?:just\s+)?(?:finished|ended|end|stop|finish)\s+" + ART + ADJ + K + r"(?P<tail>.*)$"),
            re.compile(r"^" + ART + ADJ + K + r"\s+(?:done|finished|over|complete|is done|is over)(?P<tail>.*)$")]
BACK_RE = re.compile(r"^(?:i'?m|i am|im|we'?re)\s+(?:back|home|done)(?:\s+(?:now|home|jarvis))?$")
CANCEL_RE = re.compile(r"^(?:cancel|scrap|forget|never mind|nevermind)\s+" + ART + ADJ + K + r"$")
HOWLONG_RE = re.compile(r"^how long (?:have i been|has my|is my|have we been|am i)\b.*?\b" + K)
NUMS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
SCORE = r"(?P<n>10|[1-9](?:\.5)?|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*(?:out of|/|of)\s*(?:10|ten))?"
FEEL_RE = re.compile(r"^(?:(?:it|that)\s+(?:was|felt)\s+|felt(?: like)?\s+|feels(?: like)?\s+|i'?d say\s+|id say\s+|"
                     r"about\s+|maybe\s+|like\s+|probably\s+|solid\s+|a\s+|an\s+|honestly\s+)*" + SCORE +
                     r"(?:\s+(?:i guess|i think|probably|maybe|jarvis|please))?$")
TAIL_FEEL = re.compile(r"\b(?:felt(?: like)?|feels(?: like)?|it was|that was|rate it|score)\s+(?:(?:a|an|about|like|maybe)\s+)*" + SCORE + r"\b")
SKIP_RE = re.compile(r"^(?:skip|skip it|no|nope|nah|no thanks|no score|pass|not now|don'?t know|dunno|i don'?t know)"
                     r"(?:\s+(?:please|jarvis|thanks|thank you))?$")
TAIL_OK = re.compile(r"^(?:\s+(?:now|right now|please|jarvis|outside|around the block|with the dog|with \w+|today|tonight|"
                     r"this morning|real quick|for a bit|again))*\s*$")


def _clean(text):
    t = (text or '').lower().strip()
    t = re.sub(r'^(hey |ok |okay )?(jarvis|siri)[,.!]?\s*', '', t)
    t = t.replace('’', "'")
    t = re.sub(r'(?<!\d)\.|\.(?!\d)|[!?,;]+', ' ', t)          # keeps "7.5", drops the rest
    return re.sub(r'\s+', ' ', t).strip()


def _kind(word):
    return dict(KINDS).get(word, 'workout')


def _score(word):
    n = NUMS.get(word)
    return n if n is not None else float(word) if '.' in word else int(word)


def _asking(now=None):
    u = STATE['ask_until']
    return bool(u and (now or _now()) <= u)


def parse(text, now=None):
    """Sentence -> {'kind': start | done | feel | skip | cancel | howlong, ...} or None (not ours)."""
    t = _clean(text)
    if not t or re.search(r'\b(?:remind|reminder|timer)\b', t):          # reminders keep their own words
        return None
    for rx in DONE_RES:
        m = rx.match(t)
        if m:
            f = TAIL_FEEL.search(m.group('tail'))
            out = {'kind': 'done', 'what': _kind(m.group('k'))}
            if f:
                out['feel'] = _score(f.group('n'))
            return out
    for rx in START_RES:
        m = rx.match(t)
        if m and TAIL_OK.match(m.group('tail')):
            return {'kind': 'start', 'what': _kind(m.group('k'))}
    m = CANCEL_RE.match(t)
    if m:
        return {'kind': 'cancel', 'what': _kind(m.group('k'))}
    m = HOWLONG_RE.match(t)
    if m:
        return {'kind': 'howlong', 'what': _kind(m.group('k'))}
    if BACK_RE.match(t) and open_row(now=now):                         # "I'm back" means something only mid-walk
        return {'kind': 'done', 'what': None}
    if _asking(now):
        m = FEEL_RE.match(t)
        if m:
            return {'kind': 'feel', 'feel': _score(m.group('n'))}
        if SKIP_RE.match(t):
            return {'kind': 'skip'}
    return None


# ---- the CSV (his to open in Numbers; we only ever add rows or fill blanks in the last ones)
def _rows(path=None):
    try:
        with open(path or LOG, newline='') as f:
            return [r for r in csv.DictReader(f)]
    except OSError:
        return []


def _write(rows, path=None):
    p = path or LOG
    tmp = p + '.tmp'
    with open(tmp, 'w', newline='') as f:
        w = csv.DictWriter(f, HEADER, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, p)                               # all-or-nothing: Numbers never sees half a file


def _started(r):
    try:
        return dt.datetime.strptime(r['Date'] + ' ' + r['Start'], '%Y-%m-%d %H:%M')
    except (KeyError, TypeError, ValueError):
        return None


def _is_open(r):
    return bool(r.get('Start')) and not r.get('End') and not (r.get('Notes') or '').strip()


def open_row(rows=None, now=None, path=None):
    """The workout still going (newest first), or None. Older than STALE_H hours doesn't count."""
    now = now or _now()
    for r in reversed(rows if rows is not None else _rows(path)):
        if _is_open(r):
            s = _started(r)
            if s and dt.timedelta(0) <= now - s <= dt.timedelta(hours=STALE_H):
                return r
    return None


def _clock(t):
    return '%d:%02d' % (t.hour % 12 or 12, t.minute)        # "6:10" -- Siri reads 6:00 as six o'clock


def _mins(n):
    if n < 90:
        return '%d minute%s' % (n, '' if n == 1 else 's')
    h, m = divmod(n, 60)
    return '%d hour%s' % (h, '' if h == 1 else 's') + (' %d minutes' % m if m else '')


def handle(c, s=None, path=None):
    """Does one workout step and returns what Jarvis says. Never touches the lights."""
    c = c if isinstance(c, dict) else (parse(str(c or '')) or {'kind': 'start', 'what': 'workout'})
    kind, now = c.get('kind'), _now()
    p = path or LOG
    rows = _rows(p)
    cur = open_row(rows, now)
    if kind == 'start':
        what = c.get('what') or 'workout'
        if cur:
            since = _started(cur)
            return "You're already on a %s since %s. Say 'done with my %s' first." % (
                KIND_WORDS.get(cur['Kind'], cur['Kind']), _clock(since), cur['Kind'])
        for r in rows:                                # forgotten ones get a note, so they're never "going" again
            if _is_open(r):
                r['Notes'] = 'no end said'
        rows.append({'Date': now.strftime('%Y-%m-%d'), 'Start': now.strftime('%H:%M'), 'End': '', 'Minutes': '',
                     'Kind': what, 'Feel (1-10)': '', 'Notes': ''})
        _write(rows, p)
        STATE.update(ask_until=None, ask_row=None)
        return '%s started at %s. Enjoy it.' % (KIND_WORDS.get(what, what).capitalize(), _clock(now))
    if kind == 'done':
        if not cur:
            what = c.get('what') or 'workout'
            return "I didn't have a %s going, so there's nothing to close. Next time say 'starting a %s'." % (
                KIND_WORDS.get(what, what), what if what != 'bike' else 'bike ride')
        n = max(0, int((now - _started(cur)).total_seconds() // 60))
        cur['End'], cur['Minutes'] = now.strftime('%H:%M'), str(n)
        if c.get('feel') is not None and 1 <= c['feel'] <= 10:
            cur['Feel (1-10)'] = _fmt(c['feel'])
            _write(rows, p)
            STATE.update(ask_until=None, ask_row=None)
            return 'Nice. %s %s, %s out of 10. Logged.' % (_mins(n), KIND_WORDS.get(cur['Kind'], cur['Kind']),
                                                         _fmt(c['feel']))
        _write(rows, p)
        STATE.update(ask_until=now + dt.timedelta(minutes=ASK_MIN), ask_row=(cur['Date'], cur['Start']))
        return 'Nice work. %s %s. How did it feel, 1 to 10?' % (_mins(n), KIND_WORDS.get(cur['Kind'], cur['Kind']))
    if kind in ('feel', 'skip'):
        key = STATE['ask_row']
        STATE.update(ask_until=None, ask_row=None)
        if kind == 'skip':
            return 'Okay, no score. The Watch numbers fill in after the next Health Sync.'
        f = c.get('feel')
        if f is None or not 1 <= f <= 10:
            return 'Give it a number from 1 to 10.'
        for r in rows:
            if key and (r.get('Date'), r.get('Start')) == key:
                r['Feel (1-10)'] = _fmt(f)
                _write(rows, p)
                return 'Got it, %s out of 10. The Watch numbers fill in after the next Health Sync.' % _fmt(f)
        return "I couldn't find that workout in the log, so the score wasn't saved."
    if kind == 'cancel':
        if not cur:
            return "There's no workout going, so nothing to cancel."
        cur['Notes'] = 'cancelled'
        _write(rows, p)
        return 'Okay, %s cancelled.' % KIND_WORDS.get(cur['Kind'], cur['Kind'])
    if kind == 'howlong':
        if not cur:
            return "You don't have a workout going right now."
        n = max(0, int((now - _started(cur)).total_seconds() // 60))
        return '%s so far on your %s. Keep going.' % (_mins(n).capitalize(), KIND_WORDS.get(cur['Kind'], cur['Kind']))
    return None


def _fmt(f):
    return ('%g' % f)


def week_summary(days=7, path=None, now=None):
    """For the selftest / a later briefing line: (count, minutes, average feel or None) over the last N days."""
    now = now or _now()
    cut = (now - dt.timedelta(days=days)).strftime('%Y-%m-%d')
    done = [r for r in _rows(path) if r.get('Date', '') >= cut and r.get('Minutes') and r.get('Notes') != 'cancelled']
    feels = [float(r['Feel (1-10)']) for r in done if (r.get('Feel (1-10)') or '').strip()]
    mins = sum(int(r['Minutes']) for r in done if r['Minutes'].isdigit())
    return len(done), mins, (round(sum(feels) / len(feels), 1) if feels else None)
