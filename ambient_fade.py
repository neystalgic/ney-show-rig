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
HEADS = len(sys.argv) > 8 and sys.argv[8] == 'heads'          # the moving heads join in (same colour, dim, slow drift)
HEAD_LVL = 0.35                                              # head brightness 0-1 (the node's own caps still apply)
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


def hue_at(t):
    """The colour (hue degrees) the lamps show at time t -- the heads use the same, smoothly."""
    import math
    if HUE_LO is not None and HUE_HI is not None:
        return HUE_LO + (HUE_HI - HUE_LO) * (0.5 - 0.5 * math.cos(2 * math.pi * t / TURN))
    return (t / TURN) * 360.0


def heads_loop():
    """Moving heads: each on its 'Coffee table' ceiling aim, drifting slowly, in the lamps' colour. Art-Net to the
    DMX node, which still enforces every safety limit. Never run with the Hue Hub (it stops the hub first)."""
    import json, math, socket, urllib.request
    import hub_dmx as hd
    try:
        st = json.load(open(os.path.join(HERE, 'hub_state.json')))['settings']
        host = str(st.get('dmx_host') or 'zephyrus').strip()
        tg = (st.get('head_targets') or {}).get('Coffee table') or {}
        ncfg = ip = None
        for h_ in [x.strip() for x in host.split(',') if x.strip()]:    # "LAN address, Tailscale name"
            try:
                ip = socket.getaddrinfo(h_, hd.ARTNET_PORT, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
                ncfg = json.loads(urllib.request.urlopen('http://%s:%d/config' % (ip, hd.NODE_PORT), timeout=2).read())
                break
            except Exception:
                continue
        if ncfg is None:
            raise OSError('no answer')
    except Exception as e:
        print('  heads: DMX node not reachable (%s) -- lamps only' % e.__class__.__name__)
        return
    heads, uni = ncfg['heads'], int(ncfg.get('universe', 0))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 0
    print('  heads: joining in on their Coffee table ceiling aims')
    while not os.path.exists(STOP):
        t = time.time() - t0
        lin = [max(0.0, c) ** 2.2 for c in vivid(hue_at(t) % 360.0)]
        mx = max(lin) or 1.0
        rgb = [int(round(255 * x / mx)) for x in lin]
        data = bytearray(512)
        for i, h in enumerate(heads):
            tt, a = tg.get(str(i)), int(h['addr']) - 1
            if not tt or a < 0 or a + 14 > 512:
                continue
            pan = int(tt['pan'] + 12.0 / 540.0 * 65535.0 * math.sin(2 * math.pi * (t / 150.0 + i / 4.0)))
            pan = max(int(h.get('pan_min', 0)), min(int(h.get('pan_max', 65535)), pan))
            tilt = int(tt['tilt'])
            data[a], data[a + 1], data[a + 2], data[a + 3] = pan >> 8, pan & 255, tilt >> 8, tilt & 255
            data[a + 4] = int(h.get('motor_speed', 0))
            data[a + 5] = int(round(hd.MASTER_MIN + HEAD_LVL * (hd.MASTER_MAX - hd.MASTER_MIN)))
            data[a + 6], data[a + 7], data[a + 8] = rgb
        try:
            sock.sendto(hd.artdmx(seq, uni, data), (ip, hd.ARTNET_PORT))
        except OSError:
            pass
        seq += 1
        time.sleep(1.0 / 25.0)


if HEADS:
    import threading
    threading.Thread(target=heads_loop, daemon=True).start()
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
print('Ambient fade stopped.')   # the heads' sender stops with it -> the node fades them out and parks them up
