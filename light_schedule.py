#!/usr/bin/env python3
# =============================================================================
# LIGHT SCHEDULE -- the daily rhythm (Nov 9): bed ~11 pm, up at 8 am, every day.
#
#   21:30  wind-down: lamps fade to warm candle light (2200 K, 35%) over 10 min
#   23:00  night light: deep red, 12%; the moving heads park and power off
#   08:40  morning: a 20-minute fade from deep night blue up to a soft sky blue, full at 09:00 (Nov 10)
#
# It never interrupts a show: if the hub is running AND hearing sound, that step is
# skipped (and logged). Otherwise it stops the hub / fades first, like the Siri looks.
# Change times or switch it off in light_schedule.json (copy the DEFAULTS below).
# Runs inside rig_control (always on).  Log: /tmp/light_schedule.log
# =============================================================================
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, 'light_schedule.json')
LOG = '/tmp/light_schedule.log'
DEFAULTS = {'enabled': True, 'winddown': '21:30', 'night': '23:00', 'sunrise': '08:40', 'sunrise_min': 20}
STATE = {'done': {}, 'last': 'starting', 'running': None}


def log(msg):
    STATE['last'] = msg
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


def settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def _ramp(lights, steps):
    """steps = [(brightness %, mirek or None, xy or None, seconds to get there)]"""
    for bri, mirek, xy, secs in steps:
        body = {'on': {'on': True}, 'dimming': {'brightness': float(bri)},
                'dynamics': {'duration': int(max(0.4, secs - 0.5) * 1000)}}
        if mirek:
            body['color_temperature'] = {'mirek': int(mirek)}
        if xy:
            body['color'] = {'xy': {'x': xy[0], 'y': xy[1]}}
        lights(body)
        time.sleep(secs)


def winddown(lights):
    _ramp(lights, [(45, 400, None, 3), (40, 430, None, 300), (35, 454, None, 300)])


def night(lights, heads_off):
    _ramp(lights, [(16, None, (0.69, 0.30), 60), (12, None, (0.69, 0.30), 120)])   # Nov 10: deep red ~12% (3% was too dark), not purple
    heads_off()


def sunrise(lights, minutes):
    secs = minutes * 60.0
    # deep night blue -> dawn blue -> soft sky blue (Michael, Nov 10: soft blue mornings, full at 9 am)
    _ramp(lights, [(1, None, (0.16, 0.10), 2), (12, None, (0.17, 0.15), secs * 0.30), (35, None, (0.19, 0.22), secs * 0.35),
                   (60, None, (0.22, 0.27), secs * 0.35)])


def _fire(name, s, lights, stop_all, heads_off, hub_busy):
    if hub_busy():
        log('%s skipped -- the hub is running with sound (show / music on)' % name)
        return
    log('%s starting' % name)
    STATE['running'] = name
    try:
        stop_all()
        if name == 'winddown':
            winddown(lights)
        elif name == 'night':
            night(lights, heads_off)
        elif name == 'sunrise':
            sunrise(lights, s['sunrise_min'])
        log('%s done' % name)
    except Exception as e:
        log('%s failed: %s: %s' % (name, e.__class__.__name__, e))
    finally:
        STATE['running'] = None


def watch(lights, stop_all, heads_off, hub_busy):
    log('schedule started')
    while True:
        try:
            s = settings()
            if s['enabled'] and not STATE['running']:
                now = time.localtime()
                hm, today = time.strftime('%H:%M', now), time.strftime('%Y-%m-%d', now)
                for name in ('sunrise', 'winddown', 'night'):
                    at = s[name]
                    # fire within 5 min of the time (survives a short sleep / restart), once a day
                    h, m = map(int, at.split(':'))
                    late = (now.tm_hour * 60 + now.tm_min) - (h * 60 + m)
                    if 0 <= late < 5 and STATE['done'].get(name) != today:
                        STATE['done'][name] = today
                        threading.Thread(target=_fire, args=(name, s, lights, stop_all, heads_off, hub_busy),
                                         daemon=True).start()
                        break
        except Exception as e:
            STATE['last'] = 'check failed: %s' % e.__class__.__name__
        time.sleep(20)


def start(lights, stop_all, heads_off, hub_busy):
    threading.Thread(target=watch, args=(lights, stop_all, heads_off, hub_busy),
                     name='light-schedule', daemon=True).start()


def status():
    s = settings()
    return dict(enabled=s['enabled'], winddown=s['winddown'], night=s['night'],
                sunrise='%s (bright at +%d min)' % (s['sunrise'], s['sunrise_min']),
                running=STATE['running'], last=STATE['last'])
