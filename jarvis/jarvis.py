#!/usr/bin/env python3
# =============================================================================
# JARVIS (step 0) -- "Ney", the rig's assistant. Type a sentence, it does ONE safe thing.
#
#   python3 jarvis/jarvis.py              chat (type "quit" to stop)
#   python3 jarvis/jarvis.py --say        ...and it answers out loud (macOS voice)
#   python3 jarvis/jarvis.py --dry        shows what it WOULD do, touches nothing
#   python3 jarvis/jarvis.py -c "movie night"     one command and exit
#
# How it decides: fast word rules first (instant, offline). If none match, it asks the
# local model in Ollama (free, on this Mac, works with the internet off). Whatever the
# model says, it can ONLY pick from the ACTIONS list below -- anything else is refused.
# Strobe / fast-movement looks ask "are you sure?" first.
# Actions go through rig_control (port 7040) with its token, exactly like Siri does.
# Settings (not secret): jarvis/jarvis.json   Log: /tmp/jarvis.log
# =============================================================================
import argparse, datetime as dt, json, os, re, subprocess, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
TOKEN_FILE = os.path.join(RIG, 'rig_control.token')
WEIGHT_LOG = os.path.expanduser('~/Desktop/Weight Log.csv')
DEFAULTS = {'model': 'qwen2.5:7b', 'ollama': 'http://127.0.0.1:11434', 'rig': 'http://127.0.0.1:7040',
            'voice': 'Daniel', 'name': 'Ney'}

# The ONLY things Jarvis can do. look name -> what it says back.
ACTIONS = {
    'purple':      'Purple, full brightness.',
    'show':        'Light show. Everything moves to the music.',
    'showuv':      'Light show with the UV stars. Fan off, everyone seated.',
    'flash':       'Multicolour flash.',
    'hype':        'Hype mode.',
    'music':       'Music mode.',
    'lava':        'Lava lamp show.',
    'rainbow':     'Rainbow breathing, all lamps in sync.',
    'upbeat':      'Upbeat rainbow.',
    'breathe':     'Calm breathing colours.',
    'movienight':  'Movie night.',
    'movieuv':     'Movie night with the UV stars.',
    'movieglow':   'Movie glow.',
    'redglow':     'Red glow.',
    'cozy':        'Cozy.',
    'morning':     'Morning blue.',
    'nightlight':  'Red night light.',
    'purplenight': 'Purple night light. Heads off. Sleep well.',
    'night':       'Night mode. Heads off, red night light. Sleep well.',
    'heads_on':    'Powering up the heads.',
    'heads_off':   'Parking the heads and powering them off.',
    'bright':      'Bright white.',
    'producing':   'Producing mode. Fill speaker off.',
    'fillon':      'Fill speaker back on.',
    'off':         'Lights off.',
    'wake':        'Waking the Zephyrus.',
    'later':       None,                      # tonight only: no dimming until <time>
    'schedule_normal': None,                  # back to the normal 22:30 / 23:00 schedule
    'color':       None,                      # any colour, optional brightness ("blue at 40 percent")
    'level':       None,                      # brightness only ("dim the lights", "50 percent")
    'help':        None,                      # "what can you do"
    'status':      None,                      # says how the rig is doing
    'weight':      None,                      # logs a weight, needs a number
}
CONFIRM = {'show', 'showuv', 'flash', 'hype', 'strobe'}   # strobe / fast movement: ask first

# Any colour by name (Hue xy). White/warm white use colour temperature instead.
COLOURS = {
    'red': (0.69, 0.30), 'orange': (0.60, 0.38), 'amber': (0.56, 0.41), 'gold': (0.52, 0.44),
    'yellow': (0.48, 0.47), 'lime': (0.40, 0.50), 'green': (0.17, 0.70), 'teal': (0.17, 0.40),
    'turquoise': (0.17, 0.36), 'cyan': (0.16, 0.30), 'sky blue': (0.22, 0.27), 'light blue': (0.22, 0.27),
    'blue': (0.15, 0.06), 'navy': (0.15, 0.05), 'indigo': (0.18, 0.06), 'violet': (0.24, 0.09),
    'purple': (0.27, 0.12), 'lavender': (0.29, 0.20), 'magenta': (0.38, 0.16), 'pink': (0.45, 0.23),
    'hot pink': (0.50, 0.24), 'rose': (0.48, 0.28), 'white': 250, 'warm white': 400,
}
COLOUR_RE = re.compile(r'\b(%s)\b' % '|'.join(sorted((re.escape(c) for c in COLOURS), key=len, reverse=True)))


def find_colour(t):
    m = COLOUR_RE.search(t)
    return m.group(1) if m else None


def find_percent(t):
    m = re.search(r'\b(\d{1,3})\s*(%|percent)', t)
    if m:
        return max(1, min(100, int(m.group(1))))
    if re.search(r'\b(dim|dimmer|low|lower|down|soft|softer)\b', t):
        return 30
    if re.search(r'\b(full|max|brightest|all the way up)\b', t):
        return 100
    return None


# Word rules, most specific first. (pattern, action)
RULES = [
    (r'\b(schedule|bedtime|lights?) back to normal\b|\bnormal schedule\b|\breset (the )?schedule\b', 'schedule_normal'),
    (r"(no dimming|don.?t (start )?dim\w*|push (bed ?time|the schedule|wind ?down)|bed ?time (at|to)|stay up|keep (them|the lights|it) (on|up|bright))"
     r".*?\b(until|till|til|to|at)\s+(?P<when>midnight|\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?)", 'later'),
    (r'\b(log|weigh|weight)\b.*\b(\d{2,3}(\.\d)?)\b|\b(\d{3}(\.\d)?)\s*(lb|lbs|pounds)\b', 'weight'),
    (r'\bstatus\b|how.*(rig|everything|system).*(doing|going)|you (up|there|alive)', 'status'),
    (r'\bpurple\b.*\b(night|bed|sleep)|\b(night|bed|sleep)\w*\b.*\bpurple\b', 'purplenight'),
    (r"\b(i.?m producing|producing|production mode|studio mode|making (music|beats?)|working on (a |the )?(track|song|beat))\b|\bfill (speaker )?(off|out)\b", 'producing'),
    (r'\bfill (speaker )?(on|back)\b', 'fillon'),
    (r'\bnight ?light\b', 'nightlight'),
    (r'\b(show|party|light ?show)\b.*\b(uv|stars?)\b|\b(uv|stars?)\b.*\b(show|party)\b', 'showuv'),
    (r'\b(uv|stars?)\b', 'movieuv'),
    (r'\bmovie glow\b', 'movieglow'),
    (r'\bmovie|film|netflix\b', 'movienight'),
    (r'\bheads? (off|down|to bed)\b|park the heads', 'heads_off'),
    (r'\bheads? (on|up)\b|wake the heads', 'heads_on'),
    (r'\b(wake|start|turn on) (the )?zephyrus\b', 'wake'),
    (r'\bred glow\b', 'redglow'),
    (r'\b(good ?night|bed ?time|going to (bed|sleep)|night mode|sleep)\b', 'night'),
    (r'\bmorning\b|\bwake ?up\b', 'morning'),
    (r'\b(light ?show|show mode|party|show time|showtime)\b', 'show'),
    (r'\b(flash|strobe)\b', 'flash'),
    (r'\bhype\b|turn up\b.*\bmusic|go crazy', 'hype'),
    (r'\blava\b', 'lava'),
    (r'\brainbow\b', 'rainbow'),
    (r'\bupbeat\b', 'upbeat'),
    (r'\b(breathe|breathing|calm|chill)\b', 'breathe'),
    (r'\bcozy\b|\bwarm\b(?! white)', 'cozy'),
    (r'\bmusic mode\b', 'music'),
    ('__colour__', 'color'),
    (r'\b(\d{1,3})\s*(%|percent)|\b(dim|dimmer) (the |them|it)|\b(lights?|them|it) (down|lower|dimmer)\b|^dim\b', 'level'),
    (r'what can you do|\bhelp\b|what do you (know|understand)|commands', 'help'),
    (r'\b(lights? (off|out)|turn (it|them|everything) off|kill the lights)\b', 'off'),
    (r'lights? on\b|turn (it|them|the lights?) up|brighter|can.?t see|too dark', 'purple'),
]


def settings():
    s = dict(DEFAULTS)
    try:
        with open(os.path.join(HERE, 'jarvis.json')) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def log(msg):
    try:
        with open('/tmp/jarvis.log', 'a') as f:
            f.write(dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


# -- understanding --
def by_rules(text):
    t = text.lower().strip()
    t = re.sub(r'^(hey |ok |okay )?(jarvis|siri)[,.!]?\s*', '', t)        # "Jarvis, ..." -> the command
    if not re.sub(r'[^a-z0-9]', '', t):
        return {'action': 'nothing', 'value': None}
    for pat, action in RULES:
        if pat == '__colour__':
            c = find_colour(t)
            if c:
                return {'action': 'color', 'value': {'name': c, 'bri': find_percent(t)}}
            continue
        m = re.search(pat, t)
        if m:
            if action == 'level':
                return {'action': 'level', 'value': find_percent(t) or 30}
            if action == 'later':
                return {'action': 'later', 'value': m.group('when')}
            if action == 'weight':
                num = next((g for g in m.groups() if g and re.fullmatch(r'\d{2,3}(\.\d)?', g)), None)
                return {'action': 'weight', 'value': float(num) if num else None}
            return {'action': action, 'value': None}
    return None


SYSTEM = """You are Jarvis, the voice control for Michael's room lights (Hue lamps, moving heads, UV spots).
Turn his sentence into ONE action. Reply with JSON only:
{"action": "<one of the actions below or unknown>", "color": "<colour name or null>", "brightness": <1-100 or null>, "value": <number for weight or null>}
Actions:
- color: set every lamp to one colour (put the colour in "color", brightness if he said one)
- level: change brightness only (put it in "brightness")
- show: full light show to the music. showuv: light show plus UV stars. flash: multicolour strobe. hype: fast bright party.
- music: lights react to music calmly. lava: slow lava-lamp show. rainbow: all lamps one colour, breathing through the rainbow.
- upbeat: bright rainbow drifting. breathe: calm breathing colours. redglow: dim reds/pinks/purples drifting. cozy: warm dim.
- movienight: movie lights. movieuv: movie with UV stars. movieglow: dim movie glow.
- morning: soft blue. nightlight: red night light. purplenight: dim purple night light, heads off. night: bedtime, heads off, red.
- heads_on / heads_off: moving heads power. off: all lights off. producing: fill speaker off for music production. fillon: fill back on.
- status: how the rig is doing. help: what Jarvis can do. later: no dimming until a time (put the time in "value" as text).
Mood words map to looks: chill/relax -> breathe; party/turn up -> hype; romantic -> redglow; focus/work -> color (soft blue, 70);
gaming/moody -> color (purple or blue, 40); sleep -> night. If the sentence is not about the lights, rig or schedule, action is "unknown"."""
def by_model(text, s, post=None):
    """Ask Ollama. Returns an allowlisted action or None. post() is swappable for tests."""
    body = {'model': s['model'], 'stream': False, 'format': 'json',
            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': text}],
            'options': {'temperature': 0}}
    try:
        raw = (post or _post)(s['ollama'] + '/api/chat', body, 30)
        out = json.loads(raw['message']['content'])
    except Exception as e:
        log('model unavailable: %s' % e)
        return None
    action = str(out.get('action', '')).strip().lower()
    if action not in ACTIONS:                     # the allowlist is the law
        return None
    if action == 'color':
        c = str(out.get('color') or '').lower().strip()
        if c not in COLOURS:
            return None
        bri = out.get('brightness')
        return {'action': 'color', 'value': {'name': c, 'bri': int(bri) if isinstance(bri, (int, float)) else None}, 'model': True}
    if action == 'level':
        bri = out.get('brightness')
        return {'action': 'level', 'value': int(bri) if isinstance(bri, (int, float)) else 30, 'model': True}
    value = out.get('value')
    if action == 'weight':
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = None
    return {'action': action, 'value': value, 'model': True}


def understand(text, s, post=None):
    return by_rules(text) or by_model(text, s, post) or {'action': 'unknown', 'value': None}


def understand_all(text, s, post=None):
    """One sentence can ask for a look AND a schedule change. Split on 'and' / 'then' / commas;
    if the word rules understand the pieces, do each (looks first). Otherwise ask the model once."""
    pieces = [p for p in re.split(r'\s*(?:,|\band then\b|\bthen\b|\band\b|\balso\b)\s*', text) if p.strip()]
    found = []
    for p in pieces:
        i = by_rules(p)
        if i and i not in found:
            found.append(i)
    if len(found) > 1:
        return sorted(found, key=lambda i: i['action'] in ('later', 'schedule_normal', 'weight', 'status'))
    i = understand(text, s, post)
    i['heard'] = text
    return [i]


SCHEDULE_FILE = os.path.join(RIG, 'light_schedule.json')


def night_time(when):
    """'midnight' / '12' / '12:30' / '1am' / '11:30' -> (hour, minute), assuming late evening."""
    w = str(when).lower().replace('.', '').strip()
    if w == 'midnight':
        return 0, 0
    m = re.match(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$', w)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if h > 23 or mi > 59:
        return None
    if ap == 'pm' and h < 12:
        h += 12
    elif ap == 'am' and h == 12:
        h = 0
    elif not ap:
        h = 0 if h == 12 else (h + 12 if 6 <= h <= 11 else h)
    return h, mi


def _speak_time(h, mi):
    if (h, mi) == (0, 0):
        return 'midnight'
    return '%d%s %s' % (h % 12 or 12, (':%02d' % mi) if mi else '', 'am' if h < 12 else 'pm')


def push_schedule(when, path=None, now=None):
    t = night_time(when)
    if not t:
        return "What time? Try 'no dimming until midnight'."
    h, mi = t
    night = (h * 60 + mi + 20) % (24 * 60)
    now = now or dt.datetime.now()
    expires = (now + dt.timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    with open(path or SCHEDULE_FILE, 'w') as f:
        json.dump({'winddown': '%02d:%02d' % (h, mi), 'night': '%02d:%02d' % divmod(night, 60),
                   '_expires': expires.strftime('%Y-%m-%d %H:%M'),
                   '_note': 'Tonight only, set by Jarvis. Ignored after _expires.'}, f)
    return 'No dimming until %s. Red wind-down then, night light 20 minutes later. Back to normal tomorrow.' % _speak_time(h, mi)


def normal_schedule(path=None):
    with open(path or SCHEDULE_FILE, 'w') as f:
        f.write('{}\n')
    return 'Schedule back to normal: red wind-down at 10:30, night light at 11.'


# -- doing --
def _post(url, body, timeout):
    req = urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _rig(path, s):
    with open(TOKEN_FILE) as f:
        token = f.read().strip()
    req = urllib.request.Request(s['rig'] + '/' + path, headers={'X-Token': token})
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read().decode('utf-8', 'replace')


def log_weight(value, path=WEIGHT_LOG):
    new = not os.path.exists(path)
    with open(path, 'a') as f:
        if new:
            f.write('Date,Weight (lb),Notes\n')
        f.write('%s,%.1f,via Jarvis\n' % (dt.date.today().isoformat(), value))
    return 'Logged %.1f pounds.' % value


def do(intent, s, rig=None, weight_path=WEIGHT_LOG):
    a, v = intent['action'], intent.get('value')
    rig = rig or (lambda p: _rig(p, s))
    if a == 'nothing':
        return "I'm listening. Say what you want after the beep, like 'blue at 50 percent' or 'movie night'."
    if a == 'unknown':
        return "I heard '%s' but I'm not sure what you want. Try a colour, a look, or 'what can you do'." % intent.get('heard', '')
    if a == 'help':
        return ("I can set any colour and brightness, like 'pink at 40 percent'. Looks: light show, show with the stars, "
                "movie night, rainbow, cozy, chill, morning, night light, goodnight. Also heads on or off, lights off, "
                "I'm producing, no dimming until midnight, log your weight, and status.")
    if a == 'color':
        name, bri = v['name'], v.get('bri') or 100
        c = COLOURS[name]
        body = {'on': {'on': True}, 'dimming': {'brightness': float(bri)}, 'dynamics': {'duration': 800}}
        if isinstance(c, tuple):
            body['color'] = {'xy': {'x': c[0], 'y': c[1]}}
        else:
            body['color_temperature'] = {'mirek': c}
        rig('set:' + json.dumps(body))
        return '%s, %d percent.' % (name.capitalize(), bri)
    if a == 'level':
        rig('set:' + json.dumps({'on': {'on': True}, 'dimming': {'brightness': float(v)}, 'dynamics': {'duration': 800}}))
        return 'Lights at %d percent.' % v
    if a == 'weight':
        if v is None or not 150 <= v <= 400:
            return 'What number should I log?'
        return log_weight(v, weight_path)
    if a == 'later':
        return push_schedule(v)
    if a == 'schedule_normal':
        return normal_schedule()
    if a == 'status':
        try:
            st = json.loads(rig('status'))
            look = st.get('look') or 'nothing'
            return 'Rig is up. Current look: %s.' % look
        except Exception as e:
            return "I can't reach the rig right now (%s)." % e.__class__.__name__
    try:
        rig(a)
    except urllib.error.HTTPError as e:
        return "The rig said no to '%s' (%s %s)." % (a, e.code, e.reason)
    except Exception as e:
        return "I couldn't reach the rig (%s)." % e.__class__.__name__
    return ACTIONS[a]


def say(text, s):
    try:
        subprocess.Popen(['/usr/bin/say', '-v', s['voice'], text])
    except OSError:
        pass


def handle(text, s, dry=False, ask=input, rig=None, confirm=True):
    intents = understand_all(text, s)
    log('heard %r -> %s' % (text, intents))
    if dry:
        return '[dry] would do: ' + ', '.join(i['action'] + ('' if i.get('value') is None else ' %s' % i['value'])
                                             for i in intents)
    out = []
    for intent in intents:
        if intent['action'] in CONFIRM:
            if not confirm:
                out.append('Strobes in the drops, everyone seated.')
            elif ask('That one strobes / moves fast. Everyone seated? (y/n) ').strip().lower()[:1] != 'y':
                out.append('Okay, skipped the light show.')
                continue
        said = do(intent, s, rig)
        if intent.get('model') and intent['action'] not in ('status', 'help'):
            said = "Heard '%s'. %s" % (intent.get('heard', text), said)
        out.append(said)
    return ' '.join(out)


def ask_rig(text, s):
    """Everything goes through rig_control's /ask -- the same brain Siri uses."""
    with open(TOKEN_FILE) as f:
        token = f.read().strip()
    req = urllib.request.Request(s['rig'] + '/ask', json.dumps({'text': text}).encode(),
                                 {'Content-Type': 'application/json', 'X-Token': token})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode('utf-8', 'replace')
    except Exception as e:
        return "I can't reach the rig (%s)." % e.__class__.__name__


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--say', action='store_true')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('-c', dest='command')
    args = ap.parse_args()
    s = settings()
    run = (lambda t: handle(t, s, dry=True)) if args.dry else (lambda t: ask_rig(t, s))
    if args.command:
        out = run(args.command)
        print(out)
        if args.say:
            say(out, s)
        return
    print('%s is listening. Type a command (quit to stop).' % s['name'])
    while True:
        try:
            text = input('you> ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ('quit', 'exit', 'bye'):
            break
        if not text:
            continue
        out = run(text)
        print('%s> %s' % (s['name'].lower(), out))
        if args.say:
            say(out, s)


if __name__ == '__main__':
    main()
