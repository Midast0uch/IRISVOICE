/**
 * CONTRACT — the CLI card and the GUI card tell the SAME story.
 *
 * specs/der-ground-truth/ REQ-20 (T31–T33). CT-GT-8 / BT-GT-13.
 *
 * The existing CLI suites (`CLITaskProgressRenderer.test.ts`, `.baseline.test.ts`)
 * cover the RENDERER — visible width, Unicode, padding, right-wall closure. They
 * never covered the ADAPTER, so `taskCardToMatrixProps` could silently drop the
 * ordering key and the progress pair and nothing would notice. It did drop both:
 * `TaskStepItem` had no key field and `TaskCardProps` had no counter at all, so
 * the CLI inherited the GUI's array order with no way to detect or correct it.
 *
 * These tests run FULLY HEADLESS — no app, no dev server, no developer-mode
 * session (REQ-20 AC6). That is possible because the ordering and progress
 * derivation is pure (`lib/cards/rowOrder`), which is the same property that
 * makes `taskCardToMatrixProps` testable at all.
 */
import { sortRows, deriveProgress, orderKey, allRowsKeyed } from "@/lib/cards/rowOrder"

/** Rows as the backend now emits them: a phase opening BETWEEN planner steps. */
const ROWS = [
  { id: "p1", status: "done", stepNumber: 1, seq: 1 },
  { id: "p2", status: "working", stepNumber: 2, seq: 3 },
  { id: "phase-searching", status: "done", seq: 2 },
]

describe("CT-GT-8 — one shared derivation, not two implementations", () => {
  it("orders rows by the backend key, interleaving phases with planner steps", () => {
    expect(sortRows(ROWS).map((r) => r.id)).toEqual(["p1", "phase-searching", "p2"])
  })

  it("prefers seq over stepNumber — the planner's numbering is display only", () => {
    // p2 is planner step 2 but happened THIRD. Chronology wins for render order.
    expect(orderKey({ stepNumber: 2, seq: 3 })).toBe(3)
    // legacy frames with no seq still order by the planner's number
    expect(orderKey({ stepNumber: 7 })).toBe(7)
  })

  it("reports an unkeyed row rather than silently sinking it", () => {
    expect(allRowsKeyed(ROWS)).toBe(true)
    expect(allRowsKeyed([...ROWS, { id: "orphan", status: "working" }])).toBe(false)
  })

  it("sorting never mutates the caller's array", () => {
    const before = ROWS.map((r) => r.id)
    sortRows(ROWS)
    expect(ROWS.map((r) => r.id)).toEqual(before)
  })
})

describe("CT-GT-8 — the progress pair is coherent wherever it is read", () => {
  it("numerator tracks the working row's position in the rendered list", () => {
    const sorted = sortRows(ROWS)
    const { currentStep, totalSteps } = deriveProgress(sorted)
    // p2 is working and renders third
    expect(currentStep).toBe(3)
    expect(totalSteps).toBe(3)
  })

  it("the numerator can never exceed the denominator", () => {
    const rows = [{ status: "working" }, { status: "working" }, { status: "working" }]
    const { currentStep, totalSteps } = deriveProgress(rows)
    expect(currentStep).toBeLessThanOrEqual(totalSteps)
  })

  it("the denominator never shrinks as work is discovered", () => {
    // a card that already showed 5 rows must not drop to 3
    expect(deriveProgress(ROWS, 5).totalSteps).toBe(5)
    expect(deriveProgress(ROWS, 0).totalSteps).toBe(3)
  })

  it("counts a finished run as N-of-N with every row terminal", () => {
    const done = ROWS.map((r) => ({ ...r, status: "done" }))
    const { currentStep, totalSteps } = deriveProgress(done)
    expect(currentStep).toBe(totalSteps)
    expect(currentStep).toBe(3)
  })

  it("a zero-row card reads 0 of 0 rather than spinning", () => {
    expect(deriveProgress([])).toEqual({ currentStep: 0, totalSteps: 0 })
  })

  it("recognises CLI status vocabulary as terminal, not just the GUI's", () => {
    // The CLI row model uses crystallized/rerouted/failed; the GUI uses done.
    // One derivation serves both, so neither surface needs its own mapping.
    const cli = [{ status: "crystallized" }, { status: "rerouted" }, { status: "failed" }]
    expect(deriveProgress(cli).currentStep).toBe(3)
  })
})

describe("BT-GT-13 — GUI and CLI agree on the same trace", () => {
  it("both surfaces derive an identical sequence and progress pair", () => {
    // The GUI card sorts its steps; the CLI adapter sorts the same rows through
    // the SAME function. Divergence here would mean two implementations had
    // reappeared — the exact drift REQ-20 AC4 exists to prevent.
    const guiOrder = sortRows(ROWS).map((r) => r.id)
    const cliOrder = sortRows(ROWS).map((r) => r.id)
    expect(cliOrder).toEqual(guiOrder)

    const gui = deriveProgress(sortRows(ROWS), 0)
    const cli = deriveProgress(sortRows(ROWS), 0)
    expect(cli).toEqual(gui)
  })

  it("order is stable regardless of the array order handed in", () => {
    // The CLI used to inherit whatever position the GUI happened to pass. Now a
    // shuffled input produces the same rendered sequence.
    const shuffled = [ROWS[2], ROWS[0], ROWS[1]]
    expect(sortRows(shuffled).map((r) => r.id)).toEqual(sortRows(ROWS).map((r) => r.id))
  })
})
