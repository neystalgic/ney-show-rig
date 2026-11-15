#!/usr/bin/env python3
# tidy_map.py -- the TouchDesigner tidy-up plan as data (away/td-tidy, task #59, Nov 15).
#
# Which box each top-level operator in /project1 belongs to: INPUT, DECKS, MIXER, OUTPUT, or SYSTEM
# (SYSTEM = the room link and the Claude connection: never moved, never renamed).
# It is a PLAN only: nothing here talks to TouchDesigner, the hub or the lights.
#
#   python3 tidy_map.py            -> writes "Group Map.csv" next to this file (one row per operator)
#
# The layout rule (see PLAN.txt): phase A only moves tiles on the canvas and draws labelled boxes.
# No operator changes name or parent, so every '/project1/<name>' path in the builders keeps working.

import csv, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..'))          # Hue Rig
DESIGNS = os.path.dirname(REPO)                                  # Touchdesigner Designs

# The builders that write into /project1 (read as text only, never run).
BUILDERS = [
    os.path.join(REPO, 'build_hue_hub_td.py'), os.path.join(REPO, 'build_vj.py'),
    os.path.join(REPO, 'build_osmo_fx.py'), os.path.join(REPO, 'build_show_clock.py'),
    os.path.join(REPO, 'build_hue_rig.py'),
    os.path.join(DESIGNS, 'Sacred Geometry', 'build_sacred_geometry.py'),
    os.path.join(DESIGNS, 'Mapper Pack', 'build_mapper_pack.py'),
    os.path.join(DESIGNS, 'Show Tools', 'build_show_tools.py'),
]

# Boxes, left to right on the canvas. x = where the box's left edge goes (TouchDesigner node units).
GROUPS = {
    'INPUT':  {'order': 1, 'x': 0,    'colour': (0.25, 0.35, 0.6),  'title': '1 INPUT -- what comes in: hub feed, clock, camera, movie, palette'},
    'DECKS':  {'order': 2, 'x': 1400, 'colour': (0.45, 0.25, 0.6),  'title': '2 DECKS -- the visuals; only the one on screen should cook'},
    'MIXER':  {'order': 3, 'x': 2800, 'colour': (0.6, 0.25, 0.5),   'title': '3 MIXER -- your mix, the VJ board, Osmo blend'},
    'OUTPUT': {'order': 4, 'x': 4200, 'colour': (0.35, 0.2, 0.45),  'title': '4 OUTPUT -- show_out to the projector window'},
    'SYSTEM': {'order': 5, 'x': 0,    'colour': (0.3, 0.3, 0.3),    'title': 'SYSTEM -- room link + Claude connection. Do not move or rename'},
}

EXACT = {
    # INPUT: things that bring the outside world in
    'hue_feed': 'INPUT', 'show_clock': 'INPUT', 'movie_in': 'INPUT', 'osmo_fx': 'INPUT',
    'feeling_palette': 'INPUT', 'demons_guard': 'INPUT', 'promo_recorder': 'OUTPUT',
    # DECKS: whole visual pieces
    'geo_show': 'DECKS', 'geo_visual': 'DECKS', 'flower_of_life': 'DECKS', 'metatrons_cube': 'DECKS',
    'sri_yantra': 'DECKS', 'golden_angle': 'DECKS', 'tesseract': 'DECKS', 'chladni': 'DECKS',
    'kaleidoscope': 'DECKS', 'reaction_diffusion': 'DECKS', 'breath_geo': 'DECKS', 'breath_3d': 'DECKS',
    'sacred_particles': 'DECKS', 'sacred_line': 'DECKS', 'bloom_core': 'DECKS',
    # MIXER: where decks are chosen and blended
    'comp1': 'MIXER', 'comp2': 'MIXER', 'vj': 'MIXER', 'vj_xfade': 'MIXER', 'vj_pick': 'MIXER',
    'osmo_amount': 'MIXER', 'osmo_mix': 'MIXER',
    # OUTPUT
    'show_out': 'OUTPUT', 'projector_window': 'OUTPUT', 'out1': 'OUTPUT', 'null4': 'OUTPUT',
    # SYSTEM: sends to the real lamps / talks to Claude / the light desk panel
    'hue_rig': 'SYSTEM', 'mcp_webserver_base': 'SYSTEM', 'light_desk': 'SYSTEM',
}
PREFIXES = [('proc_', 'DECKS'), ('mp_', 'DECKS'), ('sacred_', 'DECKS'), ('osmo_', 'MIXER'), ('vj_', 'MIXER')]

# Never moved, renamed or switched off -- even in a later phase.
NEVER_TOUCH = {'mcp_webserver_base', 'hue_rig', 'hue_feed', 'show_clock', 'light_desk', 'projector_window'}

# Decks that may be put to sleep when not on screen (phase C). Feedback decks keep their state when paused.
SLEEPABLE_PREFIXES = ('proc_', 'mp_')
SLEEPABLE = {'flower_of_life', 'metatrons_cube', 'sri_yantra', 'golden_angle', 'tesseract', 'chladni',
             'kaleidoscope', 'reaction_diffusion', 'breath_geo', 'breath_3d', 'sacred_particles', 'sacred_line'}
# mp_strobe is the projector strobe effect: keep it out of the sleep list (it is gated by the guest/strobe rules).
NOT_SLEEPABLE = {'mp_strobe', 'geo_show', 'geo_visual'}


def classify(name):
    """Which box an operator in /project1 belongs to. Unknown names -> 'UNSORTED' (Michael decides)."""
    if name in EXACT:
        return EXACT[name]
    for pre, grp in PREFIXES:
        if name.startswith(pre):
            return grp
    return 'UNSORTED'


def sleepable(name):
    if name in NEVER_TOUCH or name in NOT_SLEEPABLE:
        return False
    return name in SLEEPABLE or name.startswith(SLEEPABLE_PREFIXES)


_PATH = re.compile(r"/project1/([A-Za-z_][A-Za-z_0-9]*)")
_CREATE = re.compile(r"\b(?:P|_P|PARENT|parent_)\.create\(\s*\w+\s*,\s*'([A-Za-z_][A-Za-z_0-9]*)'")
_GET = re.compile(r"\b(?:P|_P|PARENT|parent_)\.op\(\s*'([A-Za-z_][A-Za-z_0-9]*)'\s*\)")


def builder_names(paths=None):
    """Every top-level /project1 name the builders mention, read as plain text. {name: [builder file, ...]}"""
    found = {}
    for p in (paths or BUILDERS):
        if not os.path.exists(p):
            continue
        with open(p, encoding='utf-8', errors='replace') as f:
            text = f.read()
        for rx in (_PATH, _CREATE, _GET):
            for m in rx.finditer(text):
                found.setdefault(m.group(1), set()).add(os.path.basename(p))
    return {k: sorted(v) for k, v in found.items()}


def rows(names=None):
    """One row per operator: name, group, sleepable, never_touch, used_by (builders)."""
    refs = builder_names() if names is None else {n: [] for n in names}
    out = []
    for n in sorted(refs, key=lambda n: (GROUPS.get(classify(n), {'order': 9})['order'], n)):
        out.append({'operator': n, 'group': classify(n), 'sleepable_when_off_screen': 'yes' if sleepable(n) else 'no',
                    'never_touch': 'yes' if n in NEVER_TOUCH else 'no', 'mentioned_in': ' + '.join(refs[n])})
    return out


def write_csv(path=None, names=None):
    path = path or os.path.join(HERE, 'Group Map.csv')
    rs = rows(names)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rs[0].keys()) if rs else ['operator'])
        w.writeheader()
        w.writerows(rs)
    return path, len(rs)


if __name__ == '__main__':
    p, n = write_csv()
    print('wrote %s (%d operators)' % (os.path.basename(p), n))
