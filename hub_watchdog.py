#!/usr/bin/env python3
# =============================================================================
# HUB WATCHDOG -- restarts the Hue Hub when it wedges, so a frozen show fixes itself.
#
# Runs inside rig_control (the always-on switchboard), checking every 5 s.
# It only ever acts on a hub that is RUNNING but broken -- a hub you stopped on
# purpose stays stopped. Three kinds of broken:
#   1. frozen:      the process is there but its web API hasn't answered for 45 s
#   2. bridge lost: the hub says "not connected" / "lost the bridge" / fell back to rehearsal, for 90 s
#                   (it retries every 5 s on its own; 90 s of that means it's stuck)
#   3. deaf:        the audio stream stopped delivering blocks for 30 s, or the hub
#                   hears nothing at all ("no sound arriving") for 60 s
# Restart = the same safe sequence as by hand (Nov 7): polite stop, force after 10 s,
# WAIT 30 s so the bridge and the Scarlett let go, start, put the palette + vibe back.
# Never more than 3 restarts an hour; after that it stops trying and says so.
# Log: /tmp/hub_watchdog.log     Settings (not secret): hub_watchdog.json
# =============================================================================
import json, os, re, subprocess, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'hub_watchdog.json')
LOG = '/tmp/hub_watchdog.log'
DEFAULTS = {'enabled': True, 'api_dead_s': 45, 'bridge_lost_s': 90, 'audio_stuck_s': 30,
            'no_sound_s': 60, 'settle_s': 30, 'max_per_hour': 3, 'grace_s': 120}
BAD_BRIDGE = re.compile(r'^(not connected|lost the bridge|rehearsal)', re.I)   # rehearsal = it couldn't reach the bridge at start

STATE = {'last': 'starting', 'restarts': [], 'dead_since': None, 'bridge_since': None,
         'deaf_since': None, 'blocks': None, 'blocks_t': None, 'grace_until': 0.0,
         'restarting': False, 'last_ok': None, 'last_good': {}}


def log(msg):
    STATE['last'] = msg
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


def settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def hub_running():
    r = subprocess.run(['/usr/bin/pgrep', '-f', 'hue_hub.py'], capture_output=True, text=True)
    return bool(r.stdout.strip())


def hub_live(timeout=3):
    with urllib.request.urlopen('http://127.0.0.1:7020/api/live', timeout=timeout) as r:
        return json.loads(r.read())


def _reset_timers():
    STATE.update(dead_since=None, bridge_since=None, deaf_since=None, blocks=None, blocks_t=None)


def _problem(live, now, s):
    """The reason to restart, or None."""
    bridge = str(live.get('bridge') or '')
    if BAD_BRIDGE.match(bridge) and not live.get('blackout'):
        STATE['bridge_since'] = STATE['bridge_since'] or now
        if now - STATE['bridge_since'] >= s['bridge_lost_s']:
            return 'Hue bridge stuck for %d s (%s)' % (s['bridge_lost_s'], bridge[:60])
    else:
        STATE['bridge_since'] = None

    blocks = live.get('audio_blocks')                     # newer hubs report the audio block counter
    if isinstance(blocks, int):
        if blocks != STATE['blocks']:
            STATE.update(blocks=blocks, blocks_t=now)
        elif STATE['blocks_t'] and now - STATE['blocks_t'] >= s['audio_stuck_s']:
            return 'audio stream frozen for %d s' % s['audio_stuck_s']

    heard = str((live.get('audio') or {}).get('status') or '')
    if 'no sound arriving' in heard:
        STATE['deaf_since'] = STATE['deaf_since'] or now
        if now - STATE['deaf_since'] >= s['no_sound_s']:
            return 'no sound arriving from the Scarlett for %d s' % s['no_sound_s']
    else:
        STATE['deaf_since'] = None
    return None


def restart(why, stop_hub, start_hub, after_start=None):
    """The Nov 7 recipe: stop, wait, start, put the look back."""
    s = settings()
    good = dict(STATE['last_good'])
    STATE['restarting'] = True
    try:
        log('RESTART (%s) -- palette %s, vibe %s' % (why, good.get('palette'), good.get('vibe')))
        stop_hub()
        if hub_running():                                  # a hub stuck in the MIDI or audio driver
            subprocess.run(['/usr/bin/pkill', '-9', '-f', 'hue_hub.py'])
        time.sleep(s['settle_s'])                          # let the bridge + Scarlett let go (never back-to-back)
        start_hub(good.get('palette') or 'music')
        if after_start:
            after_start(good)
        log('restarted OK')
    except Exception as e:
        log('restart failed: %s: %s' % (e.__class__.__name__, e))
    finally:
        STATE['restarts'].append(time.time())
        STATE['grace_until'] = time.time() + s['grace_s']  # give the new hub time to settle in
        _reset_timers()
        STATE['restarting'] = False


def _tick(busy, stop_hub, start_hub, after_start):
    s = settings()
    now = time.time()
    if not s['enabled']:
        STATE['last'] = 'disabled in hub_watchdog.json'
        return
    if busy() or STATE['restarting'] or now < STATE['grace_until']:
        _reset_timers()
        return
    if not hub_running():                                  # stopped on purpose (or not started): leave it be
        _reset_timers()
        STATE['last'] = 'hub not running -- nothing to watch'
        return
    try:
        live = hub_live()
    except Exception:
        STATE['dead_since'] = STATE['dead_since'] or now
        STATE['last'] = 'hub not answering for %d s' % (now - STATE['dead_since'])
        why = 'web API frozen for %d s' % s['api_dead_s'] if now - STATE['dead_since'] >= s['api_dead_s'] else None
    else:
        STATE['dead_since'] = None
        STATE['last_ok'] = time.strftime('%H:%M:%S')
        STATE['last_good'] = {k: live.get(k) for k in ('palette', 'vibe', 'energy', 'blackout')}
        why = _problem(live, now, s)
        if not why:
            STATE['last'] = 'hub OK'
    if not why:
        return
    STATE['restarts'] = [t for t in STATE['restarts'] if now - t < 3600]
    if len(STATE['restarts']) >= s['max_per_hour']:
        if now - STATE.get('gave_up', 0) > 3600:
            STATE['gave_up'] = now
            log('giving up: %s, but already restarted %d times this hour -- needs a person' % (why, len(STATE['restarts'])))
        STATE['last'] = 'gave up (%s) -- needs a person' % why
        return
    restart(why, stop_hub, start_hub, after_start)


def watch(busy, stop_hub, start_hub, after_start=None, period=5.0):
    log('watchdog started')
    while True:
        try:
            _tick(busy, stop_hub, start_hub, after_start)
        except Exception as e:
            STATE['last'] = 'check failed: %s' % e.__class__.__name__
        time.sleep(period)


def start(busy, stop_hub, start_hub, after_start=None):
    threading.Thread(target=watch, args=(busy, stop_hub, start_hub, after_start),
                     name='hub-watchdog', daemon=True).start()


def status():
    now = time.time()
    return dict(last=STATE['last'], last_ok=STATE['last_ok'], restarting=STATE['restarting'],
                restarts_last_hour=len([t for t in STATE['restarts'] if now - t < 3600]))
