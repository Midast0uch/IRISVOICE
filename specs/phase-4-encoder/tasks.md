# Tasks: Phase 4 — LFM2.5 Encoder Integration

> **Blocked on Phase 1** (registry, namespaced ids, `purpose`) **and Phase 3** (CPU device policy).

---

## Wave 0 — Baselines and probe sets (REQ-8)

- [ ] **T0.1** (REQ-8 AC1) Build the retrieval probe set: queries with known-relevant documents,
  committed under `backend/tests/data/`.
  RIPPLE: ⚠️ **before any model swap.** A baseline captured after the swap is not a baseline. Draw
  probes from real stored PiNs, **including several whose relevant content sits past token 512** —
  those are the REQ-2 cases and must be in the set from the start.

- [ ] **T0.2** (REQ-8 AC2) Build the verification probe set: labelled `(expected, result)` pairs
  covering paraphrases, genuine failures, bare stubs, **well-phrased stubs**, and
  vocabulary-overlap-without-satisfaction.
  RIPPLE: the last two catch a semantic scorer going wrong. A set of only paraphrases makes any
  encoder look perfect.

- [ ] **T0.3** (REQ-8 AC1/AC4) Record the **BGE-M3 baseline**: recall@k, latency, resident memory.
  Commit the numbers into this spec.

- [ ] **T0.4** (REQ-8 AC2/AC3) Record the **substring scorer baseline**, reporting both error
  directions separately.
  RIPPLE: a single accuracy number hides which direction moved. **False-VERIFIED is the dangerous
  direction** — it feeds Phase 6's outer loop successes that did not happen.

- [ ] **T0.5** Confirm Phase 1 and Phase 3 landed: `purpose` exists, ids namespaced, two local
  instances register, `resolve_device_policy` returns CPU + empty ladder for `embedding`/`rerank`.

---

## Wave 1 — Chunking and provenance (REQ-1, REQ-2) — *no model swap yet*

- [ ] **T1.1** (REQ-1 AC5, REQ-3 AC2) Add the `backend` provenance field to `Embedding` and to
  persisted rows. Backfill existing rows as `bge-m3`.
  RIPPLE: ⚠️ **do this while every vector is still BGE-M3.** Retrofitting provenance once two spaces
  coexist means guessing which space a row belongs to — and a wrong guess is a silent cross-space
  comparison. Dimension unchanged (1024), so this is additive.

- [ ] **T1.2** (REQ-3 AC2) Add the cross-space refusal at the **single** point vectors are compared:
  differing `backend` **raises**, never returns a float.
  RIPPLE: ⚠️ both backends are 1024-dim. No shape mismatch, no exception, no NaN — a cross-space
  comparison returns a plausible number and worse results. This check is the only thing that catches
  it; review will not. CT-E6 pins it.

- [ ] **T1.3** (REQ-2) Implement chunker + max-pool + post-pool L2 in `EmbeddingService`, **above**
  the model so index and query traverse the same path.
  RIPPLE: normalise **after** pooling (AC4) — per-chunk normalise then max-pool yields a non-unit
  vector and silently breaks cosine for every caller. Sub-window text must be byte-identical to
  today's output (AC5).

- [ ] **T1.4** (REQ-2 AC3) Bound chunks per document; log when a tail is dropped.
  RIPPLE: silent tail-dropping is the failure a user finds a year later. The log line **is** the
  requirement.

- [ ] **T1.5** (REQ-1 AC4) Make the backend configurable, BGE-M3 still default.
  RIPPLE: the swap must be reversible from config, not from a revert. Also the rollback path for
  REQ-3's abandoned-migration edge case.

- [ ] **T1.6** Route [`crawler/rerank.py:67`](backend/crawler/rerank.py:67) `_embed` through
  `EmbeddingService`.
  RIPPLE: ⚠️ the **second** embedding consumer. Left alone it truncates at 512 while the memory path
  chunks — two behaviours for the same text, only one of them tested.

- [ ] **T1.7** Tests: `test_chunk_and_pool.py`, `test_pooling_is_max_not_mean.py` (constructed so
  mean-pooling **fails**), `test_embedding_contract.py` (CT-E1, CT-E2),
  `test_cross_space_refusal.py` (CT-E6).

---

## Wave 2 — Embedding-350M as a CPU provider (REQ-1, REQ-6, REQ-7)

- [ ] **T2.1** (REQ-6 AC1/AC4) Register Embedding-350M with `purpose="embedding"`, resolved through
  Phase 3's `resolve_device_policy` → CPU, empty ladder, `counts_against_vram=False`.
  RIPPLE: consume the resolver — do **not** add a second device decision (Phase 3 D-1).

- [ ] **T2.2** (REQ-6 AC3) ⚠️ **Filter `providerOptions` in
  [`ModelInferenceSection.tsx:80`](components/ModelInferenceSection.tsx:80) to `purpose === "chat"`.**
  RIPPLE: ⚠️ **cross-phase.** This file is CONTRACT LOCK / NO-CHANGE in Phases 1 and 3 — correct for
  them, and wrong the moment this phase registers a non-chat provider. `providers.map()` is
  unfiltered, so the encoders land in the **Brain/Tool** dropdowns.
  **Land this in the SAME change as T2.1.** Between the two tasks, an embedding model is bindable as
  your reasoning model.

- [ ] **T2.3** (REQ-1 AC1/AC2/AC6) Implement the Embedding-350M backend behind `EmbeddingService`,
  1024-dim, CPU, signatures unchanged.
  RIPPLE: CT-E1 pins the interface. `_hash_embed` untouched.

- [ ] **T2.4** (REQ-7) Resolve artifacts from the user's folder before any network fetch; verify
  integrity; never silently download.
  RIPPLE: uses Phase 3 REQ-6's symlink-aware discovery — the models live in a symlinked HF cache.

- [ ] **T2.5** (REQ-8 AC1/AC4) Run `eval_embedding_quality.py` against T0.1; record next to T0.3.
  RIPPLE: ⚠️ **GATE.** If recall is materially below baseline, REQ-8 AC5 says report it as a finding
  and do **not** default the swap on. **Do not adjust the probe set to close the gap** — the probe
  set is the instrument; reshaping it destroys the only evidence the swap was safe.

- [ ] **T2.6** Tests: `test_encoder_provider_registration.py` (CT-E7),
  `__tests__/ModelInferenceSection.test.tsx`,
  `test_long_pin_retrievable_by_tail.py` (content **past token 512**),
  `test_encoders_do_not_shrink_chat_context.py`, `test_memory_survives_missing_models.py`.

---

## Wave 3 — Background re-index with dual-read (REQ-3)

- [ ] **T3.1** (REQ-3 AC3) Dual-read router: search both spaces with **space-matched** query vectors,
  merge.
  RIPPLE: the query must be embedded **once per space** with that space's backend. Embedding once and
  searching both is exactly the cross-space bug T1.2 refuses.

- [ ] **T3.2** (REQ-3 AC1/AC4/AC5) Resumable background re-index worker.
  RIPPLE: ⚠️ **write the vector, THEN set the migrated mark.** Reversed leaves a row dual-read
  believes migrated with no new vector — that document silently stops being found. Order is the
  requirement, not an implementation detail.

- [ ] **T3.3** (REQ-3 AC6, REQ-9 AC3) Expose progress + backend state in `/api/debug/caducean`
  (read-only).

- [ ] **T3.4** (REQ-3 AC7) Stop dual-reading and report completion when all rows migrated.
  RIPPLE: rows written *during* migration go to the new space and are already migrated — never
  re-queued. Getting this wrong means the migration never finishes.

- [ ] **T3.5** Tests: `test_reindex_no_outage.py`, `test_reindex_resumes.py`,
  `test_reindex_write_before_mark.py` (crash injected **between** write and mark).

---

## Wave 4 — Encoder-350M for DER (REQ-4, REQ-5)

- [ ] **T4.1** (REQ-4 AC3, D-4) ⚠️ **FIRST: pin the stub-guard ordering (CT-E4)** — a scorer stubbed
  to return `1.0` unconditionally must still leave a bare stub at `0.0`.
  RIPPLE: ⚠️ write this **before the semantic scorer exists.** A semantic scorer is exactly what
  would rescue a well-phrased stub — *"I have retrieved the user's email address"* is a strong
  entailment and a complete failure to do the work. The guard must be structurally unreachable, not
  outweighed.

- [ ] **T4.2** (REQ-4 AC1/AC2/AC5) Implement semantic entailment scoring in `_verified_fraction`,
  returning `[0.0, 1.0]`.
  RIPPLE: ⚠️ **do not touch the `0.8`/`0.3` bands**
  ([`agent_kernel.py:7172-7175`](backend/agent/agent_kernel.py:7172)). The distribution shifts from
  bimodal to continuous; retuning bands in the same change makes neither effect attributable. CT-E3
  pins them. **Phase 6 consumes these labels** — an unmeasured shift here propagates into the outer
  loop's guards.

- [ ] **T4.3** (REQ-4 AC4/AC6) Fallback + time budget: unavailable / erroring / slow → substring
  scorer, logged `scorer="fallback"`.
  RIPPLE: verification must never block on a model load. `_verify_step_result` is on the DER step path.

- [ ] **T4.4** (REQ-5) Add the encoder classification path to `TaskClassifier.classify`, keeping
  keyword rules as fast path and fallback, returning the unchanged tuple.
  RIPPLE: the call site at
  [`agent_kernel.py:4428-4432`](backend/agent/agent_kernel.py:4428) already try/excepts and defaults
  to `"full"` — **NO CHANGE needed there** (verified). No new classes, so `TASK_CLASS_SPACE_MAP` is
  untouched.

- [ ] **T4.5** (REQ-5 AC4/AC5/AC6) Log both classes with confidence **and the budget each would
  produce**; apply the confidence floor.
  RIPPLE: ⚠️ `task_class` selects DER's budget **fraction** (Phase 1 REQ-1 AC2), so a
  misclassification mis-sizes the budget for the whole task. Logging only the label hides that.
  The floor's value comes from rollout data (OQ-2) — ship logging-only first.

- [ ] **T4.6** (REQ-8 AC2/AC3) Run the verification evaluation against T0.2; report **both** error
  directions next to T0.4.
  RIPPLE: ⚠️ **GATE.** A drop in false-FAILED bought with a rise in false-VERIFIED is a regression,
  not an improvement.

- [ ] **T4.7** Tests: `test_verified_fraction_semantic.py` (paraphrase > 0.0 — **fails today**),
  `test_encoder_fallback.py`, `test_classifier_confidence_floor.py`,
  `test_der_band_contract.py` (CT-E3, CT-E5), `test_der_verifies_paraphrase.py`,
  `test_der_rejects_wellphrased_stub.py`.

---

## Wave 5 — Harness, observability, close-out

- [ ] **T5.1** (REQ-9 AC1/AC2) Structured logging per verification and per classification.
- [ ] **T5.2** Build `scripts/validate_encoder_path.py` with all 9 harness assertions.
  RIPPLE: **3 and 7** are load-bearing — 3 catches chunking that retrieves only the head; 7 catches a
  semantic scorer that became a way for stubs to pass.
- [ ] **T5.3** (REQ-8 AC5) Decide the default from T2.5 and T4.6. Record the numbers **and the
  decision**.
  RIPPLE: if the numbers do not support it, that is a legitimate outcome — REQ-1 AC4 keeps BGE-M3
  selectable, and Wave 1's chunking/provenance work is valuable either way.
- [ ] **T5.4** (REQ-8 AC6) Record the ColBERT decision from the measured baseline.
- [ ] **T5.5** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 (**append**) and `bootstrap/GOALS.md`.
- [ ] **T5.6** Full regression: `pytest`, `npx jest`, `npx tsc --noEmit`.

---

## Dependency / parallelization notes

**Hard sequencing:**
- **Phases 1 and 3 before T2.1.**
- **Wave 0 before everything.** A baseline captured after the swap is not a baseline.
- **T1.1 before T2.3.** Provenance must exist while every vector is still BGE-M3.
- **T1.2 before Wave 3.** Dual-read is where cross-space comparison would happen.
- **T2.1 and T2.2 in the SAME change.** Between them the encoders are bindable as reasoning models.
- **T4.1 before T4.2.** The stub guard is pinned before the scorer that could defeat it exists.
- **T2.5 gates Wave 3**; **T4.6 gates T5.3.**

**Parallelizable:**
- **Wave 4 (DER encoder) is fully independent of Waves 1–3 (retrieval)** — different models,
  different code paths, no shared state.
- T0.1 and T0.2 are independent of each other.
- T2.4 (artifacts) is independent of T2.3 (the backend).

**Riskiest tasks:**
1. **T1.2 / Wave 3 — cross-space comparison.** Both backends are 1024-dim, so it fails with **no
   error at all**. CT-E6 and harness assertion 5 are the only guards.
2. **T3.2 — write-then-mark ordering.** Reversed, documents silently stop being found, and only
   after a crash at exactly the wrong moment.
3. **T4.2 — the semantic scorer rescuing stubs.** The new false-VERIFIED direction is worse than the
   false-FAILED it fixes: it feeds Phase 6's outer loop successes that did not happen.
4. **T1.3 — chunking that retrieves only the head.** Passes a naive chunking test, fails the actual
   requirement.
5. **T2.2 — skipping the purpose filter.** An embedding model selectable as your brain.
6. **T2.5 / T4.6 — adjusting the probe set.** The one response that destroys the evidence.
7. **T1.6 — the second embedding consumer.** Easy to miss; two behaviours, one tested.

### Baseline record
<!-- T0.3/T0.4 record "before"; T2.5/T4.6 record "after". -->

| Metric | BGE-M3 / substring (before) | Embedding-350M / encoder (after) |
|---|---|---|
| recall@1 / @5 / @10 | **BLOCKED** — `sentence_transformers` not installed in this environment; record when run on a machine with BGE-M3. (Hash fallback numbers see eval_results.json — not comparable.) | *(placeholder — requires real models; record after T2.5)* |
| query latency | **BLOCKED** — same as above. | *(placeholder)* |
| resident memory | **BLOCKED** — same as above. | *(placeholder)* |
| paraphrase recognized (fewer false FAILED) | **0 / 3** (substring baseline). All 3 paraphrases scored 0.0 — substring cannot recognise paraphrase. | *(placeholder — record after T4.6)* |
| unsatisfied-but-overlapping rejected (fewer false VERIFIED) | **0 / 4** (substring baseline). All 4 well-phrased-stub/vocab-overlap probes scored >0.0 — substring passes cases where overlapping vocabulary appears as a verbatim substring. | *(placeholder — record after T4.6)* |
| stub rejected | **2 / 2 (100%)** — substring stub guard correctly rejects bare stubs. | 100% (required) |
| **T5.3 — default backend decision** | — | *(pending — requires T2.5 and T4.6 measurements)* |
| **T5.4 — ColBERT decision** | — | *(pending — requires recall measurements from real model)* |
