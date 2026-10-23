# =============================================================================
# HUE HUB -- the TouchDesigner side
#
# Builds two components in /project1:
#   hue_feed     sends the Hue Hub the picture (wire any TOP into it) and the
#                beat from show_clock, 30 times a second. That's all TD does now.
#   light_desk   the Light Desk, inside TouchDesigner. Open it with
#                open_desk()   (or right-click light_desk > View...)
#
#   exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/build_hue_hub_td.py').read())
#
# Then   sync_geometry()   makes the Sacred Geometry visuals and the Mapper Pack
# effects in this project follow the room: its colours, the beat, and the pads
# you touch (the row picks the geometry, the column shapes it, pressure makes it bigger,
# the room's brightness makes it glow), and builds geo_show -- the visual that
# matches what's playing, cross-fading, with a mapper effect on top.
# open_show() shows it. Without the hub the visuals keep moving on their own.
# unsync_geometry() gives everything its own settings back.
#
# The old hue_rig is left alone -- set its "Send to the Lights" off (or delete
# it yourself) once the hub is running.
# Safe to run again: it replaces only hue_feed and light_desk.
# =============================================================================

import os

HUB_BASE = '/Users/michaelney/Touchdesigner Designs/Hue Rig'   # (v35: infinity tunnel + full projector resolution)


def _hfirst(g):
    try:
        return g[0]
    except Exception:
        return g


def _hset(o, name, value, expr=False):
    try:
        p = getattr(o.par, name)
        if expr:
            p.expr = value
        else:
            p.val = value
        return True
    except Exception:
        return False


FEED_CODE = r'''# hue_feed -- sends the picture and the beat to the Hue Hub
GEO_NAMES = ['golden_angle', 'flower_of_life']   # heartbeat: which visual to report
import json
import socket

import math
import sys
import time

import numpy

_S = {'sock': None, 'n': 0, 'rx_t': -10.0, 'rx_try': -10.0, 'last': None, 'shown': None, 'log': ''}
# which Sacred Geometry visual goes with each light form, best first
VIS_FOR = {'golden': ['golden_angle', 'flower_of_life'], 'spiral': ['golden_angle', 'flower_of_life'],
           'flower': ['flower_of_life'], 'metatron': ['metatrons_cube', 'flower_of_life'],
           'yantra': ['sri_yantra', 'metatrons_cube'], 'chladni': ['chladni', 'flower_of_life'],
           'tetrahedron': ['tesseract', 'metatrons_cube'], 'cube': ['tesseract', 'metatrons_cube'],
           'tesseract': ['tesseract', 'metatrons_cube'],
           'kaleido': ['kaleidoscope', 'flower_of_life'],
           'blend': ['__blend__', 'kaleidoscope', 'flower_of_life'],
           'reaction': ['reaction_diffusion', 'golden_angle', 'flower_of_life'],
           # the procedural pieces (build_procedural): chosen by the music, phrase by phrase
           'warp': ['proc_warp', 'reaction_diffusion'], 'attractor': ['proc_attractor', 'golden_angle'],
           'truchet': ['proc_truchet', 'kaleidoscope'], 'contours': ['proc_contours', 'chladni'],
           'mandala': ['proc_mandala', 'flower_of_life'], 'voronoi': ['proc_voronoi', 'reaction_diffusion'],
           'harmonograph': ['proc_harmonograph', 'golden_angle'], 'quasicrystal': ['proc_quasicrystal', 'kaleidoscope'],
           'life': ['proc_life', 'reaction_diffusion']}
LOG = r"@@LOG@@"


def _linear():
    """True if this project works in linear colour (Preferences > Color, TouchDesigner 2025+).
    The default, Pass-through, shows numbers as they are (screen / sRGB values)."""
    if 'lin' not in _S:
        ws = str(getattr(project, 'workingColorSpace', '')).upper()
        _S['lin'] = ('LINEAR' in ws) or ('ACES' in ws)
    return _S['lin']


def _log(text):
    if text == _S['log']:
        return
    _S['log'] = text
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%H:%M:%S ') + text + '\n')
    except OSError:
        pass


def _status(c, text, log=True):
    if c.par.Syncstatus.eval() != text:
        c.par.Syncstatus = text
    if log:
        _log(text)


def _set(c, name, v):
    p = getattr(c.par, name, None)
    if p is not None and p.eval() != v:
        p.val = v


def _visual_index(c, form):
    show = op(c.par.Showpath.eval())
    names = show.fetch('visuals', [], search=False) if show is not None else []
    for name in VIS_FOR.get(form, []):
        if name in names:
            return names.index(name)
    return None


EASE = {
    'linear': lambda t: t,
    'sine': lambda t: 0.5 - 0.5 * math.cos(math.pi * t),
    'smooth': lambda t: t * t * (3 - 2 * t),
    'smoother': lambda t: t * t * t * (t * (6 * t - 15) + 10),
    'cubic': lambda t: 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2,
    'expo': lambda t: 0.0 if t <= 0 else 1.0 if t >= 1 else (2 ** (20 * t - 10) / 2 if t < 0.5
                                                              else (2 - 2 ** (-20 * t + 10)) / 2),
    'circ': lambda t: (1 - math.sqrt(1 - (2 * t) ** 2)) / 2 if t < 0.5 else (math.sqrt(1 - (-2 * t + 2) ** 2) + 1) / 2,
}


def _golden_step(n):
    step = max(1, int(round(n / 1.6180339887)))
    while n > 1 and math.gcd(step, n) != 1:
        step += 1
    return step


def _blend(c):
    """Top row: one sacred geometry at 100%, held, then it morphs into the next along a curve.
    Beat-locked: Hold and Morph are in beats (geo_show > Show page)."""
    show = op(c.par.Showpath.eval())
    if show is None or not hasattr(show.par, 'W0'):
        return
    names = [n for n in show.fetch('visuals', [], search=False) if n != '__blend__']
    n = len(names)
    if n == 0:
        return
    tempo = max(40.0, float(c.par.Tempo.eval()))
    spb = 60.0 / tempo
    hold = max(0.0, float(show.par.Hold.eval()))
    morph = max(0.25, float(show.par.Morph.eval()))
    # flicker safety: a morph never quicker than 0.4 s, a whole step never quicker than 1 s
    k = max(1.0, 0.4 / (morph * spb), 1.0 / ((hold + morph) * spb))
    hold, morph = hold * k, morph * k
    period = hold + morph
    pos = float(c.par.Beats.eval()) / period
    step = int(math.floor(pos))
    f = (pos - step) * period
    order = str(show.par.Order.eval())
    jump = _golden_step(n) if order == 'golden' else 1
    a = (step * jump) % n
    b = ((step + 1) * jump) % n
    t = 0.0 if f < hold else min(1.0, (f - hold) / morph)
    e = max(0.0, min(1.0, EASE.get(str(show.par.Curve.eval()), EASE['sine'])(t)))
    w = [0.0] * n
    w[a] += 1.0 - e
    w[b] += e
    for i in range(32):
        p = getattr(show.par, 'W%d' % i, None)
        if p is not None:
            v = round(w[i], 4) if i < n else 0.0
            if p.eval() != v:
                p.val = v
    txt = names[a] if e < 0.005 else names[b] if e > 0.995 else '%s -> %s  %d%%' % (names[a], names[b], int(e * 100))
    if hasattr(show.par, 'Showing') and show.par.Showing.eval() != txt:
        show.par.Showing = txt


def _crossfade(c, dt):
    """Fades geo_show from the visual it shows to the one that matches what's playing."""
    want = _visual_index(c, str(c.par.Vis.eval()))
    if want is None:
        return
    if _S['shown'] is None:
        _S['shown'] = want
        _set(c, 'Forma', want)
        _set(c, 'Formb', want)
        _set(c, 'Mix', 1.0)
    if want != int(c.par.Formb.eval()) and c.par.Mix.eval() >= 1.0:
        _set(c, 'Forma', int(c.par.Formb.eval()))
        _set(c, 'Formb', want)
        _set(c, 'Mix', 0.0)
    show = op(c.par.Showpath.eval())
    fade = max(0.05, float(show.par.Fade.eval())) if show is not None and hasattr(show.par, 'Fade') else 0.4
    if c.par.Mix.eval() < 1.0:
        _set(c, 'Mix', min(1.0, c.par.Mix.eval() + dt / fade))
    _set(c, 'Formindex', int(c.par.Formb.eval()))


def _apply(c, m):
    if 'movie' in m:
        _set(c, 'Movie', bool(m.get('movie')))
        if m.get('moviesrc') in ('capture', 'screen', 'camera'):
            _set(c, 'Moviesrc', m['moviesrc'])
    _set(c, 'Georot', float(m.get('rot', 0.0)))
    _set(c, 'Phase', float(m.get('phase', 0.0)))
    ch = m.get('chladni') or [3, 5, -1]
    _set(c, 'Chladn', float(ch[0]))
    _set(c, 'Chladm', float(ch[1]))
    _set(c, 'Chladsign', float(ch[2]))
    for key, name in (('colora', 'Geocola'), ('colorb', 'Geocolb')):
        col = m.get(key) or [1, 1, 1]
        for ch_, v in zip('rgb', col):
            v = float(v)
            if _linear():                                 # the shaders get colours in the project's space
                v = v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            _set(c, name + ch_, round(v, 4))
    for i, col in enumerate(m.get('vcols') or []):
        for k_, ch_ in enumerate(('ar', 'ag', 'ab', 'br', 'bg', 'bb')):
            if k_ < len(col):
                v = float(col[k_])
                if _linear():
                    v = v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                _set(c, 'Vc%d%s' % (i, ch_), round(v, 4))
    for key, name in (('beats', 'Beats'), ('build', 'Build'), ('energy', 'Energy'), ('press', 'Press'), ('tempo', 'Tempo'),
                      ('guard', 'Guard'), ('master', 'Master'), ('x', 'X'), ('zoom', 'Zoom'), ('turn', 'Turn'),
                      ('line', 'Line'), ('akick', 'Akick'), ('asnare', 'Asnare'), ('ahats', 'Ahats'),
                      ('alevel', 'Alevel'), ('abright', 'Abright'), ('adrop', 'Adrop')):
        if key in m:
            _set(c, name, round(float(m[key]), 4))
    if 'section' in m:
        _set(c, 'Section', str(m['section']))
    lam = m.get('lamps')
    t = c.op('lamps')
    if lam is not None and t is not None:                 # every lamp's live colour (for the Shape Mapper)
        keys = [str(row[0]) for row in lam]
        if t.numRows != len(lam) + 1 or [str(t[r, 0]) for r in range(1, t.numRows)] != keys:
            t.clear()
            t.appendRow(['key', 'label', 'r', 'g', 'b'])
            for row in lam:
                t.appendRow([str(row[0]), str(row[1]), row[2], row[3], row[4]])
        else:
            for r, row in enumerate(lam, 1):
                for k_, v in enumerate(row[2:5]):
                    if str(t[r, 2 + k_]) != str(v):
                        t[r, 2 + k_] = v
    _set(c, 'Form', str(m.get('form', '')))
    if m.get('vis'):
        _set(c, 'Vis', str(m['vis']))


def _receive(c, dt):
    """The hub's geometry clock (port 7012). Without the hub the visuals keep moving on their own."""
    rx = getattr(sys, '_hue_sync_sock', None)        # one socket for the whole TD session
    if rx is None and absTime.seconds - _S['rx_try'] >= 2.0:
        _S['rx_try'] = absTime.seconds
        try:
            rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rx.bind(('127.0.0.1', int(c.par.Syncport.eval())))
            rx.setblocking(False)
            sys._hue_sync_sock = rx
        except OSError as e:
            rx = None
            _status(c, 'cannot listen on port %d: %s' % (int(c.par.Syncport.eval()), e))
    last = None
    while rx is not None:
        try:
            last = rx.recv(65536)
        except (BlockingIOError, OSError):
            break
    m = None
    if last is not None:
        try:
            m = json.loads(last.decode())
        except ValueError:
            m = None
    if m is not None:
        _S['rx_t'] = absTime.seconds
        _S['rx_n'] = _S.get('rx_n', 0) + 1
        _apply(c, m)
        _status(c, 'in step with the hub -- %s, visual: %s' % (m.get('form', ''), m.get('vis', '')), log=False)
        _log('in step with the hub')
        if absTime.seconds - _S.get('beat_t', -100.0) >= 15.0:      # a heartbeat in td_sync_log.txt (for checking)
            _S['beat_t'] = absTime.seconds
            g = op(c.parent().path + '/' + GEO_NAMES[0]) if GEO_NAMES else None
            def pv(o, n):
                q = getattr(o.par, n, None) if o is not None else None
                return ('%.3f' % q.eval()) if q is not None else '-'
            _log('rx %d | vis %s | Georot %s Energy %s Akick %s Alevel %s Zoom %s | %s: Rotate %s Scale %s Glow %s' % (
                _S['rx_n'], m.get('vis'), pv(c, 'Georot'), pv(c, 'Energy'), pv(c, 'Akick'), pv(c, 'Alevel'),
                pv(c, 'Zoom'), GEO_NAMES[0] if GEO_NAMES else '-', pv(g, 'Rotate'), pv(g, 'Scale'), pv(g, 'Glow')))
    elif absTime.seconds - _S['rx_t'] > 2.0:
        # no hub: keep the geometry alive here in TouchDesigner
        t = absTime.seconds
        _set(c, 'Georot', (c.par.Georot.eval() + 6.0 * dt) % 360.0)
        _set(c, 'Phase', c.par.Phase.eval() + dt * 0.25)
        _set(c, 'Beats', c.par.Beats.eval() + dt * max(40.0, c.par.Tempo.eval()) / 60.0)
        _set(c, 'Build', min(1.0, c.par.Build.eval() + dt * 0.5))
        _set(c, 'Energy', round(0.6 + 0.15 * math.sin(t * 2 * math.pi * 0.1), 4))
        _set(c, 'Press', 0.0)
        for a_ in ('Akick', 'Asnare', 'Ahats', 'Alevel', 'Adrop'):
            _set(c, a_, 0.0)
        _set(c, 'Master', 1.0)
        _status(c, 'hub not running -- the visuals animate on their own')
    _crossfade(c, dt)
    _blend(c)


BUILD = r"@@BUILD@@"


def _autoupdate(c):
    """When build_hue_hub_td.py in the Hue Rig folder is updated, rebuild hue_feed with it and put the
    Sacred Geometry back in step -- no Textport needed. (Save the project afterwards to keep it.)"""
    import os
    if absTime.seconds - _S.get('upd_t', -100.0) < 3.0 or _S.get('upd_busy'):
        return
    _S['upd_t'] = absTime.seconds
    try:
        mt = os.path.getmtime(BUILD)
    except OSError:
        return
    seen = c.fetch('build_mtime', None, search=False)
    if seen is None:
        c.store('build_mtime', mt)
        return
    if mt > seen + 0.5:
        _S['upd_busy'] = True
        c.store('build_mtime', mt)
        _log('build_hue_hub_td.py was updated -- rebuilding hue_feed and re-syncing the geometry')
        run("exec(open(args[0]).read()); "
            "sync_geometry() if op('/project1/geo_show') is not None or args[1] else None; "
            "geo_check()", BUILD, True, delayFrames=20)


def onFrameEnd(frame):
    c = parent()
    now = absTime.seconds
    dt = 0.0 if _S['last'] is None else max(0.0, min(0.25, now - _S['last']))
    _S['last'] = now
    try:
        _receive(c, dt)
    except Exception as e:
        _status(c, 'sync error: %s' % e)
    try:
        _autoupdate(c)
    except Exception as e:
        _log('auto-update error: %s' % e)
    if not c.par.Active.eval():
        c.par.Status = 'Off'
        return
    _S['n'] += 1                                 # every frame: the lamps follow the picture in real time
    msg = {}
    clk = op(c.par.Clockpath.eval())
    if clk is not None and hasattr(clk.par, 'Beats'):
        msg['beats'] = float(clk.par.Beats.eval())
        msg['tempo'] = float(clk.par.Tempo.eval())
        msg['source'] = 'Ableton Link' if 'Link' in str(clk.par.Status.eval()) else 'show_clock'
    else:
        msg['beats'] = None
    pic = 'no picture'
    if c.par.Sendpicture.eval() and (len(c.inputs) > 0 or c.par.Movie.eval()):
        try:
            a = op('small').numpyArray(delayed=True)
            if a is not None and a.size:
                a = a[::-1, :, :3]                        # top row first
                a = a.clip(0, 1)
                if _linear():                             # linear project: back to screen (sRGB) values
                    a = numpy.where(a <= 0.0031308, a * 12.92, 1.055 * numpy.power(a, 1 / 2.4) - 0.055)
                g = (a * 255 + 0.5).astype('uint8')
                msg['grid'], msg['h'], msg['w'] = g.reshape(-1).tolist(), int(g.shape[0]), int(g.shape[1])
                pic = 'picture %dx%d' % (g.shape[1], g.shape[0])
        except Exception as e:
            pic = 'picture error: %s' % e
    if _S['sock'] is None:
        _S['sock'] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _S['sock'].sendto(json.dumps(msg, separators=(',', ':')).encode(), ('127.0.0.1', int(c.par.Port.eval())))
        st = 'Sending %s + %s to the hub' % ('beat' if msg['beats'] is not None else 'no beat', pic)
    except OSError as e:
        st = 'Could not send: %s' % e
    if c.par.Status.eval() != st:
        c.par.Status = st
    return
'''

MOUSE_CODE = r'''# light_desk -- shows the desk page, reloads it when the hub comes up,
# and passes the mouse on to it
import socket
import urllib.parse

_M = {'last': None, 'up': None, 'n': 0}


def hub_up(url):
    try:
        p = urllib.parse.urlparse(url)
        s = socket.create_connection((p.hostname or 'localhost', p.port or 80), timeout=0.05)
        s.close()
        return True
    except OSError:
        return False


def onFrameEnd(frame):
    c = parent()
    w = op('desk')
    _M['n'] += 1
    if _M['n'] % 60 == 1:                        # once a second: is the hub running?
        up = hub_up(c.par.Url.eval())
        if up and _M['up'] is not True:          # it just came up -> load the desk
            try:
                w.par.reload.pulse()
            except Exception:
                pass
        _M['up'] = up
        try:
            op('view').par.index = 0 if up else 1
        except Exception:
            pass
    try:
        u, v = float(c.panel.u), float(c.panel.v)
        left = bool(float(c.panel.lselect))
        inside = bool(float(c.panel.inside))
        wheel = float(c.panel.wheel)
    except Exception:
        return
    if c.par.Flipy.eval():
        v = 1.0 - v
    state = (round(u, 4), round(v, 4), left)
    if inside and (state != _M['last'] or wheel):
        try:
            w.interactMouse(u, v, left=left, wheel=wheel * 3)
        except Exception:
            pass
        _M['last'] = state
    elif not inside and _M['last'] and _M['last'][2]:
        try:
            w.interactMouse(u, v, left=False)
        except Exception:
            pass
        _M['last'] = None
    return
'''

KEYS_CODE = r'''# light_desk -- typing into the desk (only while the mouse is over it)
def onKey(dat, key, character, alt=False, lAlt=False, rAlt=False, ctrl=False, lCtrl=False, rCtrl=False,
          shift=False, lShift=False, rShift=False, state=False, time=0, cmd=False, lCmd=False, rCmd=False, *a, **k):
    c = parent()
    try:
        if not state or not bool(float(c.panel.inside)):
            return
        w = op('desk')
        if character and len(character) == 1 and character.isprintable():
            w.sendString(character)
        else:
            w.sendKey(key, shift=shift, alt=alt, ctrl=ctrl, cmd=cmd)
    except Exception:
        pass
    return
'''


def _setres(top, w, h):
    """Set a TOP's size, whatever this TouchDesigner version calls the parameters."""
    _hset(top, 'outputresolution', 'custom')
    done = []
    for pw, ph in (('resolutionw', 'resolutionh'), ('resolution1', 'resolution2'), ('resw', 'resh'),
                   ('outputresolutionw', 'outputresolutionh')):
        if _hset(top, pw, w) and _hset(top, ph, h):
            done.append(pw)
    return done


def build_feed(parent_):
    old = parent_.op('hue_feed')
    if old is not None:
        old.destroy()
    c = parent_.create(baseCOMP, 'hue_feed')
    c.nodeX, c.nodeY = 0, -2200
    pg = c.appendCustomPage('Feed')
    p = _hfirst(pg.appendToggle('Active', label='Send to the Hub'))
    p.default = p.val = True
    p = _hfirst(pg.appendToggle('Sendpicture', label='Send the Picture'))
    p.default = p.val = True
    p = _hfirst(pg.appendInt('Port', label='Hub Port'))
    p.default = p.val = 7011
    p = _hfirst(pg.appendStr('Clockpath', label='Show Clock'))
    p.default = p.val = '/project1/show_clock'
    p = _hfirst(pg.appendStr('Status', label='Status'))
    p.val = 'starting'
    # MOVIE MODE (set by the hub: desk > Movie): the lamps follow the film instead of the visuals
    p = _hfirst(pg.appendToggle('Movie', label='Movie Mode (from the hub)'))
    p.default = p.val = False
    p = _hfirst(pg.appendMenu('Moviesrc', label='Movie Picture From'))
    p.menuNames = ['capture', 'screen', 'camera']
    p.menuLabels = ['Capture Card (PS5 / PC)', "This Mac's Screen", 'Camera at the Screen']
    p.val = 'capture'
    p = _hfirst(pg.appendStr('Moviepath', label='Movie Picture TOP'))
    p.default = p.val = '/project1/movie_in/out1'

    # the hub's geometry clock -- sync_geometry() points the Sacred Geometry visuals at these
    sp = c.appendCustomPage('Sync')
    p = _hfirst(sp.appendStr('Syncstatus', label='Status'))
    p.val = 'starting'
    p = _hfirst(sp.appendInt('Syncport', label='Hub Sync Port'))
    p.default = p.val = 7012
    for name, label in (('Georot', 'Rotation (deg)'), ('Phase', 'Phase (cycles)'), ('Pulse', 'Beat Pulse'),
                        ('Chladn', 'Chladni N'), ('Chladm', 'Chladni M'), ('Chladsign', 'Chladni Family')):
        _hfirst(sp.appendFloat(name, label=label))
    c.par.Chladn, c.par.Chladm, c.par.Chladsign = 3, 5, -1
    for name, label, rgb in (('Geocola', 'Colour A', (1.0, 0.78, 0.38)), ('Geocolb', 'Colour B', (0.62, 0.36, 1.0))):
        for q, v in zip(sp.appendRGB(name, label=label), rgb):
            q.default = q.val = v
    for name, label, d in (('Beats', 'Beats (the hub clock)', 0.0), ('Build', 'Build (across the pads)', 1.0), ('Energy', 'Energy (room brightness)', 0.6),
                           ('Press', 'Pad Pressure', 0.0), ('Tempo', 'Tempo', 120.0),
                           ('Guard', 'Flicker Guard (/s)', 2.0), ('Master', 'Master', 1.0),
                           ('X', 'Across the Pads (0-1)', 0.5), ('Zoom', 'Zoom', 1.05), ('Turn', 'Extra Turn (deg)', 78.75),
                           ('Line', 'Line Width (x)', 1.2),
                           # the gear through the Scarlett (desk > Audio): drum hits 0-1 (flicker-limited by the hub)
                           ('Akick', 'Audio Kick', 0.0), ('Asnare', 'Audio Snare', 0.0), ('Ahats', 'Audio Hats', 0.0),
                           ('Alevel', 'Audio Loudness', 0.0), ('Abright', 'Audio Brightness', 0.5),
                           ('Adrop', 'Audio Drop', 0.0)):
        q = _hfirst(sp.appendFloat(name, label=label))
        q.default = q.val = d
    p = _hfirst(sp.appendStr('Section', label='Music Section'))
    p.val = 'quiet'
    cp = c.appendCustomPage('Colours')            # each visual's own two colours (top row: one lamp each)
    for i in range(len(GEO_VISUALS)):
        for ab, rgb in (('a', (1.0, 0.78, 0.38)), ('b', (0.62, 0.36, 1.0))):
            for q, v in zip(cp.appendRGB('Vc%d%s' % (i, ab), label='%s %s' % (GEO_VISUALS[i], ab.upper())), rgb):
                q.default = q.val = v
    p = _hfirst(sp.appendStr('Form', label='Light Form'))
    p = _hfirst(sp.appendStr('Vis', label='Visual Form'))
    p.val = 'flower'
    p = _hfirst(sp.appendStr('Showpath', label='Show Output'))
    p.default = p.val = '/project1/geo_show'
    for name, label in (('Forma', 'Fading From (input)'), ('Formb', 'Showing (input)'), ('Formindex', 'Visual (geo_visual input)')):
        _hfirst(sp.appendInt(name, label=label))
    p = _hfirst(sp.appendFloat('Mix', label='Cross-fade'))
    p.default = p.val = 1.0

    pic = c.create(inTOP, 'in1_picture')
    pic.nodeX, pic.nodeY = 0, 0
    d = c.create(textDAT, 'small_shader')
    with open(os.path.join(HUB_BASE, 'hue_downsample.glsl')) as f:
        d.text = f.read()
    d.nodeX, d.nodeY = 200, 200
    g = c.create(glslTOP, 'small')
    g.nodeX, g.nodeY = 200, 0
    g.par.pixeldat = d.name
    _hset(g, 'outputresolution', 'custom')
    _hset(g, 'resolutionw', 32)
    _hset(g, 'resolutionh', 20)
    _hset(g, 'format', 'rgba16float')
    mv = c.create(selectTOP, 'movie_pic')               # Movie mode: the film instead of the visuals
    mv.nodeX, mv.nodeY = 0, -100
    _hset(mv, 'top', 'parent().par.Moviepath', expr=True)
    pk = c.create(switchTOP, 'pick')
    pk.nodeX, pk.nodeY = 100, 0
    pk.inputConnectors[0].connect(pic)
    pk.inputConnectors[1].connect(mv)
    _hset(pk, 'index', 'parent().par.Movie', expr=True)
    g.inputConnectors[0].connect(pk)
    o = c.create(outTOP, 'out1')
    o.nodeX, o.nodeY = 400, 0
    o.inputConnectors[0].connect(g)

    lt = c.create(tableDAT, 'lamps')                  # each lamp's live colour, from the hub
    lt.nodeX, lt.nodeY = 200, -200
    lt.clear()
    lt.appendRow(['key', 'label', 'r', 'g', 'b'])
    e = c.create(executeDAT, 'send')
    e.nodeX, e.nodeY = 0, -200
    e.text = FEED_CODE.replace('@@LOG@@', os.path.join(HUB_BASE, 'td_sync_log.txt')).replace(
        '@@BUILD@@', os.path.join(HUB_BASE, 'build_hue_hub_td.py'))
    _hset(e, 'frameend', True)
    _hset(e, 'active', True)
    _hset(c, 'opviewer', "me.op('out1')", expr=True)
    return c


def build_desk(parent_):
    old = parent_.op('light_desk')
    if old is not None:
        old.destroy()
    c = parent_.create(containerCOMP, 'light_desk')
    c.nodeX, c.nodeY = 300, -2200
    _hset(c, 'w', 1280)
    _hset(c, 'h', 820)
    pg = c.appendCustomPage('Desk')
    p = _hfirst(pg.appendStr('Url', label='Desk Address'))
    p.default = p.val = 'http://127.0.0.1:7020'
    _hfirst(pg.appendPulse('Reload', label='Reload Desk'))
    p = _hfirst(pg.appendToggle('Flipy', label='Flip Mouse Up/Down (if clicks land wrong)'))
    p.default = p.val = False

    w = c.create(webrenderTOP, 'desk')
    w.nodeX, w.nodeY = 0, 0
    _hset(w, 'url', "parent().par.Url", expr=True)
    _setres(w, 1280, 820)
    # what to show while the hub isn't running
    t = c.create(textTOP, 'waiting')
    t.nodeX, t.nodeY = 0, -150
    _hset(t, 'text', 'The Hue Hub is not running.\n\nIn Terminal:\n'
                     "cd '/Users/michaelney/Touchdesigner Designs/Hue Rig'\n"
                     'python3 hue_hub.py\n\nThe desk appears here by itself once it starts.')
    _setres(t, 1280, 820)
    _hset(t, 'fontsizex', 34)
    _hset(t, 'bgalpha', 1)
    v = c.create(switchTOP, 'view')
    v.nodeX, v.nodeY = 200, 0
    v.inputConnectors[0].connect(w)
    v.inputConnectors[1].connect(t)
    _hset(v, 'index', 1)
    # the desk (or the waiting note) is the panel's background. A COMP's own parameters look for
    # names next to the COMP, not inside it -- so point at the child explicitly.
    _hset(c, 'top', "me.op('view')", expr=True)

    m = c.create(executeDAT, 'mouse')
    m.nodeX, m.nodeY = 0, -200
    m.text = MOUSE_CODE
    _hset(m, 'frameend', True)
    _hset(m, 'active', True)

    kc = c.create(textDAT, 'keys_callbacks')
    kc.nodeX, kc.nodeY = 200, -350
    kc.text = KEYS_CODE
    k = c.create(keyboardinDAT, 'keys')
    k.nodeX, k.nodeY = 200, -200
    _hset(k, 'callbacks', kc.name)

    pe = c.create(parameterexecuteDAT, 'reload')
    pe.nodeX, pe.nodeY = 400, -200
    pe.text = ("def onPulse(par):\n"
               "    if par.name == 'Reload':\n"
               "        try:\n"
               "            op('desk').par.reload.pulse()\n"
               "        except Exception:\n"
               "            pass\n"
               "    return\n")
    _hset(pe, 'op', '..')
    _hset(pe, 'pars', 'Reload')
    _hset(pe, 'onpulse', True)
    _hset(pe, 'valuechange', False)
    return c


def start_hub():
    """Starts the Hue Hub in its own Terminal window (same as double-clicking
    'Start Hue Hub.command' in the Hue Rig folder)."""
    import subprocess
    cmd = os.path.join(HUB_BASE, 'Start Hue Hub.command')
    try:
        subprocess.Popen(['open', cmd])
        print('Starting the Hue Hub in a Terminal window -- the desk appears once it is running.')
    except Exception as e:
        print('Could not start it (%s). Double-click "Start Hue Hub.command" in the Hue Rig folder.' % e)


# ---------------------------------------------------------------------------------------------------
# THE PROCEDURAL PIECES -- generative art as GLSL pixel shaders, following the hub like the geometry:
#   proc_warp       domain warping (Inigo Quilez): noise bent by noise -- smoke, marble, liquid
#   proc_attractor  a strange attractor (Peter de Jong map, Paul Bourke) drawn with an orbit trap
#   proc_truchet    Truchet tiles: quarter-circle paths that re-route on the beat
#   proc_contours   contour lines of moving noise, like a living topographic map
#   proc_mandala    a signed-distance-field mandala with polar repetition; a ring ripples on every beat
#   proc_voronoi    Voronoi / Worley cells whose seeds dance and jump on the kick
#   proc_harmonograph  a pendulum drawing whose frequency ratios are musical intervals
#   proc_quasicrystal  5- / 7-fold plane waves: order that never repeats (the symmetry of Penrose tilings)
#   proc_life       a cellular automaton (Brian's Brain) that steps once per 8th note; the kick seeds it
# Each is a baseCOMP with the same controls as the Sacred Geometry (Scale, Rotate, Spin, Line Width, Glow,
# Build, Colour A/B), an out1, and a 'shader' DAT you can edit live. sync_geometry() builds any that are
# missing and puts them in geo_show's rotation; the music picks them phrase by phrase.
# Uniforms: uT = (time, beats, kick, loudness)  uS = (scale, rotate, glow, line)
#           uCa = (colour A, hats)  uCb = (colour B, snare)  uX = (build, drop, brightness of the sound, 0)
# ---------------------------------------------------------------------------------------------------
PROC_COMMON = r'''
uniform vec2 uRes;
uniform vec4 uT;
uniform vec4 uS;
uniform vec4 uCa;
uniform vec4 uCb;
uniform vec4 uX;
out vec4 fragColor;

float hash1(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
vec2 hash2(vec2 p) { float n = hash1(p); return vec2(n, hash1(p + n + 17.17)); }
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash1(i), b = hash1(i + vec2(1.0, 0.0)), c = hash1(i + vec2(0.0, 1.0)), d = hash1(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p) {
    float s = 0.0, a = 0.5;
    mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
    for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = m * p; a *= 0.5; }
    return s;
}
vec2 rot(vec2 p, float deg) { float a = radians(deg); float c = cos(a), s = sin(a); return mat2(c, s, -s, c) * p; }
vec2 centred() {
    vec2 res = max(uRes, vec2(1.0));
    return (vUV.st - 0.5) * vec2(res.x / res.y, 1.0);
}
vec4 finish(vec3 col) {
    col *= uS.z;                                   // glow: the room's brightness and the music's loudness
    col = col / (1.0 + 0.35 * max(col.r, max(col.g, col.b)));   // soft highlight roll-off, no hard clipping
    return TDOutputSwizzle(vec4(col, 1.0));
}
'''

PROC_SHADERS = {
    'proc_warp': r'''
void main() {
    vec2 p = rot(centred(), uS.y) * 1.7 / max(0.2, uS.x);
    float t = uT.x * 0.06;
    vec2 q = vec2(fbm(p + vec2(0.0, t)), fbm(p + vec2(5.2, 1.3) - t));
    float k = 2.2 + 2.6 * uT.z;
    vec2 r = vec2(fbm(p + k * q + vec2(1.7, 9.2) + 0.15 * t), fbm(p + k * q + vec2(8.3, 2.8) - 0.126 * t));
    float f = fbm(p + k * r);
    vec3 col = mix(uCa.rgb * 0.08, uCa.rgb, clamp(f * f * 2.4, 0.0, 1.0));
    col = mix(col, uCb.rgb, clamp(length(q) * 0.85, 0.0, 1.0) * 0.75);
    col += vec3(0.9) * pow(clamp(r.y, 0.0, 1.0), 4.0) * (0.25 + 0.6 * uCa.w);
    col *= 0.55 + 0.65 * uT.w;
    fragColor = finish(col);
}
''',
    'proc_attractor': r'''
void main() {
    vec2 z = rot(centred(), uS.y) * 1.6 / max(0.2, uS.x);
    float t = uT.x * 0.05;
    float a = 1.641 + 0.35 * sin(t * 0.9) + 0.12 * uT.z;
    float b = 1.902 + 0.30 * cos(t * 0.7);
    float c = 0.316 + 0.25 * sin(t * 0.5 + 1.0);
    float d = 1.525 + 0.30 * cos(t * 0.8 + 2.0);
    vec2 trapP = 0.6 * vec2(sin(t * 1.3), cos(t * 1.1));
    float trap = 1e9, acc = 0.0;
    for (int i = 0; i < 7; i++) {
        z = vec2(sin(a * z.y) - cos(b * z.x), sin(c * z.x) - cos(d * z.y));
        float dd = length(z - trapP);
        trap = min(trap, dd);
        acc += exp(-dd * 4.0);
    }
    float fil = exp(-trap * (6.0 - 2.0 * uT.w));
    vec3 col = mix(uCa.rgb, uCb.rgb, fract(acc * 0.06 + t * 0.2));
    col = col * fil * 1.6 + uCa.rgb * 0.04;
    col += vec3(1.0) * pow(fil, 6.0) * (0.3 + 0.7 * uCa.w);
    fragColor = finish(col * (0.6 + 0.6 * uT.w));
}
''',
    'proc_truchet': r'''
void main() {
    float n = 7.0 / max(0.2, uS.x);
    vec2 g = rot(centred(), uS.y) * n;
    vec2 id = floor(g);
    vec2 f = fract(g) - 0.5;
    float bar = floor(uT.y / 4.0), beat = floor(uT.y);
    float h = hash1(id + bar * 7.31);
    if (hash1(id * 1.7 + beat * 3.17) > 0.86) h = 1.0 - h;        // a few tiles flip on every beat
    if (h > 0.5) f.x = -f.x;
    float d = min(abs(length(f - 0.5) - 0.5), abs(length(f + 0.5) - 0.5));
    float w = 0.018 + 0.006 * uS.w * (1.0 + 1.5 * uCa.w);
    float line = smoothstep(w, w * 0.35, d);
    float halo = exp(-d * 28.0) * 0.45;
    float k = 0.5 + 0.5 * sin(id.x * 0.7 + id.y * 1.3 + uT.y * 0.785);
    vec3 col = mix(uCa.rgb, uCb.rgb, k) * (line + halo) * (0.55 + 0.75 * uT.z);
    fragColor = finish(col + uCa.rgb * 0.03);
}
''',
    'proc_contours': r'''
void main() {
    vec2 p = rot(centred(), uS.y) * 1.4 / max(0.2, uS.x);
    float t = uT.x * 0.05;
    float f = fbm(p * 1.5 + vec2(t, -0.7 * t)) + 0.35 * fbm(p * 3.1 - t);
    float lines = 12.0 + 8.0 * uT.z;
    float v = f * lines - uT.y * 0.25;
    float d = abs(fract(v) - 0.5) / max(fwidth(v), 1e-4);
    float l = 1.0 - clamp(d - 0.4 * uS.w, 0.0, 1.0);
    vec3 col = mix(uCa.rgb, uCb.rgb, clamp(fract(floor(v) * 0.137) + uCb.w * 0.5, 0.0, 1.0));
    col = col * l + uCa.rgb * 0.05 * f;
    fragColor = finish(col * (0.6 + 0.6 * uT.w));
}
''',
    'proc_mandala': r'''
void main() {
    vec2 p = rot(centred(), uS.y) / max(0.2, uS.x);
    float r = length(p), a = atan(p.y, p.x);
    float N = 8.0 + 4.0 * floor(mod(uT.y / 16.0, 2.0));
    float sec = 6.2831853 / N;
    float an = mod(a + sec * 0.5, sec) - sec * 0.5;
    vec2 q = vec2(cos(an), sin(an)) * r;
    float petal = length(q - vec2(0.24, 0.0)) - 0.085 * (1.0 + 0.35 * uT.z);
    float outer = abs(length(q - vec2(0.43, 0.0)) - 0.055);
    float ring1 = abs(r - 0.34) - 0.002;
    float ring2 = abs(r - 0.52) - 0.002;
    float ripple = abs(r - fract(uT.y) * 0.7) - 0.004;
    float d = min(min(abs(petal), outer), min(ring1, ring2));
    float w = 0.003 + 0.0015 * uS.w;
    float line = smoothstep(w, 0.0, d) + exp(-max(d, 0.0) * 45.0) * 0.35;
    float rip = (smoothstep(0.006, 0.0, ripple) + exp(-max(ripple, 0.0) * 30.0) * 0.4) * (1.0 - fract(uT.y));
    vec3 col = mix(uCa.rgb, uCb.rgb, smoothstep(0.15, 0.6, r)) * line + uCb.rgb * rip * (0.4 + 0.6 * uT.w);
    fragColor = finish(col * (0.7 + 0.5 * uT.w));
}
''',
    'proc_voronoi': r'''
void main() {
    vec2 p = rot(centred(), uS.y) * 4.5 / max(0.2, uS.x);
    vec2 i = floor(p), f = fract(p);
    float md = 8.0, md2 = 8.0;
    vec2 cell = vec2(0.0);
    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            vec2 g = vec2(float(x), float(y));
            vec2 o = hash2(i + g);
            o = 0.5 + 0.42 * sin(uT.x * 0.5 + 6.2831853 * o + uT.z * 0.6);
            vec2 rr = g + o - f;
            float dd = dot(rr, rr);
            if (dd < md) { md2 = md; md = dd; cell = i + g; } else if (dd < md2) { md2 = dd; }
        }
    }
    float e = sqrt(md2) - sqrt(md);
    float w = 0.035 + 0.008 * uS.w;
    float edge = smoothstep(w, 0.0, e) + exp(-e * 14.0) * 0.3;
    float k = hash1(cell);
    vec3 fill = mix(uCa.rgb, uCb.rgb, k) * (0.06 + 0.12 * uT.w);
    vec3 col = fill + mix(uCb.rgb, uCa.rgb, k) * edge * (0.6 + 0.7 * uT.z);
    col += vec3(1.0) * step(0.985, hash1(cell + floor(uT.y * 4.0))) * uCa.w * 0.4 * (1.0 - sqrt(md));
    fragColor = finish(col);
}
''',
    'proc_harmonograph': r'''
float segd(vec2 p, vec2 a, vec2 b) { vec2 pa = p - a, ba = b - a; float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0); return length(pa - ba * h); }
void main() {
    vec2 p = rot(centred(), uS.y) / max(0.2, uS.x);
    float ph = mod(floor(uT.y / 32.0), 6.0);
    vec2 R = ph < 0.5 ? vec2(2.0, 3.0) : ph < 1.5 ? vec2(3.0, 4.0) : ph < 2.5 ? vec2(4.0, 5.0)
           : ph < 3.5 ? vec2(3.0, 5.0) : ph < 4.5 ? vec2(1.0, 2.0) : vec2(5.0, 6.0);
    float t0 = uT.x * 0.12;
    float amp = 0.36 * (1.0 + 0.18 * uT.z);
    float d = 1e9, at = 0.0;
    vec2 prev = vec2(0.0);
    for (int i = 0; i < 240; i++) {
        float s = float(i) / 239.0 * 25.13;
        float dec = exp(-s * 0.045);
        vec2 q = amp * dec * vec2(sin(R.x * s + t0) + 0.4 * sin(R.y * s * 1.003 + 1.7),
                                  sin(R.y * s + 1.3 * t0 + 0.5) + 0.4 * sin(R.x * s * 0.997 + 0.4));
        if (i > 0) { float dd = segd(p, prev, q); if (dd < d) { d = dd; at = float(i) / 239.0; } }
        prev = q;
    }
    float w = 0.0018 + 0.0009 * uS.w * (1.0 + uCa.w);
    float line = smoothstep(w, 0.0, d) + exp(-d * 70.0) * 0.35;
    vec3 col = mix(uCa.rgb, uCb.rgb, at) * line * (0.6 + 0.6 * uT.w);
    fragColor = finish(col);
}
''',
    'proc_quasicrystal': r'''
void main() {
    vec2 p = rot(centred(), uS.y) * 22.0 / max(0.2, uS.x);
    float N = mod(floor(uT.y / 16.0), 2.0) < 0.5 ? 5.0 : 7.0;
    float v = 0.0;
    for (int k = 0; k < 7; k++) {
        if (float(k) >= N) break;
        float a = 3.14159265 * float(k) / N;
        v += cos(dot(p, vec2(cos(a), sin(a))) + uT.y * 0.785 + uT.x * 0.15);
    }
    v = 0.5 + 0.5 * v / N;
    float bands = 0.5 + 0.5 * cos(v * 3.14159265 * (5.0 + 3.0 * uT.z));
    float edge = pow(bands, 6.0);
    vec3 col = mix(uCa.rgb, uCb.rgb, v) * (0.15 + 0.85 * edge) * (0.55 + 0.6 * uT.w);
    col += vec3(1.0) * pow(bands, 30.0) * 0.25 * (0.4 + uCa.w);
    fragColor = finish(col);
}
''',
    'proc_life': r'''
void main() {
    vec2 res = max(uRes, vec2(1.0));
    vec2 q = rot(centred(), uS.y) / max(0.2, uS.x);
    vec2 uv = fract(q * vec2(res.y / res.x, 1.0) + 0.5);
    vec4 s = texture(sTD2DInputs[0], uv);
    vec3 col = uCa.rgb * s.r * 1.3 + uCb.rgb * s.g * 0.8 + mix(uCb.rgb, uCa.rgb, 0.5) * s.b * 0.35;
    fragColor = finish(col * (0.65 + 0.5 * uT.w + 0.4 * uT.z));
}
''',
}

LIFE_SIM = r'''
uniform vec4 uG;      // x = generation (8th notes), y = random seed, z = kick, w = 1 = start afresh
uniform vec2 uRes;
out vec4 fragColor;
float hash1(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
void main() {
    vec2 px = 1.0 / max(uRes, vec2(1.0));
    vec2 uv = vUV.st;
    vec4 c = texture(sTD2DInputs[0], uv);
    float tag = mod(uG.x, 256.0) / 256.0;
    if (abs(c.a - tag) < 0.5 / 256.0) { fragColor = c; return; }      // this generation is done: hold it
    float n = 0.0;
    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            if (x == 0 && y == 0) continue;
            n += step(0.5, texture(sTD2DInputs[0], fract(uv + vec2(float(x), float(y)) * px)).r);
        }
    }
    float on = step(0.5, c.r), dying = step(0.5, c.g);
    float non = (on < 0.5 && dying < 0.5 && abs(n - 2.0) < 0.5) ? 1.0 : 0.0;
    float ndy = on;
    float h = hash1(floor(uv / px) + uG.y);
    if (uG.w > 0.5) { non = step(0.72, h); ndy = 0.0; }
    if (h > 1.0 - 0.006 * uG.z) non = 1.0;
    float trail = max(c.b * 0.80, non);
    fragColor = vec4(non, ndy, trail, tag);
}
'''

PROC_VISUALS = list(PROC_SHADERS)
GEO_VISUALS = ['golden_angle', 'flower_of_life', 'metatrons_cube', 'sri_yantra', 'chladni', 'tesseract',
               'kaleidoscope', 'reaction_diffusion'] + PROC_VISUALS


def build_movie_in(where='/project1', feed='/project1/hue_feed'):
    """movie_in: the picture Movie mode follows. Three sources, switched by the desk (Setup > Movie mode):
      capture  a USB capture card (HDMI splitter: PS5 / PC -> projector + capture card)
      screen   this Mac's own screen (macOS asks to allow Screen Recording for TouchDesigner)
      camera   a webcam pointed at the projection (works with anything, no extra hardware)
    Each source only runs while Movie mode is on and it is the one chosen. Pick the device on 'capture' /
    'camera' (their Device parameter); trim the camera's view to just the screen with 'camera_crop'."""
    P = op(where)
    old = P.op('movie_in')
    if old is not None:
        if old.op('out1') is not None:
            return False
        old.destroy()                                 # a half-built one from an earlier error: start again
    F = "op('%s').par." % feed
    c = P.create(baseCOMP, 'movie_in')
    try:
        _build_movie_parts(c, F)
    except Exception:
        c.destroy()
        raise
    return True


def _build_movie_parts(c, F):
    c.nodeX, c.nodeY = 0, -1400
    srcs = []
    for name, kind in (('capture', videodeviceinTOP), ('screen', screengrabTOP), ('camera', videodeviceinTOP)):
        t = c.create(kind, name)
        t.nodeX, t.nodeY = 0, -len(srcs) * 150
        _hset(t, 'active', "bool(%sMovie.eval()) and %sMoviesrc.eval() == '%s'" % (F, F, name), expr=True)
        srcs.append(t)
    cr = c.create(cropTOP, 'camera_crop')
    cr.nodeX, cr.nodeY = 150, -300
    cr.inputConnectors[0].connect(srcs[2])
    pk = c.create(switchTOP, 'pick')
    pk.nodeX, pk.nodeY = 300, -150
    for i, t in enumerate([srcs[0], srcs[1], cr]):
        pk.inputConnectors[i].connect(t)
    _hset(pk, 'index', "['capture', 'screen', 'camera'].index(%sMoviesrc.eval())" % F, expr=True)
    o = c.create(outTOP, 'out1')
    o.nodeX, o.nodeY = 450, -150
    o.inputConnectors[0].connect(pk)


def _build_life_sim(comp, disp, F):
    """proc_life's simulation: a GLSL TOP fed back into itself (Feedback TOP), 192 x 120 cells, one
    generation per 8th note of the hub's beat; displayed by glsl1."""
    d = comp.create(textDAT, 'sim_shader')
    d.nodeX, d.nodeY = -400, 200
    d.text = LIFE_SIM
    init = comp.create(constantTOP, 'init')
    init.nodeX, init.nodeY = -600, 0
    for parname, val in (('outputresolution', 'custom'), ('resolutionw', 192), ('resolutionh', 120)):
        _hset(init, parname, val)
    fb = comp.create(feedbackTOP, 'fb')
    fb.nodeX, fb.nodeY = -400, 0
    fb.inputConnectors[0].connect(init)
    sim = comp.create(glslTOP, 'sim')
    sim.nodeX, sim.nodeY = -200, 0
    sim.par.pixeldat = d.name
    sim.inputConnectors[0].connect(fb)
    for parname in ('format', 'outputpixelformat', 'pixelformat'):
        if _hset(sim, parname, 'rgba16float'):
            break
    _hset(fb, 'top', 'sim')
    gen = "int(%sBeats.eval() * 2)" % F
    rows = [('uRes', ('192', '120')),
            ('uG', (gen, "(%s * 1.37) %% 997" % gen, F + 'Akick',
                    "1 if (%s %% 128 == 0 or absTime.frame < 90) else 0" % gen))]
    try:
        sim.seq.vec.numBlocks = len(rows)
    except Exception:
        sim.par.vec = len(rows)
    for k, (uname, exprs) in enumerate(rows):
        getattr(sim.par, 'vec%dname' % k).val = uname
        for letter, e in zip('xyzw', exprs):
            getattr(sim.par, 'vec%dvalue%s' % (k, letter)).expr = e
    disp.inputConnectors[0].connect(sim)


def build_procedural(where='/project1', feed='/project1/hue_feed', rebuild=False):
    """Builds the procedural pieces that are missing (or all of them with rebuild=True) and refreshes the
    shader code of the ones that exist. Returns the names built."""
    P = op(where)
    f = op(feed)
    F = "op('%s').par." % (f.path if f is not None else feed)
    made = []
    for i, name in enumerate(PROC_VISUALS):
        comp = P.op(name)
        if comp is not None and rebuild:
            comp.destroy()
            comp = None
        if comp is None:
            comp = P.create(baseCOMP, name)
            comp.nodeX, comp.nodeY = i * 220, -1100
            pg = comp.appendCustomPage('Sacred')
            for nm, label, d in (('Scale', 'Scale', 1.0), ('Rotate', 'Rotate (deg)', 0.0), ('Spin', 'Spin (deg/s)', 0.0),
                                 ('Linewidth', 'Line Width', 2.0), ('Glow', 'Glow', 1.0), ('Build', 'Build', 1.0)):
                q = _hfirst(pg.appendFloat(nm, label=label))
                q.default = q.val = d
            for nm, label, rgb in (('Colora', 'Colour A', (1.0, 0.45, 0.1)), ('Colorb', 'Colour B', (0.35, 0.2, 1.0))):
                for q, v in zip(pg.appendRGB(nm, label=label), rgb):
                    q.default = q.val = v
            rp = comp.appendCustomPage('Output')
            for q, v in zip(rp.appendWH('Res', label='Resolution'), (1280, 800)):
                q.default = q.val = v
            sh = comp.create(textDAT, 'shader')
            sh.nodeX, sh.nodeY = 0, 200
            g = comp.create(glslTOP, 'glsl1')
            g.nodeX, g.nodeY = 200, 0
            g.par.pixeldat = sh.name
            for parname, val, ex in (('outputresolution', 'custom', False), ('resolutionw', 'parent().par.Resw', True),
                                     ('resolutionh', 'parent().par.Resh', True)):
                try:
                    if ex:
                        getattr(g.par, parname).expr = val
                    else:
                        getattr(g.par, parname).val = val
                except Exception:
                    pass
            for parname in ('format', 'outputpixelformat', 'pixelformat'):
                try:
                    getattr(g.par, parname).val = 'rgba16float'
                    break
                except Exception:
                    pass
            rows = [('uRes', ('me.par.resolutionw', 'me.par.resolutionh')),   # own params: no cook loop
                    ('uT', ('absTime.seconds', F + 'Beats', F + 'Akick', F + 'Alevel')),
                    ('uS', ('parent().par.Scale', 'parent().par.Rotate + parent().par.Spin * absTime.seconds',
                            'parent().par.Glow', 'parent().par.Linewidth')),
                    ('uCa', ('parent().par.Colorar', 'parent().par.Colorag', 'parent().par.Colorab', F + 'Ahats')),
                    ('uCb', ('parent().par.Colorbr', 'parent().par.Colorbg', 'parent().par.Colorbb', F + 'Asnare')),
                    ('uX', ('parent().par.Build', F + 'Adrop', F + 'Abright', '0'))]
            try:
                g.seq.vec.numBlocks = len(rows)
            except Exception:
                g.par.vec = len(rows)
            for k, (uname, exprs) in enumerate(rows):
                getattr(g.par, 'vec%dname' % k).val = uname
                for letter, e in zip('xyzw', exprs):
                    getattr(g.par, 'vec%dvalue%s' % (k, letter)).expr = e
            o = comp.create(outTOP, 'out1')
            o.nodeX, o.nodeY = 400, 0
            o.inputConnectors[0].connect(g)
            if name == 'proc_life':
                _build_life_sim(comp, g, F)
            made.append(name)
        if name == 'proc_life' and comp.op('sim_shader') is not None and comp.op('sim_shader').text != LIFE_SIM:
            comp.op('sim_shader').text = LIFE_SIM
        sh = comp.op('shader')
        code = PROC_COMMON + PROC_SHADERS[name]
        if sh is not None and sh.text != code:
            sh.text = code                       # the newest version of the piece (your edits: rebuild=False keeps
    return made                                  # the comp, but the shader code follows this file)

# Mapper Pack generators that follow the hub (mp_strobe is left out on purpose: it is made to flash)
MAPPER_FX = ['mp_line_sweep', 'mp_barcode', 'mp_grid_pulse', 'mp_tunnel', 'mp_radar', 'mp_plasma', 'mp_edge_chase']
_SYNC_PARS = ['Rotate', 'Spin', 'Glow', 'Build', 'Scale', 'Linewidth', 'Brightness', 'Colorar', 'Colorag', 'Colorab', 'Colorbr', 'Colorbg',
              'Colorbb', 'Moden', 'Modem', 'Sign']
_FX_PARS = ['Sync', 'Bpm', 'Rate', 'Intensity', 'Kick', 'Colorar', 'Colorag', 'Colorab', 'Colorbr', 'Colorbg',
            'Colorbb']


def _remember(comp, names):
    """Your own settings, kept once so unsync_geometry() can put them back."""
    saved = comp.fetch('hue_sync_saved', None, search=False) or {}
    for pn in names:
        p = getattr(comp.par, pn, None)
        if p is None or pn in saved:
            continue
        try:
            if p.mode != ParMode.CONSTANT:
                continue
        except Exception:
            pass
        saved[pn] = p.eval()
    comp.store('hue_sync_saved', saved)
    return saved



# ---------------------------------------------------------------------------------------------------------
# INFINITY TUNNEL (v34): the Osmo (through the Cam Link) films the projection, and the picture is projected
# back slightly smaller, turned and colour-shifted -- so the room's own image falls into itself, forever.
# The kick pulls the tunnel deeper, the loudness twists it, the hats spin the colours, a drop bursts it.
# No camera? It builds the same tunnel from its own last frame, so it always works.
# SAFE BY DESIGN: everything projected passes 'tunnel_safe', which limits how fast the picture can brighten
# or darken (overall, and pixel by pixel) to the Flicker Guard -- a camera loop can never make it flash.
# geo_show > Tunnel page: On, Depth, Twist, Decay, Seed (how much of the geometry feeds it), Colour Shift.
# ---------------------------------------------------------------------------------------------------------
TUNNEL_TARGET = r"""
uniform vec2 uRes;
uniform vec4 uA;   // kick, loudness, drop, hats
uniform vec4 uP;   // depth (size of each copy), twist (deg per copy), decay (brightness kept per copy), seed
uniform vec4 uQ;   // colour shift per copy, camera on/off, unused, unused
out vec4 fragColor;
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
vec3 hueRot(vec3 c, float turns) {
    float a = turns * 6.2831853;
    vec3 k = vec3(0.57735);
    float ca = cos(a), sa = sin(a);
    return c * ca + cross(k, c) * sa + k * dot(k, c) * (1.0 - ca);
}
vec2 rot(vec2 p, float deg) { float a = radians(deg); float c = cos(a), s = sin(a); return mat2(c, s, -s, c) * p; }
void main() {
    vec2 uv = vUV.st;
    vec2 res = max(uRes, vec2(1.0));
    vec2 asp = vec2(res.x / res.y, 1.0);
    vec2 p = (uv - 0.5) * asp;
    float size = clamp(uP.x - 0.05 * uA.x - 0.06 * uA.z, 0.55, 0.97);      // the kick pulls it deeper
    float twist = uP.y * (1.0 + 0.6 * uA.y) + 20.0 * uA.z;                    // louder = more twist
    vec2 q = rot(p, twist) / size;
    vec2 quv = q / asp + 0.5;
    float inside = step(0.0, quv.x) * step(quv.x, 1.0) * step(0.0, quv.y) * step(quv.y, 1.0);
    float camAvg = luma(texture(sTD2DInputs[3], vec2(0.5)).rgb);
    float camOK = uQ.y * smoothstep(0.004, 0.02, camAvg);                     // camera picture present?
    vec3 rec = mix(texture(sTD2DInputs[2], quv).rgb, texture(sTD2DInputs[1], quv).rgb, camOK) * inside;
    rec = max(hueRot(rec, uQ.x * (1.0 + 1.5 * uA.w)), 0.0) * uP.z * (0.92 + 0.12 * uA.y);
    vec3 seed = texture(sTD2DInputs[0], uv).rgb * uP.w;
    vec3 col = max(seed, rec);                                               // the geometry rides on top
    float frameEdge = smoothstep(0.012, 0.0, min(min(quv.x, 1.0 - quv.x), min(quv.y, 1.0 - quv.y))) * inside;
    col += frameEdge * (0.25 + 0.5 * uA.x) * hueRot(vec3(0.9, 0.5, 1.0), uQ.x * 7.0);   // a glowing rim per copy
    fragColor = TDOutputSwizzle(vec4(min(col, vec3(1.0)), 1.0));
}
"""

TUNNEL_SAFE = r"""
uniform vec4 uL;   // per-pixel step, overall step (per frame), brightest average allowed, unused
out vec4 fragColor;
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
void main() {
    vec2 uv = vUV.st;
    vec3 t = texture(sTD2DInputs[0], uv).rgb;
    vec3 pr = texture(sTD2DInputs[1], uv).rgb;
    float lt = luma(texture(sTD2DInputs[2], vec2(0.5)).rgb);
    float lp = luma(texture(sTD2DInputs[3], vec2(0.5)).rgb);
    float cap = lt > uL.z ? uL.z / max(lt, 1e-5) : 1.0;     // never a white-out
    t *= cap; lt *= cap;
    vec3 d = clamp(t - pr, -uL.x, uL.x);                     // no pixel jumps
    float dg = abs(lt - lp);
    float k = dg > uL.y ? uL.y / dg : 1.0;                    // the whole picture brightens/darkens slowly
    fragColor = TDOutputSwizzle(vec4(clamp(pr + d * k, 0.0, 1.0), 1.0));
}
"""


def _glsl_inputs(g, tops):
    """A GLSL TOP's inputs 0, 1, 2 ... in this order, through its TOPs parameter (no wires needed)."""
    for conn in g.inputConnectors:
        try:
            conn.disconnect()
        except Exception:
            pass
    g.par.tops = ' '.join(t.path for t in tops)


def _tunnel_glsl(c, name, code, rows, x, y):
    sh = c.create(textDAT, name + '_code')
    sh.nodeX, sh.nodeY = x, y + 150
    sh.text = code
    g = c.create(glslTOP, name)
    g.nodeX, g.nodeY = x, y
    g.par.pixeldat = sh.name
    for parname in ('format', 'outputpixelformat', 'pixelformat'):
        try:
            getattr(g.par, parname).val = 'rgba16float'
            break
        except Exception:
            pass
    try:
        g.seq.vec.numBlocks = len(rows)
    except Exception:
        g.par.vec = len(rows)
    for k, (uname, exprs) in enumerate(rows):
        getattr(g.par, 'vec%dname' % k).val = uname
        for letter, e in zip('xyzw', exprs):
            getattr(g.par, 'vec%dvalue%s' % (k, letter)).expr = e
    return g


def _pick_camlink(cam):
    """Point the tunnel camera at the Cam Link (the Osmo) if it is plugged in."""
    try:
        p = cam.par.device
        names, labels = list(p.menuNames), list(p.menuLabels)
        for want in ('cam link', 'elgato', 'osmo'):
            for n_, l_ in zip(names, labels):
                if want in (str(n_) + ' ' + str(l_)).lower():
                    p.val = n_
                    return str(l_)
    except Exception:
        pass
    return None


def build_tunnel(c, seed, F, keep):
    """The infinity tunnel inside geo_show, after the trails. Returns the TOP to show."""
    pg = c.appendCustomPage('Tunnel')
    for nm, label, d, lo, hi in (('Depth', 'Depth (size of each copy)', 0.86, 0.55, 0.97),
                                 ('Twist', 'Twist (deg per copy)', 4.0, -45.0, 45.0),
                                 ('Decay', 'Decay (brightness kept)', 0.86, 0.5, 0.97),
                                 ('Seed', 'Seed (geometry in the tunnel)', 1.0, 0.0, 1.0),
                                 ('Hueshift', 'Colour Shift per Copy', 0.04, 0.0, 0.25)):
        q = _hfirst(pg.appendFloat(nm, label=label))
        q.default = d
        q.val = keep.get(nm, d)
        q.normMin, q.normMax = lo, hi
    q = _hfirst(pg.appendToggle('Tunnel', label='Infinity Tunnel On'))
    q.default = True
    q.val = keep.get('Tunnel', True)
    q = _hfirst(pg.appendToggle('Usecam', label='Use the Camera (Osmo / Cam Link)'))
    q.default = True
    q.val = keep.get('Usecam', True)
    q = _hfirst(pg.appendStr('Camera', label='Camera'))
    cam = c.create(videodeviceinTOP, 'tunnel_cam')
    cam.nodeX, cam.nodeY = 1100, -650
    _hset(cam, 'active', 'bool(parent().par.Tunnel) and bool(parent().par.Usecam)', expr=True)
    found = _pick_camlink(cam)
    q.val = found or 'Cam Link not found (plugged in?) -- using the digital tunnel'
    if not found:                       # never fall back to the Mac's own FaceTime camera
        c.par.Usecam = False
    crop = c.create(cropTOP, 'tunnel_cam_crop')                 # trim the camera's view to the projection
    crop.nodeX, crop.nodeY = 1250, -650
    crop.inputConnectors[0].connect(cam)
    for nm, label, d, parname in (('Cropl', 'Camera Crop Left', 0.28, 'cropleft'), ('Cropr', 'Camera Crop Right', 1.0, 'cropright'),
                                  ('Cropb', 'Camera Crop Bottom', 0.59, 'cropbottom'), ('Cropt', 'Camera Crop Top', 0.92, 'croptop')):
        q_ = _hfirst(pg.appendFloat(nm, label=label))
        q_.default = d
        q_.val = keep.get(nm, d)
        q_.normMin, q_.normMax = 0, 1
        _hset(crop, parname, 'parent().par.' + nm, expr=True)
    cavg = c.create(analyzeTOP, 'tunnel_cam_avg')
    cavg.nodeX, cavg.nodeY = 1400, -750
    cavg.inputConnectors[0].connect(crop)
    _hset(cavg, 'op', 'average')
    fb = c.create(feedbackTOP, 'tunnel_fb')
    fb.nodeX, fb.nodeY = 1250, -500
    fb.inputConnectors[0].connect(seed)
    tgt = _tunnel_glsl(c, 'tunnel_target', TUNNEL_TARGET, [
        ('uRes', ('me.par.resolutionw', 'me.par.resolutionh')),   # own params: no cook loop
        ('uA', (F + 'Akick', F + 'Alevel', F + 'Adrop', F + 'Ahats')),
        ('uP', ('parent().par.Depth', 'parent().par.Twist', 'parent().par.Decay', 'parent().par.Seed')),
        ('uQ', ('parent().par.Hueshift', '1 if parent().par.Usecam else 0', '0', '0'))], 1400, -500)
    _glsl_inputs(tgt, [seed, crop, fb, cavg])
    tavg = c.create(analyzeTOP, 'tunnel_target_avg')
    tavg.nodeX, tavg.nodeY = 1550, -650
    tavg.inputConnectors[0].connect(tgt)
    _hset(tavg, 'op', 'average')
    pavg = c.create(analyzeTOP, 'tunnel_prev_avg')
    pavg.nodeX, pavg.nodeY = 1550, -750
    pavg.inputConnectors[0].connect(fb)
    _hset(pavg, 'op', 'average')
    # Flicker Guard G flashes a second: a 10% swing and back takes >= 1/G s  ->  <= G/300 a frame at 60 fps
    safe = _tunnel_glsl(c, 'tunnel_safe', TUNNEL_SAFE, [
        ('uL', ('0.06', '0.8 * max(0.5, %sGuard) / (5.0 * max(30.0, project.cookRate))' % F, '0.55', '0'))], 1700, -500)
    _glsl_inputs(safe, [tgt, fb, tavg, pavg])
    _hset(fb, 'top', 'tunnel_safe')
    sw = c.create(switchTOP, 'tunnel_on')
    sw.nodeX, sw.nodeY = 1850, -100
    sw.inputConnectors[0].connect(seed)
    sw.inputConnectors[1].connect(safe)
    # shows the tunnel only while it is on AND its shaders are healthy (an error never blacks out the show)
    _hset(sw, 'index', "1 if (parent().par.Tunnel and not op('tunnel_target').errors() "
                       "and not op('tunnel_safe').errors()) else 0", expr=True)
    return sw



# ---------------------------------------------------------------------------------------------------------
# FULL RESOLUTION (v35): geo_show renders at the projector's own resolution (the Optoma: 1280 x 800), with
# optional supersampling (drawn bigger, then shrunk = smoother lines), and open_projector() puts it on the
# projector edge to edge, pixel for pixel -- no window borders, no scaling blur.
#   geo_show > Output page: Width, Height (the projector's pixels), Supersample (1x / 1.5x / 2x)
#   open_projector()   full screen on the projector      close_projector()   take it down
# ---------------------------------------------------------------------------------------------------------
def _projector_monitor():
    """(width, height, index, name) of the projector: the screen that isn't the Mac's own."""
    best = None
    try:
        for m in monitors:
            info = (int(m.width), int(m.height), int(m.index), str(getattr(m, 'displayName', '') or getattr(m, 'description', '')))
            if not getattr(m, 'isPrimary', False):
                if best is None or (info[0], info[1]) == (1280, 800):
                    best = info
    except Exception:
        pass
    return best


def _hires(top, wexpr, hexpr):
    _hset(top, 'outputresolution', 'custom')
    _hset(top, 'resolutionw', wexpr, expr=True)
    _hset(top, 'resolutionh', hexpr, expr=True)
    for fm in ('best', 'bestfit'):
        if _hset(top, 'fillmode', fm):
            break
    for parname in ('format', 'outputpixelformat', 'pixelformat'):
        try:
            getattr(top.par, parname).val = 'rgba16float'
            break
        except Exception:
            pass


def _full_res(c, P, visuals, keep):
    """The Output page of geo_show, and every picture in it (and the procedural pieces) at that resolution."""
    pm = _projector_monitor()
    dw, dh = (pm[0], pm[1]) if pm else (1280, 800)
    pg = c.appendCustomPage('Output')
    for q, v in zip(pg.appendWH('Res', label='Projector Resolution'), (keep.get('Resw', dw), keep.get('Resh', dh))):
        q.default = v
        q.val = v
    q = _hfirst(pg.appendMenu('Supersample', label='Supersample (smoother lines)'))
    q.menuNames = ['1', '1.5', '2']
    q.menuLabels = ['1x (fastest)', '1.5x (sharp)', '2x (sharpest)']
    q.default = '1.5'
    q.val = keep.get('Supersample', '1.5')
    q = _hfirst(pg.appendStr('Projector', label='Projector Found'))
    q.val = ('%s  %dx%d  (monitor %d)' % (pm[3], pm[0], pm[1], pm[2])) if pm else 'not connected -- using 1280 x 800'
    w_in = "int(parent().par.Resw * float(parent().par.Supersample.eval()))"
    h_in = "int(parent().par.Resh * float(parent().par.Supersample.eval()))"
    skip = ('analyzeTOP', 'videodeviceinTOP', 'cropTOP', 'outTOP')
    for t in c.children:
        if getattr(t, 'family', '') == 'TOP' and t.OPType not in skip:
            _hires(t, w_in, h_in)
    w_out = "int(op('%s').par.Resw * float(op('%s').par.Supersample.eval()))" % (c.path, c.path)
    h_out = "int(op('%s').par.Resh * float(op('%s').par.Supersample.eval()))" % (c.path, c.path)
    for name in visuals:                                    # the procedural pieces draw at that size natively
        comp = P.op(name)
        if comp is not None and name.startswith('proc_') and hasattr(comp.par, 'Resw'):
            comp.par.Resw.expr = w_out
            comp.par.Resh.expr = h_out
    # the finished picture leaves geo_show at exactly the projector's pixels (supersampling shrunk back down)
    try:
        fin = c.create(fitTOP, 'to_projector')
    except Exception:
        fin = c.create(selectTOP, 'to_projector')
    fin.nodeX, fin.nodeY = 2150, -100
    _hset(fin, 'outputresolution', 'custom')
    _hset(fin, 'resolutionw', 'parent().par.Resw', expr=True)
    _hset(fin, 'resolutionh', 'parent().par.Resh', expr=True)
    for ft in ('mipmap', 'linear'):
        if _hset(fin, 'filtertype', ft):
            break
    return fin


def open_projector(where='/project1'):
    """geo_show full screen on the projector, pixel for pixel."""
    P = op(where)
    show = P.op('geo_show')
    if show is None:
        print('No geo_show yet -- run sync_geometry()')
        return
    pm = _projector_monitor()
    w = P.op('projector_window') or P.create(windowCOMP, 'projector_window')
    w.nodeX, w.nodeY = 2100, -400
    target = P.op('show_out') or show.op('out1')         # show_out (your own mix) when it exists, else geo_show
    _hset(w, 'winop', target.path)
    _hset(w, 'title', 'Projector')
    _hset(w, 'borders', False)
    _hset(w, 'alwaysontop', True)
    _hset(w, 'cursorvisible', False)
    if pm:
        _hset(w, 'monitor', pm[2])
        for pn, v in (('winw', pm[0]), ('winh', pm[1]), ('winoffsetx', 0), ('winoffsety', 0)):
            _hset(w, pn, v)
        for pn, v in (('justifyh', 'left'), ('justifyv', 'top'), ('size', 'fill')):
            _hset(w, pn, v)
    else:
        print('No projector found -- opening it on this screen at 1280 x 800 (plug the projector in and run again).')
        _hset(w, 'winw', 1280)
        _hset(w, 'winh', 800)
    try:
        w.par.winopen.pulse()
    except Exception as e:
        print('Could not open the window: %s' % e)
        return
    print('The show is on %s at %s.  close_projector() takes it down.' % (
        pm[3] if pm else 'this screen', '%dx%d' % (pm[0], pm[1]) if pm else '1280x800'))


def close_projector(where='/project1'):
    w = op(where).op('projector_window')
    if w is not None:
        try:
            w.par.winclose.pulse()
        except Exception:
            pass


def build_show(P, feed, visuals, fx):
    """geo_show: the sacred geometry that matches what's playing (cross-fading between them),
    with a Mapper Pack effect added on top. Its output is the finished picture."""
    old = P.op('geo_show')
    keep = {}
    if old is not None:
        for pn in ('Fx', 'Fxmix', 'Fade', 'Hold', 'Morph', 'Curve', 'Order', 'Trails',
                   'Tunnel', 'Usecam', 'Depth', 'Twist', 'Decay', 'Seed', 'Hueshift', 'Resw', 'Resh', 'Supersample',
                   'Cropl', 'Cropr', 'Cropb', 'Cropt'):
            if hasattr(old.par, pn):
                keep[pn] = getattr(old.par, pn).eval()
        old.destroy()
    c = P.create(baseCOMP, 'geo_show')
    c.nodeX, c.nodeY = 1800, -400
    pg = c.appendCustomPage('Show')
    p = _hfirst(pg.appendMenu('Fx', label='Mapper Effect'))
    p.menuNames = ['none'] + fx
    p.menuLabels = ['None'] + [n.replace('mp_', '').replace('_', ' ').title() for n in fx]
    p.val = keep.get('Fx', fx[0] if 'mp_line_sweep' not in fx else 'mp_line_sweep') if fx else 'none'
    if p.val not in p.menuNames:
        p.val = 'none'
    p = _hfirst(pg.appendFloat('Fxmix', label='Effect Amount'))
    p.default = 0.35
    p.val = keep.get('Fxmix', 0.35)
    p.normMin, p.normMax = 0, 1
    p = _hfirst(pg.appendFloat('Trails', label='Trails (0 = off)'))
    p.default = 0.6
    p.val = keep.get('Trails', 0.6)
    p.normMin, p.normMax = 0, 0.95
    p = _hfirst(pg.appendFloat('Fade', label='Cross-fade (s)'))
    p.default = 0.4
    p.val = keep.get('Fade', 0.4)
    p.normMin, p.normMax = 0.05, 2
    # top row of pads: one geometry at 100%, held, then morphing into the next
    bp = c.appendCustomPage('Blend')
    p = _hfirst(bp.appendFloat('Hold', label='Hold Each (beats)'))
    p.default = 4.0
    p.val = keep.get('Hold', 4.0)
    p.normMin, p.normMax = 0, 16
    p = _hfirst(bp.appendFloat('Morph', label='Morph Into Next (beats)'))
    p.default = 4.0
    p.val = keep.get('Morph', 4.0)
    p.normMin, p.normMax = 0.25, 16
    p = _hfirst(bp.appendMenu('Curve', label='Morph Curve'))
    p.menuNames = ['sine', 'smooth', 'smoother', 'cubic', 'expo', 'circ', 'linear']
    p.menuLabels = ['Sine', 'Smoothstep', 'Smootherstep', 'Cubic', 'Exponential', 'Circular', 'Linear']
    p.val = keep.get('Curve', 'sine')
    p = _hfirst(bp.appendMenu('Order', label='Order'))
    p.menuNames = ['inorder', 'golden']
    p.menuLabels = ['In Order', 'Golden Steps']
    p.val = keep.get('Order', 'inorder')
    p = _hfirst(bp.appendStr('Showing', label='Showing'))
    for i in range(max(8, len(visuals))):
        q = _hfirst(bp.appendFloat('W%d' % i, label='Weight %d' % (i + 1)))
        q.val = 1.0 if i == 0 else 0.0
    F = "op('%s').par." % feed.path
    sels = []
    for i, name in enumerate(visuals):
        s_ = c.create(selectTOP, 'vis_%d' % i)
        s_.nodeX, s_.nodeY = 0, -i * 120
        _hset(s_, 'top', P.op(name).path + '/out1')
        sels.append(s_)
    # the top row of pads: one geometry at 100%, held, then morphing into the next (Blend page)
    n = len(sels)
    blend = c.create(compositeTOP, 'blend_all')
    blend.nodeX, blend.nodeY = 200, -(n + 1) * 120
    _hset(blend, 'operand', 'add')
    for i, s_ in enumerate(sels):
        w = c.create(levelTOP, 'weight_%d' % i)
        w.nodeX, w.nodeY = 100, -i * 120 - 60
        w.inputConnectors[0].connect(s_)
        _hset(w, 'opacity', 'parent().par.W%d' % i, expr=True)          # set by the blend sequencer
        blend.inputConnectors[i].connect(w)
    a = c.create(switchTOP, 'from_visual')
    b = c.create(switchTOP, 'to_visual')
    a.nodeX, a.nodeY, b.nodeX, b.nodeY = 300, 0, 300, -200
    for k, s_ in enumerate(sels + [blend]):           # the blend is the last input
        a.inputConnectors[k].connect(s_)
        b.inputConnectors[k].connect(s_)
    _hset(a, 'index', F + 'Forma', expr=True)
    _hset(b, 'index', F + 'Formb', expr=True)
    x = c.create(crossTOP, 'cross')
    x.nodeX, x.nodeY = 400, -100
    x.inputConnectors[0].connect(a)
    x.inputConnectors[1].connect(b)
    _hset(x, 'cross', F + 'Mix', expr=True)
    fsel = c.create(selectTOP, 'fx')
    fsel.nodeX, fsel.nodeY = 400, -300
    _hset(fsel, 'top', "'cross' if parent().par.Fx.eval() == 'none' else '%s/' + parent().par.Fx.eval() + '/out1'" % P.path,
          expr=True)
    lev = c.create(levelTOP, 'fx_amount')
    lev.nodeX, lev.nodeY = 600, -300
    lev.inputConnectors[0].connect(fsel)
    _hset(lev, 'opacity', "0 if parent().par.Fx.eval() == 'none' else parent().par.Fxmix", expr=True)
    add = c.create(addTOP, 'add')
    add.nodeX, add.nodeY = 800, -100
    add.inputConnectors[0].connect(x)
    add.inputConnectors[1].connect(lev)
    # TRAILS: the finished picture leaves a fading echo that drifts outward -- the kick throws it further
    fb = c.create(feedbackTOP, 'trail_fb')
    fb.nodeX, fb.nodeY = 800, -300
    fb.inputConnectors[0].connect(add)
    xf = c.create(transformTOP, 'trail_move')
    xf.nodeX, xf.nodeY = 900, -300
    xf.inputConnectors[0].connect(fb)
    for parname in ('sx', 'sy'):
        _hset(xf, parname, '1.004 + 0.03 * %sAkick + 0.06 * %sAdrop' % (F, F), expr=True)
    _hset(xf, 'rotate', '0.3 * parent().par.Trails', expr=True)
    lv = c.create(levelTOP, 'trail_fade')
    lv.nodeX, lv.nodeY = 1000, -300
    lv.inputConnectors[0].connect(xf)
    _hset(lv, 'opacity', 'min(0.95, parent().par.Trails)', expr=True)
    mx = c.create(compositeTOP, 'trail_mix')
    mx.nodeX, mx.nodeY = 1100, -100
    mx.inputConnectors[0].connect(add)
    mx.inputConnectors[1].connect(lv)
    for operand in ('maximum', 'max', 'add'):
        if _hset(mx, 'operand', operand):
            break
    _hset(fb, 'top', 'trail_mix')
    last = mx
    try:                                                   # the infinity tunnel (never allowed to break the show)
        last = build_tunnel(c, mx, F, keep)
    except Exception as e:
        import traceback
        print('  infinity tunnel: could not build (%s: %s)' % (type(e).__name__, e))
        c.store('tunnel_error', traceback.format_exc()[-900:])
    try:                                                   # every picture at the projector's resolution
        fin = _full_res(c, P, visuals, keep)
        fin.inputConnectors[0].connect(last)
        last = fin
    except Exception as e:
        import traceback
        print('  full resolution: could not set up (%s: %s)' % (type(e).__name__, e))
        c.store('res_error', traceback.format_exc()[-900:])
    o = c.create(outTOP, 'out1')
    o.nodeX, o.nodeY = 2300, -100
    o.inputConnectors[0].connect(last)
    _hset(c, 'opviewer', "me.op('out1')", expr=True)
    try:
        c.viewer = True
    except Exception:
        pass
    c.store('visuals', list(visuals) + ['__blend__'])
    return c


def sync_geometry(feed='/project1/hue_feed', where='/project1'):
    """The Sacred Geometry visuals and the Mapper Pack effects follow the hub: the room's colours,
    the geometry clock, and the pads you touch (row = which geometry, column = its shape; pressing
    harder makes it bigger; the room's brightness makes it glow). geo_show shows the visual that
    matches what's playing, with an effect on top. Run it again after adding more visuals.
    unsync_geometry() undoes it."""
    f = op(feed)
    P = op(where)
    if f is None or not hasattr(f.par, 'Build'):
        print('hue_feed is from before this update -- run build_hue_hub_td.py first, then sync_geometry().')
        return
    F = "op('%s').par." % f.path
    try:
        if build_movie_in(where, f.path):
            print('  movie_in built (Movie mode: capture card / this screen / camera)')
    except Exception as e:
        print('  movie_in: could not build (%s: %s)' % (type(e).__name__, e))
    try:
        built = build_procedural(where, f.path)
        if built:
            print('  procedural pieces built: %s' % ', '.join(built))
    except Exception as e:
        print('  procedural pieces: could not build (%s: %s)' % (type(e).__name__, e))
    done, missing, fxdone = [], [], []
    for name in GEO_VISUALS:
        comp = P.op(name)
        if comp is None or comp.op('out1') is None:
            missing.append(name)
            continue
        saved = _remember(comp, _SYNC_PARS)
        vi = GEO_VISUALS.index(name)
        if 'Rotate' in saved:        # turns with the lamps, plus an extra turn from where you play across the pads
            _hset(comp, 'Rotate', '%s + %sGeorot + %sTurn' % (saved['Rotate'], F, F), expr=True)
            _hset(comp, 'Spin', 0.0)
        if 'Brightness' in saved:    # reaction-diffusion: glows with the room
            _hset(comp, 'Brightness', '%s * (0.55 + 0.9 * %sEnergy) * (0.8 + 0.4 * %sAlevel) * %sMaster'
                  % (saved['Brightness'], F, F, F), expr=True)
        if 'Glow' in saved:          # the room's brightness + the music's loudness make it glow; the snare lifts it
            _hset(comp, 'Glow', '%s * (0.55 + 0.9 * %sEnergy) * (0.7 + 0.5 * %sAlevel + 0.4 * %sAsnare) * %sMaster'
                  % (saved['Glow'], F, F, F, F), expr=True)
        if 'Build' in saved:         # left pads partly drawn, right pads whole
            _hset(comp, 'Build', F + 'Build', expr=True)
        if 'Scale' in saved:         # left pads smaller, right pads bigger; press harder = a little bigger
            # ...the kick pumps it (like the lamps), the drop bursts it outwards
            _hset(comp, 'Scale', '%s * %sZoom * (1 + 0.12 * %sPress + 0.2 * %sAkick + 0.25 * %sAdrop)'
                  % (saved['Scale'], F, F, F, F), expr=True)
        if 'Linewidth' in saved:     # left pads thin lines, right pads bold; the hats make the lines shimmer
            _hset(comp, 'Linewidth', '%s * %sLine * (1 + 0.5 * %sAhats)' % (saved['Linewidth'], F, F), expr=True)
        if 'Colorar' in saved:       # its own colours: the room's two, or on the top row one lamp each
            for a_, ab in (('Colora', 'a'), ('Colorb', 'b')):
                for ch in 'rgb':
                    if vi < 8:
                        _hset(comp, a_ + ch, '%sVc%d%s%s' % (F, vi, ab, ch), expr=True)
                    else:                    # the procedural pieces: the room's two colours
                        _hset(comp, a_ + ch, '%sGeocol%s%s' % (F, ab, ch), expr=True)
        if name == 'chladni':
            _hset(comp, 'Moden', F + 'Chladn', expr=True)
            _hset(comp, 'Modem', F + 'Chladm', expr=True)
            _hset(comp, 'Sign', F + 'Chladsign', expr=True)
        done.append(name)
    for name in MAPPER_FX:
        comp = P.op(name)
        if comp is None or not hasattr(comp.par, 'Rate'):
            continue
        saved = _remember(comp, _FX_PARS)
        _hset(comp, 'Sync', True)
        _hset(comp, 'Bpm', F + 'Tempo', expr=True)
        # never more cycles a second than the Flicker Guard allows
        cap = '%sGuard * 60.0 / max(40.0, %sTempo)' % (F, F)
        _hset(comp, 'Rate', 'max(-(%s), min(%s, %s))' % (cap, cap, saved.get('Rate', 0.5)), expr=True)
        _hset(comp, 'Intensity', '%s * (0.6 + 0.6 * %sEnergy) * %sMaster' % (saved.get('Intensity', 1.0), F, F),
              expr=True)
        _hset(comp, 'Kick', 'max(%sPress, %sAkick)' % (F, F), expr=True)
        for a_, b_ in (('Colora', 'Geocola'), ('Colorb', 'Geocolb')):
            for ch in 'rgb':
                _hset(comp, a_ + ch, F + b_ + ch, expr=True)
        fxdone.append(name)
    visuals = [n for n in GEO_VISUALS if n in done]
    show = None
    if visuals:
        show = build_show(P, f, visuals, fxdone)
        _hset(f, 'Showpath', show.path)
    gv = P.op('geo_visual')                        # from the first version: keep it following along
    if gv is not None:
        _hset(gv, 'index', F + 'Formb', expr=True)
    print('')
    print('SACRED GEOMETRY + MAPPER FX IN STEP WITH THE ROOM')
    print('  geometry following the hub: ' + (', '.join(done) or 'nothing'))
    if missing:
        print('  not in this project yet:    ' + ', '.join(missing))
    print('  mapper effects following:   ' + (', '.join(fxdone) or 'none (build the Mapper Pack to add them)'))
    if P.op('mp_strobe') is not None:
        print('  mp_strobe is left alone -- it is made to flash')
    if show is not None:
        print('  geo_show = the finished picture: it fades to the visual that matches what is playing')
        print('  (the top row of pads: all of them blended together),')
        print('  with a mapper effect on top (geo_show > Show page: Mapper Effect, Effect Amount).')
        print('  Look at it:  open_show()   On the projector, full res:  open_projector()   Undo all of this:  unsync_geometry()')
    print('')


def open_show(path='/project1/geo_show'):
    """The show full screen on the projector (your extended display): no borders, pixel for pixel."""
    open_projector('/'.join(path.split('/')[:-1]) or '/project1')


def open_viewer(path='/project1/geo_show'):
    """The old floating preview window (for looking at it on the Mac's own screen)."""
    s = op(path)
    if s is None:
        print('No geo_show yet -- run sync_geometry()')
        return
    try:
        s.openViewer(unique=True, borders=True)
    except TypeError:
        s.openViewer()


def geo_check(feed='/project1/hue_feed', where='/project1'):
    """What the Sacred Geometry is following -- prints it and saves td_check.txt in the Hue Rig folder."""
    f = op(feed)
    P = op(where)
    out = ['', 'GEOMETRY CHECK  (%s)' % absTime.seconds]

    def errs(o):
        try:
            return o.errors(recurse=True) or 'none'
        except TypeError:
            return o.errors() or 'none'
    def add(label, fn):
        try:
            out.append('  %-28s %s' % (label, fn()))
        except Exception as e:
            out.append('  %-28s ERROR %s: %s' % (label, type(e).__name__, e))
    add('hue_feed', lambda: f.path if f is not None else 'MISSING -- run build_hue_hub_td.py')
    if f is not None:
        for n in ('Syncstatus', 'Status', 'Vis', 'Formb', 'Mix', 'Georot', 'Energy', 'Build', 'Zoom', 'Turn', 'Line',
                  'Akick', 'Asnare', 'Ahats', 'Alevel', 'Adrop', 'Section', 'Master'):
            add('feed.' + n, lambda n=n: getattr(f.par, n).eval() if hasattr(f.par, n) else 'no such parameter (old hue_feed)')
        add('feed send DAT', lambda: (f.op('send').par.active.eval(), f.op('send').errors() or 'no errors'))
    for name in GEO_VISUALS + MAPPER_FX[:2]:
        comp = P.op(name)
        if comp is None:
            out.append('  %-28s not in %s' % (name, where))
            continue
        for n in ('Rotate', 'Spin', 'Scale', 'Glow', 'Build', 'Linewidth', 'Brightness', 'Colorar', 'Kick', 'Rate'):
            q = getattr(comp.par, n, None)
            if q is None:
                continue
            add('%s.%s' % (name, n), lambda q=q: '%s = %.3f  %s' % (
                str(q.mode).split('.')[-1], float(q.eval()), q.expr if q.expr else ''))
        add(name + ' errors', lambda comp=comp: errs(comp))
    sh = P.op('geo_show')
    add('geo_show', lambda: 'exists' if sh is not None else 'MISSING -- run sync_geometry()')
    if sh is not None:
        add('geo_show.Showing', lambda: sh.par.Showing.eval())
        add('geo_show weights', lambda: [round(getattr(sh.par, 'W%d' % i).eval(), 2) for i in range(32)
                                         if hasattr(sh.par, 'W%d' % i)])
        add('geo_show visuals', lambda: sh.fetch('visuals', [], search=False))
        add('geo_show errors', lambda: errs(sh))
        add('geo_show out1 size', lambda: (sh.op('out1').width, sh.op('out1').height))
        add('geo_show drawing size', lambda: (sh.op('trail_mix').width, sh.op('trail_mix').height))
        add('geo_show Output', lambda: (sh.par.Resw.eval(), sh.par.Resh.eval(), sh.par.Supersample.eval(),
                                        sh.par.Projector.eval()))
        add('tunnel on / camera', lambda: (sh.par.Tunnel.eval(), sh.par.Usecam.eval(), sh.par.Camera.eval()))
        add('tunnel build error', lambda: sh.fetch('tunnel_error', 'none', search=False))
        add('resolution build error', lambda: sh.fetch('res_error', 'none', search=False))
        add('tunnel shader errors', lambda: (sh.op('tunnel_target').errors() or 'none', sh.op('tunnel_safe').errors() or 'none'))
        add('tunnel showing', lambda: sh.op('tunnel_on').par.index.eval())
        add('tunnel cam size', lambda: (sh.op('tunnel_cam').width, sh.op('tunnel_cam').height, sh.op('tunnel_cam').par.device.eval()))
        for vn in sh.fetch('visuals', [], search=False):
            if vn != '__blend__' and P.op(vn) is not None and P.op(vn).op('out1') is not None:
                add('  size ' + vn, lambda vn=vn: (P.op(vn).op('out1').width, P.op(vn).op('out1').height))
    add('monitors', lambda: [(m.index, m.width, m.height, bool(getattr(m, 'isPrimary', False)),
                              str(getattr(m, 'displayName', ''))) for m in monitors])
    if sh is not None:                                     # snapshots of each stage + the GLSL compile logs
        snapdir = os.path.join(HUB_BASE, 'td_snaps')
        try:
            os.makedirs(snapdir, exist_ok=True)
        except OSError:
            pass
        for nm in ('cross', 'add', 'trail_mix', 'tunnel_target', 'tunnel_safe', 'tunnel_on', 'to_projector', 'out1'):
            t = sh.op(nm)
            if t is not None:
                add('snap ' + nm, lambda t=t, nm=nm: (t.save(os.path.join(snapdir, nm + '.png')), t.width, t.height,
                                                     t.par.outputresolution.eval() if hasattr(t.par, 'outputresolution') else '-')[1:])
        for nm in ('tunnel_target', 'tunnel_safe'):
            g = sh.op(nm)
            if g is not None:
                def log(g=g):
                    i = sh.create(infoDAT, '_chk_info')
                    try:
                        i.par.op = g.path
                        i.cook(force=True)
                        txt = ' | '.join(str(c_.val) for r_ in i.rows() for c_ in r_)
                        k_ = txt.find('Pixel Shader')
                        return (txt[k_:k_ + 700] if k_ >= 0 else txt[:700]) or 'clean'
                    finally:
                        i.destroy()
                add('compile log ' + nm, log)
    if sh is not None and sh.op('tunnel_target') is not None:
        g_ = sh.op('tunnel_target')
        add('glsl seqs', lambda: [q.name for q in g_.seq])
        add('trail_mix res pars', lambda: (sh.op('trail_mix').par.resolutionw.expr, sh.op('trail_mix').par.resolutionw.eval(),
                                           str(sh.op('trail_mix').par.resolutionw.mode), sh.op('trail_mix').par.outputresolution.eval(),
                                           [p_.name for p_ in sh.op('trail_mix').pars() if 'res' in p_.name.lower()]))
        add('glsl inputs', lambda: ([i_.name for i_ in g_.inputs], [i_.name for i_ in sh.op('tunnel_safe').inputs]))
    mc = op('/project1/mcp_webserver_base')
    if mc is not None:                                      # the Claude connection (TouchDesigner MCP)
        def mcp_diag():
            import sys, traceback
            ext = mc.par.externaltox.eval()
            absx = ext if os.path.isabs(ext) else os.path.join(project.folder, ext)
            mods = os.path.join(os.path.dirname(absx), 'modules')
            res = {'externaltox': ext, 'abs': absx, 'modules_exists': os.path.isdir(mods),
                   'children': [c_.name + ':' + c_.OPType for c_ in mc.children]}
            try:
                import yaml
                res['yaml'] = 'ok ' + getattr(yaml, '__version__', '?')
            except Exception as e:
                res['yaml'] = 'MISSING %s' % e
            try:
                im = mc.op('import_modules')
                res['import_modules_dat'] = im is not None
                if im is not None:
                    im.module.setup()
                    res['setup'] = 'ok'
            except Exception as e:
                res['setup'] = 'FAILED ' + traceback.format_exc()[-700:]
            try:
                import mcp
                res['import mcp'] = 'ok ' + str(getattr(mcp, '__file__', ''))
            except Exception as e:
                res['import mcp'] = 'FAILED %s' % e
            return res
        add('claude mcp', mcp_diag)
    pw = P.op('projector_window')
    add('projector window', lambda: 'not made yet' if pw is None else (pw.isOpen, pw.par.winop.eval()))
    print('\n'.join(out) + '\n')
    try:
        with open(os.path.join(HUB_BASE, 'td_check.txt'), 'a', encoding='utf-8') as fh:
            fh.write('\n'.join(str(l) for l in out) + '\n')
        print('Saved to td_check.txt in the Hue Rig folder.')
    except OSError as e:
        print('Could not save td_check.txt: %s' % e)


def unsync_geometry(where='/project1'):
    """Gives the Sacred Geometry visuals and mapper effects their own settings back."""
    P = op(where)
    for name in GEO_VISUALS + MAPPER_FX:
        comp = P.op(name)
        if comp is None:
            continue
        saved = comp.fetch('hue_sync_saved', None, search=False) or {}
        for pn, v in saved.items():
            p = getattr(comp.par, pn, None)
            if p is not None:
                try:
                    p.expr = ''
                    p.mode = ParMode.CONSTANT
                except Exception:
                    pass
                p.val = v
        try:
            comp.unstore('hue_sync_saved')
        except Exception:
            pass
    print('Visuals and effects are on their own settings again (geo_show is left in place).')


def _desk_log(lines):
    try:
        with open(os.path.join(HUB_BASE, 'td_desk_log.txt'), 'a') as f:
            f.write('\n'.join(str(l) for l in lines) + '\n')
    except OSError:
        pass


def desk_check(path='/project1/light_desk'):
    """Prints what the desk is doing -- send me a screenshot of this."""
    import socket
    d = op(path)
    if d is None:
        print('No light_desk -- run build_hue_hub_td.py')
        return
    out = ['', 'DESK CHECK']
    def add(label, fn):
        try:
            out.append('  %-26s %s' % (label, fn()))
        except Exception as e:
            out.append('  %-26s ERROR %s: %s' % (label, type(e).__name__, e))
    add('background (top) expr', lambda: d.par.top.expr)
    add('background (top) value', lambda: d.par.top.eval())
    add('view index (0=desk 1=note)', lambda: op(path + '/view').par.index.eval())
    add('view size', lambda: (op(path + '/view').width, op(path + '/view').height))
    add('waiting note text', lambda: op(path + '/waiting').par.text.eval()[:40])
    add('desk url', lambda: op(path + '/desk').par.url.eval())
    add('desk page loaded', lambda: op(path + '/desk').loaded)
    add('desk size', lambda: (op(path + '/desk').width, op(path + '/desk').height))
    for n in ('desk', 'view', 'waiting', 'mouse'):
        add(n + ' errors', lambda n=n: (op(path + '/' + n).errors() or 'none') + ' / ' + (op(path + '/' + n).warnings() or 'none'))
    def hub():
        s = socket.create_connection(('localhost', 7020), timeout=0.2)
        s.close()
        return 'running'
    add('Hue Hub on port 7020', hub)
    print('\n'.join(out) + '\n')
    _desk_log(out)


def desk_fix(path='/project1/light_desk'):
    """Points the desk at the hub, sizes it, reloads it, and shows what it found."""
    d = op(path)
    w = d.op('desk') if d else None
    if w is None:
        print('No light_desk -- run build_hue_hub_td.py')
        return
    names = ['%s=%s' % (p.name, p.eval()) for p in w.pars()
             if any(k in p.name.lower() for k in ('res', 'url', 'reload', 'active', 'src', 'size', 'w', 'h'))
             and len(p.name) < 24]
    print('Web Render settings found:', ', '.join(names))
    _desk_log(['', 'DESK FIX', 'all web render pars: ' + ', '.join(p.name for p in w.pars())])
    d.par.Url = 'http://127.0.0.1:7020'
    for p in w.pars():
        if p.name.lower() in ('url', 'urlorfile', 'address'):
            try:
                p.expr = "parent().par.Url"
            except Exception:
                pass
    print('size set with:', _setres(w, 1280, 820) or 'nothing matched', '-> now', (w.width, w.height))
    _setres(d.op('waiting'), 1280, 820)
    for n in ('reload', 'reloadsrc'):
        try:
            getattr(w.par, n).pulse()
            print('pulsed', n)
        except Exception:
            pass
    print('Give it two seconds, then run  desk_check()  again.')


def open_desk(path='/project1/light_desk'):
    """Opens the Light Desk in its own window inside TouchDesigner."""
    d = op(path)
    if d is None:
        print('No light_desk yet -- run build_hue_hub_td.py')
        return
    try:
        d.openViewer(unique=True, borders=True)
    except TypeError:
        d.openViewer()


_hub_lines = ['', 'HUE HUB (TouchDesigner side)', '----------------------------']
_P = op('/project1') or op('/')
try:
    _feed = build_feed(_P)
    _hub_lines.append('OK    hue_feed   (picture + beat -> the hub, port 7011)')
    for _name in ('surface_right', 'mp_line_sweep', 'mp_plasma', 'mp_grid_pulse'):
        if _P.op(_name) is not None:
            _feed.inputConnectors[0].connect(_P.op(_name).outputConnectors[0])
            _hub_lines.append('      %s is wired into hue_feed -- wire any picture you like' % _name)
            break
    else:
        _hub_lines.append('      wire the picture you want the lamps to see into hue_feed')
except Exception as _e:
    _hub_lines.append('FAIL  hue_feed  %s: %s' % (type(_e).__name__, _e))
try:
    build_desk(_P)
    _hub_lines.append('OK    light_desk (open it:  open_desk() )')
except Exception as _e:
    _hub_lines.append('FAIL  light_desk  %s: %s' % (type(_e).__name__, _e))
if _P.op('show_clock') is None:
    _hub_lines.append('      no show_clock yet -- the hub keeps its own beat (or build_show_clock.py)')
_old = _P.op('hue_rig')
if _old is not None and hasattr(_old.par, 'Active'):
    try:
        _old.par.Active = False
        _hub_lines.append('      old hue_rig: "Send to the Lights" switched off (the hub drives the lamps now)')
    except Exception:
        pass
if any(_P.op(_n) is not None for _n in GEO_VISUALS + MAPPER_FX):
    _hub_lines.append('      Sacred Geometry / Mapper Pack found -- sync_geometry() puts them in step with the room')
_hub_lines += ['', 'Next, here in the Textport:   start_hub()   then   open_desk()', '']
print('\n'.join(_hub_lines))
