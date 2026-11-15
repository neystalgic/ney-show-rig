#!/usr/bin/env python3
# Offline tests for the TouchDesigner tidy-up plan (away/td-tidy, Nov 15). No TouchDesigner, no hub, no lights,
# no network: a fake operator tree stands in for /project1. Run:  python3 test_td_tidy.py
import ast, os, socket, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _no_network(*a, **k):
    raise AssertionError('tests must not touch the network')


socket.socket = _no_network
socket.create_connection = _no_network

import tidy_map as M
import cook_audit as A

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print('FAIL %s %s' % (name, detail))


# ---- 1. the map covers everything the builders put in /project1
refs = M.builder_names()
check('builders found', len(refs) >= 30, len(refs))
unsorted = [n for n in refs if M.classify(n) == 'UNSORTED']
check('every builder operator has a box', not unsorted, unsorted)
for must in ('hue_feed', 'vj', 'vj_pick', 'show_out', 'projector_window', 'mcp_webserver_base', 'geo_show', 'osmo_mix'):
    check('builders mention %s' % must, must in refs)
check('5 boxes', set(M.GROUPS) == {'INPUT', 'DECKS', 'MIXER', 'OUTPUT', 'SYSTEM'})
check('every box has a title + colour', all(g['title'] and len(g['colour']) == 3 for g in M.GROUPS.values()))
check('no white/amber box colours (Michael)', all(not (min(g['colour']) > 0.8) for g in M.GROUPS.values()))
check('columns left to right', [M.GROUPS[g]['x'] for g in ('INPUT', 'DECKS', 'MIXER', 'OUTPUT')] == sorted(
    M.GROUPS[g]['x'] for g in ('INPUT', 'DECKS', 'MIXER', 'OUTPUT')))

# ---- 2. the groups make sense
for n, g in (('hue_feed', 'INPUT'), ('show_clock', 'INPUT'), ('movie_in', 'INPUT'), ('flower_of_life', 'DECKS'),
             ('proc_mandala', 'DECKS'), ('mp_plasma', 'DECKS'), ('comp2', 'MIXER'), ('vj', 'MIXER'),
             ('vj_pick', 'MIXER'), ('osmo_mix', 'MIXER'), ('show_out', 'OUTPUT'), ('projector_window', 'OUTPUT'),
             ('hue_rig', 'SYSTEM'), ('mcp_webserver_base', 'SYSTEM'), ('something_new', 'UNSORTED')):
    check('classify %s -> %s' % (n, g), M.classify(n) == g, M.classify(n))

# ---- 3. safety lists
for n in ('mcp_webserver_base', 'hue_rig', 'hue_feed', 'show_clock', 'projector_window'):
    check('%s never touched' % n, n in M.NEVER_TOUCH and not M.sleepable(n))
check('strobe deck never put to sleep/woken by the plan', not M.sleepable('mp_strobe'))
check('geo_show not sleepable (projector fallback)', not M.sleepable('geo_show'))
for n in ('flower_of_life', 'proc_life', 'mp_tunnel', 'breath_3d', 'reaction_diffusion'):
    check('%s sleepable' % n, M.sleepable(n))
check('nothing in MIXER/OUTPUT/SYSTEM is sleepable',
      not [n for n in refs if M.classify(n) in ('MIXER', 'OUTPUT', 'SYSTEM', 'INPUT') and M.sleepable(n)])

# ---- 4. CSV
with tempfile.TemporaryDirectory() as d:
    p, n = M.write_csv(os.path.join(d, 'g.csv'))
    lines = open(p).read().splitlines()
    check('csv rows = operators + header', len(lines) == n + 1 and n == len(refs), (len(lines), n))
    check('csv header', lines[0].startswith('operator,group,'))

# ---- 5. cook_audit is read-only (checked by reading its code)
tree = ast.parse(open(os.path.join(HERE, 'cook_audit.py')).read())
BAD_CALLS = {'create', 'destroy', 'connect', 'disconnect', 'copy', 'copyOPs', 'save', 'store', 'unstore', 'run',
             'cook', 'pulse', 'write', 'system', 'Popen', 'urlopen', 'request', 'send', 'sendBytes', 'unlink', 'remove'}
bad = []
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        f = node.func
        nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')
        if nm in BAD_CALLS:
            bad.append(nm)
        if nm == 'open':
            bad.append('open')
    if isinstance(node, (ast.Assign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and not (isinstance(t.value, ast.Name) and t.value.id == '_spec'):
                bad.append('sets .%s' % t.attr)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        mods = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
        if set(mods) & {'socket', 'urllib', 'requests', 'subprocess', 'http', 'shutil'}:
            bad.append('import %s' % mods)
check('cook_audit only reads', not bad, bad)
tree2 = ast.parse(open(os.path.join(HERE, 'tidy_map.py')).read())
imps = [a.name for n in ast.walk(tree2) if isinstance(n, ast.Import) for a in n.names]
check('tidy_map imports only csv/os/re', set(imps) <= {'csv', 'os', 're'}, imps)


# ---- 6. cook_audit on a fake /project1
class FakeOp:
    def __init__(self, name, cooks=0, cpu=0.0, kids=()):
        self.name, self.totalCooks, self.cpuCookTime, self.gpuCookTime = name, cooks, cpu, 0.0
        self.kids = list(kids)
        self.children = self.kids

    def findChildren(self):
        out = []
        for k in self.kids:
            out += [k] + k.findChildren()
        return out


inner = FakeOp('glsl1', 100)
root = FakeOp('project1', kids=[FakeOp('hue_feed', 50), FakeOp('flower_of_life', 10, kids=[inner]),
                                FakeOp('proc_life', 5), FakeOp('mp_strobe', 3), FakeOp('vj', 7),
                                FakeOp('mcp_webserver_base', 1), FakeOp('mystery', 0)])
a = A.snap(root)
check('snap counts children too', a['ops']['flower_of_life']['cooks'] == 110, a['ops']['flower_of_life'])
# one frame later: hue_feed, flower (inner), proc_life and vj cooked; strobe idle
root.kids[0].totalCooks += 1; inner.totalCooks += 1; root.kids[2].totalCooks += 1; root.kids[4].totalCooks += 1
before = {k: (o.totalCooks) for k, o in [(o.name, o) for o in root.kids]}
lines = []
r = A.report(a, root, printer=lines.append)
text = '\n'.join(lines)
check('two decks cooking flagged', r['decks_cooking'] == ['flower_of_life', 'proc_life'], r['decks_cooking'])
check('strobe deck not flagged', 'mp_strobe' not in r['decks_cooking'])
check('unsorted named', r['unsorted'] == ['mystery'], r['unsorted'])
check('report says read-only', 'read-only' in text)
check('report grouped in order', text.index('-- INPUT') < text.index('-- DECKS') < text.index('-- MIXER') < text.index('-- SYSTEM'))
check('report changed nothing', {o.name: o.totalCooks for o in root.kids} == before)
a2 = A.snap(root)
r2 = A.report(a2, root, printer=lambda s: None)
check('idle window -> decks OK', r2['decks_cooking'] == [])
check('new operator since snap does not crash', A.compare({'ops': {}}, a2)[0][2] == 0)


class Broken:
    name = 'broken'
    children = []

    @property
    def totalCooks(self):
        raise RuntimeError('no')

    def findChildren(self):
        raise RuntimeError('no')


check('odd operator does not crash snap', A.snap(FakeOp('p', kids=[Broken()]))['ops']['broken']['cooks'] == 0)

# ---- 7. plan files present, plain text
for f in ('PLAN.txt', 'DEPLOY.txt', 'Group Map.csv'):
    check('%s exists' % f, os.path.exists(os.path.join(HERE, f)))
check('no .md files', not [f for f in os.listdir(HERE) if f.endswith('.md')])
for f in ('PLAN.txt', 'DEPLOY.txt'):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        t = open(p).read()
        check('%s has no secrets/addresses' % f, 'hue_config' not in t and 'rig_control.token' not in t
              and '192.168.' not in t and 'ssh ' not in t)

print('%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
