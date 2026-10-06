"use client"

/**
 * Draws the open lens over the timeline (mounted by Timeline inside its relative wrapper).
 *   artifact -> the document from the conversation (live: a reformat shows in place);
 *               Pop out = the full-wing document panel (what an artifact opened with
 *               before the lens); To dashboard = a card in the Workspace Hub.
 *   diff     -> DiffReview (Keep / Undo per hunk, wired to diff_undo).
 * Esc closes. A conversation switch closes (the item belonged to the other thread).
 */
import React from "react"
import { RichDocument } from "@/components/chat/RichDocument"
import { DiffReview } from "@/components/chat/diff/DiffReview"
import { Lens } from "@/components/chat/lens/Lens"
import { closeLens, useLens } from "@/lib/lens/lensStore"
import { addLensToWorkspace } from "@/lib/workspace/addLensItem"
import type { SendMessageFn } from "@/lib/diffs/api"
import type { DocRender } from "@/components/chat-view"

export interface LensHostProps {
  documents: DocRender[]
  conversationId: string | null
  sendMessage?: SendMessageFn | null
  glowColor: string
  /** Pop out an artifact: the full-wing document panel. */
  onPopOutDocument?: (docId: string) => void
  requestDocumentBody?: (documentId: string) => void
}

export function LensHost({ documents, conversationId, sendMessage, glowColor, onPopOutDocument, requestDocumentBody }: LensHostProps) {
  const item = useLens()
  const [status, setStatus] = React.useState<string | null>(null)

  React.useEffect(() => {
    setStatus(null)
  }, [item])

  // The item belongs to the thread it was opened in.
  const convRef = React.useRef(conversationId)
  React.useEffect(() => {
    if (convRef.current !== conversationId) closeLens()
    convRef.current = conversationId
  }, [conversationId])

  React.useEffect(() => {
    if (!item) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeLens()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [item])

  const doc = item?.kind === "artifact" ? documents.find((d) => d.id === item.docId) : undefined
  const needsBody = !!doc && !(doc.content || "").trim() && !!doc.documentId
  React.useEffect(() => {
    if (needsBody && doc?.documentId) requestDocumentBody?.(doc.documentId)
  }, [needsBody, doc?.documentId, requestDocumentBody])

  if (!item) return null

  if (item.kind === "diff") {
    const title = `Changes · ${item.title || "this turn"}`
    return (
      <Lens
        title={title}
        onClose={closeLens}
        status={status}
        onToDashboard={() => {
          addLensToWorkspace({ v: 1, kind: "diff", title: `± ${item.title || "Changes"}`, diffs: item.diffs })
          setStatus("Opened in the dashboard workspace.")
        }}
      >
        <DiffReview diffs={item.diffs} sendMessage={sendMessage} />
      </Lens>
    )
  }

  if (!doc) return null
  const title = (doc.title || "").trim() || "Document"
  // A markdown synthesis carries the sources of every document of its turn (as the inline card did).
  const sources =
    doc.format === "markdown" && doc.turnId
      ? documents
          .filter((d) => d.turnId === doc.turnId)
          .flatMap((d) => d.sources || [])
          .filter((s, i, all) => all.findIndex((x) => x.url === s.url) === i)
      : doc.sources
  return (
    <Lens
      title={title}
      onClose={closeLens}
      status={status}
      onPopOut={
        onPopOutDocument
          ? () => {
              closeLens()
              onPopOutDocument(doc.id)
            }
          : undefined
      }
      onToDashboard={() => {
        addLensToWorkspace({ v: 1, kind: "artifact", id: doc.id, title, format: doc.format, content: doc.content || "" })
        setStatus("Opened in the dashboard workspace.")
      }}
    >
      {needsBody ? (
        <p className="text-[12px]" style={{ color: "rgba(230,233,242,.55)" }}>Loading the document…</p>
      ) : (
        <RichDocument
          content={doc.content}
          format={doc.format as "markdown" | "html" | "table" | "diagram" | "text" | "json" | "image"}
          title={doc.title}
          glowColor={glowColor}
          alternatives={doc.alternatives}
          trust={doc.trust}
          onFormatChange={(newFormat) =>
            sendMessage?.("reformat_document", {
              document_id: doc.documentId,
              format: newFormat,
              turn_id: doc.turnId,
              original_format: doc.format,
              trust: doc.trust,
            })
          }
          defaultCollapsed={false}
          sources={sources}
          harPath={doc.harPath}
        />
      )}
    </Lens>
  )
}

export default LensHost
