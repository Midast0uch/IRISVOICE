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
- AC2: WHEN a recall runs THEN THE SYSTEM SHALL score exactly the M rows nearest the
  query by fingerprint within the filter (session, chunk types, zones, same embedding backend)
  plus the newest 50 rows of the filter, with **comparative recency**: order by a cosine
  BAND first, then by freshness inside the band (`_RECENCY_BAND = 0.002`, half-life 168 h).
  A near-tie in meaning is broken by age; a clear semantic winner is never displaced.
  **Measured 2026-10-28 (120 queries, M = 500):**

  | ranker | live (vs exact cosine) | shipped (vs the ranker applied exactly) |
  |---|---|---|
  | absolute blend w=0.05 | 0.8767 / 0.9475 / 0.8817 | 0.9975 / 1.0000 / 0.9900 |
  | band 0.01 | 0.8833 / 0.9442 / 0.9167 | 0.9983 / 0.9975 / 0.9825 |
  | band 0.002, M=500 | 0.9658 / 0.9867 / 0.9692 | 0.9950 / 0.9967 / 0.9892 |
  | band 0.002, M=1000 | 0.9700 / 0.9858 / 0.9775 | 1.0000 / 0.9975 / 0.9983 |
  | band 0.001, M=1000 | 0.9875 / 0.9933 / 0.9850 | 1.0000 / 1.0000 / 0.9983 |
  | **band 0.0005, M=1000 (shipped)** | **0.9917 / 0.9975 / 0.9908** | **1.0000 / 1.0000 / 0.9992** |
  | band -> 0 | = ceiling (below) | - (no recency) |

  Ceiling at M=1000: **1.0000 / 1.0000 / 0.9975**. NDCG@10 at the shipped setting:
  0.9947 / 0.9984 / 0.9941. The band width is the dial between agreement with exact
  search and how much freshness decides; 0.0005 is the knee, past which the term is
  cosmetic. A keyword hit is guaranteed a place in the delivered set regardless of
  its vector (REQ-3 AC2). M = 500 (was 200: 0.9742 / 0.9983 / 0.9650).
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
- AC1b: THE SYSTEM SHALL ALSO measure **recall@10_shipped** - the same candidate path scored
  against the SHIPPED ranker (cosine × (1 − w) + recency × w) applied to every row of the
  filter. Cosine truth caps the delivered number by construction while the blend exists, so
  it cannot express "1.0". Measured 2026-10-28 at M=500: shipped truth reads **research
  0.9975 / turn 1.0000 / global 0.9900**, against cosine truth 0.8767 / 0.9475 / 0.8817 for
  the same delivered rank. Both columns are reported; neither replaces the other.
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

## Open Questions — RESOLVED FROM THE CODE (2026-10-28)

Both were answerable from the code and the bench, not from preference. Left here with the
answer and the evidence so the next agent does not re-open them.

1. **int8 beside float, or replace?** → **Replace, per chunk type, and it is already done.**
   `vector_quant.py:9-19` states the float is kept "only while the bench shows int8 loses more
   than 0.02 recall@10 for that [type]". `evals/memory_bench.py` reports delta 0.0 on every
   type (document_data 0.8433 = 0.8433, context_fragment 0.9317 = 0.9317, der_output 0.855 =
   0.855, der_failure, research_summary), and the live store has `embedding` NULL on all
   143,239 rows with `vec_i8` on all of them. REQ-4 AC1 stands as written. New writes must not
   pay for a float that stores nothing (see REQ-9 AC6).
2. **Store budget numbers per zone?** → **Already in the code: `chunk_decay.ZONE_BUDGET`** =
   trusted (160,000 rows / 320 MB), tool (40,000 / 80 MB), reference (25,000 / 55 MB) —
   measured 2026-10-27 × 1.5 headroom, with `decay_pass` pruning oldest-unused-first and
   `_protected_ids` keeping pins and live claims. The spec must cite these numbers, not invent
   them. **Finding:** the pass exists but has no production caller, and the bench READS the
   budget (`memory_bench.py:432,523`) without asserting against it. REQ-5 AC2's guard is the
   missing half — tracked, not silently assumed done.

## Addendum: File Recall (REQ-9, owner request 2026-10-28)

*(Numbered REQ-9: REQ-8 is Observability above. This addendum was first written as REQ-8 and
collided with it.)*

Owner requirement: "make sure we can recall all file types and the content in the files
themselves, and make sure they're compressed in the memory.db like they should."

### Measured state (2026-10-28, live store D:\IRIS\store\memory.db)
- **No file-ingestion path exists.** No table, tool or API takes an arbitrary user file,
  extracts its text and stores it. `document_data` (83,831 chunks, 58% of the store, 85 MB of
  text) holds the AGENT'S OWN rendered documents (reports, research docs, cards; columns
  `fmt/kind/title/capture_path/har_path`), not user files. `documents` and `document_chunks`
  do not exist.
- **The identity table already exists**: `file_nodes` (5,246 rows) keys files by
  `file_path UNIQUE` with `language`, `last_edited` (REAL epoch), `edit_count`, `confidence`,
  `decay_rate`, `project_id`, `topology_primitive`. It is the Mycelium coordinate node for a
  file. It has no content hash and no size column.
- **The write path already exists**: `EpisodicStore.fragment_and_store(content, session_id,
  chunk_type, zone, tool_name)` (`episodic.py:877`) splits into overlapping ≤2,048-char
  windows, dedups at cosine ≥ 0.92, writes int8 + fingerprint, and goes through `app_write`.
- **FTS needs no hook**: `context_chunks_fts` is external-content FTS5 with three triggers
  (`context_chunks_fts_ai/ad/au`), so any insert through the writer is indexed in the same
  transaction. Verified against the live schema.
- **`chunk_type` has no CHECK constraint** — a new value is legal without a migration.
- **Vector compression is already done**: 143,239/143,239 rows carry `vec_i8` + `vec_fp` +
  `vec_scale` (1,160 B/row vs 4,096 B float32); `embedding` is NULL on every row.
- **Text is stored raw** (134 MB, mean 937 B/chunk, cap 2,048 chars) — FTS5 indexes it.
- Recall is type-blind: any text that becomes a `context_chunks` row is reachable through the
  same fingerprint + FTS path (reach 0.9742/0.9983/0.9625, words 0.625).

### Requirements (EARS)
- **REQ-9 AC1** — WHEN a user file is ingested, THE SYSTEM SHALL identify it in `file_nodes`
  by absolute path (upsert on `file_path`), recording the file's content hash, size and
  mtime, and SHALL produce its text as `context_chunks` rows with `chunk_type = "file"`,
  `tool_name = <absolute path>` and the zone the file is trusted with.
- **REQ-9 AC2** — THE SYSTEM SHALL write file text through the EXISTING chunk writer
  (`fragment_and_store`), so chunking, dedup, int8 + fingerprint, the FTS trigger and the
  fingerprint delta all apply with no second write path.
- **REQ-9 AC3** — WHEN a stored file's hash changes THEN THE SYSTEM SHALL ingest the new text
  and FOLD the superseded chunks (`folded_into` = the new head), never delete them; WHEN the
  file is gone THEN THE SYSTEM SHALL fold its chunks and mark the node stale.
- **REQ-9 AC4** — WHEN recall runs, THE SYSTEM SHALL return file chunks through the same
  candidate union (fingerprint M=200 + newest 50 + FTS 50) and the same blend, with no special
  casing; a file chunk competes with conversation memory on one measured rank.
- **REQ-9 AC5** — IF a file cannot be decoded or extracted THEN THE SYSTEM SHALL record the
  failure (counted by reason, logged with the path, never a silent empty ingest) and SHALL
  store the reference-only record so the user still sees the file exists.
- **REQ-9 AC6** — WHEN a file chunk is written THEN THE SYSTEM SHALL NOT store the float32
  vector: int8 + fingerprint only (REQ-4 AC1 is proven at delta 0.0 for every chunk type).
  At 5 MB/file this is 1,160 B/chunk instead of 5,256 B/chunk.
- **REQ-9 AC7** — THE SYSTEM SHALL keep file text inside the owner's budget (~100 MB total,
  5 MB per file, owner 2026-10-28): a file over the per-file cap is truncated at extraction
  and the truncation is recorded on the node, never silent.
- **REQ-9 AC8** — THE SYSTEM SHALL report in the bench a `files` section: files known, chunks
  produced, extraction failures by reason, bytes of stored file text, and `recall@10_live`
  over a file-content query set.

### Decisions Locked (owner, 2026-10-28)
- **File types: ALL of it** — UTF-8 text, PDF/DOCX/XLSX, images via OCR, audio/video via
  transcription. This is the owner's yes to the extraction dependencies; each package is named
  before install (SAFETY RAILS).
- **Storage: BOTH forms, distinct** — a file record (`file_nodes`: path, type, size, mtime,
  hash) AND extracted-text chunks in `context_chunks`. The distinction is visible: a hit with
  no chunks is a reference-only hit and says so.
- **Text stays raw** — FTS5 needs it; bounded by the zone budget.

### Waves
- **W1 — UTF-8 text** (stdlib only): code, md, json, yaml, csv, log, txt. Node upsert + hash
  + chunks through `fragment_and_store` + fold on change + bench `files` section.
- **W2 — PDF/DOCX/XLSX**: named packages (pypdf, python-docx, openpyxl — confirm at install).
- **W3 — Images (OCR)**: the app's vision adapter, or a named OCR package.
- **W4 — Audio/video**: transcription. `backend/audio/parakeet_worker.py` is named by a test
  but absent from the tree (pre-existing failure) — resolve or route around it.

### Risks and findings raised by this addendum
- **Turn-level reach needs one call-site decision.** File chunks are not a conversation, so a
  filter keyed on `session_id = <the turn's session>` cannot see them; the `global` filter can
  but has no production caller. W1 must either (a) address files by zone with a session-less
  recall leg at `agent_kernel.py:4037-4049`, or (b) pin file chunks to the ingesting session.
  (a) is the memory-native answer (a file is an address, not a conversation). Not silently
  left out: this is the difference between a flag that is OFF and a feature that is done.
- **`decay_pass` must not prune a file the user still has on disk** unless REQ-9 AC7's budget
  forces it; `_protected_ids` covers pins and claims, not file nodes.

## REQ-10: Two planes — semantic and phase (owner decision 2026-10-28)

**User Story:** As IRIS I want meaning and position kept as two different measurements so
that "similar words" and "same phase of work" never contaminate each other.

**Verified:** `context_chunks` has no coordinate column (printed 2026-10-28); the phase lives
in `memory_chain.coords_*` (4-number rows: 3,637 `coords_from` / 3,075 `coords_to` of 13,739)
and `caducean_trajectories` (14,298 rows, x/y/ξ/u).

**Acceptance Criteria:**
- AC1: THE CHUNK VECTOR SHALL NOT carry phase. No concatenation; the fingerprint stays 1 bit
  per dimension over 1024 dimensions (128 bytes).
- AC2: THE SYSTEM SHALL reach a chunk's position by INCIDENCE
  (`chunk.session_id = memory_chain.thread_id`), never by a coordinate stored on the chunk.
- AC3: THE SYSTEM SHALL blend at the RANK: `score = cosine·(1−λ) + affinity·λ`,
  `affinity = 1/(1+d_Σ)`, `d_Σ = w_ξ·|Δξ| + w_u·|Δu|`; x and y are REGIME labels, matched not
  subtracted (measured: 17 and 43 distinct values, zeros on 36.5 % / 45.1 % of rows).
- AC4: λ SHALL be per filter and gated on measured coverage (2026-10-28: turn 100.0 %,
  global 38.6 %, research **0.0 %**). A filter with no positioned row uses λ = 0.
- AC5: A row with no position SHALL be treated as ABSENT, not zero; the weights renormalise.
- AC6: THE SCHEDULER SHALL NOT read live u/ξ (CT-3/CT-4); only the cognitive layer computes λ.
- AC7: `coords_*` SHALL hold only coordinates before λ is tuned. Measured 2026-10-28: 10,102
  `coords_from` and 10,664 `coords_to` rows hold other values (`'json'` 675×, `'markdown'`).

## REQ-11: Three levels — thread, episode, chunk (prepared for the CLM)

**User Story:** As IRIS I want each conversation's context to be one addressable vector so I
can navigate history by conversation, then by task, then by payload.

**Verified:** L2 exists (`episodes` 362 rows with `embedding`, `full_content`, `node_id`;
`mycelium_episode_index` 4,526 rows linking `node_ids`/`space_ids`/`landmark_id`/
`coordinate_hash`). L1 is absent: no table named `*thread*` or `*strand*`. Keys do not meet:
5,262 chain threads, 8,098 chunk sessions, **1,584 in both**.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL store L1 as a DERIVED row (`thread_context`), rebuildable from chunks;
  deleting it SHALL lose no truth.
- AC2: THE SYSTEM SHALL give L2 the L3 codec (`episodes.vec_i8/vec_fp/vec_scale`), recomputed
  from the stored `embedding`.
- AC3: ALL THREE LEVELS SHALL use one codec (int8 + 128-byte fingerprint) and one scan.
- AC4: THE L1 SCAN SHALL cost at most one tenth of the L3 scan at the same store size
  (measured basis: 5,262 × 128 B = 673 KB against 108,314 × 128 B = 13.6 MB ≈ 20×).
- AC5: EVERY chunk SHALL reach its thread. The measured match rate is reported; the 1,584 /
  5,262 gap is the first work item, not a footnote.
- AC6: A strand SHALL be a `thread_id` (`strand-<hex>`), not a new table, until strands are
  used widely (6 strand sessions / 47 chunks today).

## Handoff — the CLM needs its own spec, next

Recorded 2026-10-28 (owner): "after we finish and finalize the recall spec the CLM will need a
spec and be next."

- This spec PREPARES the memory for it (REQ-11) and stops there. The editable live view,
  placeholders, compaction policy and skill steering are **out of scope here**
  (`CLM_MYCELIUM_DESIGN_BRIEF.md` §11 Phase 1+).
- What the CLM spec inherits as ground: three addressable levels, one codec, incidence to the
  phase plane, an immutable record layer, and `episodes` already holding an L2 vector.
- What it must not re-litigate: two planes (REQ-10), the codec (REQ-4), the decay law (REQ-5).

## Spec Status (2026-10-28)

| REQ | state |
|---|---|
| 1 reach | built; `recall@10_live` now measures the DELIVERED rank |
| 2 honest vectors | built (fallbacks labelled + counted) |
| 3 exact words | built (FTS5 + literal-first fetch, stopword policy) |
| 4 compression | built (int8 replace proven; fold; distil partial) |
| 5 budget + decay | built and CALLED (maintenance pass, every 5 tasks) |
| 6 benchmark | built (`memory_bench.py`, standards) |
| 7 memory rank | shadow, switch OFF (measured loss: 0.72/0.75/0.56 vs 0.97/1.00/0.96) |
| 8 observability | built |
| 9 file recall | W1 built + live gate PASS; W2-W4 not started (need package names) |
| 10 two planes | decided, measured, **not built** (repair first) |
| 11 three levels | prepared in spec, **not built** (keys first) |
