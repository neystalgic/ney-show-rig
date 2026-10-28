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
#   movienight   movie lights (hub Movie vibe), ready for a film
#   hub          the MOVIE HUB remote page (phone): services, play/pause, trackpad, typing,
#                volume, lights.  Its buttons call /m/... (open, key, type, mouse, click, scroll,
#                vol, lights, night, status) -- see movie_remote.py
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


def hub_vibe(name, energy=0.6):
    for _ in range(30):                             # the hub may restart once to switch light areas
        try:
            return hub_api({'op': 'vibe', 'name': name, 'energy': energy})
        except Exception:
            time.sleep(1)
    raise RuntimeError('the Hue Hub did not answer')


def hub_setting(key, value):
    for _ in range(20):
        try:
            return hub_api({'op': 'setting', 'key': key, 'value': value})
        except Exception:
            time.sleep(1)
    raise RuntimeError('the Hue Hub did not answer')


def movie_lights(what):
    """Movie Hub lights: movie / intermission / resume / up / picture_on / picture_off."""
    if what in ('movie', 'resume', 'intermission', 'picture_on', 'picture_off'):
        stop_ambient()
        if not hub_up():
            start_hub('sync')
        if what == 'movie':
            hub_vibe('movie')
            hub_setting('intermission', False)
        elif what == 'resume':
            hub_setting('intermission', False)
        elif what == 'intermission':
            hub_setting('intermission', True)
        elif what == 'picture_on':
            hub_setting('movie_src', 'camera')
            hub_setting('movie', True)
        elif what == 'picture_off':
            hub_setting('movie', False)
    elif what == 'up':
        LOOKS['cozy'][1]()
    else:
        raise ValueError('unknown lights: %s' % what)


LOOKS = {
    'movie': ('Movie mode', lambda: (stop_ambient(), start_hub('sync'))),
    'show': ('The light show', lambda: (stop_ambient(), start_hub('lava'))),
    'music': ('Music mode', lambda: (stop_ambient(), start_hub('music'))),
    'rainbow': ('Rainbow fade, every lamp together', lambda: (stop_all(), start_ambient(70, 90, 0))),
    'rainbowroom': ('Rainbow across the room', lambda: (stop_all(), start_ambient(70, 120, 240))),
    'bright': ('Bright white', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 100.0},
                                                                'color_temperature': {'mirek': 200},
                                                                'dynamics': {'duration': 600}}))),
    'cozy': ('Cozy warm white', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 60.0},
                                                                 'color_temperature': {'mirek': 370},
                                                                 'dynamics': {'duration': 1500}}))),
    'movienight': ('Movie night', lambda: movie_lights('movie')),
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

    def reply_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def cookie_key(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'rig_key':
                return v
        return ''

    def handle_any(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        tok = (q.get('token') or [self.headers.get('X-Token', '')])[0] or self.cookie_key()
        if not hmac.compare_digest(tok, TOKEN):
            return self.reply(403, 'Not allowed.')
        path = u.path.strip('/')
        if path == 'hub':                               # the Movie Hub remote (remembers the key in a cookie)
            with open(os.path.join(HERE, 'movie_hub.html'), 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Set-Cookie', 'rig_key=%s; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly' % TOKEN)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path.startswith('m/'):
            return self.movie(path[2:], q)
        look = path.lower()
        if look == 'status':
            s = dict(STATE, hub=running('hue_hub.py'), rainbow_fade=running('ambient_fade.py'))
            return self.reply(200, json.dumps(s))
        if look not in LOOKS:
            return self.reply(404, 'Unknown look. Try: ' + ', '.join(sorted(LOOKS)))
        threading.Thread(target=apply, args=(look,), daemon=True).start()
        return self.reply(200, LOOKS[look][0] + ', coming up.')

    def movie(self, what, q):
        import movie_remote as mr
        g = lambda k, d=None: (q.get(k) or [d])[0]
        try:
            if what == 'status':
                return self.reply_json(200, dict(access=mr.trusted(), services={k: v[0] for k, v in mr.SERVICES.items()},
                                                 screens=len(mr.displays()), sound=mr.volume(), look=STATE.get('look'),
                                                 busy=STATE.get('busy'), error=STATE.get('last_error')))
            if what == 'access':
                return self.reply_json(200, dict(access=mr.ask_access()))
            if what == 'vol':
                if g('mute') is not None:
                    return self.reply_json(200, mr.volume(mute=g('mute') == '1'))
                return self.reply_json(200, mr.volume(delta=int(float(g('d', '0')))))
            if what in ('lights', 'night'):
                l = g('l', 'movie') if what == 'lights' else 'movie'
                def work():
                    with LOCK:
                        STATE.update(busy=True, last_error=None)
                        try:
                            movie_lights(l)
                            STATE.update(look='movie' if l != 'up' else 'cozy', since=time.strftime('%H:%M'))
                            if what == 'night' and g('s') in mr.SERVICES:
                                mr.open_service(g('s'))
                        except Exception as e:
                            STATE['last_error'] = 'lights %s: %s' % (l, e)
                        finally:
                            STATE['busy'] = False
                threading.Thread(target=work, daemon=True).start()
                return self.reply_json(200, dict(ok=True, lights=l))
            if what == 'open':
                sid = g('s', '')
                if sid not in mr.SERVICES:
                    return self.reply_json(404, dict(error='unknown service'))
                threading.Thread(target=mr.open_service, args=(sid,), daemon=True).start()
                return self.reply_json(200, dict(ok=True, opening=mr.SERVICES[sid][0], fullscreen=mr.trusted()))
            if not mr.trusted():
                return self.reply_json(200, dict(ok=False, need_access=True))
            if what == 'key':
                k = g('k', '')
                if k not in mr.KEYS:
                    return self.reply_json(404, dict(error='unknown key'))
                flags = (mr.CMD if g('cmd') == '1' else 0) | (mr.SHIFT if g('shift') == '1' else 0)
                mr.key(k, flags)
            elif what == 'type':
                n = min(int(self.headers.get('Content-Length', 0) or 0), 2000)
                text = self.rfile.read(n).decode('utf-8', 'ignore') if n else g('t', '')
                mr.type_text(text)
            elif what == 'mouse':
                mr.mouse_move(max(-400, min(400, float(g('dx', 0)))), max(-400, min(400, float(g('dy', 0)))))
            elif what == 'click':
                mr.click('right' if g('b') == 'right' else 'left')
            elif what == 'scroll':
                mr.scroll(max(-600, min(600, int(float(g('dy', 0))))))
            else:
                return self.reply_json(404, dict(error='unknown'))
            return self.reply_json(200, dict(ok=True))
        except Exception as e:
            return self.reply_json(500, dict(error='%s: %s' % (type(e).__name__, e)))

    do_GET = do_POST = handle_any


if __name__ == '__main__':
    print('Rig control on port %d' % PORT, flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
