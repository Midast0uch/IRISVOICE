"use client"

import { useEffect, useState } from "react"

export interface AgentQuestion {
  questionId: string
  text: string
  options?: string[]
  allowOther?: boolean
  multiSelect?: boolean
  header?: string
}

export interface AgentQuestionState {
  hasPendingQuestion: boolean
  /** Id of the question SET, when the tool emitted one. */
  setId?: string
  /** Every question in the set, in the order the agent asked them. */
  questions: AgentQuestion[]
  /** First question — the single-question convenience the old shape exposed. */
  questionId?: string
  text?: string
  options?: string[]
  allowOther?: boolean
}

const EMPTY: AgentQuestionState = { hasPendingQuestion: false, questions: [] }

/**
 * Lifts pending-question state for the surfaces outside ChatView.
 *
 * SOURCE OF TRUTH: the agent's AskUserQuestion tool
 * (`backend/agent/tools/ask_user_tool.py`), which emits `question:ask` on the
 * event bus; `useIRISWebSocket` forwards it verbatim as `iris:question_ask`.
 * chat-view keeps its own `pendingQuestions` map for the inline QuestionCard;
 * this hook is the wing-independent read of the SAME event, so a question can
 * be seen and answered when ChatView is not on screen (REQ-16).
 *
 * THE PAYLOAD IS A SET, NOT A QUESTION. The tool always sends `set_id` + a
 * `questions` array, and mirrors the legacy top-level
 * `question_id`/`text`/`options`/`allow_other` keys ONLY when the set holds
 * exactly one question (see ask_user_tool.py "WIRE PAYLOAD"). Reading only the
 * top-level keys — which this hook used to do — therefore drops EVERY
 * multi-question set on the floor. The array is preferred here and the legacy
 * keys are the fallback.
 *
 * FIELD-NAME BUG FIXED 2026-08-25: this read `detail?.questionId`, but the
 * payload is snake_case (`question_id`), matching chat-view's handler and the
 * backend. `questionId` was therefore ALWAYS undefined — harmless while only a
 * "?" badge consumed it, fatal the moment anything tried to ANSWER with it.
 * Both spellings are accepted so a rename on either side cannot silently
 * reintroduce it. (The same class of bug already cost this feature once:
 * agent_kernel.py:4467 records `iris:question:ask` vs `iris:question_ask`
 * stopping QuestionCard from ever rendering.)
 */
export function useAgentQuestion(): AgentQuestionState {
  const [state, setState] = useState<AgentQuestionState>(EMPTY)

  useEffect(() => {
    const onAsk = (e: Event) => {
      const d = (e as CustomEvent).detail || {}

      const raw: unknown[] = Array.isArray(d.questions) && d.questions.length
        ? d.questions
        : [d] // single-question set, or a pre-set-era payload

      const questions: AgentQuestion[] = raw
        .map((item): AgentQuestion | null => {
          const q = (item || {}) as Record<string, unknown>
          const id = q.question_id ?? q.questionId
          const text = q.text
          if (!id || !text) return null
          return {
            questionId: String(id),
            text: String(text),
            options: Array.isArray(q.options) ? q.options.map(String) : undefined,
            allowOther: Boolean(q.allow_other ?? q.allowOther),
            multiSelect: Boolean(q.multi_select ?? q.multiSelect),
            header: q.header ? String(q.header) : undefined,
          }
        })
        .filter((q): q is AgentQuestion => q !== null)

      // Nothing answerable in the payload — ignore rather than render a dead
      // prompt with no id to respond with.
      if (questions.length === 0) return

      const first = questions[0]
      setState({
        hasPendingQuestion: true,
        setId: d.set_id ? String(d.set_id) : undefined,
        questions,
        questionId: first.questionId,
        text: first.text,
        options: first.options,
        allowOther: first.allowOther,
      })
    }
    const onDone = () => setState(EMPTY)

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
