import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jarvis as j
s = dict(j.DEFAULTS)
cases = {
 'show mode': 'show', 'light show please': 'show', 'movie night': 'movienight', 'movie with the stars': 'movieuv',
 'turn on the uv': 'uvstars', 'goodnight': 'night', "I'm going to bed": 'night', 'night light': 'nightlight',
 'make them purple': 'color', 'turn the lights up': 'purple', "I can't see shit": 'purple', 'lights on': 'purple',
 'bright white please': 'color', 'rainbow': 'rainbow', 'strobe it': 'flash', 'lava lamp': 'lava',
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
assert j.handle('make it purple', s, dry=True).startswith('[dry] would do: color')
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
assert [i['action'] for i in both] == ['color', 'later'], both
out = j.handle("Turn the lights purple and dont start dimming them till midnight", s, rig=rig)
assert calls[0].startswith('set:') and 'midnight' in out, (calls, out)
n0 = len(calls); out = j.handle('show mode', s, rig=rig, confirm=False)
assert len(calls) == n0 and 'confirmed' in out, out                    # Siri: no spoken yes -> nothing runs
out = j.handle('light show confirmed', s, rig=rig, confirm=False, voice_yes=True)
assert calls[-1] == 'show' and out.startswith('Confirmed'), out
out = j.handle('light show', s, rig=rig, confirm=False, guest=True)
assert calls[-1] == 'show' and 'Guest mode' in out, out                # rig_control swaps it for the safe show
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
for t in ('light show with the uv stars', 'show mode with stars', 'uv stars light show'):
    assert j.by_rules(t)['action'] == 'showuv', t
assert j.by_rules('movie with the stars')['action'] == 'movieuv'
print('showuv ok')
for t, w in {"I'm producing": 'producing', 'studio mode': 'producing', 'working on a track': 'producing',
             'fill speaker off': 'producing', 'fill back on': 'fillon'}.items():
    assert j.by_rules(t)['action'] == w, t
print('producing ok')

# --- Nov 12: comprehension upgrade ---
assert j.by_rules('Jarvis')['action'] == 'nothing' and j.by_rules('')['action'] == 'nothing'
assert j.by_rules('Jarvis, movie night')['action'] == 'movienight'
i = j.by_rules('make the lights blue at 40 percent'); assert i['action'] == 'color' and i['value'] == {'name': 'blue', 'bri': 40}, i
i = j.by_rules('hot pink'); assert i['value']['name'] == 'hot pink'
i = j.by_rules('dim the lights'); assert i == {'action': 'level', 'value': 30}, i
i = j.by_rules('lights at 70 percent'); assert i == {'action': 'level', 'value': 70}, i
assert j.by_rules('what can you do')['action'] == 'help'
assert j.by_rules('red glow')['action'] == 'redglow' and j.by_rules('purple night lights')['action'] == 'purplenight'
assert j.by_rules('red night light')['action'] == 'nightlight'
calls.clear(); out = j.handle('set it to sky blue at 50 percent', s, rig=rig)
assert out == 'Sky blue, 50 percent.' and json.loads(calls[0][4:])['color']['xy']['x'] == 0.22, (out, calls)
calls.clear(); out = j.handle('warm white', s, rig=rig); assert 'color_temperature' in calls[0]
# model path: colour from mood, says what it heard; junk refused; bare name never acts
out = j.handle('something moody for gaming', s, rig=rig) if False else None
fake_c = lambda url, body, t: {'message': {'content': json.dumps({'action': 'color', 'color': 'purple', 'brightness': 40})}}
i = j.by_model('something moody for gaming', s, fake_c); assert i['action'] == 'color' and i['value'] == {'name': 'purple', 'bri': 40}
fake_bad = lambda url, body, t: {'message': {'content': json.dumps({'action': 'color', 'color': 'chartreuse-ish'})}}
assert j.by_model('x', s, fake_bad) is None
calls.clear(); out = j.handle('Jarvis', s, rig=rig); assert calls == [] and "listening" in out
print('comprehension tests passed')

assert j.by_rules('guest mode')['action'] == 'guest_on' and j.by_rules('friends are over')['action'] == 'guest_on'
assert j.by_rules('guest mode off')['action'] == 'guest_off' and j.by_rules('guests are gone')['action'] == 'guest_off'
print('guest mode tests passed')
