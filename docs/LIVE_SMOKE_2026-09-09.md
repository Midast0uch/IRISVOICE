# LIVE SMOKE — 2026-09-09 (Session 311)

**Replaces:** `docs/LIVE_TESTING_CHECKLIST.md` (stale 2026-05-27) and the stale Gate 1/2 sections of `bootstrap/GOALS.md` for live-test purposes.
**Branch:** `feat/agent-multi-step-tool-execution @ 54381309` — DO NOT PUSH without explicit approval.
**Specs under test:**
- SPEC 1: `specs/speech-lane-engine/` — Waves 1–4 + TG-4 green (196/196, AC10.1–AC10.14 PROVEN in suite). **Zero live-session evidence. This run is the live proof.**
- SPEC 2: `specs/vision-goal-directed-search/` — T1–T42 DONE incl. T33–T36 harnesses + Wave 7 T37–T42 interop. **Final live e2e deferred while speech lanes consumed sessions. Must re-verify on current build (shares DER path).**
**Backend state at plan creation:** KILLED (stale PID 16272 was pre-T16 code). Fresh start required.
**Env rule:** `IRIS_EMBEDDING_SIDECAR` stays ON for live runs. Never set `=0` (test-suite-only measure — sidecar must spawn on `:18183`).

---
## 0. How we run this (collaboration contract)

- **You (user) = hands + eyes:** drive UI at `http://localhost:3000`, report see/hear, flip toggles, barge-in by voice, confirm UX.
- **Me (assistant) = instruments:** watch `.iris-logs/`, WS events, counters, HAR files, benchmark gates.
- **Evidence rule:** paste actual output (log line, WS frame, screenshot path, HAR timestamp). "Done" without output does not close an item.
- **Bug vs feature:** bug = frontend does not reflect what backend did (contract break). Odd layout = feature until proven otherwise.
- **BLOCKER RULE (locked):** on a serious blocker — crash, hang, WS dead, gate wedge, data loss, or a spec promise visibly broken — STOP the checklist, log it in §8, attempt a fix, re-verify the failed item, then proceed. Minor oddities go to §7 Findings and do not stop the run.
- **Status marks:** `[ ]` todo · `[~]` in-progress · `[x]` pass (with evidence link) · `[!]` BLOCKER (see §8) · `[S]` skipped with reason.
- **Log convention:** every checked item gets one row in §7 (pass evidence or observation). Every `[!]` gets a row in §8.

### Launch (manager only — every server command blocks forever otherwise)

```bash
npm run iris:start:backend    # detaches, prints PID, returns immediately
npm run iris:start:frontend   # same
npm run iris:status           # pid + alive + memory per service
npm run iris:stop             # kills every tracked service and its tree
```

- Logs: `.iris-logs/<service>-<timestamp>.log`. PIDs: `.iris-pids/`.
- Backend: ~216s to ready (pocket-tts model load dominates). Budget 300s. Ready = `/health` → 200 or `Application startup complete` in log. Deadline-bound poll, not iteration count.
- Frontend: do NOT poll HTTP (Next compiles on first request, `curl` hangs). Poll listener on `:3000` (`netstat -ano -p TCP | findstr :3000`) or `Ready in` in frontend log.
- Port contract: backend `8090` (`data/iris_config.json` → `ports.backend_port`; `IRIS_BACKEND_PORT` wins). Frontend WS `ws://<host>:8090/ws/iris`. Confirm `:8090` listening before any UI test — otherwise orb sits in "reconnecting".
- Teardown: `npm run iris:stop`, verify ports clear. Orphan on 8090 = stale-port failure.
- Drive order: Browser MCP → Chrome DevTools MCP → Playwright (last resort, `waitUntil: domcontentloaded` — persistent WS blocks `load`).

### Orient (stop if you cannot orient — app not testable)

Orb (centre) + ChatWing (left) + DashboardWing (right) are anchors. Must reach: orb, ChatWing textbox ("Start a conversation"), DashboardWing, settings (WheelView).

- **Orb click gotcha:** orb labels are `<span>`s in a 3D-transformed container — `click` may report success while label gets nothing. Use JS dispatch, verify with snapshot. HexNode buttons take real uid clicks. Clicking orb itself navigates back to root (no back button).
- **Known non-blockers:** web-mode desync after reload (toggle off→on to re-sync `set_web_mode`); stale `localStorage` (clear for truly fresh state); CSS is PRE-COMPILED (`css-src/globals.css` → `public/globals.css` via tailwind CLI — new utility classes silently missing until rebuilt); `* {margin:0}` must stay in `@layer base`.

---
## 1. Pre-flight [~]

| ID | Check | Expected | Evidence |
|----|-------|----------|----------|
| [x] P0.1 | Backend fresh via manager, `/health` → 200 | Ready ≤300s, no traceback at boot | PASS 2026-09-09: PID 22876, `/health` 200, `Application startup complete` + `Uvicorn running on http://0.0.0.0:8090`, zero Traceback. Log `.iris-logs/backend-20260909-075925.log`. Outbound `httpcore connect_tcp.failed` DEBUG lines are provider probes, not boot errors |
| [x] P0.2 | Frontend listener on `:3000` + `Ready in` in log | No compile hang | PASS 2026-09-09: PID 29988 (listener 31128), `Ready in 30.3s`. Log `.iris-logs/frontend-20260909-075940.log` |
| [x] P0.3 | WS connected (healthy idle orb = connected WS + NO inner glow) | Orb breathes idle, no "reconnecting" | PASS 2026-09-09: user-confirmed orb alive and behaving normally at idle |
| [x] P0.4 | Web-mode re-sync (off→on) | `set_web_mode` ack in log | PASS 2026-09-09: two `set_web_mode enabled:true` frames (seq 5 + 6), `[WebMode] session=session_iris web_mode=True (global internet access ON)` |
| [x] P0.5 | Fresh conversation (clear `localStorage` if needed) | Empty chat, textbox present | PASS w/ FINDING F1 2026-09-09: ChatWing usable, old threads visible (no clustering). Ordering + cross-instance persistence questioned — see F1, not a blocker |
| [x] P0.6 | Log baseline noted (backend log path for this run) | Path pasted below | PASS — paths in §10 |
| [x] P0.0 | Launcher on `:8080` (NOT optional — `next.config.mjs` rewrites `/launcher/:path*` → `:8080`; root page 500s/`/_error` compile without it) | Vite ready, `:3000/` → 200 | PASS 2026-09-09: PID 3600 via manager `--cwd iris-launcher`, vite v5.4.19 ready in ~153s (slow fs), listener on `:8080`, frontend root 200 len=22811. Skill gap filed: app-testing said backend+frontend only — launcher is required for root page |

---
## 2. Core regression (fast fail — STOP on red)

| ID | Check | Expected | Evidence |
|----|-------|----------|----------|
| [x] R1.1 | Chat "Hello" → Enter | Streaming reply, typing indicator, `process_text_message` in log, no hang | PASS 2026-09-09: text `Hey there. I'm IRIS...` (cerebras/qwen-3.8-27b) + warm TTS audible (turn-2 45ch error reply spoken via `synthesize_stream`). Turn-1 cold-worker silence = F3 (one-time) |
| [x] R1.2 | "What tools do you have available?" | DER path: `task:start → tool:call → tool:result → task:done` + `inference_event` | PASS-reframed 10:40: direct answer CORRECT (1566ch grouped tool rundown, no planning — planner restraint, contrasts F4 misfire). `task:start` count still 0 post-restart → DER proof (incl. B2 verifier fix) deferred to S2.1 multi-step task. TTS skipped on re-cold worker (spawn 10:40:03 → ready 10:40:55, 52s); format card-vs-plain folded into R1.5 |
| [ ] R1.3 | Voice settings card (DashboardWing → Voice → Speech) | `narration_enabled` toggle visible in BOTH personal + developer modes, default ON | screenshot |
| [x] R1.4 | Model selection APPLY + mid-session switch | Log `Model selection updated`, correct `context_window`, no provider clobber | PASS 10:38: `Model selection updated: reasoning=qwen-3.8-27b, tool_execution=qwen-3.8-27b, provider=cerebras, context_window=64000` + `API key stored via provider keyring for 'cerebras'` + slot probe True. B1 dropdown fix + key re-entry both proven on this path |
| [ ] R1.5 | Reload persistence | Conversation + settings restored; prism card (MARKDOWN + "Expand to panel") + TaskListCard, NO duplicate plain-text below card | screenshot |
| [ ] R1.6 | Audio idle | Mic reopens after reply, no stuck TTS gate, orb back to idle | observation |

---
## 3. SPEC 1 — speech-lane-engine (the live proof owed)

Suite state: TG-4 196/196, AC10.1–AC10.14 PROVEN. Live state: ZERO sessions. All items below are live-only.

| ID | Check (drive) | Expected (UX + function) | My instrument read |
|----|---------------|--------------------------|--------------------|
| [ ] S2.1 | Multi-step task ("research X and compare") | Planned beats SPEAK at start; FIRST beat immediate; final reply SUBSUMES pending narration (queued narration cancelled, never spoken after reply) | `admit()` subsumption logs; spoken-vs-cancelled counter |
| [ ] S2.2 | Narration toggle OFF mid-task, then ON next task | Queued beats purged; pre-synth holds aborted + freed; replies/alerts UNAFFECTED; drops counted; narration resumes next task | toggle flips/drops counter; hold-free paths on every exit |
| [ ] S2.3 | Thinking gap (slow tool) | Filler fires ONCE; never same phrase twice in a row; subsumed when real beat arrives; never merges into reactive line | filler logs (`filler_allowed` silence gate = not playing + pending==0) |
| [ ] S2.4 | Watch orb DURING narration | Orb breathes via EXISTING `audio_envelope` (0.06-speaking / 0.0-idle + `listening_state`); NO phantom chat card; NO `tts_started` from narration path with matching turn_id; error path clears orb | WS `audio_envelope` frames; `tts_started` turn_id non-match |
| [ ] S2.5 | Barge-in during narration | Narration killed, fresh turn starts, mic gate reopens synchronously | barge-ins-during-narration counter; gate derived from `is_playing()` |
| [ ] S2.6 | Content cap spot-check (marathon beat) | Long beat capped at sentence boundary ≤60 words; spoken always a prefix of authored; short beat verbatim | `_cap_narration_text` log |
| [ ] S2.7 | Counter readout → OQ-1/OQ-2 verdict | 7 counters: barge-ins / spoken-vs-cancelled / shadow divergences / merge rate / pre-synth hit-waste / toggle flips-drops / expectation-miss freq. Subjective rating stays DEFERRED unless counters leave OQ open | pasted counter values |

---
## 4. SPEC 2 — vision-goal-directed-search (live e2e on current build)

Suite state: T1–T42 DONE. Live state: OQ-3/CT-5 confirmed on 2 pages only; full e2e + harness re-runs owed (speech-lane Wave 7 interop touched the shared DER path: T37 batch scheduling, T38 validator correction, T39 GoalAnatomy union).

| ID | Check (drive) | Expected (UX + function) | My instrument read |
|----|---------------|--------------------------|--------------------|
| [ ] V3.1 | Goal search ("find 3 sources on X, compare prices") | Goal Anatomy inspector renders (terminal chassis dev / TaskListCard personal), target anchor visible | `GoalAnatomy` mutate/log |
| [ ] V3.2 | Watch steps land per page (need 3+ pages; was 2) | Steps advance per page; `TASK_PROGRESS` carries `detail_url` + `phase/phase_sequence`; URL subtitle badges on TaskListCard rows | WS `TASK_PROGRESS` frames |
| [ ] V3.3 | Batch pool during multi-URL run | Batch pool status in TaskListCard + terminal chassis; per-host concurrency ≤2; 429 → exponential-jitter backoff | batch pool logs |
| [ ] V3.4 | Conflicting facts across sources | ≥2-domain corroborated facts get verified checkmarks; irreconcilable flagged with citations | verification matrix |
| [ ] V3.5 | Re-run / price change | Temporal pills ("Price dropped 10%"), `revision+1` | `TemporalDelta` log |
| [ ] V3.6 | Mid-run follow-up ("only EU sources") | In-flight `mutate()`, plan continues WITHOUT restart | mutation log |
| [ ] V3.7 | Takeover (`AskUserQuestion kind=browser_takeover` / challenge) | Takeover banner + contextual reason; panel unlocks (`pointer-events:auto`); resume on resolve, re-arm `none` | `iris:browser_takeover_requested` event |
| [ ] V3.8 | Crawl proof (I own this) | NEW `data/har/*.har` with current timestamp; browser panel URL → `/api/browser/capture/{job_id}/{page}` as pages land | HAR listing |

---
## 5. Interop (specs together — highest-risk seams)

| ID | Check | Expected |
|----|-------|----------|
| [ ] I4.1 | V3.1 run WITH narration ON | Beats narrate crawl progress; no overlap; saccadic cursor ≤180ms under ≥3 actions/s, no queue drift; overlay `loading → dispersing → crawling → complete` without lag |
| [ ] I4.2 | Toggle OFF mid-crawl | Narration drops; crawl + TaskListCard progress continue visibly |
| [ ] I4.3 | Takeover WHILE narrating | Awaiting/Critical lane preempts narration; re-announces after resolve |
| [ ] I4.4 | DER sanity (I own this) | `[DER] budget=N from window=M` shows REAL window (never 8192 with binding); per-turn calls below Wave-0 baseline; `memory_chain` rows land per step in `data/memory.db` with mediator recorded; repeated failure in one coord region lowers that mediator THERE only |

---
## 6. Benchmarks + closeout

| ID | Check | Expected |
|----|-------|----------|
| [ ] B5.1 | `benchmark_vision_search_efficiency --assert-efficiency` | ≥40% latency + token reduction (last: −68% / −99%; baseline 6.31s/5p/~4075tok vs hybrid 2.02s/1p/~35tok) |
| [ ] B5.2 | `benchmark_websearch_memory --assert-websearch` | IRIS peak ≤50 / return ≤25 / driver peak ≤350 MB (5 clean URLs ×2, 5/5 usable) |
| [ ] B5.3 | `bootstrap/GOALS.md` roadmap flip | Speech-lanes gate marked complete (only after §3 green) |
| [ ] B5.4 | Commit call (USER decides) | `specs/` artifacts untracked by convention — commit or keep MCM-only. NO PUSH without approval |

**Short-on-time path:** P0 → §2 → S2.1/S2.2/S2.4 → V3.2/V3.6 → I4.1 → B5.1. Covers subsumption, toggle, echo, detail_url, mutation, interop.

---
## 7. Findings log (every checked item leaves a row)

| Time | ID | Result (pass/obs) | Evidence (log line / WS / screenshot / HAR) | Notes |
|------|----|-------------------|----------------------------------------------|-------|
| 2026-09-09 | F9 ✅ FIXED (live re-verify on return) | Root cause: `agent_kernel._format_tool_result` fell to compact-JSON for dicts without content keys; `get_rendered_documents` envelope (`success/conversation_id/documents`) hit it → `str(result)[:200]` → card row | FIXED: documents-envelope branch summarizes `N document(s) retrieved: titles…` (full data stays in store). Twins `test_der_concurrent` +2 new tests pass; 6 `_FakeKernel._router` fails proven pre-existing via clean-HEAD worktree (removed after). Backend restarted (PID 12692) so fix is live | Re-verify: next green turn's RECALL row must read `N document(s) retrieved…` |
| 2026-09-09 | F10 (timing) | conv-96 5:15 (crawl 61+55s, synthesis ~3.1min). conv-97 5:38 (13:05:10→13:10:48): crawl legs 148s+82s, synthesis ~84s (13:09:24→13:10:48). Pattern: crawl legs SERIAL (~1-2.5min each) + synthesis on bloated context (1.5-3min). Citing→synthesizing dominates per user | Both `DER completed der_steps=3` | Perf follow-up: parallelize legs (T37 pool exists — verify it engages), bound synthesis context. No code yet |
| 2026-09-09 | F11 (conv-97 quality + spec-conformance) | `DataExtractor` LLM EMPTY responses ×2 (key live) + 404s + truncated renders → thin-but-honest result. Spec-conformance read: retrieval/extraction (BELOW the spec) failed on input quality; the spec's gates (verification ≥2 domains, no-fabrication) correctly refused to invent — the machinery kept its promises, its inputs didn't. Extraction robustness (retry/dedicated model) is the real gap | `Empty response from API` ×2; `DER completed`; honest `comparison wasn't completed…` | Follow-up, not blocker. T33 benchmark re-run post-smoke quantifies |
| 2026-09-09 | F12 (counter vs rows) | Card counter `[3/8]` while ~6/8 nodes green: counter (`unifiedProgress` over steps+pages) and row states (planner steps + phase rows) derive from different slices, so they disagree visibly | conv-97 snapshot: [3/8]... wait UI said [1/7] mid-run → [3/8] end vs 6 green rows | Counter must count what rows show (or rows show what counter counts) — card honesty batch |
| 2026-09-09 | F13 (browser surface) | In-app browser renders captured pages as raw HTML, no CSS/styling/components | `/api/browser/capture/...` serves settled DOM; stylesheets dropped (likely trust-routing sanitization of untrusted content) | Design tension: XSS-safety vs a browser that doesn't look like the web. Needs a decision, not just a fix |
| 2026-09-09 | F8 (tier: text capped, POSITION still broken) | Text cap `min(320px,60vw)` proven live (span max-width 320px + ellipsis in DOM). BUT pill (396px @ viewport center x=960) still overlaps dashboard iframe (right-edge hit-test = `IFRAME.flex-1.w-full`). Root cause: `orbWingGeometry` models BOTH wings at fixed 510px → symmetric frame → offset 0; real dashboard is flex-fluid (iframe fills space), so the true free-band center isn't viewport center | Fix needs live measurement (wing rects) or model rework + visual loop — queued, not attempted solo |
| 2026-09-09 | F7 (S2.1/V3.2 obs) | OBS — S2.1 DER RAN but liquid-card steps never visibly advanced; `task:start/done/fail` vocabulary absent — real card events are `TASK_CARD` + `CARD_LIFECYCLE` + `TOOL_DECISION`/`TOOL_DISPATCH` (found conv-95: card created, double-emit `continues`, 147s crawler_query success) | Tier `[5/5]` frozen + no completion UX on error turns; `task:start` count 0 is VOCABULARY not absence | Step-progress advancement (V3.2 `detail_url`/phase) still unproven — needs a COMPLETED turn. `AskUserQuestion` → `question_response` (`Diagram` click) proven working end-to-end (T11-ish behavior alive) |
| 2026-09-09 | F6 (persistence split, sharpened on return) | OBS — after refresh: TASK card rehydrated but PRISM result card did NOT (chat text persists, prism document gone). Plus: rehydrated card shows 3 steps while ~7 were taken live (plan steps persisted, runtime sub-steps/phases not) | Task cards persist (DB-backed); prism documents + fine-grained progress are in-memory only | Two gaps in one: (a) prism rehydration missing, (b) persisted card undercounts the work. Both feed the memory-probe run: card ID handoff across conversations is the workaround under test |
| 2026-09-09 | F5 (follow-up, NOT this smoke) | Turn-lifecycle gap: failed DER turn emits NO `task:done`/`task:fail` (count = 0 all session) → frontend keeps routing follow-ups as `steer` into the dead turn → steering inbox never drains (consumer only runs mid-live-task). Chat wedges until new conversation or restart | `steer queued for session_iris` 14:13:06 never consumed; `task:done/task:fail` count 0 | B2's one-liner removes the trigger; lifecycle redesign is spec-sized follow-up, do NOT widen |
| 2026-09-09 | F4 (R1.1 obs) | OBS — turn-2 entered DER on trivial prompt (`Say okay in five words`) → liquid progress card rendered → DER died in pre-existing `verifier.py` importlib NameError → lane spoke the error aloud correctly | `DER path error ... NameError`, `DER response: [IRIS error: name 'importlib' is not defined]`, `_speak_response` 45ch error reply, user heard it | importlib = §9 pre-existing (T10 finding), NOT a regression; lanes speaking the failure is correct behavior. Open Q: why trivial chitchat routes to DER (`_needs_planning` on imperative `Say...`?) — revisit if it pollutes §3 narration tests |
| 2026-09-09 | F3 (R1.1/R1.6 obs, USER-CORRECTED) | OBS — turn-1 TTS silent; user states startup TTS was NEVER slow before, so the 3.3min cold spawn is itself anomalous, not normal cold cost | 09:57:12 `tts manager loaded=False` → lazy spawn on first use (no boot preload of TTS worker this run); ready 10:00:32 (~3.3min vs 11.2s baseline). Warm path verified audible turn-2 | Open Q: did boot preload regress, or is spawn latency pure env (torch import on slow fs)? Revisit post-smoke; restart below re-colds TTS — expect one silent turn again. 2nd datapoint: post-restart spawn→ready 52s (vs 3.3min) — env variance dominates, worker now warm |
| 2026-09-09 | F1 (P0.5 obs) | OBS — threads visible but not in linear date/time order; Tauri-version threads absent | `data/conversations.db` 483KB (9/7) is live file; strays exist `C:\dev\data\conversations.db` 250KB (8/9) + `backend\data\conversations.db` 20KB (7/28); backend `get_conversations()` sorts `(pinned, updated_at)` desc | User: Tauri-run threads should persist in all instances via conversation.db — suspected not wired. NOT a blocker (chat usable). Verify later: which DB Tauri writes, whether frontend re-sorts, whether `updated_at` bumps on new messages |
| 2026-09-09 | F2 (R1.1 pre) | OBS — model selection DESYNC: UI shows Qwen 3 27B / Cerebras, backend config `reasoning_model=gemma-4-31b` (invalid on Cerebras — likely the chatview billing error), kernel at boot had `gpt-oss:120b-cloud` (Ollama-style id, also invalid on Cerebras) | Boot 08:01:06 `Model selection updated: reasoning=gpt-oss:120b-cloud provider=cerebras`; NO `Model selection updated` after boot; 09:19 `[Config] moved persisted secret model_selection.api_key into keyring` (user key save landed); disk config now `gemma-4-31b` — something rewrote selection post-boot without a kernel update | BLOCKS all LLM smoke until resolved. EXACT billing text captured from frontend log: `Agent kernel error: Payment required to access this resource. Visit your billing tab.` (= provider HTTP 402 on the invalid model id). Next: B1 re-verify (re-select Qwen), then R1.1 retry |
| 2026-09-09 14:01 | MEM-PROBE (conv-98) ❌ FAIL — recall NOT tainted, tool-chain failed | Fresh kernel `conv-98` (new conversation, cerebras/qwen-3.8-27b); episodic join fired pre-plan (`Found 3 similar episodes` + `Found 2 similar failures` 13:58:32-34) → context-taint ruled OUT. Step 1 `list_conversations` (resolve 1456ms, dispatch 2624ms, returned 105 convs) never fetched card content — planner's 14:00:07 "both in hand" premise was false, verifier accepted `success=True` on wrong shape. Step 2 `crawler_query` 77751ms (GitHub README chrome dump ~15KB+ into context). Synthesis `infer` → `Empty response from API` ×4 (14:00:08/17/25/29) → sub_loop_split burned 3 retries → episode `f218d4b6` score 0.1, `failure_reason=None` (F5: no task:fail close event). `DER completed der_steps=3` 14:01:17. Turnaround ~171s: crawl 78s + failure loop ~70s + fallback report ~48s | Recall failure = tool selection + verifier gap, NOT memory. Synthesis empties = F11 signature on bloated context. Honest-failure reply rendered (presentational partial-pass on failure path) |
| 2026-09-09 14:01 | F7/F12 re-confirmed live (conv-98 card `card_17055ac2-b51`) | Card counter `[5/10]` vs plan `steps=3`: 10 rows = 3 plan steps + 7 runtime phase rows (SEARCH/EXTRACT/CITE/FAILED×3/READ appended after plan steps, T29 rule). Step 3 (combine) mislabeled SEARCH. RECALL row renders raw `list_conversations` JSON user-visible; SEARCH row renders raw page chrome; FAILED subs show internal resolver verdict text. Acceptance bar #2 (no raw JSON/tool payloads user-visible) = FAIL | Counter must count plan steps only (or rows show what counter counts); phase rows nest under parent step; card rows go through `_format_tool_result` envelope (F9 pattern) |
| 2026-09-09 17:40 | FIX BATCH session-312 (conv-98 findings) — applied, backend restarted PID 11020 | (1) C3: `list_conversations` envelope summary in `_format_tool_result` — "N conversation(s) with documents (index only — call get_rendered_documents(conversation_id=…)…)" replaces raw JSON on card rows AND in working memory (extends F9 branch). (2) P1: step-reasoning working memory capped 6000 chars (`_smart_excerpt`, explicit marker). (3) P3: ONE shrunk-context retry (1500-char excerpt) on Empty response before the `[step N completed]` placeholder — kills the 4-empty burn. (4) result_summary (300-char envelope excerpt) persisted per step in `_queue_steps_snapshot`; frontend hydration maps it to `resultPreview` (revisited cards show what each step found). (5) C1: counter counts SETTLED rows (done/fail/error/skipped) in `deriveProgress` + `deriveCurrentStep` — user-directed 2026-09-09; CT-GT-8 expectation updated 3→2 with decision cited. (6) Verb: `combin` → SYNTH (was SEARCH via /find/ in "findings"). (7) Visual (user-approved): header Xur static when settled (Xur speed≤0 = one frame); breathing ring /40→/60 + glow; phase rows indent pl-4; settled rows dim 0.75; faint amber 〰 glyph on the working row while `audio_envelope.phase==="speaking"` (new `iris:audio_phase` mirror); bounded per-row history (6 lines) in expand panel. | Checks: py_compile OK; twins 24 pass / 6 pre-existing `_FakeKernel._router` fails (identical to F9 clean-HEAD baseline); `tsc --noEmit` detached run completed zero-output (clean). MCM record_edit deferred — server dropped mid-session; re-record on commit |
| | | | | |

## 8. Blocker log (serious only — triggers STOP → fix → re-verify)

| Time | ID | Symptom | Logs / capture | Fix attempted | Re-verify |
|------|----|---------|----------------|---------------|-----------|
| 2026-09-09 | B3 (R1.2) KEY LIVE, watch narrowed | Cerebras key did NOT survive 1st restart (`missing_api_key`, re-entered 10:38) but DID survive 2nd restart (slot probe True post-boot, no re-entry) | Loss therefore 1st-restart-specific, not a general restart-wipes-key rule. Candidates: kill-mid-write timing, or a 24228-boot path that cleared it (scrub slot-mismatch?). No code change; do NOT restart mid-smoke to chase it | Re-APPLY (user action, 1st restart only) | KEY LIVE across 2nd restart. Revisit only if it recurs |
| 2026-09-09 | B5 ✅ CLOSED + VERIFIED in user flow | Vector: dashboard `POST /api/config/save` bursts with `api_key:""` hit the ONE unguarded writer (`main.py::api_config_save`). Fix: guard on non-empty + comment; contract 3/3; live sentinel probe on PID 31864 | VERIFIED LIVE on return: user APPLY → dashboard open/close → new conversation → key STILL set (slot probe True). Exact flow that used to kill it. B3's 1st-restart loss explained by same vector | Done — no further action unless a new loss appears |
| 2026-09-09 | B4 ✅ CLOSED — verifier proven live end-to-end | conv-97: `[SemanticVerifier] default encoder reuses shared EmbeddingService (backend=lfm25-emb-350m)` 13:07:46 (semantic path, not fallback) → `_split_step trigger=verify_failed` 13:09:27 (honest fail of step 3) → split into 1 sub-loop (41 work units) → episodic memory joined (`Found 5 similar episodes`) → turn completed with X + truthful failure report. The DER loop worked EXACTLY as specced under adversity | B2 (`importlib.util`) + B4 (`os`) one-liners | Done. Card showed X + 5/8 honestly; user notes the failure report could have been plain text (card-vs-text routing question, open) |
| 2026-09-09 | B2 (R1.2) | Chat wedged: follow-up `What tools...` sent as `steer` into dead conv-92 turn, queued never consumed; user sees stuck-on-last-prompt | `steer` seq 33 conv-92 queued 14:13:06, zero consumption after; trigger = F4 importlib NameError killing DER with no close event | FIXED 2026-09-09: `backend/agent/verifier.py:34` += `import importlib.util` (one-liner, py_compile OK). Requires backend restart (running process caches old module; also clears wedged steer queue) | NEW conversation → `What tools...` → DER completes past verify → `task:start/tool:call/tool:result` sequence (SUPERSEDED by B4: fix was incomplete, same function next line) |
| 2026-09-09 | B1 (R1.4) ✅ CLOSED | Model & Inference → mode-routing dropdown reverted on select | Root cause: `sendMessage` checked per-instance `wsRef`; `connect()` early-returns for shared-socket adopters without assigning it → inference-instance sends queued forever. `set_role_binding` count was 0 all session | FIXED: `hooks/useIRISWebSocket.ts` falls back to shared `_sharedWs` (recompiled 3.3s, `GET / 200`). Jest harness hangs in this env (re-run post-smoke) | VERIFIED LIVE 09:50: `set_role_binding reasoning+tool_execution instance=cerebras model_override=qwen-3.8-27b outcome=ok` (seq 14/15, explicit-gesture). User: dropdown holds (slight delay on first switch — likely stale-queue flush + WS/REST round-trip, non-blocking) |
| | | | | | |

---
## 9. Pre-existing (do NOT file as regressions)

- `backend/agent/verifier.py` uses `importlib.util` without importing it — DER file turns error; lanes speak the error correctly. One-liner, out of smoke scope.
- `test_der_phase1::test_single_authority` stale assertion (absent at HEAD).
- `voice_pipeline` stale paths / stale VAD asserts / stale sounddevice mock + 2 headless hangs deselected (`TestAudioLevelCallback::test_audio_level_callback_fires_during_vad` + one more).
- Empty-URL `dispatch_urls` KeyError when registry empty (noted, untouched); retry-round real-title observation (T40 follow-up); TTS residual ~7MB/synth (MKL fast-MM off, −72%, bounded by idle-unload; literal gate still red).
- Regression baselines (session-310, post-54381309): contract 1478–1485 pass / 30 pre-existing fail (1 = episodic-store isolation artifact passing solo); audio 252/7 pre-existing; barge solo 40/40; voice_pipeline 99 pass / 10F+2E subset-of-pre; vision 275 pass / 2–3 pre-existing.

## 10. Acceptance bar (USER-LOCKED 2026-09-09 — overrides any earlier looser reading)

A `pass` requires ALL three, not just function:

1. **Functional** — the turn completes through the real path (plan → execute → verify → reply) with no missing-key starvation, no NameError-class crash, no wedge requiring a new conversation or restart.
2. **Presentational** — a non-technical user can read the result: no raw JSON/tool payloads anywhere user-visible, tables fit their card at normal widths, follow-ups and questions render OUTSIDE result cards as chat, progress steps track linearly (pending → working → done, no late flips, no yo-yo counter), the working indicator never spills its lane.
3. **Timing** — end-to-end websearch in a time a user would tolerate. Baseline 5–7 min REJECTED by user. Breakdown first (crawl legs serial? synthesis context bloat?), then agree the target with the user before claiming pass.

Explicit corrections to earlier claims: model switching is NOT working (key dies around dashboard use); task cards are NOT working (steps don't track); memory is UNPROVEN until a live recall is demonstrated (not just a memory-record line in logs); honest failure text does not excuse the slowness that produced it.

## 11. Run state

- Current phase: SESSION 312 — fix batch applied (backend restarted PID 11020), awaiting live re-verify of the memory probe
- Last green item: fix batch checks green (py_compile, twins 24/6-pre-existing, tsc clean); conv-98 findings recorded in §7
- Active blocker (§8 row): none
- Model binding this run: cerebras / `qwen-3.8-27b` (reasoning + tool_execution, explicit-gesture, outcome=ok)
- Backend log this run: `.iris-logs/` (PID 11020, restarted 17:40 for the session-312 batch; priors 123105 PID 12692 [F9], 121621 PID 31864 [B5 fix], 105926 PID 31084, 101810 PID 24228, 075925 PID 22876)
- Frontend log this run: `.iris-logs/frontend-20260909-075940.log` (PID 29988 — TSX changes hot-recompile on next page load)
- Launcher log this run: `.iris-logs/launcher-20260909-082236.log` (PID 3600)
- Screenshots: `screenshots/` (timestamped, never repo root)
