#!/usr/bin/env python3
# =============================================================================
# BEAT SENDER -- Rig 2.0 Phase 2 (first version). Shares the hub's beat with other
# machines (Unreal on the Zephyrus first) as OSC over UDP.
#
# Listens to the hub's own live stream (http://127.0.0.1:7020/api/stream, ~20 a second)
# and sends each frame to every target in beat_sender.json. Read-only: it never
# changes the hub or the lights. If the hub isn't running it waits and retries,
# backing off from 1 s up to 30 s, so it can be left running.
#
# OSC addresses (all floats 0..1 unless noted):
#   /ney/beat      phase inside the current beat (0 on the beat -> 1 just before the next)
#   /ney/onbeat    1 on the frame a new beat starts, else 0   (int)
#   /ney/count     beat in the bar 1..4, then bar number      (int, int)
#   /ney/tempo     BPM                                         (float, not 0..1)
#   /ney/level     overall loudness
#   /ney/kick /ney/snare /ney/hats   drum hits (jump up on a hit, then fall)
#   /ney/drop      how "drop" the music is right now
#   /ney/section   quiet / groove / breakdown / drop           (string)
#   /ney/colour    the lamps' average colour                   (r, g, b)
#   /ney/blackout  1 when the hub is blacked out               (int)
# Run:   python3 beat_sender.py            (Ctrl-C to stop)   Log: /tmp/beat_sender.log
# =============================================================================
import json, os, socket, struct, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'beat_sender.json')
STREAM = 'http://127.0.0.1:7020/api/stream'
DEFAULTS = {'targets': [{'name': 'listener on this Mac', 'host': '127.0.0.1', 'port': 7701}]}


# -- OSC, written out by hand so nothing needs installing --
def _pad(b):
    return b + b'\0' * (4 - len(b) % 4)


def osc(address, *args):
    tags, data = ',', b''
    for a in args:
        if isinstance(a, bool) or isinstance(a, int):
            tags += 'i'; data += struct.pack('>i', int(a))
        elif isinstance(a, float):
            tags += 'f'; data += struct.pack('>f', a)
        else:
            tags += 's'; data += _pad(str(a).encode())
    return _pad(address.encode()) + _pad(tags.encode()) + data


def osc_decode(pkt):
    """The other way round (for the listener and the tests)."""
    def string(i):
        j = pkt.index(b'\0', i)
        return pkt[i:j].decode(), (j // 4 + 1) * 4
    addr, i = string(0)
    tags, i = string(i)
    out = []
    for t in tags[1:]:
        if t == 'i':
            out.append(struct.unpack('>i', pkt[i:i + 4])[0]); i += 4
        elif t == 'f':
            out.append(round(struct.unpack('>f', pkt[i:i + 4])[0], 4)); i += 4
        elif t == 's':
            s, i = string(i); out.append(s)
    return addr, out


# -- hub frame -> OSC messages --
def _avg_colour(cols):
    rgb = []
    for h in (cols or {}).values():
        h = str(h).lstrip('#')
        if len(h) == 6:
            rgb.append(tuple(int(h[k:k + 2], 16) / 255.0 for k in (0, 2, 4)))
    if not rgb:
        return (0.0, 0.0, 0.0)
    return tuple(round(sum(c[k] for c in rgb) / len(rgb), 4) for k in range(3))


class Framer:
    def __init__(self):
        self.last_beat = None

    def messages(self, snap):
        clock = snap.get('clock') or {}
        audio = snap.get('audio') or {}
        beats = float(clock.get('beats') or 0.0)
        whole = int(beats)
        onbeat = int(self.last_beat is not None and whole != self.last_beat)
        self.last_beat = whole
        f = lambda v: max(0.0, min(1.0, float(v or 0.0)))
        return [
            osc('/ney/beat', round(beats - whole, 4)),
            osc('/ney/onbeat', onbeat),
            osc('/ney/count', int(clock.get('beat') or 1), int(clock.get('bar') or 1)),
            osc('/ney/tempo', float(clock.get('tempo') or 120.0)),
            osc('/ney/level', f(snap.get('level'))),
            osc('/ney/kick', f(audio.get('kick'))),
            osc('/ney/snare', f(audio.get('snare'))),
            osc('/ney/hats', f(audio.get('hats'))),
            osc('/ney/drop', f(audio.get('drop'))),
            osc('/ney/section', str(audio.get('section') or 'quiet')),
            osc('/ney/colour', *[float(c) for c in _avg_colour(snap.get('cols'))]),
            osc('/ney/blackout', int(bool(snap.get('blackout')))),
        ]


def log(msg):
    line = time.strftime('%H:%M:%S ') + msg
    print(line, flush=True)
    try:
        with open('/tmp/beat_sender.log', 'a') as fh:
            fh.write(line + '\n')
    except OSError:
        pass


def settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS) as fh:
            s.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return s


def resolve(targets):
    """Names like zephyrus.local -> an IPv4 address, looked up once per settings reload
    (not every frame), so a machine that changes address is found again within ~30 s."""
    out = []
    for t in targets:
        try:
            ip = socket.getaddrinfo(t['host'], None, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
            out.append((ip, int(t['port'])))
        except (OSError, KeyError, ValueError):
            pass                                             # that machine is off: skip it for now
    return out


def frames(url=STREAM):
    """Yield hub snapshots from the server-sent-events stream."""
    with urllib.request.urlopen(url, timeout=5) as r:
        for raw in r:
            line = raw.decode('utf-8', 'replace').strip()
            if line.startswith('data: '):
                try:
                    yield json.loads(line[6:])
                except ValueError:
                    continue


def run():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    framer, wait, sent = Framer(), 1.0, 0
    while True:
        targets = resolve(settings()['targets'])
        try:
            log('connecting to the hub; sending to %s' % ', '.join('%s:%d' % t for t in targets))
            for snap in frames():
                wait = 1.0                                   # connected: reset the back-off
                for m in framer.messages(snap):
                    for t in targets:
                        try:
                            sock.sendto(m, t)
                        except OSError:
                            pass                             # a target that's off just misses frames
                sent += 1
                if sent % 600 == 0:                          # about every 30 s
                    log('%d frames sent' % sent)
                    targets = resolve(settings()['targets'])
            log('hub stream ended')
        except Exception as e:
            log('hub not reachable (%s); retrying in %d s' % (e.__class__.__name__, wait))
        time.sleep(wait)
        wait = min(wait * 2, 30.0)                           # exponential back-off


if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        pass
