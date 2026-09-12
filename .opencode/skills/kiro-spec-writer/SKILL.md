---
name: kiro-spec-writer
description: Draft Kiro-style spec-driven development artifacts (requirements.md, design.md, tasks.md) using EARS notation. Use when the user asks for a "Kiro style" spec, "EARS notation" requirements, or a three-file spec (requirements + design + tasks). Triggers on "kiro", "spec-driven", "EARS requirements", "requirements.md design.md tasks.md".
---

# Kiro Spec Writer

Produces the three canonical Kiro spec-driven development artifacts for a feature,
using **EARS notation** for requirements. Use this skill whenever the user asks for
a "Kiro style" spec, "EARS notation" requirements, or a requirements/design/tasks
split.

## When to use
- User says "Kiro style", "EARS notation", "spec it out Kiro", or wants a
  requirements + design + tasks breakdown.
- A feature is large enough to need a written requirement set before code.

## The three artifacts (ALWAYS produce all three, in `specs/<feature>/`)

1. **`requirements.md`** — WHAT the system must do. User stories + EARS acceptance
   criteria + edge cases. No implementation detail.
2. **`design.md`** — HOW it is built. Architecture, sequence diagrams (mermaid),
   data models, key decisions, error handling, testing strategy.
3. **`tasks.md`** — discrete, trackable, dependency-ordered tasks grouped into
   "waves" for parallel execution; each task linked to a requirement ID.

Do NOT mash all three into one file. Do NOT write narrative-only requirements.

## EARS notation (5 patterns — use the right one)

| Pattern | Form | Use for |
|---|---|---|
| Ubiquitous | `THE SYSTEM SHALL <requirement>` | Always-true behavior |
| Event-driven | `WHEN <trigger> THEN THE SYSTEM SHALL <response>` | Reactions to events |
| State-driven | `WHILE <state> THE SYSTEM SHALL <response>` | Behavior during a state |
| Optional | `WHERE <feature included> THE SYSTEM SHALL <response>` | Optional capabilities |
| Unwanted | `IF <condition> THEN THE SYSTEM SHALL <response>` | Fault/exception handling |

Rules:
- Use precise, testable language. No "should", "maybe", "nice to have" in SHALL
  statements.
- One requirement = one concern. Number them (REQ-1, REQ-2, …).
- Every requirement has a **User Story**: `As a <role> I want <capability> so that
  <benefit>`.
- Every requirement has **Acceptance Criteria** in EARS, numbered (1.1, 1.2, …).
- Every requirement lists **Edge Cases** (empty input, timeout, crash, gate off).

## requirements.md template

```markdown
# Requirements: <Feature Name>

## Decisions Locked
<user-resolved Open Questions — so future sessions don't re-litigate. e.g.
"Narration triggers on u/xi physics events (oscillating→converged / split / collapse),
not a timer." "Pacman = subtle OrbCanvas particles on card border, backend-triggered.">

## Introduction
<1-3 sentences: what problem, who benefits.>

### Success criteria
- <measurable, checkable bullet — aim for the BEST result, not the minimum that passes.
  Ask "what is the optimal outcome?" and set the target there; only settle for
  "good enough" when the user explicitly accepts the trade-off. Ground each target in a
  measured baseline or mark it UNVERIFIED with a live-measurement task.>

## Requirements

### REQ-1: <Short title>
**User Story:** As a <role> I want <capability> so that <benefit>.

**Verified:** <file:line traced against actual code> | OR | NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL <ubiquitous requirement>.
- AC2: WHEN <trigger> THEN THE SYSTEM SHALL <response>.
- AC3: IF <fault> THEN THE SYSTEM SHALL <safe response>.

**Edge Cases:**
- <empty / timeout / crash / disabled-gate>

### REQ-2: …

### REQ-N: Observability / tuning instrumentation
**User Story:** As the tuner I want <measured signal> so that <I can tune thresholds>.
**Verified:** NEW
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log <timestamped, scoped-by-thread signal> so trigger frequency
  is measurable.
**Edge Cases:**
- <high-volume → off critical path; missing id → fallback>

## Non-Requirements (Out of Scope)
- <explicit exclusions>

## Open Questions
- <deferred, non-blocking — resolve WITH user, then move to Decisions Locked>
```

## design.md template

```markdown
# Design: <Feature Name>

## Context
<why this exists; constraints that bound the design>

## Architecture Overview
<components + how they connect; mermaid diagram>

## Sequence / Data Flow
<mermaid sequenceDiagram for the main flow>

## Data Models
<structs / schemas with fields>

## Key Decisions
<decision, rationale, alternatives rejected>

## Ripple-Effect Map (MANDATORY — from Workflow step 2)
Every change touches more than its target module. List EVERY area the change reaches,
classified so nothing is missed:
| Area / File | Change? | Classification | Why / Evidence (file:line) |
|---|---|---|---|
| <file> | Yes / No / Contract-Lock | CHANGE NEEDED / NO CHANGE (verified) / CONTRACT LOCK | <what and why; cite proof> |
| <frontend handler> | No | NO CHANGE (verified) | <already handles new behavior — file:line> |
| <contract/event shape> | No code | CONTRACT LOCK | <pin with contract test CT-x to prevent silent break> |
Rules:
- "NO CHANGE (verified)" MUST cite the file:line proving the area already handles the
  new behavior. Do not assert "no change needed" without evidence — that is how regressions
  slip through.
- "CONTRACT LOCK" areas get a contract test ID (CT-x) in the Testing Strategy so a future
  edit can't break the interface silently.
- Include areas that are NOT modified but whose assumptions the change relies on (e.g.
  "frontend already reacts to wake_detected — verified at useIRISWebSocket.ts:652").

## Error Handling
<failure modes + EARS-style responses>

## Testing Strategy
<contract + behavioral + intertwined + physics-aware + standing CDD harness; organized
 as tests/unit | tests/contract | tests/behavioral; what each verifies>
```

## tasks.md template

```markdown
# Tasks: <Feature Name>

> Each task links to a requirement. Group into waves for parallel execution.

## Wave 1 — Foundation
- [ ] T1 (REQ-1, REQ-2): <task> — <file> — RIPPLE: <other areas this task touches or relies on>
- [ ] T2 (REQ-3): <task> — <file> — RIPPLE: <...>

## Wave 2 — Integration
- [ ] T3 (REQ-4, REQ-5): <task> — <file> — RIPPLE: <...>

## Wave 3 — Verification
- [ ] T4 (REQ-28): contract tests — <test files> — RIPPLE: <CT-x locks which interface>

## Traceability Matrix (MANDATORY — every AC accounted for)
| REQ | ACs | Covering tasks | Covering tests | Status |
|---|---|---|---|---|
| REQ-1 | AC1.1–1.4 | T1, T7 | <test files or TBD> | covered |
| REQ-2 | AC2.1 (no task — deferred: <reason + who decided>) | — | — | DEFERRED |
Every acceptance criterion in requirements.md MUST appear in exactly one row
as covered or explicitly deferred. A covered AC names the task(s) AND the
test(s) that prove it — a task without a proving test is a wish, not coverage.
A deferred AC names the reason and the decision owner; silent gaps are
spec defects, not scope discipline. Fill the Status column during writing
(projected) and re-verify it at closeout (proven).

## Wave gates (MANDATORY — no wave starts on a red gate)
Each wave ends with a gate task (TG-1, TG-2, …) that proves THAT wave's REQs:
re-run every covering test named in the matrix rows for the wave's REQs and
record green/red per AC. The next wave MUST NOT start while its predecessor's
gate is red, unless the user explicitly overrides (recorded in Decisions
Locked with the reason). A gate is per-AC, not per-task: ten green tasks
mean nothing if one AC has no proving test.

## Dependency / parallelization notes
- <which waves are backend-independent and may run parallel with frontend; which tasks
 must land before others (e.g. a communication hook depends on the committed-outcome
 record existing)>
- <which tasks are NO-CHANGE-verified areas that only need a contract test, vs. tasks
 that modify code — so reviewers see at a glance what actually changes>
```

## Workflow (STRICT ORDER — the quality is in steps 1-5)
1. **Verify against actual code BEFORE writing.** Read the real modules the feature
   touches. Trace the actual control flow. If a design audit / blueprint / doc exists,
   do NOT trust its "as-built" claims — auditors are frequently wrong or stale. For
   every claimed gap/finding, classify it as REAL GAP / ALREADY FIXED /
   BLUEPRINT-DIVERGENT / CANNOT VERIFY, with file:line evidence. Establish a green
   test baseline first and distinguish real breaks from stale-test artifacts. A spec
   written without this step is how silent drift and phantom requirements enter.
2. **Ripple-effect analysis (MANDATORY — do not skip).** A change in one module almost
   always affects others. For EVERY requirement, trace every module/file the change
   touches AND every downstream consumer that depends on the changed behavior
   (event shapes, function signatures, session/state, frontend handlers, contracts).
   Classify each touched area as: **CHANGE NEEDED** (code must be modified),
   **NO CHANGE (verified correct)** (already handles the new behavior — cite file:line
   as proof), or **CONTRACT LOCK** (behavior unchanged but the interface shape must be
   pinned by a contract test so a future edit can't silently break it). This is the
   step that prevents "fix one thing, break three others." Output the Ripple-Effect Map
   (see design.md template) and surface it to the user before writing tasks.
3. **User-in-the-loop decision gates.** Surface Open Questions explicitly and let the
   user resolve UX / communication / threshold decisions. Capture each resolution back
   into the spec (a "Decisions Locked" section), not just in chat. The user's domain
   calls are the highest-value inputs and must be written into requirements, never
   guessed. Preserve the architecture the user values; target only the broken/regressed
   layers.
4. Decide scope: which requirements are in/out (Non-Requirements section).
5. **Design Deliberation & Optimization (MANDATORY — see the dedicated section below).**
   Before writing any requirement, deliberate the most optimum design: question the
   default approach, understand WHY it exists, consider ≥2 alternatives, evaluate across
   every cost layer, and choose the BEST result — not the first workable one. Record the
   decision + rationale + rejected alternatives for design.md Key Decisions.
6. Write `requirements.md` first (EARS + user stories + edge cases + verification
   evidence + observability requirement).
7. Write `design.md` (architecture, mermaid, data models, decisions, **Ripple-Effect
   Map**, contract+behavioral testing strategy).
8. Write `tasks.md` (waves, each linked to a REQ, with parallelization notes AND a
   per-task ripple note so no dependent code is missed).
9. **Traceability matrix + wave gates (MANDATORY — the spec is not done without
   them).** Build the Traceability Matrix (see tasks.md template): every single
   AC from requirements.md lands in exactly one row as covered (task + proving
   test named) or explicitly deferred (reason + decision owner named). Then add
   one gate task per wave (TG-1, TG-2, …) proving that wave's REQs per-AC. Run
   the matrix against the spec you just wrote: any AC with no covering task is
   a spec defect — add the task, narrow the AC with user approval, or record
   an explicit deferral. NEVER leave an AC silently unmapped (that is how
   AC21.3-class gaps survive to production: modeled, unwired, unnoticed).
10. **Iterative revision loop = Amendment Protocol (MANDATORY).** After writing,
    AND on EVERY later edit to any spec file — including "just recording a
    decision" (there are no lightweight spec edits) — run the Amendment
    Protocol below: triplet rule, evidence-to-ripple, stale-reference sweep,
    and the mechanical verification. A revision that skips the protocol is how
    AC21.3-class gaps and stale ripple maps enter; the audit that catches them
    later is the most expensive possible time to find them.
11. Report the file paths and a one-line summary of each artifact, plus the REAL/STALE
    classification summary from step 1, the Ripple-Effect Map summary from step 2, and
    the Design Deliberation summary from step 5, PLUS the traceability verdict from
    step 9 (counts: ACs covered / deferred / unmapped — unmapped MUST be zero).

## Amendment Protocol (MANDATORY — runs on EVERY spec edit after creation)

Step 10 fails in practice because amendments don't feel like revisions: recording a
locked decision looks like a one-line edit, so the workflow never fires — and the
matrix silently goes stale (observed case: 8 AC10s in requirements.md vs 5 matrix
rows; ripple rows missing for cited filler sites, orb components, and the settings
path; "blocked by OQ-4" notes surviving OQ-4's resolution). This protocol fixes that.

**Trigger — AMENDMENT MODE:** you are in Amendment Mode whenever you edit ANY file
under `specs/<feature>/` after the spec's first creation — including "just recording
a decision," "just adding an AC," or "just resolving an OQ." There is no lightweight
spec edit. A decision recorded in chat but not fully landed in all three artifacts
does not exist.

**The triplet rule:** a requirements.md change is an INCOMPLETE EDIT until all three
land in the SAME edit pass:
1. the requirement / decision / AC text in requirements.md,
2. its Traceability Matrix row in tasks.md (covered with task + proving test named,
   or explicitly deferred with reason + owner),
3. its ripple impact: new or rewritten task(s) if work is implied, Ripple-Effect
   Map row(s) in design.md for every file the decision touches or cites, and a Key
   Decisions entry if a deliberation happened.
Finish the triplet before replying. Never "land the decision now, matrix later."

**Evidence-to-ripple rule:** every `file:line` cited as evidence in a decision, AC,
or Verified line MUST be classified in the Ripple-Effect Map in the same pass
(CHANGE NEEDED / NO CHANGE (verified) / CONTRACT LOCK). A cited file with no map
row is a spec defect — the map is how future edits know the file is load-bearing.

**Stale-reference sweep:** when an OQ resolves, an AC is added/renamed, or a wave is
restructured, grep the whole `specs/<feature>/` dir for the OQ id / AC pattern /
wave name and update EVERY mention: verdict lines, dependency notes, task
descriptions, gate scopes. A resolved OQ still referenced as open anywhere is a
spec defect.

**Mechanical verification (run it — 30 seconds, not by eye):**
1. Count ACs per REQ (e.g. count `AC10.x` occurrences in requirements.md vs matrix
   rows for that REQ). Every counted AC MUST have exactly one matrix row.
2. Check the verdict arithmetic: covered + deferred + unmapped MUST equal the
   counted total, and unmapped MUST be zero.
3. Check ripple coverage: every basename cited as `file:line` evidence in
   requirements.md Decisions Locked / Verified lines MUST appear in design.md's
   Ripple-Effect Map.

**Amendment Definition of Done (holds before you reply):**
- [ ] Matrix unmapped = 0; verdict arithmetic matches the fresh AC count.
- [ ] Every cited file classified in the ripple map.
- [ ] No stale OQ/AC/wave cross-references (sweep ran).
- [ ] Design Key Decisions + Testing Strategy updated if the amendment deliberated
      or named new tests (every BT-Sx/CT-Sx id exists in BOTH the tasks.md matrix
      and the design.md Testing Strategy).

## Design Deliberation & Optimization Discipline (MANDATORY for every spec)

The goal is the MOST OPTIMUM and EFFECTIVE design — the best result possible, not the
first workable one. This applies to ANY spec, at EVERY layer, from the START. Do not
write the obvious approach and discover the better one later.

### Part A — Deliberate the best approach
For every significant design decision:
1. State the **default/obvious** approach.
2. **Understand WHY it exists** — trace what problem the current/default approach solves
   before proposing to change it. Never "optimize away" something load-bearing.
3. Consider **≥2 alternatives**.
4. Evaluate each against the cost layers (Part B).
5. **Surface trade-offs** — when alternatives have real costs (latency vs memory,
   complexity vs performance), present the trade-off and let the user decide; do not
   silently pick.
6. Choose the most optimum, and record decision + rationale + rejected alternatives in
   design.md Key Decisions.

### Part B — Optimize every layer
For each decision, evaluate against ALL relevant cost layers:
- **Resource** — memory, CPU, GPU, disk, network
- **Latency** — response time, load time, time-to-first-result
- **Complexity** — code, dependencies, maintenance, cognitive load
- **Architecture** — coupling, extensibility, testability
- **Operational cost** — compute, API calls, money, energy

For each layer, apply the six deliberation questions:
1. **Necessity** — can this work be ELIMINATED entirely? The cheapest resource is the one
   never allocated; the cheapest work is the work never done.
2. **Timing** — can it be DEFERRED, BATCHED, or OVERLAPPED? (e.g. lazy-load instead of
   boot-preload; warm-on-first-use so the cost hides behind other work.)
3. **Measurement** — is the target GROUNDED IN MEASURED REALITY, or assumed? Never write
   "reduce from X to Y" without measuring X first. If you cannot measure, mark the target
   UNVERIFIED and add a live-measurement task.
4. **Completeness** — are ALL paths/sites that touch this ENUMERATED? A resource can have
   multiple init/spawn/warm-up sites; find every one.
5. **Metric** — is the success metric PRECISE, and does the chosen approach actually move
   it? (e.g. trimming reduces working set, not committed private memory — know which
   metric you target.)
6. **Verification** — is there a LIVE/REAL verification gate, not just unit tests? A
   target that passes unit tests but fails live is not done.

### Part C — The spec is a living document
- **During writing:** after each artifact, re-check the earlier ones and REVISE if a new
  finding changes a decision/requirement/task.
- **During implementation:** when implementation reveals a better approach, add a
  "refinements" wave to tasks.md and update requirements/design so the spec reflects the
  as-built optimum. Never let the spec go stale.

### Balance: optimize hard, don't over-build
Pursuing the best result must not become gold-plating. For each optimization, ask: is this
worth the added complexity? Respect YAGNI — optimize what matters, not everything.

## Required per-requirement discipline
- **Verification evidence:** every REQ carries a `Verified:` line citing the file:line
  it was traced against, or `Verified: NEW (unverified — implementation pending)`. This
  makes the spec self-documenting about what is grounded vs. assumed. A spec full of
  unverified SHALLs is a wish-list, not a contract.
- **Observability requirement:** for any feature with tunable thresholds or emergent
  behavior, include a requirement for instrumentation (e.g. a timestamped log scoped by
  conversation/thread) so the NEXT iteration can measure and tune. Treat "how will we
  know if this is tuned right?" as a first-class requirement, not an afterthought.
- **Decisions Locked section:** at the top of requirements.md, list the user-resolved
  Open Questions so future sessions don't re-litigate them.
- **Ripple-Effect Map (MANDATORY):** design.md MUST contain a Ripple-Effect Map
  (Workflow step 2) classifying every touched/downstream area as CHANGE NEEDED /
  NO CHANGE (verified, with file:line) / CONTRACT LOCK. This is the primary guard
  against fixing one area and silently breaking others. A spec without a Ripple-Effect
  Map is incomplete.

## Quality bar
- Every SHALL statement is testable AND carries verification evidence (above).
- No implementation file paths in requirements.md except where the requirement
  names a module that MUST exist.
- design.md has at least one mermaid diagram AND a Ripple-Effect Map (Workflow step 2)
  AND a Testing Strategy using the contract + behavioral + intertwined + CDD-harness
  model (see below).
- The spec records the Design Deliberation (Workflow step 5): for each significant
  decision, the default approach, ≥2 alternatives considered, the chosen optimum, and
  the rejected alternatives with rationale. A spec that states only the chosen approach
  without the deliberation is incomplete.
- Every performance/memory/latency target is either grounded in a measured baseline or
  marked UNVERIFIED with a live-measurement task. No target is written from assumption.
- tasks.md tasks are small enough to check off independently, reference REQ IDs, note
  which waves may run in parallel, AND carry a per-task RIPPLE note.
- The Traceability Matrix exists, every AC is covered or explicitly deferred
  (unmapped = zero), and each wave ends with a per-AC gate task. A spec whose
  matrix has silent gaps is incomplete no matter how good its prose.
- After ANY amendment (not just at creation), the Amendment Definition of Done
  holds: matrix unmapped = zero with verdict arithmetic matching a fresh AC
  count, every cited file classified in the ripple map, no stale cross-refs.

## Testing Strategy standard (write this into design.md)
This system is ONE recursive operator at four scales; bugs live in the SEAMS between
parts, not inside them. Unit tests alone are insufficient. Organize as:
```
tests/unit/         pure logic only (no I/O, no cross-layer)
tests/contract/     boundary pins (interface shapes, caught BEFORE behavior)
tests/behavioral/   full-loop drives (emergent properties, run system as it runs)
scripts/validate_der_*.py   STANDING CDD HARNESS — replays recorded trajectories
                            through the FULL stack; asserts contracts + behaviors EVERY run
```
- **Contract tests** pin every boundary (backend→frontend event shape, agent→TTS text
  shape, loop→ledger record shape). A contract break is caught at the interface.
- **Behavioral tests** drive a FULL task through the real loop and assert EMERGENT
  properties (no phantom card, spoken ⊆ visible, failure recorded AND shown, self-tuning
  REJECTS the hack).
- **Intertwined:** contract + behavioral share fixtures/assertions. Every behavioral gap
  found DECOMPOSES into the contract test that would have caught it — the gap becomes a
  permanent guard.
- **Physics-aware:** inject Caducean u/ξ trajectory states and assert system-level
  outcome (split when oscillating, silence when converged, narration fires on band crossing).
- **Live-verification gate:** for any performance/memory/latency target, include a live
  measurement step (e.g. a script that measures the real running system) so targets are
  validated against reality, not just unit/contract tests. A target that passes unit tests
  but fails live is not done.
- Document this standard in the project's CLAUDE.md and AGENTS.md if not already present.
