"use client"

/**
 * The composer's two signs (docs/design/chatview-2026-10-06, "Composer").
 *
 *   @  = who hears this      (a "to" chip; only IRIS exists today)
 *   #  = what you point at   (ONE list, two groups: "IRIS made" and "This project")
 *
 * A reference is an ADDRESS (a card id, an artifact id, a strand id, a file
 * path), never the content it points at. The chip shows the address; the send
 * payload carries the addresses.
 */

import React from "react"
import { fetchStrands } from "@/lib/strands/api"
import type { TaskCard } from "@/hooks/useTaskProgress"
import type { WorkspaceTab } from "@/stores/workspaceStore"

export interface ComposerRef {
  /** "#T-38" or "file:backend/router.py": what the payload carries. */
  address: string
  /** "task card · router window test": what the picker shows. */
  label: string
  /** "project" refs are files and folders (path chip); the rest are IRIS made. */
  kind?: "iris" | "project"
  /** Project refs: the path the chip shows. */
  path?: string
  /** Task-card refs: the card to resolve in the gateway (referenced_cards). */
  card?: { cardId: string; conversationId: string }
}

/** A document or artifact shown in this conversation. */
export interface RefDoc {
  id: string
  title: string
}

/** Who can hear a message. Data-driven: people and helpers are added here later.
 *  The list is the SAME in every strand (owner, 2026-10-06): an `@person` or
 *  another agent can be addressed from any strand of any thread. Never filter it
 *  by strand, strand tag ("people" is only a label) or thread root. */
export interface Hearer {
  address: string
  label: string
}
export const WHO_HEARS: Hearer[] = [{ address: "@iris", label: "your agent" }]

/**
 * A "#" or "@" at the caret that should open a list, or null when the sign stays text:
 * it opens only at a word start (not after a letter or digit: `a@b.com`, `C#`), outside
 * inline code (odd backtick count before the caret) and fenced blocks, and not for a
 * "#" at a line start that is followed by a space (a markdown heading).
 */
export interface RefTrigger {
  sign: "#" | "@"
  query: string
  /** Index of the sign; the pick removes text[at .. caret). */
  at: number
}
const TRIGGER = /(^|[\s(])([#@])([^\s#@`]*)$/
export function refTriggerOf(text: string, caret: number): RefTrigger | null {
  const before = text.slice(0, caret)
  const m = TRIGGER.exec(before)
  if (!m) return null
  if (((before.match(/`/g) || []).length) % 2 === 1) return null
  if (((before.match(/```/g) || []).length) % 2 === 1) return null
  const at = before.length - m[2].length - m[3].length
  const lineStart = at === 0 || before[at - 1] === "\n"
  if (m[2] === "#" && lineStart && m[3] === "" && /^\s/.test(text.slice(caret))) return null
  return { sign: m[2] as "#" | "@", query: m[3], at }
}
/** The draft without the sign and query the pick replaces. */
export function withoutTrigger(text: string, t: RefTrigger, caret: number): string {
  return text.slice(0, t.at) + text.slice(caret)
}

const MAX_PER_GROUP = 8

/** A tab that is a real project file or folder (not a dropped artifact or a virtual document). */
const isProjectTab = (t: WorkspaceTab) =>
  (t.type === "file" || t.type === "folder") && !t.isVirtual && !!t.path && !/^(artifact|diff):/.test(t.path)

/**
 * Every address the user can point at, in the picker's two groups.
 * IRIS made: task cards, the artifacts shown in the conversation, the strands of
 * its thread (loaded once per conversation, the first time the list opens).
 * This project: the project folder and the open file tabs of the workspace store.
 * (The app has no folder listing source, so files not open in a tab do not list.)
 */
export function useRefCandidates(opts: {
  conversationId: string | null
  cards: TaskCard[]
  docs: RefDoc[]
  tabs: WorkspaceTab[]
  wanted: boolean
}): { iris: ComposerRef[]; project: ComposerRef[] } {
  const { conversationId, cards, docs, tabs, wanted } = opts
  const [strands, setStrands] = React.useState<{ for: string; list: ComposerRef[] } | null>(null)

  React.useEffect(() => {
    if (!wanted || !conversationId || strands?.for === conversationId) return
    let live = true
    fetchStrands(conversationId)
      .then((rows) => {
        if (!live || !Array.isArray(rows)) return
        setStrands({
          for: conversationId,
          list: rows.map((s) => ({ address: `#${s.id}`, label: `strand · ${s.title || s.id}`, kind: "iris" as const })),
        })
      })
      .catch(() => {
        // Strands are one of three IRIS sources; cards and artifacts still list.
        if (live) setStrands({ for: conversationId, list: [] })
      })
    return () => {
      live = false
    }
  }, [wanted, conversationId, strands?.for])

  const iris = React.useMemo(() => {
    const out: ComposerRef[] = []
    for (const c of cards) {
      out.push({
        address: `#${c.cardId}`,
        label: `task card · ${c.planTitle || c.cardId}`,
        kind: "iris",
        card: { cardId: c.cardId, conversationId: c.conversationId },
      })
    }
    for (const d of docs) out.push({ address: `#${d.id}`, label: `artifact · ${d.title}`, kind: "iris" })
    if (strands && strands.for === conversationId) out.push(...strands.list)
    const seen = new Set<string>()
    return out.filter((r) => (seen.has(r.address) ? false : (seen.add(r.address), true)))
  }, [cards, docs, strands, conversationId])

  const project = React.useMemo(() => {
    const seen = new Set<string>()
    const out: ComposerRef[] = []
    for (const t of tabs) {
      if (!isProjectTab(t)) continue
      const address = `file:${t.path}`
      if (seen.has(address)) continue
      seen.add(address)
      out.push({
        address,
        label: t.type === "folder" ? "folder" : "open file",
        kind: "project",
        path: t.path.replace(/^\.\//, ""),
      })
    }
    return out
  }, [tabs])

  return { iris, project }
}

export interface RefMatches {
  iris: ComposerRef[]
  project: ComposerRef[]
  /** The two groups as the one list the keys walk: IRIS made first. */
  flat: ComposerRef[]
}

/** The candidates the list shows for the typed query, minus the ones already picked. */
export function matchRefs(
  all: { iris: ComposerRef[]; project: ComposerRef[] },
  picked: ComposerRef[],
  query: string,
): RefMatches {
  const q = query.toLowerCase()
  const pick = (list: ComposerRef[]) =>
    list
      .filter((r) => !picked.some((p) => p.address === r.address))
      .filter((r) => !q || `${r.address} ${r.label} ${r.path ?? ""}`.toLowerCase().includes(q))
      .slice(0, MAX_PER_GROUP)
  const iris = pick(all.iris)
  const project = pick(all.project)
  return { iris, project, flat: [...iris, ...project] }
}

/** The people and agents the "@" list shows for the typed query. */
export function matchHearers(query: string): Hearer[] {
  const q = query.toLowerCase()
  return WHO_HEARS.filter((h) => !q || `${h.address} ${h.label}`.toLowerCase().includes(q))
}

/** The tray above the message box: who hears this, the picked references, a hint. */
export function RefTray({
  to,
  onRemoveTo,
  refs,
  onRemove,
}: {
  to: string[]
  onRemoveTo: (address: string) => void
  refs: ComposerRef[]
  onRemove: (address: string) => void
}) {
  return (
    <div className="iris-tray" data-testid="composer-tray">
      <span className="iris-to" title="Who hears this message" data-testid="composer-to">
        to {to[0]}
      </span>
      {to.slice(1).map((w) => (
        <span key={w} className="iris-chip who2" data-testid="composer-who">
          {w}
          <button type="button" aria-label={`Remove ${w}`} onClick={() => onRemoveTo(w)}>
            ×
          </button>
        </span>
      ))}
      {refs.map((r) => (
        <span
          key={r.address}
          className={r.kind === "project" ? "iris-chip path" : "iris-chip"}
          title={r.kind === "project" ? r.address : r.label}
          data-testid="composer-ref"
          data-kind={r.kind ?? "iris"}
        >
          {r.kind === "project" ? r.path : r.address}
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

const mouseDownPick = (fn: () => void) => (e: React.MouseEvent) => {
  // mousedown, not click: the textarea keeps focus.
  e.preventDefault()
  fn()
}

/** The list that opens at a "#": two labelled groups, one keyboard walk. */
export function RefPicker({
  matches,
  folder,
  selected,
  onPick,
}: {
  matches: RefMatches
  folder: string
  selected: number
  onPick: (r: ComposerRef) => void
}) {
  const row = (r: ComposerRef, i: number) => (
    <button
      key={r.address}
      type="button"
      role="option"
      aria-selected={i === selected}
      className={i === selected ? "sel" : undefined}
      onMouseDown={mouseDownPick(() => onPick(r))}
    >
      {r.kind === "project" ? (
        <>
          <b className="p">▸ {r.path!.split("/").pop() || r.path}</b>
          <span>{r.path}</span>
        </>
      ) : (
        <>
          <b>{r.address}</b>
          <span>{r.label}</span>
        </>
      )}
    </button>
  )
  return (
    <div className="iris-pop" role="listbox" aria-label="References" data-testid="ref-picker">
      {matches.iris.length > 0 && (
        <div className="iris-ph" role="presentation" data-testid="ref-group-iris">
          IRIS made<small>cards · artifacts · strands</small>
        </div>
      )}
      {matches.iris.map((r, i) => row(r, i))}
      {matches.project.length > 0 && (
        <div className="iris-ph" role="presentation" data-testid="ref-group-project">
          This project<small>{folder}</small>
        </div>
      )}
      {matches.project.map((r, i) => row(r, matches.iris.length + i))}
    </div>
  )
}

/** The list that opens at an "@": who hears this. */
export function WhoPicker({
  items,
  selected,
  onPick,
}: {
  items: Hearer[]
  selected: number
  onPick: (h: Hearer) => void
}) {
  return (
    <div className="iris-pop" role="listbox" aria-label="Who hears this" data-testid="who-picker">
      <div className="iris-ph" role="presentation">
        Who hears this<small>@</small>
      </div>
      {items.map((h, i) => (
        <button
          key={h.address}
          type="button"
          role="option"
          aria-selected={i === selected}
          className={i === selected ? "sel" : undefined}
          onMouseDown={mouseDownPick(() => onPick(h))}
        >
          <b className="w">{h.address}</b>
          <span>{h.label}</span>
        </button>
      ))}
    </div>
  )
}
