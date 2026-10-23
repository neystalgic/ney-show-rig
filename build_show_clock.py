# =============================================================================
# SHOW CLOCK -- one beat for the whole show
#
# Builds show_clock in /project1: follows Ableton Live's tempo and beat
# through Ableton Link (or runs on its own BPM with Tap), and hands that beat
# to the lamps and the Mapper Pack animations so everything hits together.
#
#   exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/build_show_clock.py').read())
#
# Then:  follow_all()     -> hue_rig and every mp_ animation follow the clock
# In Live: switch on "Link" (top-left of the window, next to the tempo).
# Safe to run again: it replaces only show_clock.
# =============================================================================

import os

SC_BASE = '/Users/michaelney/Touchdesigner Designs/Hue Rig'
SC_PATH = '/project1/show_clock'


def _sc_first(g):
    try:
        return g[0]
    except Exception:
        return g


def _sc_set(o, name, value):
    try:
        setattr(o.par, name, value)
        return True
    except Exception:
        return False


TICK = r'''# show_clock -- works out the show's beat every frame
import math
import time

_S = {'beats': 0.0, 'wall': None, 'taps': []}
NAMES = {'beats': ('beats', 'beat_total', 'totalbeats'), 'ramp': ('rampbeat', 'beatramp'),
         'tempo': ('tempo', 'bpm'), 'linked': ('linked',), 'peers': ('numpeers', 'peers')}


def _ch(chop, key):
    if chop is None:
        return None
    for n in NAMES[key]:
        try:
            c = chop.chan(n)
        except Exception:
            c = None
        if c is not None:
            return float(c.eval())
    return None


def link_beats(chop):
    """(beats, tempo, peers) from the Ableton Link CHOP, or None."""
    b, r, tempo = _ch(chop, 'beats'), _ch(chop, 'ramp'), _ch(chop, 'tempo')
    if b is None or tempo is None:
        return None
    if r is not None:                            # whole beats + where we are inside this beat
        x = math.floor(b) + r
        if x - b > 0.5:
            x -= 1.0
        elif b - x > 0.5:
            x += 1.0
        b = x
    peers = _ch(chop, 'peers')
    return b, tempo, peers


def requests(c, now):
    reqs = c.fetch('reqs', [], storeDefault=True)
    if not reqs:
        return
    c.store('reqs', [])
    bpb = max(1, int(c.par.Beatsperbar.eval()))
    for r in reqs:
        if r == 'tap':
            taps = [t for t in _S['taps'] if now - t < 2.5] + [now]
            _S['taps'] = taps[-5:]
            if len(_S['taps']) >= 2:
                gaps = [b - a for a, b in zip(_S['taps'], _S['taps'][1:])]
                c.par.Bpm = max(40.0, min(240.0, 60.0 / (sum(gaps) / len(gaps))))
            _S['beats'] = float(round(_S['beats']))          # this tap is on a beat
        elif r == 'downbeat':                                  # now = beat 1 of a bar
            cur = c.fetch('rawbeats', 0.0) + c.par.Offset.eval()
            c.par.Offset = c.par.Offset.eval() + (round(cur / bpb) * bpb - cur)


def onFrameEnd(frame):
    c = parent()
    now = time.time()
    dt = 0.0 if _S['wall'] is None else max(0.0, min(0.25, now - _S['wall']))
    _S['wall'] = now
    requests(c, now)

    status = ''
    lk = None
    if c.par.Source.eval() == 'link':
        lk = link_beats(op('link'))
        if lk is None:
            status = 'Ableton Link CHOP not giving beats -- running on BPM below'
        elif lk[2] is not None and lk[2] < 1:
            status = 'Waiting for Ableton Link -- switch on Link in Live'
            lk = None
    if lk is not None:
        raw, tempo = lk[0], lk[1]
        _S['beats'] = raw
        status = 'Following Ableton Link (%d peer%s)' % (lk[2] or 0, '' if (lk[2] or 0) == 1 else 's') \
            if lk[2] is not None else 'Following Ableton Link'
    else:
        tempo = c.par.Bpm.eval()
        _S['beats'] += dt * tempo / 60.0
        raw = _S['beats']
        if not status:
            status = 'Free running at %.1f BPM' % tempo
    c.store('rawbeats', raw)
    beats = raw + c.par.Offset.eval()
    bpb = max(1, int(c.par.Beatsperbar.eval()))
    for name, v in (('Beats', beats), ('Tempo', tempo), ('Bar', int(math.floor(beats / bpb)) + 1),
                    ('Beat', int(math.floor(beats)) % bpb + 1)):
        p = getattr(c.par, name)
        if p.eval() != v:
            p.val = v
    if c.par.Status.eval() != status:
        c.par.Status = status
    return
'''

BUTTONS = '''ACTIONS = {'Tap': 'tap', 'Downbeat': 'downbeat'}

def onPulse(par):
    c = par.owner
    if par.name in ACTIONS:
        c.store('reqs', list(c.fetch('reqs', [])) + [ACTIONS[par.name]])
    return
'''


def build_show_clock():
    parent_ = op('/project1')
    old = parent_.op('show_clock')
    if old is not None:
        old.destroy()
    c = parent_.create(baseCOMP, 'show_clock')
    c.nodeX, c.nodeY = -400, -1900

    pg = c.appendCustomPage('Clock')
    p = _sc_first(pg.appendMenu('Source', label='Source'))
    p.menuNames = ['link', 'free']
    p.menuLabels = ['Ableton Link (follow Live)', 'Free (BPM below)']
    p.default = p.val = 'link'
    for name, label, d, lo, hi in (('Bpm', 'BPM (Free / fallback)', 140, 40, 240),
                                   ('Offset', 'Nudge (beats)', 0, -4, 4)):
        q = _sc_first(pg.appendFloat(name, label=label))
        q.default = q.val = d
        q.normMin, q.normMax = lo, hi
    _sc_first(pg.appendPulse('Tap', label='Tap Tempo (Free)'))
    _sc_first(pg.appendPulse('Downbeat', label='Now Is Beat 1'))
    q = _sc_first(pg.appendInt('Beatsperbar', label='Beats per Bar'))
    q.default = q.val = 4
    q.normMin, q.normMax = 1, 8
    ro = c.appendCustomPage('Readout')
    for name, label in (('Beats', 'Beats (total)'), ('Tempo', 'Tempo')):
        q = _sc_first(ro.appendFloat(name, label=label))
        q.val = 0
    for name, label in (('Bar', 'Bar'), ('Beat', 'Beat')):
        q = _sc_first(ro.appendInt(name, label=label))
        q.val = 1
    q = _sc_first(ro.appendStr('Status', label='Status'))
    q.val = 'starting'

    link = c.create(abletonlinkCHOP, 'link')
    link.nodeX, link.nodeY = 0, 0
    for name, v in (('enable', True), ('active', True), ('beats', True), ('rampbeat', True),
                    ('tempo', True), ('status', True)):
        _sc_set(link, name, v)

    tick = c.create(executeDAT, 'tick')
    tick.nodeX, tick.nodeY = 200, 0
    tick.text = TICK
    _sc_set(tick, 'frameend', True)
    _sc_set(tick, 'active', True)

    pe = c.create(parameterexecuteDAT, 'buttons')
    pe.nodeX, pe.nodeY = 400, 0
    pe.text = BUTTONS
    _sc_set(pe, 'op', '..')
    _sc_set(pe, 'pars', 'Tap Downbeat')
    _sc_set(pe, 'onpulse', True)
    _sc_set(pe, 'valuechange', False)

    os.makedirs(os.path.join(SC_BASE, 'toxes'), exist_ok=True)
    path = os.path.join(SC_BASE, 'toxes', 'show_clock.tox')
    c.save(path)
    return c, path


# ---- making other components follow the clock ---------------------------------------------
def follow_show_clock(target, clock=SC_PATH):
    """hue_rig or a Mapper Pack animation keeps time with show_clock."""
    done = []
    if hasattr(target.par, 'Useclock'):                       # hue_rig
        target.par.Useclock = True
        target.par.Clockpath = clock
        done.append('lamps')
    g = target.op('glsl1')                                     # Mapper Pack animation
    if g is not None:
        i = 0
        while hasattr(g.par, 'vec%dname' % i):
            if getattr(g.par, 'vec%dname' % i).eval() == 'uBeats':
                getattr(g.par, 'vec%dvaluex' % i).expr = (
                    "op('%s').par.Beats if op('%s') else absTime.seconds * parent().par.Bpm / 60"
                    % (clock, clock))
                done.append('beat')
                break
            i += 1
    if hasattr(target.par, 'Bpm'):
        target.par.Bpm.expr = "op('%s').par.Tempo if op('%s') else 120" % (clock, clock)
    if hasattr(target.par, 'Sync'):
        try:
            if target.par.Sync.mode == ParMode.CONSTANT:
                target.par.Sync = True
        except Exception:
            pass
    return done


def unfollow_show_clock(target):
    g = target.op('glsl1')
    if g is not None:
        i = 0
        while hasattr(g.par, 'vec%dname' % i):
            if getattr(g.par, 'vec%dname' % i).eval() == 'uBeats':
                getattr(g.par, 'vec%dvaluex' % i).expr = 'absTime.seconds * parent().par.Bpm / 60'
            i += 1
    if hasattr(target.par, 'Useclock'):
        target.par.Useclock = False
    if hasattr(target.par, 'Bpm'):
        v = target.par.Bpm.eval()
        target.par.Bpm.expr = ''
        target.par.Bpm.mode = ParMode.CONSTANT
        target.par.Bpm = v


def follow_all(parent_path='/project1'):
    """Every hue_rig and Mapper Pack animation in the project follows show_clock."""
    names = []
    for c in op(parent_path).children:
        if c.name == 'show_clock':
            continue
        if hasattr(c.par, 'Useclock') or (c.op('glsl1') is not None and hasattr(c.par, 'Sync')):
            if follow_show_clock(c):
                names.append(c.name)
    print('Following show_clock: ' + (', '.join(names) if names else '(nothing found)'))
    return names


_sc_lines = ['', 'SHOW CLOCK BUILD', '----------------']
try:
    _sc, _sc_path = build_show_clock()
    _sc_lines.append('OK    show_clock -> %s' % _sc_path)
except Exception as _e:
    _sc_lines.append('FAIL  show_clock  %s: %s' % (type(_e).__name__, _e))
_sc_lines += ['',
              'In Ableton Live: switch on Link (top-left, next to the tempo).',
              'Then in this Textport:   follow_all()',
              'No Ableton? Set Source = Free, then Tap Tempo and press Now Is Beat 1 on a downbeat.', '']
print('\n'.join(_sc_lines))
