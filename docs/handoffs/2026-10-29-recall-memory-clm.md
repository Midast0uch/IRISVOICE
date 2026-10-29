# Handoff — recall engine, memory write path, profile, CLM (2026-10-29)

Session owner: Midas. Read this before touching recall, memory writes, the profile or CLM.

## 0. TL;DR for the next agent

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
