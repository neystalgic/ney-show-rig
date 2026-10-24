# =============================================================================
# HUE HUB -- Ableton plays the lights (through the Mac's IAC Driver)
#
# Keep Push 2 in Live mode -- scenes, clips, Expressive Chords, everything --
# and send Live's MIDI to the hub through an IAC bus. Every note is played
# through the SAME pad data as Push's User mode (colour, effect, geometry,
# latch, flicker protection):
#
#   "Same as the pads"   note number = the pad that sends that note in User
#                        mode (36-99; notes outside are folded in by octaves)
#   "Notes -> colours"   pitch picks the colour (C red, D orange, E green,
#                        G blue, A violet ...), the octave picks the row, so
#                        low notes = flower of life, high notes = tesseract /
#                        the blend
#
#   velocity           = brightness          pressure (poly / MPE) = pressure
#   pitch bend         = bends the colour    all notes off (Live stop) = pads off
#   program change N   = plays look N (put a program change on a clip, so a
#                        scene launch changes the look too)
#
# Setup in Live: a MIDI track, MIDI From = the track you play (or any track),
# MIDI To = IAC Driver, Monitor = In. Clips launched from scenes come through
# too. Push 2's User mode keeps working exactly as before.
# =============================================================================

import time

import mido

WHEEL = [0, 1, 1, 2, 3, 3, 4, 5, 5, 6, 7, 7]      # pitch class -> colour column (red ... pink)

# ---- "Degrees -> colours" (iac_map = 'degree'): every note takes the colour of its step in the key
#   1 red  2 orange  3 yellow  4 green  5 blue  6 indigo  7 violet,  the 1 an octave up (or higher) = rainbow
#   notes outside the scale = halfway between their two neighbours
# The VJ track (MIDI channel 16, a Drum Rack) sets the key: notes 68-79 = C ... B, 80-83 = major / minor /
# dorian / mixolydian (third bank of 16 pads). The rest of channel 16 is the VJ board (TouchDesigner reads it).
VJ_CH = 15                                          # mido counts channels from 0: 15 = MIDI channel 16
HEARD_CH = 1                                        # MIDI channel 2: chords the audio brain hears in the mix
HEARD_HOLD = 6.0                                    # after you play a note, heard chords wait this long
KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
SCALES = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10],
          'dorian': [0, 2, 3, 5, 7, 9, 10], 'mixolydian': [0, 2, 4, 5, 7, 9, 10]}
SCALE_PADS = ['major', 'minor', 'dorian', 'mixolydian']
DEG_RGB = [(1.0, 0.0, 0.0), (1.0, 0.35, 0.0), (1.0, 0.85, 0.0), (0.0, 1.0, 0.1), (0.0, 0.3, 1.0),
           (0.29, 0.0, 1.0), (0.62, 0.0, 1.0)]
DEG_NAMES = ['red', 'orange', 'yellow', 'green', 'blue', 'indigo', 'violet']
DEG_EFFECTS = ['wash', 'glow', 'hit', 'pulse', 'chase', 'sparkle', 'sweep']   # = the pad rows in hub_pads


def degree_of(note, root, scale):
    """(step 0-6, between 0 / 0.5) of a MIDI note in the key (any of Live's scales)."""
    iv = (note - root) % 12
    try:
        from hub_liveosc import scale_steps
        sc = scale_steps(scale)
    except Exception:
        sc = SCALES.get(scale, SCALES['major'])
    if iv in sc:
        return sc.index(iv), 0.0
    return max(k for k, x in enumerate(sc) if x < iv), 0.5


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class LiveMidi:
    def __init__(self, hub):
        self.hub = hub
        self.inp = None
        self.name = None
        self.status = 'looking for the IAC Driver'
        self.last_try = 0.0
        self.held = {}            # (channel, note) -> pad note
        self.out = None           # IAC output: the audio brain's heard chords go out on channel 2
        self.heard_note = None
        self.last_played = -100.0
        self.notes = 0
        self.last_note = None
        self.open()

    def settings(self):
        return self.hub.state['settings']

    def open(self):
        self.last_try = time.time()
        if not self.settings().get('iac_on', True):
            self.status = 'off (desk > Setup > Ableton)'
            return
        want = str(self.settings().get('iac_port', 'IAC')).lower()
        try:
            from hub_audio import midi_call
        except Exception:
            midi_call = lambda fn, *a, **k: fn(*a)
        try:
            names = [n for n in midi_call(mido.get_input_names) if want in n.lower() and 'push' not in n.lower()]
        except Exception as e:
            self.status = 'MIDI not available (%s)' % e
            return
        if not names:
            self.status = 'no IAC Driver bus found (Audio MIDI Setup > IAC Driver > Device is online)'
            return
        try:
            self.inp = midi_call(mido.open_input, names[0])
            self.name = names[0]
            self.status = 'listening to "%s"' % names[0]
        except Exception as e:
            self.inp = None
            self.status = 'could not open "%s" (%s)' % (names[0], e)

    def close(self):
        try:
            if self.inp:
                self.inp.close()
        except Exception:
            pass
        self.inp = None
        try:
            if self.out:
                self.out.close()
        except Exception:
            pass
        self.out = None

    # ------------------------------------------------------------ the audio brain's chords -> MIDI
    def send_heard(self, root, minor=False, strength=0.0):
        """A steady chord heard in the music -> note on IAC channel 2 (root, C2-B2 so never the rainbow).
        Everything that listens to the show's MIDI (hub, TouchDesigner, the Zephyrus) treats it like a
        played note -- but notes you actually play win for HEARD_HOLD seconds."""
        if not self.settings().get('heard_on', True) or self.name is None:
            return
        try:
            from hub_audio import midi_call
        except Exception:
            midi_call = lambda fn, *a, **k: fn(*a)
        try:
            if self.out is None:
                self.out = midi_call(mido.open_output, self.name)
            if self.heard_note is not None:
                self.out.send(mido.Message('note_off', channel=HEARD_CH, note=self.heard_note, velocity=0))
            n = 48 + int(root) % 12
            self.out.send(mido.Message('note_on', channel=HEARD_CH, note=n, velocity=int(40 + 60 * max(0.0, min(1.0, strength)))))
            self.heard_note = n
        except Exception as e:
            self.out = None
            self.status_heard = 'could not send heard chords (%s)' % e

    def poll(self):
        if self.inp is None:
            if time.time() - self.last_try > 3.0:
                self.open()
            return
        if not self.settings().get('iac_on', True):
            self.release_all()
            self.close()
            self.status = 'off (desk > Setup > Ableton)'
            return
        try:
            for msg in self.inp.iter_pending():
                self.handle(msg)
        except Exception as e:
            self.status = 'lost the IAC Driver (%s)' % e
            self.close()

    # ------------------------------------------------------------ notes -> pads
    def pad_for(self, note):
        if self.settings().get('iac_map', 'pads') == 'wheel':
            row = max(0, min(7, note // 12 - 2))        # C1-B1 -> row 1 ... C8 and up -> top row
            return 36 + row * 8 + WHEEL[note % 12]
        while note < 36:
            note += 12
        while note > 99:
            note -= 12
        return note

    def release_all(self):
        h = self.hub
        now = time.time()
        with h.lock:
            for p in set(self.held.values()):
                h.pads.note_off(p, now)
        self.held.clear()

    # ------------------------------------------------------------ degrees -> colours
    def key(self):
        st = self.settings()
        return int(st.get('deg_root', 0)) % 12, st.get('deg_scale', 'major'), int(st.get('deg_home', 60))

    def degree_pad(self, note):
        """The pad (and exact colour) for a note in 'degree' mode."""
        root, scale, home = self.key()
        d, half = degree_of(note, root, scale)
        home_root = home + ((root - home) % 12)
        if d == 0 and half == 0.0 and note >= home_root + 12:
            self.last_degree = 8
            self.deg_rgb = None                         # rainbow: the pad's own multi-colour effect shows
            return 92, None                             # the octave: rainbow (top row, first pad)
        d = d % 7                                       # scales with 8 notes: the 8th wraps to red
        rgb = DEG_RGB[d] if half == 0.0 else _mix(DEG_RGB[d], DEG_RGB[(d + 1) % 7], 0.5)
        self.last_degree = d + 1 + half
        self.deg_rgb = rgb                              # the hub lays this colour over the whole room
        row = DEG_EFFECTS.index(self.settings().get('deg_effect', 'wash')) if self.settings().get(
            'deg_effect', 'wash') in DEG_EFFECTS else 0
        return 36 + row * 8 + d, rgb                    # the row picks the effect (wash, glow, pulse ...)

    def handle_vj(self, msg):
        if msg.type == 'note_on' and msg.velocity > 0:
            st = self.settings()
            if not st.get('vj_keypads', False):         # the 64 pads are geometry recipes now: key comes from the desk
                return
            if 68 <= msg.note <= 79:
                st['deg_root'] = msg.note - 68
            elif 80 <= msg.note <= 83:
                st['deg_scale'] = SCALE_PADS[msg.note - 80]
            else:
                return
            try:
                self.hub.save_soon()
            except Exception:
                pass

    def handle(self, msg):
        h = self.hub
        now = time.time()
        t = msg.type
        if (getattr(msg, 'channel', 0) == VJ_CH and self.settings().get('vj_keypads', False)
                and t in ('note_on', 'note_off', 'control_change', 'polytouch')):
            return self.handle_vj(msg)
        # (otherwise the VJ track's notes colour the room by their step in the key, like any other notes)
        ch_ = getattr(msg, 'channel', 0)
        if t == 'note_on' and msg.velocity > 0:
            if ch_ == HEARD_CH:
                if time.time() - self.last_played < HEARD_HOLD:
                    return                              # you're playing: your notes set the colour
            else:
                self.last_played = time.time()
            rgb = None
            if self.settings().get('iac_map', 'pads') == 'degree':
                p, rgb = self.degree_pad(msg.note)
            else:
                p = self.pad_for(msg.note)
            self.held[(getattr(msg, 'channel', 0), msg.note)] = p
            with h.lock:
                h.pads.note_on(p, msg.velocity, now, h.clock[0])
                v = h.pads.voices.get(p)
                if v is not None and rgb is not None:
                    v.rgb = rgb
            self.notes += 1
            self.last_note = (msg.note, p)
        elif t in ('note_off', 'note_on'):
            p = self.held.pop((getattr(msg, 'channel', 0), msg.note), None)
            if p is not None and p not in self.held.values():
                with h.lock:
                    h.pads.note_off(p, now)
        elif t == 'polytouch':
            p = self.held.get((getattr(msg, 'channel', 0), msg.note))
            if p is not None:
                h.pads.pressure(msg.value, p)
        elif t == 'aftertouch':                      # MPE: one channel per note
            ps = [p for (ch, n), p in self.held.items() if ch == getattr(msg, 'channel', 0)]
            if ps and self.settings().get('iac_mpe', True):
                for p in ps:
                    h.pads.pressure(msg.value, p)
            else:
                h.pads.pressure(msg.value)
        elif t == 'pitchwheel':
            h.pads.pitch(msg.pitch)
        elif t == 'program_change' and self.settings().get('iac_looks', True):
            looks = h.state['looks']
            if looks:
                h.go(looks[msg.program % len(looks)]['id'])
        elif t == 'control_change' and msg.control in (120, 123):
            self.release_all()                       # Live's stop / all notes off
        elif t == 'stop':
            self.release_all()

    def describe(self):
        s = self.status
        if self.settings().get('iac_map', 'pads') == 'degree':
            root, scale, _ = self.key()
            s += ' -- key %s %s' % (KEY_NAMES[root], scale)
            ld = getattr(self, 'last_degree', None)
            if ld is not None:
                s += ', last note: %s' % ('8 (rainbow)' if ld == 8 else (
                    '%d (%s)' % (ld, DEG_NAMES[int(ld) - 1]) if ld == int(ld) else 'between %d and %d' % (int(ld), int(ld) % 7 + 1)))
        if self.inp is not None and self.notes:
            s += ' -- %d notes so far' % self.notes
        return s
