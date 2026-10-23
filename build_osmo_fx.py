# build_osmo_fx.py -- the Osmo as an instrument (v1)
#   * Gear-cam kaleidoscope: point the Osmo at your hands on the Push / Digitakt; the wall becomes a
#     live mandala made of your playing (mirror segments, spin, zoom punched by the kick).
#   * Motion: how much the camera sees moving -> spins the mandala faster, zooms it in, and lifts the
#     Hue lamps (posts {'op':'crowd'} to the hub, which still runs it through flicker protection).
#   * Everything that reaches the projector goes through the same flicker-safe pass as the tunnel.
# Run inside TouchDesigner:  exec(open(<this file>).read()); build()
P = op('/project1')

KAL = r"""
uniform vec4 uA;   // segments, angle (radians), zoom, kick
uniform vec4 uB;   // loudness, motion, time (s), brightness
out vec4 fragColor;
void main() {
    vec2 res = uTDOutputInfo.res.zw;
    vec2 p = (vUV.st - 0.5) * vec2(res.x / res.y, 1.0);
    float r = length(p);
    float seg = 6.28318530718 / max(uA.x, 2.0);
    float a = atan(p.y, p.x) + uA.y;
    a = mod(a, seg);
    a = abs(a - 0.5 * seg);                                  // mirror inside each slice
    float z = uA.z * (1.0 - 0.10 * uA.w) * (1.0 - 0.25 * uB.y);
    vec2 q = vec2(cos(a), sin(a)) * r * z;
    q += 0.06 * vec2(sin(uB.z * 0.21), cos(uB.z * 0.17));    // slow drift through the picture
    vec2 uv = 0.5 + q;
    uv = 1.0 - abs(1.0 - mod(uv, 2.0));                      // mirror-repeat at the edges
    vec3 c = texture(sTD2DInputs[0], uv).rgb * uB.w * (0.8 + 0.4 * uB.x);
    float ring = 0.0;                                        // three soft sacred-geometry rings
    for (int i = 1; i <= 3; i++) {
        float rr = 0.15 * float(i) * (1.0 + 0.04 * uA.w);
        ring += smoothstep(0.006, 0.0, abs(r - rr));
    }
    c += ring * vec3(0.55, 0.85, 0.35) * (0.25 + 0.35 * uB.x);
    c *= smoothstep(0.62, 0.40, r) * 0.85 + 0.15;            // fade towards the edges
    fragColor = TDOutputSwizzle(vec4(c, 1.0));
}
"""

# the same flicker-safe pass as the tunnel (build_hue_hub_td.py TUNNEL_SAFE)
SAFE = r"""
uniform vec4 uL;   // per-pixel step, overall step (per frame), brightest average allowed, unused
out vec4 fragColor;
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
void main() {
    vec2 uv = vUV.st;
    vec3 t = texture(sTD2DInputs[0], uv).rgb;
    vec3 pr = texture(sTD2DInputs[1], uv).rgb;
    float lt = luma(texture(sTD2DInputs[2], vec2(0.5)).rgb);
    float lp = luma(texture(sTD2DInputs[3], vec2(0.5)).rgb);
    float cap = lt > uL.z ? uL.z / max(lt, 1e-5) : 1.0;
    t *= cap; lt *= cap;
    vec3 d = clamp(t - pr, -uL.x, uL.x);
    float dg = abs(lt - lp);
    float k = dg > uL.y ? uL.y / dg : 1.0;
    fragColor = TDOutputSwizzle(vec4(clamp(pr + d * k, 0.0, 1.0), 1.0));
}
"""

POST = r"""
# osmo_fx: sends the motion amount to the Hue Hub ~5 times a second (the hub lifts the lamps with it)
import json, threading, urllib.request
_busy = [False]
def _post(v):
    try:
        rq = urllib.request.Request('http://localhost:7020/api', data=json.dumps({'op': 'crowd', 'value': v}).encode(),
                                    headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(rq, timeout=0.5).read()
    except Exception:
        pass
    _busy[0] = False

def onFrameEnd(frame):
    if frame % 12 or _busy[0]:
        return
    fx = parent()
    if not fx.par.Crowdlights.eval():
        return
    v = 0.0 if fx.par.Mode.eval() == 'tunnel' else float(op('motion')['r'])
    _busy[0] = True
    threading.Thread(target=_post, args=(round(v, 3),), daemon=True).start()
"""

FX = '/project1/osmo_fx'


def _set(o, name, v):
    try:
        o.par[name].val = v
        return True
    except Exception:
        return False


def _res(o, w, h):
    _set(o, 'outputresolution', 'custom')
    _set(o, 'resolutionw', w)
    _set(o, 'resolutionh', h)


def _glsl(c, name, code, rows, tops, x, y, w=1280, h=800):
    sh = c.create(textDAT, name + '_code')
    sh.nodeX, sh.nodeY = x, y - 150
    sh.text = code
    g = c.create(glslTOP, name)
    g.nodeX, g.nodeY = x, y
    g.par.pixeldat = sh.name
    for pn in ('format', 'outputpixelformat', 'pixelformat'):
        if _set(g, pn, 'rgba16float'):
            break
    _res(g, w, h)
    g.seq.vec.numBlocks = len(rows)
    for k, (uname, exprs) in enumerate(rows):
        g.par['vec%dname' % k].val = uname
        for letter, e in zip('xyzw', exprs):
            g.par['vec%dvalue%s' % (k, letter)].expr = e
    for conn in g.inputConnectors:
        try:
            conn.disconnect()
        except Exception:
            pass
    g.par.tops = ' '.join(t.path for t in tops)
    return g


def build():
    keep = {}
    old = op(FX)
    x0, y0 = 0, 0
    lv = P.op('osmo_amount')
    if lv is not None:
        x0, y0 = lv.nodeX - 250, lv.nodeY - 200
    if old is not None:
        x0, y0 = old.nodeX, old.nodeY
        keep = {p.name: p.val for p in old.customPars if p.name != 'Motion'}
        old.destroy()
    fx = P.create(baseCOMP, 'osmo_fx')
    fx.nodeX, fx.nodeY = x0, y0
    fx.color = (0.2, 0.5, 0.3)

    pg = fx.appendCustomPage('Osmo')
    m = pg.appendMenu('Mode', label='Mode')[0]
    m.menuNames = ['kaleido', 'tunnel', 'both']
    m.menuLabels = ['Gear-cam kaleidoscope', 'Camera tunnel', 'Both']
    m.default = 'kaleido'
    m.val = 'kaleido'

    def fl(n, label, d, lo, hi):
        p = pg.appendFloat(n, label=label)[0]
        p.default, p.val, p.normMin, p.normMax = d, d, lo, hi
        return p
    s = pg.appendInt('Segments', label='Mirror segments')[0]
    s.default, s.val, s.normMin, s.normMax = 6, 6, 2, 16
    s.clampMin, s.min = True, 2
    fl('Spin', 'Spin (turns/s)', 0.03, 0, 0.3)
    fl('Zoom', 'Zoom', 1.0, 0.3, 3)
    fl('Gain', 'Camera brightness', 1.0, 0, 2)
    fl('Motiongain', 'Motion sensitivity', 10.0, 0, 40)
    fl('Motion', 'Motion (live)', 0.0, 0, 1)
    t = pg.appendToggle('Crowdlights', label='Motion lifts the lamps')[0]
    t.default, t.val = True, True
    for n, label, d in (('Cropl', 'Crop left', 0.0), ('Cropr', 'Crop right', 1.0),
                        ('Cropb', 'Crop bottom', 0.34), ('Cropt', 'Crop top', 0.66)):
        fl(n, label, d, 0, 1)
    for k, v in keep.items():
        if fx.par[k] is not None:
            try:
                fx.par[k].val = v
            except Exception:
                pass

    # camera (shared with the tunnel -- the Osmo can only be opened once)
    cam = fx.create(selectTOP, 'cam'); cam.nodeX, cam.nodeY = 0, 0
    cam.par.top = '/project1/geo_show/tunnel_cam'
    crop = fx.create(cropTOP, 'crop'); crop.nodeX, crop.nodeY = 150, 0
    crop.inputConnectors[0].connect(cam)
    for a, b in (('cropleft', 'Cropl'), ('cropright', 'Cropr'), ('cropbottom', 'Cropb'), ('croptop', 'Cropt')):
        crop.par[a].expr = 'parent().par.%s' % b

    # motion: tiny grey picture vs the one before it
    small = fx.create(resolutionTOP, 'small'); small.nodeX, small.nodeY = 150, -250
    small.inputConnectors[0].connect(crop); _res(small, 64, 36)
    mono = fx.create(monochromeTOP, 'mono'); mono.nodeX, mono.nodeY = 300, -250
    mono.inputConnectors[0].connect(small)
    mprev = fx.create(feedbackTOP, 'mprev'); mprev.nodeX, mprev.nodeY = 450, -350
    mprev.inputConnectors[0].connect(mono); mprev.par.top = 'mono'
    diff = fx.create(compositeTOP, 'diff'); diff.nodeX, diff.nodeY = 600, -250
    diff.par.operand = 'difference'
    diff.inputConnectors[0].connect(mono); diff.inputConnectors[1].connect(mprev)
    avg = fx.create(analyzeTOP, 'mavg'); avg.nodeX, avg.nodeY = 750, -250
    avg.inputConnectors[0].connect(diff); avg.par.op = 'average'
    tc = fx.create(topToCHOP, 'mraw'); tc.nodeX, tc.nodeY = 900, -250
    tc.par.top = 'mavg'
    mth = fx.create(mathCHOP, 'mgain'); mth.nodeX, mth.nodeY = 1050, -250
    mth.inputConnectors[0].connect(tc)
    mth.par.preoff = -0.012                                  # camera noise floor
    mth.par.gain.expr = 'parent().par.Motiongain'
    lim = fx.create(limitCHOP, 'mclamp'); lim.nodeX, lim.nodeY = 1200, -250
    lim.inputConnectors[0].connect(mth)
    _set(lim, 'type', 'clamp'); _set(lim, 'min', 0.0); _set(lim, 'max', 1.0)
    lag = fx.create(lagCHOP, 'mlag'); lag.nodeX, lag.nodeY = 1350, -250
    lag.inputConnectors[0].connect(lim)
    _set(lag, 'lag1', 0.08); _set(lag, 'lag2', 0.9)
    mo = fx.create(nullCHOP, 'motion'); mo.nodeX, mo.nodeY = 1500, -250
    mo.inputConnectors[0].connect(lag)
    fx.par.Motion.expr = "round(float(op('%s/motion')['r']), 3)" % FX

    # spin: turns per second (faster when there's movement), added up
    rate = fx.create(constantCHOP, 'spinrate'); rate.nodeX, rate.nodeY = 1050, -450
    rate.par.name0 = 'a'
    rate.par.value0.expr = "parent().par.Spin * 6.2832 * (1 + 3 * float(op('motion')['r']))"
    spd = fx.create(speedCHOP, 'angle'); spd.nodeX, spd.nodeY = 1200, -450
    spd.inputConnectors[0].connect(rate)

    feed = "op('/project1/hue_feed').par"
    kal = _glsl(fx, 'kal', KAL, [
        ('uA', ('parent().par.Segments', "float(op('angle')['a'])", 'parent().par.Zoom', feed + '.Akick')),
        ('uB', (feed + '.Alevel', "float(op('motion')['r'])", 'absTime.seconds', 'parent().par.Gain')),
    ], [crop], 300, 0)

    fb = fx.create(feedbackTOP, 'fb'); fb.nodeX, fb.nodeY = 450, 250
    fb.inputConnectors[0].connect(kal); fb.par.top = 'safe'
    kavg = fx.create(analyzeTOP, 'kal_avg'); kavg.nodeX, kavg.nodeY = 450, 100
    kavg.inputConnectors[0].connect(kal); kavg.par.op = 'average'
    favg = fx.create(analyzeTOP, 'fb_avg'); favg.nodeX, favg.nodeY = 600, 250
    favg.inputConnectors[0].connect(fb); favg.par.op = 'average'
    safe = _glsl(fx, 'safe', SAFE, [
        ('uL', ('0.06 * 60.0 / max(30.0, project.cookRate)',
                "0.8 * max(0.5, op('/project1/hue_feed').par.Guard) / (5.0 * max(30.0, project.cookRate))",
                '0.55', '0')),
    ], [kal, fb, kavg, favg], 750, 0)

    tsel = fx.create(selectTOP, 'tunnel'); tsel.nodeX, tsel.nodeY = 750, -100
    tsel.par.top = '/project1/null4'
    both = fx.create(compositeTOP, 'both'); both.nodeX, both.nodeY = 900, -100
    both.par.operand = 'screen'
    both.inputConnectors[0].connect(safe); both.inputConnectors[1].connect(tsel)
    pick = fx.create(switchTOP, 'pick'); pick.nodeX, pick.nodeY = 1050, 0
    for i, src in enumerate((safe, tsel, both)):
        pick.inputConnectors[i].connect(src)
    pick.par.index.expr = 'parent().par.Mode.menuIndex'
    out = fx.create(outTOP, 'out1'); out.nodeX, out.nodeY = 1200, 0
    out.inputConnectors[0].connect(pick)

    post = fx.create(executeDAT, 'post_motion'); post.nodeX, post.nodeY = 1500, -450
    post.text = POST
    _set(post, 'frameend', True); _set(post, 'active', True)

    # into the projector mix: osmo_amount (Opacity = how much Osmo) -> osmo_mix -> show_out
    if lv is not None:
        lv.inputConnectors[0].connect(fx.outputConnectors[0])
    # the tunnel uses the camera only when the Osmo is filming the wall
    g = P.op('geo_show')
    if g is not None and g.par['Usecam'] is not None:
        g.par.Usecam.expr = "op('%s').par.Mode.eval() != 'kaleido'" % FX
    errs = [str(e) for e in fx.errors(recurse=True)]
    return {'built': fx.path, 'errors': errs[:5], 'osmo_amount_in': [i.path for i in lv.inputs] if lv else None}
