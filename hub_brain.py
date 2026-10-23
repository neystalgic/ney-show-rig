# =============================================================================
# HUE HUB -- the audio brain (Essentia)
#
# Listens to the same sound the hub already hears (the gear + Ableton's master
# through the Scarlett's Loopback) and works out the HARMONY:
#   chord   the chord sounding right now (e.g. Fm, Db, Eb) and how sure it is
#   key     the key of the last ~30 s of music (EDM key profiles)
# plus a couple of timbre measures (brightness, spectral flux) for later.
#
# When you are NOT playing notes, a steady chord is sent into the show as a MIDI
# note on channel 2 of the IAC bus ("heard chords"), so the lamps, the visuals
# and later the Zephyrus colour the room by the chord's step in the key, exactly
# like notes you play (1 red, 2 orange ...). Notes you play always win.
#
# Needs (once):  python3 -m pip install --user "essentia==2.1b6.dev1389"
# Without Essentia the hub simply runs without the brain.
# =============================================================================

import collections
import threading
import time

try:
    import numpy as np
except ImportError:
    np = None

es = None
IMPORT_ERROR = None
try:
    import essentia
    try:
        essentia.log.infoActive = False
        essentia.log.warningActive = False
    except Exception:
        pass
    import essentia.standard as es
except Exception as e:                      # not installed: the hub carries on without the brain
    IMPORT_ERROR = repr(e)

NOTE_PC = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7,
           'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11}


def available():
    return es is not None and np is not None


def parse_chord(name):
    """'C#m' -> (1, True); 'Eb' -> (3, False); anything odd -> (None, False)."""
    if not name:
        return None, False
    minor = name.endswith('m')
    root = name[:-1] if minor else name
    return NOTE_PC.get(root), minor


class Brain:
    FRAME = 4096
    HOP = 2048

    def __init__(self, sr=48000):
        self.sr = int(sr)
        self.lock = threading.Lock()
        self.buf = collections.deque()           # mono float32 blocks from the sound card
        self.buffered = 0
        self.frame = np.zeros(self.FRAME, dtype=np.float32)
        self.win = es.Windowing(type='blackmanharris62', size=self.FRAME)
        self.spec = es.Spectrum(size=self.FRAME)
        self.peaks = es.SpectralPeaks(orderBy='magnitude', magnitudeThreshold=1e-5, minFrequency=40,
                                      maxFrequency=5000, maxPeaks=60, sampleRate=self.sr)
        self.hpcp = es.HPCP(size=12, referenceFrequency=440, harmonics=8, bandPreset=True, minFrequency=40,
                            maxFrequency=5000, weightType='cosine', nonLinear=False, windowSize=1.0,
                            sampleRate=self.sr)
        self.chords = es.ChordsDetection(hopSize=self.HOP, windowSize=1.0, sampleRate=self.sr)
        self.key = es.Key(profileType='edma', numHarmonics=4, pcpSize=12, slope=0.6, usePolyphony=True,
                          useThreeChords=True)
        self.centroid = es.Centroid(range=self.sr / 2.0)
        self.flux = es.Flux()
        self.hist = collections.deque(maxlen=int(2.0 * self.sr / self.HOP))   # ~2 s of HPCP frames
        self.key_avg = np.zeros(12, dtype=np.float64)
        self.frames = 0
        self.state = dict(chord=None, strength=0.0, root=None, minor=False, key=None, scale=None,
                          key_strength=0.0, bright=0.0, flux=0.0, level=0.0, stable=None)
        self._cand = (None, 0)                   # (chord, how many updates in a row)
        self._events = collections.deque(maxlen=8)
        self.run = True
        self.th = threading.Thread(target=self._loop, name='hub-brain', daemon=True)
        self.th.start()

    # -- sound card thread: just queue the samples (never blocks the audio callback) --
    def feed(self, x):
        with self.lock:
            self.buf.append(np.asarray(x, dtype=np.float32).copy())
            self.buffered += len(x)
            while self.buffered > self.sr * 2:             # never fall more than 2 s behind
                self.buffered -= len(self.buf.popleft())

    def stop(self):
        self.run = False

    def poll(self):
        """New steady chords since the last call: [(root 0-11, minor, strength), ...]"""
        out = []
        while self._events:
            out.append(self._events.popleft())
        return out

    # -- the brain's own thread --
    def _take(self, n):
        with self.lock:
            if self.buffered < n:
                return None
            parts, got = [], 0
            while got < n:
                b = self.buf.popleft()
                need = n - got
                if len(b) > need:
                    parts.append(b[:need])
                    self.buf.appendleft(b[need:])
                    got += need
                else:
                    parts.append(b)
                    got += len(b)
            self.buffered -= n
        return np.concatenate(parts)

    def _loop(self):
        while self.run:
            x = self._take(self.HOP)
            if x is None:
                time.sleep(0.01)
                continue
            try:
                self._process(x)
            except Exception:
                time.sleep(0.05)

    def _process(self, hop):
        self.frame = np.concatenate([self.frame[self.HOP:], hop]).astype(np.float32)
        level = float(np.sqrt(np.mean(self.frame * self.frame)) + 1e-12)
        sp = self.spec(self.win(self.frame))
        f, m = self.peaks(sp)
        h = self.hpcp(f, m)
        self.hist.append(h)
        self.frames += 1
        st = self.state
        st['level'] = level
        st['bright'] = float(self.centroid(sp)) / (self.sr / 2.0)
        st['flux'] = float(self.flux(sp))
        loud = level > 1e-3                      # about -60 dBFS: below that it's silence
        hn = np.asarray(h, dtype=np.float64)
        frame_tonal = hn.sum() > 0 and np.sort(hn)[-3:].sum() / hn.sum() >= 0.42
        if loud and frame_tonal:
            self.tonal_frames = getattr(self, 'tonal_frames', 0) + 1
            self.key_avg = self.key_avg * 0.997 + np.asarray(h, dtype=np.float64) * 0.003   # ~30 s memory
        if self.frames % 4 == 0 and len(self.hist) >= 8:          # ~10 chord guesses a second
            avg = np.mean(np.array(self.hist), axis=0)
            tonal = avg.sum() > 0 and np.sort(avg)[-3:].sum() / avg.sum() >= 0.42   # drums alone: ~0.34
            st['tonal'] = round(float(np.sort(avg)[-3:].sum() / max(avg.sum(), 1e-9)), 2)
            if not loud or not tonal:
                self._cand = (None, 0)
                st['chord'], st['strength'] = None, 0.0
            else:
                ch, strength = self.chords(np.array(self.hist, dtype=np.float32))
                name, s = (ch[-1], float(strength[-1])) if len(ch) else (None, 0.0)
                st['chord'], st['strength'] = name, s
                c, k = self._cand
                k = k + 1 if name == c else 1
                self._cand = (name, k)
                root, minor = parse_chord(name)
                # steady for ~0.4 s and reasonably sure -> a new chord event
                if root is not None and k == 3 and s >= 0.45 and name != st['stable']:
                    st['stable'], st['root'], st['minor'] = name, root, minor
                    self._events.append((root, minor, s))
        if self.frames % 48 == 0 and getattr(self, 'tonal_frames', 0) >= 150:   # ~6 s of real harmony first      # the key, every ~2 s
            k, scale, strength, _ = self.key(self.key_avg.astype(np.float32))
            st['key'], st['scale'], st['key_strength'] = k, scale, float(strength)

    def snapshot(self):
        st = self.state
        return dict(chord=st['chord'], strength=round(st['strength'], 2), steady=st['stable'],
                    key=('%s %s' % (st['key'], st['scale'])) if st['key'] else None,
                    key_strength=round(st['key_strength'], 2), bright=round(st['bright'], 3),
                    tonal=st.get('tonal'))
