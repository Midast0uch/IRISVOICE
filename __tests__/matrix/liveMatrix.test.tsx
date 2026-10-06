/**
 * Phase 4 DONE line: "A developer turn shows the prompt line, a live matrix
 * whose rows appear, run and fold as nodes do, and a rendered answer. It fits
 * the wing width with no sideways scroll, and a >cmd command shows as an EXEC
 * row." NOT THIS: personal-mode look changes, removing the ANSI export renderer.
 */
import React from "react"
import { render, screen, fireEvent } from "@testing-library/react"
import "@testing-library/jest-dom"
import { MatrixFrame } from "@/components/chat/matrix/LiveMatrix"
import { ShellRunEntry } from "@/components/chat/matrix/ShellRunEntry"
import { buildMatrix, foldLine, memoryLine, parentOf } from "@/components/chat/matrix/matrixModel"
import { taskCardToMatrixProps } from "@/components/chat/TaskCardEntry"
import { renderBlueprintCellMatrixCLI, type TaskCardProps } from "@/lib/cli/CLITaskProgressRenderer"
import { buildShellRuns, SHELL_QUIET_MS } from "@/lib/cli/shellRuns"
import { buildChatTimeline } from "@/lib/chatview-turn-timeline"
import { MarkdownMessage } from "@/components/chat/MarkdownMessage"
import type { TaskCard } from "@/hooks/useTaskProgress"
import type { TerminalLine } from "@/components/terminal/terminalScrollback"

const GLOW = "#00d4ff"

function card(steps: Array<Partial<TaskCard["steps"][number]> & { id: string; description: string; status: TaskCard["steps"][number]["status"] }>, extra: Partial<TaskCard> = {}): TaskCard {
  return {
    cardId: "card-1",
    conversationId: "conv-dev",
    isWorking: true,
    currentStep: 0,
    totalSteps: steps.length,
    planTitle: "Fix the router window test",
    steps: steps.map((s, i) => ({ seq: i + 1, ...s })),
    ...extra,
  } as TaskCard
}

const LIVE = card([
  { id: "n1", description: "read router.py 419-466", status: "done", toolName: "read_file", resultPreview: "48 ln" },
  { id: "n2", description: "pytest tests/unit/test_router.py", status: "error", toolName: "run_command", resultPreview: "1 failed", history: ["collected 12 items", "NameError: _RESERVE is not defined"] },
  { id: "n2_s1", description: "grep _RESERVE =", status: "working", toolName: "grep_files" },
  { id: "n3", description: "router.py", status: "pending", toolName: "edit_file" },
])

describe("matrix model", () => {
  it("groups a split child (<parent>_s<n>) into a 'looked closer' chamber right after its parent", () => {
    const m = buildMatrix(taskCardToMatrixProps(LIVE))
    expect(parentOf("n2_s1")).toBe("n2")
    expect(m.items.map((it) => (it.kind === "row" ? it.row.id : `chamber:${it.chamber.parentId}`))).toEqual(["n1", "n2", "chamber:n2", "n3"])
    expect(m.running).toBe(1)
    expect(m.failed).toBe(1)
  })

  it("speaks plain words: DONE / FAILED / STOPPED, never converged or crystallized", () => {
    const done = buildMatrix(taskCardToMatrixProps(card([{ id: "a", description: "x", status: "done" }], { isWorking: false })))
    expect(foldLine(done, false, "0:21").word).toBe("DONE")
    const failed = buildMatrix(taskCardToMatrixProps(card([{ id: "a", description: "x", status: "error" }], { isWorking: false })))
    expect(foldLine(failed, false, "0:03").word).toBe("FAILED")
    expect(foldLine(done, true, "0:03").word).toBe("STOPPED")
    const props: TaskCardProps = { objective: "o", steps: [], memoryEvents: [{ direction: "crystallize", engine: "episodic", detail: "skill" }] }
    expect(memoryLine(props)).toBeNull()
  })
})

describe("MatrixFrame — rows appear, run and fold", () => {
  it("renders every node as a row; the running row scans and the Xur rides the rail", () => {
    const { container } = render(<MatrixFrame matrix={taskCardToMatrixProps(LIVE)} glowColor={GLOW} working elapsedSec={31} thought="look closer" />)
    const rows = container.querySelectorAll("[data-row-id]")
    expect(Array.from(rows).map((r) => r.getAttribute("data-row-id"))).toEqual(["n1", "n2", "n2_s1", "n3"])
    const running = container.querySelector('[data-state="running"]')!
    expect(running.className).toContain("iris-mx-scan")
    expect(container.querySelector("[data-matrix-thk]")).toHaveTextContent("look closer")
    expect(container.querySelector('[data-matrix-chamber="n2"]')).toHaveTextContent("looked closer")
    expect(screen.getByText("0:31", { exact: false })).toBeInTheDocument()
  })

  it("opens a failed row's output by default; other rows stay closed", () => {
    const { container } = render(<MatrixFrame matrix={taskCardToMatrixProps(LIVE)} details={{ n2: { history: ["NameError: _RESERVE is not defined"] }, n1: { history: ["ok"] } }} glowColor={GLOW} working elapsedSec={1} />)
    const details = container.querySelectorAll("[data-matrix-detail]")
    expect(details).toHaveLength(1)
    expect(details[0]).toHaveTextContent("NameError")
  })

  it("folds a finished run to one line, and the line unfolds", () => {
    const settled = card([{ id: "a", description: "read", status: "done", toolName: "read_file" }, { id: "b", description: "test", status: "done", toolName: "run_command" }], { isWorking: false })
    const { container } = render(<MatrixFrame matrix={taskCardToMatrixProps(settled)} glowColor={GLOW} working={false} elapsedSec={21} />)
    expect(container.querySelector('[data-matrix="folded"]')).toHaveTextContent("✓ DONE")
    expect(container.querySelector('[data-matrix="folded"]')).toHaveTextContent("2 steps · 0:21")
    fireEvent.click(container.querySelector('[data-matrix="folded"] button')!)
    expect(container.querySelectorAll("[data-row-id]")).toHaveLength(2)
  })

  it("a settled chamber folds to one line that says it found it", () => {
    const c = card([
      { id: "n2", description: "pytest", status: "error", toolName: "run_command" },
      { id: "n2_s1", description: "grep", status: "done", toolName: "grep_files" },
      { id: "n3", description: "edit", status: "working", toolName: "edit_file" },
    ])
    const { container } = render(<MatrixFrame matrix={taskCardToMatrixProps(c)} glowColor={GLOW} working elapsedSec={5} />)
    const ch = container.querySelector('[data-matrix-chamber="n2"]')!
    expect(ch).toHaveTextContent("looked closer · found it")
    expect(ch.querySelectorAll("[data-row-id]")).toHaveLength(0)
  })

  it("fits the wing: no preformatted or sideways-scrolling block; long targets truncate", () => {
    const long = card([{ id: "a", description: "x".repeat(400), status: "working", toolName: "read_file" }])
    const { container } = render(<MatrixFrame matrix={taskCardToMatrixProps(long)} glowColor={GLOW} working elapsedSec={1} />)
    expect(container.querySelector("pre")).toBeNull()
    expect(container.innerHTML).not.toContain("whitespace-pre ")
    expect(container.innerHTML).not.toContain("overflow-x-auto")
    expect(container.querySelector("[data-row-id] .truncate")).not.toBeNull()
  })

  it("never shows engine words on screen", () => {
    const { container } = render(<MatrixFrame matrix={taskCardToMatrixProps(LIVE)} glowColor={GLOW} working elapsedSec={1} />)
    expect(container.textContent).not.toMatch(/sub-loop|converged|crystalliz|landmark/i)
  })
})

describe("parity: the GUI matrix and the ANSI export render the same run", () => {
  it("same rows, same order, same verbs; ANSI targets are the GUI targets (truncated)", () => {
    const props = taskCardToMatrixProps(LIVE)
    const ansi = renderBlueprintCellMatrixCLI(props, false).split("\n").filter((l) => /[○◎●✦]/.test(l))
    const gui = buildMatrix(props).flat
    expect(ansi).toHaveLength(gui.length)
    gui.forEach((row, i) => {
      expect(ansi[i]).toContain(row.verb)
      const shown = ansi[i].slice(ansi[i].indexOf(row.verb) + row.verb.length).replace(/[│\s]+$/, "").trim().replace(/…$/, "")
      expect(row.target.startsWith(shown)).toBe(true)
    })
  })
})

describe(">cmd as an EXEC row", () => {
  const line = (id: number, kind: TerminalLine["kind"], text: string, ts: number, extra: Partial<TerminalLine> = {}): TerminalLine => ({ id, kind, text, ts, ...extra })

  it("groups shell commands with their output; [exit N] fails; chat and system lines are skipped", () => {
    const runs = buildShellRuns([
      line(1, "command", "$ >git status", 1000, { conversationId: "c1" }),
      line(2, "system", "[shell] → terminal_input", 1001),
      line(3, "output", " M router.py", 1100),
      line(4, "output", "a reply mirrored from chat", 1101, { source: "chat" }),
      line(5, "command", "$ >pytest -q", 2000, { conversationId: "c1" }),
      line(6, "output", "1 failed", 2100),
      line(7, "output", "[exit 1]", 2101),
      line(8, "command", "$ /run fix it", 3000),
    ], 10_000)
    expect(runs.map((r) => [r.command, r.state, r.output])).toEqual([
      ["git status", "done", [" M router.py"]],
      ["pytest -q", "failed", ["1 failed", "[exit 1]"]],
    ])
    expect(runs[0].conversationId).toBe("c1")
  })

  it("the newest run stays running until its output is quiet", () => {
    const lines = [line(1, "command", "$ >npm test", 0), line(2, "output", "PASS a", 100)]
    expect(buildShellRuns(lines, 100 + SHELL_QUIET_MS - 1)[0].state).toBe("running")
    expect(buildShellRuns(lines, 100 + SHELL_QUIET_MS)[0].state).toBe("done")
  })

  it("renders the prompt line and a one-node matrix with an EXEC row that opens to the output", () => {
    const [run] = buildShellRuns([line(1, "command", "$ >pytest -q", 0), line(2, "output", "1 failed", 50), line(3, "output", "[exit 1]", 60)], 10_000)
    const { container } = render(<ShellRunEntry run={run} glowColor={GLOW} now={10_000} />)
    expect(container.querySelector("[data-prompt-line]")).toHaveTextContent("❯ >pytest -q")
    const row = container.querySelector("[data-row-id]")!
    expect(row).toHaveTextContent("EXEC")
    expect(row.getAttribute("data-state")).toBe("failed")
    expect(container.querySelector("[data-matrix-detail]")).toHaveTextContent("[exit 1]")
  })

  it("the timeline places a shell run between the messages around it", () => {
    const at = (t: number) => new Date(t)
    const msgs = [{ id: "m1", timestamp: at(1000) }, { id: "m2", timestamp: at(5000) }]
    const [run] = buildShellRuns([line(1, "command", "$ >ls", 3000)], 99_999)
    const t = buildChatTimeline(msgs, [], [run])
    expect(t.map((e) => (e.kind === "message" ? e.message.id : e.kind))).toEqual(["m1", "shell", "m2"])
  })
})

describe("the developer answer is rendered markdown in the mono family", () => {
  it("bold and code render as elements, not literal ** and backticks", () => {
    const { container } = render(<MarkdownMessage text={"Fixed. The cap uses **the reserve** now: `_RESERVE`."} variant="cli" />)
    expect(container.querySelector(".iris-md.iris-md-cli")).not.toBeNull()
    expect(container.querySelector("strong")).toHaveTextContent("the reserve")
    expect(container.querySelector("code")).toHaveTextContent("_RESERVE")
    expect(container.textContent).not.toContain("**")
  })
})

describe("TaskCardEntry: developer mode draws the live matrix (guard: fails on the old 9 px <pre>)", () => {
  it("developer: a live matrix, no preformatted picture", () => {
    const { TaskCardEntry } = require("@/components/chat/TaskCardEntry")
    const { container } = render(<TaskCardEntry card={LIVE} isDeveloper glowColor={GLOW} matrixElapsedSec={12} />)
    expect(container.querySelector("[data-matrix]")).not.toBeNull()
    expect(container.querySelector("pre")).toBeNull()
    expect(container.querySelectorAll("[data-row-id]").length).toBe(4)
  })
})
