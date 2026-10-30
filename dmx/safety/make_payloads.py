"""Turn safety_zones.csv (from safety_map.py) into DMX-node /head payloads.

Each head gets tilt_max_deg = 85 (the unsafe-area model) plus one avoid zone per unsafe direction,
where 'lean' is the most it may lean toward that area. Usage:
    python3 make_payloads.py safety_zones.csv payloads.json [--skip "Head 3"]
Payloads are only written to a file; sending them to the node is a separate, supervised step.
"""
import csv, json, sys

src, dst = sys.argv[1], sys.argv[2]
skip = set(sys.argv[sys.argv.index('--skip') + 1].split(',')) if '--skip' in sys.argv else set()
heads = {}
for r in csv.DictReader(open(src)):
    if r['head'] in skip:
        continue
    h = heads.setdefault(r['head'], {'addr': int(r['address']), 'tilt_max_deg': 85.0, 'avoid': []})
    if r['zone_az'] == '':
        continue
    h['avoid'].append({'az': float(r['zone_az']), 'width': float(r['zone_width']),
                       'lean': float(r['max_lean_inside']), 'why': r['reason']})
json.dump(heads, open(dst, 'w'), indent=1)
for k, v in heads.items():
    print(k, 'addr', v['addr'], '-', len(v['avoid']), 'zones')
