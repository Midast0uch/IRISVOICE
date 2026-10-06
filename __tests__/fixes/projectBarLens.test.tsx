/**
 * Owner fix 4 (2026-10-06): the composer's project bar lists only real project folders and files.
 * (Owner-approved requirement change, rev 4: a dropped artifact or diff is a VIEW in the Hub's Views
 * lane, never a tab.)
 */
import React from "react"
import { render, screen } from "@testing-library/react"
import "@testing-library/jest-dom"
import { ProjectBar } from "@/components/chat/composer/ProjectBar"
import { useWorkspaceStore } from "@/stores/workspaceStore"
import { addLensToWorkspace } from "@/lib/workspace/addLensItem"
import { oneHunkDiff } from "../turnui/harness"

beforeEach(() => {
  useWorkspaceStore.setState({ tabs: [], sections: [], archived: [], activeTabId: null, showKanban: true, views: [] })
})

describe("the project bar ignores lens tabs", () => {
  it("lists the project folder and files, not a dropped artifact or diff", () => {
    const st = useWorkspaceStore.getState()
    st.addTab({ id: "f1", type: "folder", path: "C:/dev/IRISVOICE", label: "IRISVOICE", icon: "folder" })
    st.addTab({ id: "f2", type: "file", path: "C:/dev/IRISVOICE/router.py", label: "router.py", icon: "file" })
    addLensToWorkspace({ v: 1, kind: "artifact", id: "doc-1", title: "Plan.md", format: "markdown", content: "hello" })
    addLensToWorkspace({ v: 1, kind: "diff", title: "± router.py", diffs: [oneHunkDiff()] })

    render(<ProjectBar />)

    expect(screen.getByTestId("project-folder")).toHaveTextContent("IRISVOICE")
    expect(screen.getByRole("tab", { name: "router.py" })).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "Plan.md" })).toBeNull()
    expect(screen.queryByRole("tab", { name: "± router.py" })).toBeNull()
    expect(screen.getAllByRole("tab")).toHaveLength(1)
  })

  it("the Hub keeps the dropped artifact as a view, not a tab or a card", () => {
    addLensToWorkspace({ v: 1, kind: "artifact", id: "doc-1", title: "Plan.md", format: "markdown", content: "hello" })
    render(<ProjectBar />)
    const s = useWorkspaceStore.getState()
    // Owner-approved requirement change (rev 4): a view, no tab and no section card.
    expect(s.views.some((v) => v.kind === "artifact" && v.title === "Plan.md")).toBe(true)
    expect(s.tabs).toHaveLength(0)
    expect(s.sections.flatMap((x) => x.cards)).toHaveLength(0)
    expect(screen.queryAllByRole("tab")).toHaveLength(0)
  })
})
