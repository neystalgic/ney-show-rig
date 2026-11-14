import os, sys, tempfile, json, socket
def _offline(*a, **k):
    raise OSError('tests are offline: no network')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = _offline   # no real calls, ever
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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # away copy: repo root is 2 up
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

# --- Nov 13: food logging ---
assert j.parse_food('log 263.8') is None and j.by_rules('log 263.8')['action'] == 'weight'
f = j.parse_food('log half a burger, 600 calories, 35 protein'); assert f == {'item': 'half a burger', 'kcal': 600, 'protein': 35}, f
f = j.parse_food('I ate a banana with peanut butter'); assert f == {'item': 'a banana with peanut butter', 'kcal': None, 'protein': None}, f
f = j.parse_food('log protein shake 160 cal 30g protein'); assert f['kcal'] == 160 and f['protein'] == 30 and f['item'] == 'protein shake', f
assert j.by_rules('log a banana')['action'] == 'food' and j.by_rules('how am I doing today')['action'] == 'today'
assert j.by_rules('i weigh 265')['action'] == 'weight'
import body_log as BL
BL.FOOD = os.path.join(d, 'food.csv'); BL.HEADERS = {BL.FOOD: ['Date', 'Time', 'Item', 'Calories', 'Protein (g)', 'Source']}
j._body_log = lambda: BL
out = j.do({'action': 'food', 'value': {'item': 'half a burger', 'kcal': 600, 'protein': 35}}, s, rig)
assert out.startswith('Logged half a burger: 600 calories, 35 grams of protein.') and '600 calories, 35 grams' in out, out
j.estimate_food = lambda item, s, post=None: (105, 1)
out = j.do({'action': 'food', 'value': {'item': 'a banana', 'kcal': None, 'protein': None}}, s, rig)
assert '(my estimate)' in out and 'Today so far: 705 calories, 36 grams' in out, out
assert 'Today so far: 705 calories' in j.do({'action': 'today'}, s, rig)
print('food logging tests passed')

# --- Nov 14 (away loop): food logging polish ---
assert j.__file__.startswith(os.path.dirname(os.path.abspath(__file__))), j.__file__     # testing the away copy
P = j.parse_food
# the Nov 13 bug: trailing 'about' + numbers joined by 'and'
f = P('I ate a Chipotle chicken quesadilla, about 1050 calories and 60 grams of protein')
assert f == {'item': 'a chipotle chicken quesadilla', 'kcal': 1050, 'protein': 60}, f
f = P('log a smoothie around 1,050 calories roughly 40 grams protein'); assert f == {'item': 'a smoothie', 'kcal': 1050, 'protein': 40}, f
f = P('I had a bagel, like 300 calories.'); assert f == {'item': 'a bagel', 'kcal': 300, 'protein': None}, f
f = P('I had a burrito bowl like'); assert f['item'] == 'a burrito bowl', f
f = P('i ate some pad thai roughly, ...'); assert f['item'] == 'some pad thai', f
# fractions scale estimates only (numbers given = what he ate)
f = P('I ate half the chips and queso'); assert f == {'item': 'half the chips and queso', 'kcal': None, 'protein': None, 'fraction': 0.5, 'base': 'chips and queso'}, f
for said, fr, base in [('I had a third of a pizza', 1 / 3.0, 'pizza'), ('I ate two thirds of the burrito', 2 / 3.0, 'burrito'),
                       ('log a quarter of the cake', 0.25, 'cake'), ('i ate 3/4 of my sandwich', 0.75, 'sandwich'),
                       ('I ate a half of a bagel', 0.5, 'bagel'), ('i had the rest of the chips and queso', 'rest', 'chips and queso')]:
    f = P(said); assert f['fraction'] == fr and f['base'] == base, (said, f)
assert 'fraction' not in P('log a quarter pounder') and 'fraction' not in P('log half a burger, 600 calories, 35 protein')
f = P('I ate the extra chicken'); assert f == {'item': 'extra chicken', 'kcal': None, 'protein': None}, f
# several foods in one sentence -> separate rows; 'X and Y' that is one dish stays together
f = P('I ate the extra chicken and half the chips and queso')
assert [x['item'] for x in f['items']] == ['extra chicken', 'half the chips and queso'], f
assert f['items'][1]['fraction'] == 0.5
f = P('log a burger, fries and a coke'); assert [x['item'] for x in f['items']] == ['a burger', 'fries', 'a coke'], f
f = P('log a burger 700 calories and a coke 140 calories')
assert [(x['item'], x['kcal']) for x in f['items']] == [('a burger', 700), ('a coke', 140)], f
for one in ('log mac and cheese', 'i ate rice and beans', 'log chips and queso', 'log a peanut butter and jelly sandwich'):
    assert 'items' not in P(one), (one, P(one))
assert P('log 263.8') is None and P('log about 500 calories') is None and P('i ate, and') is None
# understand_all hands the whole sentence to the food parser (pieces like 'half the chips' aren't commands)
i = j.understand_all('Jarvis, I ate the extra chicken and half the chips and queso', s)
assert len(i) == 1 and i[0]['action'] == 'food' and len(i[0]['value']['items']) == 2, i
# logging: fresh food log, fake estimates (Ollama is never called)
BL.FOOD = os.path.join(d, 'food2.csv'); BL.HEADERS = {BL.FOOD: ['Date', 'Time', 'Item', 'Calories', 'Protein (g)', 'Source']}
asked = []
EST = {'chips and queso': (1200, 30), 'one extra side portion of chicken': (250, 45), 'pizza': (2400, 100), 'bagel': (300, 11)}
j.estimate_food = lambda item, s, post=None: (asked.append(item), EST.get(item))[1]
rows = lambda: list(__import__('csv').DictReader(open(BL.FOOD)))
out = j.handle('I ate the extra chicken and half the chips and queso', s, rig=rig)
assert asked == ['one extra side portion of chicken', 'chips and queso'], asked
r = rows(); assert [(x['Item'], x['Calories'], x['Protein (g)'], x['Source']) for x in r] == [
    ('extra chicken', '250', '45', 'Jarvis estimate'), ('half the chips and queso', '600', '15', 'Jarvis estimate')], r
assert out.startswith('Logged 2 things: extra chicken: 250 calories, 45 grams of protein (my estimate); and half the chips and queso: 600') \
    and out.endswith('Today so far: 850 calories, 60 grams of protein.'), out
# 'the rest of' works back from the earlier half -> no new estimate needed
asked.clear(); out = j.handle('I had the rest of the chips and queso', s, rig=rig)
assert asked == [] and rows()[-1]['Item'] == 'rest of the chips and queso' and rows()[-1]['Calories'] == '600' and rows()[-1]['Protein (g)'] == '15', rows()[-1]
assert 'the rest of what you logged earlier' in out and 'Today so far: 1450 calories' in out, out
# a third then the rest of a pizza -> two thirds of the whole
j.handle('I ate a third of a pizza', s, rig=rig); assert rows()[-1]['Calories'] == '800', rows()[-1]
j.handle('I ate the rest of the pizza', s, rig=rig); assert rows()[-1]['Calories'] == '1600' and rows()[-1]['Protein (g)'] == '66', rows()[-1]   # 33 logged for the third -> 99 whole
# 'rest of' with nothing earlier -> half an estimate, and it says so
out = j.handle('I ate the rest of the bagel', s, rig=rig)
assert rows()[-1]['Calories'] == '150' and "my estimate; I didn't find the first part" in out, out
# numbers given are kept as said, never scaled
j.handle('log half a burger, 600 calories, 35 protein', s, rig=rig); assert rows()[-1]['Calories'] == '600'
# estimate unavailable -> still logged without numbers, old wording
out = j.handle('I ate a mystery stew', s, rig=rig); assert out.startswith("Logged a mystery stew, but I couldn't estimate it"), out
# model returning bare words / junk for food never crashes
assert 'What did you eat' in j.do({'action': 'food', 'value': None}, s, rig)
print('food polish tests passed (Nov 14)')
