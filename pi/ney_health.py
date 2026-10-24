#!/usr/bin/env python3
# =============================================================================
# NEY PI -- show health watch
#
# The Hue Hub on the Mac sends this a heartbeat every 10 s (setting "pi_url").
# If the hub goes quiet, the lights lose the bridge, or TouchDesigner stops
# feeding the hub, the Pi notices within a minute and (optionally) pings your
# phone through ntfy (free app; set "ntfy_topic" in config.json).
#
#   status page:  http://ney-pi.local:7030/
#   heartbeat in: POST http://ney-pi.local:7030/beat   (JSON from the hub)
# =============================================================================
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, 'config.json')
DEFAULTS = dict(port=7030, quiet_after=60, ntfy_topic='', ntfy_server='https://ntfy.sh', show_name='Ney show')

state = {'last': None, 't': 0.0, 'alerts': {}, 'log': []}
lock = threading.Lock()


def cfg():
    c = dict(DEFAULTS)
    try:
        with open(CFG_PATH) as f:
            c.update(json.load(f))
    except Exception:
        pass
    return c


def log(msg):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + msg
    print(line, flush=True)
    with lock:
        state['log'] = (state['log'] + [line])[-200:]


def notify(title, msg):
    c = cfg()
    log('ALERT %s: %s' % (title, msg))
    if not c['ntfy_topic']:
        return
    try:
        rq = urllib.request.Request('%s/%s' % (c['ntfy_server'].rstrip('/'), c['ntfy_topic']),
                                    data=msg.encode(), headers={'Title': '%s: %s' % (c['show_name'], title)})
        urllib.request.urlopen(rq, timeout=8).read()
    except Exception as e:
        log('could not send the phone alert (%s)' % e)


def problems(beat, age, quiet_after):
    """[(key, title, message)] for what is wrong right now."""
    out = []
    if beat is None or age > quiet_after:
        how = 'yet' if beat is None else 'for %d s' % age
        out.append(('hub', 'Hue Hub silent', 'No heartbeat from the Hue Hub %s -- is it running?' % how))
        return out
    if 'streaming' not in str(beat.get('bridge', '')):
        out.append(('bridge', 'Lights offline', 'The hub is not streaming to the lights: %s' % beat.get('bridge')))
    if beat.get('feed') is False:
        out.append(('td', 'TouchDesigner quiet', 'TouchDesigner is not feeding the hub -- is the show open?'))
    return out


def watch():
    started = time.time()
    while True:
        c = cfg()
        if time.time() - started < c['quiet_after']:      # give the Mac time to say hello after a reboot
            time.sleep(5)
            continue
        with lock:
            beat, t = state['last'], state['t']
        age = time.time() - t if t else 1e9
        now_bad = {k: (title, msg) for k, title, msg in problems(beat, age, c['quiet_after'])}
        with lock:
            was = dict(state['alerts'])
            if 'hub' in now_bad:                          # hub silent: the other checks are unknown, keep them
                now_bad.update({k: v for k, v in was.items() if k != 'hub'})
            state['alerts'] = now_bad
        for k, (title, msg) in now_bad.items():
            if k not in was:
                notify(title, msg)
        for k in was:
            if k not in now_bad:
                notify('Resolved', '%s -- fixed' % was[k][0])
        time.sleep(5)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path != '/beat':
            self.send_response(404); self.end_headers(); return
        try:
            n = int(self.headers.get('Content-Length', 0))
            beat = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            self.send_response(400); self.end_headers(); return
        with lock:
            state['last'], state['t'] = beat, time.time()
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')

    def do_GET(self):
        with lock:
            beat, t, alerts, lg = state['last'], state['t'], dict(state['alerts']), list(state['log'][-30:])
        age = int(time.time() - t) if t else None
        body = {'heartbeat_age_s': age, 'problems': {k: v[1] for k, v in alerts.items()}, 'last_beat': beat,
                'log': lg}
        data = json.dumps(body, indent=1).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(data)


def main():
    c = cfg()
    threading.Thread(target=watch, daemon=True).start()
    log('Ney Pi health watch on port %d' % c['port'])
    ThreadingHTTPServer(('0.0.0.0', c['port']), H).serve_forever()


if __name__ == '__main__':
    main()
