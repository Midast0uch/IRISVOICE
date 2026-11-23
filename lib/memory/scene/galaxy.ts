// @ts-nocheck -- same style as engine.ts (the validated scene engine); three.js only, no React.
// W4 of the memory cortex plan (docs/Design/Memory-Cortex/LIVE-CONTEXT-AND-GALAXY-PLAN.md §8, §8.10):
// the cortex as a CLUSTER OF GALAXIES inside one woven shell - one 3D galaxy per domain (sector), alike and each its
// own, placed by their RELATIONS: domains whose claims are linked pull together and lean toward each other, a small
// domain linked to a bigger one is its irregular companion, only domains with enough claims are spirals. A COSMIC WEB
// of filaments joins linked galaxies (the hyphae between domains), and every galaxy is tied to the nucleus (the live
// context) at the centre. The shell is WOVEN FROM THE GALAXIES: each sends an anchor thread to the equator that
// becomes its strands to the two poles. A recall pulse runs claim -> anchor -> strand -> pole -> the whole weave.
// Outside the shell: deep space and far galaxies.
//
// Rules carried from the interface (MEMORY-INTERFACE §2, §11): every visual stands for a real value (claims, edges
// and their traversals, sector sizes and proven shares, recall events); the map never moves while it is read - the
// structure does not rotate, life is in the shaders; nothing builds brightness; the CPU sets uniforms and moves a few
// hundred dust points.
import * as THREE from 'three';

const V3 = THREE.Vector3;
const TAU = Math.PI * 2;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;

function rngOf(seed) { let s = seed >>> 0 || 1; return () => { s = (s * 16807) % 2147483647; return s / 2147483647; }; }
function hashKey(k) { let h = 7; for (const c of String(k)) h = (h * 31 + c.charCodeAt(0)) | 0; return h >>> 0; }

export const GALAXY_MAX = 12;   // domains drawn as their own galaxy (the rest: the nucleus side)
/** §9.2: the seven coordinate spaces round every sector, in ONE fixed order and angle everywhere. */
export const HALO_SPACES = ['domain', 'context', 'toolpath', 'conduct', 'style', 'chrono', 'capability'];
const PULSE_SLOTS = 8;
const LINKS_PER_CLAIM = 6;
const MAX_LINKS = 600;

/**
 * Where everything sits. Pure.
 *  regs:   [{key, size, col}]                  size = the domain's moments (domCounts), largest first
 *  claims: [{reg, born, proven, act}]          reg = index into regs
 *  links:  [{a, b}]                            claim-index pairs (landmark edges)
 * RELATIONAL (owner, 2026-11-23): galaxies whose claims are linked pull together and lean toward each other; a small
 * domain linked to a bigger one is its irregular companion beside it; only domains with enough claims are spirals.
 * Coordinates are world (the group is not tilted: every galaxy has its own tilt).
 */
export function layoutGalaxy({ R, regs, claims, links = [], seed = 7 }) {
  const rng = rngOf(seed);
  const gauss = () => (rng() + rng() + rng() + rng()) / 2 - 1;
  const GR = R * 0.62, HH = R * 0.72;
  const shellR = (h, size = 0.6) => GR * (1.2 + 0.1 * size) * Math.pow(Math.max(0, 1 - Math.pow(h / HH, 2)), 0.85) + R * 0.02;
  const stat = regs.map(() => ({ n: 0, proven: 0, act: 0 }));
  claims.forEach(c => { const st = stat[c.reg]; if (!st) return; st.n++; if (c.proven) st.proven++; st.act += c.act || 0; });
  const shown = regs.slice(0, GALAXY_MAX), NG = shown.length;
  // how related two domains are: the landmark edges between their claims
  const S = Array.from({ length: NG }, () => new Array(NG).fill(0));
  links.forEach(l => { const ca = claims[l.a], cb = claims[l.b]; if (!ca || !cb) return; const i = ca.reg, j = cb.reg;
    if (i === j || i >= NG || j >= NG || i < 0 || j < 0) return; S[i][j]++; S[j][i]++; });
  const weight = (r, i) => Math.log10(1 + (r.size || 0)) + 0.8 * Math.log10(1 + stat[i].n);
  const maxW = Math.max(0.001, ...shown.map(weight));
  const maxAct = Math.max(1, ...stat.map(st => st.act));
  const arms = shown.map((r, i) => {
    const st = stat[i], h = hashKey(r.key), w = weight(r, i) / maxW;
    let best = -1, bs = 0; S[i].forEach((s, j) => { if (s > bs) { bs = s; best = j; } });
    const partnerBigger = best >= 0 && weight(shown[best], best) > weight(r, i);
    const kind = st.n >= 10 ? 'spiral' : partnerBigger ? 'irregular' : 'elliptical';
    const nArms = kind === 'spiral' ? (st.n > 60 ? 3 : 2) + (h % 3 === 0 && st.n > 120 ? 1 : 0) : 0;
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(((h % 97) / 97 - 0.5) * 1.9, (h % 360) / 360 * TAU, (((h >> 8) % 89) / 89 - 0.5) * 1.5));
    return { key: r.key, reg: i, col: new THREE.Color(r.col), kind, nArms, n: st.n, size: w, partner: best, partnerS: bs, companion: kind === 'irregular',
      rad: R * (kind === 'spiral' ? 0.09 + 0.14 * Math.sqrt(w) : 0.06 + 0.07 * Math.sqrt(w)), tight: 2.8 + 3.0 * (st.n ? st.proven / st.n : 0.3),
      bar: kind === 'spiral' && h % 4 === 1, core: 0.35 + 0.65 * Math.sqrt(st.act / maxAct), q,
      c: new V3(), az: 0, ph: (h % 1000) / 1000 * TAU, clumps: [] };
  });
  // start from a stable compass (angle and height from the key), then relax: linked galaxies pull to a distance that
  // shrinks with how many links they share, a companion sits right beside its partner, none overlap, all stay inside
  arms.forEach((a, i) => { const h = hashKey(a.key + 'p'), an = (h % 628) / 100, y = ((hashKey(a.key + 'y') % 100) / 100 * 2 - 1) * HH * 0.45;
    const rr = i === 0 ? R * 0.16 : R * (0.34 + 0.14 * ((h >> 4) % 100) / 100); a.c.set(Math.cos(an) * rr, y, Math.sin(an) * rr); });
  arms.forEach(a => { if (a.companion) { const p = arms[a.partner]; a.c.copy(p.c).add(new V3(gauss(), gauss() * 0.5, gauss()).normalize().multiplyScalar(p.rad + a.rad)); } });
  for (let it = 0; it < 240; it++) {
    const F = arms.map(() => new V3());
    for (let i = 0; i < NG; i++) for (let j = i + 1; j < NG; j++) {
      const a = arms[i], b = arms[j], d = a.c.clone().sub(b.c), L = d.length() || 1e-3; d.multiplyScalar(1 / L);
      const s = S[i][j], comp = (a.companion && a.partner === j) || (b.companion && b.partner === i);
      let f = 0;
      if (L < (a.rad + b.rad) * 1.3) f += ((a.rad + b.rad) * 1.3 - L) * 0.5;                     // never overlap
      else f += 0.002 * R * R / (L * L);                                                           // the unrelated spread out
      if (comp) f -= (L - (a.rad + b.rad) * 1.15) * 0.12;                                           // a companion beside its partner
      else if (s > 0) f -= (L - (a.rad + b.rad) * (1.4 + 2.2 / (1 + Math.log2(1 + s)))) * 0.05;   // related: closer, the more links
      F[i].addScaledVector(d, f); F[j].addScaledVector(d, -f);
    }
    arms.forEach((a, i) => {
      a.c.add(F[i]);
      const L0 = a.c.length(), keep = R * 0.1 + a.rad * 0.7;   // clear of the nucleus
      if (L0 < keep) a.c.addScaledVector(L0 > 1e-4 ? a.c.clone().normalize() : new V3(1, 0, 0), keep - L0);
      a.c.y = clamp(a.c.y, -HH * 0.55 + a.rad, HH * 0.55 - a.rad);
      const lim = Math.max(R * 0.05, shellR(a.c.y) * 0.8 - a.rad), hr = Math.hypot(a.c.x, a.c.z);
      if (hr > lim) { a.c.x *= lim / hr; a.c.z *= lim / hr; }
    });
  }
  // each galaxy leans partly toward its strongest partner (linked discs face each other, like interacting galaxies)
  arms.forEach(a => {
    const nrm = new V3(0, 1, 0).applyQuaternion(a.q);
    if (a.partner >= 0) { const to = arms[a.partner].c.clone().sub(a.c).normalize(), want = nrm.dot(to) < 0 ? to.negate() : to;
      const n2 = nrm.clone().lerp(want, a.companion ? 0.55 : 0.35).normalize(); a.q = new THREE.Quaternion().setFromUnitVectors(nrm, n2).multiply(a.q); }
    a.nrm = new V3(0, 1, 0).applyQuaternion(a.q); a.ax = new V3(1, 0, 0).applyQuaternion(a.q); a.az2 = new V3(0, 0, 1).applyQuaternion(a.q);
    a.az = Math.atan2(a.c.z, a.c.x); a.lift = Math.sign(a.c.y) || 1; a.ang = a.az;
    if (a.kind === 'irregular') { const h = hashKey(a.key + 'c'); for (let k = 0; k < 3 + (h % 3); k++)
      a.clumps.push(new V3(gauss(), gauss() * 0.5, gauss()).multiplyScalar(a.rad * 0.45)); }
  });
  // a point of a galaxy in its own frame (x along ax, y along its normal, z along az2) -> world
  const toWorld = (a, x, y, z) => a.c.clone().addScaledVector(a.ax, x).addScaledVector(a.nrm, y).addScaledVector(a.az2, z);
  const spiralLocal = (a, j, r, dth = 0) => { const th = a.ph + j * TAU / Math.max(1, a.nArms) + r * a.tight + dth;
    return [Math.cos(th) * r * a.rad, Math.sin(th) * r * a.rad]; };
  // claims: spirals along their arms (the newest near the core, the oldest at the rim: time runs outward);
  // irregulars in their clumps; ellipticals in their body
  const pos = new Array(claims.length), place = new Array(claims.length);
  const groups = new Map();
  claims.forEach((c, i) => { const gg = groups.get(c.reg) || []; gg.push(i); groups.set(c.reg, gg); });
  for (const [reg, idx] of groups) {
    idx.sort((p, q) => (claims[q].born || 0) - (claims[p].born || 0));
    const a = reg >= 0 && reg < arms.length ? arms[reg] : null;
    idx.forEach((ci, k) => {
      const t = idx.length > 1 ? k / (idx.length - 1) : 0.5;
      if (a && a.kind === 'spiral') {
        const j = k % a.nArms, r = clamp(0.16 + 0.78 * t + gauss() * 0.05, 0.1, 0.98), dth = gauss() * 0.22 * (1 - r * 0.3);
        const [x, z] = spiralLocal(a, j, r, dth), y = gauss() * a.rad * (0.03 + 0.05 * (1 - r));
        pos[ci] = toWorld(a, x, y, z); place[ci] = { arm: reg, j, r, th: a.ph + j * TAU / a.nArms + r * a.tight + dth, y };
      } else if (a) {
        const base = a.kind === 'irregular' ? a.clumps[k % a.clumps.length] : new V3();
        const v = base.clone().add(new V3(gauss(), gauss() * 0.6, gauss()).multiplyScalar(a.rad * (a.kind === 'irregular' ? 0.14 : 0.36)));
        pos[ci] = toWorld(a, v.x, v.y, v.z); place[ci] = { arm: reg, j: 0, r: clamp(Math.hypot(v.x, v.z) / a.rad, 0, 1), th: Math.atan2(v.z, v.x), y: v.y };
      } else {   // beyond the drawn galaxies: the nucleus side, still a place of its own
        pos[ci] = new V3(gauss(), gauss(), gauss()).multiplyScalar(R * 0.05); place[ci] = { halo: true };
      }
    });
  }
  // §9.2 a domain's halo: seven orbits in its galaxy's plane, beside it; reg -1 = the nucleus side
  const HALO_R = R * 0.05;
  const galOf = reg => (reg >= 0 && reg < arms.length ? arms[reg] : null);
  const haloFrame = reg => { const a = galOf(reg);
    if (a) return { c: a.c.clone().addScaledVector(a.nrm, a.rad * 0.55).addScaledVector(a.ax, a.rad * 0.85), u: a.ax, v: a.az2 };
    return { c: new V3(0, R * 0.16, 0), u: new V3(1, 0, 0), v: new V3(0, 0, 1) }; };
  const orbit = (reg, space) => { const f = haloFrame(reg), i = Math.max(0, HALO_SPACES.indexOf(space)), an = i / HALO_SPACES.length * TAU;
    return f.c.clone().addScaledVector(f.u, Math.cos(an) * HALO_R).addScaledVector(f.v, Math.sin(an) * HALO_R); };
  const hasHalo = reg => reg === -1 || !!galOf(reg);
  // §10 a pin: still, near its galaxy's core, every pin its own place
  const pinAt = (reg, j) => { const a = galOf(reg), fr = (j * 0.6180339) % 1, fz = (j * 0.7548777) % 1;
    if (a && a.kind === 'spiral') { const [x, z] = spiralLocal(a, j % a.nArms, 0.2 + 0.45 * fr, -0.35); return toWorld(a, x, a.rad * 0.06 * (fz - 0.5), z); }
    if (a) return toWorld(a, (fr - 0.5) * a.rad * 0.6, (fz - 0.5) * a.rad * 0.2, ((fr * 7) % 1 - 0.5) * a.rad * 0.6);
    const an = j * 2.399963, r = R * (0.06 + 0.012 * (j % 6)); return new V3(Math.cos(an) * r, -R * 0.1, Math.sin(an) * r); };
  // the sector dial (outside): on a ring at the equator, at the galaxy's compass angle
  const DIAL_R = GR * 1.5;
  const labelAt = reg => { const a = galOf(reg); if (!a) return null; return new V3(Math.cos(a.az) * DIAL_R, 0, Math.sin(a.az) * DIAL_R); };
  // looking at a galaxy: from above its disc and a little outward, far enough to see it whole with its neighbours
  const viewOf = reg => { const a = galOf(reg); if (!a) return null;
    const out = a.c.clone().setY(0); if (out.lengthSq() < 1e-4) out.set(1, 0, 0); out.normalize();
    const n = a.nrm.dot(out) < 0 ? a.nrm.clone().negate() : a.nrm.clone();
    return { pivot: a.c.clone(), eye: a.c.clone().addScaledVector(n.multiplyScalar(0.75).add(out.multiplyScalar(0.65)).normalize(), a.rad * 3.2) }; };
  // the cosmic-web filament between two galaxies: a curve that bows away from the nucleus (travel follows it)
  const pathBetween = (ra, rb) => { const a = galOf(ra), b = galOf(rb); if (!a || !b) return null;
    const m = a.c.clone().add(b.c).multiplyScalar(0.5), push = m.clone(); if (push.lengthSq() < 1e-4) push.set(0, 1, 0);
    m.addScaledVector(push.normalize(), R * 0.08); return [a.c.clone(), m, b.c.clone()]; };
  const related = reg => (S[reg] || []).map((s, j) => ({ reg: j, s })).filter(o => o.s > 0).sort((p, q) => q.s - p.s);
  return { GR, HH, R, arms, sats: [], pos, place, tilt: new THREE.Quaternion(), posWorld: pos.map(p => (p ? p.clone() : p)),
    shellR, toWorld, spiralLocal, HALO_R, hasHalo, haloCentre: reg => haloFrame(reg).c, haloOrbit: orbit, haloOrbitLocal: orbit,
    haloQ: reg => { const a = galOf(reg); return a ? a.q.clone() : new THREE.Quaternion(); },
    pinAt, labelAt, viewOf, pathBetween, related, S, DIAL_R };
}

const FOCUS_GLSL = `float focusDim(float reg,float foc){return foc<-.5?1.:(abs(reg-foc)<.5?1.2:(reg<-.5?.55:.22));}`;
const STAR_VS = `uniform float uTime,uPix,uVis,uFoc;attribute float aA,aPh,aSz,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;
  ${FOCUS_GLSL}
  void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float tw=.78+.22*sin(uTime*(.6+aPh*.9)+aPh*40.);
    vC=aC;vA=aA*tw*uVis*smoothstep(.4,3.,-mv.z)*focusDim(aReg,uFoc);gl_PointSize=min(aSz*uPix*(60./-mv.z),6.*uPix);gl_Position=projectionMatrix*mv;}`;
const STAR_FS = `varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
  gl_FragColor=vec4(vC,(smoothstep(.5,.0,d)*.55+smoothstep(.18,.0,d)*.6)*vA);}`;
// soft glows (galaxy cores and halos, nebula clumps, far galaxies): large, faint, gaussian
const GLOW_VS = `uniform float uPix,uVis,uFoc;attribute float aA,aSz,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;
  ${FOCUS_GLSL}
  void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vC=aC;vA=aA*uVis*focusDim(aReg,uFoc)*smoothstep(.3,2.5,-mv.z);
    gl_PointSize=clamp(aSz*uPix*(300./-mv.z),2.*uPix,180.*uPix);gl_Position=projectionMatrix*mv;}`;
const GLOW_FS = `varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=dot(c,c)*4.;if(d>1.)discard;gl_FragColor=vec4(vC,exp(-d*3.2)*vA);}`;

/**
 * The scene objects. `links`: [{a, b, w}] claim-index pairs with a use weight 0..1 (traversals, log-scaled).
 * Returns {group, update, pulse, focus, mark, dispose, arms, sats}.
 */
export function createGalaxy({ R, U, layout, links, halos = [], claimNodes = [], pins = [], claimInfo = [], seed = 11 }) {
  const rng = rngOf(seed);
  const gauss = () => (rng() + rng() + rng() + rng()) / 2 - 1;
  const { GR, HH, arms, pos, place, shellR, toWorld, spiralLocal } = layout;
  const sats = [];
  const g = new THREE.Group();
  const uni = { ...U, uVis: { value: 1 }, uIn: { value: 0 }, uHalo: { value: -9 }, uFoc: { value: -1 }, uFocArm: { value: -1 }, uHov: { value: -1 }, uSel: { value: -1 } };
  const disposables = [];
  const W = new THREE.Color('#ffffff'), WARM = new THREE.Color('#ffe2b8'), COOL = new THREE.Color('#bfe0ff');
  const bez = (A0, M0, B0, u) => { const q = 1 - u; return new V3(q * q * A0.x + 2 * q * u * M0.x + u * u * B0.x, q * q * A0.y + 2 * q * u * M0.y + u * u * B0.y, q * q * A0.z + 2 * q * u * M0.z + u * u * B0.z); };
  const addPoints = (P, C, A, PH, SZ, RG = null, vs = STAR_VS, fs = STAR_FS) => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
    geo.setAttribute('aReg', new THREE.Float32BufferAttribute(RG || new Array(P.length / 3).fill(-1), 1));
    geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3));
    geo.setAttribute('aA', new THREE.Float32BufferAttribute(A, 1));
    geo.setAttribute('aPh', new THREE.Float32BufferAttribute(PH, 1));
    geo.setAttribute('aSz', new THREE.Float32BufferAttribute(SZ, 1));
    const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: vs, fragmentShader: fs, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(geo, mat); o.frustumCulled = false; g.add(o); disposables.push(geo, mat); return o;
  };
  const glows = { P: [], C: [], A: [], PH: [], SZ: [], RG: [] };
  const glow = (p, col, a, sz, reg = -1) => { glows.P.push(p.x, p.y, p.z); glows.C.push(col.r, col.g, col.b); glows.A.push(a); glows.PH.push(0); glows.SZ.push(sz); glows.RG.push(reg); };

  // ── deep space (owner, 2026-11-23: seen from outer space - a multitude of universes): a far star field and far
  //    galaxies beyond the shell. The memory is one of many. ─────────────────────────────────────────────────────
  {
    const P = [], C = [], A = [], PH = [], SZ = [];
    for (let i = 0; i < 2600; i++) { const u = rng() * 2 - 1, ph = rng() * TAU, q = Math.sqrt(1 - u * u), rr = R * (14 + 8 * rng());
      P.push(Math.cos(ph) * q * rr, u * rr, Math.sin(ph) * q * rr); const c = COOL.clone().lerp(WARM, rng()); C.push(c.r, c.g, c.b);
      A.push(0.08 + 0.3 * Math.pow(rng(), 3)); PH.push(rng()); SZ.push(1.6 + rng() * 2.4); }
    for (let k = 0; k < 7; k++) {
      const u = rng() * 1.4 - 0.7, ph = rng() * TAU, q = Math.sqrt(1 - u * u), rr = R * (12 + 5 * rng());
      const c0 = new V3(Math.cos(ph) * q * rr, u * rr, Math.sin(ph) * q * rr), qq = new THREE.Quaternion().setFromEuler(new THREE.Euler(rng() * 3, rng() * 3, rng() * 3));
      const col = new THREE.Color().setHSL(rng(), 0.45, 0.72), rad = R * (0.25 + 0.35 * rng()), na = 2 + (k % 2);
      for (let i = 0; i < 260; i++) { const r = Math.pow(rng(), 0.7), th = (i % na) * TAU / na + r * 4 + gauss() * 0.35;
        const v = new V3(Math.cos(th) * r * rad, gauss() * rad * 0.05, Math.sin(th) * r * rad).applyQuaternion(qq).add(c0);
        P.push(v.x, v.y, v.z); const cc = col.clone().lerp(W, 0.5 * (1 - r)); C.push(cc.r, cc.g, cc.b); A.push(0.05 + 0.12 * (1 - r)); PH.push(rng()); SZ.push(1.4); }
      glow(c0, col.clone().lerp(W, 0.4), 0.05, rad / R * 8);
    }
    addPoints(P, C, A, PH, SZ);
  }

  // ── the galaxies: one per domain - spiral (enough claims), irregular companion (linked to a bigger one), elliptical ─
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [];
    const total = 15000, wsum = arms.reduce((s, a) => s + 0.25 + a.size, 0) || 1;
    arms.forEach(a => {
      const n = Math.round(total * (0.25 + a.size) / wsum), coreC = WARM.clone().lerp(a.col, 0.25);
      for (let i = 0; i < n; i++) {
        let x, y, z, r;
        if (a.kind === 'spiral') {
          r = Math.pow(rng(), 0.75);
          if (a.bar && r < 0.3 && rng() < 0.5) { const s = (rng() * 2 - 1) * 0.3; x = Math.cos(a.ph) * s * a.rad + gauss() * a.rad * 0.03; z = Math.sin(a.ph) * s * a.rad + gauss() * a.rad * 0.03; }
          else { const j = Math.floor(rng() * a.nArms), dth = gauss() * 0.32 * (1 - r * 0.3); [x, z] = spiralLocal(a, j, r, dth); }
          y = gauss() * a.rad * (0.02 + 0.09 * Math.exp(-r * 4));   // a thin disc, a swollen bulge
        } else if (a.kind === 'irregular') {
          const cl = a.clumps[Math.floor(rng() * a.clumps.length)], v = cl.clone().add(new V3(gauss(), gauss() * 0.5, gauss()).multiplyScalar(a.rad * 0.18));
          x = v.x; y = v.y; z = v.z; r = clamp(v.length() / a.rad, 0, 1);
        } else {
          const v = new V3(gauss(), gauss() * 0.65, gauss()); r = clamp(v.length() / 1.4, 0, 1); v.multiplyScalar(a.rad * 0.42); x = v.x; y = v.y; z = v.z;
        }
        const p = toWorld(a, x, y, z); P.push(p.x, p.y, p.z);
        const c = a.kind === 'elliptical' ? coreC.clone().lerp(a.col, 0.4 * r) : a.col.clone().lerp(coreC, Math.pow(1 - r, 2.2)).lerp(W, 0.12 * (1 - r));
        C.push(c.r, c.g, c.b); A.push((0.08 + 0.2 * (1 - r)) * (a.kind === 'spiral' ? 1 : 0.85)); PH.push(rng()); SZ.push(1.0 + rng() * 0.9); RG.push(a.reg);
      }
      // the core: its brightness = how much this domain's claims were used
      for (let i = 0; i < 70; i++) { const v = new V3(gauss(), gauss() * 0.7, gauss()).multiplyScalar(a.rad * 0.06); const p = toWorld(a, v.x, v.y, v.z);
        P.push(p.x, p.y, p.z); C.push(coreC.r, coreC.g, coreC.b); A.push(0.25 * a.core); PH.push(rng()); SZ.push(1.8); RG.push(a.reg); }
      glow(a.c, coreC, 0.16 * a.core, a.rad / R * 9, a.reg);
      glow(a.c, a.col, 0.045, a.rad / R * 26, a.reg);   // the faint halo of the whole galaxy
    });
    addPoints(P, C, A, PH, SZ, RG);
  }

  // ── the claims ARE stars of their galaxy: a core in the domain's tint; a ring = proven (solid) or still learning
  //    (dashed); brightness = sync; they grow as you go inside (uIn); hover and focus ring them white ──────────────
  const CLAIM_VS = `uniform float uTime,uPix,uVis,uIn,uFoc,uHov,uSel;attribute float aIdx,aProven,aSync,aReg,aPh;attribute vec3 aC;
    varying vec3 vC;varying float vA,vP,vH,vS;
    ${FOCUS_GLSL}
    void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float h=step(abs(aIdx-uHov),.5),sel=step(abs(aIdx-uSel),.5);
      vC=aC;vP=aProven;vH=h;vS=sel;float tw=.85+.15*sin(uTime*(.4+aPh)+aPh*30.);
      vA=(.3+.55*aSync)*tw*uVis*focusDim(aReg,uFoc)*(1.+.6*max(h,sel));
      float sz=(1.6+1.6*aSync)*(1.+1.2*uIn)*(1.+.7*max(h,sel));
      gl_PointSize=clamp(sz*uPix*(60./-mv.z),2.*uPix,(8.+5.*uIn+8.*max(h,sel))*uPix);gl_Position=projectionMatrix*mv;}`;
  const CLAIM_FS = `varying vec3 vC;varying float vA,vP,vH,vS;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    float core=smoothstep(.17,.0,d),glow=smoothstep(.5,.0,d)*.28,ang=atan(c.y,c.x);
    float ring=smoothstep(.045,.0,abs(d-.36))*mix(step(0.,sin(ang*10.))*.55,1.,vP);
    float hi=max(vH,vS);vec3 col=mix(vC,vec3(1.),.35+.4*hi);
    gl_FragColor=vec4(col,(core*.95+glow+ring*(.45+.55*hi))*vA);}`;
  {
    const P = [], C = [], IX = [], PR = [], SY = [], RG = [], PH = [];
    pos.forEach((p, k) => { if (!p) return; const pl = place[k] || {}, info = claimInfo[k] || {}, a = pl.arm != null ? arms[pl.arm] : null;
      const col = a ? a.col.clone().lerp(W, 0.45) : new THREE.Color('#cfe9f5');
      P.push(p.x, p.y, p.z); C.push(col.r, col.g, col.b); IX.push(k); PR.push(info.proven ? 1 : 0); SY.push(clamp(info.sync ?? 0.4, 0, 1)); RG.push(a ? a.reg : -1); PH.push(rng()); });
    if (P.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3));
      geo.setAttribute('aIdx', new THREE.Float32BufferAttribute(IX, 1)); geo.setAttribute('aProven', new THREE.Float32BufferAttribute(PR, 1));
      geo.setAttribute('aSync', new THREE.Float32BufferAttribute(SY, 1)); geo.setAttribute('aReg', new THREE.Float32BufferAttribute(RG, 1));
      geo.setAttribute('aPh', new THREE.Float32BufferAttribute(PH, 1));
      const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: CLAIM_VS, fragmentShader: CLAIM_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      const o = new THREE.Points(geo, mat); o.frustumCulled = false; o.renderOrder = 2; g.add(o); disposables.push(geo, mat);
    }
  }

  // ── the cosmic web (owner, 2026-11-23: show the galaxies in relation to each other): a filament of stars between
  //    two galaxies whose claims are linked, brighter and wider with more links; a faint thread from every galaxy to
  //    the nucleus. Light streams along them (a moving wave in the shader). ──────────────────────────────────────
  const FIL_VS = `uniform float uTime,uPix,uVis,uFoc;attribute float aA,aPh,aSz,aReg,aU,aRegB;attribute vec3 aC;varying vec3 vC;varying float vA;
    ${FOCUS_GLSL}
    void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float flow=.55+.45*sin(aU*38.-uTime*1.3+aPh*2.);
      float fd=max(focusDim(aReg,uFoc),focusDim(aRegB,uFoc));
      vC=aC;vA=aA*flow*uVis*fd*smoothstep(.3,2.5,-mv.z);gl_PointSize=clamp(aSz*uPix*(60./-mv.z),1.3*uPix,5.*uPix);gl_Position=projectionMatrix*mv;}`;
  const S = layout.S || [];
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [], RB = [], UU = [];
    const fil = (A0, M0, B0, ca, cb, n, spread, a0, ra, rb) => { for (let i = 0; i < n; i++) { const u = rng(), p = bez(A0, M0, B0, u), env = 0.35 + 0.65 * Math.sin(u * Math.PI);
      P.push(p.x + gauss() * spread * env, p.y + gauss() * spread * env, p.z + gauss() * spread * env); const c = ca.clone().lerp(cb, u);
      C.push(c.r, c.g, c.b); A.push(a0 * (0.5 + 0.5 * env)); PH.push(rng()); SZ.push(1.1 + rng() * 0.7); RG.push(ra); RB.push(rb); UU.push(u); } };
    for (let i = 0; i < arms.length; i++) for (let j = i + 1; j < arms.length; j++) {
      const cnt = (S[i] && S[i][j]) || 0; if (!cnt) continue; const path = layout.pathBetween(i, j); if (!path) continue;
      const s = Math.log2(1 + cnt);
      fil(path[0], path[1], path[2], arms[i].col, arms[j].col, Math.round(90 + 70 * s), R * (0.006 + 0.004 * s), 0.1 + 0.04 * Math.min(4, s), i, j);
      for (let k = 0; k < 3; k++) glow(bez(path[0], path[1], path[2], 0.3 + 0.2 * k), arms[i].col.clone().lerp(arms[j].col, 0.3 + 0.2 * k), 0.018, 3 + 2 * rng());   // nebula dust where they meet
    }
    arms.forEach(a => { const m = a.c.clone().multiplyScalar(0.5).add(new V3(0, R * 0.04, 0)); fil(a.c, m, new V3(), a.col, WARM, 70, R * 0.004, 0.07, a.reg, a.reg); });
    if (P.length) { const o = addPoints(P, C, A, PH, SZ, RG, FIL_VS);
      o.geometry.setAttribute('aU', new THREE.Float32BufferAttribute(UU, 1)); o.geometry.setAttribute('aRegB', new THREE.Float32BufferAttribute(RB, 1)); }
  }

  // ── hyphae: claim links. In one galaxy: along its own spiral (each link its own lane). Between galaxies: the link
  //    rides the cosmic-web filament (A -> its galaxy -> the web -> the other galaxy -> B), so links bundle into
  //    cords. Lit by use: a base glow from the link's weight, a light runs along it when a recall walks it. ────────
  const HYPHA_VS = `uniform float uTime,uVis,uIn,uFoc;uniform vec2 uPulse[${PULSE_SLOTS}];attribute float aLink,aU,aW,aReg;varying float vA;
    ${FOCUS_GLSL}
    void main(){float lit=0.;for(int i=0;i<${PULSE_SLOTS};i++){vec2 p=uPulse[i];if(p.x==aLink){float age=uTime-p.y;float head=age/1.1;
      lit=max(lit,smoothstep(.09,0.,abs(aU-head))*step(0.,age)*step(age,1.6)+.6*smoothstep(1.,0.,age)*step(0.,age));}}
      vA=(step(.001,aW)*(.014+.05*aW)*(.3+.7*sin(aU*3.14159))*(1.-.5*uIn)*focusDim(aReg,uFoc)+lit*.75)*uVis;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`;
  const HYPHA_FS = `varying float vA;void main(){gl_FragColor=vec4(.8,.96,.92,vA);}`;
  const linkOf = new Map();
  {
    const P = [], L = [], UU = [], WW = [], RG = [];
    const deg = new Map(), kept = [];
    for (const it of links.map((ln, id) => ({ ln, id })).sort((x, y) => (y.ln.w || 0) - (x.ln.w || 0))) {
      if (kept.length >= MAX_LINKS) break;
      const da = deg.get(it.ln.a) || 0, db = deg.get(it.ln.b) || 0; if (da >= LINKS_PER_CLAIM || db >= LINKS_PER_CLAIM) continue;
      deg.set(it.ln.a, da + 1); deg.set(it.ln.b, db + 1); kept.push(it);
    }
    kept.forEach(({ ln, id }) => {
      const pa = place[ln.a], pb = place[ln.b]; if (!pa || !pb || !pos[ln.a] || !pos[ln.b] || pa.arm == null || pb.arm == null) return;
      const pts = [];
      if (pa.arm === pb.arm) {
        const a = arms[pa.arm];
        for (let k = 0; k <= 14; k++) { const u = k / 14, env = Math.sin(u * Math.PI), r = lerp(pa.r, pb.r, u), th = lerp(pa.th, pb.th, u) + ((id * 0.618) % 1 - 0.5) * 0.25 * env;
          const y = lerp(pa.y, pb.y, u) + ((id * 0.7548) % 1 - 0.5) * a.rad * 0.08 * env;
          pts.push(toWorld(a, Math.cos(th) * r * a.rad, y, Math.sin(th) * r * a.rad)); }
      } else {
        const A0 = pos[ln.a], B0 = pos[ln.b], ca = arms[pa.arm].c, cb = arms[pb.arm].c, path = layout.pathBetween(pa.arm, pb.arm);
        const m = path ? path[1] : ca.clone().add(cb).multiplyScalar(0.5), jit = new V3(gauss(), gauss(), gauss()).multiplyScalar(R * 0.01);
        const c1 = ca.clone().lerp(m, 0.35).add(jit), c2 = cb.clone().lerp(m, 0.35).add(jit);
        for (let k = 0; k <= 18; k++) { const u = k / 18, q = 1 - u;
          pts.push(new V3(q * q * q * A0.x + 3 * q * q * u * c1.x + 3 * q * u * u * c2.x + u * u * u * B0.x,
            q * q * q * A0.y + 3 * q * q * u * c1.y + 3 * q * u * u * c2.y + u * u * u * B0.y,
            q * q * q * A0.z + 3 * q * q * u * c1.z + 3 * q * u * u * c2.z + u * u * u * B0.z)); }
      }
      const reg = pa.arm === pb.arm ? arms[pa.arm].reg : -1;
      for (let k = 0; k < pts.length - 1; k++) {
        P.push(pts[k].x, pts[k].y, pts[k].z, pts[k + 1].x, pts[k + 1].y, pts[k + 1].z);
        L.push(id, id); UU.push(k / (pts.length - 1), (k + 1) / (pts.length - 1)); WW.push(Math.max(0.05, ln.w), Math.max(0.05, ln.w)); RG.push(reg, reg);
      }
      [ln.a, ln.b].forEach(c => { const l = linkOf.get(c) || []; l.push(id); linkOf.set(c, l); });
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aLink', new THREE.Float32BufferAttribute(L, 1));
    geo.setAttribute('aU', new THREE.Float32BufferAttribute(UU, 1)); geo.setAttribute('aW', new THREE.Float32BufferAttribute(WW, 1));
    geo.setAttribute('aReg', new THREE.Float32BufferAttribute(RG, 1));
    uni.uPulse = { value: Array.from({ length: PULSE_SLOTS }, () => new THREE.Vector2(-1, -99)) };
    const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: HYPHA_VS, fragmentShader: HYPHA_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.LineSegments(geo, mat); o.frustumCulled = false; g.add(o); disposables.push(geo, mat);
  }

  // ── the woven shell: every galaxy sends an anchor thread to the shell's equator that becomes its strands to the two
  //    poles (big galaxies three strands a side, small ones one). Strands are star streams. ───────────────────────
  const DIAL_R = layout.DIAL_R || GR * 1.5;
  const NS = 40, strands = [];
  arms.forEach((a, ai) => { const fs = a.size > 0.45 && a.kind === 'spiral' ? [-1, 0, 1] : [0]; for (const f of fs) for (const dir of [1, -1]) strands.push({ ai, f, dir }); });
  const y0Of = a => clamp(a.c.y, -HH * 0.3, HH * 0.3);
  const strandPt = (sd, s) => {
    const a = arms[sd.ai], th = a.az + sd.f * 0.2 + sd.dir * 1.1 * s + sd.f * 0.15 * s;
    const h = y0Of(a) * (1 - s) + sd.dir * HH * Math.pow(Math.sin(s * Math.PI / 2), 1.15), rho = shellR(h, a.size);
    return new V3(Math.cos(th) * rho, h, Math.sin(th) * rho);
  };
  const SAMPLES = strands.map(sd => Array.from({ length: NS + 1 }, (_, j) => strandPt(sd, j / NS)));
  // the anchor thread: from the galaxy's outer edge, toward the shell, to the strand's start
  const edgeOf = a => { const out = a.c.clone().setY(0); if (out.lengthSq() < 1e-4) out.set(Math.cos(a.az), 0, Math.sin(a.az)); return a.c.clone().addScaledVector(out.normalize(), a.rad * 0.9); };
  const armLeg = (sd, u) => { const e = edgeOf(arms[sd.ai]), s0 = strandPt(sd, 0), m = e.clone().lerp(s0, 0.5); m.y = lerp(e.y, s0.y, 0.2); return bez(e, m, s0, u); };
  const STRAND_VS = `uniform float uTime,uPix,uVis,uIn,uFocArm;uniform vec3 uSP[4];attribute float aS,aArm,aDir,aPh,aSz;attribute vec3 aC;varying vec3 vC;varying float vA;
    void main(){float lit=0.;for(int i=0;i<4;i++){vec3 p=uSP[i];float age=uTime-p.z;if(age<0.||age>4.)continue;
      if(age<.9&&p.x==aArm&&aS<0.){float s=age/.9-1.;lit=max(lit,exp(-pow(aS-s,2.)/.004));}
      if(age>=.9&&age<2.1&&p.x==aArm&&p.y==aDir){float s=(age-.9)/1.2;lit=max(lit,exp(-pow(aS-s,2.)/.004));}
      if(age>=2.1&&p.y==aDir){float e=age-2.1;float back=max(0.,1.-e/1.6);lit=max(lit,.55*back*exp(-pow((1.-aS)-e*.8,2.)/.006));}}
      vec4 mv=modelViewMatrix*vec4(position,1.);float tw=.7+.3*sin(uTime*(.5+aPh*.8)+aPh*40.);
      float base=(aS<0.?.06+.12*pow(1.+aS,1.5):.3*(1.-.5*aS))*(uFocArm<-.5?1.:(abs(aArm-uFocArm)<.5?1.3:.3));
      vC=mix(aC,vec3(.96,1.,.98),clamp(lit,0.,1.));vA=(base*tw*(1.-.85*uIn)+.9*lit)*uVis*smoothstep(.4,3.,-mv.z);
      gl_PointSize=clamp((aSz+1.4*lit)*uPix*(60./-mv.z),1.4*uPix,(4.+3.*lit)*uPix);gl_Position=projectionMatrix*mv;}`;
  const LINE_FS = `varying vec3 vC;varying float vA;void main(){gl_FragColor=vec4(vC,vA);}`;
  uni.uSP = { value: Array.from({ length: 4 }, () => new V3(-1, 0, -99)) };
  {
    const P = [], SS = [], AR = [], DR = [], C = [], PH = [], SZ = [];
    const push = (p, sv, ai, dir, col, sz, spread) => { P.push(p.x + gauss() * spread, p.y + gauss() * spread, p.z + gauss() * spread);
      SS.push(sv); AR.push(ai); DR.push(dir); C.push(col.r, col.g, col.b); PH.push(rng()); SZ.push(sz); };
    const at = (arr, ns, sv) => { const f = sv * ns, i0 = Math.min(ns - 1, Math.floor(f)); return arr[i0].clone().lerp(arr[i0 + 1], f - i0); };
    strands.forEach((sd, n) => {
      const col = arms[sd.ai].col.clone().lerp(W, 0.15), main = sd.f === 0, cnt = main ? 230 : 150;
      for (let i = 0; i < cnt; i++) { const sv = Math.pow(rng(), 1.25); push(at(SAMPLES[n], NS, sv), sv, sd.ai, sd.dir, col, main ? 1.25 : 1.0, R * (0.004 + 0.006 * (1 - sv))); }
      if (sd.dir > 0) for (let i = 0; i < 70; i++) { const u = rng(); push(armLeg(sd, u), u - 1, sd.ai, 0, col, 1.0, R * 0.005); }
    });
    const bridge = new THREE.Color(0.66, 0.85, 0.92);
    strands.forEach((sd, n) => {
      let nb = -1, bd = 9; strands.forEach((o, m) => { if (o.dir !== sd.dir || m === n) return;
        const da = ((arms[o.ai].az + o.f * 0.2) - (arms[sd.ai].az + sd.f * 0.2) + TAU * 2) % TAU; if (da > 0.01 && da < bd) { bd = da; nb = m; } });
      if (nb < 0) return;
      [0.22, 0.45, 0.68].forEach(s0 => { const a = strandPt(sd, s0), b = strandPt(strands[nb], s0);
        for (let k = 0; k < 16; k++) { const u = (k + rng()) / 16, sag = 0.92 - 0.06 * Math.sin(u * Math.PI), q = a.clone().lerp(b, u); q.x *= sag; q.z *= sag;
          push(q, s0, sd.ai, sd.dir, bridge, 0.9, R * 0.003); } });
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aS', new THREE.Float32BufferAttribute(SS, 1));
    geo.setAttribute('aArm', new THREE.Float32BufferAttribute(AR, 1)); geo.setAttribute('aDir', new THREE.Float32BufferAttribute(DR, 1));
    geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3)); geo.setAttribute('aPh', new THREE.Float32BufferAttribute(PH, 1));
    geo.setAttribute('aSz', new THREE.Float32BufferAttribute(SZ, 1));
    const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: STRAND_VS, fragmentShader: STAR_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(geo, mat); o.frustumCulled = false; o.userData.strands = true; g.add(o); disposables.push(geo, mat);
  }
  // dust: starts on the anchor thread and climbs the strand to the pole
  const DUST = 26, LEG_NS = 12, LEG_SHARE = 0.35;
  const dust = strands.map(() => Array.from({ length: DUST }, () => ({ s: rng(), v: 0.012 + rng() * 0.02, o: new V3(gauss(), gauss(), gauss()).multiplyScalar(R * 0.008) })));
  const LEG = strands.map(sd => Array.from({ length: LEG_NS + 1 }, (_, j) => armLeg(sd, 0.3 + 0.7 * j / LEG_NS)));
  const dCount = strands.length * DUST, dP = new Float32Array(Math.max(1, dCount) * 3), dC = new Float32Array(Math.max(1, dCount) * 3), dA = new Float32Array(Math.max(1, dCount));
  strands.forEach((sd, n) => { const c = arms[sd.ai].col; for (let k = 0; k < DUST; k++) dC.set([c.r, c.g, c.b], (n * DUST + k) * 3); });
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dP, 3)); dustGeo.setAttribute('aC', new THREE.BufferAttribute(dC, 3)); dustGeo.setAttribute('aA', new THREE.BufferAttribute(dA, 1));
  dustGeo.setAttribute('aPh', new THREE.Float32BufferAttribute(new Array(Math.max(1, dCount)).fill(0).map(() => rng()), 1));
  dustGeo.setAttribute('aSz', new THREE.Float32BufferAttribute(new Array(Math.max(1, dCount)).fill(1.1), 1));
  dustGeo.setAttribute('aReg', new THREE.Float32BufferAttribute(strands.flatMap(sd => new Array(DUST).fill(arms[sd.ai].reg)), 1));
  { const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: STAR_VS, fragmentShader: STAR_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(dustGeo, mat); o.frustumCulled = false; g.add(o); disposables.push(dustGeo, mat); }

  // ── §9.2 the halos: seven dots per domain (strength = how many of its nodes sit in that space) and a faint ring ──
  const HALO_VS = `uniform float uTime,uPix,uVis,uIn,uHalo;attribute float aA,aSz,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;
    void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float mine=step(abs(aReg-uHalo),.5);
      vC=aC;vA=aA*uVis*mix(1.-.55*uIn,1.+1.2*uIn,mine);gl_PointSize=min(aSz*uPix*(60./-mv.z),(5.+5.*mine*uIn)*uPix);gl_Position=projectionMatrix*mv;}`;
  const RING_VS = `uniform float uVis,uIn,uHalo;attribute float aReg;varying float vA;
    void main(){float mine=step(abs(aReg-uHalo),.5);vA=.05*uVis*mix(1.-.6*uIn,1.+2.*uIn,mine);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`;
  const colOfReg = reg => (reg >= 0 && arms[reg] ? arms[reg].col : new THREE.Color(0.85, 0.9, 0.95));
  if (halos.length) {
    const P = [], C = [], A = [], SZ = [], RG = [], LP = [], LR = [];
    halos.forEach(h => { const tint = colOfReg(h.reg);
      HALO_SPACES.forEach((sp, i) => {
        const o = layout.haloOrbitLocal(h.reg, sp), n = (h.counts && h.counts[sp]) || 0;
        P.push(o.x, o.y, o.z); C.push(tint.r, tint.g, tint.b); RG.push(h.reg);
        A.push(n > 0 ? 0.22 + 0.4 * Math.min(1, Math.log10(1 + n) / 2) : 0.05); SZ.push(n > 0 ? 3.2 + Math.min(2.5, Math.log10(1 + n) * 1.6) : 2.2);
        const o2 = layout.haloOrbitLocal(h.reg, HALO_SPACES[(i + 1) % HALO_SPACES.length]);
        LP.push(o.x, o.y, o.z, o2.x, o2.y, o2.z); LR.push(h.reg, h.reg);
      }); });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3));
    geo.setAttribute('aA', new THREE.Float32BufferAttribute(A, 1)); geo.setAttribute('aSz', new THREE.Float32BufferAttribute(SZ, 1));
    geo.setAttribute('aReg', new THREE.Float32BufferAttribute(RG, 1));
    const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: HALO_VS, fragmentShader: STAR_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(geo, mat); o.frustumCulled = false; g.add(o); disposables.push(geo, mat);
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', new THREE.Float32BufferAttribute(LP, 3)); lg.setAttribute('aReg', new THREE.Float32BufferAttribute(LR, 1));
    const lm = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: RING_VS, fragmentShader: `varying float vA;void main(){gl_FragColor=vec4(.8,.92,1.,vA);}`,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const l = new THREE.LineSegments(lg, lm); l.frustumCulled = false; g.add(l); disposables.push(lg, lm);
  }

  // ── the threads that hold things to their galaxy: a spur from each claim to its arm's spine; hyphae from a claim to
  //    the nodes its steps walked (in the halo); a stalk from the galaxy to its halo; a straight tether per pin ──────
  const THREAD_VS = `uniform float uTime,uVis,uIn;uniform vec2 uCP[${PULSE_SLOTS}];attribute float aClaim,aU,aA;attribute vec3 aC;varying vec3 vC;varying float vA;
    void main(){float lit=0.;for(int i=0;i<${PULSE_SLOTS};i++){vec2 p=uCP[i];if(p.x==aClaim){float age=uTime-p.y;
      lit=max(lit,smoothstep(.12,0.,abs(aU-age/.7))*step(0.,age)*step(age,1.)+.5*smoothstep(1.4,0.,age)*step(0.,age));}}
      vC=mix(aC,vec3(.96,1.,.98),clamp(lit,0.,1.));vA=(aA*(1.+.6*uIn)+.75*lit)*uVis;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`;
  uni.uCP = { value: Array.from({ length: PULSE_SLOTS }, () => new THREE.Vector2(-1, -99)) };
  {
    const P = [], CL = [], UU = [], AA = [], C = [];
    const curve = (A0, B0, ctl, n, claim, a0, col) => { let prev = A0;
      for (let k = 1; k <= n; k++) { const u = k / n, pt = bez(A0, ctl, B0, u);
        P.push(prev.x, prev.y, prev.z, pt.x, pt.y, pt.z); CL.push(claim, claim); UU.push((k - 1) / n, u);
        const fa = a0 * (0.55 + 0.45 * Math.sin(u * Math.PI)); AA.push(fa, fa); C.push(col.r, col.g, col.b, col.r, col.g, col.b); prev = pt; } };
    pos.forEach((p, k) => { const pl = place[k] || {}; if (!p || pl.arm == null) return; const a = arms[pl.arm];
      if (a.kind === 'spiral') { const [x, z] = spiralLocal(a, pl.j, pl.r), f = toWorld(a, x, 0, z); curve(p, f, p.clone().lerp(f, 0.5), 4, k, 0.035, a.col); }
      else curve(p, a.c, p.clone().lerp(a.c, 0.5), 4, k, 0.03, a.col); });
    claimNodes.slice(0, 3000).forEach(cn => { const p = pos[cn.k]; if (!p) return; const pl = place[cn.k] || {}, ctl = p.clone().lerp(cn.p, 0.5);
      ctl.y = lerp(p.y, cn.p.y, 0.15); curve(p, cn.p, ctl, 8, cn.k, 0.008, colOfReg(pl.arm != null ? pl.arm : -1)); });
    halos.forEach(h => { const c = layout.haloCentre(h.reg), a = h.reg >= 0 ? arms[h.reg] : null, base = a ? a.c.clone() : new V3();
      const col = colOfReg(h.reg); curve(base, c, base.clone().lerp(c, 0.5).add(new V3(0, R * 0.01, 0)), 8, -1, 0.07, col);
      HALO_SPACES.forEach(sp => { const o = layout.haloOrbitLocal(h.reg, sp), n = (h.counts && h.counts[sp]) || 0;
        curve(c, o, c.clone().lerp(o, 0.5), 2, -1, n > 0 ? 0.07 : 0.025, col); }); });
    pins.forEach(pn => { const a = pn.reg >= 0 ? arms[pn.reg] : null, to = a ? a.c : new V3();
      P.push(pn.p.x, pn.p.y, pn.p.z, to.x, to.y, to.z); CL.push(-1, -1); UU.push(0, 1); AA.push(0.1, 0.1); C.push(1, 0.86, 0.62, 1, 0.86, 0.62); });
    if (P.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aClaim', new THREE.Float32BufferAttribute(CL, 1));
      geo.setAttribute('aU', new THREE.Float32BufferAttribute(UU, 1)); geo.setAttribute('aA', new THREE.Float32BufferAttribute(AA, 1));
      geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3));
      const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: THREAD_VS, fragmentShader: LINE_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      const o = new THREE.LineSegments(geo, mat); o.frustumCulled = false; g.add(o); disposables.push(geo, mat);
    }
  }

  // ── the membrane: a faint woven skin on the shell's envelope, tinted by the nearest galaxy ──────────────────────
  {
    const prof = [];
    for (let j = 0; j <= 40; j++) { const y = HH * j / 40; prof.push(new THREE.Vector2(Math.max(0.001, shellR(y, 0.6) * 0.99), y)); }
    const full = [...prof.slice(1).reverse().map(v => new THREE.Vector2(v.x, -v.y)), ...prof];
    const geo = new THREE.LatheGeometry(full, 72);
    const C = [], pa = geo.attributes.position;
    for (let i = 0; i < pa.count; i++) { const th = Math.atan2(pa.getZ(i), pa.getX(i)); let best = 0, bd = 9;
      arms.forEach((a, k) => { const d = Math.abs(Math.atan2(Math.sin(th - a.az), Math.cos(th - a.az))); if (d < bd) { bd = d; best = k; } });
      const c = (arms[best] ? arms[best].col : new THREE.Color('#9fd6ee')).clone().lerp(new THREE.Color('#bfe9f5'), 0.35); C.push(c.r, c.g, c.b); }
    geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3));
    const mat = new THREE.ShaderMaterial({ uniforms: uni, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      vertexShader: `attribute vec3 aC;varying vec3 vC,vN,vV,vP;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vC=aC;vP=position;
        vN=normalize(normalMatrix*normal);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,
      fragmentShader: `uniform float uTime,uVis,uIn;varying vec3 vC,vN,vV,vP;void main(){float f=pow(1.-abs(dot(vN,vV)),2.6);
        float ph=atan(vP.z,vP.x),y=vP.y*${(4 / HH).toFixed(4)};
        float w=pow(abs(sin(ph*9.+y*1.6+uTime*.05)*sin(ph*9.-y*1.6-uTime*.04)),.35);
        gl_FragColor=vec4(vC,(.003+.034*f)*(.5+.5*w)*uVis*(1.-.85*uIn));}` });
    const o = new THREE.Mesh(geo, mat); o.frustumCulled = false; o.renderOrder = -1; g.add(o); disposables.push(geo, mat);
  }
  // the dial: a faint ring of stars at the equator, a tick of each domain's colour at its galaxy's compass angle
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [];
    for (let i = 0; i < 520; i++) { const th = i / 520 * TAU; P.push(Math.cos(th) * DIAL_R, 0, Math.sin(th) * DIAL_R); C.push(0.7, 0.86, 0.95); A.push(0.05); PH.push(rng()); SZ.push(0.9); RG.push(-1); }
    arms.forEach(a => { for (let i = -6; i <= 6; i++) { const t2 = a.az + i * 0.006;
      P.push(Math.cos(t2) * DIAL_R, 0, Math.sin(t2) * DIAL_R); C.push(a.col.r, a.col.g, a.col.b); A.push(0.5 - Math.abs(i) * 0.03); PH.push(rng()); SZ.push(1.8); RG.push(a.reg); } });
    addPoints(P, C, A, PH, SZ, RG);
  }
  // the soft glows (galaxy cores and halos, nebula dust, far galaxies), drawn once
  if (glows.P.length) addPoints(glows.P, glows.C, glows.A, glows.PH, glows.SZ, glows.RG, GLOW_VS, GLOW_FS);

  // the poles: where the strands meet; they flash once when a recall pulse arrives
  const poleGeo = new THREE.BufferGeometry();
  poleGeo.setAttribute('position', new THREE.Float32BufferAttribute([0, HH, 0, 0, -HH, 0], 3));
  poleGeo.setAttribute('aF', new THREE.Float32BufferAttribute([0, 0], 1));
  const poleMat = new THREE.ShaderMaterial({ uniforms: uni,
    vertexShader: `uniform float uPix,uVis;attribute float aF;varying float vF,vA;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vF=aF;vA=uVis;gl_PointSize=min((6.+26.*aF)*uPix*(60./-mv.z),60.*uPix);gl_Position=projectionMatrix*mv;}`,
    fragmentShader: `varying float vF,vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);float core=smoothstep(.2,0.,d);float ring=smoothstep(.5,.44,d)*smoothstep(.36,.42,d)*vF;gl_FragColor=vec4(.92,.99,1.,(core*(.35+.6*vF)+ring*.6)*vA);}`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  { const o = new THREE.Points(poleGeo, poleMat); o.frustumCulled = false; g.add(o); disposables.push(poleGeo, poleMat); }
  // pulse heads (CPU, at most PULSE_SLOTS): claim -> its galaxy's anchor edge (or straight to the pole)
  const headGeo = new THREE.BufferGeometry(), hP = new Float32Array(PULSE_SLOTS * 3), hA = new Float32Array(PULSE_SLOTS);
  headGeo.setAttribute('position', new THREE.BufferAttribute(hP, 3)); headGeo.setAttribute('aA', new THREE.BufferAttribute(hA, 1));
  headGeo.setAttribute('aC', new THREE.Float32BufferAttribute(new Array(PULSE_SLOTS * 3).fill(1), 3));
  headGeo.setAttribute('aPh', new THREE.Float32BufferAttribute(new Array(PULSE_SLOTS).fill(0), 1));
  headGeo.setAttribute('aSz', new THREE.Float32BufferAttribute(new Array(PULSE_SLOTS).fill(3.2), 1));
  headGeo.setAttribute('aReg', new THREE.Float32BufferAttribute(new Array(PULSE_SLOTS).fill(-1), 1));
  { const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: STAR_VS, fragmentShader: STAR_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(headGeo, mat); o.frustumCulled = false; g.add(o); disposables.push(headGeo, mat); }

  let pulses = [], linkSlot = 0, strandSlot = 0, claimSlot = 0, now = 0;
  /** A recall used claim `k`: its links and threads light; a light runs from the claim to its galaxy's anchor, up a
   *  strand to the pole, and back down every strand on that side. Real recall events only (engine liveEmit). */
  function pulse(k) {
    const pl = place[k]; if (!pl || !pos[k]) return;
    uni.uCP.value[claimSlot % PULSE_SLOTS].set(k, now); claimSlot++;
    (linkOf.get(k) || []).slice(0, 3).forEach(id => { uni.uPulse.value[linkSlot % PULSE_SLOTS].set(id, now); linkSlot++; });
    const a = pl.arm != null ? arms[pl.arm] : null, dir = a ? (Math.sign(a.c.y) || ((k % 2) ? 1 : -1)) : (Math.sign(pos[k].y) || 1);
    uni.uSP.value[strandSlot % 4].set(a ? pl.arm : -2, dir, now); strandSlot++;
    pulses.push({ from: pos[k].clone(), to: a ? edgeOf(a) : new V3(0, dir * HH, 0), dur: a ? 0.9 : 2.1, dir, t0: now });
    if (pulses.length > PULSE_SLOTS) pulses.shift();
  }

  function update(t, vis, inside = 0, haloReg = -9) {
    now = t; uni.uVis.value = vis; uni.uIn.value = inside; uni.uHalo.value = haloReg;
    strands.forEach((sd, n) => dust[n].forEach((d, j) => { const q = (d.s + t * d.v) % 1, onLeg = q < LEG_SHARE;
      const s = onLeg ? q / LEG_SHARE : (q - LEG_SHARE) / (1 - LEG_SHARE), path = onLeg ? LEG[n] : SAMPLES[n], ns = onLeg ? LEG_NS : NS;
      const f = s * ns, i0 = Math.floor(f), w = f - i0, A = path[i0], B = path[Math.min(ns, i0 + 1)], idx = (n * DUST + j) * 3;
      dP[idx] = lerp(A.x, B.x, w) + d.o.x; dP[idx + 1] = lerp(A.y, B.y, w) + d.o.y; dP[idx + 2] = lerp(A.z, B.z, w) + d.o.z;
      dA[n * DUST + j] = onLeg ? (0.08 + 0.16 * s) * Math.sin(Math.min(1, s * 4) * 1.57) : 0.12 + 0.18 * (1 - s); }));
    dustGeo.attributes.position.needsUpdate = true; dustGeo.attributes.aA.needsUpdate = true;
    const pf = poleGeo.attributes.aF; let fTop = 0, fBot = 0;
    for (let i = 0; i < PULSE_SLOTS; i++) {
      const p = pulses[i]; if (!p) { hA[i] = 0; continue; }
      const age = t - p.t0;
      if (age < p.dur) { const u = age / p.dur, m = p.from.clone().lerp(p.to, 0.5); m.y += (p.to.y - p.from.y) * 0.3;
        const v = bez(p.from, m, p.to, u); hP.set([v.x, v.y, v.z], i * 3); hA[i] = Math.sin(Math.min(1, u * 4) * 1.57); }
      else hA[i] = 0;
      if (age >= 2.1 && age < 2.7) { const f = 1 - (age - 2.1) / 0.6; if (p.dir > 0) fTop = Math.max(fTop, f); else fBot = Math.max(fBot, f); }
    }
    pulses = pulses.filter(p => t - p.t0 < 4.2);
    headGeo.attributes.position.needsUpdate = true; headGeo.attributes.aA.needsUpdate = true;
    pf.array[0] = fTop; pf.array[1] = fBot; pf.needsUpdate = true;
  }

  function dispose() { disposables.forEach(d => d.dispose && d.dispose()); }
  function focus(reg) { uni.uFoc.value = reg == null ? -1 : reg; uni.uFocArm.value = reg == null || reg < 0 || !arms[reg] ? -1 : reg; }
  function mark(hov, sel) { uni.uHov.value = hov == null ? -1 : hov; uni.uSel.value = sel == null ? -1 : sel; }
  return { group: g, update, pulse, dispose, arms, sats, focus, mark };
}
