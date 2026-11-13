#!/usr/bin/env python3
# =============================================================================
# NEY BRAIN (Pi) -- Rig 2.0 Phase 1, first piece (Nov 12).
# Runs the light schedule from the Pi with the Pi's OWN Hue key, but ONLY while the Mac's rig doesn't answer.
# When the Mac is up, the Mac runs the schedule exactly as before -- no double fades.
#   wind-down 22:30  red 40% -> 30% -> 22% over ~20 min
#   night     23:00  red 16% -> 12%            (catch-up until 05:00 if the Mac stayed down)
#   sunrise   08:40  deep blue -> soft sky blue 60%, full at 9:00 (catch-up until 10:30)
# A step that was missed while the Mac was asleep runs late (catch-up) instead of never.
# Heads are NOT touched from the Pi yet (parking + plug order stays on the Mac).
# Key: ~/.ney_secrets/hue_pi.json (never printed). Status: ~/NeyBrain/status.json   Log: ~/NeyBrain/brain.log
# =============================================================================
import datetime as dt, json, os, re, ssl, sys, time, urllib.request

HOME = os.path.expanduser('~')
KEY_FILE = os.path.join(HOME, '.ney_secrets', 'hue_pi.json')
BASE = os.path.join(HOME, 'NeyBrain')
STATUS_FILE = os.path.join(BASE, 'status.json')
DONE_FILE = os.path.join(BASE, 'done.json')
MAC_URLS = ('http://Michaels-MacBook-Pro-2.local:7040/', 'http://michaels-macbook-pro-2.local:7040/')
RED, NIGHT_RED = (0.69, 0.30), (0.69, 0.30)
PLUG_NAME = re.compile(r'^\s*(head|spot|plug)\b', re.I)

# name: (start HH:MM, catch-up until HH:MM, steps [(bri, xy, seconds)])
SCHEDULE = {
    'winddown': ('22:30', '23:00', [(40, RED, 60), (30, RED, 600), (22, RED, 600)]),
    'night':    ('23:00', '05:00', [(16, NIGHT_RED, 60), (12, NIGHT_RED, 120)]),
    'sunrise':  ('08:40', '10:30', [(1, (0.16, 0.10), 2), (12, (0.17, 0.15), 360), (35, (0.19, 0.22), 420),
                                    (60, (0.22, 0.27), 420)]),
}
STATE = {'mac_alive': None, 'mac_down_since': None, 'last': 'starting', 'running': None}


def log(msg):
    STATE['last'] = msg
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + msg
    print(line, flush=True)


# ---------------------------------------------------------------- Hue (Pi key)
def _key():
    with open(KEY_FILE) as f:
        return json.load(f)


def hue(method, path, body=None, timeout=5):
    k = _key()
    req = urllib.request.Request('https://%s/clip/v2/resource/%s' % (k['ip'], path),
                                 json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header('hue-application-key', k['username'])
    req.add_header('Content-Type', 'application/json')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def is_plug(light):
    md = light.get('metadata') or {}
    return md.get('archetype') == 'plug' or bool(PLUG_NAME.match(md.get('name') or '')) or 'dimming' not in light


def lamps(body):
    n = 0
    for l in hue('GET', 'light').get('data', []):
        if is_plug(l):
            continue
        hue('PUT', 'light/%s' % l['id'], body)
        n += 1
    return n


def run_steps(steps, sleep=time.sleep, put=None):
    put = put or lamps
    for bri, xy, secs in steps:
        put({'on': {'on': True}, 'dimming': {'brightness': float(bri)}, 'color': {'xy': {'x': xy[0], 'y': xy[1]}},
             'dynamics': {'duration': int(max(0.4, secs - 0.5) * 1000)}})
        sleep(secs)


# ---------------------------------------------------------------- is the Mac running the rig?
def mac_urls():
    extra = _load(os.path.join(BASE, 'brain.json'), {}).get('mac_urls') or []     # Mac's IPs, written at deploy time
    return list(extra) + [u for u in MAC_URLS if u not in extra]


def mac_answers(timeout=3):
    for u in mac_urls():
        try:
            urllib.request.urlopen(u, timeout=timeout)
            return True
        except urllib.error.HTTPError:
            return True                        # 403 'Not allowed.' = rig_control is up
        except Exception:
            continue
    return False


# ---------------------------------------------------------------- schedule logic (pure, testable)
def _mins(hhmm):
    h, m = map(int, hhmm.split(':'))
    return h * 60 + m


def due(name, now, done):
    """Is this step due now and not done for its night/morning yet? Handles catch-up past midnight."""
    start, until, _ = SCHEDULE[name]
    s, u, t = _mins(start), _mins(until), now.hour * 60 + now.minute
    if u > s:                                  # same day window
        inside, day = s <= t < u, now.date()
    else:                                      # crosses midnight (night: 23:00 -> 05:00)
        inside = t >= s or t < u
        day = now.date() if t >= s else now.date() - dt.timedelta(days=1)
    key = day.isoformat()
    if not inside or done.get(name) == key:
        return None
    if name == 'winddown' and done.get('night') == key:
        return None
    return key


def tick(now, done, mac_alive, act):
    """One check. mac_alive: has the Mac been unreachable long enough? act(name) runs the step."""
    for name in ('night', 'winddown', 'sunrise'):  # night first: if both are due after a long sleep, skip wind-down
        key = due(name, now, done)
        if not key:
            continue
        if mac_alive:
            continue                           # the Mac runs it (on time) -- leave it alone
        done[name] = key
        if name == 'night':
            done['winddown'] = key
        act(name)
        return name
    return None


# ---------------------------------------------------------------- main loop
def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def main():
    os.makedirs(BASE, exist_ok=True)
    done = _load(DONE_FILE, {})
    try:
        import front_door                            # Nov 12: the Pi is the front door (passes to the Mac, covers when it sleeps)
        front_door.start(lamps, hue, mac_urls, log)
    except Exception as e:
        log('front door failed to start: %s: %s' % (e.__class__.__name__, e))
    log('Ney brain started (schedule failover, catch-up on)')
    while True:
        now = dt.datetime.now()
        alive = mac_answers()
        if alive:
            STATE['mac_down_since'] = None
        else:
            STATE['mac_down_since'] = STATE['mac_down_since'] or time.time()
        STATE['mac_alive'] = alive
        mac_down_long = (not alive) and time.time() - STATE['mac_down_since'] >= 90   # 90 s grace: restarts / blips
        try:
            def act(name):
                STATE['running'] = name
                log('Mac not answering -- running %s from the Pi' % name)
                try:
                    run_steps(SCHEDULE[name][2])
                    log('%s done (Pi)' % name)
                except Exception as e:
                    log('%s failed: %s: %s' % (name, e.__class__.__name__, e))
                finally:
                    STATE['running'] = None
            if tick(now, done, not mac_down_long, act):
                _save(DONE_FILE, done)
            elif STATE['last'].startswith('Ney brain started') or 'watching' in STATE['last']:
                STATE['last'] = 'watching -- Mac %s' % ('up, it runs the schedule' if alive else 'not answering')
        except Exception as e:
            log('check failed: %s: %s' % (e.__class__.__name__, e))
        try:
            key_ok = os.path.exists(KEY_FILE)
            _save(STATUS_FILE, dict(at=time.strftime('%Y-%m-%d %H:%M:%S'), mac_alive=alive, key=key_ok,
                                    running=STATE['running'], last=STATE['last'], done=done))
        except OSError:
            pass
        time.sleep(30)


if __name__ == '__main__':
    main()
