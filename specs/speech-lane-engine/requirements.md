# Requirements: Speech Lane Engine

## Decisions Locked

- Lane scheduler, NOT a DAG (2026-09-07): no join ("wait for TWO things") exists in speech coordination — all relations are serialize / preempt / subsume / chain. Revisit only if someone names a join (the join test).
- No reuse of CaduceanPhaseManager (2026-09-07): it is inference admission control (quota/oscillator physics), not workflow orchestration. Borrow lane/gate vocabulary only.
- Model declares WHAT, engine decides HOW/WHEN (2026-09-07): lane assignment is a deterministic function of situation, never a per-turn model choice. The agent's scheduling authority ends at the speak/show intent declaration.
- Migration is strangler, not rewrite (2026-09-07): shadow-mode observer first, cut over narration → play → replies, flags die last as derived views.
- Alert lanes: Critical + Awaiting-user (user-locked 2026-09-07).
- Barge-in kills running + pending speech; the new turn starts clean (user-locked 2026-09-07).
- Narration is ephemeral: heard, never persisted to history (user-locked 2026-09-07).
- Spoken shaping is adaptive by content type, not a fixed cap (user-locked 2026-09-07): prose explanations speak generously in active conversation; tables/diagrams/code are described, never recited verbatim; the type table stays extensible for unthought cases.
- Default lane for unclassifiable triggers is narration (fail-safe toward ephemerality: heard, never persisted as phantom history).
- Narration content policy (user-locked 2026-09-07, session-304): commentary speaks ONLY direction & intent, meaningful findings, and time & scale expectations. Mechanical steps (subtask splitting, tool names, file-by-file progress) are NEVER narrated. Pivots/dead-ends are direction changes and may never pass silently.
- Narration rhythm (user-locked 2026-09-07, session-304): running commentary — periodic beats, roughly one per plan segment, never one per mechanical step.
- Narration production = hybrid (user-locked 2026-09-07, session-304): direction + time expectations are planned beats authored at task start; findings + pivots are authored live as short reactive lines. The agent owns content and may revise/replace/cancel pending beats mid-task (pivotable narration); the engine owns timing/interruption and never rewrites content. Stale planned beats are cancelled via REQ-4 subsumption, not spoken.
- OQ-1 resolved (2026-09-07, session-304): both shaping paths — the agent-authored describe line takes precedence; the extractive fallback stays. The agent's spoken line must be strong enough to describe a table/diagram/code to a user NOT looking at the screen. Measure both live.
- OQ-2 resolved (2026-09-07, session-304): awaiting lane = the three confirmed states only (takeover, approval, question); reminders/timers deferred until they arise in logged traffic.
- OQ-3 resolved (2026-09-07, session-304): on reply admission, narration finishes its current sentence; the remaining pending chatter is cancelled (matches AC4.4).
- Fillers demoted to gap-filler exception (user-locked 2026-09-07, session-305): the canned filler tables (agent_kernel.py:6242, tts.py:835) survive only as an exception path — fired only when speech would otherwise be silent AND the first planned beat is not ready; never the same phrase twice consecutively; subsumed mid-play (finish sentence, cancel rest) the moment a real beat arrives.
- Beat authoring = planning call as first writer + amendable queue (user-locked 2026-09-07, session-305): planned beats are authored by the task-planning call (structured output field) since direction/time expectations are projections of the plan; no separate mandatory authoring call. The scheduler queue IS the beat store (single source of truth, no shadow copy). Beats are immutable nodes (id, text, kind: planned|reactive, status: pending|playing|spoken|cancelled); the agent amends via atomic ops (ADD / REPLACE = cancel+add / CANCEL), each landing fully or rejected with a logged reason (already spoken, turn dead) — never partial, never silent. Engine transitions status only; agent writes content only.
- Reactive-line burst merge (user-locked 2026-09-07, session-305): findings arriving within a short debounce window author as ONE merged line, never N back-to-back utterances (content-level merge, not audio stitching). Pivot-grade findings speak immediately without waiting; queued minor findings fold into the next line. Window value is UNVERIFIED — tune live via REQ-9 counters.
- Anti-repetition = prompt guidance + cheap engine bounce (user-locked 2026-09-07, session-305): varied few-shot examples in the authoring prompt, plus an ephemeral ring buffer of recent spoken beats; a normalized-opening exact match triggers ONE re-author bounce, then the line speaks regardless (never block the turn). No embeddings, nothing on the synthesis hot path.
- One voice, identical prosody for all lanes (user-locked 2026-09-07, session-305): no register/prosody distinction between narration and replies. Whether users confuse lanes is an empirical question deferred to shadow-mode evidence.
- TTS engine swap REJECTED (user-locked 2026-09-07, session-305): no replacement of the current TTS (e.g. Raon-OpenTTS-0.3B was evaluated and declined — CC BY-NC license, non-streaming diffusion synthesis, no emotion/pacing control surface, first-audio latency budget risk). Not deferred, not a spike: out.
- First beat speaks on authoring (user-locked 2026-09-07, session-305): the first planned beat speaks the moment planning completes — it is a statement of intent, nothing to wait for. Fillers only cover the pre-beat gap (see filler demotion above).
- Beat spacing = coalesce pending, never interrupt playing (user-locked 2026-09-07, session-305): a beat authored while a pending (unspoken) beat sits queued merges/replaces it (pending narration is subsumable per REQ-4); a playing beat finishes its current sentence before the next speaks. Spacing is emergent from coalescing — no spacing timers. Same mechanism as the reactive-line burst merge.
- Wait-states are narratable events (user-locked 2026-09-07, session-305, supersedes "silence is default"): the agent is expected to be aware of what it waits on. Narration triggers are event-driven from the wait lifecycle — (1) entering a known long wait may author a time-expectation line at wait entry, (2) a wait crossing its stated expectation triggers an expectation-miss reactive line, (3) wait exit delivers results as findings. A revised time-expectation ("taking longer than stated") is a beat REVISION through the amendment API (T13), not a timeout-extension mechanism — none exists and none is built. Timer-driven heartbeats remain banned.
- Narration earns airtime by duration (user-locked 2026-09-07, session-305): narration speaks only when the task is expected to outlive the reply; trivial tasks stay fully voiced via the REPLY lane and the acknowledgment path. The gate is duration-based, not segment-count-based; threshold tunable via REQ-9 counters.
- Mic stays half-duplex during narration (user-locked 2026-09-07, session-305): narration holds the derived mic gate closed like all playback (AC7.2); interruption is wake-word barge-in → REQ-4 kill-and-fresh-turn. No full-duplex, no mid-playback VAD yielding, no narration exemption from the gate (own-voice false-wake risk). Full-duplex would be a separate audio-pipeline feature, out of this spec.
- User speech mid-task cancels pending beats; agent re-authors (user-locked 2026-09-07, session-305): the user's speech starts a new turn — pending narration dies with the old turn (REQ-5), consistent with kill-and-fresh-turn. The running task continues; the agent submits fresh beats via the amendment API when it next has something worth saying. No paused-queue state; staleness self-heals.
- Narration toggle = frontend UI control (user-locked 2026-09-07, session-305): a toggle in the widget/dashboard settings turns narration off and back on at any time, instantly. Rides the existing settings/preference path (no WS event-shape changes). Engine: one admission check — narration off drops beats at admission, logged and counted per REQ-9. Voice command may map to the same toggle later. Session-scoped initially; persistence decided after live use.
- Final-finding double-speak: no new rule (user-locked 2026-09-07, session-305). Engine side is OQ-3 (reply admission cancels pending narration after the current sentence); agent side is authoring guidance — findings near task completion belong in the reply, not narration; the agent cancels its own final beat and folds the content into the reply via the amendment API.
- Failure narration wording (user-locked 2026-09-07, session-305): cause at direction level + next step, one line, sentence-capped. No stack traces, no tool names (REQ-10 bans). If the failure needs a user decision, the line hands off and pairs with an ALERT_AWAITING question state. Full failure reports live in the REPLY; narration covers only the mid-task pivot.
- Finding privacy = authoring guidance, not enforcement (user-locked 2026-09-07, session-305): refer to artifacts by natural name ("the auth module"), never recite identifiers/paths/line numbers — identifiers stay in the visible reply. No narration-specific privacy rule (narration is ephemeral and replies are spoken aloud too; a separate rule would be inconsistent). The real ban is robotic identifier recitation, already covered by REQ-10.
- Override scope separation (user-locked 2026-09-07, session-305): the "read it to me" override stays REQ-6 reply-lane scoped (targets shown content). Narration voice control ("keep me posted" / "stop talking") routes through the narration toggle. Two controls, two concerns, no interaction.
- Hybrid pre-synthesis of narration beats (user-locked 2026-09-07, session-305): planned beats 2..N are pre-synthesized immediately after authoring (synthesize-and-hold) so synthesis latency hides in segment wait time; the first beat and reactive lines stream on demand (their text does not exist before they are due, so pre-synthesis cannot help them). Invariants: (a) pre-synthesis jobs run at LOWEST TTS-worker priority and never delay REPLY/ALERT synthesis — lane priority governs synthesis jobs, not just playback; (b) held buffers are sentence-capped, bounded per task, freed on every exit path (play, subsumption/replace, barge-in, turn end, toggle off, session end); (c) pre-synthesis failure degrades to on-admission synthesis — the beat never dies for it; (d) every outcome (played-from-hold / fell back / cancelled-waste) is logged per REQ-9 so hit rate and waste are measured live. The synthesize-and-hold worker action is a Wave 4 design item (grounded then).
- OQ-4 resolved — visual echo via the EXISTING orb reaction chain, zero new frontend events (user-locked 2026-09-07, session-305): the Xu orb already reacts to every TTS situation through two live channels — `audio_envelope` (RMS+cadence+phase; gateway wires it at iris_gateway.py:2466-2493, emits ~10Hz during playback at iris_gateway.py:4961-5064 with a final zero-envelope to stop; XurOrb.tsx:117-132 + OrbCanvas.tsx:299/486-503 breathe with it, Mode D for TTS) and `tts_started` (turn_id + total_words; generic tts_play path already emits it at iris_gateway.py:4911-4917; useIRISWebSocket.ts:949-956 re-dispatches as `iris:tts_started`). The lane engine plays ALL lanes through this same playback path — narration therefore drives the orb automatically, in half-duplex (mic gate closed, orb shows speaking phase per C1). Narration `tts_started` turn_ids MUST NOT match any chat message id (follow the existing `tts-play-*` convention) so chat-view word-highlighting never fires → no phantom card. REUSE MANDATE (user-locked 2026-09-07, session-305): this spec is a refactor — the engine reuses the existing tts_play playback path, the audio_envelope cadence chain, and the contract tests that already pin these shapes (test_voice_pipeline.py:1877 turn_id/total_words, test_barge_in.py:409-443 envelope-stop-on-barge-in + 10Hz cadence, test_voice_pipeline.py:976-1039 per-chunk + final-idle). No new orb modes, no new WS event types, no parallel playback machinery; flags die as derived views per the locked strangler decision.

## Introduction

Speech today is coordinated by scattered flags and locks with no ordering guarantees, while five different code paths independently decide what gets spoken. This feature replaces flag coordination with a deterministic lane engine: every utterance enters a lane with a distinct contract, ambiguous triggers classify through a fixed hierarchy, and gates derive from scheduler state instead of manual open/close. Users get interactivity without dead air; developers get a finite, testable decision surface.

### Success criteria

- Zero speech paths coordinated by manual flags/locks (every open/close replaced by derived scheduler state).
- spoken ⊆ visible enforced by test on every road (no invented speech, no raw full-text marathons, no mid-sentence clips).
- First-audio latency unchanged or better vs the measured baseline (~1.2 s synthesis for ~2 s audio; 60 s first-chunk budget never consumed by scheduling).
- Every (situation × lane-state) cell from the decision table covered by a unit test; barge-in, subsumption, and turn-boundary behavior covered behaviorally.
- Live shadow-mode session with zero unexplained divergences before cutover.

## Requirements

### REQ-1: Deterministic lane router
**User Story:** As the system, I want lane assignment computed from the situation by rules, so that the same situation always yields the same lane and model variance can never corrupt scheduling.

**Verified:** NEW (replaces flag scattering; situation inputs exist at callers — WS endpoint `backend/main.py:2933`, voice turn, agent tools).

**Acceptance Criteria:**
- AC1.1: THE SYSTEM SHALL assign every utterance to exactly one lane via a pure function of (trigger label, turn phase, lane occupancy) with no model call in the path.
- AC1.2: WHEN the agent supplies speak/show intent, THE SYSTEM SHALL treat it as content declaration only; it SHALL NOT influence lane selection beyond the declared artifact-vs-conversation distinction.
- AC1.3: THE SYSTEM SHALL record the routing decision (inputs + chosen lane) on the utterance node for observability.

**Edge Cases:**
- Router throws → utterance falls to the default lane (narration) rather than dropping speech or crashing the turn.
- Concurrent arrivals → FIFO within equal priority; router evaluation is O(1) and never blocks synthesis start.

### REQ-2: Distinct lane contracts
**User Story:** As a user, I want narration, replies, and alerts to behave differently on interruption, persistence, and length, so that each kind of speech is predictable.

**Verified:** NEW (partial precedent: SpeakTool caps `backend/agent/tools/speak_tool.py:29-30`; narration lock `backend/agent/conversation_kernel.py:63`).

**Acceptance Criteria:**
- AC2.1: THE SYSTEM SHALL implement four lanes — NARRATION (ephemeral, subsumable, sentence-capped, dies at turn boundary), REPLY (persisted, preempts narration, chaptered, survives turn boundary), ALERT_CRITICAL (preempts all, one breath, persisted), ALERT_AWAITING (survives turn boundaries, re-announces once, never dies silently).
- AC2.2: WHILE two lanes hold utterances, THE SYSTEM SHALL serialize audio strictly by lane priority; equal priority SHALL be FIFO.
- AC2.3: IF two lanes ever share a behavior, THE SYSTEM SHALL treat that as a design smell to resolve (merge or sharpen), never as an accepted overlap.

**Edge Cases:**
- Zero-duration/empty utterance → dropped at admission with a debug log (never enqueued).
- All lanes empty → gates report idle; no polling loops spin (event-driven wake).

### REQ-3: Ambiguous-trigger hierarchy
**User Story:** As the router, I want a fixed precedence for unclear triggers, so that classification never depends on interpretation.

**Verified:** NEW (trigger labels exist at sources: WS `msg_type`, voice-turn origin, tool-call origin).

**Acceptance Criteria:**
- AC3.1: WHEN a trigger's lane is ambiguous, THE SYSTEM SHALL classify by strict precedence: L1 explicit caller label > L2 turn-phase rule > L3 content-shape rule > L4 default lane (narration).
- AC3.2: THE SYSTEM SHALL log every L2–L4 classification (trigger + rule fired + lane) so ambiguous traffic is measurable and the table can be tightened.
- AC3.3: IF a trigger arrives with no usable label, phase, or shape, THE SYSTEM SHALL place it in the default lane rather than dropping it.

**Edge Cases:**
- Conflicting labels (two callers disagree) → L1 uses the originating caller's label; the conflict is logged as a warning.
- Hierarchy table itself is data (not code branches) so new rules land without touching the router.

### REQ-4: Preemption and subsumption
**User Story:** As a user interrupting the agent, I want speech to stop immediately and the new turn to start clean, so that I never fight stale audio.

**Verified:** NEW (precedent: barge-in paths in `backend/tests/test_barge_in.py`; narration lock in `conversation_kernel.py`).

**Acceptance Criteria:**
- AC4.1: WHEN barge-in is detected, THE SYSTEM SHALL cancel the running utterance and clear all pending utterances, then admit the new turn's speech (kill-and-fresh-turn).
- AC4.2: WHEN a REPLY or ALERT_AWAITING utterance is admitted while NARRATION utterances are pending, THE SYSTEM SHALL cancel the pending narration unspoken (subsumption: never narrate what the reply is about to say).
- AC4.3: WHEN ALERT_CRITICAL is admitted, THE SYSTEM SHALL preempt any running utterance immediately.
- AC4.4: IF cancellation races synthesis completion, THE SYSTEM SHALL prefer completed audio (never cut a final 200 ms to satisfy bookkeeping).

**Edge Cases:**
- Barge-in with empty lanes → no-op, turn starts normally (no error, no log above debug).
- Subsumption during playback (not just pending) → finish the current sentence, then yield (no mid-word cuts).

### REQ-5: Turn-boundary policy
**User Story:** As a user across a multi-turn conversation, I want progress chatter to die with its turn while answers and waiting states survive, so that speech never leaks across turns.

**Verified:** NEW.

**Acceptance Criteria:**
- AC5.1: WHEN a turn ends, THE SYSTEM SHALL cancel all NARRATION utterances tied to it.
- AC5.2: WHILE a REPLY utterance is playing across a turn boundary, THE SYSTEM SHALL let it finish (replies are turn-anchored, not turn-bounded).
- AC5.3: WHEN a turn ends with a live ALERT_AWAITING node, THE SYSTEM SHALL keep it and re-announce it exactly once at the next idle moment.
- AC5.4: IF a new turn starts while a prior REPLY still plays, THEN barge-in rules (REQ-4) govern — boundary policy never overrides an explicit interruption.

**Edge Cases:**
- Rapid turn churn (3+ turns in 5 s) → at most one re-announcement queued; extras collapse (no nag storms).
- Session end → all lanes drain silently (no orphaned audio, no stuck gates).

### REQ-6: Content-aware spoken shaping
**User Story:** As a user in active conversation, I want explanations spoken in full but tables and diagrams described rather than recited, so that speech never feels like the chat being read aloud.

**Verified:** NEW (precedent: `show.format` already carries content type — markdown/table/diagram/html/text; normalizer `backend/voice/tts_normalizer.py:92`; existing derivations at `backend/agent/agent_kernel.py:3837`, `backend/iris_gateway.py:5764`, `backend/iris_gateway.py:10993`).

**Acceptance Criteria:**
- AC6.1: THE SYSTEM SHALL shape spoken text by content type: prose/explanation speaks generously in active conversation; table/diagram/code SHALL be summarized or described and never recited cell-by-cell or line-by-line.
- AC6.2: THE SYSTEM SHALL resolve shaping through ONE resolver with fixed precedence (agent `speak` line > type-aware shaping > first-sentence fallback) replacing all per-path derivations.
- AC6.3: THE SYSTEM SHALL guarantee spoken ⊆ visible: every spoken utterance is derived from shown content; nothing invented, no raw full-text marathons, no mid-sentence clips (sentence-boundary respect, same principle as the synthesis chapter guard).
- AC6.4: WHEN content matches no listed type, THE SYSTEM SHALL apply describe-don't-recite and log the unlisted type for table extension.

**Edge Cases:**
- Empty spoken derivation (nothing worth saying) → silence is legal; the turn proceeds visibly (speech is companion, never load-bearing).
- Mixed content (prose + table) → speak the prose, describe the table, in document order.
- User explicitly asks "read it to me" → full recitation allowed (explicit override beats the type table).

### REQ-7: Serialization without flags
**User Story:** As the audio pipeline, I want one mouth with derived gates, so that no stuck thread can ever wedge listening or speaking again.

**Verified:** NEW (replaces: `_NARRATION_PLAYBACK_LOCK` at `backend/agent/conversation_kernel.py:63`; `set_tts_active` toggles at `backend/audio/voice_command.py:1749/1768/1775`, `backend/iris_gateway.py:2536/4283/4773`, `backend/api/chat.py:248/262`).

**Acceptance Criteria:**
- AC7.1: THE SYSTEM SHALL serialize all playback through lane order; the narration lock SHALL be removed once its last caller migrates.
- AC7.2: THE SYSTEM SHALL derive the half-duplex mic gate from scheduler state (any play-node running) instead of manual open/close calls at any site.
- AC7.3: IF a node wedges past its watchdog, THE SYSTEM SHALL fail the node and free derived gates automatically (structurally closes the stuck-producer open item: no manual reset exists to forget).
- AC7.4: WHILE the scheduler runs, THE SYSTEM SHALL add zero latency to first-audio vs the measured baseline (scheduling is O(1) queue ops off the synthesis path).

**Edge Cases:**
- Scheduler process fault → watchdog fails all live nodes, gates derive idle, turns continue visibly (speech degrades, conversation never blocks).
- Barge-in during gate transition → preemption wins; gate follows the new state within one poll interval.

### REQ-8: Failure semantics
**User Story:** As a user, I want speech failures to be brief and self-healing, so that a dead worker never silences the conversation or wedges the UI.

**Verified:** NEW (precedent: TTS crash-restart paths in `backend/agent/tts.py`; worker protocol).

**Acceptance Criteria:**
- AC8.1: IF an utterance node fails (worker death, timeout, empty audio), THE SYSTEM SHALL mark it failed, free its gates, and continue the turn visibly without it.
- AC8.2: WHEN playback dies mid-utterance on a REPLY or ALERT lane, THE SYSTEM SHALL emit a one-breath Critical notice at most once per turn (never a loop of failure announcements).
- AC8.3: THE SYSTEM SHALL retry a failed utterance at most once, on the next scheduler pass, then drop it (no infinite respawn).

**Edge Cases:**
- Failure during shadow mode → logged as divergence data, never acted on (shadow changes nothing).
- Cascading failures (3+ node failures in one turn) → lane drains, turn completes silently-visible, error logged once with turn scope.

### REQ-9: Speech observability
**User Story:** As the tuner, I want every routing, preemption, subsumption, and shaping decision logged per turn, so that the next iteration measures instead of guesses.

**Verified:** NEW.

**Acceptance Criteria:**
- AC9.1: THE SYSTEM SHALL log lane assignment (trigger, rule fired, lane), preemptions, subsumptions, shaping decisions (type table hit/miss), and node outcomes, each stamped with turn_id and session scope.
- AC9.2: THE SYSTEM SHALL count unlisted content types (REQ-6 extension feed) and L2–L4 hierarchy hits (table-tightening feed) as named counters.
- AC9.3: WHILE in shadow mode, THE SYSTEM SHALL log would-order divergences against actual behavior without altering it.

**Edge Cases:**
- High-volume narration → observability stays off the synthesis hot path (log after admission, never inline with audio).
- Missing turn_id → session-scoped fallback identifier, never a dropped record.

### REQ-10: Narration content policy (running commentary)
**User Story:** As a user, I want the agent's work commentary to tell me why the work is going the way it is going, so that the voice is a useful guide instead of machinery chatter.

**Verified:** NEW (grounding pending — OQ-5; Wave 4 tasks written after Phase -1 grounding)

**Acceptance Criteria:**
- AC10.1: THE SYSTEM SHALL restrict narration content to direction & intent, meaningful findings, and time & scale expectations; mechanical steps SHALL NOT be narrated.
- AC10.2: WHEN a task plan is formed, THE SYSTEM SHALL author narration beats for direction and time/scale expectations at planning time.
- AC10.3: WHEN a meaningful finding or pivot occurs, THE SYSTEM SHALL author a short reactive line live and MAY revise or cancel pending planned beats it invalidates.
- AC10.4: WHEN a planned beat is invalidated, THE SYSTEM SHALL cancel it via REQ-4 subsumption rather than speak it.
- AC10.5: THE SYSTEM SHALL keep each narration beat within the AC2.1 sentence cap and the AC6.3 spoken⊆visible guarantee.
- AC10.6: THE SYSTEM SHALL schedule narration pre-synthesis jobs at lowest TTS-worker priority such that they NEVER delay synthesis of REPLY or ALERT utterances (lane priority governs synthesis jobs, not just playback — AC7.4 must hold for the reply path even while narration pre-synthesis is in flight).
- AC10.7: THE SYSTEM SHALL bound held narration audio (sentence-capped buffers, per-task cap) and free every held buffer on play, cancel (subsumption, replace, barge-in, turn end), narration-toggle off, and session end. A pre-synthesis job racing a cancel SHALL discard the completed audio and count it as waste.
- AC10.8: THE SYSTEM SHALL play narration through the existing unified playback path so the Xu orb's current reaction chain (audio_envelope speaking-phase breathing + tts_started) drives its visual echo with NO new frontend events, NO new orb modes, and NO WS shape changes. Narration tts_started turn_ids SHALL NOT match any chat message id (no phantom word-highlighting).
- AC10.9: WHEN multiple reactive findings arrive within the debounce window, THE SYSTEM SHALL author ONE merged line covering them; pivot-grade findings SHALL speak immediately without waiting; queued minor findings SHALL fold into the next line.
- AC10.10: THE SYSTEM SHALL speak the first planned beat the moment authoring completes, SHALL coalesce a newly authored beat into a pending (unspoken) beat rather than queue back-to-back, SHALL always let a playing beat finish its current sentence before the next, and SHALL gate narration on the task being expected to outlive the reply.
- AC10.11: THE SYSTEM SHALL treat tool-execution wait states as narratable events — a known long wait MAY author a time-expectation line at entry, a wait crossing its stated expectation SHALL trigger a reactive line, and wait exit SHALL deliver results as findings. Timer-driven heartbeats SHALL NOT be used.
- AC10.12: WHEN a newly authored beat's normalized opening matches a recent spoken beat, THE SYSTEM SHALL bounce it back for re-authoring exactly once, then speak it regardless (never block the turn).
- AC10.13: THE SYSTEM SHALL use canned filler phrases only as a gap-filler exception — fired only when speech would otherwise be silent AND the first beat is not ready, never the same phrase twice consecutively, and subsumed mid-play (finish sentence, cancel rest) when a real beat arrives.
- AC10.14: THE SYSTEM SHALL provide a frontend narration toggle riding the existing settings/preference path (no WS shape changes); WHEN narration is off, THE SYSTEM SHALL drop narration beats at admission (replies and alerts unaffected) and SHALL log and count every drop.

**Edge Cases:**
- Planning yields no beats → narration stays silent for that task (silence is legal per REQ-6).
- A beat is invalidated mid-synthesis → finish the current sentence, cancel the remainder (AC4.4).
- Reactive line arrives while a planned beat is queued → revision wins; the stale beat is dropped at admission, not played then contradicted.
- Pre-synthesis fails or the worker is busy with higher-lane work → the beat falls back to on-admission synthesis at play time (degraded latency, never dropped for it); logged per REQ-9.
- Narration toggle flips off mid-task → pending beats dropped at admission, in-flight pre-synthesis aborted, held buffers freed immediately.

## Non-Requirements (Out of Scope)

- Reusing CaduceanPhaseManager for speech (wrong lifecycle; vocabulary reference only).
- DAG machinery (topo-sort, dependency tracking) — revisit only if a join is named and passes the join test.
- Changing WebSocket event shapes or frontend handlers (locked by existing contract tests).
- Touching STT/VAD/wake-word behavior (out of scope; pipeline consumers only).
- Voice cloning, new voices, or synthesis quality work (engine internals untouched — the scheduler only decides what/when).

## Open Questions
- OQ-4: RESOLVED 2026-09-07 (session-305) — visual echo rides the existing orb reaction chain (see Decisions Locked); moved to Decisions Locked.
- OQ-5: REQ-10 grounding — GROUNDED session-309 (specs/speech-lane-engine/grounding.md, T11). Two divergences resolved: (1) no timeout-extend mechanism exists — AC10.11 wait triggers are entry/expectation-miss/exit against stated budgets only; (2) the settings transport exists but the kernel-side apply is a `pass` stub (iris_gateway.py:5470-5472) — T15 implements the narration-key apply. Remaining scope as listed stands grounded with file:line evidence.
