/**
 * T24 — guard tests for the REQ-17 mesh film.
 *
 * The film shipped on numeric verification plus live user sign-off, not on
 * automated tests. Canvas output cannot be meaningfully unit-tested, so these
 * are SOURCE guards in the same idiom as the REQ-14 CT-6/CT-7 non-interference
 * checks: they pin the handful of invariants whose violation is silent,
 * expensive to rediscover, and was actually hit during development.
 *
 * Each guard below corresponds to a real failure from the seven build
 * iterations — not a hypothetical.
 */
import { readFileSync } from "fs"
import { join } from "path"

const SRC = readFileSync(
  join(process.cwd(), "components/iris/browser/BrowserNavigationOverlay.tsx"),
  "utf8",
)

/** Body of a named function/const declaration, up to the next top-level one. */
function region(startMarker: string, endMarker: string): string {
  const a = SRC.indexOf(startMarker)
  expect(a).toBeGreaterThan(-1)
  const b = SRC.indexOf(endMarker, a)
  return SRC.slice(a, b > -1 ? b : undefined)
}

describe("mesh film — lattice invariants", () => {
  test("the mesh pitch is derived from meshR, never from the band's hexR", () => {
    // THE failure that made wall-sharing impossible. Cells were drawn at
    // 0.94x the pitch radius, so neighbouring vertices never coincided, 0% of
    // walls deduplicated, every cell kept a private boundary and growth could
    // not cross between them. Measured: 1.00*R -> 35% of walls shared;
    // 0.94*R -> 0%. If the pitch and the drawn radius ever disagree again the
    // film silently degrades to disconnected outlines.
    expect(SRC).toMatch(/const\s+mdx\s*=\s*Math\.sqrt\(3\)\s*\*\s*meshR/)
    expect(SRC).toMatch(/const\s+mdy\s*=\s*1\.5\s*\*\s*meshR/)
    expect(SRC).not.toMatch(/const\s+mdx\s*=\s*Math\.sqrt\(3\)\s*\*\s*hexR/)
  })

  test("walls are deduplicated on quantised endpoints", () => {
    // One edge object per SHARED wall is the whole mechanism; six edges per
    // cell would double-draw interior walls and let one copy grow while the
    // other was already drawn.
    expect(SRC).toContain("edgeAt")
    expect(SRC).toMatch(/const\s+q\s*=\s*\(v:\s*number\)\s*=>\s*Math\.round\(v\s*\*\s*10\)/)
  })
})

describe("mesh film — wave timing invariants", () => {
  test("MESH_WAVE_LIFE is DERIVED from every term that feeds arrival", () => {
    // A hand-set lifetime drifts out of step the moment any arrival term is
    // tuned, and the failure mode is waves retiring while walls they lit are
    // still mid-fade — those walls blank instantly. Arrival stacks contour
    // noise, patch jitter and patch spread on top of depth, so all three must
    // appear in the lifetime.
    const decl = region("const MESH_WAVE_LIFE", "\n/**")
    for (const term of [
      "MESH_CONTOUR_NOISE",
      "MESH_PATCH_JITTER",
      "MESH_PATCH_SPREAD",
      "MESH_WAVE_DRAW",
      "MESH_WAVE_HOLD",
      "MESH_WAVE_FADE",
    ]) {
      expect(decl).toContain(term)
    }
  })

  test("contour noise is present and non-trivial", () => {
    // Without it the front collapses as a rectangle: `depth` is distance to
    // the NEAREST EDGE, whose iso-contours are concentric rectangles. This is
    // the "square funnel". Measured front depth-spread: 0.008-0.018 without,
    // 0.043-0.046 with.
    const m = SRC.match(/const\s+MESH_CONTOUR_NOISE\s*=\s*([0-9.]+)/)
    expect(m).not.toBeNull()
    expect(Number(m![1])).toBeGreaterThan(0.05)
  })

  test("wave count is controlled by a launch throttle, not by eviction", () => {
    // Dropping a live wave from the buffer blanks every wall it still lit — a
    // visible pop. The cap exists only as a runaway backstop.
    expect(SRC).toContain("MESH_WAVE_MIN_GAP_MS")
    expect(SRC).toMatch(/sinceLast\s*>=\s*MESH_WAVE_MIN_GAP_MS/)
  })
})

describe("mesh film — gating", () => {
  test("renders nothing under prefers-reduced-motion (REQ-17 AC6)", () => {
    const fn = region("function drawHexMesh", "function draw(")
    expect(fn).toMatch(/if\s*\(reducedRef\.current\)\s*return/)
  })

  test("the activity gate accepts CRAWL states, not just vision actions", () => {
    // A crawl emits crawler_page_fetched, NOT crawler_vision_action. Gating on
    // vision actions alone silently disabled the film during the exact case it
    // exists for — the first iteration shipped that way and looked like a
    // no-op.
    const fn = region("function drawHexMesh", "function draw(")
    expect(fn).toContain('"crawling"')
    expect(fn).toContain('"loading"')
    expect(fn).toContain('"dispersing"')
  })
})

describe("mesh film — simulator/production parity (REQ-17 AC8)", () => {
  test("the enable switch is a persisted preference, not an iris:* event", () => {
    // The simulator's value came entirely from driving the SAME code path
    // production drives. A simulator-only event to toggle a visual would
    // reintroduce exactly the divergence the harness existed to prevent.
    expect(SRC).toContain("MESH_PREF_KEY")
    expect(SRC).toMatch(/localStorage\.getItem\(MESH_PREF_KEY\)/)
    // The pref-changed notification is a same-tab signal, NOT a crawler event.
    expect(SRC).toMatch(/MESH_PREF_EVENT\s*=\s*"iris:hex_mesh_pref"/)
    const fn = region("const read = () =>", "}, [])")
    expect(fn).not.toMatch(/crawler_/)
  })

  test("the film defaults ON — absent preference means enabled", () => {
    // Standard behavior, opt-out. A first run, a cleared profile or storage
    // being unavailable must all still show the film.
    expect(SRC).toMatch(/localStorage\.getItem\(MESH_PREF_KEY\)\s*!==\s*"0"/)
    expect(SRC).not.toMatch(/localStorage\.getItem\(MESH_PREF_KEY\)\s*===\s*"1"/)
  })
})
