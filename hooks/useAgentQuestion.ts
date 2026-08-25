"use client"

import { useEffect, useState } from "react"

export interface AgentQuestionState {
  hasPendingQuestion: boolean
  questionId?: string
  /** The question itself. Needed to ANSWER it outside ChatView (REQ-16). */
  text?: string
  /** Multiple-choice options, when the asker supplied them. */
  options?: string[]
  /** True when a free-text answer is accepted alongside/instead of options. */
  allowOther?: boolean
}

/**
 * Lifts pending-question state for the surfaces outside ChatView.
 *
 * chat-view keeps its own `pendingQuestions` map for the inline QuestionCard;
 * this hook is the wing-independent read of the same event stream, so a
 * question can be SEEN AND ANSWERED when ChatView is not on screen (REQ-16).
 *
 * It used to expose only `hasPendingQuestion` + `questionId`, which was enough
 * for a "?" badge and nothing else. The text and options were on the event all
 * along — they were simply dropped here, which is why the only thing the orb
 * could ever say was "there is a question somewhere else".
 *
 * FIELD-NAME BUG FIXED 2026-08-25: this read `detail?.questionId`, but the
 * payload is snake_case (`question_id`, matching chat-view.tsx's handler and
 * the backend). `questionId` was therefore ALWAYS undefined — harmless while
 * nothing used it, fatal the moment anything tried to answer with it. Both
 * spellings are accepted now so a future rename on either side cannot silently
 * reintroduce it.
 */
export function useAgentQuestion(): AgentQuestionState {
  const [state, setState] = useState<AgentQuestionState>({
    hasPendingQuestion: false,
  })

  useEffect(() => {
    const onAsk = (e: Event) => {
      const detail = (e as CustomEvent).detail || {}
      const id = detail.question_id ?? detail.questionId
      const text = detail.text
      // Without an id there is nothing to answer, and without text there is
      // nothing to show — ignore the event rather than render a dead prompt.
      if (!id || !text) return
      setState({
        hasPendingQuestion: true,
        questionId: String(id),
        text: String(text),
        options: Array.isArray(detail.options) ? detail.options.map(String) : undefined,
        allowOther: detail.allow_other ?? detail.allowOther,
      })
    }
    const onDone = () => setState({ hasPendingQuestion: false })

    window.addEventListener("iris:question_ask", onAsk)
    window.addEventListener("iris:question_answered", onDone)
    window.addEventListener("iris:question_timeout", onDone)
    return () => {
      window.removeEventListener("iris:question_ask", onAsk)
      window.removeEventListener("iris:question_answered", onDone)
      window.removeEventListener("iris:question_timeout", onDone)
    }
  }, [])

  return state
}
