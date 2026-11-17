# Offline tests for W6 PUSH SHOW (away loop, Nov 17). Fake Push 2 MIDI, fake hub + director, network blocked.
# Patches TEMP COPIES of hub_push2.py / hub_visuals.py; the live files are checked unchanged at the end.
#   python3 away/push-show/test_push_show.py
import ast
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
REF = os.path.join(REPO, 'away', 'push-show-ref')
PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    PASS, FAIL = PASS + bool(ok), FAIL + (not ok)
    print(('ok    ' if ok else 'FAIL  ') + name)


def _no_net(*a, **k):
    raise RuntimeError('network blocked in tests')


socket.socket.connect = _no_net
socket.socket.sendto = _no_net
socket.create_connection = _no_net


def md5(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


LIVE = {n: md5(os.path.join(REPO, n)) for n in ('hub_push2.py', 'hub_visuals.py')}

# ------------------------------------------------------------------ fake mido (Push 2 User port)
class Msg:
    def __init__(self, type, **kw):
        self.type = type
        self.__dict__.update(kw)


class FakeOut:
    def __init__(self):
        self.sent = []

    def send(self, m):
        self.sent.append(m)

    def close(self):
        pass


class FakeIn:
    def __init__(self):
        self.pending = []

    def iter_pending(self):
        p, self.pending = self.pending, []
        return iter(p)

    def close(self):
        pass


OUT, INP = FakeOut(), FakeIn()
mido = types.ModuleType('mido')
mido.Message = Msg
mido.get_input_names = lambda: ['Ableton Push 2 User Port']
mido.get_output_names = lambda: ['Ableton Push 2 User Port']
mido.open_input = lambda n: INP
mido.open_output = lambda n: OUT
sys.modules['mido'] = mido

# ------------------------------------------------------------------ patch temp copies
TMP = tempfile.mkdtemp(prefix='pushshow_')
for n in ('hub_push2.py', 'hub_visuals.py', 'hub_pads.py', 'hub_geometry.py', 'hue_stream.py'):
    shutil.copy2(os.path.join(REPO, n), TMP)
APPLY = os.path.join(HERE, 'apply_patches.py')
r = subprocess.run([sys.executable, APPLY, '--target', TMP], capture_output=True, text=True)
check('apply_patches on temp copies', r.returncode == 0 and 'done' in r.stdout)
r2 = subprocess.run([sys.executable, APPLY, '--target', TMP], capture_output=True, text=True)
check('second run is a no-op (already patched)', r2.returncode == 0 and r2.stdout.count('already patched') == 2)
check('backups written', all(os.path.exists(os.path.join(TMP, n + '.bak-2026-11-17-pushshow'))
                             for n in ('hub_push2.py', 'hub_visuals.py')))
# STOP case: an anchor moved -> nothing touched (not even the other file)
TMP2 = tempfile.mkdtemp(prefix='pushshow_stop_')
for n in ('hub_push2.py', 'hub_visuals.py'):
    shutil.copy2(os.path.join(REPO, n), TMP2)
p = os.path.join(TMP2, 'hub_push2.py')
open(p, 'w').write(open(p).read().replace('PLAY = 85\n', 'PLAY = 85  # moved\n'))
before = {n: md5(os.path.join(TMP2, n)) for n in ('hub_push2.py', 'hub_visuals.py')}
r3 = subprocess.run([sys.executable, APPLY, '--target', TMP2], capture_output=True, text=True)
check('STOP when an anchor moved', r3.returncode == 1 and 'STOP' in r3.stdout)
check('STOP touches nothing', before == {n: md5(os.path.join(TMP2, n)) for n in before}
      and not os.path.exists(os.path.join(TMP2, 'hub_showsync.py')))

sys.path.insert(0, TMP)
import hub_showsync as ss
import hub_push2
import hub_visuals

# ------------------------------------------------------------------ fake director + hub
class Director:
    def __init__(self):
        self.hue = 0.78
        self.last = dict(act='burst', mode='', phrase_bar=2, rgb=(0.5, 0.0, 1.0),
                         zones=[dict(id='1A', level=0.2), dict(id='1B', level=0.6)])
        self.on = True

    def acts_on(self):
        return True

    def audio_mix(self):
        return 0.6

    def clock_hits(self, beats):
        return dict(kick=1.0 if beats % 1 < 0.1 else 0.0, snare=0.0, hats=0.0)

    def status(self):
        z = self.last if self.on else None
        a = (z or {}).get('act', 'zones')
        return dict(on=bool(z), act=a if z else None, mode=(z or {}).get('mode'), bar=3 if z else 0, bars=8,
                    lock=HUB.state['settings'].get('show_lock', ''), acts_on=HUB.state['settings'].get('show_acts', True))


class Pads:
    def __init__(self):
        self.panics = 0
        self.voices = {}
        self.touch = None

    def panic(self):
        self.panics += 1

    def release_all(self, t):
        pass

    def describe(self):
        return ''

    def latched(self):
        return False


class Hub:
    def __init__(self):
        self.state = dict(settings=dict(show_lock='', show_wave='bounce', show_loop_dir='alternate', show_audio=0.6,
                                        show_acts=True), calibration={}, looks=[dict(id='a', motion='still', speed=1.0)],
                          songs=[])
        self.active = 'a'
        self.commands = []
        self.pads = Pads()
        self.lock = threading.Lock()
        self.dmx = types.SimpleNamespace(chase=Director())
        self.hold = self.blackout = False
        self.song = None
        self.clock = (16.0, 120.0, 0)
        self.audioshow = types.SimpleNamespace(env=dict(kick=0.0), section='groove', gate=0.0)
        self.rig = types.SimpleNamespace(segs=[], channels=[], lamps=[])
        self.live = {}

    def look(self, i):
        return next((l for l in self.state['looks'] if l['id'] == i), None)

    def push_colour(self, c):
        return c

    def command(self, c):
        self.commands.append(c)
        if c.get('op') == 'setting':
            self.state['settings'][c['key']] = c['value']
        return True


HUB = Hub()
P = hub_push2.Push2(HUB)
check('Push opens on the fake User port', P.out is OUT and P.mode == 'play')


def last_pad(note):
    for m in reversed(OUT.sent):
        if m.type == 'note_on' and m.note == note:
            return m.velocity
    return None


def last_btn(cc):
    for m in reversed(OUT.sent):
        if m.type == 'control_change' and m.control == cc:
            return m.value
    return None


def palette_rgb(slot):
    for m in reversed(OUT.sent):
        if m.type == 'sysex' and list(m.data[:7]) == [0x00, 0x21, 0x1D, 0x01, 0x01, 0x03, slot]:
            d = m.data
            return (d[7] | d[8] << 7, d[9] | d[10] << 7, d[11] | d[12] << 7)
    return None


def press(note):
    P.handle(Msg('note_on', note=note, velocity=100))


def note(row, col):
    return 36 + row * 8 + col


# ---- the SHOW button
check('SHOW button is free in the live file', 'SHOW' not in open(os.path.join(REPO, 'hub_push2.py')).read().split('class Push2')[0]
      and ' 112' not in open(os.path.join(REPO, 'hub_push2.py')).read())
P.handle(Msg('control_change', control=hub_push2.SHOW, value=127))
check('MIX (CC 112) -> SHOW mode', P.mode == 'show' and HUB.pads.panics == 1)
check('SHOW button lit', last_btn(112) == 127)
check('other mode buttons dim', last_btn(hub_push2.NOTE) == 10 and last_btn(hub_push2.SESSION) == 10)
check('status shows act + bar x of 8', 'SHOW mode -- Burst (bar 3 of 8) -- lock: auto' in P.status)

# ---- pad LEDs
check('palette: playing = bright purple', palette_rgb(90) == (170, 60, 255))
check('palette: locked = medium purple', palette_rgb(91) == (90, 30, 140))
check('palette: rest = dim purple', palette_rgb(92) == (25, 8, 40))
check('playing act (Burst) pad bright', last_pad(note(7, 5)) == 90)
check('other acts dim', all(last_pad(note(7, c)) == 92 for c in range(5)))
check('AUTO lit (no lock)', last_pad(note(7, 6)) == 90)
check('acts on/off lit (acts on)', last_pad(note(7, 7)) == 90)
check('modes dim while an act plays', all(last_pad(note(6, c)) == 92 for c in range(7)))
check('wave bounce + loop alternate lit', last_pad(note(5, 0)) == 90 and last_pad(note(5, 4)) == 90
      and last_pad(note(5, 1)) == 92 and last_pad(note(5, 6)) == 92)
check('audio 60% lit', last_pad(note(4, 3)) == 90 and last_pad(note(4, 5)) == 92)
check('bottom four rows + spare pads dark', all(last_pad(note(r, c)) == 0 for r in range(4) for c in range(8))
      and last_pad(note(6, 7)) == 0 and last_pad(note(5, 7)) == 0 and last_pad(note(4, 6)) == 0)

# ---- pads -> settings (the hub's own 'setting' op)
def lastcmd():
    return HUB.commands[-1] if HUB.commands else None


press(note(7, 2))
check('Gobos pad -> show_lock gobos', lastcmd() == dict(op='setting', key='show_lock', value='gobos'))
check('locked act pad = medium, AUTO now dim', last_pad(note(7, 2)) == 91 and last_pad(note(7, 6)) == 92)
check('status shows the lock', 'lock: Gobos' in P.status)
press(note(7, 2))
check('tap the locked act again -> AUTO', lastcmd()['value'] == '')
press(note(6, 2))
check('Wave mode pad -> show_lock wave', lastcmd() == dict(op='setting', key='show_lock', value='wave'))
press(note(7, 6))
check('AUTO pad -> show_lock ""', lastcmd() == dict(op='setting', key='show_lock', value=''))
press(note(7, 7))
check('acts pad toggles show_acts off', lastcmd() == dict(op='setting', key='show_acts', value=False))
press(note(7, 7))
check('...and on again', lastcmd()['value'] is True)
press(note(5, 1))
check('forward pad -> show_wave forward', lastcmd() == dict(op='setting', key='show_wave', value='forward'))
check('forward lit, bounce dim', last_pad(note(5, 1)) == 90 and last_pad(note(5, 0)) == 92)
press(note(5, 5))
check('ccw pad -> show_loop_dir ccw', lastcmd() == dict(op='setting', key='show_loop_dir', value='ccw'))
press(note(4, 5))
check('100% pad -> show_audio 1.0', lastcmd() == dict(op='setting', key='show_audio', value=1.0))
press(note(4, 0))
check('0% pad -> show_audio 0.0', lastcmd()['value'] == 0.0 and last_pad(note(4, 0)) == 90)
n = len(HUB.commands)
press(note(0, 0))
press(note(6, 7))
P.handle(Msg('note_off', note=note(7, 2), velocity=0))
P.handle(Msg('polytouch', note=note(7, 2), value=90))
check('dark pads, releases and pressure send nothing', len(HUB.commands) == n)
check('all values are in rig_control /show/set allowlist', all(
    (c['key'] != 'show_wave' or c['value'] in ('bounce', 'forward', 'back', 'alternate')) and
    (c['key'] != 'show_loop_dir' or c['value'] in ('alternate', 'ccw', 'cw')) and
    (c['key'] != 'show_audio' or 0.0 <= c['value'] <= 1.0) and
    c['key'] in ('show_lock', 'show_acts', 'show_wave', 'show_loop_dir', 'show_audio') for c in HUB.commands))

# zones act playing a mode -> the mode pad is bright
HUB.dmx.chase.last = dict(act='zones', mode='loop', phrase_bar=0, zones=[dict(id='1A', level=1.0)])
P.refresh(force=True)
check('zones act: playing mode (Loop) bright, Zones act bright', last_pad(note(6, 3)) == 90 and last_pad(note(7, 3)) == 90)
HUB.dmx.chase.on = False
P.poll()
P.last_refresh = 0
P.poll()
check('director off: status says so, no pad bright', 'director off' in P.status
      and all(last_pad(note(6, c)) == 92 for c in range(7)))
HUB.dmx.chase.on = True
# leaving SHOW mode works as before
P.handle(Msg('control_change', control=hub_push2.NOTE, value=127))
check('NOTE -> back to PLAY mode, SHOW button dim', P.mode == 'play' and last_btn(112) == 10)
HUB.dmx = types.SimpleNamespace(chase=types.SimpleNamespace())        # old hub_chase without status()
P.handle(Msg('control_change', control=hub_push2.SHOW, value=127))
press(note(7, 0))
check('no director: SHOW mode still safe', P.mode == 'show' and 'director off' in P.status)
HUB.dmx = types.SimpleNamespace(chase=Director())

# ------------------------------------------------------------------ visuals: names TD really has
def ref_vis_for():
    txt = open(os.path.join(REF, 'td_hue_feed_send.txt')).read()
    i = txt.index('VIS_FOR = {') + len('VIS_FOR = ')
    depth, j = 0, i
    while True:
        depth += {'{': 1, '}': -1}.get(txt[j], 0)
        j += 1
        if depth == 0:
            break
    return ast.literal_eval(txt[i:j])


VIS_FOR = ref_vis_for()
TD_VIS = [l.split('/')[-2] for l in open(os.path.join(REF, 'td_geo_show_visuals.txt')) if '->' in l]
WANT = dict(hues='flower_of_life', heads='metatrons_cube', gobos='sri_yantra', uv='tesseract', burst='kaleidoscope',
            pulse='golden_angle', wave='chladni', loop='proc_mandala', call='proc_voronoi', split='proc_quasicrystal',
            orbit='proc_harmonograph', relay='proc_attractor')
check('TD_FORMS = TD hue_feed VIS_FOR keys', ss.TD_FORMS == set(VIS_FOR))
for k, vis in WANT.items():
    z = dict(act=k, mode='') if k in ss.ACTS else dict(act='zones', mode=k)
    f = ss.form_for(z)
    check('%s -> %s (TD has it)' % (k, vis), f in VIS_FOR and VIS_FOR[f][0] == vis and vis in TD_VIS)
check('unknown mode name is skipped', ss.form_for(dict(act='zones', mode='newmode')) is None)
ss.FORM_FOR['pulse'] = 'not_a_td_form'
check('form TD does not have is skipped', ss.form_for(dict(act='zones', mode='pulse')) is None)
ss.FORM_FOR['pulse'] = 'golden'
check('director off -> no form', ss.form_for(None) is None and ss.form_for(dict(on=False, act=None)) is None)
check('relay frame from hub_chase (no act) -> attractor', ss.form_for(dict(u=0.5)) == 'attractor')
check('a pad touched recently wins', ss.director_form(HUB, True) is None and ss.director_form(HUB, False) == 'kaleido')

# ------------------------------------------------------------------ message fields
S = ss.Sync()
HUB.dmx.chase.last = dict(act='zones', mode='wave', rgb=(0.5, 0.0, 1.0), zones=[dict(level=0.2), dict(level=0.6)])
f = S.fields(HUB, 100.0)
check('fields: act + mode', f['act'] == 'zones' and f['mode'] == 'wave')
check('fields: hue from the director colour (purple ~0.75)', abs(f['hue'] - 0.75) < 0.01)
for i in range(1, 20):
    f = S.fields(HUB, 100.0 + i * 0.033)
check('fields: level glides to the zones mean (0.4)', abs(f['level'] - 0.4) < 0.01)
HUB.dmx.chase.last['zones'] = [dict(level=0.0)]
f1 = S.fields(HUB, 100.0 + 20 * 0.033)
check('fields: level falls slower than it rises (one frame: -12%, a rise moves ~48%)', 0.33 < f1['level'] < 0.4)
check('fields: kick from drummer on the beat (beat 16.0)', f1['kick'] > 0.3)
HUB.clock = (16.5, 120.0, 0)
k = [S.fields(HUB, 101.0 + i * 0.033)['kick'] for i in range(1, 10)]
check('fields: kick decays between beats', all(b <= a for a, b in zip(k, k[1:])) and k[-1] < k[0])
check('fields: everything 0-1', all(0.0 <= S.fields(HUB, 102.0)[x] <= 1.0 for x in ('hue', 'level', 'kick')))
HUB.dmx.chase.last = dict(act='heads', heads={0: dict(level=0.5), 1: dict(level=0.5)})
f = S.fields(HUB, 103.0)
check('fields: act frame, heads levels, hue from director.hue', f['act'] == 'heads' and f['mode'] == ''
      and abs(f['hue'] - 0.78) < 1e-6 and f['level'] > 0)
HUB.dmx.chase.last = None
check('fields: director off -> act/mode empty only', S.fields(HUB, 104.0) == dict(act='', mode=''))

# ------------------------------------------------------------------ patched hub_visuals
V = hub_visuals.Visuals(HUB)
src = open(os.path.join(TMP, 'hub_visuals.py')).read()
check('Visuals has a Sync', isinstance(V.showsync, ss.Sync))
check('message gets the director fields', '**self.showsync.fields(h, now)' in src)
check('visual pick defers to a touched pad', 'touch[0] <= PAD_HOLD' in src and src.index('dform =') > src.index('want = self.wanted_form(look)'))

# ------------------------------------------------------------------ live files untouched
check('live hub_push2.py / hub_visuals.py unchanged', LIVE == {n: md5(os.path.join(REPO, n)) for n in LIVE})
check('no hub_showsync.py in the repo root yet', not os.path.exists(os.path.join(REPO, 'hub_showsync.py')))

print('\n%d passed, %d failed' % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
