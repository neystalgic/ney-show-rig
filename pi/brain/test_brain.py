import datetime as dt, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ney_brain as b
T = lambda h, m, d=12: dt.datetime(2026, 11, d, h, m)
ran = []
act = lambda n: ran.append(n)
# Mac up: never acts
done = {}; assert b.tick(T(23, 1), done, True, act) is None and ran == []
# Mac down at 22:31 -> wind-down runs once
done = {}; assert b.tick(T(22, 31), done, False, act) == 'winddown' and b.tick(T(22, 40), done, False, act) is None
# then night at 23:00
assert b.tick(T(23, 0), done, False, act) == 'night' and done['night'] == '2026-11-12'
# Mac asleep all evening, Pi notices at 01:30 (next day): night catches up, wind-down skipped
ran.clear(); done = {}
assert b.tick(T(1, 30, 13), done, False, act) == 'night' and done['night'] == '2026-11-12' and done['winddown'] == '2026-11-12'
assert b.tick(T(2, 0, 13), done, False, act) is None and ran == ['night']
# past 05:00 no more night catch-up; sunrise from 08:40, catch-up until 10:30
assert b.tick(T(6, 0, 13), done, False, act) is None
assert b.tick(T(9, 50, 13), done, False, act) == 'sunrise' and b.tick(T(10, 0, 13), done, False, act) is None
assert b.tick(T(10, 45, 14), {}, False, act) is None       # too late for sunrise
# run_steps sends xy + brightness, never sleeps for real here
sent = []; b.run_steps(b.SCHEDULE['night'][2], sleep=lambda s: None, put=sent.append)
assert sent[-1]['dimming']['brightness'] == 12.0 and sent[-1]['color']['xy'] == {'x': 0.69, 'y': 0.30}
assert b.is_plug({'metadata': {'name': 'Head 1'}, 'dimming': {}}) and not b.is_plug({'metadata': {'name': 'Couch lamp'}, 'dimming': {}})
print('brain tests passed')
