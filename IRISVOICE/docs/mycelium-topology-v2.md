# IRIS Mycelium — Topology Layer
## Specification v2.0 · 3D Landmark Geometry · Vertical Scaling
**March 2026 · IRIS AI Platform · Depends on Mycelium v1.5**

> *"The flat graph describes. The topology layer locates."*

---

## Section 1: Relationship to v1.5 (Foundational Layer)

### Dependency

v2.0 is entirely additive. Every v1.5 table, class, and integration point is unchanged. The foundational layer operates exactly as specified in v1.5. v2.0 adds a geometric layer above crystallized landmarks that v1.5 does not see and does not need to.

The v1.5 foundational layer handles everything about who the user is and how to find relevant past episodes:
- Seven coordinate spaces
- Landmark crystallization and merging
- Resonance-augmented episodic recall
- The readable profile
- All of it stays

What v1.5 cannot do is reason about the **geometry of the space around** crystallized landmarks. It knows that a landmark is mature. It does not know whether the current session is inside the anchor's core, approaching it, drifting from it, or circling it without engaging. v2.0 adds precisely that reasoning — and nothing else.

The integration surface is minimal:
- Two additional calls in `MyceliumInterface`
- One additional step in `DistillationProcess`
- Two new tables
- One new file
- The rest of the codebase is untouched

### The Layered Architecture

**v1.5 Foundational Layer (unchanged)**
- Seven coordinate spaces: conduct, domain, style, chrono, capability, context, toolpath
- Landmark crystallization, merging, permanence
- Resonance-augmented episodic recall
- Readable profile derived from coordinates
- Session Registry / whiteboard — horizontal scaling

**v2.0 Topology Layer (additive)**
- 3D local charts around crystallized landmarks (activation >= 12)
- X / Y / Z axes: domain proximity, operational similarity, temporal convergence
- Five behavioral primitives: Core, Exploration, Transfer, Acquisition, Evolution + Orbit
- Deficiency detection from orbital patterns
- Anchor trajectory and staleness lifecycle
- `TOPOLOGY:` context zone appended to coordinate path
- Vertical scaling: sessions compound in geometric precision over time

---

## Section 2: Why 3D and Not Just Height

### The Limitation of a Linear Model

The intuitive model for landmark depth is height — Floor 1, Floor 2, Floor 3. A landmark at level 3 is more crystallized than one at level 1. Simple. Intuitive. Wrong.

Height is a linear ordering. It implies that landmarks crystallize into a strict hierarchy where some are simply more important than others. But that is not what happens with a user who has developed genuine expertise in multiple areas. A user with crystallized anchors on both AI infrastructure and crypto does not have one that is "higher" — they have two anchors in genuinely different regions of behavior-space.

The relationship between those two anchors is as meaningful as their individual depths. And a new session can be close to both, close to neither, or converging on one while diverging from the other. Height cannot express any of that. Direction is the information that height throws away.

### The Three Axes

Three axes capture the full local geometry around each crystallized anchor. Together they express **direction in behavior-space** — not just how far a session is from an anchor, but where it is relative to it and where it is going.

| Axis | Name | Low (0.0) | High (1.0) |
|------|------|-----------|-----------|
| **X** | Domain Proximity | Intellectually distant from anchor | Intellectually adjacent / inside anchor core |
| **Y** | Operational Similarity | Different tools, conduct, execution pattern | Same tools, same working style, same contract |
| **Z** | Temporal Convergence | Diverging from anchor over time | Converging toward anchor — acquiring mastery |

The power is in the combinations. The same X and Y values mean completely different things depending on Z. Two sessions with identical X=0.6, Y=0.5 are completely different situations if one has Z=+0.30 (actively developing toward the anchor) and the other has Z=-0.25 (drifting away from something previously well-established).

And Z alone does not tell the full story. Z=+0.30 means converging — but converging from where? From X=0.2 (intellectually distant but approaching) is a very different situation from X=0.8 (already inside the anchor's core and deepening). The three axes together describe a position and a direction in a way that no subset of them can.

---

## Section 3: The Five Behavioral Primitives

Every session positioned in a crystallized anchor's local chart is classified into one of five behavioral primitives. The primitive drives all downstream decisions: Planner calibration, deficiency detection, trajectory tracking, and anchor lifecycle evaluation.

### CORE
| Axis | Signal |
|------|--------|
| X (Domain Proximity) | **High** — operating in the anchor's intellectual domain |
| Y (Operational Similarity) | **High** — executing with the anchor's established patterns |
| Z (Temporal Convergence) | **Neutral** — stable, established position |

**Meaning:** User is operating in fully established territory. The deepest, most confirmed position relative to this anchor. Highest-confidence signal in the topology layer.

**Planner Action:** Maximum autonomy. Skip fundamentals entirely. Trust the established coordinate pattern. This is the most efficient operating state — the agent takes the most latitude here.

---

### EXPLORATION
| Axis | Signal |
|------|--------|
| X (Domain Proximity) | **High** — intellectually adjacent to the anchor |
| Y (Operational Similarity) | **Low** — executing differently than the anchor's established pattern |
| Z (Temporal Convergence) | **Any** — direction doesn't change the classification |

**Meaning:** User is in familiar conceptual territory but trying new approaches. Knows the domain but is experimenting with execution. Common at the edge of established expertise.

**Planner Action:** Provide domain support, lighter on operational scaffolding. The user knows the subject — they are testing new execution patterns. Don't over-scaffold the domain.

---

### TRANSFER
| Axis | Signal |
|------|--------|
| X (Domain Proximity) | **Low** — new intellectual territory, distant from anchor's domain |
| Y (Operational Similarity) | **High** — executing with the anchor's established patterns |
| Z (Temporal Convergence) | **Any** — direction doesn't change the classification |

**Meaning:** User is applying established habits to unfamiliar subject matter. The execution contract is familiar but the content is new. Common when skills transfer across domains.

**Planner Action:** Trust the execution pattern — don't over-scaffold conduct or toolpath. Add domain-level scaffolding to support the new intellectual territory without disrupting established habits.

---

### ACQUISITION
| Axis | Signal |
|------|--------|
| X (Domain Proximity) | **Any** — position in X doesn't determine this primitive |
| Y (Operational Similarity) | **Any** — position in Y doesn't determine this primitive |
| Z (Temporal Convergence) | **Positive and above CONVERGENCE_THRESHOLD** — actively converging |

**Meaning:** User is moving toward an anchor — developing mastery in real time. Z is the determining signal here, not the current X/Y position. The trajectory matters more than the current location.

**Planner Action:** Progressive scaffolding appropriate. More depth than CORE because the user is still developing, but forward-leaning. The system is watching mastery develop — support the convergence.

---

### EVOLUTION
| Axis | Signal |
|------|--------|
| X (Domain Proximity) | **Medium to high** — was well-positioned here previously |
| Y (Operational Similarity) | **Medium to high** — was operating in established patterns here |
| Z (Temporal Convergence) | **Negative and below DIVERGENCE_THRESHOLD** — actively diverging |

**Meaning:** User is drifting away from a previously well-established anchor. Expertise is shifting, not declining. The anchor may be becoming stale — the user has grown beyond it or moved on.

**Planner Action:** Do not over-rely on the old anchor's domain assumptions. The user's coordinate pattern is changing. Evaluate whether a new crystallization should be triggered. Reduce assumption of familiarity.

---

### ORBIT
| Axis | Signal |
|------|--------|
| X (Domain Proximity) | **Medium** — near the anchor but not inside the core |
| Y (Operational Similarity) | **Medium** — near the anchor's patterns but not matching closely |
| Z (Temporal Convergence) | **Near zero** — neither converging nor diverging |

**Meaning:** User keeps appearing near the anchor without engaging the core. Not acquiring, not evolving. Circling. This is the deficiency signal — something adjacent is being approached but not landed on.

**Planner Action:** Add scaffolding when tasks touch the orbital region. Not as a recommendation — as calibration. This is the area where the user needs more support than their domain coordinate alone would suggest.

---

## Section 4: Deficiency Detection

### What Orbital Patterns Mean

Deficiency detection is the topology layer's most operationally novel capability. It is also the most subtle — because it is not about what the user is bad at. It is about what they keep approaching without landing.

An orbit pattern means: in the 3D chart space of a crystallized anchor, the user has repeatedly appeared in the same X-Y region with near-zero Z. Not converging. Not diverging. Circling. Five or more sessions in roughly the same position relative to the anchor, none of them moving toward the core.

That pattern signals something in the orbital region that the user is aware of — they keep touching it — but has not been acquired. It might be:

- A skill adjacent to a strong anchor that the user keeps encountering but has not invested in directly
- A tool or technique that appears in their tasks but is being used shallowly
- A domain the user is aware of and curious about but has not committed time to
- A deficiency gap between two strong anchors that the user keeps navigating around

The system does not diagnose which of these it is. It does not make recommendations. It generates a **deficiency signal** — a calibration input that tells the Planner: when tasks touch this orbital region, provide more scaffolding than the domain coordinate alone would suggest.

> **What it is NOT:** Deficiency detection is not a learning recommendation engine. The Planner never tells the user "you should learn security." It uses deficiency signals the same way it uses any coordinate — to calibrate how much support to provide on a specific task. The signal changes agent behavior silently. The user never sees it directly.

### How Detection Works

The `DeficiencyDetector` reads the `mycelium_charts` table for ORBIT-classified sessions relative to a given anchor. It clusters orbital positions in X-Y space using Euclidean distance. When a cluster contains five or more sessions, it generates a `DeficiencySignal` with the centroid of the cluster and the session count.

The centroid tells the Planner where in X-Y space the orbit is occurring. A centroid at X=0.45, Y=0.30 means the user is intellectually somewhat adjacent to the anchor but executing quite differently — a domain gap showing up at the edge of operational familiarity. A centroid at X=0.30, Y=0.55 is the mirror: familiar execution, unfamiliar domain. The two situations call for different scaffolding even though they are both orbit patterns.

---

## Section 5: Trajectory and Anchor Lifecycle

### Z-Axis Trajectory

The Z axis is the trajectory axis. It tells the system not just where the user is relative to an anchor but where they are going. A snapshot of X and Y is a position. The history of Z over time is a trajectory. The two together — current position plus direction of travel — is something no flat graph can express.

Z is computed from the history of Euclidean X-Y distances from the anchor's origin across recent sessions. If that distance is decreasing — the user is getting closer in X-Y space — Z is positive (converging). If increasing, Z is negative (diverging). If stable, Z is near zero.

**Key insight:** Z is a second-order signal. It is not a coordinate of who the user is. It is a coordinate of how the user's relationship with a specific anchor is **changing**. That distinction is why Z belongs in the topology layer and not in the foundational coordinate graph.

### Anchor Staleness and Retirement

Evolution is not failure. When a user's sessions start consistently diverging from a crystallized anchor, it means their expertise is shifting — not that the anchor was wrong. The anchor was accurate when it was built. The user has grown beyond it or moved on. That is a success, not a problem.

The topology layer handles this with anchor staleness evaluation. When an anchor accumulates `STALENESS_SESSION_COUNT` consecutive sessions with negative Z, and a newer landmark of the same task class has higher activation count, the anchor is marked stale. New sessions are no longer positioned relative to it. Historical chart positions are kept for audit.

The underlying landmark is untouched. v1.5 handles landmark lifecycle independently. Staleness is a topology-layer concept — it means the anchor's chart is no longer active, not that the landmark's navigational truth has been lost.

> **Retirement is not deletion.** A stale anchor's chart stops receiving new positions. The landmark itself — its coordinate cluster, traversal sequence, score, everything — is fully preserved in v1.5. It can still fire as a Planner prior. Its nodes are still permanent. Staleness only means the 3D geometry around it has been retired. The map entry remains.

---

## Section 6: What the Planner Receives

### The `TOPOLOGY:` Context Zone

Agents receive the same `MYCELIUM:` coordinate path from v1.5. The topology layer appends a `TOPOLOGY:` zone after it. Compact — typically under 20 tokens. The agents do not need to understand the geometric structure. They need the signals it produces.

```
MYCELIUM: conduct:[0.85,0.70,0.90,0.40,0.25]@31 | domain(ai):[0.10,0.95,1.0]@203
        | domain(crypto):[0.20,0.87,0.90]@156 | confidence:0.91

TOPOLOGY: anchors:[lm_a1b2c3d4,lm_e5f6g7h8] | primitives:[core,acquisition]
        | z:[+0.02,+0.31] | trajectory:[converging on crypto-security]
        | deficiency:[orbital pattern near ai-infra (7 sessions)]
        | ?conf:+0.08
```

**Reading this example:**
- `core` relative to the AI infrastructure anchor — the user is operating in fully established territory. Maximum autonomy. Skip fundamentals.
- `acquisition` relative to the crypto anchor — actively developing, Z=+0.31 strong convergence. Add progressive scaffolding on crypto-adjacent tasks.
- A deficiency signal: 7 sessions orbiting near the AI infrastructure anchor without penetrating the core. Something adjacent keeps coming up. Add support when tasks touch that region.
- Confidence delta +0.08 — high-confidence topology signal overall. Core and acquisition both boost confidence.

The Planner receives this and calibrates plan structure before generating a single planning step. Plan shape is not derived from task text alone — it is derived from the intersection of what the task requires and who the user is, how they work, and where they currently are in their development relative to this task's domain.

---

## Section 7: Vertical and Horizontal Scaling

### Two Independent Dimensions

**Horizontal Scaling (v1.5)**
- More parallel workers
- Session Registry / whiteboard eliminates redundant context across workers
- Each additional worker's marginal context cost approaches zero as the whiteboard fills
- The swarm scales out without linear context growth
- Five workers cost roughly the same context as one. Ten workers cost slightly more than five.

**Vertical Scaling (v2.0)**
- Sessions compound in value over time as anchors crystallize and local geometry refines
- A user with one year of activity does not just have more data — they have a topological structure
- Each new session is more precisely understood than the last because the local chart it is positioned in has been refined by dozens of previous sessions
- The system does not just know more over time. It knows more **precisely**.
- Six months of daily use produces richer local geometry than one month — but the context window cost is identical.

The two dimensions are independent and additive. A large swarm navigating a mature topology layer gets both benefits simultaneously — horizontal parallelism with near-zero marginal context cost per worker, and vertical depth where each worker's coordinate path is anchored in geometrically refined local charts.

### The Convergence at Scale

In a mature system — one with multiple crystallized anchors, months of chart positions, and confirmed trajectory data — a task arrives and the following happens simultaneously:

1. **Horizontal:** Multiple workers spawn. Whiteboard fills. Workers 2-4 receive delta-only context. Near-zero marginal cost.
2. **Vertical:** The brain agent's coordinate path includes a `TOPOLOGY:` zone derived from months of locally refined chart geometry. The primitive classification tells it precisely what relationship the user has with this task's domain right now.
3. **The Planner** generates a plan shaped by both: bold and parallelized (horizontal autonomy) AND calibrated to the user's current development position relative to this domain (vertical precision).

This is the compounding return of the full architecture. Horizontal scaling means more work gets done simultaneously without growing the context bill. Vertical scaling means the work that gets done is more precisely calibrated to the user with every session. Neither improvement hits a ceiling. Neither makes the other worse.

> *The flat graph scales infinitely in depth without growing the context representation. The topology layer scales infinitely in precision without growing the context representation. Both together: the system never hits a ceiling where more history makes it worse. It only ever gets more precise.*

---

## Section 8: Architecture Reference

### New File

One new file. Everything else in the codebase is a minimal addition to existing files.

**`backend/memory/mycelium/topology.py`**
- `ChartRegistry` — manages which landmarks qualify as chart origins
- `AxisCalculator` — computes X, Y, Z for a session relative to an anchor
- `PrimitiveClassifier` — maps (X, Y, Z) to one of the five behavioral primitives
- `DeficiencyDetector` — identifies orbital patterns and generates `DeficiencySignal`s
- `AnchorLifecycle` — evaluates staleness, manages chart origin lifecycle
- `TopologyLayer` — main entry point, all public methods, `TOPOLOGY:` encoding

### New Database Tables

**`mycelium_charts`**
One row per session per active chart origin.

| Column | Type | Notes |
|--------|------|-------|
| `position_id` | TEXT PRIMARY KEY | |
| `landmark_id` | TEXT | FK to `mycelium_landmarks` |
| `session_id` | TEXT | |
| `x` | REAL | Domain proximity (0.0–1.0) |
| `y` | REAL | Operational similarity (0.0–1.0) |
| `z` | REAL | Temporal convergence (signed float) |
| `primitive` | TEXT | CORE / EXPLORATION / TRANSFER / ACQUISITION / EVOLUTION / ORBIT |
| `confidence` | REAL | |
| `created_at` | REAL | Unix timestamp |
| `stale` | INTEGER | 0 = active, 1 = stale |

Indexed by: `landmark_id`, `session_id`, `primitive`, `stale`
Pruned at 90 days during topology maintenance pass.

**`mycelium_trajectories`**
One row per crystallized landmark (chart origin).

| Column | Type | Notes |
|--------|------|-------|
| `trajectory_id` | TEXT PRIMARY KEY | |
| `landmark_id` | TEXT | FK to `mycelium_landmarks` |
| `z_values` | TEXT | JSON array, last 20 |
| `z_trend` | REAL | Weighted moving average (exponential decay weighting) |
| `primitive_history` | TEXT | JSON array |
| `staleness_count` | INTEGER | Consecutive negative-Z sessions |
| `last_updated` | REAL | Unix timestamp |

Updated incrementally — every session that gets chart-positioned updates the trajectory.

### Integration Points

**`MyceliumInterface` — two additions**

```python
# After standard coordinate navigation:
topology_ctx = self.topology.get_topology_context(session_id, active_nodes)
if topology_ctx:
    topology_str = self.topology.encode_topology_context(topology_ctx)
    return f"{coordinate_path}\n{topology_str}"

# After crystallize_landmark():
self.topology.record_session_position(session_id, active_nodes)
```

**`DistillationProcess` — one addition**

```python
# After v1.5 maintenance pass completes:
topo_result = self.memory.mycelium.topology.run_topology_maintenance()
```

### Key Constants

All constants live in `topology.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `CHART_ACTIVATION_THRESHOLD` | `12` | Activations before a landmark becomes a chart origin |
| `CHART_CAPTURE_RADIUS` | `0.65` | How close a session must be to get positioned in a chart |
| `MIN_SESSIONS_FOR_TRAJECTORY` | `4` | Minimum sessions before Z is non-zero |
| `CONVERGENCE_THRESHOLD` | `0.08` | Z >= this → ACQUISITION primitive |
| `DIVERGENCE_THRESHOLD` | `-0.06` | Z <= this → EVOLUTION primitive |
| `ORBIT_RADIUS_OUTER` | `0.55` | Outer boundary of orbital region |
| `ORBIT_RADIUS_INNER` | `0.20` | Inner boundary (inside = CORE, not orbit) |
| `MIN_ORBIT_SESSIONS` | `5` | Sessions needed to confirm a deficiency signal |
| `STALENESS_SESSION_COUNT` | `8` | Consecutive negative-Z sessions before evaluating retirement |

---

## Section 9: What v2.0 Does Not Do

| Constraint | Detail |
|-----------|--------|
| Does not modify v1.5 | Every v1.5 table, class, integration point, and agent-facing output is unchanged. v2.0 adds. It does not change. |
| Does not expose raw geometry to agents | The `TOPOLOGY:` string is semantic — primitives and signals, not X/Y/Z floats. |
| Does not make recommendations | Deficiency signals are calibration inputs. The Planner uses them to add scaffolding silently. The user never sees it directly. |
| Does not retroactively position historical sessions | Charts are created going forward from the point an anchor reaches `CHART_ACTIVATION_THRESHOLD`. |
| Does not create charts for non-crystallized landmarks | Only landmarks with `activation_count >= CHART_ACTIVATION_THRESHOLD` become chart origins. |
| Does not delete stale anchors | A stale anchor's chart stops receiving new positions. The landmark itself is fully preserved in v1.5. |
| Does not touch `data/identity.db` | Same constraint as v1.5. |
| Does not implement Torus multi-network features | Cross-network / multi-user topology is a future phase. This spec covers single-user local topology only. |

---

## Section 10: Testing Checklist

### Topology Layer (v2.0)

- [ ] `ChartRegistry.get_chart_origins()` returns only landmarks with `activation_count >= CHART_ACTIVATION_THRESHOLD`
- [ ] `ChartRegistry.get_nearest_origins()` returns empty list when no crystallized anchors exist
- [ ] `AxisCalculator.compute_x()` returns 0.0 when session has no domain nodes near anchor cluster
- [ ] `AxisCalculator.compute_x()` returns 1.0 when session nodes exactly match anchor domain cluster
- [ ] `AxisCalculator.compute_y()` weights conduct match at 60%, toolpath at 40%
- [ ] `AxisCalculator.compute_z()` returns 0.0 when fewer than `MIN_SESSIONS_FOR_TRAJECTORY` sessions exist
- [ ] `AxisCalculator.compute_z()` returns positive when X-Y distance from origin is decreasing over sessions
- [ ] `AxisCalculator.compute_z()` returns negative when X-Y distance from origin is increasing over sessions
- [ ] `PrimitiveClassifier.classify(0.9, 0.9, 0.0)` returns `CORE`
- [ ] `PrimitiveClassifier.classify(0.3, 0.8, 0.0)` returns `TRANSFER`
- [ ] `PrimitiveClassifier.classify(0.8, 0.3, 0.0)` returns `EXPLORATION`
- [ ] `PrimitiveClassifier.classify(0.5, 0.5, +0.15)` returns `ACQUISITION`
- [ ] `PrimitiveClassifier.classify(0.7, 0.6, -0.10)` returns `EVOLUTION`
- [ ] `PrimitiveClassifier.classify(0.4, 0.4, +0.02)` returns `ORBIT`
- [ ] `DeficiencyDetector.detect_orbits()` returns empty list when fewer than `MIN_ORBIT_SESSIONS` orbit records exist
- [ ] `DeficiencyDetector.detect_orbits()` returns `DeficiencySignal` when cluster confirmed
- [ ] `DeficiencyDetector` does not flag CORE sessions as orbital
- [ ] `AnchorLifecycle.evaluate_staleness()` returns False when `staleness_count < STALENESS_SESSION_COUNT`
- [ ] `AnchorLifecycle.evaluate_staleness()` returns True only when both: staleness_count threshold met AND superseded by newer anchor of same task class
- [ ] `AnchorLifecycle.mark_stale()` does not delete or modify the underlying landmark
- [ ] `TopologyLayer.record_session_position()` returns empty list when no crystallized anchors exist
- [ ] `TopologyLayer.record_session_position()` writes one row to `mycelium_charts` per nearby anchor
- [ ] `TopologyLayer.get_topology_context()` returns None on fresh install (no crystallized anchors)
- [ ] `TopologyLayer.get_topology_context()` returns correct primitives after chart data exists
- [ ] `TopologyLayer.encode_topology_context()` produces string under 25 tokens
- [ ] `TOPOLOGY:` zone appended after `MYCELIUM:` zone in coordinate path string
- [ ] v1.5 tables (`mycelium_nodes`, `mycelium_edges`, `mycelium_landmarks`, `mycelium_profile`, etc.) untouched by any v2.0 operation
- [ ] `run_topology_maintenance()` prunes chart positions older than 90 days
- [ ] `run_topology_maintenance()` runs after the full v1.5 maintenance pass, not before or during
- [ ] `data/identity.db` never referenced in `topology.py`

---

*IRIS Mycelium — Topology Spec v2.0 · v1.5 is the foundation. v2.0 is the geometry built on it.*
*Exploration. Transfer. Acquisition. Evolution. Orbit.*
*Horizontal scales the swarm. Vertical scales the understanding. Both together: infinite precision, constant cost.*
