# =============================================================================
# HUE HUB -- the key comes from Live (AbletonOSC)
#
# Ableton Live 12 knows the song's key and scale (the Scale menu in the top
# bar). With the free AbletonOSC remote script running in Live (Settings >
# Link, Tempo & MIDI > Control Surface: AbletonOSC), the hub asks Live for
# them and keeps the colours in step: change Live's key, and 1 = red follows.
#
#   AbletonOSC listens on UDP 11000 and answers on 11001 (this module).
# =============================================================================

import socket
import struct
import time

# Live 12's scale names -> semitone steps from the root (anything else: major / minor by name)
SCALE_TABLE = {
    'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10],
    'dorian': [0, 2, 3, 5, 7, 9, 10], 'mixolydian': [0, 2, 4, 5, 7, 9, 10],
    'lydian': [0, 2, 4, 6, 7, 9, 11], 'phrygian': [0, 1, 3, 5, 7, 8, 10], 'locrian': [0, 1, 3, 5, 6, 8, 10],
    'harmonic minor': [0, 2, 3, 5, 7, 8, 11], 'melodic minor': [0, 2, 3, 5, 7, 9, 11],
    'harmonic major': [0, 2, 4, 5, 7, 8, 11], 'phrygian dominant': [0, 1, 4, 5, 7, 8, 10],
    'dorian #4': [0, 2, 3, 6, 7, 9, 10], 'lydian dominant': [0, 2, 4, 6, 7, 9, 10],
    'lydian augmented': [0, 2, 4, 6, 8, 9, 11], 'super locrian': [0, 1, 3, 4, 6, 8, 10],
    'hungarian minor': [0, 2, 3, 6, 7, 8, 11], 'bhairav': [0, 1, 4, 5, 7, 8, 11],
    'major pentatonic': [0, 2, 4, 7, 9], 'minor pentatonic': [0, 3, 5, 7, 10], 'minor blues': [0, 3, 5, 6, 7, 10],
    'whole tone': [0, 2, 4, 6, 8, 10], 'hirajoshi': [0, 2, 3, 7, 8], 'in-sen': [0, 1, 5, 7, 10],
    'iwato': [0, 1, 5, 6, 10], 'kumoi': [0, 2, 3, 7, 9],
}


def scale_steps(name):
    n = str(name or 'major').strip().lower()
    if n in SCALE_TABLE:
        return SCALE_TABLE[n]
    return SCALE_TABLE['minor'] if 'minor' in n else SCALE_TABLE['major']


# ---- just enough OSC ----
def _pad(b):
    return b + b'\0' * (4 - len(b) % 4)


def osc_message(address, *args):
    tags, data = ',', b''
    for a in args:
        if isinstance(a, int):
            tags += 'i'; data += struct.pack('>i', a)
        elif isinstance(a, float):
            tags += 'f'; data += struct.pack('>f', a)
        else:
            tags += 's'; data += _pad(str(a).encode())
    return _pad(address.encode()) + _pad(tags.encode()) + data


def osc_parse(pkt):
    def string(i):
        j = pkt.index(b'\0', i)
        return pkt[i:j].decode('utf-8', 'replace'), (j // 4 + 1) * 4
    addr, i = string(0)
    tags, i = string(i)
    args = []
    for t in tags[1:]:
        if t == 'i':
            args.append(struct.unpack('>i', pkt[i:i + 4])[0]); i += 4
        elif t == 'f':
            args.append(struct.unpack('>f', pkt[i:i + 4])[0]); i += 4
        elif t == 's':
            s, i = string(i); args.append(s)
        elif t in 'TF':
            args.append(t == 'T')
    return addr, args


class LiveKey:
    def __init__(self, hub, live_port=11000, my_port=11001):
        self.hub = hub
        self.live = ('127.0.0.1', live_port)
        self.sock = None
        self.my_port = my_port
        self.last_ask = 0.0
        self.last_heard = 0.0
        self.root = None
        self.scale = None
        self.status = 'waiting for Live (AbletonOSC)'
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(('127.0.0.1', my_port))
            self.sock.setblocking(False)
        except OSError as e:
            self.sock = None
            self.status = 'could not listen on port %d (%s)' % (my_port, e)

    def settings(self):
        return self.hub.state['settings']

    def poll(self):
        if self.sock is None or not self.settings().get('key_from_live', True):
            return
        now = time.time()
        if now - self.last_ask > 5.0:                     # (re)subscribe -- also finds Live after a restart
            self.last_ask = now
            for prop in ('root_note', 'scale_name'):
                try:
                    self.sock.sendto(osc_message('/live/song/start_listen/%s' % prop), self.live)
                    self.sock.sendto(osc_message('/live/song/get/%s' % prop), self.live)
                except OSError:
                    pass
        changed = False
        for _ in range(20):
            try:
                pkt, _a = self.sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                break
            try:
                addr, args = osc_parse(pkt)
            except Exception:
                continue
            if addr == '/live/song/get/root_note' and args:
                v = int(args[-1]) % 12
                changed |= v != self.root
                self.root = v
                self.last_heard = now
            elif addr == '/live/song/get/scale_name' and args:
                v = str(args[-1])
                changed |= v != self.scale
                self.scale = v
                self.last_heard = now
        if changed and self.root is not None and self.scale:
            st = self.settings()
            st['deg_root'], st['deg_scale'] = self.root, self.scale.lower()
            try:
                self.hub.save_soon()
            except Exception:
                pass
        if now - self.last_heard < 15.0 and self.root is not None:
            names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            self.status = 'following Live: %s %s' % (names[self.root], self.scale)
        elif self.last_heard:
            self.status = 'lost Live (AbletonOSC) -- using the last key'
