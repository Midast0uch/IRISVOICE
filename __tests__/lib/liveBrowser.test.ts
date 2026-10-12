/**
 * lib/liveBrowser — the agent's live browser, kept per run.
 *
 * Two conversations can hold a session at once. One shared slot made the panel
 * flip between them, and a close that never arrived left a dead run behind.
 */
import { recordFrame, setControl, clearRun, clearAllRuns, getLiveRun } from "@/lib/liveBrowser"

const frame = (run_id: string, seq = 1) => ({ run_id, seq, bytes: `b-${run_id}-${seq}` })

afterEach(() => {
  for (const id of ["a", "b", "c", "d", "e", "f"]) clearRun(id)
})

describe("liveBrowser per-run store", () => {
  it("keeps two runs apart", () => {
    recordFrame(frame("a", 1))
    recordFrame(frame("b", 7))
    expect(getLiveRun("a")?.frame?.bytes).toBe("b-a-1")
    expect(getLiveRun("b")?.frame?.bytes).toBe("b-b-7")
    expect(getLiveRun("nope")).toBeNull()
  })

  it("getLiveRun() with no id returns the latest run", () => {
    recordFrame(frame("a"))
    recordFrame(frame("b"))
    expect(getLiveRun()?.runId).toBe("b")
    recordFrame(frame("a", 2))
    expect(getLiveRun()?.runId).toBe("a")
  })

  it("clearRun removes only its own run; the latest falls back to the newest left", () => {
    recordFrame(frame("a"))
    recordFrame(frame("b"))
    clearRun("b")
    expect(getLiveRun("b")).toBeNull()
    expect(getLiveRun("a")).not.toBeNull()
    expect(getLiveRun()?.runId).toBe("a")
    clearRun("a")
    expect(getLiveRun()).toBeNull()
  })

  it("is bounded to 4 runs - the least recently active is dropped", () => {
    for (const id of ["a", "b", "c", "d"]) recordFrame(frame(id))
    recordFrame(frame("a", 2)) // a is active again, so b is now the oldest
    recordFrame(frame("e"))
    expect(getLiveRun("b")).toBeNull()
    for (const id of ["a", "c", "d", "e"]) expect(getLiveRun(id)).not.toBeNull()
    expect(getLiveRun()?.runId).toBe("e")
  })

  it("setControl changes only its run and keeps snapshots stable otherwise", () => {
    recordFrame(frame("a"))
    recordFrame(frame("b"))
    const before = getLiveRun("a")
    expect(getLiveRun("a")).toBe(before) // referentially stable between changes
    setControl("b", true)
    expect(getLiveRun("a")).toBe(before)
    expect(getLiveRun("a")?.control).toBe(false)
    expect(getLiveRun("b")?.control).toBe(true)
  })

  it("ignores frames with no run_id", () => {
    recordFrame({ seq: 1 })
    expect(getLiveRun()).toBeNull()
  })

  it("a reconnect drops every run - a dead session's frame does not stay on screen", () => {
    // Live 2026-10-12: after a backend restart the panel kept showing the gone
    // session's last frame with a Take control button that did nothing.
    recordFrame(frame("a"))
    recordFrame(frame("b"))
    clearAllRuns()
    expect(getLiveRun()).toBeNull()
    expect(getLiveRun("a")).toBeNull()
    recordFrame(frame("b", 2)) // the backend resends a still-live run's frame
    expect(getLiveRun()?.runId).toBe("b")
  })
})
