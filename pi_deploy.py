#!/usr/bin/env python3
# =============================================================================
# PI DEPLOY -- Claude's route to the Pi without SSH of its own (Michael's call, Nov 12): rig_control (which already
# has the Mac's SSH access to the Pi) copies pi/brain/ to ~/NeyBrain on the Pi, runs the brain's tests ON THE PI,
# and only then restarts the brain. Bridge task: {"do": "pi_deploy"}.  Result: STATUS['last'] (and bridge status).
# Also: {"do": "pi_brain_status"} reads ~/NeyBrain/status.json + the last log lines.
# =============================================================================
import json, os, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'pi', 'brain')
PI = 'mjney99@100.127.200.67'
FILES = ('ney_brain.py', 'test_brain.py', 'ney-brain.service', 'restart.sh')
STATUS = {'last': 'not run', 'brain': None}


def _say(m):
    STATUS['last'] = '%s %s' % (time.strftime('%H:%M:%S'), m)


def ssh(cmd, stdin=None, timeout=40):
    return subprocess.run(['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', PI, cmd],
                          input=stdin, capture_output=True, text=True, timeout=timeout)


def _mac_urls():
    urls = []
    for iface in ('en0', 'en1', 'en7', 'en8'):
        ip = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', iface], capture_output=True, text=True).stdout.strip()
        if ip:
            urls.append('http://%s:7040/' % ip)
    for ts in ('/Applications/Tailscale.app/Contents/MacOS/Tailscale', '/usr/local/bin/tailscale', '/opt/homebrew/bin/tailscale'):
        if os.path.exists(ts):
            ip = subprocess.run([ts, 'ip', '-4'], capture_output=True, text=True).stdout.strip().splitlines()
            if ip:
                urls.append('http://%s:7040/' % ip[0])
            break
    return urls


def deploy():
    try:
        _say('copying the brain to the Pi')
        r = ssh('mkdir -p ~/NeyBrain')
        if r.returncode:
            return _say('failed: Pi not reachable over SSH (%s)' % (r.stderr.strip()[:100]))
        for f in FILES:
            with open(os.path.join(SRC, f)) as fh:
                r = ssh('cat > ~/NeyBrain/%s.new && mv ~/NeyBrain/%s.new ~/NeyBrain/%s' % (f, f, f), stdin=fh.read())
            if r.returncode:
                return _say('failed copying %s: %s' % (f, r.stderr.strip()[:100]))
        ssh('cat > ~/NeyBrain/brain.json', stdin=json.dumps({'mac_urls': _mac_urls()}))
        _say('running the brain tests on the Pi')
        r = ssh('cd ~/NeyBrain && python3 test_brain.py')
        if r.returncode or 'passed' not in r.stdout:
            return _say('tests FAILED on the Pi, old brain left running: %s' % (r.stdout + r.stderr).strip()[-160:])
        _say('restarting the brain')
        try:
            ssh('bash ~/NeyBrain/restart.sh', timeout=30)
        except subprocess.TimeoutExpired:
            pass                                   # the check below decides
        r = ssh('pgrep -f "[n]ey_brain.py" >/dev/null && echo running; systemctl is-enabled ney-brain 2>/dev/null || echo not-installed')
        out = r.stdout.split()
        if 'running' not in out:
            return _say('brain did not start -- see ~/NeyBrain/brain.log on the Pi')
        _say('DONE: brain running on the Pi%s' % ('' if 'enabled' in out else
                                                   ' (not yet set to start on boot -- needs the one sudo line)'))
        read_status()
    except Exception as e:
        _say('failed: %s: %s' % (e.__class__.__name__, e))


def read_status():
    try:
        r = ssh('cat ~/NeyBrain/status.json 2>/dev/null; echo; echo ---; tail -5 ~/NeyBrain/brain.log 2>/dev/null; '
                'systemctl is-enabled ney-brain 2>/dev/null || echo not-installed', timeout=15)
        body, _, rest = r.stdout.partition('---')
        st = json.loads(body.strip() or '{}')
        st['log'] = rest.strip().splitlines()[:-1]
        boot = (rest.strip().splitlines() or ['?'])[-1]
        st['boot'] = 'enabled' if boot == 'enabled' else 'not-installed'
        STATUS['brain'] = st
        return st
    except Exception as e:
        STATUS['brain'] = {'error': '%s' % e.__class__.__name__}
        return STATUS['brain']
