# Tasks: In-App Browser Surface

Waves are ordered by what unblocks measurement, then by what unblocks the rest.
Wave 1 exists because two Open Questions in `requirements.md` are answerable only with data,
and guessing them would bake a wrong bound into everything after.

Every task states the REQ it serves and its RIPPLE. Red-flip is required: a test that cannot
be shown to fail is not evidence.

---

## Wave 1 — Measure before choosing (unblocks two Open Questions)

**T1 — Measure real capture sizes**
Instrument the existing crawler to record captured-HTML byte size per page across a
representative crawl set (≥5 jobs, mixed sites). Report min/median/p95/max.
*Serves:* REQ-1 AC5 retention bound; the `srcdoc` vs HTTP-endpoint Open Question.
*RIPPLE:* Sizes above ~1–2 MB make `srcdoc` impractical and settle that question by evidence.
*Done when:* numbers exist in the spec, not an assumption.

**T2 — Decide replay transport and record it**
Using T1's data, choose `srcdoc` or the sandboxed HTTP endpoint. Write the decision and its
measured basis into `requirements.md` Decisions Locked.
*Serves:* REQ-1 Open Question. *Blocks:* T5.
*RIPPLE:* If HTTP, REQ-3 AC4's CSP requirement becomes live and T7 must cover it.

---

## Wave 2 — Egress guard (must exist before any fetch does)

**T3 — Implement the egress guard**
Scheme allowlist (`http`/`https` only), host resolution, address-class rejection (loopback,
private, link-local, unique-local, multicast, IPv6-mapped equivalents), size/time/redirect-depth
bounds. The guard returns the **checked address**, and the fetch uses it.
*Serves:* REQ-5 AC1/AC3/AC4.
*RIPPLE:* Any future server-side fetcher should route through this, not reimplement it.

**T4 — Per-hop re-check**
Apply the guard on every redirect hop, not the initial URL only.
*Serves:* REQ-5 AC2.
*RIPPLE:* Requires manual redirect handling; the HTTP client must not auto-follow.

**T4a — Adversarial guard tests**
One test per refusal class, plus a redirect chain terminating at loopback and an IPv6-mapped
private address. Prove each can fail (remove the rule ⇒ test goes red).
*Serves:* REQ-5 AC1–AC5.
*RIPPLE:* This is the feature's primary security evidence — it carries the most weight of any
test here, and a guard whose test cannot fail is indistinguishable from no guard.

---

## Wave 3 — The two content paths

**T5 — Capture replay store + endpoint**
Persist crawler captures keyed by `job_id`+`page_number` with provenance (URL, timestamp).
Bounded retention, oldest-first eviction that cannot fail an in-flight task. Serve per T2.
*Serves:* REQ-1 AC1/AC2/AC4/AC5.
*RIPPLE:* Touches crawler capture write path — must stay off the crawl hot path (async write,
failure to store never fails the fetch).

**T6 — Fetch proxy**
Server-side fetch through T3's guard; strip `X-Frame-Options` and `frame-ancestors`; `<base>`
anchor or rewrite relative refs; decode `Content-Encoding` before rewriting; forward NO cookies,
NO `Authorization`, no user credential. Specific failures surfaced (REQ-2 AC4).
*Serves:* REQ-2 AC1–AC4, REQ-3 AC5.
*RIPPLE:* Response rewriting must not corrupt non-HTML bodies — content-type check first.

**T7 — Gate + isolation headers**
Wire the proxy to the app-wide internet capability gate via `capability_denied_by` so it
refuses exactly like `crawler_query`/`search`/`open_url` and names the true blocker. If served
over HTTP, attach the REQ-3 AC4 CSP and ensure no permissive CORS toward the app origin.
*Serves:* REQ-2 AC5, REQ-3 AC4.
*RIPPLE:* Reuses the `capability_denied_by` fix from `specs/long-horizon-der-execution` T29 —
do not add a second gate mechanism.

---

## Wave 4 — Frontend surface

**T8 — Sandbox the content frame**
Set `sandbox` without `allow-same-origin` and without `allow-top-navigation` on the web-content
frame. Leave the agent-authored `srcDoc` HTML-tab branch (`dark-glass-dashboard.tsx:1381`)
working — it is app-authored, not foreign.
*Serves:* REQ-3 AC1/AC2/AC3.
*RIPPLE:* This is what removes the parent's ability to observe the frame; T9 must land with it
or the overlay loses the little visibility it has.

**T9 — View-agent + protocol**
Inject the view-agent into served content. Implement the parent side with **both** checks:
`event.source === iframe.contentWindow` AND shape/version match. Sandboxed frames post with
`origin === "null"`, so origin alone is not authentication.
*Serves:* REQ-4 AC1/AC2/AC4.
*RIPPLE:* Highest-risk task in the feature — a loose validator here reintroduces exactly the
capability T8 removed.

**T10 — Extraction indication**
Indicate the region the agent extracted and scroll it into view.
*Serves:* REQ-4 AC3.
*RIPPLE:* Depends on the extractor emitting offsets it does not emit today (Open Question) —
if it does not, mark the reading approximate rather than fabricating coordinates.

**T11 — Degradation path**
Page strips the script / blocks injection ⇒ fall back to the existing coarse overlay states.
Never throw.
*Serves:* REQ-4 AC5.
*RIPPLE:* Reuses `BrowserNavigationOverlay` unchanged.

**T12 — Fix the in-app back button**
`dark-glass-dashboard.tsx:1395` checks `iframeRef.current?.contentWindow` and then calls
`window.history.back()` — navigating the **application**, not the page. Pre-existing defect,
independent of this feature, made more visible by it.
*Serves:* REQ-2 usability; not a new requirement, a bug fix.
*RIPPLE:* With a sandboxed cross-origin frame, in-frame history is not reachable from the
parent; back must be driven through the view protocol or the control removed rather than
left lying.

---

## Wave 5 — Seam and trace

**T13 — Trace both paths**
Record navigation to the REQ-18 trace with `surface="in-app"` and a `replay`/`proxy`
discriminator.
*Serves:* REQ-6 AC3.
*RIPPLE:* Extend the existing REQ-18 contract test; do not replace it. Respect `der_trace.py`'s
bounded-entry accounting.

**T14 — Prove the module is optional**
Behavioral test: proxy disabled/unreachable ⇒ crawl task still completes end to end. Source
inspection: DER step loop still has zero per-tool branches.
*Serves:* REQ-6 AC1/AC2/AC4.
*RIPPLE:* This is the task that keeps the long-horizon spec's seam claim honest. If it fails,
the seam is wrong and the fix belongs in the seam, not here.

---

## Wave 6 — Acceptance

**T15 — Top-level acceptance gate**
One drive asserting all six success criteria from `requirements.md`: a typed URL renders; an
agent crawl shows captured bytes in order; the frame scrolls as pages are read; no proxied page
reaches app cookies/storage/API; the guard refuses private/loopback/link-local; and the crawl
completes with the proxy off.
*Serves:* all REQs.
*RIPPLE:* Must pass before this feature is claimed done, and must be shown failable — remove
the sandbox attribute and the isolation assertion goes red.

---

## Notes for the executor

- Read all three spec files before starting. Reconcile REQ ids against `design.md`'s
  Ripple-Effect Map; if they disagree, that is a finding to report, not a conflict to
  engineer around.
- Wave 1 is not optional. Two bounds in this spec are deliberately unset because they should
  come from measurement; setting them by guess is the failure mode this ordering exists to
  prevent.
- The security requirements (REQ-3, REQ-5) are where this feature can do real harm. Every
  assertion protecting them must be proven able to fail before it is trusted.
- Do not reintroduce `webbrowser.open` on any path.
- Verify the citations in this spec against the code. Line references drift, and a brief that
  is confidently wrong is worse than one that is vague.
