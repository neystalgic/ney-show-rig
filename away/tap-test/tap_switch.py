#!/usr/bin/env python3
# =============================================================================
# TAP SWITCH -- the Hue Tap Switch Mini (arrives Thu Nov 12) drives the rig.  Michael's layout (Nov 11):
#   1  LIGHT SHOW  heads, spots + Hue lamps moving together to the music (and the visualizer follows the hub)
#   2  MOVIE       movie lights, both spots UV-only on the galaxy tapestry, fill speaker +6 dB
#   3  CYCLE       each press = the next look in CYCLE below (colours, settings, pizzazz)
#   4  NIGHT       heads park + power off, lamps to the red night light
# Setup in the Hue app: pair it, leave every button with NO action (otherwise the bridge also switches
# lights itself). Name it anything with "tap" in it, or set its id in tap_switch.json.
# Runs inside rig_control (always on): polls the bridge's button state ~3x a second. Dormant until found.
# Log: /tmp/tap_switch.log
# Nov 14 (away loop): one press = one action -- a long hold no longer fires twice (see should_act), and the
# very first press of a never-pressed button is no longer swallowed.
# =============================================================================
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'tap_switch.json')
LOG = '/tmp/tap_switch.log'
BUTTONS = {1: 'show', 2: 'movieuv', 3: 'cycle', 4: 'night'}
CYCLE = ['rainbow', 'flash', 'hype', 'movieglow', 'cozy']        # button 3 steps through these
STATE = {'device': None, 'last': 'dormant: no Tap Switch found yet', 'seen': {}, 'cycle_i': -1}


def log(msg):
    STATE['last'] = msg
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


def settings():
    s = {'enabled': True, 'device_id': None, 'cycle': CYCLE, 'buttons': {str(k): v for k, v in BUTTONS.items()}}
    try:
        with open(SETTINGS) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def _hs():
    import sys
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import hue_stream
    return hue_stream


def find_device(hs, cfg, s):
    if s.get('device_id'):
        return s['device_id']
    for d in hs.v2(cfg, 'device').get('data', []):
        name = ((d.get('metadata') or {}).get('name') or '').lower()
        prod = ((d.get('product_data') or {}).get('product_name') or '').lower()
        if 'tap' in name or 'tap' in prod:
            return d['id']
    return None


HOLD_MAX_S = 3.0      # a press counts as "still held" this long after its last event (repeats refresh it)


def should_act(n, ev):
    """One press = one action (Nov 14 fix, found by the away/tap-test dry run).
    Hue sends: initial_press -> short_release            (a tap)
               initial_press -> long_press -> repeat ... -> long_release   (a hold)
    Before, a hold acted TWICE (initial_press and long_press), so button 3 skipped a look.
    Now: initial_press always acts (it is always a new press). long_press / repeat / short_release
    only act if we never saw that press start (it happened between two polls)."""
    held = STATE.setdefault('held', {})
    now = time.time()
    recent = held.get(n, 0) > now - HOLD_MAX_S
    if ev == 'initial_press':
        held[n] = now
        return True
    if ev in ('long_press', 'repeat'):
        held[n] = now                                   # keep the press "held" while the button is down
        return not recent
    if ev == 'short_release':
        held.pop(n, None)
        return not recent
    if ev == 'long_release':
        held.pop(n, None)
        return False
    return ev is None                                   # very old bridges report no event name


def poll(on_press):
    s = settings()
    if not s['enabled']:
        STATE['last'] = 'disabled in tap_switch.json'
        return
    hs = _hs()
    cfg = hs.load_config()
    if not STATE['device']:
        STATE['device'] = find_device(hs, cfg, s)
        if not STATE['device']:
            STATE['last'] = 'dormant: no Tap Switch found yet'
            return
        log('found the Tap Switch (%s)' % STATE['device'])
    for b in hs.v2(cfg, 'button').get('data', []):
        if (b.get('owner') or {}).get('rid') != STATE['device']:
            continue
        n = int((b.get('metadata') or {}).get('control_id', 0))
        rep = (b.get('button') or {}).get('button_report') or {}
        stamp, ev = rep.get('updated'), rep.get('event')
        if n not in STATE['seen']:                      # first look: remember what was there before we started
            STATE['seen'][n] = stamp                    # (even "never pressed", so the FIRST real press counts)
            continue
        if stamp is None or STATE['seen'][n] == stamp:
            continue
        STATE['seen'][n] = stamp
        if not should_act(n, ev):
            continue
        action = s['buttons'].get(str(n))
        if action == 'cycle':
            lst = s.get('cycle') or CYCLE
            STATE['cycle_i'] = (STATE['cycle_i'] + 1) % len(lst)
            action = lst[STATE['cycle_i']]
        if action:
            log('button %d (%s) -> %s' % (n, ev, action))
            on_press(action)


def watch(on_press, period=0.33):
    log('tap switch watcher started')
    while True:
        try:
            poll(on_press)
        except Exception as e:
            STATE['last'] = 'check failed: %s' % e.__class__.__name__
            time.sleep(2.0)
        time.sleep(period)


def start(on_press):
    threading.Thread(target=watch, args=(on_press,), name='tap-switch', daemon=True).start()


def status():
    return dict(device=STATE['device'], last=STATE['last'], cycle_next=(STATE['cycle_i'] + 1))
