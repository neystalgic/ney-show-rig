#!/usr/bin/env python3
"""Offline tests for the MAX show (hub_max.py through hub_modes.Director). Fake hub, fake clock, no network."""
import os, socket, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))     # the Hue Rig folder (hub_chase etc.)
sys.path.insert(0, HERE)
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('network blocked in tests'))
import hub_modes as hm  # noqa: E402
import hub_max as mx  # noqa: E402

FAILS, PASSES = [], [0]


def check(name, ok, detail=''):
    if ok:
        PASSES[0] += 1
    else:
        FAILS.append(name)
        print('FAIL', name, detail)


class Show:
    def __init__(self):
        self.section = 'quiet'
        self.env = dict(kick=0.0, snare=0.0, hats=0.0)
        self.feat = {}


class Hub:
    def __init__(self, **s):
        base = dict(dmx_pattern='max', dmx_on=True, dmx_host='192.168.1.80', beats_per_bar=4, energy=0.6)
        base.update(s)
        self.state = {'settings': base}
        self.audioshow = Show()
        self.blackout = False


LAMPS = {0: (-0.7, -0.7, 'Play'), 1: (0.8, -0.7, 'Top Lamp'), 2: (1.1, 0.6, 'Hue color lamp 2'), 3: (-1.0, 1.0, 'Floor Shade')}
HEADS = [dict(type='lm70s')] * 4 + [dict(type='focus17')] * 2
BPP = 8 * 4   # beats per phrase


def run(hub, d, b0, b1, step=0.05, tempo=120.0, env_fn=None, sec_fn=None):
    out, b = [], b0
    t = 1000.0 + b0 * 60.0 / tempo
    while b < b1:
        if env_fn:
            hub.audioshow.env = env_fn(b)
        if sec_fn:
            hub.audioshow.section = sec_fn(b)
        out.append((b, t, d.step(t, b, 'music', HEADS)))
        b += step
        t += step * 60.0 / tempo
    return out


# 1. the built-in drummer's song: groove x3, breakdown -> build, drop x2 -- on a loop
hub = Hub()
d = hm.Director(hub, LAMPS)
seen = run(hub, d, 0.0, BPP * 12)
check('max frames are the max act', all(z and z['act'] == 'max' for _, _, z in seen))
parts = {}
for b, _, z in seen:
    parts.setdefault(int(b // BPP), set()).add(z['part'])
check('phrases 0-2 groove', all(parts[p] == {'groove'} for p in (0, 1, 2)), parts)
check('phrase 3 breakdown then build', parts[3] == {'breakdown', 'build'}, parts[3])
check('phrases 4-5 drop', parts[4] == {'drop'} and parts[5] == {'drop'}, (parts[4], parts[5]))
check('it loops', parts[6] == {'groove'} and parts[9] == {'breakdown', 'build'}, (parts[6], parts[9]))

# 2. groove pieces + palettes: all four pieces show up, never the same twice in a row, fight = neon
gp = []
for p in sorted(parts):
    z = next(z for b, _, z in seen if int(b // BPP) == p and b % BPP > 1)
    if z['part'] == 'groove':
        gp.append((z['rb'], z['palette']))
hub2 = Hub()
d2 = hm.Director(hub2, LAMPS)
seen2 = run(hub2, d2, 0.0, BPP * 24, step=0.25)
for p in range(24):
    z = next(z for b, _, z in seen2 if int(b // BPP) == p and b % BPP > 1)
    if z['part'] == 'groove':
        gp.append((z['rb'], z['palette']))
pieces = [x[0] for x in gp]
check('all four groove pieces play', set(pieces) == set(mx.GROOVE), pieces)
check('fight is always neon', all(pl == 'neon' for pc, pl in gp if pc == 'fight'), gp)
seq_pc = [x[0] for x in gp[:6]]
check('no groove piece twice in a row (one song)', all(a != b for a, b in zip(seq_pc, seq_pc[1:])), seq_pc)
pals = set(x[1] for x in gp)
check('palettes beyond rainbow', len(pals - {'rainbow'}) >= 3, pals)
bz = [z for b, _, z in seen if z['part'] == 'breakdown']
check('breakdown = deep UV + purple', bz and all(z['rb'] == 'deep' and z['palette'] == 'uv' for z in bz))
check('breakdown spots on the UV tapestry', all(z['spots'][4]['fx'].get('uv_only') for z in bz))

# 3. strobes ONLY on builds + drops
grv = [z for _, _, z in seen if z['part'] in ('groove', 'breakdown')]
check('no strobe in grooves / breakdowns', all(z['hit'] is None and not z['burst'] for z in grv))
check('no head asks for a flash in a groove', all('flash' not in cv for z in grv for cv in z['heads'].values()))
bl = [(b, z) for b, _, z in seen if z['part'] == 'build' and b < BPP * 4]
early = set(z['hit'] for b, z in bl if z['build'] < 0.25)
check('no strobe in the first quarter of a build', early == {None}, early)


def hits_between(lo, hi):
    return len(set(z['hit'] for b, z in bl if lo <= z['build'] < hi and z['hit'] is not None))


h_mid, h_end = hits_between(0.25, 0.4), hits_between(0.75, 0.9)
check('build strobes speed up (beats -> 16ths)', h_end >= 3 * h_mid, (h_mid, h_end))
check('build white at the end', any(z['white'] for b, z in bl if z['build'] >= 0.8 and z['hit'] is not None))
ih = [z for b, z in bl if b >= BPP * 4 - 1.0]
check('the inhale: last beat black, no strobe', ih and all(z['hit'] is None and all(zo['level'] == 0 for zo in z['zones']) for z in ih))
bh = [cv for b, z in bl for cv in z['heads'].values()]
check('build heads inside the strobe cone', all(cv['lean'] <= 0.42 + 1e-9 for cv in bh))
dz = [(b, t, z) for b, t, z in seen if z['part'] == 'drop' and BPP * 4 <= b < BPP * 6]
t_land = dz[0][1]
burst = [z for b, t, z in dz if t - t_land < 1.9]
after = [z for b, t, z in dz if t - t_land > 2.1]
check('drop lands with a 2 s burst', burst and all(z['burst'] and z['burst_rgbw'] for z in burst))
check('burst over after 2 s', all(not z['burst'] for z in after))
check('drop hits on the kicks', len(set(z['hit'] for b, t, z in dz if b < BPP * 4 + 16 and z['hit'] is not None and t - t_land > 2.1)) >= 8)
check('drop heads inside the strobe cone', all(cv['lean'] <= 0.42 + 1e-9 for _, _, z in dz for cv in z['heads'].values()))
check('drop: every fixture flashes', any(min(zo['level'] for zo in z['zones']) > 0.9 for _, _, z in dz))
check('drops: fire <-> ice or a hot palette', all(z['palette'] in mx.DROP_PALS for _, _, z in dz))
dpals = []
for c in range(4):
    z = next(z for b, _, z in seen2 if int(b // BPP) == 6 * c + 4)
    dpals.append(z['palette'])
check('consecutive drops never the same palette', all(a != b for a, b in zip(dpals, dpals[1:])), dpals)
check('fire is followed by ice', all(b == 'ice' for a, b in zip(dpals, dpals[1:]) if a == 'fire'), dpals)

# 4. cascades: a colour runs through the fixtures with a fading tail
cz = [z for b, _, z in seen2 if z['rb'] == 'cascade']
lit = [sorted((v for v in [zo['level'] for zo in z['zones']] + [cv['level'] for cv in z['heads'].values()]), reverse=True)
       for z in cz]
check('cascade: several fixtures lit at once', any(sum(1 for v in L if v > 0.05) >= 3 for L in lit))
check('cascade: a tail (levels differ)', any(len(set(round(v, 2) for v in L if v > 0.05)) >= 3 for L in lit))
check('max colour: fully saturated', all(max(zo['rgb']) >= 0.99 for _, _, z in seen for zo in z['zones']))

# 5. the visualizer / Unreal still get every fixture
fs = d.fixture_states()
check('fixture_states follows the max show', len(fs) == len(d.chase_seq()) and len(fs) >= 8, len(fs))
check('describe names the piece', 'bar' in d.describe() and ' - ' in d.describe(), d.describe())

# 6. the rainbow show is untouched
hub3 = Hub(dmx_pattern='rainbow')
d3 = hm.Director(hub3, LAMPS)
r3 = run(hub3, d3, 0.0, 8.0)
check('rainbow pattern still plays the rainbow show', all(z['act'] == 'rainbow' for _, _, z in r3))
hub4 = Hub(dmx_pattern='max', movie=True)
d4 = hm.Director(hub4, LAMPS)
check('movie: the max show steps aside', d4.step(1000.0, 1.0, 'music', HEADS) is None)

# 7. with music: a drop is held for its 8 bars, a breakdown ends it, a build is HEARD
hub5 = Hub()
d5 = hm.Director(hub5, LAMPS)


def kicks(b):
    f = b - int(b)
    return dict(kick=1.0 if f < 0.1 else 0.0, snare=1.0 if (int(b) % 2 == 1 and f < 0.1) else 0.0, hats=0.0)


sec = lambda b: 'drop' if 16.0 <= b < 18.0 else 'groove'
r5 = run(hub5, d5, 0.0, 16.0 + 8 * 4 + 8, env_fn=kicks, sec_fn=sec)
p5 = [(b, z['part']) for b, _, z in r5]
check('music: groove before the drop', all(p == 'groove' for b, p in p5 if 2 < b < 16), )
check('music: the drop held for 8 bars', all(p == 'drop' for b, p in p5 if 16.2 < b < 16 + 31.5))
check('music: back to groove after', all(p == 'groove' for b, p in p5 if b > 16 + 32.5))
check('music: it is live (his pocket)', all(z['pocket'] for b, _, z in r5 if b > 1))
hub6 = Hub()
d6 = hm.Director(hub6, LAMPS)
sec6 = lambda b: 'drop' if 16.0 <= b < 18.0 else 'breakdown' if b >= 24 else 'groove'
r6 = run(hub6, d6, 0.0, 30.0, env_fn=kicks, sec_fn=sec6)
check('music: a breakdown ends the drop early', [z['part'] for b, _, z in r6 if b > 25][-1] in ('breakdown', 'build'))
hub7 = Hub()
d7 = hm.Director(hub7, LAMPS)


def roll(b):                                        # a breakdown, then a snare roll that keeps speeding up
    if b < 16:
        return dict(kick=0.0, snare=1.0 if (b % 2 < 0.1) else 0.0, hats=0.0)
    rate = 2 if b < 20 else 4 if b < 24 else 8
    f = (b * rate) % 1.0
    return dict(kick=0.0, snare=1.0 if f < 0.3 else 0.0, hats=0.0)


r7 = run(hub7, d7, 0.0, 30.0, step=0.02, env_fn=roll, sec_fn=lambda b: 'breakdown')
p7 = [(b, z['part']) for b, _, z in r7]
check('music: a quiet breakdown stays a breakdown', all(p == 'breakdown' for b, p in p7 if 4 < b < 14), [p for b, p in p7 if 4 < b < 14][:5])
check('music: a rising snare roll is heard as a BUILD', any(p == 'build' for b, p in p7 if b > 20))

# 8. safety basics in the frame: guest / movie / strobe limits live in hub_dmx -- the frame only asks
check('flash ids only with a hit', all(('flash' in cv) == (z['hit'] is not None) for _, _, z in seen for cv in z['heads'].values() if cv['level'] > 0 or 'flash' in cv))
check('slot_for white = open wheel', mx.slot_for((1.0, 1.0, 1.0)) == 0 and mx.slot_for((1.0, 0.0, 0.0)) == 22)

print('max show tests: %d passed, %d failed' % (PASSES[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
