# FAULTLINE — The Three-Layer Tool-Failure Taxonomy

**Status:** Implemented (session 244) · **Pin:** `pin_b808635af544` · **Module:** `backend/agent/tool_errors.py`
**Say "FAULTLINE" to reference this architecture.**

---

## 1. Why FAULTLINE exists

Before FAULTLINE, a tool failure reached DER's reviewer as a content-free string:

```python
{"success": False, "error": "crawler_query returned no usable content for query"}
```

The crawl subsystem *knew* exactly what happened — `github.com parked, reason=run_budget, 5/5 sources dead` — but that knowledge was stripped at the tool boundary. An uninformed reviewer does the only thing it can: re-plan. Same query → same results → same wall. That is how one slow GitHub page turned into a 14-minute blind-retry loop (verified live, session 244, job `40863a59…`; root cause in `pin_4979f57589c6`).

**FAULTLINE's principle:** errors are *information*. A failure must arrive at the decision-maker with its cause, its dimensions, and its original truth intact.

**Design constraint from the user (recorded verbatim intent):** this foundation is acknowledged to be **surface-level** — a scaffold expected to be improved in future iterations. It is built to be grown, not to be final.

---

## 2. The three layers

```
┌───────────────────────────────────────────────────────────────────┐
│ LAYER 1 — DIMENSIONS (stable core; hardcoded deliberately)        │
│                                                                   │
│   retryable : yes | no | maybe     ← will trying again help?      │
│   blame     : self | world | query ← whose fault is it?           │
│   info_state: blocked | missing | unknown ← does info exist?      │
│                                                                   │
│   These are INVARIANTS. "Will retrying help" is meaningful        │
│   forever. Hardcoded because they never change.                   │
├───────────────────────────────────────────────────────────────────┤
│ LAYER 2 — LABEL REGISTRY (open; data-not-code)                    │
│                                                                   │
│   A label = a named bundle of dimension values + prose.           │
│     walled        = no    / world / blocked                       │
│     rate_limited  = maybe / world / blocked                       │
│     empty         = no    / query / missing                       │
│                                                                   │
│   New label = register_error_label(...) — a DATA EDIT, never a    │
│   loop rewrite (same philosophy as verbRegistry/memoryRegistry).  │
│   Consumers understand new labels through their dimensions        │
│   immediately — zero new branches anywhere.                       │
├───────────────────────────────────────────────────────────────────┤
│ LAYER 3 — UNCLASSIFIED BUCKET (how the vocabulary evolves)        │
│                                                                   │
│   An unrecognized type is NEVER discarded. Stored raw with full   │
│   details + counted (unknown_label_counts()). Repeated unknowns   │
│   are promotion candidates via promote_unknown().                 │
│   The vocabulary grows FROM EVIDENCE.                             │
└───────────────────────────────────────────────────────────────────┘
```

### Why lessons scale automatically

The learning system stores **records**: `(dimensions, context, outcome)` — not
`if walled then X` rules. The reviewer generalizes by **similarity across
dimensions** ("retryable:no + blame:world — same shape as last time, don't
retry"). A failure mode nobody has named yet still lands near its neighbors on
the dimension space, so the system behaves sensibly toward it on day one.

---

## 3. Canonical outcome shape

Every failure leaving any tool boundary carries:

```python
{
    "success": False,
    "error": "<human message>",
    "error_type": "walled",              # Layer-2 label
    "retryable": "no",                   # Layer-1 dimension
    "blame": "world",                    # Layer-1 dimension
    "info_state": "blocked",             # Layer-1 dimension
    "details": {
        "raw": "<original exception string>",   # NEVER lost
        # ...tool-specific structured detail...
        # "unclassified": True                # only when Layer 3 caught it
    },
    "ts": 1787340000.0,
}
```

**Nothing is ever lost.** `details["raw"]` always preserves the original
exception/message. FAULTLINE adds structure on top; it never replaces truth.

---

## 4. Boundary enforcement — universal by choke point

Universality comes from **enforcement at the single doorway**, not from hoping
every tool author remembers:

```
agent_kernel / iris_gateway
        │  execute_tool(...)
        ▼
┌─────────────────────────────────────────────┐
│ ToolBridge.execute_tool()  ← THE BOUNDARY   │
│                                             │
│   result = _execute_tool_dispatch(...)      │
│   result = normalize_failure(result)        │  ← FAULTLINE choke point
│                                             │
│   • already-typed → dimensions filled in    │
│   • bare legacy error → auto-classified     │
│   • success results → untouched             │
└─────────────────────────────────────────────┘
        │
        ▼  typed outcome reaches DER reviewer / card / memory
```

Consequences:
- The ~47 legacy `{"success": False, "error": str(exc)}` sites get typed
  outcomes **without being rewritten**
- Every **future** tool inherits the taxonomy automatically
- Migrating a tool to call `tool_error()` directly only *upgrades precision*
  — it can never be forgotten

`normalize_failure` is idempotent and preserves extra keys tools attach
(`documents`, `conversations`, …).

---

## 5. Wiring into RL learning + memory

The hooks already existed; FAULTLINE feeds them:

```
tool fails
   │
   ├─► ToolBridge.execute_tool boundary ──► typed result to DER reviewer
   │                                         (branch: retry/diversify/ask/report)
   │
   ├─► _record_tool_event (FFI → SQLite system_events)
   │      payload now carries error_type / retryable / blame / info_state
   │      → episodes recallable by CAUSE ("last 3 searches hit walled github")
   │        — the fixed-field recall shape Wormhole/memoryRegistry expect
   │
   └─► DER reviewer ─► verified_label (VERIFIED/UNVERIFIED/FAILED)
          └─► task:learning emit (signal + verified_label)
                 └─► memoryRegistry "learning" kind → card badges/footnote
```

Each type teaches a different lesson:

| Type | Lesson |
|---|---|
| `transient` | Retrying was reasonable — keep retry policy |
| `walled` | Stop serving this domain for similar queries (feeds SourceRegistry down-weighting) |
| `empty` | The query was the problem — rephrase, don't repeat |
| `invalid_params` | The planner made a bad call — fix the call |

---

## 6. Crawler integration (the motivating case)

| Piece | Where | What it does |
|---|---|---|
| Total arun ceiling | `crawler_engine._ARUN_TOTAL_S` (25s, env `IRIS_CRAWL_ARUN_TOTAL_S`) | crawl4ai's `page_timeout` covers navigation only; this caps the whole fetch. Timeout pages flow into the existing unusable-page lane |
| Plain-HTTP salvage | `crawl_runner` merge (pre-existing) | Re-fetches timed-out URLs over plain HTTP in seconds — server-rendered sites (GitHub) recover fully. Bidirectional: fail fast inbound, recover fast outbound |
| Park ledger | `orchestrator._parks_by_job` | `_park_source` records `(domain, wall_kind)` per run |
| `park_summary` | `CrawlResult.park_summary` | `"5/5 sources parked (github.com: run_budget x5; distinct domains: 1)"` |
| Typed outcome | `tool_bridge._execute_crawler_query` | `error_type="sources_parked"` + summary + explicit guidance *"A retry of the SAME search will fail identically"* |
| Futile-retry guard | `orchestrator.research()` | Skips the broadened Exa re-plan when all sources parked on ONE domain |

**Deliberately rejected:** domain-diversity caps — they block legitimate
multi-page sources (release lists live as many URLs on one domain).

---

## 7. Extension protocol

1. **New failure mode appears** → it lands in Layer 3, stored raw + counted
2. **Evidence accumulates** → `unknown_label_counts()` shows the frequency
3. **Promote** → `promote_unknown(label, retryable, blame, info_state, description)`
4. Done. Reviewer, memory, and future cards understand it through dimensions —
   no consumer code changed.

Seeded vocabulary today: `transient`, `walled`, `rate_limited`, `empty`,
`invalid_params`, `capability_missing`, `crashed`.

---

## 8. Current coverage & roadmap (the surface-level part)

| Coverage | State |
|---|---|
| Crawler paths (`crawler_query`, `web_search`, `open_url`) | Fully typed (5 sites) |
| Boundary auto-classification | Live at `execute_tool` — covers ALL 52 failure sites |
| Learning-record enrichment | Live in `_record_tool_event` payload |
| Per-tool precise labels (media, research, documents, dev/git, MCP) | **Roadmap** — currently auto-classified from message heuristics; migrate high-value tools to direct `tool_error()` calls for exact labels |
| Card rendering of new labels | Via memoryRegistry edit (designed path), not yet exercised |
| SourceRegistry domain down-weighting from parks | Roadmap — park ledger has the data |

Known pre-existing crawler-suite failures (10) are environmental/live-network
and unrelated (stash-control verified, session 244).

---

## 9. Test map

`backend/tests/unit/test_tool_errors.py` — 17 tests:

- Layer 1: seeded labels carry valid dimensions
- Layer 2: canonical shape; registry growth API; invalid registrations refused
- Layer 3: unknown labels stored + counted + flagged, never dropped; promotion works
- Classifier: exception-type mapping; unknown → `crashed`
- Boundary: legacy errors typed; extra keys survive; idempotence; success untouched;
  park-language messages classify as `walled`

---

## 10. Related pins & sessions

- `pin_b808635af544` — FAULTLINE design anchor (three layers, user caveat)
- `pin_4979f57589c6` — run-budget root cause (88.6s GitHub page vs 90s budget)
- `pin_5c3c379e2505` — bidirectional fetch optimization handoff
- Session 244 · live-test campaign per `pin_4c8330dffa72` / `pin_5d9ec24c241e`
