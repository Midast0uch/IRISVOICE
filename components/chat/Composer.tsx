"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Video, Image, Smile } from 'lucide-react'
import { Icon } from '@iconify/react'
import { SuggestionPills } from "@/components/chat/SuggestionPills"
import ContextPill from "@/components/chat/ContextPill"
import ModelSwitcher from "@/components/ModelSwitcher"
import { ProjectBar } from "@/components/chat/composer/ProjectBar"
import {
  RefTray,
  RefPicker,
  useRefCandidates,
  hashQueryOf,
  withoutHashQuery,
  matchRefs,
  type ComposerRef,
  type RefDoc,
} from "@/components/chat/composer/refs"
import { useBrandPalette } from "@/hooks/useBrandPalette"
import { recallHistory, appendSystem } from "@/components/terminal/terminalScrollback"
import type { TerminalSnapshot } from "@/components/terminal/terminalScrollback"
import type { TaskProgress, TaskCard } from "@/hooks/useTaskProgress"
import type { SendMessageFunction } from "@/hooks/useIRISWebSocket"
import type { Suggestion } from "@/types/iris"

export interface ComposerProps {
  isRemoteView?: boolean
  isDeveloper: boolean
  glowColor: string
  fontColor: string
  voiceState: "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error"
  audioLevel: number
  sendMessage?: SendMessageFunction
  // Drag and drop / file input
  handleDragOver: (e: React.DragEvent) => void
  handleDragLeave: (e: React.DragEvent) => void
  handleDrop: (e: React.DragEvent) => void
  isDraggingFile: boolean
  draggedFileType: 'image' | 'video' | 'file' | null
  fileInputRef: React.RefObject<HTMLInputElement | null>
  handleFileInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  // Suggestions
  currentSuggestions: Suggestion[]
  setCurrentSuggestions: React.Dispatch<React.SetStateAction<Suggestion[]>>
  // Send path
  handleSendMessage: (overrideText?: string) => Promise<void>
  // Input text / focus
  inputText: string
  setInputText: React.Dispatch<React.SetStateAction<string>>
  inputRef: React.RefObject<HTMLInputElement | null>
  setIsInputFocused: React.Dispatch<React.SetStateAction<boolean>>
  // Jump to latest
  showJumpToLatest: boolean
  jumpToLatest: () => void
  // Web mode
  webMode: boolean
  setWebMode: React.Dispatch<React.SetStateAction<boolean>>
  // @-card mention menu
  cardMentionOpen: boolean
  setCardMentionOpen: React.Dispatch<React.SetStateAction<boolean>>
  mentionCandidates: TaskCard[]
  openCardMentionPicker: () => void
  // Slash-command menu
  slashMenuOpen: boolean
  setSlashMenuOpen: React.Dispatch<React.SetStateAction<boolean>>
  slashMatches: Array<{ name: string; display_name: string; when_to_use: string; available: boolean }>
  acceptSlash: (command: string) => void
  // Shell / workspace
  terminalSnapshot: TerminalSnapshot
  activeTabPath: string | null
  // Footer toolbar
  contextUsage: { used: number; max: number }
  taskProgress: TaskProgress
  // Composer design 2026-10-06: steer/stop, # references.
  /** The conversation on screen; # candidates and the stop message name it. */
  conversationId: string | null
  /** A turn is running in this conversation: Enter steers, the button stops. */
  isRunning: boolean
  /** Picked # references (addresses). chat-view puts them in the send payload. */
  composerRefs: ComposerRef[]
  setComposerRefs: React.Dispatch<React.SetStateAction<ComposerRef[]>>
  /** Documents and artifacts shown in this conversation. */
  refDocs: RefDoc[]
}

export function Composer({
  isRemoteView,
  isDeveloper,
  glowColor,
  fontColor,
  voiceState,
  audioLevel,
  sendMessage,
  handleDragOver,
  handleDragLeave,
  handleDrop,
  isDraggingFile,
  draggedFileType,
  fileInputRef,
  handleFileInputChange,
  currentSuggestions,
  setCurrentSuggestions,
  handleSendMessage,
  inputText,
  setInputText,
  inputRef,
  setIsInputFocused,
  showJumpToLatest,
  jumpToLatest,
  webMode,
  setWebMode,
  cardMentionOpen,
  setCardMentionOpen,
  mentionCandidates,
  openCardMentionPicker,
  slashMenuOpen,
  setSlashMenuOpen,
  slashMatches,
  acceptSlash,
  terminalSnapshot,
  activeTabPath,
  contextUsage,
  taskProgress,
  conversationId,
  isRunning,
  composerRefs,
  setComposerRefs,
  refDocs,
}: ComposerProps) {
  // Hover state for the upload pill — only the composer reads it.
  const [uploadHovered, setUploadHovered] = React.useState(false)

  // ── # references: a picker of ADDRESSES (never content) ──────────────────
  const [b1, b2] = useBrandPalette()
  const hashQuery = hashQueryOf(inputText)
  const [hashDismissedFor, setHashDismissedFor] = React.useState<string | null>(null)
  const pickerWanted = hashQuery !== null && hashDismissedFor !== inputText
  const refCandidates = useRefCandidates({
    conversationId,
    cards: mentionCandidates,
    docs: refDocs,
    wanted: pickerWanted,
  })
  const refMatches = pickerWanted ? matchRefs(refCandidates, composerRefs, hashQuery ?? '') : []
  const [refSel, setRefSel] = React.useState(0)
  const refSelIdx = Math.min(refSel, Math.max(0, refMatches.length - 1))
  const pickRef = (r: ComposerRef) => {
    setComposerRefs(prev => (prev.some(p => p.address === r.address) ? prev : [...prev, r]))
    setInputText(t => withoutHashQuery(t))
    setRefSel(0)
    inputRef.current?.focus()
  }

  // ── One send/stop button. A turn runs here: it stops it. ────────────────
  const stopTurn = () => {
    sendMessage?.('stop', { conversation_id: conversationId, message_id: `stop-${Date.now()}` })
  }
  const sendStopButton = (compact: boolean) => (
    <motion.button
      type="button"
      onClick={() => { if (isRunning) stopTurn(); else void handleSendMessage() }}
      disabled={!isRunning && (!inputText.trim() || voiceState === 'listening')}
      className={`flex items-center justify-center ${compact ? 'w-[28px] h-[28px]' : 'w-[32px] h-[32px]'} transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0 font-mono text-[14px] leading-none`}
      style={{
        color: isRunning ? '#ff7a6e' : inputText.trim() ? glowColor : 'rgba(255,255,255,0.5)',
        background: 'linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)',
        border: `1px solid ${isRunning ? 'rgba(255,122,110,0.5)' : inputText.trim() ? glowColor : `${fontColor}80`}`,
        borderRadius: '9999px',
        boxShadow: inputText.trim() && !isRunning
          ? `0 0 12px ${glowColor}40, inset 0 1px 0 rgba(255,255,255,0.03)`
          : '0 1px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)',
      }}
      whileHover={{ scale: 1.08 }}
      whileTap={{ scale: 0.92 }}
      title={isRunning ? 'Stop IRIS' : 'Send message'}
      aria-label={isRunning ? 'Stop IRIS' : 'Send message'}
      data-testid={isRunning ? 'stop-turn' : 'send-message'}
    >
      {isRunning ? '■' : '↵'}
    </motion.button>
  )

    /* Input Area — single fused input for chat + shell.
        T2 (REQ-1 AC3): TerminalSlideOver / TerminalWidget are removed
        from developer mode ENTIRELY (decision locked 2026-08-21) —
        all shell output streams into the unified scroll above via
        terminalScrollback subscriptions, which are preserved. */
  return (
      <div
        className={isRemoteView ? "iris-comp px-4 pb-4 pt-4 flex-shrink-0 relative z-30 bg-black/60 border-t" : "iris-comp px-3 pb-3 pt-4 flex-shrink-0 relative z-30 bg-black/60 border-t"}
        style={{ borderColor: 'rgba(255,255,255,0.05)', ['--b1' as string]: b1, ['--b2' as string]: b2 }}
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
              // Audit bug: this path built its own message and sent it
              // with no conversation_id, no typing state and no dev
              // routing. It now takes the one send path.
              void handleSendMessage(s.message)
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

        {/* Composer design 2026-10-06, both modes: who hears this and the
            picked # references, then the project folder and open files, then
            the message box. */}
        <RefTray refs={composerRefs} onRemove={(a) => setComposerRefs(prev => prev.filter(r => r.address !== a))} />
        <ProjectBar />
        {refMatches.length > 0 && (
          <RefPicker items={refMatches} selected={refSelIdx} onPick={pickRef} />
        )}

          {/* Mode-split input area (cli-workspace-unification scope fix):
              DEVELOPER gets the REQ-1/REQ-2 attached two-row footer;
              PERSONAL keeps the ORIGINAL single-row layout (Web toggle
              LEFT of the textarea, pill cluster RIGHT of it on the same
              row, aligned to the textarea glow line). REQ-2's user story
              is developer-scoped — the restructured footer must not leak
              into personal mode. */}
          <div className={isDeveloper ? "relative" : (isRemoteView ? "relative flex items-end gap-2 px-1" : "relative flex items-end gap-2")} style={{ marginRight: '4px' }}>

          {/* REQ-6 AC3 (T7): the counterpart to pinned-only auto-scroll.
              Once the user scrolls up they are no longer auto-followed,
              so they need one control to get back. Sits above the
              composer (same `absolute bottom-full` slot the slash menu
              uses) and disappears the moment they are pinned again. */}
          {showJumpToLatest && (
            <button
              type="button"
              onClick={jumpToLatest}
              data-testid="jump-to-latest"
              className="absolute bottom-full right-0 mb-1.5 z-40 flex items-center gap-1 px-2 py-1 rounded-full text-[10px] transition-opacity hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, rgba(5,5,12,0.97) 0%, rgba(12,12,20,0.95) 100%)',
                border: `1px solid ${glowColor}40`,
                color: fontColor,
                boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
              }}
              title="Jump to latest"
            >
              <ChevronDown size={12} style={{ color: glowColor }} />
              Jump to latest
            </button>
          )}

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
            {/* Gate 3 T12 (REQ-7): slash-command menu — filtered from
                GET /api/dev/cli-tools; Tab/Enter accept, Escape dismiss.
                Rendered above the input; never intercepts '@'. */}
            {isDeveloper && slashMenuOpen && slashMatches.length > 0 && (
              <div className="absolute bottom-full left-0 right-0 mb-1 z-50"
                style={{
                  background: 'linear-gradient(135deg, rgba(5,5,12,0.97) 0%, rgba(12,12,20,0.95) 100%)',
                  border: `1px solid ${glowColor}40`,
                  borderRadius: '8px',
                  boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
                  // REQ-4 AC1: this menu was `overflow-hidden`, so it was
                  // never a scroll container and the wheel passed straight
                  // through it to the timeline. Cap it and let it scroll
                  // itself, then trap the gesture at its edges.
                  maxHeight: 'min(30vh, 260px)',
                  overflowY: 'auto',
                  overscrollBehavior: 'contain',
                }}>
                {slashMatches.map((c) => (
                  <button key={c.name} type="button"
                    onMouseDown={(ev) => { ev.preventDefault(); acceptSlash(c.name) }}
                    className="w-full text-left px-3 py-1.5 flex items-baseline gap-2 hover:bg-white/5 transition-colors">
                    <span className="font-mono text-[11px]" style={{ color: glowColor }}>{c.display_name}</span>
                    <span className="text-[10px] opacity-60 truncate">{c.when_to_use}</span>
                  </button>
                ))}
              </div>
            )}
            {/* Gate 3 T12 AC2: '>' hint row — workdir + shell mode,
                non-blocking. */}
            {isDeveloper && inputText.startsWith('>') && (
              <div className="absolute bottom-full left-0 mb-1 px-2 py-0.5 font-mono text-[9px] opacity-60 pointer-events-none"
                style={{ color: fontColor }}>
                {'{'}shell mode{'}'} {activeTabPath ?? '(default repo)'}
              </div>
            )}
            <textarea
              ref={inputRef as any}
              value={inputText}
              onChange={(e) => {
                const v = e.target.value;
                setInputText(v);
                setRefSel(0);
                const opening = /(^|\s)@$/.test(v);
                if (opening && !cardMentionOpen) openCardMentionPicker();
                setCardMentionOpen(opening);
                // ── Gate 3 T12 (REQ-7): '/' opens the command menu;
                // '@' picker precedence is untouched (CONTRACT LOCK).
                if (isDeveloper && voiceState !== 'listening') {
                  setSlashMenuOpen(v.startsWith('/'))
                } else if (slashMenuOpen) {
                  setSlashMenuOpen(false)
                }
                // Auto-expand height
                e.target.style.height = 'auto';
                e.target.style.height = `${e.target.scrollHeight}px`;
              }}
              onKeyDown={(e) => {
                // ── # reference picker keys (accept beats send, like the slash menu)
                if (refMatches.length > 0) {
                  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault()
                    setRefSel((refSelIdx + (e.key === 'ArrowDown' ? 1 : refMatches.length - 1)) % refMatches.length)
                    return
                  }
                  if ((e.key === 'Enter' || e.key === 'Tab') && !e.shiftKey) {
                    e.preventDefault()
                    pickRef(refMatches[refSelIdx])
                    return
                  }
                  if (e.key === 'Escape') {
                    e.preventDefault()
                    setHashDismissedFor(inputText)
                    return
                  }
                }
                // ── Gate 3 T12 (REQ-7): slash menu keys ──────────
                if (slashMenuOpen && slashMatches.length > 0) {
                  if (e.key === 'Escape') {
                    e.preventDefault()
                    setSlashMenuOpen(false) // close without clearing input
                    return
                  }
                  if ((e.key === 'Tab' || e.key === 'Enter') && !e.shiftKey) {
                    e.preventDefault() // accept beats send while menu is open
                    acceptSlash(slashMatches[0].name)
                    return
                  }
                } else if (slashMenuOpen && e.key === 'Escape') {
                  e.preventDefault()
                  setSlashMenuOpen(false)
                  return
                }
                // ── Gate 3 T11 (REQ-6): ↑/↓ command history ──────
                if (isDeveloper && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
                  const el = e.currentTarget
                  // multi-line draft: arrows must move the caret (REQ-6 edge)
                  if (inputText.includes('\n')) return
                  const atStart = el.selectionStart === 0 && el.selectionEnd === 0
                  const atEnd = el.selectionStart === el.value.length
                  if (e.key === 'ArrowUp' && !atStart) return
                  if (e.key === 'ArrowDown' && !atEnd) return
                  e.preventDefault()
                  const { line } = recallHistory(e.key === 'ArrowUp' ? 'up' : 'down', inputText)
                  if (line !== null) {
                    setInputText(line)
                    requestAnimationFrame(() => {
                      el.selectionStart = el.selectionEnd = el.value.length
                    })
                  }
                  return
                }
                // ── Gate 3 T13 (REQ-8): Ctrl+C abort ─────────────
                if (isDeveloper && e.key === 'c' && (e.ctrlKey || e.metaKey) && !e.shiftKey) {
                  // Only when text is NOT selected (copy keeps working).
                  const el = inputRef.current
                  const hasSelection = !!el && el.selectionStart !== el.selectionEnd
                  if (hasSelection) return
                  e.preventDefault()
                  if (terminalSnapshot.sessionState === 'working') {
                    sendMessage?.('dev_abort', {})
                    appendSystem('^C — abort sent')
                  } else {
                    setInputText('') // nothing running: clear line (AC3)
                  }
                  return
                }
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                  // Reset height
                  if (inputRef.current) inputRef.current.style.height = 'auto';
                }
              }}
              onFocus={() => setIsInputFocused(true)}
              onBlur={() => setIsInputFocused(false)}
              placeholder={
                voiceState === 'listening'
                  ? 'Listening...'
                  : isDeveloper
                    ? 'command  ·  / tools  ·  > shell  ·  @ card'
                    : 'Type command or drop file...'
              }
              disabled={voiceState === 'listening'}
              className={
                isRemoteView
                  ? "w-full bg-transparent border-0 py-3 pr-2 text-[16px] focus:outline-none transition-all placeholder:text-white/30 disabled:opacity-50 resize-none min-h-[44px] max-h-[120px] scrollbar-hide"
                  : isDeveloper
                    /* pl-5 clears the prompt glyph rendered below. */
                    ? "w-full bg-transparent border-0 py-2 pl-5 pr-9 font-mono text-[12px] focus:outline-none transition-all placeholder:text-white/25 disabled:opacity-50 resize-none min-h-[36px] max-h-[120px] scrollbar-hide"
                    : "w-full bg-transparent border-0 py-2 pr-2 text-[13px] focus:outline-none transition-all placeholder:text-white/30 disabled:opacity-50 resize-none min-h-[36px] max-h-[120px] scrollbar-hide"
              }
              rows={1}
              style={{
                borderColor: isDraggingFile ? glowColor : inputText ? glowColor : `${glowColor}30`,
                color: fontColor,
                borderBottomWidth: '1px',
                boxShadow: isDraggingFile ? `0 0 8px ${glowColor}40` : inputText ? `0 1px 0 0 ${glowColor}` : 'none',
                // The caret is the one part of a CLI the user watches
                // constantly, so it carries the brand colour rather than
                // the browser default.
                caretColor: isDeveloper ? glowColor : undefined,
              }}
            />

            {/* Developer mode: the one send/stop button sits at the end of the
                line (the footer toolbar has no spare width for it). */}
            {isDeveloper && (
              <div className="absolute right-0" style={{ top: '4px' }}>{sendStopButton(true)}</div>
            )}

            {/* Prompt glyph. Developer mode only, and hidden while the
                mic is open — the line is not yours to type on then. */}
            {isDeveloper && !isRemoteView && voiceState !== 'listening' && (
              <span
                aria-hidden
                className="absolute left-0 font-mono text-[12px] pointer-events-none select-none"
                style={{ top: '0.5rem', lineHeight: '1.25rem', color: glowColor, opacity: 0.75 }}
              >
                ❯
              </span>
            )}
            
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

          {/* REQ-7 (T8) — explicit send control. PERSONAL MODE ONLY.
              Developer mode is a CLI surface with its own affordances,
              and its REQ-2 footer toolbar measures 454px against 486px
              usable at the balanced wing; a 44px control would overflow
              it (measured 2026-09-04). Personal mode's textarea is
              flex-1 with no min-width, so it absorbs the 40px: 292→252
              at the 360px wing, 442→402 at 510, 612→572 at 680.
              Guards mirror the send path (handleSendMessage :1844):
              empty input, or an actively-listening mic. isTyping
              deliberately does NOT disable — the backend per-session
              lock queues messages (long-horizon-der-execution).
              AC3: onClick is handleSendMessage itself; no second path.
              2026-10-06 (composer design): while a turn runs in this
              conversation the same button reads "Stop IRIS" and sends the
              stop message; developer mode gets it at the end of the line.

              SUPERSEDES specs/phase-5-switcher REQ-1 AC1 (which removed
              the Send pill). That decision's load-bearing half — AC3,
              moving the button's disabled conditions into the send path —
              is preserved and still locked by its own tests; only the
              visibility half is reversed. Signed off 2026-09-04. */}
          {!isDeveloper && (
            <div className="flex-shrink-0" style={{ transform: 'translateY(-6.5px)' }}>
              {sendStopButton(false)}
            </div>
          )}

          {/* DEVELOPER MODE ONLY — attached horizontal footer toolbar (REQ-2).
              Exact sequence: [Web 32] →8px→ [Upload 32] →12px→ |1px| →12px→
              [Model 116] →12px→ |1px| →12px→ [Chips 32] →10px→ [ContextPill 174]
              = 454px explicit width, centered in the 486px usable width
              (balanced ≈16px distribution margin). The ⏎ enter icon stays
              removed (AC4); its width is allocated to ContextPill (174px).

              THE SPACING IS EXPLICIT, PER PAIR — do not replace it with a
              uniform `gap` and a justify rule. That substitution is what
              broke this row, and it was then "fixed" four times by
              changing the justification (ml-auto, justify-center,
              justify-evenly, justify-between) and once by making the pill
              flex-1. None could work: a single gap value cannot express
              8/12/12/12/12/10, and the pill caps itself at max-w-[200px]
              so it can never absorb slack handed to it.
              justify-center keeps the 454px cluster centred, so whatever
              width the wing happens to be (510 balanced / 680 spotlight /
              360 background) the margins stay equal on both sides. */}
          {isDeveloper ? (
           <div className="flex items-center justify-start w-full px-2 mt-2 h-[32px] flex-shrink-0">

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
              className="flex items-center justify-center w-[32px] h-[32px] ml-[8px] transition-all disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
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
            <div className="flex-shrink-0 rounded-full ml-[12px]" style={{ width: '1px', height: '20px', background: glowColor, opacity: 0.3 }} />

            {/* Model switcher — Phase 5 REQ-2. Sibling of ContextPill
                (D-2), never a new ContextPill prop (CT-S1). Reads
                useInferenceState and writes through its existing
                sendRoleBinding — no new backend surface (D-3). */}
            <div className="flex-shrink-0 ml-[12px]">
              <ModelSwitcher glowColor={glowColor} fontColor={fontColor} />
            </div>

            {/* Divider 2 — the REQ-2 sequence has a rule on BOTH sides of
                the model switcher. It was lost when the row was converted
                to a uniform gap, which is part of why the spacing stopped
                reading as a designed rhythm. */}
            <div className="flex-shrink-0 rounded-full ml-[12px]" style={{ width: '1px', height: '20px', background: glowColor, opacity: 0.3 }} />

            {/* Model switcher — Phase 5 REQ-2. Sibling of ContextPill
                (D-2), never a new ContextPill prop (CT-S1). Reads
                useInferenceState and writes through its existing
                sendRoleBinding — no new backend surface (D-3).
                Rendered on the LEFT per layout order. */}
            <ModelSwitcher glowColor={glowColor} fontColor={fontColor} />

            {/* The conversation chips moved onto the timeline's spine gutter
                (components/chat/spine): hover the left edge for the turns. */}

            {/* ContextPill — declares its own dark-glass panel; the ⏎
                enter icon's freed width gives it the full 174px REQ-2
                allocation. Rendered LAST in the sequence (far right).
                Internal order is phase label then token numbers
                (e.g. "IDLE  0 / 128.0k"). */}
            {/* The pill CANNOT absorb the row's slack, whatever the
                wrapper says: ContextPill caps itself at max-w-[200px], so
                a flex-1 wrapper just grows an empty box around a 200px
                pill and leaves the gap exactly where it was. That is the
                mistake behind every previous attempt at this footer —
                ml-auto, justify-center, justify-evenly and flex-1 all
                tried to hand the slack to a child that is not allowed to
                take it.
                The row distributes the slack BETWEEN the controls instead
                (justify-between on the container), which puts the web
                toggle on the left edge and this pill on the right edge and
                spreads the rest across the middle. min-w-0 stays so the
                pill can still shrink when the row is genuinely tight —
                REQ-3's rule that the SWITCHER collapses first. */}
            {/* No flex-1: the pill sizes to its content now, and mr-3
                keeps it off the footer's right edge so the conversation
                chips' dropdown — which opens beside it — has somewhere to
                land instead of being clipped by the panel border. */}
            <div className="min-w-0 mr-3" style={{ marginLeft: 'auto' }}>
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
  )
}
