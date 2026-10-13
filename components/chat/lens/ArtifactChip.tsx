"use client"

/**
 * A compact titled artifact card in the turn: a per-kind icon, title, one-line meta
 * ("document · 120 words · just now"), an Open control, a grip. Click or Enter opens the lens;
 * drag takes the artifact to the dashboard workspace. An image artifact (a screenshot) also
 * shows its picture inline, so the user sees it without opening anything.
 * Look: iris-strands.html (`.art`). Spec: reply-surface.html (R4: icon, title, meta, Open).
 */
import React, { useState } from "react"
import { Code2, FileText, Globe, Image as ImageIcon, Table2, Workflow, type LucideIcon } from "lucide-react"
import { openLens } from "@/lib/lens/lensStore"
import { setLensDrag } from "@/lib/lens/dragPayload"
import { artifactMeta, type MetaDoc } from "@/components/chat/lens/artifactMeta"

export interface ArtifactChipDoc extends MetaDoc {
  id: string
  title?: string
  /** The artifact kind the agent chose (document, code, data, diagram, page, image). */
  kind?: string
  /** Set on a card that came back from history with no body: the image URL is built from it. */
  documentId?: string
  /** The body is still streaming in: the chip shows a "writing…" meta line, not a time. */
  partial?: boolean
}

const OK = "#5fcf98"

/** Icon by the agent's kind; a doc that carries only a render format is mapped from the format. */
const ICON: Record<string, LucideIcon> = {
  image: ImageIcon,
  page: Globe,
  html: Globe,
  document: FileText,
  markdown: FileText,
  text: FileText,
  data: Table2,
  table: Table2,
  json: Table2,
  code: Code2,
  diagram: Workflow,
}

export function artifactKindOf(doc: { kind?: string; format: string }): string {
  return (doc.kind || "").trim().toLowerCase() || doc.format
}

export function ArtifactChip({ doc, note }: { doc: ArtifactChipDoc; note?: string }) {
  const [imgFailed, setImgFailed] = useState(false)
  const kind = artifactKindOf(doc)
  const isImage = kind === "image" || doc.format === "image"
  const title = (doc.title || "").trim() || (isImage ? "Screenshot" : "Document")
  const Icon = ICON[kind] || ICON[doc.format] || FileText
  // The body of an image artifact IS its URL. A card rehydrated from history has no body, so
  // the URL is rebuilt from the document id (same route the live render carries).
  const imageSrc = isImage ? (doc.content || "").trim() || (doc.documentId ? `/api/documents/${doc.documentId}/image` : "") : ""
  // A streaming artifact has no finished time yet: its meta line counts the body as it grows.
  const meta = doc.partial
    ? [artifactMeta({ ...doc, createdAt: undefined }), "writing…"].filter(Boolean).join(" · ")
    : artifactMeta(doc)
  const open = () => openLens({ kind: "artifact", docId: doc.id })
  return (
    <div
      role="button"
      tabIndex={0}
      draggable
      data-artifact-chip={doc.id}
      data-artifact-kind={kind}
      data-artifact-partial={doc.partial ? "true" : undefined}
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
      className="flex min-w-0 flex-col gap-2 px-2.5 py-2"
      style={{ borderRadius: 10, border: `1px solid ${OK}59`, background: "#080a16", cursor: "pointer" }}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          aria-hidden
          data-artifact-icon={kind}
          className="flex-none"
          style={{ display: "grid", placeItems: "center", borderRadius: 7, width: 28, height: 28, background: "rgba(95,207,152,.12)", color: OK }}
        >
          <Icon size={15} strokeWidth={2} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <b className="truncate" style={{ font: "600 13px/1.3 system-ui, sans-serif", color: "#e6e9f2" }}>{title}</b>
          <span className="truncate font-mono" style={{ fontSize: 11, lineHeight: 1.3, color: "rgba(230,233,242,.55)" }} data-artifact-meta>
            {meta}
            {note ? ` · ${note}` : ""}
          </span>
        </span>
        <span
          data-artifact-open
          className="flex-none"
          style={{ borderRadius: 6, border: `1px solid ${OK}59`, color: OK, padding: "2px 8px", font: "600 11px/1.4 system-ui, sans-serif" }}
        >
          Open
        </span>
        <span aria-hidden title="Drag to the dashboard" className="flex-none" style={{ color: "rgba(230,233,242,.38)", fontSize: 14, cursor: "grab" }}>⠿</span>
      </div>
      {isImage && imageSrc && !imgFailed && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          data-artifact-thumb
          src={imageSrc}
          alt={title}
          loading="lazy"
          draggable={false}
          onError={() => setImgFailed(true)}
          className="w-full"
          style={{ maxHeight: 180, objectFit: "cover", objectPosition: "top", borderRadius: 7, border: "1px solid rgba(230,233,242,.12)", display: "block" }}
        />
      )}
      {isImage && imgFailed && (
        <p className="text-[10px] italic" style={{ color: "rgba(230,233,242,.45)" }}>
          The picture could not be loaded. Its stored image is gone or was evicted.
        </p>
      )}
    </div>
  )
}

export default ArtifactChip
