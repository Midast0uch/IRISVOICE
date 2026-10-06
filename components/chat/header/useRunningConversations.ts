"use client"

import { useMemo, useSyncExternalStore } from "react"
import { getTurnsState, subscribeTurns } from "@/lib/turns/turnStore"

const NONE = new Set<string>()

/**
 * Conversation ids that have a turn running now. A running turn in a
 * conversation other than the one on screen means another strand works.
 */
export function useRunningConversations(): ReadonlySet<string> {
  const state = useSyncExternalStore(subscribeTurns, getTurnsState, getTurnsState)
  return useMemo(() => {
    let out: Set<string> | null = null
    for (const [conv, ids] of Object.entries(state.byConversation)) {
      if (ids.some((id) => state.byId[id]?.status === "running")) (out ??= new Set()).add(conv)
    }
    return out ?? NONE
  }, [state])
}
