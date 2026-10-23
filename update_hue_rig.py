# =============================================================================
# HUE RIG -- update in place (keeps your wiring and settings)
#
# Gives an existing hue_rig the newest engine and controls:
#   - quicker, punchier lamps with the new flicker protection
#   - Lamps page: a role, colour and brightness for every lamp
#   - Cues page: save looks and fire them with a cross-fade
#   - Blackout
#
#   exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/update_hue_rig.py').read())
# =============================================================================

import os

_BASE = '/Users/michaelney/Touchdesigner Designs/Hue Rig'
exec(open(os.path.join(_BASE, 'hue_rig_controls.py')).read())   # add_controls, hue_cue

_lines = ['', 'HUE RIG UPDATE', '--------------']
_rigs = [o for o in root.findChildren(type=baseCOMP, name='hue_rig')]
if not _rigs:
    _lines.append('No hue_rig in this project -- run build_hue_rig.py instead.')
for _rig in _rigs:
    try:
        _old_smooth = _rig.par.Smooth.eval()
        _added = add_controls(_rig)
        if abs(_old_smooth - 0.5) < 1e-6:         # still on the old default -> the new, snappier one
            _rig.par.Smooth = 0.3
        with open(os.path.join(_BASE, 'hue_engine.py')) as _f:
            _rig.op('engine').text = _f.read()
        _lines.append('OK    %s  (Flicker Guard = %g / sec)%s' % (
            _rig.path, _rig.par.Flickerguard.eval(),
            ('  added: ' + ', '.join(_added)) if _added else ''))
    except Exception as _e:
        _lines.append('FAIL  %s  %s: %s' % (_rig.path, type(_e).__name__, _e))
_lines += ['', 'Look page: Smoothing (0 = instant), Flicker Guard (the speed limit), Blackout.',
           'Lamps page: what each lamp does.   Cues page: save a look, then Go.',
           "Fire a cue from anywhere:  hue_cue('drop')",
           'Lamps page: set each lamp\'s "place" (left-right, height) to where it really is.',
           'One beat for lights + visuals: run build_show_clock.py, then follow_all()', '']
print('\n'.join(_lines))
