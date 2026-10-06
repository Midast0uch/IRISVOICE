/**
 * Shared fixtures for the in-turn interaction tests (__tests__/turnui).
 * Payloads are shaped exactly like the backend sends them:
 *   - a diff: backend/tests/contract/test_edit_diff_contract.py
 *     (`edit_file` of "three" -> "THREE" in a five-line file)
 *   - turn parts: backend/agent/turn_protocol.py (`route_bus_event`)
 *   - permission / question asks: backend/agent/permissions.py, tools/ask_user_tool.py
 */
import React from "react"
import { render } from "@testing-library/react"
import { Timeline } from "@/components/chat/Timeline"
import { EMPTY_TURNS, reduceTurnMessage, type TurnRecord, type TurnsState } from "@/lib/turns/turnStore"
import type { TurnMessage } from "@/lib/turns/protocol"
import type { EditDiff } from "@/lib/diffs/api"
import type { TaskCard } from "@/hooks/useTaskProgress"

export const GLOW = "#00d4ff"
export const CONV = "conv-1"
export const TURN = "turn-1"

/** The diff the backend contract test asserts for `edit_file(three -> THREE)`. */
export function oneHunkDiff(over: Partial<EditDiff> = {}): EditDiff {
  return {
    diff_id: "d-one",
    path: "/work/router.py",
    added: 1,
    removed: 1,
    hunks: [{ header: "@@ -1,5 +1,5 @@", lines: [" one", " two", "-three", "+THREE", " four", " five"] }],
    truncated: false,
    undoable: true,
    ...over,
  }
}

/** Two separate hunks in one file (the contract's `_two_hunk_edit` shape). */
export function twoHunkDiff(over: Partial<EditDiff> = {}): EditDiff {
  return {
    diff_id: "d-two",
    path: "/work/cap.py",
    added: 2,
    removed: 2,
    hunks: [
      { header: "@@ -1,4 +1,4 @@", lines: [" a", "-b", "+B", " c", " d"] },
      { header: "@@ -20,4 +20,4 @@", lines: [" x", "-y", "+Y", " z"] },
    ],
    truncated: false,
    undoable: true,
    ...over,
  }
}

export function msg(type: TurnMessage["type"], payload: Record<string, unknown>): TurnMessage {
  return { type, payload: { v: 1, turn_id: TURN, conversation_id: CONV, ...payload } } as unknown as TurnMessage
}

export function reduce(msgs: TurnMessage[], s: TurnsState = EMPTY_TURNS): TurnsState {
  return msgs.reduce(reduceTurnMessage, s)
}

let _seq = 0
export function part(p: Record<string, unknown>): TurnMessage {
  return msg("turn.part", { seq: ++_seq, ts: 1790000000 + _seq, part: p })
}

export function startMsg(mode: "personal" | "developer" = "developer"): TurnMessage {
  _seq = 0
  return msg("turn.start", { strand_id: CONV, author: "user", to: ["@iris"], refs: [], mode, prompt: "fix the cap", ts: 1790000000 })
}

export function turnOf(msgs: TurnMessage[]): TurnRecord {
  return reduce(msgs).byId[TURN]
}

export function editResultPart(diff: EditDiff | EditDiff[]): TurnMessage {
  const list = Array.isArray(diff) ? diff : [diff]
  return part({
    type: "tool_result",
    name: "edit_file",
    call_id: "e1",
    ok: true,
    data: { tool: "edit_file", call_id: "e1", success: true, turn_id: TURN, diff: list[list.length - 1], ...(list.length > 1 ? { diffs: list } : {}) },
  })
}

export function permissionRequestPart(over: Record<string, unknown> = {}): TurnMessage {
  return part({
    type: "interaction",
    event: "permission:request",
    data: {
      request_id: "perm-1",
      tool_name: "run_command",
      tier: "side_effect",
      params: { command: "pytest -q tests/unit/test_router.py" },
      description: "Execute run_command",
      timeout_seconds: 30,
      requires_confirmation: false,
      ...over,
    },
  })
}

export function questionAskPart(over: Record<string, unknown> = {}): TurnMessage {
  return part({
    type: "interaction",
    event: "question:ask",
    data: { question_id: "q_1", text: "Keep the reserve at 256?", options: ["Keep it", "Change it"], allow_other: false, timeout_seconds: 120, turn_id: TURN, ...over },
  })
}

/** A task card as the card store builds it. */
export function card(steps: Array<Record<string, unknown>>, extra: Record<string, unknown> = {}): TaskCard {
  return {
    cardId: "card-1",
    conversationId: CONV,
    turnId: TURN,
    responseTurnId: TURN,
    isWorking: true,
    currentStep: 0,
    totalSteps: steps.length,
    planTitle: "Fix the cap",
    steps: steps.map((s, i) => ({ seq: i + 1, ...s })),
    ...extra,
  } as unknown as TaskCard
}

export interface MountOpts {
  isDeveloper: boolean
  turn: TurnRecord
  card?: TaskCard
  documents?: Array<Record<string, unknown>>
  sendMessage?: jest.Mock
  removePendingPermission?: jest.Mock
  removePendingQuestion?: jest.Mock
  pendingPermissions?: Map<string, unknown>
  pendingQuestions?: Map<string, unknown>
  setExpandedDocId?: jest.Mock
  conversationId?: string
}

/** The real Timeline, fed one turn: its prompt, the assistant message (id = turn id) and optionally its card. */
export function mountTimeline(o: MountOpts) {
  const user = { id: "u1", text: "fix the cap", sender: "user", timestamp: new Date(1000) }
  const reply = { id: TURN, turn_id: TURN, text: o.turn.text || "On it.", sender: "assistant", timestamp: new Date(2000) }
  const entries: any[] = [
    { kind: "message", ts: 1000, message: user, index: 0 },
    { kind: "message", ts: 2000, message: reply, index: 1 },
  ]
  if (o.card) entries.push({ kind: "card", ts: 2000, card: o.card })
  const conv = {
    id: o.conversationId ?? CONV,
    title: "t",
    preview: "",
    messages: [user, reply],
    documents: (o.documents ?? []) as any[],
    timestamp: new Date(),
    isPinned: false,
    lastMessagePreview: "",
  }
  const fn = () => jest.fn()
  const props: any = {
    renderTimeline: entries,
    messages: conv.messages,
    messagesContainerRef: React.createRef(),
    messagesEndRef: React.createRef(),
    pinnedToBottomRef: { current: true },
    setShowJumpToLatest: fn(),
    isTyping: false,
    taskProgressStillRunning: false,
    awaitingFirstBlock: false,
    matrixElapsedSec: 5,
    pendingPermissions: o.pendingPermissions ?? new Map(),
    removePendingPermission: o.removePendingPermission ?? fn(),
    removePendingQuestion: o.removePendingQuestion ?? fn(),
    isDeveloper: o.isDeveloper,
    glowColor: GLOW,
    fontColor: "#fff",
    prefersReducedMotion: true,
    sendMessage: o.sendMessage ?? jest.fn(() => true),
    conversations: [conv],
    activeConversation: conv,
    activeConversationId: conv.id,
    anchoredQuestionIds: new Set<string>(),
    pendingQuestions: o.pendingQuestions ?? new Map(),
    questionCardFor: (q: { questionId: string; text: string }) => <div key={q.questionId} data-legacy-question={q.questionId}>{q.text}</div>,
    liveTurnById: new Map([[o.turn.id, o.turn]]),
    taskProgress: { turnId: undefined, steps: [], currentStep: 0, totalSteps: 0, isWorking: false, cards: [] },
    crawlState: { sources: [] },
    copiedMessageId: null,
    currentTtsMessageId: null,
    ttsWordIndex: -1,
    isSpeaking: false,
    editingMessageId: null,
    setEditingMessageId: fn(),
    editingText: "",
    setEditingText: fn(),
    retryingMessageId: null,
    expandedThinking: new Set<string>(),
    setExpandedThinking: fn(),
    setDocumentModalMessage: fn(),
    setExpandedDocId: o.setExpandedDocId ?? fn(),
    getContentType: () => "text",
    isMessageExpanded: () => true,
    toggleMessageExpanded: fn(),
    handleCopyMessage: fn(),
    handleFeedback: fn(),
    handlePlayTTSClick: fn(),
    handleShareMessage: fn(),
    handleDownloadMessage: fn(),
    handleResendUserMessage: fn(),
    handleRetryPrompt: fn(),
    renderWithLinks: (t: string) => t,
    requestDocumentBody: fn(),
    conversationChips: [],
    handleChipClick: fn(),
  }
  return { props, ...render(<Timeline {...props} />) }
}
