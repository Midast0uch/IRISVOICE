"use client"

import { useEffect, useState } from "react"

export interface AgentQuestionState {
  hasPendingQuestion: boolean
  questionId?: string
}

/**
 * Lifts pending-question state for the orb (chat-view keeps its own
 * pendingQuestions for the inline QuestionCard). The orb shows a question
 * badge when a question is asked and wings are closed.
 */
export function useAgentQuestion(): AgentQuestionState {
  const [state, setState] = useState<AgentQuestionState>({
    hasPendingQuestion: false,
  })

  useEffect(() => {
    const onAsk = (e: Event) => {
      const detail = (e as CustomEvent).detail
      setState({ hasPendingQuestion: true, questionId: detail?.questionId })
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
