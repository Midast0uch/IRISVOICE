/**
 * Put a dropped (or "To dashboard") artifact or diff into the Workspace Hub's Views lane.
 * A view keeps its content in the store (nothing is fetched from a path). It is NOT a tab
 * and not a project file: the tab bar and the composer's project bar never see it, and the
 * hub's other tools (terminal, tasks, archive, tabs) are left as they are.
 */
import { useWorkspaceStore } from "@/stores/workspaceStore"
import type { LensDrag } from "@/lib/lens/dragPayload"

let _n = 0

export function addLensToWorkspace(p: LensDrag): string {
  const id = `view-${Date.now().toString(36)}${(_n++).toString(36)}`
  useWorkspaceStore.getState().addView({
    id,
    kind: p.kind,
    title: p.title || (p.kind === "diff" ? "Changes" : "Document"),
    format: p.kind === "artifact" ? p.format : undefined,
    content: p.kind === "artifact" ? p.content : undefined,
    diffs: p.kind === "diff" ? p.diffs : undefined,
  })
  return id
}
