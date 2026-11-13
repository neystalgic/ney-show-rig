#!/usr/bin/env python3
# =============================================================================
# PI HUE KEY -- gives the Raspberry Pi its OWN Hue key (Michael's call, Nov 12), so calm looks,
# the night light and the schedule can run from the Pi with the Mac asleep.
#
# Run from rig_control (bridge task "pi_hue_key"): asks the Hue bridge for a new key named
# "ney_pi" and waits up to 60 s for the round button. The key goes straight to the Pi over SSH into
# ~/.ney_secrets/hue_pi.json (folder 700, file 600 -- outside every repo and backup). It is never printed,
# logged or saved on the Mac. Revoke any time in the Hue app (Settings > ... > connected apps: ney_pi).
# =============================================================================
import json, subprocess, time
import hue_stream as hs

PI_SSH = 'mjney99@100.127.200.67'
PI_FILE = '~/.ney_secrets/hue_pi.json'
STATUS = {'last': 'not started'}


def _say(msg):
    STATUS['last'] = '%s %s' % (time.strftime('%H:%M:%S'), msg)


def create(wait_s=60):
    cfg = hs.load_config()
    ip = cfg.get('ip')
    if not ip:
        return _say('failed: no bridge address in the Mac config')
    _say('waiting for the round button on the Hue bridge (%d s)' % wait_s)
    key = None
    end = time.time() + wait_s
    while time.time() < end:
        try:
            res = hs.http('POST', 'https://%s/api' % ip, {'devicetype': 'ney_pi#raspberrypi', 'generateclientkey': True})
        except Exception as e:
            return _say('failed: bridge not reachable (%s)' % e.__class__.__name__)
        item = res[0] if isinstance(res, list) and res else {}
        if 'success' in item:
            key = {'ip': ip, 'username': item['success']['username'], 'clientkey': item['success']['clientkey'],
                   'name': 'ney_pi', 'created': time.strftime('%Y-%m-%d %H:%M')}
            break
        time.sleep(1.5)
    if not key:
        return _say('button not pressed in time -- ask Claude to try again')
    try:                                                   # prove the new key works before handing it over
        n = len(hs.v2({'ip': ip, 'username': key['username']}, 'light').get('data', []))
    except Exception as e:
        return _say('key created but test failed (%s) -- revoke "ney_pi" in the Hue app and retry' % e.__class__.__name__)
    cmd = ('umask 077 && mkdir -p ~/.ney_secrets && chmod 700 ~/.ney_secrets && '
           'cat > %s.tmp && mv %s.tmp %s && chmod 600 %s && test -s %s && echo saved') % ((PI_FILE,) * 5)
    try:
        r = subprocess.run(['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', PI_SSH, cmd],
                           input=json.dumps(key), capture_output=True, text=True, timeout=30)
    except Exception as e:
        return _say('key works (%d lights) but could not reach the Pi (%s) -- revoke "ney_pi" in the Hue app and retry'
                    % (n, e.__class__.__name__))
    if r.returncode != 0 or 'saved' not in r.stdout:
        return _say('key works (%d lights) but saving on the Pi failed: %s -- revoke "ney_pi" in the Hue app and retry'
                    % (n, (r.stderr or r.stdout).strip()[:120]))
    key = None                                             # drop it from memory
    _say('DONE: the Pi has its own Hue key "ney_pi" (sees %d lights), saved in %s' % (n, PI_FILE))
