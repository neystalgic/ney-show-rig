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
    'night':       'Night mode. Heads off, red night light. Sleep well.',
    'heads_on':    'Powering up the heads.',
    'heads_off':   'Parking the heads and powering them off.',
    'bright':      'Bright white.',
    'off':         'Lights off.',
    'wake':        'Waking the Zephyrus.',
    'status':      None,                      # says how the rig is doing
    'weight':      None,                      # logs a weight, needs a number
}
CONFIRM = {'show', 'flash', 'hype', 'strobe'}   # strobe / fast movement: ask first

# Word rules, most specific first. (pattern, action)
RULES = [
    (r'\b(log|weigh|weight)\b.*\b(\d{2,3}(\.\d)?)\b|\b(\d{3}(\.\d)?)\s*(lb|lbs|pounds)\b', 'weight'),
    (r'\bstatus\b|how.*(rig|everything|system).*(doing|going)|you (up|there|alive)', 'status'),
    (r'\bnight ?light\b', 'nightlight'),
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
    (r'\b(cozy|warm)\b', 'cozy'),
    (r'\bmusic mode\b', 'music'),
    (r'\b(bright )?white\b', 'bright'),
    (r'\b(lights? (off|out)|turn (it|them|everything) off|kill the lights)\b', 'off'),
    (r'\bpurple\b|lights? on\b|turn (it|them|the lights?) up|brighter|can.?t see|too dark', 'purple'),
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
    for pat, action in RULES:
        m = re.search(pat, t)
        if m:
            if action == 'weight':
                num = next((g for g in m.groups() if g and re.fullmatch(r'\d{2,3}(\.\d)?', g)), None)
                return {'action': 'weight', 'value': float(num) if num else None}
            return {'action': action, 'value': None}
    return None


SYSTEM = ("You control a home light rig. Reply with JSON only: {\"action\": <one of %s or \"unknown\">, "
          "\"value\": <number for weight, else null>}. Pick the single best action for the user's sentence. "
          "Purple is the owner's favourite colour: use 'purple' for lights on / brighter. Never use 'bright' "
          "(white) unless the user says white. If nothing fits, action is \"unknown\".")


def by_model(text, s, post=None):
    """Ask Ollama. Returns an allowlisted action or None. post() is swappable for tests."""
    body = {'model': s['model'], 'stream': False, 'format': 'json',
            'messages': [{'role': 'system', 'content': SYSTEM % json.dumps(sorted(ACTIONS))},
                         {'role': 'user', 'content': text}],
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
    value = out.get('value')
    if action == 'weight':
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = None
    return {'action': action, 'value': value}


def understand(text, s, post=None):
    return by_rules(text) or by_model(text, s, post) or {'action': 'unknown', 'value': None}


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
    if a == 'unknown':
        return "I didn't catch that. Try: show, movie night, purple, night, or status."
    if a == 'weight':
        if v is None or not 150 <= v <= 400:
            return 'What number should I log?'
        return log_weight(v, weight_path)
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


def handle(text, s, dry=False, ask=input, rig=None):
    intent = understand(text, s)
    log('heard %r -> %s' % (text, intent))
    if dry:
        return '[dry] would do: %s%s' % (intent['action'], '' if intent.get('value') is None else ' %s' % intent['value'])
    if intent['action'] in CONFIRM:
        if ask('That one strobes / moves fast. Everyone seated? (y/n) ').strip().lower()[:1] != 'y':
            return 'Okay, skipped.'
    return do(intent, s, rig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--say', action='store_true')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('-c', dest='command')
    args = ap.parse_args()
    s = settings()
    if args.command:
        out = handle(args.command, s, args.dry)
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
        out = handle(text, s, args.dry)
        print('%s> %s' % (s['name'].lower(), out))
        if args.say:
            say(out, s)


if __name__ == '__main__':
    main()
