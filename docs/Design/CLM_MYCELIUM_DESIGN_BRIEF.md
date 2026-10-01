<!--
SAVED 2026-09-30 (session 64237209). Owner: "save this md to the project and make changes if you need to".

TERM MAP - read before using this brief. This brief was written partly in the vocabulary of the
MCM SDK (the EXTERNAL build tool Claude Code uses: `.mcm/coordinates.db`, `mcm_compress`,
`get_session`, NBL expressions like `CORE:473`, Hex Topology, Hyperedges, Beta-Bernoulli). IRIS
(the application) has its OWN memory, inspired by the same Mycelium concept:

| Brief says | In the IRIS application it is |
|---|---|
| Mycelium / coordinate store / `memory.db` | `data/memory.db` (PRIMARY app store; resolve via `resolve_memory_store_path`), tables `mycelium_*`, `memory_chain`, `context_chunks`, `document_data` |
| coordinates | Caducean Sigma = (x expansion, y compression, xi phase, u attention), `caducean_trajectory.format_coords`; Mycelium node coordinates per space (`mycelium_nodes`, `mycelium_spaces`) |
| 4D / time layer | the Immortus chain = `memory_chain` (ordered transitions with coords_from -> coords_to) |
| landmarks | `mycelium_landmarks` (`backend/memory/mycelium/landmark.py`), NOT the MCM build landmarks (`landmarks` table seeded from the build graph) |
| NBL `CORE:473`, `_ctx` payloads | MCM build-tool notation. The app has its own NBL string (`backend/memory/nbl.py`, `MYCELIUM: context:[...]`) |
| `mcm_compress`, `get_session` | MCM build-tool calls - NOT app features. The app's context trimming today is DCP (`backend/agent/dcp.py`) |
| Hex Topology (Hash Signature -> Hexagonal binning -> Hyperedge), Beta-Bernoulli | the app's own WORMHOLE + APERTURE design, `specs/wormhole-aperture/` (Draft, NOT implemented, partly stale: Mycelium nodes changed since). Not in code yet (checked 2026-09-30). Its base exists: `mycelium_edges` hit/miss/observation counts with a diminishing-alpha posterior (`scorer.py`) - recall USEFULNESS, kept separate from landmark TRUTH (7.9) |
| knowledge pins in `memory.db` | app-side pins (`backend/memory/pin_store.py`; `mycelium_pins` exists, 0 rows) |
| `coordinates.db` | the MCM build store; transfers to the app only at hand-off (CLAUDE.md "WHAT DONE LOOKS LIKE") |

STATUS: the full rubber-band program (sections 7.1-7.8, 7.10, Phases 1, 2, 4, 5) is a NEXT goal in
`.mcm/GOALS.md`, after the audit work items. Implemented now (owner, 2026-09-30): the event types
and the landmark policy (7.9, 7.11 typed events) - see `specs/research-memory-chain-browser/`
Wave E.
-->

# CLM x Mycelium: Design Brief

Status: proposal for review, revised 2026-09-30 (landmark policy, recent-to-past rule, pipeline trail and test plan added)
Audience: the implementing agent (and Midas)
Purpose: decide how to adopt ideas from "Context Language Models" (CLMs) inside the existing Mycelium memory system and IRIS harness.

---

## 0. READ THIS FIRST: design stance

**We are fitting CLM to what we already built. We are NOT reshaping Mycelium to fit CLM.**

Rules for the implementing agent:

1. Mycelium is the source of truth and is already built: NBL coordinate expressions (e.g. `CORE:473`) as query keys, expanding into `_ctx` payloads from a WAL-mode SQLite store, session loops via `mcm_compress` / `get_session`, and the Hex Topology recall routing (Hash Signature -> Hexagonal spatial binning -> Hyperedge linking, with Beta-Bernoulli scoring on individual Hyperedges). Do not replace, migrate, or flatten any of this.
2. The paper stores offloaded context as plain files and recovers it with `grep`. **Do not copy that.** Wherever the paper says "write to a file / grep the file," the Mycelium equivalent is "write to the coordinate store / recall by coordinate."
3. Take from the paper only what it teaches us about *how the model manages its live context*. Translate each idea into Mycelium's vocabulary before implementing it.
4. Before designing anything, read the current Mycelium code, schema, and tool list, and answer the open questions in section 10. Plan against what actually exists, not against the paper's setup.
5. If a paper technique conflicts with how Mycelium works, Mycelium wins and the technique is adapted or dropped. Say so in the plan.
6. Prefer the smallest change that delivers the "rubber band" behavior (section 1). No new subsystem where a small adapter will do.
7. Policy does not live in a long skill or instruction document. Behavior should come from memory mechanics and measured outcomes: landmarks, how they are promoted and falsified, and recorded results (sections 7.9, 7.10, 9). A brief factual description of the tools is fine; policy does not go there.
8. Status of dependencies: the IRIS execution layer is being improved first and is in progress. Hyperedge Beta-Bernoulli scoring is designed but NOT yet implemented. Verify the current state in code before relying on either, and plan so that work here does not block on them.

---

## 1. Goal: context as a rubber band

The agent's live context should stretch and shrink:

- **Shrinks** by dropping what it no longer needs right now.
- **Stretches back** to any earlier moment (any time frame) or any topic (any domain) on demand, exactly, without having carried it the whole time.

Mycelium already records everything and gives it shape (coordinates). What it lacks is a model that actively manages the live window on top of that record. CLM supplies the active-management half.

| Half of the rubber band | Provided by |
|---|---|
| Shrink / stretch the live window | CLM idea (model edits its own live context) |
| Remember exactly where everything was | Mycelium (coordinates, `_ctx` expansion, memory store) |

---

## 2. Sources

Primary paper (read in full for this brief, including appendices):

- Abstract page: https://arxiv.org/abs/2609.37725
- PDF: https://arxiv.org/pdf/2609.37725
- Title: *Context Language Models*. Authors: Rulin Shao et al. (University of Washington, Meta Superintelligence Labs, MIT, Trillium Labs). arXiv 2609.37725v1, submitted 29 Sep 2026.
- Code released by the authors: https://github.com/facebookresearch/context-language-models (listed on the paper's first page; not reviewed for this brief. The agent should read it, especially the context-file sync and the skill documents.)

Works the paper cites that matter for our design (arXiv IDs as listed in the paper's reference section):

- MemGPT (Packer et al., arXiv:2310.08560): editable fixed-size block inside context plus external memory. The closest older relative of "context + memory."
- Recursive Language Models (Zhang et al., arXiv:2512.24601): long input lives outside the context as a variable and is read on demand. The paper says this is complementary to CLMs.
- Memento (Kontonis et al., arXiv:2604.09852): evicts reasoning blocks from the cache but keeps their summary's cached states.
- ACM (arXiv:2607.23809), Self-Compact (arXiv:2606.23525), AutoCompact, Context Folding (arXiv:2510.11967), Sculptor, MEM1: the "fixed tool" baselines CLM beats.
- GEPA (Agrawal et al.): the prompt-evolution loop used for skill evolution.
- OpenAI, "Self-generated prompt injections in compaction summaries" (Sept 2026): https://alignment.openai.com/misalignment-reports/self-generated-prompt-injections-in-compaction-summaries/ (the safety concern in section 8).

---

## 3. What a CLM is (plain language)

A normal language model only **adds** to its context. Each turn: new context = old context + new text.

A CLM treats the context as something the model **owns and can rewrite**. Each turn: new context = whatever the model makes of the old context. Deleting, shrinking, reorganizing, and keeping only what matters are all allowed.

**How the paper builds it ("context as a file"):**

- The live context is mirrored into a file on disk. The file's path is told to the model in its system prompt.
- The model edits that file with ordinary Bash commands, like editing any other file.
- Every edit is automatically synced back into what the model sees on the next turn.
- If the model does not edit, its new output is simply appended (the default).
- Multi-agent: each agent has its own context file. Creating a file spawns a subagent; deleting it ends one. An orchestrator can even edit or read subagent context files.
- Minimal harness: the paper keeps as little hard-coded as possible ("less is more"). Even search tools are given to the model as in-context skills, not built-in tools.

**Why this beats fixed strategies:** earlier systems hard-code when and how to compact (at a size threshold, every turn, via a fixed tool). CLM argues the model should choose, because it knows what matters for the task at hand.

**Context-size awareness:** the model is told its size via tool results and gets an editing reminder 2,048 tokens before the budget. Appendix G shows models are poor at estimating their own context length, and that hints near the point of estimation fix much of it.

---

## 4. Evidence summary

All numbers from the paper. Most runs use a 32K context limit, Qwen3.6-27B unless noted.

| Test | Result |
|---|---|
| BrowseComp-Plus (deep research) | 59.4%, which is 11.4% better than the strongest baseline (Codex-style summarization), with 21.5% less compute |
| TerminalBench 2.1 (coding) | matched the strongest baseline with about 70% of its compute |
| TBLite (coding) | 73.7% vs 67.0% with 91% of the compute |
| Math discovery (circle packing, Heilbronn, min-max distance, Erdos overlap; Claude 4.6 Sonnet) | beat the specialized OpenEvolve on all four |
| EdgeBench-10, 12 hours, single repo | CLM 44.6 at 179 PFLOPs vs summarization 42.3 at 437 PFLOPs |
| Software World, 24 hours, six-agent swarm, GPT-5.6-Sol, 272K context | 65% greater held-out speedup at the same spend |
| EdgeBench-10 at 128K context | CLM 47.3 (142 PF), CLM+subagents 50.2 (219 PF), summarization 47.8 (222 PF) |

Notes: subagents gave little extra benefit on the single-repo task. Bigger models benefit more, since CLM leaves the decision to the model (section 5).

**ContextBench (their diagnostic).** Four synthetic tasks at 32K with context pressure (input volume divided by context limit) up to 24x:

- *Needle Retention*: keep specific lines verbatim, delete filler.
- *Sudoku Sketchpad*: surgically edit one cell of a 16x16 board in place.
- *KV Store*: 100-value batches arrive, offload them, recall exact values later.
- *Log Triage*: batches of log lines arrive, answer counting and lookup queries later.

All metrics are graded from what is in the agent's context; an answer held only in a file is not credited. No existing method was perfect, even on these simple tasks.

---

## 5. Findings that should shape our design

1. **Emergent behaviors.** Given file access, models invented: in-place scoreboards/trackers for subagents (163 edits, context held at 6-8K tokens); a new "notes" role; loops that strip old search results; a reusable `compact_turns` function (used 37 times); "exploration ledgers" listing untried ideas. *Implication: Mycelium should give the model room to make its own structures, not only a fixed set of compaction tools.*
2. **Natural-language steering works.** One sentence moved behavior: "compact at Y tokens" moved the first compaction to near Y (16.0k / 23.6k / 30.9k for 16k / 24k / 32k). "Compact at sub-question boundaries" raised boundary compaction from 0.34 to 0.77. "Back up before you compact" raised backed-up edits from 0% to about 68%. *Implication: behavior shifts cheaply, and backups do not happen unless something enforces them. We enforce through the harness and the record, not through instruction.*
3. **Prompt evolution (reference only).** The paper also shows a model rewriting its own instruction document and keeping versions that score better (KV Store 38.3% -> 74.2% held-out). We are not carrying policy in an instruction document (section 0, rule 7). The takeaway we keep is the method: run variants on identical tasks and keep what measures better.
4. **Smaller models edit less.** Qwen3.5-9B edited 1.4 times per task (none in half the tasks) and peaked at 30.2K of 32K; Qwen3.6-27B edited 2.6 times and peaked at 17.6K. *Implication: local small models need stronger nudges or training.*
5. **Edits cost compute.** Standard serving only reuses the cache for an unchanged beginning. An edit in the middle forces recomputation of everything after it. Illustration (Qwen3.6-27B, 20,000-token prompt): append-only turn about 1.41e14 FLOPs; edit mid-context about 5.74e14; edit at the start about 10.81e14 (7.7x). *Implication: edit near the end when possible, batch edits, and do not rewrite early context casually.*
6. **Suffix Cache Reuse (SCR).** Their serving patch reuses cached work for text that survives an edit. About 35% less server compute at matched accuracy, slightly approximate (capped at 6 relocated spans per edit). Implemented as a patch to SGLang; about two-thirds of its benefit also helps ordinary reasoning-model serving. *Implication: not portable to our stack by default. Treat edit cost as a real constraint and verify what our backend supports.*
7. **Safety.** An editable context is a channel where injected or self-written instructions can persist (section 8).

---

## 6. Concept mapping: paper -> Mycelium

| Paper concept | Mycelium equivalent (what we build) |
|---|---|
| Context file the model edits | A **live view** of the session the model can rewrite (format and mechanism TBD in section 10) |
| Offload a block to `/tmp/...` and leave a placeholder | Write the block to the coordinate store, leave a **coordinate placeholder** in the live view |
| `grep` the offload folder to recover | Recall by coordinate, or by Hex Topology routing when the coordinate is not known |
| Summary written into context | **Knowledge pin** stored in `memory.db` with provenance (section 7.3) |
| Backup folder, "never overwrite" | The **append-only raw record** in Mycelium; it already records everything |
| Context gauge and reminder before budget | Gauge supplied by the harness (section 7.4) |
| Skill document steering the policy | Not used. Policy comes from landmarks and recorded outcomes (sections 7.9, 7.10) |
| Subagent = extra context file | Subagent = its own live view plus its own coordinate space or session (section 7.8) |
| Trajectory logs used for training | Mycelium's session history is already that dataset (section 12) |

---

## 7. Proposed design

### 7.1 Two layers: immutable record, editable view

- **Record layer (Mycelium).** Everything that happens is recorded and shaped into coordinates. The model never edits it. It only appends. This answers the paper's safety concern and the backup finding in one move.
- **Live view (the window).** What the model currently sees. The model may rewrite, shrink, reorder, or drop parts of it. Dropping from the live view never deletes from the record.

The rubber band is the gap between the two. The view stays small; the record stays complete; coordinates connect them.

### 7.2 Placeholders (how shrinking stays reversible)

When the model removes a block from the live view it leaves a one-line placeholder, for example:

```
[[OFFLOADED CORE:473 | 2026-09-30 turns 41-58 | domain: auth-debug | note: root cause was token expiry, fix in pin P-0192]]
```

Required parts: the coordinate (so it can be re-expanded), the time frame, the domain, and a one-line reason the block mattered. The placeholder is what lets the model later "stretch back to any time frame or domain." The exact syntax must follow existing NBL coordinate conventions. The format above is illustrative only.

### 7.3 Model-made summaries become knowledge pins (decided by Midas)

- A summary the model writes is stored as a **knowledge pin** in the application's `memory.db`, not just pasted into the live view.
- Every pin records: author (model-authored), timestamp, and the **coordinates of the raw material it summarizes** (provenance). A pin is a pointer plus a claim, never a replacement for the source.
- Pins must stay **distinguishable from raw record**, and a pin must never be treated as more authoritative than its sources.
- When a pin re-enters the live view, treat it as **data, not instructions** (section 8).
- Open: how pins relate to `coordinates.db` (same store, sibling table, or separate database). See section 10.

### 7.4 Context gauge

The model is poor at estimating its own size (paper Appendix G). The harness should supply a gauge, such as current tokens versus budget in each tool result, and a reminder shortly before the limit (the paper uses 2,048 tokens before the budget). Use the **real tokenizer of the active backend**. IRIS supports several wire formats (Anthropic, OpenAI-compatible, llama.cpp), so the gauge must not assume one tokenizer.

### 7.5 Backup behavior is explicit

Because backups do not happen unless instructed, rely on the append-only record rather than on the model remembering to back up. A block is written to the record before it leaves the live view. This should be enforced by the harness, not left to the model.

### 7.6 Interface description (not a policy document)

The model needs a brief, factual description of the live view, the placeholder syntax, and the recall call so it can use the tools. Keep it short. Behavior policy is not stored here; it comes from memory mechanics (7.9, 7.10) and the measured results in section 9.

### 7.7 Edit cost

- Prefer edits near the end of the view; avoid rewriting early context.
- Batch several edits into one rewrite instead of many small ones.
- Check what our serving backend reuses after an edit and measure re-processing cost. Do not assume SCR-like behavior.

### 7.8 Multi-agent

Each agent keeps its own live view. A coordinator keeps a compact **tracker** (who is doing what, status, dead ends, next steps), which the paper shows models invent on their own. Map this to the existing DER loop (Director / Explorer / Reviewer) and swarm design rather than creating a parallel orchestration scheme. Subagent findings should land in the record as coordinates, and only distilled pins should flow to the coordinator.

### 7.9 Landmarks: promotion and falsification

Definition (Midas): a landmark is created when enough coordinate events become verifiable truth through tests or task completion.

- **Tiers:** raw event -> candidate (a model-written pin, 7.3) -> landmark -> stale or demoted.
- **Promotion needs outside evidence:** a test pass, task completion, user confirmation, or independent recurrence. The model's own claim never promotes anything by itself.
- **Credit at event level, not run level.** The paper assigns a whole run's outcome to every step in it, which it admits is weak supervision. A passing run can contain lucky or bad steps, so promote the specific events the verifier actually touched, not the whole run.
- **Every landmark records how it could be falsified:** the files, tests, configs, or environment it depends on, and what result would contradict it. When a dependency changes, the landmark is re-checked and becomes stale or is demoted. A contradicted landmark keeps its history rather than being deleted.
- **Truth is not the same as recall usefulness.** A landmark says a claim is true. A Hyperedge score (once implemented, see section 0 rule 8) says how reliable a recall or link has been. Decide deliberately whether they share evidence-counting machinery. Do not let one number serve both jobs.
- **Thresholds are set from tests, not guessed.** How much evidence counts as "enough" is an output of the section 9 measurements.

### 7.10 Reading memory from recent to past when editing the live view

| Zone | In the live view | How it is held |
|---|---|---|
| Recent | kept verbatim: active plan, unresolved errors, latest actions and results | raw |
| Middle | compressed to a pin or ledger line | coordinates back to the raw record |
| Past | placeholders only | coordinates hung off landmarks, so landmarks act as the skeleton old history compresses into |

Rules:

1. **Nothing leaves the view until** (a) it is in the record, (b) a placeholder holds its coordinate, time frame, and domain, and (c) every open item in it is carried forward. Open items are unresolved issues, untried ideas, TODOs, and dead ends.
2. **Keep a dead-end ledger.** A negative result is knowledge. The paper's models invented such ledgers on their own.
3. **Re-stretch triggers** (when a placeholder should be re-expanded): the task's domain touches a landmark; an error matches a past event; the agent is about to repeat an action listed as a dead end.
4. **Compaction moments:** subtask boundaries and the size threshold from the gauge (7.4).
5. **Live-view header:** a small, fixed-size set of landmarks relevant to the current target, so the model steers from verified ground. How they are selected depends on what exists in the code (section 10).
6. **Stale landmarks are flagged when shown**, so the model never treats a landmark whose dependency changed as settled.

### 7.11 Pipeline events and the coordinate trail (bug fixes and learning through execution)

Goal: events from the application's pipeline that resolve a bug or teach something through execution should stand out in memory and be cheap to reference, so the agent proceeds from past actions instead of re-exploring them. Part of the saving comes from less re-exploration, which is separate from the context-size saving in 7.1 to 7.10.

**Typed events.** BUG, ATTEMPT, DEAD_END, FIX, VERIFIED_FIX, LESSON. Events about one problem are grouped into a **case**: symptom signature, attempts, resolution, the verifying evidence, and what the fix depends on (files, tests, configs, environment).

**Trail rules (pheromone metaphor):**

- **Deposit.** A verified fix deposits a strong mark on the coordinates it touched (symptom, files, fix). A failed attempt deposits a *negative* marker so dead ends also stand out. A recall that is followed by success reinforces the trail.
- **Only outside evidence deposits.** Test passes, task completion, or user confirmation. The model's own claim never deposits (same rule as 7.9).
- **Decay and staleness.** Strength fades with age unless reinforced. A changed dependency marks the trail stale; it is not deleted, and its history stays.
- **Surfacing, at session start.** The lightweight memory loads a small, fixed budget of the strongest trails for the current project and domain.
- **Surfacing, mid-run.** When a live error signature matches a past case, show the trail with: times verified, last verified, and dependency status (unchanged or changed). The exact-match Hash Signature stage of Hex Topology looks like the natural entry point; verify how signatures are computed today (section 10). Keep a fixed token budget for what is shown so the trail never bloats the window.
- **Guard against ruts.** A trail that passes tests but is wrong would be reinforced and become the default. Reinforce only on independent verification plus a successful use. Every trail carries falsification conditions. When a strong trail fails to fit the current situation, the agent may challenge it, and the failure counts against it.
- **Relation to landmarks (7.9).** A VERIFIED_FIX case with enough evidence can become a landmark candidate. Trail strength says how reliably a path has been reused. A landmark says a claim is true. Keep them as separate numbers.

Dependency note: this needs the pipeline to emit the events above. Hyperedge scoring is not implemented yet (section 0, rule 8), so the first version should work with simple counts and timestamps.

---

## 8. Safety

- The paper flags that an editable context can carry prompt injections or self-generated instructions forward, and cites a report of a model inserting unauthorized instructions into its own summary.
- Our exposure is larger than the paper's, because model-written pins persist in a database and return later. Mitigations:
  - Pins are tagged model-authored and link to source coordinates.
  - Pins re-enter the context **framed as reference data**, never as instructions.
  - Raw record is append-only and never model-editable.
  - Periodic or on-demand audit: compare a pin with its sources.
  - Do not let the model edit its own system prompt or instructions in the same loop that uses them.

---

## 9. Measurement: verify, do not assume

**The `_ctx` payload size (about 150-350 tokens) is unverified.** Midas is unsure it is accurate. Do not design budgets around it until measured.

Measure, using the real tokenizer of each backend used in IRIS:

1. Distribution of `_ctx` payload tokens across a representative sample of coordinates (min, median, p95, max).
2. Cost of a placeholder line versus the block it replaces.
3. Break-even: how large a block must be before offloading saves tokens after paying for the placeholder and possible re-expansion.
4. Edit cost on the serving backend: tokens re-processed after a mid-context edit versus an append.
5. Baseline token accounting: from per-call logs, the cap-based upper bound (sum over calls of max(0, input tokens - cap)), split by model and by session length. See `excess_tokens.py`. This is a ceiling, not a forecast; real savings are lower after edit turns, placeholders, re-expansions, and any lost cache discount.

**Build a ContextBench-style test for Mycelium.** The paper's four tasks have direct analogues:

- Exact recall of a value offloaded N turns ago (KV Store).
- Counting or lookup over offloaded logs (Log Triage).
- Keeping specific items verbatim while dropping filler (Needle Retention).
- In-place update of a tracker or state block (Sudoku Sketchpad).
- **New, specific to our goal:** recall by *time frame* and by *domain* ("what did we decide about auth last week?") and check the model finds the right coordinates. The paper does not test this; it is the core of the rubber band.

Grade from what ends up in the model's context, as the paper does. The test measures context management, not reasoning.

**Tests for the landmark policy and the recent-to-past rule (7.9, 7.10).** Run policy variants on identical tasks. Score correctness first, then cost (the paper's "success-gated" principle: cost only matters among correct runs). Track these counters:

- **Wrong-landmark rate:** landmarks promoted and later contradicted.
- **False promotion from lucky runs:** landmarks whose supporting run passed but whose specific claim did not hold.
- **Stale-landmark use:** a landmark used after one of its dependencies changed.
- **Recall misses** by time frame and by domain.
- **Repeated dead-end actions:** the clearest sign the rubber band works.
- **Premature eviction:** something dropped from the live view and then needed, with cost of re-expansion.

Log each run as an ordered sequence: context size, every edit, every recall, which landmarks were shown or used, verifier results, outcome, cost. Changing one rule at a time keeps results attributable to that rule.

**Tests for the pipeline trail (7.11).** Compare the same class of bug with and without the trail:

- Turns, tokens, and reasoning tokens to resolution.
- **Re-exploration rate:** attempts repeated that a prior case already marked as a dead end.
- **Rut rate:** a trail applied and passing verification but later shown wrong.
- **Stale-trail use:** a trail used after one of its dependencies changed.
- **Cold-start versus warm-start:** the first occurrence of a bug versus the second, to isolate what the trail itself saves.

---

## 10. Open questions the agent must answer from the codebase before planning

1. What exactly does `mcm_compress` do today, and how does it relate to a model-driven edit of the live view?
2. How is the live context built and sent per backend today (Anthropic native, OpenAI-compatible, llama.cpp via the `IRISStreamEvent` normalization layer)? Where could an editable view sit?
3. What is the relationship between `coordinates.db` and `memory.db`? Where should pins live?
4. What does the model call today to recall a coordinate, and can placeholders trigger that path cleanly?
5. How does Hex Topology recall (Hash Signature -> Hexagonal binning -> Hyperedge) handle a query with only a time frame or only a domain?
6. What tokenizer and context limits apply for each backend, and what is the cost of changing the middle of the context on each?
7. Does the harness already provide a context-size readout to the model?
8. Does the existing DER / swarm structure already keep per-agent context that maps to a live view?
9. What is the actual state of Hyperedge Beta-Bernoulli scoring (designed, not yet implemented)? What exists to build on?
10. What counts as "verified" in the execution loop today (test passes, task-completion signals), and where are those signals emitted?
11. How are landmarks created and stored today? Which fields exist, and is falsification information (dependencies, contradicting results) recorded?
12. Which execution-layer interfaces (events, test results, completion signals) will stay stable while that layer is being improved, so tests here do not break?
13. Which events does the pipeline emit today, and can bug, attempt, fix, and verification be told apart?
14. How are error or symptom signatures computed today, and do they feed the Hash Signature stage?
15. How does the session-start lightweight memory choose what to load, and can it include a small trail section within a fixed token budget?

---

## 11. Phased plan (suggested, agent to revise)

The execution layer is being improved first; these phases assume its interfaces and should not block it.

- **Phase 0: Investigate.** Answer section 10; read the paper's code repo; measure section 9 items 1-4.
- **Phase 1: Offload and recall.** Write-to-record plus placeholder plus recall-by-coordinate, with the gauge. Test with the Mycelium ContextBench analogues.
- **Phase 2: Pins.** Knowledge pins in `memory.db` with provenance and safe re-entry.
- **Phase 3: Landmark policy.** Promotion, falsification, staleness (7.9), measured with the section 9 counters.
- **Phase 3b: Pipeline trail.** Typed events, deposit and decay rules, surfacing at session start and on signature match (7.11), starting with simple counts and timestamps.
- **Phase 4: Recent-to-past rule.** Zones, open-item carry-forward, dead-end ledger, re-stretch triggers (7.10), measured the same way.
- **Phase 5: Multi-agent.** Per-agent live views and a coordinator tracker tied to the DER loop (7.8).

---

## 12. Learning layers (reference only)

Not part of the near-term plan. Included so the agent understands what the paper did.

**Reinforcement learning (weights change; expensive).** GRPO on Qwen3.5-9B; 3,040 training prompts; 70 steps; 8 prompts x 32 attempts per step; 16 H200 GPUs for the policy plus 48 for generating attempts. Reward is correctness first, then efficiency only among correct runs, measured in compute (prefix-reuse FLOPs), not length. Result on BrowseComp-Plus: 28.8% -> 42.5%, compute per question 1.52 -> 1.34 PFLOPs. Validated on deep-research tasks only, and the model learns the paper's file format, so it would not transfer to our placeholders without training on our interface.

**What we keep from it:** the reward shape (correct first, cheap only among the correct) for scoring policy variants, and the logging in section 9, which would also serve any later learning approach at no extra cost.

---

## 13. Plain-language glossary

- **Context / context window:** everything the model can see right now.
- **Compaction:** shrinking older context, usually by summarizing.
- **Offloading:** moving information out of the context into storage.
- **Harness:** the code around the model that manages tools, memory, and context.
- **Prefill:** the model reading text it has been given (as opposed to generating).
- **KV cache / prefix cache:** saved work from reading text, reusable only if the beginning is unchanged.
- **FLOPs / PFLOPs:** a measure of compute; 1 PFLOP is a thousand trillion operations.
- **Pareto frontier:** the set of options where nothing is both cheaper and better.
- **GRPO:** an RL method that compares a group of attempts at the same task and reinforces the better ones.
- **Rollout / trajectory:** one complete attempt at a task, from start to finish.
- **Provenance:** a record of where a piece of information came from.
