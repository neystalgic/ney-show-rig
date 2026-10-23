# =============================================================================
# HUE RIG -- the controls (used by build_hue_rig.py and update_hue_rig.py)
#
# Adds to hue_rig:
#   Look page   Flicker Guard, Blackout
#   Lamps page  a role, colour and brightness for every lamp
#   Cues page   save looks and fire them with a cross-fade
# Safe to run on a hue_rig that already has some of these: it only adds
# what's missing and never changes your settings.
# =============================================================================

import os

HUE_BASE = '/Users/michaelney/Touchdesigner Designs/Hue Rig'
MODE_NAMES = ['palette', 'sample', 'chase', 'flash', 'ripple', 'rainbow']
MODE_LABELS = ['Palette (breathing feeling colours)', 'Sample the Picture (lamps match the wall)',
               'Chase (pairs with Line Sweep / Edge Chase)', 'Flash (pairs with Strobe)',
               'Ripple (pairs with Grid Pulse / Tunnel)', 'Rainbow Show (red to violet)']
ROLE_NAMES = ['mode', 'wash', 'beat', 'fixed', 'off']
ROLE_LABELS = ['Follow the Mode', 'Slow wash (ignores Mode)', 'Hit on the beat / kick',
               'Steady colour', 'Off']


def _first(g):
    try:
        return g[0]
    except Exception:
        return g


def _page(comp, name):
    for p in comp.customPages:
        if p.name == name:
            return p
    return comp.appendCustomPage(name)


def _float(page, name, label, d, lo, hi):
    p = _first(page.appendFloat(name, label=label))
    p.default = p.val = d
    p.normMin, p.normMax = lo, hi
    p.min, p.max = lo, hi
    p.clampMin = p.clampMax = True
    return p


def _lamp_rows(comp):
    """[(name, u, v)] from hue_lamps.csv"""
    path = comp.par.Lampsfile.eval() if hasattr(comp.par, 'Lampsfile') else ''
    out = []
    try:
        with open(path) as f:
            rows = [l.rstrip('\n').split('\t') for l in f if l.strip()]
        for r in rows[1:]:
            try:
                out.append((r[1], float(r[3]), float(r[4])))
            except (IndexError, ValueError):
                continue
    except OSError:
        pass
    return out


def add_controls(comp):
    added = []
    look = _page(comp, 'Look')
    if hasattr(comp.par, 'Mode') and list(comp.par.Mode.menuNames) != MODE_NAMES:
        cur = comp.par.Mode.eval()
        comp.par.Mode.menuNames, comp.par.Mode.menuLabels = MODE_NAMES, MODE_LABELS
        comp.par.Mode = cur if cur in MODE_NAMES else 'palette'
        added.append('Rainbow Show mode')
    if hasattr(comp.par, 'Flickerguard'):
        p = comp.par.Flickerguard
        p.normMin, p.normMax = 0.5, 3
        p.min, p.max = 0.5, 3
        p.clampMin = p.clampMax = True
    else:
        _float(look, 'Flickerguard', 'Flicker Guard (max flashes / sec)', 2, 0.5, 3)
        added.append('Flicker Guard')
    if not hasattr(comp.par, 'Blackout'):
        p = _first(look.appendToggle('Blackout', label='Blackout'))
        p.default = p.val = False
        added.append('Blackout')
    try:
        comp.par.Smooth.label = 'Smoothing (0 = instant, 1 = slow washes)'
        comp.par.Smooth.default = 0.3
    except Exception:
        pass

    # ---- keeping together: the show clock, the picture, each other ----
    if not hasattr(comp.par, 'Useclock'):
        p = _first(look.appendToggle('Useclock', label='Follow the Show Clock (Ableton)'))
        p.default = p.val = True
        p = _first(look.appendStr('Clockpath', label='Show Clock Component'))
        p.default = p.val = '/project1/show_clock'
        _float(look, 'Ahead', 'Lights Ahead (ms, makes up for bulb delay)', 60, 0, 300)
        p = _first(look.appendMenu('Colorsfrom', label='Colours From'))
        p.menuNames = ['palette', 'picture']
        p.menuLabels = ['Feeling Palette / colours below', 'The Picture (match the projection)']
        p.default = p.val = 'palette'
        _float(look, 'Picturehits', 'Hits from the Picture (flashes on the wall)', 0, 0, 1)
        _float(look, 'Together', 'Togetherness (0 = each lamp its own, 1 = one look)', 0.3, 0, 1)
        added.append('Show Clock + Picture + Togetherness controls')

    # ---- one row of controls per lamp ----
    lamps = _page(comp, 'Lamps')
    rows = _lamp_rows(comp)
    names = [r[0] for r in rows]
    n = min(12, max(6, len(names)))
    for i in range(1, n + 1):
        nm = names[i - 1] if i <= len(names) else 'lamp %d' % i
        u, v = (rows[i - 1][1], rows[i - 1][2]) if i <= len(rows) else ((i - 0.5) / n, 0.5)
        if not hasattr(comp.par, 'L%drole' % i):
            p = _first(lamps.appendMenu('L%drole' % i, label='%d  %s' % (i, nm)))
            p.menuNames, p.menuLabels = ROLE_NAMES, ROLE_LABELS
            p.default = p.val = 'mode'
            for q, cv in zip(lamps.appendRGB('L%dcolor' % i, label='     colour'), (1.0, 0.88, 0.7)):
                q.default = q.val = cv
            _float(lamps, 'L%dbright' % i, '     brightness', 1.0, 0, 1)
            if i == 1:
                added.append('Lamps page')
        else:
            getattr(comp.par, 'L%drole' % i).label = '%d  %s' % (i, nm)   # names may have changed
        if not hasattr(comp.par, 'L%dposx' % i):
            for q, val in zip(lamps.appendXY('L%dpos' % i, label='     place (left-right, height)'), (u, v)):
                q.default = q.val = val
                q.normMin, q.normMax = 0, 1
            if i == 1:
                added.append('lamp places')

    # ---- cues ----
    cues = _page(comp, 'Cues')
    if not hasattr(comp.par, 'Cue'):
        p = _first(cues.appendStr('Cuename', label='Name for a New Cue'))
        p.val = ''
        _first(cues.appendPulse('Savecue', label='Save Current Look as Cue'))
        p = _first(cues.appendMenu('Cue', label='Cue'))
        p.menuNames = p.menuLabels = ['(none yet)']
        _first(cues.appendPulse('Gocue', label='Go'))
        _first(cues.appendPulse('Prevcue', label='Previous Cue'))
        _first(cues.appendPulse('Nextcue', label='Next Cue'))
        _float(cues, 'Fade', 'Cross-fade Time (sec)', 2.0, 0, 30)
        p = _first(cues.appendFile('Cuesfile', label='Cues File'))
        p.default = p.val = os.path.join(HUE_BASE, 'hue_cues.json')
        added.append('Cues page')

    # ---- buttons -> engine ----
    pe = comp.op('reload_callback')
    if pe is not None:
        pe.text = ("ACTIONS = {'Savecue': 'save', 'Gocue': 'go', 'Nextcue': 'next', 'Prevcue': 'prev'}\n"
                   "\n"
                   "def onPulse(par):\n"
                   "    c = par.owner\n"
                   "    if par.name == 'Reload':\n"
                   "        c.store('reload', c.fetch('reload', 0) + 1)\n"
                   "    elif par.name in ACTIONS:\n"
                   "        c.store('cue_reqs', list(c.fetch('cue_reqs', [])) + [ACTIONS[par.name]])\n"
                   "    return\n")
        try:
            pe.par.pars = 'Reload Savecue Gocue Nextcue Prevcue'
        except Exception:
            pass
    return added


def hue_cue(name, rig='/project1/hue_rig'):
    """Fire a saved cue by name, e.g. hue_cue('drop')."""
    c = op(rig)
    c.store('cue_reqs', list(c.fetch('cue_reqs', [])) + ['go:' + name])
