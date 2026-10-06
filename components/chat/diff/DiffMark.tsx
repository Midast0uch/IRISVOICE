"use client"

/**
 * The ± icon: it appears where an edit happened (a matrix row, a task-card step) and
 * the chip under the reply that sums up the turn's edits. Click opens the review in
 * the lens; drag takes the diff to the dashboard workspace.
 * Look: docs/design/chatview-2026-10-06/iris-strands.html (`.dfx`, `.dchip`).
 */
import React from "react"
import type { EditDiff } from "@/lib/diffs/api"
import { openLens } from "@/lib/lens/lensStore"
import { setLensDrag } from "@/lib/lens/dragPayload"

export const OK = "#5fcf98"
export const BAD = "#ff7a6e"

export function baseName(path: string): string {
  const p = (path || "").replace(/[\\/]+$/, "")
  const i = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"))
  return i >= 0 ? p.slice(i + 1) : p
}

export function diffTitle(diffs: EditDiff[]): string {
  const files = Array.from(new Set(diffs.map((d) => baseName(d.path))))
  return files.length === 1 ? files[0] : `${files.length} files`
}

function startDrag(e: React.DragEvent, diffs: EditDiff[]) {
  setLensDrag(e.dataTransfer, { v: 1, kind: "diff", title: `± ${diffTitle(diffs)}`, diffs })
}

export function DiffMark({ diffs, className = "" }: { diffs: EditDiff[]; className?: string }) {
  if (!diffs.length) return null
  const title = diffTitle(diffs)
  return (
    <button
      type="button"
      data-diff-mark
      draggable
      onDragStart={(e) => startDrag(e, diffs)}
      onClick={(e) => {
        e.stopPropagation()
        openLens({ kind: "diff", diffs, title })
      }}
      className={`iris-dfx flex-none ${className}`}
      title={`Review the change to ${title} (drag to the dashboard)`}
      aria-label={`Review the change to ${title}`}
    >
      ±
    </button>
  )
}

/** "± 2 files changed · router.py +4 −1 · review": the turn's edits in one chip under the reply. */
export function DiffSummaryChip({ diffs }: { diffs: EditDiff[] }) {
  if (!diffs.length) return null
  const added = diffs.reduce((n, d) => n + (d.added || 0), 0)
  const removed = diffs.reduce((n, d) => n + (d.removed || 0), 0)
  const files = new Set(diffs.map((d) => d.path)).size
  const title = diffTitle(diffs)
  return (
    <button
      type="button"
      data-diff-summary
      draggable
      onDragStart={(e) => startDrag(e, diffs)}
      onClick={() => openLens({ kind: "diff", diffs, title })}
      title="Review all changes in this turn"
      className="self-start inline-flex items-center gap-2 rounded-lg px-2.5 py-1.5 font-mono text-[11.5px] leading-none"
      style={{ border: `1px solid ${OK}59`, background: "#080a16", color: "#e6e9f2", cursor: "pointer" }}
    >
      <span style={{ color: OK }}>±</span>
      {files} file{files === 1 ? "" : "s"} changed · {title}
      <span style={{ color: OK }}>+{added}</span>
      <span style={{ color: BAD }}>−{removed}</span>
      <span style={{ color: "rgba(230,233,242,.55)" }}>· review</span>
      <span aria-hidden style={{ color: "rgba(230,233,242,.38)" }}>⠿</span>
    </button>
  )
}

export default DiffMark
