#!/usr/bin/env python3
"""Shortcut trim check (away loop, Nov 15). Reads the shortcut list (SET) from jarvis/shortcut_factory.py and the
word rules (RULES) from jarvis/jarvis.py WITHOUT importing them -- so no token is read, nothing is signed or opened,
and nothing touches the network. Then checks the trim plan:
  - every shortcut is either KEPT or RETIRED (none forgotten, none twice)
  - every RETIRED look still has a way in: a Jarvis phrase that lands on the same look, or the Movie Hub page
  - prints the regenerate command that rebuilds ONLY the kept ones (for the next token rotation)
Run:  python3 away/shortcut-trim/trim_check.py        (from the Hue Rig folder)"""
import ast, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(os.path.dirname(HERE))

# The six to keep, and why (the reason is printed in the report).
KEEP = {
    'Jarvis':      'the front door for everything else: Back Tap, Apple Watch, "Hey Siri, Jarvis"',
    'Goodnight':   'the Sleep Focus automation runs it -- deleting it breaks bedtime',
    'Morning':     'the "alarm stopped" automation runs it -- deleting it breaks morning blue',
    'Purple':      'favourite colour, one tap on the Watch, no talking needed',
    'Movie Hub':   'one page with play/pause, intermission, resume and lights up (replaces 4 shortcuts)',
    'Rig Health':  'Home Screen page: green/red for the whole rig',
}

# Retired shortcut -> what replaces it. ('jarvis', phrase) must route to the same look as the shortcut's path;
# ('page', name) means the button lives on that page; ('decide', why) = a gap Michael must decide on (reported, not an error).
RETIRE = {
    'Light Show':        ('jarvis', 'light show'),
    'Safe Show':         ('jarvis', 'safe show'),
    'Movie Night':       ('jarvis', 'movie night'),
    'Movie Stars':       ('jarvis', 'movie stars'),
    'Movie Mode':        ('decide', 'no Jarvis phrase reaches the music-reactive "movie" look yet ("movie mode" -> Movie night)'),
    'Rainbow Fade':      ('jarvis', 'rainbow'),
    'Lights Off':        ('jarvis', 'lights off'),
    'Guest Mode':        ('jarvis', 'guest mode'),
    'Play Pause':        ('page', 'Movie Hub'),
    'Intermission':      ('page', 'Movie Hub'),
    'Back to the Movie': ('page', 'Movie Hub'),
    'Lights Up':         ('page', 'Movie Hub'),
    'Health Report':     ('page', 'Rig Health'),   # health.html links to /body ("Health Report ->")
}

# Shortcut path -> the look/action Jarvis must reach for it to count as covered.
PATH_TO_ACTION = {'/show': 'show', '/showsafe': 'showsafe', '/movienight': 'movienight', '/movieuv': 'movieuv',
                  '/movie': 'movie', '/rainbow': 'rainbow', '/off': 'off', '/guest_on': 'guest_on',
                  '/body': 'brief'}


def _literal(path, name):
    """Return the literal value of a top-level `name = [...]` in a .py file, without running the file."""
    with open(path) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError('%s not found in %s' % (name, path))


def load_set(factory=None):
    return _literal(factory or os.path.join(RIG, 'jarvis', 'shortcut_factory.py'), 'SET')


def load_rules(jarvis=None):
    return _literal(jarvis or os.path.join(RIG, 'jarvis', 'jarvis.py'), 'RULES')


def route(text, rules):
    """Same steps as jarvis.by_rules for plain look words (food/colour/reminder steps skipped -- not needed here)."""
    t = text.lower().strip()
    t = re.sub(r'^(hey |ok |okay )?(jarvis|siri)[,.!]?\s*', '', t)
    for pat, action in rules:
        if pat.startswith('__'):
            continue
        if re.search(pat, t):
            return action
    return None


def check(shortcuts, rules, keep=KEEP, retire=RETIRE):
    """Returns (problems, lines). problems empty = the plan is sound."""
    problems, lines = [], []
    names = [s[0] for s in shortcuts]
    paths = {s[0]: s[2] for s in shortcuts}
    for n in names:
        if n in keep and n in retire:
            problems.append('%s is both kept and retired' % n)
        elif n not in keep and n not in retire:
            problems.append('%s is in the factory but not in the plan' % n)
    for n in list(keep) + list(retire):
        if n not in names:
            problems.append('%s is in the plan but not in the factory' % n)
    for n in names:
        if n in keep:
            lines.append('KEEP    %-18s %s' % (n, keep[n]))
    for n in names:
        if n not in retire:
            continue
        how, what = retire[n]
        if how == 'decide':
            lines.append('DECIDE  %-18s -> %s' % (n, what))
            continue
        if how == 'page':
            if what not in keep:
                problems.append('%s points to page %s, which is not kept' % (n, what))
            lines.append('RETIRE  %-18s -> button on the %s page' % (n, what))
            continue
        want = PATH_TO_ACTION.get(paths[n])
        got = route('jarvis, ' + what, rules)
        if want is None:
            problems.append('%s: no known look for path %s' % (n, paths[n]))
        elif got != want:
            problems.append('%s: "Jarvis, %s" goes to %r, not %r' % (n, what, got, want))
        lines.append('RETIRE  %-18s -> "Jarvis, %s" (%s)' % (n, what, got))
    return problems, lines


def regen_command(keep=KEEP):
    names = ', '.join(repr(n) for n in keep)
    return ('cd "$HOME/Touchdesigner Designs/Hue Rig" && python3 -c "import sys; sys.path.insert(0, \'jarvis\'); '
            'import shortcut_factory as f; print(f.build_all(only={%s}))"' % names.replace('"', '\\"'))


def main():
    problems, lines = check(load_set(), load_rules())
    print('\n'.join(lines))
    print('\nKeep %d, retire %d.' % (len(KEEP), len(RETIRE)))
    print('Regenerate only the kept ones (next token rotation):\n  ' + regen_command())
    if problems:
        print('\nPROBLEMS:\n  ' + '\n  '.join(problems))
        return 1
    print('\nPlan OK: every retired shortcut still has a way in.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
