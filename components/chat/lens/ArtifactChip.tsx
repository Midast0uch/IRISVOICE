"use client"

/**
 * A compact titled artifact card in the turn: icon, title, one-line meta
 * ("document · 120 words · just now"), a grip. Click or Enter opens the lens;
 * drag takes the artifact to the dashboard workspace.
 * Look: iris-strands.html (`.art`).
 */
import React from "react"
import { openLens } from "@/lib/lens/lensStore"
import { setLensDrag } from "@/lib/lens/dragPayload"
import { artifactMeta, type MetaDoc } from "@/components/chat/lens/artifactMeta"

export interface ArtifactChipDoc extends MetaDoc {
  id: string
  title?: string
}

const OK = "#5fcf98"

export function ArtifactChip({ doc, note }: { doc: ArtifactChipDoc; note?: string }) {
  const title = (doc.title || "").trim() || "Document"
  const open = () => openLens({ kind: "artifact", docId: doc.id })
  return (
    <div
      role="button"
      tabIndex={0}
      draggable
      data-artifact-chip={doc.id}
      aria-label={`Open ${title}`}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          open()
        }
      }}
      onDragStart={(e) =>
        setLensDrag(e.dataTransfer, { v: 1, kind: "artifact", id: doc.id, title, format: doc.format, content: doc.content || "" })
      }
      className="flex min-w-0 items-center gap-2.5 px-2.5 py-2"
      style={{ borderRadius: 10, border: `1px solid ${OK}59`, background: "#080a16", cursor: "pointer" }}
    >
      <span
        aria-hidden
        className="flex-none font-mono"
        style={{ display: "grid", placeItems: "center", borderRadius: 7, width: 28, height: 28, background: "rgba(95,207,152,.12)", color: OK, fontSize: 12, fontWeight: 600 }}
      >
        ≡
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <b className="truncate" style={{ font: "600 13px/1.3 system-ui, sans-serif", color: "#e6e9f2" }}>{title}</b>
        <span className="truncate font-mono" style={{ fontSize: 11, lineHeight: 1.3, color: "rgba(230,233,242,.55)" }} data-artifact-meta>
          {artifactMeta(doc)}
          {note ? ` · ${note}` : ""}
        </span>
      </span>
      <span aria-hidden title="Drag to the dashboard" className="flex-none" style={{ color: "rgba(230,233,242,.38)", fontSize: 14, cursor: "grab" }}>⠿</span>
    </div>
  )
}

export default ArtifactChip
