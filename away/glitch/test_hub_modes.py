#!/usr/bin/env python3
"""Offline tests for hub_modes.py (the show director). Fake hub, fake clock, no network."""
import math, os, socket, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(os.path.dirname(HERE)))


def _no_network(*a, **k):
    raise RuntimeError('network blocked in tests')


socket.create_connection = _no_network
import hub_modes as hm  # noqa: E402

FAILS = []
PASSES = [0]


def check(name, ok, detail=''):
    if ok:
        PASSES[0] += 1
    else:
        FAILS.append(name)
        print('FAIL', name, detail)


class Show:
    def __init__(self):
        self.section = 'groove'
        self.env = dict(kick=0.0, snare=0.0, hats=0.0)


class Hub:
    def __init__(self, **s):
        base = dict(dmx_pattern='modes', dmx_on=True, dmx_host='192.168.1.80', beats_per_bar=4, energy=0.6,
                    show_acts=False, show_audio=1.0)   # mode tests: acts off, audio only; sections 16-18 test those
        base.update(s)
        self.state = {'settings': base}
        self.audioshow = Show()
        self.blackout = False


LAMPS = {0: (-0.7, -0.7, 'Desk lamp'), 1: (0.8, -0.7, 'Play'), 2: (1.1, 0.6, 'Couch lamp'), 3: (-1.0, 1.0, 'Corner'),
         4: (0.0, 0.0, 'Middle')}
HEADS = [dict(type='lm70s')] * 4 + [dict(type='focus17')] * 2


def run(hub, d, beats_from, beats_to, step=0.05, tempo=120.0, env_fn=None):
    seen = []
    b = beats_from
    t = 1000.0 + beats_from * 60.0 / tempo
    while b < beats_to:
        if env_fn:
            hub.audioshow.env = env_fn(b)
        z = d.step(t, b, 'music', HEADS)
        seen.append((b, z))
        b += step
        t += step * 60.0 / tempo
    return seen


# 1. zones: every lamp belongs to a head; room order left -> right
hub = Hub()
d = hm.Director(hub, LAMPS)
d.heads_i = [0, 1, 2, 3]
lz, order = d.zones()
check('every lamp has a zone', set(lz) == set(LAMPS) and all(v in (0, 1, 2, 3) for v in lz.values()), lz)
check('desk lamp -> head 1 zone', lz[0] == 0, lz)
check('room order is by x', [hm.hub_chase.DEFAULT_HEAD_XY[h][0] for h in order] ==
      sorted(hm.hub_chase.DEFAULT_HEAD_XY[h][0] for h in order), order)

# 2. the director switches EXACTLY on 8-bar lines, never repeats back to back
hub = Hub()
d = hm.Director(hub, LAMPS)
seen = run(hub, d, 0.0, 32 * 8 + 1, step=0.1)
changes = []
prev = None
for b, z in seen:
    m = z and z.get('mode')
    if m != prev and prev is not None:
        changes.append((round(b, 2), prev, m))
    prev = m
check('switches only on 8-bar lines', all(abs(b / 32.0 - round(b / 32.0)) < 0.01 for b, _, _ in changes), changes)
check('a switch every phrase', len(changes) >= 7, changes)
check('never the same mode twice in a row', all(a != c for _, a, c in changes), changes)
used = {z['mode'] for _, z in seen if z}
check('uses at least 5 different modes in a groove', len(used) >= 5, used)
mods = [m for _, _, m in changes]
check('no mode repeats within 3 phrases', all(mods[i] not in mods[max(0, i - 2):i] for i in range(len(mods))), mods)

# 3. every output in range, colours never white, only real heads (not the spots)
bad = []
for b, z in seen:
    if not z or z.get('mode') == 'relay':
        continue
    for i, cv in z['heads'].items():
        import colorsys
        s_ = colorsys.rgb_to_hsv(*cv['rgb'])[1]
        if not (0 <= cv['level'] <= 1 and 0 <= cv['lean'] <= 1 and 0 <= cv['u'] <= 1 and s_ >= 0.55 and i in (0, 1, 2, 3)):
            bad.append((b, i, cv))
check('levels / leans / pan positions in range, saturated colour', not bad, bad[:3])

# 4. drops: the director steps aside (the normal show + strobe take the drop)
hub = Hub()
d = hm.Director(hub, LAMPS)
hub.audioshow.section = 'drop'
check('drop -> still on (burst when acts are on; modes only: keeps going)', d.step(5.0, 10.0, 'music', HEADS) is not None)
hub.audioshow.section = 'groove'
check('after the drop -> on', d.step(5.1, 10.1, 'music', HEADS) is not None)

# 5. lock holds a mode; pool limits auto
hub = Hub(show_lock='wave')
d = hm.Director(hub, LAMPS)
ms = {z['mode'] for _, z in run(hub, d, 0, 32 * 4, 0.25) if z}
check('lock holds one mode', ms == {'wave'}, ms)
hub = Hub(show_pool='pulse,orbit')
d = hm.Director(hub, LAMPS)
ms = {z['mode'] for _, z in run(hub, d, 0, 32 * 6, 0.25) if z}
check('pool limits auto', ms <= {'pulse', 'orbit'} and len(ms) == 2, ms)

# 6. breakdowns only use the calm pool
hub = Hub()
hub.audioshow.section = 'breakdown'
d = hm.Director(hub, LAMPS)
ms = {z['mode'] for _, z in run(hub, d, 0, 32 * 6, 0.25) if z}
check('breakdown -> calm modes only', ms <= set(hm.POOLS['breakdown']), ms)

# 7. rhythm: pulse follows the kick; call & response splits kick / snare zones
hub = Hub(show_lock='pulse')
d = hm.Director(hub, LAMPS)
hub.audioshow.env = dict(kick=1.0, snare=0.0, hats=0.0)
z1 = d.step(1.0, 0.0, 'music', HEADS)
hub.audioshow.env = dict(kick=0.0, snare=0.0, hats=0.0)
z2 = d.step(1.01, 0.02, 'music', HEADS)
check('pulse: kick lights every zone', all(cv['level'] > 0.95 for cv in z1['heads'].values()), z1['heads'])
check('pulse: dark between kicks', all(cv['level'] < 0.25 for cv in z2['heads'].values()))
check('pulse: one colour room-wide', len({tuple(round(x, 3) for x in cv['rgb']) for cv in z1['heads'].values()}) == 1)
hub = Hub(show_lock='call')
d = hm.Director(hub, LAMPS)
hub.audioshow.env = dict(kick=1.0, snare=0.0, hats=0.0)
z = d.step(1.0, 0.0, 'music', HEADS)
lz, order = d.zones()
lit = sorted(order.index(i) % 2 for i, cv in z['heads'].items() if cv['level'] > 0.9)
check('call: kick lights zone A only', lit and all(x == 0 for x in lit), z['heads'])
hub.audioshow.env = dict(kick=0.0, snare=1.0, hats=0.0)
z = d.step(1.1, 0.1, 'music', HEADS)
lit = sorted(order.index(i) % 2 for i, cv in z['heads'].items() if cv['level'] > 0.9)
check('call: snare lights zone B only', lit and all(x == 1 for x in lit), z['heads'])

# 8. wave: one zone per beat, travelling across the room
hub = Hub(show_lock='wave', show_wave='forward')
d = hm.Director(hub, LAMPS)
peaks = []
for k in range(8):
    z = d.step(10.0 + k, float(k) + 0.01, 'music', HEADS)
    peaks.append(max(z['heads'], key=lambda i: z['heads'][i]['level']))
_, order = d.zones()
check('wave travels in room order', peaks[:4] == order and peaks[4:] == order, (peaks, order))

# 9. colour changes at most every 2 bars
hub = Hub(show_lock='pulse')
d = hm.Director(hub, LAMPS)
hues, prev, ch_bars = [], None, []
for b, z in run(hub, d, 0, 64, 0.25):
    h = round(d.hue, 4)
    if prev is not None and h != prev:
        ch_bars.append(b / 4.0)
    prev = h
gaps = [b - a for a, b in zip(ch_bars, ch_bars[1:])]
check('colour holds >= 2 bars', all(g >= 2 - 1e-6 for g in gaps), ch_bars)

# 10. aims stay inside the head's window / lean cap
cv = dict(level=1, lean=1.0, u=1.0, rgb=(1, 0, 1))
check('theta never past the lean cap', d.theta(cv, 30.0) <= 30.0)
check('pan inside the window', 1000 <= d.pan(cv, 1000, 5000) <= 5000 and 1000 <= d.pan(dict(cv, u=0.0), 1000, 5000))

# 11. relay mode delegates to the tested relay (one head lit) without touching shared settings
hub = Hub(show_lock='relay')
d = hm.Director(hub, LAMPS)
ok = True
for b, z in run(hub, d, 0, 32, 0.25):
    if z is None or z.get('mode') != 'relay':
        ok = False
        break
    lit = [i for i, cv in z['heads'].items() if cv['level'] > 0.05]
    if len(lit) > 1:
        ok = False
check('relay mode: one head at a time', ok)
check('relay mode leaves dmx_pattern alone', hub.state['settings']['dmx_pattern'] == 'modes')

# 12. off unless dmx_pattern == modes (old relay settings still work)
hub = Hub(dmx_pattern='normal')
d = hm.Director(hub, LAMPS)
check('normal -> off', d.step(1, 0, 'music', HEADS) is None)
hub = Hub(dmx_pattern='relay')
d = hm.Director(hub, LAMPS)
check('relay pattern -> the relay', d.step(1, 0.5, 'music', HEADS) is not None)
hub = Hub()
hub.state['settings']['movie'] = True
check('movie -> off', hm.Director(hub, LAMPS).step(1, 0, 'music', HEADS) is None)

# 13. lamps follow their zone, one colour per channel, same length
hub = Hub(show_lock='split')
d = hm.Director(hub, LAMPS)
cols = [(0.5, 0.0, 1.0)] * 5
out = d.lamps(cols, [0, 1, 2, 3, 4], 5.0, 1.0, 'music')
check('lamps: same count', len(out) == 5)
check('lamps: all in range', all(0 <= x <= 1 for c in out for x in c))
st = d.status()
check('status for the control page', st['on'] and st['mode'] == 'split' and st['bars'] == 8 and len(st['modes']) == len(hm.MODES), st)

# 14. Michael's calibrated map (show_zones): zones in front-door order, lamp-only + head-only zones
ZMAP = {'order': ['1A', '1B', '2A', '2B', '3A'],
        'zones': {'1A': {'heads': [3], 'lamps': ['Top Lamp', 'Hue color lamp 2']}, '1B': {'heads': [2], 'lamps': ['Play']},
                  '2A': {'heads': [4], 'lamps': ['Floor Shade']}, '2B': {'heads': [1], 'lamps': []},
                  '3A': {'heads': [], 'lamps': ['Hue color lamp 1', 'Behind Desk']}}}
L2 = {0: (0, 0, 'Behind Desk'), 1: (0, 0, 'Floor Shade'), 2: (0, 0, 'Top Lamp'), 3: (0, 0, 'Play'),
      4: (0, 0, 'Hue color lamp 1'), 5: (0, 0, 'Hue color lamp 2')}
hub = Hub(show_zones=ZMAP, show_lock='wave', show_wave='forward', show_loop_dir='ccw')
d = hm.Director(hub, L2)
d.heads_i = [0, 1, 2, 3]
zl = d.zone_list()
check('map: 5 zones in front-door order', [z['id'] for z in zl] == ZMAP['order'], zl)
check('map: heads numbered like the room (Head 3 -> index 2 in 1A)', zl[0]['heads'] == [2] and zl[3]['heads'] == [0], zl)
check('map: 3A is lamps only', zl[4]['heads'] == [] and sorted(zl[4]['channels']) == [0, 4], zl[4])
check('map: 2B is a head only', zl[3]['channels'] == [] and zl[3]['heads'] == [0], zl[3])
seq = []
for k in range(6):
    z = d.step(50.0 + k, float(k) + 0.01, 'music', HEADS)
    top = max(zo['level'] for zo in z['zones'])
    seq.append(sorted(zo['id'] for zo in z['zones'] if zo['level'] > top - 1e-6))
check('map: the wave flows down the room by column (1A+1B -> 2A+2B -> 3A)',
      seq == [['1A', '1B'], ['2A', '2B'], ['3A']] * 2, seq)
z = d.step(70.0, 2.01, 'music', HEADS)                       # beat 2 -> column 3 (3A, lamps only)
out = d.lamps([(0.5, 0, 1)] * 6, [0, 1, 2, 3, 4, 5], 70.0, 2.01, 'music')
bright = {ch for ch, c in enumerate(out) if max(c) > 0.3}
check('map: on column 3\'s beat the two studio lamps are the bright ones', bright == {0, 4}, out)
check('map: tandem lamps (Top Lamp + colour lamp 2) always match', all(abs(a - b) < 1e-9 for a, b in zip(out[2], out[5])))
# loop round the living room
hub.state['settings']['show_lock'] = 'loop'
hub.state['settings']['show_loop_dir'] = 'ccw'
d3 = hm.Director(hub, L2)
seq = []
for k in range(8):
    z = d3.step(90.0 + k, float(k) + 0.01, 'music', HEADS)
    seq.append(max(z['zones'], key=lambda zo: zo['level'])['id'])
check('map: loop circles 1A -> 2A -> 2B -> 1B', seq == ['1A', '2A', '2B', '1B'] * 2, seq)
check('map: default loop order', d3.loop_order(d3.zone_list()) == ['1A', '2A', '2B', '1B'])
# call & response across the room: south wall (A) on the kick, north wall (B) on the snare
hub.state['settings']['show_lock'] = 'call'
d4 = hm.Director(hub, L2)
hub.audioshow.env = dict(kick=1.0, snare=0.0, hats=0.0)
z = d4.step(120.0, 0.01, 'music', HEADS)
lit = sorted(zo['id'] for zo in z['zones'] if zo['level'] > 0.9)
check('map: kick lights the south wall (row A)', lit == ['1A', '2A', '3A'], lit)
hub.audioshow.env = dict(kick=0.0, snare=1.0, hats=0.0)
z = d4.step(121.0, 0.02, 'music', HEADS)
lit = sorted(zo['id'] for zo in z['zones'] if zo['level'] > 0.9)
check('map: snare lights the north wall (row B)', lit == ['1B', '2B'], lit)
hub.audioshow.env = dict(kick=0.0, snare=0.0, hats=0.0)
hub.state['settings']['show_lock'] = 'relay'
d2 = hm.Director(hub, L2)
heads_lit = []
for b, z in run(hub, d2, 0, 40, 0.25):
    if z:
        lit = [i for i, cv in z['heads'].items() if cv['level'] > 0.5]
        if lit and (not heads_lit or heads_lit[-1] != lit[0]):
            heads_lit.append(lit[0])
check('map: relay hands off round the loop (Head 3, 4, 1, 2)', heads_lit[:4] == [2, 3, 0, 1], heads_lit)

# 15. directions: wave back / bounce / alternate, loop clockwise / alternate
def wave_cols(hub_, beats_list, t0):
    d_ = hm.Director(hub_, L2)
    out_ = []
    for k, b in enumerate(beats_list):
        z = d_.step(t0 + k, b, 'music', HEADS)
        top = max(zo['level'] for zo in z['zones'])
        out_.append(sorted({zo['id'][0] for zo in z['zones'] if zo['level'] > top - 1e-6}))
    return out_
hb = Hub(show_zones=ZMAP, show_lock='wave', show_wave='back')
check('wave back: 3A -> 2A+2B -> 1A+1B', wave_cols(hb, [k + 0.01 for k in range(6)], 200) == [['3'], ['2'], ['1']] * 2)
hb = Hub(show_zones=ZMAP, show_lock='wave', show_wave='bounce')
check('wave bounce: 1-2-3-2-1-2-3-2', wave_cols(hb, [k + 0.01 for k in range(8)], 300) == [['1'], ['2'], ['3'], ['2']] * 2)
hb = Hub(show_zones=ZMAP, show_lock='wave', show_wave='alternate')
first = wave_cols(hb, [k + 0.01 for k in range(3)], 400)
hb2 = Hub(show_zones=ZMAP, show_lock='wave', show_wave='alternate')
dd = hm.Director(hb2, L2)
dd.step(500, 0.01, 'music', HEADS)
nxt = []
for k in range(3):                                   # next phrase (bar 8+)
    z = dd.step(501 + k, 32 + k + 0.01, 'music', HEADS)
    top = max(zo['level'] for zo in z['zones'])
    nxt.append(sorted({zo['id'][0] for zo in z['zones'] if zo['level'] > top - 1e-6}))
check('wave alternate: forward one phrase, back the next', first == [['1'], ['2'], ['3']] and nxt == [['3'], ['2'], ['1']], (first, nxt))
hb = Hub(show_zones=ZMAP, show_lock='loop', show_loop_dir='cw')
dl = hm.Director(hb, L2)
seq = [max(dl.step(600 + k, k + 0.01, 'music', HEADS)['zones'], key=lambda zo: zo['level'])['id'] for k in range(4)]
check('loop clockwise: 1A -> 1B -> 2B -> 2A', seq == ['1A', '1B', '2B', '2A'], seq)
hb = Hub(show_zones=ZMAP, show_lock='loop', show_loop_dir='alternate')
dl = hm.Director(hb, L2)
a = [max(dl.step(700 + k, k + 0.01, 'music', HEADS)['zones'], key=lambda zo: zo['level'])['id'] for k in range(4)]
b = [max(dl.step(800 + k, 32 + k + 0.01, 'music', HEADS)['zones'], key=lambda zo: zo['level'])['id'] for k in range(4)]
check('loop alternate: ccw one phrase, cw the next', a == ['1A', '2A', '2B', '1B'] and b == ['1A', '1B', '2B', '2A'], (a, b))

# 16. ACTS -- the firework structure: every element gets its moment
import random as _r
def acts_over(hub_, phrases, seed, section='groove'):
    d_ = hm.Director(hub_, L2)
    d_.rng = _r.Random(seed)
    hub_.audioshow.section = section
    out_ = []
    for k in range(phrases):
        z = d_.step(2000.0 + k, k * 32 + 1.01, 'music', HEADS)
        out_.append(z['act'])
    return out_, d_
ha = Hub(show_zones=ZMAP, show_acts=True)
seq1, _ = acts_over(ha, 10, 1)
seq2, _ = acts_over(Hub(show_zones=ZMAP, show_acts=True), 10, 2)
check('acts: every groove act gets a turn within 6 phrases', {'hues', 'heads', 'gobos', 'zones'} <= set(seq1[:6]), seq1)
check('acts: never the same act twice in a row', all(a != b for a, b in zip(seq1, seq1[1:])), seq1)
check('acts: not a fixed cycle (order changes between runs)', seq1 != seq2, (seq1, seq2))
check('acts: no UV reveal in a groove', 'uv' not in seq1, seq1)
seqb, _ = acts_over(Hub(show_zones=ZMAP, show_acts=True), 8, 3, 'breakdown')
check('acts: breakdowns use the dark acts only', set(seqb) <= {'uv', 'gobos', 'hues'} and 'uv' in seqb, seqb)
check('acts: no repeat in breakdowns either', all(a != b for a, b in zip(seqb, seqb[1:])), seqb)
nospots = [h for h in HEADS if h.get('type') != 'focus17']
hn = Hub(show_zones=ZMAP, show_acts=True)
dn = hm.Director(hn, L2)
dn.rng = _r.Random(4)
an = [dn.step(3000.0 + k, k * 32 + 1.01, 'music', nospots)['act'] for k in range(10)]
check('acts: no gobos / UV without spots', not ({'gobos', 'uv'} & set(an)), an)
def act_frame(name, env=None, beats=1.01, t=4000.0):
    h_ = Hub(show_zones=ZMAP, show_acts=True, show_lock=name)
    if env:
        h_.audioshow.env = env
    d_ = hm.Director(h_, L2)
    return d_, d_.step(t, beats, 'music', HEADS)
d_, z = act_frame('heads', dict(kick=1.0, snare=0, hats=0))
hv = list(z['heads'].values())
check('head moment: all four heads lit, in unison', len(hv) == 4 and all(v['level'] > 0.9 for v in hv)
      and len({(v['u'], v['lean']) for v in hv}) == 1, hv)
check('head moment: sharp (fast) moves', all(v.get('fast') for v in hv))
check('head moment: lamps down to a glow', all(zo['level'] <= 0.1 for zo in z['zones']))
check('head moment: spots out', not z['spots'])
_, z2 = act_frame('heads', beats=3.01, t=4001.0)
check('head moment: snaps to a new position every 2 beats', list(z2['heads'].values())[0]['u'] != hv[0]['u'])
d_, z = act_frame('hues')
check('hue showcase: heads dark', all(v['level'] == 0 for v in z['heads'].values()))
check('hue showcase: zones in different colours', len({tuple(round(x, 2) for x in zo['rgb']) for zo in z['zones']}) == len(z['zones']))
check('hue showcase: lamps bright', max(zo['level'] for zo in z['zones']) > 0.9)
d_, z = act_frame('gobos')
check('gobos: both spots throw a gobo', sorted(z['spots']) == [4, 5] and all(sp['fx']['gobo'] > 0 for sp in z['spots'].values()), z['spots'])
check('gobos: heads dark, lamps near dark', all(v['level'] == 0 for v in z['heads'].values()) and all(zo['level'] < 0.1 for zo in z['zones']))
d_, z = act_frame('uv')
check('UV reveal: spots on UV only, aimed at the stars', all(sp['fx']['uv_only'] and sp['fx']['hold_when'] == 'always'
      and sp['fx']['hold_head'] == i for i, sp in z['spots'].items()) and sorted(z['spots']) == [4, 5], z['spots'])
out = d_.lamps([(0.6, 0.1, 1.0)] * 6, [0, 1, 2, 3, 4, 5], 4000.0, 1.01, 'music')
check('UV reveal: total dark -- every lamp off', all(max(c) < 1e-9 for c in out), out)
check('UV reveal: heads dark', all(v['level'] == 0 for v in z['heads'].values()))
h_ = Hub(show_zones=ZMAP, show_acts=True)
h_.audioshow.section = 'drop'
zb = hm.Director(h_, L2).step(5000.0, 1.0, 'music', HEADS)
check('drop: the BURST act (not the timer strobe)', zb is not None and zb['act'] == 'burst', zb and zb['act'])
d_, z = act_frame('wave')
check('locking a mode still works with acts on', z['act'] == 'zones' and z['mode'] == 'wave')
st = d_.status()
check('status lists the acts for the control page', st['acts_on'] and len(st['acts']) == len(hm.ACTS))

# 17. QUALITY (Nov 15 v2, after Michael: "low reactivity, not full brightness, no zones, no switches, no rainbows")
#     a synthetic 124 BPM track: kick every beat, snare on 2 + 4, hats on the 8ths; measured like a viewer would
import colorsys as _cs
def shape(age, a=0.01, d=0.12):
    if age < 0: return 0.0
    return age / a if age < a else math.exp(-(age - a) / d)
def run_track(hub_, d_, bars, t0=9000.0, fps=60.0, bpm=124.0, section='groove'):
    hub_.audioshow.section = section
    spb = 60.0 / bpm
    frames = []
    t = 0.0
    while t < bars * 4 * spb:
        b = t / spb
        bi = math.floor(b)
        age = (b - bi) * spb
        kick = shape(age) * 0.7                            # a real-ish level (not 1.0): normalisation must lift it
        snare = shape(age) * 0.6 if bi % 4 in (1, 3) else 0.0
        hats = shape(((b * 2) - math.floor(b * 2)) * spb / 2) * 0.4
        hub_.audioshow.env = dict(kick=kick, snare=snare, hats=hats)
        z = d_.step(t0 + t, b + 0.001, 'music', HEADS)
        lam = d_.lamps([(0.3, 0.1, 0.5)] * 6, [0, 1, 2, 3, 4, 5], t0 + t, b + 0.001, 'music')
        frames.append((b, kick, z, lam))
        t += 1.0 / fps
    return frames
def corr(xs, ys):
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else 0.0
hq = Hub(show_zones=ZMAP, show_acts=True)
dq = hm.Director(hq, L2)
dq.rng = _r.Random(7)
fr = run_track(hq, dq, 64)
mx_l = max(max(c) for _, _, _, lam in fr for c in lam)
check('quality: lamps reach FULL brightness', mx_l >= 0.95, mx_l)
mx_h = max(cv['level'] for _, _, z, _ in fr for cv in z['heads'].values())
check('quality: heads reach full level', mx_h >= 0.95, mx_h)
lit = [(k, sum(max(c) for c in lam) / len(lam)) for b, k, z, lam in fr if z['act'] in ('zones', 'hues', 'heads', 'burst')]
cr = corr([k for k, _ in lit], [v for _, v in lit])
check('quality: the lamps follow the kick (correlation >= 0.5)', cr >= 0.5, round(cr, 2))
switches = sum(1 for a, b in zip(fr, fr[1:]) if (a[2]['act'], a[2]['mode']) != (b[2]['act'], b[2]['mode']))
check('quality: a switch every 8 bars (>= 7 in 64 bars)', switches >= 7, switches)
acts_seen = {z['act'] for _, _, z, _ in fr}
check('quality: at least 4 different acts in 64 bars', len(acts_seen) >= 4, acts_seen)
def spread(z):
    lv = [zo['level'] for zo in z['zones']]
    m = sum(lv) / len(lv)
    return math.sqrt(sum((x - m) ** 2 for x in lv) / len(lv))
zf = [z for _, _, z, _ in fr if z['act'] == 'zones' and z['mode'] in ('wave', 'loop', 'call', 'split')]
frac_zoned = sum(1 for z in zf if spread(z) > 0.2) / max(1, len(zf))
check('quality: zones visibly do different things (>= 30% of frames)', frac_zoned >= 0.3, round(frac_zoned, 2))
hues = set()
for _, _, z, lam in fr:
    for c in lam:
        h_, s_, v_ = _cs.rgb_to_hsv(*c)
        if v_ > 0.3 and s_ > 0.5:
            hues.add(int(h_ * 12) % 12)
check('quality: rainbows -- at least 9 of 12 colour families used', len(hues) >= 9, sorted(hues))
hd = Hub(show_zones=ZMAP, show_acts=True)
dd2 = hm.Director(hd, L2)
frd = run_track(hd, dd2, 4, t0=20000.0, section='drop')
check('quality: drops = burst', all(z['act'] == 'burst' for _, _, z, _ in frd))
crd = corr([k for _, k, _, _ in frd], [sum(max(c) for c in lam) / 6 for _, _, _, lam in frd])
check('quality: the burst flashes ON THE KICK (correlation >= 0.8)', crd >= 0.8, round(crd, 2))
check('quality: burst heads move fast in unison', all(all(cv.get('fast') for cv in z['heads'].values()) for _, _, z, _ in frd))

# 18. SEMI AUDIO REACTIVE: the built-in drummer
hs_ = Hub(show_zones=ZMAP, show_acts=False, show_lock='pulse', show_audio=0.0)
ds_ = hm.Director(hs_, L2)
hs_.audioshow.env = dict(kick=0.0, snare=0.0, hats=0.0)        # silence
on_beat = ds_.step(30000.0, 8.01, 'music', HEADS)
off_beat = ds_.step(30000.4, 8.6, 'music', HEADS)
check('drummer: with NO audio the show still hits on every beat', all(cv['level'] > 0.8 for cv in on_beat['heads'].values()), on_beat['heads'])
check('drummer: and drops between beats', all(cv['level'] < 0.4 for cv in off_beat['heads'].values()))
hm_ = Hub(show_zones=ZMAP, show_acts=False, show_lock='pulse', show_audio=0.6)
dm_ = hm.Director(hm_, L2)
hm_.audioshow.env = dict(kick=0.0, snare=0.0, hats=0.0)
dm_.step(31000.0, 0.5, 'music', HEADS)
z_ = dm_.step(31003.0, 12.01, 'music', HEADS)                    # 3 s of silence -> drummer takes over
check('drummer: 2 s of silence -> the clock carries the show', all(cv['level'] > 0.8 for cv in z_['heads'].values()))
ha_ = Hub(show_zones=ZMAP, show_acts=False, show_lock='pulse', show_audio=1.0)
da_ = hm.Director(ha_, L2)
ha_.audioshow.env = dict(kick=0.0, snare=0.0, hats=0.0)
z_ = da_.step(32003.0, 12.01, 'music', HEADS)
check('drummer: audio-only (show_audio 1) ignores the clock', all(cv['level'] < 0.2 for cv in z_['heads'].values()))
hq2 = Hub(show_zones=ZMAP, show_acts=True, show_audio=0.6)
dq2 = hm.Director(hq2, L2)
dq2.rng = _r.Random(9)
fr2 = run_track(hq2, dq2, 32, t0=40000.0)
lit2 = [(k, sum(max(c) for c in lam) / len(lam)) for b, k, z, lam in fr2 if z['act'] in ('zones', 'hues', 'heads', 'burst')]
check('drummer + audio together still follow the kick', corr([k for k, _ in lit2], [v for _, v in lit2]) >= 0.5)
check('status reports the audio mix', dq2.status()['audio_mix'] == 0.6)

# ---------------------------------------------------------------- RAINBOW MUSIC SHOW (Nov 18)
ZR = {'order': ['1A', '1B', '2A', '2B', '3A'],
      'zones': {'1A': {'heads': [3], 'lamps': ['Top Lamp', 'Hue color lamp 2'], 'spots': [2]}, '1B': {'heads': [2], 'lamps': ['Play']},
                '2A': {'heads': [4], 'lamps': ['Floor Shade'], 'spots': [1]}, '2B': {'heads': [1], 'lamps': []},
                '3A': {'heads': [], 'lamps': ['Hue color lamp 1', 'Behind Desk']}}}
def rb_hub(**kw):
    kw.setdefault('pocket_moves', 'snap')                  # the movement tests below; CALM (the default) is tested on its own
    h = Hub(show_zones=ZR, dmx_pattern='rainbow', show_audio=0.6, **kw)
    d_ = hm.Director(h, L2)
    d_.rng = _r.Random(3)
    return h, d_
hr, dr = rb_hub(rb_fav_always=False)
zl_ = (dr.step(50000.0, 0.0, 'music', HEADS), dr.zone_list())[1]
check('rainbow: zones carry their spots (Spot 2 = node 5 in 1A, Spot 1 = node 4 in 2A)', zl_[0]['spots'] == [5] and zl_[2]['spots'] == [4])
fr_ = run_track(hr, dr, 64, t0=50000.0)
check('rainbow: the director runs it (act rainbow)', all(z['act'] == 'rainbow' for _, _, z, _ in fr_))
subs = [z['rb'] for _, _, z, _ in fr_]
ch_ = [(i, subs[i - 1], subs[i]) for i in range(1, len(subs)) if subs[i] != subs[i - 1]]
check('rainbow grooves (rb_fav_always off): steps, chase and ripple all play, never the same twice in a row',
      {'steps', 'chase', 'ripple'} <= set(subs) and all(a != b for _, a, b in ch_))
import colorsys as _cs2
def pinkish(rgb):
    h_, s_, v_ = _cs2.rgb_to_hsv(*rgb); return s_ > 0.3 and v_ > 0.05 and 290 < h_ * 360 < 345
hcv, dcv = rb_hub()
frcv = run_track(hcv, dcv, 64, t0=50500.0)
gcv = [z['rb'] for _, _, z, _ in frcv]
gcv = [gcv[i] for i in range(len(gcv)) if i == 0 or gcv[i] != gcv[i - 1]]
check('rainbow grooves (default): chase every other phrase, the other pieces in between (all of them get shown)',
      gcv.count('chase') >= len(gcv) // 2 and len(set(gcv)) >= 3 and all('chase' in gcv[i:i + 2] for i in range(len(gcv) - 1)))
hca, dca = rb_hub(rb_fav_always=True)
frca = run_track(hca, dca, 32, t0=50700.0)
check('rb_fav_always = true: chase in every groove', {z['rb'] for _, _, z, _ in frca} == {'chase'})
hx2, dx2 = rb_hub(rb_fav_always=False)
fr2_ = run_track(hx2, dx2, 64, t0=51000.0)
sb2 = [z['rb'] for _, _, z, _ in fr2_]
g2 = [sb2[i] for i in range(len(sb2)) if i == 0 or sb2[i] != sb2[i - 1]]
check('rb_fav_always = false: chase every other phrase, the others in between, never the same twice in a row',
      'chase' in g2 and len(set(g2)) >= 3 and all(a != b for a, b in zip(g2, g2[1:])))
check('rainbow: no pink anywhere (lamps, heads)', not any(pinkish(zo['rgb']) for _, _, z, _ in fr_ for zo in z['zones'])
      and not any(pinkish(cv['rgb']) for _, _, z, _ in fr_ for cv in z['heads'].values()))
check('rainbow: every lamp in a zone shares one colour in steps (group in sync)', all(len({zo['rgb'] for zo in z['zones']}) == 1
      for _, _, z, _ in fr_ if z['rb'] == 'steps'))
st_ = [(b, z['zones'][0]['rgb']) for b, _, z, _ in fr_ if z['rb'] == 'steps']
chg = [st_[i][0] for i in range(1, len(st_)) if st_[i][1] != st_[i - 1][1]]
check('steps: the colour snaps ON a kick (every 2nd kick)', chg and all(b - math.floor(b) < 0.05 for b in chg))
lit_ = [(k, sum(max(c) for c in lam) / len(lam)) for b, k, z, lam in fr_ if z['rb'] in ('steps', 'ripple')]
check('rainbow: the room punches with the kick', corr([k for k, _ in lit_], [v for _, v in lit_]) >= 0.5)
cz_ = [z for _, _, z, _ in fr_ if z['rb'] == 'chase']
def lit_fixtures(z):
    out = [('l', zo['id'][2:]) for zo in z['zones'] if zo['level'] > 0.01]
    out += [('h', h) for h, cv in z['heads'].items() if cv['level'] > 0.01]
    out += [('s', i) for i, sp in z['spots'].items() if sp['level'] > 0.01]
    return out
check('chase: precisely ONE fixture lit at a time (lamps, heads, spots), the rest dark', cz_ and all(len(lit_fixtures(z)) == 1 for z in cz_))
rp_ = [z for _, _, z, _ in fr_ if z['rb'] == 'ripple']
check('ripple: the colour rolls out from the studio desk (3A leads the door side)', rp_ and any(len({zo['rgb'] for zo in z['zones']}) >= 3 for z in rp_))
# drop -> all-out, breakdown -> breath
hd_, dd_ = rb_hub()
frd = run_track(hd_, dd_, 16, t0=60000.0, section='drop')
check('drop -> All-out rainbow', all(z['rb'] == 'allout' for _, _, z, _ in frd))
cc = [(b, z['zones'][0]['rgb'], z['heads'][0]['rgb'], z['heads'][0]['u']) for b, _, z, _ in frd]
chd = [cc[i][0] for i in range(1, len(cc)) if cc[i][1] != cc[i - 1][1]]
check('all-out: colour snaps on EVERY beat', len(chd) >= 60 and all(abs(b - round(b)) < 0.05 for b in chd))
check('all-out: heads one colour step along (neighbours, never clashing)', all(hm.RB.index(h) == (hm.RB.index(l) + 1) % 7 for _, l, h, _ in cc))
check('all-out: heads jump position every beat', len({u for *_, u in cc}) == 2)
check('all-out: a new gobo every beat', len({z['spots'][4]['fx']['gobo'] for _, _, z, _ in frd}) == 6)
fl_ = [(k, sum(max(c) for c in lam) / len(lam)) for b, k, z, lam in frd]
check('all-out: flashes with the kick (real darkness between)', corr([k for k, _ in fl_], [v for _, v in fl_]) >= 0.5 and min(v for _, v in fl_) < 0.3)
hb_, db_ = rb_hub()
frb = run_track(hb_, db_, 16, t0=70000.0, section='breakdown')
check('breakdown -> Rainbow breath, spots UV on the tapestry', all(z['rb'] == 'breath' and z['spots'][4]['fx']['uv_only'] for _, _, z, _ in frb))
br_l = [z['zones'][0]['level'] for _, _, z, _ in frb]
check('breath: the room breathes (15% .. 100%)', min(br_l) < 0.2 and max(br_l) > 0.95)
check('rainbow: no strobe asked for (spot fx have no strobe/shutter keys)', not any('strobe' in k or 'shutter' in k
      for _, _, z, _ in fr_ + frd for sp in z['spots'].values() for k in sp['fx']))
check('rainbow: status names the piece', dr.status()['name'] in hm.RB_NAMES.values() and dr.describe().split(' (')[0] in hm.RB_NAMES.values())
hn_, dn_ = rb_hub(show_lock='chase')
frn = run_track(hn_, dn_, 32, t0=80000.0)
check('show_lock = chase holds the chase', all(z['rb'] == 'chase' for _, _, z, _ in frn))

# ---------------------------------------------------------------- POCKET: snaps follow HIS hits, not the grid
def run_hits(hub_, d_, secs, kicks, snares, t0, gain=lambda t: 1.0, fps=60.0, bpm=124.0, section='groove'):
    """A pattern by hit TIMES (seconds) -- off the grid on purpose."""
    hub_.audioshow.section = section
    spb = 60.0 / bpm
    frames = []
    t = 0.0
    while t < secs:
        k = max([shape(t - x) for x in kicks if x <= t + 1e-9] or [0.0]) * 0.8 * gain(t)
        sn = max([shape(t - x) for x in snares if x <= t + 1e-9] or [0.0]) * 0.7 * gain(t)
        hub_.audioshow.env = dict(kick=k, snare=sn, hats=0.0)
        z = d_.step(t0 + t, t / spb + 0.001, 'music', HEADS)
        lam = d_.lamps([(0.3, 0.1, 0.5)] * 6, [0, 1, 2, 3, 4, 5], t0 + t, t / spb + 0.001, 'music')
        frames.append((t, z, lam))
        t += 1.0 / fps
    return frames
spb_ = 60.0 / 124.0
# a syncopated pocket: kicks on 1, the "a" of 2, the "&" of 3; snares on the "e" of 2 and late on 4 -- none on the grid
pat_k = [0.0, 1.75, 2.5]; pat_s = [1.25, 3.62]
K_, S_ = [], []
for bar_ in range(16):
    K_ += [(bar_ * 4 + x) * spb_ for x in pat_k]; S_ += [(bar_ * 4 + x) * spb_ for x in pat_s]
hp_, dp_ = rb_hub(show_lock='steps')
frp = run_hits(hp_, dp_, 16 * 4 * spb_, K_, S_, t0=90000.0)
sp_ = [(t, z) for t, z, _ in frp if z['rb'] == 'steps']
check('pocket: live while the music plays', all(z.get('pocket') for t, z in sp_ if t > 0.2))
cc_ = [sp_[i][0] for i in range(1, len(sp_)) if sp_[i][1]['zones'][0]['rgb'] != sp_[i - 1][1]['zones'][0]['rgb'] and sp_[i][0] > 0.2]
check('pocket: colour snaps land on HIS kicks (within one frame), off the grid', len(cc_) >= 15
      and all(min(abs(t - x) for x in K_) < 0.035 for t in cc_))
hj_ = [sp_[i][0] for i in range(1, len(sp_)) if sp_[i][1]['heads'][0]['u'] != sp_[i - 1][1]['heads'][0]['u'] and sp_[i][0] > 0.2]
check('pocket: the heads jump on HIS snares, never on a kick-only moment', len(hj_) >= 20
      and all(min(abs(t - x) for x in S_) < 0.035 for t in hj_))
check('pocket: those snare jumps are off the beat grid (the syncopation survives)',
      any(abs((t / spb_) - round(t / spb_)) > 0.2 for t in hj_))
# dynamics: 8 loud bars, then 8 bars at 35% -- the quiet section stays quiet AND still snaps
loud = 8 * 4 * spb_
hd2, dd2 = rb_hub(show_lock='steps')
frq = run_hits(hd2, dd2, 16 * 4 * spb_, K_, S_, t0=95000.0, gain=lambda t: 1.0 if t < loud else 0.35)
def avg_peak(fs):
    return sum(max(sum(max(c) for c in lam) / len(lam), 0) for t, z, lam in fs) / max(1, len(fs))
pk_l = max(sum(max(c) for c in lam) / len(lam) for t, z, lam in frq if 2.0 < t < loud)
pk_q = max(sum(max(c) for c in lam) / len(lam) for t, z, lam in frq if t > loud + 0.5)
check('pocket: a quiet section after a loud one stays clearly dimmer (dynamics kept)', pk_q < 0.75 * pk_l)
cq_ = [frq[i][0] for i in range(1, len(frq)) if frq[i][0] > loud + 0.3 and frq[i][1]['heads'][0]['u'] != frq[i - 1][1]['heads'][0]['u']]
check('pocket: ...and the quiet hits still snap the heads', len(cq_) >= 10)
# real-world: the hit detector is scale-free (every hit looks big) -- the raw loudness (feat db) keeps the dynamics
hf_, df_ = rb_hub(show_lock='steps')
class _Feat(dict): pass
def gain_db(t): return 1.0 if t < loud else 1.0
hf_.audioshow.feat = dict(db=-12.0)
fa_ = run_hits(hf_, df_, loud, K_, S_, t0=97000.0)
hf_.audioshow.feat = dict(db=-28.0)                        # the verse: 16 dB down, but the hits look just as big
fb_ = run_hits(hf_, df_, 8.0, K_, S_, t0=97000.0 + loud)
pa_ = max(sum(max(c) for c in lam) / len(lam) for t, z, lam in fa_ if t > 2.0)
pb_ = max(sum(max(c) for c in lam) / len(lam) for t, z, lam in fb_ if t > 0.5)
check('pocket: 16 dB quieter verse -> clearly dimmer even when the hits look full size', pb_ < 0.7 * pa_)
check('pocket: ...and still snapping', len({z['zones'][0]['rgb'] for t, z, lam in fb_}) >= 3)
# PIVOTS (Michael: "up to 90 degree turns and pivots with the 808, kick and clap"): round each head's tapestry aim
TGT_ = {'UV tapestry': {str(i): {'pan': 20000 + 1000 * i, 'tilt': 15000} for i in range(4)}}
hx_, dx_ = rb_hub(show_lock='steps', head_targets=TGT_, pocket_moves='calm')
frx = run_hits(hx_, dx_, 2 * 4 * spb_, K_, S_, t0=98500.0)
check('pivots are OFF by default (Michael, live: too snappy)', not any('pan16' in z['heads'][0] for _, z, _ in frx))
hv_, dv_ = rb_hub(show_lock='steps', head_targets=TGT_, pocket_pivots=True)
frv = run_hits(hv_, dv_, 8 * 4 * spb_, K_, S_, t0=98000.0)
pv_ = [z['heads'][0] for t, z, _ in frv if z.get('pocket') and t > 0.3]
d45 = 45.0 / 540.0 * 65535.0
check('pivot: the heads turn 90 degrees (45 either side of the tapestry aim), snapping', pv_ and
      {round(h['pan16']) for h in pv_} == {round(20000 + d45), round(20000 - d45)} and all(h.get('snap') for h in pv_))
pt_ = [frv[i][0] for i in range(1, len(frv)) if frv[i][0] > 0.3 and frv[i][1].get('pocket') and frv[i][1]['heads'][0].get('pan16') != frv[i - 1][1]['heads'][0].get('pan16')]
check('pivot: each turn lands on a clap / snare', len(pt_) >= 15 and all(min(abs(t - x) for x in S_) < 0.035 for t in pt_))
lt_ = [frv[i][0] for i in range(1, len(frv)) if frv[i][0] > 0.3 and frv[i][1].get('pocket') and abs(frv[i][1]['heads'][0]['lean'] - frv[i - 1][1]['heads'][0]['lean']) > 0.2]
check('pivot: the tilt nods on the kick', len(lt_) >= 15 and all(min(abs(t - x) for x in K_) < 0.035 for t in lt_))
check('pivot: every head moves as one body (same turn, same nod)', all(len({round(z['heads'][h]['pan16'] - 1000 * h) for h in range(4)}) == 1
      and len({z['heads'][h]['lean'] for h in range(4)}) == 1 for t, z, _ in frv if z.get('pocket') and t > 0.3))
hv_.audioshow.feat = dict(level=dict(kick=1.0))
z8 = dv_.step(98000.0 + 8 * 4 * spb_ + 0.01, 32.01, 'music', HEADS)
check('pivot: the 808 ringing sinks the heads further', z8['heads'][0]['lean'] >= 0.5 - 1e-9 and z8['heads'][0]['lean'] in (0.5, 0.95))
# CALM (the default, Michael Nov 18: "avoid unnecessary movement from the heads"): hits play through colour +
# brightness; the heads hold a position per phrase and glide only when the phrase changes
hc_ = Hub(show_zones=ZR, dmx_pattern='rainbow', show_audio=0.6, show_lock='chase', head_targets=TGT_, pocket_pivots=True, pocket_moves='calm')
dc_ = hm.Director(hc_, L2); dc_.rng = _r.Random(3)
frc = run_hits(hc_, dc_, 16 * 4 * spb_, K_, S_, t0=99500.0)
mv_ = [(t, z['turn'], tuple((z['heads'][h]['u'], z['heads'][h]['lean']) for h in range(4))) for t, z, _ in frc if z.get('pocket')]
by_ph = {}
for t, ph, p_ in mv_:
    by_ph.setdefault(ph, set()).add(p_)
check('calm: the heads hold ONE position per phrase (no jumps on the hits)', by_ph and all(len(v) == 1 for v in by_ph.values()))
check('calm: they move when the phrase changes', len({next(iter(v)) for v in by_ph.values()}) >= 2 or len(by_ph) == 1)
check('calm: no fast / snap / pivot moves at all', not any(k in z['heads'][h] for t, z, _ in frc for h in range(4) for k in ('fast', 'snap', 'pan16')))
cz2 = [z for t, z, _ in frc if z.get('pocket')]
check('calm: the hits still play -- chase walks the zones on the kicks', len({next(zo['id'] for zo in z['zones'] if zo['level'] > 0.01)
      for z in cz2 if any(zo['level'] > 0.01 for zo in z['zones'])}) >= 4)
# GLITCHES: reactions deleted (Michael, Nov 19) -- a dropout / stutter / noise burst changes nothing in the lights
import collections as _co, types as _ty
class _G:
    gap = True
    stutter = True
hg_, dg_ = rb_hub(show_lock='steps')
hg_.audio = _ty.SimpleNamespace(an=_ty.SimpleNamespace(glitch=_G()), glitch_events=_co.deque([(1e12, 'crush', 1.0, 0.0)], maxlen=20))
T0 = 120000.0
frg = run_hits(hg_, dg_, 2 * 4 * spb_, K_, S_, t0=T0)
check('glitches: no reaction at all (no dark, no freeze, no white flare)', all(z.get('glitch') is None for _, z, _ in frg)
      and any(zo['level'] > 0 for _, z, _ in frg for zo in z['zones'])
      and not any(zo['rgb'] == (1.0, 1.0, 1.0) for _, z, _ in frg for zo in z['zones'])
      and len({z['zones'][0]['rgb'] for _, z, _ in frg}) >= 3)
# the loved chase, exactly: heads JUMP on the hits, punch with the lows
hl_, dl_ = Hub(show_zones=ZR, dmx_pattern='rainbow', show_audio=0.6, show_lock='chase'), None
dl_ = hm.Director(hl_, L2); dl_.rng = _r.Random(3)
frl = run_hits(hl_, dl_, 4 * 4 * spb_, K_, S_, t0=52000.0)
cl_ = [z for t, z, _ in frl if z.get('pocket') and t > 0.3]
check('the loved chase (defaults): chase, heads jump position on the hits (fast), no pivots',
      all(z['rb'] == 'chase' for z in cl_) and len({z['heads'][2]['u'] for z in cl_}) >= 3 and
      all(z['heads'][2].get('fast') and 'pan16' not in z['heads'][2] for z in cl_))
# THE REAL HUB ORDER (Nov 19 bug): lamps() calls step() first each frame without the fixtures, then the DMX
# calls step() with them at the same instant -- the spots must still get their cues
hro, dro = rb_hub(show_lock='chase')
spots_seen = []
for k in range(400):
    t = 54000.0 + k / 50.0
    b = t / spb_
    hro.audioshow.env = dict(kick=0.9 if k % 25 < 2 else 0.1, snare=0.8 if k % 25 in (12, 13) else 0.0, hats=0.0)
    dro.lamps([(0.3, 0.1, 0.5)] * 6, [0, 1, 2, 3, 4, 5], t, b, 'music')      # the lamps first (no fixture list)
    z = dro.step(t, b, 'music', HEADS)                                          # then the DMX, same instant
    spots_seen.append(z and z.get('spots') or {})
check('real hub order: the spots get cues (4 and 5), and they light', all(set(s_) == {4, 5} for s_ in spots_seen[50:])
      and any(s_[4]['level'] > 0.3 for s_ in spots_seen[50:]) and any(s_[5]['level'] > 0.3 for s_ in spots_seen[50:]))
# chase: the spots answer the snares too (Nov 19, "all the light fixtures")
hsp, dsp = rb_hub(show_lock='chase')
frsp = run_hits(hsp, dsp, 4 * 4 * spb_, K_, S_, t0=53000.0)
sp_on = [(t, i) for t, z, _ in frsp if z.get('pocket') and t > 0.3 and z['rb'] == 'chase' for i in (4, 5)
         if z['spots'][i]['level'] > 0.5 and not any(zo['level'] > 0 and i in zz.get('spots', []) for zo, zz in zip(z['zones'], dsp.zone_list()))]
seq_ = []
for t, z, _ in frsp:
    if z.get('pocket') and t > 0.3 and z['rb'] == 'chase':
        lf = lit_fixtures(z)
        if lf and (not seq_ or seq_[-1] != lf[0]):
            seq_.append(lf[0])
WANT = [('h', 0), ('h', 1), ('l', 'Play'), ('s', 5), ('h', 2), ('l', 'Top Lamp'), ('l', 'Hue color lamp 2'), ('l', 'Floor Shade'),
        ('h', 3), ('s', 4)]
bounce_ = WANT + WANT[-2:0:-1]
k0 = next((k for k in range(len(bounce_)) if [bounce_[(k + m) % len(bounce_)] for m in range(len(seq_))] == seq_), None)
check('chase: Michael\'s order, one by one, there and back: Head 1, Head 2, Play, Spot 2, Head 3, Top Lamp, the other 1A bulb, '
      'Shade, Head 4, Spot 1 (then back)', len(seq_) >= 12 and k0 is not None, seq_[:14])
check('chase: Top Lamp and the other 1A bulb are separate fixtures', ('l', 'Top Lamp') in seq_ and ('l', 'Hue color lamp 2') in seq_)
check('chase: the lamps outside the frame (Behind Desk, lamp 1) stay dark', not any(f[1] in ('Behind Desk', 'Hue color lamp 1') for f in seq_))
def step_colours(frames):
    """[(fixture, colour or None for a spot)] one entry per step of the wave"""
    out = []
    for t, z, _ in frames:
        if not (z.get('pocket') and t > 0.3 and z['rb'] == 'chase'):
            continue
        lf = lit_fixtures(z)
        if not lf:
            continue
        f = lf[0]
        c = (next(zo['rgb'] for zo in z['zones'] if zo['level'] > 0.01) if f[0] == 'l' else z['heads'][f[1]]['rgb'] if f[0] == 'h' else None)
        if not out or out[-1][0] != f:
            out.append((f, c))
    return out
def rainbow_steps_ok(sc):
    known = [(k, c) for k, (_, c) in enumerate(sc) if c is not None]
    return len(known) >= 5 and all((hm.RB.index(c2) - hm.RB.index(c1)) % 7 == (k2 - k1) % 7 for (k1, c1), (k2, c2) in zip(known, known[1:]))
check('chase: each step (whichever fixture) is the next ROY G BIV colour', rainbow_steps_ok(step_colours(frsp)))
check('spots scan the room in the rainbow pieces (not in breath: UV on the tapestry)',
      all(sp['fx'].get('scan') for t, z, _ in frsp if z['rb'] == 'chase' for sp in z['spots'].values())
      and all(not sp['fx'].get('scan') for _, _, z, _ in frb for sp in z['spots'].values()))
fs_ = dsp.fixture_states(frsp[-1][1])
check('the screen gets the room: the 10 wave fixtures in his order, one lit with its colour',
      [f['name'] for f in fs_] == ['Head 1', 'Head 2', 'Play', 'Spot 2', 'Head 3', 'Top Lamp', 'Hue color lamp 2', 'Floor Shade', 'Head 4', 'Spot 1'])
lit_counts = [sum(1 for f in dsp.fixture_states(z) if f['level'] > 0.01) for t, z, _ in frsp if z.get('pocket') and t > 0.3 and z['rb'] == 'chase']
check('the screen: exactly one fixture lit at a time in the wave', lit_counts and all(c == 1 for c in lit_counts))
# SCATTER (Nov 19, Michael: "each small transient affects a DIFFERENT light, including the heads and the spots")
hsx, dsx = rb_hub(show_lock='scatter')
frs = run_hits(hsx, dsx, 8 * 4 * spb_, K_, S_, t0=150000.0)
def fixtures(z):
    out = {('z', zo['id']): (zo['level'], zo['rgb']) for zo in z['zones']}
    out.update({('h', h): (cv['level'], cv['rgb']) for h, cv in z['heads'].items()})
    out.update({('s', i): (sp['level'], hm.RB[hm.RB_SLOT.index(sp['fx']['color'])] if sp['fx']['color'] in hm.RB_SLOT else None)
                for i, sp in z['spots'].items()})
    return out
flares = []                                                  # (time, fixture, colour) each time a fixture jumps up
prev = None
for t, z, _ in frs:
    if not z.get('pocket') or t < 0.3:
        prev = fixtures(z); continue
    cur = fixtures(z)
    for f, (lv, c) in cur.items():
        if prev and lv > prev.get(f, (0, None))[0] + 0.25:
            flares.append((t, f, c))
    prev = cur
hits_ = sorted([x for x in K_ + S_ if 0.3 < x < 8 * 4 * spb_ - 0.1])
check('scatter: one flare per transient (kicks AND snares)', abs(len(flares) - len(hits_)) <= 2, (len(flares), len(hits_)))
check('scatter: every flare lands on his hits', all(min(abs(t - x) for x in K_ + S_) < 0.035 for t, _, _ in flares))
check('scatter: the next hit is always a DIFFERENT light', all(a[1] != b[1] for a, b in zip(flares, flares[1:])))
kinds = {f[0] for _, f, _ in flares}
check('scatter: lamps, heads AND spots all take hits', kinds == {'z', 'h', 's'}, kinds)
zone_flares = [(f, c) for _, f, c in flares if f[0] in ('z', 'h')]
order_ = [(hm.RB.index(b[2]) - hm.RB.index(a[2])) % 7 for a, b in zip(flares, flares[1:]) if a[1][0] != 's' and b[1][0] != 's']
check('scatter: every hit is the NEXT colour in ROY G BIV', order_ and all(x in (1, 2) for x in order_) and order_.count(1) >= len(order_) * 0.6, order_[:12])
check('scatter: real darkness between hits (the rest stay dark)', min(sum(1 for lv, _ in fixtures(z).values() if lv > 0.3) for t, z, _ in frs
      if z.get('pocket') and t > 0.3) <= 1)
# ROY G BIV ORDER (Michael, Nov 18 eve: "regardless of what bulb is triggered, the pattern maintains ROY G BIV")
check('ROY G BIV order in chase (the wave, any fixture): every step is the NEXT colour',
      rainbow_steps_ok(step_colours(run_hits(*rb_hub(show_lock='chase', pocket_moves='calm'), 4 * 4 * spb_, K_, S_, t0=139000.0))))
for piece in ('allout', 'steps'):
    ho_, do_ = rb_hub(show_lock=piece if piece != 'allout' else '', pocket_moves='calm')
    if piece == 'allout':
        ho_.state['settings']['rb_vj'] = {'piece': 'allout'}
    fo_ = run_hits(ho_, do_, 4 * 4 * spb_, K_, S_, t0=140000.0)
    seq = []
    for t, z, _ in fo_:
        c = next((zo['rgb'] for zo in z['zones'] if zo['level'] > 0.01), None)
        if c is not None and (not seq or seq[-1] != c):
            seq.append(c)
    steps_ = [(hm.RB.index(b) - hm.RB.index(a)) % 7 for a, b in zip(seq, seq[1:])]
    check('ROY G BIV order in %s: every colour change is the NEXT colour, whichever bulb lights' % piece, len(steps_) >= 6 and all(x == 1 for x in steps_), steps_[:12])
# VJ ON THE MUSIC (Nov 18): the dial picks the piece, taps add moments, the music still drives the hits
hj_, dj_ = rb_hub(pocket_moves='calm')
SJ = hj_.state['settings']
T1 = 130000.0
SJ['rb_vj'] = {'piece': 'allout'}
frj = run_hits(hj_, dj_, 2 * 4 * spb_, K_, S_, t0=T1)
check('VJ: the dial\'s piece plays whatever the section (all-out in a groove)', all(z['rb'] == 'allout' for _, z, _ in frj))
cj_ = [frj[i][0] for i in range(1, len(frj)) if frj[i][1].get('pocket') and frj[i][1]['zones'][0]['rgb'] != frj[i - 1][1]['zones'][0]['rgb']]
check('VJ: still audio reactive (colour changes land on his kicks)', len(cj_) >= 5 and all(min(abs(t - x) for x in K_) < 0.035 for t in cj_ if t > 0.3))
tj = T1 + 2 * 4 * spb_
SJ['rb_vj'] = {'piece': 'chase'}
hj_.audioshow.env = dict(kick=0.5, snare=0.0, hats=0.0)
zj = dj_.step(tj + 0.01, (tj + 0.01) / spb_, 'music', HEADS)
check('VJ: turning the dial switches the piece right away (not at the next phrase)', zj['rb'] == 'chase')
SJ['rb_vj'] = {'piece': 'chase', 'hit': {'kind': 'colour', 't': tj + 0.02, 'n': 4}}
zh = dj_.step(tj + 0.3, (tj + 0.3) / spb_, 'music', HEADS)
cf_ = zh['zones'][0]['rgb']
check('VJ tap 1: a full flash on everything, in the colour of the moment (keeps the order)', cf_ in hm.RB and
      all(zo['rgb'] == cf_ and zo['level'] == 1.0 for zo in zh['zones']) and all(h['rgb'] == cf_ for h in zh['heads'].values()))
zh2 = dj_.step(tj + 1.3, (tj + 1.3) / spb_, 'music', HEADS)
check('VJ tap 1: over after a second', not all(zo['level'] == 1.0 for zo in zh2['zones']))
SJ['rb_vj'] = {'piece': 'chase', 'hit': {'kind': 'cut', 't': tj + 1.4}}
zc_ = dj_.step(tj + 1.5, (tj + 1.5) / spb_, 'music', HEADS)
check('VJ tap 2: a cut to black (half a second)', all(zo['level'] == 0 for zo in zc_['zones']) and all(h['level'] == 0 for h in zc_['heads'].values()))
SJ['rb_vj'] = {'piece': 'steps', 'freeze': True}
zf1 = dj_.step(tj + 2.0, (tj + 2.0) / spb_, 'music', HEADS)
hj_.audioshow.env = dict(kick=0.0, snare=0.8, hats=0.0)
zf2 = dj_.step(tj + 2.6, (tj + 2.6) / spb_, 'music', HEADS)
check('VJ tap 4: freeze holds the frame', zf1['zones'] == zf2['zones'] and zf1['heads'] == zf2['heads'])
SJ['rb_vj'] = {'piece': 'steps'}
zs0 = dj_.step(tj + 2.7, (tj + 2.7) / spb_, 'music', HEADS)
SJ['rb_vj'] = {'piece': 'steps', 'hit': {'kind': 'skip', 't': tj + 2.71}}
zs1 = dj_.step(tj + 2.72, (tj + 2.72) / spb_, 'music', HEADS)
zs2 = dj_.step(tj + 2.74, (tj + 2.74) / spb_, 'music', HEADS)
check('VJ tap 3: one step on in ROY G BIV (a manual hit), once per tap', hm.RB.index(zs1['zones'][0]['rgb']) == (hm.RB.index(zs0['zones'][0]['rgb']) + 1) % 7
      and zs2['zones'][0]['rgb'] == zs1['zones'][0]['rgb'])
SJ['rb_vj'] = None
zn = dj_.step(tj + 2.8, (tj + 2.8) / spb_, 'music', HEADS)
check('VJ off: back to the normal show', zn['rb'] in hm.RB_NAMES)
# silence -> the beat clock carries on (room never dies), pocket off
hs2, ds2 = rb_hub(show_lock='steps')
run_hits(hs2, ds2, 4 * 4 * spb_, K_, S_, t0=99000.0)
hs2.audioshow.env = dict(kick=0.0, snare=0.0, hats=0.0)
fsl = []
for i in range(300):
    t = 4 * 4 * spb_ + i / 60.0
    fsl.append(ds2.step(99000.0 + t, t / spb_ + 0.001, 'music', HEADS))
check('pocket: 2 s of silence hands over to the beat clock', not fsl[-1].get('pocket') and fsl[30].get('pocket'))
check('pocket: ...which keeps the colour stepping', len({z['zones'][0]['rgb'] for z in fsl[150:]}) >= 2)

print('hub_modes tests: %d passed, %d failed' % (PASSES[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
