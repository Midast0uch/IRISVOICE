# Plan: Trust-Routing for Web Content + Server-Side Document Store

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

---

## Unifying design: a single `trust` signal

`trust ∈ {"trusted", "untrusted"}`, derived from **"did this content touch external/web
sources?"** Propagates to three consumers through one flag:

```
web/crawler tool runs
        │
        ├─► pacman_fragment: zone="untrusted"  (episodic + Mycelium trust-cap)
        │
        ├─► DOCUMENT_RENDER.trust  ──► frontend sanitizes html/mermaid when untrusted
        │
        └─► DocumentStore record.trust  (preserved across reformats)
```

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

### W5 — `reformat_document` retrieves-and-reformats (no client content, no re-render)
- Frontend `reformat_document` WS message sends `{document_id, target_format}` only (drop `content`).
- `iris_gateway._handle_reformat_document` passes `document_id` to `kernel.reformat_document`,
  which **retrieves the canonical data** from Immortus/Mycelium (by `document_id` or semantic
  query) and reformats *that data* into any presentation — table→markdown→diagram→html —
  instead of re-LLMs the previously-rendered text.
- For deterministic transforms (table→csv) the LLM step can be skipped; for freeform formats
  the existing LLM reformat applies to the *data*, not the render.
- Bonus: data is queryable → "show me that table again" / "reformat that as a diagram" work
  from memory, not from a stale client copy.

### W6 — Testing matrix (CDD-first, multi-type — NOT unit-only)

Testing is defined **before** implementation (Contract-Driven Development): the contract
and behavioral tests below are the acceptance criteria for W1–W5, not an afterthought.

| # | Type | What it verifies | Location / pattern |
|---|------|------------------|--------------------|
| T1 | **Contract (CDD)** | `DOCUMENT_RENDER` payload shape includes `trust` + `document_id`; `reformat_document` WS message is `{document_id, target_format}` (no `content`). Catches frontend/backend drift. | `backend/tests/` standalone importlib (mirror `smoke_document_flow.py` to avoid pytest memory spike) |
| T2 | **Behavioral** | `web_search` / `crawler_query` output → `untrusted` zone; local tools (`ask_user`, `speak`) → `trusted`; a turn that used web mid-conversation → turn fragment tagged `untrusted`. | `pacman_fragment` + `agent_kernel` pacman_store tests |
| T3 | **Invariant** | Untrusted content **never** lands in the `trusted` zone (cellwall-style assertion at the `pacman_fragment` boundary). | new test mirroring `test_cellwall_untrusted_rejected_from_trusted_zone` |
| T4 | **Security** | Real XSS payload (`<img src=x onerror=alert(1)>`, `javascript:` href) injected into an `untrusted` html doc is stripped/neutralized before render; mermaid `securityLevel` flips to `strict` for untrusted. | jest (jsdom) + backend sanitizer assertion |
| T5 | **Component** | `RichDocument` renders trusted html raw; sanitizes untrusted html; `MermaidDiagram` trust-gated `securityLevel`. | `__tests__/components/` (jest, already wired — see `OrbWorkingIndicator.test.tsx`) |
| T6 | **Integration** | Reformat via `document_id` retrieves the **canonical data** from Immortus/Mycelium and reformats; updated `DOCUMENT_RENDER` preserves `trust` + `document_id`. | `backend/tests/` standalone |
| T7 | **E2E smoke** | Full loop: `document:render` → click format pill → `reformat_document` (by `document_id`) → updated `document:render`; assert no `content` sent by client. | `backend/tests/smoke_*` standalone (13/13-style) |
| T8 | **Regression** | Existing Mycelium trust-cap tests (`test_mycelium_kyudo_security.py`) still pass; show-without-speak JSON-leak fix regression. | existing + new |
| T9 | **Data-centric retrieval** | Agent stores canonical data (not render) in Immortus 4D + Mycelium; can retrieve it by semantic query and reformat to N formats (table→markdown→diagram→html) without the client sending `content`. | `backend/tests/` standalone + jest |

**Acceptance gate:** W1–W5 are "done" only when T1–T9 are green. No new tests written to
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

---

## Verification strategy
- **CDD-first:** T1 (contract) + T2/T3 (behavioral/invariant) + T9 (data-centric retrieval) are written before W1–W5 code.
- Existing Mycelium trust-cap tests (`test_mycelium_kyudo_security.py`) remain green (T8).
- Standalone importlib scripts (not `pytest`) for backend contract/integration to avoid the
  ~38s numpy cold-import memory spike noted in prior plan follow-up pins.
- Frontend: `npx tsc --noEmit` clean + jest component/security tests (T4/T5) green.
- Backend: `py_compile` clean + targeted standalone tests (T1/T2/T3/T6/T7/T9) green.
- E2E smoke (T7) mirrors the project's `smoke_document_flow.py` 13/13 pattern.
