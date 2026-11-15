#!/usr/bin/env python3
"""Offline tests for trim_check.py. No network, no token, no shortcuts signed or opened:
sockets and subprocess are blocked for the whole run, and the live factory / jarvis files are only parsed (ast)."""
import os, socket, subprocess, sys, tempfile, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _blocked(*a, **k):
    raise RuntimeError('network/subprocess blocked in tests')


socket.socket.connect = _blocked
socket.create_connection = _blocked
subprocess.run = subprocess.Popen = _blocked

import trim_check as tc

OK = FAIL = 0


def t(cond, label):
    global OK, FAIL
    if cond:
        OK += 1
    else:
        FAIL += 1
        print('FAIL:', label)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


live_factory = os.path.join(tc.RIG, 'jarvis', 'shortcut_factory.py')
live_jarvis = os.path.join(tc.RIG, 'jarvis', 'jarvis.py')
before = (sha(live_factory), sha(live_jarvis))

# 1. the real files parse without running them
SET = tc.load_set()
RULES = tc.load_rules()
t(len(SET) >= 10 and all(len(s) == 3 for s in SET), 'SET parsed as (name, kind, path)')
t(any(a == 'show' for _, a in RULES), 'RULES parsed')
t('Jarvis' in [s[0] for s in SET], 'Jarvis is in the factory')

# 2. the plan against the real files: sound, ~6 kept, the musts are kept
problems, lines = tc.check(SET, RULES)
t(problems == [], 'plan has no problems: %s' % problems)
t(5 <= len(tc.KEEP) <= 7, 'about six kept')
for must in ('Jarvis', 'Goodnight', 'Morning'):       # Back Tap + the two automations depend on these
    t(must in tc.KEEP, '%s kept' % must)
t(any(l.startswith('DECIDE') and 'Movie Mode' in l for l in lines), 'Movie Mode gap is surfaced, not hidden')
t(sum(l.startswith(('KEEP', 'RETIRE', 'DECIDE')) for l in lines) == len(SET), 'one line per shortcut')

# 3. routing matches Jarvis for the phrases the plan relies on
for phrase, want in [('Jarvis, light show', 'show'), ('safe show', 'showsafe'), ('movie night', 'movienight'),
                     ('movie stars', 'movieuv'), ('rainbow', 'rainbow'), ('lights off', 'off'),
                     ('guest mode', 'guest_on'), ('goodnight', 'night'), ('hey siri, purple', None)]:
    got = tc.route(phrase, RULES)
    if want:
        t(got == want, '%r -> %r (got %r)' % (phrase, want, got))
t(tc.route('movie mode', RULES) != 'movie', 'confirms the gap: "movie mode" does not reach the reactive look')

# 4. the checker catches mistakes
fake = [('A', 'speak', '/show'), ('B', 'speak', '/off'), ('C', 'page', '/hub')]
p, _ = tc.check(fake, RULES, keep={'C': 'x'}, retire={'A': ('jarvis', 'light show')})
t(any('B is in the factory but not in the plan' in x for x in p), 'forgotten shortcut caught')
p, _ = tc.check(fake, RULES, keep={'C': 'x', 'B': 'y'}, retire={'A': ('jarvis', 'lights off'), 'B': ('jarvis', 'lights off')})
t(any('both kept and retired' in x for x in p), 'double listing caught')
t(any('"Jarvis, lights off" goes to' in x for x in p), 'wrong phrase caught')
p, _ = tc.check(fake, RULES, keep={'C': 'x', 'B': 'y'}, retire={'A': ('page', 'Gone')})
t(any('not kept' in x for x in p), 'retired-to-a-dropped-page caught')
p, _ = tc.check(fake, RULES, keep={'C': 'x', 'B': 'y', 'Z': 'z'}, retire={'A': ('jarvis', 'light show')})
t(any('Z is in the plan but not in the factory' in x for x in p), 'unknown name caught')

# 5. parsing never executes the file (a booby-trapped copy would raise if run)
with tempfile.TemporaryDirectory() as d:
    trap = os.path.join(d, 'f.py')
    open(trap, 'w').write("raise SystemExit('executed!')\nSET = [('X', 'speak', '/off')]\n")
    t(tc.load_set(trap) == [('X', 'speak', '/off')], 'ast-only parse, file not executed')

# 6. regenerate command: only kept names, uses the existing build_all(only=...), no token in it
cmd = tc.regen_command()
t('build_all(only={' in cmd and all(repr(n) in cmd for n in tc.KEEP), 'regen command lists the kept six')
t(not any(repr(n) in cmd for n in tc.RETIRE), 'regen command has no retired names')
t('token' not in cmd.lower(), 'no token in the command')

# 7. live files untouched
t((sha(live_factory), sha(live_jarvis)) == before, 'live files unchanged')

print('%d/%d passed' % (OK, OK + FAIL))
sys.exit(1 if FAIL else 0)
