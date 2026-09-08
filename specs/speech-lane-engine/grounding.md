# T11 Grounding Table — REQ-10 (Wave 4) Phase -1 gate

Every function / class / WS-message-type the Wave 4 spec names, with file:line
evidence. Status is one of EXISTS / DOES NOT EXIST (names the creating task).
Two BLUEPRINT-DIVERGENT rows change Wave 4 scope — read them first.

## Divergences (scope-changing — resolve before T12/T13/T15)

| # | Spec assumption | Reality | Consequence |
|---|---|---|---|
| D1 | "Timeout extend" is a wait-state trigger alongside start/timeout/complete (OQ-5 scope) | **DOES NOT EXIST — and none is built.** No extend/prolong mechanism anywhere in `backend/agent/` (zero hits). The user-visible behavior ("taking longer than stated") is a beat REVISION through the T13 amendment API (REPLACE), plus the expectation-miss reactive line against the stated budget. A timeout-extension policy engine would be over-build for a narration sentence. | Drop "extend" from AC10.11 triggers; revised expectations route through beat revision. No new machinery. Owned by T13. |
| D2 | "The narration toggle rides the existing settings path" (no new plumbing) | **HALF-BUILT.** Transport exists: frontend sends `settings_sync` with a settings dict (iris_gateway.py:5463). Application does NOT: the re-apply loop body is literally `pass` (iris_gateway.py:5470-5472), and no pending-settings store exists anywhere (searched `pending_settings`, `apply_settings` — only the dead loop). The "re-applied on next process_text_message" comment is aspirational. | T15 scope grows by one minimal item: implement the kernel-side apply for (at least) the narration key. Transport + TTS-config precedent (data/iris_config.json persist at iris_gateway.py:1373) are reused; no new WS shape. |

## Plan segments (T12 beat authoring)

| Symbol the spec will name | Status | Evidence |
|---|---|---|
| `ExecutionPlan` (plan container) | EXISTS | core_models.py:732 — plan_id, original_task, strategy, reasoning, steps, outcome, plan_title |
| `PlanStep` (plan segment ≈ narration beat source) | EXISTS | core_models.py:711 — step_id, step_number, description, status, tool, params, depends_on, critical, result, failure_reason, duration_ms, expected_output |
| `StepStatus` (segment lifecycle) | EXISTS | core_models.py:700 — pending/running/completed/failed/skipped/blocked |
| `AgentKernel._plan_task()` (first writer) | EXISTS | agent_kernel.py:5503 — returns ExecutionPlan; called with up-to-3 attempts at agent_kernel.py:6346 |
| Planning prompt schema (where beats field lands) | EXISTS | agent_kernel.py:5638-5640 — JSON schema with `plan_title` + `steps[]` |
| `_parse_planner_json` (where beats parse lands) | EXISTS | agent_kernel.py:5368 — prefers objects with steps/plan_title; materialized at 5730-5763 |
| `ExecutionPlan.beats` / prompt `beats` key | DOES NOT EXIST | Created by **T12** (one JSON key in prompt schema + parse + dataclass field). No other planner-output field may be repurposed. |

## Tool-execution wait states (T13 triggers)

| Symbol the spec will name | Status | Evidence |
|---|---|---|
| Wait entry (tool start) | EXISTS | `IRISStreamEvent.TOOL_CALL` = "tool:call" (event_bus.py:100), emitted agent_kernel.py:8165 (+ resolved re-emit 12033) |
| Wait exit (tool complete) | EXISTS | `IRISStreamEvent.TOOL_RESULT` = "tool:result" (event_bus.py:101), emitted agent_kernel.py:12792 |
| Wait timeout (tool budget) | EXISTS | tool_bridge.py:933-941 — 60s vision/gui_automation, 30s everything else; error string "Tool '{name}' timed out after {s}s" |
| Wait timeout (step turn-budget) | EXISTS | agent_kernel.py:8272 ("[STEP TIMEOUT: turn budget exhausted before step start]"), :8305 ("[STEP TIMEOUT: step exceeded the remaining turn budget]") inside `_execute_plan_der` (:7434) |
| Wait extend | DOES NOT EXIST | See D1 — deliberately not created; expectation-miss uses stated budgets |
| Step entry/exit (segment granularity) | EXISTS | `PlanStep.status` transitions inside `_execute_plan_der` (agent_kernel.py:7434) |

## Filler gap-filler exception (T13/T16)

| Symbol the spec will name | Status | Evidence |
|---|---|---|
| Thinking-feedback filler emit | EXISTS | agent_kernel.py:6233-6250 — fire-and-forget `get_speak_tool().speak(random.choice(_fillers), priority="low")` at DER entry; 4 canned phrases (spec said 6242-6250; emit site is 6233-6250) |
| `SpeakTool.speak` caps | EXISTS | tools/speak_tool.py:30 MAX_TEXT_CHARS=500, :32 _PENDING_WINDOW=10.0s rate limit, :138-139 rate_limited status |
| `FILLER_PHRASES` + pre-synth cache | EXISTS | tts.py:845 FILLER_PHRASES, :853 `_pre_synthesize_fillers`, :872 `get_filler_audio` random cached wav (spec said 835-868; actual 845-897) |
| Consecutive-repeat guard | DOES NOT EXIST | Created by **T13** (AC10.13: never same phrase twice; subsumed on beat arrival via REQ-4) |

## Narration toggle path (T15)

| Symbol the spec will name | Status | Evidence |
|---|---|---|
| `settings_sync` transport | EXISTS | iris_gateway.py:5463-5468 — frontend settings dict arrives over existing WS |
| Kernel-side settings apply | DOES NOT EXIST (stub) | iris_gateway.py:5470-5472 loop body is `pass` — see D2. Created by **T15** (apply at least the narration key; reuse TTS-config persist precedent iris_gateway.py:1373) |
| Scheduler admission check | DOES NOT EXIST | Created by **T15** (narration-off drops beats at admission, logged + counted; in-flight pre-synth aborted, buffers freed) |

## Awaiting lane surfaces, OQ-2 (T13 re-announce targets)

| Symbol the spec will name | Status | Evidence |
|---|---|---|
| Question state → QuestionCard | EXISTS | components/chat/QuestionCard.tsx:59; `question_response` funnel (chat-view.tsx:4484); `question:ask` event; AskUserTool ASK_USER_QUESTION_TIMEOUT=120 (tools/ask_user_tool.py:33) |
| Approval state → PermissionCard | EXISTS | components/chat/PermissionCard.tsx:74; permission system backend/agent/permissions.py (120s/180s timeouts) |
| Takeover state → takeover banner | EXISTS | `BROWSER_TAKEOVER_REQUESTED` = "browser:takeover_requested" (event_bus.py:151) → `iris:browser_takeover_requested` → BrowserNavigationOverlay banner (components/iris/browser/BrowserNavigationOverlay.tsx:379-386, 1781-1803), fed via navOverlay.takeover (dark-glass-dashboard.tsx:2097) |
| No new awaiting UI | — | Locked: the lane reuses the three surfaces above (OQ-2 decision) |

## Instruments for tuning (feeds OQ-1/OQ-2; recommendation in handoff pin)

Existing REQ-9 counters (speech_lanes.py observability, proven live in T10):
`hierarchy:*`, `unlisted_type:*`, `preemption`, `subsumption`, `node:*`
plus ShadowObserver divergence logs.

| Proposed instrument | Source | Status |
|---|---|---|
| barge-ins-during-narration | `record_preemption(detail="barge-in")` log lines | EXISTS (derive in review, no code) |
| spoken-vs-cancelled | `node:done` vs `node:cancelled` counters | EXISTS |
| shadow divergences | ShadowObserver logs | EXISTS |
| merge rate | burst-merge event | Created by **T13** with the merge mechanism (counter, not infra) |
| pre-synth hit/waste | held-buffer outcomes | Specified by D13 invariants, created by **T14** |
| toggle flips + drops | admission-drop counter | Specified by AC10.14, created by **T15** |
| expectation-miss freq | wait crossing stated budget | Created by **T13** with wait triggers (counter, not infra) |
| subjective live-rating protocol | human sessions | **Recommend DEFER** — counters answer the tuning questions (which roads shape badly, which waits miss, what gets subsumed); rating is expensive and uncalibrated. Revisit only if OQ-1/OQ-2 stay open after one counter review. |

## Verdict

Zero BLUEPRINT-DIVERGENT rows remain unhandled: D1 narrows AC10.11 (T13), D2 grows
T15 by one apply item. Every other Wave 4 symbol is EXISTS with file:line, or
names its creating task. T12/T13/T15 file targets are determined — T11 complete.
