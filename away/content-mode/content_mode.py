"""CONTENT MODE -- the Mac side (away loop W5, Nov 17; rules approved by Michael in AGENTS.md, Nov 15).

What it is: short-form filming only. Voice-confirmed ("Jarvis, content mode confirmed"), switches itself off after
5 minutes, re-armable ("content mode again"), blocked by guest mode. While it's on: strobe + white any time, and the
heads change colour every beat (the show's "one colour every 2 bars" rule is skipped).
What it never does: lift any limit at the Pi node (the studio-seat no-go zone and the eye-level limits live there --
see NODE-PLAN.txt), speak on its own (Jarvis talks only when spoken to), or touch the fan / spots / power.

Where it plugs in (apply_patches.py installs it):
  rig_control ask_jarvis rig(): 'content:{json}' -> rig_side()   (returns the sentence Jarvis says)
  rig_control apply():          any other look ends content mode first -> look_changed()
  rig_control start-up:         boot() -- content mode never survives a restart
Settings (not secret, edit by hand): content_mode.json next to rig_control.py. State: content_state.json.
Nothing here blocks the web server: the lights work goes on Jarvis's job queue; the 5-minute timer is one small
daemon thread that checks once a second.
"""
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_MINUTES = 5                                   # AGENTS.md: auto-off after 5 min -- the file can't make it longer
DEFAULTS = {'minutes': 5, 'rearm_grace_minutes': 10, 'strobe': 'always', 'flash_beats': 1, 'white': True,
            'studio_seat': None}
STROBES = ('always', 'flash', 'phrase', 'drop', 'beat')
OFF_SETTINGS = [('dmx_strobe', 'off'), ('flash_beats', 8), ('content_white', False)]   # back to the normal rules,
# strobe first: a hub that wasn't restarted refuses content_white, and that must never keep the strobe on


def load_config(folder=HERE):
    """content_mode.json merged over the defaults, with every number kept inside the safe range."""
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(folder, 'content_mode.json')) as f:
            got = json.load(f)
        if isinstance(got, dict):
            cfg.update({k: v for k, v in got.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    try:
        cfg['minutes'] = min(MAX_MINUTES, max(1.0, float(cfg['minutes'])))
    except (TypeError, ValueError):
        cfg['minutes'] = MAX_MINUTES
    try:
        cfg['rearm_grace_minutes'] = min(30.0, max(0.0, float(cfg['rearm_grace_minutes'])))
    except (TypeError, ValueError):
        cfg['rearm_grace_minutes'] = DEFAULTS['rearm_grace_minutes']
    if cfg['strobe'] not in STROBES:
        cfg['strobe'] = 'always'
    try:
        cfg['flash_beats'] = min(8, max(1, int(cfg['flash_beats'])))
    except (TypeError, ValueError):
        cfg['flash_beats'] = 1
    cfg['white'] = cfg['white'] not in (False, 'false', 'off', 0, '0', None)
    return cfg


def on_settings(cfg):
    """The hub settings content mode sets (after the normal light show has started)."""
    return [('dmx_strobe', cfg['strobe']), ('flash_beats', cfg['flash_beats']), ('content_white', bool(cfg['white']))]


def _mins(sec):
    sec = int(round(sec))
    m, s = divmod(sec, 60)
    return ('%d minute%s' % (m, '' if m == 1 else 's') if m else '') + (' %d seconds' % s if s else '') or '0 seconds'


class ContentMode:
    """The on/off + 5-minute timer, with a clock you can swap for tests."""

    def __init__(self, folder=HERE, clock=time.time):
        self.folder, self.clock = folder, clock
        self.path = os.path.join(folder, 'content_state.json')
        self.lock = threading.Lock()
        self.until = 0.0                          # when it switches itself off (0 = off)
        self.expired_at = 0.0                     # last time the TIMER ended it (re-arm without 'confirmed' only then)
        try:
            with open(self.path) as f:
                st = json.load(f)
            self.until, self.expired_at = float(st.get('until', 0) or 0), float(st.get('expired_at', 0) or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def cfg(self):
        return load_config(self.folder)

    def _save(self):
        try:
            with open(self.path, 'w') as f:
                json.dump({'until': self.until, 'expired_at': self.expired_at,
                           'note': 'content mode state (away/content-mode). until 0 = off.'}, f)
        except OSError:
            pass

    def active(self, now=None):
        return self.until > 0 and (self.clock() if now is None else now) < self.until

    def remaining(self, now=None):
        return max(0.0, self.until - (self.clock() if now is None else now)) if self.until else 0.0

    def decide(self, op, confirmed, guest, now):
        """-> (verb, sentence). verb: arm | extend | end | refuse | none. Changes nothing by itself."""
        cfg = self.cfg()
        mins = _mins(cfg['minutes'] * 60)
        if op == 'status':
            if self.active(now):
                return 'none', 'Content mode is on, %s left.' % _mins(self.remaining(now))
            return 'none', 'Content mode is off.'
        if op == 'off':
            if self.active(now):
                return 'end', 'Content mode off. Strobe and colours back to the normal rules.'
            return 'none', 'Content mode is already off.'
        if op not in ('on', 'again'):
            return 'refuse', "I didn't catch that content mode command."
        if guest:
            return 'refuse', 'Guest mode is on, so content mode stays off.'
        if op == 'again' and self.active(now):
            return 'extend', 'Content mode: %s more, from now.' % mins
        grace = cfg['rearm_grace_minutes'] * 60
        recent = op == 'again' and self.expired_at > 0 and 0 <= now - self.expired_at <= grace
        if not confirmed and not recent:
            return 'refuse', ("Content mode strobes and goes white. Room empty except you at the desk? "
                              "Then say 'content mode confirmed'.")
        return 'arm', ('Content mode on for %s. Strobe and white any time; the studio seat stays off limits. '
                       "Say 'content mode again' for more." % mins)

    def arm(self, now):
        with self.lock:
            self.until = now + self.cfg()['minutes'] * 60
            self._save()

    def end(self, now, expired):
        with self.lock:
            self.until = 0.0
            self.expired_at = now if expired else 0.0
            self._save()

    def due(self, now):
        """True once when the timer has run out."""
        return self.until > 0 and now >= self.until


_CM = None


def get(folder=HERE, clock=time.time):
    global _CM
    if _CM is None:
        _CM = ContentMode(folder, clock)
    return _CM


def start(rc, cm):
    """Runs on Jarvis's job queue: the normal light show, then the content-mode settings on top."""
    if rc.STATE.get('guest') or not cm.active():
        return                                    # guest mode came on, or it was switched off, while queued
    with rc.LOCK:
        rc.STATE.update(busy=True, last_error=None)
        try:
            rc.show_full()                        # heads on, music hub, rainbow, dmx on (flash, 2 bars)
            for k, v in on_settings(cm.cfg()):
                rc.hub_setting(k, v)
            rc.STATE.update(look='content', since=time.strftime('%H:%M'))
        except Exception as e:
            rc.STATE['last_error'] = 'content: %s' % e
        finally:
            rc.STATE['busy'] = False


def restore(rc):
    """Back to the normal rules: no white, no strobe, one colour every 2 bars. Heads keep dancing."""
    try:
        if not rc.hub_up():
            return 'hub off'
    except Exception as e:
        rc.STATE['last_error'] = 'content restore: %s' % e
        return 'failed'
    failed = []
    for k, v in OFF_SETTINGS:                     # each on its own: one refusal never skips the others
        try:
            rc.hub_setting(k, v)
        except Exception as e:
            failed.append(k)
            rc.STATE['last_error'] = 'content restore %s: %s' % (k, e)
    if rc.STATE.get('look') == 'content':
        rc.STATE.update(look='music', since=time.strftime('%H:%M'))
    return 'failed' if failed else 'restored'


def tick(rc, cm, now=None):
    """One check of the timer (the thread calls this once a second)."""
    now = cm.clock() if now is None else now
    if cm.due(now):
        cm.end(now, expired=True)
        return restore(rc)
    return None


def _ensure_timer(rc, cm):
    if getattr(cm, 'thread', None) and cm.thread.is_alive():
        return

    def loop():
        while True:
            time.sleep(1.0)
            try:
                tick(rc, cm)
            except Exception:
                pass
    cm.thread = threading.Thread(target=loop, name='content-mode-timer', daemon=True)
    cm.thread.start()


def rig_side(p, rc, cm=None, timer=True):
    """'content:{"op": "on", "confirmed": true}' from Jarvis -> what Jarvis says. Lights work is queued."""
    cm = cm or get()
    try:
        v = json.loads(p.split(':', 1)[1])
        op, confirmed = str(v.get('op')), bool(v.get('confirmed'))
    except (ValueError, IndexError, AttributeError):
        return "I didn't catch that content mode command."
    now = cm.clock()
    verb, said = cm.decide(op, confirmed, bool(rc.STATE.get('guest')), now)
    if verb == 'arm':
        cm.arm(now)
        rc.JOBS.put(lambda: start(rc, cm))
    elif verb == 'extend':
        cm.arm(now)
    elif verb == 'end':
        cm.end(now, expired=False)
        rc.JOBS.put(lambda: restore(rc))
    if verb in ('arm', 'extend') and timer:
        _ensure_timer(rc, cm)
    return said


def look_changed(rc, look, cm=None):
    """Called at the top of rig_control.apply(): any other look ends content mode BEFORE it runs."""
    cm = cm or get()
    if look == 'content' or not cm.active():
        return None
    cm.end(cm.clock(), expired=False)
    return restore(rc)


def boot(rc, cm=None, wait=True):
    """rig_control start-up: if it stopped while content mode was on, switch it off cleanly (needs 'confirmed'
    again). The hub may still be starting, so the restore runs in the background."""
    cm = cm or get()
    if not cm.until:
        return None
    cm.end(cm.clock(), expired=False)
    if wait:
        def later():
            for _ in range(30):
                if restore(rc) != 'hub off':
                    return
                time.sleep(2)
        threading.Thread(target=later, name='content-mode-boot', daemon=True).start()
        return 'ending'
    return restore(rc)
