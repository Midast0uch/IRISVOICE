# IRIS — Goals and Roadmap

**Location:** `.mcm/GOALS.md` (moved from `bootstrap/GOALS.md` on 2026-09-30). The previous
157 KB roadmap is archived at `.mcm/GOALS-archive-2026-09-24.md` — domain specs, gate
checklists and incident history live there; do not plan from its status lines.

**Read order for any session:** this file (the WHY and WHERE) → `docs/audits/2026-09-29/PROGRESS.md`
(START HERE = the current work order; Standards = what must not regress) → the handoff pins named
there → the app-testing skill (`.opencode/skills/app-testing/SKILL.md`, Mode A) before you
validate anything.

Status vocabulary used below (same rule as `docs/CADUCEAN_ARCHITECTURE.md`): **VERIFIED**
(measured in a live run or a test that can fail, with the evidence named) · **CARRIED** (copied
from the archive, NOT re-verified since 2026-09-24) · **OPEN**.

---

## 1. Objective anchor (never changes)

Build IRIS until it can run fully autonomously: receive tasks through its own interface, execute
them using its own backend, and improve itself over time without external scaffolding.

## 2. Completion condition

**IRIS ships itself** (Domain 17, the Self-Coding Agent = Gate 3): IRIS uses its own agent kernel,
file tools and DER loop to write, test and commit its own remaining features without external AI
assistance. Gate 4 (memory visualization: the dashboard becomes a visual Mycelium decoder) is the
graduate condition; its spec is provided after Gate 3 is verified.

At completion, the MCM build graph (`.mcm/coordinates.db`) transfers to the application's runtime
store, **`data/memory.db` (the primary app store — owner, 2026-09-30)**, via the one human-run step
in CLAUDE.md ("WHAT DONE LOOKS LIKE"). The old `bootstrap/coordinates.db` is retired and must not
be read; its startup copy path stays gated off (`IRIS_BOOTSTRAP_TRANSFER`, default 0) — that copy
is what put ~1M unused MCM `graph_edges` rows into `data/memory.db`.

## 3. How progress is proven (the standard, since 2026-09-30)

A goal item is done when a measurement says so, not when code exists:

1. **Real tasks through the real app** — `evals/run_evals.py` (coding group: 15 tasks with hidden
   tests; research group: 6). Pass flags and `reply_s` (time to the reply text).
2. **Causes, not guesses** — in-process stack dumps (`IRIS_STACK_DUMP_S=4` →
   `scripts/stackdump_summary.py`) and `EXPLAIN QUERY PLAN` on answer-path queries.
3. **Guarded standards** — each measured win gets a pin, a row in PROGRESS "Standards", and a
   guard proven to fail on the old state (contract test on the structural cause, or
   `evals/standards.json` checked on every run; the runner exits 5 on a regression).

Details: CLAUDE.md "BUILD + VERIFY IRIS — THE MEASURED LOOP" and the app-testing skill, Mode A.

## 4. Where it stands (2026-09-30)

VERIFIED this audit (commits 6c34c569 … 8655ff40 on `feat/agent-multi-step-tool-execution`):
- **Coding eval 15/15** (baseline 0/15); full group 18 min, replies 14-145 s, median ~50 s
  (`evals/results/20260930-065124.json` → `evals/standards.json`).
- **Multi-step tool execution (Domain 20's core)**: in developer mode every tool-less DER step runs
  `node_executor.run_node` — a bounded Brain tool loop that sees the user's request word for word.
- **Answer-path latency**: per-step physics on its own ordered lane with fold-back at shape
  decisions; ledger rows on one ordered lane; the two cold full-table scans indexed. Standards
  S1-S8 (PROGRESS).
- **TTS ready with the backend**: `/health` 503 until the worker is warm; concurrent-spawn hang
  fixed.
- Research group: **OPEN** (1/6 at baseline, not re-run).

## 5. Gates

| Gate | Goal | Status |
|---|---|---|
| 1 — Developer Mode | frontend + backend together; local GGUF on GPU; stable inference | CARRIED: G1.1-G1.5 verified; G1.6-G1.8 need e2e confirmation. G1.1 (`/health` 200) now also means TTS is ready. Re-verify with the app-testing skill. |
| 2 — Launcher + Developer Mode | launcher, Personal/Developer modes, isolated worktree, merge/discard | CARRIED: Domain 13 partial ([13.2] not started, [13.5] partial) |
| 3 — Self-Coding Agent (Domain 17) | IRIS writes/tests/commits its own features | OPEN — no longer blocked by missing multi-step execution (see §4); measure it with a self-edit eval task set |
| 4 — Memory visualization | dashboard = visual Mycelium decoder | OPEN — spec after Gate 3 |

## 6. Domains (status; details in the archive)

| Domain | Status |
|---|---|
| 1 DER loop gaps · 2 Voice pipeline · 5 Mycelium stubs · 6 Frontend quality · 10 Performance/memory · 16 Backend stability · 18 C++ hybrid core | CARRIED ✓ complete |
| 19 Caducean v2 | CARRIED ✓ complete; the physics now runs on its own lane (VERIFIED, S3) |
| 20 Agent multi-step tool execution | VERIFIED core delivered (run_node, coding 15/15); remaining: `plan_update` tool, tool-model argument repair, personal-mode research via run_node, turn protocol/store (execution audit Phase 2 rest + Phase 3) |
| 21 Caducean scheduling + kernel unification | CARRIED "built, awaiting live verification" — the phase gate is live (`IRIS_PHASE_SCHEDULER=1`); priority lane / coupling / batch still FLAG-OFF |
| 17 Self-Coding Agent | OPEN (Gate 3) |
| 3 Vision · 4 Skills · 7 Backend quality · 8 Distribution · 11 PiN verification · 12 MCP storage · 13 Launcher · 14 CLI toolkit + crawler · 15 Linux build | CARRIED partial / not started — see the archive before starting any of them |
| 9 Advanced features | not before 2-8 complete |

## 7. Current work order

The live, ordered list is PROGRESS.md "Next work". At the time of this move:
1. Verify the disk move and record Standard S9 (cold start).
2. Owner decisions in MCM `pin_22b078571d73`: make the topology halt live at the fold-back;
   build indexes off the startup path; attribute the ~5 GB in `data/memory.db` (lead: the
   `graph_edges` rows above).
3. Oracle: reconcile the two calibration instruments, then calibrate `tool_choice` (the one
   near-flip); give the Oracle only decisions that measurably pay.
4. Turn-end bookkeeping onto an ordered lane; the per-launch `__pycache__` purge (item D5).
5. Reply surface Phase A; execution audit Phase 2 rest, Phase 3, the live execution matrix.

### 7a. NEXT after the audit work items: ONE memory program - CLM rubber band + Wormhole/Aperture/NodeChains (owner, 2026-09-30)

These ship TOGETHER (owner): they are one valve seen from two sides and they learn from one stream.
- CLM (`docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`; arXiv 2609.37725,
  github.com/facebookresearch/context-language-models): the live context window shrinks and
  stretches back on demand - the model edits a live VIEW, the record stays append-only,
  placeholders carry the address to re-expand. Decides what LEAVES the window. Replaces DCP.
- WORMHOLE + APERTURE + NODE CHAINS (`specs/wormhole-aperture/`, Draft, not implemented, partly
  stale - nodes changed; refresh against the code first): Stage A Wormhole (state hash of quantized
  Sigma + domains -> hex neighbours -> hyperedges with Beta-Bernoulli posteriors; cause and outcome
  lattices as recall axes, REQ-46), Stage B Aperture (single-slot, boundary-claimed delivery -
  decides what ENTERS the window), Stage C NodeChains (successful node paths become chains; pivots
  are events; variants from proven pivots). Node chains are the proof that curation worked.
- SHARED FOUNDATION (build and MEASURE first): the event alphabet `docs/Design/EVENT_TAXONOMY.md`
  (closed lattices; owner review pending) + Wave E typed events and the landmark policy
  (`specs/research-memory-chain-browser/` D9, built 2026-09-30) + a meaningful Sigma (REQ-8,
  built; live eval guard pending). How well the aperture works is decided by how well events and
  landmarks are curated (owner) - measure curation quality (EVENT_TAXONOMY section 8) before
  Stage A-C build on it.
STARTS WHEN: DER-DAG execution, websearch and developer mode are foundationally good, and the
coordinate events in the memory store are meaningful and trustworthy.

### 7b. LATER (after 7a, once there is a significant user base): the hive network (owner, 2026-10-01)

A Nostr + Tailscale network where users and their agents share bugs, fixes and features - a
message board of understanding, like Buzz (owner's analogy: the spiders of "Children of Time"
passing learned understanding between individuals). It works because every IRIS runs the same
memory and DER-DAG executions: the closed event alphabet (`docs/Design/EVENT_TAXONOMY.md`) makes
one user's node chains and cases readable by every other user - the alphabet IS the protocol
(version it with `schema_version`). Nostr signs every event (provenance per peer); Tailscale gives
private meshes for trusted groups; `landmark_bridges` already has remote project/instance fields.
Three rules decide whether it works - keep the design compatible with them now:
1. SHARE UNDERSTANDING, NOT DATA: error signatures, chain sequences in the alphabet, evidence
   counts. Never paths, code, page text or personal content (event payloads already hold
   references, not content).
2. REMOTE KNOWLEDGE IS A HINT, NEVER PROOF: a shared fix enters as a CANDIDATE, counts at most as
   `recurrence` evidence, and becomes a landmark only after it passes LOCALLY (test, completion,
   user). Otherwise one bad or malicious peer spreads a false "verified fix" to everyone.
3. TRUST PER SOURCE: score each peer by how often its shared fixes held up locally - the same
   Beta-Bernoulli machinery that scores a recall (specs/wormhole-aperture REQ-4).

### 7c. LATER (after the developer-mode CLI design): IRIS builds upon itself (owner, 2026-10-01)

Not a priority now; it becomes one once developer mode (CLI design etc.) is finished.
- The agent's sandbox is a COMPLETELY SEPARATE REPO from the main one - not a `git worktree` of
  it. (Today's worktree was a full checkout of this repo, created on every switch to developer
  mode: 13-17 min of hard-disk work, unbounded, and it ran across eval tasks.)
- Creating it ALWAYS asks the user first (done 2026-10-01: the mode switch creates nothing; the
  developer prompt makes the agent ask before it edits IRIS source or creates a sandbox).
- To design: the flow by which the agent builds on itself and pushes updates seamlessly - from
  the sandbox repo, through the measured loop (evals, standards, landmarks), to the user's
  approval, to the main repo - without the agent ever writing the live codebase directly.

## 8. Machine facts that shape every measurement

- `C:` is a 97%-full 7200 rpm hard disk (repo, Python, `data/memory.db`); `D:` is an NVMe SSD
  (LM Studio models via junction, HF cache via `HF_HOME`). Cold reads are 10-20× warm reads —
  measure cold separately, never mix.
- The Brain is a cloud model (`gemma4:31b-cloud` via Ollama); its per-call time varies (13-19 s
  for the same planning call), which is why wall-clock standards carry a stated tolerance.
