import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jarvis as j
s = dict(j.DEFAULTS)
cases = {
 'show mode': 'show', 'light show please': 'show', 'movie night': 'movienight', 'movie with the stars': 'movieuv',
 'turn on the uv': 'movieuv', 'goodnight': 'night', "I'm going to bed": 'night', 'night light': 'nightlight',
 'make them purple': 'purple', 'turn the lights up': 'purple', "I can't see shit": 'purple', 'lights on': 'purple',
 'bright white please': 'bright', 'rainbow': 'rainbow', 'strobe it': 'flash', 'lava lamp': 'lava',
 'heads off': 'heads_off', 'power the heads on': 'heads_on', 'lights off': 'off', 'status': 'status',
 'how is the rig doing': 'status', 'log 268.4': 'weight', 'I weigh 267': 'weight', '266.5 lbs': 'weight',
 'good morning': 'morning', 'cozy': 'cozy', 'wake the zephyrus': 'wake',
}
bad = [(t, (j.by_rules(t) or {}).get('action'), want) for t, want in cases.items() if (j.by_rules(t) or {}).get('action') != want]
assert not bad, bad
assert j.by_rules('log 268.4')['value'] == 268.4 and j.by_rules('266.5 lbs')['value'] == 266.5
# model fallback: allowlist enforced
fake = lambda content: (lambda url, body, t: {'message': {'content': json.dumps(content)}})
assert j.by_model('vibes for chilling', s, fake({'action': 'breathe'}))['action'] == 'breathe'
assert j.by_model('delete files', s, fake({'action': 'rm -rf'})) is None
assert j.by_model('x', s, lambda *a: (_ for _ in ()).throw(OSError('down'))) is None
assert j.understand('qwerty', s, fake({'action': 'unknown'}))['action'] == 'unknown'
# doing: rig calls + confirmation + weight
calls = []
rig = lambda p: (calls.append(p), json.dumps({'look': 'purple'}))[1]
assert j.do({'action': 'purple'}, s, rig) == j.ACTIONS['purple'] and calls == ['purple']
assert 'purple' in j.do({'action': 'status'}, s, rig)
assert j.handle('strobe it', s, ask=lambda q: 'n', rig=rig) == 'Okay, skipped.' and calls == ['purple', 'status']
j.handle('strobe it', s, ask=lambda q: 'y', rig=rig); assert calls[-1] == 'flash'
d = tempfile.mkdtemp(); p = os.path.join(d, 'w.csv')
assert j.do({'action': 'weight', 'value': 268.4}, s, rig, p) == 'Logged 268.4 pounds.'
assert open(p).read().splitlines()[-1].endswith(',268.4,via Jarvis')
assert j.do({'action': 'weight', 'value': 26.0}, s, rig, p) == 'What number should I log?'
assert j.handle('make it purple', s, dry=True).startswith('[dry] would do: purple')
print('all jarvis tests passed (%d phrases)' % len(cases))
