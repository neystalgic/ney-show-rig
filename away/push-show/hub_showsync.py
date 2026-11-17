# =============================================================================
# HUE HUB -- SHOW SYNC: Push 2 SHOW pads + the visuals follow the show director     W6, away loop Nov 17
#
# Michael, Nov 16: "bind light modes to buttons on the Push and have them synchronized with our sacred
# geometry in colour and intensity."
#
# 1. PUSH 2 SHOW MODE (the MIX button): four rows of pads drive the director (hub_modes.py) through the
#    hub's own setting path -- the same settings the console and /show/set change:
#      top row   Hue showcase  Head moment  Gobos  Zones  UV  Burst  AUTO  acts on/off
#      row 2     Pulse  Call  Wave  Loop  Split  Orbit  Relay
#      row 3     wave: bounce  forward  back  alternate  |  loop: alternate  ccw  cw
#      row 4     audio mix  0  25  50  60  75  100 %
#    Pads in the rig's purple: playing = bright, locked (waiting for its turn) = medium, the rest dim.
#    Tap the locked act / mode again = back to AUTO.  The bottom four rows stay dark.
#
# 2. VISUALS FOLLOW THE LIGHTS: while the director runs, the TouchDesigner message also carries
#      act, mode   what's playing ('' when the director is off)
#      hue         the director's colour, 0-1
#      level       the zones' mean level, 0-1 (glides: quick up, slower down -- no flicker)
#      kick        the kick the director dances to, 0-1 (music + built-in drummer, decaying)
#    and the visual is picked per act / mode (FORM_FOR). A pad you touched in the last 20 s still wins.
#
# Safety: no network, no lights. It only reads the director's last frame and asks the hub to change five
# allowlisted settings (show_lock, show_acts, show_wave, show_loop_dir, show_audio); hub_modes + hub_dmx
# keep every limit (lean caps, pan windows, no strobe for a mode) and the DMX node has the last word.
# =============================================================================
import colorsys
import math

ACTS = ['hues', 'heads', 'gobos', 'zones', 'uv', 'burst']
MODES = ['pulse', 'call', 'wave', 'loop', 'split', 'orbit', 'relay']
WAVES = ['bounce', 'forward', 'back', 'alternate']
LOOPS = ['alternate', 'ccw', 'cw']
AUDIO = [0.0, 0.25, 0.5, 0.6, 0.75, 1.0]
NAMES = {'hues': 'Hue showcase', 'heads': 'Head moment', 'gobos': 'Gobos', 'zones': 'Zone modes', 'uv': 'UV reveal',
         'burst': 'Burst', 'pulse': 'Pulse', 'call': 'Call & Response', 'wave': 'Wave', 'loop': 'Loop',
         'split': 'Split', 'orbit': 'Orbit', 'relay': 'Relay'}

# act / mode -> the form key TouchDesigner's hue_feed understands (its VIS_FOR picks the visual):
#   hues flower_of_life, heads metatrons_cube, gobos sri_yantra, uv tesseract, burst kaleidoscope,
#   pulse golden_angle, wave chladni, loop proc_mandala, call proc_voronoi, split proc_quasicrystal,
#   orbit proc_harmonograph, relay proc_attractor
FORM_FOR = {'hues': 'flower', 'heads': 'metatron', 'gobos': 'yantra', 'uv': 'tesseract', 'burst': 'kaleido',
            'pulse': 'golden', 'wave': 'chladni', 'loop': 'mandala', 'call': 'voronoi', 'split': 'quasicrystal',
            'orbit': 'harmonograph', 'relay': 'attractor'}
# the form keys TD's hue_feed knows (VIS_FOR's keys, copied Nov 17) -- anything else is never sent
TD_FORMS = {'golden', 'spiral', 'flower', 'metatron', 'yantra', 'chladni', 'tetrahedron', 'cube', 'tesseract',
            'kaleido', 'blend', 'reaction', 'warp', 'attractor', 'truchet', 'contours', 'mandala', 'voronoi',
            'harmonograph', 'quasicrystal', 'life'}

COLOURS = {'on': (170, 60, 255), 'mid': (90, 30, 140), 'dim': (25, 8, 40)}     # purple: playing / locked / rest


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ------------------------------------------------------------------------------ the director
def director(hub):
    """The show director (hub_dmx.Heads.chase = hub_modes.Director), or None if it isn't there."""
    d = getattr(getattr(hub, 'dmx', None), 'chase', None)
    return d if d is not None and hasattr(d, 'status') and hasattr(d, 'acts_on') else None


def status(hub):
    d = director(hub)
    if d is None:
        return {}
    try:
        return d.status() or {}
    except Exception:
        return {}


def _settings(settings):
    s = settings or {}
    try:
        audio = float(s.get('show_audio', 0.6))
    except (TypeError, ValueError):
        audio = 0.6
    return (str(s.get('show_lock', '') or '').strip().lower(), str(s.get('show_wave', 'bounce') or 'bounce'),
            str(s.get('show_loop_dir', 'alternate') or 'alternate'), audio)


def _cell(note):
    if not 36 <= note <= 99:
        return None, None
    return (note - 36) // 8, (note - 36) % 8                  # row 0 = bottom


# ------------------------------------------------------------------------------ Push 2 SHOW pads
def pad_action(note, st, settings):
    """A pad press -> (setting key, value) for the hub's 'setting' op, or None (dark pad)."""
    row, col = _cell(note)
    lock, _, _, _ = _settings(settings)
    if row == 7:
        if col < len(ACTS):
            return ('show_lock', '' if lock == ACTS[col] else ACTS[col])
        if col == 6:
            return ('show_lock', '')
        acts_on = (st or {}).get('acts_on', (settings or {}).get('show_acts', True))
        return ('show_acts', not bool(acts_on))
    if row == 6 and col < len(MODES):
        return ('show_lock', '' if lock == MODES[col] else MODES[col])
    if row == 5:
        if col < 4:
            return ('show_wave', WAVES[col])
        if col < 7:
            return ('show_loop_dir', LOOPS[col - 4])
    if row == 4 and col < len(AUDIO):
        return ('show_audio', AUDIO[col])
    return None


def pad_level(note, st, settings):
    """'on' / 'mid' / 'dim' for a SHOW pad, None = dark."""
    row, col = _cell(note)
    st = st or {}
    lock, wave, loop, audio = _settings(settings)
    act = st.get('act') if st.get('on') else None
    mode = st.get('mode') if act == 'zones' else None
    if row == 7:
        if col < len(ACTS):
            return 'on' if act == ACTS[col] else 'mid' if lock == ACTS[col] else 'dim'
        if col == 6:
            return 'on' if not lock else 'dim'
        return 'on' if st.get('acts_on', (settings or {}).get('show_acts', True)) else 'dim'
    if row == 6 and col < len(MODES):
        return 'on' if mode == MODES[col] else 'mid' if lock == MODES[col] else 'dim'
    if row == 5 and col < 7:
        return 'on' if (WAVES[col] == wave if col < 4 else LOOPS[col - 4] == loop) else 'dim'
    if row == 4 and col < len(AUDIO):
        return 'on' if abs(audio - AUDIO[col]) < 0.01 else 'dim'
    return None


def display_text(st):
    """'SHOW mode -- Gobos (bar 3 of 8) -- lock: auto'."""
    st = st or {}
    if not st.get('on'):
        return 'SHOW mode -- director off (Director on from the console or desk)'
    a = st.get('act') or 'zones'
    key = (st.get('mode') or 'relay') if a == 'zones' else a
    lock = st.get('lock') or ''
    return 'SHOW mode -- %s (bar %d of %d) -- lock: %s' % (NAMES.get(key, key), st.get('bar', 0), st.get('bars', 8),
                                                          NAMES.get(lock, lock) if lock else 'auto')


# ------------------------------------------------------------------------------ the visuals
def form_for(z):
    """The TD form key for a director frame or status (None = director off, or a name TD doesn't have)."""
    if not z or ('on' in z and not z['on']):
        return None
    a = z.get('act') or 'zones'
    key = (z.get('mode') or 'relay') if a == 'zones' else a
    f = FORM_FOR.get(key)
    return f if f in TD_FORMS else None


def director_form(hub, pad_recent):
    """The visual the director wants -- unless a pad was touched in the last PAD_HOLD seconds."""
    if pad_recent:
        return None
    d = director(hub)
    return form_for(getattr(d, 'last', None)) if d is not None else None


class Sync:
    """Extra fields for the TouchDesigner message: act, mode, hue, level, kick."""

    def __init__(self):
        self.t = None
        self.level = 0.0
        self.kick = 0.0

    def _kick(self, d, hub):
        try:
            raw = _clamp(float((getattr(getattr(hub, 'audioshow', None), 'env', None) or {}).get('kick', 0.0) or 0.0))
            w = _clamp(float(d.audio_mix()))
            clk = _clamp(float(d.clock_hits(hub.clock[0]).get('kick', 0.0)))
            return _clamp(w * raw + (1.0 - w) * clk)
        except Exception:
            return 0.0

    def fields(self, hub, now):
        dt = 0.033 if self.t is None else _clamp(now - self.t, 0.0, 0.25)
        self.t = now
        d = director(hub)
        z = getattr(d, 'last', None) if d is not None else None
        if not z:
            self.level = self.kick = 0.0
            return dict(act='', mode='')
        a = z.get('act') or 'zones'
        m = (z.get('mode') or 'relay') if a == 'zones' else ''
        lv = [float(zo.get('level', 0.0)) for zo in (z.get('zones') or []) if isinstance(zo, dict)]
        if not lv:
            lv = [float(cv.get('level', 0.0)) for cv in (z.get('heads') or {}).values() if isinstance(cv, dict)]
        target = _clamp(sum(lv) / len(lv)) if lv else 0.0
        tau = 0.05 if target > self.level else 0.25          # quick up, slower down
        self.level += (target - self.level) * (1.0 - math.exp(-dt / tau))
        rgb = z.get('rgb')
        if isinstance(rgb, (list, tuple)) and len(rgb) == 3 and max(rgb) > 0:
            hue = colorsys.rgb_to_hsv(*[_clamp(float(v)) for v in rgb])[0]
        else:
            hue = float(getattr(d, 'hue', 0.0) or 0.0) % 1.0
        self.kick = max(self._kick(d, hub), self.kick * math.exp(-dt / 0.2))
        return dict(act=a, mode=m, hue=round(hue, 4), level=round(_clamp(self.level), 4), kick=round(_clamp(self.kick), 4))
