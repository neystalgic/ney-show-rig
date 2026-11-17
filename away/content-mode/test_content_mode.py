"""Offline tests for CONTENT MODE (away loop W5). Fake clock, fake rig/hub, temp copies of the live files.
NO network: every socket connect raises. Live files are hashed before and after: they must not change.
Run:  python3 away/content-mode/test_content_mode.py
"""
import hashlib, importlib, json, os, queue, shutil, socket, subprocess, sys, tempfile, threading, types

def _no_net(*a, **k):
    raise OSError('network blocked in tests')
socket.socket.connect = _no_net
socket.create_connection = _no_net

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import content_mode as cm_mod
import content_words as cw
import apply_patches as ap

OK = [0]
def check(cond, what):
    if not cond:
        raise SystemExit('FAIL: ' + what)
    OK[0] += 1

LIVE = ['rig_control.py', 'jarvis/jarvis.py', 'hub_dmx.py', 'hue_hub.py']
def digest():
    return {p: hashlib.sha1(open(os.path.join(RIG, p), 'rb').read()).hexdigest() for p in LIVE}
before = digest()
check(not os.path.exists(os.path.join(RIG, 'content_mode.py')), 'content_mode.py is not live yet')

# ---------------------------------------------------------------- fakes
class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t

def fake_rc(hub=True):
    calls = []
    rc = types.SimpleNamespace(STATE={'look': 'purple'}, JOBS=queue.Queue(), LOCK=threading.Lock(), calls=calls)
    rc.show_full = lambda: calls.append(('show_full',))
    rc.hub_setting = lambda k, v: calls.append((k, v))
    rc.hub_up = lambda: hub
    return rc

def drain(rc):
    while not rc.JOBS.empty():
        rc.JOBS.get()()

def fresh(cfg=None):
    d = tempfile.mkdtemp(prefix='content-test-')
    if cfg is not None:
        json.dump(cfg, open(os.path.join(d, 'content_mode.json'), 'w'))
    clk = Clock()
    return d, clk, cm_mod.ContentMode(d, clk)

def say(rc, cm, op, confirmed=False):
    return cm_mod.rig_side('content:' + json.dumps({'op': op, 'confirmed': confirmed}), rc, cm, timer=False)

# ---------------------------------------------------------------- words
W = {'content mode confirmed': ('on', True), 'jarvis content mode': ('on', False), 'filming mode confirmed': ('on', True),
     'content mode again': ('again', False), 'more content mode': ('again', False),
     'content mode again confirmed': ('again', True), 'content mode off': ('off', None), 'stop content mode': ('off', None),
     'no more content mode': ('off', None), 'how long is left on content mode': ('status', None),
     'content mode status': ('status', None)}
for t, (op, c) in W.items():
    v = cw.parse(t)
    check(v and v['op'] == op and (c is None or v['confirmed'] == c), 'words: %r -> %r' % (t, v))
for t in ('light show', 'strobe it', 'content', 'make content', 'movie mode', 'guest mode', ''):
    check(cw.parse(t) is None, 'words: %r must not be content mode' % t)
check('installed' in cw.handle({'op': 'on'}, lambda p: (_ for _ in ()).throw(KeyError(p))), 'old rig -> not installed')
check("can't reach" in cw.handle({'op': 'on'}, lambda p: (_ for _ in ()).throw(OSError())), 'rig down')
check("didn't catch" in cw.handle({'op': 'rm'}, lambda p: 'x'), 'bad op refused')
got = []
check(cw.handle({'op': 'on', 'confirmed': True}, lambda p: (got.append(p), 'yes')[1]) == 'yes', 'handle returns rig words')
check(got == ['content:{"op": "on", "confirmed": true}'], 'handle sends content:{json}')

# ---------------------------------------------------------------- config clamps
d, clk, cm = fresh({'minutes': 30, 'rearm_grace_minutes': 99, 'strobe': 'rm -rf', 'flash_beats': 0, 'white': 'false',
                    'studio_seat': {'pan': 1}})
c = cm.cfg()
check(c['minutes'] == 5 and c['rearm_grace_minutes'] == 30 and c['strobe'] == 'always' and c['flash_beats'] == 1,
      'config clamped: %r' % c)
check(c['white'] is False and c['studio_seat'] == {'pan': 1}, 'white off + studio_seat kept')
check(cm_mod.load_config('/nonexistent')['minutes'] == 5, 'missing file -> defaults')
shipped = json.load(open(os.path.join(HERE, 'content_mode.json')))
check('studio_seat' in shipped and shipped['studio_seat'] is None and shipped['minutes'] == 5, 'shipped json placeholder')

# ---------------------------------------------------------------- arming
d, clk, cm = fresh()
rc = fake_rc()
s = say(rc, cm, 'on')
check("'content mode confirmed'" in s and not cm.active() and rc.JOBS.empty(), 'no confirmed -> refused, nothing queued')
rc.STATE['guest'] = True
s = say(rc, cm, 'on', True)
check('Guest mode' in s and not cm.active() and rc.JOBS.empty(), 'guest mode blocks even confirmed')
rc.STATE['guest'] = False
s = say(rc, cm, 'on', True)
check('5 minutes' in s and 'studio seat' in s and cm.active(), 'confirmed -> on: %s' % s)
check(abs(cm.remaining() - 300) < 1e-6, '5 minutes on the clock')
drain(rc)
check(rc.calls == [('show_full',), ('dmx_strobe', 'always'), ('flash_beats', 1), ('content_white', True)],
      'start: show then content settings: %r' % rc.calls)
check(rc.STATE['look'] == 'content' and rc.STATE['busy'] is False, 'state look=content')
check('left' in say(rc, cm, 'status') and '5 minutes' in say(rc, cm, 'status'), 'status while on')

# extend while on: from NOW, never stacking past 5 minutes
clk.t += 120
rc.calls.clear()
s = say(rc, cm, 'again')
check('more' in s and abs(cm.remaining() - 300) < 1e-6 and rc.JOBS.empty(), 'again while on -> 5 min from now, no restart')
say(rc, cm, 'again'); say(rc, cm, 'again')
check(abs(cm.remaining() - 300) < 1e-6, 'repeated again never stacks')

# timer
clk.t += 299
check(cm_mod.tick(rc, cm) is None and cm.active(), 'still on at 4:59')
clk.t += 1
check(cm_mod.tick(rc, cm) == 'restored' and not cm.active(), 'auto-off at 5:00')
check(rc.calls == list(cm_mod.OFF_SETTINGS), 'restore: white off, strobe off, 2-bar colours: %r' % rc.calls)
check(rc.STATE['look'] == 'music', 'look back to music after content')
check(cm_mod.tick(rc, cm) is None, 'tick fires once only')
check(say(rc, cm, 'status') == 'Content mode is off.', 'status when off')

# re-arm within grace (after the TIMER ended it) without 'confirmed'
clk.t += 9 * 60
rc.calls.clear()
s = say(rc, cm, 'again')
check(cm.active() and 'on for' in s, 're-arm within 10 min of auto-off, no confirmed needed')
drain(rc)
check(rc.calls[0] == ('show_full',) and ('content_white', True) in rc.calls, 're-arm restarts the content look')
# guest mode always wins, even on a re-arm
cm.end(clk.t, expired=True); clk.t += 60; rc.STATE['guest'] = True
check('Guest' in say(rc, cm, 'again') and not cm.active(), 'guest blocks re-arm')
rc.STATE['guest'] = False
clk.t += 11 * 60
check("'content mode confirmed'" in say(rc, cm, 'again') and not cm.active(), 'again after grace -> needs confirmed')
check(cm.active() is False and 'on for' in say(rc, cm, 'again', True) and cm.active(), 'again confirmed after grace works')

# manual off: no grace afterwards
rc.calls.clear(); drain(rc); rc.calls.clear()
s = say(rc, cm, 'off')
check('off' in s and not cm.active(), 'manual off')
drain(rc)
check(rc.calls == list(cm_mod.OFF_SETTINGS), 'manual off restores')
check("'content mode confirmed'" in say(rc, cm, 'again'), 'after manual off, again needs confirmed')
check(say(rc, cm, 'off') == 'Content mode is already off.', 'off when off')
check("didn't catch" in cm_mod.rig_side('content:{bad', rc, cm, timer=False), 'bad json refused')

# grace 0 = always confirmed
d2, clk2, cm2 = fresh({'rearm_grace_minutes': 0})
cm2.arm(clk2.t); clk2.t += 300; cm_mod.tick(fake_rc(), cm2); clk2.t += 1
check("'content mode confirmed'" in cm2.decide('again', False, False, clk2.t)[1], 'grace 0 -> confirmed always')

# guest mode switched on while the start was queued -> nothing happens
d, clk, cm = fresh(); rc = fake_rc()
say(rc, cm, 'on', True); rc.STATE['guest'] = True; drain(rc)
check(rc.calls == [], 'guest on before the queued start -> no show, no strobe')

# another look ends content mode BEFORE it runs
d, clk, cm = fresh(); rc = fake_rc()
say(rc, cm, 'on', True); drain(rc); rc.calls.clear()
check(cm_mod.look_changed(rc, 'content', cm) is None and cm.active(), 'content itself does not end it')
check(cm_mod.look_changed(rc, 'night', cm) == 'restored' and not cm.active(), 'a new look ends content mode')
check(rc.calls == list(cm_mod.OFF_SETTINGS), 'and restores first')
check(cm_mod.look_changed(rc, 'purple', cm) is None, 'nothing to do when off')
check("'content mode confirmed'" in say(rc, cm, 'again'), 'ended by a look -> again needs confirmed')

# hub off: restore is skipped quietly, nothing raises
d, clk, cm = fresh(); rc = fake_rc(hub=False)
say(rc, cm, 'on', True); clk.t += 300
check(cm_mod.tick(rc, cm) == 'hub off' and not cm.active(), 'expiry with hub off')
bad = fake_rc(); bad.hub_setting = lambda k, v: (_ for _ in ()).throw(RuntimeError('hub'))
check(cm_mod.restore(bad) == 'failed' and 'content restore' in bad.STATE['last_error'], 'hub error recorded')
old_hub = fake_rc()
def picky(k, v):
    if k == 'content_white':
        raise RuntimeError('unknown setting')     # hub not restarted after the install
    old_hub.calls.append((k, v))
old_hub.hub_setting = picky
check(cm_mod.restore(old_hub) == 'failed' and old_hub.calls == [('dmx_strobe', 'off'), ('flash_beats', 8)],
      'hub refusing content_white still turns the strobe off')
check(cm_mod.OFF_SETTINGS[0] == ('dmx_strobe', 'off'), 'strobe off goes first')
bad_up = fake_rc(); bad_up.hub_up = lambda: (_ for _ in ()).throw(OSError('x'))
check(cm_mod.restore(bad_up) == 'failed', 'hub_up error handled')

# state survives in the file; boot ends it (restart mid-session)
d, clk, cm = fresh(); rc = fake_rc()
say(rc, cm, 'on', True)
cm_b = cm_mod.ContentMode(d, clk)
check(cm_b.active(), 'state file read back')
rc.calls.clear()
check(cm_mod.boot(rc, cm_b, wait=False) == 'restored' and not cm_b.active(), 'boot switches it off')
check(rc.calls == list(cm_mod.OFF_SETTINGS), 'boot restores the hub')
check(cm_mod.boot(rc, cm_b, wait=False) is None, 'boot when off does nothing')
check("'content mode confirmed'" in say(rc, cm_b, 'again'), 'after a restart, needs confirmed')
open(os.path.join(d, 'content_state.json'), 'w').write('garbage')
check(not cm_mod.ContentMode(d, clk).active(), 'corrupt state file -> off')

# the real timer thread (short): fires on its own with a fake clock
d, clk, cm = fresh(); rc = fake_rc()
cm_mod.rig_side('content:' + json.dumps({'op': 'on', 'confirmed': True}), rc, cm, timer=True)
drain(rc); rc.calls.clear(); clk.t += 301
for _ in range(40):
    if not cm.active() and rc.calls:
        break
    threading.Event().wait(0.1)
check(not cm.active() and rc.calls == list(cm_mod.OFF_SETTINGS), 'timer thread switched it off')
check(cm.thread.daemon, 'timer thread is a daemon (never blocks a restart)')

# ---------------------------------------------------------------- installer on temp copies
tmp = tempfile.mkdtemp(prefix='content-rig-')
for p in [f for f in os.listdir(RIG) if f.endswith('.py')]:     # every rig module (test_jarvis imports a few)
    shutil.copy2(os.path.join(RIG, p), os.path.join(tmp, p))
shutil.copytree(os.path.join(RIG, 'jarvis'), os.path.join(tmp, 'jarvis'),
                ignore=shutil.ignore_patterns('__pycache__', '*.bak-*'))
check(ap.main(['--rig', tmp, '--check']) == 0 and not os.path.exists(os.path.join(tmp, 'content_mode.py')),
      '--check writes nothing')
check(ap.main(['--rig', tmp]) == 0, 'install on temp copy')
for p in ('content_mode.py', 'content_mode.json', 'jarvis/content_words.py', 'rig_control.py.bak-nov17-content',
          'jarvis/jarvis.py.bak-nov17-content', 'hub_dmx.py.bak-nov17-content', 'hue_hub.py.bak-nov17-content'):
    check(os.path.exists(os.path.join(tmp, p)), 'installed: ' + p)
T = {p: open(os.path.join(tmp, p)).read() for p in LIVE}
for p, t in T.items():
    compile(t, p, 'exec'); OK[0] += 1
check(T['hub_dmx.py'].count("s.get('content_white')") == 3, 'hub_dmx: 2 floors + the hit')
check('content_white=bool' in T['hue_hub.py'], 'hue_hub: setting allowed')
check('\nimport ' in T['rig_control.py'] and ' sys' in T['rig_control.py'].split('def ')[0], 'rig_control imports sys')
check(T['rig_control.py'].count('import content_mode') == 3, 'rig_control: 3 hooks')
json.dump({'minutes': 3}, open(os.path.join(tmp, 'content_mode.json'), 'w'))
before_tmp = {p: open(os.path.join(tmp, p)).read() for p in LIVE}
ap.main(['--rig', tmp])
check({p: open(os.path.join(tmp, p)).read() for p in LIVE} == before_tmp, 'second run changes nothing')
check(json.load(open(os.path.join(tmp, 'content_mode.json'))) == {'minutes': 3}, 'your content_mode.json kept')

# jarvis-show installer still works after this one (and this one after it)
sys.path.insert(0, os.path.join(RIG, 'away', 'jarvis-show'))
js = importlib.import_module('apply_patches') if False else None
spec = importlib.util.spec_from_file_location('js_patch', os.path.join(RIG, 'away', 'jarvis-show', 'apply_patches.py'))
js = importlib.util.module_from_spec(spec); spec.loader.exec_module(js)
both_j, h1 = js.patch_jarvis(T['jarvis/jarvis.py']); both_r, h2 = js.patch_rig_control(T['rig_control.py'])
check(h1 == h2 == 'patched', 'jarvis-show anchors still fit after content mode')
compile(both_j, 'j', 'exec'); compile(both_r, 'r', 'exec'); OK[0] += 1
live_j, live_r = open(os.path.join(RIG, 'jarvis/jarvis.py')).read(), open(os.path.join(RIG, 'rig_control.py')).read()
rev_j = ap.patch_jarvis(js.patch_jarvis(live_j)[0])[0]; rev_r = ap.patch_rig_control(js.patch_rig_control(live_r)[0])[0]
compile(rev_j, 'j', 'exec'); compile(rev_r, 'r', 'exec')
check('content_words' in rev_j and 'show_words' in rev_j, 'content mode after jarvis-show works too')

# patched Jarvis: word rules route it, the model can't pick it, nothing else changed
code = r'''
import json, socket, sys, os
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(OSError('blocked'))
sys.path.insert(0, sys.argv[1]); os.chdir(sys.argv[1])
import jarvis as j
s = dict(j.DEFAULTS)
assert j._content is not None
for t, op in [('content mode confirmed', 'on'), ('jarvis, content mode again', 'again'), ('content mode off', 'off')]:
    i = j.by_rules(t); assert i['action'] == 'content' and i['value']['op'] == op, (t, i)
for t, a in [('strobe it', 'flash'), ('light show', 'show'), ('guest mode', 'guest_on'), ('lights off', 'off')]:
    assert j.by_rules(t)['action'] == a, t
fake = lambda content: (lambda url, body, t: {'message': {'content': json.dumps(content)}})
assert j.by_model('film something', s, fake({'action': 'content'})) is None, 'model must not pick content'
sent = []
out = j.handle('content mode confirmed', s, rig=lambda p: (sent.append(p), 'Content mode on.')[1], confirm=False)
assert out == 'Content mode on.' and sent == ['content:{"op": "on", "confirmed": true}'], (out, sent)
out = j.handle('content mode', s, rig=lambda p: 'needs confirmed', confirm=False)
assert out == 'needs confirmed', out
print('jarvis ok')
'''
r = subprocess.run([sys.executable, '-c', code, os.path.join(tmp, 'jarvis')], capture_output=True, text=True, timeout=60)
check(r.returncode == 0 and 'jarvis ok' in r.stdout, 'patched jarvis: ' + r.stdout[-300:] + r.stderr[-600:])
run = "import socket,runpy,sys; socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(OSError('blocked')); " \
      "sys.argv=[sys.argv[1]]; runpy.run_path(sys.argv[0], run_name='__main__')"
r = subprocess.run([sys.executable, '-c', run, os.path.join(tmp, 'jarvis', 'test_jarvis.py')], capture_output=True,
                   text=True, timeout=90, cwd=os.path.join(tmp, 'jarvis'))
check(r.returncode == 0, 'existing jarvis/test_jarvis.py on the patched copy: ' + r.stdout[-300:] + r.stderr[-600:])

check(digest() == before, 'live files unchanged')
check(not os.path.exists(os.path.join(RIG, 'content_mode.py')), 'nothing installed live')
shutil.rmtree(tmp, ignore_errors=True) if False else None   # (no deleting: temp dirs are cleaned by the OS)
print('content mode tests: %d/%d passed' % (OK[0], OK[0]))
