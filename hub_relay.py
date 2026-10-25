# =============================================================================
# HUE HUB -- the relay: the show's MIDI goes out to the Zephyrus
#
# The Zephyrus (3D + AI render box) listens to the same MIDI that already runs
# the show, over the network: the Mac's "Show" session (Audio MIDI Setup >
# MIDI Network Setup), which rtpMIDI on the Zephyrus connects to.
#
# What goes out on the "Show" session:
#   ch 1   the notes you play (Note Colours track)          straight through from the IAC bus
#   ch 2   chords the audio brain hears in the mix           straight through from the IAC bus
#   ch 16  VJ pads (VJ track)                                straight through from the IAC bus
#   (every other channel on the IAC bus goes through too -- except ch 15, which is the relay's own)
#   CLOCK  start / stop / continue / song position / 24 ticks a beat
#          from the Digitakt (through the Scarlett) while it runs; Ableton's clock on the IAC bus
#          (if Live sends one) only when the Digitakt's is silent -- never both at once
#   ch 15  the show's STATE as controllers, ~30 times a second (only what changed, everything every 2 s):
#          CC 1  degree colour 1-8 (1 red ... 7 violet, 8 = the octave: rainbow; in-between notes = the lower step)
#          CC 2  geometry family 0-7 (VJ board row: flower, metatron, yantra, golden, tesseract, chladni,
#                quasicrystal, mandala)
#          CC 3  construction 0-7 (VJ board column)
#          CC 4  kick (envelope, 0-127)          CC 5  loudness (0-127)
#          CC 6  build progress (0-127)          CC 7  diffuse amount (0-127)
#          CC 8  brightness / master (0-127, 0 in blackout)
#          CC 9  look (0 clean, 1 ASCII, 2 8-bit, 3 outline, 4 superflat, 5 mirror) -- only once
#                TouchDesigner tells the hub (see VJ_FEED below); until then it isn't sent
#          CC 10 lighting effect (0 wash, 1 glow, 2 pulse, 3 chase, 4 sparkle, 5 sweep, 6 hit)
#
# Kick, loudness and brightness are the values AFTER the flicker protection (the same ones TouchDesigner
# gets), so nothing downstream can be driven faster than the Flicker Guard. The Zephyrus's picture comes
# back to the Mac over NDI and through the flicker-safe pass anyway.
#
# Build progress / diffuse: TouchDesigner's VJ board owns these. Until it sends them to the hub
# (VJ_FEED), the relay works them out the same way, from the VJ pad, the tempo and the board's
# default times (build 1 bar, then diffuse 0.6 over 4 bars) -- desk > Setup > Zephyrus relay.
#
# VJ_FEED (optional, for later): if TouchDesigner's hue_feed adds
#     "vj": {"family": 0-7, "construction": 0-7, "build": 0-1, "diffuse": 0-1, "look": "ascii"}
# to what it already sends the hub, the relay uses those exact values instead of working them out.
#
# The relay only SENDS on "Show" and only LISTENS to the IAC bus and the Scarlett -- it never listens to
# "Show", so nothing can loop. It opens its own connections (with callbacks, so the clock goes out the
# moment it arrives, not once a frame); the hub's own IAC / Scarlett listeners are untouched.
# =============================================================================

import math
import threading
import time

import mido

STATE_CH = 14                       # mido counts from 0: 14 = MIDI channel 15
VJ_CH = 15                          # MIDI channel 16
LOOKS = ['clean', 'ascii', '8bit', 'outline', 'superflat', 'mirror']
EFFECTS = ['wash', 'glow', 'pulse', 'chase', 'sparkle', 'sweep', 'hit']
CHANNEL_TYPES = ('note_on', 'note_off', 'control_change', 'polytouch', 'aftertouch', 'pitchwheel', 'program_change')
CLOCK_TYPES = ('clock', 'start', 'stop', 'continue', 'songpos')
RATE = 30.0                         # state controllers per second (at most)
REFRESH = 2.0                       # everything again every 2 s (for a Zephyrus that just connected)


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _cc(x):
    """0-1 -> 0-127"""
    return int(round(_clamp(float(x)) * 127))


def _call(fn, timeout=3.0):
    try:
        from hub_audio import midi_call
    except Exception:
        return fn()
    return midi_call(fn, timeout=timeout)


class Relay:
    def __init__(self, hub):
        self.hub = hub
        self.lock = threading.Lock()
        self.out = None
        self.out_name = None
        self.ins = {}                   # 'iac' / 'gear' -> (name, port)
        self.status = 'starting'
        self.last_try = -100.0
        self.sent = {}                  # cc -> last value sent
        self.sent_t = 0.0
        self.full_t = 0.0
        self.gear_clk_t = -100.0        # the Digitakt's clock last arrived (it wins over Ableton's)
        self.counts = dict(notes=0, vj=0, clock=0, state=0)
        self.recipe = None              # (family, construction, time the VJ pad was hit)
        self.err = ''
        self.open()

    def settings(self):
        return self.hub.state['settings']

    # ------------------------------------------------------------ ports
    def open(self):
        self.last_try = time.time()
        st = self.settings()
        if not st.get('relay_on', True):
            self.status = 'off (desk > Setup > Zephyrus relay)'
            return
        want = str(st.get('relay_port', 'Show')).lower().strip() or 'show'
        try:
            outs = _call(mido.get_output_names)
            ins = _call(mido.get_input_names)
        except Exception as e:
            self.status = 'MIDI not available (%s)' % e
            return
        if self.out is None:
            names = [n for n in outs if want in n.lower() and 'iac' not in n.lower() and 'push' not in n.lower()]
            if not names:
                self.status = ('no "%s" network session (Mac: Audio MIDI Setup > MIDI Studio > Network > '
                               'My Sessions "Show", Enabled)' % st.get('relay_port', 'Show'))
                return
            try:
                self.out = _call(lambda: mido.open_output(names[0]))
                self.out_name = names[0]
                self.sent, self.full_t = {}, 0.0
            except Exception as e:
                self.out = None
                self.status = 'could not open "%s" (%s)' % (names[0], e)
                return
        # what it listens to: the IAC bus (Live's notes + VJ pads + heard chords), the Scarlett (Digitakt clock)
        for key, sub, cb in (('iac', str(st.get('iac_port', 'IAC')), self._from_iac),
                             ('gear', str(st.get('trig_port', 'Scarlett')), self._from_gear)):
            if key in self.ins or not sub.strip():
                continue
            names = [n for n in ins if sub.lower() in n.lower() and 'push' not in n.lower()
                     and want not in n.lower()]
            if names:
                try:
                    self.ins[key] = (names[0], _call(lambda n=names[0], c=cb: mido.open_input(n, callback=c)))
                except Exception as e:
                    self.err = 'could not listen to "%s" (%s)' % (names[0], e)
        self.status = 'sending to "%s"' % self.out_name

    def close(self):
        for key, (name, port) in list(self.ins.items()):
            try:
                port.close()
            except Exception:
                pass
        self.ins = {}
        with self.lock:
            try:
                if self.out is not None:
                    self.out.reset()             # all notes off on the Zephyrus
                    self.out.close()
            except Exception:
                pass
            self.out = None

    def _send(self, msg):
        with self.lock:
            if self.out is None:
                return False
            try:
                self.out.send(msg)
                return True
            except Exception as e:
                self.out = None
                self.status = 'lost "%s" (%s)' % (self.out_name, e)
                return False

    # ------------------------------------------------------------ straight through (MIDI's own thread)
    def _from_iac(self, msg):
        t = msg.type
        if t in CHANNEL_TYPES:
            if msg.channel == STATE_CH:
                return                          # ch 15 is the relay's own
            if msg.channel == VJ_CH and t == 'note_on' and msg.velocity > 0:
                self._vj_pad(msg.note)
            if self._send(msg) and t == 'note_on' and msg.velocity > 0:
                self.counts['vj' if msg.channel == VJ_CH else 'notes'] += 1
        elif t in CLOCK_TYPES and time.time() - self.gear_clk_t > 0.5:
            if self._send(msg) and t == 'clock':     # Ableton's clock, only while the Digitakt's is silent
                self.counts['clock'] += 1

    def _from_gear(self, msg):
        if msg.type in CLOCK_TYPES:              # the Digitakt's notes are drum triggers: they stay on the Mac
            if msg.type == 'clock':
                self.gear_clk_t = time.time()
            if self._send(msg) and msg.type == 'clock':
                self.counts['clock'] += 1

    def _vj_pad(self, note):
        if self.settings().get('vj_keypads', False) or not 36 <= note <= 99:
            return                              # (key pads, not a recipe)
        r = (note - 36) % 64                     # row = family, column = construction (as the VJ board does it
        self.recipe = (r // 8, r % 8, time.time())   # when it can't see Push's own pad)

    # ------------------------------------------------------------ the show's state on ch 15 (hub thread)
    def state(self, now):
        h = self.hub
        st = self.settings()
        cc = {}
        lm = h.ableton
        ld = getattr(lm, 'last_degree', None) if lm is not None else None
        if ld is not None:
            cc[1] = max(1, min(8, int(math.floor(ld))))
        vj = h.feed.get('vj') if now - h.feed.get('vj_t', -100.0) < 1.0 else None
        if vj:                                   # TouchDesigner's own values (VJ_FEED)
            for k, n in (('family', 2), ('construction', 3)):
                if vj.get(k) is not None:
                    cc[n] = int(vj[k]) % 8
            if vj.get('build') is not None:
                cc[6] = _cc(vj['build'])
            if vj.get('diffuse') is not None:
                cc[7] = _cc(vj['diffuse'])
            if vj.get('look') in LOOKS:
                cc[9] = LOOKS.index(vj['look'])
        elif self.recipe is not None:            # worked out the way the VJ board does it
            fam, con, t0 = self.recipe
            cc[2], cc[3] = fam, con
            bar = 4.0 * 60.0 / max(40.0, float(h.clock[1] or 120.0))
            bb = max(0.05, float(st.get('relay_build_bars', 1.0)) * bar)
            db = max(0.05, float(st.get('relay_diffuse_bars', 4.0)) * bar)
            build = _clamp((now - t0) / bb)
            cc[6] = _cc(build)
            cc[7] = _cc(float(st.get('relay_diffuse', 0.6)) * _clamp((now - t0 - bb) / db))
        m = getattr(h, 'td_msg', None)           # after the flicker protection (hub_visuals)
        if m:
            cc[4] = _cc(m.get('akick', 0.0))
            cc[5] = _cc(m.get('alevel', 0.0))
            cc[8] = _cc(m.get('master', 1.0))
        else:
            cc[8] = 0 if h.blackout else _cc(h.live.get('master', 1.0))
        eff = st.get('deg_effect', 'wash')
        cc[10] = EFFECTS.index(eff) if eff in EFFECTS else 0
        return cc

    def poll(self, now):
        st = self.settings()
        if not st.get('relay_on', True):
            if self.out is not None or self.ins:
                self.close()
            self.status = 'off (desk > Setup > Zephyrus relay)'
            return
        if self.out is None or len(self.ins) < 2:
            if now - self.last_try > (3.0 if self.out is None else 10.0):   # a missing listener: look now and then
                self.open()
            if self.out is None:
                return
        if now - self.sent_t < 1.0 / RATE:
            return
        self.sent_t = now
        full = now - self.full_t > REFRESH
        if full:
            self.full_t = now
        try:
            with self.hub.lock:
                cc = self.state(now)
        except Exception as e:
            self.err = 'state: %s' % e
            return
        for n, v in sorted(cc.items()):
            if full or self.sent.get(n) != v:
                if self._send(mido.Message('control_change', channel=STATE_CH, control=n, value=int(v))):
                    self.sent[n] = v
                    self.counts['state'] += 1

    def describe(self):
        s = self.status
        if self.out is not None:
            lis = ', '.join('%s "%s"' % (k, n) for k, (n, _) in sorted(self.ins.items())) or 'nothing yet'
            c = self.counts
            s += ' -- from %s -- %d notes, %d VJ pads, %d clock ticks, %d state messages so far' % (
                lis, c['notes'], c['vj'], c['clock'], c['state'])
            if time.time() - self.gear_clk_t < 0.5:
                s += ' -- clock: Digitakt'
        if self.err:
            s += ' -- ' + self.err
        return s
