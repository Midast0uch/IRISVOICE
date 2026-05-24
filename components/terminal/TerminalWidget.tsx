'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { useTerminal } from '@/contexts/TerminalContext'

const ACCENT_FALLBACK = '#60a5fa'

export function TerminalWidget() {
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || ACCENT_FALLBACK
  const { sendMessage } = useTerminal()

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const termRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fitAddonRef = useRef<any>(null)
  const lineBufferRef = useRef<string>('')
  const sendRef = useRef(sendMessage)
  const containerRef = useRef<HTMLDivElement>(null)
  const [workdir, setWorkdir] = useState<string>('')
  const [mounted, setMounted] = useState(false)

  useEffect(() => { sendRef.current = sendMessage }, [sendMessage])

  // Initialize xterm once
  useEffect(() => {
    if (!containerRef.current) return
    const container = containerRef.current

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let term: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let fitAddon: any
    let resizeObserver: ResizeObserver | null = null
    let disposed = false

    Promise.all([
      import('@xterm/xterm'),
      import('@xterm/addon-fit'),
    ]).then(([{ Terminal }, { FitAddon }]) => {
      if (disposed) return

      term = new Terminal({
        fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
        fontSize: 13,
        lineHeight: 1.5,
        cursorBlink: true,
        cursorStyle: 'bar',
        theme: {
          background: '#0b0c1a',
          foreground: '#e2e8f0',
          cursor: glowColor,
          selectionBackground: `${glowColor}40`,
          black: '#1a1a2e',
          brightBlack: '#4a5568',
          red: '#fc8181',
          brightRed: '#feb2b2',
          green: '#68d391',
          brightGreen: '#9ae6b4',
          yellow: '#f6e05e',
          brightYellow: '#faf089',
          blue: '#63b3ed',
          brightBlue: '#90cdf4',
          magenta: '#b794f4',
          brightMagenta: '#d6bcfa',
          cyan: '#76e4f7',
          brightCyan: '#b2f5ea',
          white: '#e2e8f0',
          brightWhite: '#ffffff',
        },
        allowTransparency: true,
        scrollback: 2000,
        convertEol: false,
      })

      fitAddon = new FitAddon()
      term.loadAddon(fitAddon)
      term.open(container)
      fitAddon.fit()

      termRef.current = term
      fitAddonRef.current = fitAddon

      term.writeln('\x1b[2m\u250C\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510\x1b[0m')
      // Convert hex glowColor to RGB for ANSI
      const hexToRgb = (hex: string) => ({
        r: parseInt(hex.slice(1, 3), 16),
        g: parseInt(hex.slice(3, 5), 16),
        b: parseInt(hex.slice(5, 7), 16),
      })
      const { r, g, b } = hexToRgb(glowColor)
      term.writeln(`\x1b[2m\u2502\x1b[0m  \x1b[1m\x1b[38;2;${r};${g};${b}mIRIS Developer Terminal\x1b[0m                \x1b[2m\u2502\x1b[0m`)
      term.writeln('\x1b[2m\u2502  Direct shell access \u2022 Security filtered  \u2502\x1b[0m')
      term.writeln('\x1b[2m\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518\x1b[0m')
      term.writeln('')
      term.write('$ ')

      // Input handler — direct shell via terminal_input
      term.onData((data: string) => {
        if (data === '\r') {
          const line = lineBufferRef.current
          lineBufferRef.current = ''
          term.write('\r\n')
          if (line.trim()) {
            sendRef.current('terminal_input', { line })
          } else {
            term.write('$ ')
          }
        } else if (data === '\x7f' || data === '\b') {
          if (lineBufferRef.current.length > 0) {
            lineBufferRef.current = lineBufferRef.current.slice(0, -1)
            term.write('\b \b')
          }
        } else if (data === '\x03') {
          lineBufferRef.current = ''
          term.write('^C\r\n')
          sendRef.current('dev_abort', {})
          term.write('$ ')
        } else if (data >= ' ') {
          lineBufferRef.current += data
          term.write(data)
        }
      })

      resizeObserver = new ResizeObserver(() => {
        try { fitAddon.fit() } catch { /* ignore */ }
      })
      resizeObserver.observe(container)

      setMounted(true)
    }).catch((err) => {
      console.error('[TerminalWidget] failed to load xterm:', err)
    })

    // Backend output listeners
    const onOutput = (e: Event) => {
      const detail = (e as CustomEvent).detail as { line?: string }
      if (detail?.line !== undefined && termRef.current) {
        termRef.current.write(detail.line.replace(/\r?\n/g, '\r\n'))
      }
    }
    const onStarted = (e: Event) => {
      const detail = (e as CustomEvent).detail as { tool_name?: string }
      if (termRef.current && detail?.tool_name) {
        termRef.current.write(`\x1b[2m[${detail.tool_name} started]\x1b[0m\r\n`)
      }
    }
    const onActivity = (e: Event) => {
      const detail = (e as CustomEvent).detail as { tool_name?: string; workdir?: string }
      if (termRef.current && detail?.tool_name) {
        termRef.current.write(`\x1b[36m[tool: ${detail.tool_name}]\x1b[0m\r\n`)
      }
      if (detail?.workdir) setWorkdir(detail.workdir)
    }
    const onTextResponse = (e: Event) => {
      const detail = (e as CustomEvent).detail as { text?: string }
      if (termRef.current && detail?.text) {
        const text = detail.text.replace(/\r?\n/g, '\r\n')
        termRef.current.write(text + '\r\n$ ')
      }
    }

    window.addEventListener('iris:cli_output', onOutput)
    window.addEventListener('iris:cli_started', onStarted)
    window.addEventListener('iris:cli_activity', onActivity)
    window.addEventListener('iris:text_response', onTextResponse)

    return () => {
      disposed = true
      window.removeEventListener('iris:cli_output', onOutput)
      window.removeEventListener('iris:cli_started', onStarted)
      window.removeEventListener('iris:cli_activity', onActivity)
      window.removeEventListener('iris:text_response', onTextResponse)
      resizeObserver?.disconnect()
      term?.dispose()
      termRef.current = null
      fitAddonRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleClear = useCallback(() => {
    if (termRef.current) {
      termRef.current.clear()
      termRef.current.write('$ ')
    }
  }, [])

  return (
    <div
      ref={containerRef}
      className="w-full h-full flex flex-col"
      style={{
        minHeight: 0,
        padding: '12px 16px',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.015) 0%, transparent 50%, rgba(0,0,0,0.15) 100%)',
      }}
    />
  )
}

export default TerminalWidget
