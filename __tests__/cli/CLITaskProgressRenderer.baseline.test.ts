/**
 * BASELINE — Wave 0, specs/task-card-v2-liquid-ink.
 * Pinned behavior as of 2026-08-19: `render()` delegated to the unselected
 * Flow Pipeline variant, and content lines opened a left wall but never
 * closed a right wall (ragged output).
 * INVERTED 2026-08-19 by T12 — the renderer is now promoted to
 * `lib/cli/CLITaskProgressRenderer.ts` (only the chosen Blueprint Matrix
 * variant came with it; the other three temp/ variants were dropped, not
 * promoted). This file's import was repointed at the new module and its
 * three assertions were flipped to assert the FIXED behaviour: `render()`
 * now resolves to `renderBlueprintCellMatrixCLI`, every content row closes
 * its right wall, and visible width (not `String.length`) drives alignment.
 * This is the sanctioned T12 edit called out in its report. Further CT-5
 * coverage (wide glyphs, colour-on/off parity, long-label/long-target
 * truncation) lives in `__tests__/cli/CLITaskProgressRenderer.test.ts`.
 */
import {
  ANSI,
  renderBlueprintCellMatrixCLI,
  CLITaskProgressRenderer,
} from "../../lib/cli/CLITaskProgressRenderer"
import type { TaskCardProps } from "../../lib/cli/CLITaskProgressRenderer"
// Only used for the one negative comparison below (render() no longer
// resolves to the unselected Flow Pipeline variant). temp/ itself is
// untouched by T12; it is removed by T19 once T8 has also promoted what it
// needs.
import { renderCyberDoubleRailCLI } from "../../temp/task-card-redesign/CLITaskProgressRenderer"

// Defensive local ANSI strip — asserted against even when useColor=false.
function stripAnsi(s: string): string {
  return s.replace(/\x1b\[[0-9;]*m/g, "")
}

// Shared fixture: >=3 steps, one with `summary`, one with `branchLabel`,
// mixed statuses (done / running / pending). Field names read from
// TaskStepItem / TaskCardProps in lib/cli/CLITaskProgressRenderer.ts.
const task: TaskCardProps = {
  objective: "Refactor the websocket client",
  steps: [
    {
      id: "1",
      verb: "read",
      target: "src/main.rs",
      status: "done",
      summary: "142 lines read",
    },
    {
      id: "2",
      verb: "patch",
      target: "src/ws_client.rs",
      status: "running",
      branchLabel: "Detour",
    },
    {
      id: "3",
      verb: "exec",
      target: "cargo build",
      status: "pending",
    },
  ],
}

describe("CLITaskProgressRenderer — BASELINE (inverted by T12)", () => {
  it("1. render() now resolves to the Blueprint Matrix variant, NOT the Flow Pipeline one", () => {
    const rendered = CLITaskProgressRenderer.render(task, true)
    expect(rendered).toBe(renderBlueprintCellMatrixCLI(task, true))
    expect(rendered).not.toBe(renderCyberDoubleRailCLI(task, true))

    const renderedNoColor = CLITaskProgressRenderer.render(task, false)
    expect(renderedNoColor).toBe(renderBlueprintCellMatrixCLI(task, false))
    expect(renderedNoColor).not.toBe(renderCyberDoubleRailCLI(task, false))
  })

  it("2. every content line closes its right wall and lines up with the frame — no more ragged output", () => {
    const output = CLITaskProgressRenderer.render(task, false)
    const lines = output.split("\n").map(stripAnsi)

    const FRAME_START = /^[┌├└]/ // ┌ ├ └
    const FRAME_END = /[┐┤┘]$/ // ┐ ┤ ┘

    const frameRows = lines.filter((l) => FRAME_START.test(l))
    const contentRows = lines.filter((l) => !FRAME_START.test(l))

    expect(frameRows.length).toBeGreaterThan(0)
    expect(contentRows.length).toBeGreaterThan(0)

    // Every frame row closes with the matching corner/tee glyph.
    for (const row of frameRows) {
      expect(row).toMatch(FRAME_END)
    }

    // Content rows open a left wall (│) AND now close a right wall (│).
    for (const row of contentRows) {
      expect(row.startsWith("│")).toBe(true)
      expect(row.endsWith("│")).toBe(true)
    }

    // Every row — frame and content alike — is the same visible width now.
    const lengths = new Set(lines.map((l) => l.length))
    expect(lengths.size).toBe(1)
  })

  it("3. padding is computed from VISIBLE width, so colour on/off align identically despite ANSI inflating String.length", () => {
    const coloured = CLITaskProgressRenderer.render(task, true).split("\n")
    const uncoloured = CLITaskProgressRenderer.render(task, false).split("\n")

    // ANSI still inflates String.length on a coloured content line...
    const verbLine = coloured.find((l) => stripAnsi(l).includes("READ"))
    expect(verbLine).toBeDefined()
    const raw = verbLine as string
    const strippedLen = stripAnsi(raw).length
    expect(raw.length).toBeGreaterThan(strippedLen)
    expect(raw).toContain(ANSI.reset)

    // ...but every stripped coloured row now matches its uncoloured
    // counterpart exactly, proving padding was computed on visible width,
    // not String.length.
    expect(coloured.length).toBe(uncoloured.length)
    coloured.forEach((line, i) => {
      expect(stripAnsi(line)).toBe(uncoloured[i])
    })
  })
})
