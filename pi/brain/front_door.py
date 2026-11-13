#!/usr/bin/env python3
# =============================================================================
# FRONT DOOR (Pi, port 7041) -- Rig 2.0: phones, Jarvis and the health page talk to the PI (Nov 12).
#   Mac awake  -> every request is passed straight through to the Mac's rig_control (port 7040), so everything
#                 works exactly as before.
#   Mac asleep -> the Pi answers the calm things itself with its own Hue key: colours, brightness, purple,
#                 rainbow (synced breathing), night lights, morning blue, lights off, status, health. Shows,
#                 movies and heads say "the Mac is asleep".
# Auth: the rig token in an X-Token header or the rig_key cookie -- never in a link. Phones log the health page
# in with a one-time code (POST /login with the header -> /go?c=CODE sets the cookie, code dies after 2 min).
# Token file on the Pi: ~/.ney_secrets/rig_token (600). Never printed.
# =============================================================================
import hmac, json, os, re, secrets, socket, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 7041
TOKEN_FILE = os.path.expanduser('~/.ney_secrets/rig_token')
HERE = os.path.dirname(os.path.abspath(__file__))
CODES = {}                                     # one-time login codes: code -> expiry
FD = {'gen': 0, 'look': None, 'since': None, 'mode': 'starting'}
B = {}                                         # filled by start(): lamps, hue, mac_urls, log

PURPLE, RED, SKY = (0.27, 0.12), (0.69, 0.30), (0.22, 0.27)
RAINBOW = [(0.69, 0.30), (0.60, 0.38), (0.48, 0.47), (0.17, 0.70), (0.17, 0.36), (0.15, 0.06), (0.27, 0.12), (0.45, 0.23)]


def token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def _body(bri, xy=None, mirek=None, ms=800):
    b = {'on': {'on': True}, 'dimming': {'brightness': float(bri)}, 'dynamics': {'duration': ms}}
    if xy:
        b['color'] = {'xy': {'x': xy[0], 'y': xy[1]}}
    if mirek:
        b['color_temperature'] = {'mirek': mirek}
    return b


def _rainbow(gen):
    i = 0
    while FD['gen'] == gen:
        B['lamps'](_body(75, RAINBOW[i % len(RAINBOW)], ms=9000))      # every lamp the SAME colour, breathing on
        i += 1
        for _ in range(100):
            if FD['gen'] != gen:
                return
            time.sleep(0.1)


# calm looks the Pi can do alone: name -> (reply, action)
def pi_looks():
    return {
        'purple': ('Purple, full brightness.', lambda: B['lamps'](_body(100, PURPLE))),
        'purplenight': ('Purple night light. Sleep well.', lambda: B['lamps'](_body(15, PURPLE, ms=3000))),
        'nightlight': ('Red night light.', lambda: B['lamps'](_body(12, RED, ms=3000))),
        'night': ('Night mode: red night light. The Mac is asleep, so the heads are left as they are.',
                  lambda: B['lamps'](_body(12, RED, ms=3000))),
        'morning': ('Morning blue.', lambda: B['lamps'](_body(60, SKY, ms=3000))),
        'cozy': ('Cozy.', lambda: B['lamps'](_body(60, mirek=370, ms=1500))),
        'bright': ('Bright white.', lambda: B['lamps'](_body(100, mirek=200))),
        'off': ('Lights off.', lambda: B['lamps']({'on': {'on': False}, 'dynamics': {'duration': 1500}})),
        'rainbow': ('Rainbow breathing, every lamp in sync.', None),       # special: background loop
    }


def run_look(name):
    looks = pi_looks()
    if name not in looks:
        return None
    FD['gen'] += 1
    gen = FD['gen']
    reply, fn = looks[name]
    if name == 'rainbow':
        threading.Thread(target=_rainbow, args=(gen,), daemon=True).start()
    else:
        fn()
    FD.update(look=name, since=time.strftime('%H:%M'))
    return reply


def pi_ask(text):
    """Jarvis on the Pi: the same word rules, Pi looks only. (No local model on the Pi.)"""
    import jarvis

    def rig(p):
        if p == 'status':
            return json.dumps({'look': FD.get('look')})
        if p.startswith('set:'):
            FD['gen'] += 1
            B['lamps'](json.loads(p[4:]))
            FD.update(look='custom', since=time.strftime('%H:%M'))
            return ''
        if run_look(p) is None:
            raise LookupError(p)
        return ''
    s = jarvis.settings()
    s['ollama'] = 'http://127.0.0.1:9'          # no model on the Pi: fail fast, rules only
    out = jarvis.handle(text or '', s, rig=rig, confirm=False, voice_yes=False, guest=True)
    out = out.replace("I couldn't reach the rig (LookupError).", "That one needs the Mac, and it's asleep.")
    return "The Mac's asleep, so I'm running from the Pi. " + out


def health_json():
    checks = [{'name': 'Mac (rig control)', 'level': 'down', 'detail': 'not answering -- asleep or off. The Pi is covering calm looks.'}]
    try:
        n = len(B['hue']('GET', 'light').get('data', []))
        checks.append({'name': 'Hue lamps (Pi key)', 'level': 'ok', 'detail': 'connected (%d devices)' % n})
    except Exception as e:
        checks.append({'name': 'Hue lamps (Pi key)', 'level': 'down', 'detail': 'not answering (%s)' % e.__class__.__name__})
    checks.append({'name': 'Pi brain', 'level': 'ok', 'detail': 'front door + schedule running'})
    checks.append({'name': 'Look', 'level': 'ok', 'detail': '%s%s' % (FD.get('look') or 'none', (' since ' + FD['since']) if FD.get('since') else '')})
    return {'at': time.strftime('%H:%M:%S'), 'checks': checks}


_MAC = {'base': None, 't': 0.0}


def mac_base(ttl=10.0):
    """The first Mac address that accepts a connection on 7040 within 0.8 s (cached 10 s). None = Mac asleep."""
    if time.time() - _MAC['t'] < ttl:
        return _MAC['base']
    found = None
    for base in B['mac_urls']():
        u = urllib.parse.urlparse(base)
        try:
            socket.create_connection((u.hostname, u.port or 80), timeout=0.8).close()
            found = base
            break
        except OSError:
            continue
    _MAC.update(base=found, t=time.time())
    return found


class Door(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='text/plain; charset=utf-8', headers=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _cookie(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'rig_key':
                return v
        return ''

    def _authed(self):
        try:
            t = token()
        except OSError:
            return False
        given = self.headers.get('X-Token') or self._cookie()
        return bool(given) and hmac.compare_digest(given, t)

    def _read(self):
        n = min(int(self.headers.get('Content-Length') or 0), 20000)
        return self.rfile.read(n) if n else b''

    def do_GET(self):
        self.handle_any()

    def do_POST(self):
        self.handle_any()

    def handle_any(self):
        u = urllib.parse.urlparse(self.path)
        path, q = u.path, urllib.parse.parse_qs(u.query)
        if path == '/go':                                    # one-time code -> cookie (no token in the link)
            c = (q.get('c') or [''])[0]
            exp = CODES.pop(c, 0)
            if not c or exp < time.time():
                return self._send(403, 'That login link expired. Run the Rig Health shortcut again.')
            to = (q.get('to') or ['/health'])[0]
            to = to if re.fullmatch(r'/[a-z0-9_/.\-]*', to or '') else '/health'
            return self._send(302, '', headers=(('Location', to),
                              ('Set-Cookie', 'rig_key=%s; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly' % token())))
        if not self._authed():
            return self._send(403, 'Not allowed.')
        body = self._read()
        if path == '/login':
            code = secrets.token_urlsafe(12)
            for k in [k for k, v in CODES.items() if v < time.time()]:
                CODES.pop(k, None)
            CODES[code] = time.time() + 120
            return self._send(200, code)
        if path == '/door':                                  # front door status (never proxied)
            return self._send(200, json.dumps(dict(FD, mac_urls=B['mac_urls']())), 'application/json')
        # 1) Mac awake: pass straight through
        r = self._proxy(path, u.query, body)
        if r is not None:
            FD['mode'] = 'passing to the Mac'
            return self._send(*r)
        # 2) Mac asleep: the Pi answers what it can
        FD['mode'] = 'Mac asleep -- Pi answering'
        name = path.strip('/').lower()
        if name == 'ask':
            text = (q.get('text') or [''])[0]
            if not text and body:
                try:
                    text = str(json.loads(body).get('text', ''))
                except (ValueError, AttributeError):
                    text = (urllib.parse.parse_qs(body.decode('utf-8', 'replace')).get('text') or [''])[0]
            try:
                return self._send(200, pi_ask(text.strip()))
            except Exception as e:
                return self._send(200, "The Mac's asleep and the Pi hit a snag (%s)." % e.__class__.__name__)
        if name == 'status':
            return self._send(200, json.dumps(dict(mac='asleep', look=FD.get('look'), since=FD.get('since'))), 'application/json')
        if name == 'health':
            try:
                with open(os.path.join(HERE, 'health.html'), 'rb') as f:
                    return self._send(200, f.read(), 'text/html; charset=utf-8')
            except OSError:
                return self._send(200, 'The Mac is asleep. The Pi is covering calm looks.')
        if name == 'health.json':
            return self._send(200, json.dumps(health_json()), 'application/json')
        reply = run_look(name)
        if reply:
            return self._send(200, "Mac's asleep, Pi here. " + reply)
        return self._send(503, "The Mac is asleep, so that one isn't available. I can do: colours, purple, rainbow, "
                               "night light, morning blue, cozy, lights off.")

    def _proxy(self, path, query, body):
        """Forward to the Mac. Returns (code, body, ctype, headers) or None if the Mac doesn't answer."""
        timeout = 40 if path == '/ask' else 8
        base = mac_base()
        for base in ([base] if base else []):
            url = base.rstrip('/') + path + (('?' + query) if query else '')
            req = urllib.request.Request(url, body if (body or self.command == 'POST') else None, method=self.command)
            req.add_header('X-Token', token())
            if self.headers.get('Content-Type'):
                req.add_header('Content-Type', self.headers['Content-Type'])
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return self._pack(r.status, r)
            except urllib.error.HTTPError as e:
                return self._pack(e.code, e)
            except Exception:
                continue
        return None

    @staticmethod
    def _pack(code, r):
        hdrs = tuple(('Set-Cookie', v) for v in (r.headers.get_all('Set-Cookie') or []))
        return code, r.read(), r.headers.get('Content-Type', 'text/plain; charset=utf-8'), hdrs


def start(lamps, hue, mac_urls, log):
    B.update(lamps=lamps, hue=hue, mac_urls=mac_urls, log=log)
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), Door)
    threading.Thread(target=srv.serve_forever, name='front-door', daemon=True).start()
    log('front door listening on %d' % PORT)
    return srv
