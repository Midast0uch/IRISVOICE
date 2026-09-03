Here is the definitive, merged specification. It combines the deep architectural rigor and problem register of the first version with the sharp, actionable **Policy Matrix**, explicit **JSON telemetry contract**, and **phased rollout plan** of the second version. 

This is the master document to drop into your architecture repository.

***

# Resonant Recall Mailbox: Empirical Policy & Integration Spec

**Status:** Active / Ready for Implementation  
**Dependencies:** `Wormhole-resonant-recall.md` (Parent Physics), `FAULTLINE.md` (Tool Taxonomy), `Node Chains` (Workflow Crystallization)  
**Core Philosophy:** **Empirical-Driven Architecture.** We do not hardcode operational policies (overwrite rules, TTLs, cadence mappings). We define **Policy Arms** (multi-armed bandit style), instrument them with strict telemetry, and let the system’s memory (Level 3 Meta-Learning) empirically select the best policies based on actual utility: *Chain Genesis rates* and *FAULTLINE avoidance*.

---

## 1. Governing Principles

Before touching code, the implementing agent must internalize these constraints:

1.  **The Mailbox is Delivery, Not Scoring:** The mailbox must not invent a new relevance engine. Candidate quality is owned by the parent Wormhole spec (Hash, Hex, Hyperedge, Beta-Bernoulli). If a new scored quantity is needed, it belongs in the parent spec.
2.  **Bayesian Updates Happen *After* Evidence:** A candidate does not become better merely because it is new. Beta-Bernoulli updates (`alpha`/`beta`) happen only after outcome evidence (used, ignored, failed, contradicted).
3.  **Safety Beats Cleverness:** If evidence is missing, prefer non-blocking behavior, lower staleness, and conservative defaults. A missed recall is less harmful than a hung generation loop.
4.  **The Tag is the Product:** If the Mailbox delivers a memory, and the agent uses it to succeed, but the telemetry fails to tag it as a recall episode, the Node Chain will not form. **Attribution is the actual deliverable.**

---

## 2. System Integration Map

The Mailbox is the causal bridge between the agent's physics-based memory and its execution systems.

### 2.1 The FAULTLINE Synergy (Tool Failure Taxonomy)
Recall must both **consume** and **produce** FAULTLINE data.
*   **Consumption:** If a recalled node previously resulted in a `walled` or `invalid_params` FAULTLINE event, its Hyperedge posterior takes a `beta` penalty. The Mailbox naturally deprioritizes it.
*   **Production:** If the Mailbox injects a recall that *prevents* a FAULTLINE error (e.g., recalling a workaround for a known `transient` API timeout), the Hyperedge receives an `alpha` boost.
*   **Telemetry Hook:** Every Mailbox injection must be tagged with a `recall_trace_id` so the `ToolBridge.execute_tool` boundary can attribute subsequent FAULTLINE events to the recalled context.

### 2.2 The Node Chain Genesis Bridge (The C3 Path)
The ultimate proof of a useful recall is that it crystallizes into a reusable workflow (Node Chain).
1.  **Mailbox** injects recall at a safe DER boundary.
2.  **Agent** uses the recalled mediator/tool.
3.  **Task** succeeds.
4.  **`recall_phases.py:433`** (`_log_recall_episode`) logs the episode with `source_channel='recall'`, `outcome_type='success'`, and the `ops_trace`.
5.  **`node_chain.py`** groups these episodes. When count >= 3, it extracts a Chain and generates `chain.md`.
*   *Crucial Constraint:* If the Mailbox does not cleanly tag the injected recall in the active DER context, `_log_recall_episode` cannot attribute the success, and the **C3 test will fail**.

---

## 3. The Policy Matrix (Problems & Testable Arms)

Instead of assuming the best solution, we implement decision points as configurable **Arms**. The system logs which arm was used and the eventual outcome, allowing us to empirically prune bad arms.

### 3.1 Mailbox Overwrite Policy (OV)
*Problem: A new candidate arrives while the mailbox is already occupied.*

| Arm ID | Strategy Name | Logic | Pros | Cons |
| :--- | :--- | :--- | :--- | :--- |
| **OV-A** | `Replace-if-Better` | Replace if `new_lower_bound > old_lower_bound + deadband`. | Prevents stale blocks. | Requires score comparison. |
| **OV-B** | `Bounded-Queue` | Hold max 2 candidates; pick best at DER boundary. | Reduces candidate loss. | Adds boundary selection logic. |
| **OV-C** | `Keep-First` | Drop new candidates until current is claimed/expired. | Zero churn, highly predictable. | May miss better late arrivals. |
| **OV-D** | `Faultline-Preempt` | Preempt immediately if new candidate resolves an active FAULTLINE state. | Highly context-aware. | Complex state tracking. |

### 3.2 Staleness & Freshness Gate (ST)
*Problem: The agent's confounder state drifts before the next safe splice boundary.*

| Arm ID | Strategy Name | Logic | Pros | Cons |
| :--- | :--- | :--- | :--- | :--- |
| **ST-A** | `Hard-TTL` | Drop if `time_elapsed > 15s` or `DER_nodes_elapsed > 2`. | Simple, safe. | Time is a poor proxy for relevance. |
| **ST-B** | `Confounder-Revalidation`| Drop if `hex_distance(current, trigger) > 1`. | Physically grounded. | Requires hex math at claim time. |
| **ST-C** | `Continuous-Decay` | `effective_score = lower_bound * exp(-drift_weight * distance)`. | Smooth degradation. | Harder to tune weights. |
| **ST-D** | `Pending-Hint` | Demote stale candidate to short-lived hint for future matching state. | Avoids total loss. | Adds state complexity. |

### 3.3 Late Tier-2 Arrivals (T2)
*Problem: Detached graph walks finish after the original reasoning context has moved on.*

| Arm ID | Strategy Name | Logic | Pros | Cons |
| :--- | :--- | :--- | :--- | :--- |
| **T2-A** | `Mint-Only` | Update Hyperedge topology/landmarks, **do not inject** into prompt. | Prevents context pollution. | Delays immediate utility. |
| **T2-B** | `Strict-Freshness` | Inject only if `Confounder-Revalidation` (ST-B) passes. | Safe injection. | Discards hard-earned walks. |
| **T2-C** | `High-Confidence Override`| Inject if stale, BUT only if `lower_bound > 0.95`. | Captures "eureka" moments. | Over-relies on posterior accuracy. |

### 3.4 Cadence-to-Variance Mapping (CD)
*Problem: High variance oscillation can cause polling storms and SQLite lock contention.*

| Arm ID | Strategy Name | Logic | Pros | Cons |
| :--- | :--- | :--- | :--- | :--- |
| **CD-A** | `Bounded-Linear` | `rate = clamp(base + k*var, min, max)`. | Interpretable. | Can still oscillate. |
| **CD-B** | `Saturating-Exp` | `rate = min + (max-min)*(1 - exp(-k*var))`. | Naturally bounded. | Non-linear tuning. |
| **CD-C** | `Hysteresis` | Require `N` polls of high variance to increase, `M` polls to decrease. | Prevents feedback loops. | Slower reaction time. |

### 3.5 Semantic Collision Guard (SC)
*Problem: Same physics hash, different actual task (e.g., Python async vs React state).*

| Arm ID | Strategy Name | Logic | Pros | Cons |
| :--- | :--- | :--- | :--- | :--- |
| **SC-A** | `Physics-Only` | Trust the Hash/Hex bin completely. | Baseline, zero overhead. | High collision rate early on. |
| **SC-B** | `Objective-Fingerprint`| Require MinHash/SimHash match on `active_file_type` or `task_keywords`. | Cheap, highly discriminating. | Requires fingerprint extraction. |
| **SC-C** | `Context-Signatures` | Use Node Chains REQ-12 context signatures (domain, artifact contract). | Reuses existing machinery. | Depends on chain capture quality. |

### 3.6 Deadlines & Backing Store (DL/BC)
*Problem: Tier-2 walks hanging on SQLite locks or exceeding generation boundaries.*

| Arm ID | Strategy Name | Logic | Pros | Cons |
| :--- | :--- | :--- | :--- | :--- |
| **DL-A** | `Degraded-Mode` *(Mandatory)*| On timeout: cancel, skip, log FAULTLINE, do not retry immediately. | Prevents hangs. | Drops recall temporarily. |
| **BC-A** | `WAL + Single-Flight` | SQLite WAL mode + limit concurrent Tier-2 walks to 1. | Minimal architecture change. | Still risks heavy write contention. |
| **BC-B** | `In-Memory Snapshot` | Tier-2 reads from a topology snapshot refreshed at safe boundaries. | Complete isolation. | Memory overhead. |

---

## 4. The Telemetry & Logging Contract

To let the memory empirically select the best arms, every Mailbox decision must emit a structured event to `system_events` (or equivalent telemetry store).

```json
{
  "event_type": "mailbox_decision",
  "trace_id": "uuid",
  "session_id": "uuid",
  "der_node_id": "node_883",
  "policy_arms_used": {
    "overwrite": "OV-A",
    "staleness": "ST-B",
    "cadence": "CD-C",
    "semantic": "SC-A"
  },
  "candidate": {
    "hyperedge_id": "he_992",
    "tier": "tier_1",
    "posterior_lower_bound": 0.74,
    "trigger_hex": "8812a",
    "claim_hex": "8812b"
  },
  "action_taken": "injected", // injected, dropped_stale, dropped_overwritten, expired_unclaimed
  "outcome": {
    "agent_used": true,
    "faultline_intersect": "prevented_error", // null, prevented_error, caused_error
    "chain_genesis_contrib": true // Did this feed a successful _log_recall_episode?
  }
}
```

### 4.1 FAULTLINE Label Registry Integration
Recall failures must be registered as FAULTLINE Layer 2 labels carrying the canonical dimensions (`retryable`, `blame`, `info_state`):
*   `recall_timeout`: `maybe` / `self` / `unknown`
*   `recall_store_locked`: `maybe` / `world` / `blocked`
*   `mailbox_expired`: `yes` / `self` / `missing`
*   `recall_candidate_stale`: `yes` / `query` / `unknown`
*   `recall_semantic_mismatch`: `no` / `query` / `unknown`

### 4.2 The Feedback Loop (Level 3 Meta-Learning)
At the end of a session (or during maintenance passes), the system aggregates telemetry:
1.  **Which Overwrite Arm** yields the highest `chain_genesis_contrib` rate?
2.  **Which Staleness Arm** minimizes `agent_used: false` (ignored injections)?
3.  **Which Cadence Arm** keeps `db_latency` low while maintaining a high `candidates_found` rate?
*The system then adjusts the default arm weights for the next session via Thompson Sampling or UCB.*

---

## 5. Implementation & Testing Strategy (Progressive Rollout)

Do not attempt to build all arms and the meta-learner on day one. Follow this progressive testing plan to ensure the C3 test passes and FAULTLINE remains stable.

### Phase 1: Shadow Mode & The C3 Baseline (Current Sprint)
*   **Goal:** Wire the Mailbox to `_log_recall_episode` and pass the C3 test.
*   **Action:** Implement **one** default arm for each category (e.g., `OV-A`, `ST-A`, `CD-A`, `SC-A`, `DL-A`).
*   **Crucial Wiring:** Ensure the Mailbox injection formats the recall block exactly as `recall_phases.py` expects, so that when the agent succeeds, `source_channel='recall'` and `outcome_type='success'` are logged correctly.
*   **Validation:** `pytest backend/agent/tests/test_recall_fixes.py::TestC3SkillGenesisSql` passes unmodified. `chain.md` is generated in `data/chains/`.

### Phase 2: FAULTLINE Integration & Telemetry (Next Sprint)
*   **Goal:** Connect Mailbox outcomes to FAULTLINE events.
*   **Action:** Implement the Telemetry Contract (Section 4). Add the `faultline_intersect` logic to the DER reviewer. Register the recall-specific FAULTLINE labels.
*   **Validation:** Trigger a known `walled` tool error. Verify that the Hyperedge that suggested the tool receives a `beta` penalty in the Beta-Bernoulli scorecard.

### Phase 3: Multi-Armed Shadow Logging (Sprint 3)
*   **Goal:** Gather empirical data without risking execution stability.
*   **Action:** Implement the alternative arms (e.g., `OV-B`, `ST-B`, `SC-B`). Run them in **Shadow Mode**: the system executes the default arm, but *logs* what the alternative arms *would have done*.
*   **Validation:** Analyze logs to see if `ST-B` (Confounder Revalidation) would have prevented stale injections that `ST-A` (Hard TTL) missed.

### Phase 4: A/B Testing & Meta-Learning (Sprint 4+)
*   **Goal:** Let the data dictate the architecture.
*   **Action:** Route 20% of sessions to alternative arms. Feed the telemetry into a multi-armed bandit algorithm to dynamically select the best policy arm per confounder region.

---

## 6. Edge Cases & Failure Modes

| Failure Mode | Mailbox Response | Telemetry Emitted |
| :--- | :--- | :--- |
| **SQLite Lock Contention** during Tier-2 walk | Timeout after `tier2_deadline` (e.g., 2s). Drop candidate. Do not block generation. | `mailbox_timeout` (arm: CD-x) |
| **Agent ignores injected recall** | No immediate action. Wait for DER node finalization. | `outcome.agent_used = false` |
| **Recall causes FAULTLINE `invalid_params`** | DER reviewer flags it. Hyperedge `beta += 1`. | `outcome.faultline_intersect = caused_error` |
| **Chain Archive Threshold Reached** | Mailbox continues operating. Chain archiving is deferred to maintenance pass (never on critical path). | N/A (Handled by `node_chain.py`) |
| **`chain.md` generation fails** | Chain stays in memory. Pin `ref_status='stale'`. Retried on next chain change. | `chain_md_generation_failed` |
| **Brand-new candidate (no evidence)** | Use Beta prior seed + posterior lower bound. Do not inject in high-risk contexts until minimum evidence gate is passed. | `new_candidate_trial` |

---

## 7. Contract Locks & No-Change Areas

This spec must not weaken existing contracts. The implementing agent must respect these locks:

1.  **The C3 Test:** `backend/agent/tests/test_recall_fixes.py::TestC3SkillGenesisSql` is the REQ-3 requirement. It must pass unmodified.
2.  **NodeOutcome Vocabulary:** `nodes/outcome.py` Reason closed enum is the pivot trigger vocabulary. Do not add recall-specific reasons.
3.  **Named Skills Shape:** `semantic.py` `named_skills` category shape is locked.
4.  **No Mid-Stream Injection:** Under no circumstances will the mailbox attempt to splice tokens into an active LLM generation stream. Injection happens *only* at DER node / tool-call boundaries.
5.  **Parent Spec Supremacy:** If a change appears necessary in Hyperedge scoring, landmark elevation, coupling math, or resonance drive, that change belongs in `Wormhole-resonant-recall.md`, not here.

---

## 8. Summary for the Implementing Agent

1.  **You are not building a search engine.** You are building an asynchronous, boundary-aligned delivery valve for the Caducean physics engine.
2.  **You are not hardcoding rules.** You are building a harness that can swap between `Replace-if-Better` and `Bounded-Queue` based on a config flag, and logging the results of both.
3.  **Your ultimate boss is `_log_recall_episode`.** If the Mailbox delivers a memory, and the agent uses it to succeed, but the telemetry fails to tag it as a recall episode, the Node Chain will not form, and the system will not learn.
4.  **Respect FAULTLINE.** A recalled memory that causes a `walled` error is a poisoned Hyperedge. Ensure the penalty flows back to the Beta-Bernoulli scorecard.
5.  **Let the memory decide.** Build the telemetry first. The architecture provides the mechanism; the evidence provides the answer.