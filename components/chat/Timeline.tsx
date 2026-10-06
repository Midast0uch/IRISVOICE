"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Xur } from "@/components/Xur"
import { RichDocument } from "@/components/chat/RichDocument"
import { PermissionCard } from "@/components/chat/PermissionCard"
import { TurnView } from "@/components/chat/TurnView"
import { TaskCardEntry } from "@/components/chat/TaskCardEntry"
import { ShellRunEntry } from "@/components/chat/matrix/ShellRunEntry"
import type { ChatTimelineEntry } from "@/lib/chatview-turn-timeline"
import type { TurnRecord } from "@/lib/turns/turnStore"
import type { TaskProgress } from "@/hooks/useTaskProgress"
import type { SendMessageFunction } from "@/hooks/useIRISWebSocket"
import type { CrawlState } from "@/hooks/useCrawl"
import type { Message, Conversation, ContentType } from "@/components/chat-view"

// REQ-6 AC3/AC4 (T7): how far from the bottom still counts as "pinned".
// Absorbs sub-pixel rounding between scrollHeight and clientHeight so a user
// resting at the bottom is never mistaken for a user who scrolled up.
const PINNED_THRESHOLD_PX = 48;

export interface TimelineProps {
  renderTimeline: ChatTimelineEntry<Message>[]
  messages: Message[]
  messagesContainerRef: React.RefObject<HTMLDivElement | null>
  messagesEndRef: React.RefObject<HTMLDivElement | null>
  pinnedToBottomRef: React.MutableRefObject<boolean>
  setShowJumpToLatest: React.Dispatch<React.SetStateAction<boolean>>
  isTyping: boolean
  taskProgressStillRunning: boolean
  awaitingFirstBlock: boolean
  matrixElapsedSec: number
  pendingPermissions: Map<string, { requestId: string; toolName: string; tier: "read_only" | "side_effect" | "destructive"; params?: Record<string, unknown>; description?: string; timeoutSeconds: number; requiresConfirmation: boolean }>
  removePendingPermission: (id: string) => void
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
}

export function Timeline({
  renderTimeline,
  messages,
  messagesContainerRef,
  messagesEndRef,
  pinnedToBottomRef,
  setShowJumpToLatest,
  isTyping,
  taskProgressStillRunning,
  awaitingFirstBlock,
  matrixElapsedSec,
  pendingPermissions,
  removePendingPermission,
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
}: TimelineProps) {
  return (
    <div
      ref={messagesContainerRef}
      className="flex-1 overflow-y-auto px-3 py-3 relative z-10"
      // REQ-6 AC3/AC4 (T7): re-evaluate "pinned to bottom" on every
      // user scroll. The threshold absorbs sub-pixel rounding and the
      // drift of a rounding-error scrollHeight, so a user resting at
      // the bottom is never treated as scrolled up.
      onScroll={(e) => {
        const el = e.currentTarget
        const distance = el.scrollHeight - el.scrollTop - el.clientHeight
        const atBottom = distance <= PINNED_THRESHOLD_PX
        pinnedToBottomRef.current = atBottom
        // Identical values are bailed out by React, so this does not
        // re-render on every wheel tick.
        setShowJumpToLatest(!atBottom)
      }}
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
      {(messages.length === 0 && renderTimeline.length === 0) && !isTyping ? (
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
            // Gate 3 T9: shell lines render in the terminal panel
            // only (D5) — the chat stream carries messages + cards.
            // Session 244: task cards render INLINE — after the
            // assistant message they belong to (responseTurnId join),
            // or at the bottom for unmatched/legacy cards. Dev mode
            // renders the Blueprint Matrix; personal the GUI card.
            // Phase 4: a developer `>cmd` renders as its prompt line + an EXEC row.
            if (entry.kind === "shell") {
              return <ShellRunEntry key={entry.run.id} run={entry.run} glowColor={glowColor} now={Date.now()} />
            }
            if (entry.kind === "card") {
              const card = entry.card
              return (
                <TaskCardEntry
                  key={isDeveloper ? `card-${card.cardId}` : card.cardId}
                  card={card}
                  isDeveloper={isDeveloper}
                  glowColor={glowColor}
                  matrixElapsedSec={matrixElapsedSec}
                />
              )
            }
            const message = entry.message
            const index = entry.index
            return (
              <TurnView
                key={message.id}
                message={message}
                index={index}
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
            );
          })}

          {/* Orphan fallback — hydration safety net. If a document's
              turnId has no matching message (store miss, old data,
              or a render that arrived before its message), it would
              otherwise vanish after the inline move. This keeps the
              previous bottom-stacked behaviour ONLY for orphans, so a
              reload never loses a card. Inline-matched docs are
              already rendered above and are excluded here. */}
          {(() => {
            const _all = activeConversation?.documents || []
            if (_all.length === 0) return null
            // Orphan = no message in this timeline owns its turn.
            // A turn can be owned via message.id (live anchor) OR
            // message.turn_id (rehydrated row) — both count, or an
            // inline-matched card would ALSO render here as a
            // duplicate.
            const _msgIds = new Set(renderTimeline.filter((e) => e.kind === 'message').flatMap((e) => {
              const m = (e as Extract<(typeof renderTimeline)[number], { kind: 'message' }>).message
              return m.turn_id ? [m.id, m.turn_id] : [m.id]
            }))
            const _orphans = _all.filter((d) => (((d.content || '').trim().length > 0) || !!d.documentId) && d.turnId && !_msgIds.has(d.turnId))
            if (_orphans.length === 0) return null
            return _orphans.map((doc) => (
              <div key={`orphan-${doc.id}`} className="my-3 relative">
                <RichDocument
                  content={doc.content}
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
                  expandable={
                    (doc.content || '').trim().length === 0 &&
                    !!doc.documentId
                  }
                  sources={doc.sources}
                  harPath={doc.harPath}
                />
              </div>
            ))
          })()}

          {/* Rich documents now render INLINE with their parent
              message (see the injection above, inside the
              renderTimeline.map). The previous bottom-stacked block
              made every document card float below the conversation
              and broke scroll order — measured live 2026-08-27: two
              MD cards piled at the bottom of the thread while the
              short assistant text repeated at the top. Joining on
              doc.turnId === message.id restores conversation order
              and matches the pattern the task cards already use. */}


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
                  // Session-331: remove the card OPTIMISTICALLY. The
                  // card only disappeared when the backend's
                  // permission:granted broadcast arrived — and that
                  // broadcast is routed by session/conversation, so a
                  // missing or mis-routed frame left the card rendered
                  // forever after the user clicked Allow (live report:
                  // permission cards never disappear after answering,
                  // unlike AskUserQuestion cards). Removing it here
                  // makes the click always land; a duplicate
                  // permission_granted event is a harmless no-op.
                  removePendingPermission(id)
                }}
                onDeny={(id) => {
                  sendMessage?.('notification_response', {
                    notification_id: id,
                    action: 'deny',
                  })
                  removePendingPermission(id)
                }}
                onConfirm={(id) => {
                  sendMessage?.('notification_response', {
                    notification_id: id,
                    action: 'confirm',
                  })
                  removePendingPermission(id)
                }}
              />
            ))}
          </AnimatePresence>

          {/* Agent Question Cards — UNANCHORED fallback only (T21).
              A question whose asking turn already has a message renders
              INLINE at that turn (see the doc-join join above); this
              block covers the live pre-answer window (REQ-11 AC3) and
              hides nothing the thread has already anchored. */}
          <AnimatePresence>
            {Array.from(pendingQuestions.values())
              .filter((q) => !anchoredQuestionIds.has(q.questionId))
              .map((q) => questionCardFor(q))}
           </AnimatePresence>
          </div>
       )}
     </div>
  )
}
