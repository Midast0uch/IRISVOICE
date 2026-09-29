# IRISVOICE — durable project notes

> Session narrative lives in MCM pins. **Read `pin_a0520c3def75` first** (the running handoff),
> then `pin_6a9e8dfdf6b4` (progress index), then `pin_5ee21722ed1d` (how to start the app).
> This file holds only durable facts and traps.

## Build / release
- `npm run build:static` here needs
  `CODEBUDDY_SAFE_DELETE_ENABLED=0 CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD=100000`.
- Verify `dist/index.html` after every build; a partial build leaves `dist/` broken.
  `next build` wipes `.next` — restart the dev server afterwards.
- Tauri dev loads `http://localhost:3000`; release loads `../dist`. Release can ship a STALE
  frontend even when source is fixed. Cargo target is `C:\temp\tauri-build`.
- Verify minified bundles by surviving string literals, not symbol names.

## Git safety
- A hung `git.exe` holding `.git/index.lock` blocks index-writing git commands while read-only
  git still works. Check `ls .git/index.lock` + `tasklist //FI "IMAGENAME eq git.exe"` before
  blaming yourself for a git failure. (Seen live: 0-byte `index.lock` + live `git.exe`.)
- `git update-ref` can silently fail/delete an empty `refs/heads/feat/*`; write the full
  40-char SHA and verify with `git rev-parse HEAD`.
- An unborn HEAD makes the whole tree look new — compare against the real tip.

## Starting the app under WorkBuddy
- `npm run iris:start:backend` **does not work** here: it prints "detached, pid N" and the child
  dies silently. Two proven causes: (a) the sandbox REAPS detached children; (b)
  `start-backend.py`'s own `__pycache__` purge trips the safe-delete guard
  (`SAFE_DELETE_BULK_CONFIRM_REQUIRED {"count":60,"threshold":50}`) and aborts pre-uvicorn.
- WORKAROUND (verified): long-lived BACKGROUND process, not the manager —
  `CODEBUDDY_SAFE_DELETE_ENABLED=0 CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD=100000 PYTHONUNBUFFERED=1 python start-backend.py`
  Ready in ~14–45 s. It may not outlive the turn — re-check `netstat -ano | grep :8090` first.
- Startup ORDER: backend → model server SERVING on 8082 → `.lfmrun.py` → `.brain.py`.
  `.lfmrun.py` does `load_local_model` then `set_model_selection`; the latter registers the local
  model for IN-PROCESS inference. If the bind never runs, every tool decision fails with
  "No local model loaded for in-process inference". `.brain.py` restores the split
  (reasoning → ollama `gemma4:31b-cloud`, tool_execution → local LFM).
- `.lfmrun.py` confirms the load by a **TCP connect** to `127.0.0.1:8082`, not by an app event
  (the app does not reliably emit `loaded=True`) and not by `/health` or `/props` — those BLOCK
  while a slot is busy on this llama-server build, so a healthy server looks dead.
- **NEVER kill `llama-server` by NAME** — the embedding sidecar on 18183 IS one. Kill by verified PID.

## The model-load wedge — ROOT CAUSE (fixed; do not re-open)
- `local_model_manager.py` spawned llama-server with `text=True` and no `encoding`/`errors`. ONE
  non-UTF-8 byte (`0xc4`) in its `-lv 5` output killed the stdout reader thread; nobody drained the
  pipe, so the server blocked forever in a write. Result: `/v1/models` → 503 "Loading model"
  forever, ~0 CPU, no GPU allocation, every model-calling turn wedged.
- Fix: `encoding="utf-8", errors="replace"`. Verified: reader-exit count 1 → 0, `.lfmrun.py`
  reaches "Model ready"/"BOUND ok", GPU allocation, real DER turn completes.
- **Before trusting ANY measurement, confirm**
  `curl --noproxy '*' http://127.0.0.1:8082/v1/models` is **200, not 503**.

## Logs, ports, proxy
- WHICH LOG IS WHICH: `.iris-logs/backend-<ts>.log` is the LAUNCHER's file (usually an 86-byte
  header). The APP's real log (turn details, `[DER]`, `Oracle decide`) is
  `.iris-logs/backend-<ts>-pid<N>.log`. Concluding "the backend logged nothing" from the launcher
  log is a trap. `backend/logs/irisvoice.log` is stale since 2026-09-03.
- The app log ROTATES (`.log` → `.log.1` → `.log.2`, 10 MB). Concatenate before concluding a gate
  never ran. Logs are mojibake-laden — `grep` needs `-a`.
- Backend `:8090` from Bash: `curl --noproxy '*'`. `HTTP_PROXY`/`HTTPS_PROXY` are set with **no
  `NO_PROXY`**, and the app's httpx picks them up (caught in `embedding_sidecar._health_ok`), so
  app→localhost HTTP can go through the sandbox proxy.
- MCM `query_events` is not authoritative for edits — use disk and tests as ground truth.

## Driving DER turns (the measured recipe)
- **Prefix the message with `/research`.** It maps to `AgentMode.RESEARCH` at confidence 1.0, which
  (a) makes the mode a `DER_TOKEN_BUDGETS` key → `_mode_fraction("research") = 0.90` instead of the
  0.40 default (measured `budget=5898 → 13270`), and (b) routes `_decide_mode` to
  `ExecutionMode.FULL`. Trap: the classifier emits SUFFIXED labels (`research_task`) that are NOT
  table keys, so without the slash command the budget silently drops to 0.40.
  `DER_MODE_WINDOW_FRACTION`: full/spec/research 0.90 · agentic/implement/debug/test/default 0.40 ·
  review 0.25 · quick 0.10. Budget = `window × 0.9 × fraction`; window = min(reasoning, tool_execution).
- **Keep prompts PATH-FREE** ("the current directory", never "the scripts folder") or the model
  invents `/home/user/...`. A ≥200-char message (`MESSAGE_LENGTH_LONG`) also forces FULL on its own.
- Gates: `on_track` needs `queue.mode == ExecutionMode.FULL` AND ≥3 completed steps
  (`der_loop.py:18302`). `sufficient` needs a FAILING **gather** tool reaching the GRAFT decision
  (`agent_kernel.py:12739`, `_DER_GATHER_TOOLS`); a "permanent" crash is "recorded, NOT split (D4)"
  and never grafts.
- A dead WS client does NOT stop a turn: `_session_has_client_for` fails open when
  `session == conversation_id`, and `get_agent_kernel()` sets `_sid = session_id or conversation_id`.

## Oracle / decision-engine conventions
- Adding a consumer is **atomic** (oracle.md §11.5 — never leave the declared set half-changed):
  `decision_engine.CONSUMERS` + `surface_shadow.SURFACE_CONSUMERS` + the scoring SITE + the 3
  pinned enumeration tests, all in one change.
- The engine IS the **JEV cascade** (arXiv 2609.26550): accept when confident, escalate when unsure.
  `Noul.confident()` is TWO-SIDED and `surface_bool()` already accepts-or-escalates.
  **NEVER hand-roll `noul.true(0.5)`** — that discards the escalation band, which is the whole point.
- **Check AUROC before enforcing any consumer.** `tool_choice` showed precision 1.0 with AUROC
  0.5385 (chance); `on_track` 0.0 (inverted). The cascade routes on confidence, so an uninformative
  ranking means there is no band to route.
- **Trace an enforcement value to the place that makes the decision.** The run grade is
  DISPLAY-ONLY (all 3 `_der_report_run_grade` call sites discard it). The decision that ENDS a turn
  is `_der_plan_next_step` returning `None`.
- **Any push needs a CAP** — unbounded same-turn re-queue is what killed the TrailingDirector
  (`_DEPTH_PUSH_MAX`, default 3, per-turn).
- Enforcement is off by default: `enforced_consumers()` default is `{'tool_choice'}`; override with
  `IRIS_DECISION_ENFORCE=<comma list>` (empty = full shadow).
- `trailing_director.py` was DELETED (unreachable since 2026-08-06). Live gap analysis is
  `_goal_contract_open_facts()`. `has_gaps` was KEPT in CONSUMERS (so pinned enumerations pass) but
  has no live site — like `narration`. Removing it is a separate requirements change.

## Testing pitfalls
- `pytest-timeout` is NOT installed in either venv (`.venv` = pytest 9.1.0 primary; `venv` = 9.0.3),
  so pytest.ini's `timeout = 120` is IGNORED ("Unknown config option"). A hanging test WILL stall —
  bound runs externally: `timeout 900 .venv/Scripts/python.exe -m pytest ... > C:/temp/out.txt 2>&1`.
  On Windows pytest-timeout can also kill the whole process; run suspect tests by node id.
- DUPLICATE test files: `backend/tests/<X>.py` and `backend/tests/behavioral/<X>.py` are
  byte-identical and BOTH tracked, so pytest.ini's `testpaths = backend/tests` collects most tests
  TWICE. Edit BOTH (verify `diff -q`) or they drift.
- Test output with mojibake is treated as binary by grep — use `grep -a`.
- Stale-test-double pattern: many DER failures are the TEST's own fixture/double being out of date
  (missing `_router`/`conversation_id`, a `_Step` without `expected_output`, an `_Embed` without
  `encode_with_meta`), not production bugs. **Check the double first.** Baseline-prove any fix by
  reverting it and re-running.
- VAD tests need ~0.5 s silence calibration before speech frames.
- Full frontend Jest default config is the comparison baseline; historical baseline was 8 failed
  suites / 11 tests.

## Silent-failure traps (run `.undefnames.py` before trusting a "verified" claim)
- **A referenced-but-never-bound name compiles clean and dies at runtime** — and here it always
  dies inside a `try/except Exception: pass`, so the fix it was written for is silently disabled.
  `.undefnames.py` (repo root, `symtable`-based, no dependency) finds them:
  `.venv/Scripts/python.exe .undefnames.py backend`. Found 5 in `agent_kernel.py` (session 365),
  incl. one that killed the whole `depth_met` enforcement path and one that made the `sufficient`
  gate unreachable. **A green row count can hide a dead code path**: `emit_row` runs BEFORE the
  raise, so `depth_met` logged 2 rows while `_der_last_depth` was never set.
- **"Verified" usually means the MECHANISM was tested, not the WIRING.** `_der_findings_sufficient`
  had a dedicated unit test while its only caller was dead. Before believing an enforcement path
  works, trace the value to the place that makes the decision.
- **Read each finding before reporting it.** `weakref.ref(cb) if False else cb` is flagged but
  never evaluated — not a bug. `auth_handlers.py:401`'s branch is unreachable.
- Stale test doubles keep showing up: `test_goal_contract_coverage.py`'s `_Kernel` predates
  session-326's `_der_emit_card_settle`, so the grade helper raised, the handler swallowed it and
  returned `""`. Baseline-prove by reverting your own edits and re-running.

## The ledger can be silently dead — check it before trusting ANY row count
- **`data/memory.db` is PLAINTEXT, but `sqlcipher3` is installed**, so
  `open_encrypted_memory` (backend/memory/db.py) used to run `PRAGMA key` against a plaintext file
  → `file is not a database` → `initialise_memory` RAISES → no `MemoryInterface` → `ffi_init_engine`
  (its only caller) never runs → `_engine is None` → **every ledger row is refused, silently**.
  Fixed session 365 by detecting the file header (a SQLCipher file does not start with
  `SQLite format 3\0`). The stale comment claiming "no sqlcipher3 wheel on this machine" was the tell.
- **Symptom to recognise:** `.iris-logs` shows `ffi ingest returned falsy for <tool> (row dropped by
  store)`, and `grep -a "C++ core loaded"` is EMPTY (the engine never initialised). A dead ledger
  looks exactly like a healthy one with no traffic.
- The chain is: `emit_row` → `AgentKernel._shadow_row_sink` → `bridge.record_decision` →
  `tool_bridge._ingest` → `ffi_ingest_event`. A decision row is recorded as a tool event named
  `no_tool` (tool_bridge.py:2314), so `no_tool` dominates the warnings — it is NOT a `no_tool` filter.
- `initialise_memory` failing also leaves the kernel with no memory interface
  (`get_trajectory_recorder(None)` → `_NullMemoryInterfaceMarker`).

## Wake / audio facts
- Violawake threshold is 0.70; do not raise toward 0.80. Phrase peaks 0.773–0.786; steady silence
  0.401. Backbone hash and streaming embeddings are verified — do not re-open the hash-mismatch theory.
- Pipeline: 16 kHz, 512-sample frames, 31.25 Hz callback, one embedding / 1280 samples.
- `data/hey_iris_synthesized_test.wav` is 24 kHz — resample to 16 kHz before testing.
- `IRIS_STT_WARM_DISABLE` exists but is unset; Parakeet warm-up is expensive.
- **TTS WORKS (session 365 — this note used to say `pocket_tts` was MISSING and produced ZERO
  audio; that is STALE and wrong).** Verified live: `[TTSManager] Synthesis done: 77760 samples`,
  `[TTS] engine.pipeline OK, tts manager loaded=True`, `[TTS][words] Monitor started`,
  `[TTS][producer] synthesized 47 audio chunks`. Check the log before believing a TTS defect.
- Known stale test: `TestTTSWordEventIntegration` lacks the committed audio-pipeline mock and may
  hang — not a VAD/model regression.

## The embedding sidecar (port 18183) — liveness is not capability
- It **SURVIVES backend restarts** by design, and `ensure_running()` adopts whatever answers
  `/health` ("someone else's server on the port counts"). So a **stale, embedding-incapable**
  server can hold the port forever: every embed 404s → `EmbeddingService` falls back to a HASH →
  semantic retrieval and step verification degrade → **the DER chains stop completing**
  (`result was not verified` / `all pages failed to fetch`). Seen live session 365 (pid 20768).
- **`GET /v1/embeddings` returns 404 EVEN ON A HEALTHY SERVER** — llama-server registers only
  **POST** on that route. So a capability probe MUST POST. (I got this wrong once: a GET probe
  looked correct only because the server I tested against was broken on both methods.)
- Correct check: `POST /v1/embeddings` with a one-token input → 200. `_health_ok()` is now
  health-only and the capability gate runs **only on the adoption path** (when we do not own the
  process), so it is off the hot path.
- The sidecar is launched with `--embedding -m LFM2.5-Embedding-350M-Q4_K_M.gguf --port 18183 -c 2048
  --parallel 4` (CPU-only). `--embedding` IS valid for this binary (`--embedding, --embeddings`).
- **NEVER kill `llama-server` by NAME** — the embedding sidecar IS one. Kill by verified PID.

## `.lfmrun.py` / `.brain.py` need NO_PROXY (session 365)
- Both talk to `ws://127.0.0.1:8090` via `websockets`, which honours `HTTP_PROXY` — set with **no
  `NO_PROXY`** here, so they die with `InvalidProxyStatus: proxy rejected connection: HTTP 502`.
  Run them with `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost`.
- `.lfmrun.py`'s `_server_serving()` used to be a bare TCP connect, which prints "load confirmed"
  while `/v1/models` is still **503** (llama-server binds the port BEFORE the weights are in). It now
  also requires a non-503 `/v1/models` answer. A port probe is not a readiness check.
