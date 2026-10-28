#!/usr/bin/env python3
"""Ney Sky server (runs on the Pi, port 7050).

Serves the ceiling sky page and two small JSON endpoints:
  GET/POST /state   live look from the Hue Hub: {"mode": "sky|music|movie|rest|off", "tint": [r,g,b], "level": 0..1}
  GET/POST /config  aiming + look settings, saved to sky_config.json (set from /calibrate on your phone)
Nothing here can make the sky flash: the page eases every change itself.
"""
import json, os, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('SKY_PORT', '7050'))
CFG_FILE = os.path.join(HERE, 'sky_config.json')
FILES = {'/': 'index.html', '/index.html': 'index.html', '/sky.js': 'sky.js', '/sky_data.js': 'sky_data.js',
         '/calibrate': 'calibrate.html', '/calibrate.html': 'calibrate.html'}
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8'}
MODES = {'sky', 'music', 'movie', 'rest', 'off'}
lock = threading.Lock()
state = {'mode': 'sky', 'tint': [0.6, 0.3, 1.0], 'level': 0.0, 'at': 0}


def clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))


def load_cfg():
    try:
        with open(CFG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


cfg = load_cfg()


def clean_cfg(new):
    out = {}
    rules = {'fov': (40, 170), 'rot': (-360, 720), 'lines': (0, 1), 'maglim': (2, 6.5), 'minClouds': (0, 1),
             'maxClouds': (0, 1), 'scale': (0.3, 1.5), 'fps': (10, 60)}
    for k, (lo, hi) in rules.items():
        if k in new:
            out[k] = clamp(new[k], lo, hi)
    for k in ('flip', 'calib', 'weather'):
        if k in new:
            out[k] = bool(new[k])
    if 'corners' in new:
        c = new['corners']
        if isinstance(c, list) and len(c) == 4 and all(isinstance(p, list) and len(p) == 2 for p in c):
            out['corners'] = [[clamp(p[0], -0.5, 1.5), clamp(p[1], -0.5, 1.5)] for p in c]
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/state':
            with lock:
                return self.send(200, json.dumps(state))
        if path == '/config':
            with lock:
                return self.send(200, json.dumps(cfg))
        name = FILES.get(path)
        if not name:
            return self.send(404, '{"error":"not found"}')
        with open(os.path.join(HERE, name), 'rb') as f:
            return self.send(200, f.read(), TYPES[os.path.splitext(name)[1]])

    def body(self):
        n = min(int(self.headers.get('Content-Length', 0) or 0), 20000)
        try:
            return json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return None

    def do_POST(self):
        global cfg
        path = self.path.split('?')[0]
        b = self.body()
        if not isinstance(b, dict):
            return self.send(400, '{"error":"bad json"}')
        if path == '/state':
            with lock:
                if b.get('mode') in MODES:
                    state['mode'] = b['mode']
                if isinstance(b.get('tint'), list) and len(b['tint']) == 3:
                    state['tint'] = [clamp(x, 0, 1) for x in b['tint']]
                if 'level' in b:
                    state['level'] = clamp(b['level'], 0, 1)
                state['at'] = time.time()
                return self.send(200, json.dumps(state))
        if path == '/config':
            with lock:
                cfg.update(clean_cfg(b))
                tmp = CFG_FILE + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(cfg, f, indent=1)
                os.replace(tmp, CFG_FILE)
                return self.send(200, json.dumps(cfg))
        return self.send(404, '{"error":"not found"}')


def watchdog():
    # if the hub stops talking during a show, drift back to the real sky
    while True:
        time.sleep(5)
        with lock:
            if state['mode'] == 'music' and time.time() - state['at'] > 30:
                state['mode'], state['level'] = 'sky', 0.0


if __name__ == '__main__':
    threading.Thread(target=watchdog, daemon=True).start()
    print(f'Ney Sky on http://0.0.0.0:{PORT}/  (aim it at /calibrate)')
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
