#!/usr/bin/env python3
"""Full-power test (Nov 11): drives every head and spot through what the hardware can actually do.
Sends Art-Net straight to the DMX node (the hub must be stopped first, or it fights this).
Needs node v2 with unlocks on (POST /unlock {"strobe":true,"white":true,"wheels":true,"flash_hz":20}).

  A  8 s  baseline: purple, full dimmer, beams leaning out toward the walls
  B 14 s  native strobe on the heads, slow -> as fast as they go, colour stepping R G B W
  C  6 s  open white, everything full
  D 14 s  spots: shutter strobe slow -> fast, fast colour-wheel spin, gobo spin, focus pull; heads chase
  E 10 s  fast movement: all heads swing their whole pan window together, then back
  F  4 s  big finish: everything white + max strobe, then dark
python3 full_power_test.py [node ip] [phase letters, e.g. ABCDEF]
"""
import json, math, socket, struct, sys, time, urllib.request

NODE = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.80'
PHASES = sys.argv[2] if len(sys.argv) > 2 else 'ABCDEF'
FPS = 30
cfg = json.loads(urllib.request.urlopen('http://%s:7060/config' % NODE, timeout=4).read())
heads = cfg['heads']
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
seq = 0

def send(d):
    global seq
    seq = (seq + 1) % 256
    pkt = b'Art-Net\x00' + struct.pack('<H', 0x5000) + struct.pack('>H', 14) + bytes([seq, 0]) + struct.pack('<H', 0) + struct.pack('>H', 512) + bytes(d)
    sock.sendto(pkt, (NODE, 6454))

def aim(h, d, a, lean_deg, pan_frac):
    tdeg = 240.0 if h.get('type') == 'focus17' else 180.0
    tu = int(h['tilt_up']); tdir = int(h.get('tilt_dir', 1))
    tilt = max(0, min(65535, int(tu + tdir * lean_deg / tdeg * 65535)))
    pan = int(int(h['pan_min']) + (int(h['pan_max']) - int(h['pan_min'])) * pan_frac)
    d[a], d[a + 1], d[a + 2], d[a + 3] = pan >> 8, pan & 255, tilt >> 8, tilt & 255

def frame(t, ph):
    d = bytearray(512)
    for n, h in enumerate(heads):
        a = int(h['addr']) - 1
        spot = h.get('type') == 'focus17'
        lean, pf = 30.0, 0.5
        if ph == 'E':
            pf = 0.5 + 0.5 * math.sin(t * 1.6 + n * 0.0)        # all together, full window
            lean = 35.0
        aim(h, d, a, lean, pf)
        if spot:
            col, shut, gobo, grot, focus, dim = 37, 12, 0, 0, 128, 255
            if ph == 'A': col = 75                               # a colour slot
            if ph == 'C' or ph == 'F': col = 5                   # open white
            if ph == 'D':
                shut = int(16 + (131 - 16) * min(1.0, t / 12.0))  # strobe slow -> fast
                col = 140                                         # fast clockwise wheel spin
                gobo, grot = 40, 230                              # a gobo, spinning fast
                focus = int(128 + 120 * math.sin(t * 2.0))
            if ph == 'F': shut = 131
            d[a + 4], d[a + 5], d[a + 6], d[a + 7], d[a + 8], d[a + 9] = col, gobo, grot, focus, shut, dim
        else:
            r, g, b, w, master = 160, 0, 255, 0, 134            # purple, full dimmer
            if ph == 'B':
                master = int(135 + (239 - 135) * min(1.0, t / 12.0))     # strobe slow -> fast
                r, g, b, w = [(255, 0, 0, 0), (0, 255, 0, 0), (0, 0, 255, 0), (0, 0, 0, 255)][int(t / 1.5) % 4]
            if ph == 'C': r, g, b, w, master = 255, 255, 255, 255, 134
            if ph == 'D':
                r, g, b, w = [(255, 0, 120, 0), (0, 120, 255, 0)][int(t * 2) % 2]   # heads chase at 2/s
            if ph == 'E': r, g, b, w = 0, 255, 180, 0
            if ph == 'F': r, g, b, w, master = 255, 255, 255, 255, 239
            d[a + 5], d[a + 6], d[a + 7], d[a + 8], d[a + 9] = master, r, g, b, w
    return d

LEN = dict(A=8, B=14, C=6, D=14, E=10, F=4)
for ph in PHASES:
    print('phase', ph, flush=True)
    t0 = time.time()
    while time.time() - t0 < LEN[ph]:
        send(frame(time.time() - t0, ph))
        time.sleep(1.0 / FPS)
for _ in range(30):                                            # dark, then stop sending (node fades + parks)
    send(bytearray(512)); time.sleep(1.0 / FPS)
print('done', flush=True)
