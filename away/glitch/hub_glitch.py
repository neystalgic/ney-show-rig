#!/usr/bin/env python3
# =============================================================================
# GLITCH DETECTOR (Nov 18, Michael: "I want the machines to react to the glitches in my music to give off the
# impression of sentience -- a feeling of wonder, 'how did he do that'").
#
# Fed one analysis frame at a time (hub_audio.Analyzer, ~10 ms frames) with the loudness (dB, no auto-gain) of
# the whole mix and of the four bands, plus how noise-like the spectrum is. It notices four kinds of glitch:
#   gap      the music drops out (25 dB+ under its last second) -- live while it lasts, ends when sound returns
#   stutter  3+ hard retriggers less than 0.15 s apart at an even rate (a stutter edit, a beat repeat)
#   crush    a burst of noise: the spectrum goes flat (bitcrush, white-noise hit) and the highs jump 10 dB+
#   jump     every band leaps or falls 10 dB+ at the same moment (a hard cut, a tape stop, a re-pitch)
# 'crush' and 'jump' are single events (at most one every GAP_S); 'gap' and 'stutter' are states with a
# start + an end event. Pure: no audio device, no threads -- tested on synthetic frames (test_glitch.py).
# =============================================================================
import collections
import math

BANDS4 = ('sub', 'low', 'mid', 'high')
GAP_DB = 25.0          # this far under the last second's loudness = a dropout
LIVE_DB = -50.0        # ...only if the music was really playing
STUT_JUMP = 9.0        # a retrigger: the whole mix jumps this many dB in a frame or two
STUT_MAX = 0.15        # ...this close to the previous one (seconds)
STUT_N = 3             # ...this many in a row, at an even rate
CRUSH_FLAT = 0.45      # spectral flatness (0 tonal .. 1 white noise)
CRUSH_DB = 10.0
JUMP_DB = 10.0
EVENT_GAP_S = 1.5      # single events: at most one per this many seconds (a glitch stays special)


class Glitch:
    def __init__(self):
        self.t = 0.0
        self.ctx = None                      # the mix's loudness over the last ~second (dB, slow average)
        self.hctx = None                     # the highs over the last ~2 s
        self.hist = collections.deque(maxlen=4)  # recent frames: (t, total_db, {band: db})
        self.gap_since = None
        self.gap_ref = None
        self.gap_end = -10.0
        self.retrig = []                     # times of recent retriggers
        self.stut_on = False
        self.stut_last = -10.0
        self.crush_run = 0
        self.last_event = -10.0
        self.events = []                     # (t, kind, strength, dur)
        self.counts = collections.Counter()

    # -- state for the lights ------------------------------------------------------------------------------
    @property
    def gap(self):
        return self.gap_since is not None and self.t - self.gap_since >= 0.02

    @property
    def stutter(self):
        return self.stut_on

    def take(self):
        e, self.events = self.events, []
        return e

    def _event(self, kind, strength, dur=0.0, single=True):
        if single and self.t - self.last_event < EVENT_GAP_S:
            return
        if single:
            self.last_event = self.t
        self.events.append((self.t, kind, max(0.0, min(1.0, strength)), dur))
        self.counts[kind] += 1

    # -- one analysis frame ---------------------------------------------------------------------------------
    def frame(self, t, total_db, bands, flatness):
        dt = t - self.t if self.t else 0.01
        self.t = t
        if self.ctx is None:
            self.ctx, self.hctx = total_db, bands.get('high', -120.0)
        prev = self.hist[-1] if self.hist else None
        prev2 = self.hist[-2] if len(self.hist) >= 2 else prev

        # GAP: a sudden dropout while the music was playing
        if self.gap_since is None:
            if self.ctx > LIVE_DB and total_db < self.ctx - GAP_DB:
                self.gap_since, self.gap_ref = t, self.ctx
        elif total_db > self.gap_ref - 12.0:          # the sound is back
            dur = t - self.gap_since
            self.gap_since = None
            self.gap_end = t
            if dur >= 0.02:
                self._event('gap', min(1.0, dur / 0.5), dur, single=False)
        elif t - self.gap_since > 3.0:                # that's a song ending / a real pause, not a glitch
            self.gap_since = None
            self.ctx = total_db

        # STUTTER: hard retriggers in quick, even succession
        if prev is not None and self.gap_since is None:
            jump = total_db - min(prev[1], prev2[1])
            if jump >= STUT_JUMP and (not self.retrig or t - self.retrig[-1] > 0.03):
                self.retrig = [x for x in self.retrig if t - x < 1.0] + [t]
                ivs = [b - a for a, b in zip(self.retrig, self.retrig[1:])][-(STUT_N - 1):]
                even = len(ivs) >= STUT_N - 1 and all(i <= STUT_MAX for i in ivs) and \
                    max(ivs) - min(ivs) <= 0.35 * max(ivs)
                if even:
                    self.stut_last = t
                    if not self.stut_on:
                        self.stut_on = True
                        self._event('stutter', min(1.0, 0.05 / max(0.02, sum(ivs) / len(ivs))), single=False)
        if self.stut_on and self.retrig and t - self.retrig[-1] > 2.5 * max(0.05, self._rate()):
            self.stut_on = False
            self._event('stutter_end', 0.0, t - self.stut_last, single=False)

        # CRUSH: a burst of noise
        hi = bands.get('high', -120.0)
        if flatness >= CRUSH_FLAT and hi >= self.hctx + CRUSH_DB and total_db > LIVE_DB:
            self.crush_run += 1
            if self.crush_run == 3:
                self._event('crush', (hi - self.hctx) / 25.0)
        else:
            self.crush_run = 0

        # JUMP: every band moves 10 dB+ together (both ways)
        if prev2 is not None and self.gap_since is None and not self.stut_on and t - self.gap_end > 0.3:
            d = [bands.get(k, -120.0) - prev2[2].get(k, -120.0) for k in BANDS4]
            if all(x >= JUMP_DB for x in d) or all(x <= -JUMP_DB for x in d):
                if min(total_db, prev2[1]) > LIVE_DB:   # both sides playing (a dropout / a start is not a jump)
                    self._event('jump', min(abs(x) for x in d) / 25.0)

        # slow context (the gap / the stutter don't drag it down)
        if self.gap_since is None:
            k = 1.0 - math.exp(-dt / 0.6)
            self.ctx += (total_db - self.ctx) * k
            self.hctx += (hi - self.hctx) * (1.0 - math.exp(-dt / 2.0))
        self.hist.append((t, total_db, dict(bands)))

    def _rate(self):
        ivs = [b - a for a, b in zip(self.retrig, self.retrig[1:])][-4:]
        return sum(ivs) / len(ivs) if ivs else 0.1

    def status(self):
        return dict(gap=self.gap, stutter=self.stutter, counts=dict(self.counts))
