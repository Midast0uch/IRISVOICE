# Trust-Routing + Data-Centric Document Memory

**Status:** COMPLETE (W1–W10) · **Branch:** `feat/agent-multi-step-tool-execution`
**Plan:** `docs/plans/2026-07-10-trust-routing-document-store.md`
**Tests:** W1–W10 standalone CDD suites + full regression, all green.

---

## 1. Why this exists

IRIS is a voice-controlled desktop assistant. When it answers, it frequently
produces or retrieves **structured data** — a web search result, a table, a
diagram, a file's contents. Before this work that data was:

- **Lost after the turn** — only the final prose reply was kept; the source
  table/JSON the user actually wanted was gone.
- **Trust-blind** — a web result scraped from an untrusted site and a file the
  user authored locally were treated identically, so untrusted content could
  leak into permanent memory or be re-rendered without sanitization.
- **Non-reformatable** — you could not later say "show that as a bullet list"
  because the canonical data was never stored.

Three investigation findings drove the design (see plan §Investigation findings):

1. **The `trust` signal was computed but never threaded through.** `pacman_fragment`
   already knew whether a tool was external (`web_search`, `crawler_query`); the
   turn-level zone was computed but discarded before it reached storage/render.
2. **Reformatting was format-conversion, not data-retrieval.** The old
   `reformat_document` tried to *convert* an already-rendered blob instead of
   retrieving the *canonical* data and re-presenting it — fragile and LLM-heavy.
3. **Crystallization had no data-seeding path.** Mycelium landmarks (permanent
   memory) were seeded from conversation text, never from the structured
   documents the agent had actually produced.

**Core insight:** one boolean-ish signal — `trust` (`trusted` vs `untrusted`) —
plus a single canonical store keyed by `document_id` unlocks *routing,
sanitization, retrieval, reformat, crystallization, proactive capture, and
cross-modal views* without per-feature plumbing.

---

## 2. The unifying design: one `trust` signal, three consumers

```
                         tool result / LLM "show" payload
                                      │
                                      ▼
                       ┌──────────────────────────────┐
                       │  trust = is_external_tool?    │   pacman_fragment.W2
                       │   external → "untrusted"       │
                       │   else     → "trusted"         │
                       └──────────────────────────────┘
                                      │
            ┌──────────────┬──────────┴───────────┬─────────────────┐
            ▼              ▼                       ▼                 ▼
     [ROUTING]      [SANITIZATION]          [STORAGE]          [RETRIEVAL/
   reference zone    DOMPurify gated          DocumentDataStore   CRYSTALLIZATION]
   (episodic)        on trust≠trusted         + Mycelium          trust-cap excludes
                                                + Immortus          untrusted
```

`trust` is decided **once** at the turn/tool boundary and then carried on every
downstream object (`DocumentData`, `DOCUMENT_RENDER` event, Mycelium fragment,
Immortus coordinate, reformat request). Three independent consumers read it;
none recomputes it.

---

## 3. Layer-by-layer

### Layer 1 — Trust-zone routing (W1 / W2)
- **What:** `pacman_fragment.is_external_tool(tool_name)` classifies
  `web_search` / `crawler_query` as external. The agent turn records a
  per-turn `_turn_touched_external` flag; when set, the turn's zone is
  `reference` (the untrusted membrane) instead of `trusted`.
- **Where:** `backend/agent/mcm_protocol/actions/pacman_fragment.py`
  (`_EXTERNAL_TOOLS` frozenset; `is_external_tool`); `agent_kernel.py`
  (`_pacman_zone_for_turn`, `_process_structured_response`).
- **Why:** External (web) content must never enter the trusted user-context
  zone. Routing at the zone boundary is the cheapest possible trust gate and
  reuses the existing Pacman lifecycle (Domain 1.8).
- **Test:** `test_pacman_fragment_zone.py` (5/5), `test_agent_kernel_turn_zone.py` (10/10).

### Layer 2 — Frontend sanitization (W3)
- **What:** `RichDocument.tsx` runs `DOMPurify.sanitize(html, {ADD_TAGS, ADD_ATTR})`
  **only when `trust !== "trusted"`**; `MermaidDiagram.tsx` sets
  `securityLevel: "strict"` for untrusted diagrams (prevents
  `clickNodeFn`/XSS injection via mermaid definitions). Trusted content skips
  sanitization (no double-processing of user-authored HTML).
- **Where:** `components/chat/RichDocument.tsx`, `components/chat/MermaidDiagram.tsx`,
  `components/chat/chat-view.tsx`, `DocumentPanel.tsx`; `package.json` pins
  `dompurify ^3.4.11`; `__tests__/components/trust-routing.test.tsx`.
- **Why:** Untrusted web HTML/diagrams must be neutralized before they reach the
  DOM. Gating on `trust` (not `trusted`) means authored content is never
  silently stripped, while scraped content is always cleaned.
- **Test:** jest 4/4; `npx tsc --noEmit` clean.

### Layer 3 — Canonical data storage (W4)
- **What:** Every rendered document gets a `document_id = uuid4()`.
  `_store_document_data(document_id, show, trust, turn_id, conversation_id)`
  writes the **canonical** data to three stores:
  1. `DocumentDataStore` (SQLite-WAL, keyed by `document_id`) — source of truth
     for reformat (G4).
  2. Mycelium `episodic.fragment_and_store(chunk_type="document_data")` — semantic
     recall.
  3. Immortus 4D chain via `immortus_chain_append(file_path=document_id,
     coords_from=<real trajectory coordinate>)` — trajectory retrieval (W7).
- **Where:** `agent_kernel.py:_store_document_data`; `backend/agent/document_store.py`
  (`DocumentDataStore`); `backend/agent/caducean_trajectory.py`
  (`get_latest_coordinate`).
- **Why:** A single stable `document_id` is the join key across all three memory
  layers. Storing canonical data (not a rendered blob) is what makes W5 reformat
  possible. `coords_from` is the agent's actual reasoning coordinate at
  production time — the basis for "data I gathered while thinking like this."
- **Test:** `test_document_data_store.py` (21/21).

### Layer 4 — Data-centric reformat (W5)
- **What:** `reformat_document(document_id, target_format, …)` retrieves the
  canonical data by `document_id` and re-presents it in `target_format`
  (markdown, json, text, html, diagram, …). **Deterministic-first:** if the
  requested variant is already stored, it is returned with **no LLM call**; the
  LLM fallback only runs when no variant exists (and its result is cached as a
  new variant).
- **Where:** `agent_kernel.py:reformat_document`; `document_store.py:get_variant`
  / `add_variant`.
- **Why (G1 — deterministic):** Reformatting a table→bullets should be a string
  lookup, not a nondeterministic model call. This removes latency, cost, and
  hallucination risk from the most common operation.
- **Test:** `test_document_reformat_by_id.py` (15/15).

### Layer 5 — Trajectory-conditioned retrieval (W7 / O1)
- **What:** `retrieve_documents_by_trajectory(coords, …)` queries the Immortus
  4D chain for documents produced near a given reasoning coordinate, returning
  `document_id`s that are then hydrated from `DocumentDataStore`. Implemented in
  both the **C++ core** (`iris_core.dll`, `immortus_chain_query_by_coordinate`)
  and a **Python fallback** (`_PythonFallbackEngine`) behind a `hasattr` guard.
- **Where:** `agent_kernel.py:retrieve_documents_by_trajectory`;
  `backend/gateway/iris_ffi.py`; `src-tauri/src/iris_core/iris_core.cpp`.
- **Why:** Embedding cosine similarity answers "semantically similar." Trajectory
  proximity answers "data I gathered while thinking *like this*" — a different,
  complementary axis that lets the agent recall the right artifact mid-task
  without a semantic search. Distinct from O2/O3.
- **Test:** `test_trajectory_retrieval.py` (15/15); C++ DLL rebuilt (`756b4405`).

### Layer 6 — Crystallization seeding (W8 / O2)
- **What:** When a document is stored, `MyceliumInterface.ingest_document_data`
  seeds a **trust-routed** Mycelium node: trusted data → `VERIFIED` → `context`
  space (eligible to crystallize); untrusted data → `EXTERNAL` → `toolpath`
  space only (never the trusted zone). `crystallize_landmark` gained a
  `source_channel` param. Trusted nodes crystallize at `PERMANENCE_THRESHOLD=8`
  activations; the Mycelium trust-cap (0.30) **auto-excludes** untrusted/web
  data from permanent memory.
- **Where:** `backend/memory/mycelium/interface.py` (`ingest_document_data`,
  `crystallize_landmark`); `landmark.py` (`PERMANENCE_THRESHOLD=8`,
  `_TRUST_CAP_FRACTION=0.30`); `kyudo.py` (trust cap).
- **Why:** Permanent memory must be earned by *trusted, repeatedly-used* data.
  Web scrapes should inform the current task but never become a permanent
  belief. The trust-cap is the firewall.
- **Test:** `test_crystallization_seeding.py` (7/7) — trusted→permanent at 8;
  untrusted→never trusted zone, crystallize returns None.

### Layer 7 — Proactive capture (W9 / O3)
- **What:** `_capture_tool_result(tool_name, result, conversation_id, …)` persists
  **any** non-trivial tool result (web_search, crawler_query, read_file, …) into
  the same `DocumentDataStore`, so it becomes reformat-able like an LLM `show`.
  Gated by `_is_capture_worthy` (skips `None`, `{"error":…}`, <50-char trivial,
  numeric `relevance`/`score` < 0.30). Hooked into the DER loop tool-execution
  path (`_execute_plan_der`, after `step_result = str(raw)`) inside a
  non-blocking try/except.
- **Where:** `agent_kernel.py:_capture_tool_result`, `_is_capture_worthy`,
  DER hook; trust via `is_external_tool`.
- **Why (G2 — scoping):** Capture must not embed every trivial result (cost,
  noise). The threshold gate keeps the store signal-dense. Hooking at the DER
  tool boundary means *everything the agent touches* is available for reformat
  without per-tool wiring.
- **Test:** `test_proactive_capture.py` (16/16).

### Layer 8 — Pheromone reinforcement + cross-modal synergy (W10 / O4)
- **What:**
  - `DocumentDataStore` gains **reformat pheromone edges**:
    `record_reformat(from→to)` (weight compounds, bounded 100.0),
    `get_reformat_edges`, `predict_next_format`.
  - `reformat_document` reinforces the `from_format → to_format` edge on **every**
    reformat (deterministic + LLM paths) — frequently-reformatted doc types
    become "sticky."
  - `suggest_reformat(document_id)` — the proactive-offer substrate: returns the
    most-reinforced next format for a doc's type (or None).
  - `vocalize_document(…)` — reformat → `SpeakTool.speak` (existing TTS channel).
  - `diagram_document(…)` — reformat to `diagram` (mermaid) format (the
    cross-modal "turn data into a diagram" synergy; Vision MCP only *analyzes*
    screens, so no separate generator is wired).
- **Where:** `document_store.py` (edges table + 3 methods); `agent_kernel.py`
  (`_record_reformat_edge`, `suggest_reformat`, `vocalize_document`,
  `diagram_document`); `backend/agent/tools/speak_tool.py`.
- **Why:** The interpreter already predicts next actions from pheromone edge
  weights; reformat usage is now one of those edges, so the agent can *offer* a
  reformat of a frequently-touched doc type. Cross-modal views reuse channels
  that already exist (SpeakTool, reformat's `diagram` format) — free synergy.
- **Test:** `test_reformat_pheromone.py` (11/11).

---

## 4. Cross-cutting constraints (G1–G4) and how they are satisfied

| Constraint | Requirement | Satisfied by |
|-----------|------------|--------------|
| **G1 Deterministic** | Reformat must not call LLM when avoidable | W5 deterministic-first variant lookup |
| **G2 Scoping** | Don't embed trivial/low-signal data | W9 `_is_capture_worthy` threshold gate |
| **G3 Retention** | Permanent memory only from trusted, reused data | W8 trust-cap + `PERMANENCE_THRESHOLD=8` |
| **G4 Cross-protocol** | Same data reachable from backend + frontend + MCP | Single `document_id` join key across `DocumentDataStore` / Mycelium / Immortus; `DOCUMENT_RENDER` event carries `trust` + `document_id` to the UI |

---

## 5. End-to-end data flow

```
Agent turn
  │  LLM returns {"show": {...}}  OR  tool returns result
  ▼
_pacman_zone_for_turn()  ──►  trust = "untrusted" if external else "trusted"
  │
  ├─ W3 ► DOCUMENT_RENDER event {document_id, trust, format, content}
  │        └─► Frontend: DOMPurify (if trust≠trusted) + Mermaid strict
  │
  ├─ W4 ► _store_document_data(document_id, show, trust, …)
  │        ├─ DocumentDataStore.store(...)            [source of truth]
  │        ├─ Mycelium.fragment_and_store(...)        [semantic recall]
  │        ├─ Immortus.chain_append(coords_from=...)  [trajectory recall]
  │        └─ W8 ► Mycelium.ingest_document_data(...)  [crystallization seed]
  │
  └─ W9 ► (tool results only) _capture_tool_result(...) ─► _store_document_data

Later: user says "show that as bullets"
  │
  ▼
reformat_document(document_id, "markdown")
  ├─ W5 ► DocumentDataStore.get_variant("markdown")  ── found? return (no LLM)
  │                                          └─ miss? LLM fallback → add_variant (cache)
  ├─ W10► record_reformat(from→to)  ── reinforce pheromone edge
  └─ emit DOCUMENT_RENDER (reformatted)

Cross-modal (W10):
  vocalize_document(id) ─► reformat ─► SpeakTool.speak
  diagram_document(id)  ─► reformat("diagram") ─► mermaid string
  suggest_reformat(id)  ─► predict_next_format(doc.format) ─► offer to user

Retrieval (W7):
  retrieve_documents_by_trajectory(coords) ─► Immortus 4D query ─► document_ids
                                          ─► DocumentDataStore hydrate
```

---

## 6. Trust model & security

- **Single decision point:** `trust` is derived once (`is_external_tool` /
  `_pacman_zone_for_turn`). No consumer recomputes it.
- **External = untrusted:** `web_search`, `crawler_query` only (frozen set).
- **Three firewalls:**
  1. **Routing** — untrusted content lands in the `reference` zone, never the
     trusted user-context zone (W1/W2).
  2. **Sanitization** — untrusted HTML/diagrams are DOMPurified / mermaid-strict
     before DOM (W3).
  3. **Crystallization** — the Mycelium trust-cap (0.30) prevents untrusted data
     from becoming permanent memory (W8).
- **Capture scoping** — only non-trivial, non-error, sufficiently-relevant tool
  results are stored (W9), limiting both cost and attack surface.

---

## 7. Testing matrix

| Test | Wave | File | Result |
|------|------|------|--------|
| T1 contract | W1 | `test_pacman_fragment_zone.py` | 5/5 |
| T2 behavioral | W1/W2 | `test_agent_kernel_turn_zone.py` | 10/10 |
| T3 invariant | W2 | (in T2) | — |
| T4 security | W3 | jest `trust-routing.test.tsx` | 4/4 |
| T5 component | W3 | jest (above) | 4/4 |
| T6 integration | W4/W5 | `test_document_data_store.py` | 21/21 |
| T7 e2e smoke | all | `smoke_document_flow.py` | 14/14 |
| T8 regression | all | Mycelium trust-cap suite | green |
| T9 data-centric retrieval | W4/W7 | (in T6/T10) | — |
| T10 trajectory retrieval | W7 | `test_trajectory_retrieval.py` | 15/15 |
| T11 crystallization | W8 | `test_crystallization_seeding.py` | 7/7 |
| T12 deterministic reformat | W5 | (in T6) | — |
| T13 retrieval scoping | W9 | (in T15) | — |
| T14 cross-protocol | G4 | mcp-eml discipline | green |
| T15 proactive capture | W9 | `test_proactive_capture.py` | 16/16 |
| T16 pheromone + cross-modal | W10 | `test_reformat_pheromone.py` | 11/11 |

All backend suites are **standalone CDD scripts** (no `test_` prefix, `REPO_ROOT`
on `sys.path`, `check()` helper) to avoid the ~38s numpy cold-import memory
spike of the full `pytest` collection.

---

## 8. File reference index

| Concern | File |
|--------|------|
| External-tool classification | `backend/agent/mcm_protocol/actions/pacman_fragment.py` |
| Turn trust / storage orchestration | `backend/agent/agent_kernel.py` (`_process_structured_response`, `_store_document_data`, `reformat_document`, `_capture_tool_result`, W10 methods) |
| Canonical store + pheromone edges | `backend/agent/document_store.py` |
| Trajectory coordinate | `backend/agent/caducean_trajectory.py` |
| Mycelium seed / crystallization | `backend/memory/mycelium/interface.py`, `landmark.py`, `kyudo.py` |
| C++ trajectory query | `src-tauri/src/iris_core/iris_core.cpp`, `backend/native/iris_core.dll` |
| Frontend render + sanitize | `components/chat/RichDocument.tsx`, `MermaidDiagram.tsx`, `chat-view.tsx`, `DocumentPanel.tsx` |
| TTS cross-modal | `backend/agent/tools/speak_tool.py` |
| Plan / GOALS | `docs/plans/2026-07-10-trust-routing-document-store.md`, `bootstrap/GOALS.md` (Domain 20) |

---

## 9. Open items / future

- **Proactive offer UI:** `suggest_reformat` is the substrate; wiring it into the
  Director's suggestion stream / a chat affordance is a follow-up (agent-behavior
  layer, not part of this plan's testable core).
- **Vision diagram generation:** if a true "data → diagram image" generator is
  added later, `diagram_document` is the single seam to extend.
- **Pheromone decay:** reformat edges currently only grow (bounded at 100.0); a
  decay pass could keep suggestions current as usage patterns shift.
