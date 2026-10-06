/**
 * DONE line (lens): an artifact or a ± diff dragged out of the chat lands in the dashboard
 * workspace (the Workspace Hub, DeveloperWorkspace) as a card in the Views lane that keeps its content
 * (owner-approved requirement change, rev 4: a view, never a tab).
 * The payload travels in the drag itself, so a dashboard in another window needs no copy of
 * the chat's store.
 */
import React from "react"
import { render, screen, fireEvent, act } from "@testing-library/react"
import "@testing-library/jest-dom"
import { LENS_MIME, MAX_DRAG_BODY, setLensDrag, readLensDrop } from "@/lib/lens/dragPayload"
import { useWorkspaceStore } from "@/stores/workspaceStore"
import { addLensToWorkspace } from "@/lib/workspace/addLensItem"
import { oneHunkDiff } from "./harness"

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({ getThemeConfig: () => ({ glow: { color: "#22d3ee" }, shimmer: { primary: "#22d3ee" } }) }),
}))
jest.mock("@/components/Xur", () => ({ Xur: () => <div /> }))
jest.mock("@/components/terminal/TerminalWidget", () => ({ __esModule: true, default: () => <div /> }))
jest.mock("@/components/terminal/HelpPanel", () => ({ HelpPanel: () => <div /> }))
jest.mock("@/components/workspace/AgentCommandsPanel", () => ({ AgentCommandsPanel: () => null }))
jest.mock("@/hooks/useWorkspacePersistence", () => ({ useWorkspacePersistence: () => ({ isOnline: true, isRestoring: false }) }))
jest.mock("@/hooks/useFileWatcher", () => ({ useFileWatcher: () => undefined }))
jest.mock("@/hooks/useAgentTaskEvents", () => ({ useAgentTaskEvents: () => undefined }))
jest.mock("@/components/workspace/AgentKanbanBoard", () => ({ AgentKanbanBoard: () => null }))

const dnd = () => {
  const store: Record<string, string> = {}
  return {
    store,
    types: [] as string[],
    setData(k: string, v: string) { store[k] = v; this.types = Object.keys(store) },
    getData: (k: string) => store[k] ?? "",
    effectAllowed: "",
  }
}

beforeEach(() => {
  useWorkspaceStore.setState({ tabs: [], sections: [], archived: [], activeTabId: null, showKanban: true, views: [] })
})

describe("the drag payload", () => {
  it("round-trips an artifact and a diff; a foreign drag reads as nothing", () => {
    const a = dnd()
    setLensDrag(a, { v: 1, kind: "artifact", id: "doc-1", title: "Plan", format: "markdown", content: "hello" })
    expect(readLensDrop(a)).toMatchObject({ kind: "artifact", id: "doc-1", content: "hello" })
    const d = dnd()
    setLensDrag(d, { v: 1, kind: "diff", title: "± router.py", diffs: [oneHunkDiff()] })
    expect(readLensDrop(d)).toMatchObject({ kind: "diff" })
    expect(readLensDrop(dnd())).toBeNull()
  })

  it("a body over the cap is cut and says so (bounded)", () => {
    const a = dnd()
    setLensDrag(a, { v: 1, kind: "artifact", id: "x", title: "big", format: "text", content: "x".repeat(MAX_DRAG_BODY + 10) })
    const p = readLensDrop(a) as any
    expect(p.content).toHaveLength(MAX_DRAG_BODY)
    expect(p.truncated).toBe(true)
  })
})

describe("the Workspace Hub takes a drop", () => {
  const mountHub = () => {
    const { DeveloperWorkspace } = require("@/components/workspace/DeveloperWorkspace")
    return render(<DeveloperWorkspace />)
  }

  it("an artifact dropped on the hub becomes a view card that shows its content", () => {
    const { container } = mountHub()
    const dt = dnd()
    setLensDrag(dt, { v: 1, kind: "artifact", id: "doc-1", title: "Router budget plan", format: "markdown", content: "# Plan\n\nreserve stays at 256" })
    const zone = container.querySelector("[data-workspace-drop]") as HTMLElement
    fireEvent.dragOver(zone, { dataTransfer: { ...dt, types: [LENS_MIME] } })
    expect(zone).toHaveAttribute("data-drop-over", "true")
    fireEvent.drop(zone, { dataTransfer: dt })
    expect(zone).toHaveAttribute("data-drop-over", "false")
    // Owner-approved requirement change (rev 4): the drop adds a VIEW, not a tab and not a section card.
    const st = useWorkspaceStore.getState()
    expect(st.views).toHaveLength(1)
    expect(st.views[0]).toMatchObject({ kind: "artifact", title: "Router budget plan", content: "# Plan\n\nreserve stays at 256" })
    expect(st.tabs).toHaveLength(0)
    expect(st.sections).toHaveLength(0)
    expect(screen.getAllByText("Router budget plan").length).toBeGreaterThan(0)
    expect(container).toHaveTextContent("reserve stays at 256")
  })

  it("a ± diff dropped on the hub becomes a view card with the changed lines", () => {
    const { container } = mountHub()
    const dt = dnd()
    setLensDrag(dt, { v: 1, kind: "diff", title: "± router.py", diffs: [oneHunkDiff()] })
    const zone = container.querySelector("[data-workspace-drop]") as HTMLElement
    fireEvent.drop(zone, { dataTransfer: dt })
    expect(container.querySelector("[data-workspace-diff]")).toHaveTextContent("+THREE")
    expect(container.querySelector("[data-workspace-diff]")).toHaveTextContent("-three")
  })

  it("a second drop adds a second view; a drag that is not ours is ignored", () => {
    const { container } = mountHub()
    const zone = container.querySelector("[data-workspace-drop]") as HTMLElement
    for (const id of ["a", "b"]) {
      const dt = dnd()
      setLensDrag(dt, { v: 1, kind: "artifact", id, title: id, format: "text", content: id })
      fireEvent.drop(zone, { dataTransfer: dt })
    }
    // Owner-approved requirement change (rev 4): two drops = two views; tabs and sections stay as they were.
    const st = useWorkspaceStore.getState()
    expect(st.views).toHaveLength(2)
    expect(st.tabs).toHaveLength(0)
    expect(st.sections).toHaveLength(0)
    fireEvent.drop(zone, { dataTransfer: dnd() })
    expect(useWorkspaceStore.getState().views).toHaveLength(2)
  })

  it("'To dashboard' from the lens uses the same path (a view appears without a drag)", () => {
    act(() => {
      addLensToWorkspace({ v: 1, kind: "artifact", id: "doc-2", title: "Notes", format: "markdown", content: "n" })
    })
    // Owner-approved requirement change (rev 4): a view labelled Notes; showKanban is not toggled.
    expect(useWorkspaceStore.getState().views[0].title).toBe("Notes")
    expect(useWorkspaceStore.getState().tabs).toHaveLength(0)
    expect(useWorkspaceStore.getState().showKanban).toBe(true) // unchanged from the beforeEach value
  })
})
