'use client'

import { installApiOriginBridge } from '@/lib/apiOrigin'

/**
 * Installs the `/api` origin bridge at MODULE scope, not in an effect.
 *
 * Timing is the whole point. A packaged build has no Next.js rewrite, so any
 * `fetch('/api/...')` that runs before the bridge is installed goes to
 * `http://tauri.localhost/api/...` and 404s. Module bodies evaluate when the
 * chunk loads — before any component renders and long before any effect fires
 * — so importing this first in app/layout.tsx guarantees the bridge is in
 * place ahead of the first request. An effect in a parent component would be
 * too late: React runs child effects first.
 *
 * Outside Tauri this is a no-op and the real fetch is never replaced.
 */
installApiOriginBridge()

export function ApiOriginBridge() {
  return null
}

export default ApiOriginBridge
