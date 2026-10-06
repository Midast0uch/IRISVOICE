"use client"

import React, { useState, useEffect, useRef, useCallback, useMemo, useSyncExternalStore } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Copy, Download, Share, FileText, Mail, Video, Image, File, Archive } from 'lucide-react';
import { Icon } from '@iconify/react';
import { Xur } from "@/components/Xur";
import { useNavigation } from "@/contexts/NavigationContext";
import { useBrandColor } from "@/contexts/BrandColorContext";
import { SendMessageFunction } from "@/hooks/useIRISWebSocket";
import { mergeRenderedDocuments } from "@/lib/documentMerge";
import { formatPlanEventMessage } from "@/components/chat/planEventMessage";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { SpotlightState, SpotlightStateType } from "@/hooks/useUILayoutState";
import { useLauncherMode } from "@/hooks/useLauncherMode";
import {
  computeFrame,
  chatWidth,
  frameLeft,
  TILT_DEG,
  type SpotlightStr,
} from "@/lib/orbWingGeometry";
// Phase 3 (turn protocol): live turns come from the turn store, filed by the
// conversation each event names; TurnParts draws reasoning / notices / errors.
import { useConversationTurns, getTurnsState, type TurnRecord } from "@/lib/turns/turnStore";
import { mergeLiveTurns } from "@/lib/turns/mergeTurns";
import { TurnParts } from "@/components/chat/turn/TurnParts";

// Lazy-load entire workspace — only bundles in developer mode
// (cli-workspace-unification T1: ChatView no longer replaces its body with the
// workspace in dev mode — the unified scroll IS the dev-mode body. The Visual
// Workspace Hub lives in the Dashboard Wing, not here.)
import { Composer } from "@/components/chat/Composer";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { NotificationsPanel } from "@/components/chat/NotificationsPanel";
import { HistoryPanel } from "@/components/chat/HistoryPanel";
import { Timeline } from "@/components/chat/Timeline";
import { QuestionCard } from "@/components/chat/QuestionCard";
// cli-workspace-unification T5/T6 (REQ-4): project folder bar + archive dock
import { WorkspaceTabBar } from "@/components/workspace/WorkspaceTabBar";
import { ArchiveDock } from "@/components/workspace/ArchiveDock";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import type { TaskCard } from "@/hooks/useTaskProgress";
import { buildChatTimeline } from "@/lib/chatview-turn-timeline";
import { logStructured } from "@/lib/logger";
import {
  subscribe as subscribeTerminal,
  getSnapshot as getTerminalSnapshot,
  toggleOpen as toggleTerminalOpen,
  appendCommand,
  appendOutput,
  appendSystem,
  clear as clearTerminal,
  resolveTerminalAnswer,
  TERMINAL_HELP,
  // Gate 3 T10/T11/T14
  recordHistory,
  resetRecall,
  loadHistory,
  setWorkdir as setTerminalWorkdir,
} from "@/components/terminal/terminalScrollback";
import { RichDocument } from "@/components/chat/RichDocument";
import { DocumentPanel } from "@/components/chat/DocumentPanel";
import { useManualDragWindow } from "@/hooks/useManualDragWindow"
import { useTaskProgress } from "@/hooks/useTaskProgress";
import { useCrawlContext } from "@/hooks/CrawlProvider";
import type { ConversationChip, Suggestion } from "@/types/iris";

// Notification types for the universal notification system
export interface Notification {
  id: string;
  type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  progress?: number;
}

// Content type definitions for smart message handling
/**
 * Unique message id.
 *
 * Every id used to be `Date.now().toString()`, minted independently at seven
 * call sites. Two messages created in the same millisecond — a user message
 * and the system notice that follows it, say — produced the SAME React key,
 * and React then duplicates or omits rows:
 *   "Encountered two children with the same key, `1787837013519`"
 * The counter makes a collision impossible regardless of how fast ids are
 * minted, and keeps the timestamp prefix so ids still sort chronologically.
 *
 * Nothing parses these as numbers (checked), so the added suffix is safe.
 */
let __messageSeq = 0
function newMessageId(): string {
  __messageSeq += 1
  return `${Date.now()}-${__messageSeq}`
}

/**
 * REQ-22 AC2 (2026-09-23 live finding): when a model answers with its whole
 * reply inside ONE fenced code block ("```markdown\n# Title\n...\n```"), the
 * plain bubble rendered the FENCE source as literal code — monospace with
 * visible `**`/`- ` markers and right-edge clipping. A fenced WHOLE-REPLY
 * wrapper is presentation, not content: unwrap it so the markdown renders
 * readably. A reply that CONTAINS code inside prose (multiple fences, fence
 * mid-text) is untouched — only an all-fence body unwraps.
 */
function unwrapWholeReplyFence(text: string): string {
  if (!text) return text
  const t = text.trim()
  const m = t.match(/^```(?:[\w-]*)?\s*\r?\n([\s\S]*?)\r?\n?```$/)
  return m ? m[1].trim() : text
}

/**
 * Coarse key for "is this the same content?". Used to detect that a rendered
 * prism card already displays the turn's plain text, so the text bubble can be
 * skipped without dropping the message that the card attaches to.
 *
 * Deliberately lossy: fenced-code markers and all whitespace runs collapse, so
 * the same body survives the markdown -> card render unchanged. It only ever
 * suppresses a duplicate, never decides what gets shown.
 */
function normalizeCardText(value: string): string {
  return (value || '')
    .replace(/```[a-zA-Z0-9]*\n?/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

export type ContentType = 'markdown' | 'email' | 'video' | 'picture' | 'text';

const ContentTypePatterns = {
  video: /(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov)/i,
  picture: /\.(jpg|jpeg|png|gif|webp|svg|bmp)(?:\?.*)?$/i,
  markdown: /(?:^#{1,6}\s|\*\*|__|\[.+?\]\(.+?\)|```)/m,
  email: /(?:^From:|^To:|^Subject:|\S+@\S+\.\S+)/m
};

// NOTE: chat messages are NEVER auto-routed to the web crawler.
// The previous heuristic (CRAWLER_PATTERNS) matched common English words
// like "current", "recent", "find", "show me" and misrouted normal
// conversation to crawler_query — which then failed with "crawl4ai is not
// installed" or tried to crawl the web for a conversational question.
//
// Web research is now gated by the Web toggle pill to the LEFT of the
// text area. The toggle is an INTERNET-ACCESS CAPABILITY GATE, not a
// routing switch: when ON, the agent kernel is granted web tools
// (search / crawler_query) and decides when to use them; when OFF, the
// agent has zero internet tools. Every message always goes to the agent
// (/api/chat or the agent kernel) — see plan Issue E.

const ContentTypeLabels: Record<ContentType, string> = {
  markdown: 'Markdown Document',
  email: 'Email',
  video: 'Video',
  picture: 'Image',
  text: 'Text Document'
};

export interface Message {
  id: string
  text: string
  sender: "user" | "assistant" | "error" | "system"
  timestamp: Date
  errorType?: "agent" | "voice" | "validation"
  // The line TTS actually speaks. For a long answer this is a short summary
  // BRIEFING, not the body (backend: iris_gateway builds it beside `content`).
  // Kept separate because the backend's tts_word indices count words of THIS
  // string — highlighting the body against them pointed at the wrong words.
  spoken?: string;
  // For TTS word highlighting — the words of `spoken` (what is being said),
  // NOT of `text`. Only meaningful while this message is the speaking message.
  words?: string[];
  // NOTE: currentWordIndex is NOT stored in message state — it lives in ttsWordIndex
  // component state to avoid re-serialising all conversations on every 200 ms tick.
  feedback?: 'positive' | 'negative' | null; // User feedback on AI responses
  thinking?: string; // Chain-of-thought from the model, shown in a collapsible block
  // Backend turn identifier. Live messages use id === turn_id (the anchor
  // rule below), but messages rehydrated from GET /api/conversations carry
  // the DB row id as `id` and the turn as `turn_id` — inline prism cards
  // join on EITHER so a history reload does not detach a card from its turn.
  turn_id?: string;
}

// Thread-based conversation structure
export interface Conversation {
  id: string;
  title: string;
  preview: string;
  messages: Message[];
  documents: DocRender[];
  timestamp: Date;
  isPinned: boolean;
  lastMessagePreview: string;
}


// Rich document pushed by the agent via the document:render WS event (plan Issue D.3).
export interface DocRender {
  id: string
  format: string
  content: string
  alternatives: string[]
  turnId?: string
  // W4/W5: stable id so reformat can retrieve canonical data by id (no client content).
  documentId?: string
  // REQ-10 (audit 2026-09-22, F7): the lifecycle id, persisted backend-side and
  // now rehydrated with the metadata — same id across edits and reloads.
  cardId?: string
  /** REQ-22 (2026-09-23 live): card header identity — first markdown heading
   * derived from the body at ingest; a closed card must never read blank. */
  title?: string
  reformatted?: boolean
  // Phase 4 (chat-card-redesign): true when the backend revised an existing
  // document in place, so the card can show an "Updated" indicator.
  updated?: boolean
  error?: string | null
      // Trust-routing W3: "trusted" vs anything else (web/crawler-sourced).
      trust?: string
      // REQ-13 AC5 (T18b): true while the body is streaming in; the card
      // renders open so the fill is visible, and no "Updated" badge shows.
      partial?: boolean
      // Document-rehydration provenance (REQ-5/REQ-6): source URLs + HAR path so a
  // re-hydrated research doc re-renders WITH its citations, never as bare [n].
  sources?: { url: string; title: string }[]
  harPath?: string | null
}

interface ChatWingProps {
  isOpen: boolean
  onClose: () => void
  onDashboardClick: () => void
  onDashboardClose?: () => void
  sendMessage?: SendMessageFunction
  fieldValues?: Record<string, any>
  updateField?: (sectionId: string, fieldId: string, value: any) => void
  // Spotlight Mode props
  spotlightState?: SpotlightStateType
  onSpotlightToggle?: () => void
  isDashboardOpen?: boolean
  // Browser passthrough — called when user clicks a URL in chat
  onOpenBrowserUrl?: (url: string) => void
  // Remote/mobile view: full-screen flat rendering for phone access via Tailscale
  isRemoteView?: boolean
  orbDiameter?: number
  /**
   * This wing is alone in its own detached window (?pane=chat). It fills that
   * window flat: no tilt, no perspective, no 3D panel, no entrance slide.
   * Distinct from isRemoteView, which ALSO means "phone" and enlarges every
   * hit target — a wing on a second monitor is still a desktop surface.
   */
  isDetached?: boolean
}

export function ChatWing({
  isOpen,
  onClose,
  onDashboardClick,
  onDashboardClose,
  sendMessage,
  fieldValues,
  updateField,
  spotlightState = SpotlightState.BALANCED,
  onSpotlightToggle,
  isDashboardOpen = false,
  onOpenBrowserUrl,
  isRemoteView = false,
  orbDiameter = 175,
  isDetached = false,
}: ChatWingProps) {
  const prefersReducedMotion = useReducedMotion();
  
  const MAX_CONVERSATIONS = 50
  const MAX_MESSAGES_PER_CONV = 200

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)

  // ── Shared conversation API helper (error handling + performance logging) ──
  // Wraps every conversation store API call so we never block the UI on a
  // backend failure, and we can measure call timing for diagnostics (REQ-10).
  const callConversationApi = useCallback(
    async <T,>(
      label: string,
      call: () => Promise<T>,
      fallback: T,
    ): Promise<T> => {
      const t0 = performance.now()
      try {
        const result = await call()
        const elapsed = (performance.now() - t0).toFixed(1)
        console.debug(`[ConvAPI] ${label} OK (${elapsed}ms)`)
        return result
      } catch (err) {
        const elapsed = (performance.now() - t0).toFixed(1)
        console.warn(`[ConvAPI] ${label} FAILED (${elapsed}ms):`, err)
        return fallback
      }
    },
    [],
  )

  // Load conversations from backend SQLite store. Fetches full conversation
  // data including messages.
  //
  // Session 246 (live finding): this ran ONCE on mount, so threads created
  // after the page loaded — in another window/client, or while the panel was
  // closed — never appeared until a full reload (Chrome showed 441 threads
  // while the backend store already had 442: the live superconductor thread
  // was invisible). The fetch is now a reusable callback; openHistory()
  // re-runs it every time the panel opens.
  const fetchConversations = React.useCallback(async (): Promise<Conversation[]> => {
    return callConversationApi(
      "GET /api/conversations",
      async () => {
        const res = await fetch("/api/conversations", { signal: AbortSignal.timeout(8000) })
        if (!res.ok) throw new Error(`GET /api/conversations returned ${res.status}`)
        return res.json()
      },
      { conversations: [] },
    ).then((data) => {
        const convs: Conversation[] = (data.conversations || []).map((c: any) => {
          const firstUserMsg = (c.messages || []).find((m: any) => m.role === "user" || m.sender === "user")
          return {
          id: c.id,
          // Rehydration: prefer the stored title; else derive from the first
          // user message; else a stable id-suffix label (legacy threads).
          title: c.title && !/^Conversation \d+$/.test(c.title)
            ? c.title
            : (firstUserMsg?.text || "").replace(/\s+/g, " ").trim().slice(0, 60)
              || `Conversation ${c.id?.slice(-4) || ""}`,
          preview: c.messages?.[c.messages.length - 1]?.text?.substring(0, 60) || "",
          messages: (c.messages || []).map((m: any) => ({
            id: m.id,
            text: m.text || "",
            sender: m.role === "user" ? "user" : "assistant",
            timestamp: new Date(m.timestamp || Date.now()),
            thinking: m.thinking,
            turn_id: m.turn_id,
          })),
          documents: [] as DocRender[],
          timestamp: new Date(c.updated_at || c.created_at || Date.now()),
          isPinned: !!c.pinned,
          lastMessagePreview: c.messages?.[c.messages.length - 1]?.text?.substring(0, 60) || "",
        }
        })
        return convs
      })
  }, [callConversationApi])

  // Mount: initial load + auto-select the most recent non-pinned thread.
  useEffect(() => {
    let cancelled = false
    fetchConversations().then((convs) => {
      if (cancelled) return
      setConversations(convs)
      const sorted = [...convs].sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
      const lastNonPinned = sorted.find((c) => !c.isPinned) || sorted[0] || null
      setActiveConversationId(lastNonPinned?.id || null)
    })
    return () => { cancelled = true }
  }, [fetchConversations])

  // Rich documents are stored per-conversation (Conversation.documents).
  // Each document:render WS event appends or updates a DocRender within the
  // active conversation; the expand action opens it full-panel via DocumentPanel.
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null)
  // REQ-17 (reply-surface-contract T27/T28): a rehydrated card's body is
  // fetched LAZILY when the user expands it — hydration stays metadata-only
  // (AC4); nothing ships wholesale with history. Retry clears the status so
  // the effect re-fires.
  const [docBodyStatus, setDocBodyStatus] = useState<
    Record<string, 'loading' | 'ok' | 'missing' | 'error'>
  >({})

  const retryDocumentBody = useCallback((documentId: string) => {
    setDocBodyStatus(prev => {
      const next = { ...prev }
      delete next[documentId]
      return next
    })
  }, [])

  // Audit 2026-09-22 (F11): the lazy body fetch as ONE call — the panel-expand
  // effect below and the rehydrated card's chevron peek both route through it.
  // The docBodyStatus guard prevents duplicate sends for the same document.
  const requestDocumentBody = useCallback((documentId: string) => {
    let shouldSend = false
    setDocBodyStatus(prev => {
      if (prev[documentId]) return prev
      shouldSend = true
      return { ...prev, [documentId]: 'loading' }
    })
    if (shouldSend) {
      sendMessage?.('get_document_body', {
        document_id: documentId,
        conversation_id: activeConversationIdRef.current,
      })
    }
  }, [sendMessage])

  // The fetch trigger: fires only for an expanded, body-less, store-backed doc.
  useEffect(() => {
    if (!expandedDocId) return
    const doc = conversations
      .find(c => c.id === activeConversationId)
      ?.documents.find(d => d.id === expandedDocId)
    if (!doc?.documentId) return
    if ((doc.content || '').trim().length > 0) return
    requestDocumentBody(doc.documentId)
  }, [expandedDocId, conversations, activeConversationId, requestDocumentBody])

  // REQ-17 AC3: the body fills the EXISTING card in place — no fresh
  // DOCUMENT_RENDER, no new card, no duplicate.
  useEffect(() => {
    function onBody(e: Event) {
      const detail = (e as CustomEvent<{
        document_id?: string; conversation_id?: string; status?: string
        content?: string; format?: string; sources?: DocRender['sources']
        har_path?: string | null; trust?: string
      }>).detail
      if (!detail?.document_id) return
      setDocBodyStatus(prev => ({
        ...prev,
        [detail.document_id as string]: detail.status === 'ok' ? 'ok' : 'missing',
      }))
      if (detail.status !== 'ok' || !detail.content) return
      setConversations(prev => prev.map(conv => {
        const cid = detail.conversation_id || activeConversationIdRef.current
        if (conv.id !== cid) return conv
        const documents = conv.documents.map(d =>
          d.documentId === detail.document_id
            ? {
                ...d,
                content: detail.content as string,
                format: detail.format || d.format,
                sources: detail.sources,
                harPath: detail.har_path ?? d.harPath,
                trust: detail.trust || d.trust,
                title:
                  d.title ||
                  (() => {
                    const m = (detail.content || "").match(/^\s*#\s+(.+)$/m)
                    return m ? m[1].trim() : "Document"
                  })(),
              }
            : d
        )
        return { ...conv, documents }
      }))
    }
    window.addEventListener('iris:document_body', onBody)
    return () => window.removeEventListener('iris:document_body', onBody)
  }, [])
  // turnId -> normalized content of every document rendered under that turn.
  // This exists so the text_response handlers can tell "a card exists for this
  // turn" apart from "this card IS the answer". The old check only had the turn
  // IDs, so ANY document claimed the turn and the assistant's plain text was
  // dropped outright. That did two kinds of damage: the narration the user
  // should read alongside the card disappeared, and — because no message was
  // ever created for the turn — nothing carried `id === turnId`, so the card
  // failed the inline join (doc.turnId === message.id) and fell through to the
  // orphan block at the bottom of the scroll.
  //
  // A ref, not state, for the same reason the old turn-ID set was: the REST
  // path reads it inside a fetch .then(), and a document:render can land
  // between send and response.
  const activeDocContentsRef = useRef<Map<string, string[]>>(new Map())
  useEffect(() => {
    const _docs =
      conversations.find(c => c.id === activeConversationId)?.documents || []
    const _byTurn = new Map<string, string[]>()
    for (const d of _docs) {
      if (!d.turnId) continue
      const norm = normalizeCardText(d.content || '')
      if (!norm) continue
      const cur = _byTurn.get(d.turnId)
      if (cur) cur.push(norm)
      else _byTurn.set(d.turnId, [norm])
    }
    activeDocContentsRef.current = _byTurn
  }, [activeConversationId, conversations])

  // True only when the incoming plain text is EXACTLY one of this turn's
  // rendered documents (normalized). A card CONTAINING the text as a
  // substring is NOT a duplicate — that is narration + artifact coexisting,
  // and dropping the message orphans the card to the bottom fallback
  // (2026-09-04: r.includes(norm) matched every short narration inside a
  // large markdown synthesis, so no anchor message existed and every card
  // piled at the scroll bottom). Exact equality only.
  const isTextRenderedAsDocument = (turnId: string | undefined, text: string): boolean => {
    if (!turnId) return false
    const rendered = activeDocContentsRef.current.get(turnId)
    if (!rendered || rendered.length === 0) return false
    const norm = normalizeCardText(text)
    if (!norm) return false
    return rendered.some((r) => r === norm)
  }

  const [inputText, setInputText] = useState("")
  // handleSendMessage shadows setInputText for pill sends; this is the real setter.
  const setInputTextState = setInputText
  const [webMode, setWebMode] = useState(() => {
    try {
      return localStorage.getItem('iris-web-mode') === 'true'
    } catch {
      return false
    }
  })  // explicit Web toggle — internet-access gate (plan Issue E); persisted to survive unmounts
  // Sync web-mode toggle to backend session so STT transcripts also route through the crawler.
  // Web mode SURVIVES component unmounts — we deliberately do NOT reset to off on unmount.
  // The backend's global internet-access flag is the source of truth for the running session,
  // and we re-sync it on every mount from the persisted value below.
  useEffect(() => {
    try { localStorage.setItem('iris-web-mode', String(webMode)) } catch { /* ignore */ }
    sendMessage?.('set_web_mode', { enabled: webMode })
  }, [webMode, sendMessage])
  const [justSent, setJustSent] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  // REQ-6 AC3/AC4 (T7): the timeline only auto-scrolls while the user is
  // pinned to the bottom. This ref is written by the container's onScroll and
  // read by the auto-scroll effect — deliberately a ref, not state, so the
  // effect always sees the value from BEFORE the new content was inserted
  // (inserting content does not fire a scroll event, so the pre-insertion
  // pinned state survives until the effect reads it).
  const pinnedToBottomRef = useRef(true)
  // Only drives the jump-to-latest button; must not re-render on every frame.
  const [showJumpToLatest, setShowJumpToLatest] = useState(false)
  const activeConversationIdRef = useRef<string | null>(null)
  // Tracks turn_id values already dispatched to prevent duplicate message
  // insertion when both WS text_response and REST /api/chat deliver the same
  // assistant reply (see PR 3 — Parakeet ASR pipeline).
  const seenTurnIds = useRef<Set<string>>(new Set())
  const inputRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const chatPanelRef = useRef<HTMLDivElement>(null)
  const chatOuterRef = useRef<HTMLDivElement>(null)
  const { voiceState, isChatTyping, setCurrentConversationId, clearChat, activeTheme, fieldErrors, audioLevel } = useNavigation();
  
  // Notification system state
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  // Permission request state — each request_id mapped to its card state
  interface PendingPermission {
    requestId: string
    toolName: string
    tier: "read_only" | "side_effect" | "destructive"
    params?: Record<string, unknown>
    description?: string
    timeoutSeconds: number
    requiresConfirmation: boolean
  }
  const [pendingPermissions, setPendingPermissions] = useState<Map<string, PendingPermission>>(new Map())

  // Session-331: optimistic removal for the permission card's own click
  // handlers (see the card's onApprove/onDeny/onConfirm). Mirrors the backend
  // permission_granted/denied removal path so a click always clears the card,
  // even if the broadcast is missing or mis-routed.
      const removePendingPermission = useCallback((id: string) => {
        setPendingPermissions(prev => {
          const next = new Map(prev)
          next.delete(id)
          return next
        })
      }, [])

      // REQ-12 AC1/AC2 (reply-surface-contract T22): optimistic removal for
      // question cards — same pattern as the permission card above. A ref so
      // the []-memoized event handlers always call the latest instance.
      const removePendingQuestion = useCallback((id: string) => {
        setPendingQuestions(prev => {
          const next = new Map(prev)
          next.delete(id)
          return next
        })
      }, [])
      const removePendingQuestionRef = useRef(removePendingQuestion)
      removePendingQuestionRef.current = removePendingQuestion

      // Pending agent questions state — rendered as QuestionCards
      interface PendingQuestion {
        questionId: string
        text: string
        options?: string[]
        allowOther?: boolean
        timeoutSeconds?: number
        // REQ-11 AC2 (reply-surface-contract T21): the asking turn; the card
        // anchors to it in the thread instead of pinning at the bottom.
        turnId?: string
      }
  const [pendingQuestions, setPendingQuestions] = useState<Map<string, PendingQuestion>>(new Map())

  // Window width for responsive both-open layout
  const [windowWidth, setWindowWidth] = useState(1280);
  useEffect(() => {
    setWindowWidth(window.innerWidth);
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // TTS state
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [currentTtsMessageId, setCurrentTtsMessageId] = useState<string | null>(null);
  // Word index lives here, NOT inside Message/Conversations, so the 200 ms tick
  // updates a single number rather than remapping all conversations + localStorage.
  const [ttsWordIndex, setTtsWordIndex] = useState(-1);
  // Total word count from tts_started (backend-provided).  Used by the word
  // highlighting effect when the assistant message hasn't arrived yet (re-entrancy).
  const [ttsTotalWords, setTtsTotalWords] = useState<number | null>(null);
  
  // Copy feedback state
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  
  // Smart message length handling state
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  // Thinking block expand/collapse — collapsed by default
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(new Set());
  const [documentModalMessage, setDocumentModalMessage] = useState<Message | null>(null);
  // Audit 2026-09-22 (F12): messageContentTypes state REMOVED — the old
  // getContentType wrote to it during render (setState-in-render, which React
  // flags and which only stopped looping because of the cache). The detector
  // is a cheap pure regex pass; compute it per call instead.
  
  // File upload drag-and-drop state
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [draggedFileType, setDraggedFileType] = useState<'image' | 'video' | 'file' | null>(null);
  
  // Conversation chips — input focus state (chips slide away on focus)
  const { isDeveloper } = useLauncherMode()
  const [isInputFocused, setIsInputFocused] = useState(false)

  // Help lives in Workspace Bar (one-row, 32px) — chat's /help delegates there via iris:toggle_help
  const handleHelp = useCallback(async () => {
    window.dispatchEvent(new CustomEvent('iris:toggle_help'))
  }, [])
  // T2: the slide-over is gone; isOpen is kept only so legacy `>term` /
  // question-answer auto-open calls in handleSendMessage stay no-op-safe.
  const terminalOpen = useSyncExternalStore(subscribeTerminal, () => getTerminalSnapshot().isOpen, () => false)
  // T6 (REQ-4): archive item count for the top-bar badge
  const archivedCount = useWorkspaceStore((s) => s.archived.length)
  const terminalQuestionCount = useSyncExternalStore(
    subscribeTerminal,
    () => getTerminalSnapshot().questions.length,
    () => 0,
  )
  // cli-workspace-unification T4: full scrollback snapshot for the unified
  // chronological scroll. The store keeps a stable cached snapshot object, so
  // this only re-renders when the store actually mutates (bounded at 500 lines).
  const terminalSnapshot = useSyncExternalStore(subscribeTerminal, getTerminalSnapshot, getTerminalSnapshot)

  // ── Gate 3 T10 (REQ-4): active-tab workdir ──────────────────────────────
  // A non-virtual tab with a local path drives `>` and /run workdir; virtual
  // tabs send nothing (backend default). Header display rides the store.
  const activeTabPath = useWorkspaceStore((s) => {
    const tab = s.tabs.find((t) => t.id === s.activeTabId)
    return tab && !tab.isVirtual && tab.path ? tab.path : null
  })
  useEffect(() => {
    setTerminalWorkdir(activeTabPath ?? "")
  }, [activeTabPath])

  // ── Gate 3 T11 (REQ-6 AC2): per-conversation history rehydration ────────
  useEffect(() => {
    if (activeConversationId) loadHistory(activeConversationId)
  }, [activeConversationId])

  // ── Gate 3 T12 (REQ-7): slash-command menu ──────────────────────────────
  // Sourced from GET /api/dev/cli-tools (REQ-0 AC4) — never a second
  // hardcoded list. Suppressed while listening; must not hijack @taskcard.
  const [slashCommands, setSlashCommands] = useState<Array<{
    name: string; display_name: string; when_to_use: string; available: boolean;
  }>>([])
  const [slashMenuOpen, setSlashMenuOpen] = useState(false)
  useEffect(() => {
    if (!isDeveloper) return
    let cancelled = false
    fetch('/api/dev/cli-tools')
      .then((r) => (r.ok ? r.json() : { tools: [] }))
      .then((data) => { if (!cancelled) setSlashCommands(data.tools ?? []) })
      .catch(() => { /* menu degrades to empty — input unaffected */ })
    return () => { cancelled = true }
  }, [isDeveloper])
  const slashMatches = useMemo(() => {
    if (!slashMenuOpen) return []
    const q = inputText.slice(1).toLowerCase() // after the leading '/'
    return slashCommands
      .filter((c) => c.available !== false)
      .filter((c) => !q || c.name.toLowerCase().startsWith(q) ||
        c.display_name.toLowerCase().includes(q))
      .slice(0, 8)
  }, [slashMenuOpen, slashCommands, inputText])
  const acceptSlash = (command: string) => {
    setInputText(`/${command} `)
    setSlashMenuOpen(false)
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  // Suggestion pills — populated from text_response WS payload, cleared on send or dismiss
  const [currentSuggestions, setCurrentSuggestions] = useState<Suggestion[]>([])

  // Derive isTyping: use isChatTyping for text messages (won't animate the orb),
  // and voiceState for voice pipeline processing/tool states.
  // localTyping: set optimistically when sending a message; cleared when the
  // WS/REST acknowledges (chat_typing:true arrives) or after timeout.
  const [localTyping, setLocalTyping] = useState(false)
  const isTyping = isChatTyping || voiceState === "processing_conversation" || voiceState === "processing_tool" || localTyping

  // Clear optimistic localTyping when WS/REST acknowledges the message
  useEffect(() => {
    if (isChatTyping) setLocalTyping(false)
  }, [isChatTyping])

  // Safety timeout — localTyping must never be able to pin the typing
  // indicator on. The effect above only fires on the transition INTO
  // isChatTyping=true, so any turn where that transition is not observed (the
  // response arriving before the event, a chat_typing frame lost, or
  // isChatTyping already true from a previous turn so React sees no change)
  // used to leave this stuck true forever, and `isTyping` with it.
  //
  // The primary clear is now in handleTextResponse, which runs as soon as the
  // answer arrives. This is the backstop for a turn that never produces one at
  // all — it mirrors the guard useIRISWebSocket keeps on isChatTyping.
  //
  // SILENCE WATCHDOG, NOT A FIXED CAP (2026-08-17). This was a flat 30 s and it
  // is the SECOND of a matched pair — fixing only the one in useIRISWebSocket
  // changed nothing, because `isTyping` is an OR of both inputs and this one
  // still expired on schedule. Measured live: typing true at t=12 s, false at
  // t=42 s, exactly 30 s later, with the agent still on step 2 of 4 and the
  // answer 130 s away.
  //
  // Task progress is proof the turn is alive, so the timer restarts whenever a
  // step advances. It now only fires after a real stretch of no progress.
  // (effect defined below, after taskProgress is available)

  // Get theme colors from BrandColorContext for real-time updates
  const { getThemeConfig } = useBrandColor();
  const brandTheme = getThemeConfig();
  const glowColor = brandTheme.glow.color || "#00d4ff";
  const primaryColor = brandTheme.glow.color || "#00d4ff";
  const fontColor = brandTheme.text.primary || "#ffffff";

  // Task progress (drives TaskListCard + OrbBadge)
  const taskProgress = useTaskProgress()

  // T7 (REQ-4 AC2): keep useTaskProgress's per-conversation card view in sync
  // with which conversation this component is actually showing. New
  // conversations created via the first message (chat-view.tsx:642, :936,
  // :3657) never get a backend `conversation_switched` ack — only an
  // explicit switch does — so relying on that ack alone left the hook
  // pointed at the wrong (or no) conversation the moment a fresh thread
  // started. Reuses the SAME two window events useTaskProgress already
  // listens for (iris:conversation_switched / iris:new_conversation)
  // instead of inventing a third channel; both are idempotent, so this and
  // the WS-driven dispatch can never disagree for long.
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (activeConversationId) {
      window.dispatchEvent(
        // source:'chatview' marks view-originated switches so the socket's
        // thread mirror (useIRISWebSocket) learns them while ignoring the
        // backend's own switch-ack re-emit under the same name (H1, 2026-09-04).
        new CustomEvent('iris:conversation_switched', { detail: { conversation_id: activeConversationId, source: 'chatview' } })
      )
    } else {
      window.dispatchEvent(new CustomEvent('iris:new_conversation'))
    }
  }, [activeConversationId])

  // Session 246 (live finding): card rehydration was DEAD CODE end-to-end —
  // the backend handler (_handle_get_cards), the wire type registration and
  // the frontend iris:cards merge all existed, but NO component ever SENT a
  // `get_cards` request. Cards lived only in this tab's reducer memory, so a
  // reload (or any second client) showed the thread with NO task card even
  // mid-run (conv-40 evidence). Request the persisted cards every time the
  // viewed conversation changes; the response merges idempotently.
  useEffect(() => {
    if (!activeConversationId) return
    sendMessage?.('get_cards', { conversation_id: activeConversationId })
  }, [activeConversationId, sendMessage])
  // Is the TaskListCard still driving its own progress indicator? Only while at
  // least one step is unresolved. Once every step is done/skipped/failed the
  // card is static, so the chat's own thinking indicator must take over for the
  // synthesis phase — otherwise the UI goes completely silent between the last
  // step and the answer (measured live at 79 s: 12:16:00 -> 12:17:19).
  const taskProgressStillRunning =
    taskProgress.steps.length > 0 &&
    taskProgress.steps.some(
      (s) => s.status === "working" || s.status === "pending" || s.status === "unknown"
    )

  // localTyping backstop — see the note above where localTyping is declared.
  // Lives here because it watches taskProgress, which is declared just above.
  useEffect(() => {
    if (!localTyping) return
    const timer = setTimeout(() => {
      setLocalTyping(false)
      console.log("[ChatView] localTyping reset — no task progress for 90s")
    }, 90_000)
    return () => clearTimeout(timer)
  }, [
    localTyping,
    taskProgress.currentStep,
    taskProgress.steps.length,
    taskProgress.isWorking,
    isChatTyping,
  ])
  // Crawl state (drives the plan card's source list). Owned by CrawlProvider in
  // app/layout.tsx, ABOVE this component, so the list survives a panel unmount
  // mid-run (REQ-12 AC3) instead of resetting when the user drags the widget.
  const { state: crawlState } = useCrawlContext()
  // Context-window usage (drives ContextPill)
  // max: 0 means "no window known yet" — it is NOT a value, and the pill
  // renders "—" for it. This was a hardcoded 128000, which was a lie: 128k is
  // the PAID Cerebras tier and this install is on the free 64k tier (every
  // request answers 402 payment required). Worse, the fallback also masked
  // the real bug — with the pill pre-filled, a turn that never emitted (any
  // failure path) left it showing 128k as if that were measured.
  const [contextUsage, setContextUsage] = useState<{ used: number; max: number }>({
    used: 0,
    max: 0,
  })
  useEffect(() => {
    const onUsage = (e: Event) => {
      const d = (e as CustomEvent).detail
      if (d && typeof d.used_tokens === "number") {
        // Keep the previous denominator if this event somehow omits one —
        // never overwrite a measured window with a placeholder.
        setContextUsage((prev) => ({
          used: d.used_tokens,
          max: typeof d.max_tokens === "number" ? d.max_tokens : prev.max,
        }))
      }
    }
    window.addEventListener("iris:context_usage", onUsage)
    return () => window.removeEventListener("iris:context_usage", onUsage)
  }, [])

      // Get active conversation messages
      const activeConversation = conversations.find(c => c.id === activeConversationId);
      const messages = activeConversation?.messages || [];
      // Phase 3: the live turns of THIS conversation (the store files each
      // turn under the conversation its events name — never the one on screen).
      const liveTurns = useConversationTurns(activeConversationId);
      const liveTurnById = useMemo(() => new Map(liveTurns.map((t) => [t.id, t])), [liveTurns]);

      // REQ-11/REQ-12 (reply-surface-contract T21/T22): a question whose turn
      // already has a message renders INLINE at that turn; the bottom block is
      // the fallback while the turn's reply has not landed yet (AC3). Reload
      // reconcile (AC5) falls out: pendingQuestions is in-memory only, so a
      // reload starts with an empty map — a stale card can never rehydrate.
      const anchoredQuestionIds = useMemo(() => {
        const turnOwners = new Set(
          messages.flatMap((m) => (m.turn_id ? [m.id, m.turn_id] : [m.id]))
        )
        const anchored = new Set<string>()
        for (const q of pendingQuestions.values()) {
          if (q.turnId && turnOwners.has(q.turnId)) anchored.add(q.questionId)
        }
        return anchored
      }, [messages, pendingQuestions])

      // T22: one render helper used by BOTH the bottom block (unanchored
      // fallback) and the in-turn join (T21). The optimistic removal on answer
      // lands BEFORE the backend round trip (AC1); self-dismiss at countdown
      // zero covers AC4.
      const questionCardFor = (q: {
        questionId: string
        text: string
        options?: string[]
        allowOther?: boolean
        timeoutSeconds?: number
        turnId?: string
      }) => (
        <QuestionCard
          key={q.questionId}
          questionId={q.questionId}
          text={q.text}
          options={q.options}
          allowOther={q.allowOther}
          timeoutSeconds={q.timeoutSeconds}
          onAnswer={(id, answer, source) => {
            sendMessage?.('question_response', {
              question_id: id,
              answer,
              // Forward the card's answer provenance ("click" | "text") so
              // GUI answers stay distinguishable from terminal answers
              // (source:'cli') end-to-end. Backend ignores unknown fields.
              source,
            })
            // REQ-12 AC1: optimistic removal — the card disappears on the
            // click itself, before any backend broadcast, and a lost broadcast
            // can no longer leave it rendered (session-331 permission parity).
            removePendingQuestion(id)
          }}
          onTimeout={() => removePendingQuestion(q.questionId)}
        />
      )

  // Conversation chips — derived from user messages, front-end only, no LLM.
  // Session 246 (user directive): TASK CARDS register here too — each card
  // contributes a chip labelled with its objective (planTitle); clicking
  // scrolls to the joined response message. Cards without a joinable turn
  // are skipped (a chip that cannot navigate is noise).
  const conversationChips: ConversationChip[] = useMemo(() => {
    const msgChips: ConversationChip[] = messages
      .filter(m => m.sender === 'user')
      .map((m, index) => ({
        messageId: m.id,
        label: m.text.length > 24 ? m.text.slice(0, 24) + '\u2026' : m.text,
        index,
      }))
    const joinableTurns = new Set(messages.map(m => m.id))
    const cardChips: ConversationChip[] = taskProgress.cards
      .filter(c => c.planTitle && c.responseTurnId && joinableTurns.has(c.responseTurnId))
      .map(c => ({
        messageId: c.responseTurnId!,
        label: `\u25b8 ${c.planTitle!.length > 26 ? c.planTitle!.slice(0, 26) + '\u2026' : c.planTitle!}`,
        index: msgChips.length,
      }))
    return [...msgChips, ...cardChips]
  }, [messages, taskProgress.cards])

  // Session 246 (@-card-mentions): parse @taskcard:<id> tokens out of the
  // composer text and resolve them to {card_id, conversation_id} pairs from
  // the live card collection — the gateway loads the persisted snapshots.
  const extractReferencedCards = useCallback((text: string) => {
    const ids = [...new Set([...text.matchAll(/@taskcard:([\w-]+)/g)].map(m => m[1]))]
    return ids
      .map(cardId => taskProgress.cards.find(c => c.cardId === cardId))
      .filter((c): c is TaskCard => !!c)
      .map(c => ({ card_id: c.cardId, conversation_id: c.conversationId }))
  }, [taskProgress.cards])

  // @-mention picker state: opens when the composer text ends with a bare '@'.
  // Session 246: on a NEW thread the hook holds no cards (get_cards is
  // per-conversation), so opening the picker requests a cross-thread scan
  // (payload.all) and keeps the candidates in local state.
  const [cardMentionOpen, setCardMentionOpen] = useState(false)
  const [mentionCards, setMentionCards] = useState<TaskCard[]>([])
  const openCardMentionPicker = useCallback(() => {
    setCardMentionOpen(true)
    const onCards = (e: Event) => {
      const wire = (e as CustomEvent).detail?.cards || []
      const mapped: TaskCard[] = wire.map((p: any) => ({
        cardId: p.card_id,
        conversationId: p.conversation_id,
        isWorking: false,
        currentStep: p.current_step ?? 0,
        totalSteps: p.total_steps ?? 0,
        steps: [],
        planTitle: p.plan_title ?? undefined,
        terminalState: p.terminal_state,
      }))
      setMentionCards(mapped)
      window.removeEventListener('iris:cards', onCards)
    }
    window.addEventListener('iris:cards', onCards)
    sendMessage?.('get_cards', { all: true })
    // safety: close the listener if no response arrives
    setTimeout(() => window.removeEventListener('iris:cards', onCards), 4000)
  }, [sendMessage])
  const mentionCandidates = taskProgress.cards.length > 0 ? taskProgress.cards : mentionCards

  // ── Gate 3 T9 (REQ-3/D5): DE-UNIFIED. Shell lines no longer merge into
  // the chat stream — they render in the terminal panel only (scrollback
  // store stays authoritative there). Chat keeps messages + cards.

  // ── Session 244: card↔response inline join ─────────────────────────────
  // Cards render INLINE with the assistant message they belong to (matched
  // by responseTurnId === message.id — the same join documents use), not
  // bottom-stacked. Cards with no match (legacy replays, rehydrated cards
  // whose response scrolled away) fall back to the bottom in creation order.
  // Conversation-reply cards (settled, tool-less — isConversationReplyCard)
  // are suppressed entirely: cards are for artifacts, not conversation.
  // Phase 3: a turn that streams before its final message lands (or that
  // ends in an error / cancel and never gets one) renders as a placeholder
  // anchored by its turn id — the same anchor live messages use.
  const timelineMessages = useMemo(
    () =>
      mergeLiveTurns(messages, liveTurns, (t: TurnRecord): Message => ({
        id: t.id,
        text: t.text,
        sender: "assistant",
        timestamp: new Date(t.startedAt),
        turn_id: t.id,
        feedback: null,
      })),
    [messages, liveTurns],
  )
  const renderTimeline = useMemo(
    () => buildChatTimeline(timelineMessages, taskProgress.cards),
    [timelineMessages, taskProgress.cards],
  )

  // REQ-3 AC2: elapsed running timer for the active Blueprint Matrix. Ticks
  // ONLY while a card is working (interval cleaned up on settle — bounded).
  const [matrixElapsedSec, setMatrixElapsedSec] = useState(0)
  const anyCardWorking = taskProgress.cards.some((c) => c.isWorking)
  useEffect(() => {
    if (!anyCardWorking) {
      setMatrixElapsedSec(0)
      return
    }
    const t = setInterval(() => setMatrixElapsedSec((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [anyCardWorking])

  // REQ-10 AC1/AC2: true only in the dead-air window between prompt submit
  // and the first streamed block — the glyph's exact mount window.
  const awaitingFirstBlock = useMemo(() => {
    if (!isDeveloper || !isTyping || taskProgressStillRunning) return false
    if (messages.length === 0) return false
    const last = messages[messages.length - 1]
    return last.sender === "user"
  }, [isDeveloper, isTyping, taskProgressStillRunning, messages])

  // T11 (REQ-8 AC1): Blueprint Matrix transition log — every status change of
  // any card is recorded with ISO ts + conversation id. Compares a compact
  // signature so unchanged renders never log.
  const matrixSignatureRef = useRef<string>("")
  useEffect(() => {
    const sig = taskProgress.cards
      .map((c) => `${c.cardId}:${c.steps.map((s) => s.status[0]).join("")}`)
      .join("|")
    if (sig === matrixSignatureRef.current) return
    const prev = matrixSignatureRef.current
    matrixSignatureRef.current = sig
    if (!prev) return // first sight of the cards — not a transition
    logStructured("matrix_transition", {
      conversation_id: activeConversationId,
      from: prev,
      to: sig,
    })
  }, [taskProgress.cards, activeConversationId])



  const handleChipClick = useCallback((messageId: string) => {
    const el = document.getElementById(`msg-${messageId}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('chip-highlight')
    setTimeout(() => el.classList.remove('chip-highlight'), 2000)
  }, [])

  // Calculate unread count when notifications change
  useEffect(() => {
    setUnreadCount(notifications.filter(n => !n.read).length);
  }, [notifications]);

  // cli-workspace-unification T9 (REQ-5 AC3): deep-link from a Kanban card
  // to its conversation thread. Fired by openAgentThread() in the Workspace
  // Hub; switches only when the conversation exists locally.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const handler = (e: Event) => {
      const id = (e as CustomEvent<{ conversation_id?: string }>).detail?.conversation_id
      if (!id) return
      handleSelectConversation(id)
    }
    window.addEventListener('iris:open_conversation', handler as EventListener)
    return () => window.removeEventListener('iris:open_conversation', handler as EventListener)
  }, [])

  // Mark all as read when notification panel opens
  useEffect(() => {
    if (showNotifications) {
      setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    }
  }, [showNotifications]);

  // Auto-focus input when chat becomes open
  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 300)
    }
  }, [isOpen])

  // Keep ref in sync with activeConversationId state
  useEffect(() => {
    activeConversationIdRef.current = activeConversationId
  }, [activeConversationId])

  // Scroll to bottom when the timeline grows — depends on `renderTimeline`,
  // not `messages`, because a turn can add a task card or a RichDocument
  // AFTER its assistant message arrived (live: docs streamed in late made
  // the scroll snap to the wrong place). Use container scroll to avoid
  // scrollIntoView propagating up the DOM tree and shifting the Tauri frame.
  // requestAnimationFrame defers the snap to after the new row has laid out,
  // so a multi-hundred-line MD card never reports a scrollHeight from the
  // frame before it painted.
  //
  // REQ-6 AC3/AC4 (T7): PINNED-ONLY. The old version assigned
  // `el.scrollTop = el.scrollHeight` unconditionally, which yanked a user who
  // had scrolled up to read history back to the bottom on every streaming
  // chunk and every late card join. Now the snap happens only while the user
  // is pinned to the bottom; `pinnedToBottomRef` still holds the PRE-insertion
  // state because appending content does not fire a scroll event.
  useEffect(() => {
    const el = messagesContainerRef.current
    if (!el) return
    const raf = requestAnimationFrame(() => {
      if (!pinnedToBottomRef.current) return
      el.scrollTop = el.scrollHeight
    })
    return () => cancelAnimationFrame(raf)
  }, [renderTimeline])

  // REQ-6 AC4 (T7): a new/switching conversation replaces the whole timeline,
  // so the previous thread's scroll position is meaningless. Re-pin so the
  // first streamed chunk follows instead of showing a stale jump button.
  useEffect(() => {
    pinnedToBottomRef.current = true
    setShowJumpToLatest(false)
  }, [activeConversationId])

  // REQ-6 AC3 (T7): jump-to-latest affordance for a user who scrolled up and
  // is therefore no longer auto-followed. Reuses the container ref — no second
  // scroll path, and it re-pins so streaming resumes following.
  const jumpToLatest = useCallback(() => {
    const el = messagesContainerRef.current
    if (!el) return
    pinnedToBottomRef.current = true
    setShowJumpToLatest(false)
    el.scrollTo({
      top: el.scrollHeight,
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
    })
  }, [prefersReducedMotion])

  // Handle incoming WebSocket messages via the CustomEvent listener.
  // The event detail now carries turn_id from the backend _text_response helper
  // (PR 2 Patch B).  We deduplicate by tracking seen turn_ids — this prevents
  // double-insertion when both WS text_response and REST /api/chat deliver the
  // same assistant reply.
  useEffect(() => {
    function handleTextResponse(e: Event) {
      const detail = (e as CustomEvent).detail as {
        text: string; sender?: 'user' | 'assistant' | 'error'; thinking?: string;
        turn_id?: string; spoken?: string
      }
      const { text: rawText, sender = 'assistant', thinking, spoken } = detail
      // REQ-22 AC2 (2026-09-23): unwrap a whole-reply fence once, at ingest —
      // a model that wraps its answer in ```markdown made the plain bubble
      // render raw syntax and clip; the inner markdown is the reply.
      const text = unwrapWholeReplyFence(rawText ?? '')
      if (!text) return
      // `words` must be the SPOKEN words — tts_word indices count those. When
      // the backend sent no spoken line, fall back to the body (short answers,
      // where displayed and spoken are the same text anyway).
      const spokenLine = (spoken || '').trim()
      const highlightSource = spokenLine || text

      // The response for this turn has arrived — the optimistic typing flag is
      // done, whatever we do with the text below.
      //
      // This MUST stay above the early returns that follow (prism-card turns
      // and turn_id dedup). `localTyping` was previously cleared only as a side
      // effect of `isChatTyping` transitioning INTO true, which leaves it stuck
      // whenever that transition is not observed — and every early return below
      // is such a case. A stuck `localTyping` pins `isTyping` true forever
      // (nothing else clears it on the WebSocket path), so the Xur typing
      // indicator kept spinning under a finished answer. Verified live
      // 2026-08-16: voiceState='idle', isChatTyping=false, spinner still
      // rendering — localTyping was the only input left holding it up.
      setLocalTyping(false)

      const turnId = detail.turn_id

      // Skip plain-text ONLY when one of this turn's documents already shows
      // exactly this text — otherwise the user reads the answer twice.
      //
      // This used to fire on `activeDocTurnIdsRef.current.has(turnId)`: ANY
      // document claimed the turn and the text was dropped unconditionally.
      // That is what let a card emitted before the answer swallow the answer,
      // and it is also why prism cards drifted to the bottom of the scroll —
      // no message was ever created for the turn, so `doc.turnId === message.id`
      // never matched and the card fell through to the orphan fallback.
      // Comparing content instead lets plain text and a render coexist in one
      // response, which is the whole point of showing a card beside its text.
      // Exact-duplicate text is still given its anchor message. The bubble
      // may render beside its card (coexist rule), but the message MUST
      // exist with id === turnId or the inline join
      // (doc.turnId === message.id) can never match and the card falls to
      // the orphan bottom pile. Never return before the anchor is created.
      // The render branch decides bubble visibility, not ingest.
      // (Audit bug, fixed in Phase 3: this branch used to add turnId to
      // seenTurnIds, and the dedupe just below then RETURNED before the anchor
      // existed — the card fell to the orphan pile. The render branch decides
      // bubble visibility; ingest always creates the anchor.)

      // Deduplicate by turn_id — skip if we've already finalized this turn.
      if (turnId && seenTurnIds.current.has(turnId)) {
        if (process.env.NODE_ENV !== 'production') {
          console.log(`[ChatView] Deduplicating replayed text_response turn=${turnId}`)
        }
        return
      }
      if (turnId) {
        seenTurnIds.current.add(turnId)
        // REQ-12 AC3 (reply-surface-contract T22): a finalized reply makes any
        // question card of THAT turn superseded — dismiss it. Idempotent, and
        // scoped to this exact turn so a genuinely pending question of another
        // turn stays (edge case: actively-blocking question must NOT vanish —
        // this only fires when ITS OWN turn's answer arrived).
        setPendingQuestions(prev => {
          if (prev.size === 0) return prev
          let changed = false
          const next = new Map(prev)
          for (const [qid, q] of prev) {
            if (q.turnId === turnId) {
              next.delete(qid)
              changed = true
            }
          }
          return changed ? next : prev
        })
      }

      const isUserVoice = sender === "user"
      // Use the shared newMessageId() generator (chat-view.tsx:111) so the id
      // is unique within the same millisecond. A plain Date.now() here was the
      // regression that produced 5x duplicate-key warnings on this branch
      // (chat-view.tsx:3463) — see SESSION-2026-08-27-STATE.md "Duplicate React
      // keys" for the full root cause.
      const messageId = turnId ?? newMessageId()
      // Audit bug: the final text was written to whatever conversation was on
      // screen. The turn store knows the conversation the turn ran in.
      const turnConvId = turnId ? getTurnsState().byId[turnId]?.conversationId : undefined
      const currentActiveId = turnConvId || activeConversationIdRef.current
      if (currentActiveId) {
        setConversations(prev => prev.map(conv =>
          conv.id === currentActiveId
            ? {
                ...conv,
                messages: (() => {
                  const existingIdx = turnId
                    ? conv.messages.findIndex(m => m.id === turnId)
                    : -1
                  if (existingIdx >= 0) {
                    // Update the streaming message created by chat_chunk
                    const updated = [...conv.messages]
                    updated[existingIdx] = {
                      ...updated[existingIdx],
                      text,
                      thinking: thinking || updated[existingIdx].thinking,
                      spoken: spokenLine || updated[existingIdx].spoken,
                      words: highlightSource.split(' '),
                    }
                    return updated
                  }
                  const newMessage: Message = {
                    id: messageId,
                    text,
                    sender,
                    timestamp: new Date(),
                    spoken: isUserVoice ? undefined : (spokenLine || undefined),
                    words: isUserVoice ? undefined : highlightSource.split(' '),
                    feedback: isUserVoice ? undefined : null,
                    thinking: thinking || undefined,
                  }
                  return [...conv.messages, newMessage]
                })(),
                lastMessagePreview: text.substring(0, 60),
                timestamp: new Date()
              }
            : conv
        ))
      } else {
        // newMessageId(), not Date.now(): a CONVERSATION id is a React key too,
        // and two conversations minted in the same millisecond collide exactly
        // like two messages did.
        const newId = newMessageId()
        activeConversationIdRef.current = newId
        setActiveConversationId(newId)
        setConversations(prev => {
          const newConv: Conversation = {
            id: newId,
            // Contextual title from the first message (see the POST branch —
            // same rule; never a session-local counter).
            title: (sender === 'user' ? text : 'New conversation').replace(/\s+/g, ' ').trim().slice(0, 60) || 'New conversation',
            preview: text.substring(0, 60),
            messages: [{
              id: messageId,
              text,
              sender,
              timestamp: new Date(),
              spoken: isUserVoice ? undefined : (spokenLine || undefined),
              words: isUserVoice ? undefined : highlightSource.split(' '),
              feedback: isUserVoice ? undefined : null,
              thinking: thinking || undefined,
            }],
            documents: [],
            timestamp: new Date(),
            isPinned: false,
            lastMessagePreview: text.substring(0, 60)
          }
          return [...prev, newConv]
        })
      }
      if (!isUserVoice) {
        setCurrentTtsMessageId(messageId)
        // Don't set isSpeaking here — wait for iris:tts_started so word
        // highlighting stays in sync with actual audio playback.
      }
    }
    // REQ-28: a long answer's spoken brief is generated AFTER the body and
    // streamed to TTS sentence by sentence, so its final text arrives once
    // speech is already playing. Re-point `spoken` and `words` at what is
    // actually being said; otherwise the highlight follows the fallback line
    // the body carried, which is the desync `spoken` exists to prevent.
    const handleSpokenUpdate = (e: Event) => {
      const detail = (e as CustomEvent).detail as {
        turn_id?: string; spoken?: string
      }
      const spokenLine = (detail?.spoken || '').trim()
      const turnId = detail?.turn_id
      if (!spokenLine || !turnId) return
      setConversations(prev => prev.map(conv => {
        const idx = conv.messages.findIndex(m => m.id === turnId)
        if (idx < 0) return conv
        const updated = [...conv.messages]
        updated[idx] = {
          ...updated[idx],
          spoken: spokenLine,
          words: spokenLine.split(' '),
        }
        return { ...conv, messages: updated }
      }))
    }
    window.addEventListener('iris:text_response', handleTextResponse)
    window.addEventListener('iris:spoken_update', handleSpokenUpdate)
    return () => {
      window.removeEventListener('iris:text_response', handleTextResponse)
      window.removeEventListener('iris:spoken_update', handleSpokenUpdate)
    }
  }, [])

  // Streaming text (formerly iris:chat_chunk -> active conversation) now
  // renders from the turn store: every WS turn streams as turn.part text
  // deltas filed under the turn's own conversation (Phase 3; audit bug:
  // chunks were written to whatever conversation was on screen).

  // Handle document:render — agent pushed a rich document (plan Issue D.3).
  // Appended inline with format pills; reformat updates the same doc by turn_id.
  useEffect(() => {
    function handleDocumentRender(e: Event) {
      const detail = (e as CustomEvent).detail as {
        format?: string
        content?: string
        alternatives?: string[]
        turn_id?: string
        document_id?: string
        // REQ-10 (F7): the persisted lifecycle id rides every render emit.
        card_id?: string
        reformatted?: boolean
        // Phase 4 (chat-card-redesign): backend sets this when it revises an
        // existing document in place, so the card can show an "Updated" indicator.
        updated?: boolean
        // REQ-13 AC5 (reply-surface-contract T18b): a PARTIAL emit is a
        // streaming card body filling in. It updates the SAME card in place and
        // must never be rendered as a revision — no "Updated" badge while
        // partial is set.
        partial?: boolean
        trust?: string
        sources?: { url: string; title: string }[]
        har_path?: string | null
        /** Card header label supplied by the backend (the artifact fallback names
         * the card from the user's ask when the body carries no heading). */
        title?: string
      } | undefined
      if (!detail?.content) return
      const doc: DocRender = {
        // document_id FIRST. This used to key on turn_id, and a websearch turn
        // emits SEVERAL documents under ONE turn (two crawler_query step cards
        // plus the markdown synthesis — live conv-6 had four sharing turn
        // 28c6f59e-a78). Keying on the turn made them all the same card, so
        // each render REPLACED the previous one and only the last survived with
        // a body. The other three then came back from the metadata-only
        // rehydration with no content at all — which is exactly the "3 empty
        // JSON cards next to the markdown" the user saw. A document is the
        // unit here; the turn is a grouping, not an identity.
        id: detail.document_id || detail.turn_id || `doc-${Date.now()}`,
        format: detail.format || "markdown",
        content: detail.content,
        alternatives: detail.alternatives || [],
        turnId: detail.turn_id,
        documentId: detail.document_id,
        cardId: detail.card_id,
        // REQ-22: card header identity. A backend-supplied title WINS (the
        // artifact fallback names the card from the user's ask when the body has
        // no heading); else the first markdown heading; else the first
        // substantive line; else "Document". The last two keep a label UNIQUE to
        // this artifact — owner, 2026-09-25: "All titles and labels should be
        // unique to the artifact created".
        title: (() => {
          const given = typeof detail.title === "string" ? detail.title.trim() : ""
          if (given) return given
          const m = (detail.content || "").match(/^\s*#\s+(.+)$/m)
          if (m) return m[1].trim().slice(0, 60)
          const first = (detail.content || "")
            .split("\n")
            .map((l) => l.replace(/^[\s*_`#>|-]+/, "").replace(/[\s*_`]+$/, ""))
            .find((l) => l.trim().length >= 3)
          return first ? first.trim().slice(0, 60) : "Document"
        })(),
        reformatted: detail.reformatted || false,
        // Partial emits are a stream, not a revision — suppress the badge.
        updated: detail.partial ? false : (detail.updated || false),
        error: null,
        trust: detail.trust,
        sources: detail.sources,
        harPath: detail.har_path ?? null,
        partial: detail.partial || false,
      }
      // Per-conversation document store — updates the active conversation's
      // documents array instead of a flat global array.
      setConversations((prev) =>
        prev.map((conv) => {
          if (conv.id !== activeConversationIdRef.current) return conv
          // Phase 4 (chat-card-redesign): update an existing card in place when the
          // backend revises a document by id (or re-formats by turn), instead of
          // appending a duplicate card.
          // Match on document_id ONLY when the payload carries one — see the
          // id note above. The turn_id fallback is for renders that predate
          // stable ids; using it as a co-equal match collapsed every document
          // in a multi-step turn into a single card.
          const idx = conv.documents.findIndex((d) =>
            detail.document_id
              ? d.documentId === detail.document_id
              : !!detail.turn_id && d.turnId === detail.turn_id && !d.documentId,
          )
          if (idx >= 0) {
            const updated = [...conv.documents]
            updated[idx] = doc
            return { ...conv, documents: updated }
          }
          return { ...conv, documents: [...conv.documents, doc] }
        }),
      )
    }
    function handleReformatError(e: Event) {
      const detail = (e as CustomEvent).detail as { error?: string; turn_id?: string } | undefined
      if (!detail?.turn_id) return
      setConversations((prev) =>
        prev.map((conv) => {
          if (conv.id !== activeConversationIdRef.current) return conv
          return {
            ...conv,
            documents: conv.documents.map((d) =>
              d.turnId === detail.turn_id ? { ...d, error: detail.error || "reformat failed" } : d
            ),
          }
        }),
      )
    }
    window.addEventListener('iris:document_render', handleDocumentRender)
    window.addEventListener('iris:reformat_document_error', handleReformatError)
    return () => {
      window.removeEventListener('iris:document_render', handleDocumentRender)
      window.removeEventListener('iris:reformat_document_error', handleReformatError)
    }
  }, [])

  // ── Document re-hydration (document-rehydration spec, REQ-1/2/3) ────────
  // Single convergence point: hydrateDocuments sends get_documents; the
  // iris:documents response merges into the active conversation's documents
  // keyed on document_id (idempotent — no dupes on repeated hydrate). Used by
  // the sync_state_ack handler (resume) and the conversation switch handler.
  const hydrateDocuments = useCallback(
    (convId: string | null) => {
      if (!convId || !sendMessage) return
      sendMessage('get_documents', { conversation_id: convId })
    },
    [sendMessage],
  )

  useEffect(() => {
    function handleDocuments(e: Event) {
      const detail = (e as CustomEvent).detail as {
        documents?: Array<{
          document_id?: string
          format?: string
          conversation_id?: string
          sources?: { url: string; title: string }[]
          har_path?: string | null
          created_at?: number
        }>
      } | undefined
      const docs = detail?.documents
      if (!docs || docs.length === 0) return
      // Merge into the conversation the DOCUMENTS belong to, not whichever
      // thread happens to be active when the response lands. A rapid A→B
      // switch leaves A's get_documents response in flight; merging it into
      // B (the old rule) put A's cards in B's thread (session 296: two
      // get_documents 3 s apart, 19:25:46 / 19:25:49). Fall back to the
      // active thread only when the payload does not say.
      const targetConvId = docs.find((d) => d.conversation_id)?.conversation_id
        || activeConversationIdRef.current
      setConversations((prev) =>
        prev.map((conv) => {
          if (conv.id !== targetConvId) return conv
          return {
            ...conv,
            documents: mergeRenderedDocuments(conv.documents as any, docs) as DocRender[],
          }
        }),
      )
    }
    function handleSyncStateAck(e: Event) {
      const detail = (e as CustomEvent).detail as { conversation_id?: string } | undefined
      const convId = detail?.conversation_id || activeConversationIdRef.current
      hydrateDocuments(convId || null)
    }
    window.addEventListener('iris:documents', handleDocuments)
    window.addEventListener('iris:sync_state_ack', handleSyncStateAck)
    return () => {
      window.removeEventListener('iris:documents', handleDocuments)
      window.removeEventListener('iris:sync_state_ack', handleSyncStateAck)
    }
  }, [hydrateDocuments])

  // Re-hydrate documents whenever the active conversation changes (switch OR
  // resume). Single convergence point — the iris:documents merge is idempotent,
  // so repeated calls never duplicate cards (REQ-3). The sync_state_ack handler
  // above covers the explicit resume ack as well.
  useEffect(() => {
    if (activeConversationId) hydrateDocuments(activeConversationId)
  }, [activeConversationId, hydrateDocuments])

  // Handle tts_started: backend signals first TTS audio chunk has been pushed
  // to the player. This is where we actually start word highlighting, keeping
  // it in sync with audio playback instead of starting it when text arrives.
  //
  // The backend now includes turn_id and total_words in the tts_started payload
  // so the frontend can set currentTtsMessageId immediately — BEFORE the
  // text_response (assistant) arrives — and register the tts_word listener
  // early enough to capture every word event.
  useEffect(() => {
    function handleTtsStarted(e: Event) {
      const detail = (e as CustomEvent).detail as { turn_id?: string; total_words?: number } | undefined
      setIsSpeaking(true)
      if (detail?.turn_id) {
        setCurrentTtsMessageId(detail.turn_id)
      }
      if (detail?.total_words) {
        setTtsTotalWords(detail.total_words)
      }
    }
    window.addEventListener('iris:tts_started', handleTtsStarted)
    return () => window.removeEventListener('iris:tts_started', handleTtsStarted)
  }, [])
  
  // Handle Parakeet ASR final transcription (iris:voice_final).
  // When the user speaks via the web Parakeet hook (useParakeetSTT), the
  // transcript arrives through the IRIS gateway's voice_result broadcast.
  // We add it as a user message so the conversation thread shows what was
  // heard before the assistant replies.
  useEffect(() => {
    function handleVoiceFinal(e: Event) {
      const detail = (e as CustomEvent<{ text: string; confidence?: number; turn_id?: string }>).detail
      if (!detail?.text) return

      // Deduplicate by turn_id (same logic as text_response)
      if (detail.turn_id && seenTurnIds.current.has(detail.turn_id)) {
        if (process.env.NODE_ENV !== 'production') {
          console.log(`[ChatView] Deduplicating voice_final turn=${detail.turn_id}`)
        }
        return
      }
      if (detail.turn_id) {
        seenTurnIds.current.add(detail.turn_id)
      }

      const voiceMessage: Message = {
        id: detail.turn_id ?? `voice-${Date.now()}`,
        text: detail.text,
        sender: "user",
        timestamp: new Date(),
        // No words array — user messages don't get TTS highlighting
      }

      const currentActiveId = activeConversationIdRef.current
      if (currentActiveId) {
        setConversations(prev => prev.map(conv =>
          conv.id === currentActiveId
            ? {
                ...conv,
                messages: [...conv.messages, voiceMessage],
                lastMessagePreview: voiceMessage.text.substring(0, 60),
                timestamp: new Date(),
              }
            : conv
        ))
      } else {
        const newId = detail.turn_id ?? `voice-conv-${Date.now()}`
        activeConversationIdRef.current = newId
        setActiveConversationId(newId)
        setConversations(prev => {
          const newConv: Conversation = {
            id: newId,
            // Contextual title from the first (voice) message.
            title: (voiceMessage.text || 'New conversation').replace(/\s+/g, ' ').trim().slice(0, 60) || 'New conversation',
            preview: voiceMessage.text.substring(0, 60),
            messages: [voiceMessage],
            documents: [],
            timestamp: new Date(),
            isPinned: false,
            lastMessagePreview: voiceMessage.text.substring(0, 60),
          }
          return [...prev, newConv]
        })
      }
    }
    window.addEventListener('iris:voice_final', handleVoiceFinal)
    return () => window.removeEventListener('iris:voice_final', handleVoiceFinal)
  }, [])

  // Handle execution-hardening plan events (Phase 4.1): validation failures,
  // recovery starts, topology recovery, and budget exhaustion. Surfaced as
  // system messages in the chat thread so the user sees why a step was
  // re-routed or the agent fell back to Voyager continue mode.
  useEffect(() => {
    function handlePlanEvent(e: Event) {
      const detail = (e as CustomEvent<{
        type?: string
        tool_name?: string
        error?: string
        step_id?: string
        failed_step?: string
        num_grafted?: number
        graft_attempts?: number
        critical?: boolean
      }>).detail
      if (!detail?.type) return

      const text = formatPlanEventMessage(detail)
      if (!text) return

      const systemMessage: Message = {
        // newMessageId(), not Date.now(): two plan events of the SAME type in
        // the same millisecond produced an identical key —
        // "plan-1787837301636-plan:recovery_start" twice — and React then
        // duplicates or omits rows. Recovery bursts emit exactly that way.
        id: `plan-${newMessageId()}-${detail.type}`,
        text,
        sender: "system",
        timestamp: new Date(),
      }

      const currentActiveId = activeConversationIdRef.current
      if (currentActiveId) {
        setConversations(prev => prev.map(conv =>
          conv.id === currentActiveId
            ? {
                ...conv,
                messages: [...conv.messages, systemMessage],
                lastMessagePreview: systemMessage.text.substring(0, 60),
                timestamp: new Date(),
              }
            : conv
        ))
      }
    }
    window.addEventListener('iris:plan_event', handlePlanEvent)
    return () => window.removeEventListener('iris:plan_event', handlePlanEvent)
  }, [])

  // Handle incoming permission requests from ToolPermissionSystem
  useEffect(() => {
    function handlePermissionRequest(e: Event) {
      const detail = (e as CustomEvent<{
        request_id: string; tool_name: string; tier: string;
        params?: Record<string, unknown>; description?: string;
        timeout_seconds?: number; requires_confirmation?: boolean;
        conversation_id?: string
      }>).detail
      if (!detail?.request_id || !detail?.tool_name) return

      // Session 326 (cross-thread card bug): a permission request belongs to
      // ONE conversation. Without this guard the card rendered in every open
      // thread (the backend used to broadcast to all clients). The backend now
      // routes by conversation_id; this is defence in depth so a stale or
      // mis-routed frame can never surface a card in the wrong thread.
      // An absent conversation_id is accepted (older backend / unknown
      // session) — dropping those would hide a real prompt, which is worse.
      if (
        detail.conversation_id &&
        activeConversationIdRef.current &&
        detail.conversation_id !== activeConversationIdRef.current
      ) {
        return
      }

      const perm: PendingPermission = {
        requestId: detail.request_id,
        toolName: detail.tool_name,
        tier: detail.tier as PendingPermission["tier"],
        params: detail.params,
        description: detail.description || `Execute ${detail.tool_name}`,
        timeoutSeconds: detail.timeout_seconds || 30,
        requiresConfirmation: detail.requires_confirmation || false,
      }

      setPendingPermissions(prev => {
        const next = new Map(prev)
        next.set(perm.requestId, perm)
        return next
      })
    }

    function handlePermissionResolved(e: Event) {
      const detail = (e as CustomEvent<{ request_id: string }>).detail
      if (!detail?.request_id) return
      setPendingPermissions(prev => {
        const next = new Map(prev)
        next.delete(detail.request_id)
        return next
      })
    }

    window.addEventListener('iris:permission_request', handlePermissionRequest)
    window.addEventListener('iris:permission_granted', handlePermissionResolved)
    window.addEventListener('iris:permission_denied', handlePermissionResolved)
    return () => {
      window.removeEventListener('iris:permission_request', handlePermissionRequest)
      window.removeEventListener('iris:permission_granted', handlePermissionResolved)
      window.removeEventListener('iris:permission_denied', handlePermissionResolved)
    }
  }, [])

  // Handle incoming agent questions (AskUserTool)
  useEffect(() => {
    function handleQuestionAsk(e: Event) {
      const detail = (e as CustomEvent<{
        question_id: string; text: string; options?: string[];
        allow_other?: boolean; timeout_seconds?: number; turn_id?: string
      }>).detail
      if (!detail?.question_id || !detail?.text) return
      setPendingQuestions(prev => {
        const next = new Map(prev)
        next.set(detail.question_id, {
          questionId: detail.question_id,
          text: detail.text,
          options: detail.options,
          allowOther: detail.allow_other,
          timeoutSeconds: detail.timeout_seconds,
          turnId: detail.turn_id,
        })
        return next
      })
    }
    // REQ-12 AC2 (reply-surface-contract T22): resolution is idempotent — a
    // duplicate backend broadcast after the optimistic removal is a no-op.
    function handleQuestionResolved(e: Event) {
      const detail = (e as CustomEvent<{ question_id: string }>).detail
      if (!detail?.question_id) return
      removePendingQuestionRef.current(detail.question_id)
    }
    window.addEventListener('iris:question_ask', handleQuestionAsk)
    window.addEventListener('iris:question_answered', handleQuestionResolved)
    window.addEventListener('iris:question_timeout', handleQuestionResolved)
    return () => {
      window.removeEventListener('iris:question_ask', handleQuestionAsk)
      window.removeEventListener('iris:question_answered', handleQuestionResolved)
      window.removeEventListener('iris:question_timeout', handleQuestionResolved)
    }
  }, [])

  // Handle voice command errors
  useEffect(() => {
    if (voiceState === "error") {
      const errorMessage: Message = {
        id: newMessageId(),
        text: "Voice command failed. Please try again.",
        sender: "error",
        errorType: "voice",
        timestamp: new Date(),
      }
      
      if (activeConversationId) {
        setConversations(prev => prev.map(conv => 
          conv.id === activeConversationId
            ? { ...conv, messages: [...conv.messages, errorMessage] }
            : conv
        ));
      }
    }
  }, [voiceState, activeConversationId])
  
  // Handle field validation errors
  useEffect(() => {
    if (fieldErrors && Object.keys(fieldErrors).length > 0) {
      const errorKeys = Object.keys(fieldErrors)
      const latestErrorKey = errorKeys[errorKeys.length - 1]
      const errorText = fieldErrors[latestErrorKey]
      
      const errorMessage: Message = {
        id: newMessageId(),
        text: `Validation error: ${errorText}`,
        sender: "error",
        errorType: "validation",
        timestamp: new Date(),
      }
      
      if (activeConversationId) {
        setConversations(prev => prev.map(conv => 
          conv.id === activeConversationId
            ? { ...conv, messages: [...conv.messages, errorMessage] }
            : conv
        ));
      }
    }
  }, [fieldErrors, activeConversationId])

  // Populate suggestion pills from iris:text_response CustomEvent (assistant replies only)
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ text: string; sender?: string; suggestions?: Suggestion[] }>).detail
      if (detail?.sender === 'assistant' && Array.isArray(detail.suggestions) && detail.suggestions.length > 0) {
        setCurrentSuggestions(detail.suggestions)
      }
    }
    window.addEventListener('iris:text_response', handler)
    return () => window.removeEventListener('iris:text_response', handler)
  }, [])

  // Handle TTS word highlighting.
  //
  // PRIMARY: backend tts_word events (via iris:tts_word CustomEvent) — the
  // character-proportional word monitor produces real word-level indices.
  // FALLBACK: 200 ms interval simulation when no tts_word events arrive
  // within a 1-second window of speaking starting (graceful degradation).
  //
  // isSpeaking is set by iris:tts_started (not text_response), so the
  // highlighting starts when audio actually plays, not when text arrives.
  // currentTtsMessageId is also set by tts_started (via turn_id) so the
  // tts_word listener is registered BEFORE the first word event arrives —
  // fixing the re-entrancy race where tts_started beat text_response.
  //
  // PERF: word index lives in ttsWordIndex state — a single number — so each
  // tick does NOT remap all conversations or trigger a localStorage write.
  // messages is NOT in deps; we snapshot the words array into a closure when
  // speaking starts to avoid re-creating the interval on every message change.
  useEffect(() => {
    if (!isSpeaking || !currentTtsMessageId) {
      setTtsWordIndex(-1);
      return;
    }

    // Derive total word count from the message (if already created by
    // text_response) OR from tts_started's total_words (if text_response
    // hasn't arrived yet, fixing the re-entrancy race).
    const message = messages.find((m: Message) => m.id === currentTtsMessageId);
    const totalWords = message?.words?.length ?? ttsTotalWords;

    setTtsWordIndex(0);
    let wordIndex = 0;
    let fallbackActive = false;  // disabled until 1s timeout fires

    // ── Backend tts_word event listener ──────────────────────────────────
    // When the backend emits word indices through the IRIS gateway, use them
    // directly instead of the 200ms fallback.  This keeps the visual highlight
    // perfectly in sync with the actual audio.
    let gotBackendEvent = false;
    const ttlId = setTimeout(() => {
      if (!gotBackendEvent) {
        // No backend events within 1 second — enable the fallback interval
        // so word highlighting still advances gracefully.
        fallbackActive = true;
        if (process.env.NODE_ENV !== 'production') {
          console.log('[ChatView] No tts_word event within 1s, using 200ms fallback');
        }
      }
    }, 1000);

    function onTtsWord(e: Event) {
      const detail = (e as CustomEvent<{ word_index: number; total_words?: number; is_final: boolean }>).detail;
      if (!detail || typeof detail.word_index !== 'number') return;
      if (!gotBackendEvent) {
        // First backend event — confirm the pipeline is live, kill fallback
        gotBackendEvent = true;
        fallbackActive = false;
        clearTimeout(ttlId);
        clearInterval(interval);
      }

      wordIndex = detail.word_index;
      setTtsWordIndex(wordIndex);

      if (detail.is_final) {
        setIsSpeaking(false);
        setTtsWordIndex(-1);
        setTtsTotalWords(null);
        window.removeEventListener('iris:tts_word', onTtsWord);
      }
    }
    window.addEventListener('iris:tts_word', onTtsWord);

    // ── Fallback interval ─────────────────────────────────────────────────
    // Only fires when no backend tts_word event arrived within 1 second.
    // Advances at 200ms intervals as a graceful degradation.
    const interval = setInterval(() => {
      if (!fallbackActive) return;
      wordIndex++;
      if (totalWords !== null && wordIndex >= totalWords) {
        setIsSpeaking(false);
        setTtsWordIndex(-1);
        clearInterval(interval);
        window.removeEventListener('iris:tts_word', onTtsWord);
        clearTimeout(ttlId);
        return;
      }
      setTtsWordIndex(wordIndex);
    }, 200);

    return () => {
      clearInterval(interval);
      clearTimeout(ttlId);
      window.removeEventListener('iris:tts_word', onTtsWord);
      setTtsWordIndex(-1);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSpeaking, currentTtsMessageId, ttsTotalWords]); // intentionally omit `messages` — words are snapshotted above

  // Reset speaking state when voice changes to idle
  useEffect(() => {
    if (voiceState === 'idle' && isSpeaking) {
      setIsSpeaking(false);
    }
  }, [voiceState, isSpeaking]);

  const handleSendMessage = async (overrideText?: string) => {
    // Send guards (REQ-1 AC3, Phase 5, amended per long-horizon-der-execution):
    // the backend per-session message lock QUEUES messages in order, so a
    // send during a running turn is safe — the message is processed after the
    // current turn completes. The old `|| isTyping` clause silently swallowed
    // sends during long websearch turns (observed: user could not send
    // anything for 23 minutes). Blocking is now limited to genuinely
    // impossible states: empty input and an actively-listening mic.
    // A string override comes from a suggestion pill; anything else (a click
    // event) means "send what is typed".
    const fromInput = typeof overrideText !== "string"
    const text = (fromInput ? inputText : overrideText).trim()
    if (!text || voiceState === 'listening') return
    // Clear the box only for a typed send: a pill must not wipe a draft.
    const setInputText = (v: string) => { if (fromInput) setInputTextState(v) }

    if (text === '/help' || text.toLowerCase().startsWith('/help ')) {
      setInputText('')
      setJustSent(true)
      setTimeout(() => setJustSent(false), 300)
      await handleHelp()
      return
    }

    if (isDeveloper) {
      const lower = text.toLowerCase()
      const snap = getTerminalSnapshot()
      const resolved = resolveTerminalAnswer(text, snap.questions)
      if (resolved) {
        setInputText('')
        setJustSent(true)
        setTimeout(() => setJustSent(false), 300)
        appendCommand(text)
        logStructured('cli_dispatch', { command: text, kind: 'question_answer', conversation_id: activeConversationId })
        sendMessage?.('question_response', { question_id: resolved.questionId, answer: resolved.answer, source: 'cli' })
        appendSystem(`[answered question ${resolved.questionId}]`)
        if (!snap.isOpen) toggleTerminalOpen()
        return
      }
      if (lower === '>term') {
        setInputText('')
        setJustSent(true)
        setTimeout(() => setJustSent(false), 300)
        appendCommand(text)
        toggleTerminalOpen()
        return
      }
      if (lower === 'clear' && snap.isOpen) {
        setInputText('')
        setJustSent(true)
        setTimeout(() => setJustSent(false), 300)
        clearTerminal()
        return
      }
      if (lower === 'help' && snap.isOpen) {
        setInputText('')
        setJustSent(true)
        setTimeout(() => setJustSent(false), 300)
        appendCommand(text)
        appendOutput(TERMINAL_HELP)
        return
      }
      if (text.startsWith('/run ')) {
        const query = text.slice(5).trim()
        setInputText('')
        setJustSent(true)
        setTimeout(() => setJustSent(false), 300)
        if (query) {
          appendCommand(text)
          appendSystem('[delegate] /run → dev_cli')
          logStructured('cli_dispatch', { command: text, kind: 'run_delegate', conversation_id: activeConversationId })
          // Gate 3 T10: active tab's directory rides as workdir (REQ-4 AC1).
          sendMessage?.('dev_cli', { query, ...(activeTabPath ? { workdir: activeTabPath } : {}) })
          recordHistory(text)
          if (!snap.isOpen) toggleTerminalOpen()
        }
        return
      }
      if (text.startsWith('>')) {
        const line = text.slice(1).trim()
        if (!line) {
          setInputText('')
          setJustSent(true)
          setTimeout(() => setJustSent(false), 300)
          if (!snap.isOpen) toggleTerminalOpen()
          return
        }
        setInputText('')
        setJustSent(true)
        setTimeout(() => setJustSent(false), 300)
        appendCommand(text)
        appendSystem('[shell] → terminal_input')
        logStructured('cli_dispatch', { command: text, kind: 'shell', conversation_id: activeConversationId })
        // Gate 3 T10: active tab's directory rides as workdir (REQ-4 AC1).
        sendMessage?.('terminal_input', { line: text, ...(activeTabPath ? { workdir: activeTabPath } : {}) })
        recordHistory(text)
        resetRecall()
        if (!snap.isOpen) toggleTerminalOpen()
        return
      }
    }

    setInputText("")
    setJustSent(true)
    setCurrentSuggestions([])
    setTimeout(() => setJustSent(false), 300);

    // ── Resolve thread_id: create backend conversation if new ──────
    // This replaces the old pattern where a local Date.now() ID was used
    // and the REST response handler tried to match it retroactively.
    // The server ID is the canonical ID from the start.
    let threadId: string | undefined
    let isNewConversation = false

    if (activeConversationId) {
      // Existing conversation — use the server-assigned ID directly
      threadId = activeConversationId
    } else {
      // NEW conversation — create on backend first
      isNewConversation = true
      try {
        // Title from the FIRST user message (contextual, not a session-local
        // counter). The old `Conversation ${conversations.length + 1}` named
        // every new thread "1" — conversations.length only counts what the
        // current session loaded, so it reset low every run and never derived
        // a name from the prompt. Backend REST-chat threads (conv_... ) were
        // titled from their first message; the UI path now does the same.
        const autoTitle = (text || "New conversation").replace(/\s+/g, " ").trim().slice(0, 60)
        const createRes = await fetch("/api/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: autoTitle }),
          signal: AbortSignal.timeout(8000),
        })
        if (!createRes.ok) {
          throw new Error(`POST /api/conversations returned ${createRes.status}`)
        }
        const created = await createRes.json()
        threadId = created.id

        // Persist the initial user message to the backend
        await fetch(`/api/conversations/${threadId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: "user", text }),
          signal: AbortSignal.timeout(8000),
        })
      } catch (err) {
        console.warn("[ConversationStore] Failed to create conversation:", err)
        // Fallback: local-only ID so the user can still chat
        threadId = `local-${Date.now()}`
      }
    }

    const userMessage: Message = {
      id: newMessageId(),
      text,
      sender: "user",
      timestamp: new Date(),
    }

    // Add to React state
    if (isNewConversation) {
      const newConv: Conversation = {
        id: threadId!,
        title: (text || 'New conversation').replace(/\s+/g, ' ').trim().slice(0, 60) || 'New conversation',
        preview: text.substring(0, 60),
        messages: [userMessage],
        documents: [],
        timestamp: new Date(),
        isPinned: false,
        lastMessagePreview: text.substring(0, 60),
      }
      // Replace-by-id rather than blind append. The backend used to hand out an
      // id that already existed (its auto-counter restarted at conv-1 on every
      // restart), and appending produced two entries with the same key — React:
      // "Encountered two children with the same key, `conv-1`", which silently
      // duplicates or omits rows. The store no longer collides, but the list
      // must not be one bad id away from corrupting its own rendering.
      setConversations(prev =>
        prev.some(c => c.id === newConv.id)
          ? prev.map(c => (c.id === newConv.id ? newConv : c))
          : [...prev, newConv],
      )
      setActiveConversationId(threadId!)
      // Also rebind the WS hook's active thread. useIRISWebSocket declares
      // itself authoritative for it and seeds it from localStorage DELIBERATELY
      // stickily (so a drag / unmount / reconnect does not lose the thread), and
      // it re-sends that id on reconnect. handleSelectConversation sets both ids;
      // this create path set only the local one, so the hook kept advertising the
      // PREVIOUS thread for the rest of the session.
      setCurrentConversationId(threadId!)
    } else if (activeConversationId) {
      setConversations(prev =>
        prev.map(conv =>
          conv.id === activeConversationId
            ? {
                ...conv,
                messages: [...conv.messages, userMessage],
                lastMessagePreview: text.substring(0, 60),
                timestamp: new Date(),
              }
            : conv
        )
      )
    }

    // Persist follow-up user message to backend (existing conversation).
    // New conversations already persisted the first message during create
    // (see POST /api/conversations + POST .../messages in the create branch above).
    if (!isNewConversation && threadId && !threadId.startsWith("local-")) {
      fetch(`/api/conversations/${threadId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender: "user", text }),
      }).catch(() => { /* optimistic — already shown in UI */ })
    }

    // Developer mode: prefix routing for direct shell commands
    if (isDeveloper && (text.startsWith('>') || text.startsWith('/run '))) {
      const command = text.startsWith('>')
        ? text.slice(1).trim()
        : text.slice(5).trim()
      if (command) {
        // Gate 3 T10: active tab's directory rides as workdir (REQ-4 AC1).
        sendMessage?.('terminal_input', { line: command, ...(activeTabPath ? { workdir: activeTabPath } : {}) })
        recordHistory(text)
        resetRecall()
        setInputText('')
        return
      }
    }

    // dev-cli-ide REQ-25: a message typed WHILE a turn is running is a STEER,
    // not a new turn. `text_message` queues behind the backend's per-session
    // lock for the turn's WHOLE duration, so a user watching a task go the
    // wrong way could only wait it out (the comment at the top of this
    // function records a 23-minute case). The steering channel (REQ-15) has
    // been implemented backend-side since T25/T26 and NOTHING ever sent to it;
    // this is the sender. The record reaches the DER loop at its next step
    // boundary, never mid-step, and revises the remaining plan.
    // Mode-independent: steering carries no capability gate, so it works the
    // same in personal and developer mode.
    if (anyCardWorking && sendMessage) {
      sendMessage('steer', {
        text,
        message_id: `steer-${Date.now()}`,
        conversation_id: threadId,
      })
      const steerNotice: Message = {
        id: `steer-note-${newMessageId()}`,
        text: 'Steering the running task. The agent applies this at its next step.',
        sender: 'system',
        timestamp: new Date(),
      }
      if (threadId) {
        setConversations(prev => prev.map(conv =>
          conv.id === threadId
            ? { ...conv, messages: [...conv.messages, steerNotice] }
            : conv
        ))
      }
      recordHistory(text)
      resetRecall()
      setInputText('')
      return
    }

    // === Primary path: WebSocket (streaming, no timeout) ===
    // The backend streams chat_chunk events as it generates, so the UI shows
    // live progress instead of hanging on a fixed REST timeout. REST is kept
    // as a fallback for when the WebSocket is unavailable (sendMessage unset).
    setLocalTyping(true)
    if (sendMessage) {
      // Send `threadId`, NOT `activeConversationId`. setActiveConversationId
      // was called a few lines up for a new conversation, but a React state
      // setter does not apply within the same function scope — so this read
      // still returned the PREVIOUS value (null on a first-ever conversation).
      // The backend then had no thread to file under: iris_gateway.py:4685 is
      // `payload.get("conversation_id") or session_id`, so it fell back to the
      // SESSION id — which is stable for the whole WebSocket connection. Every
      // new conversation therefore collapsed into one session-keyed thread,
      // which is the "past prompts accumulating into one thread" symptom.
      // threadId is resolved locally above and is definitive in BOTH branches
      // (for an existing conversation it IS activeConversationId).
      sendMessage("text_message", {
        text: userMessage.text,
        conversation_id: threadId,
        // Phase 3: turn.start echoes client_ref, so the live turn renders right
        // under this prompt; mode lets the backend tag the turn.
        client_ref: userMessage.id,
        mode: isDeveloper ? "developer" : "personal",
        // Session 246 (@-card-mentions): @taskcard:<id> tokens in the text are
        // resolved to persisted card snapshots so the agent can reason over
        // a PREVIOUS conversation's task results.
        referenced_cards: extractReferencedCards(userMessage.text),
        // Developer chat runs its tools in the open project tab's folder, the
        // same workdir `/run` and `>` already send (Gate 3 T10).
        ...(isDeveloper && activeTabPath ? { workdir: activeTabPath } : {}),
      })
    } else {
      // Fallback: REST /api/chat (reliable when WS unavailable)
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 300_000)  // 5 min
      fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: userMessage.text,
          thread_id: threadId,
          referenced_cards: extractReferencedCards(userMessage.text),
        }),
        signal: controller.signal,
      })
        .then(async (res) => {
          clearTimeout(timeoutId)
          if (!res.ok) {
            const body = await res.text()
            throw new Error(`POST /api/chat returned ${res.status}: ${body}`)
          }
          return res.json()
        })
        .then((data) => {
          setLocalTyping(false)
          const turnId = data.turn_id
          // Same exact-equality test as the WS path. Never drop the turn:
          // the anchor message must exist for the inline card join, even
          // on an exact duplicate (bubble + card coexist).
          // Unify through iris:text_response — exactly the same path the
          // WS chat_message / text_response events use.
          window.dispatchEvent(new CustomEvent('iris:text_response', {
            detail: {
              text: data.content || "",
              sender: 'assistant',
              thinking: data.thinking || "",
              turn_id: turnId,
            }
          }))
        })
        .catch((err) => {
          console.error("[REST fallback] /api/chat failed:", err)
          setLocalTyping(false)
        })
    }
  }

  // Conversation management functions
  const handleSelectConversation = (conversationId: string) => {
    const oldId = activeConversationId;
    setActiveConversationId(conversationId);
    setCurrentConversationId(conversationId);
    setShowHistory(false);
    // Notify backend of conversation switch for context persistence
    if (sendMessage && oldId && oldId !== conversationId) {
      sendMessage('switch_conversation', {
        conversation_id: conversationId,
        old_conversation_id: oldId,
      });
    }
  };

  const handleDeleteConversation = (e: React.MouseEvent, conversationId: string) => {
    e.stopPropagation();
    // Remove from React state immediately (optimistic)
    setConversations(prev => prev.filter(c => c.id !== conversationId));
    if (activeConversationId === conversationId) {
      const remaining = conversations.filter(c => c.id !== conversationId);
      setActiveConversationId(remaining.length > 0 ? remaining[0].id : null);
    }
    // Delete from backend (fire-and-forget). Skip local-only IDs.
    if (conversationId && !conversationId.startsWith("local-")) {
      fetch(`/api/conversations/${conversationId}`, {
        method: "DELETE",
      }).catch(() => {
        /* optimistic — already removed from UI */
      })
    }
  };

  const handlePinConversation = (e: React.MouseEvent, conversationId: string) => {
    e.stopPropagation();
    setConversations(prev => {
      const updated = prev.map(c => 
        c.id === conversationId ? { ...c, isPinned: !c.isPinned } : c
      );
      // Sort: pinned first, then by timestamp
      return updated.sort((a, b) => {
        if (a.isPinned && !b.isPinned) return -1;
        if (!a.isPinned && b.isPinned) return 1;
        return b.timestamp.getTime() - a.timestamp.getTime();
      });
    });
  };

  // Revert conversation to a specific message — deletes all messages after it.
  // Confirmation-safe: second click calls the API.
  const [revertConfirmIndex, setRevertConfirmIndex] = useState<number | null>(null)

  const handleRevertMessage = (messageIndex: number, convId: string, msgId: string) => {
    // First click: show confirmation. Second click: execute.
    if (revertConfirmIndex !== messageIndex) {
      setRevertConfirmIndex(messageIndex)
      setTimeout(() => setRevertConfirmIndex(null), 4000) // auto-clear after 4s
      return
    }
    setRevertConfirmIndex(null)

    // Truncate backend
    if (convId && !convId.startsWith("local-")) {
      fetch(`/api/conversations/${convId}/truncate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keep_until_message_id: msgId }),
      }).catch(() => { /* optimistic — already removed from UI */ })
    }

    // Update React state: keep messages up to and including the target message
    setConversations(prev =>
      prev.map(conv => {
        if (conv.id !== convId) return conv
        const keptMessages = conv.messages.slice(0, messageIndex + 1)
        return {
          ...conv,
          messages: keptMessages,
          documents: [], // clear documents associated with reverted turns
          preview: keptMessages[keptMessages.length - 1]?.text?.substring(0, 60) || "",
          lastMessagePreview: keptMessages[keptMessages.length - 1]?.text?.substring(0, 60) || "",
          timestamp: new Date(),
        }
      })
    )
  }

  // Retry on error: re-send the last user message.
  const [retryingMessageId, setRetryingMessageId] = useState<string | null>(null)
  // Inline prompt editing — retry/edit belong to the USER's turn, not the reply.
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null)
  const [editingText, setEditingText] = useState("")

  /**
   * Re-send a user prompt, optionally revised.
   *
   * Everything after the prompt is dropped before re-sending: a revised
   * question with the answer to the OLD question still sitting under it reads
   * as though the agent answered the new one. One prompt, one answer.
   *
   * Unlike handleRetryPrompt below, the fetch is issued OUTSIDE the state
   * updater — an updater must stay pure, or React's dev double-invoke fires
   * the request twice.
   */
  const handleResendUserMessage = (
    messageIndex: number,
    convId: string,
    revisedText?: string,
  ) => {
    if (retryingMessageId) return
    const conv = conversations.find((c) => c.id === convId)
    const target = conv?.messages[messageIndex]
    if (!target || target.sender !== "user") return
    const text = (revisedText ?? target.text).trim()
    if (!text) return

    setEditingMessageId(null)
    setRetryingMessageId(target.id)
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id !== convId) return c
        const kept = c.messages.slice(0, messageIndex + 1)
        // `words` is the TTS highlight map for the OLD text — stale once edited.
        kept[messageIndex] = { ...target, text, words: undefined }
        return { ...c, messages: kept, lastMessagePreview: text.substring(0, 60) }
      }),
    )

    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, thread_id: convId }),
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Chat returned ${res.status}`)
        return res.json()
      })
      .then((data) => {
        setRetryingMessageId(null)
        window.dispatchEvent(
          new CustomEvent("iris:text_response", {
            detail: {
              text: data.content || "",
              sender: "assistant",
              thinking: data.thinking || "",
              turn_id: data.turn_id,
            },
          }),
        )
      })
      .catch(() => {
        setRetryingMessageId(null)
        window.dispatchEvent(
          new CustomEvent("iris:text_response", {
            detail: { text: "Couldn't reach IRIS. Try again.", sender: "error" },
          }),
        )
      })
  }

  const handleRetryPrompt = (errorMessageIndex: number, convId: string) => {
    // Audit bug: this used to call fetch INSIDE a setConversations updater
    // (React may run an updater twice -> two requests) and left a "Retrying..."
    // message that nothing removed. A retry IS a resend of the prompt above the
    // error, so it takes the one resend path (pure updater, fetch outside).
    if (retryingMessageId) return
    const conv = conversations.find((c) => c.id === convId)
    if (!conv) return
    for (let i = errorMessageIndex - 1; i >= 0; i--) {
      if (conv.messages[i].sender === "user") {
        handleResendUserMessage(i, convId)
        return
      }
    }
  }

  const handleNewConversation = () => {
    // Do NOT mint an id here. This used to create `conv_<ts>_<rand>` locally,
    // which produced a SECOND id namespace that the conversation store never
    // saw: `new_conversation` only resets kernel context (iris_gateway.py:4660),
    // it does not insert a row, and conversation_store.add_message returns None
    // for an unknown id (conversation_store.py:230) — so every message in such a
    // thread was silently dropped and the conversation vanished on reload, since
    // chat-view rebuilds from GET /api/conversations.
    //
    // Clearing the active id instead hands the job to handleSendMessage's create
    // branch, which POSTs /api/conversations and uses the SERVER id — the
    // canonical design this file already documents ("The server ID is the
    // canonical ID from the start"). One id namespace, and the thread survives a
    // reload. Null is an already-supported state: it is the app's initial one.
    setActiveConversationId(null);
    setCurrentConversationId(undefined);
    setInputText('');

    // Close any open dropdowns
    closeDropdowns();

    // Focus input field
    setTimeout(() => inputRef.current?.focus(), 100);

    // Notify backend so the kernel context resets now rather than at first
    // message. No conversation_id: there is no thread yet, and inventing one is
    // what created the orphan namespace. The first text_message carries the real
    // server id and rebinds the backend to it.
    sendMessage?.('new_conversation', {
      timestamp: new Date().toISOString()
    });

    // Tell per-thread UI state the thread is gone. The task/plan card is the
    // visible one: it only cleared on a terminal task event, so the previous
    // conversation's card sat in the new, empty chat.
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('iris:new_conversation'));
    }
  };

  // Feedback action handlers
  const handleCopyMessage = async (text: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(messageId);
      setTimeout(() => setCopiedMessageId(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const handleFeedback = (messageId: string, feedback: 'positive' | 'negative') => {
    if (!activeConversationId) return;
    
    setConversations(prev => prev.map(conv => 
      conv.id === activeConversationId
        ? {
            ...conv,
            messages: conv.messages.map(msg => 
              msg.id === messageId ? { ...msg, feedback } : msg
            )
          }
        : conv
    ));
    
    // Send feedback to backend
    sendMessage?.('message_feedback', { message_id: messageId, feedback });
  };

  const handlePlayTTS = useRef(false);
  const handlePlayTTSClick = useCallback((text: string) => {
    // Prevent overlapping TTS plays from rapid button clicks
    if (handlePlayTTS.current) return;
    handlePlayTTS.current = true;
    sendMessage?.('tts_play', { text });
    // Reset the guard after a generous timeout; the backend will be done by then
    setTimeout(() => { handlePlayTTS.current = false; }, 15000);
  }, [sendMessage]);

  // Smart message length handling helpers
  const detectContentType = useCallback((text: string): ContentType => {
    if (ContentTypePatterns.video.test(text)) return 'video';
    if (ContentTypePatterns.picture.test(text)) return 'picture';
    if (ContentTypePatterns.markdown.test(text)) return 'markdown';
    if (ContentTypePatterns.email.test(text)) return 'email';
    return 'text';
  }, []);

  const getContentType = useCallback((message: Message): ContentType => {
    // Audit 2026-09-22 (F12): this used to back a messageContentTypes state
    // map and call `setMessageContentTypes` DURING RENDER (an uncached message
    // triggered a state write mid-render, relying on the cache to halt the
    // loop). Pure regex detection is microseconds — just compute it.
    return detectContentType(message.text);
  }, [detectContentType]);

  const toggleMessageExpanded = useCallback((messageId: string) => {
    setExpandedMessages(prev => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  }, []);

  const isMessageExpanded = useCallback((messageId: string) => {
    return expandedMessages.has(messageId);
  }, [expandedMessages]);

  const handleDownloadMessage = useCallback((message: Message) => {
    const contentType = getContentType(message);
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const filename = `IRIS_${contentType}_${timestamp}.txt`;
    
    const content = `========================================
IRIS ${ContentTypeLabels[contentType]} Export
Exported: ${new Date().toLocaleString()}
========================================

${message.text}`;
    
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    // Notify backend
    sendMessage?.('message_exported', { 
      message_id: message.id,
      content_type: contentType 
    });
  }, [getContentType, sendMessage]);

  const handleShareMessage = useCallback(async (message: Message) => {
    try {
      await navigator.clipboard.writeText(message.text);
      // Show notification
      const notif: Notification = {
        id: newMessageId(),
        type: 'completion',
        title: 'Copied to clipboard',
        message: 'Message content has been copied',
        timestamp: new Date(),
        read: false
      };
      setNotifications(prev => [notif, ...prev]);
    } catch (err) {
      console.error('Failed to share:', err);
    }
  }, []);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  // File upload handlers
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (!isDraggingFile) {
      setIsDraggingFile(true);
      
      // Detect file type from drag data
      const items = e.dataTransfer.items;
      if (items && items.length > 0) {
        const item = items[0];
        if (item.type.startsWith('image/')) {
          setDraggedFileType('image');
        } else if (item.type.startsWith('video/')) {
          setDraggedFileType('video');
        } else {
          setDraggedFileType('file');
        }
      }
    }
  }, [isDraggingFile]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    // Only clear if leaving the container (not entering a child)
    if (e.currentTarget === e.target) {
      setIsDraggingFile(false);
      setDraggedFileType(null);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingFile(false);
    setDraggedFileType(null);
    
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      const file = files[0];
      handleFileUpload(file);
    }
  }, []);

  const handleFileUpload = useCallback((file: File) => {
    // Create a message about the uploaded file
    const fileType = file.type.startsWith('image/') ? 'image' :
                     file.type.startsWith('video/') ? 'video' : 'file';
    
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      
      // Send file content or metadata based on type
      if (fileType === 'image' || fileType === 'video') {
        // For media, just send metadata and a reference
        const message = `[${fileType.toUpperCase()}: ${file.name} (${(file.size / 1024).toFixed(1)} KB)]`;
        setInputText(message);
      } else {
        // For text files, send the content (truncated if needed)
        const textContent = content.slice(0, 1000);
        const truncated = content.length > 1000 ? '... (truncated)' : '';
        setInputText(`[File: ${file.name}]\n\n${textContent}${truncated}`);
      }
    };
    
    if (fileType === 'image' || fileType === 'video') {
      reader.readAsDataURL(file);
    } else {
      reader.readAsText(file);
    }
    
    // Show notification
    const notif: Notification = {
      id: newMessageId(),
      type: 'completion',
      title: 'File ready',
      message: `${file.name} loaded. Press Enter to send.`,
      timestamp: new Date(),
      read: false
    };
    setNotifications(prev => [notif, ...prev]);
  }, []);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
    // Reset input
    e.target.value = '';
  }, []);

  // Keyboard navigation - Escape to close
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        // Close document modal first if open
        if (documentModalMessage) {
          setDocumentModalMessage(null);
          return;
        }
        // Close any open dropdowns next
        if (showNotifications || showHistory) {
          closeDropdowns();
          return;
        }
        // Finally close chat
        onClose();
      }
    };
    
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [isOpen, showNotifications, showHistory, onClose, documentModalMessage]);

  // Dropdown exclusivity handlers
  const openNotifications = () => {
    setShowNotifications(true);
    setShowHistory(false);
  };

  const openHistory = () => {
    setShowHistory(true);
    setShowNotifications(false);
    // Session 246: the thread list used to be mount-only — threads created
    // after load (other window/client) never appeared. Re-fetch on every
    // panel open; do NOT touch activeConversationId here (never yank the
    // thread the user is reading just because they opened the list).
    //
    // Session 296: fetchConversations maps REST rows that carry NO renders,
    // so it builds every Conversation with documents: [] — a blind replace
    // here wiped every prism card in every thread. Cards only exist in
    // memory (iris:document_render; get_documents rehydration is
    // metadata-only by contract CT-DOC-1 and cannot restore a body), so the
    // wipe was permanent for the session. Preserve the documents we already
    // hold; fetched threads we have never seen keep their (empty) list.
    fetchConversations()
      .then((convs) => {
        setConversations((prev) =>
          convs.map((c) => {
            const existing = prev.find((p) => p.id === c.id)
            return existing && existing.documents.length > 0
              ? { ...c, documents: existing.documents }
              : c
          }),
        )
      })
      .catch(() => {})
  };

  const closeDropdowns = () => {
    setShowNotifications(false);
    setShowHistory(false);
  };

  // Render message text with clickable URL links
  const renderWithLinks = (text: string) => {
    const urlRegex = /https?:\/\/[^\s<>"')\]]+/g;
    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = urlRegex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(text.slice(lastIndex, match.index));
      }
      const url = match[0];
      parts.push(
        <span
          key={match.index}
          onClick={() => onOpenBrowserUrl?.(url)}
          className="underline cursor-pointer transition-opacity hover:opacity-70"
          style={{ color: glowColor }}
          title={`Open in browser: ${url}`}
        >
          {url}
        </span>
      );
      lastIndex = match.index + url.length;
    }
    if (lastIndex < text.length) {
      parts.push(text.slice(lastIndex));
    }
    return parts.length > 1 ? <>{parts}</> : text;
  };

  // Permission response handlers
  const handlePermissionGrant = (notificationId: string) => {
    sendMessage?.('notification_response', { 
      notification_id: notificationId, 
      action: 'grant' 
    });
    setNotifications(prev => prev.filter(n => n.id !== notificationId));
  };

  const handlePermissionDeny = (notificationId: string) => {
    sendMessage?.('notification_response', { 
      notification_id: notificationId, 
      action: 'deny' 
    });
    setNotifications(prev => prev.filter(n => n.id !== notificationId));
  };

  // Global error state (derived from voiceState)
  const globalError = voiceState === 'error';

  // Spotlight Mode derived states
  const isInChatSpotlight = spotlightState === SpotlightState.CHAT_SPOTLIGHT;
  const isInDashboardSpotlight = spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT;
  const isBalanced = spotlightState === SpotlightState.BALANCED;

  // Both surfaces that render the wing edge-to-edge with no 3D: the phone
  // layout and a detached window. Geometry only — the mobile hit-target sizing
  // stays on isRemoteView alone.
  const isFlat = isRemoteView || isDetached;

  // The shared frame this wing sits in (lib/orbWingGeometry).
  const spotlightKey: SpotlightStr = isInChatSpotlight
    ? 'chatSpotlight'
    : isInDashboardSpotlight
      ? 'dashboardSpotlight'
      : 'balanced';
  const frame = computeFrame(
    isDashboardOpen ? 'both_open' : 'chat_open',
    spotlightKey,
  );

  // Layout geometry — see lib/orbWingGeometry. The wing no longer computes its
  // own tilt, gap or orb radius; it asks the shared module for the frame and
  // pins itself to the frame's left edge.
  const BOTH_OPEN_TILT = TILT_DEG; // degrees

  const getSpotlightWidth = () => {
    if (isDetached) return '100vw';
    if (isRemoteView) return 'calc(100vw - 24px)';
    return chatWidth(spotlightKey);
  };

  const getSpotlightTransform = () => {
    if (isFlat) return 'rotateY(0deg) rotateX(0deg)';
    if (isInChatSpotlight) return 'rotateY(0deg) rotateX(0deg)';
    if (isInDashboardSpotlight) return 'rotateY(15deg) rotateX(2deg)';
    if (isDashboardOpen) return `rotateY(${BOTH_OPEN_TILT}deg) rotateX(2deg)`; // Both open: tilted divider
    return 'rotateY(15deg) rotateX(2deg)';
  };

  const getSpotlightOpacity = () => {
    if (isFlat) return 1.0;
    if (isInDashboardSpotlight) return 0.3;
    return 1.0;
  };

  const getSpotlightFilter = () => {
    if (isFlat) return 'none';
    if (isInDashboardSpotlight) return 'saturate(0.6) blur(2px)';
    return 'none';
  };

  const getSpotlightZIndex = () => {
    if (isFlat) return 20;
    if (isInChatSpotlight) return 20;
    if (isInDashboardSpotlight) return 5;
    return 10;
  };

  const getSpotlightPointerEvents = () => {
    if (isFlat) return 'auto';
    if (isInDashboardSpotlight) return 'none';
    return 'auto';
  };

  // The chat wing is the LEFT part of the frame, so it pins to the frame's
  // left edge in every wing state. In Tauri the window is exactly the frame,
  // so this is 0; in a browser the frame is centred in the wider viewport.
  //
  // This replaces four special cases (0 / 80 / 252 / a windowWidth-relative
  // formula) that between them put the wing anywhere from flush to 252 px in.
  // The 252 px case is the one the user saw as "wings too far apart".
  const getOuterLeft = () => {
    if (isDetached) return 0;
    if (isRemoteView) return '12px';
    return frameLeft(windowWidth, frame.width);
  };
  const getOuterTop = () => isDetached ? 0 : isRemoteView ? '16px' : '6vh';
  const getOuterHeight = () => isDetached ? '100vh' : isRemoteView ? 'calc(100dvh - 32px)' : '88vh';
  const getOuterMaxHeight = () => isDetached ? '100vh' : isRemoteView ? 'calc(100dvh - 32px)' : 'calc(100vh - 24px)';
  const getOuterPerspective = () => isFlat ? 'none' : '800px';
  const getInnerBorderRadius = () => isDetached ? '0px' : isRemoteView ? '16px' : '12px';

  // Window drag from the chat HEADER (the 48px bar). Deliberately the header
  // and not the whole panel: a mousedown anywhere would start a drag from the
  // message list and the input, making text selection impossible.
  //
  // No click callback is passed — the header has no click action of its own,
  // and the hook only invokes onClickAction when one is given, so the header's
  // own buttons (dashboard, notifications, history, close) keep working
  // untouched. A drag that begins on one of those buttons no longer fires its
  // click on release: the hook swallows exactly one capture-phase click after
  // a real (>12px) drag.
  const chatHeaderRef = useRef<HTMLDivElement>(null)
  const { handleMouseDown: handleHeaderDragStart } = useManualDragWindow(chatHeaderRef)

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          ref={chatOuterRef}
          className="fixed"
          initial={isFlat ? {} : { x: -120, opacity: 0, scale: 0.95 }}
          animate={isFlat ? {} : {
            x: 0,
            opacity: getSpotlightOpacity(),
            scale: 1
          }}
          exit={isFlat ? {} : { x: -120, opacity: 0, scale: 0.95 }}
          transition={isRemoteView ? { duration: 0 } : { 
            type: "spring", 
            stiffness: 280, 
            damping: 25,
            mass: 0.8
          }}
          style={{
            left: getOuterLeft(),
            top: getOuterTop(),
            width: getSpotlightWidth(),
            height: getOuterHeight(),
            maxHeight: getOuterMaxHeight(),
            overflow: 'hidden',
            perspective: getOuterPerspective(),
            zIndex: getSpotlightZIndex(),
            filter: getSpotlightFilter(),
            pointerEvents: getSpotlightPointerEvents() as any,
            touchAction: 'manipulation',
          }}
        >
          {/* HUD Glass Panel Container */}
            <motion.div
              ref={chatPanelRef}
              className="h-full overflow-hidden flex flex-col relative"
              animate={isFlat ? {} : {
                transform: getSpotlightTransform()
              }}
              transition={isFlat ? { duration: 0 } : {
                type: "spring",
                stiffness: 280,
                damping: 25,
                mass: 0.8
              }}
            style={{
              transformOrigin: 'left center',
              transformStyle: isFlat ? 'flat' : 'preserve-3d',
              transform: isFlat ? 'rotateY(0deg) rotateX(0deg)' : undefined,
              background: 'linear-gradient(135deg, rgba(10,11,22,0.97) 0%, rgba(6,7,14,0.99) 100%)',
              boxShadow: isRemoteView ? `
                inset 0 1px 1px rgba(255,255,255,0.05),
                inset 0 -1px 1px rgba(0,0,0,0.5),
                0 0 0 1px rgba(0,0,0,0.8),
                0 8px 32px rgba(0,0,0,0.5)
              ` : `
                inset 0 1px 1px rgba(255,255,255,0.05),
                inset 0 -1px 1px rgba(0,0,0,0.5),
                0 0 0 1px rgba(0,0,0,0.8)
              `,
              borderRadius: getInnerBorderRadius(),
              border: isRemoteView ? `1px solid ${glowColor}20` : `1px solid ${glowColor}20`,
              touchAction: 'manipulation',
              willChange: 'auto',
            }}
          >
            {/* HUD Effects Overlay */}
            <div 
              className="absolute inset-0 pointer-events-none z-10"
              style={{
                background: `
                  linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.02) 50%, transparent 100%),
                  repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0,0,0,0.03) 2px,
                    rgba(0,0,0,0.03) 4px
                  )
                `,
                backgroundSize: '100% 100%, 100% 4px',
              }}
            />
            
            {/* Edge Fresnel Effect */}
            <div 
              className="absolute inset-0 pointer-events-none z-20"
              style={{
                background: `
                  linear-gradient(90deg, ${glowColor}08 0%, transparent 15%, transparent 85%, ${glowColor}08 100%),
                  linear-gradient(0deg, ${glowColor}05 0%, transparent 20%, transparent 80%, ${glowColor}05 100%)
                `,
                borderRadius: '12px',
              }}
            />

            {/* 48px Header (60px on mobile for larger touch targets) */}
            <ChatHeader
              isRemoteView={isRemoteView}
              isDetached={isDetached}
              glowColor={glowColor}
              fontColor={fontColor}
              voiceState={voiceState}
              globalError={globalError}
              chatHeaderRef={chatHeaderRef}
              handleHeaderDragStart={handleHeaderDragStart}
              isDashboardOpen={isDashboardOpen}
              onDashboardClose={onDashboardClose}
              onDashboardClick={onDashboardClick}
              onSpotlightToggle={onSpotlightToggle}
              isInChatSpotlight={isInChatSpotlight}
              onClose={onClose}
              showNotifications={showNotifications}
              openNotifications={openNotifications}
              unreadCount={unreadCount}
              showHistory={showHistory}
              openHistory={openHistory}
              closeDropdowns={closeDropdowns}
            />

            {/* Notification Dropdown Panel */}
            <NotificationsPanel
              showNotifications={showNotifications}
              glowColor={glowColor}
              notifications={notifications}
              setNotifications={setNotifications}
              unreadCount={unreadCount}
              handlePermissionGrant={handlePermissionGrant}
              handlePermissionDeny={handlePermissionDeny}
            />

            {/* History Dropdown Panel - Thread-Based */}
            <HistoryPanel
              showHistory={showHistory}
              prefersReducedMotion={prefersReducedMotion}
              glowColor={glowColor}
              fontColor={fontColor}
              conversations={conversations}
              activeConversationId={activeConversationId}
              handleNewConversation={handleNewConversation}
              handleSelectConversation={handleSelectConversation}
              handlePinConversation={handlePinConversation}
              handleDeleteConversation={handleDeleteConversation}
            />

            {/* T5 (REQ-4 AC1/AC2): compact 30px project folder bar — active
                folder pill + file tabs + [+] opening FilePickerModal. Dev
                mode only; personal mode never sees it. */}
            {isDeveloper && !isRemoteView && (
              <div className="h-[30px] shrink-0 flex items-center justify-between overflow-hidden relative z-20" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <div className="flex items-center h-full min-w-0 flex-1">
                  <WorkspaceTabBar />
                </div>
                {/* T6: archive item count badge in the top bar */}
                <div
                  className="flex items-center gap-1 px-2 py-0.5 mr-1 rounded-full flex-shrink-0"
                  style={{ background: `${glowColor}10`, border: `1px solid ${glowColor}20` }}
                  title={`${archivedCount} archived item${archivedCount === 1 ? '' : 's'}`}
                >
                  <Archive size={10} style={{ color: `${glowColor}90` }} />
                  <span className="text-[9px] tabular-nums" style={{ color: `${glowColor}90` }}>{archivedCount}</span>
                </div>
              </div>
            )}

            {/* Messages Area — THE unified chronological scroll (T1, REQ-1).
                Developer mode no longer replaces this body with the workspace:
                chat messages, shell output and Blueprint matrices all interleave
                in this ONE overflow-y-auto (pin_c86a41fa673b). */}
            <Timeline
              renderTimeline={renderTimeline}
              messages={messages}
              messagesContainerRef={messagesContainerRef}
              messagesEndRef={messagesEndRef}
              pinnedToBottomRef={pinnedToBottomRef}
              setShowJumpToLatest={setShowJumpToLatest}
              isTyping={isTyping}
              taskProgressStillRunning={taskProgressStillRunning}
              awaitingFirstBlock={awaitingFirstBlock}
              matrixElapsedSec={matrixElapsedSec}
              pendingPermissions={pendingPermissions}
              removePendingPermission={removePendingPermission}
              isDeveloper={isDeveloper}
              glowColor={glowColor}
              fontColor={fontColor}
              prefersReducedMotion={prefersReducedMotion}
              sendMessage={sendMessage}
              onOpenBrowserUrl={onOpenBrowserUrl}
              conversations={conversations}
              activeConversation={activeConversation}
              activeConversationId={activeConversationId}
              anchoredQuestionIds={anchoredQuestionIds}
              pendingQuestions={pendingQuestions}
              questionCardFor={questionCardFor}
              liveTurnById={liveTurnById}
              taskProgress={taskProgress}
              crawlState={crawlState}
              copiedMessageId={copiedMessageId}
              currentTtsMessageId={currentTtsMessageId}
              ttsWordIndex={ttsWordIndex}
              isSpeaking={isSpeaking}
              editingMessageId={editingMessageId}
              setEditingMessageId={setEditingMessageId}
              editingText={editingText}
              setEditingText={setEditingText}
              retryingMessageId={retryingMessageId}
              expandedThinking={expandedThinking}
              setExpandedThinking={setExpandedThinking}
              setDocumentModalMessage={setDocumentModalMessage}
              setExpandedDocId={setExpandedDocId}
              getContentType={getContentType}
              isMessageExpanded={isMessageExpanded}
              toggleMessageExpanded={toggleMessageExpanded}
              handleCopyMessage={handleCopyMessage}
              handleFeedback={handleFeedback}
              handlePlayTTSClick={handlePlayTTSClick}
              handleShareMessage={handleShareMessage}
              handleDownloadMessage={handleDownloadMessage}
              handleResendUserMessage={handleResendUserMessage}
              handleRetryPrompt={handleRetryPrompt}
              renderWithLinks={renderWithLinks}
              requestDocumentBody={requestDocumentBody}
            />

             {/* Document View Modal */}
            <AnimatePresence>
              {documentModalMessage && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
                  className="absolute inset-0 z-50 flex flex-col"
                  style={{ 
                    background: 'linear-gradient(135deg, rgba(10,10,20,0.99) 0%, rgba(5,5,10,0.98) 100%)'
                  }}
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="document-modal-title"
                >
                  <motion.div
                    initial={{ scale: 0.98, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.98, opacity: 0 }}
                    transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
                    className="w-full h-full flex flex-col overflow-hidden"
                  >
                    {/* Modal header - compact */}
                    <div 
                      className="px-2 py-1.5 flex items-center justify-between border-b flex-shrink-0"
                      style={{ borderColor: `${glowColor}20` }}
                    >
                      <div className="flex items-center gap-1.5" id="document-modal-title">
                        {(() => {
                          const type = getContentType(documentModalMessage);
                          const Icon = type === 'markdown' ? FileText :
                                      type === 'email' ? Mail :
                                      type === 'video' ? Video :
                                      type === 'picture' ? Image : File;
                          return <Icon size={10} style={{ color: glowColor }} />;
                        })()}
                        <span className="text-[10px] font-medium" style={{ color: fontColor }}>
                          {ContentTypeLabels[getContentType(documentModalMessage)]}
                        </span>
                        <span className="text-[8px] text-white/40">
                          ({documentModalMessage.text.length.toLocaleString()})
                        </span>
                      </div>
                      <button
                        onClick={() => setDocumentModalMessage(null)}
                        className="p-1 rounded transition-all"
                        style={{ color: `${fontColor}60` }}
                        onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; }}
                        onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; }}
                        aria-label="Close"
                      >
                        <X size={12} />
                      </button>
                    </div>
                    
                    {/* Modal content - compact */}
                    {/* REQ-4 AC1: trap the wheel at this modal's edges — a long
                        document body must scroll the modal, never the timeline
                        behind it. */}
                    <div
                      className="p-2 overflow-y-auto flex-1"
                      style={{ overscrollBehavior: 'contain' }}
                    >
                      <pre 
                        className="text-[10px] leading-snug whitespace-pre-wrap font-mono"
                        style={{ color: 'rgba(255,255,255,0.85)' }}
                      >
                        {documentModalMessage.text}
                      </pre>
                    </div>
                    
                    {/* Modal action bar - compact */}
                    <div 
                      className="px-2 py-1.5 flex gap-1.5 border-t flex-shrink-0"
                      style={{ borderColor: `${glowColor}20` }}
                    >
                      <button
                        onClick={() => handleDownloadMessage(documentModalMessage)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[9px] font-medium transition-colors"
                        style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}30`; }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}20`; }}
                      >
                        <Download size={10} />
                        Save
                      </button>
                      <button
                        onClick={() => handleShareMessage(documentModalMessage)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[9px] font-medium transition-colors"
                        style={{ backgroundColor: 'rgba(255,255,255,0.08)', color: fontColor }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.12)'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.08)'; }}
                      >
                        <Share size={10} />
                        Share
                      </button>
                      <button
                        onClick={() => handleCopyMessage(documentModalMessage.text, documentModalMessage.id)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[9px] font-medium transition-colors"
                        style={{ backgroundColor: 'rgba(255,255,255,0.08)', color: fontColor }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.12)'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.08)'; }}
                      >
                        <Copy size={10} />
                        {copiedMessageId === documentModalMessage.id ? '✓' : 'Copy'}
                      </button>
                      
                      {/* Close button */}
                      <button
                        onClick={() => setDocumentModalMessage(null)}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[9px] font-medium transition-colors ml-auto"
                        style={{ color: `${fontColor}70` }}
                        onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; }}
                        onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}70`; }}
                      >
                        <X size={10} />
                      </button>
                    </div>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Expanded Document Panel (plan Issue D.3) — full-panel viewer for a rendered doc */}
            <AnimatePresence>
              {expandedDocId && (() => {
                const doc = activeConversation?.documents.find((d) => d.id === expandedDocId)
                if (!doc) return null
                // REQ-17 (T28): a rehydrated card whose body is not in memory
                // shows loading / unavailable (+retry) rather than a blank
                // panel; the body arrives via the iris:document_body merge.
                const _hasBody = (doc.content || '').trim().length > 0
                const _status = doc.documentId
                  ? docBodyStatus[doc.documentId]
                  : undefined
                const bodyState: 'ready' | 'loading' | 'unavailable' = _hasBody
                  ? 'ready'
                  : _status === 'missing' || _status === 'error'
                    ? 'unavailable'
                    : 'loading'
                return (
                  <motion.div
                    key="doc-panel"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
                    className="absolute inset-0 z-50 flex flex-col"
                    style={{
                      background: 'linear-gradient(135deg, rgba(10,10,20,0.99) 0%, rgba(5,5,10,0.98) 100%)'
                    }}
                    role="dialog"
                    aria-modal="true"
                  >
                    <DocumentPanel
                      content={doc.content}
                      format={doc.format}
                      alternatives={doc.alternatives}
                      glowColor={glowColor}
                      trust={doc.trust}
                      bodyState={bodyState}
                      onRetry={
                        doc.documentId
                          ? () => retryDocumentBody(doc.documentId!)
                          : undefined
                      }
                      onClose={() => setExpandedDocId(null)}
                      onFormatChange={(newFormat) =>
                        sendMessage?.('reformat_document', {
                          document_id: doc.documentId,
                          format: newFormat,
                          turn_id: doc.turnId,
                          trust: doc.trust,
                          original_format: doc.format,
                        })
                      }
                    />
                  </motion.div>
                )
              })()}
            </AnimatePresence>

            {/* T6 (REQ-4 AC3): ArchiveDock directly above the input footer —
                minimized card pills with 1-click restore; auto-collapses to a
                2px glow line when empty. Dev mode only. */}
            {isDeveloper && !isRemoteView && <ArchiveDock />}

            <Composer
              isRemoteView={isRemoteView}
              isDeveloper={isDeveloper}
              glowColor={glowColor}
              fontColor={fontColor}
              voiceState={voiceState}
              audioLevel={audioLevel}
              sendMessage={sendMessage}
              handleDragOver={handleDragOver}
              handleDragLeave={handleDragLeave}
              handleDrop={handleDrop}
              isDraggingFile={isDraggingFile}
              draggedFileType={draggedFileType}
              fileInputRef={fileInputRef}
              handleFileInputChange={handleFileInputChange}
              currentSuggestions={currentSuggestions}
              setCurrentSuggestions={setCurrentSuggestions}
              handleSendMessage={handleSendMessage}
              inputText={inputText}
              setInputText={setInputText}
              inputRef={inputRef}
              setIsInputFocused={setIsInputFocused}
              showJumpToLatest={showJumpToLatest}
              jumpToLatest={jumpToLatest}
              webMode={webMode}
              setWebMode={setWebMode}
              cardMentionOpen={cardMentionOpen}
              setCardMentionOpen={setCardMentionOpen}
              mentionCandidates={mentionCandidates}
              openCardMentionPicker={openCardMentionPicker}
              slashMenuOpen={slashMenuOpen}
              setSlashMenuOpen={setSlashMenuOpen}
              slashMatches={slashMatches}
              acceptSlash={acceptSlash}
              terminalSnapshot={terminalSnapshot}
              activeTabPath={activeTabPath}
              conversationChips={conversationChips}
              handleChipClick={handleChipClick}
              messagesContainerRef={messagesContainerRef}
              contextUsage={contextUsage}
              taskProgress={taskProgress}
            />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// Note: Component renamed to ChatWing but file kept as chat-view.tsx to avoid breaking imports
export default ChatWing