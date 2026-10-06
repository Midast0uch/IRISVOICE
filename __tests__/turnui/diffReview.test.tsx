/**
 * DONE line (diffs): an edit shows ± where it happened, and the lens reviews it per hunk
 * with Keep / Undo / Undo all wired to `diff_undo` and its result. A hunk reads "undone"
 * only after an ok `diff_undo_result`; a refusal shows its reason; `undoable: false` hides
 * Undo and says why; a new file says undo deletes it; a cut diff says so.
 * Payloads are the backend's (backend/tests/contract/test_edit_diff_contract.py).
 */
import React from "react"
import fs from "fs"
import path from "path"
import { render, screen, fireEvent, within, act } from "@testing-library/react"
import "@testing-library/jest-dom"
import { DiffReview } from "@/components/chat/diff/DiffReview"
import { applyDiffUndoResult, __resetUndoForTests } from "@/lib/diffs/undoStore"
import { oneHunkDiff, twoHunkDiff } from "./harness"

beforeEach(() => __resetUndoForTests())

const hunk = (c: HTMLElement, i: number) => c.querySelector(`[data-hunk="${i}"]`) as HTMLElement

describe("DiffReview — one block per file, hunks with +/- lines", () => {
  it("shows the file, the counts, and each hunk's rows as the backend sent them", () => {
    const { container } = render(<DiffReview diffs={[twoHunkDiff()]} sendMessage={jest.fn(() => true)} />)
    expect(screen.getByText("/work/cap.py")).toBeInTheDocument()
    expect(container.querySelectorAll("[data-hunk]")).toHaveLength(2)
    expect(hunk(container, 0)).toHaveTextContent("@@ -1,4 +1,4 @@")
    expect(hunk(container, 0)).toHaveTextContent("-b")
    expect(hunk(container, 0)).toHaveTextContent("+B")
    expect(hunk(container, 1)).toHaveTextContent("+Y")
  })
})

describe("Undo is wired to diff_undo, and 'undone' waits for the backend", () => {
  it("a hunk Undo sends diff_undo with its hunk_index and is NOT undone until an ok result", () => {
    const send = jest.fn(() => true)
    const { container } = render(<DiffReview diffs={[twoHunkDiff()]} sendMessage={send} />)
    fireEvent.click(within(hunk(container, 1)).getByRole("button", { name: "Undo change 2" }))
    expect(send).toHaveBeenCalledWith("diff_undo", { diff_id: "d-two", hunk_index: 1 })
    // request sent, no answer yet: not undone
    expect(hunk(container, 1).getAttribute("data-hunk-state")).toBe("pending")
    expect(container.querySelector("[data-hunk-undone]")).toBeNull()
    act(() => applyDiffUndoResult({ diff_id: "d-two", hunk_index: 1, ok: true, told_iris: true }))
    expect(hunk(container, 1).getAttribute("data-hunk-state")).toBe("undone")
    expect(hunk(container, 1)).toHaveTextContent("undone")
    // the other hunk is untouched
    expect(hunk(container, 0).getAttribute("data-hunk-state")).toBe("idle")
  })

  it("a refusal shows its reason and the hunk stays not undone", () => {
    const send = jest.fn(() => true)
    const { container } = render(<DiffReview diffs={[twoHunkDiff()]} sendMessage={send} />)
    fireEvent.click(within(hunk(container, 0)).getByRole("button", { name: "Undo change 1" }))
    act(() =>
      applyDiffUndoResult({ diff_id: "d-two", hunk_index: 0, ok: false, reason: "the lines around this change no longer match the file" }),
    )
    expect(screen.getByRole("alert")).toHaveTextContent("the lines around this change no longer match the file")
    expect(hunk(container, 0).getAttribute("data-hunk-state")).toBe("refused")
    expect(container.querySelector("[data-hunk-undone]")).toBeNull()
    // and the user can try again
    expect(within(hunk(container, 0)).getByRole("button", { name: "Undo change 1" })).toBeEnabled()
  })

  it("Undo all sends diff_undo without a hunk_index; every hunk reads undone only after the ok result", () => {
    const send = jest.fn(() => true)
    const { container } = render(<DiffReview diffs={[twoHunkDiff()]} sendMessage={send} />)
    fireEvent.click(screen.getByRole("button", { name: /Undo all changes in/ }))
    expect(send).toHaveBeenCalledWith("diff_undo", { diff_id: "d-two" })
    expect(send.mock.calls[0][1]).not.toHaveProperty("hunk_index")
    expect(container.querySelector("[data-hunk-undone]")).toBeNull()
    act(() => applyDiffUndoResult({ diff_id: "d-two", hunk_index: null, ok: true, told_iris: true }))
    expect(container.querySelectorAll("[data-hunk-undone]")).toHaveLength(2)
    expect(container.querySelector('[data-diff-note="undone"]')).toHaveTextContent("IRIS knows you did not want this change")
  })

  it("a file-level refusal shows the reason", () => {
    render(<DiffReview diffs={[oneHunkDiff()]} sendMessage={jest.fn(() => true)} />)
    fireEvent.click(screen.getByRole("button", { name: /Undo all changes in/ }))
    act(() =>
      applyDiffUndoResult({ diff_id: "d-one", hunk_index: null, ok: false, reason: "the file changed after this edit, so undo would overwrite newer work" }),
    )
    expect(screen.getByRole("alert")).toHaveTextContent("undo would overwrite newer work")
  })

  it("when the socket is closed nothing is claimed undone and the reason says so", () => {
    const { container } = render(<DiffReview diffs={[oneHunkDiff()]} sendMessage={jest.fn(() => false)} />)
    fireEvent.click(within(hunk(container, 0)).getByRole("button", { name: "Undo change 1" }))
    expect(screen.getByRole("alert")).toHaveTextContent("not connected")
    expect(container.querySelector("[data-hunk-undone]")).toBeNull()
  })
})

describe("what the diff says about itself", () => {
  it("undoable:false hides Undo and says why", () => {
    const { container } = render(<DiffReview diffs={[oneHunkDiff({ undoable: false })]} sendMessage={jest.fn(() => true)} />)
    expect(screen.queryByRole("button", { name: /Undo/ })).toBeNull()
    expect(container.querySelector('[data-diff-note="not-undoable"]')).toHaveTextContent("no copy of the file was kept")
    // the review itself still shows the change
    expect(hunk(container, 0)).toHaveTextContent("+THREE")
  })

  it("a new file says Undo all deletes it", () => {
    const { container } = render(
      <DiffReview diffs={[oneHunkDiff({ diff_id: "d-new", new_file: true, removed: 0, hunks: [{ header: "@@ -0,0 +1,2 @@", lines: ["+a", "+b"] }] })]} sendMessage={jest.fn(() => true)} />,
    )
    expect(container.querySelector('[data-diff-note="new-file"]')).toHaveTextContent("Undo all deletes it")
  })

  it("a truncated diff says it is cut; a stub with no hunks says the file is too large to show", () => {
    const cut = render(<DiffReview diffs={[oneHunkDiff({ truncated: true })]} sendMessage={jest.fn(() => true)} />)
    expect(cut.container.querySelector('[data-diff-note="truncated"]')).toHaveTextContent("only the first lines are shown")
    cut.unmount()
    const stub = render(<DiffReview diffs={[oneHunkDiff({ diff_id: "d-stub", truncated: true, undoable: false, hunks: [], added: 0, removed: 0 })]} sendMessage={jest.fn(() => true)} />)
    expect(stub.container.querySelector('[data-diff-note="truncated"]')).toHaveTextContent("too large to show a diff")
  })

  it("Keep marks a hunk kept without sending anything", () => {
    const send = jest.fn(() => true)
    const { container } = render(<DiffReview diffs={[twoHunkDiff()]} sendMessage={send} />)
    fireEvent.click(within(hunk(container, 0)).getByRole("button", { name: "Keep change 1" }))
    expect(send).not.toHaveBeenCalled()
    expect(hunk(container, 0)).toHaveTextContent("kept")
  })

  it("several edits to one step are separate files in one review, each with its own undo", () => {
    const second = oneHunkDiff({ diff_id: "d-2nd" })
    const { container } = render(<DiffReview diffs={[oneHunkDiff(), second]} sendMessage={jest.fn(() => true)} />)
    expect(container.querySelectorAll("[data-diff-file]")).toHaveLength(2)
    expect(screen.getByText(/edit 2/)).toBeInTheDocument()
  })
})

describe("wiring: the WebSocket hook files diff_undo_result into the undo store", () => {
  it("useIRISWebSocket handles diff_undo_result with applyDiffUndoResult", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "..", "..", "hooks", "useIRISWebSocket.ts"), "utf8")
    expect(src).toMatch(/case "diff_undo_result":[\s\S]{0,200}applyDiffUndoResult\(/)
  })
})
