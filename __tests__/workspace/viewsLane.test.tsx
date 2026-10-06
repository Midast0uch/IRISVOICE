/**
 * DONE line (Views lane, concept 2 rev 4): artifacts and ± diffs dropped on the Workspace Hub
 * go to a "Views" lane beside the hub's tools. A view shows title + kind and renders its body;
 * a close x removes it; it is never a workspace tab (not in the tab bar, not in the composer's
 * project bar); the tools stay; the list is bounded (24, oldest dropped).
 */
import React from "react"
import { render, screen, fireEvent, within, act } from "@testing-library/react"
import "@testing-library/jest-dom"
import { setLensDrag, LENS_MIME } from "@/lib/lens/dragPayload"
import { useWorkspaceStore, MAX_VIEWS } from "@/stores/workspaceStore"
import { addLensToWorkspace } from "@/lib/workspace/addLensItem"
import { ProjectBar } from "@/components/chat/composer/ProjectBar"
import { oneHunkDiff } from "../turnui/harness"

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
jest.mock("@/components/workspace/AgentKanbanBoard", () => ({ AgentKanbanBoard: () => <div data-testid="kanban-stub" /> }))

const dnd = () => {
  const store: Record<string, string> = {}
  return {
    types: [] as string[],
    setData(k: string, v: string) { store[k] = v; this.types = Object.keys(store) },
    getData: (k: string) => store[k] ?? "",
    effectAllowed: "",
  }
}

const TAB = { id: "t1", type: "file" as const, path: "backend/router.py", label: "router.py", icon: "file", isVirtual: false }

beforeEach(() => {
  useWorkspaceStore.setState({
    tabs: [TAB], sections: [], archived: [], activeTabId: "t1", showKanban: true, showArchive: true, views: [],
  })
})

const mountHub = () => {
  const { DeveloperWorkspace } = require("@/components/workspace/DeveloperWorkspace")
  return render(<DeveloperWorkspace />)
}
const drop = (container: HTMLElement, payload: any) => {
  const dt = dnd()
  setLensDrag(dt, payload)
  const zone = container.querySelector("[data-workspace-drop]") as HTMLElement
  fireEvent.dragOver(zone, { dataTransfer: { ...dt, types: [LENS_MIME] } })
  fireEvent.drop(zone, { dataTransfer: dt })
}

describe("the Views lane", () => {
  it("is in the hub from the start, labelled, with a hint, beside the tools", () => {
    const { container } = mountHub()
    const lane = container.querySelector("[data-views-lane]") as HTMLElement
    expect(lane).toHaveAccessibleName("Views")
    expect(lane).toHaveTextContent(/Drag an artifact or a ± diff here/)
    // the tools are still there, not toggled by the lane: the tab bar, the tasks board, the archive and help
    expect(screen.getByRole("button", { name: /Arch/i })).toBeInTheDocument()
    expect(screen.getByTestId("kanban-stub")).toBeInTheDocument()
    expect(screen.getByTitle("Command reference (/help)")).toBeInTheDocument()
    expect(container.querySelector("[data-workspace-drop]")).toContainElement(lane)
  })

  it("an artifact dropped on the hub becomes a view card (title + kind + rendered body), not a tab", () => {
    const { container } = mountHub()
    drop(container, { v: 1, kind: "artifact", id: "doc-1", title: "Router budget plan", format: "markdown", content: "# Plan\n\nreserve stays at 256" })
    const card = container.querySelector("[data-view-card]") as HTMLElement
    expect(card.querySelector("[data-view-title]")).toHaveTextContent("Router budget plan")
    expect(card.querySelector("[data-view-kind]")).toHaveTextContent("markdown")
    expect(within(card).getByRole("heading", { name: "Plan" })).toBeInTheDocument() // markdown is rendered
    expect(card).toHaveTextContent("reserve stays at 256")
    const st = useWorkspaceStore.getState()
    expect(st.views).toHaveLength(1)
    expect(st.tabs).toEqual([TAB]) // tabs unchanged
    expect(st.sections).toHaveLength(0) // no kanban card either
    // the tab bar does not show it
    expect(screen.queryByText(/Router budget plan/, { selector: "[role=tab] *, [role=tab]" })).toBeNull()
  })

  it("html and json artifacts show raw, not rendered", () => {
    const { container } = mountHub()
    drop(container, { v: 1, kind: "artifact", id: "h", title: "Page", format: "html", content: "<h1>Hi</h1>" })
    const card = container.querySelector("[data-view-card]") as HTMLElement
    expect(card.querySelector("pre")).toHaveTextContent("<h1>Hi</h1>")
    expect(within(card).queryByRole("heading")).toBeNull()
  })

  it("a ± diff dropped on the hub becomes a view card with the changed lines", () => {
    const { container } = mountHub()
    drop(container, { v: 1, kind: "diff", title: "± router.py", diffs: [oneHunkDiff()] })
    const card = container.querySelector("[data-view-card]") as HTMLElement
    expect(card.querySelector("[data-view-kind]")).toHaveTextContent("diff")
    expect(card.querySelector("[data-workspace-diff]")).toHaveTextContent("+THREE")
    expect(card.querySelector("[data-workspace-diff]")).toHaveTextContent("-three")
    expect(useWorkspaceStore.getState().tabs).toEqual([TAB])
  })

  it("the close x removes that view only", () => {
    const { container } = mountHub()
    drop(container, { v: 1, kind: "artifact", id: "a", title: "First", format: "text", content: "a" })
    drop(container, { v: 1, kind: "artifact", id: "b", title: "Second", format: "text", content: "b" })
    expect(container.querySelectorAll("[data-view-card]")).toHaveLength(2)
    fireEvent.click(screen.getByRole("button", { name: "Close view First" }))
    const left = container.querySelectorAll("[data-view-card]")
    expect(left).toHaveLength(1)
    expect(left[0]).toHaveTextContent("Second")
    expect(useWorkspaceStore.getState().views.map((v) => v.title)).toEqual(["Second"])
  })

  it("a view is not a workspace tab: the tab bar and the composer's project bar do not list it", () => {
    const { container } = mountHub()
    drop(container, { v: 1, kind: "artifact", id: "doc-1", title: "Router budget plan", format: "markdown", content: "x" })
    const { container: bar } = render(<ProjectBar />)
    const tabs = within(bar).getAllByRole("tab").map((t) => t.textContent)
    expect(tabs).toEqual(["router.py"])
    expect(useWorkspaceStore.getState().tabs.some((t) => /Router budget plan/.test(t.label))).toBe(false)
  })

  it("'To dashboard' adds a view and leaves the kanban toggle alone", () => {
    useWorkspaceStore.setState({ showKanban: false })
    act(() => { addLensToWorkspace({ v: 1, kind: "artifact", id: "n", title: "Notes", format: "markdown", content: "n" }) })
    expect(useWorkspaceStore.getState().views[0].title).toBe("Notes")
    expect(useWorkspaceStore.getState().showKanban).toBe(false)
  })

  it(`is bounded: only the last ${MAX_VIEWS} views are kept, the oldest dropped`, () => {
    expect(MAX_VIEWS).toBe(24)
    act(() => {
      for (let i = 0; i < MAX_VIEWS + 6; i++) {
        addLensToWorkspace({ v: 1, kind: "artifact", id: `d${i}`, title: `Doc ${i}`, format: "text", content: String(i) })
      }
    })
    const titles = useWorkspaceStore.getState().views.map((v) => v.title)
    expect(titles).toHaveLength(MAX_VIEWS)
    expect(titles[0]).toBe("Doc 6")
    expect(titles[titles.length - 1]).toBe(`Doc ${MAX_VIEWS + 5}`)
  })
})
