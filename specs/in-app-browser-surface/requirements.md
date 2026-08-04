# Requirements: In-App Browser Surface

## Decisions Locked

- **The in-app browser is a MODULE attached at the DER seam, not a change to DER.** It extends `specs/long-horizon-der-execution` REQ-16/REQ-17/REQ-18. If serving a URL requires modifying the DER step loop, the seam is wrong.
- **Two paths, not one.** Agent-initiated navigation SHALL replay content the crawler already fetched. User-typed URLs SHALL go through a fetch proxy. These are different trust and provenance situations and SHALL NOT be collapsed into a single mechanism.
- **A proxied page SHALL NEVER be same-origin with the application.** Serving foreign HTML from the app's own origin would give crawled content access to app cookies, `localStorage`, and same-origin `fetch` against the app's API — precisely the capability `specs/long-horizon-der-execution` REQ-22 denies it. The trust model (`backend/memory/mycelium/kyudo.py` `CellWall` `ZONE_PERMEABILITY`) classifies external content `UNTRUSTED`/`REFERENCE_ZONE`; the rendering layer SHALL NOT hand it a channel the memory layer refuses it.
- **Visible scroll and scrape SHALL be achieved without granting the parent frame DOM access to page content.** The parent SHALL NOT reach into the frame. A narrow, one-way-out `postMessage` protocol carries coarse view state; the frame stays sandboxed without `allow-same-origin`.
- **The proxy is an SSRF surface and SHALL be treated as one.** It is a server-side fetcher whose target is caller-supplied. Address-level egress rules are a requirement of this feature, not a hardening pass afterwards.
- **What the user sees SHALL be what the agent read.** For agent-initiated navigation the displayed bytes SHALL come from the same capture the agent reasoned over, not a second live fetch that may differ.
- **`webbrowser.open` remains removed.** `specs/long-horizon-der-execution` REQ-16 AC1/AC2 already eliminated OS-browser escapes; nothing in this feature reintroduces one. The user-initiated "open externally" control (`dark-glass-dashboard.tsx`) is a display affordance, not agent navigation, and is out of scope.
- **The existing navigation overlay is the presentation layer for this feature** and SHALL NOT be redesigned here. Its contract is `hooks/useBrowserNavOverlay.ts` + `components/iris/browser/BrowserNavigationOverlay.tsx`, driven by `iris:open_tab` / `iris:crawler_*`, tracing on `iris:nav_overlay_state`.
- **Replay transport: sandboxed HTTP endpoint (T1/T2 — decided from measured capture sizes).** Measured 2026-08-04 via `scripts/measure_capture_sizes.py` across 5 jobs / 15 pages / mixed sites (example.com, Wikipedia, python.org, MDN, BBC, NYT, GitHub, rust-lang): min 559 B, median 330,855 B, p95 1,169,976 B, max 1,219,705 B, mean 385,313 B. Both replayed captures (REQ-1) and proxied pages (REQ-2) are served from the same sandboxed HTTP endpoint. Rationale: (a) p95 already approaches ~1.2 MB — srcdoc carries no hard limit but near-1–2 MB content risks browser re-serialization cost and attribute-escaping overhead for zero benefit; (b) one serving mechanism means one CSP policy (REQ-3 AC4), one `<base>`-anchoring path, and one provenance-attachment point for both content paths; (c) relative-URL resolution is cleaner against a real URL than against a `srcdoc` blob. Consequence: REQ-3 AC4's CSP requirement is LIVE and covered by T7.
- **REQ-1 capture retention bound (T1/T2 — decided from measured capture sizes): 100 pages AND 256 MB total, oldest-first eviction.** At the measured p95 (~1.17 MB/page), 100 pages ≈ 117 MB worst-case — comfortably inside the byte bound; at the median (~330 KB), 100 pages ≈ 33 MB. Eviction is async and best-effort and SHALL NOT fail an in-flight task (REQ-1 AC5).

## Introduction

The in-app browser panel currently points an `<iframe>` directly at the target URL
(`components/dark-glass-dashboard.tsx:1421`). Most real sites refuse to render this way —
`X-Frame-Options: SAMEORIGIN` or `Content-Security-Policy: frame-ancestors` — so the panel
shows "refused to connect" for the default `https://www.google.com` and for nearly every
site the agent would want. There is no proxy anywhere in the backend.

The consequence is not only cosmetic. Because the frame is cross-origin, the frontend cannot
observe it at all, which is why the navigation overlay has to degrade to coarse state and why
"watch the agent scroll and scrape a page" is currently impossible.

This feature makes the panel a real surface for agent work: the agent navigates in-app, the
page is actually displayed, and its reading of the page is visible — while keeping foreign
content inside the trust boundary the memory layer already enforces.

### Success criteria

- A user typing `https://www.google.com` into the address bar sees the page render in-app.
- An agent crawl displays the pages it fetched, in order, in the panel — the same bytes it reasoned over.
- The page visibly scrolls as the agent reads it, and the region being extracted is indicated.
- No proxied page can read the application's cookies, storage, or API responses.
- The proxy refuses private, loopback, and link-local targets, and cannot be used to reach the host's own services.
- With the proxy disabled or unreachable, agent task completion is unaffected (the module is optional; DER still completes).

## Requirements

### REQ-1 — Agent navigation replays captured content

**User Story:** As a user watching the agent work, I want the panel to show the page the agent actually read, so that what I see is evidence rather than a second opinion.

**Acceptance Criteria (EARS):**
- AC1: WHEN the agent completes a page fetch during a crawl, THE SYSTEM SHALL make that page's captured HTML available to the browser panel keyed by `job_id` and `page_number`.
- AC2: THE SYSTEM SHALL render agent-navigated pages from the capture, NOT by issuing a second network request for the same URL.
- AC3: WHERE a capture is unavailable for a page the agent reports fetching, THE SYSTEM SHALL display an explicit "capture unavailable" state and SHALL NOT silently fall back to a live fetch.
- AC4: THE displayed capture SHALL carry its provenance (source URL, fetch timestamp, `job_id`) in the panel chrome.
- AC5: THE SYSTEM SHALL bound capture retention (count and total bytes) and SHALL evict oldest-first; eviction SHALL NOT fail an in-flight task.

**Edge Cases:** A crawl that fetches the same URL twice in one job (later capture wins, both retained until eviction); a capture larger than the retention byte bound (stored truncated with an explicit truncation marker rather than dropped); a page fetched before the panel was ever opened (capture still available when the panel opens later, subject to eviction).

### REQ-2 — User-typed URLs are served through a fetch proxy

**User Story:** As a user, I want to type any URL into the in-app address bar and see it, so that the panel is a usable browser and not a broken box.

**Acceptance Criteria (EARS):**
- AC1: WHEN the user submits a URL in the in-app address bar, THE SYSTEM SHALL retrieve it server-side and serve the response to the panel.
- AC2: THE SYSTEM SHALL remove `X-Frame-Options` and any `frame-ancestors` directive from the served response so the panel can render it.
- AC3: THE SYSTEM SHALL rewrite or `<base>`-anchor relative references so stylesheets and images resolve.
- AC4: IF the upstream fetch fails, times out, or returns a non-HTML content type, THEN THE SYSTEM SHALL surface the specific failure (status, reason) in the panel rather than a blank frame.
- AC5: THE proxy SHALL be subject to the same app-wide internet capability gate as `crawler_query`/`search`/`open_url` (`tool_registry.capability_denied_by`); WHEN web mode is off, THE SYSTEM SHALL refuse the fetch and say which gate closed it.

**Edge Cases:** A URL that redirects across origins (redirect chain followed to a bounded depth, final origin reported); a response with `Content-Encoding` the proxy must decode before rewriting; a site that hard-requires cookies or login (renders logged-out; this is expected and SHALL be stated, not worked around).

### REQ-3 — Proxied content is never same-origin with the application

**User Story:** As the person whose machine this runs on, I want foreign HTML to be unable to touch my session, so that rendering a page can never become a breach.

**Acceptance Criteria (EARS):**
- AC1: THE SYSTEM SHALL render proxied and replayed content in an iframe whose `sandbox` attribute does NOT include `allow-same-origin`.
- AC2: THE SYSTEM SHALL NOT include `allow-top-navigation` in that sandbox.
- AC3: THE parent document SHALL NOT attempt to access `contentDocument` or `contentWindow` members of the content frame beyond `postMessage`.
- AC4: WHERE served from an HTTP endpoint rather than `srcdoc`, THE response SHALL carry a `Content-Security-Policy` that denies the frame access to the application's origin, and SHALL NOT set permissive CORS headers toward it.
- AC5: THE SYSTEM SHALL NOT forward application cookies, `Authorization` headers, or any user credential to the upstream target.

**Edge Cases:** A page that frame-busts via `top.location` (blocked by AC2, and SHALL fail silently rather than navigating the app); a page that opens popups (denied unless explicitly enabled); a page attempting `postMessage` to the parent with a payload shaped like the view protocol (rejected by REQ-4 AC4 validation).

### REQ-4 — Visible scroll and extraction without DOM reach-in

**User Story:** As a user, I want to watch the agent move through the page and see what it is taking, so that the crawl is legible rather than a spinner.

**Acceptance Criteria (EARS):**
- AC1: THE SYSTEM SHALL inject a view-agent script into served content that reports scroll offset, document height, and viewport height to the parent via `postMessage`.
- AC2: THE SYSTEM SHALL accept a bounded command set from the parent (`scrollTo`, `highlight`) over the same channel and SHALL ignore anything else.
- AC3: WHEN the agent extracts a region of a page, THE SYSTEM SHALL indicate that region in the frame and SHALL scroll it into view.
- AC4: THE parent SHALL validate every inbound message's `origin` and shape before acting on it, and SHALL drop messages that do not match the protocol.
- AC5: IF the view-agent script fails to load or the page blocks it, THEN THE SYSTEM SHALL degrade to the coarse overlay state already defined by `specs/long-horizon-der-execution` REQ-16 AC6–AC9 and SHALL NOT throw.

**Edge Cases:** A page that removes injected script tags on load (degrades per AC5); a page taller than the browser's maximum scroll height; a page whose own scroll container is not the document (view-agent reports the document and marks the reading as approximate).

### REQ-5 — Egress control on the proxy

**User Story:** As the operator, I want the proxy unable to reach my internal network, so that a crafted URL cannot turn my own machine into the attacker's probe.

**Acceptance Criteria (EARS):**
- AC1: THE SYSTEM SHALL resolve the target host and SHALL refuse loopback, private, link-local, unique-local, and multicast addresses.
- AC2: THE SYSTEM SHALL re-check the resolved address after every redirect hop, not only on the initial URL.
- AC3: THE SYSTEM SHALL accept only `http` and `https` schemes and SHALL refuse all others including `file`, `ftp`, `data`, and `gopher`.
- AC4: THE SYSTEM SHALL bound response size, total time, and redirect depth, and SHALL abort cleanly when any bound is exceeded.
- AC5: WHEN a fetch is refused by any rule in this requirement, THE SYSTEM SHALL log the refusal with the target and the specific rule, and SHALL surface a non-specific failure to the page.

**Edge Cases:** A hostname that resolves to a public address on first lookup and a private one on the second (AC2 re-check is the defense; the fetch SHALL use the checked address); a target behind a redirect chain ending at `127.0.0.1`; an IPv6-mapped IPv4 private address.

### REQ-6 — The module is optional

**User Story:** As the maintainer, I want the browser surface to be removable without touching DER, so that the seam claim in the long-horizon spec stays true.

**Acceptance Criteria (EARS):**
- AC1: WHERE the proxy endpoint is disabled or unreachable, THE SYSTEM SHALL still complete crawl tasks end to end, per `specs/long-horizon-der-execution` REQ-10/REQ-12.
- AC2: THE DER step-execution loop SHALL gain NO per-tool branch for this feature; routing SHALL remain the generic `execute_tool(tool_name=item.tool, ...)` dispatch pinned by REQ-17 AC1/AC4.
- AC3: THE SYSTEM SHALL record navigation to the REQ-18 trace with `surface="in-app"` for both paths in this feature, distinguishing `replay` from `proxy`.
- AC4: Removing this feature's frontend components SHALL NOT change any DER or crawler test outcome.

**Edge Cases:** The panel open while the proxy is disabled mid-session (existing frames keep their content; new navigations report the gate).

## Non-Requirements

- Implementing a full browser engine, a JavaScript-executing renderer, or a headless-Chromium display path. Proxied pages render as the app's own webview renders them; script-heavy sites may render incompletely, and that is accepted.
- Carrying user login sessions or cookies into proxied pages. Pages render logged-out.
- Replacing Crawl4AI or the existing crawler (restated from `specs/long-horizon-der-execution`).
- Redesigning `BrowserNavigationOverlay` or its state machine.
- Reintroducing any OS-browser launch path.
- Content scanning or active malware inspection of proxied HTML. Provenance-based trust remains the gate, consistent with `specs/long-horizon-der-execution` REQ-22's locked decision.
- Tauri-native response-header interception. It would solve REQ-2 for the desktop build only and not for the dev/browser flow; it remains a possible later optimization, not a requirement here.

## Open Questions

- ~~Should replayed captures (REQ-1) be served via `srcdoc` or from the same sandboxed HTTP endpoint as the proxy?~~ **RESOLVED (T2): sandboxed HTTP endpoint**, chosen from measured capture sizes (median ~330 KB, p95 ~1.2 MB) — see Decisions Locked. `srcdoc` would add a second serving mechanism, attribute-escaping cost, and a second CSP surface for zero benefit.
- Should the proxy reuse the crawler's existing fetch stack (sharing its timeout, user-agent, and HAR capture) or be an independent client? Reuse gives provenance and HAR for free; independence avoids coupling a user-facing latency path to crawl scheduling.
- ~~What is the retention bound for REQ-1 captures — count, bytes, or task lifetime?~~ **RESOLVED (T2): 100 pages AND 256 MB total, oldest-first** — set from measured capture sizes (see Decisions Locked).
- Should the view-agent (REQ-4) report extracted-region coordinates from the backend's extraction step, or should the frontend re-derive them from the extracted text? Backend-reported is authoritative but requires the extractor to emit offsets it does not emit today.
- Does the in-app address bar need history/back-forward semantics, or is single-page navigation sufficient for the agent-browser use case? The current back button calls `window.history.back()` on the APP (`dark-glass-dashboard.tsx:1395`), which is a pre-existing bug regardless of this feature's outcome.
