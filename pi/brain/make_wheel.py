#!/usr/bin/env python3
# =============================================================================
# MAKE WHEEL -- run on the Mac (needs hub_palette.py + hue_stream.py from the Hue Rig folder).
# Prints the colour wheel the Mac's ambient engine uses (hub_palette.vivid -> hue_stream.rgb_to_xyb), every 5
# degrees, as Hue xy pairs. looks.py carries this table so the Pi shows the SAME colours without those modules.
# Pure maths: no lights, no network.  python3 make_wheel.py
# =============================================================================
import os, sys
RIG = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, RIG)


def wheel(step=5):
    from hub_palette import vivid
    import hue_stream as hs
    out = []
    for h in range(0, 360, step):
        x, y = hs.rgb_to_xyb(*vivid(h))[:2]
        out.append((round(x, 4), round(y, 4)))
    return out


if __name__ == '__main__':
    w = wheel()
    rows = ['    ' + ', '.join('(%.4f, %.4f)' % p for p in w[i:i + 6]) + ',' for i in range(0, len(w), 6)]
    print('WHEEL = [\n' + '\n'.join(rows) + '\n]')
