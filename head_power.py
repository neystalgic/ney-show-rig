#!/usr/bin/env python3
# =============================================================================
# HEAD POWER -- the Hue Smart Plugs on the four moving heads.
#
# Why: going dark over DMX turns the LEDs off, but the heads' fans keep running
# until the power is cut. This cuts it when the heads aren't being used, and
# brings it back (in the right order) when a show starts.
#
# Setup (once the plugs arrive), in the Hue app:
#   - name the plugs exactly  Head 1, Head 2, Head 3, Head 4
#   - put them in their OWN room (e.g. "Moving heads"), not the living room, so
#     "lights on/off" in the Hue app or Siri never touches them
#   - plug setting "Power-on behaviour" (after a power cut): Off
# Until plugs with those names exist, everything here stays dormant.
#
# Rules it follows:
#   - ON only if the DMX node on the Zephyrus answers and its Enttec output is fine
#     (heads powered with no DMX can wander into their own auto programs)
#   - OFF after the heads have been dark for idle_min minutes
#   - OFF straight away if the node stops answering for node_lost_s seconds
#     (covers "closed the node with the heads still on")
#   - rest / off: the hub stops first, the node parks the heads pointing up and
#     fades them out, THEN the plugs go off park_s seconds later
#   - only plugs named "Head 1-4" are ever switched. The Mac, Scarlett and
#     projector are never on a smart plug.
# Settings (not secret): head_power.json next to this file.
# =============================================================================
import json, os, re, socket, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'head_power.json')
HUB_STATE = os.path.join(HERE, 'hub_state.json')
LOG = '/tmp/head_power.log'
NODE_PORT = 7060
DEFAULTS = {'enabled': True, 'idle_min': 10, 'warmup_s': 25, 'park_s': 10, 'node_lost_s': 30}
NAME_RE = re.compile(r'^\s*head\s*([1-4])\s*$', re.I)

STATE = {'plugs': {}, 'on': {}, 'node': None, 'dark_since': None, 'lost_since': None,
         'warm_until': 0.0, 'last': 'dormant: no plugs named Head 1-4 yet', 'busy': False}
_lock = threading.Lock()


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


def is_plug(light):
    """True for any on/off plug (never treat one like a lamp)."""
    md = light.get('metadata', {}) or {}
    return md.get('archetype') == 'plug' or bool(NAME_RE.match(md.get('name', '') or ''))


def _hs():
    import sys
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import hue_stream
    return hue_stream


def find_plugs():
    """{head number: (light id, is_on)} for plugs named Head 1-4."""
    hs = _hs()
    cfg = hs.load_config()
    out = {}
    for l in hs.v2(cfg, 'light').get('data', []):
        m = NAME_RE.match((l.get('metadata', {}) or {}).get('name', '') or '')
        if m and 'dimming' not in l:                 # a plug, not a lamp someone named "Head 1"
            out[int(m.group(1))] = (l['id'], bool(l.get('on', {}).get('on')))
    return out


def _switch(on):
    hs = _hs()
    cfg = hs.load_config()
    for n, (lid, _) in sorted(find_plugs().items()):
        hs.v2(cfg, 'light/%s' % lid, 'PUT', {'on': {'on': bool(on)}})


def node_status():
    host = 'zephyrus'
    try:
        with open(HUB_STATE) as f:
            host = str(json.load(f).get('settings', {}).get('dmx_host') or host).strip()
    except (OSError, ValueError):
        pass
    try:
        ip = socket.getaddrinfo(host, NODE_PORT, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        with urllib.request.urlopen('http://%s:%d/status' % (ip, NODE_PORT), timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return None


def node_ok(st):
    return bool(st) and not st.get('error')


# ---------------------------------------------------------------- actions
def request_on(quiet=False):
    """Power the heads (node must be up first). Returns a short message."""
    s = settings()
    if not s['enabled']:
        return 'Head power is switched off in head_power.json.'
    try:
        plugs = find_plugs()
    except Exception as e:
        return 'Could not reach the Hue Bridge (%s).' % e.__class__.__name__
    if not plugs:
        return '' if quiet else 'No plugs named Head 1-4 yet.'
    st = node_status()
    if not node_ok(st):
        log('ON refused: DMX node not ready')
        return 'Start the DMX node on the Zephyrus first -- heads stay off until it answers.'
    try:
        with _lock:
            _switch(True)
            STATE.update(warm_until=time.time() + s['warmup_s'], dark_since=time.time(), lost_since=None)
    except Exception as e:
        log('ON failed: %s' % e)
        return 'Could not switch the head plugs (%s).' % e.__class__.__name__
    log('ON (%d plugs)' % len(plugs))
    return 'Heads powering up -- ready in about %d s (they do a reset sweep first).' % s['warmup_s']


def request_off(wait=None, why='asked'):
    """Plugs off after the heads have parked (wait seconds). Runs in the background."""
    s = settings()
    wait = s['park_s'] if wait is None else wait

    def work():
        STATE['busy'] = True
        try:
            time.sleep(max(0, wait))
            with _lock:
                if find_plugs():
                    _switch(False)
                    log('OFF (%s)' % why)
        except Exception as e:
            log('OFF failed: %s' % e)
        finally:
            STATE['busy'] = False
    threading.Thread(target=work, daemon=True).start()
    return 'Heads parking, power off in about %d s.' % wait


# ---------------------------------------------------------------- watcher
def _tick():
    s = settings()
    if not s['enabled']:
        STATE['last'] = 'disabled in head_power.json'
        return
    plugs = find_plugs()
    STATE['plugs'] = {n: lid for n, (lid, _) in plugs.items()}
    STATE['on'] = {n: on for n, (_, on) in plugs.items()}
    if not plugs:
        STATE['last'] = 'dormant: no plugs named Head 1-4 yet'
        return
    now = time.time()
    if not any(on for _, on in plugs.values()) or STATE['busy']:
        STATE.update(dark_since=None, lost_since=None)
        return
    st = node_status()
    STATE['node'] = 'ok' if node_ok(st) else ('error: %s' % st.get('error') if st else 'not answering')
    if not node_ok(st):                               # node closed / Enttec unplugged with the heads still on
        STATE['lost_since'] = STATE['lost_since'] or now
        if now - STATE['lost_since'] >= s['node_lost_s']:
            with _lock:
                _switch(False)
            log('OFF (DMX node %s for %d s)' % (STATE['node'], s['node_lost_s']))
            STATE.update(lost_since=None, dark_since=None)
        return
    STATE['lost_since'] = None
    dark = all(int(h.get('master', 0)) == 0 for h in st.get('heads', []))
    if not dark or now < STATE['warm_until']:
        STATE['dark_since'] = None if not dark else (STATE['dark_since'] or now)
        return
    STATE['dark_since'] = STATE['dark_since'] or now
    if now - STATE['dark_since'] >= s['idle_min'] * 60:
        with _lock:
            _switch(False)
        log('OFF (dark for %d min -- fans off)' % s['idle_min'])
        STATE['dark_since'] = None


def watch(period=5.0):
    log('watcher started')
    while True:
        try:
            _tick()
        except Exception as e:
            STATE['last'] = 'check failed: %s' % e.__class__.__name__
        time.sleep(period)


def start():
    threading.Thread(target=watch, name='head-power', daemon=True).start()


def status():
    s = settings()
    d = {k: STATE[k] for k in ('plugs', 'on', 'node', 'last', 'busy')}
    if STATE['dark_since']:
        d['dark_for_s'] = int(time.time() - STATE['dark_since'])
    d['idle_min'] = s['idle_min']
    return d


if __name__ == '__main__':                            # quick look: python3 head_power.py
    try:
        p = find_plugs()
        print('plugs:', {n: ('on' if on else 'off') for n, (_, on) in p.items()} or 'none named Head 1-4 yet')
    except Exception as e:
        print('Hue Bridge not reachable:', e.__class__.__name__)
    st = node_status()
    print('DMX node:', 'ok' if node_ok(st) else ('error' if st else 'not answering'))
