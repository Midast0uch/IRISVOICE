/**
 * What a dragged artifact or diff carries to the dashboard workspace.
 *
 * The payload travels in the drag itself (not as an id the other side must look up):
 * the dashboard may be a different window, which has no copy of the chat's store.
 * Bounded: an artifact body over MAX_BODY is cut and says so.
 */
import type { EditDiff } from "@/lib/diffs/api"

export const LENS_MIME = "application/x-iris-lens"
export const MAX_DRAG_BODY = 200_000

export type LensDrag =
  | { v: 1; kind: "artifact"; id: string; title: string; format: string; content: string; truncated?: boolean }
  | { v: 1; kind: "diff"; title: string; diffs: EditDiff[] }

type DT = Pick<DataTransfer, "setData" | "getData"> & { effectAllowed?: string }

export function setLensDrag(dt: DT | null | undefined, payload: LensDrag): void {
  if (!dt) return
  let p = payload
  if (p.kind === "artifact" && p.content.length > MAX_DRAG_BODY) {
    p = { ...p, content: p.content.slice(0, MAX_DRAG_BODY), truncated: true }
  }
  try {
    dt.setData(LENS_MIME, JSON.stringify(p))
    dt.setData("text/plain", p.title)
    dt.effectAllowed = "copy"
  } catch {
    /* a drag that cannot carry data simply drops nothing */
  }
}

export function readLensDrop(dt: Pick<DataTransfer, "getData"> | null | undefined): LensDrag | null {
  if (!dt) return null
  try {
    const raw = dt.getData(LENS_MIME)
    if (!raw) return null
    const p = JSON.parse(raw) as LensDrag
    if (p && p.v === 1 && (p.kind === "artifact" || p.kind === "diff")) return p
  } catch {
    /* not ours */
  }
  return null
}

export function hasLensDrag(dt: Pick<DataTransfer, "types"> | null | undefined): boolean {
  return !!dt && Array.from(dt.types || []).includes(LENS_MIME)
}
