"""Safety map: work out, from the room plot, where each moving head must NOT point.

Model: everything is safe unless a beam would
  - hit a mirror or the glass door (reflection),
  - hit the projected image (screen),
  - pass through seated eye height over a couch (eyes).
The fan is ignored (it is off during shows).

Input : room plot JSON (the Ney Room Plot artifact's plan/room doc).
Output: per head, the largest safe lean at every pan heading, compressed into
        node-style zones {az, width, lean} (lean = max allowed lean inside the zone),
        written as CSV.  Usage:  python3 safety_map.py room.json out.csv
"""
import csv, json, math, sys

FT = 1 / 12.0
CEIL = 93 * FT            # ceiling height
EYE = (34 * FT, 52 * FT)  # seated eye band, generous
GLASS_TOP = 80 * FT       # sliding door height (estimate)
SCREEN_Z = (0.0, CEIL)    # projected image height: unknown yet, so the whole wall height
LEAN_MAX = 85             # what we'd like the heads to reach
MARGIN = 5                # degrees kept clear of anything unsafe
AZ_STEP, LEAN_STEP = 2, 1


def rect(it, pad=0.0):
    return (it['x'] - it['w'] / 2 - pad, it['y'] - it['h'] / 2 - pad,
            it['x'] + it['w'] / 2 + pad, it['y'] + it['h'] / 2 + pad)


def ray_wall(px, py, dx, dy, poly):
    """distance along a horizontal ray to the first wall, and the hit point."""
    best = (1e9, None)
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((x1 - px) * ey - (y1 - py) * ex) / den
        u = ((x1 - px) * dy - (y1 - py) * dx) / den
        if t > 1e-6 and -1e-6 <= u <= 1 + 1e-6 and t < best[0]:
            best = (t, (px + t * dx, py + t * dy))
    return best


def build(plan):
    poly = plan['room']['poly']
    items = {i['id']: i for i in plan['items']}
    unsafe = [i for i in plan['items'] if i['kind'] == 'unsafe' and i.get('cat') != 'fan']
    # eye-level areas: drawn on the plot as unsafe 'eyes' with a height band (zlo..zhi, ft)
    eyes = [u for u in unsafe if u.get('cat') == 'eyes']
    band = lambda u: (u.get('zlo', EYE[0]) if u.get('zlo') is not None else EYE[0],
                      u.get('zhi', EYE[1]) if u.get('zhi') is not None else EYE[1])
    heads = [i for i in plan['items'] if i['kind'] == 'head']

    def hits_unsafe(wx, wy, wz):
        for u in unsafe:
            x0, y0, x1, y1 = rect(u, pad=0.15)
            if not (x0 <= wx <= x1 and y0 <= wy <= y1):
                continue
            if u.get('cat') == 'reflect':
                top = GLASS_TOP if 'glass' in u['id'] else CEIL
                if wz <= top:
                    return u['label']
            elif u.get('cat') == 'screen':
                if SCREEN_Z[0] <= wz <= SCREEN_Z[1]:
                    return u['label']
            elif u.get('cat') == 'eyes':
                lo, hi = band(u)
                if lo <= wz <= hi:
                    return u['label']
        return None

    def through_eyes(px, py, pz, dx, dy, lean, dist):
        if lean < 1:
            return None
        tl = math.tan(math.radians(lean))
        top = max([band(u)[1] for u in eyes] or [0])
        s = 0.0
        while s <= dist:
            z = pz + s / tl
            if z > top:
                break
            x, y = px + s * dx, py + s * dy
            for u in eyes:
                lo, hi = band(u)
                if lo <= z <= hi:
                    x0, y0, x1, y1 = rect(u)
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        return 'eye level, ' + u['id'].replace('u-eyes-', '') + ' couch'
            s += 0.1
        return None

    out = []
    for h in heads:
        px, py, pz = h['x'], h['y'], h.get('z', 2.5)
        base, sgn = h.get('rot', 0), (-1 if h.get('flip') else 1)
        rows = []
        for az in range(0, 360, AZ_STEP):
            th = math.radians(base + sgn * az)
            dx, dy = math.cos(th), math.sin(th)
            dwall, wpt = ray_wall(px, py, dx, dy, poly)
            safe, why = LEAN_MAX, ''
            for lean in range(0, LEAN_MAX + 1, LEAN_STEP):
                tl = math.tan(math.radians(lean)) if lean else 0
                dceil = (CEIL - pz) * tl
                if lean and dceil > dwall:      # reaches a wall first
                    wz = pz + dwall / tl
                    reason = hits_unsafe(wpt[0] - dx * 0.05, wpt[1] - dy * 0.05, wz)
                    reach = dwall
                else:
                    reason, reach = None, dceil
                reason = reason or through_eyes(px, py, pz, dx, dy, lean, reach)
                if reason:
                    safe, why = max(0, lean - MARGIN), reason
                    break
            rows.append((az, safe, why))
        out.append((h, rows))
    return out


def zones(rows):
    """merge headings whose safe lean is below LEAN_MAX into node zones."""
    zs, cur = [], None
    for az, safe, why in rows + [(360, LEAN_MAX, '')]:
        if safe < LEAN_MAX:
            if cur and abs(cur['lean'] - safe) <= 10 and cur['why'] == why:
                cur['a1'] = az; cur['lean'] = min(cur['lean'], safe)
            else:
                if cur: zs.append(cur)
                cur = {'a0': az, 'a1': az, 'lean': safe, 'why': why}
        else:
            if cur: zs.append(cur); cur = None
    # join a zone that wraps through 0
    if len(zs) > 1 and zs[0]['a0'] == 0 and zs[-1]['a1'] >= 360 - AZ_STEP and zs[0]['why'] == zs[-1]['why']:
        last = zs.pop(); zs[0]['a0'] = last['a0'] - 360; zs[0]['lean'] = min(zs[0]['lean'], last['lean'])
    res = []
    for z in zs:
        a0, a1 = z['a0'] - AZ_STEP / 2 - 3, z['a1'] + AZ_STEP / 2 + 3
        res.append({'az': round(((a0 + a1) / 2) % 360), 'width': round(a1 - a0), 'lean': z['lean'], 'why': z['why']})
    return res


if __name__ == '__main__':
    plan = json.load(open(sys.argv[1]))
    out = sys.argv[2] if len(sys.argv) > 2 else 'safety_zones.csv'
    with open(out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['head', 'address', 'zone_az', 'zone_width', 'max_lean_inside', 'reason'])
        for h, rows in build(plan):
            zs = zones(rows)
            for z in zs:
                w.writerow([h['label'], h.get('addr'), z['az'], z['width'], z['lean'], z['why']])
            if not zs:
                w.writerow([h['label'], h.get('addr'), '', '', LEAN_MAX, 'no limits'])
    print(open(out).read())
