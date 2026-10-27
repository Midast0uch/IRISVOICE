# Design: Memory Recall Reach and Performance

## Context
IRIS's memory is not a vector database and must not be rebuilt as one. Its parts each
answer a different question:

| Part | Question it answers | Store |
|---|---|---|
| Context chunks | what was said / read / produced (payload) | `context_chunks` (146,653 rows) |
| Immortus chain | what happened, in order, by reference (never payload) | `memory_chain` (58,117) |
| Mycelium coordinates | who the user is, how the machine works (profile) | `mycelium_nodes` / spaces |
| Landmarks | what is PROVEN true by outside evidence (claims) | `mycelium_landmarks` |
| Kyudo | how much a source may write, how fast it fades, where it may go | channels, zones, decay |
| Caducean Σ | the phase of the work when anything happened | `caducean_trajectories`, chain coords |
| Events | the closed alphabet of what each step meant | `memory_events` (56,757) |

LEANN and memvid both answer one question - "which stored text is nearest this text?" -
and optimise storage (LEANN) or packaging/latency (memvid) for it. IRIS needs that answer
too (chunks), but recall here is a NAVIGATION: from the current position (Σ, the strand,
the zone), along what is proven and used, to the payload. The design keeps the nearest-text
answer as one cheap component and puts the memory's own structure around it.

Constraints: CPU only; the answer path waits only for plan → nodes → verify → synthesis
(everything else on a lane); one writer for the store (`db.app_write`); no new dependency
without the owner; every computed signal needs a production consumer and a sane value.

## Architecture Overview

```mermaid
flowchart LR
  Q[query + current position<br/>strand, zone, Sigma] --> F[filter<br/>Kyudo zone, type, strand,<br/>same embedding space]
  F --> FP[fingerprint scan<br/>1 bit/dim, all rows<br/>REQ-1]
  F --> KW[FTS5 words<br/>REQ-3]
  F --> NEW[newest 50<br/>recency floor]
  FP --> U[candidate union]
  KW --> U
  NEW --> U
  U --> EX[exact score<br/>cosine 0.8 + recency 0.2]
  EX --> LIVE[live rank -> context]
  EX --> NAT[memory-native rank SHADOW<br/>trust, Sigma distance, claim evidence,<br/>helped/misled, use - REQ-7]
  NAT -. Oracle bar + bench .-> LIVE
  subgraph lanes [side lanes, never the answer path]
    W[chunk write] --> H[honest vector<br/>REQ-2]
    H --> C[compress where outcomes agree<br/>fold, int8, distil - REQ-4]
    C --> D[Kyudo decay + budget<br/>REQ-5]
  end
```

## Sequence / Data Flow (REQ-1, built)

```mermaid
sequenceDiagram
  participant K as caller (research / turn / decoder)
  participant E as EpisodicStore.retrieve_context_chunks
  participant R as recall_reach.ChunkFingerprints
  participant S as app store (own read connection per thread)
  K->>E: query, filter
  E->>E: embed query (one EmbeddingService call, as before)
  E->>R: candidates(query, backend, filter)
  alt index warm
    R->>S: rows with rowid > last seen (delta, usually 0-30)
    R-->>E: 200 nearest rowids by Hamming distance
    E->>S: newest 50 of the filter + those 200 by rowid
  else warming / failed (counted)
    R-->>E: None
    E->>S: newest 200 of the filter (the old path)
  end
  E->>E: exact score, sort, token cap, retrieval_count (unchanged)
  E-->>K: chunk texts
```

Warm-up: the first `index_for(path)` starts one daemon thread that reads every vector once in
batches of 5,000 rows (measured build time in the bench), computes the store mean, keeps the
sign bits. Nothing is written.

## Data Models

`ChunkFingerprints` (per store path, in RAM):

| Field | Type | Bytes/row | Meaning |
|---|---|---|---|
| `_codes` | uint64 (16, capacity) | 128 | sign of each component, packed; COLUMN-major so the scan is 16 contiguous passes |
| `_rowids` | int64 (n,) | 8 | `context_chunks.rowid` |
| `_session`, `_type`, `_zone`, `_backend` | int32 / int16 | 10 | filter columns, by small id tables |

~146 B per chunk, ~21 MB at today's 146,653 rows; bound FP_MAX_ROWS = 1,000,000 (~146 MB).

Planned (REQ-3/4, not built): `context_chunks_fts` (FTS5, content = context_chunks, rowid
linked); `context_chunks.vec_i8` BLOB (1,024 B) + `vec_scale` REAL; `context_chunks.folded_into`
TEXT; `memory_chain.distilled` used as specified.

## Key Decisions

1. **Fingerprint first, exact score second** (REQ-1). One bit per dimension is both the
   compression and the index: 32× smaller than float32, scanned with `np.bitwise_count` in
   milliseconds, and the M = 200 survivors are scored exactly as before - so the ranking
   formula, thresholds and every caller are unchanged; only WHICH rows are scored changes.
   Rejected: HNSW/sqlite-vec (new dependency, an index to keep in sync on every write, an
   approximate graph that needs tuning); LEANN recomputation (embedding calls at query time).
2. **Plain signs, measured.** Signs about a mean taken from raw vectors (norms up to 72.5)
   reached recall@10 0.35 on the whole store; plain signs reach 0.96 (0.963 at M=200, 0.985 at
   M=500 on 40 queries). The centre is 0; nothing to drift.
2b. **Column-major codes, two scan paths.** Row-major `bitwise_count(...).sum(axis=1)` took
   28 ms at 147k rows; 16 contiguous passes with a reused buffer take 9.9 ms. A filter that
   allows under 1/8 of the rows scans only its rows (research 1,777 rows: p95 9.5 ms).
   Capacity doubles, so a new row never copies the matrix.
3. **The newest 50 stay in the scored set.** The old path's recency behaviour survives
   (a chunk written seconds ago is always considered), so the change is a superset in spirit.
4. **No schema change for REQ-1.** Fingerprints are derived from the stored vectors; a
   rebuild is a restart. Persisting them (REQ-4 AC1) comes with the compression work.
5. **Memory-native ranking stays shadow until it earns the job** (REQ-7) - the same bar the
   Oracle consumers use. Cosine is a fine first rank; the memory's structure has to prove it
   ranks better on the bench and on helped/misled outcomes.
6. **Compression is the operator, not a codec** (REQ-4): fold where outcomes agree, distil
   proven clusters into a claim + references, keep payloads only where Kyudo trust allows -
   the same "compress where outcomes agree" the DER loop and the Mycelium graph already use.
   int8 storage is the one codec, and only where the bench shows ≤ 0.02 recall loss.

### Reference points (their claims, their corpora - never mixed with ours)

| | LEANN (README) | memvid v2 (README) | IRIS (bench, this store) |
|---|---|---|---|
| storage | 91-97% below a FAISS flat index (e.g. 38K items: 130 MB → 6.4 MB ≈ 168 B/item) | single `.mv2` file, codec unspecified | fingerprint 128 B/chunk (+ float 4,096 B today; int8 1,024 B planned) |
| search | not published; recomputes embeddings on the search path | "0.025 ms P50, 0.075 ms P99" (undefined baseline) | candidate stage p50 / p95: research 2.1 / 9.5 ms, turn 5.4 / 20.6 ms, whole store 13 / 41 ms; 10× 171 / 236 ms |
| recall | "no accuracy loss" (no recall figures) | "+35% on LoCoMo" (LLM judge) | recall@10 vs exact search: 0.975 / 0.901 / 0.96 (was 0.14 / 0.054 / 0.029) |
| beyond retrieval | - | time index | position (Σ), proven claims, trust + decay, use feedback |

## Ripple-Effect Map

| Area / File | Change? | Classification | Why / Evidence |
|---|---|---|---|
| `backend/memory/recall_reach.py` | Yes (new) | CHANGE NEEDED (built) | the fingerprint index, warm-up, counters |
| `backend/memory/episodic.py` retrieve_context_chunks | Yes | CHANGE NEEDED (built) | candidate rows = 200 nearest + newest 50; old path on None (`episodic.py` reach block) |
| scoring, token cap, retrieval_count, crystallization signal | No | NO CHANGE (verified) | same loop over `rows` (`episodic.py:1063-1156`) |
| `research_memory.recall_prior_research` | No | NO CHANGE (verified) | calls retrieve_context_chunks with type/zone (`research_memory.py:482`) |
| `agent_kernel` turn recall (`:4046`, `:4065`) | No | NO CHANGE (verified) | session + zones passed through |
| `recall_decoder` (`:436`) | No | NO CHANGE (verified) | session passed through |
| reindex dual-read (`episodic.py:1017-1023`) | No | NO CHANGE (verified) | returns before the reach block while a migration runs |
| S79 / S81 answer-path standards | No | CONTRACT LOCK | `test_answer_path_standards.py` (newest-rows plan uses idx_chunks_session_ts_zone; rowid IN is a primary-key search) |
| `compare_embeddings` provenance rule | No | CONTRACT LOCK | candidates filtered to the query's backend (CT-R5) |
| Memory surface `/api/memory/*` | No (REQ-8 adds counters) | NO CHANGE now | reads its own SQL (`surface_queries.py`) |
| embedding fallback (`embedding.py:750-779`) | REQ-2 | CHANGE NEEDED (next) | mislabels hash vectors |
| FTS5 (`episodic._init_schema`) | REQ-3 | CHANGE NEEDED (next) | new virtual table + triggers or writer hook; S2 check first |
| integrity pass / Kyudo decay | REQ-5 | CHANGE NEEDED (next) | `cleanup_stale_chunks` has no caller |
| `evals/memory_bench.py`, `evals/standards.json` | Yes | CHANGE NEEDED (built) | the benchmark + its standard |

## Error Handling
- IF the warm-up read fails THEN recall keeps the old path for the life of the process,
  `fallback_error` counts it, one warning is logged.
- IF a query fails inside the index THEN that recall uses the old path (counted).
- IF the store has vectors of another dimension THEN those rows are skipped (never mixed).
- WHILE a reindex migration runs THEN dual-read answers (unchanged).

## Testing Strategy
- `tests/contract/test_memory_recall_reach_contract.py` (built): the oldest matching chunk of
  600 is reachable (CT-R1), the filter holds (CT-R2), new rows join once (CT-R3), recall
  returns a relevant chunk older than the newest 200 end to end (CT-R4; fails on the old
  path), the warming fallback is counted (CT-R5), never across embedding spaces (CT-R6).
- Contract locks kept green: `test_answer_path_standards.py` S79/S81.
- Behavioral: `evals/run_evals.py` research (r*) and coding (c*) groups before/after - no pass
  loss, no reply-time regression; the memory group (REQ-6 AC3) once built.
- Standing harness: `evals/memory_bench.py` on every memory change, compared with
  `evals/standards.json` "memory" (tolerances stated in the script).
- Physics-aware (REQ-7): replay recorded trajectories with injected Σ and assert the
  native rank prefers same-phase rows only when they also helped (never phase alone).
- HIDDEN FAILURES check: fingerprint bits must vary (no constant code), the mean must not be
  0, recall@10 must not equal reach (a sign the scan returns everything).
