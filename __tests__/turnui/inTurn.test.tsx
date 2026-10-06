/**
 * In-turn interactions, driven through the real Timeline in BOTH modes, from turn parts and
 * task-card data shaped like the backend sends them (see ./harness).
 *
 * DONE line: in both modes an edit shows ± where it happened and the lens reviews it;
 * artifacts open in the lens with pop-out and drag; IRIS's permission / question waits in the
 * turn with y / n and leaves a receipt; the matrix shows ASK and MADE rows; the personal card
 * speaks plain words.
 */
import React from "react"
import { render, screen, fireEvent, within, act } from "@testing-library/react"
import "@testing-library/jest-dom"
import {
  CONV, TURN, card, editResultPart, mountTimeline, oneHunkDiff, permissionRequestPart, part,
  questionAskPart, reduce, startMsg, turnOf, twoHunkDiff, msg,
} from "./harness"
import { applyDiffUndoResult, __resetUndoForTests } from "@/lib/diffs/undoStore"
import { closeLens, getLens } from "@/lib/lens/lensStore"
import { LENS_MIME } from "@/lib/lens/dragPayload"
import { __resetAsksForTests } from "@/lib/turns/asks"

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: { color: "#22d3ee" }, shimmer: { primary: "#22d3ee" }, accent: "#22d3ee" }),
  }),
  BrandColorProvider: ({ children }: { children: React.ReactNode }) => children,
}))
jest.mock("framer-motion", () => {
  const React = require("react")
  const motion: any = new Proxy({}, { get: (_t: any, tag: string) => React.forwardRef((p: any, ref: any) => {
    const { initial, animate, exit, transition, whileHover, whileTap, layout, ...rest } = p || {}
    return React.createElement(tag, { ...rest, ref }, p?.children)
  }) })
  return { motion, AnimatePresence: ({ children }: any) => children }
})
jest.mock("@/components/Xur", () => ({ Xur: () => <div data-testid="xur" /> }))

beforeAll(() => {
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null)
})
beforeEach(() => {
  __resetUndoForTests()
  __resetAsksForTests()
  closeLens()
})

const MODES: Array<[string, boolean]> = [["personal", false], ["developer", true]]

const editingSteps = () => [
  { id: "n1", description: "read router.py", status: "done", toolName: "read_file", resultPreview: "48 ln" },
  { id: "n2", description: "router.py", status: "done", toolName: "edit_file", resultPreview: "+1 -1", diffs: [oneHunkDiff()] },
  { id: "n3", description: "pytest -q", status: "working", toolName: "run_command" },
]

const dnd = () => {
  const store: Record<string, string> = {}
  return { store, setData: (k: string, v: string) => { store[k] = v }, getData: (k: string) => store[k] ?? "", effectAllowed: "" }
}

describe.each(MODES)("± where the edit happened — %s mode", (_m, isDeveloper) => {
  const mount = (extra: Record<string, unknown> = {}) => {
    const turn = turnOf([startMsg(isDeveloper ? "developer" : "personal"), editResultPart(oneHunkDiff())])
    return mountTimeline({ isDeveloper, turn, card: card(editingSteps()), ...extra })
  }

  it("the editing step carries a ± and the steps that did not edit carry none", () => {
    const { container } = mount()
    const row = isDeveloper ? '[data-row-id="n2"]' : '[data-task-step]:nth-of-type(2)'
    const editing = container.querySelector(row)!
    expect(editing.querySelector("[data-diff-mark]")).not.toBeNull()
    expect(container.querySelectorAll("[data-task-step] [data-diff-mark], [data-row-id] [data-diff-mark]")).toHaveLength(1)
  })

  it("the reply of the turn sums the edits in one chip (from the turn's tool_result part)", () => {
    const { container } = mount()
    const chip = container.querySelector("[data-diff-summary]")!
    expect(chip).toHaveTextContent("1 file changed · router.py")
    expect(chip).toHaveTextContent("+1")
    expect(chip).toHaveTextContent("−1")
  })

  it("clicking ± opens the review in the lens, over the timeline, with the hunk lines", () => {
    const { container } = mount()
    fireEvent.click(container.querySelector("[data-diff-mark]") as HTMLElement)
    const lens = screen.getByRole("dialog", { name: /Changes/ })
    expect(lens).toHaveTextContent("/work/router.py")
    expect(lens).toHaveTextContent("+THREE")
    expect(lens.parentElement).toBe(container.querySelector("[data-timeline-wrap]"))
  })

  it("Undo in the lens sends diff_undo; the hunk reads undone only after the backend's ok", () => {
    const send = jest.fn(() => true)
    const { container } = mount({ sendMessage: send })
    fireEvent.click(container.querySelector("[data-diff-mark]") as HTMLElement)
    fireEvent.click(screen.getByRole("button", { name: "Undo change 1" }))
    expect(send).toHaveBeenCalledWith("diff_undo", { diff_id: "d-one", hunk_index: 0 })
    expect(container.querySelector("[data-hunk-undone]")).toBeNull()
    act(() => applyDiffUndoResult({ diff_id: "d-one", hunk_index: 0, ok: true, told_iris: true }))
    expect(container.querySelector("[data-hunk-undone]")).not.toBeNull()
  })

  it("the ± is draggable and carries the diff for the dashboard", () => {
    const { container } = mount()
    const mark = container.querySelector("[data-diff-mark]") as HTMLElement
    expect(mark).toHaveAttribute("draggable", "true")
    const dt = dnd()
    fireEvent.dragStart(mark, { dataTransfer: dt })
    const p = JSON.parse(dt.store[LENS_MIME])
    expect(p.kind).toBe("diff")
    expect(p.diffs[0].diff_id).toBe("d-one")
  })

  it("Esc and back close the lens", () => {
    const { container } = mount()
    fireEvent.click(container.querySelector("[data-diff-mark]") as HTMLElement)
    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.queryByRole("dialog", { name: /Changes/ })).toBeNull()
    fireEvent.click(container.querySelector("[data-diff-mark]") as HTMLElement)
    fireEvent.click(screen.getByRole("button", { name: "Back to the chat" }))
    expect(screen.queryByRole("dialog", { name: /Changes/ })).toBeNull()
    expect(getLens()).toBeNull()
  })
})

describe.each(MODES)("artifacts open in the lens — %s mode", (_m, isDeveloper) => {
  const DOC = { id: "doc-1", documentId: "D1", turnId: TURN, format: "markdown", title: "Router budget plan", content: "# Plan\n\nbudget = window - max_tokens - reserve. The reserve stays at 256.", alternatives: [], createdAt: Date.now() }
  const mount = (extra: Record<string, unknown> = {}) =>
    mountTimeline({ isDeveloper, turn: turnOf([startMsg(isDeveloper ? "developer" : "personal")]), documents: [DOC], ...extra })

  it("the turn shows a compact titled card with a one-line meta, not the whole document", () => {
    const { container } = mount()
    const chip = container.querySelector('[data-artifact-chip="doc-1"]')!
    expect(chip).toHaveTextContent("Router budget plan")
    expect(chip.querySelector("[data-artifact-meta]")).toHaveTextContent(/^document · \d+ words · just now$/)
    expect(container.textContent).not.toContain("budget = window")
  })

  it("click opens the document inside the wing (an overlay over the timeline)", () => {
    const { container } = mount()
    fireEvent.click(container.querySelector('[data-artifact-chip="doc-1"]') as HTMLElement)
    const lens = screen.getByRole("dialog", { name: "Router budget plan" })
    expect(lens).toHaveTextContent("The reserve stays at 256")
    expect(lens.parentElement).toBe(container.querySelector("[data-timeline-wrap]"))
  })

  it("Enter on the card opens it too (keyboard)", () => {
    const { container } = mount()
    fireEvent.keyDown(container.querySelector('[data-artifact-chip="doc-1"]') as HTMLElement, { key: "Enter" })
    expect(screen.getByRole("dialog", { name: "Router budget plan" })).toBeInTheDocument()
  })

  it("Pop out opens it the way an artifact opened outside the wing before (the document panel)", () => {
    const setExpandedDocId = jest.fn()
    const { container } = mount({ setExpandedDocId })
    fireEvent.click(container.querySelector('[data-artifact-chip="doc-1"]') as HTMLElement)
    fireEvent.click(screen.getByRole("button", { name: "Pop out" }))
    expect(setExpandedDocId).toHaveBeenCalledWith("doc-1")
    expect(screen.queryByRole("dialog", { name: "Router budget plan" })).toBeNull()
  })

  it("To dashboard puts the artifact in the dashboard workspace and says so", () => {
    const { useWorkspaceStore } = require("@/stores/workspaceStore")
    useWorkspaceStore.setState({ tabs: [], sections: [], archived: [], views: [] })
    const { container } = mount()
    fireEvent.click(container.querySelector('[data-artifact-chip="doc-1"]') as HTMLElement)
    fireEvent.click(screen.getByRole("button", { name: "To dashboard" }))
    expect(screen.getByRole("status")).toHaveTextContent("Opened in the dashboard workspace.")
    // Owner-approved requirement change (rev 4): the artifact becomes a Views-lane view, not a tab.
    expect(useWorkspaceStore.getState().views[0]).toMatchObject({ title: "Router budget plan", kind: "artifact" })
    expect(useWorkspaceStore.getState().tabs).toHaveLength(0)
  })

  it("the card is draggable and carries the artifact for the dashboard workspace", () => {
    const { container } = mount()
    const chip = container.querySelector('[data-artifact-chip="doc-1"]') as HTMLElement
    expect(chip).toHaveAttribute("draggable", "true")
    const dt = dnd()
    fireEvent.dragStart(chip, { dataTransfer: dt })
    const p = JSON.parse(dt.store[LENS_MIME])
    expect(p).toMatchObject({ kind: "artifact", id: "doc-1", title: "Router budget plan", format: "markdown" })
    expect(p.content).toContain("The reserve stays at 256")
  })

  it("a streaming (partial) document stays inline so its fill is visible", () => {
    const { container } = mount({ documents: [{ ...DOC, partial: true }] })
    expect(container.querySelector('[data-artifact-chip="doc-1"]')).toBeNull()
  })
})

describe("developer matrix: MADE and ASK rows", () => {
  const DOC = { id: "doc-9", turnId: TURN, format: "table", title: "Latency by node", content: "| node | ms |\n|---|---|\n| a | 3 |\n| b | 4 |\n| c | 5 |", alternatives: [], createdAt: Date.now() }

  it("a MADE row under the step that made the artifact opens the lens", () => {
    const steps = [
      { id: "m1", description: "collect timings", status: "done", toolName: "run_command" },
      { id: "m2", description: "Latency by node", status: "done", toolName: "create_artifact" },
      { id: "m3", description: "summarise", status: "working", toolName: "read_file" },
    ]
    const turn = turnOf([startMsg("developer")])
    const { container } = mountTimeline({ isDeveloper: true, turn, card: card(steps), documents: [DOC] })
    const made = container.querySelector('[data-made-row="doc-9"]') as HTMLElement
    expect(made).toHaveTextContent("MADE")
    expect(made).toHaveTextContent("Latency by node")
    expect(made).toHaveTextContent("table · 3 rows")
    // it hangs right under the row of the step that made it
    expect(made.previousElementSibling).toHaveAttribute("data-row-id", "m2")
    fireEvent.click(made)
    expect(screen.getByRole("dialog", { name: "Latency by node" })).toBeInTheDocument()
  })

  it("an ASK row waits at the end of the rows; its keys are in the row", () => {
    const turn = turnOf([startMsg("developer"), permissionRequestPart()])
    const { container } = mountTimeline({ isDeveloper: true, turn, card: card(editingSteps()) })
    const ask = container.querySelector('[data-matrix] [data-ask="perm-1"]') as HTMLElement
    expect(ask).toHaveAttribute("data-ask-state", "waiting")
    expect(ask).toHaveTextContent("ASK")
    expect(ask).toHaveTextContent("run command · pytest -q tests/unit/test_router.py")
    expect(ask).toHaveTextContent("[y] allow")
    expect(ask).toHaveTextContent("[n] deny")
    // it is the last thing in the matrix body, below the rows
    const rows = container.querySelectorAll("[data-row-id]")
    expect(ask.compareDocumentPosition(rows[rows.length - 1]) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
  })

  it("the ASK and MADE rows never change which steps ran (the matrix rows are the card's steps)", () => {
    const turn = turnOf([startMsg("developer"), permissionRequestPart()])
    const { container } = mountTimeline({ isDeveloper: true, turn, card: card(editingSteps()), documents: [DOC] })
    expect(Array.from(container.querySelectorAll("[data-row-id]")).map((r) => r.getAttribute("data-row-id"))).toEqual(["n1", "n2", "n3"])
  })
})

describe.each(MODES)("a permission waits in the turn — %s mode", (_m, isDeveloper) => {
  const mount = (opts: { parts?: any[]; send?: jest.Mock; rmPerm?: jest.Mock; withCard?: boolean } = {}) => {
    const turn = turnOf([startMsg(isDeveloper ? "developer" : "personal"), ...(opts.parts ?? [permissionRequestPart()])])
    return mountTimeline({
      isDeveloper,
      turn,
      card: opts.withCard === false ? undefined : card(editingSteps()),
      sendMessage: opts.send,
      removePendingPermission: opts.rmPerm,
      // the legacy list still holds the request: it must NOT show a second card
      pendingPermissions: new Map([["perm-1", { requestId: "perm-1", toolName: "run_command", tier: "side_effect", params: {}, timeoutSeconds: 30, requiresConfirmation: false }]]),
    })
  }

  it("sits inside the running card (not as a loose card at the bottom)", () => {
    const { container } = mount()
    const ask = container.querySelector('[data-ask="perm-1"]')!
    expect(ask.closest(isDeveloper ? "[data-matrix]" : '[aria-label="Task progress"]')).not.toBeNull()
    expect(screen.queryByLabelText("Permission request: run_command")).toBeNull()
  })

  it("y allows: the existing response is sent, and a receipt line is left", () => {
    const send = jest.fn(() => true)
    const rmPerm = jest.fn()
    const { container } = mount({ send, rmPerm })
    const ask = container.querySelector('[data-ask="perm-1"]') as HTMLElement
    expect(document.activeElement).toBe(ask)
    fireEvent.keyDown(ask, { key: "y" })
    expect(send).toHaveBeenCalledWith("notification_response", { notification_id: "perm-1", action: "grant" })
    expect(rmPerm).toHaveBeenCalledWith("perm-1")
    const receipt = container.querySelector("[data-ask-receipt]")!
    expect(receipt).toHaveTextContent("✓ Allowed · run command · pytest -q tests/unit/test_router.py")
    expect(container.querySelector('[data-ask="perm-1"]')).toHaveAttribute("data-ask-state", "allowed")
    expect(container.textContent).not.toContain("[y] allow")
  })

  it("Enter allows; n and Esc deny and leave a Denied receipt", () => {
    const a = mount({ send: jest.fn(() => true) })
    fireEvent.keyDown(a.container.querySelector('[data-ask="perm-1"]') as HTMLElement, { key: "Enter" })
    expect(a.props.sendMessage).toHaveBeenCalledWith("notification_response", { notification_id: "perm-1", action: "grant" })
    a.unmount(); __resetAsksForTests()
    const n = mount({ send: jest.fn(() => true) })
    fireEvent.keyDown(n.container.querySelector('[data-ask="perm-1"]') as HTMLElement, { key: "n" })
    expect(n.props.sendMessage).toHaveBeenCalledWith("notification_response", { notification_id: "perm-1", action: "deny" })
    expect(n.container.querySelector("[data-ask-receipt]")).toHaveTextContent("✕ Denied · run command · pytest -q")
    n.unmount(); __resetAsksForTests()
    const e = mount({ send: jest.fn(() => true) })
    fireEvent.keyDown(e.container.querySelector('[data-ask="perm-1"]') as HTMLElement, { key: "Escape" })
    expect(e.props.sendMessage).toHaveBeenCalledWith("notification_response", { notification_id: "perm-1", action: "deny" })
  })

  it("keys typed in a text field never answer the ask", () => {
    const send = jest.fn(() => true)
    const { container } = mount({ send })
    const ask = container.querySelector('[data-ask="perm-1"]') as HTMLElement
    const input = document.createElement("input")
    ask.appendChild(input)
    fireEvent.keyDown(input, { key: "y" })
    expect(send).not.toHaveBeenCalled()
  })

  it("the countdown is the backend's timeout, shown only when the backend sent one", () => {
    const withTimeout = mount()
    expect(withTimeout.container.querySelector("[data-ask-countdown]")).toHaveTextContent("0:30")
    withTimeout.unmount(); __resetAsksForTests()
    const without = mount({ parts: [permissionRequestPart({ timeout_seconds: undefined })] })
    expect(without.container.querySelector("[data-ask-countdown]")).toBeNull()
  })

  it("a permission that needs a second look asks for y again before it grants", () => {
    const send = jest.fn(() => true)
    const { container } = mount({ send, parts: [permissionRequestPart({ requires_confirmation: true, tier: "destructive" })] })
    const ask = container.querySelector('[data-ask="perm-1"]') as HTMLElement
    fireEvent.keyDown(ask, { key: "y" })
    expect(send).not.toHaveBeenCalled()
    expect(ask).toHaveTextContent("Are you sure?")
    fireEvent.keyDown(ask, { key: "y" })
    expect(send).toHaveBeenCalledWith("notification_response", { notification_id: "perm-1", action: "confirm" })
  })

  it("the backend's own denial (timed out) leaves a receipt that says it was not answered in time", () => {
    const { container } = mount({
      parts: [permissionRequestPart(), part({ type: "interaction", event: "permission:denied", data: { request_id: "perm-1", tool_name: "run_command", reason: "timeout", timeout_seconds: 30 } })],
    })
    expect(container.querySelector("[data-ask-receipt]")).toHaveTextContent("Not answered in time")
  })

  it("with no task card the ask sits in the turn itself", () => {
    const { container } = mount({ withCard: false })
    const ask = container.querySelector('[data-ask="perm-1"]')!
    expect(ask.closest("[data-turn-asks]")).not.toBeNull()
  })

  it("a request the turn does not carry keeps its legacy card (nothing the user must answer is hidden)", () => {
    const turn = turnOf([startMsg(isDeveloper ? "developer" : "personal")])
    const { container } = mountTimeline({
      isDeveloper, turn, card: card(editingSteps()),
      pendingPermissions: new Map([["perm-x", { requestId: "perm-x", toolName: "write_file", tier: "side_effect", params: {}, timeoutSeconds: 30, requiresConfirmation: false }]]),
    })
    expect(container.querySelector('[data-ask="perm-x"]')).toBeNull()
    expect(screen.getByLabelText("Permission request: write_file")).toBeInTheDocument()
  })
})

describe.each(MODES)("a question waits in the turn — %s mode", (_m, isDeveloper) => {
  it("an option answers through the existing question response and leaves a receipt", () => {
    const send = jest.fn(() => true)
    const rmQ = jest.fn()
    const turn = turnOf([startMsg(isDeveloper ? "developer" : "personal"), questionAskPart()])
    const { container } = mountTimeline({
      isDeveloper, turn, card: card(editingSteps()), sendMessage: send, removePendingQuestion: rmQ,
      pendingQuestions: new Map([["q_1", { questionId: "q_1", text: "Keep the reserve at 256?", options: ["Keep it", "Change it"], turnId: TURN }]]),
    })
    // inside the card, and no second (legacy) copy
    expect(container.querySelector('[data-ask="q_1"]')).not.toBeNull()
    expect(container.querySelector('[data-legacy-question="q_1"]')).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }))
    expect(send).toHaveBeenCalledWith("question_response", { question_id: "q_1", answer: "Keep it", source: "click" })
    expect(rmQ).toHaveBeenCalledWith("q_1")
    expect(container.querySelector("[data-ask-receipt]")).toHaveTextContent("✓ Answered · Keep the reserve at 256? · Keep it")
  })
})

describe("personal card: plain words", () => {
  const ENGINE = /sub-?loop|converged|crystalliz|landmark|fold-?back/i

  it("a split child says it looked closer and, once done, that it reported back", () => {
    const steps = [
      { id: "n2", description: "pytest", status: "error", toolName: "run_command" },
      { id: "n2_s1", description: "grep _RESERVE =", status: "done", toolName: "grep_files" },
      { id: "n3", description: "edit", status: "done", toolName: "edit_file" },
    ]
    const turn = turnOf([startMsg("personal")])
    const { container } = mountTimeline({ isDeveloper: false, turn, card: card(steps, { isWorking: false }) })
    const child = container.querySelector('[data-task-step]:nth-of-type(2)') as HTMLElement
    expect(child).toHaveTextContent("looked closer")
    expect(child.querySelector("[data-reported-back]")).toHaveTextContent("reported back")
    expect(container.textContent).not.toMatch(ENGINE)
  })

  it("a backend branch label in the engine's words is shown in plain words", () => {
    const steps = [{ id: "a", description: "x", status: "done", toolName: "read_file", branchLabel: "Sub-Loop fold-back" }]
    const turn = turnOf([startMsg("personal")])
    const { container } = mountTimeline({ isDeveloper: false, turn, card: card(steps, { isWorking: false }) })
    expect(container.textContent).toMatch(/looked closer/)
    expect(container.textContent).not.toMatch(ENGINE)
  })

  it("a finished run says done; no engine word on the card", () => {
    const steps = [{ id: "a", description: "read", status: "done", toolName: "read_file" }, { id: "b", description: "write", status: "done", toolName: "write_file" }]
    const turn = turnOf([startMsg("personal")])
    const { container } = mountTimeline({ isDeveloper: false, turn, card: card(steps, { isWorking: false, memoryEvents: [{ kind: "episodic", at: 1, data: { task_summary: "converged on the fix", outcome_type: "success" } }] }) })
    expect(container.textContent).toMatch(/done/)
    expect(container.textContent).not.toMatch(ENGINE)
  })
})

describe("no engine words anywhere in a developer turn with every interaction on screen", () => {
  it("matrix + MADE + ASK + ± show no sub-loop / converged / crystallize / landmark", () => {
    const DOC = { id: "d", turnId: TURN, format: "markdown", title: "Plan", content: "words here", alternatives: [], createdAt: Date.now() }
    const steps = [...editingSteps(), { id: "n3_s1", description: "grep", status: "done", toolName: "grep_files" }]
    const turn = turnOf([startMsg("developer"), editResultPart(oneHunkDiff()), permissionRequestPart()])
    const { container } = mountTimeline({ isDeveloper: true, turn, card: card(steps), documents: [DOC] })
    expect(container.textContent).not.toMatch(/sub-?loop|converged|crystalliz|landmark/i)
  })
})
