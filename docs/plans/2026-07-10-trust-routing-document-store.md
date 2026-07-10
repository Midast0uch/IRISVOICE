# Plan: Trust-Routing for Web Content + Data-Centric Document Memory

**Date:** 2026-07-10
**Status:** PLANNED (not yet implemented)
**Author:** Senior Architect review (main session)
**Branch context:** `feat/agent-multi-step-tool-execution`

---

## Background

This plan addresses three findings from a review of the voice-tts-document-redesign
implementation:

1. **Bug (FIXED):** `agent_kernel._process_structured_response` returned the raw
   JSON when a `show` payload had no `speak` field — leaking JSON into TTS + chat.
   Fixed at `agent_kernel.py:2540` (returns `""` for show-only). Needs a regression test.
2. **Security:** `RichDocument.tsx:132` renders `html` via `dangerouslySetInnerHTML`
   and `MermaidDiagram.tsx:24` uses `securityLevel:"loose"` with no sanitization.
   Web/crawler-derived content can reach these paths.
3. **Reformat round-trip:** The reformat flow passes full document `content` from the
   client back to the backend, which is fragile (client can tamper; re-reformat degrades
   from an already-reformatted copy) and prevents server-side reuse/reference.

**Core insight:** The trust infrastructure already exists in the system — it just is not
*routed* to web/external content. The work is wiring + routing, not new machinery.

**Scope expansion (this revision):** After compressing and re-examining the existing
memory + agent-action systems, the plan was extended from "fix the doc feature" into
"turn documents into a novel memory primitive." Two new analysis sections
(Overlooked gaps, Unique opportunities) and work items W7–W10 were added.

---

## Investigation findings (what already exists)

### 1. Trust-zone model is built but unused for web content
- `backend/memory/episodic.py:107` — `_ZONE_REFERENCE = "reference"  # external content (future)"`
  The slot for external/web content is already reserved.
- `episodic.py:555` `fragment_and_store()` already accepts a `zone` param.
- `episodic.py:670` `recall()` already filters by `zones`.
- **Mycelium already enforces trust and is tested:** `backend/memory/mycelium/landmark.py`
  has `untrusted_fraction` + `TRUST_CAP_FRACTION`; `test_mycelium_kyudo_security.py`
  contains `test_cellwall_untrusted_rejected_from_trusted_zone`,
  `test_landmark_trust_cap_blocks_crystallization`,
  `test_mcp_pin_mismatch_downgrades_to_untrusted`. It blocks crystallization when >30%
  of a region is untrusted — but never receives web content tagged untrusted.

### 2. Routing points already carry `tool_name`
- `backend/agent/mcm_protocol/actions/pacman_fragment.py:29-67` receives `tool_name`
  and `response_text`, then calls `fragment_and_store` **without a zone** (defaults
  `trusted`). Single natural injection point.
- `agent_kernel.py:4076` DER path calls `post_turn(..., tool_name=...)` →
  `orchestrator.py:65` → `pacman_fragment`. DER *and* tool outputs both flow through
  with `tool_name`.
- `agent_kernel.py:2985-3014` ReAct path stores the turn via
  `fragment_and_store(zone="trusted")` or `post_turn`.

### 3. Document render path is extensible
- `DOCUMENT_RENDER` payload (built in `backend/agent/structured_response.py`) can carry
  additive `trust` + `document_id` fields.
- `RichDocument.tsx:132` and `MermaidDiagram.tsx:24` are the sanitization injection points.
- No sanitizer lib installed (`package.json` has no DOMPurify/sanitize-html) — the one
  genuine gap.

### 4. Store pattern already exists
- `backend/agent/conversation_context_store.py` is a proven SQLite-WAL, thread-safe,
  bounded store. A `DocumentStore` reusing it is straightforward.

### 5. The 4D Immortus memory chain (the "4d layer")
- `backend/gateway/iris_ffi.py:372` `immortus_chain_append(thread_id, result, coords_from,
  coords_to, nbl_outcome, insight, ...)` records a **reasoning trajectory**: the 4D
  coordinate transition `coords_from → coords_to` (depth/clarity/novelty/drift, per
  `immortus/constants.py`). `immortus_chain_fetch(thread_id)` replays lineage.
- This is **placement + lineage**, not a semantic store — it places data in the reasoning
  space but cannot be searched by meaning.

### 6. Mycelium semantic/episodic = meaning-based retrieval
- `backend/memory/episodic.py` stores 384-dim embeddings; `recall(query)` uses cosine
  similarity (`retrieve_context_chunks`, `find_similar_success`). The agent retrieves via
  `mcm_recall` / `pacman_recall` MCM actions (`backend/agent/mcm_protocol/actions/`).

---

## Unifying design: a single `trust` signal + data-centric storage

`trust ∈ {"trusted", "untrusted"}`, derived from **"did this content touch external/web
sources?"** Propagates to three consumers through one flag:

```
web/crawler tool runs
        │
        ├─► pacman_fragment: zone="untrusted"  (episodic + Mycelium trust-cap)
        │
        ├─► DOCUMENT_RENDER.trust  ──► frontend sanitizes html/mermaid when untrusted
        │
        └─► stored DATA record.trust  (preserved across reformats; gates crystallization)
```

Separately, the document's **canonical data** (not its render) is stored so the agent can
retrieve + reformat it arbitrarily (W4–W5), and so it can *find its place* in the 4D
Immortus layer (W7) and *crystallize* into permanent memory (W8).

---

## Overlooked gaps & risks (must-fix constraints)

These were not in the original plan. Each is grounded in existing code.

### G1 — Deterministic reformat is already half-built; we were over-paying for it
- **Evidence:** `build_reformat_payload` already reads `alternatives` from the LLM reformat
  response (`structured_response.py:91` `alternatives = list(show.get("alternatives", []))`,
  `:98` returned in payload); `_process_structured_response` already emits `alternatives`
  in `DOCUMENT_RENDER` (`agent_kernel.py` DOCUMENT_RENDER emit, ~2530).
- **Reasoning:** The data model *already* supports multiple formats per document. Reformating
  to a format already present in `alternatives` requires **zero LLM calls** — it is a
  deterministic selection from stored variants. W5 as drafted says "re-LLM the canonical
  data," which would re-pay for formats we already have. We must prefer the deterministic
  path and only invoke the LLM for genuinely new formats. This is a cost/latency/reliability
  win we were missing.

### G2 — Recall scoping: stale data could surface in wrong contexts
- **Evidence:** Mycelium `recall()` is embedding-based (`episodic.py:670`); storing canonical
  data means it becomes semantically retrievable.
- **Reasoning:** A document about "Q3 budget" could be pulled into an unrelated "finance"
  query and surface stale/incorrect data. The plan must scope retrieval — by `document_id`
  for exact reformat, and by `conversation_id` / explicit semantic intent for open recall.
  Without scoping, the feature introduces a *correctness* regression (wrong-data recall).

### G3 — Retention & privacy tiering
- **Evidence:** The memory system has `backend/memory/retention.py` and privacy tests
  (`test_privacy.py`, `test_privacy_audit.py`); web-derived (untrusted) content is the
  riskiest to persist long-term.
- **Reasoning:** Document data inherits Mycelium/Immortus retention + privacy policies.
  Untrusted (web) document data may need isolation or shorter retention than trusted data.
  W4 must specify a retention tier so we don't persist untrusted web content indefinitely.

### G4 — Cross-protocol consistency (two stores)
- **Evidence:** W4 writes to **both** Immortus (C++, `iris_ffi.py`) and Mycelium (Python,
  `episodic.py`). The project ships an `mcp-eml-testing` skill whose entire purpose is
  catching cross-protocol / cross-store drift.
- **Reasoning:** Two independent stores holding the same document data will diverge unless
  we add a consistency guarantee (single writer + reconciliation, or one store as source of
  truth mirrored to the other). This is a known failure mode the project already documents.

---

## Unique / innovative opportunities

These leverage machinery that already exists but is not yet used for this purpose.

### O1 — Trajectory-conditioned retrieval (the standout) 🌟
- **Evidence:** `immortus_chain_append` records the 4D coordinate `coords_from→coords_to`
  (`iris_ffi.py:372`); the coordinate space is depth/clarity/novelty/drift.
- **Reasoning:** We framed the 4D coordinate as "placement." The innovative use is to
  **retrieve data by cognitive-trajectory similarity, not just semantic embedding** —
  e.g. "show me the data I gathered when my reasoning was in a state like *now*." This is
  memory indexed by *how you were thinking*, not just *what it's about*. It is **already
  enabled** by the Immortus 4D model; we only add a coordinate-proximity query. No other
  assistant does this. Low incremental cost, high differentiation. → **W7.**

### O2 — Document data → crystallization → permanent reformat-able memory 🌟
- **Evidence:** Mycelium landmarks **crystallize at 8 activations**
  (`landmark.py:414` `PERMANENCE_THRESHOLD = 8`) and the **trust-cap blocks crystallization
  when >30% untrusted** (`landmark.py:40` `_TRUST_CAP_FRACTION = 0.30`, `kyudo.py:63`).
- **Reasoning:** If we store document data as context chunks that get referenced/reformatted,
  high-value data **naturally crystallizes into permanent landmarks** — and untrusted (web)
  data is *automatically excluded* from becoming permanent memory by the existing cap. This
  turns the document feature from a UI trick into a **memory-formation primitive**:
  render → reference → crystallize → durable, always-reformat-able knowledge. We should
  *design W4 to seed this*, not just dump data. → **W8.**

### O3 — Proactive capture (bigger than documents)
- **Evidence:** `backend/agent/auto_research.py` already stores research topics with memory
  confidence; the DER loop processes tool results (`der_loop.py`).
- **Reasoning:** Instead of only storing data on a `show` payload, the agent could
  **proactively extract structured data from *any* tool result** (web, file read) into the
  data store — making *everything* the agent touches reformat-able, not just explicit
  documents. High-leverage scope expansion. → **W9.**

### O4 — Pheromone-reinforced reformat + cross-modal synergy
- **Evidence:** The interpreter predicts next actions from **pheromone edge weights**
  (`interpreter.py:208-212`); the `speak` tool / `SpeakBroadcaster` vocalizes; Vision MCP
  generates diagrams.
- **Reasoning:** Frequently-reformatted doc types could become **pheromone-reinforced**, so
  the agent *proactively offers* a reformat. And any reformatted view can be **vocalized**
  ("here's that table as bullet points") or turned into a **diagram** via Vision. These
  synergies are free given existing machinery. → **W10.**

---

## Work items

### W1 — Route web/crawler tool outputs to an untrusted zone (primary, low-risk)
- Add `_ZONE_UNTRUSTED = "untrusted"` to `episodic.py` (alias/extend existing `reference`).
- In `pacman_fragment.py:55-61`, set `zone="untrusted"` when `tool_name` ∈ a
  `WEB/EXTERNAL_TOOLS` set (`web_search`, `crawler_query`, ...). Decide zone inside the
  action — no workflow-JSON change needed.

### W2 — Propagate trust to the turn-level fragment
- Track a per-turn "touched external source" flag (set when a web/crawler tool runs).
- In `agent_kernel.py:2985-3014` pacman_store block, pass `zone="untrusted"` when that
  flag is set (both `fragment_and_store` and `post_turn` paths).
- Add optional `trust`/`zone` hint param to `post_turn` (`orchestrator.py:65`), non-breaking.

### W3 — Carry `trust` through DOCUMENT_RENDER + sanitize at render
- Add `trust` to `DOCUMENT_RENDER` payload in `structured_response.py`; set `untrusted`
  when the emitting turn touched external sources (reuse W2 flag).
- Frontend: add **DOMPurify**; in `RichDocument.tsx` sanitize `html` when
  `trust !== "trusted"` before `dangerouslySetInnerHTML`; in `MermaidDiagram.tsx` set
  `securityLevel:"strict"` for untrusted.

### W4 — Store canonical DATA (not the render) in memory, keyed by `document_id`
Decouple **storage from presentation**: persist the document's *underlying structured data*
(the parsed source the LLM produced — table rows, raw JSON, etc.), NOT the rendered
html/markdown. Two coordinated homes:
- **Immortus 4D chain** (`immortus_chain_append`, `iris_ffi.py:372`): store the data with its
  current 4D coordinate `coords_from→coords_to` so it "finds its place" in the reasoning
  trajectory (lineage/placement). New call site in `_process_structured_response` when a
  `show` payload is emitted.
- **Mycelium semantic/episodic** (`episodic.py`, 384-dim embedding): store the data so it is
  **semantically retrievable** later (e.g. "the data from that table about X") via
  `mcm_recall` / `pacman_recall`.
- Keyed by a generated `document_id`; include `document_id` in `DOCUMENT_RENDER`.
- The rendered `content` becomes a *view* derived on demand — never the stored source of truth.
- **Constraints (from G1–G4):** (a) store `alternatives` alongside canonical data so
  reformat to an existing format is deterministic (G1); (b) scope retrieval by
  `document_id` / `conversation_id` to avoid stale cross-context surfacing (G2); (c) assign a
  **retention tier** — untrusted/web data shorter or isolated (G3); (d) designate one store
  as source-of-truth and reconcile to the other to prevent drift (G4).

### W5 — `reformat_document` retrieves-and-reformats (no client content, no re-render)
- Frontend `reformat_document` WS message sends `{document_id, target_format}` only (drop `content`).
- `iris_gateway._handle_reformat_document` passes `document_id` to `kernel.reformat_document`,
  which **retrieves the canonical data** from Immortus/Mycelium (by `document_id` or semantic
  query) and reformats *that data* into any presentation — table→markdown→diagram→html —
  instead of re-LLMs the previously-rendered text.
- **Deterministic-first (G1):** if `target_format` is already in the stored `alternatives`,
  return it with **no LLM call**. Only invoke the LLM for genuinely new formats, and apply it
  to the *data*, not the render.
- Bonus: data is queryable → "show me that table again" / "reformat that as a diagram" work
  from memory, not from a stale client copy.

### W6 — Testing matrix (CDD-first, multi-type — NOT unit-only)
See testing matrix below (T1–T15).

### W7 — Trajectory-conditioned retrieval (O1) 🌟
- Add a coordinate-proximity query over the Immortus 4D chain (`iris_ffi.py:372`): given the
  agent's current `coords`, return document data produced when reasoning was in a *similar
  state* (not just semantically similar).
- Exposes a novel memory primitive: "data gathered while thinking like this," distinct from
  embedding cosine similarity. Reuses the coordinate already recorded on every chain append.

### W8 — Crystallization seeding (O2) 🌟
- Store document data as Mycelium context chunks with proper coordinates so that **trusted,
  frequently-referenced data crystallizes into permanent landmarks** at the existing
  `PERMANENCE_THRESHOLD = 8` (`landmark.py:414`).
- The existing trust-cap (`landmark.py:40`, `kyudo.py:63`, 0.30) **automatically excludes
  untrusted/web data from crystallization** — no extra code needed; we just must not bypass
  it. This converts the document feature into a durable memory-formation loop.

### W9 — Proactive structured-data capture (O3)
- Extend capture beyond `show` payloads: extract structured data from *any* tool result
  (web search, file read) in the DER loop (`der_loop.py`) / `auto_research.py` into the same
  data store, so everything the agent touches becomes reformat-able.
- Scope by cost: only capture results above a relevance/structure threshold to avoid
  embedding every trivial result.

### W10 — Pheromone-reinforced reformat + cross-modal synergy (O4)
- Reinforce the reformat action's pheromone edge when used (`interpreter.py:208-212`), so the
  agent can *proactively offer* reformats of frequently-touched doc types.
- Wire reformatted views to the `speak` tool / `SpeakBroadcaster` (vocalize any view) and to
  Vision MCP (turn data into diagrams), reusing existing channels.

---

## Testing matrix (CDD-first, multi-type — NOT unit-only)

Testing is defined **before** implementation (Contract-Driven Development): the contract
and behavioral tests below are the acceptance criteria for W1–W10, not an afterthought.

| # | Type | What it verifies | Location / pattern |
|---|------|------------------|--------------------|
| T1 | **Contract (CDD)** | `DOCUMENT_RENDER` payload shape includes `trust` + `document_id`; `reformat_document` WS message is `{document_id, target_format}` (no `content`). Catches FE/BE drift. | `backend/tests/` standalone importlib (mirror `smoke_document_flow.py`) |
| T2 | **Behavioral** | `web_search` / `crawler_query` output → `untrusted` zone; local tools → `trusted`; web-using turn → fragment tagged `untrusted`. | `pacman_fragment` + `agent_kernel` pacman_store tests |
| T3 | **Invariant** | Untrusted content **never** lands in `trusted` zone (cellwall-style at `pacman_fragment` boundary). | new test mirroring `test_cellwall_untrusted_rejected_from_trusted_zone` |
| T4 | **Security** | Real XSS payload (`<img src=x onerror=alert(1)>`, `javascript:` href) in an `untrusted` html doc is stripped; mermaid `securityLevel` → `strict` for untrusted. | jest (jsdom) + backend sanitizer assertion |
| T5 | **Component** | `RichDocument` renders trusted html raw; sanitizes untrusted; `MermaidDiagram` trust-gated. | `__tests__/components/` (jest, see `OrbWorkingIndicator.test.tsx`) |
| T6 | **Integration** | Reformat via `document_id` retrieves canonical data from Immortus/Mycelium and reformats; `DOCUMENT_RENDER` preserves `trust` + `document_id`. | `backend/tests/` standalone |
| T7 | **E2E smoke** | Full loop: `document:render` → click format pill → `reformat_document` (by `document_id`) → updated `document:render`; assert no `content` sent. | `backend/tests/smoke_*` standalone (13/13-style) |
| T8 | **Regression** | Existing Mycelium trust-cap tests (`test_mycelium_kyudo_security.py`) pass; show-without-speak JSON-leak fix regression. | existing + new |
| T9 | **Data-centric retrieval** | Agent stores canonical data (not render) in Immortus 4D + Mycelium; retrieves by semantic query and reformats to N formats without client `content`. | `backend/tests/` standalone + jest |
| T10 | **Trajectory retrieval (O1)** | Coordinate-proximity query returns document data produced in a *similar reasoning state*, distinct from embedding cosine. | `backend/tests/` standalone against Immortus chain |
| T11 | **Crystallization (O2)** | Trusted, frequently-referenced document data crystallizes into a permanent landmark; untrusted data is excluded by the trust-cap (no bypass). | `backend/memory/tests/test_mycelium_*` + new |
| T12 | **Deterministic reformat (G1)** | When `target_format` ∈ stored `alternatives`, reformat returns with **no LLM call** (assert LLM not invoked). | `backend/tests/` standalone (mock LLM) |
| T13 | **Retrieval scoping (G2)** | Document data is NOT surfaced in unrelated semantic queries (no stale cross-context recall); exact reformat still works by `document_id`. | `backend/tests/` standalone |
| T14 | **Cross-protocol consistency (G4)** | Immortus ↔ Mycelium copies of the same document data stay consistent after write/update. | `backend/tests/` standalone reconciliation check |
| T15 | **Proactive capture (O3)** | Structured data from a non-`show` tool result (web/file) is captured into the store and becomes reformat-able. | `backend/tests/` standalone |

**Acceptance gate:** W1–W10 are "done" only when T1–T15 are green. No new tests written to
match code; the tests define the requirement (per project test rules).

---

## Open decisions (required before implementation)

1. **Zone naming** — add new `"untrusted"` zone, or reuse existing `"reference"` slot
   (comment says "external content (future)")? Lean: reuse `reference` to avoid touching
   the Mycelium zone enum.
2. **Which tools count as external** — `web_search` + `crawler_query` only, or also
   remote-fetching tools (MCP `send_message` results, file fetches)?
3. **Sanitization location** — frontend DOMPurify (actual XSS boundary, recommended) vs.
   backend sanitization in `build_reformat_payload`. Lean: frontend gated on `trust`.
4. **Trajectory query metric (O1/W7)** — which of the 4 coordinate dims
   (depth/clarity/novelty/drift) to weight for proximity, and the distance threshold.
5. **Crystallization seeding (O2/W8)** — auto-crystallize trusted document data at the
   existing threshold, or require an explicit "keep" signal? (Trust-cap already gates
   untrusted exclusion either way.)
6. **Proactive capture scope (O3/W9)** — which tools/results to capture, and the relevance
   threshold to bound embedding cost.
7. **Retention tier (G3)** — retention window / isolation policy for untrusted vs trusted
   document data.

---

## Verification strategy
- **CDD-first:** T1 (contract) + T2/T3 (behavioral/invariant) + T9 (data-centric) + T12
  (deterministic reformat) + T13 (scoping) are written before W1–W10 code.
- Existing Mycelium trust-cap tests (`test_mycelium_kyudo_security.py`) remain green (T8/T11).
- Standalone importlib scripts (not `pytest`) for backend contract/integration to avoid the
  ~38s numpy cold-import memory spike noted in prior plan follow-up pins.
- Frontend: `npx tsc --noEmit` clean + jest component/security tests (T4/T5) green.
- Backend: `py_compile` clean + targeted standalone tests (T1/T2/T3/T6/T7/T9/T10/T12/T13/T14/T15) green.
- E2E smoke (T7) mirrors the project's `smoke_document_flow.py` 13/13 pattern.
- Cross-protocol consistency (T14) uses the project's `mcp-eml-testing` discipline.
