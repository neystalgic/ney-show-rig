const int OCT[13] = int[13](0, 5, 4, 3, 5, 1, 3, 2, 4, 0, 2, 1, 0);
const int C16[25] = int[25](0, 7, 6, 5, 7, 4, 6, 3, 5, 4, 3, 2, 7, 1, 6, 0, 5, 2, 4, 1, 3, 0, 2, 1, 0);
const int TES[33] = int[33](0, 8, 12, 14, 15, 13, 12, 4, 6, 14, 10, 11, 15, 7, 6, 2, 10, 8, 9, 13, 5, 7, 3, 11, 9, 1, 5, 4, 0, 2, 3, 1, 0);
const int C5[11] = int[11](0, 4, 3, 2, 4, 1, 3, 0, 2, 1, 0);
const int C24[97] = int[97](0, 18, 23, 19, 22, 18, 14, 23, 15, 21, 17, 20, 16, 21, 14, 16, 12, 22, 13, 20, 12, 18, 11, 23, 10, 22, 11, 19, 15, 17, 13, 19, 10, 18, 1, 16, 9, 21, 8, 20, 9, 17, 8, 16, 0, 14, 7, 23, 6, 21, 7, 15, 6, 14, 1, 12, 5, 22, 4, 20, 5, 13, 4, 12, 0, 10, 6, 8, 4, 10, 2, 19, 3, 17, 2, 15, 3, 11, 7, 9, 5, 11, 1, 9, 3, 7, 1, 5, 3, 13, 2, 8, 0, 6, 2, 4, 0);
// Sacred line (Nov 9): ONE continuous line that travels. It draws a sacred form, turns slowly,
// then unravels from its tail and re-weaves itself into the next form.
// Polytopes are traced as a single unbroken path (an Euler circuit: every edge exactly once).
// uM = shape A, shape B, warp 0-1, draw-on 0-1      uR = 4D angle, 3D angle, time, unused
const float TAU = 6.28318530718;

vec4 axisV(int k, int n) { vec4 v = vec4(0.0); v[k % n] = (k < n) ? 1.0 : -1.0; return v; }
vec4 bitV(int i) { return vec4((i & 1) != 0 ? 1.0 : -1.0, (i & 2) != 0 ? 1.0 : -1.0, (i & 4) != 0 ? 1.0 : -1.0, (i & 8) != 0 ? 1.0 : -1.0); }
vec4 c24V(int k) {
    int pr = k / 4, sg = k % 4; int a = 0, b = 1;
    if (pr == 1) { a = 0; b = 2; } else if (pr == 2) { a = 0; b = 3; } else if (pr == 3) { a = 1; b = 2; }
    else if (pr == 4) { a = 1; b = 3; } else if (pr == 5) { a = 2; b = 3; }
    vec4 v = vec4(0.0); v[a] = (sg & 1) != 0 ? 1.0 : -1.0; v[b] = (sg & 2) != 0 ? 1.0 : -1.0; return v;
}
vec4 c5V(int k) {
    float r5 = 1.0 / sqrt(5.0);
    if (k == 0) return vec4(1, 1, 1, -r5); if (k == 1) return vec4(1, -1, -1, -r5);
    if (k == 2) return vec4(-1, 1, -1, -r5); if (k == 3) return vec4(-1, -1, 1, -r5);
    return vec4(0, 0, 0, sqrt(5.0) - r5);
}

// shape s at arc position x (0-1). w = the 4th coordinate (0 for 3D forms)
vec4 path(int s, float x) {
    x = clamp(x, 0.0, 0.99999);
    if (s == 0) { float e = x * 10.0; int i = int(e); return mix(c5V(C5[i]), c5V(C5[i + 1]), fract(e)) * 1.35; }      // 5-cell
    if (s == 1) { float e = x * 12.0; int i = int(e); return mix(axisV(OCT[i], 3), axisV(OCT[i + 1], 3), fract(e)) * 2.2; } // octahedron
    if (s == 2) { float e = x * 32.0; int i = int(e); return mix(bitV(TES[i]), bitV(TES[i + 1]), fract(e)) * 0.82; }    // tesseract
    if (s == 3) { float t = TAU * x; float r = 1.7 + 0.75 * cos(8.0 * t);                                              // torus knot (3, 8)
                  return vec4(r * cos(3.0 * t), r * sin(3.0 * t), 0.75 * sin(8.0 * t), 0.0); }
    if (s == 4) { float t = TAU * x;                                                                              // hypotrochoid flower, 6-fold
                  float R = 3.0, r = 0.5, d = 1.55;
                  vec2 p = vec2((R - r) * cos(t) + d * cos((R - r) / r * t), (R - r) * sin(t) - d * sin((R - r) / r * t));
                  return vec4(p * 0.62, 0.45 * sin(6.0 * t), 0.0); }
    if (s == 5) { float e = x * 24.0; int i = int(e); return mix(axisV(C16[i], 4), axisV(C16[i + 1], 4), fract(e)) * 1.7; } // 16-cell
    if (s == 6) { float lat = (x - 0.5) * 3.04; float lon = 13.0 * TAU * x * 0.618034;                                  // golden loxodrome sphere
                  return vec4(cos(lat) * cos(lon), sin(lat), cos(lat) * sin(lon), 0.0) * 2.1; }
    if (s == 7) { float e = x * 96.0; int i = int(e); return mix(c24V(C24[i]), c24V(C24[i + 1]), fract(e)) * 1.15; }  // 24-cell
    float t = TAU * x;                                                                                                   // Lissajous knot (3, 2, 7)
    return vec4(1.8 * cos(3.0 * t + 0.7), 1.8 * cos(2.0 * t + 0.2), 1.1 * cos(7.0 * t), 0.0);
}

bool is4D(int s) { return s == 0 || s == 2 || s == 5 || s == 7; }

vec3 place(vec4 p, int s) {
    if (is4D(s)) {                                     // turn through the 4th dimension (XW + YZ), then perspective into 3D
        float c = cos(uR.x), sn = sin(uR.x); p = vec4(c * p.x - sn * p.w, p.y, p.z, sn * p.x + c * p.w);
        float c2 = cos(uR.x * 0.618), s2 = sin(uR.x * 0.618); p = vec4(p.x, c2 * p.y - s2 * p.z, s2 * p.y + c2 * p.z, p.w);
        return p.xyz * (3.0 / (3.0 - p.w)) * 1.4;
    }
    if (s == 3 || s == 4) {                            // flat-ish curves: spin in their own plane, held at a gentle tilt
        float c = cos(uR.y), sn = sin(uR.y);
        vec3 q = vec3(c * p.x - sn * p.y, sn * p.x + c * p.y, p.z);
        float ct = cos(0.42), st = sin(0.42);
        return vec3(q.x, ct * q.y - st * q.z, st * q.y + ct * q.z);
    }
    float c = cos(uR.y), sn = sin(uR.y);                // 3D forms turn slowly about two axes
    vec3 q = vec3(c * p.x + sn * p.z, p.y, -sn * p.x + c * p.z);
    float c2 = cos(uR.y * 0.5), s2 = sin(uR.y * 0.5);
    return vec3(q.x, c2 * q.y - s2 * q.z, s2 * q.y + c2 * q.z);
}

void main() {
    const uint id = TDIndex();
    if (id >= TDNumElements()) return;
    float x = float(id) / float(TDNumElements() - 1u);
    int A = int(uM.x), B = int(uM.y);
    float k = smoothstep(0.0, 1.0, clamp(uM.z * 1.6 - (1.0 - x) * 0.6, 0.0, 1.0));   // the warp runs from the head back to the tail
    vec3 pa = place(path(A, x), A), pb = place(path(B, x), B);
    vec3 p = mix(pa, pb, k);
    p += sin(k * 3.14159) * 0.55 * vec3(sin(x * 19.0 + uR.z * 0.7), cos(x * 23.0 + uR.z * 0.5), sin(x * 29.0));   // it flows, mid-warp
    P[id] = p;
    // colour: a gradient along the line's length; the drawn-on part is lit, the rest is hidden
    vec3 c0 = vec3(0.45, 0.20, 1.00), c1 = vec3(1.00, 0.30, 0.65), c2 = vec3(1.00, 0.78, 0.35);
    vec3 col = (x < 0.5) ? mix(c0, c1, x * 2.0) : mix(c1, c2, (x - 0.5) * 2.0);
    float d = fract(uM.w - x);                                          // distance behind the travelling head
    float comet = exp(-d * 28.0);                                       // the bright segment on its journey
    float tip = exp(-d * 400.0);
    Color[id] = vec4(col * (0.55 + 1.6 * comet) + vec3(1.0, 0.96, 0.9) * tip * 1.5, 1.0);
}
