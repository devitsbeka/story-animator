import React, { useLayoutEffect, useRef } from "react";
import { EnvPalette, envAt } from "./theme";

// ============================================================================
// REALISTIC ROUGH OCEAN (WebGL2, ray-traced height field). Original shader, deterministic:
// everything is a function of the uniforms, so frames render identically in any order.
//  - choppy multi-octave sea (domain-warped sharp-crested waves)
//  - height-field tracing (secant), normals by central differences
//  - Fresnel sky reflection, moon glitter path, light through thin crests, foam, haze
//  - lens: water drops with bright rims + a white-water sheet after a splash
// The SVG world is composited above; `front` re-draws the near water OVER the hull.
// ============================================================================

export type OceanGLProps = {
  w: number; h: number; t: number;
  horizon: number;
  camX?: number; zoom?: number;
  moon?: [number, number]; moonR?: number;
  dawn?: number;
  chop?: number; // sea state: 1 rough, 1.6 storm
  roll?: number;
  heave?: number; // camera height offset (m)
  splash?: number; // seconds since a splash hit the lens (<0 = none)
  wet?: number; // 0..1 drops on the lens
  front?: [number, number][]; // screen polygon where water is drawn again over the SVG
  children?: React.ReactNode; // the SVG world, sandwiched between the far sea and the near water
};

const VS = `#version 300 es
in vec2 p; out vec2 uv;
void main(){ uv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }`;

const FS = `#version 300 es
precision highp float;
in vec2 uv; out vec4 o;
uniform vec2 uRes; uniform float uT, uHor, uCamX, uZoom, uMoonR, uDawn, uChop, uRoll, uHeave, uSplash, uWet;
uniform vec2 uMoon;
uniform vec3 cSkyTop, cSkyMid, cSkyHor, cDeep, cShallow, cHaze, cMoon, cGlint, cFoam, cInk;

float h21(vec2 p){ p = fract(p * vec2(233.34, 851.73)); p += dot(p, p + 23.45); return fract(p.x * p.y); }
float n2(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1,0)), u.x), mix(h21(i + vec2(0,1)), h21(i + vec2(1,1)), u.x), u.y); }

float crestOct(vec2 p, float sharp){
  p += vec2(n2(p * 0.7), n2(p * 0.7 + 7.3)) * 1.4;
  float a = 0.5 + 0.5 * sin(p.x);
  float b = 0.5 + 0.5 * sin(p.y * 0.83 + a * 1.3);
  return pow(a * 0.65 + b * 0.35, sharp);
}
const mat2 ROT = mat2(1.6, 1.2, -1.2, 1.6);
float sea(vec2 p, int oct){
  float f = 0.16, amp = 0.9 * uChop, sharp = 3.2, hgt = 0.0;
  vec2 q = p; q.x *= 0.75;
  for (int i = 0; i < 6; i++){
    if (i >= oct) break;
    float tt = uT * (0.75 + float(i) * 0.12);
    hgt += (crestOct((q + tt) * f, sharp) + crestOct((q - tt) * f, sharp)) * amp;
    q = ROT * q; f *= 1.95; amp *= 0.24; sharp = mix(sharp, 1.2, 0.25);
  }
  return hgt;
}
vec3 skyCol(float e){ return e < 0.35 ? mix(cSkyHor, cSkyMid, e / 0.35) : mix(cSkyMid, cSkyTop, (e - 0.35) / 0.65); }
vec3 skyDir(vec3 rd, vec3 Lm){
  vec3 s = skyCol(clamp(rd.y * 2.2, 0.0, 1.0));
  float m = max(dot(rd, Lm), 0.0);
  return s + cMoon * (pow(m, 900.0) * 3.0 + pow(m, 40.0) * 0.25 + pow(m, 6.0) * 0.08);
}

void main(){
  vec2 fc = vec2(uv.x * uRes.x, (1.0 - uv.y) * uRes.y);
  vec2 c = uRes * 0.5; float ro = radians(uRoll);
  vec2 qq = fc - c; qq = vec2(cos(ro) * qq.x + sin(ro) * qq.y, -sin(ro) * qq.x + cos(ro) * qq.y); vec2 pc = qq + c;
  float foc = 1100.0 * uZoom;
  float pitch = atan((c.y - uHor) / foc);
  float cp = cos(pitch), sp = sin(pitch);
  vec3 rd = normalize(vec3((pc.x - c.x) / foc, (c.y - pc.y) / foc, 1.0));
  rd = vec3(rd.x, rd.y * cp - rd.z * sp, rd.y * sp + rd.z * cp);
  vec3 ro3 = vec3(uCamX * 0.02, 4.2 + uHeave, uT * 2.5);
  vec3 lm = normalize(vec3((uMoon.x - c.x) / foc, (c.y - uMoon.y) / foc, 1.0));
  vec3 Lm = normalize(vec3(lm.x, lm.y * cp - lm.z * sp, lm.y * sp + lm.z * cp));
  vec3 col;
  if (pc.y < uHor) {
    float e = clamp((uHor - pc.y) / (uRes.y * 0.75), 0.0, 1.0);
    col = skyCol(e);
    vec2 sg = (pc + vec2(uCamX * 0.1, 0.0)) / 9.0; vec2 id = floor(sg); vec2 fr = fract(sg) - 0.5;
    float st = h21(id), tw = 0.6 + 0.4 * sin(uT * 2.0 + st * 40.0);
    float sd = length(fr - (vec2(h21(id + 3.1), h21(id + 7.7)) - 0.5) * 0.6);
    col += cGlint * smoothstep(0.12, 0.0, sd) * step(0.968, st) * tw * (1.0 - uDawn) * smoothstep(0.06, 0.3, e);
    vec2 cpv = vec2((pc.x + uCamX * 0.25) / 420.0 + uT * 0.05, pc.y / 140.0);
    float cl = n2(cpv) * 0.5 + n2(cpv * 2.1 + 3.0) * 0.3 + n2(cpv * 4.3) * 0.2;
    float cover = smoothstep(0.42, 0.62, cl) * smoothstep(0.0, 0.25, e);
    float lit = exp(-length(pc - uMoon) / (uRes.x * 0.45));
    vec3 cloudC = mix(cSkyTop * 0.6, mix(cHaze, cMoon, 0.6), lit * smoothstep(0.62, 0.48, cl) + 0.15);
    float md = length(pc - uMoon);
    col += cMoon * (0.32 * exp(-md / (uMoonR * 2.2)) + 0.1 * exp(-md / (uMoonR * 8.0))) * (1.0 - uDawn * 0.7);
    if (md < uMoonR + 2.0) {
      vec2 mp = (pc - uMoon) / uMoonR;
      float cr = n2(mp * 3.0 + 4.0) * 0.6 + n2(mp * 7.0) * 0.4;
      vec3 mc = mix(vec3(1.0, 0.98, 0.9), vec3(0.85, 0.8, 0.66), smoothstep(0.45, 0.75, cr));
      col = mix(col, mc, smoothstep(uMoonR + 1.5, uMoonR - 1.0, md) * (1.0 - cover * 0.8));
    }
    col = mix(col, cloudC, cover * 0.92);
  } else {
    float tA = 0.0, tB = 1500.0;
    float hA = ro3.y - sea(ro3.xz, 3);
    vec3 pB = ro3 + rd * tB; float hB = pB.y - sea(pB.xz, 3);
    float tm = tB;
    if (hB < 0.0) {
      for (int i = 0; i < 10; i++) {
        tm = mix(tA, tB, hA / (hA - hB));
        vec3 pm = ro3 + rd * tm; float hm = pm.y - sea(pm.xz, 3);
        if (hm < 0.0) { tB = tm; hB = hm; } else { tA = tm; hA = hm; }
      }
    }
    vec3 p = ro3 + rd * tm;
    float dist = tm;
    float eps = max(0.01, dist * 0.0025);
    int oc = dist < 60.0 ? 6 : 4;
    float hc = sea(p.xz, oc);
    vec3 n = normalize(vec3(sea(p.xz - vec2(eps, 0.0), oc) - sea(p.xz + vec2(eps, 0.0), oc), 2.0 * eps, sea(p.xz - vec2(0.0, eps), oc) - sea(p.xz + vec2(0.0, eps), oc)));
    float far = clamp(dist / 900.0, 0.0, 1.0);
    n = normalize(mix(n, vec3(0.0, 1.0, 0.0), far * 0.6));
    float fres = pow(clamp(1.0 - dot(n, -rd), 0.0, 1.0), 3.0) * 0.65;
    vec3 refl = skyDir(reflect(rd, n), Lm);
    float diff = pow(dot(n, Lm) * 0.4 + 0.6, 80.0);
    col = mix(cDeep + diff * cShallow * 0.18, refl, fres);
    float atten = max(1.0 - dist * dist * 0.00002, 0.0);
    col += cShallow * (hc - 0.6 * uChop) * 0.22 * atten;
    col += cGlint * pow(max(dot(reflect(rd, n), Lm), 0.0), 220.0) * 3.0 * (1.0 - uDawn * 0.3);
    float foam = smoothstep(1.05 * uChop, 1.45 * uChop, hc) * (0.6 + 0.4 * n2(p.xz * 1.8 + uT));
    foam += smoothstep(0.82, 0.98, n2(p.xz * 0.35 + vec2(uT * 0.2, 0.0))) * smoothstep(0.9 * uChop, 1.2 * uChop, hc) * 0.6;
    col = mix(col, cFoam * (0.55 + 0.45 * max(dot(n, Lm), 0.0)), clamp(foam, 0.0, 1.0) * (1.0 - far));
    col = mix(col, cHaze * 0.9, pow(far, 1.5) * 0.85);
  }
  // lens: sparse beaded drops (soft refraction: darker body, one bright highlight), short splash
  vec2 suv = fc / uRes.y;
  float splashK = (uSplash >= 0.0) ? clamp(1.0 - uSplash / 3.0, 0.0, 1.0) : 0.0;
  float amount = clamp(uWet + splashK * 0.8, 0.0, 1.0);
  for (int L = 0; L < 2; L++) {
    vec2 g = suv * (L == 0 ? 6.0 : 11.0) + float(L) * 3.7;
    vec2 id = floor(g), f = fract(g) - 0.5;
    float r = h21(id + float(L) * 9.1);
    if (r < 1.0 - amount * 0.32) continue;
    vec2 off = (vec2(h21(id + 11.0), h21(id + 23.0)) - 0.5) * 0.5;
    float sz = mix(0.07, 0.17, h21(id + 5.0));
    float slide = fract(uT * 0.04 * r + r) * 0.25;
    vec2 dv = (f - off - vec2(0.0, -slide)) * vec2(1.0, 0.8);
    float d = length(dv);
    float body = smoothstep(sz, sz * 0.75, d);
    col = mix(col, col * 0.78 + cDeep * 0.1, body * 0.55);                       // refraction darkens
    col += cGlint * smoothstep(sz * 0.35, 0.0, length(dv - vec2(-sz * 0.35, -sz * 0.35))) * body * 0.7; // highlight
  }
  if (uSplash >= 0.0 && uSplash < 0.5) {
    float k = 1.0 - uSplash / 0.5;
    float yN = fc.y / uRes.y;
    float sheet = smoothstep(0.55, 0.95, yN + (n2(vec2(fc.x / 70.0, uT * 4.0)) - 0.5) * 0.35 + (1.0 - k) * 0.5);
    col = mix(col, cFoam, sheet * k * 0.75);
  }
  o = vec4(col, 1.0);
}`;

const PAL_KEYS: (keyof EnvPalette)[] = ["skyTop", "skyMid", "skyHor", "deep", "shallow", "haze", "moon", "glint", "foam", "ink"];
const rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
type GLState = { gl: WebGL2RenderingContext; prog: WebGLProgram; loc: Record<string, WebGLUniformLocation | null> };

export const OceanGL: React.FC<OceanGLProps> = ({ w, h, t, horizon, camX = 0, zoom = 1, moon = [840, 600], moonR = 56, dawn = 0, chop = 1, roll = 0, heave = 0, splash = -1, wet = 0, front, children }) => {
  const ref = useRef<HTMLCanvasElement>(null);
  const fref = useRef<HTMLCanvasElement>(null);
  const st = useRef<GLState | null>(null);
  useLayoutEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    if (!st.current) {
      const gl = cv.getContext("webgl2", { preserveDrawingBuffer: true, antialias: false });
      if (!gl) return;
      const sh = (type: number, src: string) => { const s = gl.createShader(type)!; gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "shader"); return s; };
      const prog = gl.createProgram()!;
      gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) ?? "link");
      const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
      const pl = gl.getAttribLocation(prog, "p"); gl.enableVertexAttribArray(pl); gl.vertexAttribPointer(pl, 2, gl.FLOAT, false, 0, 0);
      const loc: GLState["loc"] = {};
      ["uRes", "uT", "uHor", "uCamX", "uZoom", "uMoon", "uMoonR", "uDawn", "uChop", "uRoll", "uHeave", "uSplash", "uWet", ...PAL_KEYS.map((k) => "c" + k[0].toUpperCase() + k.slice(1))].forEach((k) => { loc[k] = gl.getUniformLocation(prog, k); });
      st.current = { gl, prog, loc };
    }
    const { gl, prog, loc } = st.current;
    gl.viewport(0, 0, w, h);
    gl.useProgram(prog);
    gl.uniform2f(loc.uRes, w, h); gl.uniform1f(loc.uT, t); gl.uniform1f(loc.uHor, horizon); gl.uniform1f(loc.uCamX, camX);
    gl.uniform1f(loc.uZoom, zoom); gl.uniform2f(loc.uMoon, moon[0], moon[1]); gl.uniform1f(loc.uMoonR, moonR);
    gl.uniform1f(loc.uDawn, dawn); gl.uniform1f(loc.uChop, chop); gl.uniform1f(loc.uRoll, roll);
    gl.uniform1f(loc.uHeave, heave); gl.uniform1f(loc.uSplash, splash); gl.uniform1f(loc.uWet, wet);
    const pal = envAt(dawn);
    PAL_KEYS.forEach((k) => { const v = rgb(pal[k]); gl.uniform3f(loc["c" + k[0].toUpperCase() + k.slice(1)], v[0], v[1], v[2]); });
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    const fcv = fref.current;
    if (fcv) { const c2 = fcv.getContext("2d"); if (c2) { c2.clearRect(0, 0, w, h); c2.drawImage(cv, 0, 0); } }
  });
  const clip = front && front.length > 2 ? `polygon(${front.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(",")})` : undefined;
  return (
    <>
      <canvas ref={ref} width={w} height={h} style={{ position: "absolute", inset: 0, width: w, height: h }} />
      {children}
      {clip && <canvas ref={fref} width={w} height={h} style={{ position: "absolute", inset: 0, width: w, height: h, clipPath: clip }} />}
    </>
  );
};
