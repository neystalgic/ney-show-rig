# build_vj.py -- the Push 2 VJ board (v1)
#
# Keeps Push 2 in Live mode: everything arrives as MIDI through the IAC Driver.
#   MIDI channel 16  = the "VJ" track in Ableton (an empty Drum Rack + CC Control)
#       bank 1  notes 36-51  16 visual decks (tap = morph to it; hold one + tap another = blend both)
#       bank 2  notes 52-59  ASCII, 8-bit, Mirror, Bold outline, Superflat, Hold, Blend mode, Trails
#               notes 60-63  transition: Melt, Zoom-through, Pixel dissolve, Radial wipe
#               notes 64-67  colour: Degree colours, Original, Rainbow, Duotone
#       bank 3  notes 68-79  key C ... B      notes 80-83  major / minor / dorian / mixolydian
#       knobs   CC 20-27     Morph time, Trails, Zoom, Spin, Colour amount, Cell size, Blend, Brightness
#   any other channel = the notes you play: every note colours the visuals by its step in the key
#       1 red 2 orange 3 yellow 4 green 5 blue 6 indigo 7 violet, the 1 an octave up = rainbow
#
# Every frame ends in the same flicker-safe pass as the tunnel (Flicker Guard from the hub).
# Run inside TouchDesigner:  exec(open(<this file>).read()); build()

P = op('/project1')
VJ = '/project1/vj'

DECKS = [
    # bank 1 (pads 1-16): your sacred geometry show first
    ('geo', '/project1/geo_show/out1'),            # the full sacred-geometry show (hub-synced, tunnel, audio)
    ('mix', '/project1/comp2'),                    # your own comp1 / comp2 mix (reaction diffusion over geometry)
    ('reaction', None), ('flower', '/project1/flower_of_life/out1'),
    ('metatron', '/project1/metatrons_cube/out1'), ('yantra', '/project1/sri_yantra/out1'),
    ('golden', '/project1/golden_angle/out1'), ('tesseract', '/project1/tesseract/out1'),
    ('chladni', '/project1/chladni/out1'), ('kaleido', '/project1/kaleidoscope/out1'),
    ('mandala', '/project1/proc_mandala/out1'), ('quasicrystal', '/project1/proc_quasicrystal/out1'),
    ('attractor', '/project1/proc_attractor/out1'), ('life8bit', '/project1/proc_life/out1'),
    ('superflat', None), ('boldline', None),
    # bank 4 (notes 84-91): more procedural pieces
    ('truchet', '/project1/proc_truchet/out1'), ('voronoi', '/project1/proc_voronoi/out1'),
    ('harmonograph', '/project1/proc_harmonograph/out1'), ('contours', '/project1/proc_contours/out1'),
    ('warp', '/project1/proc_warp/out1'), ('plasma', '/project1/mp_plasma/out1'),
    ('tunnel2d', '/project1/mp_tunnel/out1'), ('radar', '/project1/mp_radar/out1'),
    ('builder', None),                             # the 64 geometry recipes (all 64 Push pads)
]
FAMILIES = ['flower', 'metatron', 'yantra', 'golden', 'tesseract', 'chladni', 'quasicrystal', 'mandala']
LOOKS = ['clean', 'ascii', '8bit', 'outline', 'superflat', 'mirror']
OVERLAYS = ['none', 'flower', 'metatron', 'yantra', 'golden']   # sacred geometry laid over any deck (notes 92-95)

COMMON = r"""
vec3 hsv2rgb(vec3 c) { vec3 p = abs(fract(c.xxx + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
                       return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y); }
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y); }
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
"""

# ---- deck: flat flower field (original; inspired by the superflat style -- bold outlines, flat colour)
SUPERFLAT = r"""
uniform vec4 uA;   // time, kick, loudness, unused
out vec4 fragColor;
""" + COMMON + r"""
void main() {
    vec2 res = uTDOutputInfo.res.zw;
    float s = res.y / 3.0;
    vec2 g = vUV.st * res / s + vec2(uA.x * 0.04, 0.0);
    vec2 id = floor(g);
    vec2 f = fract(g) - 0.5;
    float h = hash(id);
    float dir = mod(id.x + id.y, 2.0) < 1.0 ? 1.0 : -1.0;
    float a = atan(f.y, f.x) + dir * uA.x * (0.06 + 0.08 * h);       // slow: crisp under the flicker-safe pass
    float r = length(f) / (0.85 + 0.15 * h) * (1.0 - 0.07 * uA.y);
    float petals = 12.0;
    float pr = 0.40 + 0.05 * cos(a * petals);
    float inner = 0.15 + 0.02 * uA.z;
    vec3 col = hsv2rgb(vec3(fract(h * 5.3 + 0.55), 0.12, 0.96));       // pale flat ground
    if (r < pr) {
        float pi = mod(floor(a * petals / 6.2831853 + 0.5), petals);
        col = hsv2rgb(vec3(fract(pi / petals + h), 0.85, 1.0));
    }
    if (r < inner) col = hsv2rgb(vec3(fract(h * 3.1 + 0.13), 0.95, 1.0));
    float sep = (r < pr && r > inner) ? abs(cos(a * petals * 0.5)) * r : 1.0;
    float line = min(min(abs(r - pr), abs(r - inner)), sep * 0.6);
    col = mix(vec3(0.02), col, smoothstep(0.010, 0.016, line));
    fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
"""

# ---- deck: bold line (original; inspired by street-art line work -- thick outlines, motion dashes)
BOLDLINE = r"""
uniform vec4 uA;   // time, kick, loudness, unused
out vec4 fragColor;
""" + COMMON + r"""
void main() {
    vec2 res = uTDOutputInfo.res.zw;
    vec2 uv = (vUV.st - 0.5) * vec2(res.x / res.y, 1.0);
    float t = uA.x;
    vec2 g = uv * 2.6 + vec2(0.0, t * 0.06);
    vec2 id = floor(g);
    vec2 f = fract(g) - 0.5;
    float h = hash(id);
    float a = atan(f.y, f.x);
    float rr = length(f);
    float br = 0.24 + 0.05 * sin(a * 3.0 + t * 1.3 + h * 6.0) + 0.03 * sin(a * 5.0 - t * 0.9) + 0.03 * uA.y;
    float d = rr - br;
    float era = floor(t / 8.0);
    vec3 bg = hsv2rgb(vec3(fract(era * 0.17 + 0.02), 0.9, 1.0));
    vec3 fill = hsv2rgb(vec3(fract(h + 0.5 + era * 0.17), 0.9, 1.0));
    vec3 col = d < 0.0 ? fill : bg;
    float outline = 1.0 - smoothstep(0.022, 0.03, abs(d));
    float seg = fract(a / 6.2831853 * 10.0 + h);
    float dr = br + 0.08 + 0.02 * sin(t * 2.0) + 0.04 * uA.y;
    float dash = step(abs(rr - dr), 0.035) * step(abs(seg - 0.5), 0.12);
    float zz = abs(fract(g.x * 2.0 + h) - 0.5) * 0.25;                 // zigzag along the cell bottoms
    float zig = (1.0 - smoothstep(0.012, 0.02, abs(f.y + 0.47 - zz))) * step(0.5, h);
    col = mix(col, vec3(0.02), max(max(outline, dash), zig));
    fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
"""

# ---- the recipe builder: one of 8 sacred families x 8 constructions, built out from the centre
BUILDER = r"""
uniform vec4 uV;   // variant 0-7, build progress 0-1, time, kick
uniform vec4 uS;   // spin, scale, loudness, unused
uniform vec4 uB;   // reveal style 0-7, seed, unused, unused
out vec4 fragColor;
float ASP;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y); }
vec3 samp(vec2 p) {
    vec2 uv = p / vec2(ASP, 1.0) + 0.5;
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) return vec3(0.0);
    return texture(sTD2DInputs[0], uv).rgb;
}
mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
vec2 fold(vec2 p, float n) {
    float a = atan(p.y, p.x), r = length(p), w = 6.2831853 / n;
    a = mod(a, w); a = abs(a - 0.5 * w);
    return r * vec2(cos(a), sin(a));
}
vec2 dir(float k) { float a = 6.2831853 * k; return vec2(cos(a), sin(a)); }
void main() {
    vec2 res = uTDOutputInfo.res.zw;
    ASP = res.x / res.y;
    vec2 p0 = (vUV.st - 0.5) * vec2(ASP, 1.0);
    float t = uV.z;
    int v = int(uV.x + 0.5);
    vec2 p = rot(t * uS.x) * p0 / max(uS.y, 0.1);
    vec3 c = vec3(0.0);
    if (v == 0) c = samp(p);                                              // the pure form
    else if (v == 1) c = samp(fold(p, 6.0));                             // six-fold
    else if (v == 2) {                                                   // seed of life: centre + 6
        c = samp(p * 2.0);
        for (int i = 0; i < 6; i++) c = max(c, samp((p - 0.25 * dir(float(i) / 6.0)) * 2.0));
    }
    else if (v == 3) c = samp(fold(p, 12.0) / 1.6);                      // twelve-fold, close up
    else if (v == 4) {                                                   // flower of forms: 1 + 6 + 12
        c = samp(p * 3.0);
        for (int i = 0; i < 6; i++) c = max(c, samp((p - 0.2 * dir(float(i) / 6.0)) * 3.0));
        for (int i = 0; i < 12; i++) c = max(c, samp((p - 0.38 * dir(float(i) / 12.0 + 1.0 / 24.0)) * 3.0));
    }
    else if (v == 5) {                                                   // two eight-fold wheels, counter-turning
        vec3 a = samp(fold(rot(t * 0.3) * p, 8.0));
        vec3 b = samp(fold(rot(-t * 0.45) * p * 1.3, 8.0));
        c = 1.0 - (1.0 - a) * (1.0 - b * 0.8);
    }
    else if (v == 6) {                                                   // golden-ratio nest, five deep
        for (int i = 0; i < 5; i++) {
            float k = pow(0.618, float(i));
            float sgn = (i - (i / 2) * 2) == 0 ? 1.0 : -1.0;
            c = max(c, samp(rot(t * 0.2 * sgn) * p / k) * (1.0 - 0.12 * float(i)));
        }
    }
    else c = samp(fold(p, 3.0));                                         // three-fold
    // BUILD: each recipe grows in its own way (so quick hits don't all bloom from the middle)
    float r = length(p0);
    float ang = atan(p0.y, p0.x) / 6.2831853 + 0.5;
    float L = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float nz = noise(p0 * 3.0 + uB.y * 7.31);
    int st = int(uB.x + 0.5);
    float q;
    if (st == 0) q = r / 0.95;                                   // out from the centre
    else if (st == 1) q = 1.0 - r / 0.95;                         // in from the edges (an iris closing)
    else if (st == 2) q = (ang + 2.0 * r) / 2.9;                  // a spiral sweep
    else if (st == 3) q = 0.55 * abs(fract(ang * 6.0) - 0.5) * 2.0 + 0.45 * r / 0.95;   // along six rays
    else if (st == 4) q = vUV.s;                                  // a wipe, left to right
    else if (st == 5) q = 0.7 * nz + 0.3 * r / 0.95;              // organic, like frost spreading
    else if (st == 6) q = 0.6 * (1.0 - clamp(L * 1.5, 0.0, 1.0)) + 0.4 * nz;   // the brightest lines first
    else q = 1.0 - vUV.t;                                         // a curtain, top to bottom
    float R = uV.y * 1.1;
    float m = smoothstep(R, R - 0.08, q);
    float front = exp(-pow((q - R) / 0.02, 2.0)) * (1.0 - uV.y);
    c = c * m + front * vec3(1.0, 0.92, 0.75) * 0.5;
    // alpha = how far the build has reached here: the mixer keeps the PREVIOUS picture where it hasn't yet,
    // so the old geometry stays on the wall and is overgrown by the new one instead of the wall going black
    fragColor = TDOutputSwizzle(vec4(c, clamp(max(m, front), 0.0, 1.0)));
}
"""

# ---- the morphing mixer: decks melt / zoom / dissolve / wipe into each other through feedback
MIXER = r"""
uniform vec4 uM;   // trails, zoom (0.5 = still), spin (0.5 = still), blend amount
uniform vec4 uT;   // transition progress (1 = done), type, time, blend mode
uniform vec4 uK;   // kick, loudness, melt, hue drift
uniform vec4 uF;   // hold, use the deck's alpha as a build mask, unused...
out vec4 fragColor;
""" + COMMON + r"""
vec3 hueRot(vec3 c, float a) { const vec3 k = vec3(0.57735); float ca = cos(a);
    return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca); }
void main() {
    vec2 uv = vUV.st;
    vec2 res = uTDOutputInfo.res.zw;
    float asp = res.x / res.y;
    if (uF.x > 0.5) { fragColor = TDOutputSwizzle(vec4(texture(sTD2DInputs[2], uv).rgb, 1.0)); return; }
    float prog = clamp(uT.x, 0.0, 1.0);
    float tr = 1.0 - prog;
    int ty = int(uT.y + 0.5);
    vec2 p = (uv - 0.5) * vec2(asp, 1.0);
    float z = 1.0 - (uM.y - 0.5) * 0.04 - (ty == 1 ? 0.035 * tr : 0.0) - 0.004 * uK.x;
    float an = (uM.z - 0.5) * 0.05;
    p = mat2(cos(an), -sin(an), sin(an), cos(an)) * p * z;
    float n1 = noise(uv * 4.0 + uT.z * 0.3), n2 = noise(uv * 4.0 + 17.3 - uT.z * 0.27);
    p += (vec2(n1, n2) - 0.5) * 0.02 * (uK.z * tr * (ty == 0 ? 1.0 : 0.0) + 0.15 * uM.x);
    vec3 prev = texture(sTD2DInputs[2], p / vec2(asp, 1.0) + 0.5).rgb;
    prev = hueRot(prev, uK.w);
    vec4 a0r = texture(sTD2DInputs[0], uv);
    vec3 a0 = a0r.rgb;
    float msk = uF.y > 0.5 ? clamp(a0r.a, 0.0, 1.0) : 1.0;
    vec3 l0 = texture(sTD2DInputs[1], uv).rgb;
    int bm = int(uT.w + 0.5);
    vec3 lay = bm == 0 ? 1.0 - (1.0 - a0) * (1.0 - l0) : (bm == 1 ? abs(a0 - l0) : max(a0, l0));
    vec3 cur = mix(a0, lay, uM.w);
    float keep = uM.x * 0.96;
    float tk = 0.0;
    if (ty == 0) tk = 0.97 * tr;
    else if (ty == 1) tk = 0.95 * tr;
    else if (ty == 2) { vec2 c = floor(uv * res / 8.0); tk = hash(c + 0.37) > prog ? 1.0 : 0.0; }
    else { float ang = atan(p.y, p.x) / 6.2831853 + 0.5; tk = ang > prog ? 1.0 : 0.0; }
    float k = max(max(keep, tk), 1.0 - msk);              // not built yet here: the old picture stays (and drifts)
    fragColor = TDOutputSwizzle(vec4(mix(cur, prev, k), 1.0));
}
"""

# ---- looks: degree colour, ASCII, 8-bit, mirror, bold outline, superflat
POST = r"""
uniform vec4 uP;   // ascii, 8-bit, outline, superflat
uniform vec4 uQ;   // mirror, cell size (px), colour amount, colour mode (0 degree 1 original 2 rainbow 3 duotone)
uniform vec4 uC;   // degree colour rgb, octave rainbow
uniform vec4 uR;   // brightness, time, kick, unused
uniform vec4 uO;   // overlay amount (0 = none), unused...
uniform vec4 uD;   // reaction diffusion amount (grows over the built geometry), unused...
out vec4 fragColor;
""" + COMMON + r"""
const int GLYPH[11] = int[11](0, 4, 131200, 14336, 1016800, 145536, 18157905, 22511061, 11512810, 15261199, 33554431);
vec2 RES;
vec3 src(vec2 fc) {
    vec2 uv = fc / RES;
    if (uQ.x > 0.5) uv = 0.5 - abs(uv - 0.5);
    vec3 base = texture(sTD2DInputs[0], uv).rgb;
    vec3 dr = texture(sTD2DInputs[2], uv).rgb;
    base = mix(base, max(base * 0.35, dr), clamp(uD.x, 0.0, 1.0));
    vec3 ov = texture(sTD2DInputs[1], uv).rgb * uO.x;          // sacred geometry, screened on top
    return 1.0 - (1.0 - base) * (1.0 - clamp(ov, 0.0, 1.0));
}
vec3 colour(vec3 c, vec2 uv) {
    float L = luma(c);
    vec3 tint = uC.w > 0.5 ? hsv2rgb(vec3(fract(uv.x * 0.6 + uv.y * 0.3 + uR.y * 0.15), 0.9, 1.0)) : uC.rgb;
    tint *= clamp(0.4 / max(luma(tint), 0.05), 0.85, 1.4);   // similar brightness for every degree: colour changes stay quick
    tint = min(tint, vec3(1.0));
    int m = int(uQ.w + 0.5);
    vec3 t = c;
    if (m == 0) t = tint * (0.12 + 1.25 * L);
    else if (m == 2) t = hsv2rgb(vec3(fract(L * 0.8 + uR.y * 0.1 + uv.x * 0.2), 0.85, 1.0)) * smoothstep(0.02, 0.4, L) * 1.15;
    else if (m == 3) t = mix(vec3(0.02), tint, smoothstep(0.12, 0.5, L));
    return mix(c, t, uQ.z);
}
float edge(vec2 fc, float w) {
    float tl = luma(src(fc + vec2(-w, w))), t = luma(src(fc + vec2(0, w))), tr = luma(src(fc + vec2(w, w)));
    float l = luma(src(fc + vec2(-w, 0))), r = luma(src(fc + vec2(w, 0)));
    float bl = luma(src(fc + vec2(-w, -w))), b = luma(src(fc + vec2(0, -w))), br = luma(src(fc + vec2(w, -w)));
    float gx = -tl - 2.0 * l - bl + tr + 2.0 * r + br;
    float gy = -bl - 2.0 * b - br + tl + 2.0 * t + tr;
    return length(vec2(gx, gy));
}
vec3 flat8(vec3 c) {                     // superflat: a few bright flat colours
    float L = luma(c);
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b));
    if (mx - mn < 0.08) return L < 0.33 ? vec3(0.03) : (L < 0.66 ? vec3(0.55) : vec3(0.97));
    vec3 hc = c - mn; hc /= max(mx - mn, 1e-4);
    float h = 0.0;
    if (mx == c.r) h = (hc.g - hc.b) / 6.0; else if (mx == c.g) h = (2.0 + hc.b - hc.r) / 6.0; else h = (4.0 + hc.r - hc.g) / 6.0;
    h = floor(fract(h) * 8.0 + 0.5) / 8.0;
    return hsv2rgb(vec3(h, 0.9, L < 0.15 ? 0.25 : 1.0));
}
void main() {
    RES = uTDOutputInfo.res.zw;
    vec2 fc = vUV.st * RES;
    float cell = max(3.0, uQ.y);
    bool ascii = uP.x > 0.5, bits = uP.y > 0.5, outl = uP.z > 0.5, flat_ = uP.w > 0.5;
    vec2 sfc = fc;
    if (ascii) sfc = (floor(fc / cell) + 0.5) * cell;
    else if (bits) sfc = (floor(fc / (cell * 0.6)) + 0.5) * cell * 0.6;
    vec3 c = colour(src(sfc), sfc / RES);
    if (flat_) c = flat8(c);
    if (bits) {                         // 4 levels a channel, ordered dither
        vec2 ip = mod(floor(fc / (cell * 0.6)), 4.0);
        int bi = int(ip.x) + int(ip.y) * 4;
        int bay[16] = int[16](0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5);
        float th = (float(bay[bi]) + 0.5) / 16.0 - 0.5;
        c = floor(clamp(c, 0.0, 1.0) * 3.0 + th * 0.9 + 0.5) / 3.0;
    }
    if (outl || flat_) {
        float e = edge(sfc, 2.0 + cell * 0.12);
        c = mix(c, vec3(0.02), smoothstep(0.18, 0.4, e));
    }
    if (ascii) {
        float L = luma(c);
        int gi = int(clamp(L * 1.15, 0.0, 0.999) * 11.0);
        vec2 lc = fract(fc / cell);
        int gx = int(lc.x * 6.0), gy = int((1.0 - lc.y) * 6.0);
        float on = 0.0;
        if (gx < 5 && gy < 5) on = float((GLYPH[gi] >> (24 - (gy * 5 + gx))) & 1);
        float mx = max(c.r, max(c.g, c.b));
        c = on * (c / max(mx, 0.25)) * 0.95;
    }
    fragColor = TDOutputSwizzle(vec4(clamp(c * uR.x, 0.0, 1.0), 1.0));
}
"""

# flicker-safe, two passes.
#  A: no pixel may change faster than the Flicker Guard allows (colour or brightness); never a white-out.
#  B: the picture's AVERAGE brightness may only glide at the Guard's overall rate -- done by shifting every pixel
#     by the same small amount, so new shapes appear straight away while the overall brightness fades in.
SAFE = r"""
uniform vec4 uL;   // per-pixel step, overall step (per frame), brightest average allowed, unused
out vec4 fragColor;
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
void main() {
    vec2 uv = vUV.st;
    vec3 t = texture(sTD2DInputs[0], uv).rgb;
    vec3 pr = texture(sTD2DInputs[1], uv).rgb;
    float lt = luma(texture(sTD2DInputs[2], vec2(0.5)).rgb);
    float cap = lt > uL.z ? uL.z / max(lt, 1e-5) : 1.0;
    fragColor = TDOutputSwizzle(vec4(clamp(pr + clamp(t * cap - pr, -uL.x, uL.x), 0.0, 1.0), 1.0));
}
"""

SAFE_B = r"""
uniform vec4 uL;   // per-pixel step, overall step (per frame), unused, unused
out vec4 fragColor;
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
void main() {
    vec2 uv = vUV.st;
    vec3 a = texture(sTD2DInputs[0], uv).rgb;
    vec3 pr = texture(sTD2DInputs[1], uv).rgb;
    float la = luma(texture(sTD2DInputs[2], vec2(0.5)).rgb);
    float lp = luma(texture(sTD2DInputs[3], vec2(0.5)).rgb);
    float dm = la - lp;
    float ex = dm - clamp(dm, -uL.y, uL.y);                    // the part of the average change that is too fast
    vec3 o = clamp(a - vec3(ex), pr - uL.x, pr + uL.x);
    fragColor = TDOutputSwizzle(vec4(clamp(o, 0.0, 1.0), 1.0));
}
"""

ENGINE = r"""
# vj engine: Push pads / knobs (MIDI channel 16) and the notes you play -> the VJ board
import time
VJC = op('/project1/vj')
KEYS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
SCALES = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10],
          'dorian': [0, 2, 3, 5, 7, 9, 10], 'mixolydian': [0, 2, 4, 5, 7, 9, 10]}
SCALE_PADS = ['major', 'minor', 'dorian', 'mixolydian']
DEG = [(1.0, 0.0, 0.0), (1.0, 0.35, 0.0), (1.0, 0.85, 0.0), (0.0, 1.0, 0.1), (0.0, 0.3, 1.0),
       (0.29, 0.0, 1.0), (0.62, 0.0, 1.0)]
TOGGLES = {52: 'Ascii', 53: 'Bits', 54: 'Mirror', 55: 'Outline', 56: 'Superflat'}
VJ_CHANNELS = (16,)
IDX_OFFSET = 1          # TouchDesigner's MIDI In DAT counts note / controller numbers from 1
held = []
_last = [time.time()]


def _p():
    return VJC.par


NAMES = __DECKS__


def deck(i):
    p = _p()
    i = int(i) % len(NAMES)
    if i == p.Deck.menuIndex:
        return
    p.Deck.menuIndex = i
    VJC.store('vj_t0', absTime.seconds)               # Progress (an expression) runs 0 -> 1 over Morph time
    rd = VJC.op('rd')
    if NAMES[i] == 'reaction' and rd is not None and rd.par['Reset'] is not None:   # a fresh pattern each time you pick it
        rd.par.Reset = True
        run("op('%s').par.Reset = False" % rd.path, delayFrames=3)
    life = op('/project1/proc_life')
    if life is not None:
        li = NAMES.index('life8bit')
        life.allowCooking = (i == li) or (p.Layer.menuIndex == li and p.Layeramt.eval() > 0)


def degree(note):
    p = _p()
    root, scale, home = p.Key.menuIndex, p.Scale.eval(), int(p.Home.eval())
    sc = SCALES.get(scale, SCALES['major'])
    iv = (note - root) % 12
    if iv in sc:
        d, half = sc.index(iv), 0.0
    else:
        d, half = max(k for k, x in enumerate(sc) if x < iv), 0.5
    home_root = home + ((root - home) % 12)
    if d == 0 and half == 0.0 and note >= home_root + 12:
        p.Rainbow = True
        p.Lastdegree = 8
        return
    a, b = DEG[d], DEG[(d + 1) % 7]
    c = [x + (y - x) * half for x, y in zip(a, b)]
    p.Rainbow = False
    p.Degcolr, p.Degcolg, p.Degcolb = c
    p.Lastdegree = d + 1


def deck_index(n):
    if 36 <= n <= 51:
        return n - 36
    if 84 <= n <= 91:
        return 16 + n - 84
    return None


def recipe(r):
    # one of the 64 recipes: row = family (bottom to top), column = construction (left to right)
    p = _p()
    r = int(r) % 64
    p.Recipe = r
    p.Family.menuIndex = r // 8
    p.Variant = r % 8
    now = absTime.seconds
    VJC.store('vj_dprev', float(p.Diffamt.eval()))   # the old diffusion fades out while the new form builds
    b = float(p.Build.eval())
    VJC.store('vj_bstart', b if b < 1.0 else 0.0)    # hit again mid-build: carry on growing, don't restart small
    VJC.store('vj_b0', now)                     # Build and Diffuse (expressions) start again
    VJC.store('vj_t0', now)                     # and the last picture melts into the new build
    bi = NAMES.index('builder')
    if p.Deck.menuIndex != bi:
        p.Deck.menuIndex = bi
    # (no reset: the reaction diffusion keeps living and simply grows into the new lines)


_raw = [None, 0.0]                              # the last pad pressed on Push (its real position, 36-99)


def push_note(n):
    _raw[0], _raw[1] = n, time.time()


def recipe_for(n, late=False):
    raw, t = _raw
    if raw is not None and 36 <= raw <= 99 and time.time() - t < 0.3:
        recipe(raw - 36)                        # the pad's place on the 8x8 grid, whatever Live's layout
    elif not late:
        run("op('%s').module.recipe_for(%d, True)" % (op('engine').path, n), delayFrames=2)
    else:
        recipe((n - 36) % 64)                   # no pad seen (a clip played it): use the note


def pad_on_old(n, vel):
    p = _p()
    if deck_index(n) is not None:
        i = deck_index(n)
        if held:
            p.Layer.menuIndex = held[-1]
            _layer(True)
        held.append(i)
        deck(i)
    elif n in TOGGLES:
        par = p[TOGGLES[n]]
        par.val = not par.eval()
    elif n == 57:
        p.Hold = True
    elif n == 58:
        p.Blend.menuIndex = (p.Blend.menuIndex + 1) % 3
    elif n == 59:
        p.Trailsburst = True
    elif 60 <= n <= 63:
        p.Transition.menuIndex = n - 60
    elif 64 <= n <= 67:
        p.Colourmode.menuIndex = n - 64
    elif 68 <= n <= 79:
        p.Key.menuIndex = n - 68
    elif 80 <= n <= 83:
        p.Scale.val = SCALE_PADS[n - 80]
    elif 92 <= n <= 95:                           # sacred geometry overlay: tap to lay it on, tap again to clear
        k = n - 91
        p.Overlay.menuIndex = 0 if p.Overlay.menuIndex == k else k


def pad_on(n, vel):
    recipe_for(n)


def pad_off(n):
    return


def pad_off_old(n):
    p = _p()
    if deck_index(n) is not None:
        i = deck_index(n)
        if i in held:
            held.remove(i)
        if len(held) < 2 and VJC.fetch('vj_layer_held', False, search=False):
            _layer(False)
    elif n == 57:
        p.Hold = False
    elif n == 59:
        p.Trailsburst = False


KNOBS = {20: ('Morph', 0.1, 8.0, 'exp'), 21: ('Trails', 0.0, 1.0, 'lin'), 22: ('Zoom', 0.0, 1.0, 'lin'),
         23: ('Spin', 0.0, 1.0, 'lin'), 24: ('Colouramt', 0.0, 1.0, 'lin'), 25: ('Cell', 4.0, 32.0, 'lin'),
         26: ('Blendknob', 0.0, 1.0, 'lin'), 27: ('Bright', 0.0, 1.2, 'lin')}


def knob(cc, v):
    k = KNOBS.get(cc)
    if not k:
        return
    name, lo, hi, curve = k
    x = max(0.0, min(1.0, v / 127.0))
    _p()[name] = lo * (hi / lo) ** x if curve == 'exp' else lo + (hi - lo) * x


def midi(message, channel, index, value):
    if absTime.seconds - VJC.fetch('vj_built', -100.0, search=False) < 1.5:
        return                                  # a new MIDI In DAT replays recent history: ignore it
    m = str(message).lower()
    try:
        ch, n, v = int(channel), int(index) - IDX_OFFSET, int(float(value))
    except Exception:
        return
    is_on = 'note on' in m and v > 0
    is_off = 'note off' in m or ('note on' in m and v == 0)
    if ch in VJ_CHANNELS:
        VJC.store('vj_mode_t', absTime.seconds)   # pads were just used: Push's knobs drive the VJ board
        if is_on:
            pad_on(n, v)
            degree(n)                             # the VJ track's notes colour the visuals too (lamps: the hub)
            VJC.store('vj_played_t', absTime.seconds)
            _p().Lastnote = n
        elif is_off:
            pad_off(n)
        elif 'control' in m:
            knob(n, v)
    elif is_on:
        if ch == 2:                               # a chord the audio brain HEARD in the mix (hub_brain.py)
            if absTime.seconds - VJC.fetch('vj_played_t', -100.0, search=False) < 6.0:
                return                            # you played something in the last 6 s: your notes win
        else:
            VJC.store('play_mode_t', absTime.seconds) # playing an instrument: Push's knobs belong to Live
            VJC.store('vj_played_t', absTime.seconds)
        degree(n)
        _p().Lastnote = n


# Push 2's eight track knobs (CC 71-78, relative) read straight from Push. They steer the VJ board while
# you're on the VJ track (you pressed a VJ pad more recently than you played a note).
# Push's 8 knobs above the screen = LIGHTING EFFECTS (the Hue Hub's live settings), while you're on the VJ track.
#   (key, low, high, curve)   curve: lin / exp / step (a menu: a few clicks = one step)
LIGHT_KNOBS = {
    71: ('master', 0.0, 1.0, 'lin'),       # 1 brightness
    72: ('deg_effect', 0, 0, 'step'),      # 2 effect: wash > glow > pulse > chase > sparkle > sweep > hit
    73: ('p_speed', 0, 0, 'speed'),        # 3 effect speed, on the beat grid: x1/4 x1/2 x1 x2 x4
    74: ('p_spread', 0.0, 1.0, 'lin'),     # 4 spread across the room
    75: ('a_amt', 0.0, 1.0, 'lin'),        # 5 beat punch (how hard the music pumps the lamps)
    76: ('p_release', 0, 0, 'fade'),       # 6 fade-out in beats: 1/4 1/2 1 2 4 8 (follows the tempo)
    77: ('sat', 0.0, 1.5, 'lin'),          # 7 vibrance
    78: ('smooth', 0.0, 1.0, 'lin'),       # 8 smoothing
}
EFFECTS = ['wash', 'glow', 'pulse', 'chase', 'sparkle', 'sweep', 'hit']
SPEEDS = [0.25, 0.5, 1.0, 2.0, 4.0]
FADES = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]          # beats


def _beat_s():
    try:
        return 60.0 / max(40.0, float(op('/project1/hue_feed').par.Tempo.eval()))
    except Exception:
        return 0.5
_acc = {}
_hub = {'live': {}, 'settings': {}, 't': 0.0, 'busy': False}
_pending = {}


def _hub_post(cmds):
    import json, urllib.request
    for c in cmds:
        try:
            rq = urllib.request.Request('http://localhost:7020/api', data=json.dumps(c).encode(),
                                        headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(rq, timeout=0.6).read()
        except Exception:
            pass


def _hub_refresh():
    import json, urllib.request
    try:
        S = json.loads(urllib.request.urlopen('http://localhost:7020/api/state', timeout=0.8).read())
        _hub['live'] = dict(S.get('live', {}))
        _hub['settings'] = dict(S.get('settings', {}))
        _hub['t'] = time.time()
    except Exception:
        pass
    _hub['busy'] = False


def _flush():
    # send what the knobs changed, at most ~20 times a second, off the main thread
    import threading
    cmds = list(_pending.values())
    _pending.clear()
    if cmds:
        threading.Thread(target=_hub_post, args=(cmds,), daemon=True).start()


def push_cc(message, channel, index, value):
    import threading
    if 'control' not in str(message).lower() or absTime.seconds - VJC.fetch('vj_built', -100.0, search=False) < 1.5:
        return
    try:
        cc, v = int(index) - IDX_OFFSET, int(float(value))
    except Exception:
        return
    if cc not in LIGHT_KNOBS:
        return
    if VJC.fetch('vj_mode_t', -100.0, search=False) <= VJC.fetch('play_mode_t', -50.0, search=False):
        return
    if time.time() - _hub['t'] > 5.0 and not _hub['busy']:      # keep a fresh copy of the hub's values
        _hub['busy'] = True
        threading.Thread(target=_hub_refresh, daemon=True).start()
    key, lo, hi, curve = LIGHT_KNOBS[cc]
    d = v if v < 64 else v - 128
    if curve in ('speed', 'fade'):                    # musical steps, a few clicks each
        a = _acc.get(cc, 0) + d
        if abs(a) >= 6:
            if curve == 'speed':
                cur = float(_hub['live'].get(key, 1.0))
                i = min(range(len(SPEEDS)), key=lambda j: abs(SPEEDS[j] - cur))
                i = max(0, min(len(SPEEDS) - 1, i + (1 if a > 0 else -1)))
                val, label = SPEEDS[i], 'Speed x%s' % ('1/%d' % round(1 / SPEEDS[i]) if SPEEDS[i] < 1 else '%d' % SPEEDS[i])
            else:
                bs = _beat_s()
                cur = float(_hub['live'].get(key, 0.4)) / bs
                i = min(range(len(FADES)), key=lambda j: abs(FADES[j] - cur))
                i = max(0, min(len(FADES) - 1, i + (1 if a > 0 else -1)))
                val, label = min(4.0, max(0.02, FADES[i] * bs)), 'Fade %s beats' % FADES[i]
            _hub['live'][key] = val
            _pending[key] = {'op': 'live', 'key': key, 'value': round(val, 4)}
            VJC.store('vj_light_msg', label)
            a = 0
        _acc[cc] = a
    elif curve == 'step':
        a = _acc.get(cc, 0) + d
        if abs(a) >= 6:
            cur = _hub['settings'].get(key, 'wash')
            i = EFFECTS.index(cur) if cur in EFFECTS else 0
            i = max(0, min(len(EFFECTS) - 1, i + (1 if a > 0 else -1)))
            _hub['settings'][key] = EFFECTS[i]
            _pending[key] = {'op': 'setting', 'key': key, 'value': EFFECTS[i]}
            # patterns on, so the effect rows really move (wash still just fills the room)
            _pending['p_patterns'] = {'op': 'live', 'key': 'p_patterns', 'value': 0.0 if EFFECTS[i] == 'wash' else 1.0}
            VJC.store('vj_light_msg', 'Effect: ' + EFFECTS[i])
            a = 0
        _acc[cc] = a
    else:
        import math
        x = float(_hub['live'].get(key, lo if curve == 'lin' else math.sqrt(lo * hi)))
        step = d / 200.0
        if curve == 'exp':
            f = math.log(max(x, lo) / lo) / math.log(hi / lo)
            x = lo * (hi / lo) ** max(0.0, min(1.0, f + step))
        else:
            x = max(lo, min(hi, x + step * (hi - lo)))
        _hub['live'][key] = x
        _pending[key] = {'op': 'live', 'key': key, 'value': round(x, 4)}
        VJC.store('vj_light_msg', '%s %.2f' % (key, x))
    last = VJC.fetch('vj_flush_t', 0.0, search=False)
    if time.time() - last > 0.05:
        VJC.store('vj_flush_t', time.time())
        _flush()
    else:
        run("op('%s').module._flush()" % op('engine').path, delayFrames=3)


def push_midi(message, channel, index, value):
    m = str(message).lower()
    try:
        if 'note on' in m and float(value) > 0:
            push_note(int(index) - IDX_OFFSET)
            return
    except Exception:
        return
    push_cc(message, channel, index, value)


def _layer(on):
    # Blend now (an expression) glides from where it is to the Blend knob (or to 0) in 0.3 s
    VJC.store('vj_lay_from', float(VJC.par.Layeramt.eval()))
    VJC.store('vj_lay_t', absTime.seconds)
    VJC.store('vj_layer_held', on)
"""

PUSH_CB = r"""
def onReceiveMIDI(dat, rowIndex, message, channel, index, value, *rest):
    op('engine').module.push_midi(message, channel, index, value)
    return
"""

MIDI_CB = r"""
def onReceiveMIDI(dat, rowIndex, message, channel, index, value, *rest):
    op('engine').module.midi(message, channel, index, value)
    return
"""




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
    if tops:
        g.par.tops = ' '.join(t.path for t in tops)
    return g


def _midi_device(name='Online IAC Driver Bus 1', out=True):
    d = op('/local/midi/device')
    for r in range(1, d.numRows):
        if d[r, 'indevice'] is not None and d[r, 'indevice'].val == name:
            return int(d[r, 'id'].val)
    ids = [int(d[r, 'id'].val) for r in range(1, d.numRows) if d[r, 'id'].val.isdigit()]
    nid = max(ids + [0]) + 1
    d.appendRow([str(nid), name, name if out else '', '', ''])
    return nid


def _pars(vj, keep):
    pg = vj.appendCustomPage('VJ')
    def menu(n, label, names, labels=None, d=0):
        p = pg.appendMenu(n, label=label)[0]
        p.menuNames = names
        p.menuLabels = labels or names
        p.default = names[d]
        p.val = names[d]
        return p
    def fl(n, label, d, lo, hi, page=pg):
        p = page.appendFloat(n, label=label)[0]
        p.default, p.val, p.normMin, p.normMax = d, d, lo, hi
        return p
    def tg(n, label, d=False, page=pg):
        p = page.appendToggle(n, label=label)[0]
        p.default, p.val = d, d
        return p
    names = [d[0] for d in DECKS]
    menu('Deck', 'Deck (pads 1-16)', names)
    menu('Layer', 'Blend deck (hold 2 pads)', names + ['none'], d=len(names))
    menu('Overlay', 'Sacred geometry overlay', OVERLAYS)
    p = pg.appendInt('Recipe', label='Recipe (pad 0-63)')[0]
    p.normMin, p.normMax = 0, 63
    menu('Family', 'Family (pad row)', FAMILIES)
    p = pg.appendInt('Variant', label='Construction (pad column)')[0]
    p.normMin, p.normMax = 0, 7
    fl('Buildbars', 'Build time (bars)', 1.0, 0.25, 8)
    fl('Diffuse', 'Diffuse (reaction diffusion after the build)', 0.6, 0, 1)
    fl('Diffusebars', 'Diffuse time (bars)', 4.0, 0.5, 16)
    fl('Buildspin', 'Build spin', 0.05, 0, 0.5)
    fl('Buildscale', 'Build scale', 1.0, 0.3, 3)
    menu('Look', 'Look (knob 5)', LOOKS)
    fl('Overlayamt', 'Overlay amount', 0.7, 0, 1)
    fl('Morph', 'Morph time (s)', 1.5, 0.1, 8)
    fl('Trails', 'Trails / feedback', 0.08, 0, 1)
    fl('Zoom', 'Feedback zoom (0.5 = still)', 0.55, 0, 1)
    fl('Spin', 'Feedback spin (0.5 = still)', 0.5, 0, 1)
    fl('Colouramt', 'Colour amount', 0.85, 0, 1)
    fl('Cell', 'ASCII / pixel size', 12, 4, 32)
    fl('Blendknob', 'Blend amount', 0.5, 0, 1)
    fl('Bright', 'Brightness', 1.0, 0, 1.2)
    menu('Transition', 'Transition', ['melt', 'zoom', 'dissolve', 'wipe'],
         ['Melt', 'Zoom-through', 'Pixel dissolve', 'Radial wipe'])
    menu('Colourmode', 'Colour', ['degree', 'original', 'rainbow', 'duotone'],
         ['Degree colours', 'Original', 'Rainbow', 'Duotone'])
    menu('Blend', 'Blend mode', ['screen', 'difference', 'lighten'])
    tg('Ascii', 'ASCII')
    tg('Bits', '8-bit')
    tg('Mirror', 'Mirror')
    tg('Outline', 'Bold outline')
    tg('Superflat', 'Superflat')
    tg('Hold', 'Hold (freeze)')
    tg('Trailsburst', 'Trails burst')
    menu('Key', 'Key', ['C', 'Cs', 'D', 'Ds', 'E', 'F', 'Fs', 'G', 'Gs', 'A', 'As', 'B'],
         ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'])
    menu('Scale', 'Scale', ['major', 'minor', 'dorian', 'mixolydian'])
    p = pg.appendInt('Home', label='Home octave (note of the red 1)')[0]
    p.default, p.val = 60, 60
    fl('Takeover', 'VJ board on the projector (0 = your mix)', 1.0, 0, 1)
    st = vj.appendCustomPage('State')
    fl('Progress', 'Transition progress', 1.0, 0, 1, st)
    fl('Layeramt', 'Blend now', 0.0, 0, 1, st)
    fl('Build', 'Build progress', 1.0, 0, 1, st)
    fl('Diffamt', 'Diffuse now', 0.0, 0, 1, st)
    rgb = st.appendRGB('Degcol', label='Degree colour')
    for q, v in zip(rgb, (1.0, 0.0, 0.0)):
        q.default, q.val = v, v
    tg('Rainbow', 'Octave rainbow', False, st)
    q = st.appendInt('Lastdegree', label='Last degree')[0]
    q = st.appendInt('Lastnote', label='Last note')[0]
    for k, v in keep.items():
        if vj.par[k] is not None:
            try:
                vj.par[k].val = v
            except Exception:
                pass


def build():
    keep = {}
    old = op(VJ)
    x0, y0 = P.op('comp2').nodeX, P.op('comp2').nodeY - 300
    if old is not None:
        x0, y0 = old.nodeX, old.nodeY
        keep = {p.name: p.val for p in old.customPars if p.page.name == 'VJ'}
        old.destroy()
    vj = P.create(baseCOMP, 'vj')
    vj.nodeX, vj.nodeY = x0, y0
    vj.color = (0.6, 0.25, 0.5)
    _pars(vj, keep)
    feed = "op('/project1/hue_feed').par"

    # decks
    sel = []
    for i, (name, path) in enumerate(DECKS):
        x, y = 0, -i * 120
        if name == 'superflat':
            t = _glsl(vj, 'superflat', SUPERFLAT, [('uA', ('absTime.seconds', feed + '.Akick', feed + '.Alevel', '0'))],
                      [], -300, y)
        elif name == 'reaction':
            # its own copy of your reaction diffusion (your comp1 / comp2 mix keeps the original)
            src = op('/project1/reaction_diffusion')
            rd = vj.copy(src, name='rd')
            rd.nodeX, rd.nodeY = -450, y
            seed = vj.create(selectTOP, 'rd_seed')            # grows out of the flower of life's lines
            seed.nodeX, seed.nodeY = -600, y
            seed.par.top = '/project1/vj/builder'          # grows out of whatever recipe was just built
            edge = vj.create(edgeTOP, 'rd_edge')            # seed from the flower's lines, not its glow
            edge.nodeX, edge.nodeY = -525, y + 60
            edge.inputConnectors[0].connect(seed)
            rd.inputConnectors[0].connect(edge)
            t = vj.create(selectTOP, 'deck_reaction')
            t.nodeX, t.nodeY = -150, y
            t.par.top = 'rd/out1'
        elif name == 'builder':
            fam = vj.create(switchTOP, 'family')
            fam.nodeX, fam.nodeY = -450, y
            names_ = [d[0] for d in DECKS]
            for k, nm in enumerate(FAMILIES):
                fam.inputConnectors[k].connect(sel[names_.index(nm)])
            fam.par.index.expr = 'parent().par.Family.menuIndex'
            t = _glsl(vj, 'builder', BUILDER, [
                ('uV', ('parent().par.Variant', 'parent().par.Build', 'absTime.seconds', feed + '.Akick')),
                ('uS', ('parent().par.Buildspin', 'parent().par.Buildscale', feed + '.Alevel', '0')),
                ('uB', ('(parent().par.Family.menuIndex * 3 + parent().par.Variant) % 8', 'parent().par.Recipe', '0', '0')),
            ], [fam], -300, y)
        elif name == 'boldline':
            t = _glsl(vj, 'boldline', BOLDLINE, [('uA', ('absTime.seconds', feed + '.Akick', feed + '.Alevel', '0'))],
                      [], -300, y)
        else:
            t = vj.create(selectTOP, 'deck_' + name)
            t.nodeX, t.nodeY = x - 150, y
            t.par.top = path
            if name == 'life8bit':                      # crisp big pixels
                big = vj.create(resolutionTOP, 'life_px')
                big.nodeX, big.nodeY = x, y
                big.inputConnectors[0].connect(t)
                _res(big, 1280, 800)
                _set(big, 'inputfiltertype', 'nearest')
                t = big
        sel.append(t)
    black = vj.create(constantTOP, 'black')
    black.nodeX, black.nodeY = 0, -len(DECKS) * 120
    _res(black, 1280, 800)
    _set(black, 'colorr', 0); _set(black, 'colorg', 0); _set(black, 'colorb', 0)
    main = vj.create(switchTOP, 'main')
    main.nodeX, main.nodeY = 300, -500
    layer = vj.create(switchTOP, 'layer')
    layer.nodeX, layer.nodeY = 300, -900
    for i, t in enumerate(sel):
        main.inputConnectors[i].connect(t)
        layer.inputConnectors[i].connect(t)
    layer.inputConnectors[len(DECKS)].connect(black)
    ov = vj.create(switchTOP, 'overlay')                   # sacred geometry over whatever is playing
    ov.nodeX, ov.nodeY = 300, -1300
    ov.inputConnectors[0].connect(black)
    for k, nm in enumerate(OVERLAYS[1:]):
        ov.inputConnectors[k + 1].connect(sel[[d[0] for d in DECKS].index(nm)])
    ov.par.index.expr = 'parent().par.Overlay.menuIndex'
    main.par.index.expr = 'parent().par.Deck.menuIndex'
    layer.par.index.expr = 'parent().par.Layer.menuIndex if parent().par.Layeramt > 0 else %d' % len(DECKS)

    fb = vj.create(feedbackTOP, 'fb')
    fb.nodeX, fb.nodeY = 450, -300
    fb.inputConnectors[0].connect(main)
    mixer = _glsl(vj, 'mixer', MIXER, [
        ('uM', ("0.92 if parent().par.Trailsburst else parent().par.Trails", 'parent().par.Zoom', 'parent().par.Spin',
                'parent().par.Layeramt')),
        ('uT', ('parent().par.Progress', 'parent().par.Transition.menuIndex', 'absTime.seconds',
                'parent().par.Blend.menuIndex')),
        ('uK', (feed + '.Akick', feed + '.Alevel', '1.0', '0.002 + 0.004 * parent().par.Trails')),
        ('uF', ('1 if parent().par.Hold else 0', "1 if parent().par.Deck.eval() == 'builder' else 0", '0', '0')),
    ], [main, layer, fb], 600, -500)
    fb.par.top = 'mixer'
    _set(fb, 'format', 'rgba16float')

    rdg = vj.create(switchTOP, 'rd_gate')                  # the diffusion only runs while it's showing
    rdg.nodeX, rdg.nodeY = 750, -800
    rdg.inputConnectors[0].connect(black)
    rdg.inputConnectors[1].connect(vj.op('deck_reaction'))
    rdg.par.index.expr = '1 if parent().par.Diffamt > 0.002 else 0'
    post = _glsl(vj, 'post', POST, [
        ('uP', ('parent().par.Ascii', 'parent().par.Bits', 'parent().par.Outline', 'parent().par.Superflat')),
        ('uQ', ('parent().par.Mirror', 'parent().par.Cell', 'parent().par.Colouramt', 'parent().par.Colourmode.menuIndex')),
        ('uC', ('parent().par.Degcolr', 'parent().par.Degcolg', 'parent().par.Degcolb', 'parent().par.Rainbow')),
        ('uR', ('parent().par.Bright', 'absTime.seconds', feed + '.Akick', '0')),
        ('uO', ("(parent().par.Overlayamt * (0.8 + 0.2 * %s.Akick)) if parent().par.Overlay.menuIndex > 0 else 0" % feed,
                '0', '0', '0')),
        ('uD', ('parent().par.Diffamt', '0', '0', '0')),
    ], [mixer, ov, rdg], 900, -500)

    sfb = vj.create(feedbackTOP, 'safe_fb')
    sfb.nodeX, sfb.nodeY = 1050, -250
    sfb.inputConnectors[0].connect(post)
    pavg = vj.create(analyzeTOP, 'post_avg')
    pavg.nodeX, pavg.nodeY = 1050, -650
    psm = vj.create(resolutionTOP, 'post_avg_small')      # average a small copy: same answer, far cheaper
    psm.nodeX, psm.nodeY = 950, -650
    psm.inputConnectors[0].connect(post); _res(psm, 80, 50); _set(psm, 'format', 'rgba16float')
    pavg.inputConnectors[0].connect(psm); pavg.par.op = 'average'
    savg = vj.create(analyzeTOP, 'prev_avg')
    savg.nodeX, savg.nodeY = 1200, -250
    ssm = vj.create(resolutionTOP, 'prev_avg_small')
    ssm.nodeX, ssm.nodeY = 1100, -330
    ssm.inputConnectors[0].connect(sfb); _res(ssm, 80, 50); _set(ssm, 'format', 'rgba16float')
    savg.inputConnectors[0].connect(ssm); savg.par.op = 'average'
    guard = "max(0.5, op('/project1/hue_feed').par.Guard)"
    step = '2.0 * %s / max(30.0, project.cookRate)' % guard           # a full swing takes >= 1 / (2 x Guard) s
    overall = '0.8 * %s / (5.0 * max(30.0, project.cookRate))' % guard
    safe = _glsl(vj, 'safe', SAFE, [('uL', (step, overall, '0.55', '0'))], [post, sfb, pavg], 1350, -500)
    asm = vj.create(resolutionTOP, 'safe_avg_small')
    asm.nodeX, asm.nodeY = 1350, -700
    asm.inputConnectors[0].connect(safe); _res(asm, 80, 50); _set(asm, 'format', 'rgba16float')
    aavg = vj.create(analyzeTOP, 'safe_avg')
    aavg.nodeX, aavg.nodeY = 1500, -700
    aavg.inputConnectors[0].connect(asm); aavg.par.op = 'average'
    safe2 = _glsl(vj, 'safe2', SAFE_B, [('uL', (step, overall, '0', '0'))], [safe, sfb, aavg, savg], 1650, -500)
    sfb.par.top = 'safe2'
    _set(sfb, 'format', 'rgba16float')
    out = vj.create(outTOP, 'out1')
    out.nodeX, out.nodeY = 1800, -500
    out.inputConnectors[0].connect(safe2)

    # brains
    eng = vj.create(textDAT, 'engine')
    eng.nodeX, eng.nodeY = 300, 300
    eng.text = ENGINE.replace('__DECKS__', repr([d[0] for d in DECKS]))
    cb = vj.create(textDAT, 'midi_cb')
    cb.nodeX, cb.nodeY = 600, 450
    cb.text = MIDI_CB
    mi = vj.create(midiinDAT, 'midi_in')
    mi.nodeX, mi.nodeY = 600, 300
    mi.par.id = _midi_device()
    mi.par.callbacks = 'midi_cb'
    vj.store('vj_built', absTime.seconds)
    pc = vj.create(textDAT, 'push_cb')
    pc.nodeX, pc.nodeY = 900, 450
    pc.text = PUSH_CB
    pm = vj.create(midiinDAT, 'push_in')                    # Push's knobs, read alongside Ableton
    pm.nodeX, pm.nodeY = 900, 300
    pm.par.id = _midi_device('Ableton Push 2 Live Port', out=False)
    pm.par.callbacks = 'push_cb'
    bar = "(240.0 / max(60.0, op('/project1/hue_feed').par.Tempo.eval()))"
    vj.par.Build.expr = ("min(1.0, me.fetch('vj_bstart', 0.0, search=False) + (absTime.seconds - me.fetch('vj_b0', -100.0, search=False)) / "
                         "max(0.05, me.par.Buildbars.eval() * %s))" % bar)
    vj.par.Diffamt.expr = ("(me.par.Deck.eval() == 'builder') * max(me.fetch('vj_dprev', 0.0, search=False) * (1.0 - me.par.Build.eval()), "
                           "me.par.Diffuse.eval() * max(0.0, min(1.0, (absTime.seconds - me.fetch('vj_b0', -100.0, search=False)"
                           " - me.par.Buildbars.eval() * %s) / max(0.05, me.par.Diffusebars.eval() * %s))))" % (bar, bar))
    for par_, look in (('Ascii', 'ascii'), ('Bits', '8bit'), ('Outline', 'outline'), ('Superflat', 'superflat'),
                       ('Mirror', 'mirror')):
        vj.par[par_].expr = "me.par.Look.eval() == '%s'" % look
    # transition + blend glide: expressions on absTime (no frame callbacks needed)
    vj.par.Progress.expr = "min(1.0, (absTime.seconds - me.fetch('vj_t0', -100.0, search=False)) / max(0.05, me.par.Morph.eval()))"
    vj.par.Layeramt.expr = ("me.fetch('vj_lay_from', 0.0, search=False) + ((me.par.Blendknob.eval() if me.fetch('vj_layer_held', False, search=False) else 0.0)"
                            " - me.fetch('vj_lay_from', 0.0, search=False)) * min(1.0, (absTime.seconds - me.fetch('vj_lay_t', -100.0, search=False)) / 0.3)")

    # into the projector chain: comp2 -> vj_xfade (Takeover) -> osmo_mix -> show_out
    xf = P.op('vj_xfade') or P.create(crossTOP, 'vj_xfade')
    om = P.op('osmo_mix')
    c2 = P.op('comp2')
    xf.nodeX, xf.nodeY = c2.nodeX + 150, c2.nodeY - 150
    xf.inputConnectors[0].connect(c2)
    xf.inputConnectors[1].connect(vj.outputConnectors[0])
    xf.par.cross.expr = "op('%s').par.Takeover" % VJ
    pk = P.op('vj_pick') or P.create(switchTOP, 'vj_pick')   # only cooks what's on screen
    pk.nodeX, pk.nodeY = xf.nodeX + 150, xf.nodeY
    pk.inputConnectors[0].connect(c2)
    pk.inputConnectors[1].connect(xf)
    pk.inputConnectors[2].connect(vj.outputConnectors[0])
    pk.par.index.expr = ("0 if op('%s').par.Takeover <= 0.001 else (2 if op('%s').par.Takeover >= 0.999 else 1)"
                         % (VJ, VJ))
    if om is not None:
        om.inputConnectors[0].connect(pk)
    g = P.op('geo_show')                                 # the geo deck keeps its tunnel
    if g is not None and g.par['Tunnel'] is not None and g.par.Tunnel.mode == ParMode.EXPRESSION:
        g.par.Tunnel.expr = ''
        g.par.Tunnel.val = True
    errs = [o.path + ': ' + str(e) for o in vj.findChildren() for e in ([o.errors()] if o.errors() else [])]
    return {'built': vj.path, 'midi_id': mi.par.id.eval(), 'errors': errs[:8]}
