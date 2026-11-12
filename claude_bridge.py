#!/usr/bin/env python3
# =============================================================================
# CLAUDE BRIDGE -- lets Claude run the rig through this folder, no TouchDesigner needed.
#
# Claude (through the connected folder) drops a small file in bridge/inbox/:
#     {"do": "purple"}            any look name rig_control knows
#     {"do": "ask", "text": "..."}  a Jarvis sentence
#     {"do": "status"}            writes the rig's state
#     {"do": "reload"}            rig_control restarts itself (launchd brings it back) -- new code goes live
#     {"do": "hub_restart"}       hub stop, 20 s pause, start (never back-to-back)
#     {"do": "beat_start"}        start the beat sender if it isn't running
# Every 2 s rig_control reads the inbox, does it, writes bridge/outbox/<same name>.reply.json,
# and moves the request to bridge/done/. Anything not on the list -> bridge/rejected/.
# Requests older than 10 minutes are rejected (stale). Nothing is ever deleted.
# Runs inside rig_control (started at the bottom of rig_control.py).
# =============================================================================
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'bridge')
DIRS = {k: os.path.join(ROOT, k) for k in ('inbox', 'outbox', 'done', 'rejected')}
FIXED = ('ask', 'status', 'reload', 'hub_restart', 'beat_start')
MAX_AGE = 600
STATE = {'last': 'starting', 'handled': 0}


def _move(path, where):
    dest = os.path.join(DIRS[where], os.path.basename(path))
    if os.path.exists(dest):
        dest = dest + '.%d' % int(time.time() * 1000)
    os.replace(path, dest)


def _reply(name, obj):
    tmp = os.path.join(DIRS['outbox'], '.%s.tmp' % name)
    with open(tmp, 'w') as f:
        json.dump(dict(obj, at=time.strftime('%Y-%m-%d %H:%M:%S')), f, indent=1)
    os.replace(tmp, os.path.join(DIRS['outbox'], name + '.reply.json'))


def handle_file(path, h, now=None):
    """h = dict of handlers: looks (set), look(name), ask(text), status(), reload(), hub_restart(), beat_start()."""
    name = os.path.basename(path)
    now = now or time.time()
    try:
        if now - os.path.getmtime(path) > MAX_AGE:
            raise ValueError('stale (older than %d s)' % MAX_AGE)
        with open(path) as f:
            req = json.load(f)
        do = str(req.get('do', '')).strip()
        if do in h['looks']:
            h['look'](do)
            out = {'ok': True, 'did': do}
        elif do == 'ask':
            out = {'ok': True, 'did': 'ask', 'reply': h['ask'](str(req.get('text', '')))}
        elif do == 'status':
            out = {'ok': True, 'did': 'status', 'status': h['status']()}
        elif do in ('reload', 'hub_restart', 'beat_start'):
            out = {'ok': True, 'did': do}
        else:
            raise ValueError('not allowed: %r' % do)
    except Exception as e:
        _reply(name, {'ok': False, 'error': '%s: %s' % (e.__class__.__name__, e)})
        _move(path, 'rejected')
        return False
    _reply(name, out)
    _move(path, 'done')
    STATE['handled'] += 1
    if out['did'] in ('reload', 'hub_restart', 'beat_start'):     # after the reply is written
        threading.Thread(target=h[out['did']], daemon=True).start()
    return True


def tick(h):
    files = sorted(f for f in os.listdir(DIRS['inbox']) if f.endswith('.json') and not f.startswith('.'))
    for f in files:
        handle_file(os.path.join(DIRS['inbox'], f), h)
    STATE['last'] = 'ok %s' % time.strftime('%H:%M:%S')


def watch(h, period=2.0):
    for d in DIRS.values():
        os.makedirs(d, exist_ok=True)
    while True:
        try:
            tick(h)
        except Exception as e:
            STATE['last'] = 'error %s' % e.__class__.__name__
        time.sleep(period)


def start(h):
    threading.Thread(target=watch, args=(h,), name='claude-bridge', daemon=True).start()


def status():
    return dict(STATE)
