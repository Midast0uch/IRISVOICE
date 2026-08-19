/**
 * T12 (REQ-8, REQ-9) — CT-5 coverage for the promoted Blueprint Matrix CLI
 * renderer (`lib/cli/CLITaskProgressRenderer.ts`). The baseline inversion
 * in `CLITaskProgressRenderer.baseline.test.ts` pins the three named
 * defects being fixed; this file adds the wider CT-5 guarantees: every row
 * is the same visible width, colour on/off alignment is byte-identical
 * after stripping ANSI, wide (CJK) glyphs still align, and free text long
 * enough to overflow the frame truncates instead of breaking it.
 */
import {
  ANSI,
  CLITaskProgressRenderer,
  renderBlueprintCellMatrixCLI,
  visibleWidth,
  truncateToWidth,
} from "../../lib/cli/CLITaskProgressRenderer"
import type { TaskCardProps } from "../../lib/cli/CLITaskProgressRenderer"
import { renderCyberDoubleRailCLI } from "../../temp/task-card-redesign/CLITaskProgressRenderer"

function stripAnsi(s: string): string {
  return s.replace(/\x1b\[[0-9;]*m/g, "")
}

const baseTask: TaskCardProps = {
  objective: "Refactor the websocket client",
  steps: [
    { id: "1", verb: "read", target: "src/main.rs", status: "done", summary: "142 lines read" },
    { id: "2", verb: "patch", target: "src/ws_client.rs", status: "running", branchLabel: "Diving Deeper" },
    { id: "3", verb: "exec", target: "cargo build", status: "pending" },
  ],
}

// Total row width = wall(1) + inner(66) + wall(1) = 68 visible columns.
const EXPECTED_ROW_WIDTH = 68

describe("CLITaskProgressRenderer — Blueprint Matrix (CT-5)", () => {
  it("every row — frame and content — has identical visible width", () => {
    const output = CLITaskProgressRenderer.render(baseTask, true)
    const lines = output.split("\n")
    for (const line of lines) {
      expect(visibleWidth(line)).toBe(EXPECTED_ROW_WIDTH)
    }
  })

  it("render() equals the Blueprint Matrix variant, not the Flow Pipeline one", () => {
    expect(CLITaskProgressRenderer.render(baseTask, true)).toBe(renderBlueprintCellMatrixCLI(baseTask, true))
    expect(CLITaskProgressRenderer.render(baseTask, true)).not.toBe(renderCyberDoubleRailCLI(baseTask, true))
  })

  it("alignment is byte-identical with colour ON and OFF once ANSI is stripped", () => {
    const coloured = CLITaskProgressRenderer.render(baseTask, true)
    const uncoloured = CLITaskProgressRenderer.render(baseTask, false)
    expect(stripAnsi(coloured)).toBe(uncoloured)
  })

  it("a wide-glyph (CJK) target still aligns to the same row width", () => {
    const task: TaskCardProps = {
      objective: "CJK target check",
      steps: [{ id: "1", verb: "read", target: "读取文件内容并验证", status: "done" }],
    }
    const lines = CLITaskProgressRenderer.render(task, false).split("\n")
    for (const line of lines) {
      expect(visibleWidth(line)).toBe(EXPECTED_ROW_WIDTH)
    }
    // The CJK text itself must still be present (not dropped), just aligned.
    const targetLine = lines.find((l) => l.includes("读取"))
    expect(targetLine).toBeDefined()
  })

  it("a very long branch label does not break the frame — it truncates with a visible marker", () => {
    const longLabel = "Diving Deeper ".repeat(20).trim() // way past the 66-col frame
    const task: TaskCardProps = {
      objective: "Long label check",
      steps: [{ id: "1", verb: "patch", target: "src/ws_client.rs", status: "running", branchLabel: longLabel }],
    }
    const lines = CLITaskProgressRenderer.render(task, false).split("\n")
    for (const line of lines) {
      expect(visibleWidth(line)).toBe(EXPECTED_ROW_WIDTH)
    }
    const chamberOpenLine = lines.find((l) => l.includes("┌┄┄"))
    expect(chamberOpenLine).toBeDefined()
    expect(chamberOpenLine).toContain("…") // truncation marker
    expect(chamberOpenLine).not.toContain(longLabel) // the raw over-long label never appears whole
    // The chamber's own corner still lands inside the frame.
    expect((chamberOpenLine as string).endsWith("│")).toBe(true)
  })

  it("a very long target truncates by display width rather than overflowing", () => {
    const longTarget = "src/" + "very-long-directory-name/".repeat(10) + "file.rs"
    const task: TaskCardProps = {
      objective: "Long target check",
      steps: [{ id: "1", verb: "read", target: longTarget, status: "done" }],
    }
    const lines = CLITaskProgressRenderer.render(task, false).split("\n")
    for (const line of lines) {
      expect(visibleWidth(line)).toBe(EXPECTED_ROW_WIDTH)
    }
    const targetLine = lines.find((l) => l.includes("READ"))
    expect(targetLine).toBeDefined()
    expect(targetLine).toContain("…")
    expect(targetLine).not.toContain(longTarget)
  })

  it("truncateToWidth respects wide glyphs and never exceeds the budget", () => {
    expect(visibleWidth(truncateToWidth("读取文件内容并验证读取文件内容并验证", 10))).toBeLessThanOrEqual(10)
    expect(truncateToWidth("short", 20)).toBe("short")
  })
})
