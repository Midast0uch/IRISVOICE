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
- <measurable, checkable bullet>

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
- [ ] T1 (REQ-1, REQ-2): <task> — <file>
- [ ] T2 (REQ-3): <task> — <file>

## Wave 2 — Integration
- [ ] T3 (REQ-4, REQ-5): <task> — <file>

## Wave 3 — Verification
- [ ] T4 (REQ-28): contract tests — <test files>

## Dependency / parallelization notes
- <which waves are backend-independent and may run parallel with frontend; which tasks
 must land before others (e.g. a communication hook depends on the committed-outcome
 record existing)>
```

## Workflow (STRICT ORDER — the quality is in steps 1-2)
1. **Verify against actual code BEFORE writing.** Read the real modules the feature
   touches. Trace the actual control flow. If a design audit / blueprint / doc exists,
   do NOT trust its "as-built" claims — auditors are frequently wrong or stale. For
   every claimed gap/finding, classify it as REAL GAP / ALREADY FIXED /
   BLUEPRINT-DIVERGENT / CANNOT VERIFY, with file:line evidence. Establish a green
   test baseline first and distinguish real breaks from stale-test artifacts. A spec
   written without this step is how silent drift and phantom requirements enter.
2. **User-in-the-loop decision gates.** Surface Open Questions explicitly and let the
   user resolve UX / communication / threshold decisions. Capture each resolution back
   into the spec (a "Decisions Locked" section), not just in chat. The user's domain
   calls are the highest-value inputs and must be written into requirements, never
   guessed. Preserve the architecture the user values; target only the broken/regressed
   layers.
3. Decide scope: which requirements are in/out (Non-Requirements section).
4. Write `requirements.md` first (EARS + user stories + edge cases + verification
   evidence + observability requirement).
5. Write `design.md` (architecture, mermaid, data models, decisions, contract+behavioral
   testing strategy).
6. Write `tasks.md` (waves, each linked to a REQ, with parallelization notes).
7. Report the file paths and a one-line summary of each artifact, plus the REAL/STALE
   classification summary from step 1.

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

## Quality bar
- Every SHALL statement is testable AND carries verification evidence (above).
- No implementation file paths in requirements.md except where the requirement
  names a module that MUST exist.
- design.md has at least one mermaid diagram AND a Testing Strategy using the
  contract + behavioral + intertwined + CDD-harness model (see below).
- tasks.md tasks are small enough to check off independently, reference REQ IDs, and
  note which waves may run in parallel.

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
- Document this standard in the project's CLAUDE.md and AGENTS.md if not already present.
