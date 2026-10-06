/**
 * Turn store — the frontend half of the turn protocol (execution audit, Phase 3).
 *
 * The backend sends every turn as `turn.start`, numbered `turn.part` events and
 * exactly one `turn.end` (backend/agent/turn_protocol.py; types generated into
 * ./protocol.ts). This store FILES those messages; it never guesses:
 *
 *  - a turn is keyed by its `turn_id` and filed under the `conversation_id`
 *    the EVENT names — never the conversation that happens to be on screen
 *    (audit bug: chunk/text/plan events were written to the active thread);
 *  - parts are ordered by `seq`, so a delivery reorder on the socket cannot
 *    scramble the text, and a replayed part (reconnect buffer) is ignored;
 *  - `turn.end` carries the authoritative final text and the spoken line;
 *  - a part that arrives before its `turn.start` opens the turn anyway.
 *
 * Same lifetime pattern as hooks/useTaskProgress.ts (REQ-38): a module-level
 * store fed for the whole session, read through useSyncExternalStore, so a
 * panel that unmounts never loses a turn and every reader sees one copy.
 */
import { useSyncExternalStore } from "react"
import type {
  TurnEndPayload,
  TurnMessage,
  TurnPart,
  TurnPartPayload,
  TurnStartPayload,
  TurnStatus,
} from "./protocol"

export type TurnPhase = "running" | TurnStatus

export interface FiledPart {
  seq: number
  part: TurnPart
}

export interface TurnRecord {
  id: string
  conversationId: string
  strandId: string
  author: string
  to: string[]
  refs: string[]
  mode: "personal" | "developer"
  prompt: string
  clientRef?: string
  status: TurnPhase
  startedAt: number
  endedAt?: number
  /** Parts in seq order, one per seq. */
  parts: FiledPart[]
  /** Streamed text (text deltas in seq order); replaced by the final text on turn.end. */
  text: string
  /** Streamed reasoning (reasoning deltas in seq order). */
  reasoning: string
  speak: string
  /** The end's error string (status error/cancelled). Error PARTS are in `parts`. */
  error?: string
  /** Part count the backend reported on turn.end. */
  expectedParts?: number
  /** True when turn.start arrived (false while only parts have been seen). */
  sawStart: boolean
  /** True when turn.end carried the final text (it then wins over the deltas). */
  finalText?: boolean
}

export interface TurnsState {
  byId: Record<string, TurnRecord>
  /** turn ids per conversation, in start order. */
  byConversation: Record<string, string[]>
  /** Counted drops (never silent): parts beyond the cap, duplicates, malformed. */
  dropped: number
}

// Bounds (quality check: memory footprint bounded).
export const MAX_TURNS = 400
export const MAX_PARTS_PER_TURN = 6000

export const EMPTY_TURNS: TurnsState = { byId: {}, byConversation: {}, dropped: 0 }

function now(): number {
  return Date.now()
}

function blankTurn(turnId: string, conversationId: string, ts?: number): TurnRecord {
  return {
    id: turnId,
    conversationId,
    strandId: conversationId,
    author: "user",
    to: ["@iris"],
    refs: [],
    mode: "personal",
    prompt: "",
    status: "running",
    startedAt: typeof ts === "number" ? ts * 1000 : now(),
    parts: [],
    text: "",
    reasoning: "",
    speak: "",
    sawStart: false,
  }
}

function joinDeltas(parts: FiledPart[], type: "text" | "reasoning"): string {
  let out = ""
  for (const p of parts) if (p.part.type === type) out += (p.part as { delta: string }).delta
  return out
}

function withTurn(state: TurnsState, turn: TurnRecord): TurnsState {
  const exists = !!state.byId[turn.id]
  const byId = { ...state.byId, [turn.id]: turn }
  let byConversation = state.byConversation
  if (!exists) {
    const list = byConversation[turn.conversationId] || []
    byConversation = { ...byConversation, [turn.conversationId]: [...list, turn.id] }
  }
  let next: TurnsState = { ...state, byId, byConversation }
  // Evict the oldest ENDED turns past the cap (a running turn is never evicted).
  const ids = Object.keys(next.byId)
  if (ids.length > MAX_TURNS) {
    const ended = ids
      .map((id) => next.byId[id])
      .filter((t) => t.status !== "running")
      .sort((a, b) => a.startedAt - b.startedAt)
    const evict = new Set(ended.slice(0, ids.length - MAX_TURNS).map((t) => t.id))
    if (evict.size) {
      const byId2: Record<string, TurnRecord> = {}
      for (const id of ids) if (!evict.has(id)) byId2[id] = next.byId[id]
      const byConv2: Record<string, string[]> = {}
      for (const [cid, list] of Object.entries(next.byConversation)) {
        const kept = list.filter((id) => !evict.has(id))
        if (kept.length) byConv2[cid] = kept
      }
      next = { ...next, byId: byId2, byConversation: byConv2 }
    }
  }
  return next
}

function applyStart(state: TurnsState, p: TurnStartPayload): TurnsState {
  if (!p || !p.turn_id || !p.conversation_id) return { ...state, dropped: state.dropped + 1 }
  const prev = state.byId[p.turn_id] || blankTurn(p.turn_id, p.conversation_id, p.ts)
  if (prev.sawStart) return state // replayed start
  const turn: TurnRecord = {
    ...prev,
    conversationId: prev.parts.length ? prev.conversationId : p.conversation_id,
    strandId: p.strand_id || p.conversation_id,
    author: p.author || "user",
    to: Array.isArray(p.to) && p.to.length ? p.to : ["@iris"],
    refs: Array.isArray(p.refs) ? p.refs : [],
    mode: p.mode === "developer" ? "developer" : "personal",
    prompt: p.prompt || "",
    clientRef: p.client_ref,
    startedAt: typeof p.ts === "number" ? p.ts * 1000 : prev.startedAt,
    sawStart: true,
  }
  return withTurn(state, turn)
}

function applyPart(state: TurnsState, p: TurnPartPayload): TurnsState {
  if (!p || !p.turn_id || !p.conversation_id || typeof p.seq !== "number" || !p.part) {
    return { ...state, dropped: state.dropped + 1 }
  }
  const prev = state.byId[p.turn_id] || blankTurn(p.turn_id, p.conversation_id, p.ts)
  if (prev.expectedParts !== undefined && p.seq > prev.expectedParts) {
    return { ...state, dropped: state.dropped + 1 }
  }
  if (prev.parts.length >= MAX_PARTS_PER_TURN) return { ...state, dropped: state.dropped + 1 }
  // Insert in seq order; a seq we already hold is a replay -> ignore.
  const parts = prev.parts
  const last = parts.length ? parts[parts.length - 1].seq : 0
  let nextParts: FiledPart[]
  let appended = false
  if (p.seq > last) {
    nextParts = [...parts, { seq: p.seq, part: p.part }]
    appended = true
  } else {
    if (parts.some((x) => x.seq === p.seq)) return state
    nextParts = [...parts, { seq: p.seq, part: p.part }].sort((a, b) => a.seq - b.seq)
  }
  let text = prev.text
  let reasoning = prev.reasoning
  if (p.part.type === "text" && !prev.finalText) {
    // A late delta (after an end that carried no final text) still belongs in place.
    text = appended ? prev.text + p.part.delta : joinDeltas(nextParts, "text")
  } else if (p.part.type === "reasoning") {
    reasoning = appended ? prev.reasoning + p.part.delta : joinDeltas(nextParts, "reasoning")
  }
  return withTurn(state, { ...prev, parts: nextParts, text, reasoning })
}

function applyEnd(state: TurnsState, p: TurnEndPayload): TurnsState {
  if (!p || !p.turn_id || !p.conversation_id) return { ...state, dropped: state.dropped + 1 }
  const prev = state.byId[p.turn_id] || blankTurn(p.turn_id, p.conversation_id, p.ts)
  if (prev.status !== "running") return state // exactly one end: a replayed end changes nothing
  const status: TurnStatus = p.status === "error" || p.status === "cancelled" ? p.status : "ok"
  const hasFinal = typeof p.text === "string" && p.text.length > 0
  return withTurn(state, {
    ...prev,
    status,
    finalText: hasFinal,
    endedAt: typeof p.ts === "number" ? p.ts * 1000 : now(),
    text: hasFinal ? p.text : prev.text,
    speak: p.speak || "",
    error: p.error,
    expectedParts: typeof p.parts === "number" ? p.parts : undefined,
  })
}

/** Pure reducer: apply one wire message. Exported for tests and replay. */
export function reduceTurnMessage(state: TurnsState, msg: TurnMessage): TurnsState {
  switch (msg?.type) {
    case "turn.start":
      return applyStart(state, msg.payload)
    case "turn.part":
      return applyPart(state, msg.payload)
    case "turn.end":
      return applyEnd(state, msg.payload)
    default:
      return { ...state, dropped: state.dropped + 1 }
  }
}

/**
 * `turn.end` messages for every turn still running: used when the backend
 * process changed under an open page (its `boot_id` on initial_state differs),
 * because a restarted backend never sends the end of a turn it lost. Each end
 * is an error the chat shows; `parts` = what arrived, so nothing is awaited.
 */
export function endsForLostTurns(state: TurnsState, reason: string): TurnMessage[] {
  return Object.values(state.byId)
    .filter((t) => t.status === "running")
    .map((t) => ({
      type: "turn.end",
      payload: {
        v: 1, turn_id: t.id, conversation_id: t.conversationId, status: "error",
        parts: t.parts.length, text: t.text, speak: "", error: reason, ts: Date.now() / 1000,
      },
    }) as unknown as TurnMessage)
}

export function isTurnMessageType(type: unknown): type is TurnMessage["type"] {
  return type === "turn.start" || type === "turn.part" || type === "turn.end"
}

/** The turns of one conversation, in start order. */
export function selectConversationTurns(state: TurnsState, conversationId: string | null | undefined): TurnRecord[] {
  if (!conversationId) return []
  return (state.byConversation[conversationId] || []).map((id) => state.byId[id]).filter(Boolean)
}

/** Parts of one type, in seq order. */
export function partsOf<T extends TurnPart["type"]>(turn: TurnRecord, type: T): Array<Extract<TurnPart, { type: T }>> {
  return turn.parts.filter((p) => p.part.type === type).map((p) => p.part as Extract<TurnPart, { type: T }>)
}

// ── module-level store ───────────────────────────────────────────────────────
let _state: TurnsState = EMPTY_TURNS
const _subscribers = new Set<() => void>()
const _convCache = new Map<string, { state: TurnsState; turns: TurnRecord[] }>()

function _notify(): void {
  _subscribers.forEach((fn) => {
    try {
      fn()
    } catch {
      /* a bad subscriber must not stop the others */
    }
  })
}

/** Feed one wire message ({type, payload}) into the store. */
export function applyTurnMessage(msg: TurnMessage): void {
  const next = reduceTurnMessage(_state, msg)
  if (next === _state) return
  _state = next
  _notify()
}

export function getTurnsState(): TurnsState {
  return _state
}

export function subscribeTurns(fn: () => void): () => void {
  _subscribers.add(fn)
  return () => {
    _subscribers.delete(fn)
  }
}

/** Stable per-conversation snapshot (useSyncExternalStore needs a stable reference). */
export function getConversationTurns(conversationId: string | null | undefined): TurnRecord[] {
  const key = conversationId || ""
  const hit = _convCache.get(key)
  if (hit && hit.state === _state) return hit.turns
  const turns = selectConversationTurns(_state, conversationId)
  // Keep the old array when nothing in this conversation changed.
  if (hit && hit.turns.length === turns.length && hit.turns.every((t, i) => t === turns[i])) {
    _convCache.set(key, { state: _state, turns: hit.turns })
    return hit.turns
  }
  _convCache.set(key, { state: _state, turns })
  if (_convCache.size > 64) _convCache.delete(_convCache.keys().next().value as string)
  return turns
}

const EMPTY: TurnRecord[] = []

/** React hook: the live turns of a conversation. */
export function useConversationTurns(conversationId: string | null | undefined): TurnRecord[] {
  return useSyncExternalStore(
    subscribeTurns,
    () => getConversationTurns(conversationId),
    () => EMPTY,
  )
}

/** React hook: one turn by id (undefined until its first message). */
export function useTurn(turnId: string | null | undefined): TurnRecord | undefined {
  return useSyncExternalStore(
    subscribeTurns,
    () => (turnId ? _state.byId[turnId] : undefined),
    () => undefined,
  )
}

/** Test-only seam. Production never calls it. */
export function __resetTurnsForTests(): void {
  _state = EMPTY_TURNS
  _convCache.clear()
}
