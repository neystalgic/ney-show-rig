#!/usr/bin/env python3
"""Offline checks for "Health Sync Setup.txt" (Nov 14, away loop).
Makes sure the setup sheet matches the real code: every body_log field is covered, the URL is the Pi front
door's /body/activity, the shortcut it tells Michael to copy really carries the X-Token header and is harmless,
each section is 3 steps max, no secrets -- and that a payload built the way the sheet says lands correctly in
a TEMP Activity Log (never the real Desktop one). No network: sockets are blocked."""
import csv, datetime as dt, json, os, re, socket, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, RIG)
sys.path.insert(0, os.path.join(RIG, 'jarvis'))


def _no_net(*a, **k):
    raise RuntimeError('network blocked in tests')


socket.socket.connect = _no_net
socket.create_connection = _no_net

import body_log            # live module, imported read-only (its paths get swapped for a temp file below)
import shortcut_factory    # only builds dictionaries here; nothing is signed or opened

DOC = open(os.path.join(HERE, 'Health Sync Setup.txt'), encoding='utf-8').read()
RC = open(os.path.join(RIG, 'rig_control.py'), encoding='utf-8').read()
FD = open(os.path.join(RIG, 'pi', 'brain', 'front_door.py'), encoding='utf-8').read()
passed = failed = 0


def check(name, ok):
    global passed, failed
    print(('PASS ' if ok else 'FAIL ') + name)
    passed += bool(ok)
    failed += (not ok)


# --- the sheet covers the real fields and the real URL --------------------------------------------
for key in body_log.FIELDS:
    check('field %s is in the table and in the JSON list' % key,
          re.search(r'^\s+%s\s' % key, DOC, re.M) and DOC.count(key) >= 2)
url = shortcut_factory.BASE + '/body/activity'
check('URL = Pi front door + /body/activity (%s)' % url, url in DOC)
check('rig_control serves body/activity', "path == 'body/activity'" in RC)
check('rig_control turns day=yesterday into a date', "'yesterday'" in RC and 'add_activity(day' in RC)
check('front door passes POST bodies + Content-Type to the Mac', "self.headers.get('Content-Type')" in FD)
check('front door 503 message quoted in the sheet', "that one isn't available" in FD and "that one isn't available" in DOC)
check("rig_control's 'Not allowed.' and 'Send JSON.' quoted", "'Not allowed.'" in RC and "'Send JSON.'" in RC
      and '"Not allowed."' in DOC and '"Send JSON."' in DOC)
check('POST and JSON named', 'POST' in DOC and 'JSON' in DOC and 'day' in DOC and 'yesterday' in DOC)
check('alarm automation described', 'Is Stopped' in DOC and 'Run Immediately' in DOC)

# --- the shortcut to duplicate really has the key in a header, POSTs JSON, and changes no lights ---
names = {n: (kind, path) for n, kind, path in shortcut_factory.SET}
check('"Rig Health" is a generated shortcut', 'Rig Health' in names)
kind, path = names.get('Rig Health', ('?', '?'))
check('"Rig Health" is a page shortcut (opens a page, no look)', kind == 'page')
acts = shortcut_factory.actions(kind, path, 'FAKE-TOKEN-FOR-TEST')
first = acts[0]['WFWorkflowActionParameters']
hdr_keys = [i['WFKey']['Value']['string'] for i in first['WFHTTPHeaders']['Value']['WFDictionaryFieldValueItems']]
check('its Get Contents of URL carries X-Token', acts[0]['WFWorkflowActionIdentifier'].endswith('downloadurl')
      and 'X-Token' in hdr_keys)
check('its Get Contents of URL is already POST + JSON', first['WFHTTPMethod'] == 'POST'
      and first.get('WFHTTPBodyType') == 'JSON')
check('second action is the Open URL the sheet says to delete', len(acts) == 2
      and acts[1]['WFWorkflowActionIdentifier'] == 'is.workflow.actions.openurl' and 'Open URL' in DOC)

# --- Michael's style: 3 steps max per section, plain text, no secrets ------------------------------
sections = re.split(r'\n(?=[A-G]\. )', DOC)
for s in sections[1:]:
    steps = re.findall(r'^ (\d)\. ', s, re.M)
    check('section %s has 1-3 steps' % s[:1], 1 <= len(steps) <= 3 and steps == [str(i + 1) for i in range(len(steps))])
check('7 sections A-G', [s[:1] for s in sections[1:]] == list('ABCDEFG'))
check('no token / key value in the sheet', 'token=' not in DOC and 'FAKE-TOKEN' not in DOC
      and not re.search(r'[A-Za-z0-9_\-]{24,}', DOC))
check('only the Pi front door address appears', set(re.findall(r'\d+\.\d+\.\d+\.\d+', DOC)) == {'192.168.1.80'})
check('no paid/cloud services named', 'cloud' not in DOC.lower())
check('lines fit a phone-ish width (<=110)', max(len(l) for l in DOC.splitlines()) <= 110)

# --- simulate the morning POST against a TEMP Activity Log (same steps as rig_control) -------------
tmp = tempfile.mkdtemp()
fake = os.path.join(tmp, 'Activity Log.csv')
body_log.HEADERS[fake] = body_log.HEADERS[body_log.ACTIVITY]
real = body_log.ACTIVITY
body_log.ACTIVITY = fake


def post(payload):
    """The body/activity handler from rig_control.py, minus HTTP."""
    data = json.loads(json.dumps(payload).encode())
    day = str(data.get('day') or 'yesterday')
    if day in ('yesterday', 'today'):
        day = (dt.date.today() - dt.timedelta(days=1 if day == 'yesterday' else 0)).isoformat()
    row = body_log.add_activity(day, **{k: data.get(k) for k in body_log.FIELDS})
    got = ', '.join('%s %s' % (v, k) for k, v in row.items() if k != 'Date')
    return day, row, 'Health synced for %s: %s.' % (day, got or 'no numbers yet')


try:
    y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    full = {'day': 'yesterday', 'active_kcal': 612, 'resting_kcal': 2050.4, 'steps': 9123, 'exercise_min': 34,
            'sleep_h': 7.2, 'resting_hr': 58, 'hrv': 41.53, 'vo2max': 39.8}
    day, row, reply = post(full)
    check('day=yesterday files under yesterday', day == y)
    check('all 8 numbers stored', all(row.get(c) not in (None, '') for c in body_log.FIELDS.values()))
    check('reply looks like the sheet example', reply.startswith('Health synced for %s: 612.0 Active kcal' % y)
          and '7.2 Sleep h' in reply and '41.5 HRV ms' in reply)
    # Shortcuts sometimes sends numbers as text -- still fine
    day, row, _ = post({'day': y, 'steps': '9500', 'hrv': '44'})
    check('text numbers accepted + second sync replaces', row['Steps'] == 9500.0 and row['HRV ms'] == 44.0
          and row['Active kcal'] in (612.0, '612.0'))
    # a partial sync (only a few blocks wired) keeps the rest
    _, row, reply = post({'day': 'yesterday', 'resting_kcal': None, 'sleep_h': ''})
    check('empty values skipped, nothing wiped', str(row['Resting kcal']) == '2050.4' and str(row['Sleep h']) == '7.2')
    rows = list(csv.DictReader(open(fake, newline='')))
    check('one row per day in the CSV', len(rows) == 1 and rows[0]['Date'] == y)
    check('CSV header = body_log Activity header', list(rows[0].keys()) == body_log.HEADERS[real])
finally:
    body_log.ACTIVITY = real
check('real Activity Log path untouched by the test', body_log.ACTIVITY.endswith('Desktop/Activity Log.csv'))

print('\n%d passed, %d failed' % (passed, failed))
sys.exit(1 if failed else 0)
