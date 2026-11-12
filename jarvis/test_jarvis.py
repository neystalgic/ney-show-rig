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
assert j.handle('strobe it', s, ask=lambda q: 'n', rig=rig) == 'Okay, skipped the light show.' and calls == ['purple', 'status']
j.handle('strobe it', s, ask=lambda q: 'y', rig=rig); assert calls[-1] == 'flash'
d = tempfile.mkdtemp(); p = os.path.join(d, 'w.csv')
assert j.do({'action': 'weight', 'value': 268.4}, s, rig, p) == 'Logged 268.4 pounds.'
assert open(p).read().splitlines()[-1].endswith(',268.4,via Jarvis')
assert j.do({'action': 'weight', 'value': 26.0}, s, rig, p) == 'What number should I log?'
assert j.handle('make it purple', s, dry=True).startswith('[dry] would do: purple')
print('all jarvis tests passed (%d phrases)' % len(cases))

# --- Nov 11 night: schedule commands, several things in one sentence, Siri mode ---
for t, want in {"don't dim until midnight": 'midnight', 'no dimming till 12:30': '12:30', 'push bedtime to 1am': '1am',
                'keep the lights on until 11:30': '11:30'}.items():
    i = j.by_rules(t); assert i and i['action'] == 'later' and i['value'] == want, (t, i)
assert j.by_rules('schedule back to normal')['action'] == 'schedule_normal'
assert j.by_rules('going to bed')['action'] == 'night'           # still bed, not 'later'
assert j.night_time('midnight') == (0, 0) and j.night_time('12:30') == (0, 30) and j.night_time('11:30') == (23, 30)
assert j.night_time('1am') == (1, 0) and j.night_time('10 pm') == (22, 0) and j.night_time('nonsense') is None
import datetime as _dt
sp = os.path.join(d, 'sched.json')
msg = j.push_schedule('midnight', sp, _dt.datetime(2026, 11, 11, 23, 15))
sch = json.load(open(sp)); assert sch['winddown'] == '00:00' and sch['night'] == '00:20' and sch['_expires'] == '2026-11-12 12:00', sch
assert 'midnight' in msg
j.SCHEDULE_FILE = sp
calls.clear()
both = j.understand_all("turn the lights purple and don't start dimming them till midnight", s)
assert [i['action'] for i in both] == ['purple', 'later'], both
out = j.handle("Turn the lights purple and dont start dimming them till midnight", s, rig=rig)
assert calls == ['purple'] and 'midnight' in out, (calls, out)
out = j.handle('show mode', s, rig=rig, confirm=False)
assert calls[-1] == 'show' and out.startswith('Strobes in the drops'), out
assert 'normal' in j.handle('schedule back to normal', s, rig=rig) and open(sp).read().strip() == '{}'
# light_schedule honours / ignores the tonight-only file
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import light_schedule as ls
ls.SETTINGS = sp
json.dump({'winddown': '00:00', 'night': '00:20', '_expires': '2099-01-01 12:00'}, open(sp, 'w'))
assert ls.settings()['winddown'] == '00:00'
json.dump({'winddown': '00:00', 'night': '00:20', '_expires': '2000-01-01 12:00'}, open(sp, 'w'))
assert ls.settings()['winddown'] == '22:30'
print('night tests passed too')
