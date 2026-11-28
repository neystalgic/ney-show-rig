#!/usr/bin/env python3
# =============================================================================
# SPOT POWER -- the Hue Smart Plugs on the two Focus Spots (Nov 17).
# Modelled on head_power.py (the moving heads' plugs).
#
# Why: the Focus Spots' fans run whenever they have power, even when the DMX
# output is dark. This powers them only while a look or a show act needs them.
#
# Setup (once the plugs are in), in the Hue app:
#   - name the plugs exactly  Spot 1, Spot 2
#   - put them in the same OWN room as the head plugs (e.g. "Moving heads"), not
#     the living room, so "lights on/off" in the Hue app or Siri never touches them
#   - plug setting "Power-on behaviour" (after a power cut): Off
# Until plugs with those names exist, everything here stays dormant.
#
# Rules it follows:
#   - ON when a spot look runs (uvstars, movieuv, moviechill, showuv), when the
#     show director plays a spot act (gobos, uv, burst), or when the DMX node is
#     already sending light/UV to a spot -- and ONLY if the DMX node answers
#     (power order: node first; spots with no DMX wander into their own programs)
#   - OFF after spot_idle_min (default 10) minutes with both spots dark
#   - OFF straight away if the node stops answering for node_lost_s seconds
#   - OFF with the night / off looks (after park_s so the node fades them first)
#   - you switched them off by hand (Hue app)? It leaves them off for
#     manual_hold_min minutes instead of fighting you; a spot look still wins
#   - never switches them on again within min_off_s of switching them off
#   - Spot 2 comes on -> says once "Spot 2 is on -- ceiling fan off please"
#   - only plugs named "Spot 1" / "Spot 2" are ever switched. The Mac, Scarlett
#     and projector are never on a smart plug (refused even if the name matched).
# Settings (not secret): spot_power.json next to this file.
# =============================================================================
import json, os, re, subprocess, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'spot_power.json')
LOG = '/tmp/spot_power.log'
DEFAULTS = {'enabled': True, 'spot_idle_min': 10, 'warmup_s': 20, 'park_s': 6, 'node_lost_s': 30,
            'min_off_s': 60, 'manual_hold_min': 30, 'fan_reminder': True, 'voice': 'Moira',
            'wake_acts': ['gobos', 'uv', 'burst'],
            'auto_on': True}       # Nov 18: False = the spots only come on when asked (Tap Dial hold 3 / a spot look)
NAME_RE = re.compile(r'^\s*spot\s*([12])\s*$', re.I)
NEVER_RE = re.compile(r'mac|scarlett|projector', re.I)      # AGENTS: never a plug on these
SPOT_LOOKS = {'uvstars', 'movieuv', 'moviechill', 'showuv'}  # looks that hold the spots (UV stars)
OFF_LOOKS = {'off', 'rest', 'night', 'nightlight', 'purplenight'}   # Nov 17: heads_off no longer takes the spots (independent)
FAN_LINE = 'Spot 2 is on -- ceiling fan off please.'

STATE = {'plugs': {}, 'on': {}, 'node': None, 'dark_since': None, 'lost_since': None, 'warm_until': 0.0,
         'off_at': 0.0, 'hold_until': 0.0, 'fan_said': False, 'why_on': None,
         'last': 'dormant: no plugs named Spot 1-2 yet', 'busy': False}
_lock = threading.Lock()
_now = time.time                                     # tests swap in a fake clock


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


def _hs():
    import sys
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import hue_stream
    return hue_stream


def is_spot_plug(light):
    md = light.get('metadata', {}) or {}
    return bool(NAME_RE.match(md.get('name', '') or '')) and 'dimming' not in light


def find_plugs():
    """{spot number: (light id, is_on)} for plugs named Spot 1 / Spot 2."""
    hs = _hs()
    cfg = hs.load_config()
    out = {}
    for l in hs.v2(cfg, 'light').get('data', []):
        name = (l.get('metadata', {}) or {}).get('name', '') or ''
        m = NAME_RE.match(name)
        if m and 'dimming' not in l and not NEVER_RE.search(name):   # a plug, not a lamp called "Spot 1"
            out[int(m.group(1))] = (l['id'], bool(l.get('on', {}).get('on')))
    return out


def _switch(on, plugs=None):
    hs = _hs()
    cfg = hs.load_config()
    for n, (lid, _) in sorted((plugs if plugs is not None else find_plugs()).items()):
        hs.v2(cfg, 'light/%s' % lid, 'PUT', {'on': {'on': bool(on)}})
    if not on:
        STATE.update(off_at=_now(), dark_since=None, lost_since=None, why_on=None)


def node_status():
    """The DMX node's /status (same lookup as the heads: hub_state.json dmx_host)."""
    import head_power
    return head_power.node_status()


def node_ok(st):
    return bool(st) and not st.get('error')


def hub_show():
    """The show director's state from the hub ({} when the hub is down)."""
    try:
        with urllib.request.urlopen('http://127.0.0.1:7020/api/live', timeout=2) as r:
            return json.loads(r.read()).get('show') or {}
    except Exception:
        return {}


def spots_lit(st):
    """True when the node is sending light or UV to a Focus Spot."""
    for h in (st or {}).get('heads', []) or []:
        if h.get('type') == 'focus17' and (int(h.get('master', 0) or 0) > 0 or int(h.get('uv', 0) or 0) > 0):
            return True
    return False


def calibrating(st):
    """Nov 16: Michael is calibrating -- a fixture steered from the node page, or calib.py running.
    The plugs never switch off for 'dark' / 'quiet room' while that's going on."""
    if any((h or {}).get('calibrating') for h in (st or {}).get('heads', []) or []):
        return True
    try:
        import subprocess
        return subprocess.run(['pgrep', '-f', r'[Pp]ython.*[ /]calib\.py( |$)'], capture_output=True, timeout=3).returncode == 0
    except Exception:
        return False


def wanted(st, show, s):
    """Why the spots should be powered right now (None = they're not needed)."""
    if spots_lit(st):
        return 'spot lit'
    act = (show or {}).get('act')
    if (show or {}).get('on') and act in set(s.get('wake_acts') or []):
        return 'act %s' % act
    return None


def _say(text, voice):
    try:                                              # never blocks: macOS speaks it in the background
        subprocess.Popen(['say', '-v', voice, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        pass


SAY = _say                                            # tests swap in a recorder


def _fan_note(on_map, s):
    """Spot 2 on -> one spoken reminder per power-on (AGENTS: ceiling fan off with Spot 2)."""
    if on_map.get(2):
        if not STATE['fan_said']:
            STATE['fan_said'] = True
            log('Spot 2 on -- fan reminder')
            if s.get('fan_reminder', True):
                SAY(FAN_LINE, s.get('voice') or 'Moira')
    elif 2 in on_map:
        STATE['fan_said'] = False


# ---------------------------------------------------------------- actions
def request_on(quiet=False, why='look'):
    """Power the spots (node must be up first). Returns a short message."""
    s = settings()
    if not s['enabled']:
        return 'Spot power is switched off in spot_power.json.'
    try:
        plugs = find_plugs()
    except Exception as e:
        return 'Could not reach the Hue Bridge (%s).' % e.__class__.__name__
    if not plugs:
        return '' if quiet else 'No plugs named Spot 1 / Spot 2 yet.'
    if all(on for _, on in plugs.values()):
        STATE['hold_until'] = 0.0
        return '' if quiet else 'Spots already on.'
    if not node_ok(node_status()):
        log('ON refused: DMX node not ready')
        return 'Start the DMX node first -- spots stay off until it answers.'
    try:
        with _lock:
            _switch(True, plugs)
            STATE.update(warm_until=_now() + s['warmup_s'], dark_since=None, lost_since=None, hold_until=0.0, why_on=why)
    except Exception as e:
        log('ON failed: %s' % e)
        return 'Could not switch the spot plugs (%s).' % e.__class__.__name__
    log('ON (%d plugs, %s)' % (len(plugs), why))
    _fan_note({n: True for n in plugs}, s)
    STATE['on'] = {n: True for n in plugs}
    return 'Spots powering up -- ready in about %d s.' % s['warmup_s']


def request_off(wait=None, why='asked', background=True):
    """Plugs off after the node has faded the spots (wait seconds)."""
    s = settings()
    wait = s['park_s'] if wait is None else wait

    def work():
        STATE['busy'] = True
        try:
            time.sleep(max(0, wait))
            with _lock:
                plugs = find_plugs()
                if any(on for _, on in plugs.values()):
                    _switch(False, plugs)
                    STATE['on'] = {n: False for n in plugs}
                    _fan_note(STATE['on'], s)
                    log('OFF (%s)' % why)
        except Exception as e:
            log('OFF failed: %s' % e)
        finally:
            STATE['busy'] = False
    if background:
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
    return 'Spots off in about %d s.' % wait


def after_look(look):
    """Called by rig_control after every look. Never raises."""
    try:
        if look in SPOT_LOOKS:
            return request_on(quiet=True, why=look)
        if look in OFF_LOOKS:
            return request_off(why=look)
    except Exception as e:
        log('after_look %s failed: %s' % (look, e.__class__.__name__))
    return ''


# ---------------------------------------------------------------- watcher
def _tick():
    s = settings()
    if not s['enabled']:
        STATE['last'] = 'disabled in spot_power.json'
        return
    plugs = find_plugs()
    now = _now()
    was = dict(STATE['on'])
    STATE['plugs'] = {n: lid for n, (lid, _) in plugs.items()}
    STATE['on'] = {n: on for n, (_, on) in plugs.items()}
    if not plugs:
        STATE['last'] = 'dormant: no plugs named Spot 1-2 yet'
        return
    # switched off by someone else (Hue app, a scene) while we had them on -> don't fight it
    if any(was.get(n) and not on for n, on in STATE['on'].items()) and now - STATE['off_at'] > 15:
        STATE['hold_until'] = now + s['manual_hold_min'] * 60
        log('spots switched off by hand -- leaving them off for %d min' % s['manual_hold_min'])
    _fan_note(STATE['on'], s)
    if STATE['busy']:
        return
    any_on = any(STATE['on'].values())
    st = node_status()
    STATE['node'] = 'ok' if node_ok(st) else ('error: %s' % st.get('error') if st else 'not answering')
    why = wanted(st, hub_show(), s) if node_ok(st) else None
    STATE['why_wanted'] = why
    if not any_on:
        STATE.update(dark_since=None, lost_since=None)
        if s.get('auto_on', True) and why and now >= STATE['hold_until'] and now - STATE['off_at'] >= s['min_off_s']:
            with _lock:
                _switch(True, plugs)
            STATE.update(warm_until=now + s['warmup_s'], why_on=why)
            STATE['on'] = {n: True for n in plugs}
            log('ON (%s)' % why)
            _fan_note(STATE['on'], s)
        return
    if not node_ok(st):                               # node closed with the spots still on
        STATE['lost_since'] = STATE['lost_since'] or now
        if now - STATE['lost_since'] >= s['node_lost_s']:
            with _lock:
                _switch(False, plugs)
            STATE['on'] = {n: False for n in plugs}
            log('OFF (DMX node %s for %d s)' % (STATE['node'], s['node_lost_s']))
            _fan_note(STATE['on'], s)
        return
    STATE['lost_since'] = None
    if calibrating(st):                               # never cut the power mid-calibration (Nov 16)
        STATE['dark_since'] = None
        return
    if why or now < STATE['warm_until']:
        STATE['dark_since'] = None
        return
    STATE['dark_since'] = STATE['dark_since'] or now
    if now - STATE['dark_since'] >= s['spot_idle_min'] * 60:
        with _lock:
            _switch(False, plugs)
        STATE['on'] = {n: False for n in plugs}
        log('OFF (dark for %d min -- fans off)' % s['spot_idle_min'])
        _fan_note(STATE['on'], s)


def watch(period=5.0):
    log('watcher started')
    while True:
        try:
            _tick()
        except Exception as e:
            STATE['last'] = 'check failed: %s' % e.__class__.__name__
        time.sleep(period)


def start():
    threading.Thread(target=watch, name='spot-power', daemon=True).start()


def status():
    s = settings()
    d = {k: STATE[k] for k in ('plugs', 'on', 'node', 'last', 'busy')}
    d['wanted'] = STATE.get('why_wanted')
    if STATE['dark_since']:
        d['dark_for_s'] = int(_now() - STATE['dark_since'])
    if STATE['hold_until'] > _now():
        d['hand_off_for_s'] = int(STATE['hold_until'] - _now())
    d['idle_min'] = s['spot_idle_min']
    return d


if __name__ == '__main__':                            # quick look: python3 spot_power.py
    try:
        p = find_plugs()
        print('plugs:', {n: ('on' if on else 'off') for n, (_, on) in p.items()} or 'none named Spot 1-2 yet')
    except Exception as e:
        print('Hue Bridge not reachable:', e.__class__.__name__)
    st = node_status()
    print('DMX node:', 'ok' if node_ok(st) else ('error' if st else 'not answering'))
