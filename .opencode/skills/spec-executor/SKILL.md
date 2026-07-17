---
name: spec-executor
description: Systematically execute a Kiro-style three-file spec (requirements.md + design.md + tasks.md) as a coherent implementation. Reads ALL THREE files (not just tasks.md), reconciles REQ IDs / design decisions / task waves, executes wave-by-wave with the AGENTS.md quality check, records MCM events+tests, anchors PiNs, and crystallizes landmarks. Invoke after mcm_compress() to begin implementation from a clean context. Triggers on "execute the spec", "start implementation", "run the spec", "begin waves", or post-compaction "implement the spec".
---

# Spec Executor

Executes a Kiro-style spec as a single coherent implementation. The critical rule:
**read all three files, not just tasks.md.** `tasks.md` is the execution order;
`requirements.md` is the contract (what MUST be true, in EARS); `design.md` is the
HOW (architecture, diagrams, decisions, verification strategy). A task is DONE only
when its linked REQ is satisfied per requirements.md AND the design.md decision is
honored.

## When to use
- User says "execute the spec", "start implementation", "run the spec", "begin
  waves", or post-compaction "implement the spec".
- A `specs/<feature>/` directory exists with `requirements.md`, `design.md`,
  `tasks.md`.

## Invocation after compaction
This skill is designed to be invoked RIGHT AFTER `mcm_compress()` (the user's
"compress then implement" flow). After compress, context is pruned; this skill
re-loads the spec from disk (not from memory) so implementation starts from the
authoritative files. If you cannot recall the spec path, run
`mcm_recall("<feature> spec")` or `mcm_recall("spec path")` to recover it.

## Execution protocol (STRICT ORDER)

### Phase 0 — Load all three files
1. Read `requirements.md` fully. Build a REQ-ID → acceptance-criteria map.
2. Read `design.md` fully. Note: architecture, mermaid diagrams, Key Decisions
   (D1..Dn), UX/UI/Audio Layer Map, Resilient Transport, Verification Strategy
   (4 tiers). These decisions OVERRIDE any tempting shortcut.
3. Read `tasks.md` fully. Note the waves and each task's `(REQ-x, REQ-y)` links.
4. Cross-check: every REQ in requirements.md should be covered by ≥1 task; every
   task should link to ≥1 REQ. If a gap exists, note it but do NOT silently skip —
   flag it to the user.

### Phase 1 — Build the execution ledger
- Create a todo list (`todowrite`) with one item per task, tagged by wave.
- For each task, annotate the linked REQ IDs and the design decision(s) it must honor.
- Identify cross-layer/seam tasks (those touching ≥2 layers) — these need the
  Tier 3/4 verification from design.md, not just unit tests.

### Phase 2 — Execute wave by wave
- Do waves IN ORDER (Wave 1 before Wave 2, etc.) because later waves depend on
  earlier ones.
- Within a wave, tasks may run in parallel IF they touch disjoint files AND no
  task edits a file another task in the same wave edits. Otherwise serialize.
- For EACH task:
  1. `navigate(file)` (MCM) before editing — respect topology/confidence.
  2. Implement to satisfy the linked REQ's acceptance criteria EXACTLY (EARS is the
     requirement; do not write code to match a weaker interpretation).
  3. Honor the design.md decision for that area (e.g. if D4 says "one atomic tool",
     do not add an internal research loop).
  4. Run the **AGENTS.md QUALITY CHECK** before any test run:
     [ ] no unnecessary work in hot paths  [ ] heavy imports lazy
     [ ] error handling complete  [ ] resources cleaned up
     [ ] no shared mutable state across sessions  [ ] memory bounded
     [ ] async/sync boundary correct  [ ] structured logging
     [ ] nothing can crash and block a user response
  5. Write/run the test from design.md Verification Strategy for that layer:
     - Tier 1 (unit) for layer-internal tasks.
     - Tier 2 (contract) for boundary tasks — real instance + stubbed collaborator
       + event-bus subscription asserting emitted events; anchor to a PiN.
     - Tier 3 (integration) for cross-layer seam tasks — in-process, MOCK the fetch
       engine, never hit live web.
     - Tier 4 (behavioral) only when the full path is wired and a backend can run.
  6. On test PASS: `record_test(file, 'pass', covers=[...])`, `record_edit(file)`,
     and `pin_add(title='<feature>:<req>', type='decision', content='what held')`.
  7. On test FAIL: fix the CODE, not the test (the test is the requirement). After
     fix, re-run. If a design decision is wrong, STOP and ask the user — do not
     mutate requirements.md silently.

### Phase 3 — Verify the whole feature (not just tasks)
- After the last wave, confirm EVERY REQ in requirements.md has ≥1 passing test
  that exercises its acceptance criteria. If a REQ has no test, write one (Tier 1–3)
  before declaring done.
- Confirm the design.md Verification Strategy tiers are all represented.
- Run the project's existing suite (pytest / npm test / tsc) to catch regressions.

### Phase 4 — Record & crystallize
- `mcm_define_feature(name='<feature>', seed_files=[...], thread_id='<session>')`.
- For each verified REQ cluster, `mcm_cad_mcm_crystallize_landmark(feature_id, name, description)`.
- `mcm_compress(active_task='<feature> implementation complete', active_files=[...])`.

## Hard rules
- NEVER modify requirements.md or design.md to make code pass. If reality contradicts
  the spec, STOP and surface it. The spec is the contract; code conforms to it.
- NEVER hit live web in Tier 1–3 tests. Mock the fetch engine.
- A task is NOT done because tasks.md says so — it is done when its REQ's EARS
  criteria are proven by a passing test.
- Respect DER blueprint invariants (single operator, `u/ξ` physics, `ExecutionMode`
  display-only, narration lock) — these are non-negotiable constraints from
  design.md Context, not optional.

## Output to user
After each wave: one-line status per task (done / blocked / flagged). After Phase 3:
a REQ-coverage table (REQ-ID → test tier → pass). After Phase 4: confirmation of
crystallization.
