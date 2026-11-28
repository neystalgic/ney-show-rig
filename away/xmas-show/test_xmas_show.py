#!/usr/bin/env python3
"""The CHRISTMAS show + calm twinkle (Nov 28): the Max show engine with max_theme 'xmas'. Separate from every other
show. Fake hub, fake clock, no network."""
import os, socket, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
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
        self.section, self.env, self.feat = 'quiet', dict(kick=0.0, snare=0.0, hats=0.0), {}


class Hub:
    def __init__(self, **s):
        base = dict(dmx_pattern='max', dmx_on=True, dmx_host='192.168.1.80', beats_per_bar=4, energy=0.6)
        base.update(s)
        self.state = {'settings': base}
        self.audioshow = Show()
        self.blackout = False


LAMPS = {0: (-0.7, -0.7, 'Play'), 1: (0.8, -0.7, 'Top Lamp'), 2: (1.1, 0.6, 'Hue color lamp 2'), 3: (-1.0, 1.0, 'Floor Shade')}
HEADS = [dict(type='lm70s')] * 4 + [dict(type='focus17')] * 2
BPP = 32
CHANS = list(LAMPS)


def run(hub, d, b0, b1, step=0.1):
    out, b, t = [], b0, 1000.0 + b0 * 0.5
    while b < b1:
        z = d.step(t, b, 'music', HEADS)
        out.append((b, t, z, d.lamps([(1, 0, 0)] * 4, CHANS, t, b, 'music')))
        b += step
        t += step * 0.5
    return out


XMAS_PALS = {'xmas', 'candy', 'evergreen'}
hub = Hub(max_theme='xmas')
d = hm.Director(hub, LAMPS)
r = run(hub, d, 0.0, BPP * 24)
gro = [z for _, _, z, _ in r if z['part'] == 'groove']
check('christmas grooves use only christmas palettes', set(z['palette'] for z in gro) <= XMAS_PALS, set(z['palette'] for z in gro))
check('all three christmas palettes play', set(z['palette'] for z in gro) == XMAS_PALS, set(z['palette'] for z in gro))
check('christmas pieces: cascade, snowfall, domino, fight', set(z['rb'] for z in gro) == {'cascade', 'snowfall', 'domino', 'fight'},
      set(z['rb'] for z in gro))
check('the fight is red vs green', all(z['palette'] == 'xmas' for z in gro if z['rb'] == 'fight'))
brk = [z for _, _, z, _ in r if z['part'] == 'breakdown']
check('breakdowns twinkle in red + green', brk and all(z['rb'] == 'twinkle' and z['palette'] == 'xmas' for z in brk))
drp = [z for _, _, z, _ in r if z['part'] == 'drop']
check('drops: red + green or candy cane', drp and set(z['palette'] for z in drp) <= {'xmas', 'candy'}, set(z['palette'] for z in drp))
dp = []
for c in range(4):
    dp.append(next(z for b, _, z, _ in r if int(b // BPP) == 6 * c + 4)['palette'])
check('red + green <-> candy cane swap every drop', all(a != b for a, b in zip(dp, dp[1:])), dp)
cc = [(z, lc) for _, _, z, lc in r if z['palette'] == 'candy' and z['part'] == 'groove']
check('candy cane really goes WHITE on the lamps (not pink)', any(any(abs(c[0] - c[1]) < 1e-6 and abs(c[1] - c[2]) < 1e-6 and c[0] > 0.3
                                                                       for c in lc) for z, lc in cc))
check('... and on the heads (white LED flag)', any(cv.get('wbody') for z, _ in cc for cv in z['heads'].values()))
check('... and red too', any(any(c[0] > 0.3 and c[1] < 0.05 for c in lc) for z, lc in cc))
sn = [z for _, _, z, _ in r if z['rb'] == 'snowfall']
check('snowfall: white flakes on the fixtures', any(any(zo.get('white') for zo in z['zones']) for z in sn))
leans = [z['heads'][0]['lean'] for z in sn]
check('snowfall: the beams drift down (lean grows) and start again', max(leans) > 0.6 and min(leans) < 0.3)
check('strobes still only on builds + drops', all(z['hit'] is None for _, _, z, _ in r if z['part'] in ('groove', 'breakdown')))
yel = [c for _, _, z, _ in r for c in [zo['rgb'] for zo in z['zones']] + [cv['rgb'] for cv in z['heads'].values()]
       if c[0] > 0.5 and c[1] > 0.3 and c[2] < 0.6]
check('no yellow / gold anywhere (Nov 28: more red + green, less yellow)', not yel, yel[:3])
check('open beams: no gobos in the christmas show (Nov 28: he liked it)', all((sp.get('fx') or {}).get('gobo', 0) == 0
                                                                        for _, _, z, _ in r for sp in z['spots'].values()))
hubg = Hub(max_gobo_skip=[48])
dg = hm.Director(hubg, LAMPS)
rg = run(hubg, dg, 0.0, BPP * 6)
check('a skipped gobo never shows', all((sp.get('fx') or {}).get('gobo') != 48 for _, _, z, _ in rg for sp in z['spots'].values()))
hits_x = len(set(z['hit'] for z in drp if z['hit'] is not None))
hubm2 = Hub()
dm2 = hm.Director(hubm2, LAMPS)
rm2 = run(hubm2, dm2, 0.0, BPP * 24)
check('the Max show keeps its gobos', any((sp.get('fx') or {}).get('gobo', 0) > 0 for _, _, z, _ in rm2 for sp in z['spots'].values()))
hits_m = len(set(z['hit'] for _, _, z, _ in rm2 if z['part'] == 'drop' and z['hit'] is not None))
check('much less strobing than the Max show (Nov 28)', hits_x * 4 <= hits_m, (hits_x, hits_m))
bur_x = sum(1 for z in drp if z['burst'])
bur_m = sum(1 for _, _, z, _ in rm2 if z['part'] == 'drop' and z['burst'])
check('a shorter burst when a drop lands', bur_x < bur_m, (bur_x, bur_m))
check('drops hit white on candy cane', any(z['white'] and z['hit'] is not None for z in drp if z['palette'] == 'candy'))

# CALM: no song, no strobes, dimmer, slow twinkle, heads still
hubc = Hub(max_theme='xmas', max_calm=True)
dc = hm.Director(hubc, LAMPS)
rc = run(hubc, dc, 0.0, BPP * 8, step=0.05)
zs = [z for _, _, z, _ in rc]
check('calm: always the twinkle', all(z['rb'] == 'twinkle' and z['part'] == 'calm' for z in zs))
check('calm: never a strobe or a burst', all(z['hit'] is None and not z['burst'] for z in zs))
check('calm: no head flashes', all('flash' not in cv for z in zs for cv in z['heads'].values()))
check('calm: dimmer (an evening glow)', max(zo['level'] for z in zs for zo in z['zones']) <= 0.6 + 1e-9)
check('calm: the beams stay up and still', all(cv['lean'] <= 0.1 + 1e-9 for z in zs for cv in z['heads'].values() if cv['level'] > 0))
check('calm: the spots never scan', all(not (sp.get('fx') or {}).get('scan') for z in zs for sp in z['spots'].values()))
lv0 = [z['zones'][0]['level'] for z in zs]
check('calm: it twinkles (each lamp rises and falls)', max(lv0) > 0.3 and min(lv0) < 0.15, (min(lv0), max(lv0)))
check('calm: christmas colours, changing slowly', set(z['palette'] for z in zs) <= XMAS_PALS and len(set(z['palette'] for z in zs)) >= 2)

# SEPARATE from the other shows
hubm = Hub()
dm = hm.Director(hubm, LAMPS)
rm = run(hubm, dm, 0.0, BPP * 6)
check('the plain Max show never deals christmas palettes', not (set(z['palette'] for _, _, z, _ in rm) & XMAS_PALS))
check('the plain Max show never snows or twinkles', not ({'snowfall', 'twinkle'} & set(z['rb'] for _, _, z, _ in rm)))
hubr = Hub(dmx_pattern='rainbow', max_theme='xmas', max_calm=True)
dr = hm.Director(hubr, LAMPS)
rr = run(hubr, dr, 0.0, 8.0)
check('the rainbow show ignores the christmas settings', all(z['act'] == 'rainbow' for _, _, z, _ in rr))
check('no white on lamps outside christmas palettes', all(not zo.get('white') for _, _, z, _ in rm for zo in z['zones'])
      or all(z['palette'] in ('mono', 'frost', 'candy') for _, _, z, _ in rm if any(zo.get('white') for zo in z['zones'])))
# ON THE MUSIC (Nov 28, carols: "should be audio reactive -- right now it looks chaotic"): no kick, just bells / voices
ON = [b for b in [x * 0.75 for x in range(200)] if int(b) % 8 < 6]       # onsets, with gaps of silence-ish


def carol(b):
    hit = any(0 <= b - o < 0.08 for o in ON)
    return dict(kick=0.0, snare=0.0, hats=1.0 if hit else 0.05)


for lock in ('snowfall', 'cascade'):
    hubl = Hub(max_theme='xmas', max_lock=lock)
    dl = hm.Director(hubl, LAMPS)
    starts, b, t = set(), 0.0, 1000.0
    while b < 60.0:
        hubl.audioshow.env = carol(b)
        hubl.audioshow.section = 'groove'
        z = dl.step(t, b, 'music', HEADS)
        st = dl._mx
        if lock == 'snowfall':
            starts |= set(round(v, 2) for v in st.get('flakes', {}).values())
        else:
            starts |= set(round(L['b0'], 2) for L in st.get('casc', []))
        b += 0.02
        t += 0.01
    off = [x for x in starts if x > 2 and not any(-0.05 <= x - o < 0.2 for o in ON)]
    check('%s: every new flake / cascade lands ON a sound (none on a clock)' % lock, not off and len(starts) > 10, (len(starts), off[:5]))
    check('%s: the live pocket drives it' % lock, z['pocket'])

print('christmas show tests: %d passed, %d failed' % (PASSES[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
