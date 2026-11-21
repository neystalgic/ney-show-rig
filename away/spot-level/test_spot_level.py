#!/usr/bin/env python3
"""The spot brightness rule (Nov 19): spots use spot_level (default full), not the heads' dmx_level cap."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'hub_dmx.py')).read()
ok = []
ok.append(('spots: the heads\' cap is undone for the Focus Spots only', "if hd.get('type') == 'focus17':" in src and
           "lv = clamp(lv / dl_ * clamp(float(s.get('spot_level', 1.0))))" in src))
ok.append(('movie nights keep their gentle spots', 'if dl_ > 0.01 and not movie:' in src))
def rule(lv, dl, spot_level=1.0, movie=False):
    return min(1.0, lv / dl * spot_level) if (dl > 0.01 and not movie) else lv
ok.append(('a full hit on a spot = full beam (0.42 cap gone)', abs(rule(0.42, 0.42) - 1.0) < 1e-9))
ok.append(('half a hit = half a beam', abs(rule(0.21, 0.42) - 0.5) < 1e-9))
ok.append(('spot_level 0.7 = 70% max', abs(rule(0.42, 0.42, 0.7) - 0.7) < 1e-9))
ok.append(('movie: unchanged', rule(0.3, 0.42, movie=True) == 0.3))
# SCAN (Nov 19: "rainbow spotlights that scan the room")
sys.path.insert(0, HERE)
import hub_dmx as hd_
o = hd_.Heads.__new__(hd_.Heads)
def run_scan(i, fx, secs=24.0, movie=False):
    o.act_fx = {i: {'fx': fx}}
    o.fstate = {}
    hd = dict(addr=101, type='focus17', calibrated=True, tilt_up=32768, tilt_dir=1)
    out = []
    t = 1000.0
    while t < 1000.0 + secs:
        data = bytearray(512)
        o._spot_sync = None
        o.focus_out(data, 100, i, hd, 30000, 30.0, 0.8, 0.0, 1.0, {'spot_fx': {}}, t, 0.02, movie, False)
        pan = (data[100] << 8) | data[101]
        tilt = (data[102] << 8) | data[103]
        out.append((pan / 65535.0 * 540.0, (tilt - 32768) / 65535.0 * 240.0, data[104], data[105]))
        t += 0.02
    return out
sc4 = run_scan(4, dict(scan=True, color=22, gobo=48))
pans = [p for p, _, _, _ in sc4[200:]]
leans = [l for _, l, _, _ in sc4[200:]]
ok.append(('scan: Spot 1 sweeps the room wide (200+ degrees of pan)', max(pans) - min(pans) > 200))
ok.append(('scan: beams stay high -- 20 to 55 degrees from straight up', min(leans) > 18.0 and max(leans) < 56.0))
ok.append(('scan: smooth -- never faster than 120 deg/s', max(abs(b[0] - a[0]) for a, b in zip(sc4, sc4[1:])) <= 120 * 0.02 + 0.5))
ok.append(('scan: the show still sets the colour + gobo', sc4[-1][2] == 22 and sc4[-1][3] == 48))
sc5 = run_scan(5, dict(scan=True))
ok.append(('scan: the two spots mirror each other (opposite phase)', abs((sc4[600][0] - 197.0) + (sc5[600][0] - 191.2)) < 25))
still = run_scan(4, dict(color=22))
ps = [p for p, _, _, _ in still[200:]]
ok.append(('no scan asked: the spot keeps its old (gentle) behaviour', max(ps) - min(ps) < 5))
mv = run_scan(4, dict(scan=True), movie=True)
pm = [p for p, _, _, _ in mv[200:]]
ok.append(('movie nights: never scans', max(pm) - min(pm) < 5))
for n, v in ok:
    print(('PASS ' if v else 'FAIL ') + n)
print('spot level tests: %d passed, %d failed' % (sum(v for _, v in ok), sum(not v for _, v in ok)))
sys.exit(0 if all(v for _, v in ok) else 1)
