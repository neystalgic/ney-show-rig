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
        base = dict(dmx_pattern='modes', dmx_on=True, dmx_host='192.168.1.80', beats_per_bar=4, energy=0.6)
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
check('drop -> director off', d.step(5.0, 10.0, 'music', HEADS) is None)
hub.audioshow.section = 'groove'
check('after the drop -> back on', d.step(5.1, 10.1, 'music', HEADS) is not None)

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
hub = Hub(show_lock='wave')
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
hub = Hub(show_zones=ZMAP, show_lock='wave')
d = hm.Director(hub, L2)
d.heads_i = [0, 1, 2, 3]
zl = d.zone_list()
check('map: 5 zones in front-door order', [z['id'] for z in zl] == ZMAP['order'], zl)
check('map: heads numbered like the room (Head 3 -> index 2 in 1A)', zl[0]['heads'] == [2] and zl[3]['heads'] == [0], zl)
check('map: 3A is lamps only', zl[4]['heads'] == [] and sorted(zl[4]['channels']) == [0, 4], zl[4])
check('map: 2B is a head only', zl[3]['channels'] == [] and zl[3]['heads'] == [0], zl[3])
seq = []
for k in range(10):
    z = d.step(50.0 + k, float(k) + 0.01, 'music', HEADS)
    seq.append(max(z['zones'], key=lambda zo: zo['level'])['id'])
check('map: the wave travels 1A -> 1B -> 2A -> 2B -> 3A', seq == ZMAP['order'] * 2, seq)
z = d.step(70.0, 4.01, 'music', HEADS)                       # beat 4 -> zone 3A (lamps only)
out = d.lamps([(0.5, 0, 1)] * 6, [0, 1, 2, 3, 4, 5], 70.0, 4.01, 'music')
bright = {ch for ch, c in enumerate(out) if max(c) > 0.3}
check('map: on 3A\'s beat its two lamps are the bright ones', bright == {0, 4}, out)
check('map: tandem lamps (Top Lamp + colour lamp 2) always match', all(abs(a - b) < 1e-9 for a, b in zip(out[2], out[5])))
hub.state['settings']['show_lock'] = 'relay'
d2 = hm.Director(hub, L2)
heads_lit = []
for b, z in run(hub, d2, 0, 40, 0.25):
    if z:
        lit = [i for i, cv in z['heads'].items() if cv['level'] > 0.5]
        if lit and (not heads_lit or heads_lit[-1] != lit[0]):
            heads_lit.append(lit[0])
check('map: relay hands off in zone order (Head 3, 2, 4, 1)', heads_lit[:4] == [2, 1, 3, 0], heads_lit)

print('hub_modes tests: %d passed, %d failed' % (PASSES[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
