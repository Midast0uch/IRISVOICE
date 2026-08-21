'use client'

/**
 * TerminalSlideOver — on-demand Developer Terminal slide-over (T13a, REQ-13).
 *
 * The terminal is NOT a permanently resident panel: it slides in from the
 * right edge when opened (header button or `>term` command) and slides away
 * when closed. The panel element stays MOUNTED the whole time — only its
 * transform/visibility changes — and its scrollback lives in the module-level
 * `terminalScrollback` store, so closing and reopening NEVER loses context
 * (command history, rendered task blocks, question lists). Even a full unmount
 * (e.g. switching to the dashboard) preserves the scrollback, because the
 * store is module-scoped and keeps consuming window events for the session.
 *
 * Rendering is plain text / ASCII box-drawing — no canvas, no xterm — which is
 * the "ASCII fallback when no canvas" requirement satisfied naturally.
 *
 * Input routing (preserves the `>cmd` / `>run` channel distinction from
 * chat-view.tsx — T13b):
 *   - an answer to a rendered question  -> REQ-6 funnel:
 *     `sendMessage('question_response', { question_id, answer })`
 *   - `/run <request>`                  -> DELEGATE: `dev_cli` (agent picks tool)
 *   - anything else                     -> SHELL:   `terminal_input` (direct)
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { X, Trash2, Terminal as TerminalIcon } from 'lucide-react'
import type { SendMessageFunction } from '@/hooks/useIRISWebSocket'
import {
  subscribe,
  getSnapshot,
  appendCommand,
  appendOutput,
  appendSystem,
  clear,
  toggleOpen,
  resolveTerminalAnswer,
  renderTaskBlockAscii,
  renderQuestionAscii,
  TERMINAL_HELP,
  type TerminalLine,
} from './terminalScrollback'

interface TerminalSlideOverProps {
  sendMessage?: SendMessageFunction
  glowColor?: string
}

const LINE_COLORS: Record<TerminalLine['kind'], string> = {
  command: '#34d399',
  output: 'rgba(226,232,240,0.9)',
  system: 'rgba(255,255,255,0.4)',
  error: '#fc8181',
}

function LineView({ line }: { line: TerminalLine }) {
  return (
    <div
      className="whitespace-pre-wrap break-words"
      style={{ color: LINE_COLORS[line.kind] }}
    >
      {line.text}
    </div>
  )
}

export function TerminalSlideOver({ sendMessage, glowColor = '#60a5fa' }: TerminalSlideOverProps) {
  const [snapshot, setSnapshot] = useState(getSnapshot)
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Subscribe to the module-level store. The store survives unmounts, so this
  // re-subscribes to the SAME preserved scrollback on every reopen.
  useEffect(() => subscribe(() => setSnapshot(getSnapshot())), [])

  // Auto-scroll — unified scroll with messages (no separate scrollbar), so scroll the parent messages container.
  useEffect(() => {
    const parent = (scrollRef.current?.closest('[data-messages-scroll]') as HTMLElement | null) || scrollRef.current
    if (parent) parent.scrollTop = parent.scrollHeight
  }, [snapshot])

  // Focus the input when the panel opens.
  useEffect(() => {
    if (snapshot.isOpen) inputRef.current?.focus()
  }, [snapshot.isOpen])

  const handleSubmit = useCallback(() => {
    const text = input.trim()
    if (!text) return
    setInput('')
    appendCommand(text)

    // 1. REQ-6 answer funnel FIRST — an input that resolves to a rendered
    //    question is an answer, routed through the SAME call the QuestionCard
    //    uses (`question_response`). Never a separate answer path.
    const resolved = resolveTerminalAnswer(text, snapshot.questions)
    if (resolved) {
      sendMessage?.('question_response', {
        question_id: resolved.questionId,
        answer: resolved.answer,
        source: 'cli',
      })
      appendSystem(`[answered question ${resolved.questionId}]`)
      return
    }

    // 2. Local commands.
    const lower = text.toLowerCase()
    if (lower === '>term') {
      toggleOpen()
      return
    }
    if (lower === 'clear') {
      clear()
      return
    }
    if (lower === 'help') {
      appendOutput(TERMINAL_HELP)
      return
    }

    // 3. DELEGATE channel (`/run <request>` -> dev_cli) — labelled, distinct
    //    from the SHELL channel below (T13b: do not regress the split).
    if (text.startsWith('/run ')) {
      const query = text.slice(5).trim()
      if (query) {
        appendSystem('[delegate] /run → dev_cli')
        sendMessage?.('dev_cli', { query })
      }
      return
    }

    // 4. SHELL channel (matches the `>` prefix in the composer).
    appendSystem('[shell] → terminal_input')
    sendMessage?.('terminal_input', { line: text })
  }, [input, snapshot.questions, sendMessage])

  const open = true

  return (
    <div
        className="flex flex-col flex-shrink-0"
        style={{
          background: 'transparent',
        }}
        role="region"
        aria-label="Developer Terminal — hybrid, fused single input with chat textarea"
      >
        {/* Header — minimal, fused, no extra border when inside single input block */}
        <div
          className="flex items-center justify-between px-3 py-1.5 shrink-0 select-none"
          style={{ borderBottom: `1px solid ${glowColor}08` }}
        >
          <div className="flex items-center gap-2">
            <TerminalIcon size={12} style={{ color: `${glowColor}90` }} />
            <span className="text-[11px] font-medium tracking-wide" style={{ color: 'rgba(255,255,255,0.75)' }}>
              Terminal
            </span>
            {snapshot.questions.length > 0 && (
              <span
                className="text-[9px] px-1.5 py-0.5 rounded-full"
                style={{
                  background: `${glowColor}12`,
                  color: glowColor,
                  border: `1px solid ${glowColor}20`,
                }}
              >
                {snapshot.questions.length} question{snapshot.questions.length === 1 ? '' : 's'}
              </span>
            )}
            <span className="ml-1 text-[10px]" style={{ color: 'rgba(255,255,255,0.25)' }}>
              hybrid — fused with chat input
            </span>
          </div>
          <button
            onClick={clear}
            title="Clear terminal"
            aria-label="Clear terminal"
            className="p-1 rounded hover:bg-white/10 transition-colors"
          >
            <Trash2 size={12} style={{ color: 'rgba(255,255,255,0.35)' }} />
          </button>
        </div>

        {/* Scrollback — shares Unified Scroll with messages (no separate scrollbar) */}
        <div
          ref={scrollRef}
          className="px-3 py-2 font-mono text-[11px] leading-relaxed"
          style={{ color: 'rgba(226,232,240,0.9)' }}
        >
          {snapshot.lines.length === 0 &&
          snapshot.taskBlocks.length === 0 &&
          snapshot.questions.length === 0 ? (
            <div className="text-white/30">
              Terminal ready. Type a command, or /run &lt;request&gt; to delegate. Type help for
              commands.
            </div>
          ) : (
            <>
              {snapshot.lines.map((line) => (
                <LineView key={line.id} line={line} />
              ))}
              {snapshot.taskBlocks.map((block) => (
                <pre
                  key={block.cardId}
                  className="my-1 whitespace-pre"
                  style={{ color: 'rgba(226,232,240,0.9)' }}
                >
                  {renderTaskBlockAscii(block).join('\n')}
                </pre>
              ))}
              {snapshot.questions.map((q, i) => (
                <pre
                  key={q.questionId}
                  className="my-1 whitespace-pre"
                  style={{ color: 'rgba(226,232,240,0.9)' }}
                >
                  {renderQuestionAscii(q, i + 1).join('\n')}
                </pre>
              ))}
            </>
          )}
        </div>

      </div>
  )
}

export default TerminalSlideOver