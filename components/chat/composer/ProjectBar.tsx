"use client"

/**
 * The project bar above the message box, in both modes (docs/design/
 * chatview-2026-10-06, "Composer"): the project folder, the open files as
 * tabs, and "+" to add a folder or file.
 *
 * It reads the workspace store the old developer-only bar read, and adds
 * through the same picker (FilePickerModal). No second list of tabs.
 * The branch is omitted: the app knows the branch of its own repo
 * (/api/git/status), not of the folder the user opened.
 */

import React from "react"
import { useWorkspaceStore, type WorkspaceTab } from "@/stores/workspaceStore"
import { FilePickerModal, type PickedItem } from "@/components/workspace/FilePickerModal"

const NO_TABS: WorkspaceTab[] = []

/** A lens tab is a dropped artifact or diff (lib/workspace/addLensItem.ts): a view in the Hub, not a project file. */
const isLensTab = (t: WorkspaceTab) => /^(artifact|diff):/.test(t.path ?? "")

export function ProjectBar() {
  const tabs = useWorkspaceStore((s) => s.tabs) ?? NO_TABS
  const activeTabId = useWorkspaceStore((s) => s.activeTabId)
  const setActiveTab = useWorkspaceStore((s) => s.setActiveTab)
  const addTab = useWorkspaceStore((s) => s.addTab)
  const [picking, setPicking] = React.useState(false)

  const active = tabs.find((t) => t.id === activeTabId)
  const folder = active?.type === "folder" ? active : [...tabs].reverse().find((t) => t.type === "folder")
  const files = tabs.filter((t) => (t.type === "file" || t.type === "document") && !isLensTab(t))

  const onPick = (items: PickedItem[]) =>
    items.forEach((i) =>
      addTab({ id: i.id, label: i.label, type: i.type, path: i.path, icon: i.type, isVirtual: i.isVirtual }),
    )

  return (
    <>
      <div className="iris-proj" role="tablist" aria-label="Project folder and open files" data-testid="project-bar">
        <span className={folder ? "iris-folder" : "iris-folder none"} title="Project folder" data-testid="project-folder">
          ▸ {folder ? folder.label : "no folder"}
        </span>
        {files.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-current={t.id === activeTabId}
            title={t.path}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
        <button type="button" className="iris-addf" title="Add a folder or repo" aria-label="Add a folder or repo" onClick={() => setPicking(true)}>
          +
        </button>
      </div>
      {picking && <FilePickerModal isOpen onClose={() => setPicking(false)} onPick={onPick} />}
    </>
  )
}
