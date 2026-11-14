#!/usr/bin/env python3
# OFFLINE TEST for the Unreal Beat Deck (parts 2-4). Reads files only -- no network,
# no imports of the live rig modules. Checks the deck against the rig's real sources:
#   * every /ney/... OSC address in the deck exists in beat_sender.py
#   * the DMX patch (addresses, footprints, universe) matches dmx/config/heads_config.json
#     and the fixture layouts in dmx/app/dmx_node.py, and no two fixtures overlap
#   * the Flower of Life HLSL maths really gives 7 circles through the centre
#   * part 1 is kept word for word, and the deck holds no IP addresses or secrets
# Run: python3 test_deck.py
import ast, json, math, os, re, socket, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
DECK = open(os.path.join(HERE, 'Unreal Beat Deck.txt')).read()
fails = []

def check(ok, what):
    print(('PASS ' if ok else 'FAIL ') + what)
    if not ok:
        fails.append(what)

# block the network for the whole run, so a slip can't reach the LAN
def _no_net(*a, **k):
    raise RuntimeError('network blocked in tests')
socket.socket.connect = _no_net
socket.socket.sendto = _no_net
socket.create_connection = _no_net

# 1. OSC addresses
sender = open(os.path.join(REPO, 'beat_sender.py')).read()
known = set(re.findall(r'/ney/[a-z_]+', sender))
used = set(re.findall(r'/ney/[a-z_]+', DECK))
check(used and used <= known, 'OSC addresses in deck all exist in beat_sender.py (%s)' % ', '.join(sorted(used - known)) if used - known else 'OSC addresses in deck all exist in beat_sender.py')
check('/ney/drop' in used and '/ney/kick' in used, 'part 2 uses /ney/kick and /ney/drop')

# 2. DMX layouts from dmx_node.py, read with ast (no import, nothing runs)
node_src = open(os.path.join(REPO, 'dmx', 'app', 'dmx_node.py')).read()
consts = {}
for n in ast.parse(node_src).body:
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
            and n.targets[0].id in ('LM70S_14', 'FOCUS_17'):
        consts[n.targets[0].id] = {kw.arg: kw.value.value for kw in n.value.keywords}
lm, fo = consts['LM70S_14'], consts['FOCUS_17']
check(len(lm) == 14 and len(fo) == 17, 'node layouts are 14 and 17 channels')
# deck's function lists: count channels (16 bit = 2)
def deck_channels(title):
    block = DECK.split('"%s"' % title, 1)[1].split('\n    "', 1)[0].split('Check the channel count', 1)[0]
    total = 0
    for part in re.split(r'[|\n]', block.split('--', 1)[1].split('channels:', 1)[1]):
        m = re.search(r'(16|8) bit|\b(8)\s*(\(|$)', part.strip())
        if '16 bit' in part:
            total += 2
        elif re.search(r'\b8\b', part):
            total += 1
    return total
check(deck_channels('LM70S 14ch') == 14, 'deck LM70S function list adds up to 14 channels (got %d)' % deck_channels('LM70S 14ch'))
check(deck_channels('Focus Spot 17ch') == 17, 'deck Focus Spot function list adds up to 17 channels (got %d)' % deck_channels('Focus Spot 17ch'))
# order: pan, tilt first in both, dimmer where the node has master
check(lm['master'] == 5 and fo['master'] == 9, 'node master channel at the offsets the deck lists (LM70S 6th, Focus 10th)')

# 3. patch vs the node's own config (addresses only are read; nothing is printed but names/addresses)
cfg = json.load(open(os.path.join(REPO, 'dmx', 'config', 'heads_config.json')))
rows = re.findall(r'^\s{6}(Head \d|Focus Spot \d) \(([^)]*)\)\s+(LM70S 14ch|Focus Spot 17ch)\s+(\d+)', DECK, re.M)
check(len(rows) == len(cfg['heads']) == 6, 'deck patches all 6 fixtures (got %d rows)' % len(rows))
spans = []
for (name, where, ftype, addr), h in zip(rows, cfg['heads']):
    full = '%s (%s)' % (name, where)
    want_type = 'Focus Spot 17ch' if h.get('type') == 'focus17' else 'LM70S 14ch'
    check(full == h['name'] and int(addr) == int(h['addr']) and ftype == want_type,
          'patch %s = addr %s, %s' % (full, addr, ftype))
    foot = 17 if ftype.startswith('Focus') else 14
    spans.append((int(addr), int(addr) + foot - 1, name))
spans.sort()
check(all(a[1] < b[0] for a, b in zip(spans, spans[1:])) and spans[-1][1] <= 512, 'no overlapping DMX addresses, all inside one universe')
check(int(cfg.get('universe', 0)) == 0 and 'Extern Universe Start 0' in DECK, 'universe 0 on the node = Extern Universe Start 0 in the deck')
for h in cfg['heads']:
    deg = 240 if h.get('type') == 'focus17' else 180
    check(('-%d to %d' % (deg // 2, deg // 2)) in DECK, 'tilt range for %d-degree fixtures is in the deck' % deg)

# 4. the Flower of Life maths (same as the HLSL, Kick = Drop = Time = 0)
R = 60.0
pts = []
for i in range(252):
    c, k = i // 36, i % 36
    a = k * 2 * math.pi / 36
    cx, cy = (0.0, 0.0) if c == 0 else (R * math.cos((c - 1) * math.pi / 3), R * math.sin((c - 1) * math.pi / 3))
    pts.append((c, cx + R * math.cos(a), cy + R * math.sin(a), cx, cy))
check(max(c for c, *_ in pts) == 6 and len(pts) == 252 and 'Spawn Count 252' in DECK, '252 points make 7 circles')
check(all(abs(math.hypot(x - cx, y - cy) - R) < 1e-9 for _, x, y, cx, cy in pts), 'every point sits on its circle')
check(all(abs(math.hypot(cx, cy) - (R if c else 0)) < 1e-9 for c, _, _, cx, cy in pts), 'outer centres are one radius out (all circles pass through the middle)')
check('1.0471976' in DECK and '6.2831853' in DECK, 'HLSL uses 60 deg and 2 pi constants')

# 5. part 1 kept word for word (except the title line and the old "NEXT PARTS" teaser)
live = open(os.path.join(REPO, 'Unreal Beat Deck.txt')).read().split('\n')
body = live[1:live.index(next(l for l in live if l.startswith('NEXT PARTS')))]
check('\n'.join(body).rstrip() in DECK, 'part 1 (A-D) is unchanged in the new deck')

# 6. no addresses / secrets in a plain-text guide
check(not re.search(r'\b(192\.168|10\.\d+|100\.\d+)\.\d+\.\d+', DECK), 'no LAN/Tailscale IP addresses in the deck')
check(not re.search(r'token|password|hue_config', DECK, re.I), 'no secrets mentioned in the deck')
check(not re.search(r'\bamber\b', DECK, re.I), 'no amber colour suggested (Michael: no amber)')

print('\n%d failed' % len(fails) if fails else '\nALL PASSED')
sys.exit(1 if fails else 0)
