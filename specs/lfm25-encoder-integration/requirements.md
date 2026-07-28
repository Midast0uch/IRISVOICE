# Requirements: LFM2.5 Encoder Integration

## Decisions Locked

Resolved with the user on 2026-07-28. Do **not** re-litigate.

1. **Zero-shot first.** Both LFM2.5 models are used off-the-shelf. No fine-tuning, no adapter
   training, no distillation in this spec. If zero-shot quality is insufficient, that is a
   *finding* to report — not a licence to start training.
2. **Embedding-350M replaces BGE-M3; Encoder-350M does not.** These are different models for
   different jobs. `LFM2.5-Embedding-350M` is a dense bi-encoder producing a 1024-dim sentence
   vector — a drop-in for what IRIS actually uses BGE-M3 for. `LFM2.5-Encoder-350M` is a base
   masked-LM backbone; it produces token representations, not a sentence vector, and is used here
   for **classification/scoring**, never for retrieval vectors.
3. **Runtimes differ by model.** Encoder-350M runs in-process via `transformers` + `torch`
   (it is distributed as safetensors and needs a task head). Embedding-350M runs through the
   existing GGUF/llama.cpp path as a `purpose="embedding"` local provider.
4. **Both run on CPU** (`local-model-provider-parity` Decision Locked #6). ~350M parameters each;
   keeping them off the GPU preserves VRAM for the chat model, which is what the ≥25 tok/s target
   depends on.
5. **Long PiNs are chunked and max-pooled at query time.** Embedding-350M's context is 512 tokens;
   21% of measured PiNs exceed it. Chunk, embed each chunk, element-wise max-pool. Max-pool, not
   mean-pool: a long document that matches a query strongly in one section should score on that
   section, not have it averaged away.
6. **Re-index runs in the background with dual-read.** The store serves both the old and the new
   vector space during migration; a PiN is not considered migrated until its new vector is written.
7. **ColBERT-350M is deferred behind a quality gate.** It is specified here so the seam exists,
   but it is not built until Embedding-350M's measured retrieval quality is known. Adding
   late-interaction reranking to an unmeasured baseline is optimizing blind.
8. **`local-model-provider-parity` Wave 2 is a hard prerequisite.** This spec needs the `purpose`
   field and multi-instance local ids. Under a single `"local"` id these models cannot coexist
   with a chat model.

## Introduction

IRIS has two places where a small encoder does the job better than what is there now, and one
place where a smaller model does the same job as the incumbent.

- **Retrieval** currently runs on BGE-M3 (~2.3 GB) but uses only its dense 1024-dim output
  ([`embedding.py:11`](backend/memory/embedding.py:11) — *"Only the dense 1024-dim vector is
  persisted by IRIS today"*). The sparse and multi-vector outputs that justify BGE-M3's size are
  dead weight. Embedding-350M produces the same 1024-dim dense vector at ~15% of the size.
- **Task classification** is a keyword-set lookup
  ([`kyudo.py:566-588`](backend/memory/mycelium/kyudo.py:566)) — `word_set & self._CODE_KEYWORDS`,
  then research, then planning, then "fewer than 20 words → `quick_edit`". It cannot classify a
  task whose vocabulary it has not been given.
- **Step verification** is substring containment
  ([`agent_kernel.py:7156`](backend/agent/agent_kernel.py:7156) —
  `sum(1 for a in _assertions if a.lower() in result.lower())`). A step that satisfies its
  expected output in different words scores 0.0 and is graded `FAILED`.

The last of these is the most consequential, because `_verified_fraction` feeds
`_verify_step_result`'s VERIFIED/UNVERIFIED/FAILED bands
([`:7172-7175`](backend/agent/agent_kernel.py:7172)) and, through the ledger, the outer loop's
self-tuning signal.

### Success criteria

- BGE-M3 is removed from the default path; Embedding-350M serves retrieval at the **same 1024
  dimensions**, on CPU, with measured recall no worse than the BGE-M3 baseline on a fixed probe set.
- A PiN longer than 512 tokens is retrievable by content from **any** of its sections.
- Re-index completes in the background without a retrieval outage and without a restart.
- `_verified_fraction` scores a semantically-correct paraphrase above 0.0 — the case it currently
  fails — while still scoring a stub at 0.0.
- Task classification handles vocabulary absent from the keyword sets.
- No local chat model loses context window to either encoder (neither occupies VRAM).

## Requirements

---

### REQ-1: Embedding-350M replaces BGE-M3 behind the existing service interface

**User Story:** As a maintainer I want the smaller embedder swapped in without touching every
call site, so that the change is reversible and its effect is measurable.

**Verified:** REAL GAP — `EmbeddingService` is already the single chokepoint. Its module docstring
states *"All memory components share this single instance. Never instantiate SentenceTransformer
directly anywhere else"* ([`embedding.py:23-24`](backend/memory/embedding.py:23)), and
`get_embedding_service()` ([`:316`](backend/memory/embedding.py:316)) is the only accessor. The
hash-projection fallback (`_hash_embed`, [`:37`](backend/memory/embedding.py:37)) already proves
the backend is swappable at this seam.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep `get_embedding_service()` and the `EmbeddingService` public method
  signatures unchanged; the model swap SHALL be internal.
- AC2: THE SYSTEM SHALL produce 1024-dimensional vectors from Embedding-350M, matching
  `EMBEDDING_DIM`, so no schema or column width changes.
- AC3: THE SYSTEM SHALL retain `_hash_embed` as the dependency-free fallback, unchanged.
- AC4: THE SYSTEM SHALL select the embedding backend by configuration, with BGE-M3 remaining
  selectable for the duration of the migration.
- AC5: THE SYSTEM SHALL record which backend produced each persisted vector, so a vector's
  provenance is never inferred.
- AC6: THE SYSTEM SHALL load Embedding-350M on **CPU** and SHALL NOT consume VRAM
  (`local-model-provider-parity` REQ-5 AC8/AC9).

**Edge Cases:**
- Model file absent → fall back to `_hash_embed` with a loud warning, exactly as today; retrieval
  degrades but never fails.
- Both models configured → AC5's provenance tag disambiguates; no vector is ever compared across
  backends (REQ-3).
- `sentence-transformers` uninstalled but the GGUF present → the GGUF path is independent of
  sentence-transformers and must still work.

---

### REQ-2: PiNs longer than 512 tokens are chunked and max-pooled

**User Story:** As a user I want a long saved document to be findable by any part of its content,
not just its opening, so that research I saved is not silently unreachable.

**Verified:** NEW. Measured against the live store: **21% of PiNs exceed 512 tokens.** BGE-M3's
8192-token window meant this never had to be handled; Embedding-350M's 512-token window makes it
mandatory. Without chunking, everything past token 512 of a long PiN becomes unretrievable — and
does so *silently*, since truncation produces a perfectly valid vector.

**Acceptance Criteria:**
- AC1: WHEN text exceeds the model's 512-token window THEN THE SYSTEM SHALL split it into
  overlapping chunks, embed each, and combine them by **element-wise max-pool**.
- AC2: THE SYSTEM SHALL apply chunking identically at index time and at query time, so a stored
  vector and a query vector are always produced by the same procedure.
- AC3: THE SYSTEM SHALL bound the number of chunks per document and, WHEN the bound is exceeded,
  SHALL log that the tail was dropped rather than dropping it silently.
- AC4: THE SYSTEM SHALL L2-normalise **after** pooling, not before, so cosine similarity remains
  well-defined.
- AC5: THE SYSTEM SHALL NOT chunk text that fits in the window — the single-chunk path SHALL be
  byte-identical to the unchunked result.

**Edge Cases:**
- Empty or whitespace-only text → zero vector, as `_hash_embed` already returns
  ([`:54`](backend/memory/embedding.py:54)).
- A document of exactly 512 tokens → single chunk, AC5 path.
- A document so long it hits the AC3 bound → tail dropped **with a log line**; this is the failure
  mode most likely to be discovered a year later by a user wondering where their document went.

---

### REQ-3: Background re-index with dual-read, and no cross-space comparison

**User Story:** As a user I want retrieval to keep working while the store migrates to the new
embedder, so that upgrading does not cost me an outage or a restart.

**Verified:** NEW. **This is the highest-risk requirement in the spec.** BGE-M3 and Embedding-350M
both produce **1024-dim** vectors. Comparing a BGE-M3 vector with an Embedding-350M vector is
meaningless — they are different spaces — but because the dimensions match, nothing raises, nothing
errors, and the only symptom is silently degraded recall. A dimension change would have been safer;
this one fails quietly.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL re-embed existing rows in a background task that does not block reads or
  writes.
- AC2: THE SYSTEM SHALL NEVER compute a similarity between two vectors produced by different
  backends. A comparison whose two operands disagree on provenance SHALL be refused, not scored.
- AC3: WHILE a re-index is in progress THE SYSTEM SHALL serve queries by searching **both** spaces
  with space-matched query vectors and merging results.
- AC4: THE SYSTEM SHALL mark a row migrated only after its new vector is durably written.
- AC5: IF the re-index is interrupted (crash, restart, shutdown) THEN THE SYSTEM SHALL resume from
  the last migrated row without re-embedding completed rows and without leaving a row in a
  half-migrated state.
- AC6: THE SYSTEM SHALL expose re-index progress (rows migrated / total, current backend) so the
  operation is observable rather than inferred from latency.
- AC7: WHEN every row has migrated THEN THE SYSTEM SHALL stop dual-reading and report completion.

**Edge Cases:**
- A row written *during* the re-index → written in the **new** space, already migrated, never
  re-queued.
- Re-index started twice → second invocation is a no-op with a log line, not a second worker.
- Migration abandoned midway and the old backend re-selected → dual-read must remain correct in
  both directions; this is the rollback path.
- A corrupt or unreadable row → skip, log, continue; one bad row must not stall the migration.

---

### REQ-4: Encoder-350M scores step verification semantically

**User Story:** As the DER loop I want a step that satisfies its expected output in different
words to be graded on meaning, so that correct work is not marked FAILED for using a synonym.

**Verified:** REAL GAP — `_verified_fraction`
([`agent_kernel.py:7146-7157`](backend/agent/agent_kernel.py:7146)) splits `expected_output` on
`;` and scores `a.lower() in result.lower()` per assertion. Pure substring containment: an
assertion *"returns the user's email"* satisfied by a result saying *"the address was retrieved"*
scores **0.0**. That fraction drives `_verify_step_result`'s bands — `>= 0.8` VERIFIED,
`>= 0.3` UNVERIFIED, else FAILED ([`:7172-7175`](backend/agent/agent_kernel.py:7172)) — and the
resulting label is what the ledger records.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL score each assertion by semantic entailment against the result, replacing
  exact substring containment.
- AC2: THE SYSTEM SHALL preserve the existing return contract: a float in `[0.0, 1.0]`, and the
  existing `0.8` / `0.3` band thresholds SHALL NOT move in this spec.
- AC3: THE SYSTEM SHALL keep the stub guard absolute — a result matching `_STUB_RE` with nothing
  substantial remaining SHALL score `0.0` **before** any semantic scoring runs, and SHALL NOT be
  rescuable by the encoder.
- AC4: IF the encoder is unavailable, slow, or errors THEN THE SYSTEM SHALL fall back to the
  existing substring scorer and log the fallback — verification SHALL NOT block on a model load.
- AC5: THE SYSTEM SHALL keep scoring deterministic for a given (expected, result) pair, since the
  same input reaching two different labels would make the ledger unreadable.
- AC6: THE SYSTEM SHALL score off the DER hot path or within a bounded time budget, so a slow
  scorer cannot stall step execution.

**Edge Cases:**
- `expected` is `None` → existing behaviour is preserved exactly: `0.0` if stub, else `1.0`
  ([`:7151-7152`](backend/agent/agent_kernel.py:7151)). The encoder is not consulted.
- Empty `result` → `0.0`, before the encoder (`:7149-7150`).
- An assertion that is genuinely unsatisfied but shares vocabulary with the result → this is the
  false-positive direction, and it is **worse** than the current false negatives: it marks failed
  work VERIFIED and feeds a false success to the outer loop. REQ-8's evaluation must measure it.
- A result that restates the assertion without doing the work ("I will return the user's email") →
  must not score as satisfied. Entailment, not similarity.

---

### REQ-5: Encoder-350M classifies tasks beyond the keyword sets

**User Story:** As a user I want my task routed correctly even when I phrase it in words nobody
put in a keyword list, so that routing is not a vocabulary lottery.

**Verified:** REAL GAP — `TaskClassifier.classify`
([`kyudo.py:566-588`](backend/memory/mycelium/kyudo.py:566)) is a four-rule set-intersection
cascade: code keywords, then research, then planning, then *"fewer than 20 words →
`quick_edit`"*. Any task whose vocabulary misses all three sets falls through to a length
heuristic.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL classify a task into the existing `task_class` values using encoder
  representations, and SHALL NOT introduce new classes in this spec.
- AC2: THE SYSTEM SHALL keep the keyword rules as a fast path and as the fallback when the encoder
  is unavailable (matching the tolerance at
  [`agent_kernel.py:4428-4432`](backend/agent/agent_kernel.py:4428), which already catches
  classifier failure and defaults to `"full"`).
- AC3: THE SYSTEM SHALL return the same `(task_class, space_subset)` tuple shape — `space_subset`
  still derives from `TASK_CLASS_SPACE_MAP`.
- AC4: WHERE the encoder's confidence is below a configured floor THEN THE SYSTEM SHALL defer to
  the keyword result rather than guess.
- AC5: THE SYSTEM SHALL log both the keyword result and the encoder result during rollout, so
  disagreements are measurable before the encoder becomes authoritative.

**Edge Cases:**
- Empty task text → existing fallback, encoder not consulted.
- Encoder and keywords disagree → AC5 logs both; AC4 decides. The disagreement rate is the rollout
  signal.
- A task hitting the `< 20 words → quick_edit` rule that is genuinely complex → precisely the case
  this requirement exists for; it must appear in the REQ-8 probe set.

---

### REQ-6: Both models register as local providers, on CPU

**User Story:** As a user I want the encoders to appear as real local providers, so that their
state is visible and they do not compete with my chat model for VRAM.

**Verified:** BLOCKED on `local-model-provider-parity` Wave 2. `purpose` and namespaced
multi-instance ids do not exist yet; under the single `"local"` id
([`iris_gateway.py:7896`](backend/iris_gateway.py:7896)) these models cannot coexist with a chat
model.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL register Embedding-350M as a local provider with `purpose="embedding"`.
- AC2: WHERE ColBERT-350M is enabled THE SYSTEM SHALL register it with `purpose="rerank"`.
- AC3: THE SYSTEM SHALL NOT make either model bindable to `reasoning` or `tool_execution` —
  **including in the settings panel's Brain/Tool selectors**, not only in the chat switcher.
  ⚠️ `ModelInferenceSection.tsx:80` builds `providerOptions` from **every** provider with no
  `purpose` filter, so satisfying this AC requires changing that file. It is listed as
  NO-CHANGE/CONTRACT-LOCK in `local-model-provider-parity` (CT-L6) — correct for that spec's own
  changes, and no longer correct once non-chat providers exist.
- AC4: THE SYSTEM SHALL load both on CPU and SHALL NOT count either against the VRAM budget used
  to size a chat model (`local-model-provider-parity` REQ-5 AC8/AC9).
- AC5: THE SYSTEM SHALL NOT subject either model to the chat degradation ladder or the
  `TARGET_TPS` throughput target.
- AC6: THE SYSTEM SHALL surface load state (`loaded`, `loading`, error) for both, exactly as for a
  chat provider.

**Edge Cases:**
- Both encoders and a chat model loaded together → the chat model's derived context must be
  **identical** to what it would be with neither encoder loaded. This is
  `local-model-provider-parity` REQ-5 AC9 observed from this spec's side.
- Embedding-350M fails to load → `_hash_embed` fallback (REQ-1 edge case); memory still functions.
- Encoder-350M fails to load → REQ-4 AC4 and REQ-5 AC2 fallbacks; DER still functions.

---

### REQ-7: Model artifacts are cached once and never re-downloaded

**User Story:** As a user I want the models fetched once and reused, so that a restart is not a
download.

**Verified:** Partially covered — the user's symlinked Hugging Face cache is the discovery source
(`local-model-provider-parity` Decision Locked #4, REQ-8).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL resolve both models from the user-configured local model folder before
  attempting any network fetch.
- AC2: WHEN a model is absent locally THEN THE SYSTEM SHALL report what is missing and where it is
  expected, and SHALL NOT silently download at first use.
- AC3: THE SYSTEM SHALL verify a cached artifact's integrity before load and re-fetch on mismatch
  rather than loading a corrupt file.
- AC4: THE SYSTEM SHALL NOT re-download an artifact already present and valid.

**Edge Cases:**
- Symlinked path → resolved, following `local-model-provider-parity` REQ-8 AC1.
- Partial download from an interrupted fetch → AC3 detects and re-fetches.
- Offline machine with models present → fully functional; no network call on the load path.

---

### REQ-8: Retrieval and verification quality are measured, not assumed

**User Story:** As the person deciding whether this swap was worth it, I want the before/after
numbers, so that "smaller and faster" is not accepted as a proxy for "as good".

**Verified:** NEW. **This requirement gates the whole spec.** Every other requirement replaces a
working component with a smaller one; without a measurement, a regression in recall or verification
accuracy is invisible until a user notices their document cannot be found.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a fixed probe set of queries with known-relevant documents, stored
  in the repository, and SHALL score recall@k for BGE-M3 and Embedding-350M on the **same** set.
- AC2: THE SYSTEM SHALL provide a labelled set of (expected, result) pairs — including semantic
  paraphrases, genuine failures, stubs, and vocabulary-overlap-without-satisfaction cases — and
  SHALL score substring and encoder scorers on the same set.
- AC3: THE SYSTEM SHALL report **both** error directions for verification separately: work wrongly
  marked FAILED, and work wrongly marked VERIFIED. A single accuracy number hides the direction
  that matters.
- AC4: THE SYSTEM SHALL report memory footprint and per-call latency for each backend.
- AC5: WHERE Embedding-350M's recall is materially below BGE-M3's on the probe set THEN THE SYSTEM
  SHALL report that as a **finding** and the swap SHALL NOT be defaulted on. Do not adjust the
  probe set to close the gap.
- AC6: THE SYSTEM SHALL gate ColBERT-350M on this measurement: it is built only if reranking is
  shown to be needed against a measured baseline.

**Edge Cases:**
- Probe set too small to distinguish the backends → report the inconclusive result; an
  inconclusive measurement honestly reported is a valid outcome.
- Encoder wins on paraphrases but loses on false positives → AC3 makes this visible; it is a real
  possible outcome and must not be averaged into a single score.

---

### REQ-9: Encoder decisions are observable

**User Story:** As the tuner I want to see what the encoders decided and why, so that thresholds
can be set from data instead of from intuition.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, per verification call, the assertion, the scorer used
  (`encoder` | `substring` | `fallback`), the resulting fraction, and the band label — scoped by
  conversation/thread id.
- AC2: THE SYSTEM SHALL log, per classification, both the keyword class and the encoder class with
  its confidence (REQ-5 AC5).
- AC3: THE SYSTEM SHALL expose embedding backend, re-index progress, and both models' load state
  through the existing debug endpoint.
- AC4: THE SYSTEM SHALL keep logging off the critical path — a logging failure SHALL NOT fail a
  verification or a retrieval.

**Edge Cases:**
- High-volume verification → sampled or aggregated; volume is not a reason to log nothing.
- Missing thread id → log with an explicit `unknown` scope rather than dropping the line.

---

## Non-Requirements (Out of Scope)

- **Fine-tuning, adapters, or distillation.** Zero-shot only (Decision Locked #1).
- **Building ColBERT-350M reranking.** Specified as a seam; gated by REQ-8 AC6.
- **Replacing the Parakeet ASR or the TTS pipeline.** Untouched. Parakeet remains GPU-resident with
  its own service and its own `--device` flag.
- **Changing DER band thresholds** (`0.8` / `0.3`). REQ-4 AC2 pins them. Changing the scorer and
  the thresholds in one step makes the effect of either unmeasurable.
- **Changing the vector dimension or the store schema.** Both backends are 1024-dim.
- **Using Encoder-350M for retrieval vectors.** It is a base MLM; it has no sentence-vector head
  (Decision Locked #2).
- **Removing `_hash_embed`.** It is the last-resort fallback and stays.

## Open Questions

- **OQ-1:** Chunk size and overlap for REQ-2. Start at 480 tokens with 64 overlap (fits 512 with
  room for special tokens); tune against REQ-8 AC1 rather than guessing now.
- **OQ-2:** The confidence floor for REQ-5 AC4. Set it from the rollout disagreement data (AC5),
  not before.
- **OQ-3:** Whether REQ-4's scorer runs inline with a time budget or off-path with a deferred
  label. Inline is simpler and preserves the ledger's ordering; off-path is safer for latency.
  Decide after measuring per-call latency (REQ-8 AC4).
- **OQ-4:** Whether the re-index should be user-triggered or automatic on first start after the
  swap. Automatic is friendlier; user-triggered is safer for a store of unknown size.
