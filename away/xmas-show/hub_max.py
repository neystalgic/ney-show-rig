# =============================================================================
# THE MAX SHOW (Nov 25, Michael: "cascading effects ... more than just rainbows. I want strobes, I want max colour,
# and max bang for our buck with this powerful equipment"). Setting dmx_pattern = 'max'. A SEPARATE show: the
# rainbow show (hold 4, show_default.json) is untouched. Preview: bridge/tap_cmd.json {"mode": "maxshow"}
# (settings in max_show.json on top of the saved show).
#
# His answers (Nov 25): strobes on DROPS + BUILDS only; palettes NEON PAIRS, FIRE / ICE, MONO + WHITE, UV + PURPLE
# (the rainbow stays in the rotation now and then).
#
# THE SONG SHAPE
#   groove     a cascading piece + a new palette every phrase (8 bars; shuffle bags, never twice in a row)
#     cascade    every kick launches a colour that RUNS through every fixture in his wave order with a fading tail,
#                alternating direction -- several in flight at once on a busy pocket
#     domino     every kick bursts from the middle of the order out to both ends; every snare runs back in from the ends
#     fight      NEON: two teams in two colours -- kick = team A, snare = team B, each hit rippling through its team;
#                the colours swap sides every 2 bars
#     waterfall  the heads fan open and closed one after another (a moving wall of beams), lamps cascade on the kick
#   build      (a breakdown with the drums / loudness rising) RISER: the coming drop's colour, cascades every beat ->
#              8th -> 16th, the room fills up, the heads gather toward the ceiling, STROBE hits speeding up with it
#              (white in the last stretch). Built-in drummer: the last beat goes BLACK -- the inhale before the drop
#   drop       IMPACT: the moment it lands = a 2 s burst on the heads' OWN strobe + the spots' shutters, then every
#              kick a double-speed cascade + every fixture flashing + a strobe hit (first 4 bars on the kicks, then on
#              the snares). Fire <-> ice swap on every drop. Held max_drop_bars (8) unless a breakdown starts
#   breakdown  DEEP: UV + purple -- the lamps breathe in slow purple cascades, the spots' UV on the tapestry
# No music (2 s of silence): the BUILT-IN DRUMMER plays a whole song on a loop -- 3 phrases groove, a breakdown whose
# second half is a build, then a 2-phrase drop -- so a demo always shows the full arc.
#
# SAFETY (the existing rules, enforced in hub_dmx + the Pi node, NOT here): strobe hits only for heads inside the
# strobe cone, at most strobe_max_hz a second (default 3; the hub caps it at 8; the node's flash guard has the last
# word), never in guest mode (the node blocks it too), movie, blackout or quiet. The Hue lamps never strobe.
# =============================================================================
import math

RB = [(1.0, 0.0, 0.0), (1.0, 0.35, 0.0), (1.0, 0.82, 0.0), (0.0, 1.0, 0.12), (0.0, 0.43, 1.0), (0.24, 0.0, 1.0),
      (0.67, 0.0, 1.0)]
WHITE = (1.0, 1.0, 1.0)
PALETTES = {
    'neon': [((1.0, 0.0, 0.55), (0.0, 0.9, 1.0)),       # magenta vs cyan
             ((1.0, 0.0, 0.0), (0.0, 0.25, 1.0)),        # red vs blue
             ((0.6, 0.0, 1.0), (0.0, 1.0, 0.2)),         # purple vs green
             ((1.0, 0.3, 0.0), (0.0, 0.35, 1.0))],       # orange vs blue
    'fire': [(1.0, 0.0, 0.0), (1.0, 0.22, 0.0), (1.0, 0.45, 0.0), (1.0, 0.0, 0.1)],
    'ice': [(0.0, 0.85, 1.0), (0.0, 0.45, 1.0), (0.0, 0.1, 1.0), (0.3, 0.0, 1.0)],
    'mono': [(1.0, 0.0, 0.0), (0.0, 0.2, 1.0), (0.6, 0.0, 1.0), (1.0, 0.0, 0.5), (0.0, 1.0, 0.25)],   # + white hits
    'uv': [(0.55, 0.0, 1.0), (0.35, 0.0, 1.0), (0.75, 0.0, 1.0), (0.25, 0.0, 1.0)],
    'rainbow': RB,
    # CHRISTMAS (Nov 28, Michael liked: red + green, candy cane, snowfall, twinkle, gold drops) -- max_theme 'xmas'
    'xmas': [((1.0, 0.0, 0.0), (0.0, 1.0, 0.15)),        # red vs green
             ((0.85, 0.0, 0.05), (0.0, 0.75, 0.3))],     # deep red vs emerald
    'candy': [(1.0, 0.0, 0.0), WHITE],                    # candy cane: red, white, red, white ...
    'gold': [(1.0, 0.55, 0.05), (1.0, 0.72, 0.25), (1.0, 0.4, 0.0)],
    'frost': [WHITE, (0.6, 0.85, 1.0), (0.25, 0.5, 1.0)],
    'evergreen': [(0.0, 0.85, 0.2), (0.9, 0.0, 0.05), (0.0, 0.55, 0.25), (1.0, 0.0, 0.0)],   # greens + reds, mixed
}
PAL_NAMES = {'neon': 'neon', 'fire': 'fire', 'ice': 'ice', 'mono': 'mono + white', 'uv': 'UV + purple', 'rainbow': 'rainbow',
             'xmas': 'red + green', 'candy': 'candy cane', 'gold': 'gold', 'frost': 'frost', 'evergreen': 'evergreen'}
GROOVE = ['cascade', 'domino', 'fight', 'waterfall']
NAMES = {'cascade': 'Cascade', 'domino': 'Domino', 'fight': 'Neon fight', 'waterfall': 'Waterfall',
         'riser': 'Riser (build)', 'impact': 'Impact (drop)', 'deep': 'Deep UV (breakdown)',
         'snowfall': 'Snowfall', 'twinkle': 'Twinkle'}
DROP_PALS = ['fire', 'ice', 'neon', 'mono']
WHITE_PALS = ('mono', 'candy', 'frost')                   # palettes whose strobe hits are white
# THEMES (setting max_theme): which palettes + pieces the show deals. '' = the Max show as built Nov 25.
THEMES = {
    '': dict(pals=['neon', 'fire', 'ice', 'mono', 'uv', 'rainbow'], groove=GROOVE, drop=DROP_PALS, swap=('fire', 'ice'),
             breakdown=('deep', 'uv'), pair='neon'),
    # Nov 28 live with carols (Michael): "too much strobing, more green and red, less yellow, avoid the multi colour
    # dot gobo" -> red/green palettes only (+ candy cane), strobes LOW; then "I really liked the look of no gobos" ->
    # open beams (gobo_open)
    'xmas': dict(pals=['xmas', 'candy', 'evergreen'], groove=['cascade', 'snowfall', 'domino', 'fight'],
                 drop=['xmas', 'candy'], swap=('xmas', 'candy'), breakdown=('twinkle', 'xmas'), pair='xmas',
                 strobe='low', gobo_open=True, react='onsets'),
}


def theme(d):
    return THEMES.get(str(d.settings().get('max_theme', '') or '').strip().lower(), THEMES[''])


def is_white(c):
    return min(c) > 0.9


def gobo_test(now):
    """Nov 28: bridge/gobo_test.json {"gobo": 48} (written in the last 90 s) holds both spots on that gobo -- so Michael
    can say which wheel slot is the tacky one. Read at most once a second. -> int or None."""
    c = getattr(gobo_test, '_c', None)
    if c and now - c[0] < 1.0:
        return c[1]
    import json, os, time
    v = None
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bridge', 'gobo_test.json')
    try:
        if time.time() - os.path.getmtime(p) < 90.0:
            with open(p) as f:
                v = int(json.load(f).get('gobo'))
    except (OSError, ValueError, TypeError):
        v = None
    gobo_test._c = (now, v)
    return v


def gobos_for(d):
    if theme(d).get('gobo_open'):
        return [0]                                       # open beams, no gobo
    skip = set(theme(d).get('gobo_skip') or []) | set(d.settings().get('max_gobo_skip') or [])
    return [g for g in GOBOS if g not in skip] or GOBOS
GOBOS = [16, 32, 48, 64, 80, 96]
UV_AIMS = {4: {'az': 197.0, 'lean': 40.0}, 5: {'az': 191.2, 'lean': 67.0}}
POS = [(0.15, 0.9), (0.85, 0.6), (0.35, 0.9), (0.65, 0.6)]          # the heads' jump spots (u, lean)
LOW = [(0.2, 0.42), (0.8, 0.25), (0.4, 0.42), (0.6, 0.25)]          # drops / builds: inside the strobe cone


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def pal_col(pal, var, k):
    """Colour k of a palette (var = which pair / which mono colour this phrase)."""
    if pal in ('neon', 'xmas'):
        return PALETTES[pal][var % len(PALETTES[pal])][k % 2]
    if pal == 'mono':
        return PALETTES['mono'][var % len(PALETTES['mono'])]
    p = PALETTES.get(pal) or RB
    return p[k % len(p)]


def slot_for(rgb):
    """The Focus Spot colour-wheel slot nearest a colour (0 = open white)."""
    if min(rgb) > 0.9:
        return 0
    mx, mn = max(rgb), min(rgb)
    if mx <= 0:
        return 37
    r, g, b = rgb
    d = mx - mn
    if d == 0:
        h = 0.0
    elif mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = (b - r) / d + 2.0
    else:
        h = (r - g) / d + 4.0
    deg = h * 60.0
    if deg >= 345 or deg < 20:
        return 22
    if deg < 75:
        return 67
    if deg < 190:
        return 52
    if deg < 262:
        return 37
    if deg < 292:
        return 97
    return 82


def _setting_f(s, k, dflt, lo, hi):
    try:
        return clamp(float(s.get(k, dflt)), lo, hi)
    except (TypeError, ValueError):
        return dflt


def fixtures(d, zl):
    """His wave order (chase_seq); without one: lamp zones, then heads, then spots."""
    seq = list(d.chase_seq() or [])
    if len(seq) >= 3:
        return seq
    out = [('l', z['id'], z['channels']) for z in zl]
    out += [('h', h, []) for h in d.heads_i] + [('s', i, []) for i in d.spots_i]
    return out


# ------------------------------------------------------------------------------ cascades
def launch(st, b0, col, direction, origin, speed, tail, key='casc'):
    """A colour that runs through the fixtures from origin: direction +1 / -1 / 0 (both ways), speed in fixtures
    per beat, tail = how many fixtures it takes to fade (e-fold)."""
    L = st.setdefault(key, [])
    L.append(dict(b0=b0, col=col, dir=direction, o=origin, sp=speed, tail=tail))
    del L[:-10]


def cascade_levels(st, n, beats, key='casc'):
    lv, cols = [0.0] * n, [None] * n
    keep = []
    for L in st.get(key, []):
        pos = (beats - L['b0']) * L['sp']
        if pos > n + 6 * L['tail']:
            continue                                         # run out the far end: done
        keep.append(L)
        for k in range(n):
            if L['dir'] == 0:
                dist = abs(k - L['o'])
            elif L['dir'] > 0:
                dist = k - L['o']
            else:
                dist = L['o'] - k
            if dist < 0:
                continue
            behind = pos - dist
            if behind < 0:
                continue
            v = math.exp(-behind / max(0.2, L['tail']))
            if v > lv[k]:
                lv[k], cols[k] = v, L['col']
    st[key] = keep
    return lv, cols


# ------------------------------------------------------------------------------ the song shape
def shape(d, st, beats, now, live, sec, bpb, bar, phrase, bpp, cnt):
    """-> (part, progress): groove / build / drop / breakdown. Records a drop landing (st land_b / land_t)."""
    s = d.settings()
    if s.get('max_calm'):
        return 'calm', 0.0                                   # the calm December look: no song shape, no strobes
    drop_bars = int(_setting_f(s, 'max_drop_bars', 8, 2, 32))
    if not live:                                             # the built-in drummer: a whole song on a loop
        st['hist'] = []
        cyc = phrase % 6
        bar_in = bar - phrase * bpp
        if cyc < 3:
            part, p = 'groove', 0.0
        elif cyc == 3:
            half = max(1, bpp // 2)
            if bar_in < half:
                part, p = 'breakdown', 0.0
            else:
                b_start = (phrase * bpp + half) * bpb
                p = clamp((beats - b_start) / float(half * bpb))
                part = 'build'
                if beats >= (phrase + 1) * bpp * bpb - 1.0:
                    st['inhale'] = True
                    return 'build', 1.0
        else:
            part, p = 'drop', 0.0
            lb = (phrase - (cyc - 4)) * bpp * bpb
            if st.get('land_b') != lb:
                st['land_b'], st['land_t'] = lb, now - max(0.0, beats - lb) * st.get('spb', 0.5)
                st['landed'] = True
        st['inhale'] = False
        st['aud'] = None
        return part, p
    st['inhale'] = False
    # the music: the hub's own sections + a drop held for its bars + a build heard as rising drums / loudness
    if sec == 'drop' and st.get('aud') != 'drop':
        st['aud'], st['land_b'], st['land_t'], st['landed'] = 'drop', beats, now, True
        st['build_t'] = None
    if st.get('aud') == 'drop':
        if beats - st.get('land_b', beats) < drop_bars * bpb and sec != 'breakdown':
            return 'drop', 0.0
        st['aud'] = None
    hist = st.setdefault('hist', [])
    tot = int(cnt.get('kick', 0)) + int(cnt.get('snare', 0)) + int(cnt.get('hats', 0))
    f = getattr(getattr(d.hub, 'audioshow', None), 'feat', None) or {}
    db = f.get('db') if isinstance(f, dict) else None
    db = float(db) if isinstance(db, (int, float)) and db > -100.0 else None
    hist.append((now, tot, db))
    while hist and now - hist[0][0] > 10.0:
        hist.pop(0)

    def tot_at(age):
        for t_, n_, _ in hist:
            if t_ >= now - age:
                return n_
        return tot

    def db_mean(a0, a1):
        v = [x for t_, _, x in hist if x is not None and now - a1 <= t_ <= now - a0]
        return sum(v) / len(v) if v else None

    r2 = (tot - tot_at(2.0)) / 2.0
    r8 = (tot_at(2.0) - tot_at(8.0)) / 6.0
    d_new, d_old = db_mean(0.0, 1.0), db_mean(4.0, 5.0)
    rising = (r2 >= 3.0 and r2 >= 1.4 * r8 + 0.5) or (d_new is not None and d_old is not None and d_new - d_old >= 3.0)
    if rising:
        st['rise_t'] = now
    if sec in ('breakdown', 'quiet'):
        if st.get('brk_t') is None:
            st['brk_t'] = now
        if st.get('build_t') is None and rising and now - st['brk_t'] >= 2.0:
            st['build_t'] = now
        if st.get('build_t') is not None and now - st.get('rise_t', now) > 4.0:
            st['build_t'] = None                             # it stopped rising: back to the breakdown
        if st.get('build_t') is not None:
            return 'build', clamp((now - st['build_t']) / _setting_f(s, 'max_build_s', 8.0, 2.0, 30.0))
        return 'breakdown', 0.0
    st['brk_t'] = st['build_t'] = None
    return 'groove', 0.0


def _bag_pick(d, st, key, items, last):
    bag = [x for x in st.get(key, []) if x != last and x in items]
    if not bag:
        bag = [x for x in items if x != last] or list(items)
        d.rng.shuffle(bag)
    nxt = bag.pop(0)
    st[key] = bag
    return nxt


def _next_drop(d, st, th):
    """The next drop's palette: the theme's swap pair alternates (fire <-> ice, gold <-> candy), else something hot."""
    last = st.get('drop_pal')
    a, b = th['swap']
    if last == a:
        return b
    if last == b:
        return a
    opts = [p for p in th['drop'] if p != last and p in PALETTES] or list(th['drop'])
    return opts[d.rng.randrange(len(opts))]


def plan(d, st, part, phrase):
    """The piece + palette for this phrase / part (new on every phrase and every part change)."""
    s = d.settings()
    th = theme(d)
    key = (phrase, part) if part != 'calm' else (phrase // 2, part)      # calm: a new colour every 2 phrases
    if st.get('plan_key') == key:
        return
    prev_part = (st.get('plan_key') or (None, None))[1]
    st['plan_key'] = key
    if th is THEMES['']:
        pals = [p for p in (s.get('max_palettes') or th['pals']) if p in PALETTES] or list(th['pals'])
    else:
        pals = list(th['pals'])
    if part == 'calm':
        st['piece'] = 'twinkle'
        st['pal'] = _bag_pick(d, st, 'pal_bag', pals, st.get('pal'))
        st['var'] = d.rng.randrange(20)
    elif part == 'drop':
        if prev_part != 'drop':                              # a NEW drop: the swap pair alternates
            nxt = st.pop('next_drop', None) or _next_drop(d, st, th)
            st['drop_pal'] = st['pal'] = nxt
            st['var'] = d.rng.randrange(20)
        st['piece'] = 'impact'
    elif part == 'build':
        if prev_part != 'build':
            st['next_drop'] = st['pal'] = _next_drop(d, st, th)   # the build previews the drop's colour
            st['var'] = d.rng.randrange(20)
        st['piece'] = 'riser'
    elif part == 'breakdown':
        st['piece'], st['pal'] = th['breakdown']
    else:
        lock = str(s.get('max_lock', '') or '').strip().lower()
        groove = th['groove']
        piece = lock if lock in groove else _bag_pick(d, st, 'piece_bag', groove, st.get('piece'))
        pal = _bag_pick(d, st, 'pal_bag', pals, st.get('pal'))
        if piece == 'fight':
            pal = th['pair']                                 # the fight IS two colours
        st['piece'], st['pal'], st['var'] = piece, pal, d.rng.randrange(20)


# ------------------------------------------------------------------------------ the frame
def max_frame(d, beats, now):
    s = d.settings()
    st = d.__dict__.setdefault('_mx', {})
    bpb = int(s.get('beats_per_bar', 4) or 4)
    bpp = d.bars_per_phrase()
    bar = int(math.floor(beats / bpb))
    phrase = bar // bpp
    fdt = clamp(now - st['t_prev'], 0.0, 0.2) if st.get('t_prev') is not None else 0.02   # seconds since the last frame
    if st.get('t_prev') is not None and beats > st.get('b_prev', beats) and now > st['t_prev']:
        spb = (now - st['t_prev']) / (beats - st['b_prev'])
        st['spb'] = clamp(0.8 * st.get('spb', 0.5) + 0.2 * spb, 0.2, 2.0)
    st['t_prev'], st['b_prev'] = now, beats
    cnt, live = d.pocket(now)
    bn = int(math.floor(beats))
    frac = beats - bn
    if live:
        e = d._pk['a']
        ed = d._pk.get('d') or e
        kn, sn = cnt['kick'], cnt['snare']
        kick = e['kick']
    else:
        e = d.clock_hits(beats)
        ed = e
        kn = bn
        sn = (bn // bpb) * 2 + sum(1 for x in (1, 3) if x <= bn % bpb)     # the drummer's snares: 2 + 4
        kick = max(e['kick'], math.exp(-frac / 0.22))
    dk, ds = ed['kick'], ed['snare']
    sec = d.section()
    part, prog = shape(d, st, beats, now, live, sec, bpb, bar, phrase, bpp, cnt)
    plan(d, st, part, phrase)
    piece, pal, var = st['piece'], st['pal'], st.get('var', 0)
    zl = d.zone_list()
    seq = fixtures(d, zl)
    n = len(seq)
    new_k = kn != st.get('kn_prev')
    new_s = sn != st.get('sn_prev')
    st['kn_prev'], st['sn_prev'] = kn, sn
    st['launches'] = st.get('launches', 0)
    # Nov 28 live with carols (Michael: "it should be audio reactive -- right now it just looks chaotic"): carols have
    # almost no kick, so the christmas theme moves on EVERY onset the analyser hears (bells, voices, snares, hats --
    # the same small transients SCATTER uses) and never on a clock while the music plays; loudness sets the level.
    soft = theme(d).get('react') == 'onsets' and live
    tr = (d._pk.get('tr') or {}) if live else {}
    tot = sum(int(tr.get(k, 0) or 0) for k in ('kick', 'snare', 'hats')) if live else bn * 2 + (1 if frac >= 0.5 else 0)
    new_any = tot != st.get('tot_prev') and now - st.get('any_t', -9.0) > 0.12
    st['tot_prev'] = tot
    if new_any:
        st['any_t'] = now
    hit_str = clamp(max(ed.get('kick', 0.0), ed.get('snare', 0.0), ed.get('hats', 0.0))) if live else 1.0
    trig_k = new_k or (soft and new_any)
    lv, cols = [0.0] * n, [None] * n
    flash_slot, white, burst, burst_rgbw = None, False, False, None
    lean_cap = None
    head_pos = {}
    max_pos = POS[(kn + sn) % 4]
    k_sp = _setting_f(s, 'max_cascade_speed', 1.0, 0.25, 4.0)      # whole wave per beat (1 = the order in 1 beat)
    if piece == 'cascade':
        if trig_k:
            st['launches'] += 1
            dr = 1 if st['launches'] % 2 else -1
            launch(st, beats, pal_col(pal, var, st['launches']), dr, 0 if dr > 0 else n - 1, n * k_sp, 1.4)
        lv, cols = cascade_levels(st, n, beats)
    elif piece == 'domino':
        if trig_k and not (soft and new_s):
            st['launches'] += 1
            launch(st, beats, pal_col(pal, var, st['launches']), 0, (n - 1) / 2.0, n * k_sp, 1.2)
        if new_s:
            st['launches'] += 1
            c = pal_col(pal, var, st['launches'])
            launch(st, beats, c, 1, 0, n * k_sp, 1.0, key='casc2')
            launch(st, beats, c, -1, n - 1, n * k_sp, 1.0, key='casc3')
        lv, cols = cascade_levels(st, n, beats)
        for key in ('casc2', 'casc3'):
            l2, c2 = cascade_levels(st, n, beats, key)
            for k in range(n):
                if l2[k] > lv[k]:
                    lv[k], cols[k] = l2[k], c2[k]
    elif piece == 'fight':
        swap = (bar // 2) % 2
        if soft:
            if new_any:                                          # onsets take turns: team A, team B, A ...
                st['f_turn'] = 1 - st.get('f_turn', 1)
                st['fb_b' if st['f_turn'] else 'fa_b'] = beats
        else:
            if new_k:
                st['fa_b'] = beats
            if new_s:
                st['fb_b'] = beats
        for k in range(n):
            team = (k % 2) ^ swap
            b0 = st.get('fa_b' if team == 0 else 'fb_b')
            rank = k // 2
            if b0 is None:
                v = 0.0
            else:
                age = (beats - b0) - rank * 0.06                       # the hit ripples through its team
                v = 0.0 if age < 0 else math.exp(-age / 0.35)
            lv[k] = 0.06 + 0.94 * v
            cols[k] = pal_col(pal if pal in ('neon', 'xmas') else 'neon', var, team)
    elif piece == 'waterfall':
        if new_k:
            st['launches'] += 1
            launch(st, beats, pal_col(pal, var, st['launches']), 1, 0, n * k_sp * 0.75, 2.0)
        lv, cols = cascade_levels(st, n, beats)
        hk = [k for k, f in enumerate(seq) if f[0] == 'h']
        for j, k in enumerate(hk):
            ph = beats / 4.0 - j * 0.18                                # each head a little after the last
            tri = 1.0 - abs((ph % 1.0) * 2.0 - 1.0)
            head_pos[seq[k][1]] = (0.2 + 0.6 * j / max(1, len(hk) - 1), 0.25 + 0.65 * tri)
            lv[k] = max(lv[k], 0.35 + 0.65 * tri)
            cols[k] = cols[k] or pal_col(pal, var, j)
    elif piece == 'snowfall':
        # Nov 28 (Christmas): white flakes settle on the fixtures -- a couple every 8th, more on the hats -- each one
        # melting away slowly over the palette's colour; the heads' beams drift DOWN like falling snow over 2 bars
        fl = st.setdefault('flakes', {})
        if soft:                                                 # the music's onsets drop the flakes
            if new_any:
                for _ in range(1 + int(2 * hit_str)):
                    fl[d.rng.randrange(n)] = beats
        else:
            slot = int(math.floor(beats * 2))
            if slot != st.get('snow_slot'):
                st['snow_slot'] = slot
                for _ in range(1 + (1 if (live and ed.get('hats', 0) > 0.5) else 0) + (1 if new_k else 0)):
                    fl[d.rng.randrange(n)] = beats
        for k in range(n):
            b0 = fl.get(k)
            v = math.exp(-(beats - b0) / 0.7) if b0 is not None and beats >= b0 else 0.0
            lv[k] = 0.14 + 0.86 * v
            cols[k] = WHITE if v > 0.35 else pal_col(pal, var, k)
        hk = [k for k, f in enumerate(seq) if f[0] == 'h']
        fall = (beats % (2.0 * bpb)) / (2.0 * bpb)
        for j, k in enumerate(hk):
            head_pos[seq[k][1]] = (0.2 + 0.6 * j / max(1, len(hk) - 1), 0.12 + 0.7 * ((fall + 0.15 * j) % 1.0))
    elif piece == 'twinkle':
        # Nov 28 (Christmas): every fixture twinkles on its own -- a soft rise, a slow fade, a new colour each time;
        # breakdowns twinkle a little faster, the calm December look slower and dimmer
        tw = st.setdefault('tw', {})
        rate = 0.35 if part == 'calm' else 0.05 if soft else 0.9   # background twinkles per fixture per second
        if soft and new_any:                                     # each onset lights one or two resting lights
            idle = [k for k in range(n) if k not in tw or now - tw[k][0] > 0.8]
            d.rng.shuffle(idle)
            for k in idle[:1 + int(hit_str > 0.6)]:
                tw[k] = (now, d.rng.randrange(8))
        for k in range(n):
            if k not in tw or now - tw[k][0] > 1.6:
                if d.rng.random() < rate * fdt:
                    tw[k] = (now, d.rng.randrange(8))
            t0, ci = tw.get(k, (-99.0, 0))
            a = now - t0
            v = (a / 0.35) if a < 0.35 else math.exp(-(a - 0.35) / 0.5) if a < 4.0 else 0.0
            lv[k] = 0.16 + 0.84 * clamp(v)
            cols[k] = pal_col(pal, var, ci)
    elif piece == 'riser':
        interval = 1.0 if prog < 0.4 else 0.5 if prog < 0.75 else 0.25
        slot = int(math.floor(beats / interval))
        if slot != st.get('riser_slot'):
            st['riser_slot'] = slot
            st['launches'] += 1
            dr = 1 if st['launches'] % 2 else -1
            launch(st, beats, pal_col(pal, var, 0), dr, 0 if dr > 0 else n - 1, n / max(0.25, interval), 1.6 + 2.0 * prog)
        lv, cols = cascade_levels(st, n, beats)
        fill = 0.08 + 0.55 * prog                                    # the room fills up
        lv = [max(x, fill) for x in lv]
        cols = [c or pal_col(pal, var, 0) for c in cols]
        lean_cap = 0.42 * (1.0 - 0.6 * prog)                         # the heads gather toward the ceiling
        low = theme(d).get('strobe') == 'low'
        if prog >= (0.6 if low else 0.25):
            flash_slot = ('b', int(math.floor(beats)) if low else slot)
            white = prog >= 0.8 or pal in WHITE_PALS
        if st.get('inhale'):
            lv, flash_slot = [0.0] * n, None                         # the inhale: black, then the drop
    elif piece == 'impact':
        land_t = st.get('land_t', now)
        since_b = beats - st.get('land_b', beats)
        low = theme(d).get('strobe') == 'low'
        burst = 0.0 <= now - land_t < (1.0 if low else 2.0)
        if new_k or st.get('landed'):
            st['landed'] = False
            st['launches'] += 1
            dr = 1 if st['launches'] % 2 else -1
            launch(st, beats, pal_col(pal, var, st['launches']), dr, 0 if dr > 0 else n - 1, 2.0 * n * k_sp, 1.2)
        lv, cols = cascade_levels(st, n, beats)
        flash = max(dk, 0.7 * ds) if live else max(e['kick'], 0.7 * e['snare'], math.exp(-frac / 0.18))
        c0 = pal_col(pal, var, kn)
        for k in range(n):
            base = 0.04 + 0.96 * flash
            if base > lv[k]:
                lv[k], cols[k] = base, cols[k] or c0
        lean_cap = 0.42
        if burst:
            q = int(math.floor(beats * 4))
            c_ = pal_col(pal, var, q // 2)
            burst_rgbw = (0.0, 0.0, 0.0, 1.0) if (pal == 'mono' or q % 2 or is_white(c_)) else (c_[0], c_[1], c_[2], 0.0)
        elif low:
            flash_slot = ('bar', bar) if since_b < 4 * bpb else None    # low: one hit a bar, first 4 bars only
        elif since_b < 4 * bpb:
            flash_slot = ('k', kn)
        else:
            flash_slot = ('s', sn)
        white = pal in WHITE_PALS
    else:                                                           # DEEP: UV + purple, the room breathes
        slot = int(math.floor(beats / 2.0))
        if slot != st.get('deep_slot'):
            st['deep_slot'] = slot
            st['launches'] += 1
            dr = 1 if st['launches'] % 2 else -1
            launch(st, beats, pal_col('uv', 0, st['launches']), dr, 0 if dr > 0 else n - 1, n / 8.0, 3.0)
        lv, cols = cascade_levels(st, n, beats)
        br = 0.5 - 0.5 * math.cos(2 * math.pi * beats / (4.0 * bpb))
        lv = [0.12 + 0.3 * br + 0.58 * x for x in lv]
        cols = [c or pal_col('uv', 0, 0) for c in cols]
    # one strobe hit = a new id on every slot change (hub_dmx flashes a head once per id, rate-limited)
    if flash_slot is not None and flash_slot != st.get('flash_slot'):
        st['flash_slot'] = flash_slot
        st['flash_n'] = st.get('flash_n', 0) + 1
    hit = st.get('flash_n', 0) if flash_slot is not None else None
    # ------------------------------------------------------------------ build the frame
    dyn = 0.3 + 0.7 * d._pk.get('dyn', 1.0) if (live and (part == 'groove' or soft)) else 1.0
    if part == 'calm':
        dyn = _setting_f(s, 'max_calm_level', 0.6, 0.1, 1.0)   # an evening glow, not a show
        hit = None
    zout, hs, spots = [], {}, {}
    for k, (kind, key, chans) in enumerate(seq):
        c = cols[k] or pal_col(pal, var, k)
        v = clamp(lv[k] * dyn)
        if kind == 'l':
            zo_ = dict(id='L:' + str(key), level=v, rgb=c, channels=chans)
            if is_white(c):
                zo_['white'] = True                          # (the lamps would otherwise push white to a pastel)
            zout.append(zo_)
        elif kind == 'h':
            if key in head_pos:
                u, ln = head_pos[key]
            elif lean_cap is not None:
                u, ln = LOW[(kn + sn + key) % 4]
                ln = min(ln, lean_cap)
                if piece == 'riser':
                    u = 0.5 + (u - 0.5) * (1.0 - prog)
            else:
                u, ln = max_pos if (key + kn) % 2 == 0 else POS[(kn + sn + 2) % 4]
            hv = clamp(max(v, 0.3 + 0.7 * max(dk, ds)) if v > 0.05 else v)
            if part == 'calm' or piece in ('twinkle', 'snowfall'):
                hv = v                                       # soft pieces: no punch on the drums
            if part == 'calm':
                u, ln = 0.5, 0.1                             # calm: beams straight up, still
            cv = dict(level=hv, u=u, lean=ln, rgb=c, fast=part != 'calm')
            if is_white(c):
                cv['wbody'] = True                           # hub_dmx: the head's white LED, not a pastel
            if hit is not None:
                cv['flash'], cv['white'] = hit, white
            hs[key] = cv
        else:
            if piece == 'deep':
                aim = UV_AIMS.get(key, {'az': 180, 'lean': 50})
                spots[key] = dict(level=0.85, fx=dict(hold=dict(aim, drift=0), hold_when='always', hold_head=key, uv=1.0,
                                                      uv_only=True, uv_steady=True, gobo=0, focus=128))
                continue
            uv = 0.6 if pal == 'uv' else 0.0
            gl_ = gobos_for(d)
            gb = gobo_test(now)
            fx = dict(gobo=gb if gb is not None else (gl_[(kn + sn) % len(gl_)] if piece != 'riser' else 0),
                      color=0 if white else slot_for(c),
                      gobo_rot=0, uv=uv, uv_only=False, breathe=0,
                      focus=90 if piece == 'riser' else 150)
            if s.get('spot_scan', True) and part != 'calm':
                fx['scan'] = True
            sp = dict(level=clamp(max(v, 0.3 + 0.7 * max(dk, ds)) if v > 0.05 else v), fx=fx)
            if part == 'calm' or piece in ('twinkle', 'snowfall'):
                sp['level'] = v
            if gb is not None:                               # the gobo check: both spots on, open white, steady
                sp['level'], fx['color'], fx['scan'] = 0.85, 0, False
            if hit is not None:
                sp['flash'], sp['white'] = hit, white
            spots[key] = sp
    for h in d.heads_i:
        hs.setdefault(h, dict(level=0.0, lean=0.5, u=0.5, rgb=pal_col(pal, var, 0)))
    for i in d.spots_i:
        spots.setdefault(i, dict(level=0.0, fx=dict(gobo=0, color=slot_for(pal_col(pal, var, 0)), uv=0, uv_only=False)))
    cur = zout[0]['rgb'] if zout else pal_col(pal, var, 0)
    name = '%s - %s' % (NAMES.get(piece, piece), PAL_NAMES.get(pal, pal))
    return dict(heads=hs, zones=zout, spots=spots, lamp_floor=0.0, full=True, rgb=cur, v=d.v, head=None, turn=phrase,
                new=False, p=0.0, mode='mx_' + piece, act='max', bar=bar, phrase_bar=bar % bpp, rb=piece, rb_name=name,
                pocket=live, part=part, build=round(prog, 3), palette=pal, burst=bool(burst),
                burst_rgbw=burst_rgbw, hit=hit, white=bool(white))
