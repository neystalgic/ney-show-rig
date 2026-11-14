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
# Saved meals ("my usual Chipotle"): jarvis/meals.json -- plain JSON, edit it by hand any time (Nov 14).
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
    'showsafe':    'Photosensitive-safe light show. No strobe, no flashes.',
    'uvstars':     'UV on the stars.',
    'uvoff':       'UV off the stars.',
    'guest_on':    'Guest mode on. Strobes are blocked at the Pi.',
    'guest_off':   'Guest mode off. Strobes allowed again, sparingly.',
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
    'couch':       'Couch mode. Heads off, dim purple, and bedtime is on hold until you say goodnight.',
    'desk':        'Back at the desk. Normal schedule again.',
    'fillon':      'Fill speaker back on.',
    'off':         'Lights off.',
    'wake':        'Waking the Zephyrus.',
    'later':       None,                      # tonight only: no dimming until <time>
    'schedule_normal': None,                  # back to the normal 22:30 / 23:00 schedule
    'food':        None,                      # Nov 13: "log burger, 900 calories, 55 protein" (or estimate)
    'today':       None,                      # today's calories + protein so far
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


FOOD_VERB = re.compile(r'^(log|logged|i ate|ate|i had|had|just ate|i just ate|i just had|eating|i.?m eating)\b\s*', re.I)

# Nov 14 polish: the numbers may come with 'about' in front; leftover filler words never end up in the item name;
# 'half / a third / two thirds of X' scale an estimate; 'the rest of X' finishes something logged earlier;
# several foods in one sentence become separate rows.
_ABOUT = r'(?:\b(?:about|around|roughly|like|approximately|approx|maybe|probably|almost|nearly|over|under)\s+)?~?'
KCAL_RE = re.compile(_ABOUT + r'(\d{1,2},\d{3}|\d{2,4})\s*(?:calories|calorie|cals?|kcal)\b')
PROT_RE = re.compile(_ABOUT + r'(\d{1,3})\s*(?:g|grams?)?\s*(?:of\s*)?protein\b')
FILLER = r'(?:about|around|roughly|like|approximately|approx|maybe|probably|or so|ish|and|with|of|plus|also|then|um|uh|so)'
# a new food starts after a comma, or after 'and / plus / also / then' when the next word sounds like a new portion
# ('the extra chicken and half the chips and queso' -> 2 foods; 'chips and queso' stays one food)
STARTER = r'(?:a|an|the|half|one|two|three|four|five|six|some|my|another|extra|\d+)\b'
SPLIT_RE = re.compile(r'\s*[,;](?!\d{3}\b)\s*|\s+(?:and then|and also|and|plus|also|then)\s+(?=%s)' % STARTER)
FRACTIONS = [                     # (spoken start, fraction) -- checked in this order
    (r'(?:the )?rest of', 'rest'),
    (r'(?:two|2) thirds?|2/3', 2 / 3.0),
    (r'(?:three|3) quarters?|3/4', 0.75),
    (r'(?:a|one|1) third|1/3', 1 / 3.0),
    (r'(?:a|one|1) quarter(?!\s*pound)|1/4', 0.25),
    (r'(?:a |one )?half(?!\s*(?:pound|lb|and half))|1/2', 0.5),
]


def _fraction(label):
    """'half the chips and queso' -> (0.5, 'chips and queso'); 'rest of the pizza' -> ('rest', 'pizza');
    'a burger' -> (None, 'a burger')."""
    for pat, val in FRACTIONS:
        m = re.match(r'(?:%s)\b\s*(?:of\s+)?(?:(?:a|an|the|my)\s+)?' % pat, label)
        if m and re.search(r'[a-z]{2,}', label[m.end():]):
            return val, label[m.end():].strip()
    return None, label


def _tidy(item):
    """Drop stray punctuation and filler words left at either end ('quesadilla about' -> 'quesadilla')."""
    item = re.sub(r"[^a-z0-9'/ -]+", ' ', item.lower())
    prev = None
    while prev != item:
        prev = item
        item = re.sub(r'\s+', ' ', item).strip(" -'")
        item = re.sub(r'\s*\b%s$' % FILLER, '', item)
        item = re.sub(r'^(?:and|plus|also|then|um|uh|so)\b\s*', '', item)
        item = re.sub(r'^the\s+', '', item)                  # 'the extra chicken' -> 'extra chicken'
    return item


def _has_food(chunk):
    c = PROT_RE.sub(' ', KCAL_RE.sub(' ', chunk))
    return bool(re.search(r'[a-z]{2,}', re.sub(r'\b%s\b' % FILLER, ' ', c)))


def _one_food(chunk):
    kc, pr = KCAL_RE.search(chunk), PROT_RE.search(chunk)
    item = chunk
    for m in (kc, pr):
        if m:
            item = item.replace(m.group(0), ' ')
    item = _tidy(item)
    if not re.search(r'[a-z]{2,}', item):
        return None
    f = {'item': item, 'kcal': int(kc.group(1).replace(',', '')) if kc else None, 'protein': int(pr.group(1)) if pr else None}
    if kc is None:                       # numbers given = totals for what he ate; otherwise scale the estimate
        frac, base = _fraction(item)
        if frac is not None:
            f['fraction'], f['base'] = frac, base
    return f


def parse_food(t):
    """'log half a burger, 600 calories, 35 protein' -> {'item':..., 'kcal':600, 'protein':35}. None if it's not food
    (e.g. 'log 263.8' is a weight). Several foods -> {'items': [food, food, ...]}. A food with no numbers and a
    fraction also carries 'fraction' (0.5, 'rest', ...) and 'base' (the food without the fraction words)."""
    t = t.lower().strip(' .!')
    if not FOOD_VERB.match(t) or re.search(r'\b(lb|lbs|pounds|weigh|weight)\b', t):
        return None
    chunks = []
    for c in SPLIT_RE.split(FOOD_VERB.sub('', t)):
        if c is None or not c.strip():
            continue
        if chunks and not _has_food(c):
            chunks[-1] += ' ' + c        # 'about 1050 calories' / '60 grams of protein' belong to the food before
        else:
            chunks.append(c)
    foods = [f for f in (_one_food(c) for c in chunks) if f]
    if not foods:
        return None
    return foods[0] if len(foods) == 1 else {'items': foods}


def estimate_food(item, s, post=None):
    """Local model's guess for a typical portion. None if unavailable or silly."""
    body = {'model': s['model'], 'stream': False, 'format': 'json', 'keep_alive': '3h', 'options': {'temperature': 0},
            'messages': [{'role': 'system', 'content': 'Estimate calories and protein in grams for this food as a typical '
                          'US portion. Reply JSON only: {"calories": int, "protein": int}'},
                         {'role': 'user', 'content': item}]}
    try:
        out = json.loads((post or _post)(s['ollama'] + '/api/chat', body, 30)['message']['content'])
        kc, pr = int(out.get('calories')), int(out.get('protein'))
        if 0 < kc <= 3000 and 0 <= pr <= 250:
            return kc, pr
    except Exception as e:
        log('food estimate failed: %s' % e)
    return None


def _body_log():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import body_log
    return body_log


# --- Nov 14 (away loop): saved meals ----------------------------------------------------------------------------
# "Jarvis, my usual Chipotle" logs the saved numbers instead of a guess; "save that as my usual Chipotle" saves what
# was just logged (one food or several). The list is jarvis/meals.json -- plain JSON, edit it by hand any time:
#   {"meals": [{"name": "chipotle", "kcal": 1050, "protein": 60, "aliases": ["chipotle chicken quesadilla"]}]}
# Saying a name or alias exactly ("I had a chipotle chicken quesadilla") also uses the saved numbers.
MEALS_FILE = os.path.join(HERE, 'meals.json')
USUAL_RE = re.compile(r'^(?:(?:my|the)\s+)?usual\b')
LAST_FOOD = {'when': '', 'foods': []}       # what the last food command logged in this process (for "save that")


def _meal_key(name):
    """'My usual Chipotle!' -> 'chipotle'; 'a chipotle chicken quesadilla' -> 'chipotle chicken quesadilla';
    'the usual' -> 'usual'."""
    k = re.sub(r'^usual\b\s*', '', re.sub(r'^(?:a|an|my|some)\s+', '', _tidy(str(name or ''))))
    return re.sub(r'^(?:a|an|my|some|the)\s+', '', k).strip() or 'usual'


def _usual(name, who='your'):
    return '%s usual' % who if name == 'usual' else '%s usual %s' % (who, name)


def _whole(x):
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return None


def _meals_raw(path=None):
    try:
        with open(path or MEALS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_meals(path=None):
    """The saved meals. A hand-edited file with a typo just means 'no meals', never a crash."""
    raw = _meals_raw(path)
    meals = raw.get('meals', []) if isinstance(raw, dict) else raw
    out = []
    for m in meals if isinstance(meals, list) else []:
        if isinstance(m, dict) and m.get('name'):
            al = m.get('aliases') or []
            m = dict(m, kcal=_whole(m.get('kcal')), protein=_whole(m.get('protein')),
                     aliases=[al] if isinstance(al, str) else [a for a in al if isinstance(a, str)])
            out.append(m)
    return out


def find_meal(said, loose=False, meals=None):
    """The saved meal for what he said, or None. Exact name / alias first. loose=True ("my usual X") also accepts
    the one meal whose words match ('usual chipotle' -> 'chipotle bowl'), or the only saved meal for 'the usual'."""
    meals = load_meals() if meals is None else meals
    key = _meal_key(said)
    names = lambda m: [_meal_key(n) for n in [m['name']] + m['aliases']]
    for m in meals:
        if key in names(m):
            return m
    if loose:
        hits = meals if (key == 'usual' and len(meals) == 1) else \
            [m for m in meals if any(_same_food(key, n) for n in names(m))]
        if len(hits) == 1:
            return hits[0]
    return None


def _last_logged():
    """The Food Log's newest entry (rows written in the same minute count as one meal) -> ('date time', foods)."""
    bl = _body_log()
    rows = [r for r in bl._rows(bl.FOOD) if r.get('Date')]
    if not rows:
        return '', []
    stamp = lambda r: '%s %s' % (r['Date'], r.get('Time') or '')
    when = stamp(rows[-1])
    return when, [{'item': r.get('Item', ''), 'kcal': bl._num(r.get('Calories')), 'protein': bl._num(r.get('Protein (g)'))}
                  for r in rows if stamp(r) == when]


def save_meal(name, path=None):
    """'save that as my usual X': keep what was logged last under X (same name again = update; aliases kept)."""
    name = _meal_key(name)
    when, foods = _last_logged()
    if LAST_FOOD['foods'] and LAST_FOOD['when'] >= when:    # this process logged the newest one: exact numbers
        foods = LAST_FOOD['foods']
    foods = [f for f in foods if f.get('kcal') is not None]
    if not foods:
        return ("I don't have a logged meal with calories to save yet. Log it first, then say 'save that as %s'."
                % _usual(name, 'my'))
    prots = [f['protein'] for f in foods if f.get('protein') is not None]
    meals = load_meals(path)
    old = next((m for m in meals if _meal_key(m['name']) == name), None)
    aliases = list(old['aliases']) if old else []
    if len(foods) == 1:                  # the dish's own name works too: "I had a chipotle chicken quesadilla"
        a = _meal_key(foods[0]['item'])
        if a != name and a not in aliases and a not in {_meal_key(m['name']) for m in meals} and _fraction(a)[0] is None:
            aliases.append(a)
    meal = {'name': name, 'kcal': int(round(sum(f['kcal'] for f in foods))),
            'protein': int(round(sum(prots))) if prots else None, 'aliases': aliases,
            'items': [f['item'] for f in foods], 'saved': dt.date.today().isoformat()}
    raw = _meals_raw(path)
    top = raw if isinstance(raw, dict) else {}             # keep any notes Michael added at the top
    top['meals'] = [m for m in meals if m is not old] + [meal]
    p = path or MEALS_FILE
    with open(p + '.tmp', 'w') as f:
        json.dump(top, f, indent=2)
    os.replace(p + '.tmp', p)                              # never a half-written file
    g = '' if meal['protein'] is None else ', %d grams of protein' % meal['protein']
    return "Saved %s: %d calories%s. Next time just say '%s'." % (
        _usual(name), meal['kcal'], g, 'the usual' if name == 'usual' else _usual(name, 'my'))


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
    (r"^(?:please\s+)?(?:save|remember|store|log)\s+(?:that|this|it|those|these|them)(?:\s+(?:meal|one|food))?\s+as\s+(?P<name>.+)$", 'save_meal'),
    ('__food__', 'food'),
    (r"\b(?:what are|list|read me|tell me)\b.*\b(?:usuals|usual meals|saved meals)\b|\bwhat.?s my usual\b", 'meals'),
    (r"\bhow (am i|i.?m) doing\b|\btoday.?s? (calories|totals|food|numbers|macros)\b|\bcalories (so far|today)\b|\bwhat (have|did) i (eat|eaten|ate)\b", 'today'),
    (r'\b(schedule|bedtime|lights?) back to normal\b|\bnormal schedule\b|\breset (the )?schedule\b', 'schedule_normal'),
    (r"(no dimming|don.?t (start )?dim\w*|push (bed ?time|the schedule|wind ?down)|bed ?time (at|to)|stay up|keep (them|the lights|it) (on|up|bright))"
     r".*?\b(until|till|til|to|at)\s+(?P<when>midnight|\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?)", 'later'),
    (r'\b(log|weigh|weight)\b.*\b(\d{2,3}(\.\d)?)\b|\b(\d{3}(\.\d)?)\s*(lb|lbs|pounds)\b', 'weight'),
    (r'\bstatus\b|how.*(rig|everything|system).*(doing|going)|you (up|there|alive)', 'status'),
    (r'\bpurple\b.*\b(night|bed|sleep)|\b(night|bed|sleep)\w*\b.*\bpurple\b', 'purplenight'),
    (r'\bcouch (mode|session)\b|\b(producing|working|chilling) (on|from) the couch\b|\bi.?m on the couch\b', 'couch'),
    (r'\bback (at|to) (my |the )?desk\b|\bdesk mode\b|\bdocked\b', 'desk'),
    (r"\b(i.?m producing|producing|production mode|studio mode|making (music|beats?)|working on (a |the )?(track|song|beat))\b|\bfill (speaker )?(off|out)\b", 'producing'),
    (r'\bfill (speaker )?(on|back)\b', 'fillon'),
    (r'\bnight ?light\b', 'nightlight'),
    (r'\bguest mode (off|done|over)\b|\b(guests?|company) (are |is )?(gone|left)\b', 'guest_off'),
    (r'\bguest mode\b|\b(guests?|company|friends?) (are |is )?(over|here|coming)\b', 'guest_on'),
    (r'\b(safe|no strobe|without (the )?strobe|photosensitiv\w*|epilep\w*|gentle)\b', 'showsafe'),
    (r'\b(show|party|light ?show)\b.*\b(uv|stars?)\b|\b(uv|stars?)\b.*\b(show|party)\b', 'showuv'),
    (r'\b(uv|stars?)\b.*\b(off|stop)\b|\b(turn )?off (the )?(uv|stars)', 'uvoff'),
    (r'\b(put|turn on|add)\b.*\b(uv|stars?)\b|\buv (on )?(the )?stars\b', 'uvstars'),
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
        if pat == '__food__':
            f = parse_food(t)
            if not f and USUAL_RE.match(t):              # "my usual Chipotle" / "the usual" -- no 'I ate' needed
                f = parse_food('log ' + re.sub(r'\s+please$', '', t))
            if f:
                return {'action': 'food', 'value': f}
            continue
        if pat == '__colour__':
            c = find_colour(t)
            if c:
                return {'action': 'color', 'value': {'name': c, 'bri': find_percent(t)}}
            continue
        m = re.search(pat, t)
        if m:
            if action == 'level':
                return {'action': 'level', 'value': find_percent(t) or 30}
            if action == 'save_meal':
                return {'action': 'save_meal', 'value': m.group('name').strip(' .!')}
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
            'options': {'temperature': 0}, 'keep_alive': '3h'}      # stay loaded: no 10-20 s cold start (Nov 12)
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


def warm(s=None, post=None):
    """Load the model into memory (empty request) so the first real command is fast."""
    s = s or settings()
    try:
        (post or _post)(s['ollama'] + '/api/generate', {'model': s['model'], 'prompt': '', 'keep_alive': '3h'}, 60)
        return True
    except Exception as e:
        log('warm-up failed: %s' % e)
        return False


def understand(text, s, post=None):
    return by_rules(text) or by_model(text, s, post) or {'action': 'unknown', 'value': None}


def understand_all(text, s, post=None):
    """One sentence can ask for a look AND a schedule change. Split on 'and' / 'then' / commas;
    if the word rules understand the pieces, do each (looks first). Otherwise ask the model once."""
    pieces = [p for p in re.split(r'\s*(?:,|\band then\b|\bthen\b|\band\b|\balso\b)\s*', text) if p.strip()]
    found = []
    for p in pieces:
        i = by_rules(p)
        if i and i['action'] != 'nothing' and i not in found:     # 'Jarvis,' on its own is not a command
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


def _same_food(a, b):
    """'chips and queso' ~ 'the chips and queso': same words once articles/fillers are dropped (either way round)."""
    w = lambda x: set(re.findall(r'[a-z]{2,}', x)) - {'the', 'an', 'my', 'and', 'of', 'with', 'some'}
    wa, wb = w(a), w(b)
    return bool(wa and wb) and (wa <= wb or wb <= wa)


def _earlier_part(base, days=2):
    """For 'the rest of X': what share of X was logged today/yesterday, and the whole thing's calories + protein
    worked back from that part. -> (eaten share, whole kcal or None, whole protein or None)."""
    bl = _body_log()
    want = {(dt.date.today() - dt.timedelta(d)).isoformat() for d in range(days)}
    eaten, kc, pr = 0.0, None, None
    for r in bl._rows(bl.FOOD):
        if r.get('Date') not in want:
            continue
        fr, b = _fraction(_tidy(r.get('Item', '')))
        if not isinstance(fr, float) or not _same_food(b, base):
            continue
        eaten += fr
        k, p = bl._num(r.get('Calories')), bl._num(r.get('Protein (g)'))
        if k is not None:
            kc = k / fr
        if p is not None:
            pr = p / fr
    return eaten, kc, pr


def _log_food(f, s):
    """Work out one food's numbers (estimate, fraction, 'rest of'), write the row, return it with a spoken note."""
    f['note'], est, saved, frac = '', False, False, f.pop('fraction', None)
    base = f.pop('base', f['item'])
    if f.get('kcal') is None:
        whole_k = whole_p = None
        usual = bool(USUAL_RE.match(base))
        meal = find_meal(base, loose=usual)
        if usual and meal is None:                # "my usual X" that isn't saved: never guess, log nothing
            f['missing'] = _meal_key(base)
            return f
        if frac == 'rest':
            eaten, whole_k, whole_p = _earlier_part(base)
            if 0 < eaten < 1:
                frac = 1 - eaten
                if whole_k is not None:
                    f['note'] = ' (the rest of what you logged earlier)'
            else:                        # nothing earlier (or he already logged it all): count half a portion
                frac, whole_k, whole_p = 0.5, None, None
                f['note'] = " (I didn't find the first part, so I counted half)"
        if whole_k is None and meal is not None and meal['kcal'] is not None:
            whole_k, whole_p, saved = meal['kcal'], meal['protein'], True
            f['note'] = (' (your saved numbers; ' + f['note'][2:]) if f['note'] else ' (your saved numbers)'
            if usual and frac is None:
                f['item'] = 'usual' if _meal_key(meal['name']) == 'usual' else 'usual ' + _meal_key(meal['name'])
        if whole_k is None:
            ask = ('one extra side portion of ' + base[6:]) if base.startswith('extra ') else base
            guess = estimate_food(ask, s)
            if guess:
                whole_k, whole_p, est = guess[0], guess[1], True
                f['note'] = (' (my estimate; ' + f['note'][2:]) if f['note'] else ' (my estimate)'
        if whole_k is not None:
            m = frac if isinstance(frac, float) else 1.0
            f['kcal'] = int(round(whole_k * m))
            if f.get('protein') is None and whole_p is not None:
                f['protein'] = int(round(whole_p * m))
    _body_log().add_food(f['item'], f.get('kcal'), f.get('protein'), 'Jarvis' + (' estimate' if est else ' usual' if saved else ''))
    return f


def do(intent, s, rig=None, weight_path=WEIGHT_LOG):
    a, v = intent['action'], intent.get('value')
    rig = rig or (lambda p: _rig(p, s))
    if a == 'food':
        if isinstance(v, str):                                   # model gave just the words
            v = parse_food('log ' + v)
        if not isinstance(v, dict):
            return "What did you eat? Say it like 'log a banana' or 'I ate half a burger, 600 calories'."
        logged = []
        for f in (v['items'] if 'items' in v else [v]):
            try:
                logged.append(_log_food(dict(f), s))
            except Exception as e:
                done = (' I did log %s.' % ' and '.join(x['item'] for x in logged)) if logged else ''
                return "I couldn't write the food log (%s). That needs the Mac.%s" % (e.__class__.__name__, done)
        got = [f for f in logged if not f.get('missing')]
        LAST_FOOD.update(when=dt.datetime.now().strftime('%Y-%m-%d %H:%M'), foods=[dict(f) for f in got])
        if not got:
            n = logged[0]['missing']
            return ("I don't have %s saved yet, so I didn't log it. Log it once with the numbers, then say "
                    "'save that as %s'." % (_usual(n), _usual(n, 'my')))
        g = lambda n: '%d gram%s' % (n, '' if n == 1 else 's')
        said = []
        for f in logged:
            if f.get('missing'):
                said.append('%s: not saved yet, so I skipped it' % _usual(f['missing']))
                continue
            if f.get('kcal') is None:
                said.append("%s, but I couldn't estimate it" % f['item'])
            else:
                said.append('%s: %d calories' % (f['item'], f['kcal']) +
                            (', %s of protein' % g(f['protein']) if f.get('protein') is not None else '') + f['note'])
        if len(logged) == 1 and logged[0].get('kcal') is None:
            return "Logged %s, but I couldn't estimate it. Tell me the calories and I'll add them." % logged[0]['item']
        t = _body_log().today()
        head = 'Logged %s.' % said[0] if len(said) == 1 else \
               'Logged %d things: %s; and %s.' % (len(said), '; '.join(said[:-1]), said[-1])
        return '%s Today so far: %d calories, %d grams of protein.' % (head, t['calories'], t['protein'])
    if a == 'save_meal':
        try:
            return save_meal(v or 'usual')
        except Exception as e:
            return "I couldn't save that meal (%s). That needs the Mac." % e.__class__.__name__
    if a == 'meals':
        meals = load_meals()
        if not meals:
            return "No usual meals saved yet. Log one, then say 'save that as my usual' and a name."
        return 'Your usuals: %s.' % '; '.join(_meal_key(m['name']) + ('' if m['kcal'] is None else ', %d calories' % m['kcal'])
                                            for m in meals)
    if a == 'today':
        try:
            t = _body_log().today()
        except Exception as e:
            return "I can't read the food log right now (%s)." % e.__class__.__name__
        if not t['meals']:
            return "Nothing logged today yet. Tell me what you ate, like 'log a banana with peanut butter'."
        extra = (' %d of them without numbers.' % t['unknown']) if t['unknown'] else ''
        return 'Today so far: %d calories and %d grams of protein across %d meals.%s' % (t['calories'], t['protein'], t['meals'], extra)
    if a == 'nothing':
        return "I'm listening. Say what you want after the beep, like 'blue at 50 percent' or 'movie night'."
    if a == 'unknown':
        return "I heard '%s' but I'm not sure what you want. Try a colour, a look, or 'what can you do'." % intent.get('heard', '')
    if a == 'help':
        return ("I can set any colour and brightness, like 'pink at 40 percent'. Looks: light show, show with the stars, "
                "movie night, rainbow, cozy, chill, morning, night light, goodnight. Also heads on or off, lights off, "
                "I'm producing, no dimming until midnight, log your weight or food, my usual meals, and status.")
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


def handle(text, s, dry=False, ask=input, rig=None, confirm=True, voice_yes=False, guest=False):
    intents = understand_all(text, s)
    log('heard %r -> %s' % (text, intents))
    if dry:
        return '[dry] would do: ' + ', '.join(i['action'] + ('' if i.get('value') is None else ' %s' % i['value'])
                                             for i in intents)
    out = []
    for intent in intents:
        if intent['action'] in CONFIRM:
            if guest:
                out.append('Guest mode is on, so you get the safe show: no strobes.')
            elif not confirm and not voice_yes:
                out.append("That one strobes. Make sure everyone's seated, then say it again with 'confirmed', "
                           "like 'light show confirmed'.")
                continue
            elif not confirm:
                out.append('Confirmed. Strobes in the drops only.')
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
