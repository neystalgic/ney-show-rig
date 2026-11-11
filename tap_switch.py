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
        if stamp is None:
            continue
        first = n not in STATE['seen']
        if STATE['seen'].get(n) == stamp:
            continue
        STATE['seen'][n] = stamp
        if first:                                       # ignore whatever was pressed before we started
            continue
        if ev in ('initial_press', 'short_release', 'long_press', None):
            if ev == 'short_release' and STATE.get('pressed_at', {}).get(n, 0) > time.time() - 1.0:
                continue                                # already acted on its initial_press
            STATE.setdefault('pressed_at', {})[n] = time.time()
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
