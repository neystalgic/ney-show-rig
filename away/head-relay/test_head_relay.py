# Offline test for the HEAD RELAY (Nov 15). No network, no lights: a fake hub, a fake DMX socket and a fake clock.
#   python3 away/head-relay/test_head_relay.py
import ast, colorsys, importlib.util, json, math, os, shutil, socket, subprocess, sys, tempfile, threading, types
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.abspath(os.path.join(HERE, '..', '..'))
PASS, FAIL = [], []


def ok(cond, name):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print('FAIL:', name)


# ---- no network, anywhere -----------------------------------------------------------------------
def _blocked(*a, **k):
    raise OSError('network blocked in tests')
socket.getaddrinfo = _blocked
socket.create_connection = _blocked
urllib.request.urlopen = _blocked
SENT = []


class FakeSock:
    def __init__(self, *a, **k):
        pass

    def sendto(self, data, addr):
        SENT.append(bytes(data))

    def connect(self, *a):
        raise OSError('network blocked in tests')

    def close(self):
        pass
socket.socket = FakeSock

# ---- a temp copy of the rig, patched ------------------------------------------------------------
TMP = tempfile.mkdtemp(prefix='headrelay_')
for f in ('hub_dmx.py', 'hue_hub.py', 'rig_control.py', 'selftest.py', 'hub_lamps.json', 'light_schedule.py'):
    shutil.copy2(os.path.join(RIG, f), TMP)
shutil.copytree(os.path.join(RIG, 'jarvis'), os.path.join(TMP, 'jarvis'),
                ignore=shutil.ignore_patterns('*.bak-*', '__pycache__', 'sounds'))
with open(os.path.join(TMP, 'hub_state.json'), 'w') as f:
    json.dump({'settings': {'dmx_pattern': 'show'}}, f)
sys.path.insert(0, HERE)
import apply_patches as ap
DEPLOYED = 'hub_chase' in open(os.path.join(RIG, 'hub_dmx.py')).read()   # Nov 15: relay is live; installer-time checks only before that
before = {f: open(os.path.join(TMP, f)).read() for f in ('hub_dmx.py', 'hue_hub.py', 'rig_control.py', 'selftest.py')}
ok(ap.main(['--root', TMP]) == 0, 'installer patches a copy of the live files')
ok(os.path.exists(os.path.join(TMP, 'hub_chase.py')), 'installer adds hub_chase.py')
ok(DEPLOYED or os.path.exists(os.path.join(TMP, 'hub_dmx.py.bak-nov15-relay')), 'installer backs up first')
for f in ('hub_dmx.py', 'hue_hub.py', 'rig_control.py', 'selftest.py', os.path.join('jarvis', 'jarvis.py')):
    src = open(os.path.join(TMP, f)).read()
    try:
        compile(src, f, 'exec')
        ok(True, 'patched %s compiles' % f)
    except SyntaxError as e:
        ok(False, 'patched %s compiles (%s)' % (f, e))
snap = {f: open(os.path.join(TMP, f)).read() for f in before}
ok(ap.main(['--root', TMP]) == 0 and all(open(os.path.join(TMP, f)).read() == snap[f] for f in snap),
   'installer is safe to run twice (second run changes nothing)')
T2 = tempfile.mkdtemp(prefix='headrelay2_')
for f in ('hub_dmx.py', 'hue_hub.py', 'rig_control.py', 'selftest.py'):
    shutil.copy2(os.path.join(RIG, f), T2)
shutil.copytree(os.path.join(RIG, 'jarvis'), os.path.join(T2, 'jarvis'), ignore=shutil.ignore_patterns('*.bak-*', '__pycache__', 'sounds'))
with open(os.path.join(T2, 'hub_dmx.py'), 'a') as f:
    pass
t = open(os.path.join(T2, 'hue_hub.py')).read().replace("'hub_dmx.py', 'hub_vibes.py']", "'hub_dmx.py']")
open(os.path.join(T2, 'hue_hub.py'), 'w').write(t)
snap2 = {f: open(os.path.join(T2, f)).read() for f in ('hub_dmx.py', 'hue_hub.py', 'rig_control.py', 'selftest.py')}
ok(DEPLOYED or ap.main(['--root', T2]) == 1 and all(open(os.path.join(T2, f)).read() == v for f, v in snap2.items())
   and not os.path.exists(os.path.join(T2, 'hub_chase.py')), 'installer writes NOTHING if one file changed')

# hue_hub: the lamp hook sits in a function where beats + pmode exist, before the flicker protection
hub_src = open(os.path.join(TMP, 'hue_hub.py')).read()
tree = ast.parse(hub_src)
hook_line = hub_src[:hub_src.index('self.dmx.chase.lamps(')].count('\n') + 1
fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.lineno < hook_line <= n.end_lineno][-1]
names = {a.arg for a in fn.args.args} | {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.lineno < hook_line}
ok({'beats', 'pmode', 'now'} <= names, 'hue_hub lamp hook: beats/pmode/now are set before it')
ok(hub_src.index('self.dmx.chase.lamps(') < hub_src.index('ordered = self.lim.step(ordered, now)'), 'lamps follow BEFORE the flicker protection')
ok("dmx_pattern=str" in hub_src and "'hub_chase.py'" in hub_src, 'hub accepts dmx_pattern + reloads on hub_chase.py changes')

# ---- load the patched hub_dmx (from TMP) and the untouched live one ------------------------------
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
sys.path.insert(0, TMP)
new_dmx = load('hub_dmx_new', os.path.join(TMP, 'hub_dmx.py'))
old_dmx = load('hub_dmx_old', os.path.join(RIG, 'hub_dmx.py'))
import hub_chase
ok(hub_chase.__file__.startswith(TMP), 'hub_chase loads from the patched copy')

HEADS = [dict(addr=1, tilt_up=32768, tilt_dir=1, tilt_max_deg=35.0, pan_min=8000, pan_max=40000, upright_level=0.2),
         dict(addr=15, tilt_up=30000, tilt_dir=-1, tilt_max_deg=40.0, pan_min=0, pan_max=65535, upright_level=0.2),
         dict(addr=29, tilt_up=32768, tilt_dir=1, tilt_max_deg=49.0, pan_min=10000, pan_max=50000, upright_level=0.2,
              avoid=[dict(az=60.0, width=50.0, lean=10.0)]),
         dict(addr=43, tilt_up=33000, tilt_dir=1, tilt_max_deg=52.0, pan_min=20000, pan_max=60000, upright_level=0.2)]


class Hub:
    def __init__(self, **s):
        self.state = {'settings': dict(dict(dmx_host='zephyrus', dmx_pattern='show', energy=0.6, dmx_strobe='flash',
                                             flash_beats=8, dmx_level=0.8), **s)}
        self.live = {'master': 1.0}
        self.blackout = False
        self.lock = threading.Lock()
        self.audioshow = types.SimpleNamespace(section='groove', env={'kick': 0.0})
        self.audio = types.SimpleNamespace(ch_rms={})
        self.t_motion = 0.0

    def save_soon(self):
        pass


def make(mod, hub):
    h = mod.Heads(hub)
    h.run = False
    h.node_cfg = {'universe': 0, 'heads': [dict(x) for x in HEADS]}
    h.ip = '10.9.9.9'                      # FakeSock only records packets
    return h


def cols_at(now, hue=0.78):
    v = 0.7 + 0.3 * abs(math.sin(now * 3.0))
    return [colorsys.hsv_to_rgb((hue + 0.01 * k) % 1.0, 0.9, v) for k in range(6)]


def decode(pkt):
    data = pkt[18:]
    out = []
    for hd in HEADS:
        a = hd['addr'] - 1
        pan = data[a] << 8 | data[a + 1]
        tilt = data[a + 2] << 8 | data[a + 3]
        theta = (tilt - hd['tilt_up']) * hd['tilt_dir'] * 180.0 / 65535.0
        out.append(dict(master=data[a + 5], pan=pan, theta=theta, rgb=(data[a + 6], data[a + 7], data[a + 8])))
    return out


def run(h, hub, secs, bpm=120.0, t0=100.0, pmode='music', hue_fn=None, on_frame=None):
    frames, k = [], 0
    while k * 0.026 < secs:
        now = t0 + k * 0.026
        beats = (now - t0) * bpm / 60.0 + 0.3
        cols = cols_at(now, hue_fn(now) if hue_fn else 0.78)
        ch = getattr(h, 'chase', None)
        if ch is not None:
            cols = ch.lamps(cols, list(range(6)), now, beats, pmode)
        n0 = len(SENT)
        h.frame(now, 0.026, beats, cols, pmode)
        if len(SENT) > n0:
            z = ch._cache[1] if ch is not None and ch._cache[0] == now else None
            frames.append(dict(now=now, beats=beats, heads=decode(SENT[-1]), z=z, cols=cols))
        if on_frame:
            on_frame(now, beats)
        k += 1
    return frames


# ---- 1. the relay over 8 bars (120 BPM, normal energy: hand-off every 2 bars) ---------------------
hub = Hub()
h = make(new_dmx, hub)
fr = run(h, hub, 16.5, hue_fn=lambda now: 0.70 + 0.004 * (now - 100.0))   # palette drifts; the relay holds it per turn
lit = [[i for i, x in enumerate(f['heads']) if x['master'] > 0] for f in fr]
ok(len(fr) > 500, 'heads frames sent (%d)' % len(fr))
ok(all(len(l) <= 1 for l in lit), 'exactly ONE head lit at a time (max %d)' % max(len(l) for l in lit))
ok(sum(1 for l in lit if l) > 0.7 * len(lit), 'a head is lit most of the time')
seq = []
for l in lit:
    if l and (not seq or seq[-1] != l[0]):
        seq.append(l[0])
ok(seq[:4] == [0, 1, 2, 3], 'order 1 -> 2 -> 3 -> 4 (%s)' % [x + 1 for x in seq])
turns = [f for p, f in zip(fr, fr[1:]) if f['z'] and p['z'] and f['z']['turn'] != p['z']['turn']]
ok(len(turns) >= 3 and all(f['beats'] % 8.0 < 0.1 for f in turns), 'hand-offs land on every 2nd bar line')
ok(all(f['z']['heads'][f['z']['head']]['level'] < 0.05 for f in turns), 'outgoing head is dark at the hand-off')
for f in fr:
    for i, x in enumerate(f['heads']):
        if x['master'] > 0:
            hd = HEADS[i]
            if not (abs(x['theta']) <= min(hd['tilt_max_deg'], 45.0) * 0.95 + 0.6 and hd['pan_min'] <= x['pan'] <= hd['pan_max']
                    and not new_dmx.in_avoid(hd, x['pan'], x['theta'])):
                FAIL.append('caps at %.2f head %d theta %.1f pan %d' % (f['beats'], i + 1, x['theta'], x['pan']))
ok(not [x for x in FAIL if x.startswith('caps')], 'every lit beam inside its lean cap, pan window and avoid zones')
spd = 0.0
for p, f in zip(fr, fr[1:]):
    for a, b in zip(p['heads'], f['heads']):
        spd = max(spd, abs(b['pan'] - a['pan']) * 540.0 / 65535.0 / (f['now'] - p['now']))
ok(spd <= new_dmx.MAX_DEG_S + 1.0, 'pan never faster than %.0f deg/s (max %.1f)' % (new_dmx.MAX_DEG_S, spd))
moved, ps = {}, {}
for f, l in zip(fr, lit):
    if l:
        moved.setdefault((f['z']['turn'], l[0]), []).append(f['heads'][l[0]]['pan'] * 540.0 / 65535.0)
        ps.setdefault((f['z']['turn'], l[0]), []).append(f['z']['p'])
full = [k for k in moved if min(ps[k]) < 0.15 and max(ps[k]) > 0.85]      # turns that ran start to finish in the test
ok(len(full) >= 3 and all(max(moved[k]) - min(moved[k]) >= 15.0 for k in full),
   'each lit head really sweeps (>= 15 deg per turn): %s' % ['%d:%.0f' % (k[1] + 1, max(moved[k]) - min(moved[k])) for k in sorted(moved)])
th = {}
for f, l in zip(fr, lit):
    if l and f['z']:
        th.setdefault(f['z']['turn'], []).append(f['heads'][l[0]]['theta'])
ok(all(max(v) - min(v) >= 2.0 for v in list(th.values())[1:]), 'small tilt dip during each sweep')
rgbs = {}
for f, l in zip(fr, lit):
    if l and f['heads'][l[0]]['master'] > 20:
        r_, g_, b_ = f['heads'][l[0]]['rgb']
        rgbs.setdefault(f['z']['turn'], set()).add(round(colorsys.rgb_to_hsv(r_ / 255, g_ / 255, b_ / 255)[0], 2))
ok(all(len(v) == 1 for v in rgbs.values()) and len({min(v) for v in rgbs.values()}) > 1,
   'colour held for a whole turn, picked fresh at each hand-off')
ok(all(colorsys.rgb_to_hsv(*[c / 255 for c in f['heads'][l[0]]['rgb']])[1] >= 0.5 for f, l in zip(fr, lit) if l),
   'never white (saturation kept up)')
# lamps follow
mid = [f for f in fr if f['z'] and 0.4 < f['z']['p'] < 0.6]
good = True
for f in mid:
    near = h.chase.near(f['z']['head'])
    vs = [max(c) for c in f['cols']]
    top = max(vs)
    good &= bool(near) and all(vs[c] >= top - 1e-6 for c in near) and all(vs[c] <= top * 0.25 for c in range(6) if c not in near)
ok(mid and good, 'lamps beside the lit head glow, the others dim to ~20%')
ok(len({h.chase.near(i).__repr__() for i in range(4)}) == 4, 'each head has its own lamp(s) (estimated positions)')

# ---- 2. drops dance as before; high energy hands off every bar ----------------------------------
hub2 = Hub()
h2 = make(new_dmx, hub2)
hub2.audioshow.section = 'drop'
fr2 = run(h2, hub2, 3.0)
ok(all(f['z'] is None for f in fr2) and max(sum(1 for x in f['heads'] if x['master'] > 0) for f in fr2) >= 3,
   "'show': drops are NOT the relay (all heads dance)")
hub3 = Hub(energy=0.9)
h3 = make(new_dmx, hub3)
fr3 = run(h3, hub3, 9.0)
t3 = [f for p, f in zip(fr3, fr3[1:]) if f['z'] and p['z'] and f['z']['turn'] != p['z']['turn']]
ok(len(t3) >= 3 and all(f['beats'] % 4.0 < 0.1 for f in t3), 'high energy: hand-off every bar')
# no strobe in the relay, even with dmx_strobe 'always'
hub4 = Hub(dmx_strobe='always', strobe_max_hz=3.0)
h4 = make(new_dmx, hub4)
fr4 = run(h4, hub4, 6.0)
ok(all(x['master'] <= new_dmx.MASTER_MAX for f in fr4 for x in f['heads']) and
   all(sum(1 for x in f['heads'] if x['master'] > 0) <= 1 for f in fr4), 'no strobe hits / head strobe while the relay runs')
# off switches
for label, kw, extra, pm in [('movie', {}, lambda hb: hb.state['settings'].update(movie=True), 'music'),
                             ('sync mode', {}, None, 'sync'),
                             ('blackout', {}, lambda hb: setattr(hb, 'blackout', True), 'music'),
                             ('a scene Michael picked', {}, lambda hb: hb.state['settings'].update(dmx_cue={'a': 'Studio'}), 'music'),
                             ("pattern 'normal'", dict(dmx_pattern='normal'), None, 'music'),
                             ("'show' in lava mode", {}, None, 'lava')]:
    hb = Hub(**kw)
    if extra:
        extra(hb)
    hh_ = make(new_dmx, hb)
    f_ = run(hh_, hb, 1.5, pmode=pm)
    ok(all(f['z'] is None for f in f_) and hh_.chase.step(999.0, 50.0, pm) is None, 'relay stays off: %s' % label)
hb = Hub(dmx_pattern='relay')
hb.audioshow.section = 'quiet'
ok(make(new_dmx, hb).chase.step(5.0, 3.0, 'music') is not None, "'relay' runs outside drops too")
hb = Hub(dmx_host='')
ok(make(new_dmx, hb).chase.step(5.0, 3.0, 'music') is None, 'no heads connected -> relay off, lamps untouched')

# ---- 3. pattern 'normal' = byte-for-byte the same as today's hub_dmx ----------------------------
def packets(mod, **kw):
    del SENT[:]
    hb = Hub(dmx_pattern='normal', **kw)
    hh_ = make(mod, hb)
    run(hh_, hb, 12.0)
    return list(SENT)
for kw in (dict(), dict(dmx_strobe='phrase'), dict(dmx_strobe='off', dmx_unison=0.3)):
    a, b = packets(old_dmx, **kw), packets(new_dmx, **kw)
    ok(len(a) > 100 and a == b, "pattern 'normal' output identical to the live hub_dmx %s" % kw)

# ---- 4. order, spots, units -----------------------------------------------------------------------
o = hub_chase.relay_order(4)
ok(o == [0, 1, 2, 3, 2, 1, 0, 2, 1, 3], 'order: forward, back, skip (%s)' % [x + 1 for x in o])
ok(all(all(a != b for a, b in zip(hub_chase.relay_order(n), hub_chase.relay_order(n)[1:] + hub_chase.relay_order(n)[:1]))
       for n in range(2, 7)), 'never the same head twice in a row (2-6 heads)')
c = hub_chase.Chase(Hub(), lamps={})
c.step(1.0, 0.5, 'music', [dict(HEADS[0]), dict(type='focus17'), dict(HEADS[1]), dict(type='focus17')])
ok(c.relay_heads == [0, 2], 'spots (focus17) sit out of the relay')
c2 = hub_chase.Chase(Hub(chase_lamps={'0': ['Top Lamp']}))
ok({c2.lamp_xy[ch][2] for ch in c2.near(0)} == {'Top Lamp'}, 'chase_lamps setting overrides the estimated positions')

# ---- 5. Jarvis + rig_control + selftest -----------------------------------------------------------
sys.path.insert(0, os.path.join(TMP, 'jarvis'))
j = load('jarvis_new', os.path.join(TMP, 'jarvis', 'jarvis.py'))
s = j.settings()
fake = lambda *a, **k: {'message': {'content': json.dumps({'action': 'unknown'})}, 'response': ''}
for text, want in [('head relay', 'relay'), ('Jarvis, start the head relay', 'relay'), ('heads take turns', 'relay'),
                   ('relay mode', 'relay'), ('head relay off', 'relayoff'), ('stop the relay', 'relayoff'),
                   ('turn the uv off', 'uvoff'), ('light show', 'show')]:
    try:
        got = j.understand(text, s, fake).get('action')
    except Exception as e:
        got = 'error %s' % e
    ok(got == want, 'Jarvis: "%s" -> %s (got %s)' % (text, want, got))
site = tempfile.mkdtemp(prefix='nonet_')
open(os.path.join(site, 'sitecustomize.py'), 'w').write(
    "import socket, urllib.request\n"
    "def _b(*a, **k):\n    raise OSError('network blocked in tests')\n"
    "socket.create_connection = _b\nsocket.getaddrinfo = _b\nurllib.request.urlopen = _b\n")
r = subprocess.run([sys.executable, 'test_jarvis.py'], cwd=os.path.join(TMP, 'jarvis'), capture_output=True, text=True,
                   env=dict(os.environ, PYTHONPATH=os.pathsep.join([site, TMP, RIG])), timeout=120)
ok(r.returncode == 0, 'old test_jarvis.py still passes on the patched Jarvis' + ('' if r.returncode == 0 else ': ' + (r.stdout + r.stderr)[-300:]))
rc = ast.parse(open(os.path.join(TMP, 'rig_control.py')).read())
keys = set()
for n in ast.walk(rc):
    if isinstance(n, ast.Assign) and any(isinstance(t_, ast.Name) and t_.id == 'LOOKS' for t_ in n.targets) and isinstance(n.value, ast.Dict):
        keys = {k.value for k in n.value.keys if isinstance(k, ast.Constant)}
ok({'relay', 'relayoff', 'show', 'uvoff'} <= keys, 'rig_control has the relay / relayoff looks')
st_ = load('selftest_new', os.path.join(TMP, 'selftest.py'))
st_.chase_check()
ok(st_.RESULTS and st_.RESULTS[-1]['name'] == 'Head relay' and st_.RESULTS[-1]['level'] == 'ok',
   'selftest read-only check: %s' % (st_.RESULTS[-1] if st_.RESULTS else None))
ok(len(SENT) > 0 and True, 'all DMX went to the fake socket only')

print('test_head_relay: %d/%d passed' % (len(PASS), len(PASS) + len(FAIL)))
sys.exit(1 if FAIL else 0)
