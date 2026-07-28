# Tasks — Document Re-Hydration & Provenance Reuse

Waves are ordered; later waves depend on earlier. Each task links to REQ IDs and
honors design.md decisions. Cross-layer (seam) tasks need contract + behavioral
tests, not just unit.

## Wave 0 — HAR evidence capture (NEW, REQ-13/REQ-14)
- **T0a** (REQ-13): capture HAR at the **per-request layer inside
  `CrawlerEngine.crawl()`** (crawler_engine.py) — NOT `FetchBackend.fetch`
  (which returns a batch `CrawlResult`). Record a *light* HAR entry per request:
  `{url, method, status, response_headers, duration_ms, content_length,
  body_sha256}` (no full bodies). Thread a `job_id` from the crawl orchestrator
  (JobRegistry) down to the engine so the file is `data/har/<job_id>.har`. Test:
  unit — entry captured with correct fields for a mocked fetch; file named by
  job_id.
- **T0b** (REQ-13, REQ-5): after a crawl run, write `data/har/<job_id>.har`
  (JSON array); ensure `data/har/` exists. Propagate `har_path` to the raw
  crawler_query result → persisted on the raw JSON `document_data` row (new
  `har_path` column). Test: unit — HAR file written, `har_path` persisted,
  `ALTER TABLE` idempotent.
- **T0c** (REQ-14, REQ-18): **reuse existing `SourceRegistry.penalize_url(url,
  topics)`** (source_registry.py:91) on 403/404/timeout — do NOT create a new
  `report_fetch_outcome()`. `resolve()`/`learn()` UNCHANGED. Test: unit —
  dead-domain credibility drops; SourceRegistry still resolves/learns normally
  (use case preserved, no raw HAR stored inside it).
- **T0d** (REQ-15, REQ-16): structured logging + graceful degradation across all
  Wave 0 boundaries — HAR write fail → store without har_path; missing har_path →
  re-crawl; unknown conv → empty list; malformed JSON → empty sources; Pacman
  write fail → logged, store unaffected. Each boundary logs with context id
  `{conv_id, doc_id, job_id}`. Test: unit — each degradation path returns safe
  value + emits a log line; no path raises into caller.
- **T0e** (REQ-17): Pacman spillage — preserve existing `reference`-zone
  credibility blob (no regression); ADD `fragment_document_provenance()` writing a
  document-linked, queryable reference entry `{document_id, conversation_id,
  sources, har_path}`. Test: unit — document-linked entry retrievable by
  document_id; existing blob path still fires.
- **T0f** (REQ-18, REQ-19): smart-crawl learning loop — wire HAR outcomes (via
  `penalize_url`) + recombination citations into `learn()`; on a repeated topic
  query, `resolve()` seeds from updated knowledge. **Explicit agent orchestration
  step**: before fetching, check whether a prior crawl for the same topic exists
  with a healthy HAR (all sources 200, within TTL) → reuse persisted
  `document_data` + HAR evidence, fetch ONLY deltas (new/stale/HAR-flagged). Test:
  behavioral — second research query on same topic fetches fewer URLs (reuses HAR
  + SourceRegistry seed) than the first; dead domain from HAR is avoided.

## Wave 1 — Schema & store (backend, no behavior change yet)
- **T1** (REQ-5, REQ-4, REQ-13): `document_store.py` — idempotent `ALTER TABLE`
  adding `source_document_id`, `sources`, `har_path`; add
  `list_for_conversation(conversation_id, metadata_only=False)`. When
  `metadata_only=True` (UI path, REQ-4/T3) return light columns only
  (document_id, fmt, conversation_id, sources, har_path, created_at) — NOT the
  large `content`/`variants` blobs. Full data only when `metadata_only=False`
  (agent tool path, REQ-7/T5). *Honors D4/D6.* Test: unit — columns exist after
  double-run; list scoped by conv; metadata_only omits content.
- **T2** (REQ-5): `agent_kernel._store_document_data` — persist
  `source_document_id` + `sources` + `har_path` from `show`; when
  `source_tool=="crawler_query"`, link to most recent raw JSON row in conv and
  extract `{url,title}` into `sources`. Test: unit — synthesized row carries
  linkage + sources + har_path.

## Wave 2 — Backend read + render path
- **T3** (REQ-4, REQ-12): `iris_gateway.py` — `get_documents` WS handler,
  conv-scoped, active-thread gated. Response uses the EXISTING wrapped convention
  `{type:"documents", payload:{documents:[...]}}` (match `reformat_document_ack`),
  NOT a flat shape. Calls `list_for_conversation(conv, metadata_only=True)`. Test:
  contract — request/response shape + thread isolation; ADD explicit unit test
  asserting the `WHERE conversation_id=` clause excludes other threads (REQ-12).
- **T4** (REQ-6): `document:render` payload (agent_kernel:3017,
  ws_event_bridge:119) includes `sources` when provenance exists.
  Test: contract — payload carries sources for research doc, absent for plain.
- **T5** (REQ-7, REQ-8): `tool_registry.py` + `tool_bridge.py` —
  `get_rendered_documents` tool returning conv document DATA (incl. `har_path`),
  using the REAL executor dispatch pattern (tools route by executor *type*, e.g.
  `research` — there is no literal `executor="internal"`). Register with the
  appropriate existing read-only dispatch path in `tool_executor.py`. Calls
  `list_for_conversation(conv, metadata_only=False)` for full data. Test: contract
  — returns conv-scoped data, excludes other threads.

## Wave 3 — Frontend re-hydration (single convergence point)
- **T6** (REQ-1, REQ-2, REQ-3, REQ-5): `chat-view.tsx` — **FIRST add a
  `sync_state_ack` WS handler** (does not exist today); it reads
  `ack.conversation_id`. Then add `hydrateDocuments(convId)` which sends
  `get_documents` and merges via the existing reducer keyed on `document_id`. Wire
  `hydrateDocuments` to the new `sync_state_ack` handler + the switch handler
  (~line 1074, after `setActiveConversationId`). Test: behavioral — resume/switch
  re-populates, idempotent (no dupes).
- **T7** (REQ-6): `DocRender` type + source list / resolvable citations render.
  Test: unit — sources render as list; orphaned `[n]` avoided when sources present.

## Wave 4 — Agent recombination + re-crawl (the "combine" requirement)
- **T8** (REQ-8, REQ-9, REQ-10, REQ-11, REQ-13): agent path — prompt "combine
  doc A + doc B" → agent calls `get_rendered_documents` (reads both DATA +
  har_path), inspects HAR to decide if a source is dead/stale, re-crawls via
  existing tools ONLY when needed, synthesizes merged doc. Emits `document:render`
  (no new frontend code). Test: behavioral — full loop, mock fetch engine, assert
  merged doc emitted + persisted with linkage to both source rows + HAR consulted.

## Wave 5 — Verification & crystallization
- **T9**: Run existing suite (pytest / npm test / tsc) — no regressions.
- **T10**: Manual live test via app-testing skill (resume + switch + combine +
  verify HAR file present and re-crawl consults it).
- **T11**: `mcm_define_feature` + `mcm_cad_mcm_crystallize_landmark` +
  `mcm_compress`.

## Cross-layer / seam tasks (need Tier 3 behavioral, not just unit)
- T0a+T0b+T0c+T0d+T0e+T0f (HAR capture ↔ SourceRegistry signal ↔ logging/degradation
  ↔ Pacman spillage ↔ smart-crawl learning) — unit + contract + behavioral.
- T3+T6 (WS handler ↔ frontend hydrate) — contract + behavioral.
- T5+T8 (agent tool ↔ recombination ↔ HAR consult) — behavioral full-loop.
- T4+T7 (`document:render` sources ↔ UI render) — contract + behavioral.

## Flagged for user (not silently skipped)
- `sources` extraction parser tolerance (design.md risk) — T2 must be tolerant of
  varying raw JSON shapes; if a shape can't be parsed, store empty sources rather
  than fail the store.
- Large raw JSON: T3 (UI path) returns light metadata; T5 (agent path) returns
  full data. Separation honored in design.md.
- HAR size: light-HAR only (no full bodies) per D6; if a fetch body is needed for
  re-verify, re-crawl fetches it on demand rather than storing it.
