#!/usr/bin/env python3
"""Offline tests for hub_modes.py (the show director). Fake hub, fake clock, no network."""
import math, os, socket, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


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

print('hub_modes tests: %d passed, %d failed' % (PASSES[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
