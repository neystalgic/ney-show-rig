# test_console_route.py -- offline tests for the Rig Console (away loop W2).  No network, no hub, no lights.
#   python3 test_console_route.py
# Covers: console_route (snapshot + page + cookie), apply_patches.py on TEMP copies, the page's own node test,
# and that every key/look the page can send is already allowed by the live rig_control.py (read only).
import io, json, os, re, shutil, socket, subprocess, sys, tempfile, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)


def _no_net(*a, **k):
    raise AssertionError('network call attempted')
socket.socket = _no_net                                   # any real socket = test failure
socket.create_connection = _no_net
_real_urlopen = urllib.request.urlopen
urllib.request.urlopen = _no_net

import console_route as cr
import apply_patches as ap

PASS = FAIL = 0


def check(cond, what):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print('FAIL', what)


class FakeHandler:
    def __init__(self):
        self.code, self.headers, self.wfile, self.json, self.text = None, [], io.BytesIO(), None, None
    def send_response(self, c): self.code = c
    def send_header(self, k, v): self.headers.append((k, v))
    def end_headers(self): pass
    def reply_json(self, c, obj): self.code, self.json = c, json.loads(json.dumps(obj))
    def reply(self, c, t): self.code, self.text = c, t


def live_show():
    return {'level': 0.4567, 'clock': {'tempo': 124.0, 'bar': 3}, 'audio': {'status': 'listening', 'section': 'build'},
            'show': {'on': True, 'act': 'zones', 'mode': 'wave', 'bar': 3, 'bars': 8, 'section': 'groove', 'lock': ''},
            'cols': {'1': '#000000'}, 'secret': 'x'}


tmp = tempfile.mkdtemp(prefix='console_test_')
with open(os.path.join(tmp, 'hub_state.json'), 'w') as f:
    json.dump({'settings': {'dmx_pattern': 'modes', 'show_wave': 'back', 'show_loop_dir': 'cw', 'show_audio': 0.25,
                            'hue_key': 'nope', 'show_zones': {'order': ['1A', '1B', 2], 'zones': {}}}}, f)
STATE = {'look': 'purple', 'since': '21:00', 'busy': False, 'guest': True, 'last_error': None, 'token': 'SECRET-T'}

# ---- snapshot ----
s = cr.snapshot(STATE, tmp, live_fn=live_show)
check(s['hub'] is True and s['show']['mode'] == 'wave' and s['show']['bar'] == 3, 'live show passed through')
check(s['level'] == 0.457 and s['tempo'] == 124.0 and s['audio'] == 'listening', 'level/tempo/audio')
check(s['section'] == 'groove', 'section from the director first')
check(s['look'] == 'purple' and s['guest'] is True and s['since'] == '21:00', 'look + guest')
check(s['saved'] == {'dmx_pattern': 'modes', 'show_wave': 'back', 'show_loop_dir': 'cw', 'show_audio': 0.25,
                     'zone_order': ['1A', '1B', '2']}, 'saved settings: show keys only + zone order')
blob = json.dumps(s)
check('SECRET-T' not in blob and 'token' not in blob and 'hue_key' not in blob and 'cols' not in blob, 'nothing extra leaks out')
s = cr.snapshot(STATE, tmp, live_fn=lambda: None)
check(s['hub'] is False and s['show'] is None and s['level'] is None and s['section'] is None, 'hub off')
s = cr.snapshot({}, tmp, live_fn=lambda: {'show': 'junk', 'audio': 5, 'clock': [], 'level': 'x'})
check(s['hub'] is True and s['show'] is None and s['level'] is None and s['tempo'] is None, 'junk live survives')
s = cr.snapshot({}, os.path.join(tmp, 'nope'), live_fn=lambda: None)
check(s['saved'] == {'zone_order': []}, 'missing hub_state.json survives')

# ---- fetch_live: short timeout, None on failure, never a real call here ----
seen = {}
def fake_urlopen(url, timeout=None):
    seen.update(url=url, timeout=timeout)
    raise OSError('refused')
cr.urllib.request.urlopen = fake_urlopen
check(cr.fetch_live() is None and seen['url'] == 'http://127.0.0.1:7020/api/live' and seen['timeout'] <= 2, 'fetch_live: local hub, <=2 s, None when off')
class R:
    def read(self): return b'{"show": {"on": false}}'
cr.urllib.request.urlopen = lambda url, timeout=None: R()
check(cr.fetch_live() == {'show': {'on': False}}, 'fetch_live parses')
cr.urllib.request.urlopen = lambda url, timeout=None: type('R', (), {'read': lambda self: b'[1,2]'})()
check(cr.fetch_live() is None, 'fetch_live: non-dict -> None')
cr.urllib.request.urlopen = _no_net

# ---- handle(): page + cookie, json ----
shutil.copy(os.path.join(HERE, 'console.html'), tmp)
h = FakeHandler()
cr.handle(h, 'console', tmp, 'TKN', STATE, live_fn=live_show)
hd = dict(h.headers)
check(h.code == 200 and hd['Content-Type'].startswith('text/html') and h.wfile.getvalue().startswith(b'<!doctype html>'), 'page served')
check('rig_key=TKN' in hd['Set-Cookie'] and 'HttpOnly' in hd['Set-Cookie'] and hd['Cache-Control'] == 'no-store', 'cookie like /health')
check(hd['Content-Length'] == str(len(h.wfile.getvalue())), 'content length')
h = FakeHandler()
cr.handle(h, 'console.json', tmp, 'TKN', STATE, live_fn=live_show)
check(h.code == 200 and h.json['show']['act'] == 'zones' and 'TKN' not in json.dumps(h.json), 'json route, no token inside')
h = FakeHandler()
cr.handle(h, 'console', os.path.join(tmp, 'empty'), 'TKN', STATE)
check(h.code == 404 and 'DEPLOY' in h.text, 'missing page -> 404 hint')

# ---- the page's own test (node) ----
p = subprocess.run(['node', os.path.join(HERE, 'test_console_page.js')], capture_output=True, text=True, timeout=60)
print('  node:', p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-300:])
check(p.returncode == 0, 'page test (node) passed')

# ---- the page only sends what the LIVE rig_control already allows (read only) ----
with open(os.path.join(REPO, 'rig_control.py')) as f:
    live_rc = f.read()
m = re.search(r"ok_keys = \{(.*?)\n\s*done = \[\]", live_rc, re.S)
allowed = set(re.findall(r"'(\w+)':", m.group(1))) if m else set()
looks = set(re.findall(r"^    '(\w+)': \(", live_rc, re.M))
lines = open(os.path.join(HERE, '.page_keys.txt')).read().split()
keys = [x for x in lines if not x.startswith('look:')]
qlooks = [x[5:] for x in lines if x.startswith('look:')]
check(keys and set(keys) <= allowed, 'page keys %s all allowed by /show/set' % keys)
check(len(qlooks) == 8 and set(qlooks) <= looks, 'quick looks %s all exist' % qlooks)
check(not any(k in keys for k in ('strobe', 'energy', 'chase_lamps')), 'no strobe/energy keys from the page')

# ---- apply_patches on TEMP copies ----
root = tempfile.mkdtemp(prefix='console_apply_')
shutil.copy(os.path.join(REPO, 'rig_control.py'), root)
orig = open(os.path.join(root, 'rig_control.py')).read()
mt = os.path.getmtime(os.path.join(REPO, 'rig_control.py'))
check(ap.main(root=root, src=HERE) == 0, 'apply ok')
new = open(os.path.join(root, 'rig_control.py')).read()
check(new.count(ap.MARK) == 1 and new.index(ap.MARK) < new.index(ap.ANCHOR), 'route added once, before /show/set')
check(new.replace(ap.BLOCK, '', 1) == orig, 'nothing else changed')
i_tok, i_new = new.index('if not hmac.compare_digest(tok, TOKEN)'), new.index(ap.MARK)
check(i_tok < i_new, 'route sits after the token check (same login)')
check(os.path.exists(os.path.join(root, 'rig_control.py.bak-2026-11-17-console')), 'backup made')
check(all(os.path.exists(os.path.join(root, n)) for n in ap.FILES), 'files copied')
check(ap.main(root=root, src=HERE) == 0 and open(os.path.join(root, 'rig_control.py')).read() == new, 'idempotent')
root2 = tempfile.mkdtemp(prefix='console_stop_')
with open(os.path.join(root2, 'rig_control.py'), 'w') as f:
    f.write(orig.replace(ap.ANCHOR, "        if path == 'show/set2':"))
before = sorted(os.listdir(root2))
check(ap.main(root=root2, src=HERE) == 2 and sorted(os.listdir(root2)) == before, 'STOP when anchor moved, nothing touched')
check(os.path.getmtime(os.path.join(REPO, 'rig_control.py')) == mt and not os.path.exists(os.path.join(REPO, 'console_route.py')), 'live files untouched')

print('PASSED %d/%d' % (PASS, PASS + FAIL) if not FAIL else 'FAILED %d of %d' % (FAIL, PASS + FAIL))
sys.exit(1 if FAIL else 0)
