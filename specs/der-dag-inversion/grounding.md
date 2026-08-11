# Grounding — Wave 5 (Ontology T19–T24)

Phase -1.0 symbol grounding table. Verified 2026-08-07 against the live repo.

| Symbol the spec names | Status | Evidence (file:line) | Created by |
|---|---|---|---|
| `NodeRecord` | EXISTS | backend/agent/der_loop.py:70; `node_type` field :99 (default "step") | — |
| `SubLoopFootprint` | EXISTS | backend/agent/der_loop.py:171 (backward-compat subclass) | — |
| `_der_finalize_step` | EXISTS | backend/agent/agent_kernel.py:9451 | — |
| node-record stamp block | EXISTS | agent_kernel.py:10230–10274 (outcome, verified_fraction, mediator, coupling decision) | — |
| chain append | EXISTS | agent_kernel.py:10315–10331 (`durability_submit` → `ffi_immortus_chain_append`, shape-agnostic) | — |
| plan→queue NodeRecord | EXISTS | agent_kernel.py:5684–5687 (node_type="step" for top-level plan steps) | — |
| split children NodeRecord | EXISTS | agent_kernel.py:7886–7889 (node_type="sub_loop") | — |
| `DOMAIN_IDS` (13 topics) | EXISTS | backend/memory/mycelium/spaces.py:89–103 | — |
| `_DOMAIN_KEYWORDS` (keyword → domain) | EXISTS | backend/memory/mycelium/extractor.py:80–105 | — |
| domain extraction (free-text → registry) | EXISTS | extractor.py:187–193 | — |
| `domain_windings(voice|der|research)` | EXISTS | backend/agent/coupled_registry.py:83 | — |
| winding classify site | EXISTS | agent_kernel.py:10107 (`"voice" if from_voice else "der"`) | — |
| `classify_failure` (failure class) | EXISTS | backend/agent/der_execution_ledger.py:85 | — |
| `PinStore.link` | EXISTS | backend/memory/pin_store.py:238 (INSERT mycelium_pin_links; NO vocabulary enforcement) | — |
| `PinStore.linked` (BFS) | EXISTS | pin_store.py:408 | — |
| `mycelium_pin_links` schema | EXISTS | backend/memory/db.py:339–348 (relationship free string) | — |
| `ffi_immortus_chain_append` | EXISTS | backend/gateway/iris_ffi.py:1411 | — |
| `immortus_chain_append` (shape-agnostic) | EXISTS | iris_ffi.py:744–789 (introspects cols, lands mediator if present) | — |
| `memory_chain` CREATE + idempotent ALTER | EXISTS | iris_ffi.py:605–671 | — |
| `CaduceanTrajectoryRecorder.record` | EXISTS | backend/agent/caducean_trajectory.py:206 (domain param default "general") | — |
| `_SQL_ADD_DOMAIN_COLUMN` (ALTER pattern) | EXISTS | caducean_trajectory.py:125–127 | — |
| mid-loop episodic retrieval | EXISTS | agent_kernel.py:5898–6001 (`retrieve_similar` → hints) | — |
| `_get_failure_warnings` (AVOID path) | EXISTS | agent_kernel.py:4108 | — |
| `RecallDecoder._resolve_predict` | EXISTS | backend/agent/recall_decoder.py:454 | — |
| `MemoryInterface._mycelium` | EXISTS | backend/memory/interface.py:74 | — |
| `MemoryInterface.episodic.db` (app-store conn) | EXISTS | interface.py:55 | — |
| `initialise_mycelium_schema` (pin_links in app store) | EXISTS | backend/memory/db.py:154, :339 | — |
| `get_trajectory_recorder` | EXISTS | used at agent_kernel.py:10117 | — |

## Symbols to CREATE in this wave (no collisions with existing names)

| Symbol | Task | Home |
|---|---|---|
| `resolve_topic_domain(text)` | T19 | extractor.py (reuses `_DOMAIN_KEYWORDS`; returns registry key, else "general" + log) |
| `_der_execution_domain(from_voice, task_class)` | T19 | agent_kernel.py (voice\|der\|research from winding) |
| `NodeRecord.topic_domain / execution_domain / committed_decision` | T19 | der_loop.py |
| chain-row cols `node_type / topic_domain / execution_domain` | T19 | iris_ffi.py (CREATE + ALTER + shape-agnostic insert) |
| `LINK_VOCABULARY` + `PinStore.link` rejection | T20 | pin_store.py |
| DER link writer (parent/depends_on/sub-loop/failed_like) | T20 | agent_kernel.py finalize + der_loop.py |
| recall filter + widen-order helper | T21 | new small module (backend/memory/mycelium/recall_filters.py) |
| `compute_domain_aggregates` (PhysicsAggregate) | T22 | caducean_trajectory.py |
| `ontology.md` + CI schema-version check | T23 | specs/der-dag-inversion/ontology.md + scripts/validate_ontology_schema.py |
| tests CT-ON1..4 + behavioral failed_like walk | T24 | backend/tests/contract/* + backend/tests/behavioral/* |

## Design decisions locked (from requirements.md Decisions Locked)

- **Two domain axes, registry-backed, never free text.** topic_domain ← mycelium DOMAIN_IDS; execution_domain ← voice|der|research. Unknown → general/unknown + logged (REQ-18 AC3).
- **One shared link store, extended not duplicated.** DER relationships land in the proven mycelium link vocabulary (documents|references|implements|depends_on|contains|related_to) plus derives_from|part_of|relevant_to|failed_like. No second edge store (REQ-19).
- **Ordering rule 2: REQ-19 AC2b before any link write.** Vocabulary disambiguated in ontology.md BEFORE the first link write (T23 doc precedes T20 writes).
