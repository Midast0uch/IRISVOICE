# LIVE SMOKE — 2026-09-10 (Session 319)

**Companion to:** `docs/LIVE_SMOKE_2026-09-09.md` (session 311). That document's §10 Acceptance bar
is USER-LOCKED and **still in force** — it is not restated here, it is inherited.
**Branch:** `feat/agent-multi-step-tool-execution` — DO NOT PUSH without explicit approval.
**Spec under test:** `specs/tool-result-envelope/` — Wave 6 (T22–T28) + TG-6, plus the
session-319 code changes listed in §3.
**Backend state at plan creation:** RUNNING BUT **STALE**. PID 20848 started 09:57:23; every
session-319 change was written after that. **A fresh start is REQUIRED before any item below.**
**Env rule:** `IRIS_EMBEDDING_SIDECAR` stays ON (inherited from 09-09). `IRIS_PHASE_SCHEDULER=1`
is set in `.env:55` — leave it, and use §4 to toggle it deliberately.

> **THE LESSON THAT CREATED THIS RUN.** The session-318 handoff reported a FAIL verdict, and the
> first session-319 act was to check whether the code under test was actually loaded. It was not:
> the backend process predated the fix by 47 minutes. The result was a valid measurement of the
> **old** code that read as a measurement of the **new** code. Pre-flight item P0.7 exists to stop
> that recurring. Do not skip it.

---

## 0. How we run this (collaboration contract)

- **You (user) = hands + eyes:** drive UI at `http://localhost:3000`, report see/hear, flip
  toggles, barge-in by voice, confirm UX.
- **Me (assistant) = instruments:** watch `.iris-logs/`, WS events, counters, HAR files, gate lines.
- **Evidence rule:** paste actual output (log line, WS frame, screenshot path, HAR timestamp).
  "Done" without output does not close an item.
- **Bug vs feature:** bug = frontend does not reflect what backend did (contract break). Odd layout
  = feature until proven otherwise.
- **BLOCKER RULE (locked):** on a serious blocker — crash, hang, WS dead, gate wedge, data loss, or
  a spec promise visibly broken — STOP the checklist, log it in §8, attempt a fix, re-verify the
  failed item, then proceed. Minor oddities go to §7 and do not stop the run.
- **Status marks:** `[ ]` todo · `[~]` in-progress · `[x]` pass (with evidence) · `[!]` BLOCKER
  (see §8) · `[S]` skipped with reason.
- **Log convention:** every checked item gets one row in §7. Every `[!]` gets a row in §8.
- **Explain first rule (new, owner-locked 2026-09-10):** in the findings log, state the idea in
  plain words before the technical detail. An analogy is welcome when it helps.

### Launch (manager only — every server command blocks forever otherwise)

```bash
npm run iris:start:backend    # detaches, prints PID, returns immediately
npm run iris:start:frontend   # same
npm run iris:status           # pid + alive + memory per service
npm run iris:stop             # kills every tracked service and its tree
```

- Logs: `.iris-logs/<service>-<timestamp>.log`. PIDs: `.iris-pids/`.
- Backend: ~216 s to ready (pocket-tts model load dominates). Budget 300 s. Ready = `/health` → 200
  or `Application startup complete` in the log. Deadline-bound poll, not iteration count.
- Frontend: do NOT poll HTTP (Next compiles on first request, `curl` hangs). Poll the listener on
  `:3000` or `Ready in` in the frontend log.
- Port contract: backend `8090`; frontend WS `ws://<host>:8090/ws/iris`. Confirm `:8090` listening
  before any UI test — otherwise the orb sits in "reconnecting".
- Teardown: `npm run iris:stop`, verify ports clear. An orphan on 8090 is a stale-port failure.
- Drive order: Browser MCP → Chrome DevTools MCP → Playwright (last resort, `waitUntil:
  domcontentloaded` — persistent WS blocks `load`).

### Orient (stop if you cannot orient — the app is not testable)

Orb (centre) + ChatWing (left) + DashboardWing (right) are the anchors.

- **Orb click gotcha:** orb labels are `<span>`s in a 3D-transformed container — `click` may report
  success while the label gets nothing. Use JS dispatch and verify with a snapshot.
- **Known non-blockers:** web-mode desync after reload (toggle off→on); stale `localStorage`; CSS is
  PRE-COMPILED (`css-src/globals.css` → `public/globals.css`) — new utility classes are silently
  missing until rebuilt.

---

## 1. Pre-flight [ ]

| ID | Check | Expected | Evidence |
|----|-------|----------|----------|
| [ ] P0.1 | Backend fresh via manager, `/health` → 200 | Ready ≤300 s, no traceback at boot | |
| [ ] P0.2 | Frontend listener on `:3000` + `Ready in` in log | No compile hang | |
| [ ] P0.3 | Launcher on `:8080` (NOT optional — `next.config.mjs` rewrites `/launcher/:path*` → `:8080`; the root page 500s without it) | Vite ready, `:3000/` → 200 | |
| [ ] P0.4 | WS connected (healthy idle orb = connected WS + NO inner glow) | Orb breathes idle, no "reconnecting" | |
| [ ] P0.5 | Web-mode re-sync (off→on) | `set_web_mode` ack in log | |
| [ ] P0.6 | Log baseline noted (backend log path for this run) | Path pasted in §11 | |
| [ ] P0.7 | **THE CODE UNDER TEST IS ACTUALLY LOADED** | `agent_kernel.py` mtime is OLDER than the running backend's start time | |
| [ ] P0.8 | Phase scheduler flag state confirmed | `[phase_manager] phase_scheduler=active (IRIS_PHASE_SCHEDULER=1)` at boot | |

**P0.7 — how to check, and why it is first-class here.** Compare the two timestamps:

```bash
powershell -NoProfile -Command "Get-Process -Id <backend_pid> | Select-Object StartTime"
ls -la --time-style=full-iso backend/agent/agent_kernel.py
```

If the source file is **newer** than the process start time, the running backend does **not** have
that change. Restart and re-check. A test run against stale code produces a confident wrong answer,
which is worse than no answer.

**P0.8 — why it is checked every run.** `IRIS_PHASE_SCHEDULER=1` lives in `.env`. It was recorded
as OFF in `CADUCEAN_ARCHITECTURE.md` §9 for an unknown period because that table read the code
default instead of the running configuration. Confirm the running value, not the file.

---

## 2. Core regression (fast fail — STOP on red)

| ID | Check | Expected | Evidence |
|----|-------|----------|----------|
| [ ] R2.1 | Chat "Hello" → Enter | Streaming reply, typing indicator, `process_text_message` in log, no hang | |
| [ ] R2.2 | Model selection APPLY + mid-session switch | `Model selection updated`, correct `context_window`, no provider clobber | |
| [ ] R2.3 | Reload persistence | Conversation + settings restored | |
| [ ] R2.4 | Audio idle | Mic reopens after reply, no stuck TTS gate, orb back to idle | |
| [ ] R2.5 | TTS narration audible on the FIRST turn after restart | Audio present — **not silent** | |

**R2.5 exists because of the F5 bug.** A worker that finished loading *after* its startup deadline
used to be abandoned, which spawned another cold worker and left **every narration in the turn
silent**. The fix adopts the late-ready worker. The first turn after a restart is the exact case
that used to fail, so it is the case that must be checked.

---

## 3. SPEC — tool-result-envelope Wave 6 (the live proof owed)

Suite state: 79 tests green across the envelope / registry / recovery / URL-memory suites.
Live state: **zero sessions on this code.** Everything below is live-only.

| ID | Check (drive) | Expected (UX + function) | My instrument read |
|----|---------------|--------------------------|--------------------|
| [ ] W6.1 | Research prompt with a **seeded dead address** | The dead address is never re-fetched; a recovery step appears as its **own** step and settles honestly | `[DER:recovery] ENQUEUED (job board)`; `envelope.recovery_opens`; zero same-address refetch |
| [ ] W6.2 | Multi-step research, then **force a step failure** | The failed step's addresses enter turn memory; the next step does **not** re-crawl them | `[DER] failure path recorded URLs for <step> (turn memory now holds N address(es))` |
| [ ] W6.3 | Watch the turn end | The final answer **streams** progressively rather than appearing all at once | first token time vs completion time in the log |
| [ ] W6.4 | Watch the end of a long turn | The turn settles within the synthesis deadline (120 s) — never hangs | `run grade` line present; elapsed-vs-deadline |
| [ ] W6.5 | Prism card with a 4-column table | No mid-word breaks; headers on one line; the table scrolls rather than compresses | screenshot; compare against the session-319 screenshot |
| [ ] W6.6 | Run grade on a turn that **failed a step** | `run grade` is logged — this used to log **zero times** on the abort path | `[DER] run grade:` line present |
| [ ] W6.7 | A tool with no registered expectation bar | Judged `unclear` and **counted**, never silently matched | `unknown_expectation_counts()` non-empty |

**W6.1 is the headline item.** The recovery lane has never fired on a live blocker. A seeded dead
address inside an otherwise-successful crawl is the only honest way to prove it does.

**W6.3 note.** If streaming is not wired yet, mark `[S]` with that reason rather than `[!]`. A
missing feature is not a blocker; a broken promise is.

---

## 4. Concurrency A/B (env-controlled — see `CADUCEAN_LIVE_TEST_PLAN.md` T8)

The full protocol lives in T8. Summary for this run:

```bash
# Config A — CLASSICAL control (phase gate off)
IRIS_PHASE_SCHEDULER=0 <launch backend>
# Config B — PHASE gate on
IRIS_PHASE_SCHEDULER=1 <launch backend>
```

- Both flags are read **lazily** — a restart is not strictly required, but **use a restart** for
  this run so each config has a clean process and a clean log.
- **GOTCHA:** `main.py` loads `.env.local` with `override=True`, so `.env.local` beats a real
  environment variable. Confirm the toggle took effect via P0.8 before trusting any result.
- **Measure three numbers, not speed:** completed work, wasted work, collisions. A config that is
  faster but wastes more work is **not** a win. Minimum 3 runs per config; "inconclusive" is a
  legitimate result and must be reported as such.

| ID | Check | Expected | Evidence |
|----|-------|----------|----------|
| [ ] C4.1 | Config A: same prompt ×3 | Baseline numbers recorded | `GATE_DECISION reason=flag_off`; counters snapshot |
| [ ] C4.2 | Config B: same prompt ×3 | Not worse on any of the three numbers; better on ≥1 | `reason=gated` with `wait > 0`; counters snapshot |
| [ ] C4.3 | Gate actually acted | At least one `reason=gated` with a non-zero wait | gate lines |

---

## 5. Interop (highest-risk seams)

| ID | Check | Expected |
|----|-------|----------|
| [ ] I5.1 | Wave 6 recovery + narration ON | Recovery step narrates without overlapping the main plan; no stuck gate |
| [ ] I5.2 | Wave 6 + Caducean gate ON together | Recovery's crawl respects the gate; no 429 storm; `reason=gated` appears without stalling the turn |
| [ ] I5.3 | Failure path + grade | A turn that fails a step still reports `done + grade`, and the recovery still queues |

---

## 6. Benchmarks + closeout

| ID | Check | Expected |
|----|-------|----------|
| [ ] B6.1 | `benchmark_websearch_memory --assert-websearch` | IRIS peak ≤50 / return ≤25 / driver peak ≤350 MB |
| [ ] B6.2 | Turn wall-clock on the standard probe | Compared against the inherited baselines (conv-96 5:15 / conv-97 5:38 / conv-99 6:40) |
| [ ] B6.3 | Commit call (USER decides) | `specs/` artifacts untracked by convention. NO PUSH without approval |

**Short-on-time path:** P0.1 → **P0.7** → P0.8 → §2 → W6.1 → W6.6 → W6.5 → C4.2.
Covers staleness, the headline recovery proof, the grade fix, the card, and one A/B arm.

---

## 7. Findings log (every checked item leaves a row)

| Time | ID | Result (pass/obs) | Evidence | Notes |
|------|----|-------------------|----------|-------|
| | | | | |

---

## 8. Blocker log (serious only — triggers STOP → fix → re-verify)

| Time | ID | Symptom | Logs / capture | Fix attempted | Re-verify |
|------|----|---------|----------------|---------------|-----------|
| | | | | | |

---

## 9. Pre-existing (do NOT file as regressions)

- `backend/agent/verifier.py` `importlib.util` — fixed 2026-09-09; if it reappears, it is a
  regression, not pre-existing.
- `test_der_phase1::test_single_authority` stale assertion (absent at HEAD).
- `voice_pipeline` stale paths / stale VAD asserts / stale sounddevice mock + 2 headless hangs.
- **TTS suite hazard (new):** `test_tts_audio`, `test_tts_lifecycle`, `test_tts_pocket_load` spawn
  real workers and SIGTERM the pytest process. Run
  `backend/tests/contract/test_tts_subprocess_contract.py` instead. A SIGTERM here is not a
  regression signal.
- **`test_wave5_ledger_contract.py::test_ct17`** asserts an invariant and does **not** reproduce a
  race — its docstring says so. Do not cite it as race evidence.
- Regression baselines (session-310, post-54381309): contract 1478–1485 pass / 30 pre-existing fail;
  audio 252/7; barge solo 40/40; vision 275 pass / 2–3.

---

## 10. Acceptance bar

**Inherited and USER-LOCKED from `LIVE_SMOKE_2026-09-09.md` §10 — not restated, not relaxed.**
A `pass` requires all three: functional, presentational, timing. Read that section before
claiming any item green.

---

## 11. Run state

- Current phase: PLAN CREATED — no items run yet
- Backend log this run: (fill on start)
- Frontend log this run: (fill on start)
- Backend PID at run start: (fill — and confirm it postdates every session-319 source change)
- Screenshots: `screenshots/` (timestamped, never repo root)
- Active blocker (§8 row): none
