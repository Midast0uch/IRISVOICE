'use client'

import { useEffect, useRef, useCallback } from 'react'

export type FileEventType = 'file_changed' | 'file_created' | 'file_deleted'

export interface FileEvent {
  type: FileEventType
  path: string
  content?: string
}

interface UseFileWatcherOptions {
  rootPath?: string
  onEvent?: (event: FileEvent) => void
}

// ─────────────────────────────────────────────────────────────────────────────
// OFF until the backend endpoint exists (2026-10-07).
//
// There is NO `/ws/files` route in the backend. The only WebSocket route is the
// catch-all `@app.websocket("/ws/{client_id}")` (main.py:3200), so
// `/ws/files` connected with client_id="files" and landed in the MAIN IRIS
// GATEWAY, which requires a `type` field. This client sends
// `{ action: 'watch', path }` — a protocol the server never implemented — so
// every connect logged `[ERROR] Missing message type from client files`.
//
// Consequence: the file watcher has NEVER worked. Nothing depends on it, so
// the honest state is "not connected" rather than "connected and failing".
//
// TO RE-ENABLE: implement `POST`-free read-only `GET /ws/files` on the backend
// that accepts `{action:'watch', path}` and pushes
// `{type:'file_changed'|'file_created'|'file_deleted', path, content?}` back,
// THEN set this to true. The message shape below is the contract it must
// implement — do not change one side alone.
// ─────────────────────────────────────────────────────────────────────────────
const FILES_WS_ENABLED = false

const FILES_WS_URL = `${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8090'}/ws/files`

export function useFileWatcher(options: UseFileWatcherOptions = {}) {
  const { rootPath = '/', onEvent } = options

  // Callbacks and options live in REFS, not in the connect() dependency list.
  //
  // 2026-10-07: `connect` was a useCallback on [rootPath, onEvent] and the
  // effect depended on [connect]. DeveloperWorkspace.tsx passes an INLINE
  // arrow for onEvent, so `connect` was rebuilt on every render and the effect
  // tore down and reopened the socket every render. The cleanup called
  // `ws.close()`, which fired `onclose` and scheduled a NEW 3 s reconnect timer
  // AFTER `clearTimeout` had already run — so the timer survived and fired
  // again. Sockets and timers accumulated at RENDER cadence: measured live at
  // ~1 reconnect per second on a page that re-renders about once a second.
  // Holding the handler in a ref decouples the socket from render identity.
  const onEventRef = useRef(onEvent)
  const rootPathRef = useRef(rootPath)
  onEventRef.current = onEvent
  rootPathRef.current = rootPath

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmountedRef = useRef(false)

  const clearReconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    if (unmountedRef.current) return
    // ONE reconnect at a time. Previously every teardown could leave a pending
    // timer behind, which is what turned a 3 s backoff into a 1 Hz storm.
    clearReconnect()

    let ws: WebSocket
    try {
      ws = new WebSocket(FILES_WS_URL)
    } catch {
      // WS not available — retry, but only if we are still mounted.
      if (!unmountedRef.current) {
        reconnectTimeoutRef.current = setTimeout(connect, 5000)
      }
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      // Subscribe to the root path. Contract documented at FILES_WS_ENABLED.
      ws.send(JSON.stringify({ action: 'watch', path: rootPathRef.current }))
    }

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as FileEvent
        const handler = onEventRef.current
        if (
          handler &&
          ['file_changed', 'file_created', 'file_deleted'].includes(data.type)
        ) {
          handler(data)
        }
      } catch {
        // Ignore invalid messages
      }
    }

    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null
      if (unmountedRef.current) return
      reconnectTimeoutRef.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [clearReconnect])

  useEffect(() => {
    unmountedRef.current = false
    if (FILES_WS_ENABLED) {
      connect()
    }
    return () => {
      // Mark unmounted FIRST: onclose checks it, so no reconnect is scheduled
      // after teardown.
      unmountedRef.current = true
      clearReconnect()
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        ws.onclose = null
        ws.close()
      }
    }
  }, [connect, clearReconnect])

  return {
    send: (message: object) => {
      wsRef.current?.send(JSON.stringify(message))
    },
    isConnected: () => wsRef.current?.readyState === WebSocket.OPEN,
  }
}