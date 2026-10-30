# Tasks: Memory Recall Reach and Performance

> Each task links to a requirement. Every task that changes memory behaviour ends with:
> `python evals/memory_bench.py` (compare with the "memory" standard) AND the end-to-end evals
> it touches (`evals/run_evals.py --group research` / coding tasks), before and after
> (CLAUDE.md, the measured loop). A task is not done until both are recorded in PROGRESS
> Standards with a guard that fails on the old state.

## Wave 1 — Reach + the benchmark (DONE 2026-10-27)
- [x] T1 (REQ-1): fingerprint index — `backend/memory/recall_reach.py` — RIPPLE: none written; RAM ~146 B/chunk
- [x] T2 (REQ-1): reach path in `EpisodicStore.retrieve_context_chunks` (200 nearest + newest 50, old path on None) — `backend/memory/episodic.py` — RIPPLE: S79/S81 plans (CONTRACT LOCK), every caller unchanged
- [x] T3 (REQ-1): guards — `backend/tests/contract/test_memory_recall_reach_contract.py` (CT-R1..R6; the store-level ones fail on the old path)
- [x] T4 (REQ-6 AC1, AC2, AC4): `evals/memory_bench.py` + `evals/standards.json` "memory" — RIPPLE: reads the live store read-only, adopts the running embedding sidecar
- [ ] T4b (REQ-1 AC6): scan by region — DEFERRED 2026-10-27: warm 10x scan p95 is 115.98 ms (< 150 ms bar), so the AC6 trigger is not met; re-check when it passes the bar (Kyudo zone → sector root → strand) once the 10× scan p95 (236 ms measured) matters; keep per-region column blocks — `recall_reach.py` — RIPPLE: bench 10× scan, sector assignment (owner-gated births; use existing roots only)
- [x] T5 (REQ-8 AC2): `overview()["recall"]` = reach status/counters, keyword counters, embed fallbacks by cause + caller, sidecar retries (2026-10-27) — `backend/memory/surface_queries.py` — RIPPLE: snapshot contract keys (`test_memory_snapshot_contract.py`)

## Wave 2 — Honest vectors (REQ-2) — do first: the other waves measure on these vectors
- [x] T6 (REQ-2 AC1): `_encode_chunk_with` reports whether it fell back; `_encode_uncached_with` labels a result with the fallback backend when ANY chunk fell back (never max-pool hash with model chunks) — `backend/memory/embedding.py` — DONE 2026-10-27; RIPPLE honoured: a mixed text is stored as a PURE hash vector (never a hash+model pool), so `compare_embeddings` excludes it by label
- [x] T7 (REQ-2 AC2): `FALLBACK_COUNTERS` (chunks / lfm_error / no_model / texts / mixed_texts) + `FALLBACK_CALLERS`, one warning per fallback text with caller + session id — `embedding.py` — the caller is read from the stack because the public signature is pinned (CT-E1)
- [x] T8 (REQ-2 AC3, AC4): repair lane: find LFM-labelled rows with > 50% zero components (measured 9.4%), re-embed in bounded batches on `lane("memory_repair")`, write via `db.app_write`, resumable by rowid — `backend/memory/repair_vectors.py` + `scripts/repair_mislabelled_vectors.py` (lane `memory_repair`) — DONE: live sweep 146,973 scanned / 14,412 re-embedded / 0 failed; the ripple is closed by `recall_reach.update_rows` + `update_if_indexed` (refresh still only appends)
- [x] T9: `test_embedding_honest_label_contract.py` (4; label + mixed-space fail on the old code) + `test_memory_vector_repair_contract.py` (3); bench recorded (S131): turn recall@10 0.9008 -> 0.9225, research 0.9758, store 0.9592

## Wave 3 — Exact words (REQ-3)
- [x] T10 (REQ-3 AC1): FTS5 table over `context_chunks.content` (external content, rowid-linked), insert/delete kept in step with the one writer; backfill on a lane — `backend/memory/chunk_fts.py` + `episodic._init_chunk_fts` — DONE: external content + 3 triggers (native one-writer path included), rebuild on lane `memory_fts` (4.2 s / 146,973 rows); `test_answer_path_standards` green BEFORE the change (13 pass)
- [x] T11 (REQ-3 AC2): fuse keyword rank with fingerprint rank by reciprocal rank into the candidate union (the union, not the final score: exact scoring stays) — `episodic.py` reach block + `chunk_fts.fuse_by_rank` (RRF k=60) — DONE: union bound is 200 + 50 + 50; the exact scorer is unchanged
- [x] T12 (REQ-3 AC4): missing/broken FTS → meaning only; `COUNTERS.missing/error`, `ensure_schema` never raises, and `overview()` exposes the counters
- [x] T13: bench `--words` set (40 cases from real chunks: file names, hex ids, error classes) + `standards.json` memory.words (reach/any_hit/unique, -0.02); measured 0.075 -> 0.575 strict, 1.0 any-hit, 8/8 unique

## Wave 4 — Compress where outcomes agree (REQ-4)
- [x] T14 (REQ-4 AC1): persist the fingerprint + an int8 vector per chunk (`vec_i8`, `vec_scale`), backfill on a lane; recall reads int8 for exact scoring; bench: recall@10 within 0.02 of float per chunk type, else keep float for that type — `backend/memory/vector_quant.py`, `vector_compress.py`, `scripts/compress_vectors.py` — DONE: backfill 146,973 rows on lane `memory_vectors` (9 passes, 11 s); per-type int8 delta: context_fragment -0.0009, der_output -0.0017, document_data -0.0034, der_failure 0, research_summary 0 (all < 0.02 -> float DROPPED for all 5 types); post-drop recall research 0.9742 / turn 0.9183 / global 0.9592, words unchanged; vector bytes/row 4,096 -> 1,152; store 1.21 GB -> 955 MB after VACUUM (backend stopped: a live handle blocks the truncate); warm-up now reads the stored `vec_fp` (1,152 B/row)
- [x] T15 (REQ-4 AC2): fold near-duplicates of one strand with the same outcome (cosine ≥ 0.92 — the existing `_FRAG_DEDUP_THRESHOLD`) into one row with `folded_into` references, on the integrity lane; never across Kyudo zones; never a pinned chunk — `backend/memory/fold_chunks.py`, `scripts/fold_chunks.py` — DONE: live sweep 341 passes over ~8,500 strand groups: 35,847 rows folded into 16,575 canonicals (24.4% of the store); recall reads `folded_into IS NULL` only (episodic reach block, recall_reach._read, chunk_fts.search); `unfold()` restores (a reference, not a delete); pinned-chunk guard ready (pin link target_type 'chunk'); post-fold: turn recall 0.9183 -> 0.9983 (duplicates stopped crowding the top-10), global 0.9633, research 0.9742; candidate pool 146,973 -> 111,126
- [x] T16 (REQ-4 AC3): distil a proven claim's agreeing chunk cluster into the claim + chain references (`memory_chain.distilled`), payload kept only where Kyudo trust allows — `backend/memory/distil_claims.py`, `scripts/distil_claims.py` — DONE: live sweep: 98 proven claims distilled (cosine ≥ 0.55 agreement, bounded 50 refs each, 4,755 references, all resolve); ONE chain row per claim: content = the claim's own text (proven = trust-allowed), metadata = chunk id REFERENCES (never payloads), `distilled = 1`, `thread_id = claim-<id>` so chain_timeline finds it; idempotent (a claim with a distilled row is skipped); candidate-tier and absorbed claims never distil; folded rows are never referenced
- [x] T17 (REQ-4 AC4): bench before/after each step; bytes per chunk and store size into the standard — DONE: `evals/standards.json` memory keeps compression per type (int8-vs-float DELTA guard > 0.02), `vector_bytes_per_row` (1,152, x1.05 + 8 guard), filters recall + words; measured per step: int8 drop (vector bytes/row 4,096 -> 1,152, store 1.21 GB -> 955 MB), fold (candidates -24.4%, turn recall +0.08), distil (98 chain rows, +~600 KB)

## Wave 5 — Budget + decay (REQ-5)
- [x] T18 (REQ-5 AC1): give `cleanup_stale_chunks` its production caller as part of the ONE Kyudo decay law (channel rate; RECALL_USED/HELPED slow it, MISLED speeds it) on the integrity lane — `backend/memory/chunk_decay.py` — DONE: strength = 1 - rate(0.02/day) x m_zone(trusted 1.0 / tool 1.5 / reference 3.0, the channel multipliers) x m_outcome(HELPED 0.5, MISLED 1.8 - the law's own expand/compress constants) x active_days(ActivityClock) x a(retrieval_count); `cleanup_stale_chunks` is now the law's named entry on lane `memory_integrity`; the production caller is `interface.run_maintenance` step 4c (every N completed tasks, off the answer path); live first pass: 3,734 chunks pruned (reference 3,294 old document chunks at the EXTERNAL rate, tool 299, trusted 141), 1,985 protected
- [x] T19 (REQ-5 AC2): store budget per zone (bytes, rows) + a guard that fails when exceeded; prunes typed MEMORY_PRUNED with the reason — DONE: `chunk_decay.ZONE_BUDGET` (trusted 160k rows / 320 MB, tool 40k / 80 MB, reference 25k / 55 MB - live store x ~1.5 headroom); the same pass prunes oldest-unused-first when a zone is over; every prune typed MEMORY_PRUNED with reason + zone (the surface already renders ghosts); the bench REGRESSIONS on the same constants (`zone_usage` in the report); live: all zones within budget
- [x] T20 (REQ-5 AC3): never prune a chunk that backs a live claim or a pin — DONE: pinned chunks (pin link target_type 'chunk') and chunks referenced by a LIVE claim's distilled chain row (T16's refs; an ABSORBED claim no longer protects) are never pruned, and crystallization candidates (retrieval_count >= 5) stay; tested for all three protections

## Wave 6 — Memory-native rank (REQ-7) — after Waves 2-4, on honest + compact data
- [x] T21 (REQ-7 AC1): features per scored row: Kyudo trust (zone → channel), Σ distance (chunk write position vs current; via the chain row of the same turn), claim evidence of the chunk's strand/turn (S125 RECALL_USED links), helped/misled history, decayed use count — `backend/memory/memory_rank.py` — DONE: trust = CHANNEL_WEIGHTS[channel_for_zone(zone)]; evidence = backs a LIVE claim (T16's distilled refs); outcome = (helped-misled)/(helped+misled+1) of the strand from RECALL_HELPED/MISLED events; use = retrieval_count decayed at the law's rate, capped; sigma = affinity to the current coords_to (ABSENT when either position is unknown, never zero); features cached at TTL 300 s so the shadow never puts its queries on the answer path; zero-variance features counted (HIDDEN FAILURES)
- [x] T22 (REQ-7 AC2): shadow rank recorded beside the live rank (decision rows for the Oracle bar); never changes context while shadow — DONE: every recall writes both top-k lists to `memory_rank_shadow` (bounded to the newest 5,000) + same/reordered counters; the surface overview exposes rank_shadow status; LIVE=False leaves the returned ranking untouched (tested)
- [x] T23 (REQ-7 AC3): switch only when the bench AND helped/misled outcomes show it pays; off switch; landmark (CLAUDE.md step 8) — DONE (gate ran, switch stays OFF): the bench measures the memory rank vs cosine on the SAME candidates per filter: research 0.7242 vs 0.9742, turn 0.7525 vs 0.9983, global 0.5608 vs 0.9625 — the memory rank LOSES on recall@10 (the use/outcome multipliers promote popular strands over relevant ones); `memory_rank.LIVE = False` is the off switch; the shadow keeps recording both rankings in production so a better-weighted rank can be judged on real decisions. No landmark: the gate did not pass (measured 2026-10-28, evals/results/memory-bench-20261027-230234.json)
- [x] T24 (REQ-6 AC3): the memory eval group: tasks whose answer needs a fact taught in an EARLIER thread (seed thread → new thread asks), graded by fact, reply_s; add to `evals/tasks.json` + `run_evals.py --group memory` — DONE: 3 tasks (m01 name, m02 number, m03 preference - invented facts that exist nowhere else), the runner seeds a fact in its own conversation then asks in a NEW one (a failed seed fails the task); live on mercury-3 (provider switched from the stale cerebras binding whose key 401'd): 2/3 PASS - m02 (880417) and m03 (fern-green) recalled across threads, reply_s 84/97; m01 FAILS with a finding: the ask's phrasing sends the model to TOOL steps (searching project files for a deployment config) instead of memory - when recall engages, cross-thread facts come back

## Dependency / parallelization notes
- Wave 2 first: every later number is measured on the vectors; 9.4% noise biases all of them.
- Waves 3 and 4 touch different code (FTS write hooks vs a lane backfill) and may run in
  parallel in separate sessions, but both change store size: run the bench after each lands.
- Wave 5 depends on Wave 4's fold (a fold is a decay by agreement); Wave 6 depends on 2-4.
- NO-CHANGE areas that only need their locks kept green: S79/S81 standards, the reindex
  dual-read, every recall caller.
- New dependencies (sqlite-vec, faiss, hnswlib) are out unless the owner says yes; if the
  10× scan in the bench ever exceeds 150 ms p95, raise it as a finding, do not add one.

## Wave 7 - File recall (REQ-9)
- [x] T25 (REQ-9 AC1/AC2/AC6): ingest = node + chunks through the EXISTING writer. Identity in `file_nodes` (`file_path UNIQUE`, `last_edited` = mtime, +`content_hash`/`file_size`), payload through `fragment_and_store` (chunking, 0.92 dedup, int8 + fp, FTS triggers), `keep_float=False` -> 1,160 B/chunk instead of 5,256. Done: `backend/memory/file_ingest.py`.
- [x] T26 (REQ-9 AC3): a changed file folds its old chunks (`folded_into`); never deletes. BUG FOUND ON THE LIVE STORE: the fold ate its own 25 of 26 chunks; fixed by excluding the ids this ingest wrote, and the test now pins "a NEW chunk must stay live".
- [x] T27 (REQ-9 AC4): kernel file leg, session-less + zone-addressed, probed once per kernel (`agent_kernel.py` 3a-3). Live gate PASS on requirements.md (23,231 B -> 26 chunks, 0 float, 3 meaning hits, 6 FTS hits, re-ingest unchanged).
- [x] T28 (REQ-9 AC8): bench `files` section + `compression.types.file` row (float 1.0 vs int8 1.0, delta 0.0).
- [ ] T29 (REQ-9 W2/W3/W4): PDF/DOCX/XLSX, OCR, audio/video. BLOCKED on named packages at install (owner yes already given for the types).
- [ ] T30 (REQ-9 AC7 + cold storage): prune file chunks by budget and re-ingest on demand while the file hash matches - the filesystem is their cold tier. OWNER APPROVED 2026-10-28.

## Wave 8 - Two planes (REQ-10) - repair first
- [ ] T31 (REQ-10 AC7): repair `coords_from`/`coords_to` so they hold only coordinates (10,102 / 10,664 rows hold 'json', 'markdown', 'rest:input:<id>' today). No metric on phase before this.
- [ ] T32 (REQ-10 AC2): establish the incidence join on `thread_id` (measured 38.6 % global, 0 % by session). Report the match rate.
- [ ] T33 (REQ-10 AC3/AC4/AC5): sweep lambda per filter on the bench: turn (100 % coverage) only at first; absent != zero; keep lambda only if `recall@10_live` beats 0.86 / 0.9442 / 0.8667.

## Wave 9 - Three levels (REQ-11) - prepare, do not build the CLM
- [ ] T34 (REQ-11 AC5): reconcile the 1,584 / 5,262 key gap; report the new match rate.
- [ ] T35 (REQ-11 AC2): `episodes.vec_i8/vec_fp/vec_scale` backfilled from `embedding`; bench-verified delta <= 0.02.
- [ ] T36 (REQ-11 AC1/AC3/AC4): `thread_context` derived table + backfill; measure the L1 scan against the 20x expectation (673 KB vs 13.6 MB).
- [ ] T37 (REQ-11 AC4): recall path may use L1 as the region scan (REQ-1 AC6) once T36 lands.

## Handoff - CLM spec is NEXT
- The CLM (`docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`) gets its own spec after this one is
  finalized. It inherits: three addressable levels, one codec, incidence to the phase plane,
  an immutable record layer, an L2 vector already in `episodes`.
- It must not re-litigate: two planes (REQ-10), the codec (REQ-4), the Kyudo decay law (REQ-5),
  and "no new dependency without the owner".

## Status correction (2026-10-28, end of session)
Boxes above are stale in three places. True state:
- [x] T33 (REQ-10 lambda): DONE and NEGATIVE. Measured with the mapping fixed (ids[i] is the rowid; the loop is all indices). Coverage research 0.000 / turn 1.000 / global 0.291; recall@10_shipped global 0.9900 -> 0.9125 at lambda 0.05 and 0.8333 at 0.10. Lambda stays 0. Pin pin_c3e628e03c86.
- [x] T35 (episodes codec): DONE. 362/362 rows carry vec_i8 + vec_fp + vec_scale (backend/memory/levels.py, commit 837a44eb).
- [x] T36 (thread_context): DONE. 8,098 rows covering all 143,265 chunks in 2.7 s; L1 fingerprint scan 1,036,544 B vs 18,337,920 B = 17.7x.
- [~] T31 (coords): PARTIAL. Non-coordinate values quarantined to coords_*_raw (165 from, 947 to); 3,637 / 3,075 real positions kept. Empty strings remain; the true coordinates of the 947 rows are NOT recoverable - they were overwritten before this session.
- [ ] T32 incidence join, T34 key gap, T37 L1-as-region-scan: NOT done. Measured only (T32: 100% turn, 38.6% global); no production code uses L1 or the incidence join yet.
- [ ] T4b scan-by-region: DEFERRED, bar met (10x scan p95 115.98 ms < 150 ms).
- [ ] T29 file W2-W4 (blocked on packages), T30 file cold tier (approved, not built).

## Status correction 2 (2026-10-28, later)
- [x] T29 (REQ-9): W2 DONE - .pdf (pypdf), .docx (python-docx), .xlsx (openpyxl) extract, all through the one ingest path. W3 (OCR) and W4 (audio/video) remain: no OCR binary, no transcription route chosen.
- [x] T30 (REQ-9 AC7): DONE - prune_to_budget evicts whole files to the budget, ensure() rebuilds from disk. Files are a cache; the filesystem is their cold tier.
- [x] T34 (REQ-11 AC5): RESOLVED - the gap is population (6,514 eval-harness sessions vs 3,678 payload-free chain threads). thread_context.chain_linked records it: 376 of 8,098 sessions carry a real coordinate.
- [x] T32 (REQ-10 AC2): CLOSED BY MEASUREMENT - the incidence join exists and is measured (100% turn, 376 sessions with coordinates). Not wired into recall because T33 rejected the blend it would feed.
- [x] T33 (REQ-10 AC3): CLOSED NEGATIVE - lambda 0.05 costs global 7.8 points.
- [x] T4b + T37 (REQ-1 AC6 / REQ-11 AC4): CLOSED AS NOT NEEDED NOW - region scan exists as data (L1, 17.7x) but the 10x scan p95 is 115.98 ms, under the 150 ms bar. Wiring L1 into recall today would be unused code; revisit at ~1M chunks.
- [ ] T29 W3/W4 only (OCR, audio) remain open in REQ-9.

## Wave 10 — Audit Remediation: Delivered-Rank Fidelity, Vectorized Rescore, Bounded Filters & Cross-Conversation Fact Persistence (2026-10-29, `pin_7cee599c0fc3`)

> Supersedes the faulty diagnosis in `pin_c26f13059c2f`. Execute `T38`–`T45` in order before starting `specs/clm-memory/`.

- [ ] T38 (REQ-3 AC2): Fix keyword promotion in `EpisodicStore.retrieve_context_chunks` (`backend/memory/episodic.py:1306-1312` and `:1198-1202`): remove `scored = _kw_rows + _rest` (which places up to 50 FTS OR-query hits ahead of all 1,000 semantic candidates) and replace with a single-slot keyword guarantee (when `limit > 0`, `_kw_ids` is non-empty, and no row in `scored[:limit]` is in `_kw_ids`, replace `scored[limit - 1]` with the highest-scoring `_kw_ids` survivor); also replace the dead `chunk_fts.fuse_by_rank(_near, _kw)` call on unsorted `argpartition` output with a direct deduplicated union — `backend/memory/episodic.py`, `backend/tests/contract/test_memory_chunk_fts_contract.py` (`CT-W10-1`) — RIPPLE: `test_exact_words_reach_a_row_the_fingerprint_cannot` stays green while prose queries keep their top `limit - 1` semantic matches.
- [ ] T39 (REQ-1 AC7): Fix `since`, `until`, and `tool_name` bounded filters in `EpisodicStore.retrieve_context_chunks` (`backend/memory/episodic.py:1205-1256`): include `where_sql` in the `WHERE rowid IN (...)` query, fetch up to `FP_CANDIDATES` rows matching `where_sql` directly when `_bounded` is True so selective `tool_name` / time-window queries have full reach beyond the global top-1000, and remove the per-row `logger.warning("[EpisodicStore] row skipped by bounds...")` at line `1254` — `backend/memory/episodic.py`, `backend/tests/contract/test_recall_filter_arguments.py` (`CT-W10-2`) — RIPPLE: `test_answer_path_standards.py` S79/S81 plans unchanged.
- [ ] T40 (REQ-12 AC6): Replace the 1,050-row Python `_cosine` + `.tolist()` rescore loop in `EpisodicStore.retrieve_context_chunks` (`backend/memory/episodic.py:1205-1305`) with a two-phase vectorized numpy rescore: Phase 1 selects metadata + `vec_i8, vec_scale, embedding` (excluding `content`) and computes cosine similarity via one numpy matrix-vector multiply; Phase 2 selects `id, content` only for the `<= limit` winning rows — `backend/memory/episodic.py`, `backend/tests/contract/test_recall_filter_arguments.py` (`CT-W10-3`) — RIPPLE: `memory_rank.shadow` (`:1324`) and crystallization (`:1365`) receive the same `scored` / `top` tuples.
- [ ] T41 (REQ-12 AC2): Lower the minimum chunk length for `chunk_type == "context_fragment"` in `EpisodicStore.fragment_and_store` (`backend/memory/episodic.py:152, 959, 968`) to `_USER_CHUNK_MIN_CHARS = 10` (keeping `_CHUNK_MIN_CHARS = 50` for `der_output`), and when a new `context_fragment` chunk has cosine `>= _FRAG_DEDUP_THRESHOLD` (`0.92`) with an existing chunk, insert the new chunk and fold (`folded_into = new_id`) the older chunk via `app_write` instead of silently skipping the re-taught statement — `backend/memory/episodic.py`, `backend/tests/contract/test_turn_start_recall_contract.py` (`CT-W10-5`) — RIPPLE: `fold_chunks` and `folded_into IS NULL` filters already exclude folded chunks.
- [x] T42 (REQ-12 AC1, AC3): Persist user statements on both turn paths: (a) at turn entry in `AgentKernel.process_text_message` (`backend/agent/agent_kernel.py:9127`), submit a side-lane job appending a `role="user"`, `node_type="user_turn"` row to `memory_chain` with `thread_id=_conv_id` and the user text in `content` and `insight` (bounded to S12); (b) on turn completion for BOTH the direct path (`agent_kernel.py:9363-9391`) and the DER path (`agent_kernel.py:9888`), submit `_turn = f"User: {text}\nAssistant: {response}"` to `fragment_and_store(..., chunk_type="context_fragment", zone=_zone, keep_float=False)` via `pacman_fragment._submit_fragment_job` (bypassing `pacman_fragment._is_fragment_candidate` for `context_fragment` turn pairs) — `backend/agent/agent_kernel.py`, `backend/agent/mcm_protocol/actions/pacman_fragment.py` — RIPPLE: `iris_gateway.py:6169` (`get_agent_kernel`) already wires `_memory_interface` and `_mcm_orch`.
- [x] T43 (REQ-12 AC4, AC5): Fix cross-conversation recall in `ontology_recall.py` and `agent_kernel.py`: (a) in `relevance_gate` (`backend/agent/ontology_recall.py:474-476`), include `r.get("content")` in the matched text alongside `insight` and `result`; (b) in `turn_start_prior_memory` (`ontology_recall.py:557-563`), sort relevant candidates by `(0 if role == "user" else 1, -created_at)` BEFORE slicing to `TURN_START_KEEP`; (c) in `_plan_task` (`backend/agent/agent_kernel.py:8486-8489`), include `str(_pm_r.get("content") or "")[:240]` when formatting `_pm_line`; (d) add a bounded cross-session trusted `context_fragment` chunk fallback (`session_id=None, chunk_types=["context_fragment"], zones=["trusted"], limit=3, min_similarity=0.45`) in `_assemble_direct_context` (`:4046`) and `_plan_task` (`:8482`) so embedding similarity bridges spelling/synonym differences (`color` vs `colour`) across conversations — `backend/agent/ontology_recall.py`, `backend/agent/agent_kernel.py`, `backend/tests/contract/test_turn_start_recall_contract.py` (`CT-W10-4`) — RIPPLE: `IRIS_TURN_START_RECALL=0` off-switch preserved.
- [x] T44 (REQ-12 AC7, REQ-6 AC1b/AC2): Purge harness rows from `memory_chain` in `scripts/purge_harness_chunks.py` (`DELETE FROM memory_chain WHERE thread_id LIKE 'eval-%' OR ...`), and fix `evals/memory_bench.py`: (a) parenthesize `WHERE (embedding IS NOT NULL OR vec_i8 IS NOT NULL) AND folded_into IS NULL` at lines `227` and `273`; (b) pass `m=_m` explicitly for all keys in `ceiling_by_m` at line `376`; (c) include the FTS candidate union and single-slot keyword rule in `recall@10_live` / `recall@10_shipped`; (d) record and guard `recall@10_live` in `evals/standards.json`; (e) re-record `evals/standards.json` at the default `--queries 120 --words 40` load — `scripts/purge_harness_chunks.py`, `evals/memory_bench.py`, `evals/standards.json` (`CT-W10-6`) — RIPPLE: `standards.json` "memory" block updated with honest 40-case word reach and `recall@10_live`.
- [x] T45 (REQ-13 AC1): Upgrade the active `recall_memory` tool (`backend/agent/tool_registry.py:994-1001`, `backend/agent/tool_bridge.py:889-896, 2497-2522`) to accept `query` plus optional `since`, `until`, and `tool_name` parameters, and return `{ "success": True, "chunks": ..., "chain": ..., "episodes": ..., "results": ... }` combining `retrieve_context_chunks(query, session_id=None, since=since, until=until, tool_name=tool_name, limit=5)`, `turn_start_prior_memory(conn, query)`, and `retrieve_similar(task=query, limit=3)` — `backend/agent/tool_registry.py`, `backend/agent/tool_bridge.py`, `backend/tests/contract/test_recall_filter_arguments.py` (`CT-W10-7`) — RIPPLE: gives `since`/`until`/`tool_name` (`cb41c577`) a production caller and prevents `recall_memory` steps from returning empty on chunk/chain facts.
- [x] T46 (REQ-13 AC2, AC3): Add `confidence_floor`, `channel_weight(write_lock) * freshness(decay_rate)` weighting (`_EXTERNAL` capped at `0.30` with `3×` decay), resonance node filtering, and lazy-on-dirty section rendering inside `ProfileRenderer` (`backend/memory/mycelium/profile.py:452-750`) and `MyceliumInterface._context_parts` (`backend/memory/mycelium/interface.py:836-855`) so `toolpath` (`render_order=None`) is never rendered, non-matching `task_classes` spaces are excluded, and sections below `confidence_floor` are dropped — `backend/memory/mycelium/profile.py`, `backend/memory/mycelium/interface.py` (`CT-W10-8`) — RIPPLE: extends the existing `_context_parts` profile assembly (`interface.py:836`) instead of creating a duplicate reader.
- [x] T47 (REQ-13 AC4): Wire `context_package.mycelium_path` (which holds `zone_header + encoding + partial_profile`) and `failure_warnings=context_package.get_tier3_failures()` into `AgentKernel._plan_task` (`backend/agent/agent_kernel.py:8395-8407, 8511-8519`, replacing the dead `tier1_directives=""` read), and inject the gated `partial_profile` into `AgentKernel._assemble_direct_context` (`agent_kernel.py:3999-4023`) when Mycelium is mature — `backend/agent/agent_kernel.py` (`CT-W10-9`) — RIPPLE: both DER planner and direct response paths receive the gated profile and failure warnings.
- [x] T48 (REQ-12 AC8, REQ-6 AC3): Run live verification (`BT-W10-1`, `BT-W10-2`): (a) verify `/health` 200 and tool model loaded (`python evals/load_tool_model.py`); (b) run `python evals/run_evals.py --group memory` (`m01`, `m02`, `m03`) and verify 3/3 PASS with fresh per-run facts; (c) run the 3-thread conflict probe (teach A in thread 1, teach B in thread 2, ask in thread 3 -> B wins) — `evals/run_evals.py` — DONE 2026-10-30: BT-W10-1 3/3 on three consecutive runs (reply_s m01 38.7/37.4, m02 14.2/41.9, m03 12.8/15.3); BT-W10-2 PASS twice (`bravo-*` wins, `alpha-*` absent). RIPPLE: unblocks `specs/clm-memory/`. Entry path is memory-aware: `semantic_gate.is_memory_question` + `is_memory_write` + word-boundary action verbs + turn-session memory legs, pinned by CT-W10-10 (`test_memory_question_routing_contract.py`). Harness hygiene: `_retire_taught_facts` also clears `episodes`, and `_retire_eval_memory` clears `eval-%` rows once per group. No routing skill (2026-10-30): the live memory heuristics are gone; the general anaphora guard + wh-question guard carry the route. Matrix 10/10 (1.3–3.2 s), gate 3/3 (`reply_s_ask` 2.7 / 1.2 / 1.4 s), BT-W10-2 PASS; native `remember`/`recall` over `mycelium_pins` (app_write, one writer); newest-fact dedupe via `_same_fact_text`. Oracle `route_v2` shadow 94 rows (75 non-null: writes -> `memory_write` 0.96–0.98, recalls -> `direct` 0.70–0.81, broad -> `memory_recall` 0.419), not flipped (bar 100 rows / 0.90 / ECE 0.05).

## Wave Gates (MANDATORY — per-AC verification)
- [x] **TG-1 (Wave 1 — REQ-1 AC1–AC5, REQ-6 AC1/AC2/AC4, REQ-8 AC1–AC2):** `test_memory_recall_reach_contract.py` (`CT-R1..R6`), `test_memory_snapshot_contract.py`, `evals/memory_bench.py` — PASS (2026-10-27; AC6 deferred to T4b).
- [x] **TG-2 (Wave 2 — REQ-2 AC1–AC4):** `test_embedding_honest_label_contract.py` (4/4), `test_memory_vector_repair_contract.py` (3/3), live sweep 14,412 repaired — PASS (2026-10-27).
- [x] **TG-3 (Wave 3 — REQ-3 AC1, AC3, AC4):** `test_memory_chunk_fts_contract.py` (30/30), `test_answer_path_standards.py` (13/13) — PASS (2026-10-28; AC2 amended in TG-10).
- [x] **TG-4 (Wave 4 — REQ-4 AC1–AC4):** `test_vector_quant_contract.py`, `test_fold_chunks_contract.py`, `test_distil_claims_contract.py`, live sweep 146,973 compressed / 35,847 folded / 98 distilled — PASS (2026-10-28).
- [x] **TG-5 (Wave 5 — REQ-5 AC1–AC3):** `test_chunk_decay_contract.py`, `test_memory_maintenance_contract.py` (3/3), live pass 3,734 pruned — PASS (2026-10-28).
- [x] **TG-6 (Wave 6 — REQ-7 AC1–AC4, REQ-6 AC3):** `test_memory_rank_contract.py`, `evals/run_evals.py --group memory` (2/3 baseline; 3/3 gated in TG-10) — PASS (2026-10-28; switch stays OFF per AC3).
- [x] **TG-7 (Wave 7 — REQ-9 AC1–AC8):** `test_file_ingest_contract.py` (7/7), `test_file_formats_and_cold_tier.py` (4/4) — PASS for W1/W2/cold-tier (2026-10-28; W3/W4 OCR/audio tracked under T29).
- [x] **TG-8 (Wave 8 — REQ-10 AC1–AC7):** `evals/memory_bench.py` phase sweep + `coords_*_raw` quarantine (`pin_c3e628e03c86`) — PASS (2026-10-28; λ = 0 kept).
- [x] **TG-9 (Wave 9 — REQ-11 AC1–AC6):** `backend/memory/levels.py` L1 `thread_context` + L2 `episodes` codec backfill (`837a44eb`) — PASS (2026-10-28).
- [ ] **TG-10 (Wave 10 — REQ-1 AC7, REQ-3 AC2, REQ-6 AC1b/AC2/AC3, REQ-12 AC1–AC8, REQ-13 AC1–AC4):** `CT-W10-1..CT-W10-9` green + `python evals/memory_bench.py` green at `--words 40` + `BT-W10-1` (`m01`–`m03` 3/3 PASS) + `BT-W10-2` (conflict test newest wins).

## Traceability Matrix (66 ACs total: 65 covered, 1 deferred, 0 unmapped)

| REQ | AC | Covering tasks | Covering tests / verification | Status |
|---|---|---|---|---|
| REQ-1 | AC1 | T1 | `test_memory_recall_reach_contract.py` (`CT-R1`) | covered (proven) |
| REQ-1 | AC2 | T2 | `test_memory_recall_reach_contract.py` (`CT-R2`, `CT-R4`), `evals/memory_bench.py` | covered (proven) |
| REQ-1 | AC3 | T1, T2 | `test_memory_recall_reach_contract.py` (`CT-R3`) | covered (proven) |
| REQ-1 | AC4 | T1, T2 | `test_memory_recall_reach_contract.py` (`CT-R5`) | covered (proven) |
| REQ-1 | AC5 | T1, T2 | `test_memory_recall_reach_contract.py` (`CT-R6`) | covered (proven) |
| REQ-1 | AC6 | T4b, T37 | DEFERRED (warm 10× scan p95 = 115.98 ms < 150 ms bar; owner 2026-10-28) | DEFERRED |
| REQ-1 | AC7 | T39 | `test_recall_filter_arguments.py` (`CT-W10-2`) | covered (Wave 10) |
| REQ-2 | AC1 | T6, T9 | `test_embedding_honest_label_contract.py` | covered (proven) |
| REQ-2 | AC2 | T7, T9 | `test_embedding_honest_label_contract.py` | covered (proven) |
| REQ-2 | AC3 | T8, T9 | `test_memory_vector_repair_contract.py` | covered (proven) |
| REQ-2 | AC4 | T8, T9 | `test_memory_vector_repair_contract.py` | covered (proven) |
| REQ-3 | AC1 | T10 | `test_memory_chunk_fts_contract.py` | covered (proven) |
| REQ-3 | AC2 | T11, T38 | `test_memory_chunk_fts_contract.py` (`CT-W10-1`) | covered (Wave 10) |
| REQ-3 | AC3 | T21, T22 | `test_memory_rank_contract.py` | covered (proven) |
| REQ-3 | AC4 | T12 | `test_memory_chunk_fts_contract.py` | covered (proven) |
| REQ-4 | AC1 | T14 | `test_vector_quant_contract.py`, `evals/memory_bench.py` | covered (proven) |
| REQ-4 | AC2 | T15 | `test_fold_chunks_contract.py` | covered (proven) |
| REQ-4 | AC3 | T16 | `test_distil_claims_contract.py` | covered (proven) |
| REQ-4 | AC4 | T17 | `evals/memory_bench.py`, `evals/standards.json` | covered (proven) |
| REQ-5 | AC1 | T18 | `test_chunk_decay_contract.py`, `test_memory_maintenance_contract.py` | covered (proven) |
| REQ-5 | AC2 | T19 | `test_memory_maintenance_contract.py`, `evals/memory_bench.py` | covered (proven) |
| REQ-5 | AC3 | T20 | `test_chunk_decay_contract.py` | covered (proven) |
| REQ-6 | AC1 | T4 | `evals/memory_bench.py` | covered (proven) |
| REQ-6 | AC1b | T4, T44 | `evals/memory_bench.py`, `CT-W10-6` | covered (Wave 10) |
| REQ-6 | AC2 | T4, T13, T44 | `evals/memory_bench.py`, `evals/standards.json`, `CT-W10-6` | covered (Wave 10) |
| REQ-6 | AC3 | T24, T48 | `evals/run_evals.py --group memory` (`BT-W10-1`) | covered (Wave 10) |
| REQ-6 | AC4 | T4 | `specs/memory-recall-reach/design.md` reference table | covered (proven) |
| REQ-7 | AC1 | T21 | `test_memory_rank_contract.py` | covered (proven) |
| REQ-7 | AC2 | T22 | `test_memory_rank_contract.py` | covered (proven) |
| REQ-7 | AC3 | T23 | `evals/memory_bench.py` (`recall@10_memory_rank`) | covered (proven) |
| REQ-7 | AC4 | T21 | `test_caducean_phase_scheduler_contract.py` (CT-3/CT-4) | covered (proven) |
| REQ-8 | AC1 | T2 | `test_memory_recall_reach_contract.py` | covered (proven) |
| REQ-8 | AC2 | T5 | `test_memory_snapshot_contract.py` | covered (proven) |
| REQ-9 | AC1 | T25 | `test_file_ingest_contract.py` | covered (proven) |
| REQ-9 | AC2 | T25, T29 | `test_file_ingest_contract.py`, `test_file_formats_and_cold_tier.py` | covered (proven) |
| REQ-9 | AC3 | T26 | `test_file_ingest_contract.py` | covered (proven) |
| REQ-9 | AC4 | T27 | `test_file_ingest_contract.py` | covered (proven) |
| REQ-9 | AC5 | T25 | `test_file_ingest_contract.py` | covered (proven) |
| REQ-9 | AC6 | T25 | `test_file_ingest_contract.py` | covered (proven) |
| REQ-9 | AC7 | T25, T30 | `test_file_formats_and_cold_tier.py` | covered (proven) |
| REQ-9 | AC8 | T28 | `evals/memory_bench.py` (`files` section) | covered (proven) |
| REQ-10 | AC1 | T33 | `test_memory_recall_reach_contract.py` (`FP_BYTES = 128`) | covered (proven) |
| REQ-10 | AC2 | T32 | `evals/memory_bench.py` (`_load_positions`) | covered (proven) |
| REQ-10 | AC3 | T33 | `evals/memory_bench.py` (`_affinity`, `recall@10_phase`) | covered (proven) |
| REQ-10 | AC4 | T33 | `evals/memory_bench.py` (`phase_coverage`) | covered (proven) |
| REQ-10 | AC5 | T33 | `evals/memory_bench.py` (`_affinity` returns `None` when absent) | covered (proven) |
| REQ-10 | AC6 | T33 | `test_caducean_phase_scheduler_contract.py` (CT-3/CT-4) | covered (proven) |
| REQ-10 | AC7 | T31 | `coords_*_raw` quarantine (`pin_c3e628e03c86`) | covered (proven) |
| REQ-11 | AC1 | T36 | `backend/memory/levels.py` (`thread_context` backfill) | covered (proven) |
| REQ-11 | AC2 | T35 | `backend/memory/levels.py` (`episodes` codec backfill) | covered (proven) |
| REQ-11 | AC3 | T35, T36 | `backend/memory/levels.py` (`vector_quant.compress`) | covered (proven) |
| REQ-11 | AC4 | T36, T37 | `backend/memory/levels.py` (`report()` 17.7× ratio) | covered (proven) |
| REQ-11 | AC5 | T34 | `backend/memory/levels.py` (`chain_linked` column) | covered (proven) |
| REQ-11 | AC6 | T36 | `backend/memory/levels.py` (`thread_id` keying) | covered (proven) |
| REQ-12 | AC1 | T42 | `test_turn_start_recall_contract.py` (`CT-W10-5`), `BT-W10-1` | covered (Wave 10) |
| REQ-12 | AC2 | T41 | `test_turn_start_recall_contract.py` (`CT-W10-5`) | covered (Wave 10) |
| REQ-12 | AC3 | T42 | `test_turn_start_recall_contract.py` (`CT-W10-4`), `BT-W10-1` | covered (Wave 10) |
| REQ-12 | AC4 | T43 | `test_turn_start_recall_contract.py` (`CT-W10-4`), `BT-W10-2` | covered (Wave 10) |
| REQ-12 | AC5 | T43 | `test_turn_start_recall_contract.py` (`CT-W10-4`), `BT-W10-1` | covered (Wave 10) |
| REQ-12 | AC6 | T40 | `test_recall_filter_arguments.py` (`CT-W10-3`) | covered (Wave 10) |
| REQ-12 | AC7 | T44 | `scripts/purge_harness_chunks.py` | covered (Wave 10) |
| REQ-12 | AC8 | T48 | `evals/run_evals.py --group memory` (`BT-W10-1`, `BT-W10-2`) | covered (Wave 10) |
| REQ-13 | AC1 | T45 | `test_recall_filter_arguments.py` (`CT-W10-7`) | covered (Wave 10) |
| REQ-13 | AC2 | T46 | `test_mycelium_profile_read_contract.py` (`CT-W10-8`) | covered (Wave 10) |
| REQ-13 | AC3 | T46 | `test_mycelium_profile_read_contract.py` (`CT-W10-8`) | covered (Wave 10) |
| REQ-13 | AC4 | T47 | `test_mycelium_profile_read_contract.py` (`CT-W10-9`) | covered (Wave 10) |
