"""Jarvis craving support (away loop J3, Nov 15). Lives at jarvis/craving.py once deployed.

  "Jarvis, I'm craving"          -> days clean, one of YOUR reasons, then a calm 4-7-8 breathing count
                                     spoken on the Mac (about a minute), and "want the calm look? say yes"
  "yes" (within 5 minutes)        -> the calm look (setting craving_look, default 'breathe'). Nothing else.
  "no" / "no thanks"              -> lights stay as they are
  "how many days clean" / "my streak" -> the count
  "stop counting"                 -> stops the Mac's breathing count

Your start date and reasons live in jarvis/quit.json (yours to write, gitignored):
  {"start": "2026-11-11", "reasons": ["I want to eat without getting sick", "Clear head for producing"]}
Word rules only (the model never picks this). Never changes the lights unless you say yes.
No medical claims, no lectures: short and kind.
"""
import datetime as dt, json, os, random, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
QUIT_FILE = os.path.join(HERE, 'quit.json')
OFFER_MIN = 5                         # how long a "yes" still means "yes, the calm look"
STATE = {'offer_until': None, 'last_reason': None, 'count': None}
_now = dt.datetime.now                # tests swap this for a fake clock
_rng = random.Random()

# "I'm craving" -- but "I'm craving pizza" is food, not this. So after the word, only these may follow.
TAIL_OK = set('''right now bad badly so really again hard it weed cannabis a joint smoke to get high pot dab hit bowl
 blunt vape the pen today tonight big real kind of still super just me that is pretty help please jarvis rn'''.split())
CRAVE_RE = re.compile(r"\b(?:craving|cravings|urge|urges)\b(.*)$")
WANT_RE = re.compile(r"^(?:i\s+)?(?:really\s+|kinda\s+|kind of\s+)?(?:want|wanna|need)\s+(?:to\s+)?"
                     r"(?:smoke|get high|a joint|a hit|a dab|a bowl|a blunt|some weed|weed|to vape|vape)\b")
STREAK_RE = re.compile(r"\b(?:how many days|how long)\b.*\b(?:clean|sober|off (?:weed|cannabis|it)|quit)\b|"
                       r"\b(?:days clean|my streak|clean streak|quit streak)\b")
STOP_RE = re.compile(r"^(?:please\s+)?stop\s+(?:the\s+)?(?:counting|count|breathing(?: count)?)\b")
YES_RE = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|please|go ahead|do it|sounds good|yes please)"
                    r"(?:\s+(?:please|jarvis|thanks|thank you|the calm look|calm look))?$")
NO_RE = re.compile(r"^(?:no|nope|nah|no thanks|no thank you|not now|i.?m good|i.?m okay|skip it|leave it)"
                   r"(?:\s+(?:please|jarvis|thanks|thank you))?$")

ENCOURAGE = ["This one will pass. You don't have to act on it.", "You've ridden these out before.",
             "Ride it out with me.", "Just this one minute. That's all."]
MILESTONES = {7: 'One full week.', 14: 'Two weeks.', 30: 'A whole month.', 60: 'Two months.', 90: 'Ninety days.',
              100: 'A hundred days.', 182: 'Half a year.', 365: 'A full year.'}


def _clean(text):
    t = (text or '').lower().strip()
    t = re.sub(r'^(hey |ok |okay )?(jarvis|siri)[,.!]?\s*', '', t)
    return re.sub(r'[.!?,]+', ' ', t).strip()


def _offer_open(now=None):
    u = STATE['offer_until']
    return bool(u and (now or _now()) <= u)


def parse(text, now=None):
    """Sentence -> {'kind': craving | yes | no | streak | stop} or None (not ours)."""
    t = _clean(text)
    if not t:
        return None
    if STOP_RE.match(t):
        return {'kind': 'stop'}
    if STREAK_RE.search(t):
        return {'kind': 'streak'}
    m = CRAVE_RE.search(t)
    if m and not re.search(r'\b(?:remind|timer)\b', t):
        tail = re.findall(r"[a-z']+", m.group(1))
        if all(w in TAIL_OK for w in tail):
            return {'kind': 'craving'}
    if WANT_RE.match(re.sub(r"^i.?m\s+", 'i ', t)):
        return {'kind': 'craving'}
    if _offer_open(now):                                   # only right after an offer does "yes" mean the look
        if YES_RE.match(t):
            return {'kind': 'yes'}
        if NO_RE.match(t):
            return {'kind': 'no'}
    return None


def load_quit(path=None):
    try:
        with open(path or QUIT_FILE) as f:
            q = json.load(f)
        return q if isinstance(q, dict) else {}
    except (OSError, ValueError):
        return {}


def days_clean(q, today=None):
    try:
        start = dt.date.fromisoformat(str(q.get('start') or '').strip()[:10])
    except ValueError:
        return None
    n = ((today or _now().date()) - start).days
    return n if n >= 0 else None


def streak_line(q, today=None):
    n = days_clean(q, today)
    if n is None:
        return ''
    if n == 0:
        return "Day one. You're doing it."
    return ('%d day%s clean.' % (n, '' if n == 1 else 's')) + (' ' + MILESTONES[n] if n in MILESTONES else '')


def pick_reason(q):
    rs = [str(r).strip().rstrip('.') for r in (q.get('reasons') or []) if str(r).strip()]
    if not rs:
        return ''
    choices = [r for r in rs if r != STATE['last_reason']] or rs   # never the same one twice in a row
    r = _rng.choice(choices)
    STATE['last_reason'] = r
    return r


def count_script(cycles=3, lead_ms=12000, step_ms=650):
    """The words macOS 'say' speaks: [[slnc N]] = N ms of quiet, so each count is about a second.
    The lead-in lets Siri finish the reply first. 4-7-8 x 3 rounds = about a minute."""
    gap = ' [[slnc %d]] ' % step_ms
    nums = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight']
    out = ['[[slnc %d]] Breathe with me.' % lead_ms]
    for i in range(cycles):
        out.append('[[slnc 1200]] In' + gap + gap.join(nums[1:4]))
        out.append('[[slnc %d]] Hold' % step_ms + gap + gap.join(nums[1:7]))
        out.append('[[slnc %d]] Out, slowly' % step_ms + gap + gap.join(nums[1:8]))
    out.append('[[slnc 1200]] Good. That was a whole minute.')
    return ' '.join(out)


def script_seconds(script, word_s=0.35):
    """Rough length of a count script (for the tests): the silences plus ~0.35 s a word."""
    quiet = sum(int(n) for n in re.findall(r'\[\[slnc (\d+)\]\]', script)) / 1000.0
    words = len(re.findall(r"[A-Za-z,]+", re.sub(r'\[\[.*?\]\]', '', script)))
    return quiet + words * word_s


def _popen(args):
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def stop_count():
    p = STATE['count']
    STATE['count'] = None
    if p is not None and getattr(p, 'poll', lambda: 0)() is None:
        try:
            p.terminate()
        except Exception:
            pass
        return True
    return False


def start_count(s, runner=None):
    """Starts the spoken count on the Mac (never waits for it). Off if jarvis.json has "craving_count": "off"."""
    if str(s.get('craving_count', 'mac')).lower() != 'mac':
        return False
    stop_count()                                           # say "I'm craving" twice -> one count, not two voices
    script = count_script(lead_ms=int(s.get('craving_lead_ms', 12000)))
    try:
        STATE['count'] = (runner or _popen)(['/usr/bin/say', '-v', s.get('voice', 'Moira'), script])
        return True
    except Exception:
        return False


def handle(c, s, rig=None, path=None, runner=None):
    kind = (c or {}).get('kind', 'craving') if isinstance(c, dict) else 'craving'
    now = _now()
    q = load_quit(path)
    if kind == 'stop':
        return 'Okay, stopped counting.' if stop_count() else "I'm not counting right now."
    if kind == 'streak':
        line = streak_line(q, now.date())
        return line or "I don't have your start date yet. Put it in jarvis/quit.json, like \"start\": \"2026-11-11\"."
    if kind == 'no':
        STATE['offer_until'] = None
        return "Okay, lights stay as they are. You've got this."
    if kind == 'yes':
        STATE['offer_until'] = None
        look = s.get('craving_look', 'breathe')
        if not re.fullmatch(r'[a-z_]{2,20}', str(look)):
            look = 'breathe'
        try:
            (rig or (lambda p: None))(look)
        except Exception:
            return "I couldn't reach the lights, but keep breathing with me."
        return 'Calm look on. Breathe with it.'
    parts = []
    streak = streak_line(q, now.date())
    if streak:
        parts.append(streak)
    reason = pick_reason(q)
    parts.append(('Your reason: %s.' % reason) if reason else _rng.choice(ENCOURAGE))
    if start_count(s, runner):
        parts.append('Breathe with me on the Mac: in for 4, hold for 7, out for 8.')
    else:
        parts.append('Breathe with me: in for 4, hold for 7, out for 8. Three rounds.')
    parts.append('Want the calm look? Say yes.')
    if not streak and not reason:
        parts.append('You can add your start date and reasons in jarvis/quit.json.')
    STATE['offer_until'] = now + dt.timedelta(minutes=OFFER_MIN)
    return ' '.join(parts)
