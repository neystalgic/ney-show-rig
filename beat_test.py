#!/usr/bin/env python3
"""Fake beat for testing Unreal without music: rainbow kicks at 120 BPM.
   python3 beat_test.py [seconds]   -- pause beat_sender.py while this runs."""
import colorsys, json, socket, sys, time
from beat_sender import osc, resolve, settings
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 40
targets = resolve(settings()['targets'])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
t0 = time.time()
while time.time() - t0 < secs:
    t = time.time() - t0
    beats = t * 2.0                                   # 120 BPM
    phase = beats % 1.0
    kick = max(0.0, 1.0 - phase * 3.0)                # hit on the beat, gone by 1/3 of it
    r, g, b = colorsys.hsv_to_rgb((beats / 16.0) % 1.0, 1.0, 1.0)
    for m in (osc('/ney/kick', kick), osc('/ney/beat', phase), osc('/ney/colour', r, g, b),
              osc('/ney/onbeat', int(phase < 0.03)), osc('/ney/section', 'groove')):
        for tg in targets:
            s.sendto(m, tg)
    time.sleep(1 / 60)
print('test done')
