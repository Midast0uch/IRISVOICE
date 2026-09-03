"use client"

/**
 * useActiveFrameSrc — REQ-1 AC2 / REQ-2 AC1 (T5) frame routing.
 *
 * Decides what the content iframe renders for the ACTIVE tab:
 *   - an agent-navigated web tab WITH capture provenance replays the captured
 *     bytes: /api/browser/capture/{job_id}/{page_number} (REQ-1 AC2 — never a
 *     second live fetch of the source URL);
 *   - a web tab WITHOUT provenance goes through the PROXY, never straight at
 *     the source URL (see below);
 *   - no active tab / user-typed URL renders through the fetch proxy
 *     (REQ-2 AC1);
 *   - non-web tabs (html/code/dashboard) return undefined — they render via
 *     srcDoc/other mechanisms, never the proxy.
 *
 * TWO THINGS THIS DELIBERATELY DOES NOT DO:
 *
 * 1. It never returns a bare `active.url`. An earlier revision did, as a
 *    "fallback so the overlay shows coarse crawl state" — but pointing the
 *    frame at the live site is exactly the pre-feature behaviour that
 *    X-Frame-Options refuses, so the panel showed "refused to connect". It is
 *    also the silent live fetch REQ-1 AC3 forbids: a missing capture must be
 *    VISIBLE as missing, not quietly replaced by a different set of bytes.
 *    A web tab with a URL but no capture is a live view -> proxy path.
 *
 * 2. It no longer requires `!active` to use the proxy. The user typing a URL
 *    while any tab was open previously fell through to that bare-URL branch,
 *    so the address bar only worked with zero tabs open.
 */

import { useEffect, useMemo, useState } from "react"
import type { Tab } from "@/types/iris"

const proxied = (url: string) => `/api/browser/proxy?url=${encodeURIComponent(url)}`

/**
 * Obtain the browser-surface session cookie before any frame loads.
 *
 * The content endpoints require a token (backend/api/browser_auth.py) and an
 * <iframe src> cannot carry a header, so the token lives in an HttpOnly
 * cookie. This POSTs once to mint it. Frames must not be rendered until it
 * resolves, or the first load races the cookie and 404s.
 *
 * The token itself is never visible here — HttpOnly means page script cannot
 * read it, which is the point.
 */
export function useBrowserSurfaceSession(): boolean {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let cancelled = false
    fetch("/api/browser/session", { method: "POST", credentials: "same-origin" })
      .catch(() => undefined)
      // Ready either way: a failure means the frames will show the endpoint's
      // own refusal, which is more honest than rendering nothing forever.
      .finally(() => { if (!cancelled) setReady(true) })
    return () => { cancelled = true }
  }, [])
  return ready
}

export function useActiveFrameSrc(args: {
  tabs: Tab[]
  activeTabId: string | null
  browserUrl: string
}): string | undefined {
  const { tabs, activeTabId, browserUrl } = args
  return useMemo(() => {
    const active = tabs.find(t => t.id === activeTabId)
    if (!active) return proxied(browserUrl)
    if (active.type !== "web") {
      // Non-web tabs (html/code/dashboard) render via srcDoc/other mechanisms.
      return undefined
    }
    if (active.captureJobId && active.capturePageNumber != null) {
      return `/api/browser/capture/${active.captureJobId}/${active.capturePageNumber}`
    }
    if (active.url) return proxied(active.url)
    return proxied(browserUrl)
  }, [tabs, activeTabId, browserUrl])
}
