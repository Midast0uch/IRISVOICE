# Tasks: LFM2.5 Encoder Integration

> Each task links to a requirement. Waves are dependency-ordered.
> **Prerequisite: `local-model-provider-parity` Wave 2 must land first** — this spec needs
> `purpose` and namespaced multi-instance local ids (REQ-6, Decision Locked #8).

---

## Wave 0 — Baseline and probe sets (REQ-8)

- [ ] **T0.1** (REQ-8 AC1) Build the retrieval probe set: queries with known-relevant documents,
  committed to the repo under `backend/tests/data/`.
  RIPPLE: ⚠️ **Do this before any model swap.** A baseline captured after the swap is not a
  baseline. Draw the probes from real stored PiNs, including several whose relevant content sits
  past token 512 — those are the REQ-2 cases and they must be in the set from the start.

- [ ] **T0.2** (REQ-8 AC2) Build the verification probe set: labelled `(expected, result)` pairs
  covering semantic paraphrases, genuine failures, bare stubs, well-phrased stubs, and
  vocabulary-overlap-without-satisfaction.
  RIPPLE: the last two categories are what catch a semantic scorer going wrong. A probe set of only
  paraphrases will make any encoder look perfect.

- [ ] **T0.3** (REQ-8 AC1/AC4) Record the **BGE-M3 baseline**: recall@k, latency, resident memory.
  RIPPLE: this number is the entire justification for the swap. Commit it into the spec.

- [ ] **T0.4** (REQ-8 AC2/AC3) Record the **substring scorer baseline** on T0.2, reporting both
  error directions separately.
  RIPPLE: REQ-8 AC3 — a single accuracy number hides which direction moved. False-VERIFIED is the
  dangerous direction because it feeds the outer loop a success that did not happen.

- [ ] **T0.5** Confirm `local-model-provider-parity` Wave 2 has landed: `purpose` exists,
  local ids are namespaced, two local instances can register.
  RIPPLE: hard gate. Without it, T2.1 cannot register anything.

---

## Wave 1 — Chunking and provenance (REQ-1, REQ-2) — *no model swap yet*

- [ ] **T1.1** (REQ-1 AC5, REQ-3 AC2) Add the `backend` provenance field to the `Embedding` value
  and to persisted vector rows. Backfill existing rows as `bge-m3`.
  RIPPLE: ⚠️ **Before the swap, while every vector is still BGE-M3.** Retrofitting provenance once
  two spaces coexist means guessing which space a row belongs to — and a wrong guess is a silent
  cross-space comparison. Dimension is unchanged (1024), so this is additive.

- [ ] **T1.2** (REQ-3 AC2) Add the cross-space refusal at the **single** point vectors are compared:
  differing `backend` **raises**, never returns a float.
  RIPPLE: ⚠️ Both backends are 1024-dim. There is no shape mismatch, no exception, no NaN — a
  cross-space comparison returns a plausible number and worse results. This check is the only thing
  that catches it; review will not. CT-E6 pins it.

- [ ] **T1.3** (REQ-2) Implement the chunker + max-pool + post-pool L2 in `EmbeddingService`,
  above the model, so index and query traverse the same path (REQ-2 AC2).
  RIPPLE: normalise **after** pooling (AC4) — per-chunk normalise then max-pool yields a
  non-unit vector and silently breaks cosine for every caller. Sub-window text must take the AC5
  path and be byte-identical to today's output.

- [ ] **T1.4** (REQ-2 AC3) Bound chunks per document; log when a tail is dropped.
  RIPPLE: silent tail-dropping is the failure a user discovers a year later. The log line is the
  requirement.

- [ ] **T1.5** (REQ-1 AC4) Make the embedding backend configurable, BGE-M3 still default.
  RIPPLE: the swap must be reversible from config, not from a revert. This is also the rollback
  path for REQ-3's abandoned-migration edge case.

- [ ] **T1.6** Route `backend/crawler/rerank.py:67` `_embed` through `EmbeddingService`.
  RIPPLE: ⚠️ the **second** embedding consumer. Left alone it truncates at 512 while the memory
  path chunks — two different behaviors for the same text, and only one of them is tested.

- [ ] **T1.7** Tests:
  - `backend/tests/unit/test_chunk_and_pool.py` — parametrized sub-window / exact-window /
    multi-chunk (REQ-2 AC1/AC4/AC5).
  - `backend/tests/unit/test_pooling_is_max_not_mean.py` — constructed so mean-pooling fails.
  - `backend/tests/contract/test_embedding_contract.py` — CT-E1, CT-E2.
  - `backend/tests/contract/test_cross_space_refusal.py` — CT-E6.

---

## Wave 2 — Embedding-350M as a CPU local provider (REQ-1, REQ-6, REQ-7)

- [ ] **T2.1** (REQ-6 AC1/AC4) Register Embedding-350M as a local provider with
  `purpose="embedding"`, resolved through `resolve_device_policy` → CPU, empty ladder,
  `counts_against_vram=False`.
  RIPPLE: consumes `local-model-provider-parity` T3.0. Do **not** add a device decision here — one
  resolver, one answer (that spec's D-4b). Not bindable to `reasoning`/`tool_execution` (AC3).

- [ ] **T2.2** (REQ-1 AC1/AC2/AC6) Implement the Embedding-350M backend behind `EmbeddingService`,
  producing 1024-dim vectors on CPU. Public signatures unchanged.
  RIPPLE: CT-E1 pins the interface. `_hash_embed` stays untouched (AC3).

- [ ] **T2.3** (REQ-7) Resolve model artifacts from the user's local model folder before any network
  fetch; verify integrity; never silently download.
  RIPPLE: follows `local-model-provider-parity` REQ-8 AC1 symlink traversal — the user's models live
  in a symlinked HF cache.

- [ ] **T2.4** (REQ-8 AC1/AC4) Run `eval_embedding_quality.py` against T0.1 and record
  Embedding-350M's numbers next to the T0.3 baseline.
  RIPPLE: ⚠️ **Gate.** If recall is materially below baseline, REQ-8 AC5 says report it as a finding
  and do **not** default the swap on. **Do not adjust the probe set to close the gap** — the probe
  set is the instrument, and reshaping it destroys the only evidence the swap was safe.

- [ ] **T2.4b** (REQ-6 AC3) Filter `providerOptions` in
  [`ModelInferenceSection.tsx:80`](components/ModelInferenceSection.tsx:80) to `purpose === "chat"`.
  RIPPLE: ⚠️ **Cross-spec — this file is CONTRACT LOCK / NO-CHANGE in `local-model-provider-parity`
  (CT-L6).** That classification is correct for that spec and becomes wrong here: `providers.map()`
  is unfiltered, so registering Embedding-350M and ColBERT puts them in the settings **Brain/Tool**
  dropdowns. Land this **in the same change as T2.1**, or the encoders are bindable as reasoning
  models the moment they register. Update CT-L6's assertion to expect the filter.

- [ ] **T2.5** Tests:
  - `backend/tests/contract/test_encoder_provider_registration.py` — CT-E7.
  - `__tests__/ModelInferenceSection.test.tsx` — an `embedding` and a `rerank` provider in
    `providers[]` do **not** appear in the Brain or Tool selector (REQ-6 AC3, T2.4b).
  - `backend/tests/behavioral/test_long_pin_retrievable_by_tail.py` — content **past token 512**
    is retrievable (REQ-2). The 21%-of-PiNs case.
  - `backend/tests/behavioral/test_encoders_do_not_shrink_chat_context.py` — REQ-6 AC4.
  - `backend/tests/behavioral/test_memory_survives_missing_models.py` — `_hash_embed` fallback.

---

## Wave 3 — Background re-index with dual-read (REQ-3)

- [ ] **T3.1** (REQ-3 AC3) Implement the dual-read router: search both spaces with **space-matched**
  query vectors, merge results.
  RIPPLE: the query must be embedded **once per space** with that space's backend. Embedding once
  and searching both is the exact cross-space bug T1.2 refuses.

- [ ] **T3.2** (REQ-3 AC1/AC4/AC5) Implement the resumable background re-index worker.
  RIPPLE: ⚠️ **Write the vector, then set the migrated mark.** The reverse order — mark, then write
  — leaves a row that dual-read believes is migrated with no new vector, and that document silently
  stops being found. Order is the requirement, not an implementation detail.

- [ ] **T3.3** (REQ-3 AC6, REQ-9 AC3) Expose re-index progress and backend state through the debug
  endpoint.
  RIPPLE: extends `backend/api/caducean_debug.py`, which is strictly read-only — keep it so.

- [ ] **T3.4** (REQ-3 AC7) Stop dual-reading and report completion when every row has migrated.
  RIPPLE: rows written *during* migration are written in the new space and already migrated — never
  re-queued (edge case). Getting this wrong makes the migration never finish.

- [ ] **T3.5** Tests:
  - `backend/tests/behavioral/test_reindex_no_outage.py` — REQ-3 AC1/AC3.
  - `backend/tests/behavioral/test_reindex_resumes.py` — REQ-3 AC4/AC5.
  - `backend/tests/behavioral/test_reindex_write_before_mark.py` — crash injected **between** write
    and mark; the row reads unmigrated and is retried.

---

## Wave 4 — Encoder-350M for DER (REQ-4, REQ-5)

- [ ] **T4.1** (REQ-4 AC3, D-5) **First:** pin the stub-guard ordering with CT-E4 — a scorer stubbed
  to return `1.0` unconditionally must still leave a bare stub at `0.0`.
  RIPPLE: ⚠️ write this **before** the semantic scorer exists. A semantic scorer is exactly the
  component that would rescue a well-phrased stub ("I have retrieved the user's email address" is a
  strong entailment and a complete failure to do the work). The guard must be structurally
  unreachable, not merely outweighed.

- [ ] **T4.2** (REQ-4 AC1/AC2/AC5) Implement semantic entailment scoring in `_verified_fraction`,
  returning `[0.0, 1.0]`.
  RIPPLE: ⚠️ **Do not touch the `0.8` / `0.3` bands** ([`agent_kernel.py:7172-7175`](backend/agent/agent_kernel.py:7172)).
  The scorer's output distribution changes from bimodal to continuous; retuning bands in the same
  change makes neither effect attributable (D-6). CT-E3 pins them.

- [ ] **T4.3** (REQ-4 AC4/AC6) Add the fallback and time budget: unavailable, erroring, or slow →
  substring scorer, logged as `scorer="fallback"`.
  RIPPLE: verification must never block on a model load. `_verify_step_result` is on the DER step
  path.

- [ ] **T4.4** (REQ-5) Add the encoder classification path to `TaskClassifier.classify`, keeping
  keyword rules as fast path and fallback, returning the unchanged `(task_class, space_subset)`.
  RIPPLE: the call site at [`agent_kernel.py:4428-4432`](backend/agent/agent_kernel.py:4428)
  already try/excepts and defaults to `"full"` — NO CHANGE needed there (verified). No new classes,
  so `TASK_CLASS_SPACE_MAP` is untouched.

- [ ] **T4.5** (REQ-5 AC4/AC5) Log both keyword and encoder classes with confidence; apply the
  confidence floor.
  RIPPLE: the floor's value comes from the rollout disagreement data (OQ-2), not from a guess. Ship
  logging-only first, set the floor from what it shows.

- [ ] **T4.6** (REQ-8 AC2/AC3) Run the verification evaluation against T0.2 and report **both**
  error directions next to the T0.4 baseline.
  RIPPLE: ⚠️ **Gate.** A drop in false-FAILED bought with a rise in false-VERIFIED is a regression,
  not an improvement — it feeds the outer loop successes that did not happen.

- [ ] **T4.7** Tests:
  - `backend/tests/unit/test_verified_fraction_semantic.py` — paraphrase > 0.0 (**fails today**);
    stub exactly 0.0; restated-but-not-done not satisfied.
  - `backend/tests/unit/test_encoder_fallback.py` — unavailable / error / timeout (REQ-4 AC4).
  - `backend/tests/unit/test_classifier_confidence_floor.py` — REQ-5 AC3/AC4.
  - `backend/tests/contract/test_der_band_contract.py` — CT-E3, CT-E5.
  - `backend/tests/behavioral/test_der_verifies_paraphrase.py` — REQ-4 end-to-end.
  - `backend/tests/behavioral/test_der_rejects_wellphrased_stub.py` — D-5 end-to-end.

---

## Wave 5 — Harness, observability, close-out (REQ-8, REQ-9)

- [ ] **T5.1** (REQ-9 AC1/AC2) Structured logging: per-verification (assertion, scorer, fraction,
  band, thread id) and per-classification (keyword class, encoder class, confidence).
  RIPPLE: off the critical path (AC4) — a logging failure must not fail a retrieval or a
  verification.

- [ ] **T5.2** Build `scripts/validate_encoder_path.py` with all nine harness assertions.
  RIPPLE: assertions 3 and 7 are the load-bearing ones. 3 catches chunking that retrieves only the
  head; 7 catches a semantic scorer that became a way for stubs to pass.

- [ ] **T5.3** (REQ-8 AC5) Decide the default: swap on only if T2.4 and T4.6 support it. Record the
  numbers **and the decision** in this spec.
  RIPPLE: if the numbers do not support it, that is a legitimate outcome — REQ-1 AC4 keeps BGE-M3
  selectable and the chunking/provenance work from Wave 1 is valuable either way.

- [ ] **T5.4** (REQ-8 AC6) Record the ColBERT decision from the measured baseline. Build only if
  reranking is shown to be needed.

- [ ] **T5.5** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 (**append** a row — `local-model-provider-parity`
  T5.5 and `contextpill-model-switcher` T4.3 edit the same table; do not rewrite it) and
  `bootstrap/GOALS.md` with a **Domain 23** entry (22 is claimed by `local-model-provider-parity`).

- [ ] **T5.6** Full-suite regression + baseline record below.

---

## Dependency / parallelization notes

**Hard sequencing:**

- **`local-model-provider-parity` Wave 2 before T2.1.** Hard prerequisite (T0.5 verifies it).
- **Wave 0 before everything.** A baseline captured after the swap is not a baseline.
- **T1.1 before T2.2.** Provenance must exist while every vector is still BGE-M3; retrofitting it
  across two coexisting spaces means guessing, and a wrong guess is a silent cross-space comparison.
- **T1.2 before Wave 3.** Dual-read is where cross-space comparison would happen.
- **T4.1 before T4.2.** The stub guard is pinned before the scorer that could defeat it exists.
- **T2.4 gates Wave 3**; **T4.6 gates T5.3.**

**Parallelizable:**

- **Wave 4 is fully independent of Waves 1–3.** Different models, different code paths, no shared
  state — the DER encoder work can run alongside the retrieval work.
- T0.1/T0.2 (probe sets) are independent of each other.
- T2.3 (artifact caching) is independent of T2.2 (the backend).
- All test-writing precedes its implementation task.

**Riskiest tasks:**

1. **T1.2 / Wave 3 — cross-space comparison.** Both backends are 1024-dim, so this fails with **no
   error at all**: a plausible number and quietly worse recall. CT-E6 and harness assertion 5 are
   the only guards.
2. **T3.2 — write-then-mark ordering.** Reversed, it produces documents that silently stop being
   found, and only after a crash at exactly the wrong moment.
3. **T4.2 — the semantic scorer rescuing stubs.** The new false-VERIFIED direction is worse than the
   false-FAILED direction it fixes, because it feeds the outer loop successes that did not happen.
   T4.1's guard and `test_der_rejects_wellphrased_stub` exist for this.
4. **T1.3 — chunking that retrieves only the head.** Passes a naive chunking test and fails the
   actual requirement. `test_long_pin_retrievable_by_tail` and harness assertion 3 are the guards.
5. **T2.4 / T4.6 — the temptation to adjust the probe set.** If the numbers disappoint, reshaping
   the measurement is the one response that destroys the evidence. REQ-8 AC5: report the finding.
6. **T1.6 — the second embedding consumer.** Easy to miss; produces two different behaviors for the
   same text, only one of which is tested.

### Baseline record
<!-- T0.3 / T0.4 record the "before" numbers here; T2.4 / T4.6 record the "after". -->

| Metric | BGE-M3 / substring (before) | Embedding-350M / encoder (after) |
|---|---|---|
| recall@1 | | |
| recall@5 | | |
| recall@10 | | |
| query latency | | |
| resident memory | | |
| paraphrase recognized | | |
| unsatisfied-but-overlapping rejected | | |
| stub rejected | 100% (required) | 100% (required) |
