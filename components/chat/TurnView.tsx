"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Xur } from "@/components/Xur"
import { Copy, ThumbsUp, ThumbsDown, Volume2, ChevronDown, ChevronUp, Download, Share, ExternalLink, RefreshCw, Pencil, AlertCircle, Info } from 'lucide-react'
import { RichDocument } from "@/components/chat/RichDocument"
import { MarkdownMessage } from "@/components/chat/MarkdownMessage"
import { TurnParts } from "@/components/chat/turn/TurnParts"
import { ArtifactChip } from "@/components/chat/lens/ArtifactChip"
import { DiffSummaryChip } from "@/components/chat/diff/DiffMark"
import { AskPrompt, type AskActions } from "@/components/chat/turn/AskPrompt"
import type { AskItem } from "@/lib/turns/asks"
import { partsOf } from "@/lib/turns/turnStore"
import { diffsOf, type EditDiff, type ToolResultDiffData } from "@/lib/diffs/api"
import type { TurnRecord } from "@/lib/turns/turnStore"
import type { TaskProgress } from "@/hooks/useTaskProgress"
import type { SendMessageFunction } from "@/hooks/useIRISWebSocket"
import type { CrawlState } from "@/hooks/useCrawl"
import type { Message, Conversation, ContentType } from "@/components/chat-view"

const MESSAGE_THRESHOLDS = {
  TRUNCATE_AT: 500,            // plain text expand/collapse threshold
  DOCUMENT_MODE_AT: 400,       // artifact card threshold for media/email/file uploads
  // MARKDOWN_ARTIFACT_AT removed 2026-08-17 — length is not what makes something a
  // document. See the isDocumentMode comment below: a document is what the agent
  // stored via a `show` payload and arrives as DOCUMENT_RENDER.
  WARNING_AT: 3000
} as const;

export interface TurnViewProps {
  message: Message
  index: number
  isDeveloper: boolean
  glowColor: string
  fontColor: string
  prefersReducedMotion: boolean
  sendMessage?: SendMessageFunction
  onOpenBrowserUrl?: (url: string) => void
  conversations: Conversation[]
  activeConversation: Conversation | undefined
  activeConversationId: string | null
  anchoredQuestionIds: Set<string>
  pendingQuestions: Map<string, { questionId: string; text: string; options?: string[]; allowOther?: boolean; timeoutSeconds?: number; turnId?: string }>
  questionCardFor: (q: { questionId: string; text: string; options?: string[]; allowOther?: boolean; timeoutSeconds?: number; turnId?: string }) => React.JSX.Element
  liveTurnById: Map<string, TurnRecord>
  taskProgress: TaskProgress
  crawlState: CrawlState
  copiedMessageId: string | null
  currentTtsMessageId: string | null
  ttsWordIndex: number
  isSpeaking: boolean
  editingMessageId: string | null
  setEditingMessageId: React.Dispatch<React.SetStateAction<string | null>>
  editingText: string
  setEditingText: React.Dispatch<React.SetStateAction<string>>
  retryingMessageId: string | null
  expandedThinking: Set<string>
  setExpandedThinking: React.Dispatch<React.SetStateAction<Set<string>>>
  setDocumentModalMessage: React.Dispatch<React.SetStateAction<Message | null>>
  setExpandedDocId: React.Dispatch<React.SetStateAction<string | null>>
  getContentType: (message: Message) => ContentType
  isMessageExpanded: (messageId: string) => boolean
  toggleMessageExpanded: (messageId: string) => void
  handleCopyMessage: (text: string, messageId: string) => Promise<void>
  handleFeedback: (messageId: string, feedback: 'positive' | 'negative') => void
  handlePlayTTSClick: (text: string) => void
  handleShareMessage: (message: Message) => Promise<void>
  handleDownloadMessage: (message: Message) => void
  handleResendUserMessage: (messageIndex: number, convId: string, revisedText?: string) => void
  handleRetryPrompt: (errorMessageIndex: number, convId: string) => void
  renderWithLinks: (text: string) => React.ReactNode
  requestDocumentBody: (documentId: string) => void
  /** IRIS asks of this turn that have no task card to sit in: drawn here, in the turn. */
  turnAsks?: AskItem[]
  askActions?: AskActions
  /** A task card (matrix / personal card) is on screen for this turn: it carries the live reasoning line. */
  hasCard?: boolean
}

export function TurnView({
  message,
  index,
  isDeveloper,
  glowColor,
  fontColor,
  prefersReducedMotion,
  sendMessage,
  onOpenBrowserUrl,
  conversations,
  activeConversation,
  activeConversationId,
  anchoredQuestionIds,
  pendingQuestions,
  questionCardFor,
  liveTurnById,
  taskProgress,
  crawlState,
  copiedMessageId,
  currentTtsMessageId,
  ttsWordIndex,
  isSpeaking,
  editingMessageId,
  setEditingMessageId,
  editingText,
  setEditingText,
  retryingMessageId,
  expandedThinking,
  setExpandedThinking,
  setDocumentModalMessage,
  setExpandedDocId,
  getContentType,
  isMessageExpanded,
  toggleMessageExpanded,
  handleCopyMessage,
  handleFeedback,
  handlePlayTTSClick,
  handleShareMessage,
  handleDownloadMessage,
  handleResendUserMessage,
  handleRetryPrompt,
  renderWithLinks,
  requestDocumentBody,
  turnAsks,
  askActions,
  hasCard,
}: TurnViewProps) {
  // Smart message length handling
  const charCount = message.text.length;
  const contentType = getContentType(message);
  const isExpanded = isMessageExpanded(message.id);
  // Phase 3: the turn this message belongs to (live session only).
  const liveTurn = liveTurnById.get(message.id) ?? (message.turn_id ? liveTurnById.get(message.turn_id) : undefined);
  // Audit bug: a reply froze at 6 lines and remounted while it
  // streamed. A running turn is never clamped.
  const isStreaming = liveTurn?.status === "running";
  const shouldTruncate = !isStreaming && charCount > MESSAGE_THRESHOLDS.TRUNCATE_AT;
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

  // Per-bubble content-type icon+label REMOVED 2026-09-21
  // (reply-surface-contract T14 / REQ-5): the badge was chrome
  // the owner does not want. `getContentType` stays — it still
  // drives isDocumentMode and other routing.
                    
  // T15 (reply-surface-contract REQ-3 AC3): suppress the
  // supportive bubble when the agent's line literally repeats
  // the card's opening — the card then already carries it.
  // Guards: only when a turn-joined doc EXISTS and its body
  // starts with the bubble text, and never when they are
  // equal (equality means the emit failed and the bubble is
  // the only copy — see backend seam emit-failure fallback).
  const _bubbleText = (message.text || '').trim()
  const bubbleDuplicatesCard =
    message.sender === 'assistant' &&
    _bubbleText.length > 0 &&
    (activeConversation?.documents || []).some(
      (d) =>
        d.turnId &&
        (d.turnId === message.id || d.turnId === message.turn_id) &&
        (d.content || '').trim().length > _bubbleText.length &&
        (d.content || '').trim().startsWith(_bubbleText),
    )

  return (
  <div key={message.id} id={`msg-${message.id}`}>
    {/* Horizontal separator */}
    {index > 0 && (
      <div
        className="h-px w-full my-3"
        style={{ backgroundColor: `${glowColor}10` }}
      />
    )}

    {/* Inline RichDocument cards for this turn. T15
        (reply-surface-contract REQ-3 AC3): cards render ABOVE
        the supportive bubble so the artifact leads and the
        conversational line follows. Joined on
        doc.turnId === message.id (same key the message itself
        carries — see handleTextResponse chat-view.tsx:1033).
        Sources-carrier logic is identical to the previous
        bottom-stacked block; only the placement changed.
        A websearch turn emits multiple `show` payloads (one
        per crawler_query step as a JSON card, then the final
        markdown synthesis), and only the markdown card carries
        the merged sources for the turn — same-turn siblings
        contribute to that carrier's source list. Bodyless
        entries (a store miss or a truncated row) degrade to
        "no card" rather than an empty glass rectangle. */}
    {(() => {
      const _allDocs = activeConversation?.documents || []
      if (message.sender !== 'assistant') return null
      // Join on turn: live messages carry id === turn_id
      // (anchor rule in handleTextResponse), rehydrated
      // ones carry the DB row id and expose the turn via
      // message.turn_id. Matching BOTH keeps a prism card
      // attached to its turn after a history reload —
      // without this the card fell to the orphan pile the
      // moment openHistory() replaced the messages
      // (session 296: "cards vanish when I switch threads").
      const _myTurnDocs = _allDocs.filter(
        (d) =>
          d.turnId &&
          (d.turnId === message.id || d.turnId === message.turn_id) &&
          // REQ-17 T28: a rehydrated card may have NO in-memory
          // body (metadata-only hydration) but its document_id
          // is resolvable — admit it so the card renders and the
          // body fetches on expand. Truly empty docs still drop.
          ((d.content || '').trim().length > 0 || !!d.documentId),
      )
      if (_myTurnDocs.length === 0) return null
      // (Phase 3: the frontend copy of the failed-search rule,
      // _isEmptyResultDoc, is gone. Whether a reply is a card is
      // decided once, by the agent's create_artifact call —
      // reply-surface Phase A removed the backend copy.)
      // Build the per-turn source map once (markdown carrier
      // merges sources from same-turn siblings).
      const _turnSources = new Map<string, { url: string; title: string }[]>()
      for (const d of _allDocs) {
        if (!d.turnId) continue
        const cur = _turnSources.get(d.turnId) || []
        const merged = [...cur]
        for (const s of d.sources || []) {
          if (!merged.some((m) => m.url === s.url)) merged.push(s)
        }
        _turnSources.set(d.turnId, merged)
      }
      const carrierId =
        _myTurnDocs.find((d) => d.format === 'markdown')?.id ??
        _myTurnDocs.find(
          (d) =>
            (d.sources && d.sources.length > 0) ||
            (d.turnId && d.turnId === taskProgress.turnId),
        )?.id ??
        null
      return _myTurnDocs.map((doc) => {
        const isMarkdown = doc.format === 'markdown'
        const isSourcesCarrier = doc.id === carrierId
        const docSources: {
          url: string
          title: string
          status?: "planned" | "reading" | "read" | "blocked" | "parked"
          discovered?: boolean
          reason?: string
          jobId?: string
          capturePage?: number
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
                  jobId: s.jobId ?? undefined,
                  capturePage: s.capturePage ?? undefined,
                }))
              : isMarkdown
                ? _turnSources.get(doc.turnId || '') || doc.sources
                : doc.sources
            : undefined
        // A finished artifact is a compact titled card that opens the lens. A streaming one
        // (partial) and the live sources list of a running research stay inline, as before.
        const liveSources =
          isSourcesCarrier && !!doc.turnId && doc.turnId === taskProgress.turnId && crawlState.sources.length > 0
        if (!doc.partial && !liveSources) {
          return (
            <div key={`doc-${doc.id}`} className="my-3 relative">
              <ArtifactChip doc={doc} note={doc.updated ? "updated" : undefined} />
              {doc.error && (
                <p className="text-[9px] mt-1" style={{ color: '#ef4444' }}>{doc.error}</p>
              )}
            </div>
          )
        }
        return (
          <div key={`doc-${doc.id}`} className="my-3 relative">
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
              format={doc.format as "markdown" | "html" | "table" | "diagram" | "text" | "json" | "image"}
              title={doc.title}
              glowColor={glowColor}
              alternatives={doc.alternatives}
              trust={doc.trust}
              partial={doc.partial}
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
              expandable={
                (doc.content || '').trim().length === 0 &&
                !!doc.documentId
              }
              // Peek on a bodyless rehydrated card triggers
              // the same lazy body fetch the panel does (F11).
              onPeek={
                doc.documentId
                  ? () => requestDocumentBody(doc.documentId!)
                  : undefined
              }
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

    {/* T21 (reply-surface-contract REQ-11 AC1/AC3): question
        cards asked in THIS turn anchor here — in the thread,
        at their turn, not pinned at the bottom block. */}
    {message.sender === 'assistant' &&
      Array.from(pendingQuestions.values())
        .filter(
          (q) =>
            q.turnId &&
            anchoredQuestionIds.has(q.questionId) &&
            (q.turnId === message.id || q.turnId === message.turn_id)
        )
        .map((q) => questionCardFor(q))}

    <div
      className={`flex ${isDeveloper && message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
    >
      {message.sender === 'user' ? (
        // User message: no container in personal mode; in developer mode the
        // prompt is the concept's right-aligned `.you` bubble (iris-strands.html).
        <motion.div
          initial={{ opacity: prefersReducedMotion ? 1 : 0, y: prefersReducedMotion ? 0 : 5 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: prefersReducedMotion ? 0 : 0.15 }}
          className={isDeveloper ? "max-w-[88%] py-1 flex flex-col items-end" : "max-w-[90%] py-2"}
        >
          {/* Phase 4: developer mode shows the prompt line alone (below);
              the "You" header is personal mode's. */}
          {!isDeveloper && (
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[9px] font-medium text-white/40">You</span>
            <span className="text-[8px] text-white/30 tabular-nums">
              {message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
            </span>
          </div>
          )}
                            
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
            // Truncated message with expand option. The
            // content-type badge (icon + label) was removed
            // 2026-09-21 (reply-surface-contract REQ-5 /
            // T14): type is conveyed by the rendering itself,
            // not by chrome.
            <div className="mt-1">
              <div className="relative">
                {isDeveloper ? (
                  <pre className="font-mono text-[11px] leading-[1.5] whitespace-pre-wrap break-words" style={{ color: 'rgba(255,255,255,0.88)' }}>
                    <span style={{ color: glowColor }}>❯ </span>
                    {isExpanded ? message.text : message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT) + '...'}
                  </pre>
                ) : (
                  <p className="text-[13px] leading-relaxed text-white/90">
                    {isExpanded ? message.text : message.text.slice(0, MESSAGE_THRESHOLDS.TRUNCATE_AT) + '...'}
                  </p>
                )}
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
          ) : isDeveloper ? (
            /* Developer mode: YOUR turn in the mono family, as typed
               (renderWithLinks dropped on purpose), in the concept's
               right-aligned bubble; the time is on hover. A `>cmd` keeps
               its `❯` prompt line (ShellRunEntry). */
            <div
              className="min-w-0 font-mono text-[13px] whitespace-pre-wrap break-words"
              style={{
                color: '#e6e9f2',
                lineHeight: 1.5,
                background: '#0e1122',
                border: '1px solid rgba(160,190,255,0.09)',
                borderRadius: '12px 12px 3px 12px',
                padding: '8px 12px',
              }}
              title={message.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
              data-prompt-line
            >
              {message.text}
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
          {/* Developer mode (owner 2026-10-06, concept 2 devTurn): the answer
              sits under its matrix with no "IRIS" header and no action bar. */}
          {!isDeveloper && (
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
          )}
                            
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

          {/* Message content with smart length handling and TTS highlighting.
              T15 (REQ-3 AC3): suppressed when it duplicates the card opening —
              the card above already carries those words. */}
          {!bubbleDuplicatesCard && (isDocumentMode ? (
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
                  variant={isDeveloper ? 'cli' : 'voice'}
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
              variant={isDeveloper ? 'cli' : 'voice'}
            />
          ))}

          {/* Phase 3: reasoning line, notices and errors of this turn —
              events that had no listener before. */}
          {liveTurn && (
            <TurnParts
              turn={liveTurn}
              isDeveloper={isDeveloper}
              glowColor={glowColor}
              hasCard={hasCard}
              onRetry={
                liveTurn.status === "error" && activeConversationId
                  ? () => {
                      const conv = conversations.find((c) => c.id === activeConversationId)
                      const idx = conv
                        ? conv.messages.findIndex((m) => m.id === liveTurn.clientRef)
                        : -1
                      if (idx >= 0) handleResendUserMessage(idx, activeConversationId)
                    }
                  : undefined
              }
            />
          )}

          {/* In-turn interactions: the edits of this turn (± opens the review in the lens)
              and IRIS asks that have no task card to sit in. */}
          {liveTurn && (() => {
            const seen = new Set<string>()
            const turnDiffs: EditDiff[] = []
            for (const r of partsOf(liveTurn, "tool_result")) {
              for (const d of diffsOf(r.data as ToolResultDiffData)) {
                if (!seen.has(d.diff_id)) { seen.add(d.diff_id); turnDiffs.push(d) }
              }
            }
            return turnDiffs.length > 0 ? <div className="mt-2 flex"><DiffSummaryChip diffs={turnDiffs} /></div> : null
          })()}
          {askActions && turnAsks && turnAsks.length > 0 && (
            <div className="mt-2 flex flex-col gap-1.5" data-turn-asks>
              {turnAsks.map((a) => (
                <AskPrompt key={a.id} ask={a} variant={isDeveloper ? "row" : "card"} glowColor={glowColor} actions={askActions} />
              ))}
            </div>
          )}

          {/* Feedback action bar (personal mode only; see the header note above) */}
          {!isDeveloper && (
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
          )}
        </motion.div>
      ) : message.sender === 'system' && message.id.startsWith('steer-note-') ? (
        // A steer sent while a turn runs: one line, "↳ you steered: … · noted".
        <div className="iris-steer py-1" data-testid="steer-note">{message.text}</div>
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
    {/* Prism cards for this turn now render ABOVE the bubble
        (T15, reply-surface-contract REQ-3 AC3): the card is the
        artifact, the bubble that follows is the supportive
        speak line. The doc-join block itself lives directly
        after the separator at the top of this message row. */}
  </div>
);
}
