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
- ALSO use the Phase -1 (Spec Crafting) discipline whenever a spec is being
  CREATED or is suspected stale — a spec built without verifying against the
  actual code is how silent drift and phantom requirements enter the system.

## Invocation after compaction
This skill is designed to be invoked RIGHT AFTER `mcm_compress()` (the user's
"compress then implement" flow). After compress, context is pruned; this skill
re-loads the spec from disk (not from memory) so implementation starts from the
authoritative files. If you cannot recall the spec path, run
`mcm_recall("<feature> spec")` or `mcm_recall("spec path")` to recover it.

## Phase -1 — Spec Crafting (do this BEFORE Phase 0 if the spec is new or stale)
A spec is only as good as its grounding in the actual code. The best specs we
have built followed this discipline — it is what separates a real contract from
a wish-list. Run it before execution whenever the spec has not been verified
against the as-built system.

### Phase -1.0 — Symbol Grounding Gate (BLOCKING, run BEFORE writing any spec file)
The single most common spec failure is writing blueprint assumptions as if they
were verified code facts: inventing method names that don't exist, asserting the
wrong capture layer, or citing a "pattern to follow" that isn't there. This gate
converts the advisory "verify against code" into a checkable artifact so those
drifts are caught at write-time, not at implementation time.

**Before writing requirements.md / design.md / tasks.md, produce a grounding
table** (keep it in the spec dir as `grounding.md`, or pin it). For EVERY
function / class / method / WS-message-type / executor-value the spec will NAME,
record one row:

| symbol the spec will name | status | evidence (file:line) | if-new: which task creates it |
|---|---|---|---|
| `SourceRegistry.report_fetch_outcome` | DOES NOT EXIST | source_registry.py:91 has `penalize_url(url,topics)` | T0c reuses `penalize_url` |
| `FetchBackend.fetch` (HAR capture pt) | EXISTS but WRONG LAYER | orchestrator.py:55 returns batch `CrawlResult`; real HTTP in crawler_engine.py `CrawlerEngine.crawl()` | T0a captures inside engine |
| `get_documents` WS handler | DOES NOT EXIST | iris_gateway.py elif-chain has no such handler; pattern `reformat_document_ack` at :8194 | T3 |

Rules:
- A symbol is **EXISTS** only if you grepped the repo and have a `file:line`.
  "I think it's there" / "a prior summary said so" is NOT evidence.
- A symbol is **DOES NOT EXIST** only if you grepped and confirmed absence —
  then name the task that will create it. Never invent a NEW symbol name that
  collides with an existing one (prefer reusing the existing `penalize_url` over
  creating `report_fetch_outcome`).
- For every "existing pattern to follow" claim (WS response shape, executor
  dispatch, ALTER TABLE idempotency), cite the `file:line` of that pattern.
- **No spec file may be written until this table exists and is reviewed.** If a
  spec file is already written, run this gate retroactively and FIX any
  BLUEPRINT-DIVERGENT rows before Phase 0 (this is what caught the
  document-rehydration divergences: `report_fetch_outcome`→`penalize_url`,
  `executor="internal"`→real dispatch type, `FetchBackend.fetch`→`CrawlerEngine.crawl()`).

1. **Verify against actual code, not the blueprint.** Read the real modules the
   spec/blueprint claims exist. Trace the actual control flow. A design audit
   (against a blueprint or doc) is NOT proof of as-built behavior — auditors are
   frequently wrong or stale. For every claimed gap/finding, classify it as:
   REAL GAP / ALREADY FIXED / BLUEPRINT-DIVERGENT / CANNOT VERIFY, with
   file:line evidence. Do not trust "the doc says it's done."
2. **Establish a green baseline first.** Run the existing test suite BEFORE
   proposing changes. Distinguish real code breaks from stale-test artifacts
   (relative-path bugs, outdated mocks). Report the true baseline; do not let
   "3 failures" hide behind "the suite is green" — verify each failure's cause.
3. **User-in-the-loop decision gates.** Surface Open Questions explicitly and let
   the user resolve the UX / communication / threshold decisions. Capture each
   resolution back into the spec (not just in chat). The user's domain calls
   (e.g. "narration triggers on physics events", "Pacman = subtle OrbCanvas
   particles", "post-step hook but watch latency") are the highest-value inputs
   and must be locked into requirements, not guessed.
4. **Instrument for tuning.** A good spec includes observability so the NEXT
   iteration can improve (e.g. a timestamped narration+TTS log scoped by
   conversation thread, enabling trigger-frequency analysis). Treat "how will we
   know if this is tuned right?" as a first-class requirement, not an afterthought.
5. **Preserve fundamental values; fix integrity + display.** When a blueprint is
   stale, keep the architecture the user values (single operator, u/ξ physics,
   evidence-conditioned acting) and target only the broken/regressed layers
   (learning integrity, honest display, communication discipline). Do not rewrite
   what works to fix what's broken.
6. **Write the three artifacts** (requirements.md EARS + design.md + tasks.md)
   per the kiro-spec-writer skill, then document the contract+behavioral+CDD
   testing philosophy (see Phase 2 step 5 below) in the project's CLAUDE.md and
   AGENTS.md if not already present.

### Phase 0 — Load all three files
1. Read `requirements.md` fully. Build a REQ-ID → acceptance-criteria map.
2. Read `design.md` fully. Note: architecture, mermaid diagrams, Key Decisions
   (D1..Dn), UX/UI/Audio Layer Map, Resilient Transport, Verification Strategy
   (4 tiers). These decisions OVERRIDE any tempting shortcut.
3. Read `tasks.md` fully. Note the waves and each task's `(REQ-x, REQ-y)` links.
   4. Cross-check: every REQ in requirements.md should be covered by ≥1 task; every
    task should link to ≥1 REQ. If a gap exists, note it but do NOT silently skip —
    flag it to the user. If the spec was just crafted (Phase -1), confirm the
    REAL-GAP / ALREADY-FIXED / STALE classifications were resolved and the user's
    decision gates were locked into the requirements. ALSO re-open the Phase -1.0
    `grounding.md` table and confirm every symbol named in the spec still matches
    its `file:line` evidence (no BLUEPRINT-DIVERGENT rows remain).

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
   5. Write/run the test from design.md Verification Strategy for that layer. This
      system is ONE recursive operator at four scales; bugs live in the SEAMS
      between parts, not inside them. Unit tests alone are insufficient. Use the
      contract + behavioral + intertwined model (documented in CLAUDE.md/AGENTS.md):
      - **Unit** (`tests/unit/`) for layer-internal pure logic only.
      - **Contract** (`tests/contract/`) for boundary tasks — pin every interface
        shape (backend→frontend event, agent→TTS text, loop→ledger record). Real
        instance + stubbed collaborator + event-bus subscription asserting emitted
        events; anchor to a PiN. A contract break is caught at the interface, BEFORE
        behavior.
      - **Behavioral** (`tests/behavioral/`) for cross-layer seam tasks — drive a
        FULL task through the real loop and assert EMERGENT properties (no phantom
        card, spoken ⊆ visible, failure recorded AND shown, self-tuning REJECTS the
        hack). Mock the fetch engine; never hit live web.
      - **Intertwined rule:** contract + behavioral share fixtures/assertions. Every
        behavioral gap found DECOMPOSES into the contract test that would have caught
        it — the gap becomes a permanent guard.
      - **Physics-aware:** inject Caducean u/ξ trajectory states and assert
        system-level outcome (split when oscillating, silence when converged).
      - **Standing CDD harness** (`scripts/validate_der_*.py` family): replays
        recorded trajectories through the FULL stack and asserts contracts +
        behaviors on EVERY run. This is the gap-finding instrument.
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
- `define_feature(name='<feature>', seed_files=[...], thread_id='<session>')`  — note: no `mcm_` prefix.
- For each verified REQ cluster, `crystallize_landmark(feature_id=..., name=..., description=...)`  — note: no `mcm_` prefix.
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
