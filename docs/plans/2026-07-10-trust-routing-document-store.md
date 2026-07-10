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

### W4 — Build `DocumentStore` (server-side, keyed)
- New `backend/agent/document_store.py`, reusing `ConversationContextStore`'s SQLite-WAL
  pattern. Schema: `document_id PK, conversation_id, content, format, alternatives(JSON),
  trust, created_at`.
- `_process_structured_response` and `reformat_document` **write the canonical original**
  keyed by a generated `document_id`, and include `document_id` in `DOCUMENT_RENDER`.

### W5 — Rewire reformat to be server-keyed (no client content round-trip)
- Frontend `reformat_document` WS message sends `{document_id, target_format}` only
  (drop `content`).
- `iris_gateway._handle_reformat_document` passes `document_id` to
  `kernel.reformat_document`, which **looks up the stored original**, reformats, updates
  the store, emits `DOCUMENT_RENDER` with same `document_id` + preserved `trust`.
- Bonus: store is queryable → "show me that table again" becomes possible.

### W6 — Tests + verification
- Unit: `pacman_fragment` routes `web_search` → `untrusted` zone; trusted tools stay trusted.
- Unit: regression test for the show-without-speak JSON-leak fix.
- Integration: reformat via `document_id` returns correct payload; untrusted `html`
  sanitized in render.
- Regression: existing Mycelium trust-cap tests still pass.

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
- Existing Mycelium trust-cap tests (`test_mycelium_kyudo_security.py`) remain green.
- New unit tests for `pacman_fragment` zone routing + show-without-speak regression.
- New integration test for `document_id`-based reformat + untrusted-html sanitization.
- `npx tsc --noEmit` clean on frontend; backend `py_compile` + targeted pytest.
