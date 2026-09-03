## Page 1

# IRIS Mycelium — Kyudo Layer

## Precision & Security Architecture Guide v1.0

Foundational Layer Documentation • IRIS / Torus Network • March 2026

---

## Overview

The Kyudo Layer is the precision and security foundation of the Mycelium memory system. The name comes from Kyudo — Japanese precision archery — where the goal is not hitting the target but achieving a form so precise that hitting the target is inevitable. Security is not the goal. Precision is. Security is what happens when you do precision correctly.

The Kyudo Layer is not a separate security module bolted onto the architecture. It is the organic logic of the Mycelium system applied to two problems simultaneously: keeping external input from corrupting the coordinate graph, and making context assembly cost compound downward with session count rather than upward.

The core insight: **security and precision are the same mechanism**. A source that is safe to act on is also more likely to produce accurate coordinates. A source that might be adversarial is also more likely to produce noisy coordinates. One channel classification system solves both.

The biological model drives every design decision:

*   **Hyphae** are typed transport channels — different channels carry different content with different authority
*   The **cell wall** is a membrane — it enforces permeability by channel type, not by content inspection
*   **Quorum sensing** is the immune response — population-level threat signal triggers coordinated reorganization
*   **Predictive pre-routing** is the mycorrhizal network anticipating demand — nutrients flow toward growth before the signal arrives

None of the security properties require reading content. The channel tells you everything that matters. An attacker who crafts malicious content that looks clean cannot defeat a

---


## Page 2

system that never evaluates content.

None of the precision properties require new infrastructure. Every optimization mechanism reuses what Mycelium already builds — the coordinate graph, the landmark index, the session registry, the whiteboard — and makes it cheaper to operate the richer it becomes.

---

# Part 1: HyphaChannel – Typed Transport Channels

## The Five Channels

<table>
  <tr>
    <td>SYSTEM</td>
    <td>(4)</td>
    <td>- IRIS internals, own specs, coordinate graph outputs</td>
  </tr>
  <tr>
    <td>USER</td>
    <td>(3)</td>
    <td>- user's own documents, notes, direct statements</td>
  </tr>
  <tr>
    <td>VERIFIED</td>
    <td>(2)</td>
    <td>- MCP servers with pinned identity</td>
  </tr>
  <tr>
    <td>EXTERNAL</td>
    <td>(1)</td>
    <td>- web retrieval, unverified documents, unknown sources</td>
  </tr>
  <tr>
    <td>UNTRUSTED</td>
    <td>(0)</td>
    <td>- anonymous sources, identity-failed MCPs</td>
  </tr>
</table>

The integer values represent transport authority. Higher values reach more zones. An UNTRUSTED source cannot earn a higher channel by producing content that looks trustworthy — channels are assigned at source, before content is evaluated, and are permanent for the lifetime of that content item.

## Channel Assignment Rules

<table>
  <thead>
    <tr>
      <th>Input Type</th>
      <th>Default Channel</th>
      <th>Upgrade Condition</th>
      <th>Downgrade Condition</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>IRIS internals</td>
      <td>SYSTEM</td>
      <td>Never changes</td>
      <td>Never changes</td>
    </tr>
    <tr>
      <td>User direct statement</td>
      <td>USER</td>
      <td>-</td>
      <td>-</td>
    </tr>
    <tr>
      <td>User document upload</td>
      <td>USER</td>
      <td>-</td>
      <td>-</td>
    </tr>
    <tr>
      <td>MCP server result</td>
      <td>VERIFIED</td>
      <td>Registered pin match</td>
      <td>Pin mismatch → UNTRUSTED</td>
    </tr>
    <tr>
      <td>RAG web retrieval</td>
      <td>EXTERNAL</td>
      <td>-</td>
      <td>-</td>
    </tr>
    <tr>
      <td>RAG document (unverified)</td>
      <td>EXTERNAL</td>
      <td>-</td>
      <td>-</td>
    </tr>
    <tr>
      <td>MiniCPM observation (user-initiated)</td>
      <td>VERIFIED</td>
      <td>-</td>
      <td>Background trigger → EXTERNAL</td>
    </tr>
  </tbody>
</table>

---


## Page 3

<table>
  <tr>
    <td>MiniCPM observation<br>(background)</td>
    <td>EXTERNAL</td>
    <td>-</td>
    <td>-</td>
  </tr>
  <tr>
    <td>Anonymous / unverifiable</td>
    <td>UNTRUSTED</td>
    <td>-</td>
    <td>-</td>
  </tr>
</table>

Channel assignment happens at the ingestion boundary —
`RagIngestionBridge.on_retrieval()` **or** `MyceliumInterface.ingest_tool_call()` — before any embedding, coordinate extraction, or context injection occurs.

## MCP Source Pinning

An MCP server is **VERIFIED** only if its runtime identity matches its registered pin. Pinning is configured at application startup:

```python
mycelium.register_mcp(
    server_id="filesystem",
    url="https://mcp.iris.local/filesystem",
    content_hash="sha256:abc123..."
)
```

If a server's identity drifts from its pin — compromised server, man-in-the-middle, version change — it is automatically downgraded to **UNTRUSTED** for that session. The event is logged to `mycelium_conflicts` as a **WARNING** -level security entry. No human intervention required.

---

## Part 2: CellWall — The Context Window Membrane

### Zone Architecture

The context window is divided into four zones with fixed permeability rules. Content can only enter a zone if its channel has sufficient authority. It cannot move between zones once placed.

<table>
  <tr>
    <td>SYSTEM_ZONE</td>
    <td>[SYSTEM channel only]</td>
  </tr>
  <tr>
    <td>
      • Mycelium semantic header<br>
      • IRIS system prompt core
    </td>
    <td></td>
  </tr>
  <tr>
    <td>TRUSTED_ZONE</td>
    <td>[SYSTEM + USER channels]</td>
  </tr>
  <tr>
    <td>
      • Episodic context<br>
      • Readable profile<br>
      • User documents
    </td>
    <td></td>
  </tr>
</table>

---


## Page 4

mermaid
graph TD
    subgraph ZONE STRUCTURE
        A[TOOL_ZONE]
        B[REFERENCE_ZONE]
    end

    A -->|content can only flow DOWN in authority, never up| B

    A -->|• MCP tool results|
    A -->|• Verified desktop observations|

    B -->|• External RAG chunks|
    B -->|• Web retrieval results|
    B -->|• Unverified documents|
```

# The Membrane Principle

The cell wall does not sanitize content. It does not scan for injection patterns, suspicious keywords, or malicious payloads. Membranes do not analyze what is trying to cross them — they enforce structural properties.

**What this means in practice:** A malicious document in `REFERENCE_ZONE` can say anything. It cannot issue instructions to the agent because the agent's system prompt — injected via `CellWall.render_zone_headers()` — establishes a non-overridable framing: content in `REFERENCE_ZONE` is read-only reference material. It cannot modify behavior or override directives in higher zones. This framing cannot be suppressed.

The attacker's problem is not that their content gets detected. It is that the zone architecture makes their content structurally incapable of reaching the layers where decisions are made.

# Why No Sanitization

Tool result sanitization — scanning MCP output for instruction-like patterns before injection — sounds protective but has two fatal flaws:

1.  **It is defeatable.** Any filter that inspects content can be bypassed by obfuscation, encoding, or adversarial crafting. The inspection is a race the attacker can always win.
2.  **It is imprecise.** Legitimate tool results frequently contain imperative language, JSON with keys like "instruction", and structured text that pattern-matches to injection signatures. A sanitizer will produce false positives that corrupt legitimate results.

The membrane approach has neither flaw. It does not inspect content. It enforces zone boundaries. The attacker cannot craft their way across a structural boundary.

---


## Page 5

# Part 3: Channel-Weighted Coordinate Extraction

## Decay Modifiers by Channel

Not all coordinate updates are equally trustworthy or durable. External sources produce weaker signal that should decay faster:

<table>
  <thead>
    <tr>
      <th>Channel</th>
      <th>Decay Multiplier</th>
      <th>Initial Confidence</th>
      <th>Rationale</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>USER</td>
      <td>1.0x (standard)</td>
      <td>0.50</td>
      <td>User's own signal — full trust, standard decay</td>
    </tr>
    <tr>
      <td>VERIFIED</td>
      <td>1.5x</td>
      <td>0.40</td>
      <td>Trusted tool, but external — slightly faster decay</td>
    </tr>
    <tr>
      <td>EXTERNAL</td>
      <td>3.0x</td>
      <td>0.30</td>
      <td>Unknown quality — fast decay, earns permanence slowly</td>
    </tr>
    <tr>
      <td>UNTRUSTED</td>
      <td>5.0x</td>
      <td>0.15</td>
      <td>Actively suspect — very fast decay, rarely crystallizes</td>
    </tr>
  </tbody>
</table>

A document the agent retrieves once from an EXTERNAL source produces a coordinate update that decays 3x faster than a behavioral observation. That coordinate needs to be reconfirmed by many successful task outcomes before it contributes meaningfully to navigation. A single retrieval cannot corrupt the graph.

## Hard Channel Rules

Two rules have no exceptions:

**Rule 1 – Conduct is behavioral only.** EXTERNAL and UNTRUSTED channel content MUST NOT modify the conduct space. Conduct (agent autonomy, plan structure, confirmation behavior) is derived from the user's actual behavioral observation — never from external content. An external document cannot change how autonomous the agent behaves. This is the most important protection in the system: it prevents the agent's decision-making authority from being externally manipulated.

**Rule 2 – Landmark trust cap.** A landmark CANNOT crystallize if more than 30% (LANDMARK_TRUST_CAP) of its constituent nodes were derived from EXTERNAL or UNTRUSTED channels. Landmarks are permanent memory — the trust bar for permanence is high. Low-trust sources can influence temporary navigation but cannot write permanent patterns.

---


## Page 6

# Channel-Weighted Retrieval Scoring

Channel trust feeds directly into the retrieval ranking formula:

```python
final_score = cosine_similarity
    × (1 + resonance_multiplier)  ← Mycelium coordinate overlap
    × channel_weight              ← HyphaLayer trust signal
```

Default channel weights:

```python
CHANNEL_WEIGHTS = {
    HyphaChannel.SYSTEM:      1.5,
    HyphaChannel.USER:        1.2,
    HyphaChannel.VERIFIED:    1.0,
    HyphaChannel.EXTERNAL:    0.7,
    HyphaChannel.UNTRUSTED:   0.3,
}
```

A user document that is 80% cosine similar outranks an external web result that is 90% cosine similar. This is the correct behavior — the user’s own notes are more likely to be relevant to their tasks than something pulled from the web. Security and precision are the same mechanism.

---

# Part 4: Quorum Sensing — The Immune Response

## The Biological Parallel

Bacterial quorum sensing works by population threshold: individual cells emit chemical signals, and when signal concentration crosses a threshold, the colony shifts behavior collectively. No single cell decides. The response is emergent from accumulated signal.

The `QuorumSensor` works the same way. Individual threat signals accumulate in `threat_level`. When the population of threat signals crosses `QUORUM_THRESHOLD = 0.60`, `QuorumReorganization` fires. No single anomaly triggers it. Compound signal from multiple independent threat types does.

## Threat Signals

<table>
<thead>
<tr>
<th>Signal Type</th>
<th>Weight</th>
<th>What It Detects</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

---


## Page 7

<table>
  <tr>
    <td>Channel trust violation</td>
    <td>+0.25</td>
    <td>VERIFIED channel content producing coordinates statistically consistent with UNTRUSTED sources – suggests a compromised MCP returning adversarial data</td>
  </tr>
  <tr>
    <td>Coordinate update velocity anomaly</td>
    <td>+0.20</td>
    <td>More coordinate updates in a single session than organic learning would produce – suggests rapid graph poisoning attempt</td>
  </tr>
  <tr>
    <td>Landmark activation anomaly</td>
    <td>+0.30</td>
    <td>A landmark activated far outside its normal task class frequency (3+ standard deviations above historical mean) – suggests an attacker forcing specific pattern activation</td>
  </tr>
  <tr>
    <td>Coordinate channel mismatch</td>
    <td>+0.25</td>
    <td>A VERIFIED + node updating in a direction strongly predicted by EXTERNAL / UNTRUSTED content rather than behavioral observation – suggests indirect injection through a trusted channel</td>
  </tr>
</table>

Threat level decays at QUORUM_SIGNAL_DECAY = 0.05 per clean session. Isolated anomalies fade without triggering reorganization. Only compound, sustained threat signal crosses the threshold.

## QuorumReorganization — What Fires

When threat_level &gt;= QUORUM_THRESHOLD :

1. run_decay() with QUORUM_DECAY_MULTIPLIER = 3.0
   - applied to all nodes modified in current + previous session
   - accelerates expiry of any poisoned coordinates

2. Suspend landmark crystallization for remainder of current session
   - crystallize_landmark() returns None until clear_session()
   - prevents poisoned session from crystallizing into permanent memory

3. Set dirty = 1 on all profile sections
   - forces full profile regeneration from clean graph state

4. run_condense() in fixed space order
   - merges any artificially fragmented nodes

5. run_expand() in fixed space order
   - splits any artificially merged nodes

6. run_profile_render()
   - regenerates all sections from post-reorganization graph

---


## Page 8

7. Log full event to mycelium_conflicts
   - resolution_basis = "quorum_reorganization"

8. Reset threat_level = 0.0

## Why This Works as Security

The map that any attacker spent sessions mapping is gone after QuorumReorganization.
The coordinate geometry has reshuffled. Edge scores have been re-weighted by accelerated decay. The landmark trails they were trying to infiltrate have been suspended.

The attacker cannot know when quorum fires. They cannot know what the post-reorganization geometry looks like. And they cannot prevent it — the trigger is emergent from the population of their own actions, not from any single detectable event.

Critically: QuorumReorganization reuses the existing organic maintenance infrastructure. There is no foreign security mechanism to maintain, no separate security codebase to audit. The system reorganizes the same way it always does — just faster and triggered by threat signal rather than idle time.

---

## Part 5: Subagent Hypha Precision

### Named Channel Profiles

Different subagents have different roles and should have different coordinate access. A code worker should not be able to accidentally modify style coordinates. A research worker should not touch toolpath. A vision worker reading the desktop should only update context and capability — not domain or conduct.

Named channel profiles enforce this at the architecture level:

```python
SUBAGENT_CHANNEL_PROFILES = {
    "code_worker": {
        "read": ["domain", "conduct", "style", "chrono", "capability", "context"],
        "write": ["toolpath", "context"]
    },
    "research_worker": {
        "read": ["domain", "conduct", "style", "chrono", "capability", "context"],
        "write": ["domain", "context"]
    },
    "vision_worker": {
        "read": ["domain", "conduct", "style", "chrono", "capability", "context"]
    }
}

---


## Page 9

json
{
  "write": ["context", "capability"]
}
```

All profiles read all spaces – subagents need full context to do their jobs well. Write access is restricted to the spaces each subagent has standing to update based on what it observes.

## How Precision Improves

Typed channels for subagents produce cleaner coordinate graphs because update responsibility is distributed and bounded. A code worker that writes to `toolpath` and `context` produces highly reliable updates in those spaces – it has many observations, focused signal, no noise from unrelated spaces. A research worker that writes to `domain` accumulates dense, accurate domain expertise without polluting operational spaces.

Over time, the graph develops clear ownership geometry: `toolpath` density around code execution patterns, `domain` density around research patterns, `context` density shared across all workers. This is more precise than a single agent writing to all spaces simultaneously because the signal-to-noise ratio in each space is higher.

## Write Boundary Enforcement

When a subagent attempts to write to a space outside its profile:

*   The write is silently dropped
*   No error is propagated to the subagent
*   The QuorumSensor does NOT increment threat level for this — it is a normal boundary enforcement, not a threat signal
*   The agent continues operating normally on its permitted spaces

Silent drop rather than error is deliberate: a subagent that gets an error on a coordinate write might retry or escalate. Silent drop gives it nothing to react to.

---

## Part 6: The Compounding Cost Curve

The original goal was context windows so optimized that agents barely have to think. Not a one-time token reduction – a cost curve that bends downward with every session.

## Why Standard RAG Gets More Expensive Over Time

---


## Page 10

Standard RAG accumulates history as tokens. More sessions → more episodes → more retrieval candidates → more tokens injected. The cost curve slopes upward. You pay more to operate a system that knows more.

The coordinate graph inverts this. More sessions → richer graph → more accurate pre-navigation → smaller space subsets needed → cheaper context assembly. The system gets cheaper to operate the longer it runs.

## The Six Compounding Mechanisms

Each mechanism reduces cost independently. Together they compound:

1.  **PredictiveLoader** — eliminate navigation on familiar tasks At session boundary, pre-warm the most probable coordinate path based on chrono patterns, active project context, and last session’s task class. When the next task arrives and matches the prediction above 70% cosine similarity, return the cached path without graph traversal. Navigation cost on familiar task types: near zero. Hit rate grows with session count — the graph knows your patterns better every week.
2.  **TaskClassifier** — navigate only relevant spaces A keyword heuristic (no inference) classifies the incoming task and selects the minimum space subset needed. A quick edit needs conduct and context — 2 spaces. A research task needs domain, style, context, chrono — 4 spaces. A planning task needs 5. Full navigation (6 spaces) is the fallback, never the default. Average spaces navigated shrinks as task classification accuracy improves with session history.
3.  **WhiteboardSlicer** — broadcast only what each worker needs The coordinator assembles the full coordinate path once. Each worker receives a slice filtered to their channel profile’s readable spaces. A code_worker gets toolpath + context + shared identity spaces. A vision_worker gets context + capability. Workers doing narrow subtasks stop receiving 6-space paths they only use 2 spaces of. Broadcast cost drops proportional to worker specialization.
4.  **MicroAbstractEncoder** — compress failure warnings to 5 tokens Failure warnings are the one episodic injection that is never suppressed. But their value is in the pattern, not the narrative. A structured 5-token format [space:conduct | outcome:miss | tool:docker | condition:windows | delta:-0.08] carries the same signal as a 15-token prose sentence. As failure pattern coverage grows — more sessions, more failure types encoded — the prose injection cost for episodic context drops toward the floor of just the structured tokens.
5.  **DeltaEncoder** — store traversal diffs, not full paths Consecutive sessions in the same project traverse nearly identical coordinate paths. Only the delta changes — freshness ticks up, a new tool was used, a constraint flag shifted. Store the diff. Traversal log storage

---


## Page 11

compresses dramatically. Resonance lookups compare deltas rather than full paths — faster and cheaper as history depth grows.

6. **Partial Profile Wiring** — fetch only the sections the task needs TaskClassifier selects a space subset. Only those profile sections are fetched and injected. A quick_edit task gets a 2-section profile. A planning_task gets 5. Full profile assembly is reserved for dev inspection and explicit calls — never the inference-time default.

## The Compounding Effect

These six mechanisms share a property: **they all get better as the graph matures.**

PredictiveLoader hit rate grows with session count. TaskClassifier accuracy improves as task class fingerprints crystallize into landmarks. WhiteboardSlicer savings grow as workers specialize. MicroAbstractEncoder coverage grows as failure patterns are encoded. DeltaEncoder compression grows as paths stabilize.

The cost curve:

<table>
  <tr>
    <td>Sessions 1-10:</td>
    <td>prose fallback (maturity gate not yet crossed)</td>
  </tr>
  <tr>
    <td>Sessions 10-30:</td>
    <td>full Mycelium header, full navigation, full profile</td>
  </tr>
  <tr>
    <td>Sessions 30-100:</td>
    <td>TaskClassifier routing kicks in, partial profile wiring active</td>
  </tr>
  <tr>
    <td>Sessions 100+:</td>
    <td>PredictiveLoader cache hits climbing, DeltaEncoder compressing, WhiteboardSlicer savings compounding per worker added</td>
  </tr>
  <tr>
    <td>Sessions 500+:</td>
    <td>steady-state – context assembly cost at floor, graph precision at ceiling, inference budget fully available for actual reasoning</td>
  </tr>
</table>

The system that costs the most to run is the system you just installed. Every session after that is a step toward the floor.

---

## Part 7: How Security and Precision Are the Same Mechanism

The HyphaLayer was not designed as a security system that also happens to improve precision, or a precision system that also happens to provide security. The two properties are unified in the channel classification:

A source that is safe to act on is also more likely to produce accurate coordinates. The user's behavioral observation is the safest signal (you are watching what actually happened) and produces the most accurate coordinates (repeated behavioral confirmation compounds into high-confidence landmarks).

A source that might be adversarial is also more likely to produce noise. An external

---


## Page 12

document retrieved once has unknown quality and unknown intent. It should decay fast (precision) and have low authority over plan structure (security). Both requirements are satisfied by a single channel weight.

**The decay system is the security system.** Slow enough decay for trusted sources to crystallize into landmarks. Fast enough decay for untrusted sources to expire before they influence permanent memory. The quorum reorganization is just the decay system with an emergency multiplier.

**The landmark trust cap is a quality gate.** A landmark built primarily from external sources is not reliable enough to be permanent (precision). It is also not trustworthy enough to be permanent (security). One gate, two properties.

This unification is the reason the HyphaLayer does not require a separate security audit from the rest of the Mycelium system. The security properties are structural consequences of the precision architecture. They cannot be present without each other.

---

# Part 8: Constants Reference

All empirical constants are named and tunable. None are hardcoded. Review and adjust after the first 50 production sessions.

**Security constants ( `kyudo.py` ):**

<table>
<thead>
<tr>
<th>Constant</th>
<th>Default</th>
<th>Tunes</th>
</tr>
</thead>
<tbody>
<tr>
<td>CHANNEL_WEIGHTS</td>
<td>See Part 3</td>
<td>Retrieval score balance between trust levels</td>
</tr>
<tr>
<td>QUORUM_THRESHOLD</td>
<td>0.60</td>
<td>Sensitivity of immune response</td>
</tr>
<tr>
<td>QUORUM_DECAY_MULTIPLIER</td>
<td>3.0</td>
<td>Aggression of reorganization decay</td>
</tr>
<tr>
<td>QUORUM_SIGNAL_DECAY</td>
<td>0.05/session</td>
<td>How fast isolated threat signals fade</td>
</tr>
<tr>
<td>QUORUM_VELOCITY_THRESHOLD</td>
<td>TBD post-deployment</td>
<td>Max coordinate updates before velocity signal fires</td>
</tr>
<tr>
<td>LANDMARK_TRUST_CAP</td>
<td>0.30</td>
<td>Max % external nodes in a crystallizable landmark</td>
</tr>
<tr>
<td>CONDUCT_CHANNEL_LOCK</td>
<td>{EXTERNAL, UNTRUSTED}</td>
<td>Channels blocked from conduct space writes</td>
</tr>
</tbody>
</table>

---


## Page 13

Precision constants (kyudo.py):

<table>
  <tr>
    <th>Constant</th>
    <th>Default</th>
    <th>Tunes</th>
  </tr>
  <tr>
    <td>PREDICTION_MATCH_THRESHOLD</td>
    <td>0.70</td>
    <td>Cosine similarity required for cache hit</td>
  </tr>
  <tr>
    <td>PREDICTION_CACHE_TTL</td>
    <td>300 seconds</td>
    <td>How long pre-warmed cache stays valid</td>
  </tr>
  <tr>
    <td>DELTA_CHANGE_THRESHOLD</td>
    <td>0.05</td>
    <td>Minimum coordinate change to record in delta</td>
  </tr>
  <tr>
    <td>TASK_CLASS_SPACE_MAP</td>
    <td>See Req 16.13</td>
    <td>Task class → space subset routing rules</td>
  </tr>
</table>

Summary

The Kyudo Layer gives the IRIS Mycelium system six properties:

1. **Structural security** – external content cannot influence agent behavior by being clever. Zone architecture contains it before it is ever read.

2. **Trust-weighted precision** – high-trust sources build the permanent navigational map. Low-trust sources contribute temporary signal that decays before it solidifies.

3. **Self-healing immunity** – compound threat signals trigger accelerated reorganization using the existing organic maintenance infrastructure. No foreign security mechanism required.

4. **Subagent precision routing** – typed channel profiles give specialized workers clean coordinate ownership, producing higher signal-to-noise in each space than a generalist agent achieves.

5. **Compounding cost reduction** – six optimization mechanisms that all improve with session count, bending the inference cost curve downward as the graph matures.

6. **Unified mechanism** – properties 1–5 all emerge from channel classification at source and decay rates that reflect trust level. There is no separate security system. There is no separate optimization system. There is one architecture with two names for the same property: precision and security.

The map is never static. The cost keeps falling. The keys to its doors always change.

---


## Page 14

IRIS Mycelium — Kyudo Layer v1.0 • March 2026 • IRIS / Torus Network • Confidential