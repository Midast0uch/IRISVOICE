'use client'

import { useState, useEffect } from 'react'

export function useTailscaleAccess() {
  const [isTailscaleAccess, setIsTailscaleAccess] = useState(false)

  useEffect(() => {
    // Check if we're on a Tailscale IP range (100.64.0.0/10)
    const hostname = window.location.hostname
    const isTailscale = hostname.startsWith('100.') || hostname.endsWith('.ts.net')
    setIsTailscaleAccess(isTailscale)
  }, [])

  return isTailscaleAccess
}
