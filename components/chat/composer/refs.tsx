"use client"

/**
 * The composer's # references (docs/design/chatview-2026-10-06, "Composer").
 *
 * A reference is an ADDRESS (a card id, an artifact id, a strand id), never the
 * content it points at. The chip shows the address; the send payload carries
 * the addresses; IRIS loads the content from memory by address.
 */

import React from "react"
import { fetchStrands } from "@/lib/strands/api"
import type { TaskCard } from "@/hooks/useTaskProgress"

export interface ComposerRef {
  /** "#T-38" — what the payload carries. */
  address: string
  /** "task card · router window test" — what the picker shows. */
  label: string
}

/** A document or artifact shown in this conversation. */
export interface RefDoc {
  id: string
  title: string
}

/** The "#query" at the end of the draft, or null when the draft does not end in one. */
const HASH_AT_END = /(^|\s)#([^\s#]*)$/
export function hashQueryOf(text: string): string | null {
  const m = HASH_AT_END.exec(text)
  return m ? m[2] : null
}
export function withoutHashQuery(text: string): string {
  return text.replace(HASH_AT_END, "$1")
}

const MAX_SHOWN = 12

/**
 * Every address the user can reference from this conversation: its task cards,
 * the artifacts shown in it, and the strands of its thread. Strands load once
 * per conversation, on the first time the picker opens (`wanted`).
 */
export function useRefCandidates(opts: {
  conversationId: string | null
  cards: TaskCard[]
  docs: RefDoc[]
  wanted: boolean
}): ComposerRef[] {
  const { conversationId, cards, docs, wanted } = opts
  const [strands, setStrands] = React.useState<{ for: string; list: ComposerRef[] } | null>(null)

  React.useEffect(() => {
    if (!wanted || !conversationId || strands?.for === conversationId) return
    let live = true
    fetchStrands(conversationId)
      .then((rows) => {
        if (!live || !Array.isArray(rows)) return
        setStrands({
          for: conversationId,
          list: rows.map((s) => ({ address: `#${s.id}`, label: `strand · ${s.title || s.id}` })),
        })
      })
      .catch(() => {
        // Strands are one of three sources; cards and artifacts still list.
        if (live) setStrands({ for: conversationId, list: [] })
      })
    return () => {
      live = false
    }
  }, [wanted, conversationId, strands?.for])

  return React.useMemo(() => {
    const out: ComposerRef[] = []
    for (const c of cards) {
      if (c.conversationId === conversationId) {
        out.push({ address: `#${c.cardId}`, label: `task card · ${c.planTitle || c.cardId}` })
      }
    }
    for (const d of docs) out.push({ address: `#${d.id}`, label: `artifact · ${d.title}` })
    if (strands && strands.for === conversationId) out.push(...strands.list)
    const seen = new Set<string>()
    return out.filter((r) => (seen.has(r.address) ? false : (seen.add(r.address), true)))
  }, [cards, docs, strands, conversationId])
}

/** The candidates the picker lists for the typed query, minus the ones already picked. */
export function matchRefs(all: ComposerRef[], picked: ComposerRef[], query: string): ComposerRef[] {
  const q = query.toLowerCase()
  return all
    .filter((r) => !picked.some((p) => p.address === r.address))
    .filter((r) => !q || r.address.toLowerCase().includes(q) || r.label.toLowerCase().includes(q))
    .slice(0, MAX_SHOWN)
}

/** The tray above the message box: who hears this, the picked references, a hint. */
export function RefTray({
  refs,
  onRemove,
}: {
  refs: ComposerRef[]
  onRemove: (address: string) => void
}) {
  return (
    <div className="iris-tray" data-testid="composer-tray">
      {/* People and peers are not built yet: only IRIS hears. */}
      <span className="iris-to" title="Who hears this message" data-testid="composer-to">
        to @iris
      </span>
      {refs.map((r) => (
        <span key={r.address} className="iris-chip" title={r.label} data-testid="composer-ref">
          {r.address}
          <button type="button" aria-label={`Remove ${r.address}`} onClick={() => onRemove(r.address)}>
            ×
          </button>
        </span>
      ))}
      <span className="iris-hint">
        {refs.length ? "IRIS gets these addresses" : "# adds a reference · @ picks who hears"}
      </span>
    </div>
  )
}

/** The small picker that opens when the draft ends in "#". */
export function RefPicker({
  items,
  selected,
  onPick,
}: {
  items: ComposerRef[]
  selected: number
  onPick: (r: ComposerRef) => void
}) {
  return (
    <div className="iris-pop" role="listbox" aria-label="References" data-testid="ref-picker">
      {items.map((r, i) => (
        <button
          key={r.address}
          type="button"
          role="option"
          aria-selected={i === selected}
          className={i === selected ? "sel" : undefined}
          // mousedown, not click: the textarea keeps focus.
          onMouseDown={(e) => {
            e.preventDefault()
            onPick(r)
          }}
        >
          <b>{r.address}</b>
          <span>{r.label}</span>
        </button>
      ))}
    </div>
  )
}
