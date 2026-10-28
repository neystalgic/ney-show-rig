// Ney Sky — a real-time ceiling sky for the living room.
// Real sun, moon (with phase), stars and constellations for the configured location,
// drifting clouds, and hooks so the Hue Hub can tint / dim it per mode.
// Flicker-safe: every change is eased; nothing can flash.
(function () {
  'use strict';
  const D2R = Math.PI / 180, R2D = 180 / Math.PI;
  const qs = new URLSearchParams(location.search);
  const DEF = Object.assign({
    lat: 34.1808, lon: -118.309,       // Burbank city centre (not an address)
    fov: 110,                          // degrees of sky across the image width
    rot: 0,                            // degrees; turn until "N" points to real north
    flip: false,                       // mirror if the projector flips the image
    corners: [[0, 0], [1, 0], [1, 1], [0, 1]], // keystone corner pin (TL,TR,BR,BL), 0..1
    lines: 0.22,                       // constellation line strength (0 = off)
    maglim: 5.6,                       // faintest star shown
    style: 'dream',                    // 'dream' = Pixar-ish puffy clouds + storybook moon; 'real' = realistic
    balloons: true, bigMoon: true, shootingStars: true, // surreal touches (dream style)
    minClouds: 0.18, maxClouds: 0.8,   // keep some clouds even on clear days
    weather: true,                     // follow real cloud cover / wind (Open-Meteo)
    calib: false,                      // show grid + compass for aiming
    scale: 0.75,                       // internal render scale (Pi performance)
    fps: 30,
  }, window.SKY_DEFAULTS || {});
  let cfg = Object.assign({}, DEF);
  const num = (k) => (qs.has(k) ? parseFloat(qs.get(k)) : undefined);
  function urlOverrides() {
    ['fov', 'rot', 'lines', 'maglim', 'scale', 'fps', 'lat', 'lon'].forEach(k => { const v = num(k); if (v !== undefined && !isNaN(v)) cfg[k] = v; });
    if (qs.has('flip')) cfg.flip = qs.get('flip') === '1';
    if (qs.has('calib')) cfg.calib = qs.get('calib') === '1';
    if (qs.has('weather')) cfg.weather = qs.get('weather') === '1';
  }
  urlOverrides();

  // ---------- time ----------
  const t0Real = Date.now();
  const tStart = qs.has('t') ? Date.parse(qs.get('t')) : t0Real;
  const speed = qs.has('speed') ? parseFloat(qs.get('speed')) : 1;
  const now = () => tStart + (Date.now() - t0Real) * speed;

  // ---------- astronomy (low precision, plenty for a ceiling) ----------
  function days(ms) { return ms / 86400000 + 2440587.5 - 2451545.0; }
  function lstDeg(ms, lon) { const d = days(ms); return ((280.46061837 + 360.98564736629 * d + lon) % 360 + 360) % 360; }
  function sunRaDec(ms) {
    const d = days(ms), g = (357.529 + 0.98560028 * d) * D2R, q = 280.459 + 0.98564736 * d;
    const L = (q + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * D2R, e = (23.439 - 0.00000036 * d) * D2R;
    return [Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L)), Math.asin(Math.sin(e) * Math.sin(L))];
  }
  function moonRaDec(ms) {
    const d = days(ms), T = d / 36525, s = (a) => Math.sin(a * D2R);
    const lam = (218.32 + 481267.881 * T + 6.29 * s(135.0 + 477198.87 * T) - 1.27 * s(259.3 - 413335.36 * T)
      + 0.66 * s(235.7 + 890534.22 * T) + 0.21 * s(269.9 + 954397.74 * T) - 0.19 * s(357.5 + 35999.05 * T)
      - 0.11 * s(186.5 + 966404.03 * T)) * D2R;
    const bet = (5.13 * s(93.3 + 483202.02 * T) + 0.28 * s(228.2 + 960400.89 * T) - 0.28 * s(318.3 + 6003.15 * T)
      - 0.17 * s(217.6 - 407332.21 * T)) * D2R;
    const e = 23.439 * D2R;
    const x = Math.cos(bet) * Math.cos(lam), y = Math.cos(bet) * Math.sin(lam), z = Math.sin(bet);
    const y2 = y * Math.cos(e) - z * Math.sin(e), z2 = y * Math.sin(e) + z * Math.cos(e);
    return [Math.atan2(y2, x), Math.asin(z2)];
  }
  // RA/Dec (rad) -> local East/North/Up unit vector
  function enu(ra, dec, lstRad, latRad) {
    const H = lstRad - ra;
    return [-Math.cos(dec) * Math.sin(H),
      Math.sin(dec) * Math.cos(latRad) - Math.cos(dec) * Math.cos(H) * Math.sin(latRad),
      Math.sin(dec) * Math.sin(latRad) + Math.cos(dec) * Math.cos(H) * Math.cos(latRad)];
  }

  // ---------- GL setup ----------
  const canvas = document.getElementById('sky'); const stage = document.getElementById('stage');
  const gl = canvas.getContext('webgl', { alpha: false, antialias: true, premultipliedAlpha: false, powerPreference: 'high-performance' });
  if (!gl) { document.body.innerHTML = '<p style="color:#888;font:16px sans-serif;padding:2em">WebGL is not available.</p>'; return; }

  function sh(type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) + '\n' + src); return s; }
  function prog(vs, fs) { const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); const u = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); for (let i = 0; i < n; i++) { const a = gl.getActiveUniform(p, i); u[a.name] = gl.getUniformLocation(p, a.name); } return { p, u }; }

  // Shared GLSL: screen <-> sky direction. View is from BELOW the ceiling:
  // north up, east LEFT (like a star chart held overhead). rot turns it, flip mirrors it.
  const VIEW = `
    uniform vec2 u_res; uniform float u_halfFov; uniform float u_rot; uniform float u_flip;
    vec3 screenToDir(vec2 frag){
      vec2 p = (frag - 0.5*u_res) / (0.5*u_res.x);
      p.x *= u_flip;
      float r = length(p); float th = r*u_halfFov;
      float A = atan(-p.x, p.y) + u_rot;
      return vec3(sin(th)*sin(A), sin(th)*cos(A), cos(th));
    }
    vec2 dirToClip(vec3 v){
      float th = acos(clamp(v.z,-1.0,1.0)); float A = atan(v.x, v.y) - u_rot;
      float r = th/u_halfFov;
      vec2 p = vec2(-sin(A)*r*u_flip, cos(A)*r);
      return vec2(p.x, p.y*u_res.x/u_res.y);
    }`;
  const NOISE = `
    float hash(vec2 p){ p = fract(p*vec2(123.34, 456.21)); p += dot(p, p+45.32); return fract(p.x*p.y); }
    float vnoise(vec2 p){ vec2 i=floor(p), f=fract(p); vec2 u=f*f*(3.0-2.0*f);
      return mix(mix(hash(i),hash(i+vec2(1,0)),u.x), mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),u.x), u.y); }
    float fbm(vec2 p){ float a=0.5, s=0.0; for(int i=0;i<5;i++){ s+=a*vnoise(p); p=p*2.03+vec2(17.1,9.2); a*=0.5; } return s; }`;
  const QUAD_VS = `attribute vec2 a; void main(){ gl_Position = vec4(a,0.0,1.0); }`;

  const SKY_FS = `precision highp float;` + VIEW + NOISE + `
    uniform vec3 u_sun; uniform vec3 u_moon; uniform float u_moonLit; uniform mat3 u_toGal; uniform float u_lst; uniform float u_lat;
    uniform float u_gain; uniform vec3 u_tint; uniform float u_tintMix; uniform float u_calib; uniform float u_dream;
    vec3 dreamZen(float h){
      vec3 night=vec3(0.020,0.018,0.075), twi=vec3(0.16,0.10,0.36), sunset=vec3(0.36,0.30,0.70), day=vec3(0.30,0.62,0.98);
      if(h<-14.0) return night; if(h<-4.0) return mix(night,twi,(h+14.0)/10.0); if(h<4.0) return mix(twi,sunset,(h+4.0)/8.0); return mix(sunset,day,clamp((h-4.0)/14.0,0.0,1.0)); }
    vec3 dreamHor(float h){
      vec3 night=vec3(0.10,0.05,0.20), twi=vec3(0.62,0.28,0.55), sunset=vec3(1.0,0.58,0.48), day=vec3(0.62,0.92,0.98);
      if(h<-14.0) return night; if(h<-4.0) return mix(night,twi,(h+14.0)/10.0); if(h<4.0) return mix(twi,sunset,(h+4.0)/8.0); return mix(sunset,day,clamp((h-4.0)/14.0,0.0,1.0)); }
    vec3 lerp3(vec3 a, vec3 b, float t){ return mix(a,b,clamp(t,0.0,1.0)); }
    vec3 zenithCol(float h){
      vec3 night=vec3(0.004,0.007,0.022), astro=vec3(0.010,0.016,0.050), naut=vec3(0.035,0.055,0.17), civil=vec3(0.13,0.20,0.48), low=vec3(0.22,0.40,0.78), day=vec3(0.16,0.40,0.86);
      if(h<-18.0) return night; if(h<-12.0) return lerp3(night,astro,(h+18.0)/6.0);
      if(h<-6.0) return lerp3(astro,naut,(h+12.0)/6.0); if(h<0.0) return lerp3(naut,civil,(h+6.0)/6.0);
      if(h<10.0) return lerp3(civil,low,h/10.0); return lerp3(low,day,(h-10.0)/30.0);
    }
    vec3 horizonCol(float h){
      vec3 night=vec3(0.03,0.025,0.03), twi=vec3(0.30,0.12,0.22), sunset=vec3(1.0,0.45,0.22), gold=vec3(1.0,0.75,0.45), day=vec3(0.62,0.78,0.96);
      if(h<-14.0) return night; if(h<-6.0) return lerp3(night,twi,(h+14.0)/8.0);
      if(h<1.0) return lerp3(twi,sunset,(h+6.0)/7.0); if(h<8.0) return lerp3(sunset,gold,(h-1.0)/7.0);
      return lerp3(gold,day,(h-8.0)/14.0);
    }
    void main(){
      vec3 v = screenToDir(gl_FragCoord.xy);
      if(v.z < -0.02){ gl_FragColor = vec4(0.0,0.0,0.0,1.0); return; }
      float h = degrees(asin(clamp(u_sun.z,-1.0,1.0)));
      float toward = max(dot(normalize(v.xy+1e-5), normalize(u_sun.xy+1e-5)),0.0);
      float hz = pow(1.0-clamp(v.z,0.0,1.0), 2.2);
      vec3 col = mix(zenithCol(h), horizonCol(h), hz*(0.45+0.55*toward));
      vec3 dcol = mix(dreamZen(h), dreamHor(h), pow(1.0-clamp(v.z,0.0,1.0),1.3)*(0.55+0.45*toward));
      col = mix(col, dcol, u_dream);
      float cs = max(dot(v,u_sun),0.0);
      float warm = clamp(1.0-abs(h)/12.0,0.0,1.0);
      col += vec3(1.0,0.55,0.30)*pow(cs,6.0)*0.55*warm;          // sunset glow toward the sun
      if(h>-1.0) col += vec3(1.0,0.97,0.88)*(smoothstep(0.99955,0.99975,cs) + pow(cs,400.0)*0.6); // sun disc + halo
      // Milky Way (procedural, placed by real galactic coordinates)
      float nightF = clamp((-10.0-h)/8.0,0.0,1.0);
      if(nightF>0.0){
        float sl=sin(u_lat), cl=cos(u_lat);
        float cdcH = v.z*cl - v.y*sl, cdsH = -v.x, sd = v.y*cl + v.z*sl;
        vec3 eq = vec3(cdcH*cos(u_lst)+cdsH*sin(u_lst), cdcH*sin(u_lst)-cdsH*cos(u_lst), sd);
        vec3 g = u_toGal*eq; float b = asin(clamp(g.z,-1.0,1.0)); float l = atan(g.y,g.x);
        float band = exp(-pow(b/0.17,2.0));
        float bulge = 0.55 + 0.45*exp(-pow(l/0.9,2.0));
        float clump = fbm(vec2(l*7.0, b*22.0)+3.0);
        float rift = 1.0 - 0.55*exp(-pow((b-0.03)/0.035,2.0))*smoothstep(1.2,0.0,abs(l-0.3));
        float mw = band*bulge*(0.45+0.85*clump)*rift;
        float moonUp = clamp(u_moon.z*4.0,0.0,1.0)*u_moonLit;
        col += vec3(0.075,0.080,0.105)*mw*nightF*(1.0-0.7*moonUp);
        col += vec3(0.020,0.022,0.035)*moonUp*nightF;                // moonlit sky
      }
      col += vec3(0.035,0.020,0.010)*hz*nightF;                     // city glow low down (Burbank!)
      col = mix(col, col*0.35 + u_tint*dot(col,vec3(0.33))*1.6 + u_tint*0.04, u_tintMix);
      gl_FragColor = vec4(col*u_gain, 1.0);
      if(u_calib>0.5){
        vec2 p = (gl_FragCoord.xy-0.5*u_res)/(0.5*u_res.x);
        float ring = abs(fract(length(p)*5.0)-0.5); float spoke = abs(fract((atan(p.y,p.x)/6.2832)*12.0)-0.5);
        float edge = step(min(min(gl_FragCoord.x,u_res.x-gl_FragCoord.x),min(gl_FragCoord.y,u_res.y-gl_FragCoord.y)), 3.0);
        gl_FragColor.rgb = max(gl_FragColor.rgb, vec3(0.35)*(step(0.47,ring)+step(0.485,spoke)) + vec3(0.9,0.6,0.2)*edge);
      }
    }`;

  const CLOUD_FS = `precision highp float;` + VIEW + NOISE + `
    uniform vec3 u_sun; uniform vec3 u_moon; uniform float u_moonLit; uniform float u_moonSize;
    uniform float u_time; uniform vec2 u_wind; uniform float u_cover; uniform float u_gain; uniform vec3 u_tint; uniform float u_tintMix; uniform float u_pulse;
    void main(){
      vec3 v = screenToDir(gl_FragCoord.xy);
      if(v.z < 0.02){ gl_FragColor = vec4(0.0); return; }
      float h = degrees(asin(clamp(u_sun.z,-1.0,1.0)));
      vec3 outc = vec3(0.0); float outa = 0.0;
      // moon disc with the real phase (lit side faces the real sun)
      vec3 m = normalize(u_moon);
      float ang = acos(clamp(dot(v,m),-1.0,1.0));
      float R = u_moonSize;
      if(m.z>-0.05 && ang < R*1.6){
        vec3 e1 = normalize(cross(vec3(0.0,0.0,1.0), m)+vec3(1e-4,0.0,0.0)); vec3 e2 = cross(m,e1);
        vec3 d = v - m*dot(v,m); vec2 q = vec2(dot(d,e1), dot(d,e2))/sin(R);
        float rr = dot(q,q);
        if(rr<1.0){
          vec3 n = normalize(-m*sqrt(1.0-rr) + q.x*e1 + q.y*e2);
          float lit = smoothstep(-0.04,0.06,dot(n,u_sun));
          float mare = 0.82+0.18*fbm(q*3.0+7.0);
          vec3 mc = vec3(0.95,0.93,0.86)*mare*(0.04+0.96*lit);
          float aa = smoothstep(1.0,0.96,rr);
          outc = mc; outa = aa;
        }
        float glow = exp(-pow((ang-R)/(R*0.7),2.0))*0.10*u_moonLit*step(R,ang);
        outc += vec3(0.75,0.80,0.95)*glow; outa = max(outa, glow);
      }
      // clouds on a flat layer overhead
      vec2 uv = v.xy/max(v.z,0.08)*0.9 + u_wind;
      float n = fbm(uv*1.1 + vec2(u_time*0.004, -u_time*0.003));
      n = n*0.75 + 0.25*fbm(uv*4.3 - vec2(u_time*0.01, 0.0));
      float th = 1.0-u_cover;
      float dens = smoothstep(th, th+0.16, n);
      float thick = smoothstep(th, th+0.55, n);
      vec3 day = mix(vec3(1.0,1.0,1.0), vec3(0.62,0.66,0.74), thick*0.8);
      vec3 sunset = mix(vec3(1.0,0.62,0.45), vec3(0.55,0.32,0.42), thick);
      vec3 twi = mix(vec3(0.42,0.30,0.48), vec3(0.16,0.12,0.22), thick);
      vec3 night = mix(vec3(0.10,0.075,0.065), vec3(0.040,0.032,0.036), thick); // city-lit undersides
      vec3 cc;
      if(h>8.0) cc = day; else if(h>-1.0) cc = mix(sunset, day, (h+1.0)/9.0);
      else if(h>-9.0) cc = mix(twi, sunset, (h+9.0)/8.0); else cc = mix(night, twi, clamp((h+18.0)/9.0,0.0,1.0));
      float moonUp = clamp(m.z*4.0,0.0,1.0)*u_moonLit*clamp((-6.0-h)/6.0,0.0,1.0);
      cc += vec3(0.10,0.11,0.14)*moonUp*(1.0-thick)*(0.5+0.5*pow(max(dot(v,m),0.0),3.0));
      cc *= 1.0 + 0.18*u_pulse;
      cc = mix(cc, cc*0.35 + u_tint*dot(cc,vec3(0.33))*1.7, u_tintMix);
      float ca = dens*0.92;
      outc = mix(outc, cc, ca); outa = max(outa, ca);
      gl_FragColor = vec4(outc*u_gain, outa);
    }`;

  // ---------- DREAM style: Pixar-ish puffy clouds, big storybook moon, drifting balloons ----------
  const DREAM_FS = `precision highp float;` + VIEW + NOISE + `
    uniform vec3 u_sun; uniform vec3 u_moon; uniform float u_moonLit; uniform float u_moonSize;
    uniform float u_time; uniform vec2 u_wind; uniform float u_cover; uniform float u_gain; uniform vec3 u_tint; uniform float u_tintMix; uniform float u_pulse;
    uniform float u_balloons; uniform vec4 u_shoot;
    const float CELL = 0.95;
    vec2 h2(vec2 p){ return fract(sin(vec2(dot(p,vec2(127.1,311.7)), dot(p,vec2(269.5,183.3))))*43758.5453); }
    vec3 lerp3(vec3 a, vec3 b, float t){ return mix(a,b,clamp(t,0.0,1.0)); }

    // puffy heightfield: clusters of soft spheres. returns (height 0..1, normal.xy)
    vec3 puffs(vec2 p){
      vec2 cell = floor(p/CELL);
      float best = 0.0, sumE = 0.0, add = 0.0; vec2 sumG = vec2(0.0), addG = vec2(0.0);
      for(int j=-1;j<=1;j++) for(int i=-1;i<=1;i++){
        vec2 c = cell + vec2(float(i),float(j));
        vec2 r = h2(c);
        if(r.x > u_cover) continue;
        vec2 ctr = (c + 0.3 + 0.4*h2(c+3.7))*CELL;
        float size = (0.62 + 0.38*h2(c+9.1).x)*CELL*0.36;
        if(length(p-ctr) > size*2.3) continue;                          // cheap bounds check (Pi speed)
        float ang = h2(c+1.3).y*6.2832; vec2 ax = vec2(cos(ang),sin(ang)); vec2 px = vec2(-ax.y,ax.x);
        for(int n=0;n<13;n++){
          float fn = float(n); vec2 rr = h2(c*7.0+fn*1.37);
          vec2 off; float rad;
          if(n < 7){                                                      // big body puffs along the cloud
            float t = fn/3.0-1.0;
            off = ax*t*size*1.05 + px*(rr.x-0.5)*size*0.8;
            rad = size*(0.40 + 0.38*(1.0-abs(t)) + 0.18*rr.y);
          } else {                                                        // small cauliflower bumps on top
            float a2 = (fn-7.0)/6.0*6.2832 + rr.x*0.8; float d2 = size*(0.85+0.25*rr.y);
            off = ax*cos(a2)*d2*1.45 + px*sin(a2)*d2*0.75;                 // around the rim -> lumpy silhouette
            rad = size*(0.24 + 0.12*h2(c+fn*3.1).x);
          }
          rad *= 1.0 + 0.06*sin(u_time*0.045 + fn*1.7 + r.y*20.0);       // slow breathing
          vec2 d = p - ctr - off; float hh = rad*rad - dot(d,d);
          if(hh > 0.0){
            float hg = sqrt(hh);
            if(n < 7){ float e = exp(7.0*hg/size); sumE += e; sumG += e*(d/max(hg, 0.02*size)); best = max(best, hg/size); }
            else { float e = exp(7.0*hg/size); sumE += e; sumG += e*(d/max(hg, 0.02*size)); best = max(best, hg/size); }
          }
        }
      }
      vec2 g = sumE > 0.0 ? sumG/sumE : vec2(0.0);
      float body = smoothstep(0.0, 0.25, best);
      g += addG*body; best += add*body;
      float gl2 = length(g); if(gl2 > 6.0) g *= 6.0/gl2;
      return vec3(best, g);
    }
    // a little striped hot-air balloon, upright on screen
    vec4 balloon(vec2 q, vec3 c1, vec3 c2, vec3 L, float night){
      // q: local coords, envelope radius 1, centre at origin, basket below
      vec2 e = vec2(q.x, q.y*0.92 + 0.12*max(-q.y,0.0)*abs(q.y));   // slight teardrop
      float r = length(e);
      vec4 o = vec4(0.0);
      if(r < 1.0){
        float z = sqrt(1.0-r*r); vec3 n = normalize(vec3(e, z));
        float lon = asin(clamp(e.x/max(sqrt(1.0-e.y*e.y),0.05),-1.0,1.0));
        vec3 base = mod(floor(lon*3.2+3.0),2.0) < 1.0 ? c1 : c2;
        float lit = 0.55 + 0.45*clamp(dot(n,normalize(L)),0.0,1.0);
        vec3 col = base*lit + 0.12*pow(1.0-z,2.0);
        col = mix(col, col*0.45 + vec3(0.25,0.22,0.35)*0.2, night);
        o = vec4(col, smoothstep(1.0,0.96,r));
      }
      vec2 b = q - vec2(0.0,-1.42); vec2 bb = abs(b) - vec2(0.17,0.13);
      if(max(bb.x,bb.y) < 0.0) o = vec4(mix(vec3(0.55,0.36,0.22), vec3(0.18,0.13,0.10), night), 1.0);
      float ropeL = abs(q.x + 0.15 + (q.y+1.0)*0.25), ropeR = abs(q.x - 0.15 - (q.y+1.0)*0.25);
      if(q.y < -0.85 && q.y > -1.3 && min(ropeL,ropeR) < 0.025) o = max(o, vec4(vec3(0.3,0.25,0.22)*(1.0-0.6*night),0.9));
      // burner glow at night (steady, never flickers)
      float bg = exp(-dot(q-vec2(0.0,-1.15),q-vec2(0.0,-1.15))*18.0)*night;
      o.rgb += vec3(1.0,0.55,0.2)*bg*0.6; o.a = max(o.a, bg*0.5);
      return o;
    }
    void main(){
      vec3 v = screenToDir(gl_FragCoord.xy);
      if(v.z < 0.02){ gl_FragColor = vec4(0.0); return; }
      float h = degrees(asin(clamp(u_sun.z,-1.0,1.0)));
      float night = clamp((-4.0-h)/8.0,0.0,1.0);
      vec3 outc = vec3(0.0); float outa = 0.0;

      // big storybook moon with its real phase + soft halo rings
      vec3 m = normalize(u_moon); float R = u_moonSize;
      float ang = acos(clamp(dot(v,m),-1.0,1.0));
      if(m.z > -0.05 && ang < R*4.0){
        vec3 e1 = normalize(cross(vec3(0.0,0.0,1.0), m)+vec3(1e-4,0.0,0.0)); vec3 e2 = cross(m,e1);
        vec3 dd = v - m*dot(v,m); vec2 q = vec2(dot(dd,e1), dot(dd,e2))/sin(R); float rr = dot(q,q);
        float halo = (exp(-pow((ang-R)/(R*0.9),2.0))*0.22 + exp(-pow((ang-R*2.2)/(R*0.25),2.0))*0.05)*step(R,ang)*(0.3+0.7*night);
        outc = vec3(0.85,0.88,1.0); outa = halo;
        if(rr < 1.0){
          vec3 n = normalize(-m*sqrt(1.0-rr) + q.x*e1 + q.y*e2);
          float lit = smoothstep(-0.03,0.08,dot(n,u_sun));
          float crater = smoothstep(0.55,0.62,vnoise(q*4.0+11.0))*0.12 + smoothstep(0.6,0.7,vnoise(q*9.0+3.0))*0.06;
          vec3 mc = mix(vec3(0.20,0.22,0.38), vec3(1.0,0.97,0.86)-crater, lit);   // dark side stays a soft blue, like a storybook
          outc = mc; outa = smoothstep(1.0,0.97,rr);
        }
      }

      // shooting star (night only, rare, soft) — u_shoot: xy start on the cloud plane, z angle, w phase 0..1
      if(u_shoot.w > 0.0 && u_shoot.w < 1.0){
        vec2 pp = v.xy/max(v.z,0.08);
        vec2 dir = vec2(cos(u_shoot.z), sin(u_shoot.z));
        vec2 head = u_shoot.xy + dir*u_shoot.w*1.4;
        vec2 rel = pp - head; float along = dot(rel,-dir); float across = abs(dot(rel, vec2(-dir.y,dir.x)));
        float tail = (along > 0.0 && along < 0.35) ? (1.0-along/0.35) : 0.0;
        float s = tail*exp(-across*across*9000.0)*sin(3.14159*u_shoot.w)*0.55*night;
        outc = mix(outc, vec3(0.9,0.92,1.0), clamp(s,0.0,1.0)); outa = max(outa, s);
      }

      // light: sun by day, moon (or a dreamy fill) at night
      vec3 Ls = normalize(vec3(u_sun.xy+1e-4, 0.0))*0.85 + vec3(0.0,0.0,0.5);
      vec3 Lm = normalize(vec3(m.xy+1e-4, 0.0))*0.85 + vec3(0.0,0.0,0.5);
      vec3 L = normalize(mix(Ls, Lm, night));

      // palette through the day (pastel, Pixar-ish)
      vec3 hi, mid, sha, rim;
      if(h > 12.0){ hi=vec3(1.0,0.99,0.96); mid=vec3(0.92,0.94,1.0); sha=vec3(0.62,0.69,0.95); rim=vec3(1.0); }
      else if(h > 0.0){ float t=h/12.0; hi=lerp3(vec3(1.0,0.80,0.58),vec3(1.0,0.99,0.96),t); mid=lerp3(vec3(1.0,0.62,0.62),vec3(0.92,0.94,1.0),t); sha=lerp3(vec3(0.58,0.45,0.78),vec3(0.62,0.69,0.95),t); rim=lerp3(vec3(1.0,0.82,0.5),vec3(1.0),t); }
      else if(h > -10.0){ float t=(h+10.0)/10.0; hi=lerp3(vec3(0.36,0.39,0.68),vec3(1.0,0.80,0.58),t); mid=lerp3(vec3(0.15,0.15,0.34),vec3(1.0,0.62,0.62),t); sha=lerp3(vec3(0.045,0.045,0.12),vec3(0.58,0.45,0.78),t); rim=lerp3(vec3(0.85,0.70,1.0),vec3(1.0,0.82,0.5),t); }
      else { hi=vec3(0.27,0.29,0.52); mid=vec3(0.11,0.11,0.26); sha=vec3(0.035,0.035,0.09); rim=vec3(0.55,0.60,0.90); }

      // clouds
      vec2 uv = v.xy/max(v.z,0.08)*0.85 + u_wind;
      uv += (vec2(vnoise(uv*6.0), vnoise(uv*6.0+5.2))-0.5)*0.025;    // soft, slightly hand-made edges
      vec3 P = puffs(uv);
      float ca = smoothstep(0.0, 0.07, P.x);
      if(ca > 0.0){
        vec3 n = normalize(vec3(P.yz, 1.0));
        float diff = dot(n, L)*0.5 + 0.5;
        float tone = mix(diff, 0.22 + 0.45*smoothstep(0.40,0.56,diff) + 0.33*smoothstep(0.72,0.86,diff), 0.4);
        vec3 col = mix(sha, mid, smoothstep(0.05,0.55,tone)); col = mix(col, hi, smoothstep(0.55,0.95,tone));
        float edge = pow(1.0-n.z, 2.5);
        float facing = max(dot(normalize(n.xy+1e-4), normalize(L.xy+1e-4)), 0.0);
        col += rim*edge*facing*0.55 + rim*edge*0.06;                 // silver lining
        col *= 0.92 + 0.08*smoothstep(0.0,0.5,P.x);                  // a touch of depth in the creases
        col *= 1.0 + 0.16*u_pulse;
        col = mix(col, col*0.35 + u_tint*dot(col,vec3(0.33))*1.7, u_tintMix);
        outc = mix(outc, col, ca); outa = max(outa, ca);
      }

      // drifting hot-air balloons (a few, slow, below the clouds)
      if(u_balloons > 0.5){
        vec2 pb = v.xy/max(v.z,0.08);
        for(int i=0;i<3;i++){
          float fi = float(i);
          float period = 260.0 + fi*97.0; float ph = fract(u_time/period + fi*0.37);
          float seed = floor(u_time/period + fi*0.37) + fi*13.0;
          vec2 rs = h2(vec2(seed, fi));
          float a0 = rs.x*6.2832; vec2 dir = vec2(cos(a0), sin(a0));
          vec2 pos = -dir*1.6 + vec2(-dir.y,dir.x)*(rs.y-0.5)*1.4 + dir*3.2*ph;
          pos.y += 0.03*sin(u_time*0.21+fi);                           // gentle bob
          float sz = 0.055 + 0.03*h2(vec2(seed,7.0)).x;
          // keep them upright on the screen: work in screen-aligned axes
          vec2 sp = pb - pos;
          float cr = cos(u_rot), sr = sin(u_rot);
          vec2 q = vec2(-(sp.x*cr - sp.y*sr)*u_flip, sp.y*cr + sp.x*sr)/sz;   // screen-aligned so balloons stay upright
          if(abs(q.x) < 1.3 && q.y > -1.7 && q.y < 1.2){
            vec3 c1 = i==1 ? vec3(0.25,0.45,0.85) : vec3(0.92,0.25,0.22);
            vec3 c2 = i==2 ? vec3(1.0,0.82,0.30) : vec3(0.97,0.95,0.92);
            vec4 b = balloon(q, c1, c2, L, night);
            float fade = smoothstep(0.0,0.08,ph)*smoothstep(1.0,0.92,ph);
            b.a *= fade;
            b.rgb = mix(b.rgb, b.rgb*0.4 + u_tint*dot(b.rgb,vec3(0.33))*1.5, u_tintMix*0.6);
            outc = mix(outc, b.rgb, b.a); outa = max(outa, b.a);
          }
        }
      }
      gl_FragColor = vec4(outc*u_gain, outa);
    }`;

  const STAR_VS = `attribute vec4 a_s; uniform float u_lst; uniform float u_lat; uniform float u_maglim; uniform float u_px; uniform float u_time; uniform float u_dreamV; varying float v_g;` + VIEW + `
    varying vec3 v_c; varying float v_a;
    vec3 bvRgb(float bv){ float t = clamp((bv+0.4)/2.4,0.0,1.0);
      return mix(mix(vec3(0.65,0.75,1.0), vec3(1.0,0.98,0.95), smoothstep(0.0,0.35,t)), vec3(1.0,0.70,0.45), smoothstep(0.35,0.9,t)); }
    void main(){
      float ra=radians(a_s.x), dec=radians(a_s.y); float H = u_lst - ra;
      vec3 v = vec3(-cos(dec)*sin(H), sin(dec)*cos(u_lat)-cos(dec)*cos(H)*sin(u_lat), sin(dec)*sin(u_lat)+cos(dec)*cos(H)*cos(u_lat));
      float flux = pow(10.0, -0.4*(a_s.z-1.0));
      float tw = 1.0 + 0.10*sin(u_time*(0.6+fract(a_s.x*7.13)*0.8) + a_s.y*3.1);   // gentle, slow shimmer
      v_a = (a_s.z>u_maglim || v.z<0.03) ? 0.0 : clamp(0.38+flux*1.1,0.0,1.6)*tw*smoothstep(0.03,0.15,v.z);
      v_c = bvRgb(a_s.w);
      gl_Position = vec4(dirToClip(v), 0.0, 1.0);
      v_g = u_dreamV*smoothstep(0.35,1.6,flux);
      gl_PointSize = u_px*clamp(3.0+3.2*sqrt(flux), 3.0, 11.0)*(1.0+1.6*v_g);
    }`;
  const STAR_FS = `precision mediump float; varying vec3 v_c; varying float v_a; varying float v_g; uniform float u_vis; uniform float u_gain;
    void main(){ vec2 d = gl_PointCoord-0.5; float r = dot(d,d)*4.0; float k = 1.0+1.6*v_g; float a = (exp(-r*9.0*k*k) + 0.18*exp(-r*2.0*k*k))*v_a*u_vis;
      a += v_g*(exp(-abs(d.x)*70.0)*exp(-abs(d.y)*7.0) + exp(-abs(d.y)*70.0)*exp(-abs(d.x)*7.0))*0.7*v_a*u_vis; gl_FragColor = vec4(v_c*a*u_gain, 1.0); }`;
  const LINE_VS = `attribute vec2 a_p; uniform float u_lst; uniform float u_lat;` + VIEW + ` varying float v_a;
    void main(){ float ra=radians(a_p.x), dec=radians(a_p.y); float H=u_lst-ra;
      vec3 v = vec3(-cos(dec)*sin(H), sin(dec)*cos(u_lat)-cos(dec)*cos(H)*sin(u_lat), sin(dec)*sin(u_lat)+cos(dec)*cos(H)*cos(u_lat));
      v_a = smoothstep(0.05,0.2,v.z); gl_Position = vec4(dirToClip(v), 0.0, 1.0); }`;
  const LINE_FS = `precision mediump float; varying float v_a; uniform float u_a; uniform float u_gain; uniform vec3 u_col;
    void main(){ gl_FragColor = vec4(u_col*v_a*u_a*u_gain, 1.0); }`;

  const P = { sky: prog(QUAD_VS, SKY_FS), cloud: prog(QUAD_VS, CLOUD_FS), star: prog(STAR_VS, STAR_FS), line: prog(LINE_VS, LINE_FS), dream: prog(QUAD_VS, DREAM_FS) };
  const quad = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, quad); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const stars = new Float32Array(window.SKY_STARS || []);
  const starBuf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, starBuf); gl.bufferData(gl.ARRAY_BUFFER, stars, gl.STATIC_DRAW);
  // constellation lines, split into ~1 degree steps along great circles so they curve correctly
  const lv = [];
  function radec2v(p) { const a = p[0] * D2R, d = p[1] * D2R; return [Math.cos(d) * Math.cos(a), Math.cos(d) * Math.sin(a), Math.sin(d)]; }
  function v2radec(v) { return [((Math.atan2(v[1], v[0]) * R2D) + 360) % 360, Math.asin(Math.max(-1, Math.min(1, v[2]))) * R2D]; }
  (window.SKY_LINES || []).forEach(pl => { for (let i = 0; i + 1 < pl.length; i++) {
    const A = radec2v(pl[i]), B = radec2v(pl[i + 1]); const ang = Math.acos(Math.max(-1, Math.min(1, A[0] * B[0] + A[1] * B[1] + A[2] * B[2])));
    const n = Math.max(1, Math.ceil(ang * R2D)); let prev = pl[i];
    for (let k = 1; k <= n; k++) { const t = k / n, s = Math.sin(ang), w1 = s > 1e-6 ? Math.sin((1 - t) * ang) / s : 1 - t, w2 = s > 1e-6 ? Math.sin(t * ang) / s : t;
      const p = v2radec([A[0] * w1 + B[0] * w2, A[1] * w1 + B[1] * w2, A[2] * w1 + B[2] * w2]); lv.push(prev[0], prev[1], p[0], p[1]); prev = p; } } });
  const lineBuf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, lineBuf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(lv), gl.STATIC_DRAW);
  const TOGAL = new Float32Array([-0.0548755604, 0.4941094279, -0.8676661490, -0.8734370902, -0.4448296300, -0.1980763734, -0.4838350155, 0.7469822445, 0.4559837762]); // column-major

  // ---------- live state from the hub (eased; nothing can flash) ----------
  const MODES = { sky: { gain: 1, tint: 0 }, music: { gain: 1, tint: 0.55 }, movie: { gain: 0.3, tint: 0 }, rest: { gain: 0.15, tint: 0 }, off: { gain: 0, tint: 0 } };
  const target = { mode: qs.get('mode') || 'sky', tint: [0.6, 0.3, 1.0], level: 0 };
  const live = { gain: qs.get('instant') === '1' ? 1 : 0, tintMix: 0, tint: [0.6, 0.3, 1.0], level: 0 }; // fades in over ~4 s at start
  const served = location.protocol.startsWith('http');
  async function poll() {
    if (!served) return;
    try { const r = await fetch('state', { cache: 'no-store' }); if (r.ok) { const s = await r.json();
      if (MODES[s.mode]) target.mode = s.mode;
      if (Array.isArray(s.tint) && s.tint.length === 3) target.tint = s.tint.map(x => Math.max(0, Math.min(1, +x || 0)));
      if (typeof s.level === 'number') target.level = Math.max(0, Math.min(1, s.level)); } } catch (e) { }
  }
  async function pollConfig() {
    if (!served) return;
    try { const r = await fetch('config', { cache: 'no-store' }); if (r.ok) { cfg = Object.assign({}, DEF, await r.json()); urlOverrides(); applyCorners(); } } catch (e) { }
  }
  // real cloud cover + wind for Burbank (optional)
  const wx = { cover: null, windDir: 250, windKmh: 10 };
  async function weather() {
    if (!cfg.weather) return;
    try { const u = `https://api.open-meteo.com/v1/forecast?latitude=${cfg.lat.toFixed(2)}&longitude=${cfg.lon.toFixed(2)}&current=cloud_cover,wind_speed_10m,wind_direction_10m`;
      const j = await (await fetch(u)).json(); wx.cover = j.current.cloud_cover / 100; wx.windDir = j.current.wind_direction_10m; wx.windKmh = j.current.wind_speed_10m; } catch (e) { }
  }
  function dailyCover(ms) { const d = Math.floor(ms / 86400000); const r = Math.abs(Math.sin(d * 12.9898) * 43758.5453) % 1; return 0.25 + 0.4 * r; }

  // ---------- keystone corner pin (CSS homography) ----------
  function applyCorners() {
    const W = innerWidth, H = innerHeight, c = (cfg.corners || DEF.corners).map(p => [p[0] * W, p[1] * H]);
    const [x0, y0] = c[0], [x1, y1] = c[1], [x2, y2] = c[2], [x3, y3] = c[3];
    const dx1 = x1 - x2, dx2 = x3 - x2, dy1 = y1 - y2, dy2 = y3 - y2, sx = x0 - x1 + x2 - x3, sy = y0 - y1 + y2 - y3;
    const den = dx1 * dy2 - dx2 * dy1; const g = (sx * dy2 - dx2 * sy) / den, h = (dx1 * sy - sx * dy1) / den;
    const a = x1 - x0 + g * x1, b = x3 - x0 + h * x3, d = y1 - y0 + g * y1, e = y3 - y0 + h * y3;
    // unit square -> corners; scale input from canvas px to unit
    const m = [a / W, d / W, 0, g / W, b / H, e / H, 0, h / H, 0, 0, 1, 0, x0, y0, 0, 1];
    stage.style.transform = `matrix3d(${m.join(',')})`;
  }
  addEventListener('resize', () => { resize(); applyCorners(); });

  function resize() { const s = cfg.scale; canvas.width = Math.round(innerWidth * s); canvas.height = Math.round(innerHeight * s); stage.style.width = innerWidth + 'px'; stage.style.height = innerHeight + 'px'; }
  resize(); applyCorners();

  // rare, soft shooting stars at night (dream style): ~1 every 45-150 s, 1.6 s long
  let shoot = { next: performance.now() + 20000, start: 0, x: 0, y: 0, a: 0 };
  function shootUniform(sunAlt) {
    const t = performance.now();
    if (!cfg.shootingStars || sunAlt > -12) return [0, 0, 0, -1];
    if (t > shoot.next) { shoot = { start: t, x: Math.random() * 1.6 - 0.8, y: Math.random() * 1.6 - 0.8, a: Math.random() * 6.283, next: t + 45000 + Math.random() * 105000 }; }
    const ph = (t - shoot.start) / 1600;
    return ph >= 0 && ph < 1 ? [shoot.x, shoot.y, shoot.a, ph] : [0, 0, 0, -1];
  }
  // ---------- frame ----------
  let lastF = 0, lastT = performance.now(), simT = 0;
  const seed0 = (Math.floor(Date.now() / 86400000) * 7.31) % 50;  // fresh sky each day
  const drift = { x: seed0, y: seed0 * 0.6, vx: 0, vy: 0, cover: -1 };
  function frame(tp) {
    requestAnimationFrame(frame);
    if (tp - lastF < 1000 / cfg.fps - 2) return; lastF = tp;
    const dt = Math.min(0.2, (tp - lastT) / 1000); lastT = tp; simT += dt;
    const M = MODES[target.mode] || MODES.sky;
    // gain fades at most 25%/s; tint eases over ~1.5 s; level: 0.25 s up, 1.2 s down (max ±18% swell)
    const dg = M.gain - live.gain; live.gain += Math.sign(dg) * Math.min(Math.abs(dg), 0.25 * dt);
    const kT = 1 - Math.exp(-dt / 1.5); live.tintMix += (M.tint - live.tintMix) * kT; for (let i = 0; i < 3; i++) live.tint[i] += (target.tint[i] - live.tint[i]) * kT;
    const lvT = target.mode === 'music' ? target.level : 0; live.level += (lvT - live.level) * (1 - Math.exp(-dt / (lvT > live.level ? 0.25 : 1.2)));

    const dreamOn = cfg.style !== 'real';
    const ms = now(), lat = cfg.lat * D2R, lst = lstDeg(ms, cfg.lon) * D2R;
    const [sra, sdec] = sunRaDec(ms), [mra, mdec] = moonRaDec(ms);
    const sun = enu(sra, sdec, lst, lat), moon = enu(mra, mdec, lst, lat);
    const sunAlt = Math.asin(sun[2]) * R2D;
    const elong = Math.acos(Math.cos(sdec) * Math.cos(mdec) * Math.cos(sra - mra) + Math.sin(sdec) * Math.sin(mdec));
    const moonLit = (1 - Math.cos(elong)) / 2;
    // weather changes ease in over minutes (no clouds popping in or out)
    let coverT = wx.cover == null ? dailyCover(ms) : wx.cover; coverT = cfg.minClouds + (cfg.maxClouds - cfg.minClouds) * coverT;
    if (drift.cover < 0) drift.cover = coverT; drift.cover += (coverT - drift.cover) * (1 - Math.exp(-dt / 60));
    const cover = drift.cover;
    // clouds travel downwind: toward (wind-from + 180 deg); offset integrated so wind shifts never jump
    const wTo = (wx.windDir + 180) * D2R, wSpd = (0.0025 + 0.00025 * Math.min(40, wx.windKmh)) * speed ** 0.5;
    const kW = 1 - Math.exp(-dt / 30); drift.vx += (-Math.sin(wTo) * wSpd - drift.vx) * kW; drift.vy += (-Math.cos(wTo) * wSpd - drift.vy) * kW;
    drift.x += drift.vx * dt; drift.y += drift.vy * dt;
    const wind = [drift.x, drift.y];
    const starVis = Math.max(0, Math.min(1, (-4 - sunAlt) / 9)) * (1 - 0.35 * Math.max(0, Math.min(1, moon[2] * 4)) * moonLit);
    const W = canvas.width, H = canvas.height, hf = cfg.fov / 2 * D2R, rot = cfg.rot * D2R, flip = cfg.flip ? -1 : 1;
    gl.viewport(0, 0, W, H);
    function common(p) { gl.useProgram(p.p); const u = p.u; u.u_res && gl.uniform2f(u.u_res, W, H); u.u_halfFov && gl.uniform1f(u.u_halfFov, hf); u.u_rot && gl.uniform1f(u.u_rot, rot); u.u_flip && gl.uniform1f(u.u_flip, flip);
      u.u_lst && gl.uniform1f(u.u_lst, lst); u.u_lat && gl.uniform1f(u.u_lat, lat); u.u_gain && gl.uniform1f(u.u_gain, live.gain * (1 + 0.08 * live.level)); u.u_time && gl.uniform1f(u.u_time, simT);
      u.u_sun && gl.uniform3fv(u.u_sun, sun); u.u_moon && gl.uniform3fv(u.u_moon, moon); u.u_moonLit && gl.uniform1f(u.u_moonLit, moonLit);
      u.u_tint && gl.uniform3fv(u.u_tint, live.tint); u.u_tintMix && gl.uniform1f(u.u_tintMix, live.tintMix); }
    function quadDraw(p) { const loc = gl.getAttribLocation(p.p, 'a'); gl.bindBuffer(gl.ARRAY_BUFFER, quad); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.disableVertexAttribArray(loc); }
    // 1 sky
    gl.disable(gl.BLEND); common(P.sky); gl.uniformMatrix3fv(P.sky.u.u_toGal, false, TOGAL); gl.uniform1f(P.sky.u.u_calib, cfg.calib ? 1 : 0); gl.uniform1f(P.sky.u.u_dream, dreamOn ? 1 : 0); quadDraw(P.sky);
    // 2 stars + constellation lines (additive)
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
    if (starVis > 0.001) {
      common(P.star); gl.uniform1f(P.star.u.u_maglim, cfg.maglim); gl.uniform1f(P.star.u.u_px, Math.max(1, H / 720)); gl.uniform1f(P.star.u.u_vis, starVis); gl.uniform1f(P.star.u.u_dreamV, dreamOn ? 1 : 0);
      let loc = gl.getAttribLocation(P.star.p, 'a_s'); gl.bindBuffer(gl.ARRAY_BUFFER, starBuf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0); gl.drawArrays(gl.POINTS, 0, stars.length / 4); gl.disableVertexAttribArray(loc);
      if (cfg.lines > 0 && lv.length) { common(P.line); gl.uniform1f(P.line.u.u_a, cfg.lines * starVis); gl.uniform3f(P.line.u.u_col, 0.45, 0.55, 0.85);
        loc = gl.getAttribLocation(P.line.p, 'a_p'); gl.bindBuffer(gl.ARRAY_BUFFER, lineBuf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0); gl.drawArrays(gl.LINES, 0, lv.length / 2); gl.disableVertexAttribArray(loc); }
    }
    // 3 moon + clouds (alpha over)
    const CP = dreamOn ? P.dream : P.cloud;
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); common(CP);
    gl.uniform1f(CP.u.u_moonSize, 0.26 * D2R * (dreamOn && cfg.bigMoon ? 10.0 : 8.0)); gl.uniform2fv(CP.u.u_wind, wind); gl.uniform1f(CP.u.u_cover, cover); gl.uniform1f(CP.u.u_pulse, live.level);
    if (dreamOn) { gl.uniform1f(CP.u.u_balloons, cfg.balloons ? 1 : 0); gl.uniform4fv(CP.u.u_shoot, shootUniform(sunAlt)); }
    quadDraw(CP);
    if (cfg.calib) drawCompass(rot, flip);
    window.SKY_DEBUG = { sunAlt, moonAlt: Math.asin(moon[2]) * R2D, moonLit, cover, mode: target.mode, gain: live.gain };
  }
  // compass letters for aiming (DOM overlay inside the transformed canvas area)
  const comp = document.getElementById('compass');
  function drawCompass(rot, flip) {
    comp.style.display = 'block';
    const W = innerWidth, H = innerHeight, r = Math.min(W, H) * 0.42;
    [['N', 0], ['E', 90], ['S', 180], ['W', 270]].forEach(([k, az]) => { const A = az * D2R - rot; const el = document.getElementById('c' + k);
      el.style.left = (W / 2 - Math.sin(A) * r * flip) + 'px'; el.style.top = (H / 2 - Math.cos(A) * r) + 'px'; });
  }
  setInterval(() => { if (!cfg.calib) comp.style.display = 'none'; }, 500);

  poll(); pollConfig(); weather();
  setInterval(poll, 1000); setInterval(pollConfig, 3000); setInterval(weather, 15 * 60 * 1000);
  requestAnimationFrame(frame);
})();
