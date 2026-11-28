#!/usr/bin/env python3
"""Offline tests for the Tap Dial layout (Nov 17). Fake rig_control, fake clock, temp files, no network,
nothing in the room changes."""
import importlib.util, json, os, socket, sys, tempfile, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))     # the Hue Rig folder (hue_stream etc.)
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(OSError('network blocked in tests'))
spec = importlib.util.spec_from_file_location('tap_switch_v2', os.path.join(HERE, 'tap_switch.py'))
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)
TMP = tempfile.mkdtemp()
ts.SETTINGS = os.path.join(TMP, 'tap_switch.json')
ts.DIAL_FILE = os.path.join(TMP, 'dial.json')
ts.LOG = os.path.join(TMP, 'tap.log')
ts._hub_alive_orig = ts._hub_alive
ok = bad = 0


def check(name, cond):
    global ok, bad
    if cond:
        ok += 1
    else:
        bad += 1
        print('FAIL', name)


# ---------------------------------------------------------------- fake rig_control
class FakeRC:
    def __init__(self, hub=False, ambient=False):
        self.calls, self.hub, self.ambient = [], hub, ambient
        self.STATE = {'look': 'rainbow', 'last_error': None}
        self.LOOKS = {k: ('x', (lambda k=k: self.calls.append(('look', k)))) for k in
                      ['purple', 'rainbow', 'rainbowroom', 'upbeat', 'movieglow', 'redglow', 'breathe_slow', 'modes',
                       'moviechill', 'morning', 'nightlight']}
        hp = types.SimpleNamespace(STATE={'on': {'1': True}}, calls=self.calls)
        hp.request_on = lambda quiet=False: (self.calls.append(('heads_on',)), 'Heads powering up -- ready')[1]
        hp.request_off = lambda why='': self.calls.append(('heads_off', why))
        hp.settings = lambda: {'warmup_s': -3}
        hp.is_plug = lambda l: False
        self.head_power = hp
        sp = types.SimpleNamespace(STATE={'hold_until': 0.0, 'on': {'1': True, '2': True}})
        sp.request_on = lambda quiet=False, why='': self.calls.append(('spots_on', why))
        sp.request_off = lambda why='': self.calls.append(('spots_off', why))
        sp.settings = lambda: {'manual_hold_min': 30}
        sp._now = lambda: 1000.0
        self.light_schedule = types.SimpleNamespace(status=lambda: {'night': '23:00'})
        self.SPOT_FX_UV_SKY = {'uv': 1.0, 'uv_only': True}
        self.spot_power = sp

    def apply(self, look):
        self.LOOKS[look][1]()
        self.STATE['look'] = look
        if look == 'modes':
            self.hub = True
        if look == 'purple':
            self.hub = False

    def hub_up(self):
        return self.hub

    def hub_setting(self, k, v):
        self.calls.append(('set', k, v))

    def hub_vibe(self, n, e=0.6):
        self.calls.append(('vibe', n))

    def hub_api(self, c):
        self.calls.append(('api', c.get('op'), c.get('key'), c.get('value')))

    def start_hub(self, p):
        self.calls.append(('start_hub', p))
        self.hub = True

    def stop_ambient(self):
        self.calls.append(('stop_ambient',))

    def movie_lights(self, what):
        self.calls.append(('movie_lights', what))
        self.hub = True

    def stop_hub(self):
        self.calls.append(('stop_hub',))
        self.hub = False

    def stop_all(self):
        self.calls.append(('stop_all',))
        self.hub = False

    def start_ambient(self, *a):
        self.calls.append(('ambient', a))
        self.ambient = True

    def running(self, name):
        return self.ambient

    def sh(self, cmd, timeout=15):
        return ''

    def hue_lights(self, body):
        self.calls.append(('lamps', body))

    def fill_on(self, on):
        self.calls.append(('fill_on', on))

    def fill_boost(self, on):
        self.calls.append(('fill_boost', on))


def fresh(**kw):
    rc = FakeRC(**kw)
    ts.RC['mod'] = rc
    for k, v in ts.TAP_LOOKS.items():
        rc.LOOKS.setdefault(k, v)
    ts.STATE.update(idx={1: -1, 2: -1, 3: -1, 4: -1}, intensity=1.0, applying=False, seen_look=rc.STATE['look'])
    ts.STATE['layers'] = {'heads': None, 'spots': None}
    ts.STATE.update(spots_off_at=0.0, heads_off_at=0.0)
    ts.STATE.update(mode=None, wave=None, vj=False, rshow=False, frozen=None, hit=None, gobo_override=None, colour=None, vj_acc=0)
    try:
        os.remove(ts.DIAL_FILE)
    except OSError:
        pass
    return rc


# ---------------------------------------------------------------- gestures
G = ts.Gestures(0.5, 0.6)
check('tap: nothing before settle', G.event(1, 'initial_press', 100.0, 10.0) == [] and
      G.event(1, 'short_release', 100.1, 10.1) == [] and G.due(10.5) == [])
check('tap: single after settle', G.due(10.75) == [('single', 1)] and G.due(20) == [])
G = ts.Gestures(0.5, 0.6)
G.event(2, 'initial_press', 100.0, 10.0)
G.event(2, 'short_release', 100.1, 10.1)
check('double: second press within window', G.event(2, 'initial_press', 100.35, 10.4) == [('double', 2)])
G.event(2, 'short_release', 100.45, 10.5)
check('double: no single afterwards', G.due(11.5) == [] and G.due(20) == [] and G.p == {})
G = ts.Gestures(0.5, 0.6)
G.event(3, 'initial_press', 100.0, 10.0)
G.event(3, 'short_release', 100.1, 10.1)
check('slow taps: first is a single', G.due(10.8) == [('single', 3)])
G.event(3, 'initial_press', 100.9, 10.9)
G.event(3, 'short_release', 101.0, 11.0)
check('slow taps: second is a single too', G.due(11.7) == [('single', 3)])
G = ts.Gestures(0.5, 0.6)
G.event(4, 'initial_press', 100.0, 10.0)
G.event(4, 'long_press', 100.8, 10.8)
G.event(4, 'repeat', 101.6, 11.6)
G.event(4, 'long_release', 102.0, 12.0)
check('hold: does nothing', G.due(13) == [] and G.due(30) == [] and G.p == {})
G = ts.Gestures(0.5, 0.6)
G.event(1, 'initial_press', 100.0, 10.0)
G.event(1, 'long_press', 100.8, 10.8)
check('hold, never released: dropped', G.due(16) == [] and G.p == {})
G = ts.Gestures(0.5, 0.6)
G.event(1, 'short_release', 100.1, 10.0)
check('release whose press was missed: a tap', G.due(10.7) == [('single', 1)])
G = ts.Gestures(0.5, 0.6)
G.event(1, 'initial_press', 100.0, 10.0)
G.event(2, 'initial_press', 100.2, 10.0)
G.event(1, 'short_release', 100.1, 10.0)
G.event(2, 'short_release', 100.3, 10.0)
check('two different buttons: two singles', sorted(G.due(10.7)) == [('single', 1), ('single', 2)])
# a whole double tap arriving in ONE event-stream batch (bridge batching)
G = ts.Gestures(0.5, 0.6)
btn = {'b1': 1, 'b2': 2, 'b3': 3, 'b4': 4}
def bev(rid, ev, t):
    return {'type': 'button', 'id': rid, 'button': {'button_report': {'event': ev, 'updated': t}}}
batch = [{'type': 'update', 'data': [bev('b4', 'short_release', '2026-11-17T04:15:56.553Z'),
                                     bev('b4', 'initial_press', '2026-11-17T04:15:56.453Z')]},
         {'type': 'update', 'data': [bev('b4', 'initial_press', '2026-11-17T04:15:56.803Z'),
                                     bev('b4', 'short_release', '2026-11-17T04:15:56.903Z')]}]
evs = ts.parse(batch, btn, set())
check('parse: sorted by bridge time', [e[2] for e in evs] == ['initial_press', 'short_release', 'initial_press', 'short_release'])
out = []
for e in evs:
    out += G.event(e[1], e[2], e[3], 50.0)
check('batched double tap = double', out == [('double', 4)] and G.due(60) == [])
check('bridge_ts', abs(ts.bridge_ts('2026-11-17T04:15:56.453Z') - ts.bridge_ts('2026-11-17T04:15:56.000Z') - 0.453) < 1e-6
      and ts.bridge_ts('junk') is None)
other = [{'type': 'update', 'data': [bev('zz', 'initial_press', '2026-11-17T04:15:56.453Z'),
                                     {'type': 'light', 'id': 'b1', 'on': {'on': True}}]}]
check('parse: other devices + lights ignored', ts.parse(other, btn, set()) == [])
rot = [{'type': 'update', 'data': [{'type': 'relative_rotary', 'id': 'r1', 'relative_rotary': {
    'rotary_report': {'action': 'repeat', 'rotation': {'direction': 'clock_wise', 'steps': 30, 'duration': 400}}}}]}]
check('parse: dial', ts.parse(rot, btn, {'r1'}) == [('dial', 'clock_wise', 30)] and ts.parse(rot, btn, set()) == [])
check('parse: junk safe', ts.parse(None, btn, {'r1'}) == [] and ts.parse([{'data': None}], btn, set()) == [])

# ---------------------------------------------------------------- coalesce
check('coalesce: singles of one button collapse with skips',
      ts.coalesce([('single', 1), ('single', 1), ('single', 2), ('single', 1)]) == [('single', 1, 2), ('single', 2, 0)])
check('coalesce: a double drops that button\'s earlier singles',
      ts.coalesce([('single', 4), ('single', 2), ('double', 4)]) == [('single', 2, 0), ('double', 4, 0)])
check('coalesce: plain', ts.coalesce([('double', 3)]) == [('double', 3, 0)])

# ---------------------------------------------------------------- DMX frame (layers)
NODE = [dict(name='H1', addr=85, pan_min=0, pan_max=65535, tilt_up=32768, tilt_dir=-1),
        dict(name='H2', addr=15), dict(name='H3', addr=29), dict(name='H4', addr=43),
        dict(name='S1', addr=101, type='focus17', tilt_up=32768, tilt_dir=1, tilt_max_deg=85.0, pan_min=0, pan_max=65535),
        dict(name='S2', addr=121, type='focus17', tilt_up=32768, tilt_dir=1, tilt_max_deg=55.0, pan_min=16990, pan_max=37622)]
TG = {str(i): {'pan': 6000 + i, 'tilt': 15000} for i in range(4)}
HEADS_B = [84, 14, 28, 42]
f0 = ts.frame(NODE, {'heads': None, 'spots': None}, 10.0, 1.0, TG)
check('frame: no layers -> all dark', not any(f0))
for hm in ts.HEAD_MODES:
    fh = ts.frame(NODE, {'heads': hm, 'spots': None, 'lamp_rgb': (255, 0, 0)}, 10.0, 1.0, TG)
    check('frame: heads %s lights all 4 heads, spots stay dark' % hm, all(fh[b + 5] > 8 for b in HEADS_B)
          and not any(fh[100:117]) and not any(fh[120:137]))
fg = ts.frame(NODE, {'heads': 'glow'}, 10.0, 1.0, TG)
r, g, b = fg[84 + 6], fg[84 + 7], fg[84 + 8]
check('frame: glow = purple (blue + some red, no green)', 60 < r < 200 and b == 255 and g == 0)
fc = ts.frame(NODE, {'heads': 'colour', 'lamp_rgb': (255, 90, 0)}, 10.0, 1.0, TG)
check('frame: colour mode = the lamps\' colour', tuple(fc[84 + 6:84 + 9]) == (255, 90, 0))
fr = ts.frame(NODE, {'heads': 'rainbow'}, 10.0, 1.0, TG)
check('frame: rainbow = all four heads the same colour', len({tuple(fr[b + 6:b + 9]) for b in HEADS_B}) == 1)
def lean_of(f, b, h, tdeg):
    return abs(((f[b + 2] << 8) | f[b + 3]) - int(h.get('tilt_up', 32768))) / 65535.0 * tdeg
def pan_of(f, b):
    return (f[b] << 8) | f[b + 1]
pans, leans = [], []
for t in range(0, 200, 2):
    fh = ts.frame(NODE, {'heads': 'sweep'}, float(t), 1.0, TG)
    pans.append(pan_of(fh, 84)); leans.append(lean_of(fh, 84, NODE[0], 180.0))
check('frame: heads cover the FULL pan range (0 to a full circle)', min(pans) < 600 and max(pans) > 43000)
check('frame: heads lean from 30 to 80 deg', 29.5 < min(leans) < 32 and 78 < max(leans) <= 80.5)
fs1 = ts.frame(NODE, {'heads': 'sweep'}, 5.0, 1.0, TG)
check('frame: sweep = all four heads in step', len({pan_of(fs1, b) for b in HEADS_B}) == 1)
fg5 = ts.frame(NODE, {'heads': 'glow'}, 5.0, 1.0, TG)
check('frame: glow = heads spread out (different positions)', len({pan_of(fg5, b) for b in HEADS_B}) > 1)
nh = dict(NODE[0], pan_min=0, pan_max=28520)
pw = [pan_of(ts.frame([nh], {'heads': 'sweep'}, float(t), 1.0, TG), 84) for t in range(0, 60)]
check('frame: a head with a pan window stays inside it', max(pw) <= 28520)
fu = ts.frame(NODE, {'spots': 'uv'}, 5.0, 1.0, TG)
check('frame: UV tapestry = UV only (dimmer 0, UV 255), heads dark', fu[100 + 9] == 0 and fu[100 + 11] == 255 and
      fu[100 + 10] == 12 and fu[120 + 11] == 255 and not any(fu[84:98]))
tilt1 = (fu[102] << 8) | fu[103]
check('frame: UV tapestry uses the calibrated centre (Spot 1 lean 40)', abs(abs(tilt1 - 32768) / 65535.0 * 240.0 - 40.0) < 0.5)
for mode in ts.SPOT_MODES[2:]:
    ok_all, p4, l4 = True, [], []
    for t in range(0, 120, 2):
        fs = ts.frame(NODE, {'spots': mode}, float(t), 1.0, TG)
        p4.append(pan_of(fs, 100)); l4.append(lean_of(fs, 100, NODE[4], 240.0))
        ok_all &= NODE[5]['pan_min'] <= pan_of(fs, 120) <= NODE[5]['pan_max']
        ok_all &= fs[105] == int(mode[4:]) and fs[108] == 12 and fs[104] in (97, 82) and fs[104] == fs[124]
    check('frame: %s roams the full range (pan + lean 30-80), its gobo, spots in step, no strobe' % mode,
          ok_all and min(p4) < 600 and max(p4) > 43000 and min(l4) < 32 and max(l4) > 78)
seen = []
for t in range(0, 33):
    f = ts.frame(NODE, {'spots': 'uvscan'}, float(t), 1.0, TG)
    seen.append((pan_of(f, 100), (f[102] << 8) | f[103]))
    assert f[109] == 0 and f[111] == 255
check('frame: UV scan visits all four of Spot 1\'s corners, UV only', all(any(abs(p - cp) < 40 and abs(tl - ct) < 40 for p, tl in seen)
      for cp, ct in ts.UV_CORNERS[4]))
check('frame: UV tapestry is the first spot mode', ts.SPOT_MODES[0] == 'uv')

# ---------------------------------------------------------------- buttons (v6 grammar)
ts._lamps_parallel = lambda m, body: m.calls.append(('lamps', body))
LAMPS_ON = [True]
class HSFake:
    def load_config(self): return {}
    def v2(self, cfg, path, method='GET', body=None):
        return {'data': [{'id': 'l1', 'dimming': {}, 'on': {'on': LAMPS_ON[0]}}]}
    def rgb_to_xyb(self, r, g, b):
        import hue_stream as real
        return real.rgb_to_xyb(r, g, b)
ts._hs = lambda: HSFake()
TGT = {'Above studio desk': {'0': {'pan': 100, 'tilt': 200}}, 'UV tapestry': {'0': {'pan': 11, 'tilt': 22}, '1': {'pan': 33, 'tilt': 44}},
       'Studio clouds': {'3': {'pan': 55, 'tilt': 66}}, 'Cloud above projector': {'3': {'pan': 1, 'tilt': 2, 'cloud': True}},
       'Cloud by top lamp': {'1': {'pan': 3, 'tilt': 4, 'cloud': True}}, 'Cloud above white shelf': {'3': {'pan': 5, 'tilt': 6, 'cloud': True}}}
os.makedirs(os.path.join(TMP, 'rig'), exist_ok=True)
json.dump({'settings': {'head_targets': TGT}}, open(os.path.join(TMP, 'rig', 'hub_state.json'), 'w'))
ts.HERE = os.path.join(TMP, 'rig')

POWER = ('heads_on', 'heads_off', 'spots_on', 'spots_off')
rc = fresh()
LAMPS_ON[0] = True
rc.head_power.STATE['on'] = {'1': False}; rc.spot_power.STATE['on'] = {'1': False}
names = [ts.single(1) for _ in range(9)]
check('1 tap: exactly 8 colours, then round again', [n.split(' (')[0] for n in names] == ['colour ' + n for n in
      ['red', 'orange', 'yellow', 'green', 'blue', 'indigo', 'violet', 'pink', 'red']])
lamp_calls = [c[1] for c in rc.calls if c[0] == 'lamps']
check('1 tap: every lamp, full, one colour', len(lamp_calls) == 9 and all(b['dimming']['brightness'] == 100.0 for b in lamp_calls))
check('1 tap: nothing powered', not any(c[0] in POWER + ('set',) for c in rc.calls))
rc = fresh()
LAMPS_ON[0] = True
rc.head_power.STATE['on'] = {'1': True}; rc.spot_power.STATE['on'] = {'1': True}
ts.STATE['layers'].update(heads='sweep', spots='gobo64')
r = ts.single(1)
check('1 tap: one colour for everything that is on', r == 'colour red (lamps, heads, spots)' and ts.STATE['colour'] == ('red', (255, 0, 0))
      and ts.STATE['layers'] == {'heads': 'sweep', 'spots': 'gobo64'})
f = ts.frame(NODE, dict(ts.STATE['layers'], rgb=(255, 0, 0), slot=ts.WHEEL_SLOT['red']), 5.0, 1.0, TG)
check('frame: heads keep their movement, in the colour', all(tuple(f[b + 6:b + 9]) == (255, 0, 0) for b in HEADS_B))
check('frame: spot beams on the matching wheel slot', f[104] == 22 and f[124] == 22)
fu = ts.frame(NODE, {'spots': 'uv', 'slot': 22}, 5.0, 1.0, TG)
check('frame: UV modes stay UV', fu[109] == 0 and fu[111] == 255)
fr = ts.frame(NODE, {'heads': 'rainbow', 'rgb': (255, 0, 0)}, 5.0, 1.0, TG)
check('frame: the heads rainbow mode stays a rainbow', tuple(fr[84 + 6:84 + 9]) != (255, 0, 0))
rc = fresh(hub=True)
LAMPS_ON[0] = False
rc.head_power.STATE['on'] = {'1': True}; rc.spot_power.STATE['on'] = {'1': True}
ts.STATE['layers'].update(heads='hub', spots=None)
r = ts.single(1)
check('1 tap during the show (lamps off): show stops, heads + spots carry on in the colour', ('stop_hub',) in rc.calls and
      ts.STATE['layers'] == {'heads': 'glow', 'spots': 'gobo32'} and not any(c[0] == 'lamps' for c in rc.calls))
rc = fresh()
LAMPS_ON[0] = True
ts.single(1)
ts.scene('chill')
check('a scene clears the colour (brings its own)', ts.STATE['colour'] is None)
rc = fresh()
LAMPS_ON[0] = False
rc.head_power.STATE['on'] = {'1': False}; rc.spot_power.STATE['on'] = {'1': False}
rc.calls.clear()
check('1 tap with everything off: nothing', ts.single(1).startswith('everything is off') and rc.calls == [])
LAMPS_ON[0] = False
rc.calls.clear()
check('1 hold: lamps ON when off', ts.hold(1) == 'lamps ON' and rc.calls[-1][1]['on'] == {'on': True})
LAMPS_ON[0] = True
check('1 hold: lamps OFF when on', ts.hold(1) == 'lamps OFF' and rc.calls[-1] == ('lamps', {'on': {'on': False}, 'dynamics': {'duration': 600}}))
check('no double taps: a "double" is just a tap', ts.double(1).startswith('colour '))

rc = fresh()
rc.head_power.STATE['on'] = {'1': False}
check('2 tap with heads off: nothing', ts.single(2).startswith('heads are off') and rc.calls == [])
check('2 hold: heads ON (glow)', ts.hold(2) == 'heads ON (glow)' and ('heads_on',) in rc.calls and ts.STATE['layers']['heads'] == 'glow')
rc.head_power.STATE['on'] = {'1': True}
check('2 taps cycle the heads modes, never power', [ts.single(2) for _ in range(4)] == ['heads colour', 'heads rainbow', 'heads sweep', 'heads glow']
      and rc.calls.count(('heads_on',)) == 1 and not any(c[0] == 'heads_off' for c in rc.calls))
check('2 hold: heads OFF', ts.hold(2) == 'heads OFF' and any(c[0] == 'heads_off' for c in rc.calls) and ts.STATE['layers']['heads'] is None)

rc = fresh()
rc.spot_power.STATE['on'] = {'1': False}
check('3 tap with spots off: nothing', ts.single(3).startswith('spots are off'))
check('3 hold: spots ON on the UV tapestry', ts.hold(3) == 'spots ON (UV tapestry)' and ts.STATE['layers']['spots'] == 'uv')
rc.spot_power.STATE['on'] = {'1': True}
check('3 taps: scan, the gobos, back to UV', [ts.single(3) for _ in range(8)] == ['spots uvscan', 'spots gobo16', 'spots gobo32', 'spots gobo48',
      'spots gobo64', 'spots gobo80', 'spots gobo96', 'spots uv'])
rc.calls.clear()
check('3 hold: spots OFF + held off', ts.hold(3) == 'spots OFF' and ('spots_off', 'tap dial') in rc.calls and ts.STATE['layers']['spots'] is None)

# scenes: only what's on, nothing switched
def scene_case(L, H, S, hub=False):
    rc = fresh(hub=hub)
    LAMPS_ON[0] = L
    rc.head_power.STATE['on'] = {'1': H}
    rc.spot_power.STATE['on'] = {'1': S}
    return rc
for L, H, S in ((True, True, True), (True, False, False), (False, True, True), (False, False, True), (False, False, False)):
    rc = scene_case(L, H, S)
    got = [ts.single(4) for _ in range(5)]
    check('scenes L%d H%d S%d: the 4 (simplified Nov 20) in order, then round' % (L, H, S), [g.split(' (')[0].split(':')[0] for g in got] ==
          ['scene Purple', 'scene Rainbow show', 'scene Movie', 'scene Night sky', 'scene Purple'])
    check('scenes L%d H%d S%d: nothing switched on or off' % (L, H, S), not any(c[0] in POWER for c in rc.calls))
    check('scenes L%d H%d S%d: lamps untouched when off' % (L, H, S), L or not any(c[0] in ('lamps', 'ambient') or c[:2] == ('look', 'purple') for c in rc.calls))
    check('scenes L%d H%d S%d: off groups stay out' % (L, H, S), (H or ts.STATE['layers']['heads'] is None) and (S or ts.STATE['layers']['spots'] is None))
rc = scene_case(True, True, True)
ts.scene('studio')
check('Studio work (all on): purple 60, heads on studio aims, spots UV', any(c[0] == 'lamps' and c[1]['dimming']['brightness'] == 60.0 for c in rc.calls)
      and ts.STATE['layers'] == {'heads': 'pose', 'spots': 'uv'} and ts.STATE['pose'] == {0: [(100, 200)], 1: [(33, 44)], 3: [(55, 66)]})
rc = scene_case(True, True, True)
ts.scene('movie')
check('Movie (lamps on): the hub follows the film, UV through the hub', [c for c in rc.calls if not c[0].startswith('fill')][0] == ('stop_ambient',) and ('vibe', 'dreamy') in rc.calls
      and any(c[:2] == ('set', 'spot_fx') and c[2].get('uv_only') for c in rc.calls))
rc = scene_case(True, True, False)
ts.scene('movie')
check('Movie with the spots off: no UV asked for', ('set', 'spot_fx', {}) in rc.calls)
rc = scene_case(True, True, True)
ts.scene('nightsky')
check('Night sky (all on): dim indigo, UV scan, heads over the clouds', any(c[0] == 'lamps' and c[1]['dimming']['brightness'] == 25.0 for c in rc.calls)
      and ts.STATE['layers'] == {'heads': 'clouds', 'spots': 'uvscan'} and ts.STATE['pose'] == {1: [(3, 4)], 3: [(1, 2), (5, 6)]})
rc = scene_case(True, True, True)
ts.scene('show')
check('Show (lamps on): the auto show on the hub', ('set', 'dmx_pattern', 'modes') in rc.calls and ('set', 'show_lock', '') in rc.calls
      and ts.STATE['layers']['heads'] == 'hub')
rc = scene_case(False, True, True)
ts.scene('show')
check('Show with the lamps off: no hub (it would light the lamps) -- heads sweep, gobos', not any(c[0] == 'start_hub' for c in rc.calls)
      and ts.STATE['layers'] == {'heads': 'sweep', 'spots': 'gobo32'})
rc = scene_case(True, True, True)
ts.scene('rainbow')
check('All-out rainbow (all on)', ts.STATE['wave'] == 'rall' and ts.STATE['layers'] == {'heads': 'rainbow_sweep', 'spots': 'rainbowgobo'})
rc = scene_case(True, True, True, hub=True)
ts.scene('chill')
check('leaving the show for Chill stops the hub', ('stop_hub',) in rc.calls and ts.STATE['layers'] == {'heads': 'glow', 'spots': 'gobo48'})
fr = ts.frame(NODE, {'heads': 'rainbow_sweep', 'spots': 'rainbowgobo'}, 3.0, 1.0, TG)
check('All-out rainbow frame: 4 head colours, spots lit, wheel colours (no white)',
      len({tuple(fr[b + 6:b + 9]) for b in HEADS_B}) == 4 and fr[84 + 5] > 90 and fr[109] > 200 and fr[104] in ts.WHEEL)
fc = ts.frame(NODE, {'heads': 'clouds', 'pose': {0: [(1000, 2000), (3000, 4000)]}, 'head_rgb': (60, 90, 255)}, 0.0, 1.0, TG)
check('clouds frame: head 1 on its first cloud, heads without clouds dark', pan_of(fc, 84) == 1000 and fc[14 + 5] == 0)

# hold 4 (Nov 19): Michael's SAVED SHOW
ts.HERE_SAVED = ts.HERE
json.dump({'_note': 'x', 'rb_favourite': 'chase', 'spot_scan': True, 'chase_bounce': True, 'movie': True}, open(os.path.join(ts.HERE, 'show_default.json'), 'w'))
rc = scene_case(True, False, False)
r4 = ts.hold(4)
check('4 hold (show off): SHOW ON -- heads + spots power on, then his saved show with every saved setting',
      r4.startswith('show ON -- Rainbow show (to the music)') and ('set', 'rb_favourite', 'chase') in rc.calls and ('set', 'spot_scan', True) in rc.calls
      and ('set', 'chase_bounce', True) in rc.calls and ('set', 'dmx_pattern', 'rainbow') in rc.calls
      and ('heads_on',) in rc.calls and any(c[0] == 'spots_on' for c in rc.calls))
rc.calls[:] = []
rc.head_power.STATE['on'] = {'1': True}; rc.spot_power.STATE['on'] = {'1': True}
r5 = ts.hold(4)
pur = [c[1] for c in rc.calls if c[0] == 'lamps']
check('4 hold again (show on): SHOW OFF -- show stops, heads + spots power off, lamps purple',
      r5.startswith('show OFF') and ('stop_hub',) in rc.calls and any(c[0] == 'heads_off' for c in rc.calls)
      and any(c[0] == 'spots_off' for c in rc.calls) and pur and pur[-1]['dimming']['brightness'] == 100.0)
check('after show off, tap 4 goes on round the scenes (Rainbow show next)', ts.single(4).startswith('scene Rainbow show'))
rc = scene_case(False, False, False)
rc.hub = False
check('4 hold with everything off: lamps come on, the show starts', ts.hold(4).startswith('show ON') and
      any(c[0] == 'lamps' and c[1].get('on') == {'on': True} for c in rc.calls))
rc = scene_case(True, True, True)
ts.STATE['vj'] = False
rc = scene_case(True, True, True); rc.hub = False; ts.hold(4)
check('4 hold: the safety basics win over the saved file (movie stays off), notes are never sent',
      ('set', 'movie', True) not in rc.calls and ('set', 'movie', False) in rc.calls and not [c for c in rc.calls if c[:2] == ('set', '_note')])
os.remove(os.path.join(ts.HERE, 'show_default.json'))
rc = scene_case(True, True, True)
check('4 hold with no saved file: the show still starts (the basics)', ts.hold(4).startswith('show ON -- Rainbow show (to the music)'))
rc = scene_case(True, True, True)
ts.STATE['idx'][4] = 1
r = 'scene ' + ts.scene('vj')
vjs = [c[3] for c in rc.calls if c[:3] == ('api', 'setting', 'rb_vj')]
check('VJ (tap 4 round to it, lamps on): VJ ON THE MUSIC -- the show runs, the dial\'s first piece is chase, entry blink',
      r == 'scene VJ: Rainbow chase (on the music)' and ts.STATE['vj'] and ts.STATE['vj_music'] and ('set', 'dmx_pattern', 'rainbow') in rc.calls
      and vjs and vjs[-1]['piece'] == 'chase' and vjs[-1]['hit']['kind'] == 'blink' and not any(c[0] in POWER for c in rc.calls))
check('VJ music dial: right = the next piece of the show', ts.vj_dial(150) == 'VJ -> Rainbow scatter' and
      [c[3] for c in rc.calls if c[:3] == ('api', 'setting', 'rb_vj')][-1]['piece'] == 'scatter')
check('VJ music dial: left = back', ts.vj_dial(-150) == 'VJ -> Rainbow chase')
check('VJ music dial: a nudge does nothing', ts.vj_dial(60) is None)
last = lambda: [c[3] for c in rc.calls if c[:3] == ('api', 'setting', 'rb_vj')][-1]
check('VJ music tap 1: a colour flash (sent to the show)', ts._vj_or(1, 'single', 0).startswith('VJ colour flash') and last()['hit']['kind'] == 'colour')
check('VJ music tap 2: cut to black', ts._vj_or(2, 'single', 0) == 'VJ cut to black' and last()['hit']['kind'] == 'cut')
check('VJ music tap 3: one colour on', ts._vj_or(3, 'single', 0) == 'VJ next colour (ROY G BIV)' and last()['hit']['kind'] == 'skip')
check('VJ music tap 4: freeze / unfreeze', ts._vj_or(4, 'single', 0) == 'VJ FREEZE' and last()['freeze'] is True
      and ts._vj_or(4, 'single', 0) == 'VJ unfreeze' and last()['freeze'] is False)
check('VJ music hold 2: still the heads power', ts._vj_or(2, 'hold', 0).startswith('heads'))
check('VJ music hold 4: leaves -- back to the Rainbow show, the show\'s own choices back', ts._vj_or(4, 'hold', 0) ==
      'left VJ -> Rainbow show (to the music)' and not ts.STATE['vj'] and last() == {})
check('4 tap after leaving VJ: carries on round the scenes (Movie next)', ts.single(4).startswith('scene Movie'))
ts.scene('rshow')
check('a scene after VJ never leaves the show locked to a piece', last() == {})
rc = scene_case(False, True, True)
ts.scene('rchase')
ts.scene('vj')
check('4 hold in timed VJ (lamps off): leaves VJ', ts._vj_or(4, 'hold', 0).startswith('left VJ') and not ts.STATE.get('vj'))
rc = scene_case(False, True, True)
check('VJ with the lamps off: VJ on the timed rainbows', ts.scene('vj').startswith('VJ: ') and not ts.STATE.get('vj_music'))

# ---------------------------------------------------------------- rainbow waves on the zones (v10)
ZS = ts.ZONES_DEFAULT
check('loop order: out along the A wall, back along B', ts.loop_order(list(ZS)) == ['1A', '2A', '3A', '2B', '1B'])
# wave: a hue seen at column 1 reaches column 2 later (door -> studio)
h1 = ts._zone_hue_raw('rwave', '1A', 10.0, ZS)
later = [tt / 10.0 for tt in range(100, 300) if abs(((ts._zone_hue_raw('rwave', '2A', tt / 10.0, ZS) - h1 + 180) % 360) - 180) < 2]
check('rainbow wave travels from the front door toward the studio', later and later[0] > 10.0)
check('rainbow wave: zones in the same column share the colour', ts.zone_hue('rwave', '1A', 5, ZS) == ts.zone_hue('rwave', '1B', 5, ZS))
b0 = [round(ts.zone_hue('rbounce', z, 0.0, ZS)) for z in ('1A', '2A', '3A')]
b8 = [round(ts.zone_hue('rbounce', z, 8.0, ZS)) for z in ('1A', '2A', '3A')]
check('rainbow bounce: the colour front is at the door, then at the studio 8 s later', b0[0] != b0[2] and b8[2] != b8[0]
      and abs(((ts._zone_hue_raw('rbounce', '3A', 8.0, ZS) - 360 * 8.0 / 40.0) % 360)) < 1)
lp = [ts._zone_hue_raw('rloop', z, 0.0, ZS) for z in ts.loop_order(list(ZS))]
check('rainbow loop: the 5 zones spread evenly round the wheel', all(abs(((lp[k] - lp[k + 1]) % 360) - 72) < 0.01 for k in range(4)))
st = [ts.zone_rgb('rsteps', '1A', tt, ZS) for tt in (0.0, 2.0, 4.0, 13.9, 14.0)]
check('rainbow steps: ROY G BIV (7, no pink), a new one every 2 s, round again after 14 s', st[0] == ts.HUE_COLOURS[0][1] and st[1] == ts.HUE_COLOURS[1][1]
      and st[2] == ts.HUE_COLOURS[2][1] and st[3] == ts.HUE_COLOURS[6][1] and st[4] == ts.HUE_COLOURS[0][1])
check('rainbow steps: every zone the same colour (all in sync)', len({ts.zone_rgb('rsteps', z, 6.0, ZS) for z in ZS}) == 1)
fs_ = ts.fixture_zone_rgb('rsteps', 6.0, ZS)
check('rainbow steps: every head + spot the same colour too', len(set(fs_.values())) == 1 and fs_[0] == ts.HUE_COLOURS[3][1] and ts.HUE_COLOURS[3][0] == 'green')
fz = ts.fixture_zone_rgb('rwave', 3.0, ZS)
check('fixtures take their zone colour (head 3 + spot 2 = 1A, head 4 + spot 1 = 2A)', fz[2] == fz[5] == ts.zone_rgb('rwave', '1A', 3.0, ZS)
      and fz[3] == fz[4] == ts.zone_rgb('rwave', '2A', 3.0, ZS) and set(fz) == {0, 1, 2, 3, 4, 5})
check('wheel slots: red 22, green 52, blue 37, pink 82, purple 97', [ts.wheel_slot(c) for c in ((255, 0, 0), (0, 255, 30), (0, 60, 255),
      (255, 30, 150), (110, 0, 255))] == [22, 52, 37, 82, 97])
fw = ts.frame(NODE, {'heads': 'zonewave', 'spots': 'zonewave', 'zone_rgb': fz}, 3.0, 1.0, TG)
check('frame: each head in its zone colour', all(tuple(fw[b + 6:b + 9]) == fz[k] for k, b in enumerate(HEADS_B)))
check('frame: each spot on its zone\'s wheel slot', fw[104] == ts.wheel_slot(fz[4]) and fw[124] == ts.wheel_slot(fz[5]))
g1 = ts.frame(NODE, {'spots': 'zonesteps', 'zone_rgb': fz, 'abs_t': 0.5}, 0.5, 1.0, TG)[105]
g2 = ts.frame(NODE, {'spots': 'zonesteps', 'zone_rgb': fz, 'abs_t': 2.5}, 2.5, 1.0, TG)[105]
check('frame: rainbow steps change gobo with every colour step', g1 == 16 and g2 == 32)
# lamp driver
class HSZ(HSFake):
    def v2(self, cfg, path, method='GET', body=None):
        if method == 'PUT':
            PUTS.append((path, body)); return {}
        return {'data': [dict(id='a', dimming={}, on={'on': True}, metadata={'name': 'Top Lamp'}),
                         dict(id='b', dimming={}, on={'on': True}, metadata={'name': 'Behind Desk'}),
                         dict(id='c', dimming={}, on={'on': True}, metadata={'name': 'Hue Play floor lamp large 1'}, gradient={}),
                         dict(id='d', dimming={}, on={'on': False}, metadata={'name': 'Floor Shade'})]}
PUTS = []
real_hs = ts._hs
ts._hs = lambda: HSZ()
ts.zones = lambda: ZS
rc = fresh()
ts.STATE['wave'] = 'rwave'
bodies = ts.lamp_wave_tick(3.0, push=False)
check('lamp wave: lamps in different zones get different colours', bodies['Top Lamp']['color'] != bodies['Behind Desk']['color'])
check('lamp wave: the gradient lamp gets 5 rainbow points', len(bodies['Hue Play floor lamp large 1']['gradient']['points']) == 5)
check('lamp wave: a lamp that is off stays off (not sent)', 'Floor Shade' not in bodies)
ts.STATE['wave'] = 'rsteps'
bodies = ts.lamp_wave_tick(2.0, push=False)
check('lamp steps: snappy (250 ms), solid colour even on the gradient lamp', all(b['dynamics']['duration'] == 250 and 'color' in b for b in bodies.values()))
ts.STATE['wave'] = None
check('no wave: lamp driver sends nothing', ts.lamp_wave_tick(2.0, push=False) == {})
ts._hs = real_hs
ts._hs = lambda: HSFake()
# scenes + hold 4 family
for name, spot in (('rwave', 'zonewave'), ('rbounce', 'zonewave'), ('rloop', 'zonewave'), ('rsteps', 'zonesteps')):
    rc = scene_case(True, True, True)
    ts.scene(name)
    check('%s (all on): lamps on the zone driver, heads + spots in the wave' % name, ts.STATE['wave'] == name and
          ts.STATE['layers'] == {'heads': 'zonewave', 'spots': spot} and not any(c[0] in POWER for c in rc.calls))
rc = scene_case(False, True, False)
ts.scene('rloop')
check('Rainbow loop with only the heads on: heads in the loop, lamps untouched', ts.STATE['wave'] == 'rloop' and
      ts.STATE['layers'] == {'heads': 'zonewave', 'spots': None} and not any(c[0] in ('lamps', 'ambient') for c in rc.calls))
rc = scene_case(False, True, True)
ts.STATE['mode'] = None
ts.scene('vj')
got = [ts.vj_dial(150).split(' (')[0] for _ in range(len(ts.RAINBOWS))]
check('VJ dial: every rainbow mode in turn (best first), then round again', got == ['VJ -> ' + ts.SCENE_NAMES[m] for m in ts.RAINBOWS[1:] + ts.RAINBOWS[:1]])
rc = scene_case(True, True, True)
ts.scene('vj')
got = [ts.vj_dial(150) for _ in range(len(ts.VJ_PIECES))]
check('VJ music dial: every piece of the show in turn, then round again', got == ['VJ -> ' + ts.RB_PIECE_NAMES[m] for m in ts.VJ_PIECES[1:] + ts.VJ_PIECES[:1]])
ts.single(1)
check('button 1 colour stops the lamp wave', ts.STATE['wave'] is None)

# no pink in rainbow modes
check('nopink: the wheel maps to red..violet..red', ts.nopink(0) == 0 and abs(ts.nopink(180) - 275) < 1e-9 and ts.nopink(359.9) < 1)
import colorsys as _cs
def is_pink(rgb):
    h, sat, _ = _cs.rgb_to_hsv(*[x / 255.0 for x in rgb]); return sat > 0.3 and 290 < h * 360 < 345
check('no pink anywhere in the rainbow waves', not any(is_pink(ts.zone_rgb(k, z, tt / 4.0, ZS)) for k in ('rwave', 'rbounce', 'rloop', 'rall', 'rsync', 'rsteps')
      for z in ZS for tt in range(0, 480)))
check('no pink on the heads in rainbow / all-out', not any(is_pink(tuple(ts.frame(NODE, {'heads': hm}, tt / 4.0, 1.0, TG)[84 + 6:84 + 9]))
      for hm in ('rainbow', 'rainbow_sweep') for tt in range(0, 400)))
check('no pink on the spot wheel in all-out', 82 not in ts.WHEEL)
rc = scene_case(True, True, True)
ts.scene('chill')
check('Chill: slow pink-free rainbow fade on the lamps, heads glow, gobos', ts.STATE['wave'] == 'rsync' and ts.STATE['layers'] == {'heads': 'glow', 'spots': 'gobo48'})

rc = scene_case(True, True, True)
rc.running = lambda name: name == 'hue_hub.py'          # a hub still starting (not answering yet)
ts.scene('studio')
check('a hub that is still starting is stopped too when leaving Movie/Show', ('stop_hub',) in rc.calls)

# ---------------------------------------------------------------- v11: 9 more rainbow modes, Rainbow show, VJ, freeze
hr = ts._zone_hue_raw('rripple', '3A', 10.0, ZS)
later = [tt / 10.0 for tt in range(100, 300) if abs(((ts._zone_hue_raw('rripple', '2A', tt / 10.0, ZS) - hr + 180) % 360) - 180) < 2]
check('ripple: colour radiates from the studio desk (3A) toward the door', later and later[0] > 10.0)
check('wall split: the A wall and the B wall half the wheel apart (before no-pink)', abs(((ts._zone_hue_raw('rsplit', '1A', 7.0, ZS)
      - ts._zone_hue_raw('rsplit', '1B', 7.0, ZS)) % 360) - 180) < 1e-6)
lit = [[z for z in ZS if ts.zone_level('rchase', z, tt * 0.6 + 0.1, ZS) == 1.0] for tt in range(5)]
check('chase: exactly one zone lit at a time, round the room', all(len(x) == 1 for x in lit) and [x[0] for x in lit] == ts.loop_order(list(ZS)))
sp = [ts.zone_hue('rsparkle', z, tt * 1.2, ZS) for z in ZS for tt in range(20)]
check('sparkle: zones twinkle (lots of different colours), same every time (deterministic)', len({round(x) for x in sp}) > 10 and
      sp == [ts.zone_hue('rsparkle', z, tt * 1.2, ZS) for z in ZS for tt in range(20)])
bl = [ts.zone_level('rbreath', '1A', tt / 2.0, ZS) for tt in range(21)]
check('breath: the room breathes 25%..100% every 10 s', abs(min(bl) - 0.25) < 0.01 and abs(max(bl) - 1.0) < 0.01)
check('no pink in the new modes either', not any(is_pink(ts.zone_rgb(k, z, tt / 3.0, ZS)) for k in ('rripple', 'rsplit', 'rchase', 'rsparkle', 'rbreath')
      for z in ZS for tt in range(0, 300)))
fz = ts.fixture_zone_level('rchase', 0.1, ZS)
check('chase: heads + spots follow the lit zone (1A first: head 3 + spot 2)', fz[2] == fz[5] == 1.0 and fz[0] == 0.06)
f = ts.frame(NODE, {'heads': 'zonewave', 'spots': 'zonewave', 'zone_rgb': ts.fixture_zone_rgb('rchase', 0.1, ZS), 'zone_level': fz}, 0.1, 1.0, TG)
check('chase frame: head 3 bright, head 1 nearly dark', f[28 + 5] > 80 and f[84 + 5] < 20)
# modes
for name in [m for m in ts.RAINBOWS]:
    rc = scene_case(True, True, True)
    r = ts.scene(name)
    kind, hm, sm = ts.MODES[name]
    check('%s (all on): lamps %s, heads %s, spots %s, nothing switched' % (name, kind, hm, sm), ts.STATE['wave'] == kind and
          ts.STATE['mode'] == name and ts.STATE['layers'] == {'heads': hm, 'spots': sm} and not any(c[0] in POWER for c in rc.calls))
rc = scene_case(False, True, False)
ts.scene('rconst')
check('constellation (heads only): heads hop every saved aim, lamps untouched', ts.STATE['layers'] == {'heads': 'constellation', 'spots': None}
      and ts.STATE['pose'] and all(len(v) >= 1 for v in ts.STATE['pose'].values()) and not any(c[0] == 'lamps' for c in rc.calls))
cf = [ts.frame(NODE, {'heads': 'constellation', 'pose': {0: [(100, 200), (300, 400), (500, 600)]}}, tt, 1.0, TG) for tt in (0.0, 6.0)]
check('constellation frame: a new colour each hop', tuple(cf[0][84 + 6:84 + 9]) != tuple(cf[1][84 + 6:84 + 9]) and pan_of(cf[1], 84) != pan_of(cf[0], 84))
c3 = ts.frame(NODE, {'heads': 'constellation', 'pose': {i: [(100 * i, 200), (300 + i, 400), (500, 600 + i)] for i in range(4)}}, 7.0, 1.0, TG)
check('constellation: all four heads one colour, hopping together', len({tuple(c3[b + 6:b + 9]) for b in HEADS_B}) == 1)
tn = [ts.frame(NODE, {'heads': 'tunnel', 'pose': {0: [(111, 222)], 1: [(333, 444)]}}, tt, 1.0, TG) for tt in (5.0, 15.0)]
check('tunnel: on the tapestry for 10 s, then fanned out', pan_of(tn[0], 84) == 111 and pan_of(tn[1], 84) != 111)
check('tunnel: the heads share one colour', len({tuple(tn[0][b + 6:b + 9]) for b in HEADS_B}) == 1)
mr = ts.frame(NODE, {'heads': 'mirror'}, 3.0, 1.0, TG)
check('mirror: mirrored movement, one colour', len({tuple(mr[b + 6:b + 9]) for b in HEADS_B}) == 1 and pan_of(mr, 84) != pan_of(mr, 14))
kf = ts.frame(NODE, {'spots': 'kaleido'}, 3.0, 1.0, TG)
check('kaleidoscope: gobos spinning against each other, same colour, on the tapestry', kf[106] == 60 and kf[126] == 190
      and kf[104] == kf[124] and kf[109] > 200)

# Rainbow show: weighted picks
import random as _r
json.dump({'ratings': {'rsplit': 'fav', 'rchase': 'drop'}}, open(os.path.join(TMP, 'rig', 'tap_rainbow.json'), 'w'))
ts.RATINGS = os.path.join(TMP, 'rig', 'tap_rainbow.json')
rng = _r.Random(7)
picks = [ts.pick_rainbow('rsparkle', rng) for _ in range(3000)]
check('Rainbow show: a dropped mode never plays', 'rchase' not in picks)
check('Rainbow show: never the same mode twice in a row', 'rsparkle' not in picks)
check('Rainbow show: a favourite comes up ~3x as often', 2.3 < picks.count('rsplit') / max(1, picks.count('rbreath')) < 3.8)
json.dump({'scores': {'rsteps': 10, 'rbounce': 4, 'rwave': 3}}, open(os.path.join(TMP, 'rig', 'tap_rainbow.json'), 'w'))
check('scores: 8+ = favourite, 4-7 = normal, under 4 = never', (ts.weight('rsteps'), ts.weight('rbounce'), ts.weight('rwave')) == (3.0, 1.0, 0.0))
check('only modes scoring 6+ are left in the rainbow family', ts.RAINBOWS == ['rsteps', 'rchase', 'rbreath', 'rripple', 'rainbow', 'rsparkle', 'rsplit'])
rc = scene_case(True, True, True)
r = ts.scene('rshow')
check('Rainbow show (lamps on): the MUSIC show -- hub director on the rainbow pattern', r == 'Rainbow show (to the music)'
      and ('set', 'dmx_pattern', 'rainbow') in rc.calls and ('set', 'dmx_strobe', 'off') in rc.calls and ts.STATE['layers']['heads'] == 'hub'
      and not any(c[0] in POWER for c in rc.calls))
rc = scene_case(False, True, True)
r = ts.scene('rshow')
check('Rainbow show with the lamps off: cycles the rainbow modes by itself (no hub)', r.startswith('Rainbow show: ') and ts.STATE['rshow']
      and ts.STATE['mode'] in ts.RAINBOWS and not any(c[0] == 'start_hub' for c in rc.calls))
while not ts.JOBS.empty():
    ts.JOBS.get_nowait()
ts.STATE['rshow_next'] = 0
ts.rshow_tick()
check('Rainbow show: time up -> the next mode is queued', ts.JOBS.get_nowait() == ('auto', 0))
ts.single(1)
check('a colour by hand ends the Rainbow show', ts.STATE['rshow'] is False)

# VJ (timed rainbows: the lamps are off, so no music engine)
rc = scene_case(False, True, True)
ts.scene('rchase')
r = ts.scene('vj')
check('VJ starts on the mode that was playing', r.startswith('VJ: Rainbow chase') and ts.STATE['vj'])
check('VJ dial: a small nudge does nothing', ts.vj_dial(60) is None and ts.STATE['mode'] == 'rchase')
check('VJ dial: right = next mode', ts.vj_dial(120).startswith('VJ -> Rainbow breath') and ts.STATE['vj'])
check('VJ dial: left = previous', ts.vj_dial(-150).startswith('VJ -> Rainbow chase'))
check('VJ dial: a big flick skips several', ts.vj_dial(450).startswith('VJ -> ' + ts.SCENE_NAMES[ts.RAINBOWS[(ts.RAINBOWS.index('rchase') + 3) % len(ts.RAINBOWS)]]))
check('VJ tap 1: colour hit for 1 s', ts._vj_or(1, 'single', 0).startswith('VJ colour hit') and ts.STATE['hit']['rgb'] == ts.HUE_COLOURS[0][1])
hf = ts.frame(NODE, {'heads': 'zonewave', 'spots': 'zonewave', 'hit_rgb': (255, 0, 0)}, 1.0, 1.0, TG)
check('colour hit frame: every head red, spots on the red slot', all(tuple(hf[b + 6:b + 9]) == (255, 0, 0) for b in HEADS_B) and hf[104] == 22)
check('VJ tap 2: heads snap to saved targets', ts._vj_or(2, 'single', 0) == 'VJ heads hit' and ts.STATE['hit']['pose'])
check('VJ tap 3: next gobo', ts._vj_or(3, 'single', 0) == 'VJ gobo 16' and ts._vj_or(3, 'single', 0) == 'VJ gobo 32')
check('VJ tap 4: freeze, then unfreeze', ts._vj_or(4, 'single', 0) == 'VJ FREEZE' and ts.STATE['frozen'] and
      ts._vj_or(4, 'single', 0) == 'VJ unfreeze' and ts.STATE['frozen'] is None)
check('VJ hold 2: still switches the heads (power stays on holds)', ts._vj_or(2, 'hold', 0).startswith('heads'))
check('VJ hold 4: leaves VJ for All-out rainbow', ts._vj_or(4, 'hold', 0).startswith('left VJ -> All-out rainbow') and not ts.STATE['vj'])
# freeze holds the lamps too
ts.STATE['wave'], ts.STATE['frozen'] = 'rloop', (5.0, 1000.0)
ts._hs = lambda: HSZ()
b1 = ts.lamp_wave_tick(1000.0, push=False)
b2 = ts.lamp_wave_tick(1012.0, push=False)
check('freeze: the lamps hold still too', b1 == b2)
ts.STATE['frozen'] = None
ts._hs = lambda: HSFake()
# command file (reviews)
ts.CMD_FILE = os.path.join(TMP, 'tap_cmd.json')
json.dump({'mode': 'rkaleido'}, open(ts.CMD_FILE, 'w'))
while not ts.JOBS.empty():
    ts.JOBS.get_nowait()
check('command file: plays the mode Claude names (for reviews)', ts.read_cmd() == 'rkaleido' and ts.JOBS.get_nowait() == ('cmd', 'rkaleido')
      and not os.path.exists(ts.CMD_FILE))
json.dump({'mode': 'rm -rf'}, open(ts.CMD_FILE, 'w'))
check('command file: only known mode names', ts.read_cmd() is None)

rc = scene_case(True, True, True)
ts.hold(3)                                             # spots switched off by hand...
rc.spot_power.STATE['on'] = {'1': True}                # ...but the plug is still powering down
ts.STATE['spots_off_at'] = ts._now()
ts.hold(4)
check('a scene right after spots-off leaves the spots out (no light sent to them)', ts.STATE['layers']['spots'] is None)

# gestures v7: no doubles, a tap acts when its release arrives, a hold fires once
G = ts.Gestures(0.45, 0.2, doubles=False)
G.event(2, 'initial_press', 100.0, 10.0)
G.event(2, 'short_release', 100.1, 10.1)
check('tap acts as soon as its release arrives', G.due(10.1) == [('single', 2)])
G.event(2, 'initial_press', 100.3, 10.3)
G.event(2, 'short_release', 100.4, 10.3)
check('two quick taps = two taps (never a double)', G.due(10.3) == [('single', 2)])
G.event(4, 'initial_press', 100.0, 10.0)
out = G.event(4, 'long_press', 100.8, 10.8) + G.event(4, 'repeat', 101.6, 11.6) + G.event(4, 'long_release', 102.0, 12.0)
check('a hold fires once, no tap after', out == [('hold', 4)] and G.due(20) == [])
check('coalesce: a hold drops that button\'s earlier taps', ts.coalesce([('single', 4), ('single', 2), ('hold', 4)]) == [('single', 2, 0), ('hold', 4, 0)])
LAMPS_ON[0] = True

# ---------------------------------------------------------------- dial = brightness (always the same job)
rc = fresh(hub=True)
check('dial (show running): show master', ts.turn(-200) == 'hub' and ('api', 'live', 'master', 0.8) in rc.calls)
rc = fresh(ambient=True)
check('dial (rainbow fade): dial.json', ts.turn(-400) == 'ambient' and abs(json.load(open(ts.DIAL_FILE))['intensity'] - 0.6) < 1e-9)
rc = fresh()
ts.STATE['lamp_base'] = 100.0
check('dial (plain colour): lamp brightness', ts.turn(-500) == 'lamps' and rc.calls[-1] == ('lamps', {'dimming': {'brightness': 50.0}, 'dynamics': {'duration': 300}}))
fd = ts.frame(NODE, {'heads': 'glow'}, 10.0, 0.5, TG)
check('dial reaches the heads + spots too (half brightness)', fd[84 + 5] == int(round(8 + 0.35 * 0.5 * 126)))
check('dial: floor', ts.turn(-5000) == 'lamps' and abs(ts.STATE['intensity'] - 0.05) < 1e-9)
check('dial: back to full removes dial.json', ts.turn(9999) == 'lamps' and not os.path.exists(ts.DIAL_FILE))
rc = fresh()
ts.STATE['lamp_base'] = None
check('dial never wakes the night light', ts.turn(-200) == 'layers' and not any(c[0] == 'lamps' for c in rc.calls))
rc = fresh()
ts.STATE['layers'].update(heads='glow', spots='uv')
ts.turn(-400)
rc.STATE['look'] = 'moviechill'
check('a look from elsewhere: layers off, dial full', ts.look_watch() is True and ts.STATE['intensity'] == 1.0 and ts.STATE['layers'] == {'heads': None, 'spots': None})

# ---------------------------------------------------------------- who owns the DMX
rc = fresh(hub=True)
check('layers stand aside for the hub', ts._someone_else_drives_dmx() == 'hub')
rc = fresh()
rc.sh = lambda cmd, timeout=15: '123 python3 ambient_fade.py 50 240 0 0 0 302 325 heads'
check('layers stand aside for the ambient heads glow / calibration', ts._someone_else_drives_dmx() == 'other')
rc.sh = lambda cmd, timeout=15: ''
check('layers send when nobody else does', ts._someone_else_drives_dmx() is None)

# ---------------------------------------------------------------- worker
rc = fresh()
ts.JOBS.put(('single', 1))
ts.JOBS.put(('single', 1))
import threading
threading.Thread(target=ts.worker, daemon=True).start()
time.sleep(0.4)
lamps = [c for c in rc.calls if c[0] == 'lamps']
check('worker: two piled-up taps = one colour change (skipped ahead to orange)', len(lamps) == 1 and
      ts.STATE['idx'][1] == 1)
rc.apply = lambda look: rc.STATE.update(last_error='%s: hub did not answer' % look)
real_scene = ts.scene
ts.scene = lambda name: (_ for _ in ()).throw(RuntimeError('hub did not answer'))
ts.JOBS.put(('single', 4))
time.sleep(0.4)
check('worker: a failed look is logged, worker carries on', 'failed' in open(ts.LOG).read())
ts.scene = real_scene

# ---------------------------------------------------------------- aim mode (calibration with the Tap Dial)
ts.AIM_FLAG = os.path.join(TMP, 'tap_aim.json')
ts.AIM_FILE = os.path.join(TMP, 'calib_aim.json')
ts.AIM_SAVES = os.path.join(TMP, 'aim_saves.txt')
check('aim mode off without the flag file', ts.aim_mode() is None)
json.dump({'fixture': 5}, open(ts.AIM_FLAG, 'w'))
json.dump({'pan': 20000, 'tilt': 40000}, open(ts.AIM_FILE, 'w'))
am = ts.aim_mode()
check('aim mode on with the flag file', am == {'fixture': 5})
ts.aim_turn(40)
check('aim: dial turns the pan (40 steps = 10 deg)', ts._aim_get()['pan'] == 20000 + int(10 / 540 * 65535) or
      abs(ts._aim_get()['pan'] - (20000 + 10 / 540 * 65535)) <= 1)
ts.aim_turn(-40)
check('aim: and back', abs(ts._aim_get()['pan'] - 20000) <= 1)
ts.aim_button(1, 'single', am)
check('aim: button 1 tilts +2 deg (spot: 240 deg range)', abs(ts._aim_get()['tilt'] - (40000 + 2 / 240 * 65535)) <= 1)
ts.aim_button(2, 'double', am)
check('aim: button 2 double tilts -6 deg', abs(ts._aim_get()['tilt'] - (40000 - 4 / 240 * 65535)) <= 2)
r = ts.aim_button(3, 'single', am)
check('aim: button 3 saves the spot', 'SAVED' in r and 'fixture 5' in open(ts.AIM_SAVES).read())
check('aim: button 4 hold does nothing', 'nothing' in ts.aim_button(4, 'hold', am) and ts.aim_mode() is not None)
ts.aim_button(4, 'single', am)
check('aim: a tap on 4 leaves aim mode (doubles are off)', ts.aim_mode() is None)
rc = fresh()
calls_before = len(rc.calls)
json.dump({'fixture': 5}, open(ts.AIM_FLAG, 'w'))
ts.JOBS.put(('single', 1))
time.sleep(0.4)
check('aim: in aim mode button 1 never changes the lamps', not any(c[0] == 'lamps' for c in rc.calls[calls_before:]))
os.replace(ts.AIM_FLAG, ts.AIM_FLAG + '.off')

# ---------------------------------------------------------------- start() + settings
rc = FakeRC()
keep = rc.LOOKS['purple']
ts.watch_orig = ts.watch
ts.watch = lambda: None
ts.start(None, rc)
rc.head_power.KEEP_LIT = []
ts.start(None, rc)
ts.STATE['layers']['heads'], ts.STATE['sending'] = 'sweep', True
check('start: heads glow keeps head_power from calling it a quiet room', rc.head_power.KEEP_LIT[-1]() is True)
ts.STATE['layers']['heads'] = None
check('  (only while the glow is on)', rc.head_power.KEEP_LIT[-1]() is False)
ts.STATE['layers']['heads'], ts.STATE['sending'] = 'zonewave', True
check('rainbow modes keep the heads on too (no quiet-room switch-off mid-show)', rc.head_power.KEEP_LIT[-1]() is True)
check('start: tap looks registered, existing looks untouched', all(k in rc.LOOKS for k in ts.TAP_LOOKS) and
      rc.LOOKS['purple'] is keep)
ts.watch = ts.watch_orig
json.dump({'enabled': False, 'settle': 0.9, 'username': 'x'}, open(ts.SETTINGS, 'w'))
s = ts.settings()
check('dial: right = up by default', ts.DEFAULTS['dial_reverse'] is False)
check('settings: known keys only', s['enabled'] is False and s['settle'] == 0.9 and 'username' not in s)
open(ts.SETTINGS, 'w').write('{broken')
check('settings: broken file -> defaults', ts.settings()['enabled'] is True)
check('status shape', set(ts.status()) >= {'device', 'last', 'source', 'fill', 'layers', 'next'})

# ---------------------------------------------------------------- ambient_fade dial()
src = open(os.path.join(HERE, 'ambient_fade.py')).read()
i = src.index('def dial():')
j = src.index('return 1.0', src.index('except Exception:', i)) + len('return 1.0')
env = {'os': os, 'time': time, 'DIAL': os.path.join(TMP, 'amb_dial.json'), '_BORN': time.time()}
exec(src[i:j], env)
check('ambient: no dial file -> full', env['dial']() == 1.0)
json.dump({'intensity': 0.4}, open(env['DIAL'], 'w'))
check('ambient: fresh dial file -> 0.4', abs(env['dial']() - 0.4) < 1e-9)
os.utime(env['DIAL'], (time.time() - 60, time.time() - 60))
check('ambient: dial file older than the look -> full', env['dial']() == 1.0)
check('ambient: brightness + heads scaled', 'bri = max(1.0, bri * dial())' in src and 'HEAD_LVL * dial()' in src)
compile(src, 'ambient_fade.py', 'exec')
check('ambient: compiles', True)

# ---------------------------------------------------------------- head_power patch
hsrc = open(os.path.join(HERE, 'head_power.py')).read()
compile(hsrc, 'head_power.py', 'exec')
check('head_power: quiet room ignores a kept glow', '(hub_quiet() and not _kept_lit())' in hsrc and 'KEEP_LIT = []' in hsrc)
hp_spec = importlib.util.spec_from_file_location('hp_copy', os.path.join(HERE, 'head_power.py'))
hp = importlib.util.module_from_spec(hp_spec)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
hp_spec.loader.exec_module(hp)
hp.KEEP_LIT[:] = [lambda: (_ for _ in ()).throw(ValueError()), lambda: True]
check('head_power: _kept_lit survives a broken callable', hp._kept_lit() is True)
hp.KEEP_LIT[:] = []
check('head_power: nothing kept -> as before', hp._kept_lit() is False)

# ---------------------------------------------------------------- Nov 18 improvements
import time as _t
def fills(rc_):
    _t.sleep(0.15)
    return [c for c in rc_.calls if c[0] in ('fill_on', 'fill_boost')]
ts._hs = lambda: HSFake()
rc = scene_case(True, True, True); ts.STATE['fill_want'] = None
ts.scene('studio')
check('fill: Studio work turns the fill speaker off (producing)', fills(rc) == [('fill_boost', False), ('fill_on', False)])
rc.calls[:] = []; ts.scene('movie')
check('fill: Movie = fill on, +6 dB', fills(rc) == [('fill_on', True), ('fill_boost', True)])
rc.calls[:] = []; ts.scene('nightsky')
check('fill: Night sky = off (late night, neighbours)', fills(rc) == [('fill_boost', False), ('fill_on', False)])
rc.calls[:] = []; ts.scene('rsteps')
check('fill: a rainbow = on, 0 dB', fills(rc) == [('fill_on', True), ('fill_boost', False)])
rc.calls[:] = []; ts.scene('rchase')
check('fill: same setting again -> no MIDI sent', fills(rc) == [])
rc.calls[:] = []; ts.scene('chill')
check('fill: Chill leaves the fill alone', fills(rc) == [])
rc = scene_case(True, True, True); ts.scene('movie'); rc.calls[:] = []; ts.scene('rshow')
check('Rainbow show after a Movie scene: movie mode switched off first (never stuck following the TV)', ('set', 'movie', False) in rc.calls)
rc.calls[:] = []; ts.scene('show')
check('Show: movie mode off too', ('set', 'movie', False) in rc.calls)
# Nov 18: the show checks its music engine came up
rc = scene_case(True, True, True)
ts.SHOW_CHECK_S = 0.05
ts.STATE['_show_watch'] = False
while not ts.JOBS.empty():
    ts.JOBS.get_nowait()
ts.scene('rshow')
rc.hub = False                                          # ...but the engine never answered
n0 = len(rc.calls)
_t.sleep(0.6)
check('Rainbow show: engine not answering 20 s later -> started again + the show re-applied (the worker runs it)',
      ('start_hub', 'music') in rc.calls[n0:] and ('set', 'dmx_pattern', 'rainbow') in rc.calls[n0:])
rc = scene_case(True, True, True)
ts.STATE['_show_watch'] = False
ts.scene('rshow')
n1 = len(rc.calls)
_t.sleep(0.4)
check('Rainbow show: engine up -> nothing more', ('start_hub', 'music') not in rc.calls[n1:])
ts.SHOW_CHECK_S = 20.0
rc = scene_case(True, True, False)
rc.hub = True
ts.scene('rshow'); rc.calls[:] = []
rc.spot_power.STATE['on'] = {'1': False}
ts.spots_toggle()
check('hold 3 during the music show: spots power on, the show keeps driving them (no UV look pushed)',
      not [c for c in rc.calls if c[:2] == ('set', 'spot_fx')] and any(c[0] == 'spots_on' for c in rc.calls))
# Nov 22: a music engine that won't answer never blocks the buttons
rc = scene_case(True, True, True)
rc.hub = False
rc.start_hub = lambda p: rc.calls.append(('start_hub', p))          # ...and it stays down
ts.STATE['_show_watch'] = True                                    # (no background check in this test)
t0 = _t.time()
r_ = ts.scene('rshow')
check('engine not answering: the show returns at once (no minutes of retries), the check takes over',
      r_.endswith('the music engine is still starting') and _t.time() - t0 < 1.0 and not [c for c in rc.calls if c[0] == 'set'])
ts.STATE['_show_watch'] = False
# VJ entry blink + breathing lamp (timed VJ: lamps off)
rc = scene_case(False, True, True)
ts.scene('rchase'); ts.scene('vj')
h = ts.STATE['hit']
check('VJ entry: a double blink on heads + spots', h.get('blink') and ts.blink_dark(0.05) and not ts.blink_dark(0.25)
      and ts.blink_dark(0.4) and not ts.blink_dark(0.7))
ts._hs = lambda: HSZ()
ts.STATE['wave'] = 'rchase'
b = ts.lamp_wave_tick(_t.time(), push=False)
wx = HSZ().rgb_to_xyb(1.0, 1.0, 1.0)[:2]
check('VJ: Behind Desk is white (the VJ sign), the others play the mode', b['Behind Desk']['color']['xy'] == {'x': wx[0], 'y': wx[1]}
      and b['Top Lamp']['color']['xy'] != b['Behind Desk']['color']['xy'])
ts.STATE['vj'] = False
b = ts.lamp_wave_tick(_t.time(), push=False)
check('out of VJ: Behind Desk back in the mode', b['Behind Desk']['color']['xy'] != {'x': wx[0], 'y': wx[1]})
# blip
PUTS[:] = []
rc = scene_case(True, False, True)
ts.heads_toggle()
_t.sleep(0.6)
dips = [b_ for pth, b_ in PUTS if pth == 'light/b' and 'dimming' in b_ and b_.get('dynamics', {}).get('duration') == 0]
check('hold 2 (heads ON): Behind Desk blips (got it)', len(dips) == 2 and dips[0]['dimming']['brightness'] < dips[1]['dimming']['brightness'])
PUTS[:] = []
rc.head_power.STATE['on'] = {'1': True}
ts.heads_toggle()
_t.sleep(0.5)
check('hold 2 (heads OFF): no blip (the heads going dark is the sign)', not [p_ for p_, _ in PUTS if p_ == 'light/b'])
# brightness while frozen in VJ
rc = scene_case(False, True, True)
ts._hs = lambda: HSFake()
ts.scene('rchase'); ts.scene('vj')
ts.STATE['frozen'] = (1.0, 1000.0)
ts.DIALQ['acc'] = -200; ts.DIALQ['ev'].set()
th = threading.Thread(target=ts.dial_worker, daemon=True); th.start(); _t.sleep(0.4)
check('VJ frozen: the dial is brightness (mode stays)', abs(ts.STATE['intensity'] - 0.8) < 1e-6 and ts.STATE['mode'] == 'rchase')

# MAX SHOW (Nov 25): its own start command, his saved show + max_show.json on top, hold 4 still turns it off
json.dump({'rb_favourite': 'chase', 'dmx_level': 0.42, 'dmx_pattern': 'rainbow'}, open(os.path.join(ts.HERE, 'show_default.json'), 'w'))
json.dump({'_note': 'x', 'dmx_pattern': 'max', 'dmx_level': 0.75, 'max_palettes': ['fire', 'ice'], 'movie': True},
          open(os.path.join(ts.HERE, 'max_show.json'), 'w'))
pr = dict(ts.max_preset())
check('max preset: the max pattern, its own brightness, his saved settings underneath, notes + movie never sent',
      pr['dmx_pattern'] == 'max' and pr['dmx_level'] == 0.75 and pr['rb_favourite'] == 'chase' and pr['max_palettes'] == ['fire', 'ice']
      and pr['movie'] is False and '_note' not in pr)
rc = scene_case(True, False, False, hub=True)
rm = ts.max_show()
check('max show: lamps on, heads + spots power on, the max settings go to the hub',
      rm.startswith('max show ON -- Max show') and ('heads_on',) in rc.calls and any(c[0] == 'spots_on' for c in rc.calls)
      and ('set', 'dmx_pattern', 'max') in rc.calls and rc.STATE['look'] == 'tap_scene_maxshow')
check('max show: the rainbow pattern is never sent after it', [c for c in rc.calls if c[:2] == ('set', 'dmx_pattern')][-1][2] == 'max')
rc.calls[:] = []
rc.head_power.STATE['on'] = {'1': True}; rc.spot_power.STATE['on'] = {'1': True}
r6 = ts.hold(4)
check('hold 4 during the max show: SHOW OFF (heads + spots off, lamps purple)',
      r6.startswith('show OFF') and ('stop_hub',) in rc.calls and any(c[0] == 'heads_off' for c in rc.calls))
rc = scene_case(True, True, True, hub=True)
r7 = ts.hold(4)
check('hold 4 after it: Michael\'s saved RAINBOW show, unchanged', r7.startswith('show ON -- Rainbow show') and
      ('set', 'dmx_pattern', 'rainbow') in rc.calls and ('set', 'dmx_pattern', 'max') not in rc.calls)
check('the max show is not on the dial (tap 4 = the same 4 scenes)', ts.SCENES == ['purple', 'rshow', 'movie', 'nightsky'])
check('the bridge can ask for it by name', 'maxshow' in ts.SCENE_NAMES)
os.remove(os.path.join(ts.HERE, 'max_show.json'))

print('%d/%d passed' % (ok, ok + bad))
sys.exit(1 if bad else 0)
