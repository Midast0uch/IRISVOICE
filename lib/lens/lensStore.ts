/**
 * The lens: what is open over the timeline of the chat wing (an artifact, or the
 * review of an edit). One item at a time. Module-level store (same pattern as the
 * turn store) so a ± mark deep in a matrix row can open it without prop drilling;
 * `LensHost` (components/chat/lens) is the one reader that draws it.
 *
 * An artifact is opened BY ID and resolved live from the conversation's documents,
 * so a reformat or update shows in place. A diff review carries its diffs.
 */
import { useSyncExternalStore } from "react"
import type { EditDiff } from "@/lib/diffs/api"

export type LensItem =
  | { kind: "artifact"; docId: string }
  | { kind: "diff"; diffs: EditDiff[]; title?: string }

let _item: LensItem | null = null
const _subs = new Set<() => void>()

function _notify(): void {
  _subs.forEach((fn) => {
    try {
      fn()
    } catch {
      /* a bad subscriber must not stop the others */
    }
  })
}

export function openLens(item: LensItem): void {
  _item = item
  _notify()
}

export function closeLens(): void {
  if (_item === null) return
  _item = null
  _notify()
}

export function getLens(): LensItem | null {
  return _item
}

export function subscribeLens(fn: () => void): () => void {
  _subs.add(fn)
  return () => {
    _subs.delete(fn)
  }
}

export function useLens(): LensItem | null {
  return useSyncExternalStore(subscribeLens, getLens, () => null)
}
