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
#   off / rest   lights off, hub and fades stopped; moving heads park, then their plugs go off
#   strobe       the light show, strobe version: heads flash on every beat (max 3 a second, ceiling only)
#   nostrobe     the light show, non strobe version: same show, no flashes
#   movieglow    dim movie glow: every lamp + the moving heads the same colour, drifting through purples,
#                blues and pinks (heads: soft ceiling washes, slow drift)
#   wake         wake the Zephyrus (Wake-on-LAN over the cable); show / music / strobe looks do it too
#   heads_on     moving heads' smart plugs on (only if the DMX node answers) -- show/music do this too
#   heads_off    moving heads park, then their plugs go off (fans stop)
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
import hmac, json, os, re, secrets, subprocess, sys, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import head_power                                  # Hue Smart Plugs on the moving heads (dormant until they exist)
import hub_watchdog                                # restarts a frozen hub on its own (Nov 9)
import light_schedule                              # wind-down 21:30, night light 23:00, morning 8:40-9:00
import tap_switch                                  # Hue Tap Switch Mini: 1 show, 2 movie, 3 cycle, 4 night (Nov 11)
import claude_bridge                               # Claude runs the rig through bridge/inbox, no TouchDesigner (Nov 12)
import rig_health                                  # /health: green/red per part of the rig, for the phone (Nov 12)

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


def launch_hub():
    """Start the hub in the background (no Terminal window), the same way TouchDesigner does."""
    import shlex
    with open(os.path.join(HERE, 'hub_log.txt'), 'a') as f:
        f.write('\nStarting the Hue Hub at %s (rig_control)\n' % time.ctime())
    app = os.path.join(HERE, 'Ney Hub.app')         # the launcher app holds the microphone permission (Nov 9)
    if os.path.isdir(app):
        subprocess.Popen(['/usr/bin/open', '-n', '-g', '-a', app], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    subprocess.Popen(['/usr/bin/env', '-i', 'HOME=' + os.path.expanduser('~'), '/usr/bin/arch', '-arm64', '/bin/zsh', '-lc',
                      'cd %s && exec python3 -u hue_hub.py >> hub_log.txt 2>&1' % shlex.quote(HERE)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def start_hub(palette):
    if not hub_up():
        launch_hub()
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
            if 'dimming' not in l or head_power.is_plug(l):   # smart plugs are never switched like lamps
                continue
            hs.v2(cfg, 'light/%s' % l['id'], 'PUT', body)
    finally:
        os.chdir(cwd)


def start_ambient(bri, turn, spread, *extra):
    try:
        os.remove(os.path.join(HERE, 'ambient.stop'))
    except OSError:
        pass
    log = open('/tmp/ambient_fade.log', 'w')
    subprocess.Popen([PY, os.path.join(HERE, 'ambient_fade.py'), str(bri), str(turn), str(spread)] + [str(e) for e in extra],
                     cwd=HERE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


ZEPHYRUS_MAC = '00:e0:4c:68:10:5b'                 # its wired (USB-C) adapter -- Wake-on-LAN


def wake_zephyrus():
    """Wake-on-LAN magic packet to the Zephyrus (harmless if it's already awake)."""
    import socket
    mac = bytes.fromhex(ZEPHYRUS_MAC.replace(':', ''))
    pkt = b'\xff' * 6 + mac * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for addr in ('255.255.255.255', '192.168.1.255'):
        for port in (9, 7):
            try:
                s.sendto(pkt, (addr, port))
            except OSError:
                pass
    s.close()


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


def movie_reactive():
    """Movie lights that follow the Scarlett's OUTPUT (loopback 5+6 = whatever the Mac plays):
    blue -> violet -> pink, louder = brighter, a soft glow in quiet scenes (Nov 2: input 2 alone
    heard nothing from Safari, so the lamps sat on the warm idle glow)."""
    hub_vibe('dreamy', 0.6)
    hub_setting('music_ch', '5,6')


def movie_lights(what):
    """Movie Hub lights: movie / intermission / resume / up / picture_on / picture_off."""
    if what in ('movie', 'resume', 'intermission', 'picture_on', 'picture_off'):
        stop_ambient()
        if not hub_up():
            start_hub('sync')
        if what == 'movie':
            movie_reactive()
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


# Spot looks for movie nights (hub setting spot_fx). FLAG = the Happiness Project flag + couch looks (Nov 4-7);
# UV_SKY = both spots UV-only on the galaxy tapestry (the night-sky aims, Nov 8).
SPOT_FX_FLAG = {"hold": {"az": 136, "lean": 76, "drift": 0}, "hold_when": "movie", "hold_head": 4, "level": 1.0, "gobo": 45,
                "gobo_rot": 0, "focus": 135, "breathe": 110, "breathe_s": 8, "color": 186,
                "per_head": {"5": {"hold": {"az": 180, "lean": 65, "drift": 8, "drift_s": 40}, "hold_head": 5, "gobo": 180,
                                   "gobo_rot": 210, "focus": 160, "breathe": 80, "breathe_s": 10, "color": None}}}
SPOT_FX_UV_SKY = {"hold": {"az": 192, "lean": 46, "drift": 0}, "hold_when": "movie", "hold_head": 4, "level": 1.0,
                  "uv": 1.0, "uv_only": True, "gobo": 0, "focus": 128,
                  "per_head": {"5": {"hold": {"az": 180, "lean": 65, "drift": 0}, "hold_head": 5, "uv": 1.0, "uv_only": True}}}


def _cc(num, val, label):
    """One MIDI CC on channel 16 over the IAC bus to Ableton. Never raises; result in STATE['fill']."""
    try:
        import rtmidi
        mo = rtmidi.MidiOut()
        names = mo.get_ports()
        idx = next((i for i, n in enumerate(names) if 'IAC' in n), None)
        if idx is None:
            STATE['fill'] = 'no IAC port (ports: %s) -- enable IAC Driver in Audio MIDI Setup' % (names or 'none')
            return False
        mo.open_port(idx)
        mo.send_message([0xB0 | 15, num, val])
        mo.close_port()
        STATE['fill'] = '%s: CC%d=%d ch16 on %s at %s' % (label, num, val, names[idx], time.strftime('%H:%M:%S'))
        return True
    except Exception as e:
        STATE['fill'] = 'failed: %s: %s' % (e.__class__.__name__, e)
        return False


def fill_on(on):
    """Nov 12: fill speaker on/off -- CC 103 ch16 -> the fill track's Track Activator in Ableton (127 on, 0 off).
    Off while producing (the fill makes a weird stereo image); on for movies and shows."""
    _cc(103, 127 if on else 0, 'fill ON' if on else 'fill OFF (producing)')


def fill_boost(on):
    """Fill speaker +6 dB for movies: MIDI CC 102 (channel 16) on the IAC bus -> map it in Ableton to the fill
    track's Utility gain (CC 127 = +6 dB, 0 = 0 dB). Never raises; what happened goes in STATE['fill']."""
    try:
        import rtmidi
        mo = rtmidi.MidiOut()
        names = mo.get_ports()
        idx = next((i for i, n in enumerate(names) if 'IAC' in n), None)
        if idx is None:
            STATE['fill'] = 'no IAC port (ports: %s) -- enable IAC Driver in Audio MIDI Setup' % (names or 'none')
            return
        mo.open_port(idx)
        mo.send_message([0xB0 | 15, 102, 127 if on else 0])
        mo.close_port()
        STATE['fill'] = '%s: sent CC102=%d ch16 on %s at %s' % ('UP +6 dB' if on else 'normal', 127 if on else 0,
                                                             names[idx], time.strftime('%H:%M:%S'))
    except Exception as e:
        STATE['fill'] = 'failed: %s: %s' % (e.__class__.__name__, e)


def movie_uv():
    movie_lights('movie')
    hub_setting('spot_fx', SPOT_FX_UV_SKY)
    fill_on(True)
    fill_boost(True)


def movie_flag():
    movie_lights('movie')
    hub_setting('spot_fx', SPOT_FX_FLAG)


def show_full():
    """Button 1: everything moving together to the music, one colour stepping on the beat, strobe only in drops."""
    wake_zephyrus(); stop_ambient(); fill_on(True); fill_boost(False)
    head_power.request_on(quiet=True)
    start_hub('music')
    hub_vibe('rainbow', 0.8)
    hub_setting('dmx_strobe', 'flash')
    hub_setting('flash_beats', 8)                   # Nov 11: one colour every 2 bars, not every beat
    hub_setting('dmx_on', True)


def show_uv():
    """Nov 11: the light show on the heads + both spots holding the UV stars, glowing with the music."""
    show_full()
    hub_setting('spot_fx', dict(SPOT_FX_UV_SKY, hold_when='always'))


PI_NODE = ('http://192.168.1.80:7060', 'http://100.127.200.67:7060')
GUEST_FILE = os.path.join(HERE, 'guest_mode.json')
STROBE_LOOKS = {'show', 'showuv', 'flash', 'strobe', 'hype'}


def node_post(path, body):
    last = None
    for base in PI_NODE:
        try:
            req = urllib.request.Request(base + path, json.dumps(body).encode(), {'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=4) as r:
                return json.loads(r.read() or b'{}')
        except Exception as e:
            last = e
    raise RuntimeError('Pi node not answering (%s)' % last.__class__.__name__)


def guest_mode(on):
    """Nov 12: GUEST MODE -- strobes blocked AT THE PI NODE (not just by look choice). On: the node's strobe unlock is
    switched off and its flash limit drops to 2 a second; any strobe look becomes the safe show. Off: back to
    Michael's settings (strobe allowed, flash limit 20)."""
    res = node_post('/unlock', {'strobe': False, 'flash_hz': 2} if on else {'strobe': True, 'flash_hz': 20})
    if on and hub_up():
        try:
            hub_setting('dmx_strobe', 'off')
        except Exception:
            pass
    STATE['guest'] = bool(on)
    with open(GUEST_FILE, 'w') as f:
        json.dump({'guest': bool(on), 'since': time.strftime('%Y-%m-%d %H:%M'), 'node': res}, f)


COUCH_HOLD = os.path.join(HERE, 'light_schedule.json')


def scarlett_present():
    """Is the MacBook docked? (the Scarlett is on the desk's USB)"""
    out = subprocess.run(['/usr/sbin/ioreg', '-p', 'IOUSB', '-w0'], capture_output=True, text=True).stdout
    return 'scarlett' in out.lower()


def couch_mode():
    """Nov 13: producing on the couch (MacBook unplugged, headphones / laptop speakers). The hub stops cleanly so the
    watchdog never 'restarts a frozen hub', heads power off, lamps go to a dim purple working light, and tonight's
    wind-down / night light are held until Michael says goodnight (or docks again). Morning blue still runs."""
    head_power.request_off(why='couch mode')
    stop_all()
    hue_lights({'on': {'on': True}, 'dimming': {'brightness': 35.0}, 'color': {'xy': {'x': 0.27, 'y': 0.12}},
                'dynamics': {'duration': 2000}})
    tomorrow = time.strftime('%Y-%m-%d', time.localtime(time.time() + 86400))
    with open(COUCH_HOLD, 'w') as f:
        json.dump({'enabled': False, '_expires': tomorrow + ' 08:00', '_note': 'couch mode hold (Nov 13 feature)'}, f)
    STATE['couch'] = True


def desk_mode():
    """Back at the desk: the normal schedule resumes. Lights are left as they are."""
    try:
        with open(COUCH_HOLD) as f:
            if 'couch mode hold' in json.load(f).get('_note', ''):
                with open(COUCH_HOLD, 'w') as g:
                    g.write('{}\n')
    except (OSError, ValueError):
        pass
    STATE['couch'] = False


def show_safe():
    """Nov 12: a light show for guests who may be photosensitive. No strobe of any kind (heads, spots, flash mode),
    no UV hold, calmer music reaction; heads still move with the music."""
    wake_zephyrus(); stop_ambient(); fill_on(True); fill_boost(False)
    head_power.request_on(quiet=True)
    start_hub('music')
    hub_setting('dmx_strobe', 'off')
    hub_setting('spot_fx', {})
    hub_vibe('rainbow', 0.5)
    hub_setting('dmx_on', True)


def night_mode():
    """Button 4: heads park and power off, lamps to the red night light."""
    fill_boost(False)
    stop_all()
    hue_lights({'on': {'on': True}, 'dimming': {'brightness': 12.0}, 'color': {'xy': {'x': 0.69, 'y': 0.30}},
                'dynamics': {'duration': 2500}})
    head_power.request_off(why='night mode')


LOOKS = {
    'movie': ('Movie mode', lambda: (stop_ambient(), start_hub('music'), movie_reactive())),
    'lava': ('Lava lamp show', lambda: (wake_zephyrus(), stop_ambient(), head_power.request_on(quiet=True), start_hub('lava'))),
    'music': ('Music mode', lambda: (wake_zephyrus(), stop_ambient(), head_power.request_on(quiet=True), start_hub('music'),
                                     hub_setting('dmx_strobe', 'off'))),
    'flash': ('Multicolour flash: heads + spots strobing, all one colour stepping round the rainbow on the beat',
              lambda: (wake_zephyrus(), stop_ambient(), head_power.request_on(quiet=True), start_hub('music'),
                       hub_vibe('rainbow', 0.8), hub_setting('dmx_strobe', 'flash'), hub_setting('dmx_on', True))),
    'wake': ('Waking the Zephyrus', lambda: wake_zephyrus()),
    'strobe': ('Light show -- strobe version', lambda: (wake_zephyrus(), stop_ambient(), head_power.request_on(quiet=True), start_hub('music'),
                                                        hub_setting('dmx_strobe', 'always'), hub_setting('dmx_on', True))),
    'showsafe': ('Photosensitive-safe light show: no strobe, no flashes, gentle colour changes, heads still move',
                 lambda: show_safe()),
    'uvstars': ('UV on the stars: both spots hold the ceiling stars in UV, whatever else is running', lambda: hub_setting('spot_fx', dict(SPOT_FX_UV_SKY, hold_when='always'))),
    'uvoff': ('Spots back to the show (UV off the stars)', lambda: hub_setting('spot_fx', {})),
    'guest_on': ('Guest mode ON: strobes blocked at the Pi, any strobe look becomes the safe show', lambda: guest_mode(True)),
    'guest_off': ('Guest mode OFF: strobes allowed again (sparingly)', lambda: guest_mode(False)),
    'couch': ('Couch mode: hub off, heads off, dim purple, bedtime held until you say goodnight', lambda: couch_mode()),
    'desk': ('Back at the desk: normal schedule again', lambda: desk_mode()),
    'nostrobe': ('Light show -- non strobe', lambda: (wake_zephyrus(), stop_ambient(), head_power.request_on(quiet=True), start_hub('music'),
                                                      hub_setting('dmx_strobe', 'off'), hub_setting('dmx_on', True))),
    'heads_on': ('Moving heads powering up', lambda: head_power.request_on()),
    'heads_off': ('Moving heads parking, then power off', lambda: head_power.request_off(why='heads_off')),
    'rainbow': ('Rainbow breathing, every lamp in sync', lambda: (stop_all(), start_ambient(75, 90, 0, 10, 22))),   # Nov 10: all bulbs one colour, breathing
    'rainbowroom': ('Rainbow across the room', lambda: (stop_all(), start_ambient(70, 120, 240))),
    'bright': ('Bright white', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 100.0},
                                                                'color_temperature': {'mirek': 200},
                                                                'dynamics': {'duration': 600}}))),
    'purple': ('Purple, full brightness (Michael\'s favourite)', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 100.0},
                                                                 'color': {'xy': {'x': 0.27, 'y': 0.12}},
                                                                 'dynamics': {'duration': 800}}))),   # Nov 11: purple is the default 'lights on'
    'cozy': ('Cozy warm white', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 60.0},
                                                                 'color_temperature': {'mirek': 370},
                                                                 'dynamics': {'duration': 1500}}))),
    'movienight': ('Movie night', lambda: movie_flag()),
    'movieuv': ('Movie night: UV stars from both spots, fill speaker +6 dB', lambda: movie_uv()),
    'showuv': ('Light show with the UV stars: heads to the music, both spots holding UV on the stars', lambda: show_uv()),
    'purplenight': ('Purple night light: heads park and power off, lamps dim purple', lambda: (
        head_power.request_off(why='purplenight'), stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 15.0},
        'color': {'xy': {'x': 0.27, 'y': 0.12}}, 'dynamics': {'duration': 3000}}))),   # Nov 11: Michael asked for purple at bedtime
    'fillup': ('Fill speaker +6 dB (MIDI CC102 to Ableton)', lambda: fill_boost(True)),
    'filldown': ('Fill speaker back to normal', lambda: fill_boost(False)),
    'producing': ('Producing: fill speaker off (lights untouched)', lambda: (fill_boost(False), fill_on(False))),
    'fillon': ('Fill speaker back on', lambda: fill_on(True)),
    'show': ('Light show: everything together to the music, strobe only in drops', lambda: show_full()),
    'night': ('Night mode: heads off, red night light', lambda: night_mode()),
    'hype': ('Hype: every lamp + head one bright colour, fast moves', lambda: (wake_zephyrus(), stop_ambient(),
             head_power.request_on(quiet=True), start_hub('music'), hub_vibe('hype', 0.85), hub_setting('dmx_strobe', 'off'))),
    'breathe_slow': ('Slow breathing colours', lambda: (stop_all(), start_ambient(65, 420, 140, 16, 18))),
    'upbeat': ('Upbeat: bright rainbow drifting across the room', lambda: (stop_all(), start_ambient(90, 150, 240))),
    'movieglow': ('Movie glow: purples, blues + pinks, all lamps together, dim',
                  lambda: (stop_all(), start_ambient(30, 90, 0, 0, 0, 255, 350, 'heads'))),
    'redglow': ('Red glow: purples, pinks + reds drifting across the room, dim ambient',
                lambda: (stop_all(), start_ambient(40, 120, 50, 0, 0, 315, 365))),
    'breathe': ('Calm breathing colours', lambda: (stop_all(), start_ambient(70, 300, 140, 10, 22))),
    'morning': ('Morning light, soft blue', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 60.0},
                                                                 'color': {'xy': {'x': 0.22, 'y': 0.27}},
                                                                 'dynamics': {'duration': 8000}}))),
    'nightlight': ('Red night light', lambda: (stop_all(), hue_lights({'on': {'on': True}, 'dimming': {'brightness': 12.0},
                                                                         'color': {'xy': {'x': 0.69, 'y': 0.30}},
                                                                         'dynamics': {'duration': 2500}}))),
    'off': ('Lights off', lambda: (stop_all(), hue_lights({'on': {'on': False}, 'dynamics': {'duration': 1500}}),
                                   head_power.request_off(why='lights off'))),
}
LOOKS['rest'] = ('Rest mode', LOOKS['off'][1])


def apply(look):
    if STATE.get('guest') and look in STROBE_LOOKS:  # guest mode: never a strobe look
        look = 'showsafe'
    if look in ('night', 'purplenight', 'nightlight') and STATE.get('couch'):
        desk_mode()                                 # saying goodnight ends the couch hold
    with LOCK:
        STATE.update(busy=True, last_error=None)
        try:
            LOOKS[look][1]()
            STATE.update(look=look, since=time.strftime('%H:%M'))
            try:                                    # remembered across rig_control restarts (Nov 12)
                with open(os.path.join(HERE, 'rig_last_look.json'), 'w') as f:
                    json.dump({'look': look, 'since': STATE['since']}, f)
            except OSError:
                pass
        except Exception as e:
            STATE['last_error'] = '%s: %s' % (look, e)
        finally:
            STATE['busy'] = False


JOBS = __import__('queue').Queue()                  # Jarvis actions run in the order he said them (Nov 12 race fix)


def _job_worker():
    while True:
        fn = JOBS.get()
        try:
            fn()
        except Exception as e:
            STATE['last_error'] = 'jarvis job: %s' % e


def ask_jarvis(text):
    """'Hey Siri, Jarvis' -> /ask?text=... -> Jarvis picks allowlisted actions -> the reply Siri speaks."""
    jd = os.path.join(HERE, 'jarvis')
    if jd not in sys.path:
        sys.path.insert(0, jd)
    import jarvis
    if not getattr(ask_jarvis, 'worker', None):
        ask_jarvis.worker = threading.Thread(target=_job_worker, name='jarvis-jobs', daemon=True)
        ask_jarvis.worker.start()

    def rig(p):
        if p == 'status':
            return json.dumps({'look': STATE.get('look'), 'guest': STATE.get('guest', False)})
        if p.startswith('set:'):                    # a colour / brightness from Jarvis (validated there)
            body = json.loads(p[4:])

            def _set():
                with LOCK:
                    stop_all()
                    hue_lights(body)
                    STATE.update(look='custom', since=time.strftime('%H:%M'))
            JOBS.put(_set)
            return ''
        if p not in LOOKS:
            raise KeyError(p)
        JOBS.put(lambda: apply(p))
        return ''
    yes = bool(re.search(r'\b(confirm(ed)?|yes|seated)\b', (text or '').lower()))
    try:
        return jarvis.handle(text or '', jarvis.settings(), rig=rig, confirm=False, voice_yes=yes,
                             guest=bool(STATE.get('guest')))
    except Exception as e:
        return 'Jarvis hit a snag: %s.' % e.__class__.__name__


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
        if path == 'health':                            # the phone health page (remembers the key in a cookie)
            with open(os.path.join(HERE, 'health.html'), 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Set-Cookie', 'rig_key=%s; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly' % TOKEN)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == 'body':                              # Nov 13: the Body page (weight, food, activity)
            with open(os.path.join(HERE, 'body.html'), 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == 'body/activity':                     # Nov 13: the iPhone "Health Sync" shortcut posts the Watch's numbers
            import body_log, datetime as _dt
            n = min(int(self.headers.get('Content-Length') or 0), 5000)
            try:
                data = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self.reply(400, 'Send JSON.')
            day = str(data.get('day') or 'yesterday')
            if day in ('yesterday', 'today'):
                day = (_dt.date.today() - _dt.timedelta(days=1 if day == 'yesterday' else 0)).isoformat()
            row = body_log.add_activity(day, **{k: data.get(k) for k in body_log.FIELDS})
            got = ', '.join('%s %s' % (v, k) for k, v in row.items() if k != 'Date')
            return self.reply(200, 'Health synced for %s: %s.' % (day, got or 'no numbers yet'))
        if path == 'body.json':
            import body_log
            return self.reply_json(200, body_log.summary())
        if path == 'health.json':
            return self.reply_json(200, rig_health.snapshot())
        if path == 'ask':                               # Jarvis from Siri / Shortcuts / anywhere
            text = (q.get('text') or [''])[0]
            n = int(self.headers.get('Content-Length') or 0)
            if not text and n:
                raw = self.rfile.read(n).decode('utf-8', 'replace')
                try:
                    text = str(json.loads(raw).get('text', ''))
                except (ValueError, AttributeError):
                    text = (urllib.parse.parse_qs(raw).get('text') or [raw])[0]
            return self.reply(200, ask_jarvis(text.strip()))
        if path.startswith('m/'):
            return self.movie(path[2:], q)
        look = path.lower()
        if look == 'status':
            s = dict(STATE, hub=running('hue_hub.py'), rainbow_fade=running('ambient_fade.py'),
                     head_power=head_power.status(), watchdog=hub_watchdog.status(),
                     schedule=light_schedule.status(), tap_switch=tap_switch.status())
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
    try:
        with open(os.path.join(HERE, 'rig_last_look.json')) as f:
            STATE.update(json.load(f))
    except (OSError, ValueError):
        pass
    try:
        with open(GUEST_FILE) as f:
            STATE['guest'] = bool(json.load(f).get('guest'))
    except (OSError, ValueError):
        STATE['guest'] = False
    head_power.start()

    def _wd_stop():
        with LOCK:
            stop_hub()

    def _wd_start(palette):
        with LOCK:
            start_hub(palette)

    def _wd_restore(good):                          # put the vibe back the way it was
        if good.get('vibe'):
            try:
                hub_vibe(good['vibe'], float(good.get('energy') or 0.6))
            except Exception:
                pass
        if good.get('blackout'):
            try:
                hub_api({'op': 'blackout', 'on': True})
            except Exception:
                pass
    hub_watchdog.start(lambda: STATE['busy'], _wd_stop, _wd_start, _wd_restore)

    def _tap(look):                                 # a Tap Switch press = the same as asking for that look
        if look in LOOKS:
            threading.Thread(target=apply, args=(look,), daemon=True).start()
    tap_switch.start(_tap)

    def _sched_stop():
        with LOCK:
            stop_all()
        STATE.update(look='schedule', since=time.strftime('%H:%M'))

    def _hub_busy():                                # a show is on: running hub that hears sound
        return running('hue_hub.py') and not head_power.hub_quiet()
    light_schedule.start(hue_lights, _sched_stop, lambda: head_power.request_off(why='night light'), _hub_busy)
    def _hub_summary():
        try:
            d = json.loads(urllib.request.urlopen('http://127.0.0.1:7020/api/live', timeout=2).read())
            out = {k: d.get(k) for k in ('palette', 'vibe', 'bridge', 'blackout', 'heads', 'level')}
            out.update(audio=(d.get('audio') or {}).get('status'), section=(d.get('audio') or {}).get('section'))
            return out
        except Exception as e:
            return 'not answering (%s)' % e.__class__.__name__

    def _bridge_status():
        return dict(STATE, hub=running('hue_hub.py'), hub_live=_hub_summary(), beat_sender=running('beat_sender.py'),
                    head_power=head_power.status(), watchdog=hub_watchdog.status(), schedule=light_schedule.status(),
                    tap_switch=tap_switch.status(), bridge=claude_bridge.status(), time=time.strftime('%H:%M:%S'),
                    jarvis_log=sh('tail -12 /tmp/jarvis.log 2>/dev/null').splitlines(), health=rig_health.snapshot(), rotate=STATE.get('rotate'), dock=STATE.get('dock'), couch=STATE.get('couch'), py_env=STATE.get('py_env'), jarvis_app=STATE.get('jarvis_app'), voices=STATE.get('voices'), jarvis_ears=STATE.get('jarvis_ears'),
                    listen_log=sh('tail -6 /tmp/jarvis_listen.log /tmp/jarvis_listen.out 2>/dev/null').splitlines(),
                    pi_hue_key=__import__('pi_hue_key').STATUS.get('last'), pi_deploy=__import__('pi_deploy').STATUS)

    def _brain_poll():                              # the Pi brain's own status, once a minute over SSH
        import pi_deploy
        while True:
            pi_deploy.read_status()
            time.sleep(60)
    threading.Thread(target=_brain_poll, name='pi-brain-poll', daemon=True).start()
    rig_health.start(lambda: dict(state=dict(STATE), head_power=head_power.status(), watchdog=hub_watchdog.status(),
                                  schedule=light_schedule.status(), bridge=claude_bridge.status(),
                                  tap_switch=tap_switch.status(), pi_brain=__import__('pi_deploy').STATUS.get('brain')))

    def _factory():
        jd = os.path.join(HERE, 'jarvis')
        if jd not in sys.path:
            sys.path.insert(0, jd)
        import shortcut_factory
        return shortcut_factory

    def _shortcut_test():                           # build + sign every shortcut WITHOUT opening them (dry run)
        try:
            made, failed = _factory().build_all(open_them=False, only=['Purple', 'Rig Health'])
            STATE['rotate'] = 'dry run: signed %s%s' % (', '.join(made), ('; FAILED ' + '; '.join(failed)) if failed else '')
        except Exception as e:
            STATE['rotate'] = 'dry run failed: %s: %s' % (e.__class__.__name__, e)

    JARVIS_APP = os.path.join(HERE, 'Ney Jarvis.app')

    def _build_jarvis_app():                        # Nov 13: the app that holds the mic for "Hey Jarvis"
        pl = os.path.join(JARVIS_APP, 'Contents', 'Info.plist')
        steps = [['/usr/bin/osacompile', '-o', JARVIS_APP, os.path.join(HERE, 'tools', 'ney_jarvis_launcher.applescript')],
                 ['/usr/libexec/PlistBuddy', '-c', 'Add :NSMicrophoneUsageDescription string "Jarvis listens for Hey Jarvis on this Mac. Nothing leaves the Mac."', pl],
                 ['/usr/libexec/PlistBuddy', '-c', 'Add :LSUIElement bool true', pl],
                 ['/usr/bin/codesign', '--force', '--deep', '-s', '-', JARVIS_APP]]
        for c in steps:
            if c[0].endswith('PlistBuddy'):
                key = c[2].split()[1].lstrip(':')
                subprocess.run(['/usr/libexec/PlistBuddy', '-c', 'Delete :%s' % key, pl], capture_output=True)
            r = subprocess.run(c, capture_output=True, text=True)
            if r.returncode:
                STATE['jarvis_app'] = 'build failed at %s: %s' % (os.path.basename(c[0]), (r.stderr or r.stdout).strip()[:120])
                return
        STATE['jarvis_app'] = 'built %s' % time.strftime('%H:%M')

    def _jarvis_ears():                             # keep "Hey Jarvis" running (only once the app exists)
        time.sleep(40)
        while True:
            try:
                on = True
                try:
                    with open(os.path.join(HERE, 'jarvis', 'jarvis.json')) as f:
                        on = json.load(f).get('listen', True)
                except (OSError, ValueError):
                    pass
                if on and os.path.isdir(JARVIS_APP) and not running('jarvis/listen.py'):
                    subprocess.Popen(['/usr/bin/open', '-n', '-g', '-a', JARVIS_APP], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    STATE['jarvis_ears'] = 'started %s' % time.strftime('%H:%M')
                elif running('jarvis/listen.py'):
                    STATE['jarvis_ears'] = 'listening'
            except Exception as e:
                STATE['jarvis_ears'] = 'check failed: %s' % e.__class__.__name__
            time.sleep(60)
    threading.Thread(target=_jarvis_ears, name='jarvis-ears', daemon=True).start()

    def _voices():                                  # English voices on this Mac (Premium / Enhanced first)
        out = subprocess.run(['/usr/bin/say', '-v', '?'], capture_output=True, text=True).stdout.splitlines()
        en = [l.split('#')[0].strip() for l in out if ' en_' in l or ' en-' in l]
        STATE['voices'] = sorted(en, key=lambda l: (not ('Premium' in l or 'Enhanced' in l), l))[:40]

    def _chime_demo():                              # Michael asked to hear the chimes (sound only, no lights)
        for i, f in enumerate(('chime1_rise.wav', 'chime2_glass.wav', 'chime3_warm.wav'), 1):
            subprocess.run(['/usr/bin/say', '-v', 'Daniel', 'Chime %d.' % i])
            time.sleep(0.3)
            subprocess.run(['/usr/bin/afplay', os.path.join(HERE, 'jarvis', 'sounds', f)])
            time.sleep(1.0)

    def _py_env():                                  # read-only: which Python the hub/Jarvis use + what's installed
        cmd = ('which python3; python3 --version; python3 -c "import sys;print(sys.executable)"; '
               'for m in sounddevice numpy onnxruntime openwakeword faster_whisper; do '
               'python3 -c "import $m" 2>/dev/null && echo "$m: yes" || echo "$m: no"; done; '
               'system_profiler SPAudioDataType 2>/dev/null | grep -E "^        [A-Za-z].*:$" | head -12')
        STATE['py_env'] = subprocess.run(['/usr/bin/arch', '-arm64', '/bin/zsh', '-lc', cmd], capture_output=True,
                                         text=True, timeout=60).stdout.strip().splitlines()

    def _make_missing():                            # any shortcut whose signed file is older than the token (or missing)
        try:
            f = _factory()
            tok_t = os.path.getmtime(TOKEN_FILE)
            need = [n for n, k, p in f.SET
                    if not os.path.exists(os.path.join(f.OUT, '%s.shortcut' % n))
                    or os.path.getmtime(os.path.join(f.OUT, '%s.shortcut' % n)) < tok_t]
            made, failed = f.build_all(open_them=True, only=need) if need else ([], [])
            STATE['rotate'] = 'remade %s%s' % (', '.join(made) or 'nothing', ('; FAILED ' + '; '.join(failed)) if failed else '')
        except Exception as e:
            STATE['rotate'] = 'remake failed: %s: %s' % (e.__class__.__name__, e)

    def _rotate_token():
        """Nov 12 (Michael: 'Run it'): new rig token -> Mac + Pi, rebuild every shortcut (Pi front door, token in a
        header), open them for Add, then restart rig_control so the old token dies."""
        try:
            new = secrets.token_urlsafe(24)
            tmp = TOKEN_FILE + '.new'
            with open(tmp, 'w') as f:
                f.write(new)
            os.chmod(tmp, 0o600)
            os.replace(tmp, TOKEN_FILE)
            new = None
            import pi_deploy
            if not pi_deploy.sync_token():
                STATE['rotate'] = 'new token on the Mac, but the Pi copy FAILED -- run pi_deploy'
            made, failed = _factory().build_all(open_them=True)
            STATE['rotate'] = 'rotated %s; opened %d shortcuts%s' % (time.strftime('%H:%M'), len(made),
                                                                  ('; FAILED ' + '; '.join(failed)) if failed else '')
            with open(os.path.join(HERE, 'rig_last_look.json'), 'w') as f:
                json.dump({'look': STATE.get('look'), 'since': STATE.get('since'), 'rotate': STATE['rotate']}, f)
        except Exception as e:
            STATE['rotate'] = 'rotation failed: %s: %s' % (e.__class__.__name__, e)
            return
        time.sleep(3)
        os._exit(1)                                 # launchd restarts rig_control with the new token

    def _reload():
        time.sleep(1.0)
        os._exit(1)                                 # launchd (KeepAlive) starts rig_control again with the new code

    def _hub_restart():
        with LOCK:
            stop_hub()
            time.sleep(20)                          # never back-to-back
            launch_hub()

    def _beat_start():
        if not running('beat_sender.py'):
            subprocess.Popen(['/usr/bin/python3', '-u', os.path.join(HERE, 'beat_sender.py')], cwd=HERE,
                             stdout=open('/tmp/beat_sender.out', 'a'), stderr=subprocess.STDOUT, start_new_session=True)

    def _beat_keeper():                             # Nov 12: the beat sender starts with the rig and comes back if it dies
        time.sleep(20)
        while True:
            try:
                _beat_start()
            except Exception:
                pass
            time.sleep(60)
    threading.Thread(target=_beat_keeper, name='beat-keeper', daemon=True).start()

    def _dock_watch():                              # Nov 13: unplug the MacBook -> couch mode by itself
        last = None
        time.sleep(15)
        while True:
            try:
                now_docked = scarlett_present()
                if last is True and not now_docked:
                    STATE['dock'] = 'undocked %s -> couch mode' % time.strftime('%H:%M')
                    apply('couch')
                elif last is False and now_docked:
                    STATE['dock'] = 'docked %s -> normal schedule' % time.strftime('%H:%M')
                    desk_mode()
                elif last is None:
                    STATE['dock'] = 'docked' if now_docked else 'undocked'
                last = now_docked
            except Exception as e:
                STATE['dock'] = 'check failed: %s' % e.__class__.__name__
            time.sleep(30)
    threading.Thread(target=_dock_watch, name='dock-watch', daemon=True).start()

    def _idle_watch():                                    # Nov 13: away loop only runs when Michael is idle
        import re as _re
        out_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bridge', 'idle.json')
        while True:
            try:
                out = subprocess.run(['/usr/sbin/ioreg', '-c', 'IOHIDSystem', '-d', '4'], capture_output=True, text=True, timeout=10).stdout
                m = _re.search(r'"HIDIdleTime" = (\d+)', out)
                if m:
                    os.makedirs(os.path.dirname(out_p), exist_ok=True)
                    with open(out_p + '.tmp', 'w') as f:
                        json.dump({'hid_idle_s': int(m.group(1)) // 1000000000, 'at': time.time()}, f)
                    os.replace(out_p + '.tmp', out_p)
            except Exception:
                pass
            time.sleep(60)
    threading.Thread(target=_idle_watch, name='idle-watch', daemon=True).start()

    def _jarvis_warm():                             # Nov 12: keep Jarvis's local brain loaded (no slow first answer)
        jd = os.path.join(HERE, 'jarvis')
        if jd not in sys.path:
            sys.path.insert(0, jd)
        time.sleep(30)
        while True:
            try:
                import jarvis
                jarvis.warm()
            except Exception:
                pass
            time.sleep(1500)
    threading.Thread(target=_jarvis_warm, name='jarvis-warm', daemon=True).start()

    claude_bridge.start(dict(looks=set(LOOKS), look=lambda n: threading.Thread(target=apply, args=(n,), daemon=True).start(),
                             ask=ask_jarvis, status=_bridge_status, reload=_reload, hub_restart=_hub_restart,
                             beat_start=_beat_start, tasks={'pi_hue_key': lambda: __import__('pi_hue_key').create(180),
                                    'pi_deploy': lambda: __import__('pi_deploy').deploy(),
                                    'pi_brain_status': lambda: __import__('pi_deploy').read_status(),
                                    'pi_door_test': lambda: __import__('pi_deploy').door_test(),
                                    'shortcut_test': _shortcut_test, 'rotate_token': _rotate_token,
                                    'make_missing_shortcuts': _make_missing, 'py_env': _py_env,
                                    'build_jarvis_app': _build_jarvis_app, 'voices': _voices, 'chime_demo': _chime_demo,
                                    'jarvis_restart': lambda: sh('pkill -f "[j]arvis/listen.py" || true')}))
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
