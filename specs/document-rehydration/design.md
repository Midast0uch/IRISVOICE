# Design — Document Re-Hydration & Provenance Reuse

## Architecture overview

```
                         ┌─────────────────────────────────────────┐
                         │            data/memory.db                │
                         │  document_data (EXISTING, reused)        │
                         │   document_id | conversation_id | fmt |  │
                         │   content | variants | alternatives |     │
                         │   trust | revision |                     │
                         │   [NEW] source_document_id | sources(JSON)│
                         │                                           │
                         │   row A: raw crawler_query JSON (fmt=json)│
                         │   row B: synthesized show (fmt=markdown)  │
                         │         source_document_id -> row A       │
                         └─────────────────────────────────────────┘
                              ▲ store (already happens)      │ read
                              │                              ▼
   AGENT ──get_rendered_documents──► DocumentDataStore.get_for(conv)  (NEW tool, REQ-7)
     │                                      │
     │ crawler_query / search (re-crawl)    │ list_for_conversation (NEW, REQ-4)
     ▼                                      ▼
   existing crawl pipeline            WS get_documents handler (NEW, REQ-4)
                                            │
                                            ▼
   document:render (EXISTING, +sources)  ──►  frontend hydrateDocuments() (NEW, REQ-1/2)
                                            │        │
                                            │        └─► existing reducer (chat-view.tsx:538)
                                             ▼
                                    renderedDocuments (re-populated)

                         ┌─────────────────────────────────────────┐
                         │  data/har/<job_id>.har  (NEW, file-backed)│
                         │   light HAR: per-request                  │
                         │   {url, method, status, resp_headers,    │
                         │    duration_ms, content_length,          │
                         │    body_sha256}  (no full bodies)         │
                         └─────────────────────────────────────────┘
                               ▲ captured at CrawlerEngine.crawl() (per-request)
                               │ har_path  (NEW column on document_data)
                               │ linked via source_document_id
                               │
                               │ one-way signal
                               ▼
                          SourceRegistry (UNCHANGED use case)
                            resolve(query) -> seed URLs
                            learn() -> decaying credibility
                            penalize_url(url, topics) -> down-weight dead domain
```

## Key decisions (locked, ordered D1–D6)

- **D1 — Re-crawl is a fallback, not primary.** Primary re-hydration reads
  persisted `document_data` (no network). The agent re-crawls ONLY when it
  decides sources are dead/stale or the combination needs fresh data — via the
  EXISTING `crawler_query` / `search` tools. No new crawl code. (Supersedes the
  earlier "D9" label; consolidated here.)
- **D2 — Provenance is surfaced, not orphaned.** A re-hydrated research document
  re-renders WITH its source URLs / citations resolved, never as bare `[1][2]`
  text with no targets. Drives REQ-6 (sources on render) + REQ-17 (Pacman
  document-linked provenance).
- **D3 — Explicit-only prompt trigger.** The agent tool `get_rendered_documents`
  exists; the agent calls it only when the prompt implies document
  retrieval/recombination. The prompt case needs NO new frontend fetch code — it
  re-emits `document:render` through the live path.
- **D4 — Reuse `document_data`, add columns.** `ALTER TABLE document_data ADD
  COLUMN source_document_id TEXT; ADD COLUMN sources TEXT; ADD COLUMN har_path
  TEXT;` (JSON list of `{url,title}`). Mirrors the existing `ADD COLUMN revision`
  at document_store.py:70. No new table.
- **D5 — Single convergence point.** Frontend `hydrateDocuments(conversationId)`
  is the ONLY new UI code. It fetches via `get_documents` and merges through the
  existing `setRenderedDocuments` reducer (keyed on `document_id`). Live
  `document:render`, resume, switch, and prompt-recombined docs ALL flow through
  `document:render` → same reducer. No divergent render path.
- **D6 — HAR is evidence, SourceRegistry is knowledge; keep them separate.**
  HAR captures per-crawl HTTP *evidence* (status/headers/timing/body-hash),
  file-backed at `data/har/<job_id>.har`, linked to the raw JSON row via
  `source_document_id` + `har_path`. SourceRegistry keeps its aggregated,
  decaying topic→URL credibility use case (resolve/learn unchanged). HAR outcomes
  down-weight a domain via the EXISTING `SourceRegistry.penalize_url(url, topics)`
  (source_registry.py:91) — do NOT invent a new `report_fetch_outcome()` method;
  reuse `penalize_url`. One-way signal, never raw transaction storage inside
  SourceRegistry (REQ-14).

## Component changes

### Backend

 1. **`document_store.py`**
    - `DocumentDataStore.__init__` / `get_for`: run idempotent `ALTER TABLE` to add
      `source_document_id`, `sources`, `har_path` columns (guarded, like `revision`).
    - New `list_for_conversation(conversation_id)` → returns all rows for conv
      (already has `get()` for single id). Returns dicts including new columns.
    - `store()` / `_store_document_data` (agent_kernel.py:3087): accept and persist
      `source_document_id` + `sources` + `har_path` when present in the `show` dict.

 0. **HAR capture (Wave 0 — NEW, REQ-13/REQ-14)**
    - **Capture at the per-request layer, NOT `FetchBackend.fetch`.** The real
      HTTP fetch happens inside `CrawlerEngine.crawl()` (crawler_engine.py);
      `FetchBackend.fetch` returns a *batch* `CrawlResult`, so wrapping it would
      capture a batch, not individual requests. (Do NOT wrap `FetchBackend.fetch`
      — that was a blueprint error caught by the grounding audit.) Wrap the
      individual request inside `CrawlerEngine` to record a light HAR entry per
      request:
      `{url, method, status, response_headers, duration_ms, content_length,
      body_sha256}`. No full response bodies.
    - A `job_id` must be threaded from the crawl orchestration down to the engine
      so the HAR file can be named `data/har/<job_id>.har`. If no job_id exists
      at engine level today, generate/propagate one (crawl orchestrator already
      has a job concept via JobRegistry).
    - After a crawl run completes, write `data/har/<job_id>.har` (JSON array of
      entries). Ensure `data/har/` exists (create if missing).
    - Propagate `har_path` to the raw crawler_query result so
      `_store_document_data` persists it on the raw JSON row; the synthesized
      `show` inherits `source_document_id` → resolves to the HAR via the raw row.
    - **Reuse existing `SourceRegistry.penalize_url(url, topics)`**
      (source_registry.py:91) on 403/404/timeout — do NOT create a new
      `report_fetch_outcome()` method. `resolve()`/`learn()` unchanged.

2. **`agent_kernel.py` `_store_document_data`** (3087)
   - Extract `source_document_id` and `sources` from `show` (currently dropped).
   - When storing a synthesized `show` whose `source_tool == "crawler_query"` (or
     research), look up the most recent raw JSON row in the same conversation and
     set `source_document_id`; extract `{url,title}` list into `sources`.

 3. **`iris_gateway.py`** — new WS handler `get_documents`
    - Request `{conversation_id}` → `DocumentDataStore.list_for_conversation(
      conversation_id, metadata_only=True)` → response using the EXISTING
      wrapped convention `{type:"documents", payload:{documents:[...]}}` (match
      `reformat_document_ack` at iris_gateway.py:8194, NOT a flat shape). Scoped
      by active thread (REQ-12). Add an explicit unit test asserting the
      `WHERE conversation_id=` clause isolates threads.

 4. **`tool_registry.py` + `tool_bridge.py`** — new tool `get_rendered_documents`
    - Returns the active conversation's document DATA (content, variants, sources,
      source_document_id, har_path) so the agent can recombine (REQ-7/REQ-8).
    - **Use the REAL executor dispatch pattern** — tools are routed by executor
      *type* (e.g. `research` for crawler_query), not a literal `"internal"`
      string. Register `get_rendered_documents` with the appropriate existing
      executor type / dispatch path (read-only), reusing `tool_executor.py`
      routing. Do NOT assume an `executor="internal"` literal exists.

5. **`document:render` payload** (agent_kernel.py:3017, ws_event_bridge.py:113)
   - Add `sources` array when provenance exists (REQ-6).

### Frontend (`components/chat-view.tsx`)

0. **Add `sync_state_ack` WS handler first** (does NOT exist today). The WS
   message router in chat-view.tsx must handle `sync_state_ack` and read its
   `conversation_id` before any wiring can occur.
1. New `hydrateDocuments(conversationId)`:
    - send `get_documents {conversation_id}`; on response (wrapped
      `{type:"documents", payload:{documents:[...]}}`), merge each doc via the
      existing reducer (lines 538-553) keyed on `document_id` (REQ-3 idempotent).
2. Wire triggers:
    - `sync_state_ack` handler (added in step 0) → `hydrateDocuments(ack.conversation_id)` (REQ-1).
    - switch handler (~line 1074, after `setActiveConversationId`) →
      `hydrateDocuments(newId)` (REQ-2).
 3. `DocRender` type (~line 129): add optional `sources?: {url:string,title:string}[]`.
 4. Render source list / resolvable citations from `sources` (REQ-6). Prompt case
    (REQ-10) needs no new code — flows through existing `document:render`.

### Observability & resilience (REQ-15, REQ-16)
- **Structured logging**: every new boundary logs with a stable context id
  `{conv_id, doc_id, job_id}`. Canonical lines:
  - `HAR write job=<id> entries=<n> path=data/har/<id>.har conv=<c>`
  - `DOC STORE doc=<id> conv=<c> source_doc=<sid> har=<path> sources=<n>`
  - `GET DOCS conv=<c> returned=<n>`
  - `GET RENDERED DOCS conv=<c> returned=<n>`
  - `RECRAWL doc=<id> reason=dead_source url=<u> har_status=<code>`
  - `SMART CRAWL query=<q> reused=<n> fetched=<m>` (REQ-19 memory-first signal)
- **Graceful degradation** (REQ-16): each boundary fails safe:
  - HAR write fails → doc stores without `har_path` (logged).
  - `har_path` file missing → agent re-crawls (not an error).
  - `get_documents` unknown/empty conv → empty list, never 500.
  - malformed raw JSON → empty `sources`, store still succeeds.
  - Pacman/reference write fails → logged, doc store unaffected.
  - No new boundary may raise into the user-response path.

### Pacman spillage (REQ-17)
- Preserve existing `pacman_fragment._store_credibility_metadata` (web tools →
  `reference` zone, opaque `<CREDIBILITY_META>` blob). Do NOT regress it.
- ADD: when a document is stored with provenance, also write a **document-linked**
  reference-zone entry tagged `{document_id, conversation_id, sources, har_path}`
  (queryable by document, not just an opaque blob). Reuse the existing
  `reference` zone + episodic store; new helper `fragment_document_provenance()`.
- This lets future recall retrieve a document's full provenance from Pacman by
  `document_id`, complementing the `document_data` columns.

### Smart-crawl learning loop (REQ-18, REQ-19)
- **Feedback paths into SourceRegistry** (existing `learn()`/`resolve()` +
  `penalize_url(url, topics)` — do NOT create a new `report_fetch_outcome()`):
  - HAR per-URL outcome (200/403/404/timeout) → `penalize_url(url, topics)`
    down-weights dead/stale domains.
  - Recombination outcome: when a synthesized doc cites specific sources, call
    `learn(query, used_sources)` so those domains gain credibility for that topic.
- **Memory-first crawl (REQ-19)**: on a new research query, `resolve(query)`
  returns the updated seed set. Before fetching, the agent checks whether a prior
  crawl for the same topic exists with a healthy HAR (all sources 200, within
  `ttl_days`). If so, it reuses the persisted `document_data` + HAR evidence and
  fetches ONLY deltas (new/stale/HAR-flagged sources). Net effect: fewer fetches,
  better sources, dead domains avoided — the learning compounds across sessions.
- This is the "exemplary powerful" path: the more the agent researches, the
  smarter (and cheaper) each subsequent crawl becomes, because SourceRegistry +
  HAR + document_data form a persistent, queryable memory of what was learned.

## Data flow: "combine doc A and doc B" (REQ-8)

1. User: "combine the migration table with the speed table from earlier."
2. Agent calls `get_rendered_documents` → gets doc A data + doc B data (incl.
   `sources`, `source_document_id`).
3. Agent synthesizes merged content. If it judges sources stale/insufficient, it
   calls `crawler_query`/`search` (REQ-9 re-crawl) to refresh, then synthesizes.
4. Agent emits `show` with merged content → `_store_document_data` (links
   `source_document_id` to both A and B raw rows) → `document:render` (with
   `sources`) → frontend reducer merges → new card appears.

## Verification strategy (4 tiers)

- **Unit** (`tests/unit/`): `list_for_conversation` returns only conv-scoped rows;
  `ALTER TABLE` idempotent (run twice safe); `_store_document_data` persists
  `source_document_id`/`sources`.
- **Contract** (`tests/contract/`): `get_documents` request/response shape;
  `document:render` carries `sources` when provenance present; agent
  `get_rendered_documents` returns conv-scoped data.
- **Behavioral** (`tests/behavioral/`): full loop — (a) render a research doc,
  disconnect/reconnect, assert cards reappear WITH sources; (b) prompt "combine
  doc A + doc B", assert agent reads both via tool and emits merged doc. Mock the
  fetch engine; never hit live web in Tier 1-3.
- **Manual live** (app-testing skill): resume a chat with a research-synthesized
  doc → cards reappear with clickable sources; switch conversations → correct
  docs; prompt combine → merged doc. Capture WS + console.

## Risks / open questions
- `sources` extraction depends on the raw crawler JSON shape (confirmed present
  in live DB: `--- Source: <url> ---` headers). Parser must be tolerant if shape
  varies.
- Large raw JSON rows could be big; `list_for_conversation` should return
  metadata-light summaries for the UI path and full data only for the agent tool
  path (REQ-4 vs REQ-7 separation).
