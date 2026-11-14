#!/usr/bin/env python3
# =============================================================================
# Offline test for Health Report v2 (Nov 14). Fake CSVs in a temp folder -- never touches the
# real Desktop logs, never opens a network connection (sockets are blocked while it runs).
#   python3 test_health_report.py
# Part 1 checks body_log.summary() numbers; part 2 (if node is installed) runs the page's
# JavaScript against a fake browser and checks the headline tiles.
# =============================================================================
import csv, datetime as dt, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))


def _no_network(*a, **k):
    raise RuntimeError('test tried to use the network')
socket.socket = _no_network
socket.create_connection = _no_network


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def point_at(m, folder):
    m.WEIGHT, m.FOOD, m.ACTIVITY = (os.path.join(folder, n) for n in ('Weight Log.csv', 'Food Log.csv', 'Activity Log.csv'))
    m.HEADERS = {m.FOOD: ['Date', 'Time', 'Item', 'Calories', 'Protein (g)', 'Source'],
                 m.ACTIVITY: ['Date', 'Active kcal', 'Resting kcal', 'Steps', 'Exercise min', 'Sleep h', 'Resting HR', 'HRV ms', 'VO2max']}


T = dt.date.today()
day = lambda n: (T + dt.timedelta(days=n)).isoformat()


def write_fake(folder, food_days=19):
    with open(os.path.join(folder, 'Weight Log.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Date', 'Weight (lb)', 'Notes'])
        for i, n in enumerate(range(-29, 1)):
            w.writerow([day(n), round(270 - 0.2 * i, 1), ''])           # losing 0.2 lb a day, steady
    with open(os.path.join(folder, 'Food Log.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Date', 'Time', 'Item', 'Calories', 'Protein (g)', 'Source'])
        for n in range(-food_days, 0):
            w.writerow([day(n), '12:00', 'meal', 2500, 150, 'test'])
        w.writerow([day(-3), '20:00', 'mystery snack', '', '', 'test'])  # unknown calories -> partial day
    with open(os.path.join(folder, 'Activity Log.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Date', 'Active kcal', 'Resting kcal', 'Steps', 'Exercise min', 'Sleep h', 'Resting HR', 'HRV ms', 'VO2max'])
        for n in range(-19, 0):
            resting = '' if n >= -5 else 2100                             # last 5 days: Watch sent no resting kcal
            hr = 57 if n == -1 else (60 if n >= -8 else 62)
            w.writerow([day(n), 800, resting, 9000, 30, 6.5 if n == -2 else 7.5, hr, 45, 38])


fails = []
def check(name, ok, got=None):
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else '  (got %r)' % (got,)))
    if not ok:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='health-v2-test-')
try:
    v2 = load(os.path.join(HERE, 'body_log.py'), 'body_log_v2')
    v1 = load(os.path.join(ROOT, 'body_log.py'), 'body_log_v1')    # live file, read only, for the "nothing broke" check

    # --- Mifflin-St Jeor estimate ---
    check('resting estimate 263.8 lb in 2026 = 2257', v2.resting_estimate(263.8, dt.date(2026, 11, 14)) == 2257,
          v2.resting_estimate(263.8, dt.date(2026, 11, 14)))
    check('no weight -> no estimate', v2.resting_estimate(None) is None)

    # --- empty logs don't crash ---
    point_at(v2, tmp)
    s = v2.summary()
    check('empty: deficit empty', s['deficit'] == {} and s['deficit_avg7'] == {})
    check('empty: adaptive needs 14 days', s['adaptive'] == {'kcal': None, 'need_days': 14}, s['adaptive'])
    check('empty: no HR check', s['hr_check'] is None)

    # --- full fake month ---
    write_fake(tmp)
    point_at(v1, tmp)
    s, old = v2.summary(), v1.summary()
    D = s['deficit']
    check('deficit with Watch resting = 800+2100-2500 = 400', D[day(-10)] == {'burn': 2900, 'eaten': 2500, 'deficit': 400,
          'resting_est': False, 'partial': False}, D.get(day(-10)))
    est = v2.resting_estimate(270 - 0.2 * 28, T + dt.timedelta(days=-1))
    check('missing resting kcal -> estimated + flagged', D[day(-1)]['resting_est'] and D[day(-1)]['deficit'] == 800 + est - 2500, D.get(day(-1)))
    check('meal without calories -> partial', D[day(-3)]['partial'] is True)
    check('no deficit on a day with no food', day(0) not in D)
    want = [D[day(n)]['deficit'] for n in range(-7, 0) if n != -3]
    check('7-day avg skips partial days', s['deficit_avg7'][day(-1)] == int(round(sum(want) / len(want))), s['deficit_avg7'].get(day(-1)))
    ad = s['adaptive']
    check('adaptive burn ~ 2500 + 0.2 lb/day x 3500 = 3200', ad['kcal'] is not None and abs(ad['kcal'] - 3200) <= 40, ad)
    check('adaptive uses 18 complete food days', ad.get('days') == 18 and abs(ad['lb_per_week'] - 1.4) < 0.1, ad)
    hc = s['hr_check']
    check('resting HR 57 vs 7-day avg 60 (-3)', hc == {'date': day(-1), 'hr': 57.0, 'avg7': 60.0, 'diff': -3.0}, hc)
    wk = s['weekly'][0]
    check('weekly has v2 columns', all(k in wk for k in ('avg_deficit', 'avg_resting_hr', 'avg_hrv', 'avg_sleep')), wk)
    check('resting estimate for today from latest weight', s['resting_est_today'] == v2.resting_estimate(264.2), s['resting_est_today'])

    # --- nothing v1 relied on changed ---
    for k in ('days', 'weight', 'weight_avg7', 'activity', 'today', 'change', 'start', 'latest'):
        check('v1 key unchanged: ' + k, s[k] == old[k])
    check('v1 food numbers unchanged', all({kk: v for kk, v in s['food'][d].items() if kk != 'unknown'} == old['food'][d] for d in old['food']))
    v1cols = ('week_of', 'avg_calories', 'avg_protein', 'avg_weight', 'avg_active_kcal', 'avg_steps', 'days_logged')
    check('v1 weekly columns unchanged', [{c: r[c] for c in v1cols} for r in s['weekly']] == [{c: r[c] for c in v1cols} for r in old['weekly']])

    # --- fewer than 14 food days -> adaptive waits ---
    write_fake(tmp, food_days=10)
    a2 = v2.summary()['adaptive']
    check('10 food days (1 partial) -> needs 5 more', a2 == {'kcal': None, 'need_days': 5}, a2)
    check('summary is JSON-safe', bool(json.dumps(s)))

    # --- part 2: run the page's JavaScript against a fake browser ---
    node = shutil.which('node')
    if not node:
        print('SKIP page render test (node not installed)')
    else:
        html = open(os.path.join(HERE, 'body.html'), encoding='utf-8').read()
        js = html.split('<script>', 1)[1].rsplit('</script>', 1)[0]
        harness = os.path.join(tmp, 'render.js')
        with open(harness, 'w', encoding='utf-8') as f:
            f.write('''
const DATA=%s;const els={};
const ctx=new Proxy({},{get:(t,k)=>k in t?t[k]:(()=>{}),set:(t,k,v)=>(t[k]=v,true)});
function el(id){return els[id]||(els[id]={id,textContent:'',innerHTML:'',clientWidth:320,clientHeight:180,width:0,height:0,
 getContext:()=>ctx,parentNode:{classList:{on:{},toggle(c,b){this.on[c]=!!b}}},querySelector(){return this},value:''})}
global.document={getElementById:el,documentElement:{}};global.window={devicePixelRatio:2};
global.getComputedStyle=()=>({getPropertyValue:()=>' #a36bff '});global.setInterval=()=>0;global.addEventListener=()=>0;
global.fetch=async()=>({ok:true,json:async()=>DATA,text:async()=>''});
%s
setTimeout(()=>{console.log(JSON.stringify({def:String(els.t_def.textContent),ldef:els.l_def.textContent,good:els.t_def.parentNode.classList.on.good,
 def7:String(els.t_def7.textContent),ad:String(els.t_ad.textContent),lad:els.l_ad.textContent,hr:els.hrline.textContent,rows:els.wk.innerHTML.split('<tr>').length-1,sub:els.sub.textContent}))},50);
''' % (json.dumps(s), js))
        out = subprocess.run([node, harness], capture_output=True, text=True, timeout=30)
        check('page JS runs without errors', out.returncode == 0 and not out.stderr.strip(), out.stderr[-500:])
        if out.returncode == 0:
            r = json.loads(out.stdout.strip().splitlines()[-1])
            last = D[day(-1)]
            check('headline tile = latest deficit', r['def'] == str(last['deficit']), r)
            check('headline says est. when resting is estimated', '(est.)' in r['ldef'], r['ldef'])
            check('green flag matches the 500 goal', r['good'] == (last['deficit'] >= 500), r)
            check('7-day avg tile', r['def7'] == str(s['deficit_avg7'][day(-1)]), r)
            check('adaptive tile shows kcal + lb/wk', r['ad'] == str(ad['kcal']) and 'lb/wk' in r['lad'], r)
            check('HR line text', r['hr'].startswith('Resting HR 57 bpm') and '(-3)' in r['hr'], r['hr'])
            check('weekly table drawn', r['rows'] >= 3, r)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n%d failed' % len(fails) if fails else '\nALL PASSED')
sys.exit(1 if fails else 0)
