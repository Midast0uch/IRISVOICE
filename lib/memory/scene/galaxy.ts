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
export function layoutGalaxy({ R, regs, claims, links = [], seed = 7 }) {   // links: [{a, b, w}]
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
      rad: R * (kind === 'spiral' ? 0.12 + 0.12 * Math.sqrt(w) : kind === 'irregular' ? 0.065 + 0.05 * Math.sqrt(w) : 0.075 + 0.06 * Math.sqrt(w)), tight: 2.8 + 3.0 * (st.n ? st.proven / st.n : 0.3),
      bar: kind === 'spiral' && h % 4 === 1, core: 0.35 + 0.65 * Math.sqrt(st.act / maxAct), q,
      c: new V3(), az: 0, ph: (h % 1000) / 1000 * TAU, clumps: [] };
  });
  // ── the arrangement (owner, 2026-11-23: fill the 3D space; inside need not mirror the outside - organise it,
  //    efficient and beautiful): a DOUBLE HELIX of galaxies round the nucleus axis, pole to pole - the Caducean pair
  //    of the physics. Order = relations: from the largest at the equator, two chains grow up and down, each next
  //    galaxy the one most linked to that chain's end; along the height the galaxies alternate strands, so related
  //    galaxies sit next to each other across the axis and their filaments weave it. A companion sits beside its
  //    partner. Every disc faces outward at its own angle (seen open, never as a line).
  const chain = arms.filter(a => !a.companion);
  let seq = [];
  if (chain.length) {
    const root = chain[0].reg, left = new Set(chain.slice(1).map(a => a.reg)), up = [], down = [];
    let endU = root, endD = root, turn = 0;
    while (left.size) { const end = turn % 2 ? endD : endU; let best = -1, bs = -1;
      left.forEach(r => { const sc = S[end][r] * 1000 + arms[r].size; if (sc > bs) { bs = sc; best = r; } });
      left.delete(best); if (turn % 2) { down.push(best); endD = best; } else { up.push(best); endU = best; } turn++; }
    seq = [...down.reverse(), root, ...up];
  }
  const YMAX = HH * 0.62, phi0 = (hashKey('caduceus') % 628) / 100, N = seq.length;
  seq.forEach((reg, i) => { const a = arms[reg], y = N > 1 ? -YMAX + 2 * YMAX * i / (N - 1) : 0, strand = i % 2;
    const phi = phi0 + (y / YMAX) * 1.7 * Math.PI + strand * Math.PI;
    const rho = Math.max(R * 0.14, shellR(y) * 0.5);
    a.c.set(Math.cos(phi) * rho, y, Math.sin(phi) * rho); a.helix = { i, strand, phi }; });
  arms.forEach(a => { if (!a.companion) return; const p = arms[a.partner], out = p.c.clone().setY(0);
    if (out.lengthSq() < 1e-4) out.set(1, 0, 0); out.normalize(); const tan = new V3(-out.z, 0, out.x);
    a.c.copy(p.c).addScaledVector(tan, (p.rad + a.rad) * 1.05 * (hashKey(a.key) % 2 ? 1 : -1)).add(new V3(0, (p.rad + a.rad) * 0.35, 0)); });
  for (let it = 0; it < 80; it++) arms.forEach((a, i) => {   // only what the helix cannot promise: no overlap, inside the shell
    arms.forEach((b, j) => { if (i === j) return; const d = a.c.clone().sub(b.c), L = d.length() || 1e-3, need = (a.rad + b.rad) * 1.08;
      if (L < need) a.c.addScaledVector(d.multiplyScalar(1 / L), (need - L) * 0.5); });
    a.c.y = clamp(a.c.y, -HH * 0.66 + a.rad * 0.5, HH * 0.66 - a.rad * 0.5);
    const lim = Math.max(R * 0.05, shellR(a.c.y) * 0.86 - a.rad * 0.6), hr = Math.hypot(a.c.x, a.c.z);
    if (hr > lim) { a.c.x *= lim / hr; a.c.z *= lim / hr; } });
  arms.forEach(a => {
    const h = hashKey(a.key + 'n'), out = a.c.clone().setY(0); if (out.lengthSq() < 1e-4) out.set(1, 0, 0); out.normalize();
    const tan = new V3(-out.z, 0, out.x), up = new V3(0, Math.sign(a.c.y) || 1, 0);
    let nrm = out.clone().multiplyScalar(0.72).addScaledVector(up, 0.42 + 0.2 * ((h % 50) / 50)).addScaledVector(tan, ((h % 100) / 100 - 0.5) * 0.9);
    if (a.partner >= 0) { const to = arms[a.partner].c.clone().sub(a.c).normalize(); nrm.addScaledVector(nrm.dot(to) < 0 ? to.negate() : to, a.companion ? 0.5 : 0.2); }
    nrm.normalize();
    a.q = new THREE.Quaternion().setFromUnitVectors(new V3(0, 1, 0), nrm).multiply(new THREE.Quaternion().setFromAxisAngle(new V3(0, 1, 0), (h % 628) / 100));
    a.nrm = new V3(0, 1, 0).applyQuaternion(a.q); a.ax = new V3(1, 0, 0).applyQuaternion(a.q); a.az2 = new V3(0, 0, 1).applyQuaternion(a.q);
    a.az = Math.atan2(a.c.z, a.c.x); a.lift = Math.sign(a.c.y) || 1; a.ang = a.az;
    if (a.kind === 'irregular') { const hc = hashKey(a.key + 'c'); for (let k = 0; k < 3 + (hc % 3); k++)
      a.clumps.push(new V3(gauss(), gauss() * 0.7, gauss()).multiplyScalar(a.rad * 0.45)); }
  });
  // a point of a galaxy in its own frame (x along ax, y along its normal, z along az2) -> world
  const toWorld = (a, x, y, z) => a.c.clone().addScaledVector(a.ax, x).addScaledVector(a.nrm, y).addScaledVector(a.az2, z);
  const spiralLocal = (a, j, r, dth = 0) => { const th = a.ph + j * TAU / Math.max(1, a.nArms) + r * a.tight + dth;
    return [Math.cos(th) * r * a.rad, Math.sin(th) * r * a.rad]; };
  // ── the shape of a galaxy comes from its DATA (owner, 2026-11-23: "landmarks almost like a sun"): every landmark
  //    is a SUN with a mass (use, evidence, proven). Linked suns pull together (springs, stronger with traversals),
  //    heavy suns sink toward the core and keep their space (mass repulsion), time runs outward (the start), and a
  //    more proven domain settles flatter (more ordered). The disc then turns differentially, so CHAINS of linked
  //    suns wind into arms - only where the data has chains; clusters stay clumps; no landmarks, no structure. ─────
  const pos = new Array(claims.length), place = new Array(claims.length);
  const groups = new Map();
  claims.forEach((c, i) => { const gg = groups.get(c.reg) || []; gg.push(i); groups.set(c.reg, gg); });
  const linkW = new Map(); links.forEach(l => { if (l.a !== l.b) linkW.set(l.a + '|' + l.b, (linkW.get(l.a + '|' + l.b) || 0) + 0.3 + (l.w || 0)); });
  // STAR SYSTEMS (owner, 2026-11-23: "some organisation of how things are clustered - I just see dots everywhere"):
  // the suns of a galaxy that link to each other form a system (weighted label propagation on the link graph, heavy
  // suns first, at most 7 systems; a small group joins the system it links to most, else its suns stay loose in the
  // outskirts). The heaviest system sits at the core, the others outward on a golden spiral by mass; inside a system
  // its heaviest sun is the centre and the rest settle round it (links pull, mass pushes). Loose suns: the outskirts.
  const systems = arms.map(() => []);
  for (const [reg, idx] of groups) {
    const a = reg >= 0 && reg < arms.length ? arms[reg] : null;
    if (!a) { idx.forEach(ci => { pos[ci] = new V3(gauss(), gauss(), gauss()).multiplyScalar(R * 0.05); place[ci] = { halo: true }; }); continue; }
    const n = idx.length, at = new Map(idx.map((ci, i) => [ci, i]));
    const m = idx.map(ci => Math.max(0.5, claims[ci].mass || 1)), mMax = Math.max(...m), totalM = m.reduce((x, y) => x + y, 0);
    const E = [], adj = idx.map(() => []);
    linkW.forEach((w, key) => { const [x, y] = key.split('|').map(Number), ia = at.get(x), ib = at.get(y);
      if (ia != null && ib != null && ia !== ib) { E.push([ia, ib, w]); adj[ia].push([ib, w]); adj[ib].push([ia, w]); } });
    const lab = idx.map((_, i) => i), ord = idx.map((_, i) => i).sort((p, q) => m[q] - m[p]);
    for (let it = 0; it < 20; it++) { let ch = 0;
      ord.forEach(i => { if (!adj[i].length) return; const sc = new Map();
        adj[i].forEach(([j, w]) => sc.set(lab[j], (sc.get(lab[j]) || 0) + w * (0.5 + m[j] / mMax)));
        let best = lab[i], bs = sc.get(lab[i]) || 0; sc.forEach((v, l) => { if (v > bs + 1e-9) { bs = v; best = l; } });
        if (best !== lab[i]) { lab[i] = best; ch++; } });
      if (!ch) break; }
    const byL = new Map(); idx.forEach((_, i) => { const gg = byL.get(lab[i]) || []; gg.push(i); byL.set(lab[i], gg); });
    const big = [...byL.values()].map(mem => ({ mem, mass: mem.reduce((x, i) => x + m[i], 0) })).sort((p, q) => q.mass - p.mass)
      .filter((s0, k) => k < 7 && s0.mem.length >= 3);
    const sysOf = new Array(n).fill(-1); big.forEach((s0, k) => s0.mem.forEach(i => { sysOf[i] = k; }));
    for (let i = 0; i < n; i++) if (sysOf[i] < 0) { const sc = new Array(big.length).fill(0);
      adj[i].forEach(([j, w]) => { if (sysOf[j] >= 0) sc[sysOf[j]] += w; }); let bk = -1, bs = 0; sc.forEach((v, k) => { if (v > bs) { bs = v; bk = k; } });
      if (bk >= 0) { sysOf[i] = bk; big[bk].mem.push(i); } }
    const NS0 = big.length;
    big.forEach((s0, k) => { const r = k === 0 ? 0 : 0.32 + 0.58 * Math.sqrt(k / Math.max(1, NS0 - 1)), th = a.ph + k * 2.399963;
      s0.cx = Math.cos(th) * r; s0.cz = Math.sin(th) * r; s0.r = 0.1 + 0.28 * Math.sqrt(s0.mass / totalM);
      s0.sun = s0.mem.reduce((bb, i) => (m[i] > m[bb] ? i : bb), s0.mem[0]); });
    const P = new Array(n);
    big.forEach(s0 => {
      const mem = s0.mem, mm = new Map(mem.map((i, k) => [i, k])), nn = mem.length, mx = Math.max(...mem.map(i => m[i]));
      const L = mem.map((i, k) => (i === s0.sun ? new V3() : new V3(Math.cos(k * 2.4) * Math.sqrt(k / nn), gauss() * 0.08, Math.sin(k * 2.4) * Math.sqrt(k / nn))));
      const EE = E.filter(([i, j]) => mm.has(i) && mm.has(j)).map(([i, j, w]) => [mm.get(i), mm.get(j), w]), F = L.map(() => new V3());
      for (let it = 0; it < (nn > 120 ? 50 : 80); it++) {
        F.forEach(f => f.set(0, 0, 0));
        for (let p2 = 0; p2 < nn; p2++) for (let q = p2 + 1; q < nn; q++) {
          const dx = L[p2].x - L[q].x, dy = L[p2].y - L[q].y, dz = L[p2].z - L[q].z, L2 = Math.max(dx * dx + dy * dy + dz * dz, 4e-4);
          const k2 = 0.004 * (0.6 + (m[mem[p2]] * m[mem[q]]) / (mx * mx) * 2) / L2;
          F[p2].x += dx * k2; F[p2].y += dy * k2; F[p2].z += dz * k2; F[q].x -= dx * k2; F[q].y -= dy * k2; F[q].z -= dz * k2; }
        EE.forEach(([p2, q, w]) => { const d = L[q].clone().sub(L[p2]), l = d.length() || 1e-3, f = 0.06 * Math.min(3, w) * (l - 0.15) / l;
          F[p2].addScaledVector(d, f); F[q].addScaledVector(d, -f); });
        for (let p2 = 0; p2 < nn; p2++) { if (mem[p2] === s0.sun) { L[p2].set(0, 0, 0); continue; }
          F[p2].addScaledVector(L[p2], -0.03); F[p2].y -= L[p2].y * 0.15; const l = F[p2].length(); if (l > 0.05) F[p2].multiplyScalar(0.05 / l); L[p2].add(F[p2]); }
      }
      const rmax = Math.max(0.05, ...L.map(v => v.length()));
      L.forEach((v, k) => { v.multiplyScalar(s0.r / rmax); P[mem[k]] = new V3(s0.cx + v.x, v.y, s0.cz + v.z); });
    });
    const loose = idx.map((_, i) => i).filter(i => sysOf[i] < 0).sort((p, q) => (claims[idx[q]].born || 0) - (claims[idx[p]].born || 0));
    loose.forEach((i, k) => { const r = 0.72 + 0.3 * (loose.length > 1 ? k / (loose.length - 1) : 0.5), th = a.ph + k * 2.399963 + 1.1;
      P[i] = new V3(Math.cos(th) * r, gauss() * 0.05, Math.sin(th) * r); });
    const flatK = 1.1 - 0.6 * (stat[reg].n ? stat[reg].proven / stat[reg].n : 0.3), turn = v => { const r = Math.hypot(v.x, v.z), tw = a.tight * 0.4 * r, c = Math.cos(tw), sn = Math.sin(tw);
      return [(v.x * c - v.z * sn) * a.rad * 0.92, v.y * a.rad * 0.92 * flatK, (v.x * sn + v.z * c) * a.rad * 0.92]; };
    for (let i = 0; i < n; i++) { const [x, y, z] = turn(P[i]), ci = idx[i]; pos[ci] = toWorld(a, x, y, z);
      place[ci] = { arm: reg, j: 0, r: clamp(Math.hypot(x, z) / a.rad, 0, 1.4), th: Math.atan2(z, x), y, x, z, mass: m[i] / mMax, sys: sysOf[i], sun: sysOf[i] >= 0 && big[sysOf[i]].sun === i }; }
    big.forEach((s0, k) => { const [x, , z] = turn(new V3(s0.cx, 0, s0.cz));
      systems[reg].push({ id: k, reg, x, z, c: toWorld(a, x, 0, z), r: s0.r * a.rad * 0.92, members: s0.mem.map(i => idx[i]), sun: idx[s0.sun], mass: s0.mass / totalM }); });
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
    // a pin is a MOON of its galaxy's clusters (owner, 2026-11-23): pins shared out across the groups, each on a small
    // still orbit beside its group (held, not drifting)
    const sys = a ? systems[reg] || [] : [];
    if (sys.length) { const sy = sys[j % sys.length], an = j * 2.399963, rr = sy.r * (1.15 + 0.35 * fr);
      return toWorld(a, sy.x + Math.cos(an) * rr, a.rad * 0.05 * (fz - 0.5), sy.z + Math.sin(an) * rr); }
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
    pinAt, labelAt, viewOf, pathBetween, related, S, DIAL_R, seq, systems };
}

const OFF_GLSL = `uniform vec3 uOff[12];vec3 offOf(float r){return r<-.5?vec3(0.):uOff[int(clamp(r,0.,11.))];}`;
const FOCUS_GLSL = `float focusDim(float reg,float foc){return foc<-.5?1.:(abs(reg-foc)<.5?1.2:(reg<-.5?.55:.22));}
  uniform vec3 uOff[12];vec3 offOf(float r){return r<-.5?vec3(0.):uOff[int(clamp(r,0.,11.))];}
  uniform float uNearZ,uSpan;float depthK(float z){return clamp(1.3-(z-uNearZ)/uSpan,.3,1.3);}`;
const STAR_VS = `uniform float uTime,uPix,uVis,uFoc,uIn;attribute float aA,aPh,aSz,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;
  ${FOCUS_GLSL}
  void main(){vec4 mv=modelViewMatrix*vec4(position+offOf(aReg),1.);float tw=.78+.22*sin(uTime*(.6+aPh*.9)+aPh*40.);
    vC=aC;vA=aA*tw*uVis*smoothstep(.4,3.,-mv.z)*focusDim(aReg,uFoc)*depthK(-mv.z)*(aReg<-.5?1.-.9*uIn:1.-.55*uIn);gl_PointSize=min(aSz*uPix*(60./-mv.z),6.*uPix);gl_Position=projectionMatrix*mv;}`;
const STAR_FS = `varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
  gl_FragColor=vec4(vC,(smoothstep(.5,.0,d)*.55+smoothstep(.18,.0,d)*.6)*vA);}`;
// soft glows (galaxy cores and halos, nebula clumps, far galaxies): large, faint, gaussian
const GLOW_VS = `uniform float uPix,uVis,uFoc,uIn;attribute float aA,aSz,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;
  ${FOCUS_GLSL}
  void main(){vec4 mv=modelViewMatrix*vec4(position+offOf(aReg),1.);vC=aC;vA=aA*uVis*focusDim(aReg,uFoc)*smoothstep(.3,2.5,-mv.z)*depthK(-mv.z)*(1.-.55*uIn);
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
  const uni = { ...U, uVis: { value: 1 }, uIn: { value: 0 }, uHalo: { value: -9 }, uFoc: { value: -1 }, uFocArm: { value: -1 }, uHov: { value: -1 }, uSel: { value: -1 }, uIso: { value: 0 },
    uNearZ: { value: 0 }, uSpan: { value: R * 2 }, uOff: { value: Array.from({ length: 12 }, () => new V3()) }, uIsoK: { value: 0 } };
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
    for (let i = 0; i < 1800; i++) { const u = rng() * 2 - 1, ph = rng() * TAU, q = Math.sqrt(1 - u * u), rr = R * (14 + 8 * rng());
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
    { const o = addPoints(P, C, A, PH, SZ); o.userData.shell = true; o.userData.deep = true; }   // deep space stays round every tab, and inside
  }

  // ── the galaxies, drawn FROM their suns (owner, 2026-11-23): each landmark's own system (a cloud sized by its mass,
  //    orbit rings round the heaviest), bridges of stars along its strongest links (the arms ARE links), a disc that
  //    follows where the suns are, a faint halo of old stars. Colour = the landmark's state: young (this week) pink
  //    like newborn stars, proven bright and white, still learning in the domain's tint, fading amber. A domain
  //    with no landmarks has no structure: a soft featureless cloud. The heaviest sun is the core, with spikes. ────
  const PINK = new THREE.Color('#ff8fc4'), AMBER = new THREE.Color('#ffb46b');
  const spikes = [];
  const byGal = arms.map(() => []);
  pos.forEach((p, k) => { const pl = place[k]; if (p && pl && pl.arm != null && byGal[pl.arm]) byGal[pl.arm].push(k); });
  const STATE_COL = { 1: new THREE.Color('#eef6ff'), 2: new THREE.Color('#86dcff'), 3: new THREE.Color('#ff80c4'), 4: new THREE.Color('#ff8a4c') };
  const sunCol = (a, k) => { const info = claimInfo[k] || {};
    if (info.young) return PINK.clone().lerp(W, 0.25);
    if (info.fading) return AMBER.clone();
    return info.proven ? a.col.clone().lerp(W, 0.55) : a.col.clone().lerp(W, 0.15); };
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [];
    const put = (p, c, al, sz, reg) => { P.push(p.x, p.y, p.z); C.push(c.r, c.g, c.b); A.push(al); PH.push(rng()); SZ.push(sz); RG.push(reg); };
    const total = 13000, wsum = arms.reduce((sum, a) => sum + 0.25 + a.size, 0) || 1;   // the frame budget (28 fps at DPR 1, measured)
    arms.forEach(a => {
      const budget = Math.round(total * (0.25 + a.size) / wsum), ks = byGal[a.reg], coreC = WARM.clone().lerp(a.col, 0.25);
      const halo = (cnt, al) => { for (let i = 0; i < cnt; i++) { const u = rng() * 2 - 1, ph = rng() * TAU, q = Math.sqrt(1 - u * u), rr = a.rad * (0.3 + 1.0 * Math.pow(rng(), 0.6));
        put(toWorld(a, Math.cos(ph) * q * rr, u * rr * 0.8, Math.sin(ph) * q * rr), coreC.clone().lerp(a.col, 0.5), al * (0.6 + 0.8 * rng()), 0.9, a.reg); } };
      if (!ks.length) {   // no landmarks: a featureless cloud (its moments, no structure yet)
        for (let i = 0; i < budget * 0.8; i++) { const v = new V3(gauss(), gauss() * 0.75, gauss()), r = clamp(v.length() / 1.4, 0, 1); v.multiplyScalar(a.rad * 0.45);
          put(toWorld(a, v.x, v.y, v.z), coreC.clone().lerp(a.col, 0.5 * r), 0.06 + 0.14 * (1 - r), 1.0 + rng() * 0.6, a.reg); }
        halo(Math.round(budget * 0.2), 0.035);
        glow(a.c, coreC, 0.06, a.rad / R * 6, a.reg); glow(a.c, a.col, 0.018, a.rad / R * 12, a.reg);
        return;
      }
      const mass = ks.map(k => place[k].mass || 0.3), msum = mass.reduce((x, y) => x + y, 0) || 1;
      const flatY = v => v.y * 0.45;
      // (1) each sun's system: a cloud sized by its mass (45% of the budget)
      ks.forEach((k, i) => { const pl = place[k], cnt = Math.max(4, Math.round(budget * 0.45 * mass[i] / msum)), col = sunCol(a, k), sr = a.rad * (0.025 + 0.07 * Math.sqrt(mass[i]));
        for (let j = 0; j < cnt; j++) { const v = new V3(gauss(), gauss(), gauss()).multiplyScalar(sr); v.y = flatY(v);
          put(toWorld(a, pl.x + v.x, pl.y + v.y, pl.z + v.z), col.clone().lerp(W, 0.15 * rng()), 0.07 + 0.16 * rng(), 1.0 + rng() * 0.7, a.reg); } });
      // (2) bridges: stars along the strongest links between this galaxy's suns (20%) - the arms are the links
      const inner = links.filter(l => { const pa = place[l.a], pb = place[l.b]; return pa && pb && pa.arm === a.reg && pb.arm === a.reg; })
        .sort((x, y) => (y.w || 0) - (x.w || 0)).slice(0, 260);
      const bridgeN = Math.round(budget * 0.2 / Math.max(1, inner.length));
      inner.forEach(l => { const pa = place[l.a], pb = place[l.b], mid = new V3((pa.x + pb.x) / 2 * 0.85, (pa.y + pb.y) / 2, (pa.z + pb.z) / 2 * 0.85);
        const ca = sunCol(a, l.a), cb = sunCol(a, l.b);
        for (let j = 0; j < bridgeN; j++) { const u = rng(), q = 1 - u, x = q * q * pa.x + 2 * q * u * mid.x + u * u * pb.x, y = q * q * pa.y + 2 * q * u * mid.y + u * u * pb.y, z = q * q * pa.z + 2 * q * u * mid.z + u * u * pb.z;
          const sp = a.rad * 0.012; put(toWorld(a, x + gauss() * sp, y + gauss() * sp * 0.5, z + gauss() * sp), ca.clone().lerp(cb, u), 0.06 + 0.1 * rng(), 0.9 + rng() * 0.5, a.reg); } });
      // (3) the disc follows the suns' density: a sun picked by mass, a wider, flatter offset (20%)
      const cum = []; let acc = 0; mass.forEach(x => { acc += x; cum.push(acc); });
      for (let i = 0; i < budget * 0.2; i++) { const u = rng() * acc; let lo = 0; while (cum[lo] < u) lo++; const pl = place[ks[lo]];
        const v = new V3(gauss(), gauss() * 0.3, gauss()).multiplyScalar(a.rad * 0.16);
        put(toWorld(a, pl.x + v.x, pl.y + v.y, pl.z + v.z), a.col.clone().lerp(coreC, 0.3 * rng()), 0.04 + 0.08 * rng(), 0.9, a.reg); }
      // (4) a faint halo of old stars (15%)
      halo(Math.round(budget * 0.15), 0.035);
      // the heaviest suns: a glow each; orbit rings (their systems) round the three heaviest; spikes on the core sun
      const top = ks.map((k, i) => ({ k, m: mass[i] })).sort((x, y) => y.m - x.m);
      top.slice(0, 4).forEach(({ k, m }, i) => { const p = pos[k], col = sunCol(a, k);   // 4 glows a galaxy: large sprites cost fill rate
        glow(p, col, 0.06 + 0.1 * m, a.rad / R * (1.8 + 2.6 * m), a.reg);
        if (i < 3) { const pl = place[k], rings = 1 + Math.min(2, Math.round(m * 2));
          for (let rI = 1; rI <= rings; rI++) { const rr = a.rad * (0.04 + 0.035 * rI) * (0.7 + m);
            for (let j = 0; j < 48; j++) { const th = j / 48 * TAU; put(toWorld(a, pl.x + Math.cos(th) * rr, pl.y, pl.z + Math.sin(th) * rr), col.clone().lerp(W, 0.4), 0.09, 0.8, a.reg); } } }
        if (i === 0) spikes.push({ p: p.clone(), c: col.clone().lerp(W, 0.5), a: 0.35, sz: a.rad / R * 6, reg: a.reg }); });
      glow(a.c, a.col, 0.018, a.rad / R * 13, a.reg);   // the faint light of the whole galaxy (wide glows made a navy haze)
      (layout.systems[a.reg] || []).forEach(sy => glow(sy.c, sunCol(a, sy.sun).lerp(a.col, 0.5), 0.03 + 0.05 * Math.sqrt(sy.mass), sy.r / R * 11, a.reg));   // a group's light (wide lights made a haze)
    });
    addPoints(P, C, A, PH, SZ, RG);
  }

  // ── the space between the galaxies: interstellar stars that fill the shell (tinted by the nearest galaxy),
  //    nebula clouds round the helix, and the luminous double-helix spine that joins the galaxies in order ─────────
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [];
    for (let i = 0; i < 1800; i++) { const y = (rng() * 2 - 1) * HH * 0.9, rm = shellR(y) * 0.95, rho = rm * Math.pow(rng(), 0.45), th = rng() * TAU;
      const p = new V3(Math.cos(th) * rho, y, Math.sin(th) * rho); let best = null, bd = 1e9;
      arms.forEach(a => { const d = a.c.distanceTo(p) / a.rad; if (d < bd) { bd = d; best = a; } });
      const c = best ? best.col.clone().lerp(COOL, 0.5) : COOL; P.push(p.x, p.y, p.z); C.push(c.r, c.g, c.b);
      A.push(0.006 + 0.022 * Math.pow(rng(), 2)); PH.push(rng()); SZ.push(0.9 + rng() * 0.5); RG.push(-1); }   // a whisper: the inside is a black void
    addPoints(P, C, A, PH, SZ, RG);
    const NEB = [new THREE.Color('#7a5cff'), new THREE.Color('#2fd4c8'), new THREE.Color('#ff6fae'), new THREE.Color('#4f8dff')];
    for (let k = 0; k < 10; k++) { const y = (k / 9 * 2 - 1) * HH * 0.55, th = (hashKey('neb' + k) % 628) / 100, rho = shellR(y) * (0.3 + 0.4 * rng());
      const c0 = new V3(Math.cos(th) * rho, y, Math.sin(th) * rho), col = NEB[k % NEB.length];
      for (let j = 0; j < 2; j++) glow(c0.clone().add(new V3(gauss(), gauss() * 0.6, gauss()).multiplyScalar(R * 0.08)), col, 0.007 + 0.005 * rng(), 4 + 3 * rng()); }
  }
  // the double-helix spine: a filament of stars through the galaxies in helix order (two strands, the Caducean pair)
  const SPINE = [];
  if (layout.seq && layout.seq.length > 1) {
    const pts = layout.seq.map(r => arms[r].c.clone()), curve = new THREE.CatmullRomCurve3([new V3(0, -HH * 0.95, 0), ...pts, new V3(0, HH * 0.95, 0)], false, 'centripetal');
    SPINE.push({ curve, cols: [new THREE.Color('#9fe6ff'), new THREE.Color('#ffe2b8')] });
  }

  // ── the claims ARE stars of their galaxy: a core in the domain's tint; a ring = proven (solid) or still learning
  //    (dashed); brightness = sync; they grow as you go inside (uIn); hover and focus ring them white ──────────────
  const CLAIM_VS = `uniform float uTime,uPix,uVis,uIn,uFoc,uHov,uSel,uIso;attribute float aIdx,aProven,aSync,aReg,aPh,aMass,aState,aKind,aFam;attribute vec3 aC,aFamC;
    uniform float uIsoK;varying vec3 vC,vFamC;varying float vA,vP,vH,vS,vSt,vPh,vKind,vFam;
    ${FOCUS_GLSL}
    void main(){vec4 mv=modelViewMatrix*vec4(position+offOf(aReg),1.);float h=step(abs(aIdx-uHov),.5),sel=step(abs(aIdx-uSel),.5);
      vC=aC;vP=aProven;vH=h;vS=sel;vSt=aState;vPh=aPh;vKind=aKind;vFam=aFam;vFamC=aFamC;float tw=abs(aState-4.)<.5?.55+.45*sin(uTime*2.6+aPh*20.):.85+.15*sin(uTime*(.4+aPh)+aPh*30.);
      float iso=(uIso<.5?1.:(abs(aState-uIso)<.5?1.4:.08))*(uIsoK<.5?1.:(abs(aKind-uIsoK)<.5?1.4:.08));
      vA=(.55+.35*aSync)*mix(.6,1.,aMass)*tw*uVis*focusDim(aReg,uFoc)*iso*(1.+.6*max(h,sel));
      float sz=(1.6+1.2*aSync)*(.8+1.*aMass)*(1.+1.2*uIn)*(1.+.7*max(h,sel))*1.6;
      gl_PointSize=clamp(sz*uPix*(60./-mv.z),2.*uPix,(8.+5.*uIn+8.*max(h,sel))*uPix);gl_Position=projectionMatrix*mv;}`;
  const CLAIM_FS = `uniform float uTime;varying vec3 vC,vFamC;varying float vA,vP,vH,vS,vSt,vPh,vKind,vFam;
    void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    vec2 q=abs(c*2.);float hi=max(vH,vS),d2=d*d,core=exp(-d2*150.)*(vSt>1.5&&vSt<2.5?.8:1.3),halo=exp(-d2*12.)*.22,a=core+halo;
    if(vKind>.5&&vKind<1.5){a+=smoothstep(.03,.0,abs(length(vec2(c.x,c.y*2.4))-.34))*.55;}                                   // a way of doing: a star with its orbit
    else if(vKind<2.5&&vKind>1.5){a+=(exp(-q.y*40.)*(1.-q.x)+exp(-q.x*40.)*(1.-q.y))*.6;}                                     // a fact: a fixed star with spikes
    else if(vKind<3.5&&vKind>2.5){vec2 o=vec2(.15,.0);a=exp(-dot(c-o,c-o)*220.)*1.1+exp(-dot(c+o,c+o)*220.)*.85+halo;}       // how you like it: a binary star
    else if(vKind<4.5&&vKind>3.5){float tl=smoothstep(.0,.42,c.x-c.y)*exp(-abs(c.x+c.y)*22.)*.55;a=core+tl+halo*.5;}           // about when: a comet with its tail
    else if(vKind>4.5){float an=atan(c.y,c.x);a+=pow(abs(cos(an*3.)),20.)*smoothstep(.5,.1,d)*.55;}                            // what IRIS can do: a nova with rays
    float m=0.;if(vFam>.5){float an=uTime*.7+vPh*6.28;vec2 mp=vec2(cos(an),sin(an))*.4;m=exp(-dot(c-mp,c-mp)*700.);}           // its strongest event: an orbiting mote
    a+=smoothstep(.035,.0,abs(d-.47))*hi*.9;                                                                                     // hover / focus
    gl_FragColor=vec4(mix(mix(vC,vec3(1.),.25+.4*hi),vFamC,clamp(m*1.5,0.,1.)),(a+m*1.2)*vA);}`;
  {
    const P = [], C = [], IX = [], PR = [], SY = [], RG = [], PH = [], MS = [], ST = [], KD = [], FA = [], FC = [];
    pos.forEach((p, k) => { if (!p) return; const pl = place[k] || {}, info = claimInfo[k] || {}, a = pl.arm != null ? arms[pl.arm] : null;
      const st = info.young ? 3 : info.fading ? 4 : info.proven ? 1 : 2, col = STATE_COL[st].clone(); MS.push(pl.mass || 0.3); ST.push(st);
      const fc = new THREE.Color(info.famCol || '#ffffff'); KD.push(info.kind || 0); FA.push(info.famCol ? 1 : 0); FC.push(fc.r, fc.g, fc.b);
      P.push(p.x, p.y, p.z); C.push(col.r, col.g, col.b); IX.push(k); PR.push(info.proven ? 1 : 0); SY.push(clamp(info.sync ?? 0.4, 0, 1)); RG.push(a ? a.reg : -1); PH.push(rng()); });
    if (P.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3));
      geo.setAttribute('aIdx', new THREE.Float32BufferAttribute(IX, 1)); geo.setAttribute('aProven', new THREE.Float32BufferAttribute(PR, 1));
      geo.setAttribute('aSync', new THREE.Float32BufferAttribute(SY, 1)); geo.setAttribute('aReg', new THREE.Float32BufferAttribute(RG, 1));
      geo.setAttribute('aPh', new THREE.Float32BufferAttribute(PH, 1)); geo.setAttribute('aMass', new THREE.Float32BufferAttribute(MS, 1)); geo.setAttribute('aState', new THREE.Float32BufferAttribute(ST, 1));
      geo.setAttribute('aKind', new THREE.Float32BufferAttribute(KD, 1)); geo.setAttribute('aFam', new THREE.Float32BufferAttribute(FA, 1)); geo.setAttribute('aFamC', new THREE.Float32BufferAttribute(FC, 3));
      const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: CLAIM_VS, fragmentShader: CLAIM_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      const o = new THREE.Points(geo, mat); o.frustumCulled = false; o.renderOrder = 2; g.add(o); disposables.push(geo, mat);
    }
  }

  // ── the cosmic web (owner, 2026-11-23: show the galaxies in relation to each other): a filament of stars between
  //    two galaxies whose claims are linked, brighter and wider with more links; a faint thread from every galaxy to
  //    the nucleus. Light streams along them (a moving wave in the shader). ──────────────────────────────────────
  const FIL_VS = `uniform float uTime,uPix,uVis,uFoc;attribute float aA,aPh,aSz,aReg,aU,aRegB;attribute vec3 aC;varying vec3 vC;varying float vA;
    ${FOCUS_GLSL}
    void main(){vec4 mv=modelViewMatrix*vec4(position+mix(offOf(aReg),offOf(aRegB),aU),1.);float flow=.55+.45*sin(aU*38.-uTime*1.3+aPh*2.);
      float fd=max(focusDim(aReg,uFoc),focusDim(aRegB,uFoc));
      vC=aC;vA=aA*flow*uVis*fd*smoothstep(.3,2.5,-mv.z)*depthK(-mv.z);gl_PointSize=clamp(aSz*uPix*(60./-mv.z),1.3*uPix,5.*uPix);gl_Position=projectionMatrix*mv;}`;
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
      glow(path[1], arms[i].col.clone().lerp(arms[j].col, 0.5), 0.02, 3.5 + 2 * rng());   // nebula dust where they meet
    }
    arms.forEach(a => { const m = a.c.clone().multiplyScalar(0.5).add(new V3(0, R * 0.04, 0)); fil(a.c, m, new V3(), a.col, WARM, 70, R * 0.004, 0.07, a.reg, a.reg); });
    SPINE.forEach(sp => { for (let i = 0; i < 1400; i++) { const u = rng(), p = sp.curve.getPoint(u), sprd = R * 0.012;
      P.push(p.x + gauss() * sprd, p.y + gauss() * sprd, p.z + gauss() * sprd); const c = sp.cols[0].clone().lerp(sp.cols[1], u);
      C.push(c.r, c.g, c.b); A.push(0.07 + 0.06 * rng()); PH.push(rng()); SZ.push(1.1 + rng() * 0.6); RG.push(-1); RB.push(-1); UU.push(u * 3); } });
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
      vA=(step(.001,aW)*(.014+.05*aW)*(.3+.7*sin(aU*3.14159))*(1.-.8*uIn)*focusDim(aReg,uFoc)+lit*.75)*uVis*(aReg<-.5?1.-uIn:1.);   // inside: links between domains ride the web, not loose lines
      gl_Position=projectionMatrix*modelViewMatrix*vec4(position+offOf(aReg),1.);}`;
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
        const a = arms[pa.arm], lane = ((id * 0.618) % 1 - 0.5) * a.rad * 0.06;
        const mid = new V3((pa.x + pb.x) / 2 * 0.85 + lane, (pa.y + pb.y) / 2 + lane * 0.5, (pa.z + pb.z) / 2 * 0.85 - lane);
        for (let k = 0; k <= 12; k++) { const u = k / 12, q = 1 - u;   // a curve between two suns, bowed a little toward the core
          pts.push(toWorld(a, q * q * pa.x + 2 * q * u * mid.x + u * u * pb.x, q * q * pa.y + 2 * q * u * mid.y + u * u * pb.y, q * q * pa.z + 2 * q * u * mid.z + u * u * pb.z)); }
      } else {
        const A0 = pos[ln.a], B0 = pos[ln.b], ca = arms[pa.arm].c, cb = arms[pb.arm].c, path = layout.pathBetween(pa.arm, pb.arm);
        const m = path ? path[1] : ca.clone().add(cb).multiplyScalar(0.5), jit = new V3(gauss(), gauss(), gauss()).multiplyScalar(R * 0.01);
        const c1 = A0.clone().lerp(m, 0.5).add(jit), c2 = B0.clone().lerp(m, 0.5).add(jit);   // from the claim toward the web (never through the core: a starburst)
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
      vC=mix(aC,vec3(.96,1.,.98),clamp(lit,0.,1.));vA=(base*tw*(1.-uIn)+.9*lit*(1.-uIn))*uVis*smoothstep(.4,3.,-mv.z);   // inside: the weave is gone, only the galaxies in black space
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
    const o = new THREE.Points(geo, mat); o.frustumCulled = false; o.userData.strands = true; o.userData.shell = true; g.add(o); disposables.push(geo, mat);
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
    const o = new THREE.Points(dustGeo, mat); o.frustumCulled = false; o.userData.shell = true; g.add(o); disposables.push(dustGeo, mat); }

  // ── §9.2 the halos: seven dots per domain (strength = how many of its nodes sit in that space) and a faint ring ──
  const HALO_VS = `uniform float uTime,uPix,uVis,uIn,uHalo;attribute float aA,aSz,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;${OFF_GLSL}
    void main(){vec4 mv=modelViewMatrix*vec4(position+offOf(aReg),1.);float mine=step(abs(aReg-uHalo),.5);
      vC=aC;vA=aA*uVis*mix(1.-.55*uIn,1.+1.2*uIn,mine)*(aReg<-.5?1.-uIn:1.);gl_PointSize=min(aSz*uPix*(60./-mv.z),(5.+5.*mine*uIn)*uPix);gl_Position=projectionMatrix*mv;}`;
  const RING_VS = `uniform float uVis,uIn,uHalo;attribute float aReg;varying float vA;${OFF_GLSL}
    void main(){float mine=step(abs(aReg-uHalo),.5);vA=.025*uVis*mix(1.-.6*uIn,1.+2.*uIn,mine)*(aReg<-.5?1.-uIn:1.);gl_Position=projectionMatrix*modelViewMatrix*vec4(position+offOf(aReg),1.);}`;
  const colOfReg = reg => (reg >= 0 && arms[reg] ? arms[reg].col : new THREE.Color(0.85, 0.9, 0.95));
  if (halos.length) {
    const P = [], C = [], A = [], SZ = [], RG = [], LP = [], LR = [];
    halos.forEach(h => { const tint = colOfReg(h.reg);
      HALO_SPACES.forEach((sp, i) => {
        const o = layout.haloOrbitLocal(h.reg, sp), n = (h.counts && h.counts[sp]) || 0;
        P.push(o.x, o.y, o.z); C.push(tint.r, tint.g, tint.b); RG.push(h.reg);
        A.push(n > 0 ? 0.2 + 0.3 * Math.min(1, Math.log10(1 + n) / 2) : 0); SZ.push(n > 0 ? 2.6 + Math.min(2, Math.log10(1 + n) * 1.3) : 0);   // only the spaces that hold something
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
  const THREAD_VS = `uniform float uTime,uVis,uIn;uniform vec2 uCP[${PULSE_SLOTS}];attribute float aClaim,aU,aA,aReg;attribute vec3 aC;varying vec3 vC;varying float vA;${OFF_GLSL}
    void main(){float lit=0.;for(int i=0;i<${PULSE_SLOTS};i++){vec2 p=uCP[i];if(p.x==aClaim){float age=uTime-p.y;
      lit=max(lit,smoothstep(.12,0.,abs(aU-age/.7))*step(0.,age)*step(age,1.)+.5*smoothstep(1.4,0.,age)*step(0.,age));}}
      vC=mix(aC,vec3(.96,1.,.98),clamp(lit,0.,1.));vA=(aA*(1.+.6*uIn)+.75*lit)*uVis;gl_Position=projectionMatrix*modelViewMatrix*vec4(position+offOf(aReg),1.);}`;
  uni.uCP = { value: Array.from({ length: PULSE_SLOTS }, () => new THREE.Vector2(-1, -99)) };
  {
    const P = [], CL = [], UU = [], AA = [], C = [], TR = [];
    const curve = (A0, B0, ctl, n, claim, a0, col, reg = -1) => { let prev = A0;
      for (let k = 1; k <= n; k++) { const u = k / n, pt = bez(A0, ctl, B0, u);
        P.push(prev.x, prev.y, prev.z, pt.x, pt.y, pt.z); CL.push(claim, claim); UU.push((k - 1) / n, u); TR.push(reg, reg);
        const fa = a0 * (0.55 + 0.45 * Math.sin(u * Math.PI)); AA.push(fa, fa); C.push(col.r, col.g, col.b, col.r, col.g, col.b); prev = pt; } };
    claimNodes.slice(0, 3000).forEach(cn => { const p = pos[cn.k]; if (!p) return; const pl = place[cn.k] || {}, ctl = p.clone().lerp(cn.p, 0.5);
      ctl.y = lerp(p.y, cn.p.y, 0.15); curve(p, cn.p, ctl, 8, cn.k, 0.008, colOfReg(pl.arm != null ? pl.arm : -1), pl.arm != null ? pl.arm : -1); });
    halos.forEach(h => { const c = layout.haloCentre(h.reg), a = h.reg >= 0 ? arms[h.reg] : null, base = a ? a.c.clone() : new V3();
      const col = colOfReg(h.reg); curve(base, c, base.clone().lerp(c, 0.5).add(new V3(0, R * 0.01, 0)), 8, -1, 0.035, col, h.reg);
    });   // (no spokes: the orbit and its moons say it - spokes read as a diagram)
    false && pins.forEach(pn => { const a = pn.reg >= 0 ? arms[pn.reg] : null;   // (moons beside their cluster need no tether)
      let to = new V3(); if (a) { const v = pn.p.clone().sub(a.c); to = toWorld(a, v.dot(a.ax) * 0.88, 0, v.dot(a.az2) * 0.88); }
      P.push(pn.p.x, pn.p.y, pn.p.z, to.x, to.y, to.z); CL.push(-1, -1); UU.push(0, 1); AA.push(0.1, 0.1); C.push(1, 0.86, 0.62, 1, 0.86, 0.62); TR.push(pn.reg, pn.reg); });
    if (P.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); geo.setAttribute('aClaim', new THREE.Float32BufferAttribute(CL, 1));
      geo.setAttribute('aU', new THREE.Float32BufferAttribute(UU, 1)); geo.setAttribute('aA', new THREE.Float32BufferAttribute(AA, 1));
      geo.setAttribute('aC', new THREE.Float32BufferAttribute(C, 3)); geo.setAttribute('aReg', new THREE.Float32BufferAttribute(TR, 1));
      const mat = new THREE.ShaderMaterial({ uniforms: uni, vertexShader: THREAD_VS, fragmentShader: LINE_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      const o = new THREE.LineSegments(geo, mat); o.frustumCulled = false; g.add(o); disposables.push(geo, mat);
    }
  }

  let voidMat = null, voidMat_o = null;   // the black inner body (below): unseen from outside, the black void once you are inside
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
        gl_FragColor=vec4(vC,(.003+.034*f)*(.5+.5*w)*uVis*(1.-uIn));}` });   // from inside: the strands show the shell, the skin stays dark
    const o = new THREE.Mesh(geo, mat); o.frustumCulled = false; o.renderOrder = -1; o.userData.shell = true; g.add(o); disposables.push(geo, mat);
    // the VOID inside the shell (owner, 2026-11-23: the inside must be black like space; the panel round it keeps its
    // own colour): the shell's inner faces in black, drawn before everything else in the shell, so the backdrop seen
    // through the shell goes dark and the galaxies, claims and weave light up on top of it
    voidMat = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0, side: THREE.BackSide, depthWrite: false });
    const vo = new THREE.Mesh(geo, voidMat); vo.frustumCulled = false; vo.renderOrder = -10; vo.userData.shell = true; g.add(vo); disposables.push(voidMat); voidMat_o = vo;
  }
  // the dial: a faint ring of stars at the equator, a tick of each domain's colour at its galaxy's compass angle
  {
    const P = [], C = [], A = [], PH = [], SZ = [], RG = [];
    for (let i = 0; i < 520; i++) { const th = i / 520 * TAU; P.push(Math.cos(th) * DIAL_R, 0, Math.sin(th) * DIAL_R); C.push(0.7, 0.86, 0.95); A.push(0.05); PH.push(rng()); SZ.push(0.9); RG.push(-1); }
    arms.forEach(a => { for (let i = -6; i <= 6; i++) { const t2 = a.az + i * 0.006;
      P.push(Math.cos(t2) * DIAL_R, 0, Math.sin(t2) * DIAL_R); C.push(a.col.r, a.col.g, a.col.b); A.push(0.5 - Math.abs(i) * 0.03); PH.push(rng()); SZ.push(1.8); RG.push(a.reg); } });
    addPoints(P, C, A, PH, SZ, RG).userData.shell = true;   // the dial
  }
  // the soft glows (galaxy cores and halos, nebula dust, far galaxies), drawn once
  if (glows.P.length) addPoints(glows.P, glows.C, glows.A, glows.PH, glows.SZ, glows.RG, GLOW_VS, GLOW_FS);
  // diffraction spikes on the bright cores (the photographic touch: a star seen through a telescope)
  if (spikes.length) addPoints(spikes.flatMap(k => [k.p.x, k.p.y, k.p.z]), spikes.flatMap(k => [k.c.r, k.c.g, k.c.b]), spikes.map(k => k.a),
    spikes.map(() => 0), spikes.map(k => k.sz), spikes.map(k => k.reg), GLOW_VS,
    `varying vec3 vC;varying float vA;void main(){vec2 c=(gl_PointCoord-.5)*2.;float a=abs(c.x),b=abs(c.y);
      float sp=exp(-b*40.)*(1.-a)+exp(-a*40.)*(1.-b)+.5*exp(-abs(a-b)*55.)*(1.-max(a,b));float core=exp(-dot(c,c)*30.);
      gl_FragColor=vec4(vC,(sp*.6+core)*vA);}`);

  // the poles: where the strands meet; they flash once when a recall pulse arrives
  const poleGeo = new THREE.BufferGeometry();
  poleGeo.setAttribute('position', new THREE.Float32BufferAttribute([0, HH, 0, 0, -HH, 0], 3));
  poleGeo.setAttribute('aF', new THREE.Float32BufferAttribute([0, 0], 1));
  const poleMat = new THREE.ShaderMaterial({ uniforms: uni,
    vertexShader: `uniform float uPix,uVis;attribute float aF;varying float vF,vA;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vF=aF;vA=uVis;gl_PointSize=min((6.+26.*aF)*uPix*(60./-mv.z),60.*uPix);gl_Position=projectionMatrix*mv;}`,
    fragmentShader: `varying float vF,vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);float core=smoothstep(.2,0.,d);float ring=smoothstep(.5,.44,d)*smoothstep(.36,.42,d)*vF;gl_FragColor=vec4(.92,.99,1.,(core*(.35+.6*vF)+ring*.6)*vA);}`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  { const o = new THREE.Points(poleGeo, poleMat); o.frustumCulled = false; o.userData.shell = true; g.add(o); disposables.push(poleGeo, poleMat); }
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

  // the inner space: the galaxy you are in stays; every other moves away to SPACE_K x its distance. The centre eases
  // to the galaxy you travel to, so the others drift apart and close in smoothly (never a jump).
  const SPACE_K = 4, cen = new V3(); let cenSet = false, lastT = 0;
  function offsetOf(reg) { return reg >= 0 && reg < 12 ? uni.uOff.value[reg].clone() : new V3(); }
  function update(t, vis, inside = 0, haloReg = -9, camD = R * 5.8) {
    const dt = Math.min(0.1, Math.max(0, t - lastT)); lastT = t;
    const tgt = haloReg >= 0 && arms[haloReg] ? arms[haloReg].c : null;
    if (tgt) { if (!cenSet || inside < 0.05) { cen.copy(tgt); cenSet = true; } else cen.lerp(tgt, 1 - Math.pow(0.04, dt)); }
    arms.forEach((a, i) => { if (i < 12) uni.uOff.value[i].copy(a.c).sub(cen).multiplyScalar((SPACE_K - 1) * inside * (cenSet ? 1 : 0)); });
    now = t; uni.uVis.value = vis; uni.uIn.value = inside; uni.uHalo.value = haloReg;
    uni.uNearZ.value = Math.max(0, camD - R); uni.uSpan.value = R * 2;   // the shell's near side is the brightest
    if (voidMat) { voidMat.opacity = inside; voidMat.visible = inside > 0.02; }
    g.children.forEach(o => { if (o.userData.shell && o !== voidMat_o && !o.userData.deep) o.visible = inside < 0.97; });   // inside: the shell's parts step away   // owner, 2026-11-23: outside the shell stays as it was; inside, the void of space
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
  /** the galaxies themselves show in the cortex tab; the shell (weave, skin, poles, dial, deep space) in every tab */
  function interior(on) { g.children.forEach(o => { if (!o.userData.shell) o.visible = on; }); }
  function focus(reg) { uni.uFoc.value = reg == null ? -1 : reg; uni.uFocArm.value = reg == null || reg < 0 || !arms[reg] ? -1 : reg; }
  function mark(hov, sel) { uni.uHov.value = hov == null ? -1 : hov; uni.uSel.value = sel == null ? -1 : sel; }
  /** the key isolates one landmark state: 1 proven, 2 still learning, 3 new this week, 4 fading; 0 = all */
  function isolate(k) { uni.uIso.value = k || 0; }
  /** the key isolates one KIND of claim: 1 a way of doing, 2 a fact, 3 how you like it, 4 about when, 5 what IRIS can do */
  function isolateKind(k) { uni.uIsoK.value = k || 0; }
  return { group: g, update, pulse, dispose, arms, sats, focus, mark, isolate, isolateKind, interior, offsetOf };
}
