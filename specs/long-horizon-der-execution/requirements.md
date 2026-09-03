# Requirements: Long-Horizon DER Execution

## Decisions Locked

- The phase scheduler remains responsible for timing, quota pacing, and priority lanes; it SHALL NOT decide whether a required semantic task action is allowed.
- Physics state may shape pacing and execution width, but task completion, retry, and tool authorization SHALL come from explicit execution state.
- A final synthesized markdown answer SHALL be able to render one Prism document card while the normal text/speech response remains visible.
- Intermediate web-tool captures SHALL persist provenance but SHALL NOT emit a Prism card on every crawl commit.
- An explicit agent `show` payload remains the preferred format choice; synthesized-markdown fallback rendering is a safety net.
- Failure is a first-class learning signal: it SHALL be persisted with context and outcome without being rewritten as success.
- Task lifecycle persistence is separate from attempt learning: a failed attempt SHALL not erase the task's resumable state or prevent later completion.
- DER completing a task is the foundation; websearch/browser/vision are MODULES that attach at a seam. If completing a task requires changing DER, the seam is wrong. Later modules SHALL be added without modifying DER.
- The encoder is an ENHANCEMENT, never a dependency. The substring/foundation path SHALL complete a websearch task on its own. A "fallback" that cannot complete the task is not a fallback.
- Steering is not interruption. A mid-task user message SHALL be considered by the running task; only an explicit stop aborts it.
- Coupling, expansion, the physics `COMPRESS` recommendation, and coordinate-graph condense are four distinct mechanisms and SHALL be referred to by the canonical names in REQ-19's vocabulary table (`design.md`), not used interchangeably.
- `.mcm/coordinates.db` is the BUILD memory used by MCM SDK tooling while developing IRIS. `backend/data/memory.db` is the APPLICATION's own coordinate store (`backend/memory/config.py:115`, `backend/memory/interface.py:8`). They are different databases with different lifetimes; the application is intended to inherit the MCM schema later, but the two SHALL NOT be conflated now (REQ-20).
- Trust and verification are orthogonal axes. A graded or improved verification score (REQ-11) SHALL NEVER change a result's trust classification; trust is assigned by provenance and enforced by the existing `HyphaChannel`/`CellWall` zone rules (`backend/memory/mycelium/kyudo.py`), which DER SHALL adopt rather than redefine (REQ-22).
- **The sub-loop footprint is a COMPRESSION, not a subset.** Resolved with the user: it SHALL convey *everything that has happened* for the goal — understanding (what has been learned), awareness (the goal itself), and direction (what must happen next) — while costing a bounded number of tokens that does **not** scale with the number of tool calls it summarises. The user's framing: the recall of a compressed state covering on the order of 20–100 tool calls must give rich context "without paying the price of consuming the tokens all over again". Truncating coverage to stay small is the wrong trade; compressing meaning is the requirement. The exact ratio and cap SHALL be chosen from measured data (REQ-18 instrumentation), not guessed up front.
- **The 182 `der_commits` rows already in `.mcm/coordinates.db` SHALL be left in place** as build history and SHALL NOT be migrated into the application store. They record agents *building* IRIS, not IRIS performing user tasks; migrating them would seed the application's learning signal with development noise. The application store starts clean (REQ-20).
- **Trust admission is by provenance alone in this feature.** External content is classified untrusted on arrival and constrained by the existing zone rules; an active content/attack scanner is a later upgrade and is explicitly NOT required here (REQ-22). Provenance is the gate now, rather than safety deferred until a scanner exists.

## Introduction

IRIS Voice must execute long-horizon tasks that combine web research, source reading,
local tools, memory, synthesis, and presentation. The current DER/Caducean system has
the recursive operator and a functioning scheduler, but its seams can discard tool
content, confuse convergence with completion, and multiply retries.

### Success criteria

- Successful web search reaches DER verification with non-empty content and source provenance.
- Failed required work is retried or repaired without physics vetoing the required action.
- Search → synthesis produces one final markdown card with source URLs and the accompanying text response.
- Repeated read-only document access does not trigger duplicate-loop failure.
- A three-domain task completes within bounded work units or emits an honest incomplete result.
- A process restart preserves task state, attempt history, evidence references, and the next resumable action.

**Top-level acceptance gate (REQ-10–REQ-18):** A websearch task completes END TO
END with the encoder ABSENT: evidence gathered, synthesis reached, one Prism
card rendered with sources, no re-gather loop. The encoder is then measured as
an improvement against that baseline (REQ-8 of `specs/phase-4-encoder`), never
as the thing that makes it work.

## Requirements

### REQ-1: Preserve structured tool results across dispatch

**User Story:** As the DER reviewer, I want the complete tool envelope so that verification, memory capture, and document rendering see the same evidence.

**Verified:** `backend/agent/tool_bridge.py:2275-2282` returns `success`, `content`, `sources`, and `trust`; the live failure showed the former dispatch boundary dropped this envelope.

**Acceptance Criteria:**

- AC1: WHEN a tool returns a successful envelope without a `result` field THEN THE SYSTEM SHALL preserve the complete envelope for formatting and capture.
- AC2: WHEN a tool returns `content`, `sources`, or `har_path` THEN THE SYSTEM SHALL make those fields available to DER verification and document capture.
- AC3: IF a tool returns an explicit failure envelope THEN THE SYSTEM SHALL preserve its error and error type without treating it as usable content.
- AC4: WHEN a cached result is returned THEN THE SYSTEM SHALL preserve the same success/content/provenance contract as a fresh result.

**Edge Cases:** Empty content with sources; legacy string results; fallback content with an informational timeout; malformed envelopes.

### REQ-2: Maintain one canonical execution ledger

**User Story:** As the DER controller, I want one attempt record for every action so that retry, split, budget, and completion decisions use the same truth.

**Verified:** Commit outcomes are recorded at `backend/agent/agent_kernel.py:7972-8005`, but gather state is separately tracked at `:7074-7079` and `:7334-7345`; this separation is a real gap.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL record task, step, attempt, parent, tool, stable action key, state, outcome class, verified label, and provenance for every attempt.
- AC2: THE SYSTEM SHALL use deterministic normalized action identity rather than process-randomized built-in hashes.
- AC3: WHEN an idempotent read returns cached data THEN THE SYSTEM SHALL record a read observation without charging it as a new side-effecting attempt.
- AC4: WHEN a parent splits THEN THE SYSTEM SHALL link every child to the parent attempt and record fold-back outcome.

**Edge Cases:** Concurrent children; same query with different constraints; restart during retry; success without usable content.

### REQ-3: Keep physics and semantic execution policy separate

**User Story:** As a long-horizon task, I want stable physics scheduling without losing required tool actions when the oscillator converges.

**Verified:** The architecture requires this boundary in `docs/CADUCEAN_ARCHITECTURE.md:167-199`; current veto logic reads `u` and scheduler amplitude in `backend/agent/agent_kernel.py:7082-7127`.

**Acceptance Criteria:**

- AC1: THE phase scheduler SHALL pace inference calls using its own scheduler and quota state.
- AC2: THE DER execution policy SHALL NOT deny a required plan action solely because `u`, `ξ`, or scheduler amplitude is converged or low.
- AC3: WHEN required work is unresolved or failed THEN THE SYSTEM SHALL allow a bounded retry, repair, or alternate tool according to execution state.
- AC4: WHEN synthesis requests redundant gathering THEN THE SYSTEM SHALL redirect it using plan/evidence state, not oscillator convergence.

**Edge Cases:** Scheduler disabled; scheduler exception; provider rate limit during required retry; multiple sessions sharing a quota.

### REQ-4: Classify failures before recovery

**User Story:** As the execution controller, I want different failures to produce different recovery actions so that one transient error does not recursively fan out the task.

**Verified:** `backend/agent/agent_kernel.py:7947-7967` currently uses `not step_success` as the split trigger; a complete failure taxonomy is not present.

**Acceptance Criteria:**

- THE SYSTEM SHALL classify failures as transient, invalid-argument, unavailable-tool, empty-result, semantic-failure, or permanent.
- WHEN a failure is transient THEN THE SYSTEM SHALL retry within the attempt budget before splitting.
- WHEN arguments are invalid THEN THE SYSTEM SHALL repair or replan before recursive fan-out.
- WHEN a source is empty THEN THE SYSTEM SHALL try a bounded alternate source before semantic failure.
- WHEN a failure is permanent THEN THE SYSTEM SHALL commit it honestly and continue independent branches when possible.

**Edge Cases:** 429 versus crawler timeout; browser crash after partial success; missing tool schema; partial source failure.

### REQ-5: Bound recursive execution and preserve completion

**User Story:** As a user running a long task, I want recursive DER recovery to terminate with a complete or honest partial result instead of an endless recovery conversation.

**Verified:** Work-unit accounting and split width are described in `docs/CADUCEAN_ARCHITECTURE.md:134-163`; parent/child terminal assertions are incomplete around `agent_kernel.py:7947-8005`.

**Acceptance Criteria:**

- THE SYSTEM SHALL debit one bounded resource across parent, child, retry, and fold-back actions.
- THE SYSTEM SHALL not split solely because a transport or envelope error hid usable evidence.
- WHEN all required plan nodes reach terminal states THEN THE SYSTEM SHALL finalize exactly once.
- IF budget ends before completion THEN THE SYSTEM SHALL emit remaining nodes and their last failure class.
- THE SYSTEM SHALL not emit a final ready-to-answer response while required nodes remain unresolved.

**Edge Cases:** Parent success with unfinished children; child success but fold-back failure; empty plan; user interruption.

### REQ-6: Preserve source provenance in the final Prism render

**User Story:** As a user, I want the synthesized answer and supporting URLs together so that I can verify the response without opening an intermediate crawl card.

**Verified:** Final fallback rendering is `backend/agent/agent_kernel.py:3081-3149`; it currently emits empty `sources` and `har_path`. Capture provenance is stored at `agent_kernel.py:3564-3576`.

**Acceptance Criteria:**

- WHEN a final response synthesizes captured web evidence THEN THE SYSTEM SHALL render one markdown Prism card with inherited source URLs and HAR provenance.
- THE SYSTEM SHALL return the normal text/speech response alongside the Prism card.
- WHEN the agent emits `show` THEN THE SYSTEM SHALL honor that format and avoid a duplicate fallback card.
- WHEN intermediate crawl results are captured THEN THE SYSTEM SHALL persist them without emitting a card for every commit.
- THE SYSTEM SHALL associate the render with conversation and turn identifiers.

**Edge Cases:** Missing sources; multiple contributing crawls; short conversational response; card update.

### REQ-7: Make memory and cross-domain context usable

**User Story:** As a long-horizon agent, I want prior findings and tool outcomes available to later domains without repeating the entire search.

**Verified:** `docs/CADUCEAN_ARCHITECTURE.md:357-398` marks Σ→document addressing UNEXERCISED; live `recall_memory` previously failed because the bridge lacked `_memory_interface`.

**Acceptance Criteria:**

- THE SYSTEM SHALL expose captured findings to later steps through a tested memory/document contract.
- WHEN a later step requests rendered documents or memory THEN repeated reads SHALL be allowed without duplicate-side-effect rejection.
- THE SYSTEM SHALL preserve source and task provenance across domains and compaction.
- IF memory is unavailable THEN THE SYSTEM SHALL degrade to bounded working context and report the missing capability without blocking the task.

**Edge Cases:** Uninitialized memory; compaction between domains; no retrieval matches; similar sources across tasks.

### REQ-8: Instrument long-horizon execution

**User Story:** As the system tuner, I want a complete attempt trace so that latency and loop causes are measurable.

**Verified:** Existing logs cover gate decisions and dispatch, but the live failure required correlating independent logs; a unified attempt trace is NEW.

**Acceptance Criteria:**

- THE SYSTEM SHALL log task, step, attempt, parent, tool, stable action key, policy decision, outcome class, duration, and verified label.
- THE SYSTEM SHALL distinguish scheduler wait, tool latency, provider retry, fallback latency, and DER recovery latency.
- WHEN an action is blocked THEN THE SYSTEM SHALL log the policy reason and ledger state that justified it.
- Instrumentation SHALL be bounded, redacted, and off the critical response path.

**Edge Cases:** Missing IDs; concurrent children; logging failure; credentials or private source content.

### REQ-9: Persist task lifecycle and learn from failure

**User Story:** As a user running a long task, I want failures to improve future decisions while the task itself remains resumable until it reaches a real terminal state.

**Verified:** The existing commit ledger records outcomes at `backend/agent/agent_kernel.py:7972-8005`, and `caducean_trajectory.py` persists commit/session-exit data; a durable task lifecycle with restart/resume semantics is NEW.

**Acceptance Criteria:**

- THE SYSTEM SHALL persist task lifecycle state as `planned`, `running`, `paused`, `completed`, `partial`, `failed`, or `cancelled`.
- THE SYSTEM SHALL persist every attempt, including failures, with its input, tool, error class, evidence references, and verified label for learning.
- WHEN an attempt fails THEN THE SYSTEM SHALL preserve the task, completed nodes, pending nodes, retry budget, and next action separately from the failure record.
- WHEN the process restarts or a client reconnects THEN THE SYSTEM SHALL rehydrate the task and resume or report the next action without duplicating completed side effects.
- THE SYSTEM SHALL transition a task to `completed` only after all required nodes have terminal outcomes and the final response/presentation boundary has been recorded.
- IF the task cannot complete within policy bounds THEN THE SYSTEM SHALL persist `partial` or `failed` with remaining nodes and a resumable explanation.
- THE SYSTEM SHALL make persisted failure outcomes available to future routing/learning without allowing a prior failure to permanently veto a valid future attempt.
- THE SYSTEM SHALL persist the attempt outcome and the task revision before emitting a terminal task event or learning signal.
- WHEN persistence of an outcome fails THEN THE SYSTEM SHALL NOT mark the task completed; it SHALL retain or enqueue the pending persistence operation and expose an honest persistence warning.
- THE SYSTEM SHALL make terminal lifecycle transitions idempotent so duplicate completion, failure, resume, or reconnect messages do not duplicate side effects.
- THE SYSTEM SHALL preserve the distinction between `FailureEvidence` (what was learned) and `TaskRecord.lifecycle` (whether work remains).
- WHEN a failure is recovered by a retry, alternate tool, or child step THEN THE SYSTEM SHALL retain the original failure and link the recovery attempt to it.
- THE SYSTEM SHALL allow future tasks to use failure evidence as a routing prior without treating it as an unconditional veto.

**Edge Cases:** Crash after tool success but before commit; crash after commit but before presentation; restart during provider wait; client disconnect; duplicate resume request; task with independent failed branch; corrupted or unavailable runtime memory; persistence/database outage.

### REQ-10: The foundation completes a websearch without the encoder

**User Story:** As a user running a websearch task on a machine with no encoder loaded, I want the task to reach a real answer so the system never silently depends on an optional model to finish ordinary work.

**Verified:** `backend/agent/verifier.py:281-284` — `_substring_score` is `1.0 if assertion.lower() in result.lower() else 0.0`, exact containment with no tokenisation; for paraphrased crawl prose this returns exactly `0.0`. This scorer is only reached through `verified_fraction`/`_score_assertion` (`verifier.py:204-279`), which the per-step verifier consults in two places: `backend/agent/agent_kernel.py:7776-7782` (`_frac >= 0.8 -> VERIFIED`, `>= 0.3 -> UNVERIFIED`, else `UNVERIFIED if len(_without_marker) >= 200 else FAILED`) for steps with an explicit `expected_output` and a non-web-content tool, and `agent_kernel.py:6151-6159` (task-level outcome banding: `_frac >= 0.8` "success", `>= 0.3` "partial", else "failure" over the joined step outputs) which decides whether `_der_synthesize_outcome` runs (REQ-12). **Correction to the originally supplied evidence:** `agent_kernel.py:7676-7678` defines `_WEB_CONTENT_TOOLS = {"crawler_query", "web_search", "search", "google_search", "exa_search"}`, and `agent_kernel.py:7736-7759` verifies those tools by CONTENT SUFFICIENCY (`success and not error` or `len >= 80` and non-error) — NOT by substring/`_frac` — so a raw search/crawl tool call already reaches per-step `VERIFIED` without the encoder. The genuine encoder-free gap is not "no crawl-shaped result can ever verify" but that the exact-containment fallback still governs the *task-level* outcome band and any *non-web-content* step (e.g. a synthesis/reason step whose `expected_output` names assertions to satisfy), and — per REQ-12 below — that even a `_frac`-driven "success" band does no synthesis at all today.

**Acceptance Criteria:**

- AC1: WHEN the encoder is absent or unavailable THEN THE SYSTEM SHALL still complete a websearch task through evidence gathering, verification, and synthesis using the substring/foundation path alone.
- AC2: THE SYSTEM SHALL NOT require the encoder to reach a terminal, useful outcome for a websearch task; the encoder-absent path SHALL be a first-class, independently testable path, not treated as an already-broken fallback.
- AC3: WHEN a search/crawl tool call succeeds with non-empty, non-error content THEN THE SYSTEM SHALL preserve the existing CONTENT SUFFICIENCY verification for that step (`_WEB_CONTENT_TOOLS`) without regressing it while REQ-11's graded scorer is introduced elsewhere.
- AC4: WHEN a task's final outcome band or a non-web-content step's assertion match depends on `_substring_score`/`_verified_fraction` THEN THE SYSTEM SHALL NOT let exact-containment failure alone prevent the task from reaching a terminal, honestly-labeled result (ties to REQ-11's graded scorer and REQ-13's fold-forward rule).

**Edge Cases:** Encoder import raises at load time; encoder times out mid-task; paraphrased crawl prose with zero literal substring overlap with the expected assertion; a task with only non-web-content steps (no `_WEB_CONTENT_TOOLS` involved); an empty `expected_output`.

### REQ-11: Verification degrades gradually, not binarily — and never grants trust

**User Story:** As the DER reviewer without an encoder, I want a graded confidence score instead of an all-or-nothing containment check so a mostly-correct paraphrase is not scored identically to a completely wrong answer — and I want that grading confined to answering "did this satisfy the assertion," never leaking into "is this safe to remember."

**Scope correction (supersedes the original framing of this requirement):** This requirement governs VERIFICATION QUALITY ONLY — whether a result satisfies an assertion. It previously implied that a more generous fallback scorer was an unqualified improvement; taken alone that is a security bug, because DER currently has only one axis (`verified_label`) where the memory layer already has two: verification quality and provenance/trust. Making the fallback scorer more generous MUST NOT let external, unverified content grade its way into trusted memory. REQ-22 defines the trust axis explicitly; this requirement is now scoped to never touch it.

**Verified:** `backend/agent/verifier.py:249-279` (`_score_assertion`) and `verifier.py:204-240` (`verified_fraction`) both return `(score, scorer_tag)` where `scorer_tag` is `"semantic"` when the encoder is used and `"fallback"` when `_substring_score` is used (`verifier.py:279`, `verifier.py:239-240`). `verifier.py:281-284` is the fallback's only scoring logic today: binary containment. `backend/tests/contract/test_der_band_contract.py` pins the `0.8`/`0.3` bands and the exact `VERIFIED`/`UNVERIFIED`/`FAILED` label strings under CT-E3/CT-E5 (file header comment, lines 1-6, and per-band tests at lines 38-105).

The two-axis model this requirement must not collapse ALREADY EXISTS in the memory layer and SHALL be adopted, not reinvented: `backend/memory/mycelium/kyudo.py:47` defines `HyphaChannel.UNTRUSTED = 0` as the lowest trust channel; `:55-61` (`CHANNEL_WEIGHTS`) gives `HyphaChannel.UNTRUSTED` a `0.3` resonance weight versus `1.0` for `VERIFIED`; `:64` (`LANDMARK_TRUST_CAP = 0.30`) caps the fraction of untrusted sources a landmark cluster may contain (the requirement's originally-supplied name for this constant, `MAX_UNTRUSTED_FRACTION`, does not exist in the file — corrected here); `:93-97` documents that `REFERENCE_ZONE` is readable/enterable by any channel including `UNTRUSTED`; `:177` states "EXTERNAL and UNTRUSTED channels may NEVER write the `conduct` space." `backend/memory/mycelium/interface.py:673-677` maps `trust == "untrusted"` to `HyphaChannel.EXTERNAL`, which writes only `REFERENCE_ZONE`/`toolpath`, and `:679-681` excludes untrusted sessions from crystallization. Separately, `specs/web-search-unified/REQ-22` ("PacMan Trust Persistence," already implemented per `specs/web-search-unified/tasks.md` T11) already tags every `crawler_query` fragment `trust:"untrusted"` before it reaches pacman (`backend/agent/tool_bridge.py:2093`, `:2289`) — confirming the trust axis is already live for web content upstream of DER's verifier. This requirement's graded scorer sits entirely on the OTHER axis and SHALL NOT be wired to touch either mechanism.

**Acceptance Criteria:**

- AC1: WHEN the encoder is unavailable THEN THE SYSTEM SHALL score assertion-vs-result similarity with a graded, normalized measure (e.g. token/claim overlap) instead of binary substring containment.
- AC2: THE SYSTEM SHALL keep the `0.8`/`0.3` band thresholds and the `VERIFIED`/`UNVERIFIED`/`FAILED` label strings UNCHANGED; only the fallback scorer's granularity changes, not the bands that consume it (CONTRACT LOCK — CT-E3).
- AC3: THE SYSTEM SHALL keep the `scorer_tag` (`"semantic"` vs `"fallback"`) observable on every score so REQ-18's trace can report which scorer produced a given verified label.
- AC4: THE stub guard (CT-E4: a bare-stub result scores `0.0` and never reaches either scorer) SHALL remain unconditional and unaffected by the graded fallback.
- AC5: WHEN the graded fallback and the encoder disagree on a score THEN THE SYSTEM SHALL prefer the encoder's score when present and record both for observability, never silently averaging them.
- AC6: IMPROVING the fallback scorer's grading (AC1) SHALL NOT change a result's trust classification — `verified_label`/`score`/`scorer_tag` SHALL NOT be read anywhere as an input to `HyphaChannel` assignment, `CellWall` zone routing, or the `trust` field on `FinalRender`/pacman fragments. A `VERIFIED` result from an `UNTRUSTED` or `EXTERNAL` source SHALL remain untrusted (CONTRACT LOCK, ties to REQ-22 and `kyudo.py:97,177`).
- AC7: THE SYSTEM SHALL treat a high graded score on external crawl/HAR content as evidence the content ANSWERS the assertion, never as evidence the content is SAFE to admit into a trusted memory zone; those remain two separate decisions (REQ-22).

**Edge Cases:** Assertion with no comparable tokens (e.g. a number or URL); non-English assertion text; extremely long result truncated before scoring; assertion list containing an empty string after `;`-splitting; a perfectly-scored (`1.0`) assertion whose source is `UNTRUSTED` — the score changes nothing about where the content is allowed to write.

### REQ-12: The success path synthesizes

**User Story:** As a user whose websearch task completed without any failed steps, I want the gathered evidence synthesized into one answer, not the raw tool outputs concatenated together.

**Verified:** `backend/agent/agent_kernel.py:6341-6348` calls `_der_synthesize_outcome` ONLY when `queue.failed_ids` is non-empty (`if queue.failed_ids:`). `agent_kernel.py:6356-6357` is the success path: `if step_outputs: return "\n".join(o for o in step_outputs if o)` — raw concatenation, no synthesis. `agent_kernel.py:9019` defines `_synthesize_response`, and a repository-wide search (`grep _synthesize_response\(`) finds zero call sites anywhere in `backend/` outside its own `def` line — it is dead code.

**Acceptance Criteria:**

- AC1: WHEN all required steps reach a terminal state with no failed step THEN THE SYSTEM SHALL synthesize the gathered evidence into a final answer rather than concatenating raw step outputs.
- AC2: THE synthesis on the success path SHALL consume the same evidence/provenance the failure-path synthesis already consumes (sources, HAR, captured documents) so REQ-6's one-Prism-card contract applies uniformly to both success and partial-failure outcomes.
- AC3: THE SYSTEM SHALL either wire the existing dead `_synthesize_response` into the success path or replace it; dead synthesis code SHALL NOT remain uncalled once this requirement is implemented.
- AC4: IF synthesis is unavailable on the success path (e.g. the reasoning provider is down) THEN THE SYSTEM SHALL fall back to a deterministic summary, mirroring the failure path's `_der_deterministic_failure_summary` behavior (`agent_kernel.py:6349-6354`), rather than silently returning raw concatenation.

**Edge Cases:** Exactly one successful step (nothing to synthesize across); success with zero usable step outputs; synthesis provider rate-limited on an otherwise-successful task; a `show`-format step already present among step outputs (REQ-6 AC3 must still avoid a duplicate card).

### REQ-13: Fold forward, not back

**User Story:** As the execution controller, when evidence has already been gathered for a goal, I want a weak verification score to produce an honest, low-confidence answer instead of another round of gathering the same evidence.

**Verified:** `backend/agent/agent_kernel.py:8265` — `queue.mark_complete(item.step_id)` runs unconditionally immediately after the commit-ledger write and edge-scoring call, for every verified label (`VERIFIED`, `UNVERIFIED`, `FAILED`) — there is no same-step retry. `agent_kernel.py:8138` gates the ONLY split path on `if not step_success and not item.is_subloop:`, and `agent_kernel.py:8116-8117` shows `step_success` is forced `False` only `if _verified == "FAILED"` — an `UNVERIFIED` (weak but non-empty) result does not force a split today. `agent_kernel.py:8148-8206` (D4/REQ-4) further narrows the split path: a `FAILED` result is only split when failure classification does NOT resolve it to `transient`/`unavailable`/`invalid_args`/`empty`/`permanent`; those classes are recorded as failure evidence and explicitly NOT split (`agent_kernel.py:8182`, "`_split_ok = False` ... recorded, NOT split (D4)"). `agent_kernel.py:8211` is the one call site of `_split_step(item, "verify_failed", ...)`, reached only for a genuine, unclassified semantic failure.

**Acceptance Criteria:**

- AC1: WHEN a step's verification produces a low but non-`FAILED` graded score (REQ-11) after evidence has already been gathered for its goal THEN THE SYSTEM SHALL fold forward to synthesis carrying an honest, lower confidence label rather than spawning additional gathering steps.
- AC2: THE existing REQ-4 failure-classification gate (transient/unavailable/invalid-args/empty/permanent do not split) SHALL remain the ONLY path that prevents fan-out for classified transport/provider failures; REQ-13 additionally SHALL prevent fan-out for a merely-weak (non-`FAILED`) graded score.
- AC3: Split via `_split_step` SHALL remain available for a genuine, unclassified semantic failure (content produced, but verification judges it substantively wrong) per the existing REQ-4 taxonomy — REQ-13 narrows when a split is triggered, it does not remove the split mechanism.
- AC4: THE SYSTEM SHALL NOT introduce a new same-step retry path; `mark_complete` SHALL continue to run exactly once per step regardless of verified label.

**Edge Cases:** A step with zero prior evidence gathered for its goal (nothing to fold forward from — split remains legitimate); repeated weak scores across multiple steps in the same task; a weak score on the LAST required step versus a mid-plan step; `is_subloop` children (already excluded from the split gate) scoring weakly themselves.

### REQ-14: Plan revision is a first-class, observable event

**User Story:** As a user watching a long task run, I want the plan to visibly grow, change, or shrink when the agent revises it, without live progress text ever overwriting what the agent set out to do.

**Verified:** `hooks/useTaskProgress.ts:210-227` ALREADY merges by step id when a second `task:start` arrives for the same `task_id` (`sameActiveTask` check), keeping each existing step's live `status` while refreshing its `description`/`toolName` from the new plan (`:216-223`). Emit sites for `task:start`: `backend/agent/agent_kernel.py:4770-4781` (early LLM-plan skeleton) and `agent_kernel.py:5635-5656` (DER queue at execution start) — the comment at `useTaskProgress.ts:203-209` documents this two-emit pattern explicitly. Separately, `update_step` writes ONLY `activeDetail`/`activeProgress`/`url` and never `description` (`hooks/useTaskProgress.ts:384-398`), with an explicit comment at `:377-381` stating that overwriting `description` previously destroyed the visible plan text as the crawler streamed progress.

**Acceptance Criteria:**

- AC1: WHEN the agent revises its plan mid-task THEN THE SYSTEM SHALL emit an explicit, distinct revision signal (reusing the existing `task:start` merge-by-id mechanism at `useTaskProgress.ts:210-227`) rather than inventing a parallel event channel.
- AC2: A plan revision SHALL be able to add new steps, revise the description/tool of an existing pending step, AND drop remaining steps that are no longer needed.
- AC3: THE SYSTEM SHALL preserve the existing invariant that live progress updates (`update_step`) NEVER overwrite plan `description` text (`useTaskProgress.ts:377-398`) — this invariant SHALL be pinned by a regression test, not merely preserved by convention.
- AC4: WHEN a revision drops a step that is already `working` or `done` THEN THE SYSTEM SHALL NOT retroactively delete its completed status from the visible history; only pending/undispatched steps SHALL be removed.
- AC5: THE SYSTEM SHALL distinguish, in the emitted payload, a revision caused by sub-loop split (REQ-4/REQ-13) from one caused by user steering (REQ-15), so REQ-18's trace can attribute the origin.

**Edge Cases:** Revision arrives while a step is mid-dispatch; revision drops the currently-`working` step; two revisions in rapid succession; revision that only reorders remaining steps; revision with zero net change (idempotent no-op).

### REQ-15: Mid-task steering, pause, and stop are three distinct channels

**User Story:** As a user running a long task, I want to redirect it, pause it, or stop it outright, and I want to know my message actually reached the running task instead of silently queuing behind it.

**Verified:** `backend/main.py:2131` declares `_session_message_locks: Dict[str, asyncio.Lock] = {}`. `backend/main.py:2192-2214` shows `_dispatch` acquiring `async with lock:` before calling `handle_message`, so a message sent while a turn is running is QUEUED and only processed after the current turn's `handle_message` returns — confirmed by reading the block directly. **Verified NOT FOUND:** a repository search of `agent_kernel.py` for steering/pause/mid-task-injection identifiers (`steer`, `mid_task`, `inject_message`, `pause_requested`) turns up only auto-steering of the plan toward synthesis (`agent_kernel.py:7300-7325`, "steer SYNTHESIS" — an internal plan nudge, not a user-message channel) — there is no path by which a mid-turn user message reaches the RUNNING DER loop. `components/chat-view.tsx:1131-1139` already removed the `isTyping` send guard (comment cites a 23-minute lockout the old guard caused), so the frontend can already send mid-turn — the gap is entirely on the backend side of the queue.

**Acceptance Criteria:**

- AC1: WHEN a user sends a message while a task is running THEN THE SYSTEM SHALL make that message available to the running loop for consideration at the NEXT step boundary, never mid-step.
- AC2: A steering message SHALL be able to revise the plan via REQ-14's revision channel (add/revise/drop remaining steps) without aborting the task.
- AC3: WHEN a user sends an explicit stop THEN THE SYSTEM SHALL abort the running task at the next step boundary and persist its lifecycle as `cancelled` (ties to the existing REQ-9 lifecycle states).
- AC4: WHEN a user requests pause THEN THE SYSTEM SHALL suspend execution at the next step boundary, persist the in-progress state, and later resume without duplicating completed side effects (ties to the existing REQ-9 `paused` lifecycle state and idempotent-resume semantics).
- AC5: THE SYSTEM SHALL give the user visible acknowledgement that a steering message landed and was considered; an unacknowledged steering message SHALL be re-sent.
- AC6: THE SYSTEM SHALL keep steering, pause, and stop as three distinct, independently observable channels — a steering message SHALL NOT be misinterpreted as a stop, and a stop SHALL NOT be delayed behind an unrelated steering message's processing.

**Edge Cases:** Steering message arrives during the exact step-boundary transition; stop arrives immediately after a step's tool call has already started (tool call in flight — see Open Questions); pause immediately followed by stop; two steering messages queued back to back; steering message that is itself empty/whitespace; client disconnects after sending steering but before acknowledgement is delivered.

### REQ-16: The agent's browser is in-app, visible, and narrated; the OS browser is never launched implicitly

**User Story:** As a user, I want the agent's own navigation to happen inside IRIS's browser surface — and I want to SEE it happen, watching pages load, scroll, and get scraped with a visible sense of what the agent is doing and why — so my actual desktop browser is never hijacked by an agent action I didn't ask to see externally, and so an in-app agent action isn't an invisible black box either.

**Verified:** `backend/mcp/builtin_servers.py:108-121` — `BrowserServer.execute_tool` calls `webbrowser.open(url)` for BOTH `open_url` (`:109-114`) and `search` (`:116-121`). `backend/agent/tool_bridge.py:1247-1254` intercepts `tool_name == "search"` BEFORE the MCP dispatch table, routing it in-app via `_execute_web_search`; `tool_bridge.py:1241-1246` carries a first-party comment stating this exact `webbrowser.open`-hijack bug was already fixed for search. `tool_bridge.py:1211-1212` shows `"open_url": ("browser", "open_url")` still present in the `mcp_tools` table with NO equivalent interception — it still reaches `BrowserServer.execute_tool` -> `webbrowser.open`. `backend/agent/tool_registry.py:334-340` registers `open_url` with `requires_desktop=True` and does NOT set `requires_internet`, so the internet-access gate never evaluates it. A SECOND, duplicate `webbrowser.open` implementation exists at `backend/agent/tool_executor.py:631-652` (`_open_url` and `_search` methods), reachable through the tool-executor dispatch path used by skill/recall tooling. The in-app surface ALREADY EXISTS: `components/dark-glass-dashboard.tsx:464-466` (`browserUrl` state + `iframeRef`), `:970-979` (`handleBrowserNavigate`), `:1345-1380` (address bar + iframe + an explicit user-initiated `window.open(..., '_blank')` "open externally" button at `:1370`, which SHALL remain user-initiated), and the crawler already drives this surface via `iris:crawler_started`/`iris:crawler_page_fetched` (`components/dashboard-wing.tsx:105-136`) and `iris:open_tab` (`dark-glass-dashboard.tsx:620-641`).

**Verified — existing "visible" precedent is a progress counter, not an overlay:** `components/dashboard-wing.tsx:105-136` already listens for `iris:crawler_started`/`iris:crawler_page_fetched`/`iris:crawler_error` and tracks `{active, query, pagesDone, pagesTotal, error}` — this proves a live event channel from crawl to UI already exists, but it renders a page-count indicator, not a narrated "what is the agent doing right now" overlay. The behavioral ACs below extend this precedent; they do not assume it already satisfies them.

**Verified — an existing seam for per-page visual feedback:** the vision MCP server is already registered and dispatchable: `backend/tools/vision_mcp_server.py:26-53` (`VisionMCPServer(BuiltinServer)`, lazy-loads `LFMVLProvider`, never raises — returns error strings) with `ToolSpec`s at `backend/agent/tool_registry.py:244-275` (`vision_detect_element -> vision.find_ui_element`, `vision_analyze_screen`, `vision_validate_action`, `vision_get_context`, all `parallel_safe=True`). This means an overlay driven by "what is the agent looking at / trying to do" can be populated from tool calls that already exist, through the REQ-17 `ToolSpec` seam, rather than a new one-off channel.

**Acceptance Criteria:**

- AC1: WHEN the agent navigates to a URL (`open_url`) THEN THE SYSTEM SHALL target the in-app browser surface (`iris:open_tab` / the existing iframe dashboard), the same way `search` already does, and SHALL NOT call `webbrowser.open`.
- AC2: THE duplicate `webbrowser.open` implementation at `tool_executor.py:631-652` SHALL be removed or made unreachable from any live tool-dispatch path.
- AC3: `open_url`'s `ToolSpec` SHALL set `requires_internet=True` so the existing internet-access capability gate applies to it exactly as it applies to other network tools.
- AC4: THE explicit, user-initiated "open externally" control in the dashboard browser panel (`dark-glass-dashboard.tsx:1370`) SHALL remain the ONLY path by which an agent-touched URL reaches the OS browser; it SHALL remain gated on direct user interaction, never agent-triggered.
- AC5: WHEN `open_incognito` or any future browser MCP tool is added THEN THE SYSTEM SHALL route it through the same in-app interception pattern rather than reintroducing `webbrowser.open`.
- AC6 (behavioral — navigation): WHEN the agent navigates to a page THEN THE SYSTEM SHALL perform that navigation VISIBLY in the in-app iframe/tab surface (the user can watch the address bar and page content change), not as a hidden headless fetch whose result is only reported after the fact.
- AC7 (behavioral — scroll/scrape): WHEN the agent scrolls within a page or scrapes its content THEN THE SYSTEM SHALL represent that action on the in-app surface (a visible scroll position change, a highlighted/targeted region, or an equivalent visual cue) rather than silently returning extracted text with no on-screen correlate.
- AC8 (overlay): THE SYSTEM SHALL render an overlay on the in-app browser surface conveying the agent's current sub-goal or intent during navigation/scroll/scrape (an "ego browser lite" narration layer — e.g. "looking for the pricing table," "reading page 2 of 3"), sourced through the existing `ToolSpec` dispatch of the vision tools (`vision_analyze_screen`, `vision_detect_element`) and/or the existing crawler progress events, rather than inventing an unrelated narration channel.
- AC9: THE overlay's state transitions (started, sub-goal text, page/step count, completed, error) SHALL be observable in REQ-18's correlated trace so behavioral tests can assert overlay state without requiring pixel-level UI assertions.

**Edge Cases:** `open_url` called with a non-http(s) scheme (`file://`, `mailto:`); `open_url` called while the dashboard browser panel is not visible (must open it, mirroring `onCloseTab`'s existing `setActiveSubApp('browser')` pattern); internet-access gate denies the call; duplicate `tool_executor.py` path invoked from an old skill definition after removal; a cross-origin page in the browsing iframe (`dark-glass-dashboard.tsx:1376-1380`) whose DOM the frontend cannot introspect under normal same-origin policy (note: the sandboxed `srcDoc` variant at `:1338-1342` is a separate, same-document `html`-type tab, not the navigable web tab) — the overlay SHALL degrade to coarse state (navigating/loaded/error) rather than fail when fine-grained scroll position is unavailable; a long multi-page scrape sequence — overlay update rate SHALL be bounded so it does not become a source of unbounded event traffic (ties to REQ-18 AC6).

### REQ-17: The module seam contract

**User Story:** As a developer adding a new capability module (websearch, browser, vision, and future ones), I want a declarative seam so my module attaches without editing DER's control flow.

**Verified:** `backend/agent/tool_registry.py:44-70` defines `ToolSpec`'s full field set (`name`, `description`, `parameters`, `category`, `aliases`, `requires_internet`, `requires_desktop`, `permission_tier`, `executor`, `mcp_server`, `mcp_tool`, `critical`, `parallel_safe`, `long_running`). The crawl stack is genuinely wired, not aspirational: Crawl4AI/Playwright at `backend/crawler/crawler_engine.py:155-171` (`AsyncWebCrawler`/`BrowserConfig(headless=...)`) with an `httpx`-only fallback at `backend/crawler/crawl_runner.py:370-395` (`_plain_http_fetch`, explicitly "Zero crawl4ai/browser dependency"). HAR provenance is genuinely GENERATED, not just passed through: `_write_har_file` (`crawler_engine.py:91-107`) writes `data/har/<job_id>.har`, called from `crawler_engine.py:385` and `crawl_runner.py:327,345`; entries are deliberately light — status/headers/timing/body-hash only, no response bodies (`crawler_engine.py:69-71`). Vision is already wired into the live tool path: `backend/tools/vision_mcp_server.py:26-53` (`VisionMCPServer`, following the `BuiltinServer` pattern) with `ToolSpec`s registered at `tool_registry.py:244-275` (`vision_detect_element -> vision.find_ui_element`, `vision_analyze_screen`, `vision_validate_action`, `vision_get_context`).

**Acceptance Criteria:**

- AC1: A module SHALL declare itself via one or more `ToolSpec` entries and SHALL require no change to DER's control flow (plan/execute/verify/commit/synthesize) to attach.
- AC2: A module SHALL emit progress and provenance through the EXISTING contracts — the REQ-1 tool envelope (`success`/`content`/`sources`/`har_path`), HAR provenance where applicable, and `CRAWLER_PHASE`-style structured progress — rather than inventing a parallel reporting channel.
- AC3: THE SYSTEM SHALL treat `requires_internet`/`requires_desktop`/`permission_tier` as the uniform capability gate for every module; a module SHALL NOT bypass the gate by routing around `ToolSpec` (as REQ-16's `open_url` gap currently does).
- AC4: Adding a module SHALL NOT require a new `if tool_name == "..."` branch inside DER's step-execution loop; dispatch SHALL resolve through the registry (`executor`/`mcp_server`/`mcp_tool`) as it does today for MCP-routed tools.
- AC5: THE crawl (Crawl4AI/HAR) and vision seams SHALL remain the reference implementations this requirement is measured against; this requirement does NOT require rewriting either.

**Edge Cases:** A module with no `mcp_server` (pure `executor="internal"`); a module that is `long_running` and must still narrate; a module registered twice under different names; a module whose `requires_internet` is true but the internet gate is disabled for the session.

### REQ-18: Observability for the above

**User Story:** As the system tuner, I want one correlated trace per task that shows which scorer ran, whether synthesis fired, every plan revision and its origin, every steering message and where it landed, and every browser navigation's target surface — so REQ-10 through REQ-17 are measurable, not just implemented.

**Verified:** This requirement extends the existing REQ-8 instrumentation discipline (`backend/agent/agent_kernel.py` attempt-trace logging; bounded, redacted, off the critical path) to the new surfaces introduced by REQ-10–REQ-17: the `scorer_tag` already returned by `verifier.py:204-279`, the `task:start`/revision events already emitted at `agent_kernel.py:4770-4781`/`5635-5656`, and the browser-navigation surface distinction introduced by REQ-16.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL log, per task, the scorer tag used (`semantic` vs `fallback`) and the resulting score for every verified label produced (REQ-11).
- AC2: THE SYSTEM SHALL log whether synthesis ran and on which path (success per REQ-12, or existing failure-path `_der_synthesize_outcome`).
- AC3: THE SYSTEM SHALL log every plan revision with its origin — sub-loop split (REQ-4/REQ-13) vs user steering (REQ-15) — distinguishing the two per REQ-14 AC5.
- AC4: THE SYSTEM SHALL log every steering message received, whether it was acknowledged (REQ-15 AC5), and the step boundary at which it was applied.
- AC5: THE SYSTEM SHALL log every browser navigation with its target surface (in-app vs external) and, when applicable, the crawl `job_id` and HAR path (REQ-17).
- AC6: Instrumentation added by this requirement SHALL be bounded, redacted, and off the critical response path, matching the existing REQ-8 discipline; it SHALL NOT itself become a source of unbounded log growth on a long-running task.

**Edge Cases:** A task with zero plan revisions and zero steering (trace should still be complete, just short); a steering message that never gets acknowledged (must still be logged as unacknowledged, not silently dropped from the trace); concurrent tasks in the same session; logging failure must not affect the underlying operation (mirrors REQ-8's edge cases).

### REQ-19: Canonical vocabulary — one name per mechanism

**User Story:** As a developer reading DER/Caducean code, I want "coupling," "expansion," "compress," and "condense" to each mean exactly one thing, so I stop mentally merging four unrelated mechanisms that happen to share vocabulary.

**Verified — four mechanisms currently wear overlapping names:**

1. **Session coupling** couples SESSIONS, never steps and never memory. `backend/agent/coupled_registry.py:153-155` — `CoupledTrajectoryRegistry.__init__` holds `self._sessions: Dict[str, _SessionRecord]`. `register_session`/`unregister_session` at `:157-178`. `apply_coupling` reads `(a, b, s)` via `ffi_caducean_get_state` at `:262-265` and writes ONLY `a` and `s` via `ffi_caducean_set_params` at `:336`. Nucleus/barrier role is assigned by `_role_energy` (`:108-116`), applied at `:292-302`. A grep of this file for `memory|mycelium|episodic|store|db|coords` returns NOT FOUND — coupling never touches memory and never creates a step.
2. **Step Expansion** (what actually creates steps) is `_growth_width` (`backend/agent/agent_kernel.py:6594-6609`) mapping live `|u|` against `U_SPLIT=0.5`/`U_CONVERGED=0.85` (`backend/agent/der_constants.py:233,246`), called only from `_split_step` (`agent_kernel.py:6659`). The four step-adding call sites are exactly: split (`:6514`, `:8221`), explorer plan-continuation (`:8592-8601`), and TrailingDirector gap items (`:8782-8787`).
3. **DER's "COMPRESS"** is an integer action code — `1` — returned by `ffi_caducean_recommend()` or passed to `ffi_caducean_update()`. It is consumed in exactly three ways and compacts nothing: as a raw action int written back to the physics engine (`agent_kernel.py:6578-6582`, comment "`action=1 -> COMPRESS (increments failure accumulator y)`"); as an LLM temperature modulator (`:7064-7085`, `_caducean_modulate_temperature`, halves temperature when `rec==1`); and as a plan-expansion gate (`:8565-8580`, skips adding new explorer steps while `rec==1`). A third `ffi_caducean_recommend()` read site not covered by the requirement's originally-supplied evidence exists at `:8406`, which persists the recommendation to a DB column — this further confirms the code is a physics label, not a compaction trigger, and is added here for completeness.
4. **Actual compaction** is two separate, unrelated mechanisms: DCP message pruning (`backend/agent/dcp.py:1-9`, budget note `:46-47`) drops/dedups chat messages before an LLM call; and mycelium coordinate-node merge/split (`backend/memory/mycelium/scorer.py:233-308` `condense()`, merges nodes within `CONDENSE_THRESHOLD` distance `<=0.04`; `:314+` `expand()`, splits a node whose outbound edge hit/miss variance exceeds `SPLIT_THRESHOLD=0.40`). There is a NAME COLLISION: `Landmark.condense()` (`backend/memory/mycelium/landmark.py:147`) is session CRYSTALLIZATION into a permanent landmark — unrelated to `scorer.condense()`'s node merge, despite sharing a method name. There is also a SECOND name collision between `scorer.expand()` (splits a coordinate NODE by variance) and DER's `_growth_width`/"expansion" (splits a STEP by `|u|`) — unrelated mechanisms, same word. Finally, `mcm_compress`, referenced throughout `CLAUDE.md`/`AGENTS.md`, has NO backend implementation in this repository — it is the external OpenCode MCM plugin's checkpoint+prune tool, operating on the BUILD-memory database (REQ-20), not on any of the above.

**Acceptance Criteria:**

- AC1: `design.md` SHALL contain exactly one canonical-vocabulary table mapping each of {Session Coupling, Step Expansion, Node Expansion, COMPRESS Recommendation, Node Condense, Landmark Crystallization, DCP Message Pruning, mcm_compress (external)} to its ground-truth file:line and to the name(s) it must not be confused with.
- AC2: New code introduced to satisfy REQ-1 through REQ-22 SHALL use the canonical name from that table, in comments and identifiers, for any of these eight mechanisms; it SHALL NOT introduce a ninth meaning for a term already claimed by the table (e.g. a new use of "expand," "condense," or "compress" that means something not in the table).
- AC3: THE two existing name collisions — `scorer.condense()` (Node Condense) vs `Landmark.condense()` (Landmark Crystallization), and `scorer.expand()` (Node Expansion) vs `_growth_width` (Step Expansion) — SHALL each carry a disambiguating docstring at their definition site that names the table and the sibling term it is not.
- AC4: `mcm_compress` SHALL be documented (in this spec, and in any new code comment that mentions it) as build-tooling external to the runtime application; no runtime code path SHALL imply it compacts application state.
- AC5: A regression test SHALL assert `backend/agent/coupled_registry.py` contains zero references to `memory|mycelium|episodic|store|db|coords` (the grep basis for Session Coupling's isolation), so a future edit cannot silently blur session coupling into a memory-writing mechanism without failing a test.

**Edge Cases:** A future contributor reusing "expand" or "condense" for a third, different meaning; renaming already-shipped public method names (`scorer.expand`/`scorer.condense`/`Landmark.condense`) is NOT required by this requirement — disambiguation is via docstring, not a breaking rename, unless a maintainer separately chooses to rename (see Non-Requirements); a comment that references `mcm_compress` without the "external, build-tooling" qualifier.

### REQ-20: The trajectory recorder binds to the application store, not the build-memory database

**User Story:** As IRIS Voice's own runtime memory, I want every DER commit and Caducean trajectory point to land in my own coordinate store (`backend/data/memory.db`), not in the developer's MCM build-memory database, so the application actually accumulates the memory it is designed to use.

**Verified — this is a measured bug, not a theory:** `backend/agent/caducean_trajectory.py:106-137` — `CaduceanTrajectoryRecorder.__init__`'s class docstring (`:107-110`) and constructor comment (`:121`) both state "the recorder is backed by the SAME SQLite DB as MemoryInterface." When `db_conn is None`, the constructor (`:125-136`) falls back to `os.environ["MCM_DB_PATH"]` or `<repo>/.mcm/coordinates.db` — the BUILD-memory database, not `MemoryInterface`'s database. `backend/agent/agent_kernel.py:8244` constructs `CaduceanTrajectoryRecorder()` with NO argument (inside `record_commit`), so every commit takes that fallback and writes to `.mcm/coordinates.db`. `agent_kernel.py:8435` instead calls `get_trajectory_recorder(self._memory_interface).record(...)`, which (`caducean_trajectory.py:544-571`) correctly resolves `memory_interface.episodic.db` when openable — two call sites, two different bindings, only one of them correct.

**MEASURED RESULT (queried directly against both databases):** `.mcm/coordinates.db` contains `der_commits=182` rows, `caducean_trajectories=0`, `caducean_session_exits=0`. `backend/data/memory.db` does not contain any of those three tables at all. So the commit ledger has been writing into the BUILD-memory database used for developing IRIS instead of the application's own coordinate store, and the trajectory coordinate write (`agent_kernel.py:8435`'s path) is not firing at all — confirmed further by `backend/data/memory.db`'s own tables: `episodes=1`, `mycelium_nodes=1`, `mycelium_edges=0`, `mycelium_landmarks=1`, `memory_chain` (which has `coords_from`/`coords_to` columns)`=0` rows, `mycelium_charts` (which has `x`,`y`,`z` columns)`=0` rows, `mycelium_trajectories=0`.

**CRITICAL DISTINCTION this requirement must state explicitly:** `.mcm/coordinates.db` is the BUILD memory — the MCM SDK coordinate graph used while developing IRIS itself (per `CLAUDE.md`'s own description). `backend/data/memory.db` is the APPLICATION's own coordinate store: `backend/memory/config.py:114-115` — `db_path: str = "data/memory.db"`; `backend/memory/interface.py:1-11` — "Nothing outside this class touches memory.db or ContextManager directly." They are different databases with different lifetimes. The application is intended to inherit the MCM schema later, but the two SHALL NOT be conflated now.

**Acceptance Criteria:**

- AC1: EVERY `CaduceanTrajectoryRecorder`/`get_trajectory_recorder` call site in `agent_kernel.py` (including `:8244`) SHALL bind to the application's `MemoryInterface`-backed store, matching the pattern already correct at `:8435`.
- AC2: THE silent environment-variable fallback (`MCM_DB_PATH` / `.mcm/coordinates.db`) in `CaduceanTrajectoryRecorder.__init__` SHALL NOT remain a silent alternate-database selector for application call sites; it SHALL either be removed for application use (application call sites always pass an explicit `db_conn`/`memory_interface`) or fail loudly (raise or log at ERROR, not silently succeed against the wrong database) if reached without one.
- AC3: A test SHALL assert that a DER commit recorded through the application's normal call path writes a row into `backend/data/memory.db`'s trajectory/commit tables, not into `.mcm/coordinates.db`.
- AC4: THE constructor docstring (`caducean_trajectory.py:107-110`) SHALL be corrected to state the actual binding rule this requirement establishes, not the aspirational "backed by the same DB" claim that is currently false for the `:8244` call site.
- AC5: A migration/retention decision for the 182 existing `der_commits` rows in `.mcm/coordinates.db` SHALL be made explicitly (migrate, discard, or leave as build-memory history) rather than silently abandoned or silently migrated without a decision — see Open Questions.

**Edge Cases:** `MemoryInterface.episodic.db` unopenable at call time (existing `_NoopTrajectoryRecorder` no-op path at `caducean_trajectory.py:530-541` must still apply for the application binding, per the existing pin_42ddd255162d guard); a process that legitimately needs the build-memory DB (MCM SDK tooling itself) must be unaffected by tightening the application call sites; concurrent writers to `backend/data/memory.db` under WAL mode; a fresh install where `backend/data/memory.db` does not yet exist.

### REQ-21: Sub-loop children carry a compressed footprint

**User Story:** As a sub-loop child step created by a growth-width split, I want enough compressed context about what the parent has already done and where the task is going that I don't have to restart from zero — especially if DCP pruning trims the conversation history between when I'm created and when I actually run.

**Verified:** `backend/agent/agent_kernel.py:6669-6679` — the child `QueueItem` is constructed with ONLY `step_id`, `step_number`, `description`, `objective_anchor`, `depth_layer`, `expected_output`, `is_subloop`, `critical`, `independent`. Everything else takes the dataclass default (`backend/agent/der_loop.py:76-93`): `tool=None`, `params={}`, `depends_on=[]`, `parallel_safe=False`, `coordinate_signal=""`, `veto_count=0`, `refined_description=None`, `gap_analysis=None`, `result=None`. So a child inherits two text strings (`description`, `objective_anchor`) and nothing else — no tool, no params, no coordinate signal, no prior result, no memory reference.

**Verified — there is no rendezvous:** children are pushed into the SAME flat `DirectorQueue` as every other step (`queue.add_item` at `agent_kernel.py:6514` and `:8221`), and the parent step is marked complete independently and unconditionally at `:8265` (`queue.mark_complete(item.step_id)`), immediately after the split that created the children. The `is_subloop=True` field comment — "collapses back to parent as one COMPRESS" (`der_loop.py:92`) — describes a LABEL consumed elsewhere for accounting (REQ-19's "COMPRESS" sense), not an aggregation or handoff mechanism; nothing reads a child's result back into a parent-scoped structure before the parent's own completion.

**Acceptance Criteria:**

- AC1: WHEN a growth-width split creates sub-loop children (`_split_step`, `agent_kernel.py:6659-6680`) THEN THE SYSTEM SHALL attach a compressed footprint to each child carrying THREE parts, per the user's Decisions-Locked framing:
  - **Understanding** — what has already been learned for this goal across ALL prior attempts, not a truncated sample of them.
  - **Awareness** — the goal itself (`objective_anchor` / `expected_output`), so the child knows what "done" means.
  - **Direction** — what remains to be done, and what has already been ruled out, so the child does not re-attempt a path already closed.
  Coverage SHALL be complete for the goal; the bound in AC2 is on COST, never on coverage. Truncating what the footprint covers in order to stay small is an explicit FAILURE of this requirement.
- AC2: THE footprint's token cost SHALL be bounded and SHALL NOT grow linearly with the number of tool calls it summarises. Illustratively (the user's own example, numbers arbitrary): a footprint covering 20–100 tool calls SHALL be recallable without re-paying anything close to the token cost of those calls. This is the compression property — a footprint that grows in proportion to the history it covers has not compressed anything and fails AC2 even if it fits a cap.
- AC2b: THE compression ratio and the cost cap SHALL be chosen from MEASURED data via REQ-18's instrumentation — how much a child actually re-derives without a footprint, and what coverage it needed — NOT guessed up front and hardcoded. A constant chosen before measurement is the defect pattern this spec exists to remove; record the measurement and the chosen value together.
- AC3: THE footprint SHALL survive DCP message pruning (`backend/agent/dcp.py`) — it SHALL be carried on the `QueueItem`/execution-ledger record itself (durable structured data), not solely in the LLM-visible message history that DCP is free to prune.
- AC4: A child step that resumes after a pruning pass (or after a restart, per REQ-9) SHALL be able to reconstruct "what has been done, where it is going, and what remains" from its footprint plus the existing `TaskRecord`/`ExecutionAttempt` ledger (REQ-2, REQ-9), without needing the full unpruned conversation history.
- AC5: THIS requirement SHALL reuse REQ-9's lifecycle/resume machinery and REQ-7's memory contract for the footprint's persistence and retrieval; it SHALL NOT introduce a new, parallel storage mechanism.

**Edge Cases:** A split with `width=3` (max fan-out) — footprint cost is paid three times, must still stay bounded per-child; a child that itself splits again (nested sub-loop, up to `MAX_DEPTH=3`) — footprint SHALL compose without growing unbounded across depth; a child created just before the parent's own attempt is recorded (ordering with REQ-2's ledger write); a footprint whose referenced memory/coordinate entry is later pruned or unavailable — the child SHALL degrade to its inherited text fields rather than fail.

### REQ-22: Trust is a first-class axis, separate from verification

**User Story:** As IRIS's memory, I want to be able to hold a result that is `answered=true` (it satisfied the assertion) and `trust=untrusted` (it came from outside the user) AT THE SAME TIME, because a well-verified answer sourced from an untrusted external page is not the same thing as a well-verified answer the user typed themselves — and content digested into memory from crawls and HAR captures comes from the outside world, which is exactly where prompt-injection and other attack vectors originate.

**Verified — the authority already exists and SHALL be adopted, not redefined:** `backend/memory/mycelium/kyudo.py:40-51` (`HyphaChannel` — `UNTRUSTED=0`, `EXTERNAL=1`, `VERIFIED=2`, `USER=3`, `SYSTEM=4`); `:89-121` (`CellWall` — zone permeability; `REFERENCE_ZONE` accepts any channel including `UNTRUSTED`, `TRUSTED_ZONE`/`SYSTEM_ZONE` do not); `:159-179` (`RagIngestionBridge` — hardcoded assignment rules, no override path; `:177` "EXTERNAL and UNTRUSTED channels may NEVER write the `conduct` space"). `backend/memory/mycelium/interface.py:667-684` (`ingest_document_data`) routes `trust=="untrusted"` to `HyphaChannel.EXTERNAL`, which writes only `toolpath`/`REFERENCE_ZONE`, and explicitly excludes untrusted sessions from crystallization. This is not a proposal — it is already partially wired for web content specifically: `specs/web-search-unified` REQ-22 ("PacMan Trust Persistence," already implemented, `specs/web-search-unified/tasks.md` T11 `[x]`) already tags every `crawler_query` fragment `trust:"untrusted"` before it reaches pacman (`backend/agent/tool_bridge.py:2093`, `:2289`) and forbids storing web fragments in `trusted`/`system` zones. This requirement's job is to make that authority explicit and binding for DER's own data model (`FinalRender.trust`, already present in `design.md`) and to close the gap REQ-11 identified: nothing about DER's verification score may be read as a trust input.

**Note on naming:** `specs/web-search-unified` also numbers a requirement "REQ-22" — that is an independent, per-spec numbering scheme (every spec in `specs/` restarts its own REQ-1); the two REQ-22s describe complementary, non-conflicting halves of the same trust mechanism (PacMan-side persistence tagging vs. DER-side data-model/verification-independence), not the same requirement duplicated.

**Acceptance Criteria:**

- AC1: A DER result SHALL be able to be simultaneously `answered=true`/`VERIFIED` (REQ-11's axis) and `trust=untrusted` (this requirement's axis); the two fields SHALL be independently settable and independently readable.
- AC2: External content (crawl, HAR, browser-scraped, or any tool in pacman's `_EXTERNAL_TOOLS` set) SHALL be classified `untrusted` on arrival, before any verification scoring occurs — trust is assigned by PROVENANCE (source type), never derived from a verification score.
- AC3: Admission of any content into a trusted memory zone (`TRUSTED_ZONE`/`TOOL_ZONE` per `kyudo.py`'s `CellWall`) SHALL require an explicit trust decision (a provenance-based channel assignment); a high verification score alone SHALL NEVER be sufficient to admit content into a zone above `REFERENCE_ZONE`.
- AC4: THE existing `HyphaChannel`/`CellWall` zone rules (`kyudo.py:97,177`) ARE the authority for this requirement; DER SHALL call into them (or their existing entry points, e.g. `interface.py:667-684`) rather than defining a second, parallel trust model.
- AC5: THE SYSTEM SHALL treat quarantine as the default: content ingested from an external source remains `untrusted`/`REFERENCE_ZONE`-only until it is either explicitly promoted by a provenance-based rule (not a score-based one) or remains permanently reference-only by design (the common case for web content, per the already-implemented `specs/web-search-unified` REQ-22).

**Edge Cases:** A `FAILED` (unverified) result from a `USER`/`SYSTEM` channel — trust is independent of verification in both directions, so a trusted source's poorly-verified result stays trusted but low-confidence, it does not get demoted to untrusted; a crawl result that scores `1.0` on every assertion — still `untrusted`, per AC2/AC3; a mixed-provenance synthesis (some `USER`-provided context, some crawled) — the synthesized result's trust SHALL reflect the lowest-trust contributing source unless the synthesis step itself is treated as a new provenance boundary (Open Question); an `EXTERNAL` visual-observation source (vision tools) — already hardcoded `EXTERNAL` per `kyudo.py`'s `_VISUAL_SOURCE_TYPES`, consistent with this requirement without change.

## Non-Requirements

- Rewriting Duffing/Caducean equations or changing oscillator mathematics.
- Making the scheduler read live reasoning state.
- Implementing neural embeddings or Σ coordinate recall in this feature; those remain UNEXERCISED capabilities.
- Replacing the crawler or frontend framework.
- Implementing the encoder itself — that is Phase 4's scope (`specs/phase-4-encoder`); this feature only requires that the foundation work without it and that the encoder be measured as an improvement against that baseline.
- Replacing Crawl4AI with a different crawl engine (already a Non-Requirement above via "Replacing the crawler"; restated per REQ-16/REQ-17 scope for clarity).
- Renaming the already-shipped `scorer.expand`/`scorer.condense`/`Landmark.condense` public method names to remove REQ-19's name collisions. REQ-19 requires disambiguating docstrings, not a rename; an actual rename is a separate, optional follow-up a maintainer may choose, not required by this feature.

## Open Questions

- Should final sources be the deduplicated union of all successful attempts or only the latest evidence set? Recommended: union with attempt provenance.
- Should a failed independent branch block finalization? Recommended: finalize with explicit partial status when critical branches are complete.
- What graded-scorer algorithm should REQ-11's fallback use — normalized token overlap, claim extraction, or something else — and what confidence floor should it apply? This SHALL be chosen from measured data (offline scoring against a labeled sample of paraphrased crawl results), not guessed.
- Should REQ-15 steering be able to abort an in-flight tool call, or only affect steps AFTER the currently-running one? The current step-boundary model (AC1) assumes the latter; aborting mid-call would require a cancellation contract with the tool bridge that does not exist today.
- What SHALL REQ-21's sub-loop footprint contain, precisely, and what is its size bound? This SHALL be chosen from measured data — e.g. sampling actual `step_result`/`description` lengths across a representative task set to set a defensible token cap — not guessed. A starting candidate (objective_anchor + last-attempt summary + one coordinate reference) is described in REQ-21 AC1 but is not itself the bound.
- Are the 182 existing `der_commits` rows in `.mcm/coordinates.db` (REQ-20) migrated into `backend/data/memory.db`, discarded, or left in place as build-memory history with no further write traffic once REQ-20 AC1 lands? This is a data-retention decision for the user/maintainer, not something to infer.
- Does trust admission (REQ-22 AC3) need an explicit scan/review step before content can ever leave `REFERENCE_ZONE`, or is provenance-based channel assignment alone (the existing `RagIngestionBridge`/`CellWall` model) sufficient, with promotion simply never happening automatically for external content? The current evidence suggests the latter (web content stays reference-only by design), but this SHALL be confirmed rather than assumed if a future requirement wants a promotion path.
