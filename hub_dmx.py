# =============================================================================
# HUE HUB -- the MOVING HEADS (4x Betopper LM70S) through the Zephyrus' Enttec
#
#   hub (this Mac)  --Art-Net, ~40 a second-->  dmx_node.py on the Zephyrus  -->  Enttec  -->  heads
#
# The heads follow the room: each head takes the colour and brightness of a Hue lamp
# AFTER the flicker protection, so they can never flash faster than the lamps can.
#   * never white: colour saturation is kept at 55% or more, the white LED only softens pastels
#   * calm movement: slow sweeps locked to the beat, at most 25 degrees a second
#   * lean: only as far from straight up as each head's calibration allows (the node enforces it too)
#   * Movie mode, blackout, rest: heads go dark and point straight up
#   * breakdown -> beams gather toward the ceiling centre; drop -> they open out
#
# Settings (desk > Setup, or POST /api op=setting):
#   dmx_host   the Zephyrus' name or IP (its Tailscale name works), '' = heads off
#   dmx_level  head brightness 0..1 (default 0.8)      dmx_move   movement amount 0..1 (default 1)
#   dmx_strobe when the heads strobe: 'phrase' (default: the moment a drop lands + every 4 bars in it),
#              'drop' (only the moment a drop lands), 'off'
#   strobe_cone how far from straight up a head may be to strobe, degrees (default 45 = between 45 and 135
#              degrees above the surface it sits on). Strobe hits: at most 3 a second, room-wide, in colour
#              (never white), made by the hub -- the heads' own strobe channel stays locked off.
# =============================================================================

import colorsys
import json
import math
import socket
import struct
import threading
import time
import urllib.request

ARTNET_PORT = 6454
NODE_PORT = 7060
SEND_HZ = 40.0
MAX_DEG_S = 25.0                 # fastest a beam may swing (degrees a second): quiet motors, no whip pans
MASTER_MIN, MASTER_MAX = 8, 134  # LM70S master: dimming range only (135-239 = built-in strobe, never used)
CH = dict(pan=0, pan_fine=1, tilt=2, tilt_fine=3, speed=4, master=5, r=6, g=7, b=8, w=9)
DEFAULT_HEADS = [dict(addr=a, tilt_up=32768, tilt_dir=1, tilt_max_deg=35.0, pan_min=0, pan_max=65535, motor_speed=0)
                 for a in (1, 15, 29, 43)]


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def artdmx(seq, universe, data):
    return (b'Art-Net\x00' + struct.pack('<H', 0x5000) + struct.pack('>H', 14) +
            bytes([seq & 255, 0, universe & 255, (universe >> 8) & 127]) + struct.pack('>H', len(data)) + bytes(data))


class Heads:
    def __init__(self, hub):
        self.hub = hub
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0
        self.t_send = 0.0
        self.node_cfg = None
        self.node_status = None
        self.status = 'off'
        self.ip = None                     # the node's address (looked up off the show thread)
        self.st = []                       # per head: dict(theta, pan, lvl, flash)
        self.sec_prev = ''
        self.phrase_prev = None
        self.last_flash = -10.0
        self.flashes = 0
        self.run = True
        threading.Thread(target=self._poll, name='hub-dmx', daemon=True).start()

    def settings(self):
        return self.hub.state['settings']

    def host(self):
        return str(self.settings().get('dmx_host', '') or '').strip()

    # the node's calibration (tilt 'up', lean limits, pan windows) -- fetched every few seconds
    def _poll(self):
        while self.run:
            h = self.host()
            if h:
                try:
                    self.ip = socket.gethostbyname(h)
                except Exception:
                    self.ip = None
                    self.status = 'cannot find %s on the network' % h
                try:
                    with urllib.request.urlopen('http://%s:%d/config' % (h, NODE_PORT), timeout=2) as r:
                        self.node_cfg = json.loads(r.read())
                    with urllib.request.urlopen('http://%s:%d/status' % (h, NODE_PORT), timeout=2) as r:
                        self.node_status = json.loads(r.read())
                except Exception as e:
                    self.node_status = None
                    self.status = 'cannot reach the DMX node on %s (%s)' % (h, e.__class__.__name__)
            time.sleep(3.0)

    def heads(self):
        hs = (self.node_cfg or {}).get('heads') or DEFAULT_HEADS
        while len(self.st) < len(hs):
            self.st.append(dict(theta=0.0, pan=None, lvl=0.0, flash=0.0))
        return hs

    def frame(self, now, dt, beats, cols, pmode):
        """cols: the lamps' colours AFTER the flicker protection (0..1 RGB tuples)."""
        h = self.host()
        if not h or now - self.t_send < 1.0 / SEND_HZ:
            if not h:
                self.status = 'off (set dmx_host to the Zephyrus)'
            return
        dt = now - self.t_send if self.t_send else dt
        self.t_send = now
        s = self.settings()
        live = self.hub.live
        dark = (self.hub.blackout or bool(s.get('movie')) or pmode == 'sync' or not cols)
        level = clamp(float(s.get('dmx_level', 0.8))) * clamp(float(live.get('master', 1.0)))
        move = clamp(float(s.get('dmx_move', 1.0)))
        section = getattr(getattr(self.hub, 'audioshow', None), 'section', 'groove')
        spread = {'breakdown': 0.3, 'quiet': 0.45, 'groove': 0.75, 'drop': 1.0}.get(section, 0.75)
        tm = float(getattr(self.hub, 't_motion', beats / 4.0))
        # STROBE HITS: when a drop lands (+ each 4-bar phrase in it), only heads in the ceiling cone, max 3 a second
        cone = clamp(float(s.get('strobe_cone', 45.0)), 0.0, 45.0)
        smode = s.get('dmx_strobe', 'phrase')
        smode = 'phrase' if smode is True else 'off' if smode in (False, None) else str(smode)
        strobe_on = smode in ('phrase', 'drop') and section == 'drop' and not dark
        bpb = int(s.get('beats_per_bar', 4) or 4)
        phrase = int(math.floor(beats / (bpb * 4.0)))           # a 4-bar phrase
        landed = section == 'drop' and self.sec_prev != 'drop'
        new_phrase = self.phrase_prev is not None and phrase != self.phrase_prev
        fire = strobe_on and (landed or (smode == 'phrase' and new_phrase)) and now - self.last_flash >= 1.0 / 3.0 + 0.01
        self.sec_prev, self.phrase_prev = section, phrase
        if fire:
            self.last_flash = now
            self.flashes += 1
        data = bytearray(512)
        hs = self.heads()
        n = len(hs)
        for i, hd in enumerate(hs):
            st = self.st[i]
            # colour: a lamp spread across the room for each head
            src = cols[int(round(i * (len(cols) - 1) / max(1, n - 1)))] if cols else (0.0, 0.0, 0.0)
            hh, ss, vv = colorsys.rgb_to_hsv(*[clamp(x) for x in src])
            ss = max(ss, 0.55)                                  # never white
            r, g, b = colorsys.hsv_to_rgb(hh, ss, 1.0)
            w = (1.0 - ss) * 0.35
            want = 0.0 if dark else vv * level
            k = 1 - math.exp(-dt / (0.06 if want > st['lvl'] else 0.25))
            st['lvl'] += (want - st['lvl']) * k
            # movement: slow, beat-locked; lean only inside the calibrated window
            lean_max = clamp(float(hd.get('tilt_max_deg', 35.0)), 0.0, 60.0) * 0.95
            if dark:
                th_t = 0.0
            else:
                wave = 0.5 + 0.5 * math.sin(2 * math.pi * (tm / 8.0 + i * 0.3))
                th_t = lean_max * move * spread * (0.35 + 0.65 * wave)
                if strobe_on:
                    th_t = min(th_t, cone * 0.8)                 # in drops, stay inside the strobe cone
            step = MAX_DEG_S * dt
            st['theta'] += clamp(th_t - st['theta'], -step, step)
            pmin, pmax = int(hd.get('pan_min', 0)), int(hd.get('pan_max', 65535))
            u = 0.5 + 0.5 * math.sin(2 * math.pi * (tm / 32.0 + i / 4.0)) * (move if not dark else 0.0)
            p_t = pmin + u * (pmax - pmin)
            if st['pan'] is None:
                st['pan'] = p_t
            pstep = MAX_DEG_S / 540.0 * 65535.0 * dt
            if not dark:
                st['pan'] += clamp(p_t - st['pan'], -pstep, pstep)
            tilt = int(hd.get('tilt_up', 32768)) + int(hd.get('tilt_dir', 1)) * st['theta'] / 180.0 * 65535.0
            tilt = int(clamp(tilt, 0, 65535))
            pan = int(clamp(st['pan'], 0, 65535))
            lv = st['lvl']
            if fire and st['theta'] <= cone:
                st['flash'] = now + 0.05
            if now < st['flash']:
                lv = 1.0                                         # the hit: full, in the head's colour
                r, g, b = colorsys.hsv_to_rgb(hh, max(ss, 0.7), 1.0)
                w = 0.0
            master = 0 if lv < 0.004 else int(round(MASTER_MIN + clamp(lv) * (MASTER_MAX - MASTER_MIN)))
            a = int(hd.get('addr', 1)) - 1
            if a < 0 or a + 14 > 512:
                continue
            data[a + CH['pan']], data[a + CH['pan_fine']] = pan >> 8, pan & 255
            data[a + CH['tilt']], data[a + CH['tilt_fine']] = tilt >> 8, tilt & 255
            data[a + CH['speed']] = int(clamp(int(hd.get('motor_speed', 0)), 0, 255))
            data[a + CH['master']] = master
            data[a + CH['r']], data[a + CH['g']] = int(r * 255), int(g * 255)
            data[a + CH['b']], data[a + CH['w']] = int(b * 255), int(w * 255)
        try:
            if not self.ip:
                return
            self.sock.sendto(artdmx(self.seq, int((self.node_cfg or {}).get('universe', 0)), data), (self.ip, ARTNET_PORT))
            self.seq = (self.seq + 1) % 256 or 1
            ns = self.node_status
            if ns:
                ready = sum(1 for x in ns.get('heads', []) if x.get('calibrated'))
                self.status = 'sending to %s -- %s, %d of %d heads calibrated%s' % (
                    h, ns.get('output', '?'), ready, len(ns.get('heads', [])), (' -- ' + ns['error']) if ns.get('error') else '')
            elif not self.status.startswith('cannot'):
                self.status = 'sending to %s' % h
        except Exception as e:
            self.status = 'cannot send to %s (%s)' % (h, e)

    def describe(self):
        return self.status
