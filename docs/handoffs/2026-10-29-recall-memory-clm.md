# Handoff — recall engine, memory write path, profile, CLM (2026-10-29)

Session owner: Midas. Read this before touching recall, memory writes, the profile or CLM.

> **AUDIT CORRECTION (2026-10-29, `pin_7cee599c0fc3` superseding `pin_c26f13059c2f`):**
> A full code + benchmark audit found critical errors in §§0, 2, 4, and 5 of this handoff.
> Read `specs/memory-recall-reach/` (`REQ-12`, `Design Key Decisions 7–11`, `Tasks Wave 10: T38–T45`)
> and follow **Section 5A (Corrected Next Actions)** below instead of the original §§0, 4, 5:
> 1. **`self._memory_interface` is NOT `None` on the WS path:** `iris_gateway.py:6169` calls
>    `get_agent_kernel` (`agent_kernel.py:22857-22886`), which calls `set_memory_interface`
>    and initializes `self._mcm_orch` (`:1937`). Because `self._mcm_orch` is NOT `None`,
>    `agent_kernel.py:9368` takes `if self._mcm_orch is not None:` (skipping the `elif`
>    `fragment_and_store` branch!) and calls `pacman_fragment.execute` (`pacman_fragment.py:217-253`),
>    which receives only `response_text` (never `User: {text}`) and drops every conversational
>    turn (`< 80` chars or lacking `_DER_SIGNALS`). And on the DER path (`agent_kernel.py:9888`),
>    no turn-pair fragment is stored at turn end at all.
> 2. **Writing `context_chunks` with `session_id` alone CANNOT fix `m03`:** `m01`–`m03`
>    (`evals/run_evals.py:188, 478-501`) seed in one WS `session_id` and ask in a new
>    conversation with a **new `session_id`**. `agent_kernel.py:4046` passes
>    `session_id=self.session_id` (a hard `WHERE session_id = ?` filter in `episodic.py:1138`),
>    and `_plan_task` (`:8450-8519`) never calls `retrieve_context_chunks` at all (`m01`/`m02`
>    pass via `turn_start_prior_memory` on `memory_chain`).
> 3. **Three bugs in commit `ff66a54a` (`ontology_recall.py` / `agent_kernel.py`):**
>    (a) `relevance_gate` (`ontology_recall.py:474`) checks `insight` and `result` only,
>    ignoring `r.get("content")`; (b) `turn_start_prior_memory` (`:562`) sorts `role == "user"`
>    **after** `relevance_gate` already truncated to `TURN_START_KEEP = 3` (`:489`);
>    (c) `_plan_task` (`agent_kernel.py:8486`) omits `_pm_r.get("content")`.
> 4. **Recall engine bugs (`episodic.py`):**
>    - Commit `26fb26a0` (`episodic.py:1309-1312`: `scored = _kw_rows + _rest`) places all 50
>      FTS `OR`-query hits ahead of all 1,000 semantic candidates before slicing `scored[:limit]`,
>      evicting high-cosine matches whenever 6+ chunks match any word in the query.
>    - Commit `cb41c577` (`episodic.py:1179-1256`) filters `since`/`until`/`tool_name` in Python
>      after the global top-1000 scan and logs up to 1,000 `WARNING` lines per query (`:1254`).
>    - Commit `1bd926ed` (`FP_CANDIDATES = 1000`) runs 3.22M pure-Python `_cosine` loop
>      iterations and fetches `content` for 1,050 rows per call.
> 5. **Benchmark & standard flaws (`evals/memory_bench.py`, `evals/standards.json`):**
>    - `memory_bench.py:370-410` never runs FTS or `_kw_rows + _rest` in `FILTERS`, so
>      `recall@10_live` (`0.9917`) did not measure the shipped code.
>    - `ceiling_by_m` (`:376`) reused `near` (`m=1000`) for `_m == 200`.
>    - `standards.json` (`0d5b61da`) was recorded with `--words 10` instead of default
>      `--words 40` and does not guard `recall@10_live`.

## 0. TL;DR for the next agent (original, superseded by Audit Correction above)

- The **recall engine is done and measured**: delivered 0.9917 / 0.9975 / 0.9917 against exact
  search, candidate ceiling 1.0 / 1.0 / 0.9950. Do not re-tune it.
- **IRIS cannot remember what the user said.** On the WS path only the assistant turn is
  persisted; `memory.db` holds only agent output; the chain holds *descriptions of the act*
  (`content=''`). This is the single blocker for m03, the profile and CLM.
- The write fix was attempted **three times and reverted** (inert). The cause is now known:
  `self._memory_interface` is `None` on that path (constructor default, `agent_kernel.py:1689`,
  set at `:1929`), and the fallback run's measurement was invalid because the backend had
  died silently mid-test.
- **Five measurements this session were invalid.** Read §7 before trusting any negative.

## 1. Environment (measured)

| item | value |
|---|---|
| backend | `http://127.0.0.1:8090` (NOT 8000), start via `npm run iris:start:backend` |
| readiness | `/health` 200 **includes TTS**; 157 s warm, up to 7 min cold (keyring plugins) |
| app store | `D:\IRIS\store\memory.db` — 73,227 chunks, 13,987 chain rows, 609 MB |
| conversations | `C:\dev\IRISVOICE\data\conversations.db` (`messages`: 687 user, 667 assistant) |
| config | `data/iris_config.json` |
| provider | `inceptionlabs` / `mercury-3` at `https://api.inceptionlabs.ai/v1` |
| credential | OS keyring via `backend/agent/inference/keyring.get_secret(provider)` (35 chars) |
| tool model | d1 on :8082 (`python evals/load_tool_model.py` verifies) |
| backend dies silently | observed once during memory init: log stops at keyring, no traceback |

## 2. Recall engine — done, measured, do not re-tune

| filter | ceiling (`recall@10_new`) | delivered (`live`) | NDCG | `shipped` | candidate p95 |
|---|---|---|---|---|---|
| research (1,782) | **1.0000** | 0.9917 | 0.9947 | **1.0000** | 2.13 ms |
| turn (2,916) | **1.0000** | 0.9975 | 0.9984 | **1.0000** | 1.71 ms |
| global (53,569) | 0.9950 | 0.9917 | 0.9946 | 0.9975 | 4.11 ms |

Settings: `FP_CANDIDATES = 1000`, `_RECENCY_BAND = 0.0005`, half-life 168 h, wall clock.
Standard recorded in `evals/standards.json` (`0d5b61da`).

Three findings that took the whole session to isolate — do not undo them:

1. **`recall@10_live` can never be 1.0 while recency affects membership** (it is scored against
   pure cosine). `recall@10_shipped` is the number to hold to 1.0.
2. **Band width is the dial.** 0.01 → 0.88/0.94/0.92; 0.002 → 0.97/0.99/0.98; 0.0005 →
   0.99/0.9975/0.99. Past 0.0005 the term is cosmetic.
3. **M is the ceiling lever.** 200 → 500 → 1000: 0.9742/0.9983/0.9650 → 0.9950/1.0/0.9875 →
   1.0/1.0/0.9950. Cost is the row fetch (8.67 ms p50 at 1000), not the scan.

## 3. What shipped (committed)

| commit | change |
|---|---|
| `44180103` | `recall@10_live` (delivered rank) + weight 0.05 / 168 h |
| `cb41c577` | **`since` / `until` / `tool_name` filters** (time window + source) |
| `26fb26a0` | keyword hit guaranteed a place in the delivered set (REQ-3 AC2) |
| `1bd926ed` | M 500 → 1000 |
| `9f2c325c` | band 0.002 → 0.0005 |
| `0d5b61da` | memory standard recorded |
| `2360b6c5` | purged 70,038 harness chunks (306.6 MB), re-baselined |
| `7ab62bf2` | keyring fallback for the provider key |
| `ff66a54a` | chain recall carries `content` + `role` (prerequisite, **does not fix m03**) |
| `3da074be` | spec finalized: REQ-10 two planes, REQ-11 three levels, status table |
| `837a44eb` | L1 `thread_context` (8,098 → now 3,372 threads, 21.7× scan) + L2 episode codec |
| `fb85828c` | file recall W1 (`file_ingest.py`) |
| `97c222a2` | phase blend λ measured and **rejected** |
| `fae46f24` | CLM spec (`specs/clm-memory/`) |

Also: `scripts/purge_harness_chunks.py`, `backend/memory/levels.py`,
`backend/memory/maintenance.py`, `backend/memory/file_ingest.py`,
`backend/tests/contract/test_recall_filter_arguments.py`,
`backend/tests/contract/test_file_formats_and_cold_tier.py`,
`backend/tests/contract/test_memory_maintenance_contract.py`.

## 4. The m03 problem — will the next actions fix it?

**m03 = "recall a preference taught in another conversation". Baseline 2/3 (m01, m02 pass).**

Diagnosis (evidence, not inference):

- The fact **is** in `memory_chain` — but as a **plan step**: `role='agent'`,
  `insight='Save the staging environment name osprey-west…'`, `result='success'`,
  **`content=''`**. The user's sentence is not stored anywhere.
- Every `context_fragment` chunk begins `[Step 1] …` — **agent output only**.
- `[WS] persisted assistant turn to conv=…` — the WS path persists one role.
- `turn_start_prior_memory` returns the two plan steps; `TURN_START_KEEP=2` is consumed, so the
  fact row never reaches the prompt. The gate scores lexical overlap, and a step that parrots
  the question beats the user's statement (`color` vs `colour`, value absent from the question).

**Will storing the user's statement fix m03? Expected yes, not proven.** It moves the fact from
the one lane that loses it into the lane that already delivers m01/m02 (chunk → embed →
fingerprint → cosine). "color"/"colour" is irrelevant to an embedding.

**Is it the right approach? Yes** — with three caveats that must ship in the same change:

1. **`_CHUNK_MIN_CHARS = 50`** (`episodic.py:152`) drops short statements. `"my name is Bob"`
   is 15 chars. Any fix that ignores this fails the most common case.
2. **Dedup at 0.92** can skip a re-taught near-identical sentence and silently keep the stale one.
3. **Engagement is not the bug.** Task-shaped prompts *do* recall (measured) — they recall a
   **stale** value. Do not force injection; the owner explicitly said passive or Oracle-triggered.

## 5. Next actions, in order, with verification

1. **Instrument before patching.** At the top of `AgentKernel.process_text_message`
   (`agent_kernel.py:9073`), log at WARNING: `_epi_u is None`, `type(self._memory_interface)`,
   and the `lane.submit()` return value. One turn proves reach. *This is the step I skipped
   three times.*
2. **Resolve the interface.** `self._memory_interface` is `None` on that path. The working
   fallback exists in `tool_bridge.py:2513`: `from backend.memory import get_memory_interface`.
   Prove it returns a store inside the live process before writing anything.
3. **Write the user's turn** via `fragment_and_store(text, session_id=…,
   chunk_type="context_fragment", zone="trusted")` on a lane — and **lower/ bypass the 50-char
   floor for user statements** (a name is a fact).
4. **Verify with a query, not a reply**: `SELECT COUNT(*) FROM context_chunks WHERE content
   LIKE '%<fresh-fact>%'` must be ≥ 1 **before** asking the question.
5. **Then run m03** with a fresh fact per run (`fern-green-<runid>`), and require all three:
   chunk exists · reply contains the value · reply does not say "no information".
6. **Conflict test**: teach A, then B in a new thread; ask. Newest must win. Today the
   *oldest/best-matching* wins (`kestrel-blue` beat `osprey-west`).
7. **Then the profile read** (`pin_a78b6885f704`) — gated by `task_classes`, `write_lock`
   as confidence weight, `confidence_floor`, `resonance` for node choice, `toolpath` excluded
   (`render_order is None`). Never dump `get_readable_profile()` into the prompt.
8. **Then CLM** (`specs/clm-memory/`): migrate `_emit_fan_traces` (the only writer of
   `der_fan_traces`, 13,886 rows) **before** deleting `dcp.py`.

## 5A. Corrected Next Actions — Execute Wave 10 of `specs/memory-recall-reach/` (`T38`–`T48`)

1. **`T38` — Fix keyword promotion (`episodic.py:1306-1312`):** Replace `scored = _kw_rows + _rest`
   with a single-slot guarantee: when `limit > 0`, `_kw_ids` is non-empty, and no row in
   `scored[:limit]` is in `_kw_ids`, replace `scored[limit - 1]` with the highest-scoring
   `_kw_ids` survivor; remove the dead `chunk_fts.fuse_by_rank` call on unsorted `argpartition`
   output (`:1202`). Prove with `CT-W10-1` in `test_memory_chunk_fts_contract.py`.
2. **`T39` — Fix bounded filters (`episodic.py:1205-1256`):** Include `where_sql` in the
   `WHERE rowid IN (...)` query, fetch up to `FP_CANDIDATES` rows matching `where_sql` when
   `_bounded` is True, and delete the per-row `logger.warning` at `:1254`. Prove with `CT-W10-2`
   in `test_recall_filter_arguments.py`.
3. **`T40` — Two-phase vectorized rescore (`episodic.py:1205-1305`):** Phase 1 fetches candidate
   metadata + `vec_i8, vec_scale, embedding` (without `content`) and computes cosine similarity
   in one numpy `mat @ q`; Phase 2 fetches `id, content` only for the `<= limit` winning rows.
   Prove with `CT-W10-3`.
4. **`T41` — Short user facts & supersede-on-dedup (`episodic.py:152, 959-1005`):** Use
   `_USER_CHUNK_MIN_CHARS = 10` for `chunk_type == "context_fragment"`, and when a new
   `context_fragment` has cosine `>= 0.92` with an older chunk, insert the new chunk and fold
   (`folded_into = new_id`) the older one. Prove with `CT-W10-5`.
5. **`T42` — Dual-path user turn persistence (`agent_kernel.py:9127, 9368, 9888`, `pacman_fragment.py:217-253`):**
   Append a `role='user'`, `node_type='user_turn'` row to `memory_chain` (`content` + `insight`)
   on turn entry, and submit `_turn = f"User: {text}\nAssistant: {response}"` to
   `fragment_and_store(..., chunk_type="context_fragment", keep_float=False)` on BOTH direct and
   DER turn completion (without `_is_fragment_candidate` dropping it).
6. **`T43` — Fix cross-conversation recall (`ontology_recall.py:474, 489, 562`, `agent_kernel.py:4046, 8482-8489`):**
   Include `r.get("content")` in `relevance_gate`, sort by `(role == "user", -created_at)`
   BEFORE slicing to `TURN_START_KEEP`, include `_pm_r.get("content")` in `_plan_task`, and add
   a bounded cross-session trusted `context_fragment` recall leg (`session_id=None`,
   `chunk_types=["context_fragment"]`, `zones=["trusted"]`, `limit=3`, `min_similarity=0.45`).
   Prove with `CT-W10-4`.
7. **`T44` — Purge chain harness rows & fix `memory_bench.py` / `standards.json`:** Purge
   `eval-*` rows from `memory_chain` in `scripts/purge_harness_chunks.py`; fix `ceiling_by_m`
   (`:376`), SQL parens (`:227, :273`), and FTS + single-slot ranking in `memory_bench.py`;
   guard `recall@10_live` in `standards.json` and re-record at default `--words 40` (`CT-W10-6`).
8. **`T45` — Upgrade active `recall_memory` tool (`tool_registry.py:994`, `tool_bridge.py:889, 2497`):**
   Accept `query` plus optional `since`, `until`, `tool_name` and return `chunks`
   (`retrieve_context_chunks(query, session_id=None, since=since, until=until, tool_name=tool_name, limit=5)`),
   `chain` (`turn_start_prior_memory`), and `episodes` (`retrieve_similar`) instead of only
   `episodes.task_summary`. Prove with `CT-W10-7`.
9. **`T46` & `T47` — Gated Mycelium profile read (`profile.py:452-750`, `mycelium/interface.py:725-741, 836-855`, `agent_kernel.py:3999, 8395, 8511`):**
   Contrary to `pin_a78b6885f704`'s claim that `get_profile_section` has 0 callers,
   `_context_parts` (`mycelium/interface.py:836-855`) ALREADY calls it by `spaces_for_class`
   and `render_order` (`toolpath` excluded), but (a) `ProfileRenderer` does not filter by
   `confidence_floor`, weight by `channel_weight(write_lock) * freshness(decay_rate)` (`_EXTERNAL`
   capped at `0.30` with `3×` decay), filter to resonant nodes, or lazily render dirty/missing
   sections on read, and (b) `agent_kernel.py:8396` (`_plan_task`) reads dead `tier1_directives=""`
   instead of `context_package.mycelium_path` and `get_tier3_failures()`. Fix in place and wire
   both `_plan_task` and `_assemble_direct_context`. Prove with `CT-W10-8` and `CT-W10-9`.
10. **`T48` — Live verification (`BT-W10-1`, `BT-W10-2`):** Run `python evals/run_evals.py --group memory`
    (3/3 PASS on `m01`, `m02`, `m03`) and the 3-thread conflict probe (newest wins). Then proceed
    to `specs/clm-memory/`.

## 6. Files

**Recall:** `backend/memory/episodic.py` (1061–1338 `retrieve_context_chunks`),
`backend/memory/recall_reach.py` (`FP_CANDIDATES`), `backend/memory/chunk_fts.py`,
`evals/memory_bench.py`, `evals/standards.json`.
**Memory writes:** `backend/agent/agent_kernel.py` (`process_text_message:9073`,
`_memory_interface:1689/1929`, `_turn_from_voice`), `backend/memory/episodic.py:877`
(`fragment_and_store`, `_CHUNK_MIN_CHARS:152`), `backend/utils/durability_queue.py`.
**Chain recall:** `backend/agent/ontology_recall.py` (`turn_start_prior_memory:536`,
`run_filtered_recall:353`, `filtered_chain_recall:142`).
**Provider:** `backend/inference_router.py:148`, `backend/agent/inference/keyring.py`,
`backend/iris_config.py:185-205` (`ProviderEntry.cred_ref`), `data/iris_config.json`.
**Profile:** `backend/memory/mycelium/spaces.py` (7 spaces, taxonomy),
`profile.py` (renderer), `interface.py:1450/1454` (`get_readable_profile`, 0 callers).
**Specs:** `specs/memory-recall-reach/` (requirements/design/tasks), `specs/clm-memory/`.
**Tests:** `backend/tests/contract/test_memory_chunk_fts_contract.py` (30),
`test_recall_filter_arguments.py` (5), `test_file_ingest_contract.py` (7),
`test_file_formats_and_cold_tier.py` (4), `test_memory_maintenance_contract.py` (3).
**Harness:** `evals/run_evals.py` (`_run_turn:186` — the proven client), `evals/tasks.json`.

## 7. Methodology — five invalid measurements (do not repeat)

1. **Client never answered the server's application heartbeat** → backend disconnected at 30 s
   → every arm "timed out" → I wrongly concluded "memory never fires on task prompts".
   Use `evals/run_evals._run_turn`, which answers it.
2. **Polled `conversations.db` by a conversation id that differed from the session id** → a
   completed turn looked like silence.
3. **Searched only `memory_chain.content`** → facts live in `insight`/`result` → wrongly
   concluded "not stored".
4. **Every arm wrote into the same live store** → cross-arm contamination (`kestrel-blue` beat
   `osprey-west`). Use a unique key per arm or an isolated store.
5. **Interpreted a negative while the backend process was dead** (silent exit during memory
   init) → "0 [USER] chunks" proved nothing.

**Rules:** before trusting a negative, prove (a) `/health` 200 and the process alive, (b) the
probe path executed (a log line from the hook), (c) the query matched the right column.
Target tests by file — never the whole `backend/tests/contract` directory (3,314 tests, 54 s
just to collect).

## 8. Known open defects (not fixed)

- **User text never stored** (§4) — the blocker.
- **`_CHUNK_MIN_CHARS = 50`** drops short facts.
- **Streamed DER turn can complete and persist without reaching a connected client**
  (`[DER] Session … has no connected clients` while the socket was alive). Looks like a freeze.
- **Profile is write-only**: `mycelium_profile` has no reader anywhere; 0 callers.
- **Backend died silently once** during memory init (no traceback, log stops at keyring).
- **`decay_pass` has no scheduled caller beyond `run_maintenance` every 5 tasks**; it pruned 0
  on the current store.
- **Phase plane**: λ rejected (−7.8 pts on global at 0.05). `coords_*` quarantined
  (165/947 to `coords_*_raw`); 376 of 8,098 sessions carry a real coordinate.

## 9. Do not re-litigate (pinned)

two planes (`pin_a80eb071542d`) · edge vs incidence (`pin_812706d2430e`) ·
profile read gating (`pin_a78b6885f704`) · phase λ rejected (`pin_c3e628e03c86`) ·
chain clock == wall clock, ρ 0.9935 (`pin_ce6b08735c29`) · recall milestone
(`pin_baa88b63257a`) · taught facts stored as step text (`pin_94b38c131442`) ·
methodology lessons (`pin_6c1cf4de4fae`).
