# MIDI Check: listens to every MIDI input on this Mac for 20 seconds and writes
# what arrived to midi_check.txt (clock + tempo, start/stop, pattern changes, notes, knobs).
# Safe to run while the Hue Hub is running: it only listens, never sends.
import time, collections, mido, datetime, os
SECONDS = 20
here = os.path.dirname(os.path.abspath(__file__))
names = mido.get_input_names()
outs = mido.get_output_names()
stats = {}
ports = []
def make_cb(name):
    s = stats[name] = dict(clock=[], start=0, stop=0, cont=0, pc=collections.Counter(),
                           notes=collections.Counter(), cc=collections.Counter(), other=collections.Counter())
    def cb(msg):
        t = time.time()
        if msg.type == 'clock': s['clock'].append(t)
        elif msg.type == 'start': s['start'] += 1
        elif msg.type == 'stop': s['stop'] += 1
        elif msg.type == 'continue': s['cont'] += 1
        elif msg.type == 'program_change': s['pc'][(msg.channel + 1, msg.program)] += 1
        elif msg.type == 'note_on' and msg.velocity > 0: s['notes'][msg.channel + 1] += 1
        elif msg.type == 'control_change': s['cc'][msg.channel + 1] += 1
        elif msg.type not in ('note_off', 'note_on', 'active_sensing'): s['other'][msg.type] += 1
    return cb
print('Listening to %d MIDI inputs for %d seconds... play your gear now.' % (len(names), SECONDS))
for n in names:
    try: ports.append(mido.open_input(n, callback=make_cb(n)))
    except Exception as e: stats[n] = dict(error=str(e))
time.sleep(SECONDS)
for p in ports: p.close()
lines = ['MIDI CHECK  %s  (%d seconds)' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), SECONDS), '',
         'Inputs:  ' + ' | '.join(names), 'Outputs: ' + ' | '.join(outs), '']
for n, s in stats.items():
    lines.append('== ' + n)
    if 'error' in s: lines.append('   could not open: ' + s['error']); continue
    c = s['clock']
    if len(c) > 48:
        dt = (c[-1] - c[0]) / (len(c) - 1)
        lines.append('   CLOCK: %d ticks, about %.1f BPM, steadiness +/- %.1f ms' % (len(c), 60.0 / (24 * dt),
                     1000 * (sum(((c[i+1]-c[i]) - dt) ** 2 for i in range(len(c)-1)) / (len(c)-1)) ** 0.5))
    else:
        lines.append('   CLOCK: none' if not c else '   CLOCK: only %d ticks' % len(c))
    lines.append('   START %d  STOP %d  CONTINUE %d' % (s['start'], s['stop'], s['cont']))
    lines.append('   PATTERN CHANGES (channel, program): ' + (', '.join('ch%d -> %d (x%d)' % (k[0], k[1], v) for k, v in s['pc'].items()) or 'none'))
    lines.append('   NOTES per channel: ' + (', '.join('ch%d: %d' % kv for kv in sorted(s['notes'].items())) or 'none'))
    lines.append('   KNOB/CC per channel: ' + (', '.join('ch%d: %d' % kv for kv in sorted(s['cc'].items())) or 'none'))
    if s['other']: lines.append('   other: ' + ', '.join('%s %d' % kv for kv in s['other'].items()))
    lines.append('')
open(os.path.join(here, 'midi_check.txt'), 'w').write('\n'.join(lines))
print('\n'.join(lines))
print('Saved to midi_check.txt')
