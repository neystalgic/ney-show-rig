# =============================================================================
# HUE HUB -- listening to the gear
#
# Your chain: Digitone -> Digitakt -> Evil Pet -> Scarlett 4i4 inputs 1 + 2.
# The hub listens to those two inputs (the finished sound, Evil Pet and all)
# and hears:
#   kick    hits in the lows   (30-150 Hz)
#   snare   hits in the body   (snares, claps, rims: 150 Hz - 5 kHz, broadband)
#   hats    hits in the highs  (6 kHz and up)
#   synth   how loud the music is in the mids (Digitone pads, Evil Pet clouds)
#   level   how loud everything is        bright  how bright / dark it sounds
# Levels adapt to how loud you play (automatic gain), so no calibration.
#
# Optional, tighter: notes from the Digitakt's MIDI out arrive through the
# Scarlett's MIDI in. A note on a channel you assign (desk > Audio) fires that
# instrument exactly on time, and the audio guess for it is skipped. The desk
# lists every channel notes arrive on, so you can see what the Digitakt sends.
# If the Digitakt sends MIDI clock, the lights' beat follows the gear's tempo.
#
# Needs (Terminal, once):   python3 -m pip install --user sounddevice numpy
# and macOS must allow Terminal to use the microphone (it asks the first time).
# =============================================================================

import collections
import math
import threading
import time

try:
    import numpy as np
except ImportError:                        # the hub still runs; the audio show says how to fix it
    np = None

VOICES = ['kick', 'snare', 'hats', 'synth']
BANDS = dict(kick=(30.0, 150.0), snare=(150.0, 5000.0), hats=(6000.0, 16000.0), synth=(200.0, 4000.0))
MIN_GAP = dict(kick=0.09, snare=0.10, hats=0.05)          # seconds between two hits of one instrument
RISE = dict(kick=4.0, snare=2.2, hats=1.8)                # how far a band's energy must jump to count as a hit
LOUD = dict(kick=0.72, snare=0.55, hats=0.45)              # ...and how loud (0-1 of its recent range) it must get
SHARE = dict(kick=-9.0, snare=-12.0, hats=-32.0)          # ...and its band's share of the whole sound (dB)
LIGHT_RATE = dict(kick=3.0, snare=2.2, hats=4.5)          # at most this many hits a second light the room...
LIGHT_GAP = dict(kick=0.2, snare=0.22, hats=0.12)         # ...never closer together than this (seconds)


class Analyzer:
    """Pure analysis: feed mono float samples, read features and hits. No sound card needed (testable)."""

    def __init__(self, sr=48000, n=2048, hop=512):
        self.sr, self.n, self.hop = int(sr), n, hop
        self.win = np.hanning(n).astype(np.float32)
        f = np.fft.rfftfreq(n, 1.0 / self.sr)
        self.freqs = f
        self.mask = {k: (f >= lo) & (f < hi) for k, (lo, hi) in BANDS.items()}
        self.buf = np.zeros(0, dtype=np.float32)
        self.prev = None
        self.t = 0.0                                   # seconds of audio analysed
        self.hist = {k: [] for k in MIN_GAP}          # recent flux values per band
        self.last_hit = {k: -10.0 for k in MIN_GAP}
        self.fluxmax = {k: 1e-6 for k in MIN_GAP}
        self.prev_flux = {k: 0.0 for k in MIN_GAP}
        self.peak_db = {k: -30.0 for k in VOICES + ['level']}
        self.floor_db = {k: -70.0 for k in VOICES + ['level']}
        self.level = {k: 0.0 for k in VOICES + ['level']}
        self.inst = {k: 0.0 for k in VOICES + ['level']}
        self.bdb = {k: -120.0 for k in VOICES + ['level']}
        self.prev_inst = {k: 0.0 for k in VOICES + ['level']}
        self.bright = 0.5
        self.hits = []                                 # (time, voice, strength 0-1)
        self.sensitivity = 1.0
        self.silent = True
        self.onset = collections.deque(maxlen=int(10.0 * self.sr / self.hop))   # ~10 s of onset strength
        self.epk = {k: 1e-9 for k in MIN_GAP}
        self.onset_s = collections.deque(maxlen=int(10.0 * self.sr / self.hop))  # snare-band jumps (minus the kick's)
        self.frames = 0

    def feed(self, x):
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        self.buf = np.concatenate([self.buf, x])
        while len(self.buf) >= self.n:
            self._frame(self.buf[:self.n])
            self.buf = self.buf[self.hop:]

    def _frame(self, frame):
        dt = self.hop / float(self.sr)
        self.t += dt
        spec = np.abs(np.fft.rfft(frame * self.win)).astype(np.float32) + 1e-9
        power = spec * spec
        logm = np.log1p(spec * 10.0)
        total_db = 10.0 * math.log10(float(power.sum()) / (self.n * self.n) + 1e-12)
        self.silent = total_db < -72.0
        # loudness per band, with automatic gain (peaks jump up, sink slowly; the floor creeps)
        for k in VOICES + ['level']:
            e = float(power[self.mask[k]].sum()) if k != 'level' else float(power.sum())
            db = 10.0 * math.log10(e / (self.n * self.n) + 1e-12)
            pk, fl = self.peak_db[k], self.floor_db[k]
            pk = db if db > pk else pk - 3.0 * dt                  # -3 dB a second
            fl = db if db < fl else fl + 1.5 * dt
            fl = min(fl, pk - 24.0)                                # keep a 24 dB window at least
            self.peak_db[k], self.floor_db[k] = pk, fl
            v = 0.0 if self.silent else max(0.0, min(1.0, (db - fl) / max(6.0, pk - fl)))
            self.inst[k] = v
            self.bdb[k] = db
            a = 1.0 - math.exp(-dt / (0.02 if v > self.level[k] else 0.22))
            self.level[k] += (v - self.level[k]) * a
        # brightness: spectral centroid, on a log scale between 150 Hz and 8 kHz
        c = float((self.freqs * power).sum() / power.sum())
        b = (math.log(max(150.0, min(8000.0, c))) - math.log(150.0)) / (math.log(8000.0) - math.log(150.0))
        self.bright += (b - self.bright) * (1.0 - math.exp(-dt / 0.3))
        # hits: a band's energy jumping well above what it was just before (scale-free, so it
        # works at any volume), on a peak, while the band is actually sounding. A drum also spills
        # into the other bands (a snare has some low end, a kick some click), so a band only
        # counts if its own jump holds up against its neighbour's.
        rs = {}
        lin = {}
        for k in MIN_GAP:
            e = float(power[self.mask[k]].sum()) + 1e-12
            h = self.hist[k]
            before = sum(h[-4:-1]) / 3.0 if len(h) >= 4 else None
            h.append(e)
            if len(h) > 8:
                del h[0]
            rs[k] = 0.0 if before is None or self.silent else e / (before + 1e-12)
            lin[k] = 0.0 if before is None or self.silent else max(0.0, e - before)
            self.epk[k] = max(e, self.epk[k] * math.exp(-dt / 4.0))
        pr = dict(self.prev_flux)
        lg = {k: math.log10(max(1.0, v)) for k, v in pr.items()}
        rival = dict(kick=lg['snare'] * 0.6, snare=lg['kick'] * 0.6, hats=lg['snare'] * 0.45)
        for k in MIN_GAP:
            need = RISE[k] / max(0.4, min(2.5, self.sensitivity))
            loud = max(self.inst[k], self.prev_inst[k])            # a real hit is loud in its own band...
            share = self.bdb[k] - self.bdb['level']                 # ...and a real part of the whole sound
            if (pr[k] > need and pr[k] >= rs[k] and lg[k] >= rival[k] and loud >= LOUD[k] and share >= SHARE[k]
                    and self.t - self.last_hit[k] >= MIN_GAP[k]):
                st = max(0.15, min(1.0, lg[k] / 1.5))
                self.last_hit[k] = self.t
                score = lg[k] + 2.0 * loud + 0.05 * max(-20.0, share)      # how clearly this is a real hit
                self.hits.append((self.t - dt, k, st, score))
        self.prev_flux = rs
        # onset strength for the beat tracker: how sharply the lows (and a little the body) jump this frame
        # (in energy, not ratios: the loud kick outweighs a quiet bass note that starts after a gap)
        o = math.sqrt(lin['kick'] / (self.epk['kick'] + 1e-12)) + 0.5 * math.sqrt(lin['snare'] / (self.epk['snare'] + 1e-12))
        self.onset.append(o)
        self.onset_s.append(math.sqrt(lin['snare'] / (self.epk['snare'] + 1e-12)) - 0.5 * math.sqrt(lin['kick'] / (self.epk['kick'] + 1e-12)))
        self.frames += 1
        self.prev_inst = dict(self.inst)
        self.prev = logm

    def take_hits(self):
        h, self.hits = self.hits, []
        return h


def midi_call(fn, *args, timeout=3.0):
    """Run a MIDI system call, but never let a stuck MIDI driver freeze the lights: give up after `timeout`."""
    box = {}

    def go():
        try:
            box['v'] = fn(*args)
        except Exception as e:
            box['e'] = e
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError('the Mac\'s MIDI system did not answer within %.0f s' % timeout)
    if 'e' in box:
        raise box['e']
    return box.get('v')


class BeatTracker:
    """Hears the tempo and where the beats fall, from the low end of the music (like a DJ mixer's beat
    sync): autocorrelation of the onset strength for the tempo, a comb over the last seconds for the phase.
    The lights then pump ON the beat -- and off-beat bass notes and synth stabs stop looking like kicks."""

    def __init__(self, fr):
        self.fr = fr                       # onset frames a second
        self.bpm = None
        self.period = None                 # seconds a beat
        self.beat_t = None                 # wall time of a beat (any beat on the grid)
        self.conf = 0.0                    # 0 = no idea, 1 = locked
        self.cand_bpm = None
        self.last = 0.0
        self.backbeat = None               # which beats carry the snare: grid beats with this parity (beat = 2 and 4)
        self.bb_score = 0.0

    def snare_side(self, snare_onset, wall_newest):
        """Is the snare on the even or the odd beats of the grid? (the snare is on 2 and 4, so this places beat 1)"""
        if self.beat_t is None or self.period is None or np is None or len(snare_onset) < self.fr * 4:
            return
        x = np.asarray(snare_onset, dtype=np.float64)[-int(self.fr * 8):]
        n = len(x)
        sums = [0.0, 0.0]
        b0 = self.phase(wall_newest - (n - 1) / self.fr)
        b1 = self.phase(wall_newest)
        for k in range(int(math.ceil(b0)), int(math.floor(b1)) + 1):
            t = self.beat_t + k * self.period
            idx = int(round(n - 1 - (wall_newest - t) * self.fr))
            if 2 <= idx < n - 2:
                sums[k % 2] += float(x[idx - 2:idx + 3].max())
        hi = 0 if sums[0] > sums[1] else 1
        lo = 1 - hi
        score = (sums[hi] - sums[lo]) / (abs(sums[hi]) + abs(sums[lo]) + 1e-9)
        self.bb_score += (score - self.bb_score) * 0.3
        if score > 0.25:
            self.backbeat = hi if (self.backbeat is None or score > 0.4 or self.backbeat == hi) else self.backbeat
        elif self.bb_score < 0.1:
            self.backbeat = None

    def update(self, onset, wall_newest, now):
        if now - self.last < 0.5 or np is None:
            return
        self.last = now
        x = np.asarray(onset, dtype=np.float64)
        n = len(x)
        if n < int(self.fr * 4) or x.max() <= 0:
            self.conf *= 0.7
            return
        x = x[-int(self.fr * 8):]
        n = len(x)
        x = x - x.mean()
        f = np.fft.rfft(x, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        if ac[0] <= 0:
            return
        ac = ac / ac[0]
        lo, hi = int(self.fr * 60.0 / 185.0), int(self.fr * 60.0 / 85.0) + 1
        best, bl = -1.0, None
        for L in range(lo, min(hi, n // 2)):
            bpm = 60.0 * self.fr / L
            prior = math.exp(-0.5 * (math.log2(bpm / 128.0) / 0.55) ** 2)   # club tempos are likely
            sc = (ac[L] + 0.5 * ac[2 * L] if 2 * L < n else ac[L]) * (0.6 + 0.4 * prior)
            if sc > best:
                best, bl = sc, L
        if bl is None:
            return
        a, b, c = ac[bl - 1], ac[bl], ac[bl + 1]                  # fractional lag: a parabola through the peak
        d = a - 2 * b + c
        frac = 0.5 * (a - c) / d if d < -1e-6 else 0.0
        lag = bl + max(-0.5, min(0.5, frac))                   # a parabola can't move the peak past its neighbours
        bpm = 60.0 * self.fr / lag
        if not (60.0 <= bpm <= 220.0):                         # nonsense estimate (silence, noise): ignore it
            return
        strength = max(0.0, min(1.0, (ac[bl] - 0.1) / 0.35))
        # tempo: follow it once it repeats (no jumping on one odd estimate)
        if self.bpm is None or abs(bpm - self.bpm) / self.bpm > 0.04:
            if self.cand_bpm is not None and abs(bpm - self.cand_bpm) / self.cand_bpm < 0.04:
                self.bpm = bpm
                self.beat_t = None
                self.conf = 0.0                                # new tempo: not sure of the grid until it re-locks
            self.cand_bpm = bpm
        else:
            self.bpm += (bpm - self.bpm) * 0.3
        if self.bpm is None:
            return
        P = self.fr * 60.0 / self.bpm
        # phase: the offset whose comb of beats lands on the most onset energy (recent beats count more)
        ks = np.arange(int(n / P) - 1)
        w = np.exp(-ks / 12.0)
        scores = []
        steps = int(P)
        if steps < 2:
            return
        for ph in range(steps):
            idx = (n - 1 - ph - ks * P).astype(int)
            idx = idx[idx >= 0]
            scores.append(float((x[idx] * w[:len(idx)]).sum()))
        scores = np.array(scores)
        ph = int(scores.argmax())
        spread = scores.max() - np.median(scores)
        pk = spread / (np.abs(scores).mean() + 1e-9)
        t_new = wall_newest - ph / self.fr
        self.period = 60.0 / self.bpm
        if self.beat_t is None:
            self.beat_t = t_new
        else:                                                  # nudge the grid toward what it hears
            k = round((t_new - self.beat_t) / self.period)
            err = t_new - (self.beat_t + k * self.period)
            self.beat_t += err * 0.35
        conf = strength * max(0.0, min(1.0, (pk - 0.3) / 1.2))
        self.conf += (conf - self.conf) * 0.4

    def phase(self, t):
        """beats since the grid's reference beat (fractional), or None"""
        if self.beat_t is None or self.period is None:
            return None
        return (t - self.beat_t) / self.period

    def near(self, t, sub=1, tol=0.07):
        """is time t within tol seconds of the grid (sub = 1 beats, 2 eighths)?"""
        b = self.phase(t)
        if b is None:
            return True
        x = b * sub
        return abs(x - round(x)) * self.period / sub <= tol


class AudioIn:
    """The Scarlett (or any input) -> Analyzer, on the sound card's own thread."""

    def __init__(self, hub):
        self.hub = hub
        self.lock = threading.Lock()
        self.an = None
        self.stream = None
        self.status = 'off'
        self.device = None
        self.last_try = 0.0
        self.pending = []           # (wall time, voice, strength, source)
        self.blocks = 0
        self.midi = None
        self.midi_name = None
        self.midi_last_try = 0.0
        self.midi_recent = {}       # voice -> wall time of the last MIDI trigger
        self.seen = {}              # MIDI channel (1-16) -> [notes seen, wall time of the last]
        self.ticks = 0              # MIDI clock from the gear (24 a beat): the lights' beat follows it
        self.tick_hist = []         # (wall time, ticks so far)
        self.clk_t = -100.0
        self.clk_bpm = None
        self.clk_run = False
        self.peak_acc = 0.0         # loudest sample since the last check (raw, before anything)
        self.peak = None            # loudest sample over the last 2 s
        self.zero_for = 0.0         # seconds of pure digital silence (macOS blocking the microphone)
        self.hear = ''              # what the self-check thinks of the input
        self.check_t = time.time()
        self.report_t = time.time()
        self.hits_total = dict(kick=0, snare=0, hats=0)       # hits that lit the room
        self.beat = None
        self.wall_newest = 0.0
        self.beat_marks = set()                               # beat numbers a kick was heard on
        self.beat_hist = collections.deque(maxlen=8)          # last 8 beats: kick on it?
        self.beat_seen = None
        self.grid_next = None
        self.grid_on = False
        self.kick_str = collections.deque(maxlen=8)
        self.heard = {}                                       # everything that sounded like a hit
        self.cands = {}
        self.lit_t = {}
        self.open()

    def settings(self):
        return self.hub.state['settings']

    def open(self):
        self.last_try = time.time()
        if not self.settings().get('audio_on', True):
            self.status = 'off'
            return
        if np is None:
            self.status = 'needs numpy + sounddevice: in Terminal run  python3 -m pip install --user sounddevice numpy'
            return
        try:
            import sounddevice as sd
        except Exception:
            self.status = 'needs sounddevice: in Terminal run  python3 -m pip install --user sounddevice numpy'
            return
        want = str(self.settings().get('audio_in', 'Scarlett')).lower()
        try:
            devs = sd.query_devices()
        except Exception as e:
            self.status = 'cannot list sound inputs (%s)' % e
            return
        idx = None
        for i, d in enumerate(devs):
            if d.get('max_input_channels', 0) >= 1 and want in d.get('name', '').lower():
                idx = i
                break
        if idx is None:
            self.status = 'no input called "%s" (is the Scarlett plugged in?)' % self.settings().get('audio_in', 'Scarlett')
            return
        d = devs[idx]
        chans = [int(c) for c in str(self.settings().get('audio_ch', '1,2')).replace(' ', '').split(',') if c.isdigit()] or [1, 2]
        n_open = max(1, min(int(d['max_input_channels']), max(chans)))
        sr = int(d.get('default_samplerate') or 48000)
        self.an = Analyzer(sr=sr)
        self.beat = BeatTracker(sr / float(self.an.hop))
        self.brain = None                                  # Essentia: chords + key (hub_brain.py), if installed
        try:
            import hub_brain
            if hub_brain.available() and self.settings().get('brain_on', True):
                self.brain = hub_brain.Brain(sr)
        except Exception:
            self.brain = None
        use = [c - 1 for c in chans if 1 <= c <= n_open]

        def cb(indata, frames, ti, status):
            try:
                x = indata[:, use].mean(axis=1) if len(use) > 1 else indata[:, use[0]]
                pk = float(np.max(np.abs(indata[:, use]))) if len(x) else 0.0
                with self.lock:
                    if pk > self.peak_acc:
                        self.peak_acc = pk
                    self.an.sensitivity = float(self.settings().get('audio_sens', 1.0))
                    self.an.feed(x)
                    if self.brain is not None:
                        self.brain.feed(x)
                    now = time.time()
                    self.wall_newest = now - (self.an.n / 2.0) / self.an.sr     # the newest frame's centre
                    for t, k, s, sc in self.an.take_hits():
                        self.pending.append((now, k, s, 'audio', sc))
                    self.blocks += 1
            except Exception:
                pass
        try:
            self.stream = sd.InputStream(device=idx, channels=n_open, samplerate=sr, blocksize=512, dtype='float32',
                                         callback=cb)
            self.stream.start()
            self.device = d['name']
            self.status = 'listening to %s, inputs %s (%d Hz)' % (d['name'], '+'.join(str(c) for c in chans), sr)
            self.base_status = self.status
            self.zero_for, self.hear, self.peak = 0.0, '', None
        except Exception as e:
            self.stream = None
            self.status = 'could not open %s (%s) -- check System Settings > Privacy > Microphone > Terminal' % (d['name'], e)

    def close(self):
        try:
            if getattr(self, 'brain', None) is not None:
                self.brain.stop()
                self.brain = None
        except Exception:
            pass
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None
        self.an = None

    # ---- the Digitakt's sequencer through the Scarlett's MIDI in (optional) ----
    def open_midi(self):
        self.midi_last_try = time.time()
        want = str(self.settings().get('trig_port', 'Scarlett')).lower()
        if not want or not self.settings().get('trig_on', True):
            return
        try:
            import mido
            names = [n for n in midi_call(mido.get_input_names) if want in n.lower()]
            if names:
                self.midi = midi_call(mido.open_input, names[0])
                self.midi_name = names[0]
        except TimeoutError as e:
            self.midi = None
            self.midi_last_try = time.time() + 55.0           # MIDI system stuck: try again in a minute
            print('Gear MIDI: %s -- the lights carry on without it' % e, flush=True)
        except Exception:
            self.midi = None

    def poll(self, now):
        """Called by the hub every frame: (re)open things, and hand over this frame's hits."""
        if self.stream is None and now - self.last_try > 5.0 and self.settings().get('audio_on', True):
            self.open()
        if self.midi is None and now - self.midi_last_try > 5.0:
            self.open_midi()
        if self.midi is not None:
            chmap = self.settings().get('trig_map', {}) or {}
            try:
                for msg in self.midi.iter_pending():
                    if msg.type == 'note_on' and msg.velocity > 0:
                        ch = getattr(msg, 'channel', 0) + 1
                        sn = self.seen.setdefault(ch, [0, now])
                        sn[0] += 1
                        sn[1] = now
                        v = chmap.get(str(ch))
                        if v in MIN_GAP:
                            self.pending.append((now, v, (msg.velocity / 127.0) ** 0.7, 'midi', 99.0))
                    elif msg.type == 'clock':
                        self.ticks += 1
                        self.clk_t = now
                    elif msg.type == 'start':
                        self.ticks, self.clk_run, self.tick_hist = 0, True, []
                    elif msg.type == 'continue':
                        self.clk_run = True
                    elif msg.type == 'stop':
                        self.clk_run = False
                self._tempo(now)
            except Exception:
                self.midi = None
        self._check(now)
        with self.lock:
            hits, self.pending = self.pending, []
            onset = list(self.an.onset) if self.an is not None else []
            sonset = list(self.an.onset_s) if self.an is not None else []
            wn = self.wall_newest
        bt = self.beat
        if bt is not None and onset:
            was = bt.last
            bt.update(onset, wn, now)
            if bt.last != was:
                bt.snare_side(sonset, wn)
        out = []
        out += self._grid(now, hits)
        for t, k, s, src, sc in hits:
            if src == 'midi':
                self.midi_recent[k] = t
                self.lit_t[k] = t
                out.append((k, s))
            elif t - self.midi_recent.get(k, -10.0) > 2.0:      # MIDI is driving this one: skip the audio guess
                self.heard[k] = self.heard.get(k, 0) + 1
                if k == 'kick' and self.grid_on:
                    continue                                     # the beat grid plays the kicks (see _grid)
                if k in ('kick', 'snare') and bt is not None and bt.conf > 0.35 and not bt.near(t, 2 if k == 'kick' else 1, 0.07):
                    continue                                     # off the beat grid: a bass note or a stab
                if self._govern(k, t, sc):
                    out.append((k, s))
        for k, s in out:
            if k in self.hits_total:
                self.hits_total[k] += 1
        return out

    def _grid(self, now, hits):
        """When the kick is four-on-the-floor and the tempo is locked, the lights pump on the grid itself --
        every beat, landing on time (sent a touch early so the bulbs light ON the beat). Stops by itself
        within a couple of beats when the kick drops out (breakdowns still happen)."""
        bt = self.beat
        if bt is None or bt.period is None or self.midi_recent.get('kick', -10.0) > now - 2.0:
            self.grid_on = False
            return []
        for t, k, s, src, sc in hits:
            if k == 'kick' and src == 'audio' and bt.near(t, 1, 0.08):
                self.beat_marks.add(round(bt.phase(t)))
                self.kick_str.append(s)
        b = bt.phase(now)
        cur = int(math.floor(b))
        if self.beat_seen is None:
            self.beat_seen = cur
        while self.beat_seen < cur - 1:                        # a beat has fully passed: did it have a kick?
            self.beat_seen += 1
            self.beat_hist.append(self.beat_seen in self.beat_marks)
            self.beat_marks = {x for x in self.beat_marks if x > self.beat_seen - 4}
        if self.beat_seen > cur:
            self.beat_seen = cur
        on = sum(self.beat_hist) >= 5 and bt.conf > 0.35 and self.beat_hist[-1] if len(self.beat_hist) >= 6 else False
        on = on or (self.grid_on and sum(list(self.beat_hist)[-2:]) >= 1 and bt.conf > 0.25)
        self.grid_on = bool(on)
        if not self.grid_on:
            self.grid_next = None
            return []
        lead = float(self.hub.state['calibration'].get('lamp_delay', 60.0)) / 1000.0 + 0.02
        nb = int(math.floor(bt.phase(now + lead)))
        if self.grid_next is None:
            self.grid_next = nb + 1
        out = []
        if nb >= self.grid_next:
            self.grid_next = nb + 1
            st = (sum(self.kick_str) / len(self.kick_str)) if self.kick_str else 0.9
            out.append(('kick', max(0.7, st)))
        return out

    def heard_clock(self, now):
        """(beats, bpm) from the tempo the hub hears, when it is sure of it"""
        bt = self.beat
        if bt is None or bt.bpm is None or bt.conf < 0.45:
            return None
        b = bt.phase(now)
        if b is None:                                          # tempo heard, grid not placed yet
            return None
        return b, bt.bpm

    def tempo_info(self):
        bt = self.beat
        if bt is None or bt.bpm is None:
            return None
        return dict(bpm=round(bt.bpm, 1), conf=round(bt.conf, 2), grid=self.grid_on)

    def _govern(self, k, t, score):
        """Busy music (bass lines, synth stabs, Evil Pet grains) can sound like drums many times a second.
        Only the clearest hits light the room: at most LIGHT_RATE a second, the strongest ones of the last
        few seconds, and never closer together than LIGHT_GAP. The lights stay punchy instead of smeared."""
        c = self.cands.setdefault(k, [])
        c.append((t, score))
        while c and t - c[0][0] > 4.0:
            del c[0]
        if t - self.lit_t.get(k, -10.0) < LIGHT_GAP[k]:
            return False
        allow = LIGHT_RATE[k] * 4.0
        if len(c) > allow:
            ranked = sorted((x[1] for x in c), reverse=True)
            if score < ranked[int(allow) - 1]:
                return False
        self.lit_t[k] = t
        return True

    def _check(self, now):
        """Every 2 s: is real sound arriving? Says so on the desk and in the Terminal / hub_log.txt."""
        if now - self.check_t < 2.0:
            return
        span = now - self.check_t
        self.check_t = now
        with self.lock:
            pk, self.peak_acc = self.peak_acc, 0.0
        if self.stream is None:
            return
        self.peak = pk
        db = 20.0 * math.log10(pk) if pk > 0 else -999.0
        self.zero_for = self.zero_for + span if pk == 0.0 else 0.0
        if self.blocks == 0:
            hear = 'no sound arriving from the sound card at all'
        elif self.zero_for >= 4.0:
            hear = ('hearing PURE SILENCE -- macOS is probably blocking the microphone for Terminal: System Settings > '
                    'Privacy & Security > Microphone > turn Terminal on, then quit Terminal and start the hub again')
        elif pk == 0.0:
            hear = 'silent so far (checking...)'
        elif db < -60.0:
            hear = 'very quiet (peak %.0f dB) -- is the gear playing? Turn up the Scarlett 1+2 gain or the Evil Pet output' % db
        else:
            hear = 'sound OK (peak %.0f dB)' % db
        base = getattr(self, 'base_status', self.status)
        self.status = base + ' -- ' + hear
        if hear.split(' (')[0] != self.hear.split(' (')[0]:
            print('Audio: ' + hear, flush=True)
        self.hear = hear
        if now - self.report_t >= 30.0:
            self.report_t = now
            print('Audio: %s | hits so far (lit / heard): kick %d/%d, snare %d/%d, hats %d/%d' % (
                hear, self.hits_total['kick'], self.heard.get('kick', 0), self.hits_total['snare'],
                self.heard.get('snare', 0), self.hits_total['hats'], self.heard.get('hats', 0)), flush=True)

    def _tempo(self, now):
        """BPM from the clock ticks of the last ~2 seconds (steady to a tenth of a BPM)"""
        if now - self.clk_t > 0.5:
            self.tick_hist = []
            self.clk_bpm = None
            return
        h = self.tick_hist
        if not h or h[-1][1] != self.ticks:
            h.append((now, self.ticks))
        while len(h) > 2 and now - h[0][0] > 2.0:
            del h[0]
        if len(h) >= 2 and h[-1][0] - h[0][0] > 0.5:
            bpm = (h[-1][1] - h[0][1]) / 24.0 / (h[-1][0] - h[0][0]) * 60.0
            if 30.0 <= bpm <= 300.0:
                self.clk_bpm = bpm if self.clk_bpm is None else self.clk_bpm + (bpm - self.clk_bpm) * 0.1

    def clock(self, now):
        """(beats, bpm) from the gear's MIDI clock while it's running, else None"""
        if self.clk_bpm is None or now - self.clk_t > 0.5:
            return None
        return self.ticks / 24.0, self.clk_bpm

    def clock_info(self):
        return None if self.clk_bpm is None else dict(bpm=round(self.clk_bpm, 1), running=self.clk_run)

    def notes_seen(self):
        now = time.time()
        return {str(ch): dict(n=v[0], ago=round(now - v[1], 1)) for ch, v in sorted(self.seen.items())}

    def features(self):
        if self.an is None:
            return None
        with self.lock:
            return dict(level=dict(self.an.level), bright=self.an.bright, silent=self.an.silent)
