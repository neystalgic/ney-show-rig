#!/usr/bin/env python3
# =============================================================================
# HEY JARVIS -- the real one (Nov 13). No Siri: say "Hey Jarvis", hear a chime, say what you want,
# Jarvis answers in his own voice from the Mac's speakers.
#   wake word : openWakeWord "hey_jarvis" model, on this Mac (free, offline)
#   your words: Whisper (faster-whisper, base.en) on this Mac (free, offline)
#   the brain : rig_control's /ask (the same Jarvis rules + local model Siri uses)
#   his voice : macOS 'say' with a British voice (jarvis.json "voice", default Daniel)
# Mic: the MacBook's own microphone (works docked AND on the couch); falls back to the default input.
# Nothing is recorded to disk; audio never leaves the Mac. Log (text only): /tmp/jarvis_listen.log
# Started by rig_control through "Ney Jarvis.app" (that app holds the microphone permission).
# =============================================================================
import json, os, queue, subprocess, sys, threading, time, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
RATE, BLOCK = 16000, 1280                      # 80 ms frames (what openWakeWord expects)
WAKE_THRESHOLD = 0.5
VOCAB = ('Jarvis. Purple, rainbow, movie night, light show, safe show, goodnight, night light, guest mode, '
         'couch mode, UV stars, heads off, lights off, status, log my weight, no dimming until midnight.')


def log(msg):
    try:
        with open('/tmp/jarvis_listen.log', 'a') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


def settings():
    s = {'voice': 'Daniel', 'whisper': 'base.en', 'mic': 'MacBook Pro Microphone', 'chime': 'chime1_rise.wav'}
    try:
        with open(os.path.join(HERE, 'jarvis.json')) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def pick_mic(sd, want):
    for i, d in enumerate(sd.query_devices()):
        if d['max_input_channels'] > 0 and want.lower() in d['name'].lower():
            return i, d['name']
    i = sd.default.device[0]
    return i, sd.query_devices(i)['name'] if i is not None and i >= 0 else 'default'


def my_chime():
    """Michael's own sound wins: drop a file named my_chime.wav / .aif / .aiff / .mp3 / .m4a into jarvis/sounds."""
    for ext in ('wav', 'aif', 'aiff', 'mp3', 'm4a'):
        p = os.path.join(HERE, 'sounds', 'my_chime.' + ext)
        if os.path.isfile(p):
            return p
    return None


def ask_rig(text):
    with open(os.path.join(RIG, 'rig_control.token')) as f:
        tok = f.read().strip()
    req = urllib.request.Request('http://127.0.0.1:7040/ask', json.dumps({'text': text}).encode(),
                                 {'Content-Type': 'application/json', 'X-Token': tok})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode('utf-8', 'replace')


class Ears:
    """Pure logic for 'listen until the sentence ends' (testable without a mic)."""
    def __init__(self, rate=RATE, block=BLOCK, max_s=7.0, wait_s=4.0, tail_s=0.8):
        self.rate, self.block = rate, block
        self.max_n, self.wait_n, self.tail_n = (int(x * rate / block) for x in (max_s, wait_s, tail_s))
        self.reset()

    def reset(self):
        self.frames, self.started, self.quiet, self.n = [], False, 0, 0
        self.floor = None

    def feed(self, frame):
        """Returns None while listening, 'done' with speech, 'nothing' if no speech came."""
        rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)) + 1e-9)
        self.n += 1
        if self.floor is None:
            self.floor = rms
        speaking = rms > max(0.012, self.floor * 3.0)
        if not speaking and not self.started:
            self.floor = 0.9 * self.floor + 0.1 * rms
        if speaking:
            self.started, self.quiet = True, 0
        elif self.started:
            self.quiet += 1
        if self.started:
            self.frames.append(frame)
        if self.started and (self.quiet >= self.tail_n or self.n >= self.max_n):
            return 'done'
        if not self.started and self.n >= self.wait_n:
            return 'nothing'
        return None

    def audio(self):
        return np.concatenate(self.frames).astype(np.float32) / 32768.0 if self.frames else np.zeros(0, np.float32)


def main():
    import sounddevice as sd
    from openwakeword.model import Model
    import openwakeword.utils
    from faster_whisper import WhisperModel

    s = settings()
    try:
        openwakeword.utils.download_models(model_names=['hey_jarvis'])   # first run only (small files)
    except Exception as e:
        log('wake model download: %s' % e)
    wake = Model(wakeword_models=['hey_jarvis'], inference_framework='onnx')
    stt = WhisperModel(s['whisper'], device='cpu', compute_type='int8')
    dev, name = pick_mic(sd, s['mic'])
    log('listening on "%s" (wake word: hey jarvis)' % name)

    q = queue.Queue()
    speaking = threading.Event()

    def cb(indata, frames, t, status):
        if not speaking.is_set():
            q.put(indata[:, 0].copy())

    def say(text):
        speaking.set()
        try:
            subprocess.run(['/usr/bin/say', '-v', s['voice'], text], timeout=60)
        finally:
            time.sleep(0.3)
            with q.mutex:
                q.queue.clear()
            wake.reset()
            speaking.clear()

    ears, mode, last_wake = Ears(), 'wake', 0.0
    with sd.InputStream(device=dev, channels=1, samplerate=RATE, blocksize=BLOCK, dtype='int16', callback=cb):
        while True:
            frame = q.get()
            if mode == 'wake':
                score = max(wake.predict(frame).values())
                if score >= WAKE_THRESHOLD and time.time() - last_wake > 2.0:
                    last_wake = time.time()
                    log('wake (%.2f)' % score)
                    ch = my_chime() or os.path.join(HERE, 'sounds', s.get('chime') or '')
                    subprocess.Popen(['/usr/bin/afplay', ch if os.path.isfile(ch) else '/System/Library/Sounds/Tink.aiff'])
                    ears.reset()
                    mode = 'hear'
                continue
            r = ears.feed(frame)
            if r is None:
                continue
            mode = 'wake'
            if r == 'nothing':
                log('no command after the wake word')
                continue
            segs, _ = stt.transcribe(ears.audio(), language='en', beam_size=1, initial_prompt=VOCAB)
            text = ' '.join(x.text for x in segs).strip()
            log('heard: %r' % text)
            if not text:
                continue
            try:
                reply = ask_rig(text)
            except Exception as e:
                reply = "I can't reach the rig right now."
                log('ask failed: %s' % e)
            log('reply: %r' % reply)
            threading.Thread(target=say, args=(reply,), daemon=True).start()


if __name__ == '__main__':
    main()
