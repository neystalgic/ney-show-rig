#!/usr/bin/env python3
# =============================================================================
# RIG CONTROL -- a tiny always-on switchboard for Siri Shortcuts and your phone.
#
#   http://<this Mac>:7040/<look>?token=<token>        (GET or POST)
#
#   movie        movie mode: the hub, every lamp in sync, brightness from Scarlett input 2
#   show         the light show (lava palette)
#   rainbow      every lamp the SAME colour, fading round the rainbow together (no hub)
#   rainbowroom  a rainbow gradient across the room, drifting (no hub)
#   bright       plain bright daylight white, 100%
#   cozy         warm white, 60%
#   off / rest   lights off, hub and fades stopped
#   status       what's running right now
#
# It answers straight away ("Switching to movie...") and does the work in the
# background. Only one look at a time; a new one replaces the old.
# The token (rig_control.token, never committed) keeps anyone else on the network out.
# Runs at login via ~/Library/LaunchAgents/com.ney.rigcontrol.plist.
# The Mac, Scarlett and projector are never switched off by this.
# =============================================================================
import hmac, json, os, secrets, subprocess, sys, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 7040
PY = sys.executable
TOKEN_FILE = os.path.join(HERE, 'rig_control.token')
if not os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, 'w') as f:
        f.write(secrets.token_urlsafe(18))
    os.chmod(TOKEN_FILE, 0o600)
TOKEN = open(TOKEN_FILE).read().strip()
LOCK = threading.Lock()
STATE = {'look': None, 'since': None, 'busy': False, 'last_error': None}


def sh(cmd, timeout=15):
    return subprocess.run(['/bin/zsh', '-lc', cmd], capture_output=True, text=True, timeout=timeout).stdout


def running(name):
    return bool(sh('pgrep -f %s || true' % name).strip())


def stop_ambient():
    if not running('ambient_fade.py'):
        return
    open(os.path.join(HERE, 'ambient.stop'), 'w').close()
    for _ in range(30):
        if not running('ambient_fade.py'):
            break
        time.sleep(0.25)
    sh('pkill -f ambient_fade.py || true')
    try:
        os.remove(os.path.join(HERE, 'ambient.stop'))
    except OSError:
        pass


def stop_hub():
    if not running('hue_hub.py'):
        return
    sh('pkill -INT -f hue_hub.py || true')
    for _ in range(40):
        if not running('hue_hub.py'):
            break
        time.sleep(0.25)
    sh('pkill -f hue_hub.py || true')
    time.sleep(3)                                   # let the bridge release the stream


def hub_api(cmd, timeout=3):
    rq = urllib.request.Request('http://127.0.0.1:7020/api', data=json.dumps(cmd).encode(),
                                headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(rq, timeout=timeout).read())


def hub_up():
    try:
        urllib.request.urlopen('http://127.0.0.1:7020/api/live', timeout=2).read()
        return True
    except Exception:
        return False


def start_hub(palette):
    if not hub_up():
        subprocess.Popen(['open', os.path.join(HERE, 'Start Hue Hub.command')])
        for _ in range(60):
            time.sleep(1)
            if hub_up():
                break
    for _ in range(30):                             # the hub may restart once to switch areas
        try:
            hub_api({'op': 'setting', 'key': 'palette', 'value': palette})
            hub_api({'op': 'blackout', 'on': False})
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError('the Hue Hub did not answer')


def hue_lights(body):
    sys.path.insert(0, HERE)
    import hue_stream as hs
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        cfg = hs.load_config()
        for l in hs.v2(cfg, 'light').get('data', []):
            hs.v2(cfg, 'light/%s' % l['id'], 'PUT', body)
    finally:
        os.chdir(cwd)


def start_ambient(bri, turn, spread):
    try:
        os.remove(os.path.join(HERE, 'ambient.stop'))
    except OSError:
        pass
    log = open('/tmp/ambient_fade.log', 'w')
    subprocess.Popen([PY, os.path.join(HERE, 'ambient_fade.py'), str(bri), str(turn), str(spread)],
                     cwd=HERE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def stop_all():
    stop_ambient()
    stop_hub()


LOOKS = {
    'movie': ('Movie mode', lambda: (stop_ambient(), start_hub('sync'))),
    'show': ('The light show', lambda: (stop_ambient(), start_hub('lava'))),
    'rainbow': ('Rainbow fade, every lamp together', lambda: (stop_all(), start_ambient(70, 90, 0))),
    'rainbowroom': ('Rainbow across the room', lambda: (stop_all(), start_ambient(70, 120, 240))),
    'bright': ('Bright white', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 100.0},
                                                                'color_temperature': {'mirek': 200},
                                                                'dynamics': {'duration': 600}}))),
    'cozy': ('Cozy warm white', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 60.0},
                                                                 'color_temperature': {'mirek': 370},
                                                                 'dynamics': {'duration': 1500}}))),
    'off': ('Lights off', lambda: (stop_all(), hue_lights({'on': {'on': False}, 'dynamics': {'duration': 1500}}))),
}
LOOKS['rest'] = ('Rest mode', LOOKS['off'][1])


def apply(look):
    with LOCK:
        STATE.update(busy=True, last_error=None)
        try:
            LOOKS[look][1]()
            STATE.update(look=look, since=time.strftime('%H:%M'))
        except Exception as e:
            STATE['last_error'] = '%s: %s' % (look, e)
        finally:
            STATE['busy'] = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        tok = (q.get('token') or [self.headers.get('X-Token', '')])[0]
        if not hmac.compare_digest(tok, TOKEN):
            return self.reply(403, 'Not allowed.')
        look = u.path.strip('/').lower()
        if look == 'status':
            s = dict(STATE, hub=running('hue_hub.py'), rainbow_fade=running('ambient_fade.py'))
            return self.reply(200, json.dumps(s))
        if look not in LOOKS:
            return self.reply(404, 'Unknown look. Try: ' + ', '.join(sorted(LOOKS)))
        threading.Thread(target=apply, args=(look,), daemon=True).start()
        return self.reply(200, LOOKS[look][0] + ', coming up.')

    do_GET = do_POST = handle_any


if __name__ == '__main__':
    print('Rig control on port %d' % PORT, flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
