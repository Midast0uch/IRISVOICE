"use client"

import { apiUrl } from "@/lib/apiOrigin"
import { useEffect, useRef, useState } from "react"

/**
 * useCrawlSSE — resilient SSE fallback for crawl research (REQ-31 AC3/AC5).
 *
 * The raw WebSocket is NOT guaranteed for the desktop widget: no auto-reconnect,
 * frequent suspend/resume drops. This hook opens an EventSource to
 * GET /api/crawl/stream/{sessionId} which replays missed events from
 * Last-Event-ID (the browser sends it automatically on reconnect) and then
 * streams live events. Every SSE message is re-dispatched as the SAME
 * CustomEvent the WS path uses, so useCrawl (and the rest of the UI) is
 * transport-agnostic.
 *
 * It only activates when the primary WS is down (caller passes wsConnected=false)
 * so we don't double-deliver events while WS is healthy.
 */
export function useCrawlSSE(sessionId: string | null, wsConnected: boolean) {
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    // Only run the SSE fallback when WS is NOT connected.
    if (wsConnected || !sessionId) {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
        setConnected(false)
      }
      return
    }

    // apiUrl, not a bare path: EventSource is not fetch, so the origin bridge
    // in lib/apiOrigin cannot intercept it. In a packaged build a relative
    // path here would resolve against tauri.localhost and never connect.
    const url = apiUrl(`/api/crawl/stream/${encodeURIComponent(sessionId)}`)
    const es = new EventSource(url)
    esRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => {
      // EventSource auto-reconnects with Last-Event-ID; mark disconnected
      // only so the UI can show a degraded banner. The browser retries.
      setConnected(false)
    }
    es.onmessage = (ev: MessageEvent) => {
      let msg: any
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      const type = msg.type
      if (!type) return
      // Re-dispatch as the same CustomEvent the WS path emits. The event name
      // is "iris:" + type (matches useIRISWebSocket dispatch convention).
      window.dispatchEvent(new CustomEvent(`iris:${type}`, { detail: msg }))
    }

    return () => {
      es.close()
      esRef.current = null
      setConnected(false)
    }
  }, [sessionId, wsConnected])

  return { sseConnected: connected }
}
