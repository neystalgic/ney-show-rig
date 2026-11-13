#!/usr/bin/env python3
# =============================================================================
# RIG HEALTH -- one green/amber/red light per part of the rig, for the phone page (/health).
# Checks run in the background every 10 s (inside rig_control), so the page loads instantly.
# Levels: ok (green), idle (grey: off on purpose), warn (amber), down (red).
# =============================================================================
import json, re, socket, subprocess, threading, time, urllib.request

PI = 'http://192.168.1.80:7060/status'
HUE_BRIDGE = 'http://192.168.1.75/api/0/config'
OLLAMA = 'http://127.0.0.1:11434/api/version'
HUB = 'http://127.0.0.1:7020/api/live'
CACHE = {'at': None, 'checks': []}


def _get(url, timeout=2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def _port(host, port, timeout=0.6):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def _running(name):
    return bool(subprocess.run(['/usr/bin/pgrep', '-f', name], capture_output=True, text=True).stdout.strip())


def _ping(host):
    r = subprocess.run(['/sbin/ping', '-c', '1', '-t', '2', host], capture_output=True, text=True)
    return r.returncode == 0


def row(name, level, detail):
    return {'name': name, 'level': level, 'detail': detail}


def check_all(extra):
    """extra: dict from rig_control -- state, head_power, watchdog, schedule, bridge, tap_switch."""
    out = []
    st = extra.get('state') or {}
    out.append(row('Rig control', 'ok', 'look: %s%s' % (st.get('look') or 'none',
                                                        (' since ' + st['since']) if st.get('since') else '')))
    # hub
    if _running('hue_hub.py'):
        try:
            live = _get(HUB)
            audio = str((live.get('audio') or {}).get('status') or '')
            m = re.search(r'peak (-?\d+) dB', audio)
            out.append(row('Music engine (hub)', 'ok', 'reacting to music: %s / %s%s' % (live.get('palette'), live.get('vibe'),
                                                         (', sound %s dB' % m.group(1)) if m else '')))
        except Exception:
            out.append(row('Music engine (hub)', 'down', 'running but not answering (watchdog will restart it)'))
    else:
        out.append(row('Music engine (hub)', 'idle', 'off -- only runs for shows, music and movies. Lamps work without it.'))
    # Hue bridge
    try:
        b = _get(HUE_BRIDGE)
        out.append(row('Hue lamps (bridge)', 'ok', 'connected -- lamps can be controlled'))
    except Exception as e:
        out.append(row('Hue lamps (bridge)', 'down', 'bridge not answering (%s) -- check its power / cable' % e.__class__.__name__))
    # Pi DMX node
    n = None
    try:
        n = _get(PI)
        out.append(row('Pi DMX node', 'warn' if n.get('error') else 'ok',
                       n.get('error') or '%s, %s' % (n.get('version', '?'), re.sub(r'\s*\(serial[^)]*\)', '', str(n.get('output', 'output ?'))))))
    except Exception as e:
        out.append(row('Pi DMX node', 'down', 'not answering (%s) -- heads can\'t move' % e.__class__.__name__))
    # guest mode (strobes blocked at the node)
    try:
        u = (n or {}).get('unlock') or {}
        locked = not u.get('strobe')
        out.append(row('Guest mode', 'ok' if locked else 'idle',
                       'ON -- strobes blocked at the Pi (max %s flashes/s)' % n.get('flash_hz') if locked
                       else 'off -- strobes allowed (max %s flashes/s)' % n.get('flash_hz')))
    except Exception:
        out.append(row('Guest mode', 'warn', 'unknown (Pi node not answering)'))
    # Pi brain (schedule failover)
    pb = extra.get('pi_brain')
    if not pb or pb.get('error'):
        out.append(row('Pi brain', 'idle' if not pb else 'warn', 'not deployed yet' if not pb else 'status unknown (%s)' % pb['error']))
    else:
        fresh = False
        try:
            fresh = time.time() - time.mktime(time.strptime(pb.get('at', ''), '%Y-%m-%d %H:%M:%S')) < 150
        except ValueError:
            pass
        lvl = 'ok' if fresh and pb.get('key') else 'warn'
        det = (pb.get('last') or '') if fresh else 'not reporting (stopped?)'
        if not pb.get('key'):
            det = 'no Hue key on the Pi'
        if fresh and pb.get('boot') == 'not-installed':
            lvl, det = 'warn', det + ' -- won\'t restart after a Pi reboot until the one sudo line is run'
        out.append(row('Pi brain', lvl, det))
    # heads power
    hp = extra.get('head_power') or {}
    on = [k for k, v in (hp.get('on') or {}).items() if v]
    out.append(row('Moving heads', 'ok' if on else 'idle', ('%d of %d on' % (len(on), len(hp.get('on') or {})))
                   if hp.get('on') else str(hp.get('last') or 'no plugs found')))
    # beat sender
    out.append(row('Beat sender', 'ok' if _running('beat_sender.py') else 'down',
                   'sending the beat to Unreal' if _running('beat_sender.py') else 'not running (restarts within a minute)'))
    # Jarvis brain
    try:
        v = _get(OLLAMA, 1.5)
        loaded = [m.get('name') for m in (_get('http://127.0.0.1:11434/api/ps', 1.5).get('models') or [])]
        out.append(row('Jarvis brain (Ollama)', 'ok' if loaded else 'warn',
                       ('loaded and fast (%s)' % ', '.join(loaded)) if loaded else
                       'running but model asleep -- first fuzzy command will be slow'))
    except Exception:
        out.append(row('Jarvis brain (Ollama)', 'warn', 'not running -- simple commands still work; open Ollama'))
    # Zephyrus
    out.append(row('Zephyrus', 'ok' if _ping('zephyrus.local') else 'idle',
                   'on the network' if _ping('zephyrus.local') else 'off or asleep'))
    # TouchDesigner (Claude's backup path)
    out.append(row('TouchDesigner', 'ok' if _port('127.0.0.1', 9981) else 'idle',
                   'open (visuals + backup path)' if _port('127.0.0.1', 9981) else 'closed (fine: Claude uses the bridge)'))
    # watchdog
    wd = extra.get('watchdog') or {}
    n = int(wd.get('restarts_last_hour') or 0)
    out.append(row('Hub watchdog', 'warn' if n else 'ok',
                   ('%d restart(s) this hour -- ' % n if n else '') + str(wd.get('last') or '')))
    # schedule
    sc = extra.get('schedule') or {}
    out.append(row('Light schedule', 'ok' if sc.get('enabled') else 'idle',
                   'wind-down %s, night %s, morning %s' % (sc.get('winddown'), sc.get('night'),
                                                          str(sc.get('sunrise', '')).split(' ')[0])))
    # Claude bridge
    br = extra.get('bridge') or {}
    out.append(row('Claude bridge', 'ok' if str(br.get('last', '')).startswith('ok') else 'warn',
                   'Claude can run the rig' if str(br.get('last', '')).startswith('ok') else str(br.get('last'))))
    # tap switch
    ts = extra.get('tap_switch') or {}
    out.append(row('Tap Switch', 'ok' if ts.get('device') else 'idle', str(ts.get('last') or '')))
    return out


def start(extra_fn, period=10.0):
    def loop():
        while True:
            try:
                CACHE.update(checks=check_all(extra_fn()), at=time.strftime('%H:%M:%S'))
            except Exception as e:
                CACHE.update(checks=[row('Health checks', 'warn', 'failed: %s' % e.__class__.__name__)],
                             at=time.strftime('%H:%M:%S'))
            time.sleep(period)
    threading.Thread(target=loop, name='rig-health', daemon=True).start()


def snapshot():
    return dict(CACHE)
