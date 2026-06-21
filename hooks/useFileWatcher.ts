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

export function useFileWatcher(options: UseFileWatcherOptions = {}) {
  const { rootPath = '/', onEvent } = options
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8090'}/ws/files`
    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        // Subscribe to root path
        ws.send(JSON.stringify({ action: 'watch', path: rootPath }))
      }

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as FileEvent
          if (onEvent && ['file_changed', 'file_created', 'file_deleted'].includes(data.type)) {
            onEvent(data)
          }
        } catch {
          // Ignore invalid messages
        }
      }

      ws.onclose = () => {
        wsRef.current = null
        // Reconnect after 3s
        reconnectTimeoutRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch {
      // WS not available, reconnect later
      reconnectTimeoutRef.current = setTimeout(connect, 5000)
    }
  }, [rootPath, onEvent])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, [connect])

  return {
    send: (message: object) => {
      wsRef.current?.send(JSON.stringify(message))
    },
    isConnected: () => wsRef.current?.readyState === WebSocket.OPEN,
  }
}
