# Execution Phases — read this before opening any spec

Specs are cut by **execution order**, not by topic. Each phase is self-contained: its
`requirements.md` / `design.md` / `tasks.md` carry everything needed to execute it, with no
"blocked on another spec" references.

**Execute in order. Do not start a phase until the previous one's final wave is green.**

| Phase | Spec | Status | Unblocks |
|---|---|---|---|
| **1** | [`phase-1-foundation/`](phase-1-foundation/) | **READY** — Wave 1 partially landed (`01e6625b`) | everything |
| **2** | [`phase-2-instrument/`](phase-2-instrument/) | **READY** | 3, 4, 5 validation |
| **3** | [`phase-3-local-loader/`](phase-3-local-loader/) | **READY** | 4, 5 |
| **4** | [`phase-4-encoder/`](phase-4-encoder/) | **READY** | 5 |
| 5 | `phase-5-switcher/` | not yet written | — |
| 6 | `phase-6-der-integrity/` | not yet written | — |

## What each phase covers

**Phase 1 — Foundation: budget, context window, provider registry.**
DER's budget derived from the real window; context-window precedence (override → authoritative →
table → default); local providers declarative rather than a side effect of loading; namespaced ids +
`purpose`; one process-wide registry; one provider collection keyed by id with atomic
endpoint+credential writes; flat-config migration; routing mode frozen.
*First because everything downstream is measured in tokens or looked up in the registry.*

**Phase 2 — The instrument: narration + honest live display.**
Agent-driven communication (text + TTS); task cards driven by real `TOOL_CALL` / ledger records;
live status without phantom cards; Pacman learning signal made visible; closing
`cross-thread-crawl-fix` T36 and the stale narration tests.
*Second because Phases 3–5 are validated by watching IRIS work, and the card currently misreports.*

**Phase 3 — Local model loader.**
Config derivation from parsed model metadata + hardware; GPU-only degradation ladder (ctx → batch)
scoped to `purpose == "chat"`; VRAM estimation including KV cache; per-model config cache;
symlink-aware folder scan; measured-throughput feedback loop.

**Phase 4 — Encoder.**
LFM2.5 Embedding-350M replacing BGE-M3 (CPU); chunk + max-pool for the 21% of PiNs over 512 tokens;
background re-index with dual-read and cross-space refusal; Encoder-350M for semantic step
verification and task classification; ColBERT deferred behind a measured quality gate.

**Phase 5 — Switcher UI.**
Remove the redundant Send pill; model switcher in the chat input row over configured API providers
and loaded local models; ContextPill design preserved.

## Superseded documents

These remain in the repo for history. **They are not authoritative and must not be executed
directly** — their requirements are redistributed across the phases above, and their cross-spec
"blocked on" notes no longer apply.

| Superseded | Redistributed into |
|---|---|
| `local-model-provider-parity/` | Phase 1 (REQ-1/2/3) + Phase 3 (the loader) |
| `contextpill-model-switcher/` | Phase 1 (REQ-5/6/7/8) + Phase 5 (the UI) |
| `lfm25-encoder-integration/` | Phase 4 |
| `der-loop-integrity-display/` REQ-3, REQ-5, REQ-14, REQ-15 | Phase 1 |
| `der-loop-integrity-display/` REQ-6, REQ-7, REQ-8, REQ-9 | Phase 2 |
| `der-loop-integrity-display/` REQ-11, REQ-12 | Phase 5 |
| `der-loop-integrity-display/` REQ-1, REQ-2, REQ-4, REQ-13 | Phase 6 |
| `cross-thread-crawl-fix/` T36-T38 | Phase 2 |
| `MODEL_SPEC_RECONCILIATION.md` | mostly dissolved — see below |

## Why the re-cut

The previous specs were organised by topic (local models / encoder / UI). Each was internally
coherent, but a single dependency chain ran through all three, so executing one meant stopping
partway to do half of another. `MODEL_SPEC_RECONCILIATION.md` existed only to explain how they
interlocked — which was the signal that the cut lines were wrong.

Two of the conflicts it documents **dissolve** under the phase cut rather than needing resolution:

- **M1** (two config collections both migrating `local_model_*`) — both sides are now Phase 1 REQ-6
  and REQ-8, one collection, one migrator.
- **M2** (encoders appearing in the settings Brain/Tool dropdown) — registration and the
  `purpose === "chat"` filter are both Phase 4.

The rest survive as ordinary within-phase requirements. The reconciliation doc is kept as the record
of *why* these decisions are what they are, not as something to execute against.
