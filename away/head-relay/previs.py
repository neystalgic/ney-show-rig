# PREVIS: 8 bars of the head relay at 120 BPM, on paper (no hub, no lights).
#   python3 away/head-relay/previs.py   -> previs_8bars.csv + previs_8bars.txt next to this file
import csv, os, sys, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hub_chase as hc

LEAN_MAX = 35.0                                     # a typical head's lean cap (each head's own cap applies live)


def main(bpm=120.0, energy=0.6):
    hub = types.SimpleNamespace(state={'settings': dict(dmx_host='zephyrus', dmx_pattern='show', energy=energy)},
                                blackout=False, audioshow=types.SimpleNamespace(section='groove'))
    c = hc.Chase(hub, lamps=hc.load_lamps(os.path.join(HERE, '..', '..', 'hub_lamps.json')))
    rows, turns = [], []
    for k in range(65):                             # every half beat for 32 beats
        beats = k * 0.5
        now = 1000.0 + beats * 60.0 / bpm
        cols = [(0.62, 0.2, 1.0)] * 6               # purple room
        c.lamps(cols, sorted(c.lamp_xy), now, beats, 'music')
        z = c.step(now, beats, 'music')
        cv = z['heads'][z['head']]
        half = cv['arc'] / 2.0
        pan = cv['way'] * (0.5 - 0.5 * __import__('math').cos(3.14159265 * cv['p']) - 0.5) * 2.0 * half
        glow = ', '.join(sorted(c.lamp_xy[ch][2] for ch in c.near(z['head'])))
        rows.append(dict(beat=beats, bar=int(beats // 4) + 1, head_lit=z['head'] + 1, level_pct=round(100 * cv['level']),
                         pan_offset_deg=round(pan, 1), lean_deg=round(c.theta(cv, LEAN_MAX), 1), lamps_glowing=glow))
        if not turns or turns[-1][0] != z['turn']:
            turns.append((z['turn'], z['head'] + 1, beats, cv['way'], cv['arc'], glow))
    with open(os.path.join(HERE, 'previs_8bars.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    lines = ['HEAD RELAY PREVIS -- 8 bars at %.0f BPM, energy %.1f (hand-off every %s), purple room' % (
        bpm, energy, 'bar' if energy >= 0.75 else '2 bars'), '']
    for n, (t, hd, b0, way, arc, glow) in enumerate(turns):
        b1 = turns[n + 1][2] if n + 1 < len(turns) else 32.0
        if b1 - b0 < 1:
            continue
        lines.append('bars %d-%d  Head %d fades in, sweeps %.0f deg %s with a small dip, fades out on the bar line.' % (
            b0 // 4 + 1, b1 // 4, hd, arc, 'left -> right' if way > 0 else 'right -> left'))
        lines.append('           Glowing: %s. Every other lamp dims to 20%%. Other heads dark (the next one pre-aims).' % glow)
    lines += ['', 'Spots: dark during the relay. Drops: the normal show (all heads, strobe allowed) takes over.']
    open(os.path.join(HERE, 'previs_8bars.txt'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
