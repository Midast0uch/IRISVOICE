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
- [ ] T21 (REQ-7 AC1): features per scored row: Kyudo trust (zone → channel), Σ distance (chunk write position vs current; via the chain row of the same turn), claim evidence of the chunk's strand/turn (S125 RECALL_USED links), helped/misled history, decayed use count — `recall_reach` or a small scorer beside `_shadow_trust_rank` — RIPPLE: CT-3/CT-4 (the scheduler never reads live u/ξ; this is the cognitive layer)
- [ ] T22 (REQ-7 AC2): shadow rank recorded beside the live rank (decision rows for the Oracle bar); never changes context while shadow
- [ ] T23 (REQ-7 AC3): switch only when the bench AND helped/misled outcomes show it pays; off switch; landmark (CLAUDE.md step 8)
- [ ] T24 (REQ-6 AC3): the memory eval group: tasks whose answer needs a fact taught in an EARLIER thread (seed thread → new thread asks), graded by fact, reply_s; add to `evals/tasks.json` + `run_evals.py --group memory`

## Dependency / parallelization notes
- Wave 2 first: every later number is measured on the vectors; 9.4% noise biases all of them.
- Waves 3 and 4 touch different code (FTS write hooks vs a lane backfill) and may run in
  parallel in separate sessions, but both change store size: run the bench after each lands.
- Wave 5 depends on Wave 4's fold (a fold is a decay by agreement); Wave 6 depends on 2-4.
- NO-CHANGE areas that only need their locks kept green: S79/S81 standards, the reindex
  dual-read, every recall caller.
- New dependencies (sqlite-vec, faiss, hnswlib) are out unless the owner says yes; if the
  10× scan in the bench ever exceeds 150 ms p95, raise it as a finding, do not add one.
