/**
 * EMITTER CONTRACT — the backend side of the card event stream.
 *
 * specs/der-ground-truth/ REQ-19, task T27. Gate GT-G6.
 *
 * This suite has TWO jobs and they are deliberately different in kind:
 *
 *   1. SELF-TEST the validator (E1..E5 each fire on a crafted stream, and a
 *      conformant stream produces nothing). A validator that cannot fail is
 *      worth nothing — this is the same anti-vacuity rule the store invariant
 *      suite carries (REQ-6, T12).
 *
 *   2. MEASURE the real captured traces and RECORD the verdict. Per REQ-19 AC3
 *      this measurement is the deliverable: it explains why the reducer suite
 *      is green while the card renders out of order. The measurement asserts
 *      the CURRENT, RECORDED state — when the emitter is fixed (T28/T29) these
 *      expectations change to zero and the change is the proof of the fix.
 *
 * Nothing here renders anything. No React, no hook, no app, no dev mode.
 */
import { validateTrace, formatReport, type CardFrame } from "@/lib/cards/emitterContract"
import { ALL_TRACES, TRACE_WEBSEARCH, TRACE_WEBSEARCH_WITH_GRAFT, TRACE_CODE_TASK } from "../fixtures/cardTraces"

const rulesIn = (frames: CardFrame[]) => new Set(validateTrace("t", frames).findings.map((f) => f.rule))

describe("emitter contract — validator self-test (it must be able to fail)", () => {
  it("a conformant stream produces no findings at all", () => {
    const clean: CardFrame[] = [
      {
        type: "task:start",
        card_id: "c1",
        conversation_id: "conv-x",
        steps: [
          { id: "s1", description: "one", status: "pending", stepNumber: 1 },
          { id: "s2", description: "two", status: "pending", stepNumber: 2 },
        ],
      },
      { type: "task:progress", card_id: "c1", conversation_id: "conv-x", phase: "searching", phase_sequence: 1, step_number: 3 },
      { type: "task:done", card_id: "c1", conversation_id: "conv-x" },
    ]
    const r = validateTrace("clean", clean)
    expect(r.findings).toEqual([])
    expect(r.violations).toBe(0)
  })

  it("E1 fires when a planner row has no ordering key", () => {
    expect(
      rulesIn([
        { type: "task:start", card_id: "c1", steps: [{ id: "s1", description: "x" }] },
        { type: "task:done", card_id: "c1" },
      ]),
    ).toContain("E1")
  })

  it("E2 fires when two distinct rows share an ordering key", () => {
    expect(
      rulesIn([
        {
          type: "task:start",
          card_id: "c1",
          steps: [
            { id: "s1", description: "x", stepNumber: 1 },
            { id: "s2", description: "y", stepNumber: 1 },
          ],
        },
        { type: "task:done", card_id: "c1" },
      ]),
    ).toContain("E2")
  })

  it("E3 fires on a started card that never terminates", () => {
    expect(rulesIn([{ type: "task:start", card_id: "c1", steps: [{ id: "s1", stepNumber: 1 }] }])).toContain("E3")
  })

  it("E3 fires on a card that terminates twice", () => {
    expect(
      rulesIn([
        { type: "task:start", card_id: "c1", steps: [{ id: "s1", stepNumber: 1 }] },
        { type: "task:done", card_id: "c1" },
        { type: "task:fail", card_id: "c1" },
      ]),
    ).toContain("E3")
  })

  it("E4 fires when phase and phase_sequence do not travel together", () => {
    expect(rulesIn([{ type: "task:progress", card_id: "c1", phase: "searching" }])).toContain("E4")
    expect(rulesIn([{ type: "task:progress", card_id: "c1", phase_sequence: 2 }])).toContain("E4")
  })

  it("E5 fires when a phase opens a row with no key relative to planner rows", () => {
    expect(
      rulesIn([{ type: "task:progress", card_id: "c1", phase: "searching", phase_sequence: 1 }]),
    ).toContain("E5")
  })
})

describe("emitter contract — MEASUREMENT of the real captured traces (REQ-19 AC3)", () => {
  it("records the verdict for every captured trace", () => {
    const report = ALL_TRACES.map(({ name, frames }) => formatReport(validateTrace(name, frames))).join("\n\n")
    // The measurement IS the deliverable — surface it in the run output so the
    // gate GT-G6 evidence can be copied into specs/der-ground-truth/tasks.md.
    // eslint-disable-next-line no-console
    console.log("\n===== EMITTER CONTRACT REPORT =====\n" + report + "\n===================================\n")
    expect(report.length).toBeGreaterThan(0)
  })

  it("VERDICT: the websearch trace violates the emitter contract", () => {
    const r = validateTrace("conv-49 websearch", TRACE_WEBSEARCH)
    // Recorded state 2026-08-23. This is NOT an aspiration — it is the measured
    // fact that explains the green-suite/broken-card gap. T28/T29 drive it to 0.
    expect(r.violations).toBeGreaterThan(0)

    const rules = new Set(r.findings.map((f) => f.rule))
    // E1: the planner's anchor row arrives with no ordering key.
    expect(rules).toContain("E1")
    // E5: every crawl phase opens a row that cannot be placed among planner rows.
    expect(rules).toContain("E5")
  })

  it("VERDICT: the graft trace collides two distinct rows on one ordering key", () => {
    const r = validateTrace("conv-49 + graft", TRACE_WEBSEARCH_WITH_GRAFT)
    const e2 = r.findings.filter((f) => f.rule === "E2")
    // The C6 fixture gives BOTH `r1` and `r1_s1` stepNumber 1 and is labelled
    // "real payload shape". With a tie, render order falls to insertion accident
    // — which is exactly why C6 passes today and the live card does not.
    expect(e2.length).toBeGreaterThan(0)
    expect(e2[0].message).toMatch(/shared by 2 distinct rows/)
  })

  it("VERDICT: even the non-crawl code task emits an unkeyed row", () => {
    const r = validateTrace("conv-code implement", TRACE_CODE_TASK)
    // The defect is NOT crawl-specific. Two planner rows, neither keyed, plus a
    // terminal synthesis phase that cannot be ordered against them.
    expect(new Set(r.findings.map((f) => f.rule))).toContain("E1")
    expect(r.violations).toBeGreaterThan(0)
  })

  it("every captured trace does reach exactly one terminal frame (E3 holds)", () => {
    // The one part of the contract the emitter already satisfies. Pinning it
    // keeps a future change from regressing what currently works.
    for (const { name, frames } of ALL_TRACES) {
      const e3 = validateTrace(name, frames).findings.filter((f) => f.rule === "E3" && f.severity === "violation")
      expect(e3).toEqual([])
    }
  })
})
