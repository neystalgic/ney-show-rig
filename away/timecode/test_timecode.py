#!/usr/bin/env python3
"""Offline: Ableton's drum notes (IAC, channel 10) become exact hits; the pads ignore channel 10."""
import os, sys, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(os.path.dirname(HERE)))
import hub_audio as ha
PASS, FAIL = [0], []
def check(n, c, x=''):
    if c: PASS[0] += 1
    else: FAIL.append(n); print('FAIL', n, x)
S = {}
a = ha.AudioIn.__new__(ha.AudioIn)
a.pending = []
a.amidi_seen = 0
a.settings = lambda: S
M = lambda **k: types.SimpleNamespace(**k)
h = a.ableton_hit(M(type='note_on', channel=9, note=36, velocity=127), 100.0)
check('C1 (36) on channel 10 = a kick, full velocity', h and h[1] == 'kick' and abs(h[2] - 1.0) < 1e-6 and h[3] == 'midi')
check('D1 (38) = snare, D#1 (39) clap = snare, F#1 (42) = hats', [a.ableton_hit(M(type='note_on', channel=9, note=n, velocity=64), 100.0)[1]
      for n in (38, 39, 42)] == ['snare', 'snare', 'hats'])
check('velocity = how hard (a soft hit is a smaller hit)', a.ableton_hit(M(type='note_on', channel=9, note=36, velocity=40), 100.0)[2] < 0.5)
check('another channel: ignored', a.ableton_hit(M(type='note_on', channel=0, note=36, velocity=100), 100.0) is None)
check('note off / velocity 0: ignored', a.ableton_hit(M(type='note_on', channel=9, note=36, velocity=0), 100.0) is None
      and a.ableton_hit(M(type='note_off', channel=9, note=36, velocity=0), 100.0) is None)
check('an unmapped note: ignored', a.ableton_hit(M(type='note_on', channel=9, note=60, velocity=100), 100.0) is None)
S['trig_notes'] = {'48': 'kick'}
check('trig_notes setting: his own drum map', a.ableton_hit(M(type='note_on', channel=9, note=48, velocity=100), 100.0)[1] == 'kick')
check('hits land in the same queue as the gear MIDI (exact, ungoverned)', len(a.pending) == 6 and all(p[3] == 'midi' for p in a.pending))
src = open(os.path.join(HERE, 'hub_livemidi.py')).read()
check('the pads (colours) ignore channel 10', "trig_ableton_ch" in src and 'return                                       # Nov 18: channel 10' in src)
print('timecode tests: %d passed, %d failed' % (PASS[0], len(FAIL)))
sys.exit(1 if FAIL else 0)
