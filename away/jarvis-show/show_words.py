# =============================================================================
# show_words.py -- Jarvis phrases for the show director (away loop W3, Nov 17).
# Lives in jarvis/ next to jarvis.py once Michael deploys it (away/jarvis-show/DEPLOY.txt).
#
#   "lock wave" / "lock the heads" / "hold gobos"  -> show_lock = that act or mode
#   "auto" / "unlock" / "back to auto"             -> show_lock = ''  (the director picks again)
#   "more audio" / "audio only"                    -> show_audio 1.0  (the music's hits drive it)
#   "clock only" / "just the drummer"              -> show_audio 0.0  (the built-in drummer on the beat clock)
#   "normal audio" / "half and half"               -> show_audio 0.6  (the default mix)
#   "less audio" -> 0.3     "audio at 75 percent"  -> 0.75
#   "wave backwards / forwards / bounce / alternate" -> show_wave back / forward / bounce / alternate
#   "loop clockwise / counter clockwise / alternate"  -> show_loop_dir cw / ccw / alternate
#   "acts off" / "modes only"  -> show_acts false     "acts on" -> show_acts true
#   "what's playing"           -> reads act or mode + bar x of 8 + section from the hub's live status
#
# Word rules only: the local model can't pick any of these (nothing added to Jarvis's ACTIONS list).
# Nothing here strobes: locking the BURST act (the drops, flashing on the kick) is refused by voice --
# it stays a console-only button.  Guest mode isn't affected by any of these.
#
# Two halves:
#   parse() + handle()  run inside Jarvis (no network of its own -- it only calls the rig() it's given)
#   rig_side()          runs inside rig_control's ask_jarvis rig(): the SAME allowlist as POST /show/set,
#                       narrowed to these five keys; hub off -> saved in hub_state.json for the next show
#                       (exactly what /show/set does), hub on -> the hub's own 'setting' op.
# =============================================================================
import json, os, re, urllib.request

MODES = ['pulse', 'call', 'wave', 'loop', 'split', 'orbit', 'relay']          # hub_modes.MODES
ACTS = ['hues', 'heads', 'gobos', 'zones', 'uv', 'burst']                      # hub_modes.ACTS
NAMES = {'pulse': 'Pulse', 'call': 'Call and Response', 'wave': 'Wave', 'loop': 'Loop', 'split': 'Split',
         'orbit': 'Orbit', 'relay': 'Relay', 'hues': 'the Hue showcase', 'heads': 'the Head moment',
         'gobos': 'Gobos', 'zones': 'the zone modes', 'uv': 'the UV reveal', 'burst': 'Burst'}
NO_VOICE_LOCK = {'burst'}            # flashes on the kick: never locked by voice

ALLOWED = {                          # key -> allowed values (None = number 0..1)
    'show_lock': [''] + MODES + [a for a in ACTS if a not in NO_VOICE_LOCK],
    'show_wave': ['bounce', 'forward', 'back', 'alternate'],
    'show_loop_dir': ['alternate', 'ccw', 'cw'],
    'show_acts': [True, False],
    'show_audio': None,
}
LIVE_URL = 'http://127.0.0.1:7020/api/live'          # the hub's live snapshot (same one /health + /console read)

# spoken name -> act/mode id (longest first when matching)
ALIASES = {
    'call and response': 'call', 'call & response': 'call', 'call response': 'call', 'call': 'call',
    'pulse': 'pulse', 'wave': 'wave', 'loop': 'loop', 'split': 'split', 'orbit': 'orbit', 'relay': 'relay',
    'head relay': 'relay', 'chase': 'relay',
    'hue showcase': 'hues', 'hues': 'hues', 'hue': 'hues', 'lamps': 'hues', 'bulbs': 'hues',
    'head moment': 'heads', 'moving heads': 'heads', 'heads': 'heads', 'head': 'heads',
    'gobos': 'gobos', 'gobo': 'gobos', 'zone modes': 'zones', 'zones': 'zones', 'zone': 'zones',
    'uv reveal': 'uv', 'uv': 'uv', 'stars': 'uv', 'the stars': 'uv',
    'burst': 'burst', 'drops': 'burst', 'drop': 'burst', 'the drop': 'burst', 'finale': 'burst',
}
_ALIAS_RE = re.compile(r'\b(%s)\b' % '|'.join(re.escape(a) for a in sorted(ALIASES, key=len, reverse=True)))
LOCK_RE = re.compile(r'^(?:please\s+)?(?:lock|hold|stay on|stick with|stick on|lock in)\b\s*(?:it\s+)?(?:on\s+|to\s+|onto\s+)?'
                     r'(?:the\s+)?(?P<what>.+?)\s*(?:please|mode|act|now|for a bit)?[.!]*$')
AUTO_RE = re.compile(r'^(?:please\s+)?(?:(?:go\s+)?back to auto|go auto|auto(?:\s*mode|\s*pilot)?|unlock(?:\s+(?:it|the show|everything|the director))?'
                     r'|let (?:it|the director|the show) (?:pick|choose|decide))(?:\s+please)?[.!]*$')
PLAYING_RE = re.compile(r"\bwhat(?:'s| is|s)\s+(?:playing|the show doing|the director doing)\b|\bwhat (?:act|mode) is (?:this|it|on|playing)\b"
                        r"|\bwhich (?:act|mode)\b|\bwhat (?:act|mode)\b")
AUDIO = [  # (pattern, value) -- checked in order
    (r'\bclock only\b|\bno audio\b|\bjust the (?:clock|drummer)\b|\bdrummer only\b|\bonly the (?:clock|drummer)\b', 0.0),
    (r'\baudio only\b|\bmore audio\b|\bfull audio\b|\ball audio\b|\bjust the music\b|\bonly the music\b', 1.0),
    (r'\b(?:normal|default) (?:audio|mix)\b|\baudio (?:back )?to normal\b|\bhalf and half\b|\breset (?:the )?audio\b', 0.6),
    (r'\bless audio\b|\bmore clock\b|\bmore drummer\b', 0.3),
]
AUDIO_PCT = re.compile(r'\baudio(?: mix)?(?: at| to)?\s+(\d{1,3})\s*(?:%|percent)')
WAVE = [
    (r'\bwave\b.*\b(?:backwards?|back|reverse|reversed)\b|\b(?:reverse|backwards?)\b.*\bwave\b', 'back'),
    (r'\bwave\b.*\bforwards?\b|\bforwards?\b.*\bwave\b', 'forward'),
    (r'\bwave\b.*\balternat\w*\b|\balternat\w* wave\b', 'alternate'),
    (r'\bbounc\w*\b', 'bounce'),
]
LOOP = [
    (r'\b(?:counter|anti)[- ]?clockwise\b', 'ccw'),
    (r'\bclockwise\b', 'cw'),
    (r'\bloop\b.*\balternat\w*\b|\balternat\w*\b.*\bloop\b', 'alternate'),
]
ACTS_OFF = re.compile(r'\bacts? (?:off|out)\b|\bno (?:more )?acts\b|\b(?:just|only) (?:the )?modes\b|^modes only\b|\bzone modes only\b')
ACTS_ON = re.compile(r'\bacts? (?:on|back)\b|\bbring (?:the )?acts back\b')
WAVE_SAY = {'back': 'Wave runs backwards.', 'forward': 'Wave runs forwards.', 'bounce': 'Wave bounces back and forth.',
            'alternate': 'Wave alternates direction.'}
LOOP_SAY = {'cw': 'Loop goes clockwise.', 'ccw': 'Loop goes counter clockwise.', 'alternate': 'Loop alternates direction.'}


def parse(t):
    """A sentence -> {'set': {...}, 'say': '...'} | {'ask': 'playing'} | {'refuse': '...'} | None."""
    t = (t or '').lower().strip()
    t = re.sub(r'^(?:hey |ok |okay )?(?:jarvis|siri)[,.!]?\s*', '', t).strip(' .!?')
    if not t:
        return None
    if PLAYING_RE.search(t):
        return {'ask': 'playing'}
    m = LOCK_RE.match(t)
    if m:
        a = _ALIAS_RE.search(m.group('what'))
        if a:
            what = ALIASES[a.group(1)]
            if what in NO_VOICE_LOCK:
                return {'refuse': "Burst is the drop -- it flashes on the kick, so I won't lock it by voice. "
                                  "It still plays in the drops, or lock it from the console."}
            return {'set': {'show_lock': what}, 'say': 'Locked on %s.' % NAMES[what]}
        return None                                  # "hold on" etc. -- not ours
    if AUTO_RE.match(t):
        return {'set': {'show_lock': ''}, 'say': 'Auto. The director picks again every 8 bars.'}
    m = AUDIO_PCT.search(t)
    if m:
        pct = min(int(m.group(1)), 100)
        return {'set': {'show_audio': round(pct / 100.0, 2)}, 'say': 'Audio mix at %d percent.' % pct}
    for pat, val in AUDIO:
        if re.search(pat, t):
            say = {0.0: 'Clock only. The built-in drummer drives it.', 1.0: 'Audio only. The music drives it.',
                   0.6: 'Normal mix: 60 percent audio.', 0.3: 'Less audio: 30 percent.'}[val]
            return {'set': {'show_audio': val}, 'say': say}
    if ACTS_OFF.search(t):
        return {'set': {'show_acts': False}, 'say': 'Acts off. Zone modes only.'}
    if ACTS_ON.search(t):
        return {'set': {'show_acts': True}, 'say': 'Acts back on.'}
    if re.search(r'\bloop\b|\bclockwise\b', t):
        for pat, val in LOOP:
            if re.search(pat, t):
                return {'set': {'show_loop_dir': val}, 'say': LOOP_SAY[val]}
    if re.search(r'\bwave\b|\bbounc', t):
        for pat, val in WAVE:
            if re.search(pat, t):
                return {'set': {'show_wave': val}, 'say': WAVE_SAY[val]}
    return None


def handle(v, rig):
    """Jarvis side: what Jarvis says back.  rig() is rig_control's (or a test fake)."""
    if not isinstance(v, dict):
        return "I didn't catch the show setting. Try 'lock gobos', 'auto' or 'what's playing'."
    if v.get('refuse'):
        return v['refuse']
    try:
        if v.get('ask') == 'playing':
            return playing(json.loads(rig('show_status') or '{}'))
        r = rig('show:' + json.dumps(v['set']))
    except KeyError:
        return "The rig doesn't know show settings yet -- rig_control needs the show-phrases update."
    except ValueError:
        return "The rig said no to that show setting."
    except Exception as e:
        return "I couldn't reach the show (%s)." % e.__class__.__name__
    say = v.get('say') or 'Done.'
    if str(r).strip() == 'saved':
        say += " The hub is off, so that's saved for the next show."
    return say


def playing(st):
    """Hub live status -> one spoken line."""
    if not isinstance(st, dict) or not st.get('hub'):
        return "The hub isn't running, so nothing's playing. Say 'show modes' to start the show."
    show = st.get('show') if isinstance(st.get('show'), dict) else {}
    if not show.get('on') or show.get('pattern') != 'modes':
        p = show.get('pattern')
        now = ' The head relay is running.' if p in ('show', 'relay') else ''
        return "Show modes are off right now.%s Say 'show modes' to start them." % now
    label = show.get('name') or show.get('act_name') or 'the show'
    out = 'Playing %s, bar %s of %s' % (label, show.get('bar') or 1, show.get('bars') or 8)
    if show.get('section'):
        out += ', %s' % show['section']
    lock = str(show.get('lock') or '')
    out += ('. Locked on %s.' % NAMES.get(lock, lock)) if lock else '. Auto picks the next one.'
    return out


# ---------------------------------------------------------------- rig_control side
def check(data):
    """Raises ValueError unless every key/value is on the voice allowlist."""
    if not isinstance(data, dict) or not data:
        raise ValueError('empty')
    for k, v in data.items():
        if k not in ALLOWED:
            raise ValueError('not allowed: %s' % k)
        ok = ALLOWED[k]
        if ok is None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
                raise ValueError('bad value for %s' % k)
        elif k == 'show_acts':
            if not isinstance(v, bool):
                raise ValueError('bad value for %s' % k)
        elif not isinstance(v, str) or v not in ok:
            raise ValueError('bad value for %s' % k)
    return data


def fetch_live(timeout=1.5):
    """The hub's live snapshot, or None (short timeout, never hangs)."""
    try:
        d = json.loads(urllib.request.urlopen(LIVE_URL, timeout=timeout).read())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def save_for_next(data, here):
    """Hub off: the same thing POST /show/set does -- merge into hub_state.json settings (atomic write)."""
    sp = os.path.join(here, 'hub_state.json')
    try:
        with open(sp) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    if not isinstance(st, dict):
        st = {}
    st.setdefault('settings', {}).update(data)
    with open(sp + '.tmp', 'w') as f:
        json.dump(st, f, indent=1)
    os.replace(sp + '.tmp', sp)


def rig_side(p, hub_up, hub_setting, here, live_fn=fetch_live):
    """Called from rig_control's ask_jarvis rig() for 'show_status' and 'show:{json}'."""
    if p == 'show_status':
        live = live_fn()
        show = (live or {}).get('show') if isinstance(live, dict) else None
        keep = ('on', 'pattern', 'act', 'act_name', 'mode', 'name', 'bar', 'bars', 'lock', 'section')
        return json.dumps({'hub': isinstance(live, dict),
                           'show': {k: show.get(k) for k in keep} if isinstance(show, dict) else None})
    if not p.startswith('show:'):
        raise KeyError(p)
    try:
        data = json.loads(p[5:])
    except ValueError:
        raise ValueError('not JSON')
    check(data)
    if not hub_up():
        save_for_next(data, here)
        return 'saved'
    for k, v in data.items():
        hub_setting(k, v)
    return 'set'
