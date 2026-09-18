# Tasks: Vision–Browser E2E Reliability & Performance

> Each task links to a requirement. Grouped into waves for parallel execution.
> Per-task RIPPLE notes name the other areas the task touches or relies on.

## Wave 1 — Foundation (serving + contracts)

- [x] T1 (REQ-1): Route browser vision consumers through `resolve_vision_client()`
      — `backend/vision/fetch_vision.py`, `backend/vision/search_discovery.py` —
      RIPPLE: preserve method surface used by `SessionVisionAdapter`; do not touch
      tier-3 lease semantics; extend the AST bypass scan in
      `test_no_direct_lfm_vl_provider_bypass.py` to cover `backend/vision/`.
      **ALSO IN SCOPE (audit 2026-09-18 — F2, which had no AC and no task and would
      otherwise have been dropped):** the fallback path in `search_discovery.py`
      calls the provider SYNCHRONOUSLY inside an async function
      (`prov.read_text(img)` `:484`, `prov.analyze_screen(...)` `:486`). That blocks
      the event loop for every concurrent task (WS, audio, other crawls), so it
      must move off the loop the way `fetch_vision` already does
      (`asyncio.to_thread`). RIPPLE: this is the same consumer T1 already touches;
      it is the F2 defect from the audit, recorded here because REQ-1's ACs cover
      the resolver, not the blocking call.
      **SCAN CONSTRAINT (Decision 17 + OQ-18):** the scan runs in DEVELOPER MODE
      only, and must allowlist the lifecycle/health sites
      (`backend/iris_gateway.py:10907-10909`, `:10972-10976`,
      `backend/inference_router.py:318-319`) or it fails on legitimate code.
- [x] T2 (REQ-2): Define the resolvable-target + separate-value action contract in
      BOTH prompts — `backend/tools/lfm_vl_provider.py`, `backend/agent/inference/router.py` —
      RIPPLE: `fetch_vision._map_action` parsing; `VisionAction.value`;
      `action_allowlist` role/name vocabulary (NO CHANGE, reuse it).
- [x] T3 (REQ-6): Make `tool_bridge._UI_EVENT_DEFAULTS` the single canonical vision
      event shape and forward it whole from BOTH forwarders —
      `backend/agent/tool_bridge.py`, `backend/iris_gateway.py` —
      RIPPLE: `ux_map.py` msg_type lock; `orchestrator._on_action` contract lock;
      `test_vision_action_fields_reach_the_panel.py` becomes the guard; add seq.
- [x] T4 (REQ-8, REQ-10): Add run-scoped per-stage timing + tuning signals —
      `backend/vision/browser_session.py`, `backend/vision/fetch_vision.py` —
      RIPPLE: off critical path; consumable by `scripts/measure_vision_latency.py`.

## Wave 2 — Loop quality (backend behavior)

- [ ] T20 (REQ-18): Browser warm-path bound + cold-launch accounting — record
      cold/warm per run, hold warmth for a run, announce a cold launch, keep the
      launch out of the action budget, bound the acquire and fail open —
      `backend/vision/browser_pool.py`, `backend/vision/browser_session.py`,
      `backend/crawler/orchestrator.py` (prewarm `:1779`),
      `backend/agent/tools/screenshot_page_tool.py` (the 4th browser path) —
      RIPPLE: pool idle-lease semantics are CONTRACT-LOCKED
      (`test_browser_pool_contract.py:251-293`) — do not change them, add the
      accounting ON TOP; the plan-time prewarm currently has NO test and MUST gain
      one; a BORROWED tier-3 server is never idle-stopped (REQ-1 AC4); the
      latency NUMBER stays UNVERIFIED until the step-10 baseline (Decision 13).

- [ ] T5 (REQ-3): Feed the `ActionTrajectory` window + no-repeat constraint into
      `_suggest_action` — `backend/vision/fetch_vision.py` —
      RIPPLE: `ActionTrajectory.window_steps`; fallback to baseline prompt on
      format failure; no change to prompt semantics for tier 1/2 beyond the same
      contract (shared with T2).
- [ ] T6 (REQ-4): Replace repeat-kind termination with measured progress
      termination — `backend/vision/fetch_vision.py` —
      RIPPLE: `visual_delta` reuse; `_step_is_no_progress`; keep hard bounds.
- [ ] T7 (REQ-9): Single observation per settled state shared across triage,
      extraction, and suggestion — `backend/vision/session_vision_adapter.py`,
      `backend/vision/frame_extraction.py`, `backend/vision/fetch_vision.py` —
      RIPPLE: `_publish_frame` dedupe already exists (reuse); changed-frame always
      fresh; `VisionProvider` protocol surface unchanged.
- [ ] T8 (REQ-2): Bounded description→handle resolution fallback —
      `backend/vision/browser_session.py` `act()` —
      RIPPLE: `last_error` observation semantics; allowlist vocabulary;
      no change to `browser_pool`.

## Wave 3 — Frontend reflection (REQ-7)

- [ ] T9 (REQ-7): Consume seq + canonical fields; absolute-scroll mirror and
      action/step/total — `hooks/useBrowserNavOverlay.ts`, `hooks/useIRISWebSocket.ts`,
      `hooks/useCrawlSSE.ts` —
      RIPPLE: `useViewProtocol` (NO CHANGE); `VisionLifecycleChip` (NO CHANGE);
      `dark-glass-dashboard` scroll effect keyed on seq.
- [ ] T10 — SUPERSEDED (2026-09-17 amendment). The takeover work is decomposed into
      Wave 4 (T15–T19). T10 is kept as a tombstone so the old number does not
      silently change meaning. Its premise ("wire takeover to the real session")
      was already FALSE: the request/answer/verify/resume path exists
      (`browser_session.request_takeover` `:1017`, `ask_browser_takeover`
      `ask_user_tool.py:499`, `question_response` -> `backend/iris_gateway.py:6220-6246`,
      wall re-check `:1080`). What was missing is the TRANSPORT (see design D5).
      Evidence: `pin_019a9210d073`.
      RIPPLE: none — NO CODE CHANGE. This is a tombstone so the old number does not
      silently change meaning; the work it described is T15–T19.

## Wave 4 — Live takeover (CDP screencast)

> New wave (2026-09-17 amendment). The spec's completion now depends on protocol
> work (owner decision: include CDP in this spec).
> **GATE CLEARED 2026-09-17:** the owner authorised the
> `specs/vision-browser-stage` REQ-14 amendment, and the narrowed guards
> CT-6b/CT-7b are owned THERE as that spec's **T25**. T17/T19 CONSUME that guard.
> Do NOT delete or weaken CT-6/CT-7. Evidence: `pin_54db2ac956a0`.

- [ ] T15 (REQ-13): CDP screencast transport — start/stop, ack pacing, bounded
      in-flight frames, degrade on CDP failure — `backend/vision/cdp_takeover.py`
      (NEW), `backend/vision/browser_session.py` —
      RIPPLE: keep `browser_session.py` free of `FastAPI`/`WebSocket`/`APIRouter`
      strings (CT-7 fails on a comment too); publish frames through the event bus,
      never through a route; the `request_takeover` seam (`:1017`) is the mount
      point; stop on close/timeout/cancel (`:1073-1097`).
- [ ] T16 (REQ-16): Frame envelope + delivery bounds + panel renderer —
      `backend/agent/event_bus.py`, `backend/agent/ws_event_bridge.py`,
      `hooks/useIRISWebSocket.ts`, `hooks/useBrowserNavOverlay.ts`,
      `components/iris/browser/BrowserNavigationOverlay.tsx` —
      RIPPLE: frames ride the WS channel ONLY (SSE is NOT extended — the capture/
      proxy surface stays untouched); `capture_store` (NO CHANGE — frames are not
      captures); `browser_surface` (NO CHANGE); `VisionLifecycleChip` (NO CHANGE);
      latest-wins drop with a dropped counter; OQ-10/OQ-11 decide encoding + rate.
- [ ] T17 (REQ-14): Takeover grant + input forwarding (grant-gated, page-scoped,
      ephemeral) — `backend/vision/cdp_takeover.py`, `backend/iris_gateway.py`,
      `hooks/useIRISWebSocket.ts`, `components/iris/browser/BrowserNavigationOverlay.tsx` —
      RIPPLE: the inbound branch is a sibling of `question_response`
      (`backend/iris_gateway.py:6220`), NOT a replacement; the answer funnel stays unchanged;
      the capture surface must keep the root `pointer-events-none` and must not add
      `<button`/`<input`/`<a href` (CT-6); the typed value never reaches memory,
      ledger, logs, or a frame echo; the narrowed guards are that spec's T25
      (GATE CLEARED 2026-09-17 — CONSUME, do not re-own).
- [ ] T18 (REQ-15): Loop suspension + ownership handoff + release paths —
      `backend/vision/fetch_vision.py`, `backend/vision/browser_session.py`,
      `backend/vision/cdp_takeover.py` —
      RIPPLE: keep the inline await (`fetch_vision.py:340-348`) as the suspension
      point; no model call and no DOM action while the grant is open; wall re-check
      before resume (existing `:1080`); cancellation releases the vision lease and
      the browser context (no orphan Chromium).
- [ ] T19 (REQ-13–REQ-16): Takeover contract + behavioral tests + harness extension —
      `backend/tests/contract/`, `backend/tests/behavioral/`,
      `scripts/validate_vision_browser_e2e.py` —
      RIPPLE: pin frame envelope + monotonic `frame_seq`, input allowlist shape,
      grant gating (no input without a grant), loop-suspension behavior, frame stop
      at terminal; CONSUME `test_takeover_input_authority_contract.py` (CT-6b/CT-7b,
      owned by vision-browser-stage T25); CT-6/CT-7 stay untouched.
- [ ] T23 (REQ-14 AC5/AC6): Credential application WITHOUT exposure — the system
      applies a keyring secret to a session field under an open grant, with
      explicit user authorisation and a value-free audit record —
      `backend/vision/cdp_takeover.py`, `backend/vision/browser_session.py`,
      `backend/agent/inference/keyring.py`, `backend/agent/tools/ask_user_tool.py` —
      RIPPLE: the value must NOT enter the model context, memory, the ledger, the
      event stream, or any log — including the prompt-assembly path, so this must
      bypass the agent's normal tool chain rather than ride it; the frame stream
      shows only the page's own (masked) rendering; a host with no keyring entry
      degrades to the manual takeover; never try several secrets (account lockout).
      Shares the REQ-14 grant with T17 — do not build a second grant mechanism.
- [ ] T24 (REQ-15 AC5/AC6): Post-takeover continuation — the revocable consent
      affordance for persisting session cookies, and off-domain continuation with
      an `AskUserQuestion` escalation when the agent cannot safely resume —
      `backend/vision/cdp_takeover.py`, `backend/vision/browser_session.py`,
      `backend/agent/tools/ask_user_tool.py`,
      `components/iris/browser/BrowserNavigationOverlay.tsx`,
      `components/chat/QuestionCard.tsx` —
      RIPPLE: nothing is persisted without consent (no silent keyring write);
      the consent prompt must NAME the host and what will be stored and be
      revocable; a domain change must NOT auto-park, and the guardrail
      re-evaluation must not silently proceed when it would block — it asks.

## Wave 5 — Verification

- [ ] T11 (REQ-1–REQ-11): contract tests —
      `backend/tests/contract/` — RIPPLE: CT-1 (canonical event shape),
      CT-2 (takeover REQUEST/RESPONSE shape — the ask/resume contract, NOT the new
      transport pins), CT-3 (orchestrator `_on_action` lock),
      CT-4 (ux_map msg_type lock), CT-5 (pool corpse self-heal — REQ-11),
      extended AST scan. The REQ-13–REQ-16 transport pins live in T19.
- [ ] T12 (REQ-3, REQ-4, REQ-9): behavioral tests with fake session+provider —
      `backend/tests/behavioral/` — RIPPLE: assert one inference per settled state,
      trajectory present, long scroll session not stopped, takeover resume.
      T19 adds the loop-suspension and frame-stop behaviors.
- [ ] T13 (REQ-8, REQ-13–REQ-16): standing CDD harness + live measurement —
      `scripts/validate_vision_browser_e2e.py`, `scripts/measure_vision_latency.py` —
      RIPPLE: reuse recorded trajectories; assert the takeover frame/grant
      invariants on every run; set latency targets AFTER baseline.
- [ ] T14 (REQ-1–REQ-18): execute the dated Verification Plan (design.md) steps
      1–11 against the running system — RIPPLE: requires frontend listener on
      `:3000`; record PASS/FAIL per step; no step inferred from a unit test.
      Steps 7–9 are the live takeover gates. Step 11 is the agent gate.
- [ ] T21 (REQ-17 AC1/AC2/AC4): Agent-driveable harness — loopback fixture pages
      (incl. a wall page), the bounded run-scoped JSONL event journal, and the
      headless exit-code gate — `scripts/fixtures/vision_pages/` (NEW),
      `backend/vision/run_journal.py` (NEW),
      `scripts/validate_vision_browser_e2e.py` — RIPPLE: journal writes must be
      off the critical path and bounded (never fail a run); the journal must not
      duplicate the capture/proxy surface; the gate must NAME the offending
      invariant on failure.
- [ ] T22 (REQ-17 AC3): Trajectory recorder + replayed corpus —
      `scripts/record_vision_trajectory.py` (NEW), `tests/vision_traces/` (NEW) —
      RIPPLE: T13 can only "reuse recorded trajectories" once this exists, so T13
      DEPENDS on T22; mirror `validate_websearch_trajectory.py`'s redacted
      schema-v1 shape; never commit a corpus containing a real page's PII or a
      session cookie.

## Traceability Matrix (MANDATORY)

| REQ | ACs | Covering tasks | Covering tests | Status |
|---|---|---|---|---|
| REQ-1 | AC1.1–1.4 | T1 | extended AST scan (T11), `test_no_direct_lfm_vl_provider_bypass.py` | covered |
| REQ-2 | AC2.1–2.4 | T2, T8 | behavioral action-resolution (T12), unit parser (T11) | covered |
| REQ-3 | AC3.1–3.4 | T5 | behavioral trajectory-in-prompt (T12), unit window (T11) | covered |
| REQ-4 | AC4.1–4.4 | T6 | behavioral long-scroll-not-stopped (T12), unit predicate (T11) | covered |
| REQ-5 | AC5.1–5.4 | T15–T19 (T10 superseded) | CT-2 ask/resume shape (T11), behavioral takeover resume (T12/T19), plan steps 7–9 (T14) | covered (transport amended 2026-09-17; ask/resume path already exists — `pin_019a9210d073`) |
| REQ-6 | AC6.1–6.4 | T3 | CT-1 canonical shape (T11), `test_vision_action_fields_reach_the_panel.py` | covered |
| REQ-7 | AC7.1–7.4 | T9 | behavioral panel state (T12), plan step 6 (T14) | covered |
| REQ-8 | AC8.1–8.4 | T4 | `measure_vision_latency.py` live gate (T13), plan step 10 (T14) | covered |
| REQ-9 | AC9.1–9.4 | T7 | behavioral one-inference-per-state (T12) | covered |
| REQ-10 | AC10.1–10.3 | T4 | tuning-signal assertions (T13) | covered |
| REQ-11 | AC11.1–11.4 | T11 (CT-5, contract-lock only — no code change) | pool corpse restart (existing `test_browser_pool_contract.py:184`) + NEW CT-5 for session-level retry | covered |
| REQ-12 | — (cross-spec, ZERO ACs here) | none — OWNED by `specs/vision-goal-directed-search` REQ-12 (T8 `[x]`) | that spec's AC12 suites | consumed, not restated |
| REQ-13 | AC13.1–13.4 | T15, T19 | frame envelope + screencast lifecycle pins (T19), plan step 7 (T14) | covered |
| REQ-14 | AC14.1–14.6 | T17, T19, T23 | grant-gating + input allowlist shape pins (T19), credential-used-not-seen pins (T23), narrowed non-interference guard (T19), plan step 8 (T14) | covered |
| REQ-15 | AC15.1–15.6 | T18, T19, T24 | loop-suspension behavior + release-on-cancel (T19), revocable consent affordance + off-domain continuation with ask-on-unsure (T24), plan steps 8–9 (T14) | covered |
| REQ-16 | AC16.1–16.4 | T16, T19 | frame envelope + monotonic `frame_seq` + dropped-count pins (T19), plan step 7 (T14) | covered |
| REQ-17 | AC17.1–17.4 | T21, T22 | fixture + bounded journal + exit-code gate pins (T21), corpus replay (T22), plan step 11 (T14) | covered |
| REQ-18 | AC18.1–18.4 | T20 | cold/warm accounting + prewarm test + hard-bound fail-open pins (T20), plan step 10 baseline (T14) | covered |

Counts: ACs counted = 71. Arithmetic: REQ-1..REQ-9 × 4 = 36, REQ-10 × 3 = 3,
REQ-11 × 4 = 4 (subtotal 43, unchanged), plus the takeover amendment
REQ-13..REQ-16 × 4 = 16 (subtotal 59), plus the verification/warm-path amendment
REQ-17 × 4 = 4 and REQ-18 × 4 = 4 (subtotal 67), plus the 2026-09-18 answer
amendment: REQ-14 AC5/AC6 (+2) and REQ-15 AC5/AC6 (+2) → 43 + 16 + 8 + 4 = **71**.
REQ-12 contributes ZERO ACs to this count (cross-spec reference; its ACs are
counted by the spec that owns it). REQ-1 AC4 and AC1/AC2 were AMENDED without
changing the AC count.
Covered = 71. Deferred = 0. Unmapped = 0.
(Historical: "Audit #1 corrected 38→39; the REQ-11 amendment raised the total to 43
in the SAME edit pass per the triplet rule.")

## Wave gates (MANDATORY — no wave starts on a red gate)

- [ ] TG-1 (Wave 1): re-run every covering test for REQ-1, REQ-2, REQ-6, REQ-8,
      REQ-10 named in the matrix; record green/red per AC. The extended AST scan
      MUST be green before Wave 2 starts.
- [ ] TG-2 (Wave 2): re-run covering tests for REQ-3, REQ-4, REQ-9, REQ-18; the
      long-scroll-not-stopped behavioral test MUST be green, and the cold/warm
      acquire accounting, the prewarm test, and the hard-bound fail-open test MUST
      be green.
- [ ] TG-3 (Wave 3): re-run covering tests for REQ-7; the seq-keyed mirror and
      late-event-rejection tests MUST be green. (REQ-5/REQ-13–REQ-16 moved to TG-4
      under the 2026-09-17 amendment.)
- [ ] TG-4 (Wave 4): re-run covering tests for REQ-5, REQ-13, REQ-14, REQ-15,
      REQ-16; the loop-suspension, grant-gating, and takeover-resume tests MUST be
      green, and so MUST the credential-used-not-seen test (T23) and the
      consent-affordance / off-domain-continuation tests (T24). GATE PRECONDITION
      (SATISFIED 2026-09-17): the
      `specs/vision-browser-stage` REQ-14 amendment is recorded, and its **T25**
      owns the narrowed guards CT-6b/CT-7b. TG-4 additionally requires T25 green
      (`pin_54db2ac956a0`).
- [ ] TG-5 (Wave 5): execute the dated Verification Plan steps 1–11; every step
      recorded PASS/FAIL. REQ-8 targets are set only from the step-10 baseline.
      Steps 7–9 are the live takeover gates. Step 11 is the agent gate, which
      REQUIRES T21 green; T13 REQUIRES T22's corpus, without which it has nothing
      to replay.
      REQ-17 covering tests: T21, T22. The gate MUST exit non-zero and NAME the
      offending invariant.

## Dependency / parallelization notes

- Wave 1 T1–T3 are independent of each other; T4 is independent of all.
- T5/T6 depend on T2 (the prompt/parse contract) for a coherent suggestion shape.
- T7 is backend-only and can run in parallel with T9 (frontend).
- T10 depends on OQ-1 (takeover UX decision) — RESOLVED 2026-09-17; T10 is a
  tombstone and its work is T15–T19.
- Wave 4 ordering: T15 (transport) gates T16/T17/T18; T19 tests T15–T18.
  T16 can start on the envelope shape while T15 finishes the pump.
- Wave 4 T17/T19 DEPEND on `specs/vision-browser-stage` **T25** (CT-6b/CT-7b) being
  green. The amendment authority is CLEARED (owner-authorised 2026-09-17); what
  remains is the test gate. T15/T16/T18 do not depend on it.
- T23 shares the REQ-14 grant with T17 — one grant mechanism, not two.
- T24 depends on T18 (the handoff must exist before post-takeover continuation).
- T1 is UNBLOCKED (OQ-20 RESOLVED 2026-09-18): cloud wins when the brain has
  vision; the local vision model is the fallback. T1's scan must respect Decision
  17 (DEVELOPER MODE only) and OQ-18's lifecycle/health allowlist.
- Wave 4 can overlap Wave 3 (T9): different files, and the takeover stream is a
  separate contract from the vision-action shape (Decision 11).
- T20 is independent of everything and can run in Wave 2 (backend-only).
- T21/T22 (the harness) SHOULD land before T13/T14. T13 depends on T22's corpus —
  without it T13 has nothing to replay — and T14 step 11 depends on T21.
- T1 is BLOCKED by OQ-18 (scan scope rule) and OQ-19 (tier-3 borrow-first). T1
  must NOT widen the AST scan before OQ-18 is answered, or it fails on legitimate
  lifecycle/health code and gets disabled.
- T20 is partially gated by OQ-19: the accounting is safe to build now, but the
  borrow-vs-spawn preference it reports on is OQ-19's answer.
- AMENDED SPEC CROSS-REFERENCE (do not duplicate): `specs/vision-goal-directed-search`
  already OWNS the pieces this amendment consumes — REQ-10 (takeover ask/resume,
  T11/T19 `[x]`), REQ-12 (keyring cookies, T8 `[x]`), and `specs/vision-goal-directed-search`
  REQ-20 (TaskGuardrails before ActionAllowlist) — NOTE: every REQ number in this
  bullet is THAT spec's numbering, not this one's — and T7 of that spec (ActionTrajectory capability `[x]`; this
  spec's REQ-3 is the missing WIRING into `_suggest_action`).
- AUTHORITY BOUNDARY: the `specs/vision-browser-stage` amendment was performed
  THERE under explicit owner instruction (2026-09-17). Its **T14 text and CT-6/CT-7
  are UNTOUCHED**, and the new guard lives in a NEW file. This spec's T19 CONSUMES
  that guard file and must not re-own, duplicate, or edit it
  (`pin_54db2ac956a0`).
- NO-CHANGE-verified areas that only need a contract test: `action_allowlist.py`,
  `browser_pool.py`, `capture_store.py`, `browser_surface.py`,
  `useViewProtocol.ts`, `VisionLifecycleChip.tsx`, `AmbientCrawlTier.tsx`.
- CONTRACT-LOCK areas (behavior unchanged, interface pinned): `ux_map.py`,
  `orchestrator._on_action`, `crawl_stream.py` SSE shape,
  `test_non_interference_contract.py` CT-6/CT-7 (narrowed by ADDING a guard, never
  by editing those two).
- CONSTRAINT FROM CT-7 (applies to every Wave 4 task): `backend/vision/browser_session.py`
  must contain NONE of `APIRouter`, `@app.`, `WebSocket`, `add_api_route`, `FastAPI`
  — a mention in a COMMENT also fails the guard — and no frontend file may contain
  the substring `browser_session`.
