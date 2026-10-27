# Requirements: Memory Recall Reach and Performance

## Decisions Locked
- **Not a copy of LEANN or memvid** (owner, 2026-10-27). They are reference points, not
  designs to port. IRIS memory is not a flat pile of vectors: it is a position-keyed,
  evidence-weighted, self-cleaning organism (Mycelium coordinates, landmarks = claims proven
  by outside evidence, the Immortus chain of transitions + references, Kyudo trust and decay,
  the Caducean position Σ = (x, y, ξ, u)). Every solution here uses that structure; a generic
  vector-DB technique is allowed only as a component under it, and only when the benchmark
  (REQ-6) shows it pays.
- **The goal is to outperform, measured** (owner): on IRIS's own corpus and real queries,
  beat both reference points on the axes each one claims - storage per item (LEANN), search
  latency (memvid) - while recall quality rises. Their numbers are their claims on their
  corpora; ours are measured by `evals/memory_bench.py` and stated side by side, never mixed.
- **Item 1 (reach) is built first** in this spec's first session; items 2-5 are specified
  for the next agent (owner, 2026-10-27).
- **The benchmark is part of done** (owner): every memory change runs `evals/memory_bench.py`
  AND the end-to-end evals it touches (`evals/run_evals.py`) before and after; a standard in
  `evals/standards.json` guards each measured win.
- **LEANN's recomputation is rejected for now**: it trades storage for embedding calls at
  query time; IRIS embeds on CPU (LFM2.5-350M sidecar) on the answer path, and its vectors are
  ~600 MB, not 200 GB. Revisit only if the store passes ~10 M chunks.
- **No new dependency without the owner** (CLAUDE.md): numpy (installed) and SQLite's own
  FTS5 only; sqlite-vec / faiss / hnswlib need an explicit owner yes.
- Sector births stay owner-gated (only after a Kyudo reorganization; MEMORY-INTERFACE §13).

## Introduction
IRIS stores 146,653 context chunks with 1024-d vectors (~600 MB, 52% of the 1.16 GB store),
but recall scores only the newest 200 rows of its filter, 9.4% of the vectors are silent
hash fallbacks labelled as model vectors, there is no keyword index, nothing is compressed,
and chunk decay has no caller. This spec makes every memory reachable, honest, compact and
budgeted, and ranks recall by what the memory itself knows (position, evidence, use, trust).

### Success criteria
- Reach: every chunk the filter allows can be returned (was 200 rows per filter).
- Recall@10 against exact search over the whole filter: the reach path ≥ 0.90 on every live
  filter, and above the old path on every filter (measured: REQ-6).
- Candidate stage p95 ≤ 20 ms at today's size and ≤ 150 ms at 10× rows (no new dependency).
  Measured 2026-10-27 (Wave 1): research 9.5 ms, turn 20.6 ms, global 41 ms (no production
  caller); 10× scan p95 236 ms - NOT met: REQ-1 AC6 (scan by region) is the planned answer.
- 0 vectors labelled with a backend they did not come from; every fallback counted.
- Store bytes per chunk fall (REQ-4) with recall@10 held within 0.02 of the float result.
- End-to-end evals (coding, research) show no pass loss and no reply-time regression.

## Requirements

### REQ-1: Recall reaches every stored chunk
**User Story:** As IRIS I want recall to consider every chunk my filter allows so that what I
learned weeks ago is found when it is the best match, not only what I learned today.

**Verified:** `backend/memory/episodic.py:1046-1052` (before: `ORDER BY timestamp DESC LIMIT
200`); callers `research_memory.py:482` (research_summary/reference, 1,777 rows),
`agent_kernel.py:4046` and `:4065` (session + zones), `recall_decoder.py:436` (session).
Built 2026-10-27: `backend/memory/recall_reach.py`, `episodic.py` reach path.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep, per store, a fingerprint of every chunk vector (1 bit per
  dimension, the sign of each component; 128 bytes at 1024-d) in RAM, bounded to FP_MAX_ROWS.
- AC2: WHEN a recall runs THEN THE SYSTEM SHALL score exactly the M = 200 rows nearest the
  query by fingerprint within the filter (session, chunk types, zones, same embedding backend)
  plus the newest 50 rows of the filter, with the existing score (cosine 0.8 + recency 0.2).
- AC3: WHEN chunks are written after the index was built THEN THE SYSTEM SHALL add them at
  the next recall, each row once.
- AC4: WHILE the index warms or IF it fails THEN THE SYSTEM SHALL use the newest-200 path and
  count each fallback (`recall_reach.COUNTERS`), never fail the recall.
- AC5: THE SYSTEM SHALL never compare vectors of different embedding backends.
- AC6: WHEN the store passes the size where the full scan exceeds 150 ms p95 THEN THE SYSTEM
  SHALL scan by REGION first - Kyudo zone, then sector root, then strand - so a query reads
  only the fingerprints of the regions its filter and position allow (memory-native
  partitioning, not a generic ANN graph).

**Measured (2026-10-27, `evals/memory_bench.py`, 120 real chat queries, truth = exact cosine
over every row of the filter):**

| Filter (production caller) | Rows | recall@10 old | recall@10 reach | candidate p50 / p95 |
|---|---|---|---|---|
| research (`research_memory.py:482`) | 1,777 | 0.14 | **0.975** | 2.1 / 9.5 ms |
| turn, biggest session (`agent_kernel.py:4046`) | 13,030 | 0.054 | **0.901** | 5.4 / 20.6 ms |
| whole store (no caller) | 146,767 | 0.029 | **0.96** | 13.2 / 41 ms |
| 10× rows, scan only | 1,467,830 | - | - | 171 / 236 ms |

Warm-up: 18-39 s on a background thread (recall uses the old path meanwhile). Signs about a
mean of raw vectors (norms up to 72.5) reached only 0.35 globally: the centre is 0.

**Edge Cases:** empty store (no candidates, old path result); a filter with fewer than 200
rows (all of them scored); a deleted row (its rowid finds nothing - skipped); a rowid reused
by a new row (the new row's own vector is scored exactly); vectors of another dimension
(skipped); more than FP_MAX_ROWS rows (newest kept, logged).

### REQ-2: Every stored vector is what its label says
**User Story:** As IRIS I want a vector labelled "lfm25-emb-350m" to come from that model so
that recall never matches my question against noise.

**Verified:** `backend/memory/embedding.py:750-760` (a failed GGUF call returns
`_hash_embed`), `:763-779` (the result is labelled with the requested backend, and a hash
chunk is max-pooled with model chunks). Measured 2026-10-27: 374 of 3,966 sampled LFM-labelled
chunk vectors (9.4%) have more than half their components exactly 0; document_data 14%.

**Acceptance Criteria:**
- AC1: IF the model call fails for any chunk of a text THEN THE SYSTEM SHALL label the result
  with the fallback backend (or return no vector), never with the requested model.
- AC2: THE SYSTEM SHALL count every fallback with its cause and log it with the caller.
- AC3: THE SYSTEM SHALL repair existing mislabelled rows on a lane (re-embed, or relabel and
  exclude from recall until re-embedded), bounded per pass, resumable.
- AC4: WHEN the repair runs THEN THE SYSTEM SHALL write through `db.app_write` only.

**Edge Cases:** the sidecar down for minutes (fallbacks counted, recall excludes them); a
text that only the fallback can encode; a row repaired twice (idempotent).

### REQ-3: Exact words are recalled as well as meaning
**User Story:** As IRIS I want a file path, an error string or a name I saw before to be
found by its exact words so that recall does not depend on the embedding knowing them.

**Verified:** NEW. `sqlite_master` holds no FTS / virtual table (audit 2026-10-27); keyword
lookups are B-tree + Python token overlap (`episodic.py:322-381`, `ontology_recall.py:376-420`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep an FTS5 index over chunk text in the app store (SQLite's own,
  no new dependency), filled on write through the one writer and backfilled on a lane.
- AC2: WHEN a recall runs THEN THE SYSTEM SHALL fuse the keyword ranking and the meaning
  ranking by rank (not raw score), so either can bring a row into the scored set.
- AC3: THE SYSTEM SHALL weigh the fused rank by the memory's own signals (REQ-7) in shadow
  until the benchmark shows the weighting pays.
- AC4: IF the FTS index is missing or broken THEN THE SYSTEM SHALL recall by meaning alone
  and count it.

**Edge Cases:** queries of stop words only; very long queries (bounded terms); a chunk
deleted (its FTS row removed in the same write); the S2 answer-path standard (a new index
can steal the planner - run `test_answer_path_standards` first).

### REQ-4: Memory compresses where outcomes agree
**User Story:** As the owner I want the store to stay small as it grows so that recall stays
fast and the SSD holds years of memory.

**Verified:** NEW. Vectors are raw float32 (4,096 B each, 52% of the store); no
zlib/zstd/int8/binary anywhere in memory code; `memory_chain.distilled` has no writer (0 of
58,117); `mycelium_traversals.delta_compressed` 0 of 5,502 (audit 2026-10-27).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL store, per chunk, the fingerprint (128 B) and an int8 vector (1,024 B)
  as the recall forms; the float vector SHALL be kept only while the benchmark shows int8
  loses more than 0.02 recall@10 for that chunk type.
- AC2: THE SYSTEM SHALL fold near-duplicate chunks of one strand (cosine ≥ 0.92 and the same
  outcome) into one row that references the folded ones (the compression arm of the one
  operator: compress where outcomes agree), on a lane.
- AC3: WHEN a cluster of agreeing chunks backs a proven claim (landmark) THEN THE SYSTEM SHALL
  distil it to the claim plus chain references (`memory_chain.distilled`), keeping payloads
  only where Kyudo trust allows (the chain holds references, never payloads).
- AC4: THE SYSTEM SHALL measure bytes per chunk and recall@10 before and after each
  compression step (REQ-6) and keep a step only if recall holds within 0.02.

**Edge Cases:** a fold that would cross Kyudo zones (never); a user-pinned chunk (never
folded); undo of a correction on a folded row (the fold keeps the references to restore).

### REQ-5: Growth has a budget and decays by the Kyudo law
**User Story:** As the owner I want chunks that no recall ever uses to fade at the speed the
memory grows so that the store does not fill with noise.

**Verified:** `episodic.py:1164-1213` `cleanup_stale_chunks` has no production caller;
`retrieval_count` is written on every recall (`episodic.py:1119-1156`); document_data is
86,818 of 146,653 chunks (59%); `RecallUsed` events now name used claims (S125).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL decay chunks by the one Kyudo law (trust channel sets the rate; use,
  outside evidence and RECALL_USED/HELPED slow it; MISLED speeds it), on the integrity lane.
- AC2: THE SYSTEM SHALL keep a store budget (bytes and rows per zone) with a guard that fails
  when the budget is exceeded, and record each prune as MEMORY_PRUNED with its reason.
- AC3: IF a chunk backs a live claim or a pin THEN THE SYSTEM SHALL not prune it.

**Edge Cases:** a burst of document ingest (budget per zone, oldest unused first); a chunk
recalled once long ago (slow decay, not immortality); the reorganization pass (decay faster
on what a suspect window touched).

### REQ-6: The memory is benchmarked like the agent
**User Story:** As the owner I want every memory change measured on my own memory so that
"faster and better than LEANN / memvid" is a number, not a claim.

**Verified:** Built 2026-10-27: `evals/memory_bench.py` (recall@10 vs exact search, reach,
candidate p50/p95, 10× scan, bytes per chunk, store size; standards in
`evals/standards.json` "memory").

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL measure, on the live store read-only with real chat queries: recall@10
  against exact cosine over the whole filter, reach, candidate latency p50/p95, a 10× scan,
  bytes per chunk, store size - per live recall filter.
- AC2: THE SYSTEM SHALL compare each run with the recorded standard and report a regression
  (recall@10 below standard − 0.02, candidate p95 above 2 × standard + 5 ms).
- AC3: THE SYSTEM SHALL add an end-to-end memory eval group to `evals/run_evals.py`: tasks
  whose answer needs something taught in an EARLIER thread (multi-session, LoCoMo-style but on
  IRIS's real loop), graded by fact, with reply_s.
- AC4: THE SYSTEM SHALL report the reference systems' published numbers next to ours, labelled
  as their claims on their corpora.

**Edge Cases:** the embedding sidecar cold (the bench waits for it, reports load time apart);
a store with no research rows (that filter reported empty, not failed); machine busy (bench
notes it; never compared against a quiet standard).

### REQ-7: Recall ranks by what the memory knows, not by cosine alone
**User Story:** As IRIS I want recall to prefer what was proven, used and helpful, written in
a similar phase of work, so that my memory behaves like memory, not like a search engine.

**Verified:** NEW. Signals that exist and are not used by chunk recall: Kyudo channel/zone
(`kyudo.channel_for_zone`, used only for crystallization at `episodic.py:1144-1152`), the Σ
address on chain rows (`memory_chain.coords_from/coords_to`, 6 decimals since S122),
landmark evidence and fading (`surface_queries._claim_alive`), RECALL_USED / HELPED / MISLED
events (`memory_events`, S125), `retrieval_count`. `_shadow_trust_rank` exists in shadow
(`episodic.py` after scoring).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute, per scored row, memory-native features: Kyudo trust, Σ
  distance between the row's write position and the current position, the evidence of the
  claims it backs, helped/misled history, use count with decay.
- AC2: THE SYSTEM SHALL rank by these features in SHADOW beside the live rank, recording both
  (the Oracle bar applies: rows ≥ 100, precision ≥ 0.90, ECE ≤ 0.05) before any switch.
- AC3: WHEN the shadow rank beats the live rank on REQ-6's benchmark and on helped/misled
  outcomes THEN THE SYSTEM SHALL switch, with an off switch and a landmark (CLAUDE.md step 8).
- AC4: THE SCHEDULER SHALL NOT read live u/ξ for recall (CT-3/CT-4); the cognitive layer may.

**Edge Cases:** a row with no Σ (feature absent, not zero); a new store with no outcomes
(cosine rank only); a feature with zero variance (a FAILURE per HIDDEN FAILURES - logged).

### REQ-8: Observability
**User Story:** As the tuner I want each recall's path, sizes and timings visible so that I
can tune M, the budgets and the weights from measurement.

**Verified:** NEW (counters exist: `recall_reach.COUNTERS`).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log per recall (debug, scoped by conversation): path (reach / old),
  rows allowed, candidates scored, returned, candidate ms.
- AC2: THE SYSTEM SHALL expose the counters (queries, fallbacks, rows built, build seconds) on
  the memory health read (`/api/memory/overview`).
**Edge Cases:** high volume (debug level, no per-row lines); a missing conversation id ("-").

## Non-Requirements (Out of Scope)
- Porting LEANN, memvid, or any external vector database.
- LEANN-style recomputation of embeddings at query time (Decisions Locked).
- A new embedding model (a model switch is a reindex migration with its own spec).
- Sector births (owner-gated).
- GPU search.

## Open Questions
- Should int8 replace float vectors in the store (REQ-4 AC1) or sit beside them until the
  bench proves it on every chunk type? (default: beside, then replace per type.)
- Store budget numbers per zone (REQ-5 AC2): set from the first bench + growth measurement.
