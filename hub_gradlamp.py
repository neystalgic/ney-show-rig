# =============================================================================
# HUE HUB -- the Play floor lamp as a GRADIENT (several colours at once)
#
# The Hue Bridge only streams this lamp as ONE colour in an entertainment area
# (all 7 zones share one channel, whatever the area type). Through the normal
# Hue controls it can show a 5-point gradient, so it sits OUTSIDE the show's
# entertainment area ("Show area") and the hub sends it its gradient directly,
# twice a second, with the lamp fading smoothly between updates.
#
#   lava mode    the wall's rainbow, bottom to top, centred on the room's colour
#   other modes  the room's lamp colours, left to right, as a gradient
#
# Setting 'grad_lamp' = the lamp's name (default "Hue Play floor lamp large 1"),
# '' switches this off.  Its brightness cap (lamp cap) still applies.
# =============================================================================

import threading
import time

try:
    import hue_stream as hs
except Exception:
    hs = None

SEND_EVERY = 0.5          # seconds between gradient updates (the bridge allows ~10 commands a second)


class GradLamp:
    def __init__(self, hub):
        self.hub = hub
        self.rid = None
        self.name = None
        self.status = 'off'
        self.want = None              # the newest gradient to send: (points, brightness, on)
        self.every = SEND_EVERY       # seconds between updates (faster in sync mode)
        self.sent = None
        self.lock = threading.Lock()
        self.run = True
        self.th = threading.Thread(target=self._loop, name='hub-gradlamp', daemon=True)
        self.th.start()

    def settings(self):
        return self.hub.state['settings']

    def _find(self):
        name = self.settings().get('grad_lamp', 'Hue Play floor lamp large 1')
        if not name or hs is None or not getattr(self.hub, 'cfg', None):
            return None
        for l in hs.v2(self.hub.cfg, 'light').get('data', []):
            if l.get('metadata', {}).get('name') == name and l.get('gradient'):
                self.name = name
                return l['id']
        self.status = 'no gradient lamp called "%s"' % name
        return None

    def update(self, colours, brightness, on=True):
        """colours: up to 5 (r, g, b) 0-1, bottom to top. brightness 0-1."""
        pts = []
        for c in colours[:5]:
            x, y, _ = hs.rgb_to_xyb(*c) if hs is not None else (0.3, 0.3, 1)
            pts.append((round(x, 4), round(y, 4)))
        with self.lock:
            self.want = (tuple(pts), round(max(0.0, min(1.0, brightness)) * 100.0, 1), bool(on))

    def _loop(self):
        last = 0.0
        while self.run:
            time.sleep(0.05)
            if time.time() - last < self.every:
                continue
            try:
                if self.rid is None:
                    self.rid = self._find()
                    if self.rid is None:
                        time.sleep(10.0)
                        continue
                with self.lock:
                    want = self.want
                if want is None or want == self.sent:
                    continue
                pts, bri, on = want
                body = dict(on=dict(on=on), dimming=dict(brightness=max(1.0, bri)),
                            gradient=dict(points=[dict(color=dict(xy=dict(x=x, y=y))) for x, y in pts],
                                          mode='interpolated_palette'),
                            dynamics=dict(duration=int(self.every * 1000)))
                if not on:
                    body = dict(on=dict(on=False), dynamics=dict(duration=300))
                hs.v2(self.hub.cfg, 'light/%s' % self.rid, 'PUT', body)
                self.sent = want
                last = time.time()
                self.status = 'gradient to "%s"' % self.name
            except Exception as e:
                self.status = 'gradient lamp: %s' % e
                last = time.time() + 2.0

    def stop(self):
        self.run = False
