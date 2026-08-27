'use client'

/**
 * useDetachedWing — the two halves of a wing living in its own window.
 *
 * A wing can be popped out of the widget onto another monitor. That makes two
 * kinds of window, and this file serves both:
 *
 *   THE WIDGET    calls `detachWing('chat')`, then closes that wing inline so
 *                 it is not drawn twice, and listens for `wing:reattach` to
 *                 put it back when the detached window is closed.
 *   THE WING      reads `?pane=` and renders that wing alone, filling its
 *                 window.
 *
 * Both windows are the SAME frontend in the SAME process. That is what makes
 * this cheap: ws_client.rs emits on the AppHandle, which reaches every window,
 * and start_ws_client is idempotent, so the detached wing rides the one
 * backend socket rather than opening a second one. A second socket would be
 * evicted by the backend's one-per-client rule and cancel in-flight agent work
 * (pin_a414a1cc8e87).
 */

import { useEffect, useState } from 'react'

export type PaneName = 'chat' | 'dashboard'

function isPane(value: string | null): value is PaneName {
  return value === 'chat' || value === 'dashboard'
}

/**
 * Which wing THIS window is, or null when it is the widget.
 *
 * The answer comes from the Tauri WINDOW LABEL — `wing-chat` or
 * `wing-dashboard` — not from the URL. Both windows load the identical app
 * root, so nothing has to be encoded into a path.
 *
 * The pane used to ride in the URL as `?pane=`, which works in dev and breaks
 * in a package: WebviewUrl::App takes a PathBuf, so `index.html?pane=chat` is
 * read as a filename by the asset resolver. `?pane=` is still honoured as a
 * fallback so the detached layouts can be opened in a plain browser during
 * development, where there is no Tauri label to read.
 *
 * Resolved in an effect, so the first client render always returns null:
 * `window` does not exist during prerender and a mismatch would hydrate wrong.
 */
export function useDetachedPane(): PaneName | null {
  const [pane, setPane] = useState<PaneName | null>(null)

  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window')
        const label = getCurrentWindow().label
        if (label.startsWith('wing-')) {
          const value = label.slice('wing-'.length)
          if (isPane(value)) {
            if (!cancelled) setPane(value)
            return
          }
        }
        // A Tauri window that is not a wing — the widget, or the launcher.
        return
      } catch {
        /* not Tauri — fall through to the browser-development path */
      }

      try {
        const value = new URLSearchParams(window.location.search).get('pane')
        if (isPane(value) && !cancelled) setPane(value)
      } catch {
        /* no search params — this is the widget */
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  return pane
}

/** Pop a wing into its own window. Safe to call outside Tauri; it does nothing. */
export async function detachWing(pane: PaneName): Promise<boolean> {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('detach_wing', { pane })
    return true
  } catch (e) {
    console.warn('[wings] detach_wing failed:', e)
    return false
  }
}

/** Close this detached wing, which reattaches it to the widget. */
export async function reattachWing(pane: PaneName): Promise<void> {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('reattach_wing', { pane })
  } catch (e) {
    console.warn('[wings] reattach_wing failed:', e)
  }
}

/**
 * Run `onReattach` in the WIDGET when a detached wing's window is closed.
 *
 * Rust emits `wing:reattach` from the window's CloseRequested handler, so the
 * widget can re-open the wing inline. Without it a closed wing would just
 * disappear with no way back.
 */
export function useWingReattachListener(onReattach: (pane: PaneName) => void): void {
  useEffect(() => {
    let dispose: (() => void) | undefined
    let cancelled = false

    void (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event')
        const unlisten = await listen<string>('wing:reattach', (event) => {
          if (isPane(event.payload)) onReattach(event.payload)
        })
        // The await above can resolve after unmount; drop it immediately
        // rather than leaving a listener bound to a dead callback.
        if (cancelled) unlisten()
        else dispose = unlisten
      } catch {
        /* not running under Tauri — nothing can detach, so nothing reattaches */
      }
    })()

    return () => {
      cancelled = true
      dispose?.()
    }
  }, [onReattach])
}
