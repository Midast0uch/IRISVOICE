/**
 * Vision Stage Simulator — scenarios (specs/vision-browser-stage REQ-12, T13).
 *
 * Each scenario is a timed script of REAL `iris:*` CustomEvents — the exact
 * contract production emits (useIRISWebSocket / useCrawlSSE re-dispatch these)
 * — so the simulator exercises the real frontend pipeline, never a parallel
 * mock renderer (REQ-12 AC2).
 *
 * REQ-12 AC1 scenario ids a–m map 1:1 to the sign-off checklist in
 * specs/vision-browser-stage/tasks.md.
 */

export interface ScenarioStep {
  /** Window CustomEvent name, e.g. "iris:crawler_started". */
  ev: string
  detail: Record<string, unknown>
  /** ms after scenario start. */
  atMs: number
}

export interface Scenario {
  id: string
  label: string
  /** What the user should SEE — rendered next to the run button + persisted
   * to localStorage for sign-off (REQ-12 AC4). */
  expect: string
  /** Extra setup instruction shown before running. */
  setup?: string
  steps: ScenarioStep[]
}

const START = { type: "crawler_started", source: "vision-stage-simulator" }

/**
 * Real pages for scenarios whose effects must be SEEN in the reading surface
 * (user feedback round 2: synthetic example.com URLs rendered as missing
 * captures / 404s). Events declare capture_available:false so the
 * live-reading tab takes the PROXY path (useActiveFrameSrc: no provenance ->
 * /api/browser/proxy?url=...) and loads the LIVE site. Internet required.
 */
const REAL_PAGES = [
  { url: "https://en.wikipedia.org/wiki/Mechanical_keyboard", title: "Mechanical keyboard — Wikipedia" },
  { url: "https://en.wikipedia.org/wiki/Keyboard_technology", title: "Keyboard technology — Wikipedia" },
  { url: "https://en.wikipedia.org/wiki/Web_scraping", title: "Web scraping — Wikipedia" },
  { url: "https://example.com", title: "Example Domain" },
  { url: "https://en.wikipedia.org/wiki/Hexagonal_tiling", title: "Hexagonal tiling — Wikipedia" },
]

export const SCENARIOS: Scenario[] = [
  {
    id: "a",
    label: "a · Crawl full lifecycle",
    expect:
      "dim stream + orb materialises (loading) → bloom outward (dispersing, first page) → shutter cadence with per-page kicks (crawling) → settle ring fades (complete)",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "best mechanical keyboards 2026", url_count: 4 }, atMs: 0 },
      { ev: "iris:crawler_page_fetched", detail: { url: REAL_PAGES[0].url, title: REAL_PAGES[0].title, page_number: 1, total: 4, host: "en.wikipedia.org", job_id: "sim-a", capture_available: false }, atMs: 1400 },
      { ev: "iris:crawler_page_fetched", detail: { url: REAL_PAGES[1].url, title: REAL_PAGES[1].title, page_number: 2, total: 4, host: "en.wikipedia.org", job_id: "sim-a", capture_available: false }, atMs: 3000 },
      { ev: "iris:crawler_page_fetched", detail: { url: REAL_PAGES[2].url, title: REAL_PAGES[2].title, page_number: 3, total: 4, host: "en.wikipedia.org", job_id: "sim-a", capture_available: false }, atMs: 4600 },
      { ev: "iris:crawler_page_fetched", detail: { url: REAL_PAGES[3].url, title: REAL_PAGES[3].title, page_number: 4, total: 4, host: "example.com", job_id: "sim-a", capture_available: false }, atMs: 6200 },
      { ev: "iris:crawler_complete", detail: { summary: "4 sources read", page_count: 4 }, atMs: 7600 },
    ],
  },
  {
    id: "b",
    label: "b · Crawl error terminal",
    expect: "the border settles in AMBER and fades (error), auto-dismisses to idle",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "will fail midway", url_count: 3 }, atMs: 0 },
      { ev: "iris:crawler_page_fetched", detail: { url: "https://x.example.com", page_number: 1, total: 3, host: "x.example.com" }, atMs: 1200 },
      { ev: "iris:crawler_error", detail: { message: "run budget exhausted (simulated)" }, atMs: 2600 },
    ],
  },
  {
    id: "c",
    label: "c · Vision cursor CLICK",
    expect:
      "orb travels to the point (~620ms ease), tightens into the cursor, trail decays; one blink impulse rides the border",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "cursor click demo", url_count: 2 }, atMs: 0 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-c", url: "https://x.example.com", kind: "click", reason: "accept cookies", action_index: 1, total: 8, x: 0.72, y: 0.35, viewport_w: 1280, viewport_h: 720, escalated: false }, atMs: 900 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-c", url: "https://x.example.com", kind: "click", reason: "open pricing", action_index: 2, total: 8, x: 0.3, y: 0.62, viewport_w: 1280, viewport_h: 720, escalated: false }, atMs: 2400 },
      { ev: "iris:crawler_complete", detail: { summary: "done" }, atMs: 4200 },
    ],
  },
  {
    id: "d",
    label: "d · Vision cursor TYPE",
    expect: "same travel grammar at the type point; cursor holds between keystrokes",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "type demo", url_count: 1 }, atMs: 0 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-d", kind: "click", action_index: 1, total: 4, x: 0.5, y: 0.2, viewport_w: 1280, viewport_h: 720 }, atMs: 800 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-d", kind: "type", action_index: 2, total: 4, x: 0.5, y: 0.2, viewport_w: 1280, viewport_h: 720 }, atMs: 2000 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-d", kind: "type", action_index: 3, total: 4, x: 0.5, y: 0.2, viewport_w: 1280, viewport_h: 720 }, atMs: 3200 },
      { ev: "iris:crawler_complete", detail: {}, atMs: 4600 },
    ],
  },
  {
    id: "e",
    label: "e · Vision SCROLL (iframe mirror)",
    expect:
      "a REAL page loads in the panel (via proxy) and its content scrolls smoothly with each event; cursor HOLDS position (scroll carries no point)",
    setup:
      "Run this, then open Dashboard → Browser — the live-reading tab loads the real page through the proxy (internet required), and the scroll events mirror into it.",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "keyboard technology scroll demo", url_count: 1 }, atMs: 0 },
      { ev: "iris:crawler_page_fetched", detail: { url: REAL_PAGES[1].url, title: REAL_PAGES[1].title, page_number: 1, total: 1, host: "en.wikipedia.org", job_id: "sim-e", capture_available: false }, atMs: 400 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-e", kind: "scroll", action_index: 1, total: 5, scroll_y: 300, scroll_height: 8000 }, atMs: 2500 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-e", kind: "scroll", action_index: 2, total: 5, scroll_y: 900, scroll_height: 8000 }, atMs: 3700 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-e", kind: "scroll", action_index: 3, total: 5, scroll_y: 1600, scroll_height: 8000 }, atMs: 4900 },
      // No complete: stay active so you can watch the mirror at leisure.
    ],
  },
  {
    id: "f",
    label: "f · Escalation NOTICE beat",
    expect:
      "violet shift + aperture HOLDS open + scan brightens/doubles ≤1.6s, expanding ring once; throttled to 5s if re-fired",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "challenge wall ahead", url_count: 2 }, atMs: 0 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-f", kind: "navigate", action_index: 1, total: 6, escalated: true }, atMs: 1000 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-f", kind: "click", action_index: 2, total: 6, x: 0.45, y: 0.55, viewport_w: 1280, viewport_h: 720, escalated: true }, atMs: 1800 },
      { ev: "iris:crawler_complete", detail: {}, atMs: 4200 },
    ],
  },
  {
    id: "g",
    label: "g · Rapid multi-page cadence",
    expect:
      "ring lap speed RE-TIMES from the median page gap (geared down); particles never jump; the reading surface visibly navigates real pages per kick",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "rapid cadence", url_count: 6 }, atMs: 0 },
      ...[0, 1, 2, 3, 4, 5].map((i) => ({
        ev: "iris:crawler_page_fetched",
        detail: {
          url: REAL_PAGES[i % REAL_PAGES.length].url,
          title: REAL_PAGES[i % REAL_PAGES.length].title,
          page_number: i + 1,
          total: 6,
          host: new URL(REAL_PAGES[i % REAL_PAGES.length].url).host,
          job_id: "sim-g",
          capture_available: false,
        },
        atMs: 800 + i * 1000,
      })),
      { ev: "iris:crawler_complete", detail: {}, atMs: 7600 },
    ],
  },
  {
    id: "h",
    label: "h · Lifecycle chip transitions",
    expect:
      "chip: VISION SPAWNING (amber pulse) → WARM (emerald) → ERROR (red, hover shows reason); disappears on cold",
    steps: [
      { ev: "iris:vision_status", detail: { status: "lifecycle", state: "spawning", trigger: "search-scoped" }, atMs: 0 },
      { ev: "iris:vision_status", detail: { status: "lifecycle", state: "warm", trigger: "search-scoped" }, atMs: 2200 },
      { ev: "iris:vision_status", detail: { status: "lifecycle", state: "error", reason: "no VL model fits free VRAM (simulated)", trigger: "lazy-call" }, atMs: 4400 },
      { ev: "iris:vision_status", detail: { status: "lifecycle", state: "cold", reason: "idle timeout" }, atMs: 7000 },
    ],
  },
  {
    id: "i",
    label: "i · Ambient tier (panel CLOSED)",
    expect:
      "with the browser panel CLOSED: compact orb ring + status line near screen bottom; with panel OPEN: minimal dot only",
    setup: "Run ONCE with the dashboard wing closed, once with it open on Browser.",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "ambient visibility demo", url_count: 3 }, atMs: 0 },
      { ev: "iris:crawler_page_fetched", detail: { url: "https://i.example.com", page_number: 1, total: 3, host: "i.example.com" }, atMs: 1500 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-i", kind: "scroll", action_index: 1, total: 3, scroll_y: 500, scroll_height: 3000 }, atMs: 2800 },
      // Leave ACTIVE (no complete) so the tier stays up while you look.
    ],
  },
  {
    id: "j",
    label: "j · Mid-run mount backfill",
    expect:
      "after the run starts, OPEN the browser panel — the overlay must show the CURRENT state immediately (loading/crawling with correct counts), not idle",
    setup: "Run this, wait ~2s, THEN open Dashboard → Browser.",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "backfill demo", url_count: 5 }, atMs: 0 },
      { ev: "iris:crawler_page_fetched", detail: { url: REAL_PAGES[2].url, title: REAL_PAGES[2].title, page_number: 1, total: 5, host: "en.wikipedia.org", job_id: "sim-j", capture_available: false }, atMs: 800 },
      { ev: "iris:crawler_page_fetched", detail: { url: REAL_PAGES[3].url, title: REAL_PAGES[3].title, page_number: 2, total: 5, host: "example.com", job_id: "sim-j", capture_available: false }, atMs: 1600 },
      // No further events: the panel must seed from CrawlProvider, not wait.
    ],
  },
  {
    id: "k",
    label: "k · Fit-to-width reading surface",
    expect:
      "the 1600px-wide fixture SHRINKS to the frame width (whole page visible, no horizontal scrollbar); height scrolls",
    steps: [], // rendered specially by the page (embedded fixture frame)
  },
  {
    id: "l",
    label: "l · Hex-lattice SCAN",
    expect:
      "during sustained scroll actions: hex cells ignite in a traveling front around the border, biased toward the cursor side; fades within ~a lap when actions stop",
    setup: "Open the browser panel first. Watch the BORDER BAND closely.",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "hex scan demo", url_count: 2 }, atMs: 0 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-l", kind: "scroll", action_index: 1, total: 8, scroll_y: 200, scroll_height: 6000, x: 0.8, y: 0.5, viewport_w: 1280, viewport_h: 720 }, atMs: 900 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-l", kind: "scroll", action_index: 2, total: 8, scroll_y: 700, scroll_height: 6000, x: 0.8, y: 0.5, viewport_w: 1280, viewport_h: 720 }, atMs: 1700 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-l", kind: "scroll", action_index: 3, total: 8, scroll_y: 1200, scroll_height: 6000, x: 0.8, y: 0.5, viewport_w: 1280, viewport_h: 720 }, atMs: 2500 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-l", kind: "scroll", action_index: 4, total: 8, scroll_y: 1700, scroll_height: 6000, x: 0.8, y: 0.5, viewport_w: 1280, viewport_h: 720 }, atMs: 3300 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-l", kind: "scroll", action_index: 5, total: 8, scroll_y: 2200, scroll_height: 6000, x: 0.8, y: 0.5, viewport_w: 1280, viewport_h: 720 }, atMs: 4100 },
      { ev: "iris:crawler_vision_action", detail: { job_id: "sim-l", kind: "scroll", action_index: 6, total: 8, scroll_y: 2700, scroll_height: 6000, x: 0.8, y: 0.5, viewport_w: 1280, viewport_h: 720 }, atMs: 4900 },
      // Actions stop here: the lattice must fade over ~one lap.
    ],
  },
  {
    id: "m",
    label: "m · Live Reading surface",
    expect:
      "exactly ONE web tab ('live-reading') after 5 REAL pages (loaded via proxy); surface follows the latest; clicking a source row's 'view' pins it; LIVE pill resumes following",
    setup:
      "Have the chat wing open so you can see the plan card's source rows. Internet required — pages load live through the proxy. After the run: click a 'view' button, then press LIVE in the address bar.",
    steps: [
      { ev: "iris:crawler_started", detail: { ...START, query: "live reading demo", url_count: 5 }, atMs: 0 },
      ...REAL_PAGES.slice(0, 5).map((p, i) => ({
        ev: "iris:crawler_page_fetched",
        detail: {
          url: p.url,
          title: p.title,
          page_number: i + 1,
          total: 5,
          host: new URL(p.url).host,
          job_id: "sim-m",
          capture_available: false,
        },
        atMs: 900 + i * 1600,
      })),
      // Stays active so you can interact with the tab strip + sources.
    ],
  },
]

/**
 * Scenario k's fixture: a deliberately 1600px-wide fixed-layout page. Served
 * through the REAL pipeline this would arrive with the nonce-tagged scaler
 * injected by backend/proxy/view_agent.py; here the SAME scaler logic is
 * embedded so the demonstration needs zero backend (REQ-12 AC5). Live
 * verification against real captures happens in LV-3.
 */
export const WIDE_FIXTURE_HTML = `<!DOCTYPE html>
<html><head><style>
  body { margin: 0; font-family: monospace; background: #fff; }
  .page { width: 1600px; padding: 24px; box-sizing: border-box; }
  .row { display: flex; gap: 16px; margin-bottom: 16px; }
  .cell { flex: 1; height: 120px; background: #e8eef4; border: 1px solid #b8c4d0;
          display: flex; align-items: center; justify-content: center;
          font-size: 28px; color: #334; }
  h1 { font-size: 40px; margin: 0 0 20px 0; color: #223; }
</style></head>
<body><div class="page">
  <h1>WIDE FIXTURE — natural width 1600px</h1>
  <div class="row">${Array.from({ length: 4 }, (_, i) => `<div class="cell">COL ${i + 1}</div>`).join("")}</div>
  <div class="row">${Array.from({ length: 4 }, (_, i) => `<div class="cell">ROW 2 · ${i + 1}</div>`).join("")}</div>
  <div class="row">${Array.from({ length: 4 }, (_, i) => `<div class="cell">ROW 3 · ${i + 1}</div>`).join("")}</div>
  <p>If you can read all four columns without horizontal scrolling,
     fit-to-width is working.</p>
</div>
<script data-iris-scaler>
(function () {
  var pending = false;
  function fit() {
    pending = false;
    try {
      var de = document.documentElement;
      var w = Math.max(de.scrollWidth, document.body ? document.body.scrollWidth : 0);
      var target = window.innerWidth || de.clientWidth || 0;
      if (!w || !target) { return; }
      var s = w > target ? target / w : 1;
      de.style.transformOrigin = '0 0';
      de.style.transform = s < 1 ? 'scale(' + s + ')' : '';
      window.__irisScale = s;
    } catch (e) {}
  }
  function schedule() {
    if (pending) return;
    pending = true;
    try { requestAnimationFrame(fit); } catch (e) { fit(); }
  }
  window.addEventListener('resize', schedule);
  schedule();
})();
</script>
</body></html>`
