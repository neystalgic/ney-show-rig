# =============================================================================
# HUE HUB -- Push 2 control
#
# Uses Push 2's USER mode, so Ableton keeps its own Push setup: press USER on
# Push 2 to play the lights, press it again to go back to Live.
#
# Three pad modes (the playing look is always what you're shaping):
#   (PLAY mode is on when Push connects)
#   SESSION button  LOOKS mode   top 6 rows = looks 1-48 (playing one = white)
#                                bottom 2 rows = song sections (go there next bar)
#   NOTE button     PLAY mode    all 64 pads are colours x effects you play live,
#                                with velocity, pressure and the touch strip
#                                (see hub_pads.py for the layout)
#   LAYOUT button   PAINT mode   top 6 rows = every lamp / colour zone, in the
#                                room's order (lit in its colour; bright = selected,
#                                tap to select, SELECT = all / none)
#                                bottom 2 rows = 16 colours: tap to paint the
#                                selected zones (nothing selected = all of them)
#   SCALE button    GEOMETRY mode  sacred geometry you play live:
#                                columns = golden, flower, yantra, metatron,
#                                chladni, spiral, cube, tesseract
#                                rows (bottom to top) = white light, golden,
#                                triad, hexad, opposite, warm, cool, fibonacci
#                                pressure = the shape grows, touch strip = spins it
#                                the buttons below the display set the PLAYING
#                                look to these forms
#
# Row of buttons BELOW the display = pattern:
#   still  breathe  pulse  chase  wave  sparkle  drift  rainbow
# Row of buttons ABOVE the display = speed (and two extras):
#   4 bars  2 bars  1 bar  2 beats  1 beat  1/2 beat  picture  wall hits on/off
#
# Knobs 1-8:
#   1 Master   2 Colour   3 Vibrance   4 Brightness   5 Movement   6 Together
#   7 Speed    8 Smoothing
#   PLAY mode: 1 Master 2 Colour 3 Vibrance 4 Pad level 5 Attack 6 Release 7 Pad speed 8 Spread
#   In LOOKS mode Colour / Vibrance turn the whole room's colours (live).
#   In PAINT mode Colour / Vibrance / Brightness change the SELECTED zones' paint.
# Master knob = Master,  Tempo knob = Look fade,  Swing knob = Flicker Guard
#
# Buttons: Left / Right arrows = previous / next look   New = copy the playing look
#   Tap Tempo = tap   Metronome = hold   Mute = blackout   Accent = hit
#   Play = start / stop the song   Record = "now is beat 1"
#   Delete = all pads off (the last pad you pushed stays on -- latched -- until
#   you push another pad, or press Delete)
#
# Needs (Terminal, once):   python3 -m pip install --user mido python-rtmidi
# =============================================================================

import colorsys
import time

import mido                                     # ImportError -> the hub runs without Push

import hub_geometry as geo
import hub_pads

MOTION_BUTTONS = {20: 'still', 21: 'breathe', 22: 'pulse', 23: 'chase', 24: 'wave', 25: 'sparkle',
                  26: 'drift', 27: 'rainbow'}
SPEED_BUTTONS = {102: 1 / 16.0, 103: 1 / 8.0, 104: 0.25, 105: 0.5, 106: 1.0, 107: 2.0}
PICTURE_BUTTON, WALLHITS_BUTTON = 108, 109
SESSION, NOTE, SELECT, LEFT, RIGHT, NEW, LAYOUT = 51, 50, 48, 44, 45, 87, 31
ROW_BRIGHT = [1.0] * 8                                           # PLAY mode: every pad shows its true colour
SIMPLE_BUTTONS = {3: 'tap', 9: 'hold', 60: 'blackout', 57: 'hit', 86: 'downbeat'}
PLAY = 85
SCALE = 58
DELETE = 118
GEO_BUTTONS = dict(zip(range(20, 28), geo.GEO_COLUMNS))      # GEOMETRY mode: buttons below = forms
GEO_COLOURS = {'golden': (255, 190, 40), 'flower': (255, 120, 200), 'yantra': (255, 60, 20),
               'metatron': (120, 160, 255), 'chladni': (40, 230, 200), 'spiral': (200, 255, 60),
               'cube': (160, 80, 255), 'tesseract': (255, 255, 255)}

SWATCHES = ['#ff0000', '#ff5a00', '#ffb000', '#ffe600', '#7dff00', '#00ff2a', '#00ffb4', '#00d2ff',
            '#005aff', '#3c00ff', '#8c00ff', '#e100ff', '#ff3ca0', '#ffbf73', '#ffffff', '#000000']
MOTION_COLOURS = {'still': (255, 190, 110), 'breathe': (255, 140, 60), 'pulse': (255, 40, 40),
                  'chase': (40, 220, 200), 'wave': (40, 120, 255), 'sparkle': (255, 255, 255),
                  'drift': (180, 80, 255), 'rainbow': (255, 60, 200)}
WHITE, DIM = 127, 126
P_TOP, P_BOTTOM, P_MOTION, P_SPEED = 1, 49, 70, 80     # palette slots


def _hex(h):
    h = (h or '#000000').lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (0, 0, 0)


def _hexs(c):
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(v)))) for v in c)


class Push2:
    def __init__(self, hub):
        self.hub = hub
        self.inp = self.out = None
        self.mode = 'play'                # the 64-pad light instrument is ready as soon as you press User
        self.sel = set()                  # selected zone keys (paint mode)
        self.status = 'not found (plug in Push 2)'
        self.last_try = 0.0
        self.last_refresh = 0.0
        self.palette, self.sent, self.btn = {}, {}, {}
        self.play_held = set()
        self.power = None                 # 'external' / 'usb' (from Push's own statistics)
        self.open()

    # ---------------------------------------------------------------- ports
    def open(self):
        self.last_try = time.time()
        try:
            ins = [n for n in mido.get_input_names() if 'Push 2' in n and 'User' in n]
            outs = [n for n in mido.get_output_names() if 'Push 2' in n and 'User' in n]
        except Exception as e:
            self.status = 'MIDI not available (%s)' % e
            return
        if not ins or not outs:
            self.status = 'not found (plug in Push 2)'
            return
        try:
            self.inp = mido.open_input(ins[0])
            self.out = mido.open_output(outs[0])
            # full LED brightness (Push limits it to 8 of 127 when it's powered only by USB),
            # and pressure per pad instead of one pressure for all pads
            self.out.send(mido.Message('sysex', data=[0x00, 0x21, 0x1D, 0x01, 0x01, 0x06, 127]))
            self.out.send(mido.Message('sysex', data=[0x00, 0x21, 0x1D, 0x01, 0x01, 0x1E, 0x01]))
            # ask whether it has its power supply (manual: 0x1A Request Statistics, reply byte 1 = external)
            self.out.send(mido.Message('sysex', data=[0x00, 0x21, 0x1D, 0x01, 0x01, 0x1A, 0x00]))
            self.palette, self.sent, self.btn = {}, {}, {}
            self.set_status()
            self.refresh(force=True)
        except Exception as e:
            self.inp = self.out = None
            self.status = 'could not open (%s)' % e

    def power_note(self):
        if self.power == 'usb':
            return ' -- USB POWER ONLY: plug in the power supply (LEDs are dimmed, colours are off)'
        return ''

    def set_status(self):
        if self.out is None:
            return
        self._set_status()
        self.status += self.power_note()

    def _set_status(self):
        if self.mode == 'play':
            held = self.hub.pads.describe()
            self.status = 'connected -- PLAY mode' + (' -- ' + held if held else '')
            return
        if self.mode == 'geo':
            held = self.hub.pads.describe()
            self.status = 'connected -- GEOMETRY mode' + (' -- ' + held if held else '')
            return
        if self.mode == 'paint':
            n = len(self.sel)
            self.status = 'connected -- PAINT mode, %s selected' % ('%d zone%s' % (n, '' if n == 1 else 's') if n else 'nothing')
        else:
            self.status = 'connected -- LOOKS mode (press User on Push 2)'

    def close(self):
        try:
            if self.out:
                for n in range(36, 100):
                    self.out.send(mido.Message('note_on', note=n, velocity=0))
                self.out.close()
            if self.inp:
                self.inp.close()
        except Exception:
            pass
        self.inp = self.out = None

    def poll(self):
        if self.inp is None:
            if time.time() - self.last_try > 3.0:
                self.open()
            return
        try:
            for msg in self.inp.iter_pending():
                self.handle(msg)
        except Exception as e:
            self.status = 'lost Push 2 (%s)' % e
            self.close()
            return
        every = 0.05 if self.mode == 'paint' else 1.0     # PAINT mode mirrors the lamps live
        if time.time() - self.last_refresh > every:
            self.refresh()

    # ---------------------------------------------------------------- helpers
    def looks(self):
        return self.hub.state['looks'][:48]

    def playing(self):
        return self.hub.look(self.hub.active)

    def zones(self):
        segs = sorted(self.hub.rig.segs, key=lambda s: s['rank'])
        return segs[:48]

    def song_sections(self):
        h = self.hub
        song = h.song_obj(h.song['id']) if h.song else (h.state['songs'][0] if h.state['songs'] else None)
        return song, (sorted(song['sections'], key=lambda s: s['bar'])[:16] if song else [])

    def save_look(self, lk):
        self.hub.command({'op': 'look.save', 'look': lk})

    def zone_colour(self, lk, key):
        return (lk.get('canvas', {}).get(key) or lk.get('fill') or '#ffffff')

    def adjust_zones(self, fn):
        """Change the paint of the selected zones (or all) of the playing look."""
        lk = self.playing()
        if not lk:
            return
        keys = list(self.sel) or [s['key'] for s in self.hub.rig.segs]
        for k in keys:
            r, g, b = (v / 255.0 for v in _hex(self.zone_colour(lk, k)))
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            h, s, v = fn(h, s, v)
            lk['canvas'][k] = _hexs([x * 255 for x in colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v)))])
        self.save_look(lk)

    # ---------------------------------------------------------------- input
    def handle(self, msg):
        h = self.hub
        if msg.type == 'sysex':
            d = list(msg.data)
            if d[:6] == [0x00, 0x21, 0x1D, 0x01, 0x01, 0x1A] and len(d) > 6:
                self.power = 'external' if d[6] == 1 else 'usb'
                self.set_status()
            return
        if msg.type == 'pitchwheel':
            h.pads.pitch(msg.pitch)
            return
        if self.mode in ('play', 'geo'):
            off = hub_pads.GEO_OFFSET if self.mode == 'geo' else 0
            if msg.type in ('note_on', 'note_off') and 36 <= msg.note <= 99:
                now = time.time()
                with h.lock:
                    if msg.type == 'note_on' and msg.velocity > 0:
                        h.pads.note_on(msg.note + off, msg.velocity, now, h.clock[0])
                    else:
                        h.pads.note_off(msg.note + off, now)
                self.set_status()
                self.pad_feedback()
                return
            if msg.type == 'polytouch' and 36 <= msg.note <= 99:
                h.pads.pressure(msg.value, msg.note + off)
                return
            if msg.type == 'aftertouch':
                h.pads.pressure(msg.value)
                return
        if msg.type == 'note_on' and msg.velocity > 0 and 36 <= msg.note <= 99:
            row, col = (msg.note - 36) // 8, (msg.note - 36) % 8      # row 0 = bottom
            top_i = (7 - row) * 8 + col
            bot_i = (1 - row) * 8 + col
            if self.mode == 'paint':
                if row >= 2:
                    zs = self.zones()
                    if top_i < len(zs):
                        k = zs[top_i]['key']
                        self.sel.symmetric_difference_update({k})
                else:
                    if bot_i < len(SWATCHES):
                        lk = self.playing()
                        keys = list(self.sel) or [s['key'] for s in h.rig.segs]
                        h.command({'op': 'paint', 'look': lk['id'], 'keys': keys, 'color': SWATCHES[bot_i]})
            else:
                if row >= 2:
                    looks = self.looks()
                    if top_i < len(looks):
                        h.go(looks[top_i]['id'])
                else:
                    song, secs = self.song_sections()
                    if song and bot_i < len(secs):
                        with h.lock:
                            h.song_start(song['id'], 'next', bot_i)       # jumps there at the next bar
            self.set_status()
            self.refresh(force=True)
            return
        if msg.type != 'control_change':
            return
        cc, val = msg.control, msg.value
        if cc in (71, 72, 73, 74, 75, 76, 77, 78, 79, 14, 15):        # relative encoders
            d = val if val < 64 else val - 128
            self.knob(cc, d)
            return
        if val == 0:                                                    # button release
            return
        lk = self.playing()
        if self.mode == 'geo' and cc in GEO_BUTTONS and lk:
            lk['motion'] = GEO_BUTTONS[cc]
            self.save_look(lk)
        elif cc in MOTION_BUTTONS and lk:
            lk['motion'] = MOTION_BUTTONS[cc]
            self.save_look(lk)
        elif cc in SPEED_BUTTONS and lk:
            lk['speed'] = SPEED_BUTTONS[cc]
            self.save_look(lk)
        elif cc == PICTURE_BUTTON and lk:
            lk['motion'] = 'picture'
            self.save_look(lk)
        elif cc == WALLHITS_BUTTON and lk:
            lk['pichits'] = 0.0 if lk.get('pichits', 0) > 0 else 0.6
            self.save_look(lk)
        elif cc == SESSION:
            self.mode = 'looks'
            h.pads.panic()
        elif cc == NOTE:
            if self.mode != 'play':
                h.pads.release_all(time.time())          # the latched pad keeps playing
            self.mode = 'play'
        elif cc == SCALE:
            if self.mode != 'geo':
                h.pads.release_all(time.time())
            self.mode = 'geo'
        elif cc == DELETE:
            h.pads.panic()                               # all pads off, the latched one too
        elif cc == LAYOUT:
            self.mode = 'paint'
            h.pads.panic()
        elif cc == SELECT and self.mode == 'paint':
            self.sel = set() if self.sel else {s['key'] for s in h.rig.segs}
        elif cc in (LEFT, RIGHT):
            ids = [l['id'] for l in h.state['looks']]
            i = ids.index(h.active) if h.active in ids else 0
            h.go(ids[(i + (1 if cc == RIGHT else -1)) % len(ids)])
        elif cc == NEW and lk:
            nid = h.command({'op': 'look.duplicate', 'id': lk['id']})
            if nid:
                h.go(nid, fade=0)
        elif cc == PLAY:
            with h.lock:
                if h.song:
                    h.command({'op': 'song.stop'})
                elif h.state['songs']:
                    h.command({'op': 'song.start', 'id': h.state['songs'][0]['id'], 'when': 'next'})
        elif cc in SIMPLE_BUTTONS:
            h.command({'op': SIMPLE_BUTTONS[cc]})
        self.set_status()
        self.refresh(force=True)

    def knob(self, cc, d):
        h = self.hub
        live = h.live
        lk = self.playing()
        paint = self.mode == 'paint'

        def live_add(key, step):
            h.command({'op': 'live', 'key': key, 'value': live.get(key, 0.0) + d * step})

        def look_add(key, step, lo=0.0, hi=1.0):
            if lk:
                lk[key] = max(lo, min(hi, lk.get(key, 0.0) + d * step))
                self.save_look(lk)

        if self.mode in ('play', 'geo') and cc in (74, 75, 76, 77, 78):
            if cc == 77:
                h.command({'op': 'live', 'key': 'p_speed', 'value': live.get('p_speed', 1.0) * 1.03 ** d})
            else:
                key, step = {74: ('p_level', 0.02), 75: ('p_attack', 0.01), 76: ('p_release', 0.03),
                             78: ('p_spread', 0.02)}[cc]
                live_add(key, step)
            return
        if cc in (71, 79):
            live_add('master', 0.01)
        elif cc == 72:
            if paint:
                self.adjust_zones(lambda hh, s, v: (hh + d / 120.0, s, v))
            else:
                t = live.get('tint', 0.0) + d * 3.0
                h.command({'op': 'live', 'key': 'tint', 'value': ((t + 180) % 360) - 180})
        elif cc == 73:
            if paint:
                self.adjust_zones(lambda hh, s, v: (hh, s + d * 0.02, v))
            else:
                live_add('sat', 0.02)
        elif cc == 74:
            if paint:
                self.adjust_zones(lambda hh, s, v: (hh, s, v + d * 0.02))
            else:
                look_add('level', 0.02)
        elif cc == 75:
            look_add('depth', 0.02)
        elif cc == 76:
            look_add('together', 0.02)
        elif cc == 77:
            h.command({'op': 'live', 'key': 'speed', 'value': live.get('speed', 1.0) * 1.03 ** d})
        elif cc == 78:
            live_add('smooth', 0.01)
        elif cc == 14:
            live_add('fade', 0.1)
        elif cc == 15:
            live_add('guard', 0.05)
        if paint and cc in (72, 73, 74):
            self.refresh(force=False)

    # ---------------------------------------------------------------- lights on Push
    def set_palette(self, idx, rgb):
        rgb = self.hub.push_colour(tuple(max(0, min(255, int(v))) for v in rgb))   # match the lamps
        if self.palette.get(idx) == rgb:
            return False
        r, g, b = rgb
        self.out.send(mido.Message('sysex', data=[0x00, 0x21, 0x1D, 0x01, 0x01, 0x03, idx,
                                                  r & 0x7F, r >> 7, g & 0x7F, g >> 7, b & 0x7F, b >> 7, 0, 0]))
        self.palette[idx] = rgb
        return True

    def pad(self, note, idx, force):
        if force or self.sent.get(note) != idx:
            self.out.send(mido.Message('note_on', note=note, velocity=idx))
            self.sent[note] = idx

    def button(self, cc, val, force):
        if force or self.btn.get(cc) != val:
            self.out.send(mido.Message('control_change', control=cc, value=val))
            self.btn[cc] = val

    def pad_feedback(self):
        """Light the pads you're holding white, the rest in their colours (PLAY / GEOMETRY mode)."""
        if self.out is None:
            return
        held = self.held_pads()
        try:
            for note in range(36, 100):
                self.pad(note, WHITE if note in held else 1 + note - 36, False)
        except Exception:
            pass

    def held_pads(self):
        """Pads to light white while held -- only if Setup asks for it; otherwise a held pad keeps its
        true colour, so Push, the lamps and TouchDesigner always show the same thing."""
        if not self.hub.state['calibration'].get('held_white', False):
            return set()
        off = hub_pads.GEO_OFFSET if self.mode == 'geo' else 0
        return {n - off for n, v in self.hub.pads.voices.items()
                if v.t_off is None and 36 <= n - off <= 99}

    def look_colour(self, lk):
        if lk.get('motion') == 'rainbow':
            return (255, 60, 200)
        cols = [_hex(x) for x in (list(lk.get('canvas', {}).values()) or [lk.get('fill', '#ffffff')])]
        avg = tuple(sum(x[i] for x in cols) // len(cols) for i in range(3))
        m = max(avg) or 1
        return tuple(min(255, int(v * 255 / m)) for v in avg) if m > 20 else (40, 40, 40)

    def refresh(self, force=False):
        if self.out is None:
            return
        self.last_refresh = time.time()
        h = self.hub
        try:
            changed = self.set_palette(WHITE, (255, 255, 255))
            changed = self.set_palette(DIM, (40, 40, 40)) or changed
            lk = self.playing() or {}
            top, bottom = [], []
            test = h.push_test if getattr(h, 'sync_test', False) else getattr(h, 'calib_test', None)
            if test is not None:                              # Setup > Colour match: every pad the test colour
                changed = self.set_palette(100, tuple(int(255 * v) for v in test)) or changed
                if changed:
                    self.out.send(mido.Message('sysex', data=[0x00, 0x21, 0x1D, 0x01, 0x01, 0x05]))
                for note in range(36, 100):
                    self.pad(note, 100, force)
                return
            if self.mode == 'play':
                held = self.held_pads()
                for note in range(36, 100):
                    row = (note - 36) // 8
                    _, _, rgb = hub_pads.pad_info(note)
                    k = ROW_BRIGHT[row]
                    c = tuple(int(255 * x * k) for x in rgb)
                    changed = self.set_palette(1 + note - 36, c) or changed
                self.play_held = held
            elif self.mode == 'geo':
                for note in range(36, 100):
                    _, _, _, base = geo.geo_pad(note)
                    changed = self.set_palette(1 + note - 36, tuple(int(255 * x) for x in base)) or changed
                self.play_held = self.held_pads()
            elif self.mode == 'paint':
                live = h.out_at(time.time() - h.lamp_delay())
                chan = {ch: i for i, ch in enumerate(h.rig.channels)}
                for i, z in enumerate(self.zones()):
                    k = chan.get(z['ch'])
                    if live is not None and k is not None and k < len(live):     # what the zone shows right now
                        c = tuple(int(255 * max(0.0, min(1.0, v))) for v in live[k])
                    else:
                        c = _hex(self.zone_colour(lk, z['key']))
                    if z['key'] not in self.sel:
                        c = tuple(v // 5 for v in c)
                    changed = self.set_palette(P_TOP + i, c if max(c) > 8 else (12, 12, 12)) or changed
                    top.append(P_TOP + i)
                for i, sw in enumerate(SWATCHES):
                    c = _hex(sw)
                    changed = self.set_palette(P_BOTTOM + i, c if max(c) else (20, 20, 20)) or changed
                    bottom.append(P_BOTTOM + i)
            else:
                looks = self.looks()
                for i, l in enumerate(looks):
                    changed = self.set_palette(P_TOP + i, self.look_colour(l)) or changed
                    top.append(WHITE if l['id'] == h.active else P_TOP + i)
                song, secs = self.song_sections()
                playing = h.song['section'] if h.song else -1
                for i, sec in enumerate(secs):
                    sl = h.look(sec['look'])
                    c = self.look_colour(sl) if sl else (60, 60, 60)
                    changed = self.set_palette(P_BOTTOM + i, tuple(v // 3 for v in c)) or changed
                    bottom.append(WHITE if i == playing else P_BOTTOM + i)
            for i, m in enumerate(GEO_BUTTONS.values() if self.mode == 'geo' else MOTION_BUTTONS.values()):
                c = GEO_COLOURS[m] if self.mode == 'geo' else MOTION_COLOURS[m]
                changed = self.set_palette(P_MOTION + i, c if lk.get('motion') == m else tuple(v // 6 for v in c)) or changed
            for i, sp in enumerate(SPEED_BUTTONS.values()):
                on = abs(lk.get('speed', -1) - sp) < 1e-6
                changed = self.set_palette(P_SPEED + i, (255, 200, 80) if on else (40, 30, 10)) or changed
            changed = self.set_palette(P_SPEED + 6, (60, 200, 255) if lk.get('motion') == 'picture' else (10, 30, 40)) or changed
            changed = self.set_palette(P_SPEED + 7, (255, 255, 255) if lk.get('pichits', 0) > 0 else (30, 30, 30)) or changed
            if changed:
                # Reapply Color Palette updates every LED using a changed slot -- no need to resend the pads
                self.out.send(mido.Message('sysex', data=[0x00, 0x21, 0x1D, 0x01, 0x01, 0x05]))
            for row in range(8):
                for col in range(8):
                    note = 36 + row * 8 + col
                    if self.mode in ('play', 'geo'):
                        self.pad(note, WHITE if note in self.play_held else 1 + note - 36, force)
                        continue
                    if row >= 2:
                        i = (7 - row) * 8 + col
                        idx = top[i] if i < len(top) else 0
                    else:
                        i = (1 - row) * 8 + col
                        idx = bottom[i] if i < len(bottom) else 0
                    self.pad(note, idx, force)
            for i, cc in enumerate(MOTION_BUTTONS):
                self.button(cc, P_MOTION + i, force)
            for i, cc in enumerate(list(SPEED_BUTTONS) + [PICTURE_BUTTON, WALLHITS_BUTTON]):
                self.button(cc, P_SPEED + i, force)
            mono = {SESSION: self.mode == 'looks', NOTE: self.mode == 'play', SCALE: self.mode == 'geo', LAYOUT: self.mode == 'paint',
                    SELECT: self.mode == 'paint',
                    9: h.hold, 60: h.blackout, PLAY: bool(h.song), 3: True, 57: True, 86: True,
                    LEFT: True, RIGHT: True, NEW: True, DELETE: bool(h.pads.latched())}
            for cc, on in mono.items():
                self.button(cc, 127 if on else 10, force)
        except Exception as e:
            self.status = 'lost Push 2 (%s)' % e
            self.close()
