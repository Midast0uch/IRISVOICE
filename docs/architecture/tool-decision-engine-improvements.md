# Tool Decision Engine: Performance, Architecture & Integration Analysis
**Findings, Bottleneck Audit, and Native LFM2-350M Optimization Roadmap (Sub-450ms Target)**

---

## 1. Executive Summary

The IRIS Tool Decision Engine was implemented to reproduce the "System 1" decision driver pattern (inspired by TypeSafe AI's Jev) using an in-process `LFM2-350M-Extract` model via `llama-cpp-python` on CPU. While it successfully establishes parallel scoring, probability calibration, and ledger-based auditing, it exhibits specific algorithmic and architectural bottlenecks that push total resolution latency to 1,500–2,500ms.

**Key Finding on LFM2-350M Latency**:
The `LFM2-350M` model **can definitely operate well under 450ms on CPU (typically 150–250ms)**. The raw forward pass scoring of the model takes only **25–60ms** when using the head KV-cache snapshot. The high latency is not caused by the model itself, but by two external mechanisms:
1. **The Autoregressive Argument Loop (`generate_args`)**: Generating JSON arguments token-by-token on CPU adds **500–1,500ms** after tool selection is already complete.
2. **Prefix-Collision Re-evaluation Loops**: When tools share a name prefix (such as all four `vision_*` tools), the engine wipes its context and sequentially re-evaluates the prompt for each candidate, adding **800–1,100ms**.

**Clarification on Quick Search vs. Deep Crawler**:
`search` and `crawler_query` do not crash or throw conflict exceptions. The disconnect is an **architectural mismatch**:
1. **Duplicate Backend**: Both tools currently call `CrawlOrchestrator().research(...)`. "Quick search" is not quick—it runs the full multi-page Crawl4AI headless browser crawler and LLM planner.
2. **Heuristic Pre-emption**: The memory pre-filter in `agent_kernel.py` automatically rewrites all web intents to `crawler_query`, preventing `search` from ever being used as an instant, lightweight lookup.

---

## 2. Model Family Analysis: Is LFM Bidirectional or Autoregressive?

Liquid AI's **LFM2 / LFM2.5** family is built on a hybrid architecture that combines gated short convolutions with linear and rotary attention mechanisms. The family is split by functional objective:

1. **Autoregressive Text/Chat Models** (e.g. `LFM2.5-350M-Extract`, `LFM2.5-350M-Instruct`):
   - These are causal, autoregressive models optimized for on-device edge deployment, chat, tool calling, and structured data extraction.
   - This is the exact GGUF variant currently loaded in IRIS (`LFM2-350M-Extract Q4_K_M` via `llama_cpp`).
   - In `backend/agent/decision_engine.py:173`, non-causal files are explicitly excluded:
     `bad in h.name.lower() for bad in ("embedding", "encoder", "vl-")`
2. **Bidirectional Encoder Models** (e.g. `LFM2.5-Retrievers`, `LFM2.5-Encoders`):
   - Liquid AI also produces bidirectional encoder variants of the 350M architecture (as well as 230M sizes) designed for classification, token-level understanding, and ColBERT-style retrieval.

### Can the Autoregressive `LFM2-350M-Extract` Achieve Sub-450ms?
**Yes.** When scoring options in parallel at the answer position, `llama_cpp` performs prompt prefill once and reads the output logits in **a single forward pass**.
- Static instruction/worked-example head (~90 tokens): Pre-computed and snapshotted once at startup (`_warm_head_state`).
- Dynamic task/options tail (~40–60 tokens): Evaluated in **10–60ms** on an 8-core CPU.
- Total decision time without prefix collisions: **150–250ms**.

The latency explodes only when:
- Serial prefix tie-breaker loops trigger (+800ms).
- Autoregressive JSON text generation runs in `generate_args` (+500–1500ms).
- Candidate menu misconfigurations trigger escalation to the Brain LLM (+2000ms+).

---

## 3. Disconnect Analysis: WebSearch, Crawler & Decision Engine

### 3.1. The `"what's"` False-Positive Vision Interception
- **File**: `backend/agent/tool_decision.py:51-65`
- **Mechanism**:
  ```python
  _VISION_TOKENS = frozenset({
      "screenshot", "screen", "screenshot,", "screens", "image", "photo",
      "picture", "pixels", "vision", "diagram", "banner", "logo",
      "what's",  # "what's on screen" style prompts split to what's
  })
  ```
- **The Defect**:
  When a user asks:
  - *"What's the stock price of Apple?"*
  - *"What's the weather in Seattle?"*
  - *"What's the capital of France?"*
  The word `"what's"` matches `_VISION_TOKENS`. `_vision_relevant(goal)` immediately returns `True`.
- **The Disconnect**:
  1. `tool_decision.py:463` forces all vision tools to the front of `names`.
  2. Because `candidate_cap` is 6 or 8, the vision tools (`vision_detect_element`, `vision_analyze_screen`, `vision_validate_action`, `vision_get_context`, `take_screenshot`, `start_screen_monitor`) occupy the entire menu.
  3. Web search tools (`search`, `crawler_query`) are pushed beyond the cap and discarded!
  4. The engine is presented with a web question but only vision tools. It outputs `NONE` or drops below the 0.85 threshold.
  5. The system escalates to the Brain reasoning model, adding 1.5–3.0 seconds of router inference latency.

### 3.2. Candidate Cap Truncation Bug in Hierarchical Lane Building
- **File**: `backend/agent/tool_decision.py:464-473, 534`
- **Mechanism**:
  ```python
  names = names[:_cap]   # Line 473: Sliced to candidate cap (e.g. 8)
  ...
  lanes: Dict[str, list] = {}
  for n in names:        # Line 534: Iterates over the TRUNCATED names list!
      lanes.setdefault(name_to_cat.get(n, "misc"), []).append(n)
  ```
- **The Defect**:
  The hierarchical selection tree (`decide_tree`) was created to solve wide menus by grouping tools into categories (`web`, `vision`, `file`, etc.). However, line 534 constructs `lanes` from `names` *after* line 473 has already sliced `names` to 8 items!
- **Consequence**:
  If `all_tools` contains 30 registered tools, and the first 8 happen to be Vision and GUI tools, the `lanes` dict contains only `vision` and `web` is missing completely. Even if `_pre_cap_count > _cap` triggers the tree, the tree never evaluates the web lane.

### 3.3. Semantic Rigidity in Memory Hints & `_is_web_intent`
- **File**: `backend/agent/explorer.py:53-69`, `backend/agent/agent_kernel.py:14187-14210`
- **Mechanism**:
  `_mem_lookup` in `agent_kernel.py` only suggests `crawler_query` if `_is_web_intent(goal)` evaluates to `True`. `_is_web_intent` checks a static list of 15 explicit phrases (e.g. `"search the web"`, `"do research"`, `"look up online"`).
- **The Disconnect**:
  Informational queries lacking those exact keywords (e.g. *"latest Nvidia Blackwell architecture release date"*) evaluate to `_is_web_intent = False`. Consequently:
  - No memory hint is provided.
  - In `tool_registry.py`, Vision tools are registered at lines 480–520, while Web tools are registered at lines 1040–1065.
  - Slicing `all_tools` drops the web tools.
- **Synchronous Event Loop Block**:
  In `agent_kernel.py:14205-14210`, `_mem_lookup` executes:
  ```python
  sr = get_source_registry()
  sr_result = _asyncio.run(sr.resolve(goal, quick=True))
  ```
  Running `_asyncio.run()` synchronously inside `_mem_lookup` within the DER thread adds 50–200ms of synchronous blocking before the decision engine even begins inference.

### 3.4. Search vs. Crawler Query Architectural Mismatch
- In `tool_registry.py`:
  - `search` is described as a "quick factual answer".
  - `crawler_query` is described as a "deep web research crawl".
- In `tool_bridge.py`:
  - `search` (line 3578) calls `CrawlOrchestrator().research(...)`.
  - `crawler_query` (line 2736) calls `CrawlOrchestrator().research(...)`.
- Both invoke Cerebras LLM URL planning, Playwright browser instances, and multi-page markdown parsing.
- A quick lookup pays the identical 5–15 second penalty as a deep crawl.

---

## 4. Disconnect & Latency Analysis: Vision Tools

### 4.1. First-Token Prefix Collision in Option Scoring
- **File**: `backend/agent/decision_engine.py:426-453`
- **Mechanism**:
  ```python
  for opt in options:
      word = " " + opt.split("_")[0]
      first_tok = self._llm.tokenize(word.encode("utf-8"), add_bos=False)
      raw.append((opt, float(row[first_tok[0]])))
      per_first.setdefault(first_tok[0], []).append(opt)

  # Tie-breaker loop:
  for tie in [g for g in per_first.values() if len(g) > 1]:
      for opt in tie:
          cont = self._llm.tokenize(f" {opt}".encode("utf-8"), add_bos=False)
          self._llm.reset()
          self._llm.eval(tokens + cont)
  ```
- **The Defect**:
  Every vision tool starts with `vision_` (`vision_detect_element`, `vision_analyze_screen`, `vision_validate_action`, `vision_get_context`).
  `word = " " + opt.split("_")[0]` evaluates to `" vision"` for all four tools.
  Every vision tool has an identical `first_tok[0]`.
- **Latency Multiplier**:
  Because they all tie, lines 437–453 iterate through every vision tool and perform:
  `self._llm.reset()` + `self._llm.eval(tokens + cont)`.
  This is a full prompt evaluation without KV-cache sharing. On an 8-core CPU, each eval costs ~220–280ms. For 4 vision tools, this adds **880ms – 1,120ms** to a single decision call.

### 4.2. Post-Dispatch Synchronous Screenshot Capture
- **File**: `backend/agent/tool_bridge.py:1601`
- **Mechanism**:
  ```python
  if tool_name in vision_tools:
      result = await self.execute_vision_tool(tool_name, params, session_id)
      screenshot_blob = self._capture_screenshot_blob()
      self._record_tool_event(..., screenshot_blob=screenshot_blob)
  ```
- **The Defect**:
  `execute_vision_tool` already captured a screen frame or communicated with `VisionMCPServer`. Immediately after it returns, line 1601 invokes `_capture_screenshot_blob()`, which executes a fresh OS screen capture and encodes it to PNG on the main thread for ledger recording. This adds **100–250ms** of synchronous latency to every vision execution.

---

## 5. Native Optimization Roadmap (Zero New Model Dependencies)

All improvements below keep the native `LFM2-350M-Extract` engine.

### Track 1: Decision Engine Algorithmic Fixes
*Target: Decision scoring latency $\le 180\text{ms}$ on CPU.*

1. **Eliminate Prefix-Collision Tie-Breakers with Single-Token Options (token form probe-gated):**
   - Instead of scoring word continuations (`" vision"`) **with a serial tie-breaker loop**, score one token per candidate at a single answer position. Either lettered:
     ```text
     Available options:
     A: vision_detect_element
     B: vision_analyze_screen
     C: vision_validate_action
     D: vision_get_context
     Answer:
     ```
     — pre-tokenize `[" A", " B", " C", " D", ...]` and read logits at `scores[len(tokens) - 1]` for those IDs — **or** tie-break-free first-token scoring, whichever the T0 probe wins.
   - **Result**: Zero ties, zero context resets, single forward pass in **25–60ms**.
   - **Correction (2026-09-25, §9.1):** letters are **not** what runs today — the live path is first-token scoring *plus* the `reset()` tie-break loop (`decision_engine.py:437-453`), and `_letter_token_ids` is never read. Removing the loop is invariant under either method; the probe only chooses the token form (REQ-1).

2. **Deterministic Fast-Path for Simple Tool Arguments**:
   - For tools with standard schemas (e.g. `{"query": str}` for `search` and `crawler_query`):
     ```python
     if set(required) == {"query"} and "query" in allowed:
         return ArgsResult(args={"query": goal}, retried=False)
     ```
   - **Result**: Completely eliminates `generate_args` autoregressive text generation for web queries, saving **500–1,500ms**.

3. **Fix `_VISION_TOKENS` False Positives**:
   - Remove `"what's"` from `_VISION_TOKENS`.
   - Require multi-word phrases for vision intent: `{"what's on screen", "what's on my screen", "look at screen"}`.
   - **Result**: Web questions never falsely masquerade as vision requests.

4. **Fix Candidate Lane Construction**:
   - In `tool_decision.py`, populate `lanes` from `pre_filtered` (all available tools), **not** from the truncated `names[:_cap]`.
   - **Result**: `web` lane is never accidentally discarded.

---

### Track 2: Web Search vs. Crawler Tiering
*Target: Quick search in $\le 500\text{ms}$; deep crawl reserved for research.*

1. **Tier Quick Search Separately from Crawl**:
   - `search`: Implement a lightweight HTTP search provider (e.g. SearXNG, DuckDuckGo API, or Exa API) that returns structured markdown snippets in <350ms without launching a browser subprocess.
   - `crawler_query`: Keep `CrawlOrchestrator` for deep research, multi-page crawls, and live visual browser actions.
2. **De-bias Prompt Worked Examples**:
   - Update `DecisionEngine._build_prompt_parts` to include examples of both:
     - *"Task: what is the weather in Tokyo" -> "Answer: search"*
     - *"Task: deep research on competitor pricing" -> "Answer: crawler_query"*

---

### Track 3: Vision Pipeline Acceleration
*Target: Vision tool resolution and execution $\le 300\text{ms}$.*

1. **Remove Redundant Screenshot Capture**:
   - In `tool_bridge.py:1601`, reuse the image buffer already captured by `VisionMCPServer` instead of initiating a second synchronous desktop capture via `_capture_screenshot_blob()`.
2. **Direct Element Target Extraction**:
   - For `vision_detect_element`, extract the target string directly from regex patterns (*"click on the 'X' button"*) instead of calling LLM completion.

---

## 6. Verification and Measurement Plan

Validate with the existing test commands:

1. **Microbenchmark Suite**:
   ```powershell
   python scripts/bench_decision_engine.py
   ```
   *Target Metric*: `engine_latency_ms` $\le 200\text{ms}$ on CPU, $\le 35\text{ms}$ on GPU.

2. **Offline Battery & Calibration**:
   ```powershell
   python scripts/calibrate_decision_threshold.py --since 2026-09-20
   ```
   *Target Metric*: Accuracy $\ge 92\%$, coverage $\ge 70\%$ at threshold 0.85 without vision collapse on search questions.

3. **End-to-End Latency**:
    ```powershell
    python scripts/bench_battery_domain.py
    ```
    *Target Metric*: Quick web search resolution + execution under 800ms total.

---

## 7. Dynamic Composite Recipes (Spec REQ-7 — Not in This Doc's Original Tracks)

The spec (`specs/tool-decision-engine-improvements/`, REQ-7) covers a track this analysis never wrote: on-the-fly `DynamicCompositeRecipe` synthesis by the Brain Agent with pre-flight artifact-contract + null-parameter validation (`validate_composite_recipe`), DER materialization via `expand_batch_nodes` / `resolve_dependent_params`, and episodic graph registration (`NodeSpec(composite_of=...)`) so repeat workflows resolve through the resident engine in ≤ 450ms. Design rationale, ripple rows, and tests (CT-DEI-3, BT-DEI-4) live in the spec — this doc defers to it rather than duplicating it.

---

## 8. Amendment Record (2026-09-25 — Every Claim Traced Against Live Code)

A line-by-line audit of this doc against the committed code found three stale assumptions and four spec gaps. The spec now carries REQ-8–REQ-12, Wave 0 (T0 probe, gates T1), and Wave 5 (T11–T16 + TG-5 gate). **Matrix count (corrected 2026-09-25):** 43/43 after that audit, 62/62 after REQ-13–REQ-17 (§8.4), **79/79 after the JEV-fidelity amendment (§9) adding REQ-18–REQ-20 plus REQ-6/REQ-14 ACs** — 0 unmapped at every stage. (The earlier "43/43" figure quoted here was stale once §8.4 landed.)

### 8.1. Stale Assumption Corrections

1. **Track 2.1 "implement a lightweight provider" → wire the existing one.** `backend/crawler/search_providers/` (`base.py`, `exa.py`, `llm.py`) already implements the lightweight tier — it is built but unwired. The `search` tool still runs the full `CrawlOrchestrator().research()` subprocess path (`backend/agent/tool_bridge.py:3644-3745`), identical to `crawler_query`. REQ-8 is therefore a reroute task (plus registry-description split), not a provider build — with one load-bearing constraint the original track missed: the current path emits REQ-16 `TASK_PROGRESS` + browser-panel frames the chat card consumes, so the reroute must preserve them (locked by CT-DEI-4).
2. **Track 1 item 1 (letter scoring) is contested by as-built evidence.** The engine deliberately scores first-tokens with a tie-break loop (`backend/agent/decision_engine.py:426-453`; rationale at :396-407) after live probes showed the answer position distributes over content tokens, not letters — and session 344 found bare-letter read-out collapses to literal name matching (`backend/agent/tool_decision.py:550-552`). T0 A/B-probes both methods on the labeled battery before T1 commits; REQ-1's ACs hold under either winner (see spec D1 contingency).
3. **Graft recovery needs no new tool-pick wiring.** Grafted/split children carry `tool=None` and already resolve engine-first through `ToolDecisionBox.resolve()` (`backend/agent/agent_kernel.py:15012-15031`). The live critical-failure path routes through the deterministic `_split_step` operator (`:12794-12989`), not the Brain-planning legacy helper (`_der_graft_recovery_plan`, `:13172-13284`, kept for M.3.3 tests). The actual defect is failure memory: resolve evidence carries no `failed_tool`/error (`:15016-15020`), and `_split_step` resets failure counters unconditionally (`:12986`) — so a grafted child can re-pick the tool that just failed (the observed conv-144 3x repeat pattern). REQ-11 fixes exactly this: failure-evidence veto that survives the reset, plus a cheap `recovery_strategy` engine gate before Brain planning spend.

### 8.2. Findings That Were Missing From the Spec (Now REQ-8–REQ-12)

| Doc finding | Spec home | Why it was missing |
| :--- | :--- | :--- |
| §3.4 + Track 2.1: `search` ≡ `crawler_query` backend | REQ-8 (tier wiring) | Spec covered scoring/args but never the provider tier |
| Track 2.2: worked examples never contrast `search` vs `crawler_query` | REQ-9 (example de-bias) | Head examples (`decision_engine.py:356-373`) unchanged by any REQ |
| Track 3.2: regex target extraction for `vision_detect_element` | REQ-10 (vision target fast-path) | REQ-5 covered capture dedup only, not arg generation |
| Graft re-pick + Brain-cost recovery planning | REQ-11 (recovery-aware resolution) | Recovery was assumed wired; only the pick was, not the memory |
| §3.3: `_asyncio.run` sync block in `_mem_lookup` (`agent_kernel.py:14656`) | REQ-12 (off-thread lookup) | Design ripple cited the file but no REQ owned the block |

### 8.3. Current Line References (This Doc's Citations Have Drifted)

| This doc cites | Live location (2026-09-25) | Status |
| :--- | :--- | :--- |
| `decision_engine.py:426-453` tie-breaker | Same lines | Current |
| `decision_engine.py:477-520` always-autoregressive args | `generate_args` at `:645-693`, still no fast-path | Current (shifted) |
| `tool_decision.py:56` `"what's"` token | `:51-54`, still present | Current |
| `tool_decision.py:464-473, 534` cap truncation | Slice at `:538-543`, lanes built from truncated `names` at `:603-605` | Current (shifted); defect live |
| `tool_bridge.py:1601` screenshot capture | `:1709/1719` + def at `:2055`, still duplicated | Current (shifted) |
| `agent_kernel.py:14205-14210` sync block | `_mem_lookup` at `:14681`, `_asyncio.run` at `:14830` (re-pinned 2026-09-25; the `:14507`/`:14656` figures in this table's first edition had already drifted) | Current (shifted); block live |
| `agent_kernel.py:14187` mem-lookup de-bias | Same function now at `:14681` | Shifted |

### 8.4. Full Wiring Survey (2026-09-25 — Every Brain Call + Heuristic Checked; Specced as REQ-13–17, Waves 6–7)

Method: enumerated all 22 `self.infer` / `router.generate` call sites and all keyword-heuristic classifiers in `backend/agent/`, then kept only Choice-shaped decisions (the engine scores options; it never writes prose). Content generation stays on the Brain — planning (`agent_kernel.py:6427`), final synthesis (`:18409-18489`), failure summary (`:13515`), TTS brief (`:3991`), tool-less step execution (`:14448-14476`). Safety and budget invariants (permissions, veto caps, termination budgets) stay deterministic and are NEVER engine territory.

Already wired: `tool_choice` (box), `presentation` (`agent_kernel.py:14060`), `narration` (`narration.py:260`).

Ranked candidates (value = frequency × Brain cost × calibration fit):

1. **Reviewer verdict** (`der_loop.py:1120`, `pass|refine|veto`) — runs per step, the hottest Brain verdict in the loop. Engine scores the 3-way Choice; Brain writes the `refined` text only on refine. Highest saving per turn.
2. **Sufficiency gate** (`agent_kernel.py:13397`, `{sufficient, missing}`, 100 tokens, temp 0.0) — runs at every graft decision. Engine scores the bool; Brain writes `missing` only when insufficient. A cheap gate in front of an already-cheap call still wins on frequency.
3. **`explorer.propose()` engine-first scoring** (`explorer.py:122-214`) — the single resolver for graft-goal steps spends a 400-token Brain call before pheromone fallback. A ~40ms engine Choice over `live_tools` belongs in front. DER steps are covered via the box; the legacy/graft-goal path is not.
4. **ModeDetector inference** (`mode_detector.py:43-80`, `agent_kernel.py:7274`) — 6-way classification (spec/research/implement/debug/test/review) by keyword lists plus a hand-set confidence. Same brittleness disease as `_VISION_TOKENS` and `_is_web_intent`. Slash commands stay deterministic overrides; the engine replaces only the keyword-inference branch, and its confidence replaces the hand-set float.
5. **Web-intent heuristics** (`agent_kernel.py:6723` + `:6753`, mirrored in `explorer.py:53-69`) — three copies of one trigger-phrase list deciding web routing before the engine ever sees the goal. Fold into a `web_intent` engine consumer or into the `tool_choice` menu directly; delete the copies. Same fix shape as REQ-3.
6. **Explorer done-bit** (`agent_kernel.py:18119`, `{done, description}`) — engine scores done/continue; Brain writes the next-goal description only on continue.
7. **Drift check** (`agent_kernel.py:18212`, `{on_track, note, suggestion}`, every 3 steps in FULL mode) — engine scores the bool; Brain writes note/suggestion only on drift.
8. **RespondDirect ReAct loop** (`agent_kernel.py:3111-3129`) — a parallel tool-choice path with native function calling that bypasses `ToolDecisionBox` entirely. Either route its tool calls through the box or shadow-record engine rows so calibration sees the traffic it currently misses.
9. **Retry-vs-graft-vs-escalate triage** — heuristic counters own this today; REQ-11's `recovery_strategy` consumer is the seam to grow it from.
10. **Model-selection authority (local vs cloud)** — a natural engine consumer; see `specs/model-selection-authority/`. Needs its own spec amendment, not this one.

Explicit non-fits (checked, rejected): query refinement (`:13893`, rewriting not choosing); plan/synthesis/summary/TTS/step-execution prose (generation); `_der_graft_recovery_plan` planning (covered by REQ-11's strategy gate); all permission, veto-cap, and termination-budget decisions (deterministic safety, engine may advise but never permit).

Spec mapping: items 1→REQ-13 (T17), 2/6/7→REQ-14 (T18), 4/5→REQ-15 (T19), 3/8→REQ-16 (T20), 9→REQ-17 (T21); item 10 deferred to `specs/model-selection-authority/`. Each REQ splits foundation ACs (Wave 6: shadow-first, T17–T21 + TG-6) from optimization ACs (Wave 7: measured enforcement flips, T22 + TG-7, bar = ≥50 rows at P(correct | conf ≥ threshold) ≥ 0.90, Brain-text-only on negative branches per D8). Matrix counts 62/62 ACs, 0 unmapped after this section; the Wave 7 bar is raised to ≥100 rows + ECE-bound in §9.

---

## 9. Amendment Record (2026-09-25 — JEV Fidelity Review)

A review of this doc + `specs/tool-decision-engine-improvements/` against JEV engineering (TypeSafe AI "System One": Choice/Score/Noul primitives, RLCD calibrated decisions, parallel multi-question scoring, per-question criteria) and against live code. Full analysis: `specs/tool-decision-engine-improvements/REVIEW-2026-09-25-jev-fidelity.md`. This section records what changed.

### 9.1. Code-verified defects (doc/spec described behavior the code does not have)

| Finding | Evidence | Spec home |
| :--- | :--- | :--- |
| **Warm-head snapshot is dead code** | `save_state()` at `decision_engine.py:308`; **no `load_state()` call anywhere in `backend/`**. Scoring re-evaluates the full prompt (`:410-412`). §2's 150–250ms arithmetic and the design's architecture diagram both assume it works. | New task **T23**, gate TG-1; test BT-DEI-12 |
| **Letter scoring not implemented; tie-break loop live** | `_score_options_one_pass` does first-token scoring (`:426-433`) + `reset()`/full-eval loop (`:437-453`); `_letter_token_ids` populated (`:315-319`) and never read. AC1.3/AC1.4 FALSE as-built. | REQ-1 invariant note + D1 correction; T1/TG-1 |
| **Noul primitive does not exist** | `grep -ri noul backend/` → zero hits, yet `docs/architecture/tool-decision-engine.md` (renamed `oracle.md` 2026-09-26):148-149 claims "typed Choice/Noul primitives" reproduced | REQ-14 AC14.6; doc §7 to correct |
| **REQ-5 covered 1 of 2 duplicate-capture sites** | `_capture_screenshot_blob()` at `tool_bridge.py:1709` (vision) **and** `:1719` (GUI) | REQ-5 amendment + T5; scope question recorded, not silently widened |
| **Amendment line refs drifted same-day** | `_mem_lookup` is at `:14681` (not `:14507`); `_asyncio.run` at `:14830` (not `:14656`) | §8.3 re-pinned above |

### 9.2. JEV-doctrine gaps (now REQ-18–REQ-20)

| Gap | Why it matters vs JEV | Spec home |
| :--- | :--- | :--- |
| **Calibration asserted, never measured** | AC6.3 is precision-at-threshold, not calibration; no ECE/Brier/reliability anywhere. `softmax_tau=0.5` (`:126`) sharpens the softmax to cross 0.85 — calibration-destroying by construction, while the code calls its output "calibrated." RLCD's entire purpose is to guarantee confidence tracks correctness. | **REQ-18** (T24); Wave 7 bar now requires ECE |
| **No per-question criteria** | The prompt head is consumer-independent (`:356-373`, "Choose the best tool…") and warmed only for `"tool_choice"` (`:304`). REQ-13–17's ~7 consumers would all be scored under tool-selection examples with zero criteria of their own. | **REQ-19** (T25, lands before T17–T21) |
| **No parallel multi-question scoring** | JEV's defining property ("adding questions barely changes response time"); the loop currently pays N full passes for N judgments about one state | **REQ-20** (T26) |
| `Score` primitive absent | JEV ships three primitives; engine has Choice only | Non-Requirements: explicit deferral to `specs/model-selection-authority/` |
| `Noul` modeled as 2-way Choice | JEV's Noul is a single calibrated P(statement true) | REQ-14 AC14.6 |
| Enforcement bar 50 rows | JEV guidance is 100–500 calibration samples; ±0.08 at n=50 | Wave 7 bar raised to ≥100 |
| No model pinning | glob `LFM2*350M*.gguf` (`:143`/`:157-160`); a swap silently invalidates every threshold (JEV: pin versions) | REQ-6 AC6.5 (T27) |
| Silent input truncation | JEV errors on budget overflow, never truncates; cuts at `:374`/`:379`/`:386` are unlogged | REQ-6 AC6.6 (T27) |
| Residual text generation in `generate_args` | REQ-7 validates null/missing but not wrong-non-null values | Recorded; enum/path/pattern validation recommended |

### 9.3. What was already faithful (unchanged)

D7's shadow-first → measured-enforcement discipline is exactly JEV's "never set thresholds without calibration data" and is the spec's strongest part. D8 (engine scores, Brain writes) is correct JEV shape. The Non-Requirements list maps cleanly onto JEV's boundaries. The bottleneck diagnosis in §3–§4 was verified accurate at every cited site.

### 9.4. Counts after this amendment

79 ACs across 20 REQs; tasks T0–T27 + gates TG-0–TG-7. New: REQ-18 (5 ACs), REQ-19 (4), REQ-20 (4), REQ-6 +3, REQ-14 +1. New tests: CT-DEI-8/9/10, BT-DEI-10/11/12.

### 9.5. Citation sweep and test baseline (2026-09-25)

Every remaining `Verified:` citation in the spec was traced against live code. **All are accurate except REQ-14**, whose done-bit and drift refs (`:18102-18121`, `:18202-18214`) had drifted ~150–180 lines onto unrelated code; the real sites are `:18261-18306` and `:18382-18397` (corrected in the spec and design ripple row). REQ-13 (`der_loop.py:1109-1145`), REQ-15 (`explorer.py:53-69`, `agent_kernel.py:6723`/`:6753`), REQ-16 (`explorer.py:146-150` 400-token call, `agent_kernel.py:3111-3129`), REQ-7 (`capabilities.py:729`/`:778`) and REQ-8 (`search_providers/` present) were all verified exact.

**Baseline:** decision-engine test set = `2 failed, 70 passed` (15.11s). Both failures are **STALE TESTS, not regressions** — `TestCtDe3Ledger::test_reason_engine_decision_records_route_only_row_once` and `TestBtDe4ReasonSingleRow::test_none_choice_one_route_only_row` assert route `"escalated"` while the code emits `"engine-none"`. Their comments encode session-345 behavior; the **2026-09-24 OQ-2 refinement** (`tool_decision.py:698-719`, documented `:99-114`) now commits a confident `NONE` when the goal carries no gather/action signal, and both fixtures use signal-free descriptions (`"just think"`, `"nothing to do"`). Owner-decision item — same class as the tracked `test_unparseable_json` stale red (`docs/architecture/tool-decision-engine.md`, renamed `oracle.md`:176-178). Not a TG-1/TG-2 blocker; **do not edit the tests** (TEST RULE).

---

## 10. Amendment Record (2026-09-25 b) — MODEL DECISION: GLiNER2.5-Decide ONNX REPLACES LFM2-350M-Extract

**Decision: the resident decision model changes from `LFM2-350M-Extract` (GGUF / llama.cpp) to
`GLiNER2.5-Decide` (ONNX / onnxruntime). The LFM path is retired, not kept as a fallback.**

Full measurements: `specs/tool-decision-engine-improvements/BENCH-2026-09-25-model-comparison.md`.
Harness: `scripts/bench_decision_models.py`.

### 10.1. Evidence (60 labeled cases, identical per-case menu)

| Configuration | Accuracy | Coverage | Accuracy ≥threshold | p50 |
| :--- | ---: | ---: | ---: | ---: |
| **GLiNER2.5-Decide ONNX int8 @0.40** | **71.7%** | 38.3% | **100.0%** | **119.2 ms** |
| LFM2-350M-Extract flat @0.85 | 60.0% | 40.0% | 70.8% | 1172.4 ms |
| LFM2-350M-Extract tree (`decide_tree`, production) @0.85 | 33.3% | 50.0% | 66.7% | 5398.9 ms |
| LFM2.5-350M base flat @0.85 | 11.7% | 91.7% | 3.6% | 845.5 ms |
| LFM2.5-350M base tree @0.85 | 25.0% | 80.0% | 31.2% | 3143.9 ms |

Three findings drove the decision:

1. **The hierarchical path was the worst configuration.** `decide_tree` costs 26.7 accuracy
   points and 4.6× latency versus flat scoring on the same model.
2. **The LFM2.5-350M "upgrade" was a large regression** — ~5× worse overall, ~20× worse above
   threshold, with a single-token collapse to `read_file` at confidence up to **0.9999**.
   Newer generation ≠ better for a task-tuned slot.
3. **GLiNER wins on every axis that matters**, and its confidence is *genuinely calibrated*:
   all 17 errors carry confidence ≤ 0.352; above 0.40 it is never wrong.

### 10.2. Why the ONNX route (and why the earlier rejection was wrong)

The safetensors route (`fastino/GLiNER2.5-Decide` + `gliner2`) is unusable here: `gliner2[local]`
requires `transformers<5` while the project runs 5.12.0, and even satisfied,
`AutoExtractor.from_pretrained` fails to load the checkpoint (`model_type: extractor` unknown).
**This doc's first pass wrongly generalised that into "GLiNER is not a fit."**

`nishparadox/gliner2.5-decide-onnx` removes every blocker:
- **Torch-free** reference runner (`gliner_onnx.py`) using **onnxruntime + tokenizers + numpy**
  — all three already present in the venv. **No second environment, no transformers change.**
- ONNX is a self-contained graph, so the custom-architecture load failure never arises.
- Session init ~15 s for the full 60-case battery (vs 81 s + 65 s cold-import for transformers).

**The GGUF requirement was a proxy, not a requirement.** The real constraints are
CPU-resident, in-process, no new heavy dependency — and `onnxruntime` satisfies all three.

### 10.3. What this invalidates

| Spec item | Fate |
| :--- | :--- |
| REQ-1 (single-token option scoring; T0 probe) | **SUPERSEDED** — no letters, no first-token, no tie-break loop. T0/T1 become moot. |
| `softmax_tau` sharpening (`decision_engine.py:126`) | **DELETED** — GLiNER's softmax is natively calibrated; sharpening would destroy that. |
| REQ-18 (calibration measurement) | **RETAINED, re-scoped** — measurement stays; the tau-resolution clause is dropped. |
| REQ-19 (per-consumer prompt heads) | **REPLACED** by per-consumer GLiNER `Task`s (schema, not prompt head). |
| REQ-20 (batched multi-question) | **SATISFIED NATIVELY** — GLiNER takes multiple `Task`s in one call. |
| REQ-3/REQ-4 (vision tokens, pre-cap lanes) | **RE-EVALUATE** — the 6-candidate cap existed because the 350M collapsed beyond 4–6 options; GLiNER handled a 17-domain benchmark and this battery's menus natively. |
| `decide_tree` / REQ-17 hierarchy | **RETIRED** for tool choice — it is the worst-measured path. |
| CT-DEI-1 (zero VRAM, CPU-resident) | **RETAINED** — onnxruntime CPUExecutionProvider satisfies it. |
| `llama-cpp-python` dependency | **STAYS** — used by 8+ other modules (`agent_kernel`, `local_model_manager`, `vision`, `iris_gateway`, `main`, `memory/config`, …), not only the decision engine. |
| `onnxruntime`, `tokenizers` | **MUST BE DECLARED** — both installed but absent from `requirements.txt`. |

### 10.4. Threshold retune (mandatory)

GLiNER's softmax spreads across the candidate menu, so the LFM-era 0.85 cut is wrong for its
distribution. Measured reliability curve — **all 17 errors ≤ 0.352**:

| threshold | coverage | accuracy above |
| ---: | ---: | ---: |
| 0.30 | 63.3% | 86.8% |
| 0.35 | 45.0% | 96.3% |
| **0.40** | **38.3%** | **100.0%** |
| 0.45+ | ≤33.3% | 100.0% |

**New default threshold for `tool_choice`: 0.40.** Coverage is comparable to today's 40% while
accuracy at threshold goes 70.8% → 100%.

### 10.5. Accepted costs

- **+432 MB** on disk (651 MB vs 218.7 MB). int8 is lossy (`max |ΔP| ≤ 0.18`) yet still reaches
  100% at 0.40; `model_fp16.onnx` (874 MB) or `model.onnx` (1.75 GB) are exact if needed.
- **New inference path** — onnxruntime alongside llama.cpp, not a drop-in for the existing
  engine module. The backend abstraction is REQ-21.
- **No LFM fallback** (owner decision). The engine returns `None` on failure and callers take
  their existing legacy-heuristic path, exactly as they do today when the engine is unavailable.
