/**
 * apiOrigin — where `/api/...` actually lives, per surface.
 *
 * WHY THIS EXISTS
 * next.config.mjs rewrites `/api/:path*` to the backend on :8090, so every
 * call site could use a same-origin relative path and never think about it.
 * A STATIC EXPORT has no rewrite layer — there is no Next.js server in the
 * packaged widget at all — so in a bundle those relative paths resolve against
 * `http://tauri.localhost` and 404.
 *
 * Rather than rewrite 31 call sites across 15 files (and rely on everyone
 * remembering forever), this reinstates the rewrite on the CLIENT, which is
 * the one place that still runs in a packaged build. `installApiOriginBridge`
 * is the whole mechanism; `apiUrl` is for the few callers that are not `fetch`
 * and therefore cannot be intercepted.
 *
 * WHICH SURFACE GETS WHICH ORIGIN
 *   Tauri (dev or packaged) — absolute http://localhost:8090. In dev this is
 *     the same destination the rewrite proxies to, so the two agree; in a
 *     package it is the only thing that works.
 *   Everything else (browser dev, and phones reaching the dev server over
 *     Tailscale) — relative. A phone MUST NOT be told to call `localhost`,
 *     which on that device is the phone itself.
 */

const BACKEND_PORT = process.env.NEXT_PUBLIC_IRIS_BACKEND_PORT || '8090'

/** True only inside a Tauri webview. Mirrors hooks/useDeepLink's isTauri. */
function inTauri(): boolean {
  if (typeof window === 'undefined') return false
  const w = window as unknown as Record<string, unknown>
  return '__TAURI__' in w || '__TAURI_INTERNALS__' in w
}

/**
 * Origin to prefix onto an `/api/...` path. Empty string means "stay relative",
 * which is the correct answer everywhere a Next.js server is serving the page.
 */
export function apiOrigin(): string {
  return inTauri() ? `http://localhost:${BACKEND_PORT}` : ''
}

/**
 * Resolve one `/api/...` path.
 *
 * Use this for the transports the bridge cannot intercept — EventSource, an
 * `<img src>`, anything that is not `fetch`. Plain `fetch('/api/...')` needs
 * no change: the bridge handles it.
 */
export function apiUrl(path: string): string {
  if (!path.startsWith('/api/')) return path
  return apiOrigin() + path
}

let installed = false

/**
 * Point relative `/api/...` fetches at the backend when there is no Next.js
 * server to proxy them.
 *
 * Idempotent, and a no-op outside Tauri — in a browser the rewrite still
 * exists and the original fetch is left completely untouched, so nothing about
 * the dev path or the Tailscale path changes.
 *
 * Only same-origin, root-relative `/api/` paths are touched. An absolute URL a
 * caller wrote deliberately is passed straight through.
 */
export function installApiOriginBridge(): void {
  if (installed) return
  if (typeof window === 'undefined') return
  const origin = apiOrigin()
  if (!origin) return

  installed = true
  const original = window.fetch.bind(window)

  window.fetch = function patchedFetch(
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> {
    try {
      if (typeof input === 'string' && input.startsWith('/api/')) {
        return original(origin + input, init)
      }
      if (input instanceof URL && input.pathname.startsWith('/api/') && input.origin === window.location.origin) {
        return original(origin + input.pathname + input.search, init)
      }
      if (input instanceof Request && new URL(input.url).pathname.startsWith('/api/')) {
        const parsed = new URL(input.url)
        if (parsed.origin === window.location.origin) {
          // A Request carries method, headers, body and mode. Rebuilding it
          // from the original preserves all of them; only the URL changes.
          return original(new Request(origin + parsed.pathname + parsed.search, input), init)
        }
      }
    } catch {
      // A malformed input is the caller's problem, not ours — hand it to the
      // real fetch and let it produce the real error.
    }
    return original(input, init)
  }
}
