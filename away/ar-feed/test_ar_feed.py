#!/usr/bin/env python3
"""The AR app's feed: beat_sender sends /ney/fix (index, r, g, b, level) per wave fixture. Offline."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import beat_sender as bs
ok = []
fr = bs.Framer()
snap = dict(clock=dict(beats=1.0, tempo=124.0), audio={}, cols={},
            fix=[[1.0, 0.0, 0.0, 0.9]] + [[0.0, 0.0, 0.0, 0.0]] * 9)
ms = [bs.osc_decode(m) for m in fr.messages(snap)]
fx = [v for a, v in ms if a == '/ney/fix']
ok.append(('ten /ney/fix messages, in order', [v[0] for v in fx] == list(range(10))))
ok.append(('the lit one carries its colour + level', fx[0][1] == 1.0 and abs(fx[0][4] - 0.9) < 1e-6 and fx[1][4] == 0.0))
ms2 = [bs.osc_decode(m) for m in bs.Framer().messages(dict(clock={}, audio={}, cols={}))]
ok.append(('no fixtures (hub not in a show): no /ney/fix, nothing breaks', not [a for a, _ in ms2 if a == '/ney/fix']))
src = open(os.path.join(HERE, 'hue_hub.py')).read()
ok.append(('the hub stream carries fix=', "fix=self._fix_snap()" in src and 'def _fix_snap(self):' in src))
for n, v in ok:
    print(('PASS ' if v else 'FAIL ') + n)
print('ar feed tests: %d passed, %d failed' % (sum(v for _, v in ok), sum(not v for _, v in ok)))
sys.exit(0 if all(v for _, v in ok) else 1)
