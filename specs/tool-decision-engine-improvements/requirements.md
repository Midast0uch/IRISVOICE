# Requirements: Tool Decision Engine Improvements (Sub-450ms Native Latency)

## Decisions Locked

- **Native LFM2-350M-Extract Retention:** Retain the resident in-process `LFM2-350M-Extract` GGUF model via `llama_cpp` on CPU. External router dependencies (such as Laya hosted cloud services) are explicitly REJECTED. All speed improvements must be achieved natively within the resident backend engine.
- **Letter-Indexed Candidate Scoring:** Replace full-string tool name forced continuations with single-letter option tokens (`[A, B, C, D]`). This eliminates prefix collision tie-breakers (e.g., across `vision_*` tools) and enables single forward pass scoring in 25–60ms on CPU.
- **Fast-Path Parameter Slot Filling:** For single-parameter query tools (`search`, `crawler_query`), eliminate autoregressive token generation (`generate_args`). Map the user goal text directly to the `"query"` parameter in 0ms, saving 500–1,500ms.
- **Token De-biasing:** Strip `"what's"` from `_VISION_TOKENS` in `backend/agent/tool_decision.py`. Require multi-word phrases (e.g. `"what's on screen"`) to prevent factual questions from falsely masquerading as vision tasks.
- **Pre-Cap Hierarchical Lane Construction:** Construct hierarchical category lanes (`web`, `vision`, `file`) from the full tool candidate set before applying candidate cap truncation, ensuring web tools are never silently dropped.
- **Vision Capture Deduplication:** In `tool_bridge.py:1601`, reuse the screenshot buffer returned by the vision tool for ledger recording instead of executing a second synchronous screen capture.
- **Dynamic On-The-Fly Composite Recipe Generation & Pre-Flight Contract Validation:** When a multi-step user goal requires interconnecting multiple tools without a pre-existing composite node in the registry, the Brain Agent synthesizes an on-the-fly composite recipe (`DynamicCompositeRecipe`). Before execution, the engine validates artifact compatibility (`NodeSpec.consumes` matches `NodeSpec.produces`) and enforces that zero required parameters are null or missing (`validate_no_null_or_missing_params`). Successfully verified recipes are registered into the node graph as reusable composite nodes (`NodeSpec(composite_of=...)`), enabling the resident Decision Engine to select them directly via sub-450ms letter scoring on future turns.

---

## Introduction

The IRIS Tool Decision Engine was built to provide calibrated, low-latency small-model tool selection. While the resident `LFM2-350M-Extract` model is computationally capable of sub-250ms inference on CPU, runtime decision latency currently averages 1,500–2,500ms. 

This latency explosion is caused by two structural bottlenecks:
1. Candidate prefix collisions among tools sharing prefixes (e.g., `vision_detect_element`, `vision_analyze_screen`), which trigger context resets and sequential prompt re-evaluations (+800–1,100ms).
2. Autoregressive JSON token generation in `generate_args` (+500–1,500ms).
In addition, heuristic false positives on the token `"what's"` push web queries into vision menus, causing high-latency escalations.

This feature optimizes the decision engine to achieve a total decision and dispatch latency under 450ms (targeting 150–250ms) entirely on CPU.

### Success Criteria

- **Decision Scoring Latency:** Candidate probability scoring p50 ≤ 180ms on CPU (down from 800–1,200ms).
- **Total Resolution Latency:** End-to-end tool decision + parameter generation p50 ≤ 450ms for simple tools (down from 2,200ms).
- **Zero Prefix Tie-Breaker Loops:** Eliminate 100% of context resets caused by shared tool name prefixes.
- **Zero Vision False Positives on Search:** 0% of factual "what's" queries (e.g. "what's the weather") routed to vision candidate menus.
- **Decision Accuracy & Calibration:** P(correct tool | confidence ≥ 0.85) ≥ 0.92 measured across benchmark batteries.

---

## Requirements

### REQ-1: Single-Forward-Pass Option Scoring (Lettered Choices)
**User Story:** As the decision engine I want candidate tools scored via single-letter tokens so that option scoring executes in a single forward pass without prefix-collision context resets.

**Verified:** NEW (currently `decision_engine.py:426-453` evaluates full word prefixes and executes serial tie-breaker evals).

**Acceptance Criteria:**
- AC1.1: THE ENGINE SHALL format candidate options in the decision prompt using single-letter indices (`A: <tool_1>`, `B: <tool_2>`, `C: <tool_3>`).
- AC1.2: THE ENGINE SHALL compute candidate probabilities by extracting output logits for pre-tokenized letter tokens at the completion position in a single forward pass.
- AC1.3: THE ENGINE SHALL complete candidate scoring in ≤ 180ms p50 on CPU without calling `_llm.reset()` or re-evaluating prompt tokens.
- AC1.4: IF multiple candidates share a common tool name prefix (e.g. `vision_*`) THEN THE ENGINE SHALL score them independently via distinct letter tokens without triggering a tie-breaker re-eval loop.

**Edge Cases:**
- Candidate list with > 26 tools → The engine applies hierarchical lane grouping before letter scoring.
- Model returns non-letter token → Fallback to argmax over candidate letter logit subset.

---

### REQ-2: Deterministic Fast-Path Parameter Slot Filling
**User Story:** As the runtime I want tools with single-string arguments (`query`) populated directly from the goal text so that the system saves 500–1,500ms of autoregressive JSON text generation.

**Verified:** NEW (currently `decision_engine.py:477-520` always runs autoregressive JSON text completion).

**Acceptance Criteria:**
- AC2.1: WHEN the chosen tool requires only a single parameter `{"query": str}` (such as `search` or `crawler_query`) THEN THE SYSTEM SHALL map the goal text directly to the `"query"` parameter.
- AC2.2: WHEN single-slot parameter extraction applies THEN THE SYSTEM SHALL bypass `generate_args` autoregressive token completion entirely.
- AC2.3: THE SYSTEM SHALL complete parameter assignment in ≤ 1ms with 0 autoregressive tokens generated.
- AC2.4: IF the chosen tool schema requires multiple complex arguments THEN THE SYSTEM SHALL execute schema-constrained JSON generation.

**Edge Cases:**
- Goal text contains surrounding quotes or whitespace → Strip leading/trailing whitespace and quotes before slot assignment.
- Empty goal text → Raise validation error without parameter assignment.

---

### REQ-3: Heuristic & Vision Token De-biasing
**User Story:** As the agent loop I want web queries containing the word "what's" routed to search instead of vision so that factual questions are not intercepted by vision candidate menus.

**Verified:** NEW (currently `tool_decision.py:56` includes `"what's"` in `_VISION_TOKENS`).

**Acceptance Criteria:**
- AC3.1: THE SYSTEM SHALL remove the isolated token `"what's"` from `_VISION_TOKENS` in `backend/agent/tool_decision.py`.
- AC3.2: THE SYSTEM SHALL require multi-word contextual phrases (`"what's on screen"`, `"look at screen"`, `"take a screenshot"`) to trigger vision relevance.
- AC3.3: WHEN a user asks a factual question starting with "what's" (e.g., "what's the stock price of Apple") THEN THE SYSTEM SHALL route the candidate menu to web search tools and SHALL NOT force vision tools to the front.

**Edge Cases:**
- Query says "what's on my screen right now" → Matches multi-word phrase; correctly routes to vision tools.

---

### REQ-4: Hierarchical Lane Construction Fix
**User Story:** As the decision router I want hierarchical category lanes constructed from all available tools rather than a pre-sliced sub-list so that web search tools are not dropped by menu truncation.

**Verified:** NEW (currently `tool_decision.py:534` iterates over `names = names[:_cap]`).

**Acceptance Criteria:**
- AC4.1: THE SYSTEM SHALL populate category lanes (`web`, `vision`, `file`, `misc`) from all pre-filtered candidates before applying candidate cap truncation.
- AC4.2: WHEN candidate count exceeds cap THEN THE SYSTEM SHALL evaluate the top candidate from each category lane.
- AC4.3: THE SYSTEM SHALL never discard the `web` lane when web search tools are available in the registry.

**Edge Cases:**
- All tools belong to one category → Lane evaluates with top candidates up to candidate cap.

---

### REQ-5: Vision Screenshot Deduplication
**User Story:** As the vision executor I want to reuse the captured screen frame instead of performing a second synchronous desktop capture so that vision executions save 100–250ms.

**Verified:** NEW (currently `tool_bridge.py:1601` invokes `_capture_screenshot_blob()` synchronously).

**Acceptance Criteria:**
- AC5.1: WHEN `execute_vision_tool` completes THEN THE SYSTEM SHALL reuse the image buffer returned by `VisionMCPServer`.
- AC5.2: THE SYSTEM SHALL eliminate the second synchronous `_capture_screenshot_blob()` call in `tool_bridge.py:1601`.
- AC5.3: THE SYSTEM SHALL record the shared image buffer to the event ledger asynchronously off the critical thread.

**Edge Cases:**
- `VisionMCPServer` fails to return an image buffer → Fallback to single asynchronous desktop capture.

---

### REQ-6: Observability & Latency Calibration
**User Story:** As the tuner I want structured decision logs and calibration scripts so that I can verify that tool decision engine resolution stays under 450ms.

**Verified:** NEW.

**Acceptance Criteria:**
- AC6.1: THE SYSTEM SHALL log structured JSON metrics for every decision event containing `decision_latency_ms`, `scoring_latency_ms`, `args_latency_ms`, and `is_fast_path`.
- AC6.2: `scripts/bench_decision_engine.py` SHALL assert decision scoring latency ≤ 180ms p50 on CPU across candidate menus.
- AC6.3: `scripts/calibrate_decision_threshold.py` SHALL verify P(correct tool | confidence ≥ 0.85) ≥ 0.92 without vision false positives on search queries.

**Edge Cases:**
- Ledger contains fewer than 50 events → Calibration script reports INSUFFICIENT_DATA without crashing.

---

### REQ-7: On-The-Fly Dynamic Composite Recipe Generation & Pre-Flight Contract Validation
**User Story:** As an agent executing complex multi-tool goals I want the Brain Agent to synthesize on-the-fly composite recipes with pre-flight parameter and artifact validation so that the system handles novel interconnected workflows without requiring hardcoded recipes or failing on null parameters.

**Verified:** NEW (currently composite tools like `crawler_query` are hardcoded in `capabilities.py:729`).

**Acceptance Criteria:**
- AC7.1: WHEN a multi-step user goal requires interconnecting multiple tools without an existing composite recipe THEN the Brain Agent SHALL synthesize an on-the-fly composite recipe (`DynamicCompositeRecipe`) specifying the sub-node execution sequence, data bindings (`{{step_id.output}}`), and target artifact kinds.
- AC7.2: THE ENGINE SHALL perform pre-flight contract validation across the synthesized recipe DAG: verifying that every node's produced artifact kind satisfies the downstream consumer's `NodeSpec.consumes` declaration.
- AC7.3: THE ENGINE SHALL perform pre-flight parameter validation verifying that zero required tool schema parameters are unassigned, null, or unresolved; IF an unresolvable parameter is detected, THE ENGINE SHALL reject the invalid DAG prior to execution and request a repair.
- AC7.4: THE SYSTEM SHALL materialize the validated dynamic recipe into DER `QueueItem`s with resolved dependencies and execute the DAG through `expand_batch_nodes` and `resolve_dependent_params`.
- AC7.5: WHEN a dynamic composite recipe completes with verified user outcome THEN THE SYSTEM SHALL register the validated DAG into the episodic node graph as a reusable composite `NodeSpec`; subsequent matching requests SHALL be selected directly by the resident Decision Engine via letter-scoring fast path in ≤ 450ms without invoking the Brain LLM.

**Edge Cases:**
- Synthesized DAG contains a circular dependency → Reject during topological sort validation and prompt Brain Agent to re-plan.
- Intermediate step produces an empty or failure outcome → Trigger advertise-driven recovery node or escalate to Brain Agent with failure reason.

---

## Non-Requirements (Out of Scope)

- Replacing `LFM2-350M-Extract` with external hosted cloud models or third-party routers.
- Allocating GPU VRAM to the Decision Engine (it must remain 100% CPU resident).
- Modifying the external tool execution signature expected by `AgentKernel`.

