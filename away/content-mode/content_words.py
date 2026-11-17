"""Jarvis words for CONTENT MODE (away loop W5, Nov 17). Word rules only -- the model can never pick it.
  "content mode confirmed" / "filming mode confirmed"  -> on for 5 minutes (needs the word 'confirmed')
  "content mode again" / "more content mode"           -> 5 more minutes (no 'confirmed' needed while it's on,
                                                          or within 10 minutes after the timer ended it)
  "content mode off" / "stop content mode"             -> off now
  "content mode status" / "how long is left on content mode"
The rig decides (guest mode, the timer) and hands back the sentence Jarvis says.
"""
import json, re

WORD = r'\b(content|filming) mode\b'


def parse(t):
    t = (t or '').lower()
    if not re.search(WORD, t):
        return None
    c = bool(re.search(r'\bconfirm(ed)?\b', t))
    if re.search(r'\b(off|stop|done|end|over|finished|cancel|kill)\b|\bno more\b', t):
        return {'op': 'off'}
    if re.search(r'\b(again|more|another|extend|re-?arm|keep going)\b', t):
        return {'op': 'again', 'confirmed': c}
    if re.search(r'\b(status|left|how long|remaining)\b', t):
        return {'op': 'status'}
    return {'op': 'on', 'confirmed': c}


def handle(v, rig):
    if not isinstance(v, dict) or v.get('op') not in ('on', 'again', 'off', 'status'):
        return "I didn't catch that content mode command."
    try:
        said = rig('content:' + json.dumps(v))
    except KeyError:
        return "Content mode isn't installed on the rig yet."
    except Exception as e:
        return "I can't reach the rig (%s)." % e.__class__.__name__
    return said or 'Done.'
