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

## Introduction
<1-3 sentences: what problem, who benefits.>

### Success criteria
- <measurable, checkable bullet>

## Requirements

### REQ-1: <Short title>
**User Story:** As a <role> I want <capability> so that <benefit>.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL <ubiquitous requirement>.
- AC2: WHEN <trigger> THEN THE SYSTEM SHALL <response>.
- AC3: IF <fault> THEN THE SYSTEM SHALL <safe response>.

**Edge Cases:**
- <empty / timeout / crash / disabled-gate>

### REQ-2: …

## Non-Requirements (Out of Scope)
- <explicit exclusions>

## Open Questions
- <deferred, non-blocking>
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
<unit / contract / integration; what each verifies>
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
```

## Workflow
1. Gather context: read the relevant code, ask clarifying questions ONE at a time
   (brainstorming-style) before writing.
2. Decide scope: which requirements are in/out.
3. Write `requirements.md` first (EARS + user stories + edge cases).
4. Write `design.md` (architecture, mermaid, data models, decisions).
5. Write `tasks.md` (waves, each linked to a REQ).
6. Report the file paths and a one-line summary of each artifact.

## Quality bar
- Every SHALL statement is testable.
- No implementation file paths in requirements.md except where the requirement
  names a module that MUST exist.
- design.md has at least one mermaid diagram.
- tasks.md tasks are small enough to check off independently and reference REQ IDs.
