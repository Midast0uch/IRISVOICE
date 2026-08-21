/**
 * REPURPOSED 2026-08-21 — cli-workspace-unification T2 (REQ-1 AC3), resolving
 * pre-existing debt (pin_c01534199cdb item A1). CALLED OUT, not silent.
 *
 * HISTORY: this suite used to render <TerminalSlideOver> directly and assert
 * its label. That drifted when the component became the fused output-only
 * panel (label changed), and then T2 removed TerminalSlideOver from the
 * developer-mode layout ENTIRELY (decision locked 2026-08-21, superseding
 * task-card-v2 REQ-13 for dev mode) — all shell output streams into the
 * unified chronological scroll instead.
 *
 * WHAT IT NOW PINS (the contract that actually matters post-T2):
 *   1. ABSENCE GUARD (REQ-1 AC3): chat-view must not import or render
 *      TerminalSlideOver / TerminalWidget — the slide-over stays dead.
 *   2. SCROLL BRIDGE (the load-bearing survivor): terminalScrollback remains
 *     the shell-output store feeding the unified scroll — commands append,
 *      output splits lines, bounds hold, and the question-answer funnel
 *      resolves exactly as the CLI expects.
 */

import { readFileSync } from "fs"
import { resolve } from "path"
import {
  appendCommand,
  appendOutput,
  appendSystem,
  getSnapshot,
  reset,
  resolveTerminalAnswer,
} from "@/components/terminal/terminalScrollback"

const CHAT_VIEW = resolve(__dirname, "../../../components/chat-view.tsx")

describe("REQ-1 AC3 — TerminalSlideOver stays removed from developer mode", () => {
  let source = ""
  beforeAll(() => {
    source = readFileSync(CHAT_VIEW, "utf8")
  })

  it("chat-view does not import TerminalSlideOver", () => {
    expect(source).not.toMatch(/import\s+\{[^}]*TerminalSlideOver[^}]*\}\s+from/)
  })

  it("chat-view does not render <TerminalSlideOver", () => {
    expect(source).not.toContain("<TerminalSlideOver")
  })

  it("chat-view does not import or render TerminalWidget", () => {
    expect(source).not.toMatch(/import\s+\{[^}]*TerminalWidget[^}]*\}\s+from/)
    expect(source).not.toContain("<TerminalWidget")
  })
})

describe("terminalScrollback — the surviving scroll bridge", () => {
  beforeEach(() => reset())

  it("commands append with $ prefix; output splits into lines; kinds are tagged", () => {
    appendCommand("pytest -q")
    appendOutput("line one\nline two\n\nline three")
    appendSystem("[shell] → terminal_input")

    const { lines } = getSnapshot()
    expect(lines.map((l) => l.kind)).toEqual([
      "command", "output", "output", "output", "system",
    ])
    expect(lines[0].text).toBe("$ pytest -q")
    expect(lines[1].text).toBe("line one")
    // Empty lines are dropped, never rendered as blank rows.
    expect(lines.some((l) => l.text.trim() === "")).toBe(false)
  })

  it("scrollback is bounded at 500 lines (quality check: bounded memory)", () => {
    for (let i = 0; i < 600; i++) appendOutput(`row ${i}`)
    const { lines } = getSnapshot()
    expect(lines.length).toBe(500)
    // Newest survive — the head was evicted, not the tail.
    expect(lines[lines.length - 1].text).toBe("row 599")
  })

  it("question-answer funnel: exact option match wins over numbering", () => {
    const pending = [
      { questionId: "q1", text: "Pick", options: ["yes", "no"], askedAt: Date.now() },
    ]
    expect(resolveTerminalAnswer("yes", pending)).toEqual({
      questionId: "q1",
      answer: "yes",
    })
    // Shell input is never hijacked by a pending question.
    expect(resolveTerminalAnswer(">ls", pending)).toBeNull()
  })
})
