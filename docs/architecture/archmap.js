/* archmap.js — shared engine for the IRIS architecture concept maps.
 *
 * A page defines window.MAP = {lanes, nodes, edges, flows, filters?, intro?}
 * and the DOM skeleton (ids: map, mini, side, flowSel, play, prev, next,
 * overview, viewToggle, slide, filters). This file draws the map as stacked,
 * colour-coded plates (2.5-D "stack" view) or flat bands, animates the switch,
 * plays flows as a slideshow (camera glide + particles along each connection),
 * and keeps a minimap of the whole map. No dependencies.
 */
(function () {
  "use strict";
  const M = window.MAP;
  const NS = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);
  const svg = $("map"), mini = $("mini"), side = $("side");
  const el = (t, a = {}, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); (p || svg).appendChild(e); return e; };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const fmt = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── geometry ─────────────────────────────────────────────── */
  const U = M.width || 1600;          // plate length in plate units
  const CARD_W = 178, CARD_H = 52;
  const VIEWS = {
    stack: { V: 112, gap: 158, dx: 0.95, dy: 0.40, su: -0.045, lift: 26, ox: 70, oy: 150 },
    flat:  { V: 104, gap: 122, dx: 0.00, dy: 1.00, su: 0.000, lift: 0,  ox: 40, oy: 16 },
  };
  let P = { ...VIEWS.stack }, viewName = "stack";
  const laneIdx = Object.fromEntries(M.lanes.map((l, i) => [l.id, i]));
  function proj(u, v, k, p = P) {
    return [p.ox + u + v * p.dx, p.oy + k * p.gap + v * p.dy + u * p.su];
  }
  function nodePos(n, p = P) {
    const k = laneIdx[n.lane];
    const [x, y] = proj(n.u, p.V / 2, k, p);
    return [x, y - p.lift];
  }
  M.nodes.forEach((n) => { n.u = (n.x || 0) - (M.xOffset || 100); });

  /* ── defs: markers, glows, plate gradients ───────────────── */
  const defs = el("defs");
  const glow = el("filter", { id: "glow", x: "-50%", y: "-50%", width: "200%", height: "200%" }, defs);
  el("feGaussianBlur", { stdDeviation: "4", result: "b" }, glow);
  const fm = el("feMerge", {}, glow); el("feMergeNode", { in: "b" }, fm); el("feMergeNode", { in: "SourceGraphic" }, fm);
  const shadow = el("filter", { id: "lift", x: "-20%", y: "-20%", width: "140%", height: "160%" }, defs);
  el("feDropShadow", { dx: "0", dy: "6", stdDeviation: "5", "flood-color": "#000", "flood-opacity": ".28" }, shadow);
  [["arr", "var(--edge)"], ["arrhot", "var(--hot)"]].forEach(([id, c]) => {
    const m = el("marker", { id, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" }, defs);
    el("path", { d: "M0,0 L10,5 L0,10 z", fill: c }, m);
  });
  M.lanes.forEach((l) => {
    const g = el("linearGradient", { id: "pg-" + l.id, x1: "0", y1: "0", x2: "1", y2: "1" }, defs);
    el("stop", { offset: "0", "stop-color": `var(${l.color})`, "stop-opacity": ".34" }, g);
    el("stop", { offset: ".6", "stop-color": `var(${l.color})`, "stop-opacity": ".14" }, g);
    el("stop", { offset: "1", "stop-color": `var(${l.color})`, "stop-opacity": ".06" }, g);
  });

  /* ── scene ───────────────────────────────────────────────── */
  const scene = el("g", { id: "scene" });
  const gPlates = el("g", {}, scene), gEdges = el("g", {}, scene), gLabels = el("g", {}, scene), gNodes = el("g", {}, scene), gFx = el("g", {}, scene);

  const plates = M.lanes.map((l, k) => {
    const g = el("g", { class: "plate", "data-lane": l.id }, gPlates);
    const side_ = el("polygon", { class: "plate-side", fill: `var(${l.color})` }, g);
    const top = el("polygon", { class: "plate-top", fill: `url(#pg-${l.id})`, stroke: `var(${l.color})` }, g);
    const tab = el("g", { class: "plate-tab" }, g);
    const tabR = el("rect", { rx: 8, height: 26, fill: `var(${l.color})` }, tab);
    const tabT = el("text", { class: "plate-label" }, tab);
    tabT.textContent = (l.icon ? l.icon + "  " : "") + l.label;
    return { l, k, side: side_, top, tab, tabR, tabT };
  });

  const byId = Object.fromEntries(M.nodes.map((n) => [n.id, n]));
  const edges = M.edges.map(([f, t, label, dash]) => {
    const p = el("path", { class: "edge" + (dash ? " dash" : ""), "marker-end": "url(#arr)" }, gEdges);
    let lt = null;
    if (label) { lt = el("text", { class: "elabel" }, gLabels); lt.textContent = label; }
    return { f, t, label, dash, p, lt };
  });

  const STATUS = M.statusColors || { live: "--live", shadow: "--shadow", planned: "--planned", fault: "--fault", enforced: "--enf" };
  const nodeEls = {};
  M.nodes.forEach((n) => {
    const lane = M.lanes[laneIdx[n.lane]];
    const g = el("g", { class: "node st-" + n.status, tabindex: "0", role: "button", "aria-label": n.t }, gNodes);
    el("ellipse", { class: "foot", rx: CARD_W * 0.42, ry: 9, cx: 0, cy: CARD_H / 2 + P.lift - 4 }, g);
    el("line", { class: "stem", x1: 0, y1: CARD_H / 2, x2: 0, y2: CARD_H / 2 + P.lift - 6, stroke: `var(${lane.color})` }, g);
    const box = el("rect", { class: "card", x: -CARD_W / 2, y: -CARD_H / 2, width: CARD_W, height: CARD_H, rx: 12, style: `--lc:var(${lane.color})` }, g);
    el("rect", { class: "cardbar", x: -CARD_W / 2, y: -CARD_H / 2, width: CARD_W, height: 5, rx: 2, fill: `var(${lane.color})` }, g);
    if (n.status === "fault") el("circle", { class: "pulse", cx: CARD_W / 2 - 12, cy: -CARD_H / 2 + 14, r: 5 }, g);
    el("circle", { class: "dot", cx: CARD_W / 2 - 12, cy: -CARD_H / 2 + 14, r: 5, fill: `var(${STATUS[n.status] || "--planned"})` }, g);
    const t = el("text", { class: "t", x: 0, y: -1, "text-anchor": "middle" }, g); t.textContent = n.t;
    const s = el("text", { class: "s", x: 0, y: 15, "text-anchor": "middle" }, g); s.textContent = n.s || "";
    g.addEventListener("click", (e) => { e.stopPropagation(); select(n.id); });
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(n.id); } });
    g.addEventListener("mouseenter", () => { if (!flow) neighbours(n.id); });
    g.addEventListener("mouseleave", () => { if (!flow) applyFilter(); });
    nodeEls[n.id] = { g, box, n };
  });

  /* ── layout (re-run on every view frame) ─────────────────── */
  function layout(p = P) {
    plates.forEach(({ k, side: sd, top, tab, tabR, tabT }) => {
      const pad = 40;
      const a = proj(-pad, 0, k, p), b = proj(U + pad, 0, k, p), c = proj(U + pad, p.V, k, p), d = proj(-pad, p.V, k, p);
      top.setAttribute("points", [a, b, c, d].map((q) => q.join(",")).join(" "));
      const th = 10 * Math.min(1, p.dx * 1.2); // plate thickness only in stack view
      const d2 = [d[0], d[1] + th], c2 = [c[0], c[1] + th];
      sd.setAttribute("points", [d, c, c2, d2].map((q) => q.join(",")).join(" "));
      sd.setAttribute("opacity", th > 1 ? 0.55 : 0);
      const tw = tabT.getComputedTextLength ? tabT.getComputedTextLength() + 22 : 160;
      tabR.setAttribute("width", tw);
      tabT.setAttribute("x", 11); tabT.setAttribute("y", 17);
    });
    placeTabs(p);
    const depth = Math.max(0, Math.min(1, p.lift / VIEWS.stack.lift)); // feet + stems only in the stack view
    M.nodes.forEach((n) => {
      const [x, y] = nodePos(n, p); n.sx = x; n.sy = y;
      const g = nodeEls[n.id].g;
      g.setAttribute("transform", `translate(${x},${y})`);
      g.querySelectorAll(".foot,.stem").forEach((e) => e.setAttribute("opacity", depth));
    });
    edges.forEach((e) => {
      const a = byId[e.f], b = byId[e.t]; if (!a || !b) return;
      const same = a.lane === b.lane;
      let x1 = a.sx, y1 = a.sy, x2 = b.sx, y2 = b.sy, d;
      if (same) {
        const s = Math.sign(x2 - x1) || 1;
        x1 += s * CARD_W / 2; x2 -= s * CARD_W / 2;
        const bend = e.dash ? -34 : 0;
        d = `M${x1},${y1} C${(x1 + x2) / 2},${y1 + bend} ${(x1 + x2) / 2},${y2 + bend} ${x2},${y2}`;
      } else {
        const down = y2 > y1 ? 1 : -1;
        y1 += down * CARD_H / 2; y2 -= down * CARD_H / 2;
        const off = e.dash ? 18 : 0; x1 += off; x2 += off;
        const my = (y1 + y2) / 2;
        d = `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`;
      }
      e.p.setAttribute("d", d);
      if (e.lt) { const L = e.p.getTotalLength(); const m = e.p.getPointAtLength(L / 2); e.lt.setAttribute("x", m.x + 6); e.lt.setAttribute("y", m.y - 5); }
    });
    extent = sceneBox();
    drawMini();
  }
  // Each layer's label rides along its plate and stays at the left edge of the
  // view, so a close-up never loses which layer a box belongs to.
  function placeTabs(p = P) {
    plates.forEach(({ k, tab, tabR }) => {
      const w = +tabR.getAttribute("width") || 160;
      let u = -40;
      if (cam) u = Math.min(U - w, Math.max(-40, cam.x + 14 * cam.w / Math.max(1, svg.clientWidth) - p.ox));
      const [x, y] = proj(u, 0, k, p);
      tab.setAttribute("transform", `translate(${x + 8},${y - 32})`);
    });
  }
  function sceneBox() {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    plates.forEach(({ k }) => [proj(-60, 0, k), proj(U + 60, 0, k), proj(U + 60, P.V, k), proj(-60, P.V, k)].forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }));
    return { x: x0 - 20, y: y0 - 70, w: x1 - x0 + 40, h: y1 - y0 + 110 };
  }

  /* ── camera ──────────────────────────────────────────────── */
  let extent = null, cam = null, camAnim = null;
  function setCam(c) { cam = c; svg.setAttribute("viewBox", `${c.x} ${c.y} ${c.w} ${c.h}`); placeTabs(); drawMiniFrame(); }
  function camTo(target, ms = 900) {
    if (reduce || !cam) { setCam(target); return; }
    const from = { ...cam }, t0 = performance.now();
    cancelAnimationFrame(camAnim);
    const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
    const tick = (now) => {
      const t = Math.min(1, (now - t0) / ms), e = ease(t);
      setCam({ x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e, w: from.w + (target.w - from.w) * e, h: from.h + (target.h - from.h) * e });
      if (t < 1) camAnim = requestAnimationFrame(tick);
    };
    camAnim = requestAnimationFrame(tick);
  }
  function fitAspect(b) {
    const r = svg.clientWidth / Math.max(1, svg.clientHeight);
    let { x, y, w, h } = b;
    if (w / h > r) { const nh = w / r; y -= (nh - h) / 2; h = nh; } else { const nw = h * r; x -= (nw - w) / 2; w = nw; }
    return { x, y, w, h };
  }
  function overview(ms) { camTo(fitAspect(extent), ms); }
  function focus(ids, ms) {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    ids.forEach((id) => { const n = byId[id]; if (!n) return; x0 = Math.min(x0, n.sx - CARD_W); x1 = Math.max(x1, n.sx + CARD_W); y0 = Math.min(y0, n.sy - CARD_H * 2.2); y1 = Math.max(y1, n.sy + CARD_H * 2.2); });
    const minW = 820;
    if (x1 - x0 < minW) { const c = (x0 + x1) / 2; x0 = c - minW / 2; x1 = c + minW / 2; }
    camTo(fitAspect({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 }), ms);
  }
  // wheel zoom + drag pan
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const pt = toScene(e.clientX, e.clientY), f = Math.exp(e.deltaY * 0.0012);
    const w = Math.min(extent.w * 1.6, Math.max(300, cam.w * f)), h = w * cam.h / cam.w;
    setCam({ x: pt.x - (pt.x - cam.x) * (w / cam.w), y: pt.y - (pt.y - cam.y) * (h / cam.h), w, h });
  }, { passive: false });
  let drag = null;
  svg.addEventListener("pointerdown", (e) => { if (e.target.closest(".node")) return; drag = { x: e.clientX, y: e.clientY, c: { ...cam } }; svg.setPointerCapture(e.pointerId); svg.classList.add("grab"); });
  svg.addEventListener("pointermove", (e) => { if (!drag) return; const s = cam.w / svg.clientWidth; setCam({ ...drag.c, x: drag.c.x - (e.clientX - drag.x) * s, y: drag.c.y - (e.clientY - drag.y) * s }); });
  svg.addEventListener("pointerup", () => { drag = null; svg.classList.remove("grab"); });
  function toScene(cx, cy) { const r = svg.getBoundingClientRect(); return { x: cam.x + (cx - r.left) / r.width * cam.w, y: cam.y + (cy - r.top) / r.height * cam.h }; }

  /* ── minimap ─────────────────────────────────────────────── */
  let miniFrame = null;
  function drawMini() {
    if (!mini) return;
    mini.innerHTML = "";
    const m = (t, a) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); mini.appendChild(e); return e; };
    mini.setAttribute("viewBox", `${extent.x} ${extent.y} ${extent.w} ${extent.h}`);
    plates.forEach(({ l, k }) => {
      const pts = [proj(-40, 0, k), proj(U + 40, 0, k), proj(U + 40, P.V, k), proj(-40, P.V, k)];
      m("polygon", { points: pts.map((q) => q.join(",")).join(" "), fill: `var(${l.color})`, opacity: ".35" });
    });
    M.nodes.forEach((n) => m("rect", { x: n.sx - 40, y: n.sy - 12, width: 80, height: 24, rx: 6, fill: `var(${M.lanes[laneIdx[n.lane]].color})`, opacity: ".9", "data-id": n.id }));
    miniFrame = m("rect", { class: "mini-frame", fill: "none", "stroke-width": extent.w / 160 });
    drawMiniFrame();
  }
  function drawMiniFrame() { if (!miniFrame || !cam) return; ["x", "y"].forEach((k) => miniFrame.setAttribute(k, cam[k])); miniFrame.setAttribute("width", cam.w); miniFrame.setAttribute("height", cam.h); }
  if (mini) mini.addEventListener("click", (e) => {
    const r = mini.getBoundingClientRect();
    const x = extent.x + (e.clientX - r.left) / r.width * extent.w, y = extent.y + (e.clientY - r.top) / r.height * extent.h;
    camTo({ ...cam, x: x - cam.w / 2, y: y - cam.h / 2 }, 500);
  });

  /* ── selection / filters ─────────────────────────────────── */
  function select(id) {
    const n = byId[id], lane = M.lanes[laneIdx[n.lane]];
    Object.values(nodeEls).forEach((x) => x.g.classList.remove("sel")); nodeEls[id].g.classList.add("sel");
    const ins = M.edges.filter((e) => e[1] === id).map((e) => byId[e[0]].t + (e[2] ? ` · ${e[2]}` : ""));
    const outs = M.edges.filter((e) => e[0] === id).map((e) => byId[e[1]].t + (e[2] ? ` · ${e[2]}` : ""));
    side.innerHTML = `
      <div class="side-head" style="--lc:var(${lane.color})"><span class="side-lane">${esc(lane.icon || "")} ${esc(lane.label)}</span>
      <h2>${esc(n.t)}</h2><div class="side-sub">${esc(n.s || "")}</div>
      <span class="badge b-${n.status}">${esc(n.status === "fault" ? "open fault" : n.status)}</span></div>
      <div class="kv"><b>Role</b>${fmt(n.role || n.s)}</div>
      ${n.in ? `<div class="kv"><b>Receives</b>${fmt(n.in)}</div>` : ""}${n.out ? `<div class="kv"><b>Sends</b>${fmt(n.out)}</div>` : ""}
      ${ins.length ? `<div class="kv"><b>From</b>${ins.map(esc).join("<br>")}</div>` : ""}
      ${outs.length ? `<div class="kv"><b>To</b>${outs.map(esc).join("<br>")}</div>` : ""}
      ${n.numbers ? `<div class="kv"><b>Numbers</b>${n.numbers.map(fmt).join("<br>")}</div>` : ""}
      ${n.faults ? `<div class="kv warn"><b>Open / notes</b>${n.faults.map(fmt).join("<br><br>")}</div>` : ""}
      ${n.files ? `<div class="kv"><b>Code</b>${n.files.map((f) => `<code>${esc(f)}</code>`).join("<br>")}</div>` : ""}
      <button class="ghost" id="focusBtn">Focus on this box</button>`;
    const fb = $("focusBtn"); if (fb) fb.onclick = () => focus([id, ...M.edges.filter((e) => e[0] === id || e[1] === id).map((e) => (e[0] === id ? e[1] : e[0]))]);
    neighbours(id);
  }
  function neighbours(id) {
    const keep = new Set([id]); edges.forEach((e) => { if (e.f === id) keep.add(e.t); if (e.t === id) keep.add(e.f); });
    Object.entries(nodeEls).forEach(([k, x]) => x.g.classList.toggle("dim", !keep.has(k)));
    edges.forEach((e) => { const on = e.f === id || e.t === id; e.p.classList.toggle("dim", !on); e.lt && e.lt.classList.toggle("dim", !on); });
    plates.forEach((pl) => pl.top.parentNode.classList.toggle("dim", false));
  }
  let filter = "all";
  const fbox = $("filters");
  (M.filters || [["all", "All"]]).forEach(([k, lab, test]) => {
    const b = document.createElement("button"); b.className = "chip" + (k === "all" ? " on" : ""); b.textContent = lab;
    b.onclick = () => { filter = k; [...fbox.children].forEach((c) => c.classList.toggle("on", c === b)); stopFlow(); applyFilter(); };
    if (fbox) fbox.appendChild(b);
  });
  function passes(n) { const f = (M.filters || []).find((x) => x[0] === filter); return !f || !f[2] || f[2](n); }
  function applyFilter() {
    clearHot();
    M.nodes.forEach((n) => nodeEls[n.id].g.classList.toggle("dim", !passes(n)));
    edges.forEach((e) => { const on = passes(byId[e.f]) && passes(byId[e.t]); e.p.classList.toggle("dim", !on); e.lt && e.lt.classList.toggle("dim", !on); });
  }
  function clearHot() {
    M.nodes.forEach((n) => nodeEls[n.id].g.classList.remove("hot"));
    edges.forEach((e) => { e.p.classList.remove("hot"); e.p.setAttribute("marker-end", "url(#arr)"); e.lt && e.lt.classList.remove("hot"); });
    gFx.innerHTML = ""; comets = [];
  }

  /* ── flows as a slideshow ────────────────────────────────── */
  const sel = $("flowSel"), slide = $("slide");
  Object.entries(M.flows).forEach(([k, f]) => { const o = document.createElement("option"); o.value = k; o.textContent = f.name; sel.appendChild(o); });
  let flow = null, step = 0, playing = false, timer = null, comets = [];
  function showStep() {
    const f = M.flows[flow], s = f.steps[step], on = new Set(s.n), hotE = new Set(s.e.map(([a, b]) => a + ">" + b));
    clearHot();
    M.nodes.forEach((n) => { const x = nodeEls[n.id].g; x.classList.toggle("dim", !on.has(n.id)); x.classList.toggle("hot", on.has(n.id)); });
    edges.forEach((e) => {
      const h = hotE.has(e.f + ">" + e.t);
      e.p.classList.toggle("hot", h); e.p.classList.toggle("dim", !h); e.p.setAttribute("marker-end", h ? "url(#arrhot)" : "url(#arr)");
      if (e.lt) { e.lt.classList.toggle("hot", h); e.lt.classList.toggle("dim", !h); }
      if (h) comets.push({ e, t0: performance.now() + comets.length * 260, parts: [0, 1, 2, 3].map((i) => el("circle", { class: "comet", r: 6 - i * 1.2, opacity: 1 - i * 0.22 }, gFx)) });
    });
    focus(s.n.concat(...s.e.map(([a, b]) => [a, b])), 1000);
    // slide card
    slide.classList.remove("in"); void slide.offsetWidth;
    slide.innerHTML = `<div class="slide-top"><span>${esc(f.name)}</span><span>${step + 1} / ${f.steps.length}</span></div>
      <div class="slide-body">${s.c}</div>
      <div class="slide-dots">${f.steps.map((_, i) => `<i class="${i === step ? "on" : i < step ? "done" : ""}" data-i="${i}"></i>`).join("")}</div>`;
    slide.querySelectorAll(".slide-dots i").forEach((d) => (d.onclick = () => { step = +d.dataset.i; showStep(); }));
    slide.classList.add("in", "show");
  }
  function animateComets(now) {
    comets.forEach((c) => {
      const L = c.e.p.getTotalLength(); if (!L) return;
      const dur = Math.max(900, L * 2.2), t = ((now - c.t0) % (dur + 500)) / dur;
      c.parts.forEach((p, i) => {
        const tt = t - i * 0.035;
        if (tt < 0 || tt > 1 || now < c.t0) { p.setAttribute("opacity", 0); return; }
        const q = c.e.p.getPointAtLength(tt * L); p.setAttribute("cx", q.x); p.setAttribute("cy", q.y); p.setAttribute("opacity", 1 - i * 0.24);
      });
    });
    requestAnimationFrame(animateComets);
  }
  if (!reduce) requestAnimationFrame(animateComets);
  function stopFlow() { playing = false; clearInterval(timer); $("play").textContent = "▶ Play"; }
  function endFlow() { stopFlow(); flow = null; sel.value = ""; slide.classList.remove("in", "show"); applyFilter(); overview(800); }
  sel.onchange = () => { stopFlow(); flow = sel.value || null; step = 0; if (flow) showStep(); else endFlow(); };
  $("next").onclick = () => { if (!flow) { sel.selectedIndex = 1; sel.onchange(); return; } if (step < M.flows[flow].steps.length - 1) { step++; showStep(); } };
  $("prev").onclick = () => { if (!flow) return; if (step > 0) { step--; showStep(); } };
  $("play").onclick = () => {
    if (playing) { stopFlow(); return; }
    if (!flow) { sel.selectedIndex = 1; sel.onchange(); }
    playing = true; $("play").textContent = "❚❚ Pause";
    timer = setInterval(() => { const f = M.flows[flow]; if (step >= f.steps.length - 1) { stopFlow(); return; } step++; showStep(); }, 4200);
  };
  $("overview").onclick = () => { if (flow) endFlow(); else overview(700); };
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input,select,textarea")) return;
    if (e.key === "ArrowRight") $("next").click(); else if (e.key === "ArrowLeft") $("prev").click(); else if (e.key === "Escape") endFlow();
  });

  /* ── view switch: stack <-> flat (animated) ─────────────── */
  function morph(to) {
    const from = { ...P }, target = VIEWS[to], t0 = performance.now(), ms = reduce ? 0 : 750;
    viewName = to; $("viewToggle").textContent = to === "stack" ? "Flat view" : "Stacked view";
    const tick = (now) => {
      const t = ms ? Math.min(1, (now - t0) / ms) : 1, e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      for (const k in target) P[k] = from[k] + (target[k] - from[k]) * e;
      layout(); if (!flow) setCam(fitAspect(extent));
      if (t < 1) requestAnimationFrame(tick); else if (flow) showStep();
    };
    requestAnimationFrame(tick);
  }
  $("viewToggle").onclick = () => morph(viewName === "stack" ? "flat" : "stack");
  svg.addEventListener("click", () => { if (!flow) { Object.values(nodeEls).forEach((x) => x.g.classList.remove("sel")); applyFilter(); } });

  /* ── boot ────────────────────────────────────────────────── */
  layout(); setCam(fitAspect(extent));
  addEventListener("resize", () => { if (!flow) setCam(fitAspect(extent)); });
  window.ArchMap = { select, focus, overview, morph };
})();
