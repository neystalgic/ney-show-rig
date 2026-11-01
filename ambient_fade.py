# =============================================================================
# AMBIENT FADE -- slow, vibrant rainbow gradients for movie nights (no hub needed)
#
# Every lamp shows a different colour so the room reads as one rainbow gradient
# (left to right as the lamps stand), and the whole gradient drifts slowly round
# the colour wheel. The Play floor lamp shows its own 5-colour slice of it.
# Colours are perceptually even (hub_palette.vivid), fades are done by the bulbs.
#
#   python3 ambient_fade.py [brightness 0-100] [seconds per full turn] [spread degrees, 0 = all one colour]
#   stop: Ctrl+C, or create a file called ambient.stop next to this script
# Don't run it while the Hue Hub is running (they'd fight over the lamps).
# =============================================================================
import os, sys, time, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hue_stream as hs
from hub_palette import vivid

BRI = float(sys.argv[1]) if len(sys.argv) > 1 else 65.0
TURN = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0     # seconds for the rainbow to go all the way round
SPREAD = float(sys.argv[3]) if len(sys.argv) > 3 else 240.0  # degrees of rainbow across the room
                                                               # (0 = every lamp the SAME colour, fading round the rainbow together)
BREATH = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0     # seconds per breath (0 = steady brightness)
BRI_LO = float(sys.argv[5]) if len(sys.argv) > 5 else BRI * 0.35   # brightness at the bottom of the out-breath
HUE_LO = float(sys.argv[6]) if len(sys.argv) > 6 else None   # optional colour range (hue degrees): the colours
HUE_HI = float(sys.argv[7]) if len(sys.argv) > 7 else None   # drift back and forth between these instead of round the wheel
STEP = 1.25 if BREATH else 2.0                                 # seconds between updates (the bulbs fade in between)


def breath_level(t):
    """0..1: a calm breath -- 40% of the time breathing in (rising), 60% breathing out (falling), eased."""
    import math
    ph = (t % BREATH) / BREATH
    k = ph / 0.4 if ph < 0.4 else 1.0 - (ph - 0.4) / 0.6
    return 0.5 - 0.5 * math.cos(math.pi * k)
STOP = os.path.join(HERE, 'ambient.stop')

cfg = hs.load_config()
area = [a for a in hs.v2(cfg, 'entertainment_configuration').get('data', [])
        if a['metadata']['name'] == 'Music area'][0]
ents = {e['id']: e for e in hs.v2(cfg, 'entertainment').get('data', [])}
lamps = []
for sl in area['locations']['service_locations']:
    rr = ents.get(sl['service']['rid'], {}).get('renderer_reference', {})
    if rr.get('rtype') == 'light':
        x = sum(p['x'] for p in sl['positions']) / len(sl['positions'])
        lamps.append((x, rr['rid']))
lamps.sort()
info = {l['id']: l for l in hs.v2(cfg, 'light').get('data', [])}
order = [rid for _, rid in lamps]
n = len(order)
for rid in order:                                              # stop any built-in effect first
    try:
        hs.v2(cfg, 'light/' + rid, 'PUT', {'effects_v2': {'action': {'effect': 'no_effect'}}})
    except Exception:
        pass
if os.path.exists(STOP):
    os.remove(STOP)
print('Ambient fade: %d lamps, %g%% brightness, a full turn every %gs. Ctrl+C or ambient.stop to stop.' % (n, BRI, TURN))
t0 = time.time()
while not os.path.exists(STOP):
    base = ((time.time() - t0 + STEP) / TURN) * 360.0       # aim where the colour will be when the fade ends
    if HUE_LO is not None and HUE_HI is not None:           # a colour range: drift lo -> hi -> lo, one round trip per TURN
        import math
        base = HUE_LO + (HUE_HI - HUE_LO) * (0.5 - 0.5 * math.cos(2 * math.pi * (time.time() - t0 + STEP) / TURN))
    bri = BRI_LO + (BRI - BRI_LO) * breath_level(time.time() - t0 + STEP) if BREATH else BRI
    for i, rid in enumerate(order):
        h = base + SPREAD * (i / max(1, n - 1) - 0.5)
        xy = lambda hh: hs.rgb_to_xyb(*vivid(hh % 360.0))[:2]
        body = {'on': {'on': True}, 'dimming': {'brightness': bri}, 'dynamics': {'duration': int(STEP * 1000)}}
        if info.get(rid, {}).get('gradient'):
            pts = [xy(h + (j / 4.0 - 0.5) * (SPREAD / max(1, n - 1)) * 2) for j in range(5)]
            body['gradient'] = {'points': [{'color': {'xy': {'x': x, 'y': y}}} for x, y in pts]}
        else:
            x, y = xy(h)
            body['color'] = {'xy': {'x': x, 'y': y}}
        try:
            hs.v2(cfg, 'light/' + rid, 'PUT', body)
        except Exception as e:
            print('  %s: %s' % (info.get(rid, {}).get('metadata', {}).get('name', rid), e))
        time.sleep(0.12 if SPREAD else 0.02)          # all-one-colour: send them back to back so they move together
    time.sleep(max(0.0, STEP - (0.12 if SPREAD else 0.02) * n))
os.remove(STOP)
print('Ambient fade stopped.')
