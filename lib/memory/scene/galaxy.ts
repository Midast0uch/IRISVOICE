// @ts-nocheck -- same style as engine.ts (the validated scene engine); three.js only, no React.
// W4 of the memory cortex plan (docs/Design/Memory-Cortex/LIVE-CONTEXT-AND-GALAXY-PLAN.md §4, §8.7-8.9):
// the cortex as ONE organism - a spiral galaxy (an arm per root sector) that fills the volume, satellite galaxies
// for the side sectors fed by tidal streams, curved hyphae that FOLLOW THE ARM and light up when a recall uses
// them, and a shell WOVEN FROM THE ARMS: each arm runs past the rim, splits into strands that spiral to a top
// and a bottom pole. A recall pulse runs claim -> arm -> strand -> pole -> the whole weave.
//
// Rules carried from the interface (MEMORY-INTERFACE §2, §11): every visual is a real value (claims, edges and
// their traversals, sector sizes, recall events); the map never moves while it is read - the structure does
// not rotate, life is in the shaders (twinkle, stars drifting along the arms, dust flowing to the poles);
// nothing builds brightness; motion in shaders, the CPU sets uniforms and a few hundred dust points.
import * as THREE from 'three';

const V3 = THREE.Vector3;
const TAU = Math.PI * 2;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;

function rngOf(seed) { let s = seed >>> 0 || 1; return () => { s = (s * 16807) % 2147483647; return s / 2147483647; }; }
function hashKey(k) { let h = 7; for (const c of String(k)) h = (h * 31 + c.charCodeAt(0)) | 0; return h >>> 0; }

export const GALAXY_MAX_ARMS = 5;
export const GALAXY_TILT = 0.5;   // radians the disc leans toward the default camera
export const GALAXY_MAX_SATS = 4;
/** §9.2: the seven coordinate spaces round every sector, in ONE fixed order and angle everywhere. */
export const HALO_SPACES = ['domain', 'context', 'toolpath', 'conduct', 'style', 'chrono', 'capability'];
const TIGHT = 4.2;           // radians the arm winds from centre to rim
const PULSE_SLOTS = 8;
const LINKS_PER_CLAIM = 6;
const MAX_LINKS = 600;

/**
 * Where everything sits. Pure: reads the territories (largest first, as the engine orders them) and the claims;
 * returns arms, satellites and one position per claim (written into the engine's somaPos, so hover, click, cards
 * and the dive keep working on the new layout).
 *  regs:   [{key, size, col}]        size = the territory's moments (domCounts)
 *  claims: [{reg, born, sync}]       reg = index into regs; born = epoch seconds (older sits further out)
 */
export function layoutGalaxy({ R, regs, claims, seed = 7 }) {
  const rng = rngOf(seed);
  const gauss = () => (rng() + rng() + rng() + rng()) / 2 - 1;
  const GR = R * 0.62;
  const nArms = Math.min(GALAXY_MAX_ARMS, regs.length);
  // arm angles: evenly spaced in KEY order, so an arm keeps its place when sizes change (the compass, §8.4)
  const armRegs = regs.slice(0, nArms).map((r, i) => ({ ...r, reg: i }));
  const byKey = [...armRegs].sort((a, b) => (a.key < b.key ? -1 : 1));
  const arms = armRegs.map(a => {
    const k = byKey.findIndex(b => b.key === a.key);
    const maxSize = Math.max(1, ...armRegs.map(x => x.size || 0));
    return { key: a.key, reg: a.reg, col: new THREE.Color(a.col), ang: k / nArms * TAU + (hashKey('arms') % 100) / 100,
      size: clamp(Math.sqrt((a.size || 0) / maxSize), 0.25, 1), lift: (k % 2 ? -1 : 1) };
  });
  const sats = regs.slice(nArms, nArms + GALAXY_MAX_SATS).map((r, j) => {
    const a = hashKey(r.key) % 628 / 100, y = (j % 2 ? -1 : 1) * R * 0.3;
    return { key: r.key, reg: nArms + j, col: new THREE.Color(r.col), pos: new V3(Math.cos(a) * R * 0.5, y, Math.sin(a) * R * 0.5),
      tiltX: (hashKey(r.key + 'x') % 100) / 100 * 1.6 - 0.8, tiltZ: (hashKey(r.key + 'z') % 100) / 100 * 1.6 - 0.8, rad: R * 0.11 };
  });
  const armOfReg = new Map(arms.map((a, i) => [a.reg, i]));
  const satOfReg = new Map(sats.map((s, i) => [s.reg, i]));
  // claims: along their arm, the newest near the centre, the oldest out at the rim (time runs outward)
  const pos = new Array(claims.length), place = new Array(claims.length);
  const groups = new Map();
  claims.forEach((c, i) => { const g = groups.get(c.reg) || []; g.push(i); groups.set(c.reg, g); });
  for (const [reg, idx] of groups) {
    idx.sort((a, b) => (claims[b].born || 0) - (claims[a].born || 0));     // newest first
    const ai = armOfReg.get(reg), si = satOfReg.get(reg);
    idx.forEach((ci, k) => {
      const t = idx.length > 1 ? k / (idx.length - 1) : 0.5;
      if (ai != null) {
        // spread through the arm's width and thickness (a line of 300 glyphs saturates under the bloom - measured)
        const a = arms[ai], r = clamp(0.22 + 0.72 * t + gauss() * 0.05, 0.15, 0.98), th = a.ang + r * TIGHT + gauss() * 0.28 * (1 - r * 0.3);
        const y = a.lift * R * 0.12 * r * r + gauss() * R * (0.03 + 0.1 * r);
        pos[ci] = new V3(Math.cos(th) * r * GR, y, Math.sin(th) * r * GR);
        place[ci] = { arm: ai, r, th, y };
      } else if (si != null) {
        const s = sats[si], r = 0.2 + 0.8 * t, th = r * 3.4 + k * 2.4;
        pos[ci] = satPoint(s, r, th, 0);
        place[ci] = { sat: si, r, th };
      } else {   // beyond the drawn arms and satellites: the outer halo, still a place of its own
        const a = rng() * TAU, rr = R * (0.7 + 0.15 * rng());
        pos[ci] = new V3(Math.cos(a) * rr, gauss() * R * 0.2, Math.sin(a) * rr);
        place[ci] = { halo: true };
      }
    });
  }
  // the disc leans toward the viewer (edge-on, the arms overlap); the engine's somaPos gets the tilted positions
  const tilt = new THREE.Quaternion().setFromAxisAngle(new V3(1, 0, 0), GALAXY_TILT);
  // §9.2 a sector's halo: beside its arm (lifted to the arm's side of the disc, clear of the star clutter) or above its
  // satellite; reg -1 = the nucleus side (nodes no live claim touches: about the work, not a topic - §9.1 rule 4)
  const HALO_R = R * 0.075;
  const haloLocal = reg => {
    const ai = armOfReg.get(reg);
    if (ai != null) { const a = arms[ai], r = 0.62, th = a.ang + r * TIGHT;
      return new V3(Math.cos(th) * r * GR, a.lift * R * (0.12 * r * r + 0.17), Math.sin(th) * r * GR); }
    const si = satOfReg.get(reg);
    if (si != null) { const sa = sats[si]; return sa.pos.clone().add(new V3(0, (Math.sign(sa.pos.y) || 1) * sa.rad * 1.5, 0)); }
    return new V3(0, R * 0.16, 0);
  };
  const orbitLocal = (reg, space) => { const i = Math.max(0, HALO_SPACES.indexOf(space)), a = i / HALO_SPACES.length * TAU;
    return haloLocal(reg).add(new V3(Math.cos(a) * HALO_R, 0, Math.sin(a) * HALO_R)); };
  const hasHalo = reg => reg === -1 || armOfReg.has(reg) || satOfReg.has(reg);
  // §10 a pin: still, at the INNER edge of its sector's arm (a fixed star the arm slides past); j spreads several
  const pinLocal = (reg, j) => {
    // every pin its own place (measured: j % 6 stacked 58 pins on 6 spots beside the core - one white ball under the
    // additive blend); golden spacing along the inner edge, from near the bulge out to mid-arm
    const ai = armOfReg.get(reg), jj = j % 6, fr = (j * 0.6180339) % 1, fz = (j * 0.7548777) % 1;
    if (ai != null) { const a = arms[ai], r = 0.2 + 0.45 * fr, th = a.ang + r * TIGHT - 0.32 - 0.12 * fz;
      return new V3(Math.cos(th) * r * GR, a.lift * R * 0.12 * r * r + R * 0.05 * (fz - 0.5), Math.sin(th) * r * GR); }
    const si = satOfReg.get(reg);
    if (si != null) { const sa = sats[si]; return satPoint(sa, 0.25 + 0.1 * jj, jj * 1.05, sa.rad * 0.1); }
    const a = j * 2.399963, r = R * (0.06 + 0.012 * jj);   // the nucleus side of `general`
    return new V3(Math.cos(a) * r, -R * 0.1, Math.sin(a) * r);
  };
  const world = v => v.applyQuaternion(tilt);
  return { GR, arms, sats, pos, place, tilt, posWorld: pos.map(p => (p ? p.clone().applyQuaternion(tilt) : p)),
    HALO_R, hasHalo, haloCentre: reg => world(haloLocal(reg)), haloOrbit: (reg, space) => world(orbitLocal(reg, space)),
    haloOrbitLocal: orbitLocal, pinAt: (reg, j) => world(pinLocal(reg, j)),
    // the sector dial: where a sector's name sits - past the arm's outer end, or above its satellite
    labelAt: reg => { const ai = armOfReg.get(reg);
      const DR = GR * 1.5;   // on the dial ring (galaxy.ts createGalaxy DIAL_R)
      if (ai != null) { const th = arms[ai].ang + TIGHT + 0.12; return world(new V3(Math.cos(th) * DR, 0, Math.sin(th) * DR)); }
      const si = satOfReg.get(reg); if (si != null) { const sa = sats[si], th = Math.atan2(sa.pos.z, sa.pos.x); return world(new V3(Math.cos(th) * DR, 0, Math.sin(th) * DR)); }
      return null; } };
}

function satPoint(s, r, th, h) {
  const lx = Math.cos(th) * r * s.rad, lz = Math.sin(th) * r * s.rad, ly = h;
  const c1 = Math.cos(s.tiltX), s1 = Math.sin(s.tiltX), y1 = ly * c1 - lz * s1, z1 = ly * s1 + lz * c1;
  const c2 = Math.cos(s.tiltZ), s2 = Math.sin(s.tiltZ), x2 = lx * c2 - y1 * s2, y2 = lx * s2 + y1 * c2;
  return new V3(s.pos.x + x2, s.pos.y + y2, s.pos.z + z1);
}

const FOCUS_GLSL = `float focusDim(float reg,float foc){return foc<-.5?1.:(abs(reg-foc)<.5?1.2:(reg<-.5?.55:.22));}`;
const STAR_VS = `uniform float uTime,uPix,uVis,uFoc;attribute float aA,aPh,aSz,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;
  ${FOCUS_GLSL}
  void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float tw=.78+.22*sin(uTime*(.6+aPh*.9)+aPh*40.);
    vC=aC;vA=aA*tw*uVis*smoothstep(.4,3.,-mv.z)*focusDim(aReg,uFoc);gl_PointSize=min(aSz*uPix*(60./-mv.z),6.*uPix);gl_Position=projectionMatrix*mv;}`;
const STAR_FS = `varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
  gl_FragColor=vec4(vC,(smoothstep(.5,.0,d)*.55+smoothstep(.18,.0,d)*.6)*vA);}`;

/**
 * The scene objects. `links`: [{a, b, w}] claim-index pairs with a use weight 0..1 (traversals, log-scaled).
 * `cloudW`: per arm, the share of moments (the inner star cloud's tint). Returns {group, update, pulse, dispose}.
 */
export function createGalaxy({ R, U, layout, links, halos = [], claimNodes = [], pins = [], claimInfo = [], seed = 11 }) {
  const rng = rngOf(seed);
  const gauss = () => (rng() + rng() + rng() + rng()) / 2 - 1;
  const { GR, arms, sats, pos, place } = layout;
  const g = new THREE.Group();
  if (layout.tilt) g.quaternion.copy(layout.tilt);
  const uni = { ...U, uVis: { value: 1 }, uIn: { value: 0 }, uHalo: { value: -9 }, uFoc: { value: -1 }, uFocArm: { value: -1 }, uHov: { value: -1 }, uSel: { value: -1 } };
  const HH = R * 0.72;
  const disposables = [];
  const addPoints = (P, C, A, PH, SZ, RG = null) => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('aReg', new THREE.Float32BufferAttribute(RG || new Array(P.length / 3).fill(-1), 1));
    geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
    geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3));
    geo.setAttribute('aA', new THREE.Float32BufferAttribute(A, 1));
    geo.setAttribute('aPh', new THREE.Float32BufferAttribute(PH, 1));
    geo.setAttribute('aSz', new THREE.Float32BufferAttribute(SZ, 1));
    const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: STAR_VS, fragmentShader: STAR_FS,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(geo, mat); o.frustumCulled = false; g.add(o); disposables.push(geo, mat); return o;
  };
  const armPoint = (a, r, dth, h) => { const th = a.ang + r * TIGHT + dth; return new V3(Math.cos(th) * r * GR, h, Math.sin(th) * r * GR); };

  // ── the disc: arm stars (count by sector size), the bulge, the inner cloud up to the poles ───────────────
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [];
    const total = 11000, wsum = arms.reduce((s, a) => s + a.size, 0) || 1;
    arms.forEach(a => {
      const n = Math.round(total * a.size / wsum);
      for (let i = 0; i < n; i++) {
        const r = Math.pow(rng(), 0.7), dth = gauss() * 0.3 * (1 - r * 0.3);
        const h = a.lift * R * 0.12 * r * r + gauss() * R * (0.02 + 0.09 * Math.pow(r, 1.4));
        const p = armPoint(a, r, dth, h); P.push(p.x, p.y, p.z);
        const c = a.col.clone().lerp(new THREE.Color('#ffffff'), 0.25 * (1 - r)); C.push(c.r, c.g, c.b);
        A.push(0.06 + 0.15 * (1 - r)); PH.push(rng()); SZ.push(1.0 + rng() * 0.8); RG.push(a.reg);   // tuned to the engine's bloom
      }
    });
    for (let i = 0; i < 1600; i++) {   // the bulge: warm, round, at the centre (the live context's home)
      const rr = Math.pow(rng(), 0.6) * R * 0.13, u = rng() * 2 - 1, ph = rng() * TAU, q = Math.sqrt(1 - u * u);
      P.push(Math.cos(ph) * q * rr, u * rr * 0.85, Math.sin(ph) * q * rr); C.push(1, 0.94, 0.85);
      A.push(0.03); PH.push(rng()); SZ.push(1.0); RG.push(-1);
    }
    for (let i = 0; i < 9000; i++) {   // the inner cloud: fills the woven shell up to the poles, tinted by the nearest arm
      const y = (rng() * 2 - 1) * HH * 0.92, rm = GR * 1.08 * Math.pow(Math.max(0, 1 - Math.pow(Math.abs(y) / HH, 2)), 0.6) * 0.9;
      const rho = rm * Math.pow(rng(), 0.55), th = rng() * TAU;
      let best = 0, bd = 9; arms.forEach((a, k) => { const d = Math.abs(Math.atan2(Math.sin(th - (a.ang + Math.min(1, rho / GR) * TIGHT)), Math.cos(th - (a.ang + Math.min(1, rho / GR) * TIGHT)))); if (d < bd) { bd = d; best = k; } });
      const c = (arms[best] ? arms[best].col : new THREE.Color('#9fd6ee')); P.push(Math.cos(th) * rho, y, Math.sin(th) * rho); C.push(c.r, c.g, c.b);
      A.push(0.012 + 0.03 * rng()); PH.push(rng()); SZ.push(0.8); RG.push(arms[best] ? arms[best].reg : -1);
    }
    addPoints(P, C, A, PH, SZ, RG);
  }

  // ── the claims ARE stars of the galaxy (owner, 2026-11-23: the old crystal glyphs did not read as part of it): a
  // core in the sector's tint; a ring = proven (solid) or still learning (dashed); brightness = sync (how strongly it
  // is proven). They grow as you go inside (uIn); hover and focus ring them white. Picking reads the same positions.
  const CLAIM_VS = `uniform float uTime,uPix,uVis,uIn,uFoc,uHov,uSel;attribute float aIdx,aProven,aSync,aReg,aPh;attribute vec3 aC;
    varying vec3 vC;varying float vA,vP,vH,vS;
    ${FOCUS_GLSL}
    void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float h=step(abs(aIdx-uHov),.5),sel=step(abs(aIdx-uSel),.5);
      vC=aC;vP=aProven;vH=h;vS=sel;float tw=.85+.15*sin(uTime*(.4+aPh)+aPh*30.);
      vA=(.3+.55*aSync)*tw*uVis*focusDim(aReg,uFoc)*(1.+.6*max(h,sel));
      float sz=(1.6+1.6*aSync)*(1.+2.2*uIn)*(1.+.7*max(h,sel));
      gl_PointSize=clamp(sz*uPix*(60./-mv.z),2.*uPix,(9.+10.*uIn+8.*max(h,sel))*uPix);gl_Position=projectionMatrix*mv;}`;
  const CLAIM_FS = `varying vec3 vC;varying float vA,vP,vH,vS;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    float core=smoothstep(.17,.0,d),glow=smoothstep(.5,.0,d)*.28,ang=atan(c.y,c.x);
    float ring=smoothstep(.045,.0,abs(d-.36))*mix(step(0.,sin(ang*10.))*.55,1.,vP);
    float hi=max(vH,vS);vec3 col=mix(vC,vec3(1.),.35+.4*hi);
    gl_FragColor=vec4(col,(core*.95+glow+ring*(.45+.55*hi))*vA);}`;
  {
    const P = [], C = [], IX = [], PR = [], SY = [], RG = [], PH = [];
    const dP = [], dC = [], dA = [], dPH = [], dSZ = [], dRG = [];
    pos.forEach((p, k) => { if (!p) return; const pl = place[k] || {}, info = claimInfo[k] || {};
      const reg = pl.arm != null ? arms[pl.arm].reg : pl.sat != null ? sats[pl.sat].reg : -1;
      const col = pl.arm != null ? arms[pl.arm].col.clone().lerp(new THREE.Color('#ffffff'), 0.45) : pl.sat != null ? sats[pl.sat].col.clone().lerp(new THREE.Color('#ffffff'), 0.4) : new THREE.Color('#cfe9f5');
      P.push(p.x, p.y, p.z); C.push(col.r, col.g, col.b); IX.push(k); PR.push(info.proven ? 1 : 0); SY.push(clamp(info.sync ?? 0.4, 0, 1)); RG.push(reg); PH.push(rng());
      for (let j = 0; j < 2; j++) { dP.push(p.x + gauss() * R * 0.007, p.y + gauss() * R * 0.007, p.z + gauss() * R * 0.007); dC.push(col.r, col.g, col.b);
        dA.push(0.06); dPH.push(rng()); dSZ.push(1.1); dRG.push(reg); } });
    if (dP.length) addPoints(dP, dC, dA, dPH, dSZ, dRG);   // a little dust round each claim
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

  // ── satellites: tilted 3D galaxies, and the tidal stream into their nearest arm ───────────────────────────
  const streams = [];
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [];
    sats.forEach(s => {
      for (let i = 0; i < 700; i++) {
        const r = Math.pow(rng(), 0.65), th = Math.floor(rng() * 2) * Math.PI + r * 3.4 + gauss() * 0.45;
        const p = satPoint(s, r, th, gauss() * R * 0.02 * (1.4 - r)); P.push(p.x, p.y, p.z);
        C.push(s.col.r, s.col.g, s.col.b); A.push(0.05 + 0.12 * (1 - r)); PH.push(rng()); SZ.push(0.9); RG.push(s.reg);
      }
      // stream: toward the arm whose rim point is nearest
      let best = 0, bd = 1e9; arms.forEach((a, k) => { const q = armPoint(a, 0.85, 0, 0); const d = q.distanceTo(s.pos); if (d < bd) { bd = d; best = k; } });
      if (arms[best]) streams.push({ reg: s.reg, from: s.pos.clone(), to: armPoint(arms[best], 0.85, 0, 0), col: s.col, parts: Array.from({ length: 140 }, () => ({ u: rng(), o: new V3(gauss(), gauss(), gauss()).multiplyScalar(R * 0.015) })) });
    });
    if (P.length) addPoints(P, C, A, PH, SZ, RG);
  }
  const streamGeo = new THREE.BufferGeometry(), sCount = streams.reduce((n, s) => n + s.parts.length, 0);
  const sP = new Float32Array(Math.max(1, sCount) * 3), sC = new Float32Array(Math.max(1, sCount) * 3), sA = new Float32Array(Math.max(1, sCount));
  {
    let k = 0; streams.forEach(s => s.parts.forEach(() => { sC.set([s.col.r, s.col.g, s.col.b], k * 3); k++; }));
    streamGeo.setAttribute('position', new THREE.BufferAttribute(sP, 3)); streamGeo.setAttribute('aC', new THREE.BufferAttribute(sC, 3));
    streamGeo.setAttribute('aA', new THREE.BufferAttribute(sA, 1));
    streamGeo.setAttribute('aPh', new THREE.Float32BufferAttribute(new Array(Math.max(1, sCount)).fill(0).map(() => rng()), 1));
    streamGeo.setAttribute('aSz', new THREE.Float32BufferAttribute(new Array(Math.max(1, sCount)).fill(1.2), 1));
    streamGeo.setAttribute('aReg', new THREE.Float32BufferAttribute(streams.flatMap(st => st.parts.map(() => st.reg)), 1));
    const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: STAR_VS, fragmentShader: STAR_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(streamGeo, mat); o.frustumCulled = false; g.add(o); disposables.push(streamGeo, mat);
  }

  // ── hyphae: claim links. Same arm -> along the arm's own curve; across arms -> a curve that bows inward.
  // Lit by use: a base glow from the link's weight (traversals), and pulses when a recall walks it. ─────────
  const HYPHA_VS = `uniform float uTime,uVis,uIn;uniform vec2 uPulse[${PULSE_SLOTS}];attribute float aLink,aU,aW;varying float vA;
    void main(){float lit=0.;for(int i=0;i<${PULSE_SLOTS};i++){vec2 p=uPulse[i];if(p.x==aLink){float age=uTime-p.y;float head=age/1.1;
      lit=max(lit,smoothstep(.09,0.,abs(aU-head))*step(0.,age)*step(age,1.6)+.6*smoothstep(1.,0.,age)*step(0.,age));}}
      vA=(step(.001,aW)*(.003+.014*aW)*(.25+.75*sin(aU*3.14159))*(1.-.8*uIn)+lit*.7)*uVis;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`;
  const HYPHA_FS = `varying float vA;void main(){gl_FragColor=vec4(.78,.95,.9,vA);}`;
  const linkOf = new Map();   // claim -> link ids (a pulse lights the claim's links)
  {
    const P = [], L = [], UU = [], WW = [];
    // lit by USE: only the most-used links are drawn (measured: ~3,000 additive links in a thin disc saturate under the
    // bloom), and a never-used link has no glow at rest - a recall pulse lights it
    // at most LINKS_PER_CLAIM per claim, the most used first (measured: hub claims hold 70-80 links; their ends
    // stacked into white knots). A hub reads as a knot with a few cords; the rest light when a recall walks them.
    const deg = new Map(), kept = [];
    for (const it of links.map((ln, id) => ({ ln, id })).sort((x, y) => (y.ln.w || 0) - (x.ln.w || 0))) {
      if (kept.length >= MAX_LINKS) break;
      const da = deg.get(it.ln.a) || 0, db = deg.get(it.ln.b) || 0; if (da >= LINKS_PER_CLAIM || db >= LINKS_PER_CLAIM) continue;
      deg.set(it.ln.a, da + 1); deg.set(it.ln.b, db + 1); kept.push(it);
    }
    kept.forEach(({ ln, id }) => {
      const pa = place[ln.a], pb = place[ln.b]; if (!pa || !pb || !pos[ln.a] || !pos[ln.b]) return;
      const pts = [];
      if (pa.arm != null && pa.arm === pb.arm) {
        const a = arms[pa.arm];
        for (let k = 0; k <= 14; k++) { const u = k / 14, r = lerp(pa.r, pb.r, u), th = lerp(pa.th, pb.th, u), y = lerp(pa.y, pb.y, u);
          // each link its own lane in the arm's width (measured: 600 links on one arm curve stacked into one white
          // cord under the additive blend); the lane tapers to the claims at both ends
          const wob = Math.sin(u * 9 + id) * R * 0.008 * Math.sin(u * Math.PI), env = Math.sin(u * Math.PI);
          const lane = ((id * 0.6180339) % 1 - 0.5) * 0.22 * env, lift = ((id * 0.7548777) % 1 - 0.5) * R * 0.05 * env;
          pts.push(new V3(Math.cos(th + lane) * r * GR + wob, y + lift + wob, Math.sin(th + lane) * r * GR - wob)); }
      } else {
        // across arms: an arch over or under the disc through the star cloud (measured: bowing toward the centre,
        // (A+B)*0.3, sent every cross link through the bulge - one white knot); each link its own height and side
        const A0 = pos[ln.a], B0 = pos[ln.b], side = id % 2 ? 1 : -1, hgt = R * (0.1 + 0.18 * ((id * 0.6180339) % 1));
        const m = A0.clone().add(B0).multiplyScalar(0.5); m.multiplyScalar(1.15).add(new V3(0, side * hgt, 0));
        for (let k = 0; k <= 14; k++) { const u = k / 14, q = 1 - u; pts.push(new V3(q * q * A0.x + 2 * q * u * m.x + u * u * B0.x, q * q * A0.y + 2 * q * u * m.y + u * u * B0.y, q * q * A0.z + 2 * q * u * m.z + u * u * B0.z)); }
      }
      for (let k = 0; k < pts.length - 1; k++) {
        P.push(pts[k].x, pts[k].y, pts[k].z, pts[k + 1].x, pts[k + 1].y, pts[k + 1].z);
        L.push(id, id); UU.push(k / (pts.length - 1), (k + 1) / (pts.length - 1)); WW.push(ln.w, ln.w);
      }
      // two short spurs (the branching of a living thread)
      [0.35, 0.7].forEach((u0, j) => { const k = Math.floor(u0 * (pts.length - 1)), p = pts[k], q = pts[Math.min(pts.length - 1, k + 1)];
        const d = q.clone().sub(p).normalize(), side = new V3(0, 1, 0).cross(d).normalize().multiplyScalar((j ? -1 : 1) * R * 0.025);
        const e = p.clone().add(side).addScaledVector(d, R * 0.012); P.push(p.x, p.y, p.z, e.x, e.y, e.z); L.push(id, id); UU.push(u0, u0); WW.push(ln.w * 0.6, ln.w * 0.6); });
      [ln.a, ln.b].forEach(c => { const l = linkOf.get(c) || []; l.push(id); linkOf.set(c, l); });
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aLink', new THREE.Float32BufferAttribute(L, 1));
    geo.setAttribute('aU', new THREE.Float32BufferAttribute(UU, 1)); geo.setAttribute('aW', new THREE.Float32BufferAttribute(WW, 1));
    uni.uPulse = { value: Array.from({ length: PULSE_SLOTS }, () => new THREE.Vector2(-1, -99)) };
    const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: HYPHA_VS, fragmentShader: HYPHA_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.LineSegments(geo, mat); o.frustumCulled = false; g.add(o); disposables.push(geo, mat);
  }

  // ── the woven shell: every arm runs past the rim and splits into strands to the two poles ─────────────────
  const DIAL_R = GR * 1.5;   // the sector dial ring sits just outside the shell, at the equator
  const shellR = (h, size) => GR * (1.2 + 0.1 * size) * Math.pow(Math.max(0, 1 - Math.pow(h / HH, 2)), 0.85) + R * 0.02;   // a lemon: pointed poles
  const NS = 40, strands = [];
  arms.forEach((a, ai) => { for (let f = -1; f <= 1; f++) for (const dir of [1, -1]) strands.push({ ai, f, dir }); });
  const strandPt = (sd, s) => {
    const a = arms[sd.ai], rimTh = a.ang + TIGHT + sd.f * 0.2, th = rimTh + sd.dir * 1.1 * s + sd.f * 0.15 * s;
    const y0 = a.lift * R * 0.12, h = y0 * (1 - s) + sd.dir * HH * Math.pow(Math.sin(s * Math.PI / 2), 1.15);
    let rho = shellR(h, a.size);
    sats.forEach(sa => { if (Math.sign(sa.pos.y) !== sd.dir) return; const sAng = Math.atan2(sa.pos.z, sa.pos.x);
      rho += R * 0.06 * Math.exp(-Math.pow(Math.atan2(Math.sin(th - sAng), Math.cos(th - sAng)), 2) / 0.12) * Math.sin(s * Math.PI); });
    return new V3(Math.cos(th) * rho, h, Math.sin(th) * rho);
  };
  const SAMPLES = strands.map(sd => Array.from({ length: NS + 1 }, (_, j) => strandPt(sd, j / NS)));
  // the arm leg (owner, 2026-11-22: the shell must be the same threads as the hyphae): three filaments leave the
  // bulge together, run along the arm, fan out and, at the rim, ARE the strands. armLeg(sd, 1) === strandPt(sd, 0).
  const ARM_NS = 28;
  const armLeg = (sd, u) => { const a = arms[sd.ai], rr = lerp(0.16, 1, u);
    const th = a.ang + rr * TIGHT + sd.f * 0.2 * Math.pow(u, 1.6), rho = lerp(0.16 * GR, shellR(a.lift * R * 0.12, a.size), Math.pow(u, 1.3));
    return new V3(Math.cos(th) * rho, a.lift * R * 0.12 * rr * rr, Math.sin(th) * rho); };
  // the arm's middle filament at radius r (fraction of GR): where claims, halos and pins attach
  const fil = (ai, r) => { const a = arms[ai], rr = clamp(r, 0.16, 1), th = a.ang + rr * TIGHT;
    return new V3(Math.cos(th) * rr * GR, a.lift * R * 0.12 * rr * rr, Math.sin(th) * rr * GR); };
  // the strands as STAR STREAMS (owner, 2026-11-23: 1-px lines read as wires; the agreed mockup is soft threads of
  // stars with dust flowing to the poles): stars along each strand and its arm leg, a little spread, thinning toward
  // the poles; the cross-hyphae are short star bridges. A recall lights them as before (uSP).
  const STRAND_VS = `uniform float uTime,uPix,uVis,uIn,uFocArm;uniform vec3 uSP[4];attribute float aS,aArm,aDir,aPh,aSz;attribute vec3 aC;varying vec3 vC;varying float vA;
    void main(){float lit=0.;for(int i=0;i<4;i++){vec3 p=uSP[i];float age=uTime-p.z;if(age<0.||age>4.)continue;
      if(age<.9&&p.x==aArm&&aS<0.){float s=age/.9-1.;lit=max(lit,exp(-pow(aS-s,2.)/.004));}
      if(age>=.9&&age<2.1&&p.x==aArm&&p.y==aDir){float s=(age-.9)/1.2;lit=max(lit,exp(-pow(aS-s,2.)/.004));}
      if(age>=2.1&&p.y==aDir){float e=age-2.1;float back=max(0.,1.-e/1.6);lit=max(lit,.55*back*exp(-pow((1.-aS)-e*.8,2.)/.006));}}
      vec4 mv=modelViewMatrix*vec4(position,1.);float tw=.7+.3*sin(uTime*(.5+aPh*.8)+aPh*40.);
      float base=(aS<0.?.07+.16*pow(1.+aS,1.5):.3*(1.-.5*aS))*(uFocArm<-.5?1.:(abs(aArm-uFocArm)<.5?1.3:.3));
      vC=mix(aC,vec3(.96,1.,.98),clamp(lit,0.,1.));vA=(base*tw*(1.-.85*uIn)+.9*lit)*uVis*smoothstep(.4,3.,-mv.z);
      gl_PointSize=clamp((aSz+1.4*lit)*uPix*(60./-mv.z),1.4*uPix,(4.+3.*lit)*uPix);gl_Position=projectionMatrix*mv;}`;
  const STRAND_FS = `varying vec3 vC;varying float vA;void main(){gl_FragColor=vec4(vC,vA);}`;   // (the threads use it too)
  const STREAM_FS = `varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    gl_FragColor=vec4(vC,(smoothstep(.5,.0,d)*.55+smoothstep(.18,.0,d)*.6)*vA);}`;
  uni.uSP = { value: Array.from({ length: 4 }, () => new V3(-1, 0, -99)) };
  {
    const P = [], S = [], AR = [], DR = [], C = [], PH = [], SZ = [];
    const push = (p, sv, ai, dir, col, sz, spread) => { P.push(p.x + gauss() * spread, p.y + gauss() * spread, p.z + gauss() * spread);
      S.push(sv); AR.push(ai); DR.push(dir); C.push(col.r, col.g, col.b); PH.push(rng()); SZ.push(sz); };
    const at = (arr, ns, sv) => { const f = sv * ns, i0 = Math.min(ns - 1, Math.floor(f)); return arr[i0].clone().lerp(arr[i0 + 1], f - i0); };
    strands.forEach((sd, n) => {
      const col = arms[sd.ai].col.clone().lerp(new THREE.Color('#ffffff'), 0.15), main = sd.f === 0;
      // the strand: denser near the rim, thinning to the pole; an arm's middle strand is its brighter cord
      const cnt = main ? 230 : 150;
      for (let i = 0; i < cnt; i++) { const sv = Math.pow(rng(), 1.25); push(at(SAMPLES[n], NS, sv), sv, sd.ai, sd.dir, col, main ? 1.25 : 1.0, R * (0.004 + 0.006 * (1 - sv))); }
      // its arm leg (shared by both sides): the arm's own stars that become the strand
      if (sd.dir > 0) for (let i = 0; i < 80; i++) { const u = Math.pow(rng(), 0.7); push(armLeg(sd, u), u - 1, sd.ai, 0, col, 1.0, R * 0.006); }
    });
    // the weave: star bridges between neighbouring strands of the same side at three heights
    const bridge = new THREE.Color(0.66, 0.85, 0.92);
    strands.forEach((sd, n) => {
      let nb = -1, bd = 9; strands.forEach((o, m) => { if (o.dir !== sd.dir || m === n) return;
        const da = ((arms[o.ai].ang + o.f * 0.2) - (arms[sd.ai].ang + sd.f * 0.2) + TAU) % TAU; if (da > 0.01 && da < bd) { bd = da; nb = m; } });
      if (nb < 0) return;
      [0.22, 0.45, 0.68].forEach(s0 => { const a = strandPt(sd, s0), b = strandPt(strands[nb], s0);
        for (let k = 0; k < 16; k++) { const u = (k + rng()) / 16, sag = 0.9 - 0.08 * Math.sin(u * Math.PI), q = a.clone().lerp(b, u); q.x *= sag; q.z *= sag;
          push(q, s0, sd.ai, sd.dir, bridge, 0.9, R * 0.003); } });
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aS', new THREE.Float32BufferAttribute(S, 1));
    geo.setAttribute('aArm', new THREE.Float32BufferAttribute(AR, 1)); geo.setAttribute('aDir', new THREE.Float32BufferAttribute(DR, 1));
    geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3)); geo.setAttribute('aPh', new THREE.Float32BufferAttribute(PH, 1));
    geo.setAttribute('aSz', new THREE.Float32BufferAttribute(SZ, 1));
    const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: STRAND_VS, fragmentShader: STREAM_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(geo, mat); o.frustumCulled = false; o.userData.strands = true; g.add(o); disposables.push(geo, mat);
  }
  // dust flowing up the strands toward the poles (CPU: ~30 per strand, lerped on the precomputed samples)
  const dust = strands.map(() => Array.from({ length: 28 }, () => ({ s: rng(), v: 0.012 + rng() * 0.02, o: new V3(gauss(), gauss(), gauss()).multiplyScalar(R * 0.008) })));
  // the dust starts ON the arm (the outer half of its leg) and climbs into the strand: the weave is the arm's own
  // matter leaving the disc (owner, 2026-11-22: the shell must read as connected to the hyphae)
  const LEG_NS = 12, LEG_SHARE = 0.35;
  const LEG = strands.map(sd => Array.from({ length: LEG_NS + 1 }, (_, j) => armLeg(sd, 0.45 + 0.55 * j / LEG_NS)));
  const dCount = strands.length * 28, dP = new Float32Array(Math.max(1, dCount) * 3), dC = new Float32Array(Math.max(1, dCount) * 3), dA = new Float32Array(Math.max(1, dCount));
  strands.forEach((sd, n) => { const c = arms[sd.ai].col; for (let k = 0; k < 28; k++) dC.set([c.r, c.g, c.b], (n * 28 + k) * 3); });
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dP, 3)); dustGeo.setAttribute('aC', new THREE.BufferAttribute(dC, 3)); dustGeo.setAttribute('aA', new THREE.BufferAttribute(dA, 1));
  dustGeo.setAttribute('aPh', new THREE.Float32BufferAttribute(new Array(Math.max(1, dCount)).fill(0).map(() => rng()), 1));
  dustGeo.setAttribute('aSz', new THREE.Float32BufferAttribute(new Array(Math.max(1, dCount)).fill(1.1), 1));
  { const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: STAR_VS, fragmentShader: STAR_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(dustGeo, mat); o.frustumCulled = false; g.add(o); disposables.push(dustGeo, mat); }
  {
    const prof = [];
    for (let j = 0; j <= 40; j++) { const y = HH * j / 40; prof.push(new THREE.Vector2(Math.max(0.001, shellR(y, 0.6) * 0.99), y)); }
    const full = [...prof.slice(1).reverse().map(v => new THREE.Vector2(v.x, -v.y)), ...prof];
    const geo = new THREE.LatheGeometry(full, 72);
    const angs = arms.map(a => a.ang + TIGHT), cols = arms.map(a => a.col);
    const C = [], pa = geo.attributes.position;
    for (let i = 0; i < pa.count; i++) { const th = Math.atan2(pa.getZ(i), pa.getX(i)); let best = 0, bd = 9;
      angs.forEach((an, k) => { const d = Math.abs(Math.atan2(Math.sin(th - an), Math.cos(th - an))); if (d < bd) { bd = d; best = k; } });
      const c = (cols[best] || new THREE.Color('#9fd6ee')).clone().lerp(new THREE.Color('#bfe9f5'), 0.35); C.push(c.r, c.g, c.b); }
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
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [];
    for (let i = 0; i < 520; i++) { const th = i / 520 * TAU; P.push(Math.cos(th) * DIAL_R, 0, Math.sin(th) * DIAL_R);
      C.push(0.7, 0.86, 0.95); A.push(0.05); PH.push(rng()); SZ.push(0.9); RG.push(-1); }
    const tick = (th, col, reg) => { for (let i = -6; i <= 6; i++) { const t2 = th + i * 0.006;
      P.push(Math.cos(t2) * DIAL_R, 0, Math.sin(t2) * DIAL_R); C.push(col.r, col.g, col.b); A.push(0.5 - Math.abs(i) * 0.03); PH.push(rng()); SZ.push(1.8); RG.push(reg); } };
    arms.forEach(a => tick(a.ang + TIGHT + 0.12, a.col, a.reg));
    sats.forEach(sa => tick(Math.atan2(sa.pos.z, sa.pos.x), sa.col, sa.reg));
    addPoints(P, C, A, PH, SZ, RG);
  }
  // the poles: where the strands meet; they flash once when a recall pulse arrives
  const poleGeo = new THREE.BufferGeometry();
  poleGeo.setAttribute('position', new THREE.Float32BufferAttribute([0, HH, 0, 0, -HH, 0], 3));
  poleGeo.setAttribute('aF', new THREE.Float32BufferAttribute([0, 0], 1));
  const poleMat = new THREE.ShaderMaterial({ uniforms: uni,
    vertexShader: `uniform float uPix,uVis;attribute float aF;varying float vF,vA;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vF=aF;vA=uVis;gl_PointSize=min((6.+26.*aF)*uPix*(60./-mv.z),60.*uPix);gl_Position=projectionMatrix*mv;}`,
    fragmentShader: `varying float vF,vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);float core=smoothstep(.2,0.,d);float ring=smoothstep(.5,.44,d)*smoothstep(.36,.42,d)*vF;gl_FragColor=vec4(.92,.99,1.,(core*(.35+.6*vF)+ring*.6)*vA);}`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  { const o = new THREE.Points(poleGeo, poleMat); o.frustumCulled = false; g.add(o); disposables.push(poleGeo, poleMat); }
  // pulse heads: claim -> along its arm to the rim (CPU, at most PULSE_SLOTS)
  const headGeo = new THREE.BufferGeometry(), hP = new Float32Array(PULSE_SLOTS * 3), hA = new Float32Array(PULSE_SLOTS);
  headGeo.setAttribute('position', new THREE.BufferAttribute(hP, 3)); headGeo.setAttribute('aA', new THREE.BufferAttribute(hA, 1));
  headGeo.setAttribute('aC', new THREE.Float32BufferAttribute(new Array(PULSE_SLOTS * 3).fill(1), 3));
  headGeo.setAttribute('aPh', new THREE.Float32BufferAttribute(new Array(PULSE_SLOTS).fill(0), 1));
  headGeo.setAttribute('aSz', new THREE.Float32BufferAttribute(new Array(PULSE_SLOTS).fill(3.2), 1));
  { const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: STAR_VS, fragmentShader: STAR_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const o = new THREE.Points(headGeo, mat); o.frustumCulled = false; g.add(o); disposables.push(headGeo, mat); }

  // ── §9.2 the halos: halos = [{reg, counts: {space: n}}] ───────────────────────────────────────────────────
  const HALO_VS = `uniform float uTime,uPix,uVis,uIn,uHalo;attribute float aA,aSz,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;
    void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float mine=step(abs(aReg-uHalo),.5);
      vC=aC;vA=aA*uVis*mix(1.-.55*uIn,1.+1.2*uIn,mine);gl_PointSize=min(aSz*uPix*(60./-mv.z),(5.+5.*mine*uIn)*uPix);gl_Position=projectionMatrix*mv;}`;
  const RING_VS = `uniform float uVis,uIn,uHalo;attribute float aReg;varying float vA;
    void main(){float mine=step(abs(aReg-uHalo),.5);vA=.05*uVis*mix(1.-.6*uIn,1.+2.*uIn,mine);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`;
  if (halos.length) {
    const P = [], C = [], A = [], SZ = [], RG = [], LP = [], LR = [];
    halos.forEach(h => {
      const tint = h.reg >= 0 ? (arms.find(a => a.reg === h.reg)?.col || sats.find(sa => sa.reg === h.reg)?.col || new THREE.Color(0.8, 0.9, 1)) : new THREE.Color(0.85, 0.9, 0.95);
      HALO_SPACES.forEach((sp, i) => {
        const o = layout.haloOrbitLocal(h.reg, sp), n = (h.counts && h.counts[sp]) || 0;
        P.push(o.x, o.y, o.z); C.push(tint.r, tint.g, tint.b); RG.push(h.reg);
        A.push(n > 0 ? 0.22 + 0.4 * Math.min(1, Math.log10(1 + n) / 2) : 0.05); SZ.push(n > 0 ? 3.2 + Math.min(2.5, Math.log10(1 + n) * 1.6) : 2.2);
        const o2 = layout.haloOrbitLocal(h.reg, HALO_SPACES[(i + 1) % HALO_SPACES.length]);
        LP.push(o.x, o.y, o.z, o2.x, o2.y, o2.z); LR.push(h.reg, h.reg);
      });
    });
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

  // -- the threads (owner, 2026-11-22: nothing floats): every claim hangs on its arm's filament by a spur; its hyphae
  // run to its nodes in the sector's halo (section 9.2); a halo grows from the arm on a stalk; a pin is held to the arm
  // by a straight tether (section 10: held, not grown). A recall of the claim runs a light along its own threads.
  const THREAD_VS = `uniform float uTime,uVis,uIn;uniform vec2 uCP[${PULSE_SLOTS}];attribute float aClaim,aU,aA;attribute vec3 aC;varying vec3 vC;varying float vA;
    void main(){float lit=0.;for(int i=0;i<${PULSE_SLOTS};i++){vec2 p=uCP[i];if(p.x==aClaim){float age=uTime-p.y;
      lit=max(lit,smoothstep(.12,0.,abs(aU-age/.7))*step(0.,age)*step(age,1.)+.5*smoothstep(1.4,0.,age)*step(0.,age));}}
      vC=mix(aC,vec3(.96,1.,.98),clamp(lit,0.,1.));vA=(aA*(1.-.3*uIn)+.75*lit)*uVis;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`;
  uni.uCP = { value: Array.from({ length: PULSE_SLOTS }, () => new THREE.Vector2(-1, -99)) };
  {
    const P = [], CL = [], UU = [], AA = [], C = [];
    const inv = layout.tilt ? layout.tilt.clone().invert() : new THREE.Quaternion();
    const local = v => v.clone().applyQuaternion(inv);
    const curve = (A0, B0, ctl, n, claim, a0, col) => { let prev = A0;
      for (let k = 1; k <= n; k++) { const u = k / n, q = 1 - u;
        const pt = new V3(q * q * A0.x + 2 * q * u * ctl.x + u * u * B0.x, q * q * A0.y + 2 * q * u * ctl.y + u * u * B0.y, q * q * A0.z + 2 * q * u * ctl.z + u * u * B0.z);
        P.push(prev.x, prev.y, prev.z, pt.x, pt.y, pt.z); CL.push(claim, claim); UU.push((k - 1) / n, u);
        const fa = a0 * (0.55 + 0.45 * Math.sin(u * Math.PI)); AA.push(fa, fa); C.push(col.r, col.g, col.b, col.r, col.g, col.b); prev = pt; } };
    // spurs: claim -> its filament (arm) or its satellite's heart
    pos.forEach((p, k) => { if (!p) return; const pl = place[k] || {};
      if (pl.arm != null) { const f = fil(pl.arm, pl.r), ctl = p.clone().lerp(f, 0.5); ctl.y = lerp(p.y, f.y, 0.8);
        curve(p, f, ctl, 5, k, 0.03, arms[pl.arm].col); }
      else if (pl.sat != null) { const sa = sats[pl.sat], ctl = p.clone().lerp(sa.pos, 0.6); curve(p, sa.pos, ctl, 5, k, 0.03, sa.col); } });
    // claim -> node hyphae (bounded by the engine); they rise from the claim and bend into the halo
    claimNodes.slice(0, 3000).forEach(cn => { const p = pos[cn.k]; if (!p) return; const to = local(cn.p), ctl = p.clone().lerp(to, 0.5);
      ctl.y = lerp(p.y, to.y, 0.15); const pl = place[cn.k] || {};
      curve(p, to, ctl, 8, cn.k, 0.006, pl.arm != null ? arms[pl.arm].col : pl.sat != null ? sats[pl.sat].col : new THREE.Color('#bfe3ee')); });
    // halo stalks (arm or satellite -> halo centre) and spokes (centre -> its seven orbits)
    halos.forEach(h => { if (!layout.haloCentre) return; const c = local(layout.haloCentre(h.reg));
      const ai = arms.findIndex(a => a.reg === h.reg), si = sats.findIndex(sa => sa.reg === h.reg);
      const base = ai >= 0 ? fil(ai, 0.62) : si >= 0 ? sats[si].pos.clone() : new V3(0, 0, 0);
      const col = ai >= 0 ? arms[ai].col : si >= 0 ? sats[si].col : new THREE.Color('#e8eef0');
      const ctl = base.clone().lerp(c, 0.5); ctl.x = base.x; ctl.z = base.z;
      curve(base, c, ctl, 8, -1, 0.07, col);
      HALO_SPACES.forEach(sp => { const o = layout.haloOrbitLocal(h.reg, sp), n = (h.counts && h.counts[sp]) || 0;
        curve(c, o, c.clone().lerp(o, 0.5), 2, -1, n > 0 ? 0.07 : 0.025, col); }); });
    // pin tethers: straight (a held line), from the pin to its arm's filament at the same radius
    pins.forEach(pn => { const p = local(pn.p), ai = arms.findIndex(a => a.reg === pn.reg);
      const to = ai >= 0 ? fil(ai, Math.hypot(p.x, p.z) / GR) : (sats.find(sa => sa.reg === pn.reg) || { pos: new V3() }).pos;
      P.push(p.x, p.y, p.z, to.x, to.y, to.z); CL.push(-1, -1); UU.push(0, 1); AA.push(0.12, 0.12);
      C.push(1, 0.86, 0.62, 1, 0.86, 0.62); });
    if (P.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aClaim', new THREE.Float32BufferAttribute(CL, 1));
      geo.setAttribute('aU', new THREE.Float32BufferAttribute(UU, 1)); geo.setAttribute('aA', new THREE.Float32BufferAttribute(AA, 1));
      geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3));
      const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: THREAD_VS, fragmentShader: STRAND_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      const o = new THREE.LineSegments(geo, mat); o.frustumCulled = false; g.add(o); disposables.push(geo, mat);
    }
  }

  let pulses = [], linkSlot = 0, strandSlot = 0, claimSlot = 0, now = 0;
  /** A recall used claim `k`: its links light, a light runs out along its arm, up its strand, to the pole, and
   *  back down every strand on that side. Real recall events only (the engine calls it from liveEmit). */
  function pulse(k) {
    const pl = place[k]; if (!pl) return;
    uni.uCP.value[claimSlot % PULSE_SLOTS].set(k, now); claimSlot++;   // its spur and its node hyphae
    (linkOf.get(k) || []).slice(0, 3).forEach(id => { uni.uPulse.value[linkSlot % PULSE_SLOTS].set(id, now); linkSlot++; });
    if (pl.arm == null) {
      // a satellite or halo claim has no arm: its light flies from the claim to the pole on its side, then runs
      // back down that side's strands (uSP arm -2 = no arm leg). Without it 90 of 389 live claims recalled dark.
      const p0 = pos[k]; if (!p0) return;
      const dir = (pl.sat != null ? Math.sign(sats[pl.sat].pos.y) : Math.sign(p0.y)) || 1;
      uni.uSP.value[strandSlot % 4].set(-2, dir, now); strandSlot++;
      pulses.push({ k, from: p0.clone(), dir, t0: now });
      if (pulses.length > PULSE_SLOTS) pulses.shift();
      return;
    }
    const dir = (k % 2) ? 1 : -1;
    uni.uSP.value[strandSlot % 4].set(pl.arm, dir, now); strandSlot++;
    pulses.push({ k, arm: pl.arm, r0: pl.r, th0: pl.th, y0: pl.y, dir, t0: now });
    if (pulses.length > PULSE_SLOTS) pulses.shift();
  }

  function update(t, vis, inside = 0, haloReg = -9) {
    now = t; uni.uVis.value = vis; uni.uIn.value = inside; uni.uHalo.value = haloReg;
    // tidal streams
    let k = 0;
    streams.forEach(s => { const m = s.from.clone().add(s.to).multiplyScalar(0.5).add(new V3(0, R * 0.08, 0));
      s.parts.forEach(p => { const u = (p.u + t * 0.02) % 1, q = 1 - u;
        sP[k * 3] = q * q * s.from.x + 2 * q * u * m.x + u * u * s.to.x + p.o.x; sP[k * 3 + 1] = q * q * s.from.y + 2 * q * u * m.y + u * u * s.to.y + p.o.y;
        sP[k * 3 + 2] = q * q * s.from.z + 2 * q * u * m.z + u * u * s.to.z + p.o.z; sA[k] = 0.04 + 0.12 * Math.sin(u * Math.PI); k++; }); });
    streamGeo.attributes.position.needsUpdate = true; streamGeo.attributes.aA.needsUpdate = true;
    // dust toward the poles
    strands.forEach((sd, n) => dust[n].forEach((d, j) => { const q = (d.s + t * d.v) % 1, onLeg = q < LEG_SHARE;
      const s = onLeg ? q / LEG_SHARE : (q - LEG_SHARE) / (1 - LEG_SHARE), path = onLeg ? LEG[n] : SAMPLES[n], ns = onLeg ? LEG_NS : NS;
      const f = s * ns, i0 = Math.floor(f), w = f - i0;
      const A = path[i0], B = path[Math.min(ns, i0 + 1)], idx = (n * 28 + j) * 3;
      dP[idx] = lerp(A.x, B.x, w) + d.o.x; dP[idx + 1] = lerp(A.y, B.y, w) + d.o.y; dP[idx + 2] = lerp(A.z, B.z, w) + d.o.z;
      dA[n * 28 + j] = onLeg ? (0.08 + 0.16 * s) * Math.sin(Math.min(1, s * 4) * 1.57) : 0.12 + 0.18 * (1 - s); }));
    dustGeo.attributes.position.needsUpdate = true; dustGeo.attributes.aA.needsUpdate = true;
    // pulse heads and the poles
    const pf = poleGeo.attributes.aF; let fTop = 0, fBot = 0;
    for (let i = 0; i < PULSE_SLOTS; i++) {
      const p = pulses[i]; if (!p) { hA[i] = 0; continue; }
      const age = t - p.t0;
      if (p.from) {   // claim -> pole on a curve that bows outward (it reaches the pole at 2.1 s, as the arm path does)
        if (age < 2.1) { const u = age / 2.1, q = 1 - u, mx = p.from.x * 1.25, mz = p.from.z * 1.25, my = (p.from.y + p.dir * HH) * 0.5;
          hP.set([q * q * p.from.x + 2 * q * u * mx, q * q * p.from.y + 2 * q * u * my + u * u * p.dir * HH, q * q * p.from.z + 2 * q * u * mz], i * 3);
          hA[i] = Math.sin(Math.min(1, u * 4) * 1.57); }
        else hA[i] = 0;
      } else if (age < 0.9) { const u = age / 0.9, r = lerp(p.r0, 1, u), th = p.th0 + (r - p.r0) * TIGHT, y = lerp(p.y0, arms[p.arm].lift * R * 0.12, u);
        hP.set([Math.cos(th) * r * GR, y, Math.sin(th) * r * GR], i * 3); hA[i] = 1; }
      else hA[i] = 0;
      if (age >= 2.1 && age < 2.7) { const f = 1 - (age - 2.1) / 0.6; if (p.dir > 0) fTop = Math.max(fTop, f); else fBot = Math.max(fBot, f); }
    }
    pulses = pulses.filter(p => t - p.t0 < 4.2);
    headGeo.attributes.position.needsUpdate = true; headGeo.attributes.aA.needsUpdate = true;
    pf.array[0] = fTop; pf.array[1] = fBot; pf.needsUpdate = true;
  }

  function dispose() { disposables.forEach(d => d.dispose && d.dispose()); }
  function focus(reg) { uni.uFoc.value = reg == null ? -1 : reg; uni.uFocArm.value = reg == null || reg < 0 ? -1 : arms.findIndex(a => a.reg === reg); }
  function mark(hov, sel) { uni.uHov.value = hov == null ? -1 : hov; uni.uSel.value = sel == null ? -1 : sel; }
  return { group: g, update, pulse, dispose, arms, sats, focus, mark };
}
