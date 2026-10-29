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
SWEEP_DEG_S = 150.0
MUSIC_SWEEP_DEG_S = 240.0        # music sweeps: as quick as the motors go              # movie sweeps only: a quick swing out and back on a loud moment
MAX_DEG_S = 25.0                 # fastest a beam may swing (degrees a second): quiet motors, no whip pans
MASTER_MIN, MASTER_MAX = 8, 134  # LM70S master: dimming range only (135-239 = built-in strobe, never used)
CH = dict(pan=0, pan_fine=1, tilt=2, tilt_fine=3, speed=4, master=5, r=6, g=7, b=8, w=9)
DEFAULT_HEADS = [dict(addr=a, tilt_up=32768, tilt_dir=1, tilt_max_deg=35.0, pan_min=0, pan_max=65535, motor_speed=0)
                 for a in (1, 15, 29, 43)]


AVOID_LEAN = 4.0


def in_avoid(hd, pan16, lean_deg, margin=0.0):
    """The node's rule: a beam leaning toward one of the head's avoid zones (pan degrees) more than the zone allows
    (AVOID_LEAN, or the zone's own 'lean' -- e.g. 25 = ceiling only, the beam stays above the screen)."""
    if abs(lean_deg) <= AVOID_LEAN:
        return False
    az = (pan16 * 540.0 / 65535.0 + (180.0 if lean_deg < 0 else 0.0)) % 360.0
    for z in hd.get('avoid') or []:
        if abs((az - float(z['az']) + 180.0) % 360.0 - 180.0) < float(z['width']) / 2.0 + margin:
            if abs(lean_deg) > max(AVOID_LEAN, float(z.get('lean', AVOID_LEAN) or AVOID_LEAN)):
                return True
    return False


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
        self.mv_fast = self.mv_slow = 0.0     # movie loudness (fast / slow) for the sweeps
        self.mv_bri = 0.0                     # movie loudness for the heads' brightness (soft: never a flash)
        self.k_prev, self.k_last, self.k_target, self.k_tm = 0.0, -10.0, 0.0, 0.0   # kick lock
        self.sweep_t, self.sweep_n, self.sweep_amp = -10.0, 0, 0.0
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
                try:                                         # IPv4 on purpose: by name the Zephyrus also answers on
                    self.ip = socket.getaddrinfo(h, NODE_PORT, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
                except Exception as e:                       # IPv6, where Windows drops it and each call stalls ~3 s
                    self.ip = None
                    self.status = 'cannot find %s on the network (%s)' % (h, e.__class__.__name__)
                try:
                    with urllib.request.urlopen('http://%s:%d/config' % (self.ip or h, NODE_PORT), timeout=2) as r:
                        self.node_cfg = json.loads(r.read())
                    with urllib.request.urlopen('http://%s:%d/status' % (self.ip or h, NODE_PORT), timeout=2) as r:
                        self.node_status = json.loads(r.read())
                    self._push_pending(h)
                except Exception as e:
                    self.node_status = None
                    self.status = 'cannot reach the DMX node on %s (%s)' % (h, e.__class__.__name__)
            time.sleep(3.0)

    def _push_pending(self, h):
        """Head settings waiting for the Zephyrus (setting 'heads_pending' = {"0": {...}}): sent as soon as the
        node answers, then cleared. Lets safety limits be set while the Zephyrus is asleep."""
        pend = dict(self.settings().get('heads_pending') or {})
        if not pend or not self.node_cfg:
            return
        done = []
        for k, vals in pend.items():
            i = int(k)
            if not 0 <= i < len(self.node_cfg.get('heads', [])) or not isinstance(vals, dict):
                done.append(k)
                continue
            rq = urllib.request.Request('http://%s:%d/head' % (self.ip or h, NODE_PORT),
                                        data=json.dumps(dict(vals, head=i)).encode(), headers={'Content-Type': 'text/plain'})
            with urllib.request.urlopen(rq, timeout=3) as r:
                self.node_cfg['heads'][i] = json.loads(r.read())
            done.append(k)
        if done:
            with self.hub.lock:
                left = {k: v for k, v in (self.settings().get('heads_pending') or {}).items() if k not in done}
                self.settings()['heads_pending'] = left
                self.hub.save_soon()

    def heads(self):
        hs = (self.node_cfg or {}).get('heads') or DEFAULT_HEADS
        while len(self.st) < len(hs):
            self.st.append(dict(theta=0.0, pan=None, lvl=0.0, flash=0.0))
        return hs

    @staticmethod
    def match(rgb, s):
        """COLOUR MATCH: lamp colours are gamma-encoded, the heads' LEDs are linear -- linearise, then
        balance the head's red/green/blue LEDs (settings dmx_gamma, dmx_gain) so a head looks like the bulbs."""
        try:
            gm = clamp(float(s.get('dmx_gamma', 2.2)), 1.0, 3.0)
            gain = [clamp(float(x), 0.0, 1.5) for x in (s.get('dmx_gain') or [1.0, 1.0, 1.0])][:3]
            if len(gain) < 3:
                gain = [1.0, 1.0, 1.0]
        except (TypeError, ValueError):
            gm, gain = 2.2, [1.0, 1.0, 1.0]
        out = [clamp(c) ** gm * k for c, k in zip(rgb, gain)]
        mx = max(out) or 1.0
        return tuple(x / mx for x in out)                     # brightness stays on the master channel

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
        movie = pmode == 'sync' or bool(s.get('movie'))
        dark = (self.hub.blackout or not cols or not s.get('dmx_on', True) or (movie and not s.get('dmx_movie', True)))
        level = clamp(float(s.get('dmx_level', 0.8))) * clamp(float(live.get('master', 1.0)))
        move = clamp(float(s.get('dmx_move', 1.0)))
        section = getattr(getattr(self.hub, 'audioshow', None), 'section', 'groove')
        spread = {'breakdown': 0.3, 'quiet': 0.45, 'groove': 0.75, 'drop': 1.0}.get(section, 0.75)
        tm = float(getattr(self.hub, 't_motion', beats / 4.0))
        # KICK LOCK: while kicks are coming in, the heads' motion steps one beat per kick (eased), so the
        # moves land on the music actually playing -- not on a clock that may be in another tempo.
        aus = getattr(self.hub, 'audioshow', None)
        kick = float((getattr(aus, 'env', None) or {}).get('kick', 0.0)) if aus is not None else 0.0
        if kick > 0.55 and self.k_prev <= 0.55 and now - self.k_last > 0.22:
            if now - self.k_last > 2.5:
                self.k_target = self.k_tm = tm               # (re)join from wherever the clock had them
            self.k_target += 1.0
            self.k_last = now
        self.k_prev = kick
        if s.get('dmx_kick_lock', True) and now - self.k_last < 2.5:
            self.k_tm += (self.k_target - self.k_tm) * (1 - math.exp(-dt / 0.12))
            tm = self.k_tm
        uni = clamp(float(s.get('dmx_unison', 0.8)))         # 1 = all heads move together, 0 = each its own phase
        # STROBE HITS: when a drop lands (+ each 4-bar phrase in it), only heads in the ceiling cone, max 3 a second
        cone = clamp(float(s.get('strobe_cone', 45.0)), 0.0, 45.0)
        smode = s.get('dmx_strobe', 'phrase')
        smode = 'phrase' if smode is True else 'off' if smode in (False, None) else str(smode)
        strobe_on = smode in ('phrase', 'drop') and section == 'drop' and not dark and not movie
        bpb = int(s.get('beats_per_bar', 4) or 4)
        phrase = int(math.floor(beats / (bpb * 4.0)))           # a 4-bar phrase
        landed = section == 'drop' and self.sec_prev != 'drop'
        new_phrase = self.phrase_prev is not None and phrase != self.phrase_prev
        fire = strobe_on and (landed or (smode == 'phrase' and new_phrase)) and now - self.last_flash >= 1.0 / 3.0 + 0.01
        self.sec_prev, self.phrase_prev = section, phrase
        if fire:
            self.last_flash = now
            self.flashes += 1
        # SWEEPS: a sudden jump in loudness swings the heads out and back -- movie: calm spot sweeps;
        # music: rapid sweeps, every head together, alternating direction
        sweep_e, sweep_kind, sweep_amp = 0.0, 0, 0.0
        if not dark:
            try:                                                 # the Scarlett's total sound (PlayStation in + the Mac's loopback)
                chr_ = dict(getattr(getattr(self.hub, 'audio', None), 'ch_rms', {}) or {})
                rms = math.sqrt(sum(float(v) ** 2 for v in chr_.values()))
            except (TypeError, ValueError):
                rms = 0.0
            db = 20.0 * math.log10(max(rms, 1e-6))
            lo, hi = ((float(s.get('sync_floor_db', -48.0)), float(s.get('sync_top_db', -12.0))) if movie else
                      (float(s.get('music_floor_db', -50.0)), float(s.get('music_top_db', -10.0))))
            lv_ = clamp((db - lo) / max(1.0, hi - lo))
            self.mv_fast += (lv_ - self.mv_fast) * (1 - math.exp(-dt / 0.08))
            self.mv_bri += (lv_ - self.mv_bri) * (1 - math.exp(-dt / (0.15 if lv_ > self.mv_bri else 0.8)))
            self.mv_slow += (lv_ - self.mv_slow) * (1 - math.exp(-dt / 1.5))
            sens = clamp(float(s.get('movie_sweep', 0.5) if movie else s.get('dmx_sweep', 0.6)))
            jump = self.mv_fast - self.mv_slow
            busy = now - self.sweep_t < ((3.7 if self.sweep_n % 3 == 2 else 2.5) if movie else 1.0)
            if sens > 0 and jump > 0.30 - 0.20 * sens and not busy:
                self.sweep_t, self.sweep_n = now, self.sweep_n + 1
                self.sweep_amp = clamp(0.45 + (jump - (0.30 - 0.20 * sens)) * 2.0, 0.45, 1.0)
            t_ = now - self.sweep_t
            sweep_kind, sweep_amp = self.sweep_n % 3, self.sweep_amp
            t_out, t_hold, t_back = ((1.3, 0.4, 2.0) if sweep_kind == 2 else (0.35, 0.3, 1.6)) if movie else (0.22, 0.12, 0.6)
            if t_ < t_out:
                sweep_e = t_ / t_out                             # out, fast
            elif t_ < t_out + t_hold:
                sweep_e = 1.0                                    # hold a beat
            elif t_ < t_out + t_hold + t_back:
                sweep_e = 0.5 + 0.5 * math.cos(math.pi * (t_ - t_out - t_hold) / t_back)   # ease back home
        else:
            self.mv_fast = self.mv_slow = self.mv_bri = 0.0
        spots = s.get('movie_spots') or {}
        data = bytearray(512)
        hs = self.heads()
        n = len(hs)
        for i, hd in enumerate(hs):
            st = self.st[i]
            # colour: a lamp spread across the room for each head
            src = cols[int(round(i * (1.0 - uni) * (len(cols) - 1) / max(1, n - 1)))] if cols else (0.0, 0.0, 0.0)
            hh, ss, vv = colorsys.rgb_to_hsv(*[clamp(x) for x in src])
            pf = getattr(self, 'proof', None)
            if pf is not None and s.get('dmx_proof', True) and vv > 0.004:
                try:                                            # the hue/saturation the Hue bulb really shows
                    hh, ss, _ = colorsys.rgb_to_hsv(*[clamp(x) for x in pf(tuple(clamp(x / vv) for x in src))])
                except Exception:
                    pass
            ss = max(ss, 0.55)                                  # never white
            r, g, b = self.match(colorsys.hsv_to_rgb(hh, ss, 1.0), s)
            w = (1.0 - ss) * 0.35
            # MOVIE: a soft ceiling wash in the lamps' colour (which follows the film's sound), slow and calm
            if dark:
                want = 0.0
            elif movie:                                          # MOVIE: brightness follows the film's loudness
                vol_k = clamp(float(s.get('movie_volume_bri', 0.85)))
                want = level * float(s.get('dmx_movie_level', 0.5)) * clamp(
                    (1.0 - vol_k) * vv + vol_k * (0.12 + 0.88 * self.mv_bri))
            else:
                want = vv * level
            k = 1 - math.exp(-dt / ((0.12 if want > st['lvl'] else 0.8) if movie else (0.06 if want > st['lvl'] else 0.25)))
            st['lvl'] += (want - st['lvl']) * k
            # movement: slow, beat-locked; lean only inside the calibrated window
            lean_max = clamp(float(hd.get('tilt_max_deg', 35.0)), 0.0, 60.0) * 0.95
            if dark:
                th_t = 0.0
            elif movie:
                th_t = min(lean_max, 6.0 + 5.0 * math.sin(now / 23.0 + i * 1.7))   # near-vertical: the ceiling, not the screen
            else:
                wave = 0.5 + 0.5 * math.sin(2 * math.pi * (tm / 8.0 + i * 0.3 * (1.0 - uni)))
                th_t = lean_max * move * spread * (0.35 + 0.65 * wave)
                if strobe_on:
                    th_t = min(th_t, cone * 0.8)                 # in drops, stay inside the strobe cone
                if st['pan'] is not None and in_avoid(hd, st['pan'], th_t, margin=30.0):   # starts rising 30 deg early
                    th_t = AVOID_LEAN * 0.9                      # facing the projection (etc.): stay near straight up
            spot = spots.get(str(i)) if isinstance(spots, dict) else None
            spot_p = None
            if movie and not dark and isinstance(spot, dict):
                try:                                             # MOVIE SPOT: hold the beam over one place (az = pan heading)
                    s_lean = min(lean_max, max(0.0, float(spot.get('lean', 30.0))))
                    home = float(spot.get('az', 45.0)) % 360.0
                    s_az, th_s = home, s_lean
                    far = abs(float(spot.get('sweep_deg', 40.0)))
                    if sweep_kind == 0:                          # dip toward straight up and back
                        th_s = s_lean * (1.0 - 0.6 * sweep_amp * sweep_e)
                    elif sweep_kind == 1:                        # quick swing toward the kitchen side
                        s_az = home - far * sweep_amp * sweep_e
                    else:                                        # CEILING SWEEP: along the ceiling toward the walls
                        c_lean = min(lean_max, float(spot.get('ceiling_lean', 25.0)))
                        end = home
                        for a_ in range(int(home) + 5, int(float(spot.get('wall_az', 225.0))) + 1, 5):
                            if in_avoid(hd, a_ / 540.0 * 65535.0, c_lean) or a_ / 540.0 * 65535.0 > int(hd.get('pan_max', 65535)):
                                break                            # stop where the zones say the screen starts
                            end = float(a_)
                        s_az = home + (end - home) * sweep_e
                        th_s = s_lean + (c_lean - s_lean) * min(1.0, sweep_e * 3.0)
                        far = max(far, end - home)
                    p16 = (s_az % 360.0) / 540.0 * 65535.0
                    if not in_avoid(hd, p16, th_s) and int(hd.get('pan_min', 0)) <= p16 <= int(hd.get('pan_max', 65535)):
                        th_t, spot_p = th_s, p16
                        home16 = home / 540.0 * 65535.0
                        reach = (far + 8.0) / 540.0 * 65535.0
                        if st['pan'] is not None and (abs(st['pan'] - home16) > reach or in_avoid(hd, st['pan'], th_s, margin=30.0)):
                            th_t = AVOID_LEAN * 0.9              # still turning toward the spot: travel upright
                except (TypeError, ValueError):
                    spot_p = None
            fast = spot_p is not None and sweep_e > 0.0
            mfast = (not movie) and sweep_e > 0.0                 # a music sweep is under way
            step = (MUSIC_SWEEP_DEG_S if mfast else SWEEP_DEG_S if fast else MAX_DEG_S) * dt
            st['theta'] += clamp(th_t - st['theta'], -step, step)
            pmin, pmax = int(hd.get('pan_min', 0)), int(hd.get('pan_max', 65535))
            if movie:
                u = 0.5 + 0.25 * math.sin(2 * math.pi * (now / 180.0 + i / 4.0))          # a very slow drift
            else:
                u = 0.5 + 0.5 * math.sin(2 * math.pi * (tm / 32.0 + i / 4.0 * (1.0 - uni))) * (move if not dark else 0.0)
            p_t = pmin + u * (pmax - pmin)
            if spot_p is not None:
                p_t = spot_p
            if mfast:                                            # music sweep: all heads swing the same way, then back
                sd = float(s.get('dmx_sweep_deg', 70.0)) * sweep_amp * sweep_e * (1.0 if self.sweep_n % 2 else -1.0)
                p_t = clamp(p_t + sd / 540.0 * 65535.0, pmin, pmax)
            if st['pan'] is None:
                st['pan'] = p_t
            pstep = (MUSIC_SWEEP_DEG_S if mfast else SWEEP_DEG_S if fast else MAX_DEG_S) / 540.0 * 65535.0 * dt
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
                r, g, b = self.match(colorsys.hsv_to_rgb(hh, max(ss, 0.7), 1.0), s)
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
                self.status = 'sending to %s (%s) -- %s, %d of %d heads calibrated%s' % (
                    h, self.ip, ns.get('output', '?'), ready, len(ns.get('heads', [])), (' -- ' + ns['error']) if ns.get('error') else '')
            elif not self.status.startswith('cannot'):
                self.status = 'sending to %s' % h
        except Exception as e:
            self.status = 'cannot send to %s (%s)' % (h, e)

    def describe(self):
        return self.status
