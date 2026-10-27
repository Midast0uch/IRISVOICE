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
- [ ] T4b (REQ-1 AC6): scan by region (Kyudo zone → sector root → strand) once the 10× scan p95 (236 ms measured) matters; keep per-region column blocks — `recall_reach.py` — RIPPLE: bench 10× scan, sector assignment (owner-gated births; use existing roots only)
- [ ] T5 (REQ-8 AC2): expose `recall_reach.COUNTERS` + build seconds on `/api/memory/overview` — `backend/memory/surface_queries.py` — RIPPLE: snapshot contract keys (`test_memory_snapshot_contract.py`)

## Wave 2 — Honest vectors (REQ-2) — do first: the other waves measure on these vectors
- [ ] T6 (REQ-2 AC1): `_encode_chunk_with` reports whether it fell back; `_encode_uncached_with` labels a result with the fallback backend when ANY chunk fell back (never max-pool hash with model chunks) — `backend/memory/embedding.py:750-779` — RIPPLE: `Embedding` dataclass consumers, `compare_embeddings` (fallback rows become their own space: excluded from LFM recall automatically)
- [ ] T7 (REQ-2 AC2): count fallbacks by cause + caller; a fallback on the answer path logs a warning with the conversation id — `embedding.py` — RIPPLE: HIDDEN FAILURES rule 4
- [ ] T8 (REQ-2 AC3, AC4): repair lane: find LFM-labelled rows with > 50% zero components (measured 9.4%), re-embed in bounded batches on `lane("memory_repair")`, write via `db.app_write`, resumable by rowid — new `scripts/repair_mislabelled_vectors.py` + a lane job — RIPPLE: fingerprints refresh only new rowids → after a repair pass, restart or add an "updated rowids" hook to `recall_reach`
- [ ] T9: guard — a contract test that a failing model call yields a non-LFM label (fails on today's code); bench before/after (recall@10 should rise on document_data)

## Wave 3 — Exact words (REQ-3)
- [ ] T10 (REQ-3 AC1): FTS5 table over `context_chunks.content` (external content, rowid-linked), insert/delete kept in step with the one writer; backfill on a lane — `episodic._init_schema`, chunk write paths (`episodic.py:936-960`) — RIPPLE: run `test_answer_path_standards` FIRST (S2: a new index can steal the planner); store size (measure)
- [ ] T11 (REQ-3 AC2): fuse keyword rank with fingerprint rank by reciprocal rank into the candidate union (the union, not the final score: exact scoring stays) — `episodic.py` reach block, `recall_reach` — RIPPLE: candidate count bound (M + K + 50)
- [ ] T12 (REQ-3 AC4): missing/broken FTS → meaning only, counted
- [ ] T13: bench gains a "words" query set (paths, error strings, names from real turns); standard for it

## Wave 4 — Compress where outcomes agree (REQ-4)
- [ ] T14 (REQ-4 AC1): persist the fingerprint + an int8 vector per chunk (`vec_i8`, `vec_scale`), backfill on a lane; recall reads int8 for exact scoring; bench: recall@10 within 0.02 of float per chunk type, else keep float for that type — RIPPLE: warm-up reads 1,152 B/row instead of 4,096 (faster build)
- [ ] T15 (REQ-4 AC2): fold near-duplicates of one strand with the same outcome (cosine ≥ 0.92 — the existing `_FRAG_DEDUP_THRESHOLD`) into one row with `folded_into` references, on the integrity lane; never across Kyudo zones; never a pinned chunk — RIPPLE: corrections undo (keep references), Memory surface counts
- [ ] T16 (REQ-4 AC3): distil a proven claim's agreeing chunk cluster into the claim + chain references (`memory_chain.distilled`), payload kept only where Kyudo trust allows — RIPPLE: landmark evidence, chain recall (`chain_timeline`), MEMORY-INTERFACE Part II §F11
- [ ] T17 (REQ-4 AC4): bench before/after each step; bytes per chunk and store size into the standard

## Wave 5 — Budget + decay (REQ-5)
- [ ] T18 (REQ-5 AC1): give `cleanup_stale_chunks` its production caller as part of the ONE Kyudo decay law (channel rate; RECALL_USED/HELPED slow it, MISLED speeds it) on the integrity lane — `backend/memory/mycelium/decay.py`, `episodic.py:1164` — RIPPLE: MEMORY-INTERFACE Part II §F11 (one law), owner rule: growth and decay in the same law
- [ ] T19 (REQ-5 AC2): store budget per zone (bytes, rows) + a guard that fails when exceeded; prunes typed MEMORY_PRUNED with the reason — RIPPLE: ghosts on the Memory surface (already read MEMORY_PRUNED)
- [ ] T20 (REQ-5 AC3): never prune a chunk that backs a live claim or a pin

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
