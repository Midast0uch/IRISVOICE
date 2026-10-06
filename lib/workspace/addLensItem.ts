/**
 * Put a dropped (or "To dashboard") artifact or diff into the dashboard's Workspace Hub
 * as a document card, with its content kept in the tab (not fetched from a path).
 * Uses the hub's own store actions: a tab, a section when there is none, a card.
 */
import { useWorkspaceStore } from "@/stores/workspaceStore"
import type { LensDrag } from "@/lib/lens/dragPayload"

let _n = 0

export function addLensToWorkspace(p: LensDrag): string {
  const st = useWorkspaceStore.getState()
  const stamp = `${Date.now().toString(36)}${(_n++).toString(36)}`
  const tabId = `lens-${stamp}`
  const label = p.title || (p.kind === "diff" ? "Changes" : "Document")
  st.addTab({
    id: tabId,
    type: "document",
    path: p.kind === "artifact" ? `artifact:${p.id}` : `diff:${p.diffs.map((d) => d.diff_id).join(",")}`,
    label,
    icon: "document",
    isVirtual: true,
    content: p.kind === "artifact" ? p.content : undefined,
    format: p.kind === "artifact" ? p.format : undefined,
    diffs: p.kind === "diff" ? p.diffs : undefined,
  })
  let sectionId = useWorkspaceStore.getState().sections[0]?.id
  if (!sectionId) {
    sectionId = "section-dropped"
    st.addSection({ id: sectionId, title: "Dropped here", width: 360, isCollapsed: false, cards: [] })
  }
  st.addCard({
    id: `card-${tabId}`,
    tabId,
    sectionId,
    state: "maximized",
    viewMode: p.kind === "diff" || p.format === "html" || p.format === "json" ? "raw" : "rendered",
    scrollPosition: 0,
  })
  useWorkspaceStore.setState({ showKanban: true })
  return tabId
}
