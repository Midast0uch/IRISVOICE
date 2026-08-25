"use client"

import React, { useState, useEffect, useRef, useCallback, useMemo, useSyncExternalStore } from "react"
import { sortRows, deriveProgress } from "@/lib/cards/rowOrder";
import { motion, AnimatePresence } from "framer-motion"
import { Send, X, BarChart3, Plus, Trash2, AlertCircle, Bell, AlertTriangle, Shield, Loader, CheckCircle, Info, History, Pin, Copy, ThumbsUp, ThumbsDown, Volume2, ChevronDown, ChevronUp, Download, Share, FileText, Mail, Video, Image, File, Smile, ExternalLink, RefreshCw, Pencil, Archive } from 'lucide-react';
import { Icon } from '@iconify/react';
import { Xur } from "@/components/Xur";
import { useNavigation } from "@/contexts/NavigationContext";
import { useBrandColor } from "@/contexts/BrandColorContext";
import { SendMessageFunction } from "@/hooks/useIRISWebSocket";
import { mergeRenderedDocuments } from "@/lib/documentMerge";
import { formatPlanEventMessage } from "@/components/chat/planEventMessage";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { IrisApertureIcon } from "@/components/ui/IrisApertureIcon";
import { SpotlightState, SpotlightStateType } from "@/hooks/useUILayoutState";
import { useLauncherMode } from "@/hooks/useLauncherMode";
import { ConversationChips } from "@/components/chat/ConversationChips";

// Lazy-load entire workspace — only bundles in developer mode
// (cli-workspace-unification T1: ChatView no longer replaces its body with the
// workspace in dev mode — the unified scroll IS the dev-mode body. The Visual
// Workspace Hub lives in the Dashboard Wing, not here.)
import { SuggestionPills } from "@/components/chat/SuggestionPills";
import { PermissionCard } from "@/components/chat/PermissionCard";
import { QuestionCard } from "@/components/chat/QuestionCard";
// cli-workspace-unification T5/T6 (REQ-4): project folder bar + archive dock
import { WorkspaceTabBar } from "@/components/workspace/WorkspaceTabBar";
import { ArchiveDock } from "@/components/workspace/ArchiveDock";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import TaskListCard from "@/components/chat/TaskListCard";
import {
  renderBlueprintCellMatrixCLI,
  type TaskCardProps,
  type TaskStepItem,
} from "@/lib/cli/CLITaskProgressRenderer";
import type { TaskCard } from "@/hooks/useTaskProgress";
import { isConversationReplyCard } from "@/hooks/useTaskProgress";
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
} from "@/components/terminal/terminalScrollback";
import ContextPill from "@/components/chat/ContextPill";
import ModelSwitcher from "@/components/ModelSwitcher";
import { RichDocument } from "@/components/chat/RichDocument";
import { MarkdownMessage } from "@/components/chat/MarkdownMessage";
import { DocumentPanel } from "@/components/chat/DocumentPanel";
import { useTaskProgress } from "@/hooks/useTaskProgress";
import { useCrawlContext } from "@/hooks/CrawlProvider";
import type { ConversationChip, Suggestion } from "@/types/iris";

// Notification types for the universal notification system
interface Notification {
  id: string;
  type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  progress?: number;
}

// Content type definitions for smart message handling
export type ContentType = 'markdown' | 'email' | 'video' | 'picture' | 'text';

const MESSAGE_THRESHOLDS = {
  TRUNCATE_AT: 500,            // plain text expand/collapse threshold
  DOCUMENT_MODE_AT: 400,       // artifact card threshold for media/email/file uploads
  // MARKDOWN_ARTIFACT_AT removed 2026-08-17 — length is not what makes something a
  // document. See the isDocumentMode comment below: a document is what the agent
  // stored via a `show` payload and arrives as DOCUMENT_RENDER.
  WARNING_AT: 3000
} as const;

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

// Helper functions for notification styling
const getNotificationColor = (type: string, glowColor: string): string => {
  switch (type) {
    case 'alert': return '#fbbf24'; // amber
    case 'permission': return '#3b82f6'; // blue
    case 'error': return '#ef4444'; // red
    case 'task': return '#a855f7'; // purple
    case 'completion': return '#22c55e'; // green
    default: return glowColor;
  }
};

const getNotificationIcon = (type: string, glowColor: string) => {
  const iconProps = { size: 10, style: { color: getNotificationColor(type, glowColor) } };
  switch (type) {
    case 'alert': return <AlertTriangle {...iconProps} />;
    case 'permission': return <Shield {...iconProps} />;
    case 'error': return <AlertCircle {...iconProps} />;
    case 'task': return <Loader {...iconProps} className="animate-spin" />;
    case 'completion': return <CheckCircle {...iconProps} />;
    default: return <Info {...iconProps} />;
  }
};

interface Message {
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
}

// Thread-based conversation structure
interface Conversation {
  id: string;
  title: string;
  preview: string;
  messages: Message[];
  documents: DocRender[];
  timestamp: Date;
  isPinned: boolean;
  lastMessagePreview: string;
}

// ── cli-workspace-unification T4 (REQ-3): TaskCard → Blueprint Matrix ──────
// The GUI card (TaskListCard) and the ASCII renderer must describe the SAME
// task from the SAME store (useTaskProgress cards); only ONE renders per mode
// (pin_d222bf18dc6b). This conversion never re-maps verbs locally — the
// backend tool name flows straight into resolveVerb() (T8a contract).

function taskStepStatusToMatrix(status: TaskCard["steps"][number]["status"]): TaskStepItem["status"] {
  switch (status) {
    case "working": return "running"
    case "done": return "done"
    case "fail":
    case "error": return "failed"
    case "vetoed": return "rerouted"
    default: return "pending" // pending / skipped / unknown
  }
}

function taskCardToMatrixProps(card: TaskCard): TaskCardProps {
  return {
    objective: card.planTitle || card.currentAction || "Task",
    // GROUND TRUTH REQ-20 AC2: render in the AUTHORITATIVE order, derived from
    // the shared key — not inherited from whatever array position the GUI card
    // happened to hand over.
    steps: sortRows(card.steps).map((s): TaskStepItem => ({
      id: s.id,
      // REQ-20 AC1: carry the key through. Dropping it here is what left the
      // CLI unable to even detect a bad order.
      seq: s.seq,
      verb: s.toolName || "exec",
      target: s.activeDetail
        ? `${s.description} — ${s.activeDetail}${s.activeProgress ? ` (${s.activeProgress})` : ""}`
        : s.description,
      status: taskStepStatusToMatrix(s.status),
      summary: s.resultPreview,
      // branchLabel stays free-form backend data ("Diving Deeper" etc.) —
      // never the literal "Sub-Loop" (task-card-v2 CT-9).
      branchLabel: undefined,
    })),
    // REQ-20 AC3: the progress pair, from the SAME derivation the GUI counter
    // and the XurOrb ring read.
    ...deriveProgress(card.steps, card.totalSteps),
    isThinking: card.isWorking && !card.currentAction,
    currentThought: card.currentAction,
    isCrystallized: card.learningSignal === "crystallized" || card.terminalState === "done",
    memoryEvents: (card.memoryEvents || []).map((m) => ({
      direction:
        String(m.kind).includes("cryst")
          ? "crystallize"
          : String(m.kind).includes("store") || String(m.kind).includes("compress")
            ? "store"
            : "retrieve",
      engine: "episodic" as const,
      detail: typeof m.data?.detail === "string" ? m.data.detail : String(m.kind || "memory activity"),
      timestamp: m.at,
    })),
  }
}


// Rich document pushed by the agent via the document:render WS event (plan Issue D.3).
interface DocRender {
  id: string
  format: string
  content: string
  alternatives: string[]
  turnId?: string
  // W4/W5: stable id so reformat can retrieve canonical data by id (no client content).
  documentId?: string
  reformatted?: boolean
  // Phase 4 (chat-card-redesign): true when the backend revised an existing
  // document in place, so the card can show an "Updated" indicator.
  updated?: boolean
  error?: string | null
  // Trust-routing W3: "trusted" vs anything else (web/crawler-sourced).
  trust?: string
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
        const res = await fetch("/api/conversations")
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
  // Ref + effect for closure-safe document turn ID lookup in the REST handler
  // (avoids closure staleness when a document:render WS event arrives between
  // fetch send and response).
  const activeDocTurnIdsRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    const _docs =
      conversations.find(c => c.id === activeConversationId)?.documents || []
    activeDocTurnIdsRef.current = new Set(
      _docs.map(d => d.turnId).filter((t): t is string => !!t)
    )
  }, [activeConversationId, conversations])

  const [inputText, setInputText] = useState("")
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

  // Pending agent questions state — rendered as QuestionCards
  interface PendingQuestion {
    questionId: string
    text: string
    options?: string[]
    allowOther?: boolean
    timeoutSeconds?: number
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
  const [messageContentTypes, setMessageContentTypes] = useState<Record<string, ContentType>>({});
  
  // File upload drag-and-drop state
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [draggedFileType, setDraggedFileType] = useState<'image' | 'video' | 'file' | null>(null);
  
  // Conversation chips — input focus state (chips slide away on focus)
  const { isDeveloper } = useLauncherMode()
  const [isInputFocused, setIsInputFocused] = useState(false)
  const [uploadHovered, setUploadHovered] = useState(false)

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
        new CustomEvent('iris:conversation_switched', { detail: { conversation_id: activeConversationId } })
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
  const [contextUsage, setContextUsage] = useState<{ used: number; max: number }>({
    used: 0,
    max: 128000,
  })
  useEffect(() => {
    const onUsage = (e: Event) => {
      const d = (e as CustomEvent).detail
      if (d && typeof d.used_tokens === "number") {
        setContextUsage({ used: d.used_tokens, max: d.max_tokens ?? 128000 })
      }
    }
    window.addEventListener("iris:context_usage", onUsage)
    return () => window.removeEventListener("iris:context_usage", onUsage)
  }, [])

  // Get active conversation messages
  const activeConversation = conversations.find(c => c.id === activeConversationId);
  const messages = activeConversation?.messages || [];

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

  // ── cli-workspace-unification T1/T4 (REQ-1/REQ-3): unified timeline ──────
  // Developer mode renders ONE chronological stream: chat messages and shell
  // lines interleaved by timestamp inside a single overflow-y-auto. Lines the
  // scrollback store mirrored from `iris:text_response` are EXCLUDED — those
  // are already rendered as regular assistant messages here (source: "chat").
  const unifiedTimeline = useMemo(() => {
    if (!isDeveloper) return null
    const items: Array<
      | { kind: "message"; ts: number; message: Message; index: number }
      | { kind: "shell"; ts: number; line: (typeof terminalSnapshot.lines)[number] }
    > = []
    for (let i = 0; i < messages.length; i++) {
      const m = messages[i]
      items.push({ kind: "message", ts: m.timestamp?.getTime?.() ?? 0, message: m, index: i })
    }
    for (const line of terminalSnapshot.lines) {
      if (line.source === "chat") continue
      items.push({ kind: "shell", ts: line.ts, line })
    }
    items.sort((a, b) => a.ts - b.ts)
    return items
  }, [isDeveloper, messages, terminalSnapshot])

  // ── Session 244: card↔response inline join ─────────────────────────────
  // Cards render INLINE with the assistant message they belong to (matched
  // by responseTurnId === message.id — the same join documents use), not
  // bottom-stacked. Cards with no match (legacy replays, rehydrated cards
  // whose response scrolled away) fall back to the bottom in creation order.
  // Conversation-reply cards (settled, tool-less — isConversationReplyCard)
  // are suppressed entirely: cards are for artifacts, not conversation.
  const renderTimeline = useMemo(() => {
    type Entry =
      | { kind: "message"; ts: number; message: Message; index: number }
      | { kind: "shell"; ts: number; line: (typeof terminalSnapshot.lines)[number] }
      | { kind: "card"; ts: number; card: TaskCard }
    const base: Entry[] = unifiedTimeline
      ? [...unifiedTimeline]
      : messages.map((message, index) => ({
          kind: "message" as const,
          ts: message.timestamp?.getTime?.() ?? 0,
          message,
          index,
        }))
    // Session 246 (user directive): ONE card per response — never stack.
    // Later cards for the same turn supersede earlier ones ('continues'
    // double-emits, re-plans); unmatched orphans collapse to the single
    // newest so dead cards cannot pile up at the bottom of the thread.
    const latestPerTurn = new Map<string, TaskCard>()
    for (const card of taskProgress.cards) {
      if (isConversationReplyCard(card)) continue
      latestPerTurn.set(card.responseTurnId || `__orphan__:${card.cardId}`, card)
    }
    const out: Entry[] = []
    const rendered = new Set<string>()
    for (const entry of base) {
      out.push(entry)
      if (entry.kind !== "message") continue
      const card = latestPerTurn.get(entry.message.id)
      if (!card || rendered.has(card.cardId)) continue
      rendered.add(card.cardId)
      out.push({ kind: "card", ts: entry.ts, card })
    }
    // Not-yet-rendered cards (orphans without a turn-id match): insert
    // CHRONOLOGICALLY using the card's creation time — after the last
    // message that was already on screen when the task started. This keeps
    // each task card in line with its own prompt/reply instead of piling
    // every card at the bottom of the thread (user-reported disjointed
    // scroll, session 248). Cards whose createdAt is unknown fall back to
    // the bottom, oldest first.
    const unrendered = [...latestPerTurn.entries()]
      .filter(([k]) => !rendered.has(latestPerTurn.get(k)!.cardId))
      .map(([, c]) => c)
      .sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0))
    for (const c of unrendered) {
      const cardTs = c.createdAt ?? Number.MAX_SAFE_INTEGER
      let insertAt = -1
      for (let i = out.length - 1; i >= 0; i--) {
        const e = out[i]
        if (e.kind === "message" && e.ts <= cardTs) {
          insertAt = i + 1
          break
        }
      }
      const entry: Entry = { kind: "card", ts: cardTs, card: c }
      if (insertAt >= 0) {
        out.splice(insertAt, 0, entry)
      } else {
        out.push(entry)
      }
    }
    return out
  }, [unifiedTimeline, messages, taskProgress.cards])

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
    if (!unifiedTimeline || unifiedTimeline.length === 0) return false
    const last = unifiedTimeline[unifiedTimeline.length - 1]
    return last.kind === "message" && last.message.sender === "user"
  }, [isDeveloper, isTyping, taskProgressStillRunning, unifiedTimeline])

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

  // Scroll to bottom when messages change — use container scroll to avoid
  // scrollIntoView propagating up the DOM tree and shifting the Tauri frame
  useEffect(() => {
    const el = messagesContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

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
      const { text, sender = 'assistant', thinking, spoken } = detail
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

      // If this turn is a rendered document (prism card), skip plain-text —
      // the RichDocument card already shows the structured content.
      //
      // NOTE for anyone re-adding an early/plan card: this suppression is why
      // that is dangerous. A document emitted BEFORE the answer exists claims
      // the turn here, and an answer arriving as plain text is then dropped —
      // the user is left reading a plan for work that already finished. Any
      // pre-answer card needs this branch to distinguish "a card exists" from
      // "the answer was rendered" before it can be safe.
      if (turnId && activeDocTurnIdsRef.current.has(turnId)) {
        seenTurnIds.current.add(turnId)
        return
      }

      // Deduplicate by turn_id — skip if we've already finalized this turn.
      if (turnId && seenTurnIds.current.has(turnId)) {
        if (process.env.NODE_ENV !== 'production') {
          console.log(`[ChatView] Deduplicating replayed text_response turn=${turnId}`)
        }
        return
      }
      if (turnId) {
        seenTurnIds.current.add(turnId)
      }

      const isUserVoice = sender === "user"
      const messageId = turnId ?? (Date.now() + 1).toString()
      const currentActiveId = activeConversationIdRef.current
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
        const newId = Date.now().toString()
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
    window.addEventListener('iris:text_response', handleTextResponse)
    return () => window.removeEventListener('iris:text_response', handleTextResponse)
  }, [])

  // Handle streaming chat chunks (iris:chat_chunk) from the WebSocket path.
  // The backend streams these during generation so the UI shows live progress
  // instead of hanging on a 120s REST timeout. Keyed by turn_id so concurrent
  // turns (different conversations) don't collide, and so the final
  // text_response can update the same message (no duplicate).
  useEffect(() => {
    function handleChatChunk(e: Event) {
      const detail = (e as CustomEvent).detail as { chunk?: string; turn_id?: string }
      const chunk = detail.chunk
      if (!chunk) return
      const turnId = detail.turn_id
      if (!turnId) return
      const convId = activeConversationIdRef.current
      if (!convId) return
      setConversations(prev => prev.map(conv => {
        if (conv.id !== convId) return conv
        const messages = [...conv.messages]
        const idx = messages.findIndex(m => m.id === turnId)
        if (idx >= 0) {
          const updated = messages[idx].text + chunk
          messages[idx] = {
            ...messages[idx],
            text: updated,
            words: updated.split(' '),
          }
        } else {
          messages.push({
            id: turnId,
            text: chunk,
            sender: 'assistant',
            timestamp: new Date(),
            words: chunk.split(' '),
            feedback: null,
          })
        }
        return { ...conv, messages }
      }))
    }
    window.addEventListener('iris:chat_chunk', handleChatChunk)
    return () => window.removeEventListener('iris:chat_chunk', handleChatChunk)
  }, [])

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
        reformatted?: boolean
        // Phase 4 (chat-card-redesign): backend sets this when it revises an
        // existing document in place, so the card can show an "Updated" indicator.
        updated?: boolean
        trust?: string
        sources?: { url: string; title: string }[]
        har_path?: string | null
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
        reformatted: detail.reformatted || false,
        updated: detail.updated || false,
        error: null,
        trust: detail.trust,
        sources: detail.sources,
        harPath: detail.har_path ?? null,
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
      setConversations((prev) =>
        prev.map((conv) => {
          if (conv.id !== activeConversationIdRef.current) return conv
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
        id: `plan-${Date.now()}-${detail.type}`,
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
        timeout_seconds?: number; requires_confirmation?: boolean
      }>).detail
      if (!detail?.request_id || !detail?.tool_name) return

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
        allow_other?: boolean; timeout_seconds?: number
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
        })
        return next
      })
    }
    function handleQuestionResolved(e: Event) {
      const detail = (e as CustomEvent<{ question_id: string }>).detail
      if (!detail?.question_id) return
      setPendingQuestions(prev => {
        const next = new Map(prev)
        next.delete(detail.question_id)
        return next
      })
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
        id: Date.now().toString(),
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
        id: Date.now().toString(),
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

  const handleSendMessage = async () => {
    // Send guards (REQ-1 AC3, Phase 5, amended per long-horizon-der-execution):
    // the backend per-session message lock QUEUES messages in order, so a
    // send during a running turn is safe — the message is processed after the
    // current turn completes. The old `|| isTyping` clause silently swallowed
    // sends during long websearch turns (observed: user could not send
    // anything for 23 minutes). Blocking is now limited to genuinely
    // impossible states: empty input and an actively-listening mic.
    if (!inputText.trim() || voiceState === 'listening') return
    const text = inputText.trim()

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
          sendMessage?.('dev_cli', { query })
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
        sendMessage?.('terminal_input', { line: text })
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
        })
      } catch (err) {
        console.warn("[ConversationStore] Failed to create conversation:", err)
        // Fallback: local-only ID so the user can still chat
        threadId = `local-${Date.now()}`
      }
    }

    const userMessage: Message = {
      id: Date.now().toString(),
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
        sendMessage?.('terminal_input', { line: command })
        setInputText('')
        return
      }
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
        // Session 246 (@-card-mentions): @taskcard:<id> tokens in the text are
        // resolved to persisted card snapshots so the agent can reason over
        // a PREVIOUS conversation's task results.
        referenced_cards: extractReferencedCards(userMessage.text),
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
          // If a rendered document (prism card) with this turn_id already
          // exists, skip adding a duplicate plain-text message — the
          // RichDocument card already shows the structured content.
          if (turnId && activeDocTurnIdsRef.current.has(turnId)) {
            return
          }
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
    // Debounce rapid retries
    if (retryingMessageId) return

    setConversations(prev =>
      prev.map(conv => {
        if (conv.id !== convId) return conv
        const msgs = conv.messages
        // Find the last user message before the error
        let lastUserMsg: (typeof msgs)[0] | null = null
        for (let i = errorMessageIndex - 1; i >= 0; i--) {
          if (msgs[i].sender === "user") {
            lastUserMsg = msgs[i]
            break
          }
        }
        if (!lastUserMsg) return conv // no user message found

        // Remove the error message and show loading state
        const errorMsg = msgs[errorMessageIndex]
        const newMsgs = msgs.filter((_, i) => i !== errorMessageIndex)
        setRetryingMessageId(lastUserMsg.id)

        // Re-send to /api/chat
        fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: lastUserMsg.text, thread_id: convId }),
        })
          .then((res) => {
            if (!res.ok) throw new Error(`Chat returned ${res.status}`)
            return res.json()
          })
          .then((data) => {
            setRetryingMessageId(null)
            // Unify through iris:text_response — same as the primary handler.
            window.dispatchEvent(new CustomEvent('iris:text_response', {
              detail: {
                text: data.content || "",
                sender: 'assistant',
                thinking: data.thinking || "",
                turn_id: data.turn_id,
              }
            }))
          })
          .catch(() => {
            setRetryingMessageId(null)
            // Restore the error message
            setConversations((innerPrev) =>
              innerPrev.map((ic) => {
                if (ic.id !== convId) return ic
                return { ...ic, messages: [...ic.messages, errorMsg] }
              })
            )
          })

        return {
          ...conv,
          messages: [
            ...newMsgs,
            {
              id: Date.now().toString(),
              text: "Retrying...",
              sender: "assistant",
              timestamp: new Date(),
              thinking: "",
            },
          ],
        }
      })
    )
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
    if (!messageContentTypes[message.id]) {
      const detected = detectContentType(message.text);
      setMessageContentTypes(prev => ({ ...prev, [message.id]: detected }));
      return detected;
    }
    return messageContentTypes[message.id];
  }, [messageContentTypes, detectContentType]);

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
        id: Date.now().toString(),
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
      id: Date.now().toString(),
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
    fetchConversations().then((convs) => setConversations(convs)).catch(() => {})
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

  // Spotlight dynamic styles — overridden for remote/mobile view
  // Both-open layout constants
  const BOTH_OPEN_TILT = 15; // degrees
  const ORB_RADIUS = orbDiameter / 2; // dynamic from parent
  const ORB_WING_GAP = -20; // negative = wings pulled closer to orb

  const getSpotlightWidth = () => {
    if (isRemoteView) return 'calc(100vw - 24px)';
    if (isInChatSpotlight) return 680; // Spotlight width (2×)
    if (isInDashboardSpotlight) return 360; // Background width (2×)
    return 510; // Balanced width (2×)
  };

  // How far the tilted inner edge visually extends toward the orb due to perspective.
  const getTiltExtension = (width: number, angleDeg: number) => {
    const rad = (angleDeg * Math.PI) / 180;
    const sin = Math.sin(rad);
    const cos = Math.cos(rad);
    const perspective = 800;
    const z = width * sin;
    const scale = perspective / (perspective - z);
    return width * (cos * scale - 1);
  };

  const getSpotlightTransform = () => {
    if (isRemoteView) return 'rotateY(0deg) rotateX(0deg)';
    if (isInChatSpotlight) return 'rotateY(0deg) rotateX(0deg)';
    if (isInDashboardSpotlight) return 'rotateY(15deg) rotateX(2deg)';
    if (isDashboardOpen) return `rotateY(${BOTH_OPEN_TILT}deg) rotateX(2deg)`; // Both open: tilted divider
    return 'rotateY(15deg) rotateX(2deg)';
  };

  const getSpotlightOpacity = () => {
    if (isRemoteView) return 1.0;
    if (isInDashboardSpotlight) return 0.3;
    return 1.0;
  };

  const getSpotlightFilter = () => {
    if (isRemoteView) return 'none';
    if (isInDashboardSpotlight) return 'saturate(0.6) blur(2px)';
    return 'none';
  };

  const getSpotlightZIndex = () => {
    if (isRemoteView) return 20;
    if (isInChatSpotlight) return 20;
    if (isInDashboardSpotlight) return 5;
    return 10;
  };

  const getSpotlightPointerEvents = () => {
    if (isRemoteView) return 'auto';
    if (isInDashboardSpotlight) return 'none';
    return 'auto';
  };

  // Remote/mobile view: minimized centered panel with horizontal padding, no offset, no tilt
  const getOuterLeft = () => {
    if (isRemoteView) return '12px';
    if (isDashboardOpen) {
      // CHAT SPOTLIGHT: pin chat to left edge so it's fully visible within frame.
      if (isInChatSpotlight) return 0;
      // DASHBOARD SPOTLIGHT: chat is blurred background — shift closer to left edge.
      if (isInDashboardSpotlight) return 80;
      // BALANCED: both wings meet at center with tilt formula.
      const width = getSpotlightWidth() as number;
      const extension = getTiltExtension(width, BOTH_OPEN_TILT);
      return windowWidth / 2 - ORB_RADIUS - ORB_WING_GAP - extension - width;
    }
    return 252;
  };
  const getOuterTop = () => isRemoteView ? '16px' : '6vh';
  const getOuterHeight = () => isRemoteView ? 'calc(100dvh - 32px)' : '88vh';
  const getOuterMaxHeight = () => isRemoteView ? 'calc(100dvh - 32px)' : 'calc(100vh - 24px)';
  const getOuterPerspective = () => isRemoteView ? 'none' : '800px';
  const getInnerBorderRadius = () => isRemoteView ? '16px' : '12px';

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          ref={chatOuterRef}
          className="fixed"
          initial={isRemoteView ? {} : { x: -120, opacity: 0, scale: 0.95 }}
          animate={isRemoteView ? {} : {
            x: 0,
            opacity: getSpotlightOpacity(),
            scale: 1
          }}
          exit={isRemoteView ? {} : { x: -120, opacity: 0, scale: 0.95 }}
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
              animate={isRemoteView ? {} : {
                transform: getSpotlightTransform()
              }}
              transition={isRemoteView ? { duration: 0 } : {
                type: "spring",
                stiffness: 280,
                damping: 25,
                mass: 0.8
              }}
            style={{
              transformOrigin: 'left center',
              transformStyle: isRemoteView ? 'flat' : 'preserve-3d',
              transform: isRemoteView ? 'rotateY(0deg) rotateX(0deg)' : undefined,
              background: 'linear-gradient(135deg, rgba(10,11,22,0.97) 0%, rgba(6,7,14,0.99) 100%)',
              boxShadow: isRemoteView ? `
                inset 0 1px 1px rgba(255,255,255,0.05),
                inset 0 -1px 1px rgba(0,0,0,0.5),
                0 0 0 1px rgba(0,0,0,0.8),
                0 8px 32px rgba(0,0,0,0.5)
              ` : `
                inset 0 1px 1px rgba(255,255,255,0.05),
                inset 0 -1px 1px rgba(0,0,0,0.5),
                0 0 0 1px rgba(0,0,0,0.8),
                20px 0 60px rgba(0,0,0,0.5)
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
            <div 
              className={isRemoteView ? "h-[60px] px-4 flex items-center flex-shrink-0 border-b relative z-30" : "h-12 px-3 flex items-center flex-shrink-0 border-b relative z-30"}
              style={{ borderColor: `${glowColor}15`, position: 'relative' }}
            >
              {/* Global error line */}
              {globalError && (
                <motion.div
                  className="absolute top-0 left-0 right-0 h-[1px] z-40"
                  style={{ background: 'rgba(239,68,68,0.8)' }}
                  animate={{ opacity: [1, 0.3, 1] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}
              
              {/* Left section: Pulse + Title + Dashboard */}
              <div className="flex items-center gap-2 flex-1">
                <motion.div
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: glowColor }}
                  animate={{
                    scale: voiceState === 'listening' ? [1, 1.4, 1] : 1,
                    opacity: voiceState === 'listening' ? [1, 0.6, 1] : 1
                  }}
                  transition={{ duration: 1.2, repeat: Infinity }}
                />
                <span
                  className="text-[13px] font-semibold tracking-wide"
                  style={{ color: fontColor, opacity: 0.9 }}
                >
                  IRIS
                </span>
                {/* Dashboard - positioned next to IRIS text - toggles open/close */}
                <button
                  onClick={() => {
                    if (isDashboardOpen && onDashboardClose) {
                      onDashboardClose();
                    } else {
                      onDashboardClick();
                    }
                    closeDropdowns();
                  }}
                  className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-1.5 rounded-lg transition-all duration-150"}
                  style={{
                    color: isDashboardOpen ? glowColor : 'rgba(255,255,255,0.75)',
                    backgroundColor: isDashboardOpen ? `${glowColor}15` : 'transparent'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = isDashboardOpen ? glowColor : 'rgba(255,255,255,0.95)';
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = isDashboardOpen ? glowColor : 'rgba(255,255,255,0.75)';
                    e.currentTarget.style.backgroundColor = isDashboardOpen ? `${glowColor}15` : 'transparent';
                  }}
                  title={isDashboardOpen ? "Close Dashboard" : "Open Dashboard"}
                >
                  <BarChart3 size={isRemoteView ? 20 : 14} />
                </button>
              </div>

              {/* Center: Spotlight Iris Aperture Button — embedded on top border line */}
              {onSpotlightToggle && (
                <div className="absolute left-1/2 -translate-x-1/2 top-0 -translate-y-1/2 z-40">
                  <button
                    onClick={() => {
                      onSpotlightToggle();
                      closeDropdowns();
                    }}
                    className={isRemoteView ? "p-2.5 rounded-full transition-all duration-150 border min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-1.5 rounded-full transition-all duration-150 border"}
                    style={{
                      color: isInChatSpotlight ? glowColor : 'rgba(255,255,255,0.7)',
                      backgroundColor: isInChatSpotlight ? `${glowColor}20` : 'transparent',
                      borderColor: isInChatSpotlight ? `${glowColor}50` : 'rgba(255,255,255,0.2)',
                      boxShadow: isInChatSpotlight ? `0 0 8px ${glowColor}40` : 'none',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = glowColor;
                      e.currentTarget.style.borderColor = `${glowColor}50`;
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = isInChatSpotlight ? glowColor : 'rgba(255,255,255,0.7)';
                      e.currentTarget.style.borderColor = isInChatSpotlight ? `${glowColor}50` : 'rgba(255,255,255,0.2)';
                    }}
                    title={isInChatSpotlight ? "Restore balanced view" : "Maximize chat"}
                  >
                    <IrisApertureIcon
                      isActive={isInChatSpotlight}
                      glowColor={glowColor}
                      fontColor={fontColor}
                      size={isRemoteView ? 18 : 14}
                    />
                  </button>
                </div>
              )}

              {/* Right section: Notifications + History + Close */}
              <div className="flex items-center gap-1 flex-1 justify-end">
                {/* Notifications */}
                <button
                  onClick={() => showNotifications ? closeDropdowns() : openNotifications()}
                  className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 relative min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-2 rounded-lg transition-all duration-150 relative"}
                  style={{
                    color: showNotifications ? glowColor : unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.75)',
                    backgroundColor: showNotifications ? `${glowColor}15` : 'transparent'
                  }}
                  onMouseEnter={(e) => {
                    if (!showNotifications) e.currentTarget.style.color = unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.95)';
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    if (!showNotifications) e.currentTarget.style.color = unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.75)';
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title="Notifications"
                >
                  <Bell size={16} />
                  {unreadCount > 0 && (
                    <motion.span
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      className="absolute top-1 right-1 w-2 h-2 rounded-full"
                      style={{ backgroundColor: glowColor }}
                    />
                  )}
                </button>

                {/* History */}
                <button
                  onClick={() => showHistory ? closeDropdowns() : openHistory()}
                  className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-2 rounded-lg transition-all duration-150"}
                  style={{
                    color: showHistory ? glowColor : 'rgba(255,255,255,0.75)',
                    backgroundColor: showHistory ? `${glowColor}15` : 'transparent'
                  }}
                  onMouseEnter={(e) => {
                    if (!showHistory) e.currentTarget.style.color = 'rgba(255,255,255,0.95)';
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    if (!showHistory) e.currentTarget.style.color = 'rgba(255,255,255,0.75)';
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title="Conversation History"
                >
                  <History size={isRemoteView ? 20 : 16} />
                </button>

                {/* Close */}
                <button
                  onClick={() => {
                    onClose();
                    closeDropdowns();
                  }}
                  className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-2 rounded-lg transition-all duration-150"}
                  style={{ color: 'rgba(255,255,255,0.75)' }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = 'rgba(255,255,255,0.95)';
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = 'rgba(255,255,255,0.75)';
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title="Close Chat"
                >
                  <X size={isRemoteView ? 20 : 16} />
                </button>
              </div>
            </div>

            {/* Notification Dropdown Panel */}
            <AnimatePresence>
              {showNotifications && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                  className="overflow-hidden border-b flex-shrink-0 z-20"
                  style={{ 
                    borderColor: `${glowColor}10`,
                    background: 'linear-gradient(180deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
                    backdropFilter: 'blur(20px)',
                    maxHeight: '50%'
                  }}
                >
                  <div className="p-3 space-y-2 overflow-y-auto">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-semibold tracking-widest uppercase text-white/50">
                        Notifications
                      </span>
                      {notifications.length > 0 && (
                        <button
                          onClick={() => setNotifications([])}
                          className="text-[9px] px-2 py-1 rounded transition-colors text-white/40 hover:text-white/70 hover:bg-white/5"
                        >
                          Clear all
                        </button>
                      )}
                    </div>
                    
                    {notifications.length === 0 ? (
                      <div className="text-center py-6 text-[11px] text-white/40">
                        No notifications
                      </div>
                    ) : (
                      notifications.map((notif) => (
                        <motion.div
                          key={notif.id}
                          initial={{ x: unreadCount > 0 && !notif.read ? -10 : 0, opacity: 0 }}
                          animate={{ x: 0, opacity: 1 }}
                          className="p-2.5 rounded-lg transition-all duration-150 group relative overflow-hidden"
                          style={{
                            backgroundColor: !notif.read ? `${glowColor}08` : 'rgba(255,255,255,0.03)',
                            borderLeft: `2px solid ${getNotificationColor(notif.type, glowColor)}`
                          }}
                        >
                          {/* Type indicator glow */}
                          <div 
                            className="absolute top-0 right-0 w-16 h-16 opacity-10 blur-xl rounded-full -translate-y-1/2 translate-x-1/2"
                            style={{ backgroundColor: getNotificationColor(notif.type, glowColor) }}
                          />
                          
                          <div className="flex items-start justify-between relative">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-1">
                                {getNotificationIcon(notif.type, glowColor)}
                                <span 
                                  className="text-[9px] font-semibold tracking-wide uppercase"
                                  style={{ color: getNotificationColor(notif.type, glowColor) }}
                                >
                                  {notif.type}
                                </span>
                                <span className="text-[8px] text-white/30 tabular-nums ml-auto">
                                  {notif.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                </span>
                              </div>
                              <p className="text-[11px] font-medium text-white/90 leading-snug">
                                {notif.title}
                              </p>
                              <p className="text-[10px] text-white/60 mt-0.5 line-clamp-2">
                                {notif.message}
                              </p>
                            </div>
                          </div>
                          
                          {/* Action buttons based on type */}
                          {notif.type === 'permission' && (
                            <div className="flex gap-2 mt-2">
                              <button
                                onClick={() => handlePermissionGrant(notif.id)}
                                className="flex-1 py-1 rounded text-[9px] font-medium transition-colors"
                                style={{ 
                                  background: `${glowColor}20`,
                                  color: glowColor
                                }}
                              >
                                Allow
                              </button>
                              <button
                                onClick={() => handlePermissionDeny(notif.id)}
                                className="flex-1 py-1 rounded text-[9px] font-medium transition-colors bg-white/10 text-white/70 hover:bg-white/15"
                              >
                                Deny
                              </button>
                            </div>
                          )}
                          
                          {notif.type === 'task' && (
                            <div className="mt-2">
                              <div className="h-1 bg-white/10 rounded-full overflow-hidden">
                                <motion.div 
                                  className="h-full rounded-full"
                                  style={{ backgroundColor: glowColor }}
                                  initial={{ width: 0 }}
                                  animate={{ width: `${notif.progress || 0}%` }}
                                />
                              </div>
                              <span className="text-[8px] text-white/40 mt-1 block">
                                {notif.progress || 0}% complete
                              </span>
                            </div>
                          )}
                        </motion.div>
                      ))
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* History Dropdown Panel - Thread-Based */}
            <AnimatePresence>
              {showHistory && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: prefersReducedMotion ? 0 : 0.2, ease: [0.22, 1, 0.36, 1] }}
                  className="overflow-hidden border-b flex-shrink-0 z-20"
                  style={{ 
                    borderColor: `${glowColor}10`,
                    background: 'linear-gradient(180deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
                    backdropFilter: 'blur(20px)',
                    maxHeight: '50%'
                  }}
                >
                  <div className="p-3 space-y-2 overflow-y-auto">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-semibold tracking-widest uppercase text-white/50">
                        Conversation Threads
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] text-white/30">
                          {conversations.length} total
                        </span>
                        <button
                          onClick={handleNewConversation}
                          className="p-1.5 rounded transition-all duration-150 flex items-center gap-1"
                          style={{ color: `${fontColor}50` }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = glowColor;
                            e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = `${fontColor}50`;
                            e.currentTarget.style.backgroundColor = 'transparent';
                          }}
                          title="Start new conversation"
                          aria-label="New conversation"
                        >
                          <Plus size={12} />
                        </button>
                      </div>
                    </div>
                    
                    {conversations.length === 0 ? (
                      <div className="text-center py-6 text-[11px] text-white/40">
                        No conversations yet
                      </div>
                    ) : (
                      conversations.map((conv) => (
                        <motion.div
                          key={conv.id}
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          onClick={() => handleSelectConversation(conv.id)}
                          className="group relative p-2.5 rounded-lg cursor-pointer transition-all duration-150 hover:bg-white/5"
                          style={{
                            backgroundColor: activeConversationId === conv.id ? `${glowColor}15` : 'rgba(255,255,255,0.03)',
                            borderLeft: `2px solid ${activeConversationId === conv.id ? glowColor : 'transparent'}`
                          }}
                        >
                          <div className="flex items-center gap-2">
                            {/* Content */}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-1">
                                {conv.isPinned && (
                                  <Pin size={10} style={{ color: glowColor }} className="fill-current flex-shrink-0" />
                                )}
                                <span className="text-[10px] font-medium text-white/90 truncate">
                                  {conv.title}
                                </span>
                                <span className="text-[8px] text-white/30 tabular-nums flex-shrink-0">
                                  {conv.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                </span>
                              </div>
                              <p className="text-[9px] text-white/50 truncate leading-snug">
                                {conv.lastMessagePreview}
                                {conv.lastMessagePreview.length >= 60 ? '...' : ''}
                              </p>
                              <span className="text-[8px] text-white/30 mt-1 block">
                                {conv.messages.length} message{conv.messages.length !== 1 ? 's' : ''}
                              </span>
                            </div>
                            
                            {/* Action buttons - centered on right */}
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 self-center">
                              <button
                                onClick={(e) => handlePinConversation(e, conv.id)}
                                className="p-1.5 rounded transition-colors hover:bg-white/10"
                                style={{ color: conv.isPinned ? glowColor : 'rgba(255,255,255,0.5)' }}
                                title={conv.isPinned ? 'Unpin' : 'Pin to top'}
                              >
                                <Pin size={12} className={conv.isPinned ? 'fill-current' : ''} />
                              </button>
                              <button
                                onClick={(e) => handleDeleteConversation(e, conv.id)}
                                className="p-1.5 rounded transition-colors hover:bg-white/10 text-white/50 hover:text-red-400"
                                title="Delete conversation"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          </div>
                        </motion.div>
                      ))
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

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
            <div
              ref={messagesContainerRef}
              className="flex-1 overflow-y-auto px-3 py-3 relative z-10"
              // DIAGNOSTIC (2026-08-17): surfaces the exact values that decide
              // whether the thinking indicator renders, so the blind window
              // between "steps finished" and "answer arrives" can be measured
              // instead of inferred from page text. Remove once the indicator
              // and the task-card counter are confirmed in sync.
              data-dbg-typing={String(isTyping)}
              data-dbg-steps-running={String(taskProgressStillRunning)}
              data-dbg-steps={`${taskProgress.currentStep}/${taskProgress.totalSteps}`}
              data-dbg-statuses={taskProgress.steps.map((s) => s.status).join(",")}
              data-dbg-working={String(taskProgress.isWorking)}
            >
              {/* Session 246: the empty-state placeholder must NOT hide task
                  cards. A thread can hold a card with no rendered messages —
                  a simulation, or a rehydrated card whose messages are still
                  loading (conv-40 evidence). Cards count as content. */}
              {(unifiedTimeline ? unifiedTimeline.length === 0 : (messages.length === 0 && renderTimeline.length === 0)) && !isTyping ? (
                <div 
                  className="flex-1 flex items-center justify-center h-full"
                  style={{ color: `${fontColor}50` }}
                >
                  <p className="text-center text-[11px]">
                    {conversations.length === 0 ? (
                      <>
                        Start a conversation
                        <br />
                        <span className="text-[10px] opacity-70">How can I help you today?</span>
                      </>
                    ) : (
                      <>
                        Select a conversation
                        <br />
                        <span className="text-[10px] opacity-70">or start a new one</span>
                      </>
                    )}
                  </p>
                </div>
              ) : (
                <div className="space-y-0">
                  {renderTimeline.map((entry) => {
                    // T4 (REQ-1/REQ-3): shell lines interleave chronologically
                    // between chat messages in developer mode — one stream.
                    if (entry.kind === "shell") {
                      const line = entry.line
                      return (
                        <div key={`shell-${line.id}`} className="py-0.5 font-mono text-[10px] leading-snug break-all whitespace-pre-wrap"
                          style={{
                            color:
                              line.kind === "command" ? glowColor
                              : line.kind === "error" ? '#ef4444'
                              : line.kind === "system" ? 'rgba(255,255,255,0.45)'
                              : 'rgba(255,255,255,0.75)',
                          }}
                        >
                          {line.text}
                        </div>
                      )
                    }
                    // Session 244: task cards render INLINE — after the
                    // assistant message they belong to (responseTurnId join),
                    // or at the bottom for unmatched/legacy cards. Dev mode
                    // renders the Blueprint Matrix; personal the GUI card.
                    if (entry.kind === "card") {
                      const card = entry.card
                      return isDeveloper ? (
                        <div key={`card-${card.cardId}`} className="py-1">
                          <pre
                            className="font-mono text-[9px] leading-[1.35] overflow-x-auto whitespace-pre"
                            style={{ color: 'rgba(255,255,255,0.85)' }}
                          >
                            {renderBlueprintCellMatrixCLI(taskCardToMatrixProps(card), false)
                              .split("\n")
                              .map((ln, i) =>
                                ln.includes("TASK :") ? (
                                  <span key={i} style={{ color: glowColor }}>{ln}{"\n"}</span>
                                ) : (
                                  <span key={i}>{ln}{"\n"}</span>
                                )
                              )}
                          </pre>
                          {/* REQ-3 AC2: elapsed running timer while live */}
                          {card.isWorking && (
                            <div className="font-mono text-[9px] mt-0.5" style={{ color: glowColor }}>
                              ⏱ {String(Math.floor(matrixElapsedSec / 60)).padStart(2, "0")}:
                              {String(matrixElapsedSec % 60).padStart(2, "0")}
                            </div>
                          )}
                        </div>
                      ) : (
                        <TaskListCard
                          key={card.cardId}
                          cardId={card.cardId}
                          steps={card.steps}
                          turnId={card.turnId}
                          mode={card.mode}
                          planTitle={card.planTitle}
                          learningSignal={card.learningSignal}
                          memoryEvents={card.memoryEvents}
                          currentAction={card.currentAction}
                          /* Session 245 (pin_07b780e7ce21): structured crawl
                             phase rotates the working step's verb.
                           * Session 246: the THK stream comes from the card's
                             own bounded action history (real progress frames,
                             REQ-10 AC4). NOTE: the previous expression read
                             `entry.message?.thinking` here, but `entry` is
                             narrowed to the card kind in this branch — a
                             latent TS error from session 245's parse-check-
                             only pass. Streamed reasoning stays visible on
                             the assistant message itself. */
                          phase={card.phase}
                          durationSec={card.durationSec}
                          cardActive={card.isWorking}
                          thoughtStream={card.isWorking ? (card.actionStream ?? undefined) : undefined}
                        />
                      )
                    }
                    const message = entry.message
                    const index = entry.index
                    // Smart message length handling
                    const charCount = message.text.length;
                    const contentType = getContentType(message);
                    const isExpanded = isMessageExpanded(message.id);
                    const shouldTruncate = charCount > MESSAGE_THRESHOLDS.TRUNCATE_AT;
                    // Artifact card rules:
                    //   - Media, email, explicit file uploads → artifact at DOCUMENT_MODE_AT (400 chars)
                    //   - Long markdown from assistant (code blocks, headers) → artifact at MARKDOWN_ARTIFACT_AT (800 chars)
                    //     This keeps voice-first UX clean: the full response is always readable,
                    //     but the chat thread stays concise — tap to expand if needed.
                    //   - Plain conversational text → always flows as chat (truncate/expand only)
                    // Is TTS saying something OTHER than this body? For a long
                    // answer the backend speaks a short summary briefing, and
                    // its tts_word indices count THAT string's words — so the
                    // body must not be highlighted against them (user rule
                    // 2026-08-17: long content is read, not spoken along to).
                    //
                    // The briefing itself is deliberately NOT rendered: it is a
                    // summary of text already fully visible right here, and
                    // showing both duplicates content. It exists as data only,
                    // to answer this one question.
                    const spokenLineForMsg = (message.spoken || '').trim();
                    const spokenDiffersFromBody =
                      message.sender === 'assistant' &&
                      spokenLineForMsg.length > 0 &&
                      spokenLineForMsg !== message.text.trim() &&
                      spokenLineForMsg.length < message.text.trim().length;
                    const isExplicitFile = message.text.startsWith('[File:') || message.text.startsWith('[IMAGE:') || message.text.startsWith('[VIDEO:');
                    // REMOVED 2026-08-17: isAssistantMarkdown — a long assistant answer
                    // was turned into a "document" purely by LENGTH + markdown syntax
                    // (contentType==='markdown' && charCount > 800), with no backend
                    // involvement at all.
                    //
                    // That produced a FAKE document: no document_id, nothing in the
                    // document store, no format alternatives, no reformat, no prism
                    // card — just a 3-line clip, a char count, and a modal rendering
                    // the raw markdown in <pre> monospace. Strictly worse than leaving
                    // it in the thread, and it is the same error the backend carried
                    // until today: LENGTH used as a proxy for "this is a document".
                    //
                    // A document is what the AGENT stored via a `show` payload. Those
                    // arrive as DOCUMENT_RENDER, are keyed by documentId, and render
                    // through <RichDocument> (the prism card) further down. Everything
                    // else is conversation and stays in the thread, in full, with
                    // truncate/expand for length.
                    const isDocumentMode = (isExplicitFile || contentType === 'email' || contentType === 'picture' || contentType === 'video') && charCount > MESSAGE_THRESHOLDS.DOCUMENT_MODE_AT;
                    
                    // Content type icon mapping
                    const ContentTypeIcon = ({ size = 12 }: { size?: number }) => {
                      const style = { color: glowColor };
                      switch (contentType) {
                        case 'markdown': return <FileText size={size} style={style} />;
                        case 'email': return <Mail size={size} style={style} />;
                        case 'video': return <Video size={size} style={style} />;
                        case 'picture': return <Image size={size} style={style} />;
                        default: return <File size={size} style={style} />;
                      }
                    };
                    
                    return (
                    <div key={message.id} id={`msg-${message.id}`}>
                      {/* Horizontal separator */}
                      {index > 0 && (
                        <div 
                          className="h-px w-full my-3"
                          style={{ backgroundColor: `${glowColor}10` }}
                        />
                      )}
                      
                      <div
                        className={`flex justify-start`}
                      >
                        {message.sender === 'user' ? (
                          // User message - no bubble container
                          <motion.div
                            initial={{ opacity: prefersReducedMotion ? 1 : 0, y: prefersReducedMotion ? 0 : 5 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: prefersReducedMotion ? 0 : 0.15 }}
                            className="max-w-[90%] py-2"
                          >
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[9px] font-medium text-white/40">You</span>
                              <span className="text-[8px] text-white/30 tabular-nums">
                                {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                              </span>
                            </div>
                            
                            {/* Smart message length handling for user messages */}
                            {isDocumentMode ? (
                              // Document mode for long messages
                              <div className="mt-1">
                                <p className="text-[13px] leading-relaxed text-white/85 line-clamp-3">
                                  {message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT)}...
                                </p>
                                <p className="text-[9px] text-white/40 mt-1">
                                  {charCount.toLocaleString()} characters
                                </p>
                                <div className="flex gap-2 mt-3">
                                  <button
                                    onClick={() => setDocumentModalMessage(message)}
                                    className="flex-1 py-1.5 px-3 rounded text-[10px] font-medium transition-all"
                                    style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
                                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}30`; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}20`; }}
                                  >
                                    View full document
                                  </button>
                                  {onOpenBrowserUrl && (
                                    <button
                                      onClick={() => {
                                        const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{font-family:system-ui,sans-serif;padding:2rem;max-width:800px;margin:0 auto;line-height:1.6;white-space:pre-wrap;word-break:break-word}</style></head><body>${message.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</body></html>`;
                                        onOpenBrowserUrl(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
                                      }}
                                      className="p-1.5 rounded transition-colors"
                                      style={{ color: `${fontColor}60` }}
                                      onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                      onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                      title="Open in browser tab"
                                    >
                                      <ExternalLink size={14} />
                                    </button>
                                  )}
                                  <button
                                    onClick={() => handleShareMessage(message)}
                                    className="p-1.5 rounded transition-colors"
                                    style={{ color: `${fontColor}60` }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                    title="Share"
                                  >
                                    <Share size={14} />
                                  </button>
                                  <button
                                    onClick={() => handleDownloadMessage(message)}
                                    className="p-1.5 rounded transition-colors"
                                    style={{ color: `${fontColor}60` }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                    title="Download"
                                  >
                                    <Download size={14} />
                                  </button>
                                </div>
                              </div>
                            ) : shouldTruncate ? (
                              // Truncated message with expand option
                              <div className="mt-1">
                                <div className="flex items-center gap-1 mb-1">
                                  <ContentTypeIcon size={12} />
                                  <span className="text-[9px] text-white/50 uppercase tracking-wide">{contentType}</span>
                                </div>
                                <div className="relative">
                                  <p className="text-[13px] leading-relaxed text-white/90">
                                    {isExpanded ? message.text : message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT) + '...'}
                                  </p>
                                  {!isExpanded && (
                                    <div 
                                      className="absolute bottom-0 left-0 right-0 h-6 pointer-events-none"
                                      style={{ background: 'linear-gradient(to bottom, transparent, rgba(10,10,20,0.95))' }}
                                    />
                                  )}
                                </div>
                                <button
                                  onClick={() => toggleMessageExpanded(message.id)}
                                  className="mt-1 flex items-center gap-1 text-[10px] font-medium transition-colors"
                                  style={{ color: glowColor }}
                                  aria-expanded={isExpanded}
                                >
                                  {isExpanded ? (
                                    <>Show less <ChevronUp size={12} /></>
                                  ) : (
                                    <>Show more <ChevronDown size={12} /></>
                                  )}
                                </button>
                                {isExpanded && (
                                  <div className="flex gap-2 mt-2 pt-2 border-t border-white/10">
                                    <button
                                      onClick={() => handleShareMessage(message)}
                                      className="p-1.5 rounded transition-colors hover:bg-white/5"
                                      style={{ color: `${fontColor}70` }}
                                      title="Share"
                                    >
                                      <Share size={14} />
                                    </button>
                                    <button
                                      onClick={() => handleDownloadMessage(message)}
                                      className="p-1.5 rounded transition-colors hover:bg-white/5"
                                      style={{ color: `${fontColor}70` }}
                                      title="Download"
                                    >
                                      <Download size={14} />
                                    </button>
                                  </div>
                                )}
                              </div>
                            ) : (
                              // Short message - display fully
                              <p className="text-[13px] leading-relaxed text-white/90">{renderWithLinks(message.text)}</p>
                            )}

                            {/* Prompt actions. Retry and Edit act on the PROMPT,
                                so they live on the user's turn — re-running the
                                agent's reply was never the thing being retried. */}
                            {editingMessageId === message.id ? (
                              <div className="mt-2 pt-2 border-t border-white/5">
                                <textarea
                                  value={editingText}
                                  onChange={(e) => setEditingText(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter" && !e.shiftKey) {
                                      e.preventDefault()
                                      handleResendUserMessage(index, activeConversationId!, editingText)
                                    }
                                    if (e.key === "Escape") setEditingMessageId(null)
                                  }}
                                  autoFocus
                                  rows={Math.min(6, Math.max(2, editingText.split("\n").length))}
                                  className="w-full resize-y rounded px-2 py-1.5 text-[13px] leading-relaxed bg-white/5 text-white/90 outline-none"
                                  style={{ border: `1px solid ${glowColor}40` }}
                                  aria-label="Edit your prompt"
                                />
                                <div className="flex items-center gap-2 mt-1.5">
                                  <button
                                    onClick={() => handleResendUserMessage(index, activeConversationId!, editingText)}
                                    disabled={!editingText.trim() || !!retryingMessageId}
                                    className="px-2 py-1 rounded text-[10px] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                    style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
                                  >
                                    Send revised
                                  </button>
                                  <button
                                    onClick={() => setEditingMessageId(null)}
                                    className="px-2 py-1 rounded text-[10px] text-white/40 hover:text-white/70 hover:bg-white/5 transition-colors"
                                  >
                                    Cancel
                                  </button>
                                  <span className="text-[9px] text-white/25 ml-auto">
                                    Enter to send · Esc to cancel
                                  </span>
                                </div>
                              </div>
                            ) : (
                              <div className="flex items-center gap-1 mt-1.5">
                                <button
                                  onClick={() => handleResendUserMessage(index, activeConversationId!)}
                                  disabled={!!retryingMessageId}
                                  className="p-1 rounded transition-colors text-white/25 hover:text-white/70 hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed"
                                  title="Retry — send this prompt again"
                                >
                                  <RefreshCw
                                    size={11}
                                    className={retryingMessageId === message.id ? "animate-spin" : ""}
                                  />
                                </button>
                                <button
                                  onClick={() => {
                                    setEditingText(message.text)
                                    setEditingMessageId(message.id)
                                  }}
                                  disabled={!!retryingMessageId}
                                  className="p-1 rounded transition-colors text-white/25 hover:text-white/70 hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed"
                                  title="Edit — revise this prompt and send it again"
                                >
                                  <Pencil size={11} />
                                </button>
                              </div>
                            )}
                          </motion.div>
                        ) : message.sender === 'assistant' ? (
                          // AI message - no bubble container with feedback bar
                          <motion.div
                            initial={{ opacity: prefersReducedMotion ? 1 : 0, y: prefersReducedMotion ? 0 : 5 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: prefersReducedMotion ? 0 : 0.15 }}
                            className="max-w-[90%] py-2"
                          >
                            <div className="flex items-center gap-2 mb-1.5">
                              <span 
                                className="text-[9px] font-semibold tracking-wide"
                                style={{ color: glowColor }}
                              >
                                IRIS
                              </span>
                              {isSpeaking && message.id === currentTtsMessageId && (
                                <Xur size={14} color={glowColor} speed={1.5} />
                              )}
                              <span className="text-[8px] text-white/30 tabular-nums ml-auto">
                                {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                              </span>
                            </div>
                            
                            {/* Collapsible thinking block — only shown when model produced reasoning */}
                            {message.thinking && (
                              <div className="mb-2">
                                <button
                                  onClick={() => setExpandedThinking(prev => {
                                    const next = new Set(prev);
                                    next.has(message.id) ? next.delete(message.id) : next.add(message.id);
                                    return next;
                                  })}
                                  className="flex items-center gap-1.5 text-[9px] font-medium tracking-wide uppercase transition-colors"
                                  style={{ color: 'rgba(255,255,255,0.3)' }}
                                  aria-expanded={expandedThinking.has(message.id)}
                                >
                                  {expandedThinking.has(message.id)
                                    ? <><ChevronUp size={10} /> Hide thinking</>
                                    : <><ChevronDown size={10} /> Show thinking</>}
                                </button>
                                <AnimatePresence>
                                  {expandedThinking.has(message.id) && (
                                    <motion.div
                                      initial={{ height: 0, opacity: 0 }}
                                      animate={{ height: 'auto', opacity: 1 }}
                                      exit={{ height: 0, opacity: 0 }}
                                      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                                      className="overflow-hidden"
                                    >
                                      <div
                                        className="mt-1.5 p-2.5 rounded text-[11px] leading-relaxed whitespace-pre-wrap font-mono"
                                        style={{
                                          color: 'rgba(255,255,255,0.35)',
                                          background: 'rgba(255,255,255,0.03)',
                                          borderLeft: '2px solid rgba(255,255,255,0.08)',
                                        }}
                                      >
                                        {message.thinking}
                                      </div>
                                    </motion.div>
                                  )}
                                </AnimatePresence>
                              </div>
                            )}

                            {/* Message content with smart length handling and TTS highlighting */}
                            {isDocumentMode ? (
                              // Document mode for long messages
                              <div className="mt-1">
                                <p className="text-[13px] leading-relaxed text-white/85 line-clamp-3">
                                  {message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT)}...
                                </p>
                                <p className="text-[9px] text-white/40 mt-1">
                                  {charCount.toLocaleString()} characters
                                </p>
                                <div className="flex gap-2 mt-3">
                                  <button
                                    onClick={() => setDocumentModalMessage(message)}
                                    className="flex-1 py-1.5 px-3 rounded text-[10px] font-medium transition-all"
                                    style={{ backgroundColor: `${glowColor}20`, color: glowColor }}
                                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}30`; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = `${glowColor}20`; }}
                                  >
                                    View full document
                                  </button>
                                  {onOpenBrowserUrl && (
                                    <button
                                      onClick={() => {
                                        const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{font-family:system-ui,sans-serif;padding:2rem;max-width:800px;margin:0 auto;line-height:1.6;white-space:pre-wrap;word-break:break-word}</style></head><body>${message.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</body></html>`;
                                        onOpenBrowserUrl(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
                                      }}
                                      className="p-1.5 rounded transition-colors"
                                      style={{ color: `${fontColor}60` }}
                                      onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                      onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                      title="Open in browser tab"
                                    >
                                      <ExternalLink size={14} />
                                    </button>
                                  )}
                                  <button
                                    onClick={() => handleShareMessage(message)}
                                    className="p-1.5 rounded transition-colors"
                                    style={{ color: `${fontColor}60` }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                    title="Share"
                                  >
                                    <Share size={14} />
                                  </button>
                                  <button
                                    onClick={() => handleDownloadMessage(message)}
                                    className="p-1.5 rounded transition-colors"
                                    style={{ color: `${fontColor}60` }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = fontColor; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = `${fontColor}60`; e.currentTarget.style.backgroundColor = 'transparent'; }}
                                    title="Download"
                                  >
                                    <Download size={14} />
                                  </button>
                                </div>
                              </div>
                            ) : shouldTruncate ? (
                              // Truncated message with expand option
                              <div className="mt-1">
                                <div className="flex items-center gap-1 mb-1">
                                  <ContentTypeIcon size={12} />
                                  <span className="text-[9px] text-white/50 uppercase tracking-wide">{contentType}</span>
                                </div>
                                <div className="relative">
                                  {/* Body: markdown, never word-highlighted.
                                      A long answer is READ, not spoken — the
                                      spoken briefing below is what TTS says and
                                      what the highlight tracks (user rule
                                      2026-08-17). Collapsed state clamps the
                                      RENDERED output with CSS instead of slicing
                                      the source, which would cut markdown
                                      mid-syntax and break the render. */}
                                  <MarkdownMessage
                                    text={message.text}
                                    className={isExpanded ? '' : 'line-clamp-6'}
                                  />
                                  {!isExpanded && (
                                    <div 
                                      className="absolute bottom-0 left-0 right-0 h-6 pointer-events-none"
                                      style={{ background: 'linear-gradient(to bottom, transparent, rgba(10,10,20,0.95))' }}
                                    />
                                  )}
                                </div>
                                <button
                                  onClick={() => toggleMessageExpanded(message.id)}
                                  className="mt-1 flex items-center gap-1 text-[10px] font-medium transition-colors"
                                  style={{ color: glowColor }}
                                  aria-expanded={isExpanded}
                                >
                                  {isExpanded ? (
                                    <>Show less <ChevronUp size={12} /></>
                                  ) : (
                                    <>Show more <ChevronDown size={12} /></>
                                  )}
                                </button>
                                {isExpanded && (
                                  <div className="flex gap-2 mt-2 pt-2 border-t border-white/10">
                                    <button
                                      onClick={() => handleShareMessage(message)}
                                      className="p-1.5 rounded transition-colors hover:bg-white/5"
                                      style={{ color: `${fontColor}70` }}
                                      title="Share"
                                    >
                                      <Share size={14} />
                                    </button>
                                    <button
                                      onClick={() => handleDownloadMessage(message)}
                                      className="p-1.5 rounded transition-colors hover:bg-white/5"
                                      style={{ color: `${fontColor}70` }}
                                      title="Download"
                                    >
                                      <Download size={14} />
                                    </button>
                                  </div>
                                )}
                              </div>
                            ) : (
                              // Short message — displayed in full. When the
                              // spoken line IS this text (the usual short case),
                              // the highlight rides directly on the rendered
                              // markdown via the overlay. When TTS is saying a
                              // different (summary) line, the body stays plain
                              // and the briefing below carries the highlight.
                              <MarkdownMessage
                                text={message.text}
                                highlightActive={
                                  message.id === currentTtsMessageId && !spokenDiffersFromBody
                                }
                                highlightIndex={ttsWordIndex}
                              />
                            )}
                            
                            {/* Feedback action bar */}
                            <div className="flex items-center gap-2 mt-2 pt-2 border-t border-white/5">
                              {/* Icon-only, like every other action here. The
                                  "Copy"/"Copied!" label was the one text button
                                  in the row; confirmation is the colour flash. */}
                              <button
                                onClick={() => handleCopyMessage(message.text, message.id)}
                                className={`p-1.5 rounded transition-colors hover:bg-white/5 ${
                                  copiedMessageId === message.id
                                    ? "text-green-400"
                                    : "text-white/40 hover:text-white/70"
                                }`}
                                title={copiedMessageId === message.id ? "Copied" : "Copy to clipboard"}
                              >
                                <Copy size={12} />
                              </button>

                              <button
                                onClick={() => handlePlayTTSClick(message.text)}
                                className="p-1.5 rounded transition-colors hover:bg-white/5 text-white/40 hover:text-white/70"
                                title="Play text-to-speech"
                              >
                                <Volume2 size={12} />
                              </button>

                              <div className="flex items-center gap-1 ml-auto">
                                <button
                                  onClick={() => handleFeedback(message.id, 'positive')}
                                  className={`p-1.5 rounded transition-colors ${
                                    message.feedback === 'positive' 
                                      ? 'text-green-400 bg-green-400/10' 
                                      : 'text-white/40 hover:text-white/70 hover:bg-white/5'
                                  }`}
                                  title="Helpful response"
                                >
                                  <ThumbsUp size={12} className={message.feedback === 'positive' ? 'fill-current' : ''} />
                                </button>
                                <button
                                  onClick={() => handleFeedback(message.id, 'negative')}
                                  className={`p-1.5 rounded transition-colors ${
                                    message.feedback === 'negative' 
                                      ? 'text-red-400 bg-red-400/10' 
                                      : 'text-white/40 hover:text-white/70 hover:bg-white/5'
                                  }`}
                                  title="Not helpful"
                                >
                                  <ThumbsDown size={12} className={message.feedback === 'negative' ? 'fill-current' : ''} />
                                </button>
                              </div>
                            </div>
                          </motion.div>
                        ) : message.sender === 'system' ? (
                          // System message (plan events: validation/recovery/budget/topology)
                          <motion.div
                            initial={{ opacity: prefersReducedMotion ? 1 : 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ duration: prefersReducedMotion ? 0 : 0.15 }}
                            className="max-w-[90%] py-2"
                          >
                            <div className="flex items-center gap-1.5 mb-1">
                              <Info size={10} className="text-amber-400" />
                              <span className="text-[9px] font-semibold text-amber-400">
                                System
                              </span>
                              <span className="text-[8px] text-white/30 tabular-nums ml-auto">
                                {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                              </span>
                            </div>
                            <p className="text-[12px] text-amber-100/90 leading-relaxed">{message.text}</p>
                          </motion.div>
                        ) : (
                          // Error message
                          <motion.div
                            initial={{ opacity: prefersReducedMotion ? 1 : 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ duration: prefersReducedMotion ? 0 : 0.15 }}
                            className="max-w-[90%] py-2"
                          >
                            <div className="flex items-center gap-1.5 mb-1">
                              <AlertCircle size={10} className="text-red-400" />
                              <span className="text-[9px] font-semibold text-red-400">
                                {message.errorType === 'voice' ? 'Voice Error' : 
                                 message.errorType === 'validation' ? 'Validation' : 'Error'}
                              </span>
                              <span className="text-[8px] text-white/30 tabular-nums ml-auto">
                                {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                              </span>
                            </div>
                            <p className="text-[12px] text-red-200/90 leading-relaxed">{message.text}</p>
                            <button
                              onClick={() => handleRetryPrompt(index, activeConversationId!)}
                              className="mt-1.5 flex items-center gap-1 text-[10px] font-medium text-red-300/70 hover:text-red-200 transition-colors"
                              title="Retry — re-send the last user message"
                            >
                              <RefreshCw size={10} />
                              Retry
                            </button>
                          </motion.div>
                        )}
                      </div>
                    </div>
                  );
                })}

                  {/* Rich documents (plan Issue D.3) — inline render with format pills + expand */}
                  {(() => {
                    // Sources render on ONE card per turn — the SYNTHESIZED
                    // (markdown) document — never on the mid-turn step cards.
                    // A websearch turn emits multiple `show` payloads (one per
                    // crawler_query step as a JSON card, then the final
                    // markdown synthesis), and each step card carries the full
                    // sources list while the synthesis card carries none
                    // (live 2026-08-12: two JSON cards with 2 sources each,
                    // markdown card with 0). Rendering sources on every card
                    // stacked duplicates; the canonical list also lives in the
                    // browser's summary tab (OPEN_TAB → dashboard_data.sources).
                    // So: the markdown card is the sources carrier, and it
                    // merges sources from its same-turn siblings when its own
                    // payload lacks them.
                    const _docs = activeConversation?.documents || []
                    const _turnSources = new Map<string, { url: string; title: string }[]>()
                    for (const d of _docs) {
                      if (!d.turnId) continue
                      const cur = _turnSources.get(d.turnId) || []
                      const merged = [...cur]
                      for (const s of d.sources || []) {
                        if (!merged.some((m) => m.url === s.url)) merged.push(s)
                      }
                      _turnSources.set(d.turnId, merged)
                    }
                    // A card with no body is not a card. Both sources of a
                    // bodyless entry are fixed above (live renders now key on
                    // document_id, hydration now carries content), but a store
                    // miss or a truncated row must degrade to "no card" rather
                    // than to an empty glass rectangle with a format badge.
                    return _docs.filter((d) => (d.content || '').trim().length > 0).map((doc) => {
                      const isMarkdown = doc.format === 'markdown'
                      // Carrier = the markdown synthesis card (preferred) or the
                      // first card with sources. Cards that are NOT the carrier
                      // render without the sources block.
                      const carrierId =
                        _docs.find((d) => d.format === 'markdown')?.id ??
                        _docs.find(
                          (d) =>
                            (d.sources && d.sources.length > 0) ||
                            (d.turnId && d.turnId === taskProgress.turnId),
                        )?.id ??
                        null
                      const isSourcesCarrier = doc.id === carrierId
                      // While the turn's crawl is live, prefer the LIVE source
                      // list; once settled, use the turn-merged sources.
                      const docSources: {
                        url: string
                        title: string
                        status?: "planned" | "reading" | "read" | "blocked" | "parked"
                        discovered?: boolean
                        reason?: string
                      }[] | undefined =
                        isSourcesCarrier
                          ? doc.turnId && doc.turnId === taskProgress.turnId &&
                            crawlState.sources.length > 0
                            ? crawlState.sources.map((s) => ({
                                url: s.url,
                                title: s.title || s.host || s.url,
                                status: s.status,
                                discovered: s.discovered,
                                reason: s.reason,
                                // REQ-15: capture provenance so each source row
                                // can pin the Live Reading surface to the
                                // exact bytes the agent read.
                                jobId: s.jobId ?? undefined,
                                capturePage: s.capturePage ?? undefined,
                              }))
                            : isMarkdown
                              ? _turnSources.get(doc.turnId || '') || doc.sources
                              : doc.sources
                          : undefined
                      return (
                    <div key={doc.id} className="my-3 relative">
                      {doc.updated && (
                        <span
                          className="absolute -top-2 right-2 z-10 rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider"
                          style={{
                            color: glowColor,
                            border: `1px solid ${glowColor}55`,
                            background: "rgba(10,11,22,0.75)",
                          }}
                        >
                          Updated
                        </span>
                      )}
                      <RichDocument
                        content={doc.content}
                        // Cast kept in sync with RichDocumentProps.format. It
                        // omitted "json" and "image", which is why a json card
                        // silently fell through to the markdown renderer with
                        // no type error to catch it.
                        format={doc.format as "markdown" | "html" | "table" | "diagram" | "text" | "json" | "image"}
                        glowColor={glowColor}
                        alternatives={doc.alternatives}
                        trust={doc.trust}
                        onFormatChange={(newFormat) =>
                          sendMessage?.('reformat_document', {
                            document_id: doc.documentId,
                            format: newFormat,
                            turn_id: doc.turnId,
                            original_format: doc.format,
                            trust: doc.trust,
                          })
                        }
                        onExpand={() => setExpandedDocId(doc.id)}
                        sources={docSources}
                        harPath={doc.harPath}
                      />
                      {doc.error && (
                        <p className="text-[9px] mt-1" style={{ color: '#ef4444' }}>{doc.error}</p>
                      )}
                    </div>
                      )
                    })
                  })()}

                  {/* Typing Indicator — suppressed while a TaskListCard is
                      ACTIVELY working (it renders its own working-step Xur, so
                      showing this one too doubles the indicator).

                      BUT NOT AFTER THE LAST STEP RESOLVES (2026-08-17). The old
                      condition was `steps.length === 0`, so once a plan existed
                      the indicator stayed suppressed for the REST of the turn —
                      including the synthesis phase that runs after the final
                      step. Measured live: last step finished 12:16:00, answer
                      arrived 12:17:19. For that 79 s the card showed every step
                      done, the orb's radial progress was gone, and nothing
                      anywhere said the agent was still working — it read as
                      finished-but-broken.

                      So: hide it while steps are still running, show it again
                      once they have all resolved and we are waiting on the
                      answer. */}
                  {isDeveloper ? (
                    /* REQ-10 (T4a): branded loading glyph — mounted ONLY
                       between prompt submit and the first streamed block
                       (last timeline item is still the user's message), so at
                       most one instance lives in the stream and it unmounts
                       the moment any content (message, shell output, matrix)
                       arrives. No orphaned rAF loops. */
                    awaitingFirstBlock && (
                      <div className="flex justify-start py-2">
                        <Xur size={32} color={glowColor} speed={1.5} />
                      </div>
                    )
                  ) : isTyping && !taskProgressStillRunning && (
                    <div>
                      <div 
                        className="h-px w-full my-3"
                        style={{ backgroundColor: `${glowColor}10` }}
                      />
                      <div className="flex justify-start">
                        <motion.div
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          className="py-2"
                        >
                          <div className="flex items-center gap-1.5">
                            <Xur size={18} color={glowColor} speed={1.5} />
                            <span className="text-[9px] font-semibold" style={{ color: glowColor }}>
                              IRIS
                            </span>
                            {/* REQ-1 AC3: no-step tasks present a minimal same-card state — nothing extra. */}
                          </div>
                        </motion.div>
                      </div>
                    </div>
                  )}

                  <div ref={messagesEndRef} />

                  {/* Agent task cards now render INLINE via renderTimeline
                      (session 244): matched cards sit after their assistant
                      message (responseTurnId === message.id), unmatched ones
                      fall back to the bottom, and settled conversation-reply
                      cards are suppressed entirely (cards are for artifacts,
                      not conversation). The old bottom-stacked block is
                      superseded — see the `entry.kind === "card"` branch in
                      the render loop above. */}


                  {/* Permission Cards — inline tool approval UI */}
                  <AnimatePresence>
                    {Array.from(pendingPermissions.values()).map((perm) => (
                      <PermissionCard
                        key={perm.requestId}
                        requestId={perm.requestId}
                        toolName={perm.toolName}
                        tier={perm.tier}
                        params={perm.params}
                        description={perm.description}
                        timeoutSeconds={perm.timeoutSeconds}
                        requiresConfirmation={perm.requiresConfirmation}
                        onApprove={(id) => {
                          sendMessage?.('notification_response', {
                            notification_id: id,
                            action: 'grant',
                          })
                        }}
                        onDeny={(id) => {
                          sendMessage?.('notification_response', {
                            notification_id: id,
                            action: 'deny',
                          })
                        }}
                        onConfirm={(id) => {
                          sendMessage?.('notification_response', {
                            notification_id: id,
                            action: 'confirm',
                          })
                        }}
                      />
                    ))}
                  </AnimatePresence>

                  {/* Agent Question Cards */}
                  <AnimatePresence>
                    {Array.from(pendingQuestions.values()).map((q) => (
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
                            // T11-adjacent (REQ-8): forward the card's answer
                            // provenance ("click" | "text") so GUI answers are
                            // distinguishable from terminal answers
                            // (source:'cli') end-to-end. Backend ignores
                            // unknown fields — additive only.
                            source,
                          })
                        }}
                      />
                     ))}
                   </AnimatePresence>
                 </div>
               )}
             </div>

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
                    <div 
                      className="p-2 overflow-y-auto flex-1"
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

            {/* Input Area — single fused input for chat + shell.
                T2 (REQ-1 AC3): TerminalSlideOver / TerminalWidget are removed
                from developer mode ENTIRELY (decision locked 2026-08-21) —
                all shell output streams into the unified scroll above via
                terminalScrollback subscriptions, which are preserved. */}
            <div
              className={isRemoteView ? "px-4 pb-4 pt-4 flex-shrink-0 relative z-30 bg-black/60 border-t" : "px-3 pb-3 pt-4 flex-shrink-0 relative z-30 bg-black/60 border-t"}
              style={{ borderColor: 'rgba(255,255,255,0.05)' }}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              {/* Suggestion pills — float left side above input, fade out on new user message */}
              <div className="absolute left-0 right-0 top-0 -translate-y-full z-30">
                <SuggestionPills
                  suggestions={currentSuggestions}
                  onSelect={(s: Suggestion) => {
                    if (!s.message) return
                    setCurrentSuggestions([])
                    // Add as a user message and send via WS — same flow as handleSendMessage
                    const userMsg = {
                      id: Date.now().toString(),
                      text: s.message,
                      sender: 'user' as const,
                      timestamp: new Date(),
                    }
                    setConversations(prev =>
                      activeConversationId
                        ? prev.map(c => c.id === activeConversationId
                            ? { ...c, messages: [...c.messages, userMsg], lastMessagePreview: s.message.substring(0, 60), timestamp: new Date() }
                            : c)
                        : (() => {
                            const newId = Date.now().toString()
                            activeConversationIdRef.current = newId
                            setActiveConversationId(newId)
                            return [...prev, { id: newId, title: (s.message || 'New conversation').replace(/\s+/g, ' ').trim().slice(0, 60) || 'New conversation', preview: s.message.substring(0, 60), messages: [userMsg], documents: [], timestamp: new Date(), isPinned: false, lastMessagePreview: s.message.substring(0, 60) }]
                          })()
                    )
                    sendMessage?.('text_message', { text: s.message })
                  }}
                  onDismiss={() => setCurrentSuggestions([])}
                  mode={isDeveloper ? 'developer' : 'personal'}
                  glowColor={glowColor}
                  fontColor={fontColor}
                />
              </div>

              {/* Drag overlay with smile/file icon */}
              <AnimatePresence>
                {isDraggingFile && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="absolute bottom-12 left-3 flex items-center gap-1.5 pointer-events-none z-40"
                  >
                    {draggedFileType === 'image' ? (
                      <Image size={14} style={{ color: glowColor }} />
                    ) : draggedFileType === 'video' ? (
                      <Video size={14} style={{ color: glowColor }} />
                    ) : (
                      <Smile size={14} style={{ color: glowColor }} />
                    )}
                    <span className="text-[10px]" style={{ color: fontColor }}>
                      Drop file here
                    </span>
                  </motion.div>
                )}
              </AnimatePresence>

                {/* Mode-split input area (cli-workspace-unification scope fix):
                    DEVELOPER gets the REQ-1/REQ-2 attached two-row footer;
                    PERSONAL keeps the ORIGINAL single-row layout (Web toggle
                    LEFT of the textarea, pill cluster RIGHT of it on the same
                    row, aligned to the textarea glow line). REQ-2's user story
                    is developer-scoped — the restructured footer must not leak
                    into personal mode. */}
                <div className={isDeveloper ? "relative" : (isRemoteView ? "relative flex items-end gap-2 px-1" : "relative flex items-end gap-2")} style={{ marginRight: '4px' }}>

                {/* PERSONAL MODE ONLY — original Web toggle LEFT of the textarea
                    (restored from pre-spec HEAD). Developer mode keeps its Web
                    toggle inside the REQ-2 toolbar row below. */}
                {!isDeveloper && (
                  <div className="flex-shrink-0" style={{ transform: 'translateY(-6.5px)' }}>
                    <motion.button
                      type="button"
                      onClick={() => setWebMode(v => !v)}
                      disabled={voiceState === 'listening'}
                      className="flex items-center justify-center w-[32px] h-[32px] transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                      style={{
                        color: webMode ? glowColor : 'rgba(255,255,255,0.5)',
                        background: 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
                        border: `1px solid ${webMode ? glowColor : `${fontColor}80`}`,
                        borderRadius: '9999px',
                        boxShadow: webMode ? `0 0 12px ${glowColor}40, inset 0 1px 0 rgba(255,255,255,0.03)` : '0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)',
                      }}
                      whileHover={{ scale: 1.08 }}
                      whileTap={{ scale: 0.92 }}
                      title={webMode ? 'Web mode ON — next send researches on the web' : 'Web mode OFF — chat with the agent'}
                      aria-pressed={webMode}
                      aria-label="Toggle web research mode"
                    >
                      <Icon icon={webMode ? 'mdi:web' : 'mdi:web-off'} width={14} height={14} />
                    </motion.button>
                  </div>
                )}

                {/* Row 1 — prompt textarea. DEVELOPER: full-width (the ONE input,
                    REQ-1). PERSONAL: flex-1 between the Web toggle and the pill
                    cluster, per the original layout. */}
                <div className={isDeveloper ? "relative" : "flex-1 relative"}>
                  {/* Session 246 (@-card-mentions): typing a bare '@' opens a
                      picker of this session's task cards; selecting one
                      inserts an @taskcard:<id> token the backend resolves into
                      per-turn context. */}
                  {cardMentionOpen && mentionCandidates.length > 0 && (
                    <div
                      className="absolute bottom-full left-0 right-0 mb-1 z-50 rounded-md overflow-hidden"
                      style={{
                        background: 'linear-gradient(160deg, rgba(14,14,24,0.97), rgba(8,8,16,0.96))',
                        border: `1px solid ${glowColor}35`,
                        boxShadow: '0 -4px 20px rgba(0,0,0,0.6)',
                        maxHeight: 180,
                        overflowY: 'auto',
                      }}
                    >
                      <div className="px-2 py-1 text-[9px] font-mono uppercase tracking-wider text-white/40">
                        Reference a task card
                      </div>
                      {mentionCandidates.map(c => (
                        <button
                          key={c.cardId}
                          className="w-full text-left px-2.5 py-1.5 text-[11px] truncate hover:bg-white/[0.06] transition-colors"
                          style={{ color: 'rgba(255,255,255,0.8)' }}
                          onMouseDown={(e) => {
                            e.preventDefault(); // keep textarea focus
                            setInputText(t => t.replace(/@$/, `@taskcard:${c.cardId} `));
                            setCardMentionOpen(false);
                          }}
                        >
                          <span style={{ color: glowColor }}>@</span>{' '}
                          {c.planTitle || c.cardId}
                          <span className="text-white/35 ml-1.5">
                            {c.isWorking ? '· running' : c.terminalState ? `· ${c.terminalState}` : ''}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                  <textarea
                    ref={inputRef as any}
                    value={inputText}
                    onChange={(e) => {
                      const v = e.target.value;
                      setInputText(v);
                      const opening = /(^|\s)@$/.test(v);
                      if (opening && !cardMentionOpen) openCardMentionPicker();
                      setCardMentionOpen(opening);
                      // Auto-expand height
                      e.target.style.height = 'auto';
                      e.target.style.height = `${e.target.scrollHeight}px`;
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSendMessage();
                        // Reset height
                        if (inputRef.current) inputRef.current.style.height = 'auto';
                      }
                    }}
                    onFocus={() => setIsInputFocused(true)}
                    onBlur={() => setIsInputFocused(false)}
                    placeholder={voiceState === 'listening' ? 'Listening...' : 'Type command or drop file...'}
                    disabled={voiceState === 'listening'}
                    className={isRemoteView ? "w-full bg-transparent border-0 py-3 pr-2 text-[16px] focus:outline-none transition-all placeholder:text-white/30 disabled:opacity-50 resize-none min-h-[44px] max-h-[120px] scrollbar-hide" : "w-full bg-transparent border-0 py-2 pr-2 text-[13px] focus:outline-none transition-all placeholder:text-white/30 disabled:opacity-50 resize-none min-h-[36px] max-h-[120px] scrollbar-hide"}
                    rows={1}
                    style={{
                      borderColor: isDraggingFile ? glowColor : inputText ? glowColor : `${glowColor}30`,
                      color: fontColor,
                      borderBottomWidth: '1px',
                      boxShadow: isDraggingFile ? `0 0 8px ${glowColor}40` : inputText ? `0 1px 0 0 ${glowColor}` : 'none',
                    }}
                  />
                  
                  {/* Voice indicator */}
                  {voiceState === 'listening' && (
                    <motion.div 
                      className="absolute left-0 bottom-0 h-[1px]"
                      style={{ backgroundColor: glowColor }}
                      animate={{ width: [`${audioLevel * 100}%`, `${Math.min(100, audioLevel * 150)}%`] }}
                      transition={{ duration: 0.1 }}
                    />
                  )}
                </div>

                {/* DEVELOPER MODE ONLY — attached horizontal footer toolbar (REQ-2).
                    Exact sequence: [Web 32] →8px→ [Upload 32] →12px→ |1px| →12px→
                    [Model 116] →12px→ |1px| →12px→ [Chips 32] →10px→ [ContextPill 174]
                    = 454px explicit width, centered in the 486px usable width
                    (balanced ≈16px distribution margin). The ⏎ enter icon stays
                    removed (AC4); its width is allocated to ContextPill (174px). */}
                {isDeveloper ? (
                <div className="flex items-center justify-center gap-2.5 mt-2 h-[32px] flex-shrink-0">

                  {/* Web toggle — internet-access capability gate (plan Issue E).
                      OFF by default: agent has no web tools. ON: agent is granted
                      web tools and decides when to use them. Every message still
                      goes to the agent — this only flips the global internet-access
                      flag via the set_web_mode WS message. Exact original glass
                      styling preserved (REQ-2 AC3). */}
                  <motion.button
                    type="button"
                    onClick={() => setWebMode(v => !v)}
                    disabled={voiceState === 'listening'}
                    className="flex items-center justify-center w-[32px] h-[32px] transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                    style={{
                      color: webMode ? glowColor : 'rgba(255,255,255,0.5)',
                      background: 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
                      border: `1px solid ${webMode ? glowColor : `${fontColor}80`}`,
                      borderRadius: '9999px',
                      boxShadow: webMode ? `0 0 12px ${glowColor}40, inset 0 1px 0 rgba(255,255,255,0.03)` : '0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)',
                    }}
                    whileHover={{ scale: 1.08 }}
                    whileTap={{ scale: 0.92 }}
                    title={webMode ? 'Web mode ON — next send researches on the web' : 'Web mode OFF — chat with the agent'}
                    aria-pressed={webMode}
                    aria-label="Toggle web research mode"
                  >
                    <Icon icon={webMode ? 'mdi:web' : 'mdi:web-off'} width={14} height={14} />
                  </motion.button>

                  {/* Send pill removed (Phase 5 REQ-1 AC1) — Enter already sends
                      and the ⏎ icon is permanently removed by cli-workspace-unification
                      REQ-2 AC4; its width is allocated to ContextPill. */}

                  {/* Upload pill — glows on hover. Exact original glass styling (AC3). */}
                  <input
                    ref={fileInputRef}
                    type="file"
                    onChange={handleFileInputChange}
                    className="hidden"
                    accept="*/*"
                  />
                  <motion.button
                    onClick={() => fileInputRef.current?.click()}
                    onMouseEnter={() => setUploadHovered(true)}
                    onMouseLeave={() => setUploadHovered(false)}
                    disabled={voiceState === 'listening'}
                    className="flex items-center justify-center w-[32px] h-[32px] transition-all disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
                    style={{
                      color: uploadHovered ? glowColor : 'rgba(255,255,255,0.7)',
                      background: 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
                      border: `1px solid ${fontColor}80`,
                      borderRadius: '9999px',
                      boxShadow: uploadHovered ? `0 0 12px ${glowColor}30, inset 0 1px 0 rgba(255,255,255,0.03)` : '0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)',
                    }}
                    whileHover={{ scale: 1.08 }}
                    whileTap={{ scale: 0.92 }}
                    title="Upload file"
                  >
                    <Icon icon="material-symbols:arrow-upload-progress" width={18} />
                  </motion.button>

                  {/* Divider 1 */}
                  <div className="flex-shrink-0 rounded-full" style={{ width: '1px', height: '20px', background: glowColor, opacity: 0.3 }} />

                  {/* Model switcher — Phase 5 REQ-2. Sibling of ContextPill
                      (D-2), never a new ContextPill prop (CT-S1). Reads
                      useInferenceState and writes through its existing
                      sendRoleBinding — no new backend surface (D-3). */}
                  <div className="flex-shrink-0">
                    <ModelSwitcher glowColor={glowColor} fontColor={fontColor} />
                  </div>

                  {/* Conversation chips pill — its own fixed 32x32 icon
                      button, sits BETWEEN the ModelSwitcher and ContextPill
                      per the REQ-2 sequence. Opens its popover drawer to the
                      LEFT of ContextPill (REQ-2 AC5). */}
                  <div
                    className="flex items-center justify-center w-[32px] h-[32px] flex-shrink-0"
                    style={{
                      background: 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
                      border: `1px solid ${fontColor}80`,
                      borderRadius: '6px',
                      boxShadow: '0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)',
                    }}
                  >
                    <ConversationChips
                      chips={conversationChips}
                      glowColor={glowColor}
                      onChipClick={handleChipClick}
                      containerRef={messagesContainerRef}
                    />
                  </div>

                  {/* ContextPill — declares its own dark-glass panel; the ⏎
                      enter icon's freed width gives it the full 174px REQ-2
                      allocation. Rendered LAST in the sequence (far right).
                      Internal order is phase label then token numbers
                      (e.g. "IDLE  0 / 128.0k"). */}
                  {/* ContextPill takes the row's slack. Its own ml-[10px] is
                      dropped so the container's gap spaces it like every other
                      child, and min-w-0 lets it shrink before anything else
                      does — REQ-3's rule that the pill keeps its information
                      longest applies to the SWITCHER collapsing first, not to
                      the pill overflowing the row. */}
                  <div className="flex-shrink min-w-0">
                    <ContextPill
                      usedTokens={contextUsage.used}
                      maxTokens={contextUsage.max}
                      phase={voiceState}
                      currentAction={taskProgress.currentAction}
                    />
                  </div>
                </div>
                ) : (
                <>
                  {/* PERSONAL MODE — original single-row pill cluster, restored
                      from pre-spec HEAD. Pills sit RIGHT of the textarea on the
                      SAME row; bottom border matches the textarea glow line.
                      The send/⏎ pill was already removed in Phase 5 (pre-spec),
                      so its absence here is original behavior, not REQ-2 AC4. */}
                  <input
                    ref={fileInputRef}
                    type="file"
                    onChange={handleFileInputChange}
                    className="hidden"
                    accept="*/*"
                  />
                  <div
                    className="flex items-center gap-2 flex-shrink-0"
                    style={{
                      borderBottom: `1px solid ${inputText ? glowColor : `${glowColor}30`}`,
                      transform: 'translateY(-6.5px)',
                    }}
                  >
                    <motion.button
                      onClick={() => fileInputRef.current?.click()}
                      onMouseEnter={() => setUploadHovered(true)}
                      onMouseLeave={() => setUploadHovered(false)}
                      disabled={voiceState === 'listening'}
                      className="flex items-center justify-center w-[32px] h-[32px] transition-all disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
                      style={{
                        color: uploadHovered ? glowColor : 'rgba(255,255,255,0.7)',
                        background: 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
                        border: `1px solid ${fontColor}80`,
                        borderRadius: '9999px',
                        boxShadow: uploadHovered ? `0 0 12px ${glowColor}30, inset 0 1px 0 rgba(255,255,255,0.03)` : '0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)',
                      }}
                      whileHover={{ scale: 1.08 }}
                      whileTap={{ scale: 0.92 }}
                      title="Upload file"
                    >
                      <Icon icon="material-symbols:arrow-upload-progress" width={18} />
                    </motion.button>

                    {/* Divider */}
                    <div className="flex-shrink-0 rounded-full" style={{ width: '1px', height: '20px', background: glowColor, opacity: 0.3 }} />

                    <ModelSwitcher glowColor={glowColor} fontColor={fontColor} />

                    <div
                      className="flex items-center justify-center w-[32px] h-[32px] flex-shrink-0 ml-1.5"
                      style={{
                        background: 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
                        border: `1px solid ${fontColor}80`,
                        borderRadius: '6px',
                        boxShadow: '0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)',
                      }}
                    >
                      <ConversationChips
                        chips={conversationChips}
                        glowColor={glowColor}
                        onChipClick={handleChipClick}
                        containerRef={messagesContainerRef}
                      />
                    </div>

                    <ContextPill
                      usedTokens={contextUsage.used}
                      maxTokens={contextUsage.max}
                      phase={voiceState}
                      currentAction={taskProgress.currentAction}
                    />
                  </div>
                </>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// Note: Component renamed to ChatWing but file kept as chat-view.tsx to avoid breaking imports
export default ChatWing