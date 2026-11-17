# console_route.py -- the RIG CONSOLE page (/console) and its live data (/console.json).  Nov 17 (away loop, W2).
#
# Michael: "voice is cool but sometimes I want to do things manually."  This is the manual side: one phone page that
# shows what the show director is doing right now and has console-style buttons for it.
#
# rig_control.py hands these two paths here AFTER its usual token check, so the login is the same as /health:
#   http://<this Mac>:7040/console?token=<token>   once -> the page remembers the key in a cookie (like /health, /hub)
#   /console.json                                  the page polls this every second (read-only)
#
# Nothing in this file changes the room.  The page's buttons use routes that already exist:
#   POST /show/set  (allowlisted show keys only: show_lock, show_wave, show_loop_dir, show_audio, show_speed,
#                    show_acts, dmx_pattern)   and   /<look>  (purple, cozy, moviechill, night, heads_on/off, guest_on/off)
import json, os, time, urllib.request

LIVE_URL = 'http://127.0.0.1:7020/api/live'        # the hub's own live snapshot (same one /health reads)
SAVED_KEYS = ('dmx_pattern', 'show_lock', 'show_wave', 'show_loop_dir', 'show_audio', 'show_speed', 'show_acts')
PAGE = 'console.html'


def fetch_live(timeout=1.5):
    """The hub's live snapshot as a dict, or None when the hub is off or not answering (short timeout, never hangs)."""
    try:
        d = json.loads(urllib.request.urlopen(LIVE_URL, timeout=timeout).read())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def saved_settings(here):
    """The show settings as saved in hub_state.json.  Wave + loop direction aren't in the live status, and when the
    hub is off this is what the next show will start with (rig_control's /show/set saves there)."""
    try:
        with open(os.path.join(here, 'hub_state.json')) as f:
            s = json.load(f).get('settings') or {}
    except (OSError, ValueError, AttributeError):
        s = {}
    out = {k: s.get(k) for k in SAVED_KEYS if k in s}
    z = s.get('show_zones')
    out['zone_order'] = [str(x) for x in (z.get('order') or [])] if isinstance(z, dict) else []
    return out


def _num(x):
    try:
        return round(float(x), 3)
    except (TypeError, ValueError):
        return None


def snapshot(state, here, live_fn=fetch_live):
    """One small picture for the page.  Only named fields go out -- never the whole STATE, never the token."""
    live = live_fn()
    live = live if isinstance(live, dict) else None
    show = (live or {}).get('show')
    show = show if isinstance(show, dict) else None
    audio = (live or {}).get('audio')
    audio = audio if isinstance(audio, dict) else {}
    clock = (live or {}).get('clock')
    clock = clock if isinstance(clock, dict) else {}
    return dict(ok=True, time=time.strftime('%H:%M:%S'),
                look=state.get('look'), since=state.get('since'), busy=bool(state.get('busy')),
                guest=bool(state.get('guest')), last_error=state.get('last_error'),
                hub=live is not None, show=show,
                level=_num(live.get('level')) if live else None,          # the music's level, 0-1
                section=(show or {}).get('section') or audio.get('section'),
                audio=audio.get('status'), tempo=_num(clock.get('tempo')),
                saved=saved_settings(here))


def handle(handler, path, here, token, state, live_fn=fetch_live):
    """Called by rig_control's Handler once the token is checked.  path is 'console' or 'console.json'."""
    if path == 'console.json':
        return handler.reply_json(200, snapshot(state, here, live_fn))
    try:
        with open(os.path.join(here, PAGE), 'rb') as f:
            body = f.read()
    except OSError:
        return handler.reply(404, 'console.html is missing -- see away/console/DEPLOY.txt')
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Set-Cookie', 'rig_key=%s; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly' % token)
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    return handler.wfile.write(body)
