'use client'

import { useState, useEffect } from 'react'

export function useIsMobile(breakpoint: number = 768) {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    // A Tauri window is a DESKTOP widget whatever its size. The widget's own
    // configured size is 680x680 (src-tauri/tauri.conf.json), which is BELOW
    // this 768 breakpoint -- so every Tauri launch reported isMobile === true,
    // app/page.tsx took its `if (isMobile || ...)` branch, and that branch
    // renders a simplified full-screen chat and NEVER renders XurOrb. The orb
    // was not too big for the window; the window was too narrow to be
    // recognised as a desktop.
    //
    // The check is inlined rather than imported from hooks/useDeepLink.ts
    // (which exports the canonical isTauri()) because that module imports
    // '@tauri-apps/api/event' at module scope, and pulling it in here would
    // load the Tauri event API into every page that merely asks about width.
    // Keep the two in step if either changes.
    const inTauri =
      typeof window !== 'undefined' &&
      (typeof (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ !== 'undefined' ||
        typeof (window as unknown as Record<string, unknown>).__TAURI__ !== 'undefined')
    if (inTauri) {
      setIsMobile(false)
      return
    }

    const check = () => setIsMobile(window.innerWidth < breakpoint)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [breakpoint])

  return isMobile
}
