"""Offline tests for the Jarvis show phrases (away loop W3, Nov 17).
  python3 away/jarvis-show/test_show_words.py
Fakes only: fake rig, fake hub (hub_up / hub_setting), fake live status, temp hub_state.json.
The network is blocked for this process. Live files are only READ (copied to a temp folder to test the patch)
and their hashes are checked before/after."""
import hashlib, json, os, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)


def _no_net(*a, **k):
    raise OSError('network blocked in tests')
socket.socket.connect = _no_net
socket.create_connection = _no_net

import show_words as sw
import apply_patches as ap

N = [0]
BAD = []


def ok(cond, what):
    N[0] += 1
    if not cond:
        BAD.append(what)
        print('FAIL', what)


def sha(p):
    try:
        return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    except OSError:
        return None

LIVE = ['jarvis/jarvis.py', 'rig_control.py', 'selftest.py', 'hub_state.json']
before = {p: sha(os.path.join(REPO, p)) for p in LIVE}

# ---------------------------------------------------------------- 1. phrases
SETS = {
    'lock wave': {'show_lock': 'wave'}, 'Jarvis, lock the heads': {'show_lock': 'heads'},
    'lock gobos': {'show_lock': 'gobos'}, 'hold the gobos please': {'show_lock': 'gobos'},
    'lock on orbit': {'show_lock': 'orbit'}, 'lock call and response': {'show_lock': 'call'},
    'stick with the hue showcase': {'show_lock': 'hues'}, 'lock the uv reveal': {'show_lock': 'uv'},
    'lock zones': {'show_lock': 'zones'}, 'lock relay': {'show_lock': 'relay'}, 'lock pulse': {'show_lock': 'pulse'},
    'auto': {'show_lock': ''}, 'unlock': {'show_lock': ''}, 'back to auto': {'show_lock': ''},
    'unlock the show': {'show_lock': ''}, 'let the director pick': {'show_lock': ''}, 'auto mode please': {'show_lock': ''},
    'more audio': {'show_audio': 1.0}, 'audio only': {'show_audio': 1.0}, 'clock only': {'show_audio': 0.0},
    'just the drummer': {'show_audio': 0.0}, 'normal audio': {'show_audio': 0.6}, 'half and half': {'show_audio': 0.6},
    'less audio': {'show_audio': 0.3}, 'audio at 75 percent': {'show_audio': 0.75}, 'audio to 40%': {'show_audio': 0.4},
    'wave backwards': {'show_wave': 'back'}, 'reverse the wave': {'show_wave': 'back'},
    'wave forwards': {'show_wave': 'forward'}, 'bounce': {'show_wave': 'bounce'}, 'make the wave bounce': {'show_wave': 'bounce'},
    'alternating wave': {'show_wave': 'alternate'},
    'loop clockwise': {'show_loop_dir': 'cw'}, 'loop counter clockwise': {'show_loop_dir': 'ccw'},
    'loop anticlockwise': {'show_loop_dir': 'ccw'}, 'loop counter-clockwise': {'show_loop_dir': 'ccw'},
    'alternate the loop': {'show_loop_dir': 'alternate'},
    'acts off': {'show_acts': False}, 'modes only': {'show_acts': False}, 'just the modes': {'show_acts': False},
    'acts on': {'show_acts': True}, 'bring the acts back': {'show_acts': True},
}
for t, want in SETS.items():
    got = sw.parse(t)
    ok(got and got.get('set') == want and got.get('say'), 'parse %r -> %s (got %s)' % (t, want, got))
    if got and got.get('set'):
        try:
            sw.check(got['set'])
            ok(True, '')
        except ValueError as e:
            ok(False, 'parse output fails its own allowlist: %r %s' % (t, e))
for t in ("what's playing", 'whats playing', 'what is playing', 'what mode is this', 'which act', "Jarvis, what's playing?"):
    ok(sw.parse(t) == {'ask': 'playing'}, 'playing %r' % t)
for t in ('lock burst', 'lock the drop', 'hold the drops'):
    r = sw.parse(t)
    ok(r and 'refuse' in r and 'set' not in r, 'burst refused %r (got %s)' % (t, r))
for t in ('hold on', 'light show', 'movie night', 'show modes', 'show modes off', 'head relay', 'stop the relay', 'goodnight',
          'purple', 'heads off', 'log 268.4', "I'm craving", 'remind me at 9 to take my meds', '50 percent', 'auto start the hub',
          'lock the door', 'starting a walk', 'more light', 'the stars', 'uv on the stars', 'what can you do', 'status', ''):
    ok(sw.parse(t) is None, 'not ours: %r (got %s)' % (t, sw.parse(t)))

# ---------------------------------------------------------------- 2. allowlist (rig side)
for good in ({'show_lock': ''}, {'show_lock': 'gobos'}, {'show_audio': 0}, {'show_audio': 1.0}, {'show_acts': False},
             {'show_wave': 'back', 'show_loop_dir': 'cw'}):
    try:
        sw.check(good); ok(True, '')
    except ValueError:
        ok(False, 'allowlist refused good %s' % good)
for bad in ({'show_lock': 'burst'}, {'show_lock': 'strobe'}, {'dmx_strobe': 'always'}, {'show_audio': 2}, {'show_audio': -0.1},
            {'show_audio': True}, {'show_audio': '1'}, {'show_acts': 1}, {'show_wave': 'sideways'}, {'show_loop_dir': 'up'},
            {'energy': 1.0}, {'dmx_pattern': 'modes'}, {}, [], {'show_lock': None}):
    try:
        sw.check(bad); ok(False, 'allowlist let through %s' % bad)
    except ValueError:
        ok(True, '')

tmp = tempfile.mkdtemp(prefix='showwords_')
hs = os.path.join(tmp, 'hub_state.json')
json.dump({'look': 'x', 'settings': {'show_speed': 1.2}}, open(hs, 'w'))
calls = []
up = [False]
r = sw.rig_side('show:' + json.dumps({'show_lock': 'wave'}), lambda: up[0], lambda k, v: calls.append((k, v)), tmp)
st = json.load(open(hs))
ok(r == 'saved' and not calls and st['settings'] == {'show_speed': 1.2, 'show_lock': 'wave'} and st['look'] == 'x',
   'hub off -> saved in hub_state.json, other keys kept (%s %s)' % (r, st))
ok(not os.path.exists(hs + '.tmp'), 'no .tmp left behind')
os.remove(hs)
sw.rig_side('show:{"show_acts": false}', lambda: False, None, tmp)
ok(json.load(open(hs)) == {'settings': {'show_acts': False}}, 'hub off + no hub_state.json -> created')
up[0] = True
r = sw.rig_side('show:' + json.dumps({'show_wave': 'back', 'show_audio': 0.6}), lambda: up[0], lambda k, v: calls.append((k, v)), tmp)
ok(r == 'set' and sorted(calls) == [('show_audio', 0.6), ('show_wave', 'back')], 'hub on -> hub_setting per key (%s)' % calls)
for p in ('show:' + json.dumps({'show_lock': 'burst'}), 'show:{"dmx_strobe": "always"}', 'show:nonsense'):
    n0 = len(calls)
    try:
        sw.rig_side(p, lambda: True, lambda k, v: calls.append((k, v)), tmp); ok(False, 'rig_side let through %s' % p)
    except ValueError:
        ok(len(calls) == n0, 'rig_side refused %s, nothing sent' % p)
try:
    sw.rig_side('purple', lambda: True, None, tmp); ok(False, 'rig_side took a look name')
except KeyError:
    ok(True, '')
LIVE_ON = {'show': {'on': True, 'pattern': 'modes', 'act': 'gobos', 'act_name': 'Gobos', 'mode': 'wave', 'name': 'Gobos',
                    'bar': 3, 'bars': 8, 'lock': '', 'section': 'groove', 'head_out': {'1': [1, 2, 3]}}, 'level': 0.4}
s1 = json.loads(sw.rig_side('show_status', None, None, tmp, live_fn=lambda: LIVE_ON))
ok(s1['hub'] and s1['show']['act'] == 'gobos' and 'head_out' not in s1['show'], 'show_status: named fields only (%s)' % s1)
s2 = json.loads(sw.rig_side('show_status', None, None, tmp, live_fn=lambda: None))
ok(s2 == {'hub': False, 'show': None}, 'show_status: hub off')
ok(sw.fetch_live(timeout=0.2) is None, 'fetch_live with no network -> None, no hang')

# ---------------------------------------------------------------- 3. what Jarvis says
said = sw.playing(json.loads(json.dumps(s1)))
ok(said == 'Playing Gobos, bar 3 of 8, groove. Auto picks the next one.', 'playing line: %s' % said)
lk = dict(LIVE_ON['show'], act='zones', name='Wave', lock='wave', section='')
ok(sw.playing({'hub': True, 'show': lk}) == 'Playing Wave, bar 3 of 8. Locked on Wave.', 'playing locked: %s' % sw.playing({'hub': True, 'show': lk}))
ok('nothing' in sw.playing({'hub': False, 'show': None}), 'playing: hub off')
ok('Show modes are off' in sw.playing({'hub': True, 'show': dict(lk, pattern='normal')}), 'playing: modes off')
ok('head relay' in sw.playing({'hub': True, 'show': dict(lk, pattern='show')}), 'playing: relay running')
seen = []
fake = lambda p: (seen.append(p), 'set')[1]
ok(sw.handle(sw.parse('lock gobos'), fake) == 'Locked on Gobos.' and seen[-1] == 'show:{"show_lock": "gobos"}', 'handle set')
ok(sw.handle(sw.parse('clock only'), lambda p: 'saved').endswith('saved for the next show.'), 'handle saved')
ok('lock it from the console' in sw.handle(sw.parse('lock burst'), lambda p: 1 / 0), 'handle refuse, rig never called')
def old_rig(p):
    raise KeyError(p)
ok('needs the show-phrases update' in sw.handle(sw.parse('auto'), old_rig), 'handle: rig_control not updated yet')
ok("couldn't reach" in sw.handle(sw.parse('auto'), lambda p: (_ for _ in ()).throw(OSError('down'))), 'handle: rig down')

# ---------------------------------------------------------------- 4. the install, on temp copies
def make_root():
    root = tempfile.mkdtemp(prefix='showroot_')
    os.makedirs(os.path.join(root, 'jarvis'))
    for name in os.listdir(os.path.join(REPO, 'jarvis')):
        if name.endswith('.py') or name in ('meals.json', 'jarvis.json'):
            shutil.copy2(os.path.join(REPO, 'jarvis', name), os.path.join(root, 'jarvis', name))
    for name in ('rig_control.py', 'selftest.py', '.gitignore', 'light_schedule.py', 'body_log.py'):
        shutil.copy2(os.path.join(REPO, name), os.path.join(root, name))
    return root

def quiet(fn, *a):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = fn(*a)
        except SystemExit as e:
            rc = 'STOP: %s' % e
    return rc, buf.getvalue()

root = make_root()
rc, out = quiet(ap.main, root)
ok(rc == 0 and 'patched' in out or 'already' in out, 'apply_patches ran: %s %s' % (rc, out))
jt = open(os.path.join(root, 'jarvis', 'jarvis.py')).read()
rt = open(os.path.join(root, 'rig_control.py')).read()
ok(ap.MARK in jt and ap.MARK in rt and ap.MARK in open(os.path.join(root, 'selftest.py')).read(), 'all three files carry the mark')
ok(os.path.exists(os.path.join(root, 'jarvis', 'show_words.py')), 'show_words.py copied')
i_def, i_hook, i_looks = rt.find('def ask_jarvis'), rt.find("show_words.rig_side(p, hub_up, hub_setting, HERE)"), rt.find('        if p not in LOOKS:')
ok(0 < i_def < i_hook < i_looks, 'rig_control hook sits inside ask_jarvis rig(), before the LOOKS check')
ok("'show_set'" not in jt.split('ACTIONS = {')[1].split('}')[0], 'model allowlist (ACTIONS) unchanged')
rc2, out2 = quiet(ap.main, root)
ok(out2.count('already patched') == 3, 'second run says already (%s)' % out2)
# anchor moved -> nothing written
r2 = make_root()
p = os.path.join(r2, 'rig_control.py')
open(p, 'w').write(open(p).read().replace('        if p not in LOOKS:', '        if p not in LOOKS_X:'))
j0 = sha(os.path.join(r2, 'jarvis', 'jarvis.py'))
rc3, out3 = quiet(ap.main, r2)
ok(str(rc3).startswith('STOP') and sha(os.path.join(r2, 'jarvis', 'jarvis.py')) == j0
   and not os.path.exists(os.path.join(r2, 'jarvis', 'show_words.py')), 'moved anchor -> STOP, nothing written')

# patched Jarvis end-to-end, in a subprocess (fresh imports from the temp copy)
DRIVER = r'''
import json, os, sys, socket
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(OSError('blocked'))
sys.path.insert(0, os.path.join(sys.argv[1], 'jarvis'))
import jarvis as j
s = dict(j.DEFAULTS)
phr = json.loads(sys.argv[2])
out = {'rules': {t: j.by_rules(t) for t in phr}}
if len(sys.argv) > 3:
    import show_words as sw
    hub, looks = [], []
    def rig(p):
        if p == 'show_status' or p.startswith('show:'):
            return sw.rig_side(p, lambda: True, lambda k, v: hub.append([k, v]), sys.argv[1],
                               live_fn=lambda: {'show': {'on': True, 'pattern': 'modes', 'name': 'Orbit', 'bar': 5, 'bars': 8,
                                                         'lock': 'orbit', 'section': 'breakdown'}})
        looks.append(p); return ''
    said = {}
    for t in ['lock the heads', 'acts off and loop clockwise', 'lock call and response', "what's playing", 'lock burst',
              'auto', 'more audio', 'wave backwards', 'purple', 'what can you do']:
        said[t] = j.handle(t, s, rig=rig, confirm=False)
    out.update(said=said, hub=hub, looks=looks)
print(json.dumps(out))
'''
dpath = os.path.join(tempfile.mkdtemp(prefix='showdrv_'), 'driver.py')
open(dpath, 'w').write(DRIVER)
PHR = ['show mode', 'movie night', 'goodnight', 'show modes', 'show modes off', 'head relay', 'stop the relay', 'purple',
       'heads off', 'heads on', 'log 268.4', 'rainbow', 'strobe it', 'turn on the uv', 'movie with the stars', 'light show confirmed',
       'guest mode', 'night light', 'blue at 40 percent', 'lights off', 'status', 'what can you do', 'cozy', 'chill',
       "don't dim until midnight", 'brief me', 'I ate a banana, 100 calories', 'remind me at 9 to take my meds', 'hold on']
orig = make_root()
def run(root, extra=False):
    a = [sys.executable, dpath, root, json.dumps(PHR)] + (['go'] if extra else [])
    p = subprocess.run(a, capture_output=True, text=True, timeout=120, cwd=root)
    if p.returncode:
        print(p.stderr[-800:])
    return json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else {}
A, B = run(orig), run(root, True)
ok(A and B and A['rules'] == B['rules'], 'existing phrases understood exactly as before (%s)'
   % [t for t in PHR if A.get('rules', {}).get(t) != B.get('rules', {}).get(t)])
said = B.get('said', {})
ok(said.get('lock the heads') == 'Locked on the Head moment.', 'e2e lock heads: %s' % said.get('lock the heads'))
ok(said.get('acts off and loop clockwise') == 'Acts off. Zone modes only. Loop goes clockwise.', 'e2e two in one: %s' % said.get('acts off and loop clockwise'))
ok(said.get('lock call and response') == 'Locked on Call and Response.', 'e2e call and response: %s' % said.get('lock call and response'))
ok(said.get("what's playing") == 'Playing Orbit, bar 5 of 8, breakdown. Locked on Orbit.', 'e2e playing: %s' % said.get("what's playing"))
ok('console' in said.get('lock burst', ''), 'e2e burst refused')
ok('lock gobos' in said.get('what can you do', ''), 'help line mentions the show phrases')
ok(B.get('hub') == [['show_lock', 'heads'], ['show_acts', False], ['show_loop_dir', 'cw'], ['show_lock', 'call'],
                    ['show_lock', ''], ['show_audio', 1.0], ['show_wave', 'back']], 'exact hub settings sent: %s' % B.get('hub'))
ok(B.get('looks') == ['set:' + json.dumps({'on': {'on': True}, 'dimming': {'brightness': 100.0}, 'dynamics': {'duration': 800},
                                           'color': {'xy': {'x': 0.27, 'y': 0.12}}})] or (len(B.get('looks', [])) == 1),
   'only the purple look reached the looks path: %s' % B.get('looks'))

# Jarvis's own test suite on the patched copy
p = subprocess.run([sys.executable, os.path.join(root, 'jarvis', 'test_jarvis.py')], capture_output=True, text=True,
                   timeout=200, cwd=os.path.join(root, 'jarvis'))
q = subprocess.run([sys.executable, os.path.join(orig, 'jarvis', 'test_jarvis.py')], capture_output=True, text=True,
                   timeout=200, cwd=os.path.join(orig, 'jarvis'))
print('test_jarvis.py: original copy rc=%d, patched copy rc=%d' % (q.returncode, p.returncode))
ok(p.returncode == 0 or q.returncode != 0, 'jarvis/test_jarvis.py passes on the patched copy: %s' % (p.stdout + p.stderr).strip().splitlines()[-1:])

# works before or after the craving / workout installs (when those are still waiting)
for other in ('jarvis-craving', 'jarvis-workout'):
    op = os.path.join(REPO, 'away', other, 'apply_patches.py')
    if not os.path.exists(op):
        continue
    import importlib.util
    spec = importlib.util.spec_from_file_location(other.replace('-', '_'), op)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    for order in ('them first', 'us first'):
        rr = make_root()
        steps = [mod.main, ap.main] if order == 'them first' else [ap.main, mod.main]
        res = [quiet(f, rr) for f in steps]
        stops = [x for x in res if str(x[0]).startswith('STOP')]
        jt2 = open(os.path.join(rr, 'jarvis', 'jarvis.py')).read()
        good = not stops and ap.MARK in jt2
        if good:
            compile(jt2, 'jarvis.py', 'exec')
        ok(good, '%s + show phrases (%s): %s' % (other, order, stops or 'ok'))

# ---------------------------------------------------------------- 5. live install consistency (read-only)
lj = open(os.path.join(REPO, 'jarvis', 'jarvis.py')).read()
lr = open(os.path.join(REPO, 'rig_control.py')).read()
if ap.MARK in lj:
    ok(ap.MARK in lr, 'LIVE: jarvis.py has the show phrases but rig_control.py does not')
    ok(os.path.exists(os.path.join(REPO, 'jarvis', 'show_words.py')), 'LIVE: jarvis/show_words.py missing')

after = {p: sha(os.path.join(REPO, p)) for p in LIVE}
ok(before == after, 'live files unchanged by the tests')

if BAD:
    print('%d of %d checks FAILED' % (len(BAD), N[0]))
    sys.exit(1)
print('ALL %d checks passed' % N[0])
