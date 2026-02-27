---
name: kiro-spec
description: >
  Run the Kiro-style spec-driven development workflow to transform a feature idea into a structured,
  executable implementation plan. Use this skill whenever a user wants to plan a feature, design a
  system, spec out a project, or avoid "vibe coding". Also trigger when the user says things like
  "help me plan this feature", "let's spec this out", "I want to build X", "create a dev spec",
  "write a spec for", or "break this into tasks". This skill produces three canonical deliverables:
  requirements.md, design.md, and tasks.md — and should be used any time structured planning
  before coding would help.
---

# Kiro Spec Workflow

Transform a raw idea into a structured, executable implementation plan using the 3-phase Kiro spec workflow. This replaces "vibe coding" (prompting until something works) with a disciplined, reviewable plan before any code is written.

---

## The 3 Phases

### Phase 1 — Requirements (`requirements.md`)
Define **what** to build, not how. Written as user stories with acceptance criteria in EARS notation.

### Phase 2 — Design (`design.md`)
Define **how** to build it. Architecture decisions, data models, sequence diagrams, key technical considerations.

### Phase 3 — Tasks (`tasks.md`)
Define **the steps** to build it. Ordered, discrete, dependency-aware implementation tasks with clear done criteria.

---

## Workflow Instructions

### Step 0: Understand the Idea
Before writing anything, make sure you understand:
- What is the user trying to build?
- Who are the users / what problem does it solve?
- Are there any known constraints (tech stack, integrations, time)?

Ask clarifying questions if needed. Don't start writing specs until you have enough to be useful.

---

### Step 1: Write `requirements.md`

Use this structure:

```markdown
# Requirements: [Feature Name]

## Overview
1-2 sentence description of what this feature does and why.

## User Stories

### [Story Title]
**As a** [type of user]
**I want to** [action]
**So that** [benefit/outcome]

#### Acceptance Criteria
- WHEN [condition] THE SYSTEM SHALL [behavior]
- IF [condition] THEN THE SYSTEM SHALL [behavior]
- THE SYSTEM SHALL [always-on behavior]
```

**EARS notation rules:**
- `WHEN [trigger] THE SYSTEM SHALL [response]` — event-driven behavior
- `IF [condition] THEN THE SYSTEM SHALL [response]` — conditional behavior  
- `THE SYSTEM SHALL [behavior]` — always-active requirement
- `WHILE [state] THE SYSTEM SHALL [behavior]` — state-based behavior

Aim for 3–8 user stories. Each story should have 2–5 acceptance criteria. Keep criteria testable and specific.

---

### Step 2: Write `design.md`

Use this structure:

```markdown
# Design: [Feature Name]

## Overview
High-level summary of the technical approach.

## Architecture

### Components
Description of key components and their responsibilities.

### Data Models
Key data structures, schemas, or types.

### Sequence Diagrams
Use Mermaid sequence diagrams for key flows:

\`\`\`mermaid
sequenceDiagram
  actor User
  participant Frontend
  participant API
  User->>Frontend: action
  Frontend->>API: request
  API-->>Frontend: response
\`\`\`

## Key Technical Decisions
- **Decision**: rationale
- **Alternative considered**: why rejected

## Error Handling
How failures and edge cases are handled.

## Dependencies
External libraries, APIs, or services required.
```

---

### Step 3: Write `tasks.md`

Use this structure:

```markdown
# Tasks: [Feature Name]

## Implementation Plan

- [ ] 1. [Task title]
  - What to do (specific, actionable)
  - Done when: [concrete done criteria]
  - Depends on: [none / task N]

- [ ] 2. [Task title]
  - What to do
  - Done when: [criteria]
  - Depends on: task 1
```

**Task writing rules:**
- Each task should be completable in 1–4 hours
- Order tasks by dependencies (nothing blocked on something later in the list)
- Start with foundational tasks (data models, interfaces) before implementation
- Include testing tasks explicitly
- Be specific enough that someone could hand the task to another dev

Aim for 8–20 tasks for a typical feature.

---

## Output

At the end of all 3 phases, present the three files as downloadable `.md` files. Summarize:
- Number of user stories and acceptance criteria
- Key architectural decisions made
- Number of tasks and estimated scope

Then ask: *"Would you like to refine any phase before moving to implementation?"*

---

## Proactive Communication During Spec Writing

Never guess or push through uncertainty during planning. Surface ambiguity early — it's much cheaper to resolve in the spec than during implementation.

### When the idea is unclear
Don't pepper the user with questions. Make your best interpretation, draft the requirements, and ask them to review:
> "I've drafted requirements based on my understanding — does this capture what you had in mind, or should we adjust before moving to design?"

### When requirements conflict
Surface conflicts immediately rather than picking one silently:
```
⚠️ Conflict detected between two requirements:
- Story 2 says: "THE SYSTEM SHALL always require login"
- Story 4 says: "THE SYSTEM SHALL allow guest checkout"

These may contradict each other. Options:
A) Guest checkout bypasses login (scope login to account features only)
B) Login is always required (remove guest checkout)
C) Make login optional but encouraged

Which did you intend?
```

### When a design decision has real tradeoffs
Don't silently pick an architecture. Present the fork:
```
🔀 Design decision needed:

Option A: [approach] — better for [scenario], but [tradeoff]
Option B: [approach] — better for [scenario], but [tradeoff]

Which fits your needs better?
```

### When a task is too vague to be actionable
Flag it before finalizing tasks.md:
> "Task 6 ('Set up auth') is too broad to implement directly. Should I break it into sub-tasks, or can you give me more detail on what's needed?"

---

## Tips

- **If the user is vague**: Write a draft requirements.md based on your best interpretation, then ask them to review it before proceeding to design. This is faster than a long Q&A.
- **If the feature is small** (< 1 day of work): You can combine design and tasks into a single lighter `spec.md` file instead.
- **If the user already has requirements**: Skip Phase 1 and start from Phase 2.
- **If the user just wants tasks**: Ask for enough context to write useful tasks, then produce `tasks.md` only.
