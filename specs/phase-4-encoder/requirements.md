# Requirements: Phase 4 — LFM2.5 Encoder Integration

> **Execution position: FOURTH.** Blocked on Phase 1 (registry, ids, `purpose`) and Phase 3
> (CPU device policy).
>
> **Supersedes** `lfm25-encoder-integration/` entirely. That document is history; **this file is
> authoritative.** Everything needed is here — do not open it.

## Decisions Locked

Resolved with the user 2026-07-28. Do **not** re-litigate.

1. **Zero-shot only.** No fine-tuning, adapters, or distillation. If zero-shot quality is
   insufficient that is a *finding*, not a licence to train.
2. **Embedding-350M replaces BGE-M3; Encoder-350M does not.** Different models, different jobs.
   `LFM2.5-Embedding-350M` is a dense bi-encoder producing a 1024-dim sentence vector — a drop-in
   for what IRIS actually uses BGE-M3 for. `LFM2.5-Encoder-350M` is a base masked-LM backbone with
   no sentence head; it is used for **classification/scoring**, never retrieval vectors.
3. **Runtimes differ.** Encoder-350M runs in-process via `transformers` + `torch` (safetensors,
   needs a task head). Embedding-350M runs through the GGUF path as a `purpose="embedding"` provider.
4. **Both run on CPU** — ~350M params each; keeps VRAM for the chat model, which is what the
   ≥25 tok/s target depends on.
5. **Long PiNs are chunked and max-pooled at query time.** 512-token window; **21% of measured PiNs
   exceed it**. Max-pool not mean-pool: a long document matching strongly in one section should
   score on that section, not have it averaged away.
6. **Re-index runs in the background with dual-read.** A PiN is not migrated until its new vector is
   durably written.
7. **ColBERT-350M is deferred behind a quality gate.** Specified so the seam exists; not built until
   Embedding-350M's measured retrieval quality is known.

## Introduction

Two places where a small encoder does the job better, and one where a smaller model does the same job.

- **Retrieval** runs on BGE-M3 (~2.3 GB) but uses only its dense 1024-dim output
  ([`embedding.py:11`](backend/memory/embedding.py:11) — *"Only the dense 1024-dim vector is
  persisted by IRIS today"*). The sparse and multi-vector outputs that justify its size are dead
  weight.
- **Task classification** is keyword-set intersection
  ([`kyudo.py:566-588`](backend/memory/mycelium/kyudo.py:566)) — code keywords, then research, then
  planning, then *"fewer than 20 words → `quick_edit`"*. It cannot classify vocabulary it was not given.
- **Step verification** is substring containment
  ([`agent_kernel.py:7156`](backend/agent/agent_kernel.py:7156) —
  `sum(1 for a in _assertions if a.lower() in result.lower())`). A step satisfying its expected
  output in different words scores **0.0** and is graded FAILED.

The last is most consequential: `_verified_fraction` feeds `_verify_step_result`'s bands
([`:7172-7175`](backend/agent/agent_kernel.py:7172)) and, through the ledger, the outer loop's
self-tuning signal — which Phase 6 repairs.

**The silent-degradation problem.** BGE-M3 and Embedding-350M are **both 1024-dim**. Comparing
across the two spaces produces a plausible number, not an error. A dimension change would have
crashed safely; this one just returns worse results. REQ-3 exists for that specifically.

### Success criteria

- BGE-M3 off the default path; Embedding-350M serves retrieval at the same 1024 dimensions, on CPU,
  with measured recall no worse than baseline on a fixed probe set.
- A PiN longer than 512 tokens is retrievable by content from **any** of its sections.
- Re-index completes in the background with no retrieval outage and no restart.
- `_verified_fraction` scores a semantically-correct paraphrase above 0.0 while still scoring a stub
  at exactly 0.0.
- Task classification handles vocabulary absent from the keyword sets.
- No chat model loses context window to either encoder.

## Requirements

---

### REQ-1: Embedding-350M replaces BGE-M3 behind the existing service interface

**User Story:** As a maintainer I want the smaller embedder swapped in without touching every call
site, so the change is reversible and its effect measurable.

**Verified:** `EmbeddingService` is already the single chokepoint — *"All memory components share
this single instance. Never instantiate SentenceTransformer directly anywhere else"*
([`embedding.py:23-24`](backend/memory/embedding.py:23)), with `get_embedding_service()`
([`:316`](backend/memory/embedding.py:316)) the only accessor. The `_hash_embed` fallback
([`:37`](backend/memory/embedding.py:37)) already proves the backend is swappable here.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep `get_embedding_service()` and the `EmbeddingService` method signatures
  unchanged; the swap SHALL be internal.
- AC2: THE SYSTEM SHALL produce 1024-dim vectors matching `EMBEDDING_DIM` — no schema or column
  width change.
- AC3: THE SYSTEM SHALL retain `_hash_embed` as the dependency-free fallback, unchanged.
- AC4: THE SYSTEM SHALL select the backend by configuration, with BGE-M3 selectable for the duration
  of the migration.
- AC5: THE SYSTEM SHALL record which backend produced each persisted vector — provenance is stored,
  never inferred.
- AC6: THE SYSTEM SHALL load Embedding-350M on **CPU**, consuming no VRAM (Phase 3 REQ-2 AC8/AC9).

**Edge Cases:**
- Model absent → `_hash_embed` fallback with a loud warning; retrieval degrades, never fails.
- Both models configured → AC5 provenance disambiguates; no cross-backend comparison (REQ-3).
- `sentence-transformers` uninstalled but the GGUF present → the GGUF path must still work.

---

### REQ-2: PiNs longer than 512 tokens are chunked and max-pooled

**User Story:** As a user I want a long saved document findable by any part of its content, not just
its opening.

**Verified:** NEW. Measured against the live store: **21% of PiNs exceed 512 tokens.** BGE-M3's
8192-token window meant this never had to be handled. Without chunking, everything past token 512
becomes unretrievable — **silently**, since truncation produces a perfectly valid vector.

**Acceptance Criteria:**
- AC1: WHEN text exceeds the 512-token window THEN THE SYSTEM SHALL split into overlapping chunks,
  embed each, and combine by **element-wise max-pool**.
- AC2: THE SYSTEM SHALL apply chunking identically at index time and query time.
- AC3: THE SYSTEM SHALL bound chunks per document and, WHEN exceeded, SHALL log that the tail was
  dropped rather than dropping it silently.
- AC4: THE SYSTEM SHALL L2-normalise **after** pooling, not before.
- AC5: THE SYSTEM SHALL NOT chunk text that fits — the single-chunk path SHALL be byte-identical to
  the unchunked result.

**Edge Cases:**
- Empty/whitespace text → zero vector, as `_hash_embed` already returns.
- Exactly 512 tokens → single chunk, AC5 path.
- Document hitting the AC3 bound → tail dropped **with a log line**. This is the failure a user
  discovers a year later wondering where their document went.

---

### REQ-3: Background re-index with dual-read, and no cross-space comparison

**User Story:** As a user I want retrieval to keep working while the store migrates.

**Verified:** NEW. **Highest-risk requirement in the phase.** Both backends produce **1024-dim**
vectors. Comparing across spaces is meaningless but raises nothing — no exception, no shape
mismatch, no NaN. Just a plausible number and quietly degraded recall.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL re-embed existing rows in a background task that blocks neither reads nor
  writes.
- AC2: THE SYSTEM SHALL NEVER compute a similarity between vectors of different provenance. A
  comparison whose operands disagree SHALL be **refused**, not scored.
- AC3: WHILE re-indexing THE SYSTEM SHALL serve queries by searching **both** spaces with
  space-matched query vectors and merging.
- AC4: THE SYSTEM SHALL mark a row migrated only **after** its new vector is durably written.
- AC5: IF interrupted THEN THE SYSTEM SHALL resume from the last migrated row without re-embedding
  completed rows and without leaving a row half-migrated.
- AC6: THE SYSTEM SHALL expose re-index progress (rows migrated / total, current backend).
- AC7: WHEN every row has migrated THEN THE SYSTEM SHALL stop dual-reading and report completion.

**Edge Cases:**
- Row written *during* re-index → written in the **new** space, already migrated, never re-queued.
- Re-index started twice → no-op with a log line, not a second worker.
- Migration abandoned and the old backend re-selected → dual-read correct in both directions.
- Corrupt row → skip, log, continue; one bad row must not stall migration.

---

### REQ-4: Encoder-350M scores step verification semantically

**User Story:** As the DER loop I want a step that satisfies its expected output in different words
graded on meaning, so correct work is not marked FAILED for using a synonym.

**Verified:** REAL GAP — `_verified_fraction`
([`agent_kernel.py:7146-7157`](backend/agent/agent_kernel.py:7146)) splits `expected_output` on `;`
and scores `a.lower() in result.lower()`. An assertion *"returns the user's email"* satisfied by
*"the address was retrieved"* scores **0.0**.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL score each assertion by semantic entailment, replacing exact substring
  containment.
- AC2: THE SYSTEM SHALL preserve the return contract — a float in `[0.0, 1.0]` — and the `0.8`/`0.3`
  band thresholds SHALL NOT move in this phase.
- AC3: THE SYSTEM SHALL keep the stub guard absolute — a result matching `_STUB_RE` with nothing
  substantial remaining SHALL score `0.0` **before** any semantic scoring, and SHALL NOT be
  rescuable by the encoder.
- AC4: IF the encoder is unavailable, slow, or errors THEN THE SYSTEM SHALL fall back to the
  substring scorer and log the fallback — verification SHALL NOT block on a model load.
- AC5: THE SYSTEM SHALL keep scoring deterministic for a given (expected, result) pair.
- AC6: THE SYSTEM SHALL score off the DER hot path or within a bounded time budget.

**Edge Cases:**
- `expected` is `None` → existing behaviour exactly: `0.0` if stub, else `1.0`
  ([`:7151-7152`](backend/agent/agent_kernel.py:7151)). Encoder not consulted.
- Empty `result` → `0.0` before the encoder.
- Assertion unsatisfied but sharing vocabulary → the **false-positive** direction, worse than the
  current false negatives: it marks failed work VERIFIED and feeds a false success to Phase 6's
  outer loop. REQ-8 AC3 must measure it separately.
- A result restating the assertion without doing the work (*"I will return the user's email"*) →
  must not score as satisfied. Entailment, not similarity.

---

### REQ-5: Encoder-350M classifies tasks beyond the keyword sets

**User Story:** As a user I want my task routed correctly even when phrased in words nobody put in a
keyword list.

**Verified:** REAL GAP — `TaskClassifier.classify`
([`kyudo.py:566-588`](backend/memory/mycelium/kyudo.py:566)) is a four-rule cascade ending in
*"fewer than 20 words → `quick_edit`"*.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL classify into the existing `task_class` values using encoder
  representations, adding no new classes.
- AC2: THE SYSTEM SHALL keep the keyword rules as a fast path and as the fallback when the encoder
  is unavailable — matching the existing tolerance at
  [`agent_kernel.py:4428-4432`](backend/agent/agent_kernel.py:4428), which already catches
  classifier failure and defaults to `"full"`.
- AC3: THE SYSTEM SHALL return the same `(task_class, space_subset)` tuple shape.
- AC4: WHERE encoder confidence is below a configured floor THEN THE SYSTEM SHALL defer to the
  keyword result rather than guess.
- AC5: THE SYSTEM SHALL log both the keyword result and the encoder result during rollout.
- AC6: THE SYSTEM SHALL treat a `task_class` change as a **budget** change, not only a routing
  change. `task_class` selects DER's per-class budget fraction (Phase 1 REQ-1 AC2), so a
  misclassification directly mis-sizes the token budget for the whole task. AC5's rollout log SHALL
  therefore record the **budget** each classification would have produced, not just the label.

**Edge Cases:**
- Empty task text → existing fallback; encoder not consulted.
- Encoder and keywords disagree → AC5 logs both; AC4 decides. Disagreement rate is the rollout signal.
- A genuinely complex task hitting the `< 20 words → quick_edit` rule → precisely the case this
  exists for; must appear in the REQ-8 probe set.

---

### REQ-6: Both models register as CPU local providers and are not bindable to chat roles

**User Story:** As a user I want the encoders visible as real providers without competing with my
chat model for VRAM or appearing where a reasoning model should.

**Verified:** Phase 1 provides `purpose` and namespaced ids; Phase 3 provides the CPU device policy.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL register Embedding-350M with `purpose="embedding"`.
- AC2: WHERE ColBERT-350M is enabled THE SYSTEM SHALL register it with `purpose="rerank"`.
- AC3: THE SYSTEM SHALL NOT make either bindable to `reasoning` or `tool_execution` — **including in
  the settings panel's Brain/Tool selectors**, not only in the chat switcher.
  ⚠️ [`ModelInferenceSection.tsx:80`](components/ModelInferenceSection.tsx:80) builds
  `providerOptions = providers.map(...)` with **no `purpose` filter**. Satisfying this AC requires
  changing that file. Phases 1 and 3 both classify it NO-CHANGE — correct for them, and no longer
  correct once non-chat providers exist.
- AC4: THE SYSTEM SHALL load both on CPU and SHALL NOT count either against the VRAM budget used to
  size a chat model.
- AC5: THE SYSTEM SHALL NOT subject either to the chat degradation ladder or `TARGET_TPS`.
- AC6: THE SYSTEM SHALL surface load state (`loaded`, `loading`, error) for both.

**Edge Cases:**
- Both encoders plus a chat model loaded → the chat model's derived context must be **identical** to
  what it would be with neither loaded.
- Embedding-350M fails to load → `_hash_embed` fallback; memory still functions.
- Encoder-350M fails to load → REQ-4 AC4 and REQ-5 AC2 fallbacks; DER still functions.

---

### REQ-7: Model artifacts are cached once and never re-downloaded

**User Story:** As a user I want the models fetched once and reused.

**Verified:** Phase 3 REQ-6 provides symlink-aware discovery of the user's HF cache.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL resolve both models from the user-configured folder before any network fetch.
- AC2: WHEN absent locally THEN THE SYSTEM SHALL report what is missing and where it is expected,
  and SHALL NOT silently download at first use.
- AC3: THE SYSTEM SHALL verify a cached artifact's integrity before load and re-fetch on mismatch.
- AC4: THE SYSTEM SHALL NOT re-download an artifact already present and valid.

**Edge Cases:**
- Symlinked path → resolved via Phase 3 REQ-6 AC1.
- Partial download → AC3 detects and re-fetches.
- Offline machine with models present → fully functional; no network call on the load path.

---

### REQ-8: Retrieval and verification quality are measured, not assumed

**User Story:** As the person deciding whether this swap was worth it, I want before/after numbers.

**Verified:** NEW. **This requirement gates the phase.** Every other requirement replaces a working
component with a smaller one; without measurement a regression is invisible until a user cannot find
their document.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a fixed probe set of queries with known-relevant documents, stored
  in the repository, and SHALL score recall@k for both backends on the **same** set.
- AC2: THE SYSTEM SHALL provide a labelled set of (expected, result) pairs — paraphrases, genuine
  failures, bare stubs, well-phrased stubs, and vocabulary-overlap-without-satisfaction — and score
  both scorers on it.
- AC3: THE SYSTEM SHALL report **both** verification error directions separately: work wrongly
  marked FAILED, and work wrongly marked VERIFIED. A single accuracy number hides the direction that
  matters.
- AC4: THE SYSTEM SHALL report memory footprint and per-call latency for each backend.
- AC5: WHERE Embedding-350M's recall is materially below baseline THEN THE SYSTEM SHALL report that
  as a **finding** and the swap SHALL NOT be defaulted on. **Do not adjust the probe set to close
  the gap.**
- AC6: THE SYSTEM SHALL gate ColBERT-350M on this measurement.

**Edge Cases:**
- Probe set too small to distinguish → report the inconclusive result; that is a valid outcome.
- Encoder wins on paraphrases but loses on false positives → AC3 makes it visible; must not be
  averaged into one score.

---

### REQ-9: Encoder decisions are observable

**User Story:** As the tuner I want to see what the encoders decided and why.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, per verification: the assertion, the scorer used
  (`encoder` | `substring` | `fallback`), the fraction, and the band — scoped by thread id.
- AC2: THE SYSTEM SHALL log, per classification, both classes with confidence **and the budget each
  would produce** (REQ-5 AC6).
- AC3: THE SYSTEM SHALL expose embedding backend, re-index progress, and both models' load state
  through `/api/debug/caducean`.
- AC4: THE SYSTEM SHALL keep logging off the critical path.

**Edge Cases:**
- High-volume verification → sampled or aggregated; volume is not a reason to log nothing.
- Missing thread id → explicit `unknown` scope rather than a dropped line.

---

## Non-Requirements (Out of Scope for Phase 4)

- **Fine-tuning, adapters, distillation.** Zero-shot only.
- **Building ColBERT reranking.** Seam only; gated by REQ-8 AC6.
- **Replacing Parakeet ASR or the TTS pipeline.** Untouched — Parakeet stays GPU-resident with its
  own service config.
- **Changing DER band thresholds** (`0.8`/`0.3`). REQ-4 AC2 pins them. Changing scorer and
  thresholds together makes neither measurable.
- **Repairing the outer-loop guards** → Phase 6. This phase supplies honest labels; Phase 6 uses them.
- **Changing the vector dimension or store schema.** Both backends are 1024-dim.
- **Using Encoder-350M for retrieval vectors.** No sentence head.
- **Removing `_hash_embed`.**

## Open Questions

- **OQ-1:** Chunk size and overlap. Start at 480 tokens / 64 overlap; tune against REQ-8 AC1.
- **OQ-2:** The confidence floor for REQ-5 AC4. Set from rollout disagreement data, not before.
- **OQ-3:** REQ-4 inline with a time budget vs off-path with a deferred label. Decide after
  measuring per-call latency (REQ-8 AC4).
- **OQ-4:** Re-index user-triggered or automatic on first start after the swap.
