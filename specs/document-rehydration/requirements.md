# Requirements — Document Re-Hydration & Provenance Reuse

> Spec family: `document-rehydration`
> Status: DRAFT (Phase -1 complete, user decisions locked)
> Grounded in: live `data/memory.db` inspection + code trace (agent_kernel.py, document_store.py, tool_bridge.py, crawler/orchestrator.py, chat-view.tsx)

## Context

When a user resumes a previous chat, or switches to a different conversation, any
`document:render` cards that were on screen **disappear** from the UI. The
underlying data is NOT lost — `DocumentDataStore` persists both the synthesized
`show` content and the raw crawler/tool JSON result into `document_data`
(`data/memory.db`), scoped by `conversation_id`. The gap is twofold:

1. **UI does not re-hydrate** `renderedDocuments` on resume/switch (it is a
   React `useState`, seeded only by live `document:render` events).
2. **The agent cannot re-address old document DATA** — there is no tool that
   returns a previously-rendered document's underlying content/sources by
   `document_id`. So a later prompt like *"combine the migration data from that
   doc with the speed data from this other doc"* cannot be satisfied, because the
   agent has no handle to the old data.

Additionally, research-synthesized documents carry provenance (source URLs,
`citation_index`, `credibility_map`) that is currently **not linked** to the
synthesized row: the raw crawl JSON and the synthesized `show` are two separate
`document_data` rows in the same conversation with no `source_document_id`
linkage, and `source_tool`/`sources` are dropped by `_store_document_data`.

## User-locked decisions

- **D1 — Re-crawl is REQUIRED, not optional.** The agent must be able to combine
  data from multiple separate renders AND re-crawl when sources are stale/dead or
  a new combination needs fresh data. Re-crawl is a first-class fallback path, not
  an afterthought.
- **D2 — Provenance is surfaced, not orphaned.** A re-hydrated research document
  re-renders WITH its source URLs / citations resolved, never as bare `[1][2]`
  text with no targets.
- **D3 — Explicit-only prompt trigger.** The agent reloads/recombines documents
  only when the user explicitly asks ("show/reload my document", "combine doc A
  and doc B"). It does NOT auto-reload on every prompt.
- **D4 — No new heavy table.** Reuse the existing `document_data` table; add
  linkage + source columns via `ALTER TABLE` (pattern already exists at
  document_store.py:70). The raw research JSON is already persisted — we link and
  surface it, we do not duplicate it.
- **D5 — Single convergence point on the frontend.** Every document (live,
  resumed, switched, prompt-recombined) arrives via the SAME `document:render`
  event → SAME reducer merge. No divergent rendering path.

## Requirements (EARS)

### REQ-1: UI re-hydration on resume
**WHEN** the frontend receives a `sync_state_ack` carrying a `conversation_id`,
**THE SYSTEM SHALL** fetch and merge that conversation's persisted documents into
`renderedDocuments` via the existing reducer, so the rendered cards reappear
without user action.

### REQ-2: UI re-hydration on conversation switch
**WHEN** the user switches to a different conversation (frontend calls
`setActiveConversationId(newId)` / sends `switch_conversation`), **THE SYSTEM
SHALL** fetch and merge the new conversation's persisted documents into
`renderedDocuments`, replacing the previous conversation's view.

### REQ-3: Idempotent merge
**THE SYSTEM SHALL** merge documents keyed on `document_id` such that calling
re-hydration multiple times (reconnect + switch + prompt) never creates
duplicate cards and never clobbers a live in-session document with a stale copy.

### REQ-4: Backend read path scoped by conversation
**THE SYSTEM SHALL** provide a `get_documents` WS request/response (payload
`{conversation_id}`) that returns all `document_data` rows for that conversation,
using the existing `DocumentDataStore` query, scoped strictly by
`conversation_id` (thread isolation — no doc A leaking into thread B).

### REQ-5: Provenance linkage persisted
**WHEN** a synthesized `show` document is stored via `_store_document_data`,
**THE SYSTEM SHALL** persist a `source_document_id` linking it to the raw
tool-result JSON row (when one exists) and a `sources` JSON column listing
`{url, title}` extracted from that raw result. (New columns via `ALTER TABLE`;
existing `revision` column added the same way at document_store.py:70.)

### REQ-6: Source URLs surfaced on render
**THE DOCUMENT RENDER payload (`document:render`) SHALL** include a `sources`
array (list of `{url, title}`) when the document has provenance, so the frontend
can render a source list / resolvable citations rather than orphaned `[1][2]`.

### REQ-7: Agent tool to read document DATA
**THE SYSTEM SHALL** provide an agent-callable internal tool (e.g.
`get_rendered_documents`) that returns, for the active conversation, the
persisted document DATA (content + variants + sources + `source_document_id`),
so the agent can recombine multiple renders in a subsequent synthesis.

### REQ-8: Agent recombination across renders
**WHEN** the user asks to combine data from two or more previously-rendered
documents, **THE SYSTEM SHALL** let the agent read each document's underlying
data (via REQ-7) and produce a new synthesized document that merges them, stored
and rendered through the normal `document:render` path.

### REQ-9: Re-crawl fallback
**WHEN** the agent determines that combined/recombined data requires fresh or
updated sources (sources dead, stale, or a genuinely new query), **THE SYSTEM
SHALL** permit the agent to invoke the existing research/crawl tools
(`crawler_query` / `search`) to fetch fresh data, then synthesize — reusing the
existing crawl pipeline, not a new one.

### REQ-10: Prompt-triggered reload (explicit only)
**WHEN** the user explicitly requests a document be shown/reloaded/recombined,
**THE SYSTEM SHALL** route that through the agent (REQ-7/REQ-8/REQ-9). The agent
emits `document:render` per document; the frontend handles it via the existing
path (no new frontend fetch code for the prompt case).

### REQ-11: No live-web dependency for re-hydration
**THE SYSTEM SHALL** re-hydrate display + make document DATA available using only
persisted `document_data` (no network call) for the common case. Network (re-crawl)
is used ONLY per REQ-9 when the agent explicitly decides fresh data is needed.

### REQ-12: Thread isolation preserved
**THE SYSTEM SHALL** enforce that `get_documents` (REQ-4) and the agent document
tool (REQ-7) return only documents whose `conversation_id` equals the active
thread, consistent with the session-conversation-switching spec's
`conversation_id` gate.

### REQ-13: HAR evidence capture (light, per-crawl)
**WHEN** the crawl pipeline (`CrawlerEngine.crawl()`, the per-request HTTP layer)
performs a web fetch for a research/crawl run, **THE SYSTEM SHALL** capture a
*light* HAR entry per request containing `{url, method, status, response_headers,
duration_ms, content_length, body_sha256}` (no full response bodies), and persist
the run's entries as a file `data/har/<job_id>.har`, referenced by a `har_path`
column on the linked `document_data` raw-JSON row (via `source_document_id`). This
is the HTTP *evidence* layer, complementary to (not a replacement for)
SourceRegistry.

### REQ-14: SourceRegistry retains its use case (no HAR merge)
**THE SYSTEM SHALL** keep `SourceRegistry` as the aggregated, decaying
topic→URL credibility knowledge base (its existing `resolve()`/`learn()` use
case unchanged). HAR outcomes MAY down-weight a domain's credibility via the EXISTING
`SourceRegistry.penalize_url(url, topics)` method (source_registry.py:91), but
SourceRegistry SHALL NOT store raw per-request transaction logs. The two layers
stay separate and wired one-way (HAR → SourceRegistry signal).

### REQ-15: Structured logging with stable context id
**THE SYSTEM SHALL** emit structured logs at every new boundary in the
re-hydration + provenance pipeline, each line carrying a stable context
identifier (`conv_id` + `doc_id` + `job_id` where applicable), covering at
minimum: HAR write (entries count + path), document store (doc id + source_doc +
har_path + sources count), `get_documents` read (conv + returned count), agent
`get_rendered_documents` (conv + returned count), and re-crawl decision (reason
+ url + har_status). Logs SHALL be emitted even on the failure paths below.

### REQ-16: Graceful degradation (no user-response block)
**THE SYSTEM SHALL** ensure every new boundary fails safe and never blocks a user
response: HAR write failure → document still stores without `har_path`; a missing
`har_path` file → agent falls back to re-crawl (not an error); `get_documents`
on an unknown/empty conversation → returns an empty list (not a 500); malformed
raw JSON that cannot yield `sources` → store empty `sources` rather than fail the
store; Pacman/reference-zone write failure → logged, does not fail the document
store.

### REQ-17: Pacman spillage is preserved and made document-linked
**THE SYSTEM SHALL** preserve the existing crawl→Pacman `reference`-zone
spillage (credibility + citation metadata from web tools) AND additionally route
the new structured provenance (`sources`, `har_path`, `source_document_id`) into
Pacman's reference zone in a **document-linked, queryable** form (tagged with
`document_id` + `conversation_id`), so provenance can be recalled by document
rather than only as an opaque `<CREDIBILITY_META>` blob. This MUST NOT regress
the existing spillage path.

### REQ-18: Smart-crawl learning loop (memory-driven)
**THE SYSTEM SHALL** close the learning loop so subsequent crawls improve: HAR
outcomes (dead/stale/healthy per URL, via `penalize_url`) and recombination
outcomes (which sources were actually used/cited in a synthesized doc) SHALL feed
back into `SourceRegistry` via `learn()` / `penalize_url()`, updating per-domain
credibility and freshness. The next `resolve(query)` SHALL then seed from this
updated knowledge — fewer fetches, better sources, dead domains avoided.

### REQ-19: Smart-crawl reduces redundant work
**WHEN** a new crawl/research query overlaps a previously-crawled topic whose
HAR shows all sources still healthy and within freshness TTL, **THE SYSTEM
SHALL** prefer reusing the persisted `document_data` + HAR evidence (and the
SourceRegistry seed) over re-fetching, only fetching deltas for sources that are
new, stale, or HAR-flagged. This is the "smart" behavior — memory-first, not
fetch-first.

## Out of scope
- Changing the `document:render` event *shape* beyond adding `sources` (REQ-6).
- Changing how live documents behave during an active session.
- New crawl engine; re-crawl reuses the existing pipeline.
- Dilithium/memory.db encryption changes.
- Making SourceRegistry store raw HAR transactions (REQ-14 forbids this).

## Verification strategy (tiers — see design.md)
- Unit: `document_store.list_for_conversation`, `ALTER TABLE` migration idempotency,
  HAR file written + `har_path` persisted + `penalize_url` down-weights;
  logging emits context-id lines; degradation paths return safe values (no 500).
- Contract: `get_documents` WS request/response shape; `document:render` carries
  `sources`; Pacman reference-zone entry is document-linked + queryable.
- Behavioral: resume a chat with a research doc → cards reappear WITH sources;
  prompt "combine doc A + doc B" → agent reads both via tool, emits merged doc;
  re-crawl path inspects HAR before deciding to refresh a dead source; a SECOND
  research query on the same topic reuses persisted evidence + SourceRegistry
  seed (fewer fetches) — proving the smart-crawl learning loop (REQ-18/REQ-19).
- Physics-aware: N/A for this feature.
