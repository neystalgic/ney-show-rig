#!/usr/bin/env python3
"""Offline tests for the glitch detector + the lights' response + the Unreal feed. No audio device, no network."""
import math, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(os.path.dirname(HERE)))
import hub_glitch as hg

PASS, FAIL = [0], []
def check(name, cond, extra=''):
    if cond:
        PASS[0] += 1
    else:
        FAIL.append(name)
        print('FAIL', name, extra)

DT = 512 / 48000.0
rnd = random.Random(4)

def music(g, t0, secs, kick_every=0.484, base=-22.0, bands=None, flat=0.15):
    """A steady groove: a kick every beat (lows jump), a little wobble everywhere."""
    t = t0
    ev = []
    while t < t0 + secs:
        age = (t - t0) % kick_every
        k = 10.0 * math.exp(-age / 0.08)
        b = dict(bands or dict(sub=-28.0, low=-26.0, mid=-27.0, high=-33.0))
        b['sub'] += k; b['low'] += k * 0.8
        g.frame(t, base + 0.6 * k + rnd.uniform(-0.5, 0.5), b, flat + rnd.uniform(-0.03, 0.03))
        ev += g.take()
        t += DT
    return t, ev

g = hg.Glitch()
t, ev = music(g, 0.01, 12.0)
check('a steady groove with kicks: no glitch at all', ev == [], ev)
# GAP
gap_seen = False
for i in range(int(0.25 / DT)):
    g.frame(t, -95.0, dict(sub=-110.0, low=-110.0, mid=-110.0, high=-110.0), 0.9)
    gap_seen = gap_seen or g.gap
    ev += g.take(); t += DT
check('gap: live while the music has dropped out', gap_seen)
t, ev2 = music(g, t, 2.0)
ev += ev2
gaps = [e for e in ev if e[1] == 'gap']
check('gap: one event when the sound comes back, with its length', len(gaps) == 1 and 0.2 < gaps[0][3] < 0.3, gaps)
check('gap: over once the music is back', not g.gap)
check('gap: the music coming back is not also a "jump"', not [e for e in ev if e[1] == 'jump'], ev)
g6 = hg.Glitch(); e8 = []
for i in range(200):
    g6.frame(0.01 + i * DT, -95.0, dict(sub=-110.0, low=-110.0, mid=-110.0, high=-110.0), 0.9); e8 += g6.take()
_, e9 = music(g6, 0.01 + 200 * DT, 3.0)
check('a song starting from silence: no glitch', not (e8 + e9), e8 + e9)
# a real pause (song end) is not a glitch
g2 = hg.Glitch()
t2, _ = music(g2, 0.01, 5.0)
e2 = []
for i in range(int(5.0 / DT)):
    g2.frame(t2, -95.0, dict(sub=-110.0, low=-110.0, mid=-110.0, high=-110.0), 0.9); e2 += g2.take(); t2 += DT
check('a long silence (song over): the gap state lets go after 3 s, no gap event', not g2.gap and not [e for e in e2 if e[1] == 'gap'])
# STUTTER: a beat-repeat at 1/32 (0.06 s)
g3 = hg.Glitch()
t3, _ = music(g3, 0.01, 6.0)
st_live, e3 = False, []
for n in range(10):
    for i in range(int(0.06 / DT)):
        age = i * DT
        lv = -16.0 if age < 0.012 else -40.0
        g3.frame(t3, lv, dict(sub=lv - 6, low=lv - 4, mid=lv - 5, high=lv - 10), 0.2)
        st_live = st_live or g3.stutter; e3 += g3.take(); t3 += DT
t3, e4 = music(g3, t3, 2.0)
e3 += e4
check('stutter: a fast even retrigger = stutter (live while it lasts)', st_live and any(e[1] == 'stutter' for e in e3), e3)
check('stutter: ends after the repeats stop', not g3.stutter and any(e[1] == 'stutter_end' for e in e3))
# CRUSH
g4 = hg.Glitch()
t4, _ = music(g4, 0.01, 6.0)
e5 = []
for i in range(8):
    g4.frame(t4, -18.0, dict(sub=-28.0, low=-26.0, mid=-24.0, high=-14.0), 0.75); e5 += g4.take(); t4 += DT
t4, e6 = music(g4, t4, 1.0)
check('crush: a noise burst (flat spectrum, highs up 15 dB+) = one crush', [e[1] for e in e5 + e6] == ['crush'], e5 + e6)
# JUMP: every band up 15 dB at once
g5 = hg.Glitch()
t5, _ = music(g5, 0.01, 6.0)
e7 = []
for i in range(30):
    g5.frame(t5, -8.0, dict(sub=-12.0, low=-11.0, mid=-12.0, high=-18.0), 0.15); e7 += g5.take(); t5 += DT
check('jump: every band leaps together = one jump event (not a kick)', [e[1] for e in e7] == ['jump'], e7)
# rate limit
for i in range(30):
    g5.frame(t5, -30.0, dict(sub=-40.0, low=-40.0, mid=-40.0, high=-45.0), 0.15); e7 += g5.take(); t5 += DT
for i in range(30):
    g5.frame(t5, -8.0, dict(sub=-12.0, low=-11.0, mid=-12.0, high=-18.0), 0.15); e7 += g5.take(); t5 += DT
check('single events stay special: at most one every 1.5 s', len([e for e in e7 if e[1] in ('jump', 'crush')]) == 1, e7)

# ---------------------------------------------------------------- through the real analyser (FFT), synthetic audio
import numpy as np
import hub_audio as ha
sr = 48000
def tone_mix(secs, seed=1):
    r = np.random.default_rng(seed)
    t = np.arange(int(secs * sr)) / sr
    x = 0.25 * np.sin(2 * np.pi * 110 * t) + 0.15 * np.sin(2 * np.pi * 440 * t) + 0.08 * np.sin(2 * np.pi * 1760 * t)
    x += 0.02 * r.standard_normal(len(t))
    env = np.exp(-((t % 0.484) / 0.09))                     # a kick-ish pump every beat
    x += 0.5 * env * np.sin(2 * np.pi * 55 * t)
    return x.astype(np.float32)
def feed(an, x):
    out = []
    for i in range(0, len(x), 512):
        an.feed(x[i:i + 512]); out += an.glitch.take()
    return out
an = ha.Analyzer(sr=sr)
ev = feed(an, tone_mix(6.0))
check('analyser: a plain groove -> no glitches', ev == [], ev)
ev = feed(an, np.zeros(int(0.2 * sr), dtype=np.float32)) + feed(an, tone_mix(2.0, 2))
check('analyser: a 0.2 s digital dropout -> one gap event', [e[1] for e in ev] == ['gap'] and 0.12 < ev[0][3] < 0.3, ev)
noise = (0.6 * np.random.default_rng(3).standard_normal(int(0.15 * sr))).astype(np.float32)
ev = feed(an, tone_mix(3.0, 4)) + feed(an, noise) + feed(an, tone_mix(2.0, 5))
check('analyser: a white-noise burst -> a crush', 'crush' in [e[1] for e in ev], ev)
blip = np.concatenate([np.concatenate([tone_mix(0.012, 6) * 4.0, np.zeros(int(0.048 * sr), dtype=np.float32) + 0.0005])
                       for _ in range(10)])
ev = feed(an, tone_mix(3.0, 7)) + feed(an, blip.astype(np.float32)) + feed(an, tone_mix(2.0, 8))
check('analyser: a 1/32 beat-repeat -> a stutter', 'stutter' in [e[1] for e in ev], ev)
check('analyser: features() carry the glitch state', isinstance(an.glitch_state(), dict) and set(an.glitch_state()) == {'gap', 'stutter'})
# ---------------------------------------------------------------- the Unreal feed (beat_sender -> /ney/...)
import beat_sender as bs
fr = bs.Framer()
snap = dict(clock=dict(beats=10.2, tempo=124.0, beat=3, bar=3), level=0.5, cols={'1': '#ff0000', '2': '#00ff00'},
            audio=dict(kick=0.8, snare=0.1, hats=0.2, drop=0.0, section='groove',
                       bands=dict(sub=0.9, low=0.5, mid=0.3, high=0.1),
                       glitch=dict(gap=False, stutter=False, events=[[100.0, 'jump', 0.5, 0.0]])))
def dec(ms):
    return [bs.osc_decode(m) for m in ms]
m1 = dec(fr.messages(snap))
addrs = [a for a, _ in m1]
check('unreal feed: the four bands', all(('/ney/band/' + k) in addrs for k in ('sub', 'low', 'mid', 'high'))
      and dict(m1)['/ney/band/sub'] == [0.8999999761581421] or abs(dict(m1)['/ney/band/sub'][0] - 0.9) < 1e-6)
check('unreal feed: gap + stutter states', dict(m1)['/ney/gap'] == [0] and dict(m1)['/ney/stutter'] == [0])
check('unreal feed: an old glitch is not replayed on connect', '/ney/glitch' not in addrs)
check('unreal feed: every lamp zone colour (digital twin)', [v for a, v in m1 if a == '/ney/lamp'][0][:2] == [0, 1.0])
snap['audio']['glitch'] = dict(gap=True, stutter=False, events=[[100.0, 'jump', 0.5, 0.0], [101.0, 'gap', 0.4, 0.2]])
m2 = dec(fr.messages(snap))
gl_ = [v for a, v in m2 if a == '/ney/glitch']
check('unreal feed: a new glitch is sent once, with kind + strength + length', len(gl_) == 1 and gl_[0][0] == 'gap'
      and dict(m2)['/ney/gap'] == [1])
m3 = dec(fr.messages(snap))
check('unreal feed: ...and never twice', not [v for a, v in m3 if a == '/ney/glitch'])
check('unreal feed: the old addresses are all still there', {'/ney/beat', '/ney/kick', '/ney/drop', '/ney/colour', '/ney/section'} <= set(addrs))

print('glitch tests: %d passed, %d failed' % (PASS[0], len(FAIL)))
sys.exit(1 if FAIL else 0)
