# =============================================================================
# HUE RIG -- six starter cues (calm, picture, groove, drop, rainbow, outro)
#
#   exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/starter_cues.py').read())
#
# Each cue starts from hue_rig's current settings and changes only what is
# listed below. The live lights don't change until you press Go. Cues with
# other names are kept; running this again just refreshes these six.
# =============================================================================

import json
import os

_rig = op('/project1/hue_rig')
_SKIP = {'Kick', 'Flickerguard', 'Palettepath', 'Blackout', 'Clockpath'}

# lamp numbers as on the Lamps page: 1 Behind Desk, 2 Floor Shade, 3 Top Lamp,
# 4 Hue Play floor lamp, 5 Hue color lamp 1, 6 Hue color lamp 2
_RED, _WARM, _VIOLET = (1.0, 0.12, 0.08), (1.0, 0.75, 0.45), (0.6, 0.25, 1.0)


def _lamp(i, role, colour=None, bright=None):
    d = {'L%drole' % i: role}
    if colour:
        d.update({'L%dcolor%s' % (i, c): v for c, v in zip('rgb', colour)})
    if bright is not None:
        d['L%dbright' % i] = bright
    return d


def _cue(name, look, *lamps):
    v = dict(look)
    for i in range(1, 13):                       # every lamp follows the Mode ...
        v['L%drole' % i] = 'mode'
        v['L%dbright' % i] = 1.0
    for l in lamps:                              # ... unless set below
        v.update(l)
    return name, v


_STARTERS = [
    # slow and together: the whole room breathes as one
    _cue('calm', {'Mode': 'palette', 'Colorsfrom': 'palette', 'Intensity': 0.7, 'Smooth': 0.6,
                  'Sync': True, 'Rate': 0.25, 'Together': 0.8, 'Picturehits': 0.0},
         _lamp(1, 'wash')),
    # the room wears the projection's colours, and pulses when the wall flashes
    _cue('picture', {'Mode': 'sample', 'Colorsfrom': 'picture', 'Intensity': 0.9, 'Smooth': 0.3,
                     'Together': 0.3, 'Picturehits': 0.4},
         _lamp(1, 'wash', bright=0.6)),
    # a chase across the room once a bar, in the picture's colours; Floor Shade hits each bar
    _cue('groove', {'Mode': 'chase', 'Colorsfrom': 'picture', 'Intensity': 0.9, 'Smooth': 0.25,
                    'Sync': True, 'Bpm': 140, 'Rate': 0.25, 'Together': 0.2, 'Picturehits': 0.0},
         _lamp(1, 'wash', bright=0.5), _lamp(2, 'beat', _RED)),
    # everything on the picture, two lamps hitting every other beat, wall flashes punch through
    _cue('drop', {'Mode': 'sample', 'Colorsfrom': 'picture', 'Intensity': 1.0, 'Smooth': 0.15,
                  'Sync': True, 'Bpm': 140, 'Rate': 0.5, 'Together': 0.1, 'Picturehits': 0.8},
         _lamp(2, 'beat', _RED), _lamp(4, 'beat', _VIOLET)),
    # the rainbow show: red, orange, yellow, green, blue, indigo, violet -- one step per beat,
    # 12 bars round: spread across the room, then the room together, then sweeping across
    _cue('rainbow', {'Mode': 'rainbow', 'Intensity': 1.0, 'Smooth': 0.2, 'Sync': True, 'Bpm': 140,
                     'Rate': 1.0, 'Together': 0.0, 'Picturehits': 0.0}),
    # low, warm, everyone together
    _cue('outro', {'Mode': 'palette', 'Colorsfrom': 'palette', 'Intensity': 0.35, 'Smooth': 0.8,
                   'Sync': True, 'Rate': 0.125, 'Together': 0.9, 'Picturehits': 0.0},
         _lamp(1, 'fixed', _WARM, 0.5), _lamp(3, 'off')),
]

if _rig is None:
    print('\nNo hue_rig at /project1/hue_rig -- undo the delete (Cmd+Z) or run build_hue_rig.py.\n')
elif not hasattr(_rig.par, 'Cuesfile'):
    print('\nRun update_hue_rig.py first (hue_rig needs its Cues page).\n')
else:
    _base = {}
    for _p in _rig.customPars:
        if _p.page.name in ('Look', 'Lamps') and _p.name not in _SKIP and not _p.isPulse \
                and not (_p.name[:1] == 'L' and _p.name[-4:-1] == 'pos') \
                and _p.style not in ('Str', 'File', 'Header'):
            _v = _p.eval()
            _base[_p.name] = _v if isinstance(_v, (int, float, str, bool)) else str(_v)
    _path = _rig.par.Cuesfile.eval()
    try:
        with open(_path) as _f:
            _cues = json.load(_f).get('cues', [])
    except (OSError, ValueError):
        _cues = []
    _names = [n for n, _ in _STARTERS]
    _cues = [c for c in _cues if c['name'] not in _names]
    for _n, _v in _STARTERS:
        _vals = dict(_base)
        _vals.update({k: v for k, v in _v.items() if k in _base})   # only lamps you really have
        _cues.append({'name': _n, 'values': _vals})
    with open(_path, 'w') as _f:
        json.dump({'cues': _cues}, _f, indent=1)
    print('\nSTARTER CUES saved: ' + ', '.join(_names))
    print("Cues page: pick one and press Go -- or  hue_cue('calm')\n")
