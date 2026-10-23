# =============================================================================
# HUE RIG -- TouchDesigner builder
#
# Builds hue_rig: the Philips Hue lamps as part of the show. It works out a
# colour for every lamp each frame -- from the Feeling Palette, from the
# projected picture (any Mapper Pack animation), or as a chase / flash /
# ripple that moves in step with the Mapper Pack -- shows the lamps on a
# preview, and sends the colours to the lights.
#
# Until the bulbs are set up it runs with 5 "virtual lamps" on the preview,
# so you can design the light show right now.
#
# Run from the Textport (Dialogs > Textport and DATs):
#
#   exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/build_hue_rig.py').read())
#
# Safe to run again: it replaces only hue_rig.
# =============================================================================

import os

BASE = '/Users/michaelney/Touchdesigner Designs/Hue Rig'
TOX_DIR = os.path.join(BASE, 'toxes')
PARENT = op('/project1') or op('/')

NOSTALGIA = ((1.00, 0.62, 0.30), (0.85, 0.50, 0.55), (1.00, 0.88, 0.70))

exec(open(os.path.join(BASE, 'hue_rig_controls.py')).read())   # add_controls, hue_cue


def first(g):
    try:
        return g[0]
    except Exception:
        return g


def try_set(owner, parname, value, expr=False):
    try:
        p = getattr(owner.par, parname)
        if expr:
            p.expr = value
        else:
            p.val = value
        return True
    except Exception:
        return False


def fpar(page, name, label, d, lo, hi, clamp=True, integer=False):
    p = first(page.appendInt(name, label=label) if integer else page.appendFloat(name, label=label))
    p.default = d
    p.val = d
    p.normMin, p.normMax = lo, hi
    if clamp:
        p.min, p.max = lo, hi
        p.clampMin = p.clampMax = True
    return p


def tpar(page, name, label, d):
    p = first(page.appendToggle(name, label=label))
    p.default = bool(d)
    p.val = bool(d)
    return p


def menu(page, name, label, names, labels, d):
    p = first(page.appendMenu(name, label=label))
    p.menuNames = names
    p.menuLabels = labels
    p.default = d
    p.val = d
    return p


def text_from(path):
    with open(os.path.join(BASE, path)) as f:
        return f.read()


def build():
    old = PARENT.op('hue_rig')
    if old is not None:
        old.destroy()
    comp = PARENT.create(baseCOMP, 'hue_rig')
    comp.nodeX, comp.nodeY = 0, -1900

    # ---- parameters ----
    h = comp.appendCustomPage('Hue')
    tpar(h, 'Active', 'Send to the Lights', 1)
    menu(h, 'Transport', 'How', ['stream', 'direct', 'preview'],
         ['Stream through the helper (fast, 50/s)', 'Direct to the bridge (no helper, slower)',
          'Preview only'], 'stream')
    fpar(h, 'Port', 'Helper Port', 7010, 1024, 65535, integer=True)
    p = first(h.appendFile('Lampsfile', label='Lamp List (from the helper)'))
    p.default = p.val = os.path.join(BASE, 'hue_lamps.csv')
    p = first(h.appendFile('Configfile', label='Bridge Settings (for Direct)'))
    p.default = p.val = os.path.join(BASE, 'hue_config.json')
    fpar(h, 'Virtuallamps', 'Virtual Lamps (until set up)', 5, 1, 16, integer=True)
    first(h.appendPulse('Reload', label='Reload Lamp List'))
    p = first(h.appendStr('Status', label='Status'))
    p.val = 'starting'

    lk = comp.appendCustomPage('Look')
    menu(lk, 'Mode', 'Mode', MODE_NAMES, MODE_LABELS, 'palette')
    fpar(lk, 'Intensity', 'Intensity', 1.0, 0, 1)
    fpar(lk, 'Maxbright', 'Max Brightness', 1.0, 0, 1)
    fpar(lk, 'Kick', 'Kick (0-1)', 0, 0, 1)
    fpar(lk, 'Rate', 'Rate (cycles per beat / sec)', 0.5, -8, 8, clamp=False)
    tpar(lk, 'Sync', 'Sync to BPM', 0)
    fpar(lk, 'Bpm', 'BPM', 120, 40, 240)
    fpar(lk, 'Smooth', 'Smoothing (0 = instant, 1 = slow washes)', 0.3, 0, 1)
    fpar(lk, 'Saturate', 'Colour Boost (Sample mode)', 1.3, 0, 3)
    fpar(lk, 'Spread', 'Sample Area (Sample mode)', 0.6, 0, 4)
    fpar(lk, 'Gain', 'Brightness Boost (Sample mode)', 1.4, 0, 4)
    tpar(lk, 'Usepalette', 'Follow the Feeling Palette', 1)
    p = first(lk.appendStr('Palettepath', label='Feeling Palette Component'))
    p.default = p.val = '/project1/feeling_palette'
    for name, label, rgb in zip(('Colora', 'Colorb', 'Accent'),
                                ('Colour A', 'Colour B', 'Accent'), NOSTALGIA):
        for q, v in zip(lk.appendRGB(name, label=label + ' (when not following)'), rgb):
            q.default = v
            q.val = v

    out = comp.appendCustomPage('Output')
    for q, v in zip(out.appendWH('Res', label='Preview Resolution'), (960, 600)):
        q.default = v
        q.val = v

    # ---- network ----
    pic = comp.create(inTOP, 'in1_picture')
    pic.nodeX, pic.nodeY = 0, 0

    def glsl(name, src, x, y, w, h, fmt='rgba16float', rows=()):
        d = comp.create(textDAT, name + '_shader')
        d.text = text_from(src)
        d.nodeX, d.nodeY = x, y + 200
        g = comp.create(glslTOP, name)
        g.nodeX, g.nodeY = x, y
        g.par.pixeldat = d.name
        try_set(g, 'outputresolution', 'custom')
        try_set(g, 'resolutionw', w, expr=True)
        try_set(g, 'resolutionh', h, expr=True)
        try_set(g, 'format', fmt)
        if rows:
            try:
                g.seq.vec.numBlocks = len(rows)
            except Exception:
                g.par.vec = len(rows)
            for i, (un, exprs) in enumerate(rows):
                getattr(g.par, 'vec%dname' % i).val = un
                for letter, e in zip('xyzw', exprs):
                    getattr(g.par, 'vec%dvalue%s' % (i, letter)).expr = e
        return g

    small = glsl('small', 'hue_downsample.glsl', 200, 0, '64', '40')
    small.inputConnectors[0].connect(pic)

    cb = comp.create(textDAT, 'lampdata_callbacks')
    cb.text = text_from('hue_lampdata_callbacks.py')
    cb.nodeX, cb.nodeY = 200, -400
    data = comp.create(scriptTOP, 'lampdata')
    data.nodeX, data.nodeY = 200, -250
    try_set(data, 'callbacks', cb.name)
    try_set(data, 'format', 'rgba32float')

    prev = glsl('preview', 'hue_preview.glsl', 400, 0, 'parent().par.Resw', 'parent().par.Resh',
                rows=[('uRes', ('me.width', 'me.height')), ('uDim', ('0.55',))])
    prev.inputConnectors[0].connect(pic)
    prev.inputConnectors[1].connect(data)

    o = comp.create(outTOP, 'out1')
    o.nodeX, o.nodeY = 600, 0
    o.inputConnectors[0].connect(prev)

    table = comp.create(tableDAT, 'lamp_colours')
    table.nodeX, table.nodeY = 400, -400

    eng = comp.create(executeDAT, 'engine')
    eng.nodeX, eng.nodeY = 0, -400
    eng.text = text_from('hue_engine.py')
    try_set(eng, 'frameend', True)
    try_set(eng, 'active', True)

    pe = comp.create(parameterexecuteDAT, 'reload_callback')
    pe.nodeX, pe.nodeY = 0, -600
    pe.text = ("def onPulse(par):\n"
               "    if par.name == 'Reload':\n"
               "        c = par.owner\n"
               "        c.store('reload', c.fetch('reload', 0) + 1)\n"
               "    return\n")
    try_set(pe, 'op', '..')
    try_set(pe, 'pars', 'Reload')
    try_set(pe, 'onpulse', True)
    try_set(pe, 'valuechange', False)

    add_controls(comp)                     # Flicker Guard, Blackout, Lamps page, Cues page

    try_set(comp, 'opviewer', "me.op('out1')", expr=True)
    try:
        comp.viewer = True
    except Exception:
        pass
    os.makedirs(TOX_DIR, exist_ok=True)
    path = os.path.join(TOX_DIR, 'hue_rig.tox')
    comp.save(path)
    return comp, path


def link_clock(target, source):
    """Make a component keep time with another (Rate, Sync, BPM):
         link_clock(op('hue_rig'), op('mp_line_sweep'))"""
    for n in ('Rate', 'Sync', 'Bpm'):
        getattr(target.par, n).expr = "op('%s').par.%s" % (source.path, n)
    print('clock of', target.path, 'follows', source.path)


def unlink_clock(target):
    for n in ('Rate', 'Sync', 'Bpm'):
        p = getattr(target.par, n)
        v = p.eval()
        p.expr = ''
        p.mode = ParMode.CONSTANT
        p.val = v


lines = ['', 'HUE RIG BUILD', '-------------']
try:
    rig, path = build()
    lines.append('OK    hue_rig -> %s' % path)
    # demo: let the lamps follow a Mapper Pack picture if there is one
    src = None
    for name in ('surface_right', 'mp_line_sweep', 'mp_grid_pulse', 'mp_plasma', 'flower_of_life'):
        if PARENT.op(name) is not None:
            src = PARENT.op(name)
            break
    if src is not None:
        rig.inputConnectors[0].connect(src.outputConnectors[0])
        rig.par.Mode = 'sample'
        lines.append('Demo: %s -> hue_rig, Mode = Sample the Picture' % src.name)
        if hasattr(src.par, 'Rate'):
            link_clock(rig, src)
    else:
        lines.append('Wire any picture into hue_rig and set Mode to "Sample the Picture".')
except Exception as e:
    lines.append('FAIL  hue_rig  %s: %s' % (type(e).__name__, e))

lines += ['', 'No bulbs set up yet? hue_rig shows 5 virtual lamps on its preview.',
          "Keep time with a Mapper Pack animation:  link_clock(op('hue_rig'), op('mp_line_sweep'))",
          "Fire a saved cue from anywhere:  hue_cue('drop')", '']
print('\n'.join(lines))
