## Page 1

# IRIS Mycelium Layer

## A Guide for Builders and Stakeholders

Version 1.6 · March 2026 · IRIS / Torus Network

---

## Part 1: The Problem This Solves

### Why AI Assistants Forget Everything

If you have ever had a long, productive conversation with an AI assistant, closed the window, and then started a new conversation only to feel like you are talking to a stranger — you have experienced the core problem that Mycelium was built to solve.

Most AI systems have no persistent memory at all. Every conversation starts completely blank. The AI does not know who you are, what you do, what you care about, what tools you prefer to use, or what happened the last hundred times you worked together. You have to re-introduce yourself every single time.

Some systems try to solve this by saving prose notes about the user — sentences injected back at the start of every conversation. This works, but it is expensive, imprecise, and it misses the most important thing entirely: it tells the agent who you are, but not how to work with you.

**KEY IDEA**

Every word the AI reads costs computing time. Information that could be represented more efficiently means more processing power available for actual reasoning.

When an AI model reads a sentence, it does not just scan the words. It runs every word through multiple layers of calculation. A number — say, a coordinate of 0.95 on a proficiency scale — is already in its native mathematical language. No interpretation required.

### The Memory Architecture Before Mycelium

IRIS Mycelium Layer — v1.6 · Confidential

---


## Page 2

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 2&lt;/page_number&gt;

**Working Memory**
The scratchpad for the current task. High-energy, temporary, wiped when the task ends.

**Episodic Memory**
The record of past conversations and completed tasks. Stored as episodes — summaries of what was asked, what tools were used, what succeeded and failed.

**Semantic Memory**
The distilled stable facts extracted from all past episodes. Before Mycelium, stored and injected as prose sentences — about 60 words of text on every single task, even when most of those facts were irrelevant.

**THE GAP**

Before Mycelium, the system knew who you were — but re-read your entire prose profile on every task. And it never learned how to work with you: how much autonomy to take, when to check in, how deeply to plan.

Confidential · IRIS / Torus Network · March 2026

---


## Page 3

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 3&lt;/page_number&gt;

# Part 2: The Inspiration — Children of Time

## A Science Fiction Novel That Predicted This Architecture

In 2015, author Adrian Tchaikovsky published Children of Time — a novel about an uplifted civilization of spiders developing intelligence over thousands of years. The most striking concept is how they transfer knowledge across generations. They do not write books. They encode understanding chemically — in pheromone trails, in biological signals, in a substrate that the next generation's nervous system reads directly, without re-interpretation or re-learning.

Each individual spider is one session. One conversation. When that conversation ends, the chemical pattern persists. The map grows richer. The paths that worked get stronger. The ones that did not, decay. The forest just works faster.

This is precisely how the Mycelium Layer was designed.

## The Parallel

<table>
<thead>
<tr>
<th>Children of Time</th>
<th>Mycelium Layer</th>
</tr>
</thead>
<tbody>
<tr>
<td>Spider individual</td>
<td>Single IRIS session</td>
</tr>
<tr>
<td>Pheromone trail</td>
<td>Coordinate path through the graph</td>
</tr>
<tr>
<td>Chemical encoding</td>
<td>Floating-point coordinates</td>
</tr>
<tr>
<td>Trail strength grows with use</td>
<td>Edge scores compound with successful tasks</td>
</tr>
<tr>
<td>Forest memory</td>
<td>Permanent landmark entries</td>
</tr>
<tr>
<td>Generational inheritance</td>
<td>Landmark persistence across deleted conversations</td>
</tr>
</tbody>
</table>

Confidential · IRIS / Torus Network · March 2026

---


## Page 4

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 4&lt;/page_number&gt;

# Part 3: What Mycelium Actually Is

## A Coordinate-Graph Navigation System

The name Mycelium comes from the underground fungal network that connects trees in a forest — invisible infrastructure through which nutrients and signals flow between organisms. Invisible to the agents using it, yet quietly routing the right information to wherever it is needed.

At its core, Mycelium is a map. Not a map of places, but a map of who the user is and how they work — represented as positions in seven coordinate spaces. Instead of the sentence "the user knows a lot about AI," the map holds 0.95 on a proficiency scale. The model reads that number directly.

## The Seven Coordinate Spaces

Each coordinate space measures a fundamentally different kind of truth about the user. Seven spaces. The right seven — across three clean categories: Identity, Operational, Environmental.

### Space 1: domain Identity — Intellectual Expertise

<table>
  <tr>
    <td>Description</td>
    <td>Where the user's knowledge lives. Multi-dimensional — a user can be an expert in AI and a novice in legal systems simultaneously.</td>
  </tr>
  <tr>
    <td>Axes</td>
    <td>proficiency [0–1], breadth [0–1], recency [0–1], specialization [0–1]</td>
  </tr>
  <tr>
    <td>Example</td>
    <td>[0.95, 0.70, 0.85, 0.80] -> deep AI expertise, broad, current, specialized</td>
  </tr>
  <tr>
    <td>Why it matters</td>
    <td>Planner uses domain confidence to decide how much to explain vs. assume. High proficiency = skip the basics.</td>
  </tr>
  <tr>
    <td>Update rate</td>
    <td>Slowly — expertise grows over months, not sessions. Decay: 0.005/day.</td>
  </tr>
</table>

Confidential · IRIS / Torus Network · March 2026

---


## Page 5

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 5&lt;/page_number&gt;

# Space 2: conduct Operational Identity — How You Work

**Description**
Not who you are as a person, but how you work with an agent. The only space that directly shapes plan structure — checkpoint placement, step count, autonomy level.

**Axes**
autonomy [0–1], iteration_style [0–1], session_depth [0–1], confirmation_threshold [0–1], correction_rate [0–1]

**Example**
[0.85, 0.70, 0.80, 0.20, 0.10] -> high autonomy, iterative, deep sessions, rarely needs confirmation

**Why it matters**
High autonomy + deep session -> bold multi-step plan. Low autonomy + high correction -> shorter plan with gates.

**Update rate**
0.008/day — faster than identity, slower than tools. Working habits evolve.

**Note**
Derived entirely from behavioral observation, never declarations. Behavior is the truth.

# Space 3: style Identity — Communication Preference

**Description**
How the user wants information delivered. Tone, detail level, directness.

**Axes**
verbosity [0–1], formality [0–1], technical_depth [0–1], directness [0–1]

**Example**
[0.30, 0.20, 0.90, 0.85] -> concise, informal, highly technical, very direct

**Why it matters**
Response length, vocabulary, whether to provide caveats. High directness = no preamble.

**Update rate**
Slowly — communication preferences are stable. Decay: 0.005/day.

# Space 4: chrono Operational — Temporal Activity Patterns

**Description**
When the user works, how long sessions run, what time of day they are most effective.

**Axes**
peak_activity_hour_utc [0–24], avg_session_minutes [0–1], preferred_session_length [0–1], timezone_signal [0–1]

**Example**
[22.5, 0.65, 0.70, 0.85] -> active late night UTC, 90-min sessions typical

**Why it matters**
Planner calibrates effort to available session time. Timezone derived inferentially — no explicit storage.

**Update rate**
Slowly — active hours are stable lifestyle patterns. Decay: 0.005/day.

Confidential · IRIS / Torus Network · March 2026

---


## Page 6

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 6&lt;/page_number&gt;

# Space 5: context Environmental — Active Project (NEW v1.6)

**Description**
What the user is working on right now. Multiple context nodes coexist — one per active project. The nearest fires. Each accumulates its own landmark trail and topological geometry over time.

**Axes**
project_id [0–1], stack_id [0–1], constraint_flags [0–1], freshness [0–1]

**Example**
[0.73, 0.42, 0.60, 0.95] -> Torus project, Python/FastAPI stack, moderate constraints, confirmed this session

**Why it matters**
Planner loads the right regional map for the current project. Switching projects gives a completely different prior even if task text looks similar.

**Update rate**
0.025/day — fastest of any profile space. Stale context misleads. Freshness axis amplifies decay signal.

**Note**
Replaces affect (v1.6). Affect started blind and was downstream of conduct/domain. Context fills the one category the other six genuinely missed.

# Space 6: capability Operational — Hardware Reality

**Description**
What the user's local environment can actually do. Prevents the agent from planning steps the hardware cannot execute.

**Axes**
gpu_tier [0–5], ram_normalized [0–1], has_docker [0/1], has_tailscale [0/1], os_id [0=linux, 0.5=mac, 1=windows]

**Example**
[4.0, 0.5, 1.0, 0.0, 1.0] -> high-end GPU, 64GB RAM, Docker yes, Tailscale no, Windows

**Why it matters**
Planner uses this to decide whether to spawn local workers, use Docker, or delegate to Torus.

**Update rate**
Updated at startup and when hardware changes. Effectively static.

# Space 7: toolpath Environmental — Behavioral Tool Habits

**Description**
The user's actual tool usage patterns, learned entirely from real sessions. Most dynamic space — habits change faster than identity.

**Axes**
tool_id [normalized hash], call_frequency_normalized, success_rate, avg_sequence_position

**Example**
[web_search: freq=0.87, success=0.94, position=0.15] -> used early, almost always works

**Why it matters**
Planner gets pre-scored tool sequence suggestions rather than reasoning from scratch. Reduces plan production cost on recurring task types.

**Update rate**
0.02/day — 4x faster than profile spaces. Tool habits change quickly.

TWO SPACES REPLACED, TWO BETTER ONES

Confidential · IRIS / Torus Network · March 2026

---


## Page 7

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 7&lt;/page_number&gt;

Location (removed v1.5): privacy-compromising, unreliable, redundant with chrono. Conduct replaced it with something that actively shapes plan structure on every task. Affect (removed v1.6): started blind, needed dozens of sessions before coordinates meant anything, and was largely downstream of conduct and domain. Context replaces it with the one category the other six spaces genuinely missed — the external environment, enabling per-project landmark trails and regional topological geometry.

Confidential · IRIS / Torus Network · March 2026

---


## Page 8

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 8&lt;/page_number&gt;

# Part 4: How the Map Gets Built

## Extraction: Coordinates From Behavior, Not Forms

The map is never filled in manually. No profile form. No onboarding wizard. Coordinates are extracted automatically from three sources during the distillation process — a background maintenance pass that runs when the system is idle.

### From What You Say

The Coordinate Extractor listens for facts in conversation. Domain and style signals extracted from explicit statements. Conduct gets a weak bootstrap from statements like "just run it" — low-confidence (0.4) and quickly overridden by behavioral observation.

### From What You Do

The primary source for conduct and toolpath. Every task outcome is observed: was a tool call approved or interrupted? Did the user redirect mid-task? Was the output accepted or heavily revised? These behavioral signals accumulate and converge on the true coordinate. The declaration is a placeholder. Behavior is the truth.

### From Your Hardware

Capability coordinates are detected at startup — GPU tier, RAM, installed tools, OS. Automatic. Silent. Always current.

## Edges: How Coordinates Connect

Coordinates alone are not enough. What makes Mycelium powerful is that coordinates are connected by scored edges — connections that say "when this node is active, that node is probably also relevant."

After many sessions, the system observes that when the domain-AI coordinate is active, the toolpath:web_search coordinate is also active. It creates an edge. Successful task -> traversed edges score up. Failed task -> traversed edges score down. Over time, edges reflecting real patterns strengthen. Noise fades.

## Decay: The Map Stays Current

Every coordinate node decays continuously. Context decays fastest (0.025/day) — stale project context actively misleads. Toolpath decays at 0.02/day — tool habits shift. Conduct at 0.008/day — working habits

Confidential · IRIS / Torus Network · March 2026

---


## Page 9

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 9&lt;/page_number&gt;

evolve slower. Domain, style, chrono, capability at 0.005/day — identity is stable.

Decay is the system's immune response. Information that is not reinforced by recent sessions gradually fades. The map self-corrects without intervention.

Confidential · IRIS / Torus Network · March 2026

---


## Page 10

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 10&lt;/page_number&gt;

# Part 5: Landmarks — Permanent Memory

## What Landmarks Are

Nodes accumulate across sessions. When a cluster of nodes has been activated enough times that it represents a crystallized, reliable pattern — not noise, not a one-off — it becomes a landmark.

A landmark is a permanent entry in the map. Unlike regular nodes, landmarks do not decay. They are the inherited memory of the system. Conversations come and go. Landmarks persist. Deleting a conversation removes the conversation — the landmark remains fully navigable.

### LANDMARK INHERITANCE

The navigational truth survives the conversation that produced it. This is the biological parallel to the pheromone trail persisting after the individual spider is gone.

## Crystallization Threshold

A node crystallizes into a landmark when its activation count reaches 12 (CHART_ACTIVATION_THRESHOLD). At that point it becomes an origin of a local 3D coordinate chart in the Topology Layer — the v2.0 extension that adds spatial reasoning over the landmark graph.

## Landmark Merging

When two landmarks representing the same underlying reality drift close enough together (50%+ coordinate overlap), they merge. The higher-confidence entry absorbs the lower-confidence one. The map condenses. Redundancy collapses into precision.

## Per-Project Context Landmarks

With the introduction of the context space in v1.6, each active project accumulates its own landmark trail. Five active projects produce five context node clusters, each with their own geometry. The map develops regional density around each project — exactly as a geographic map develops detail around populated areas.

Confidential · IRIS / Torus Network · March 2026

---


## Page 11

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 11&lt;/page_number&gt;

# Part 6: The Semantic Header

## From 60 Tokens to 15

Before Mycelium: every task began with ~60 tokens of prose profile notes. "The user is a developer working on AI infrastructure who prefers direct responses and is most active late at night."

With Mycelium: the same information is encoded as a coordinate path — 15 tokens. The model reads it directly in its native mathematical language. 75% token reduction per task. Across a swarm of 3 workers, the saving multiplies.

The semantic header is assembled automatically before every task by navigating the coordinate graph — finding the path through active nodes that covers the most relevant coordinate territory for the incoming task.

### TOKEN ECONOMY

15 tokens instead of 60 means 45 more tokens available for reasoning on every task. At scale — thousands of tasks, multiple workers — this compounds dramatically.

## What Gets Injected

The semantic header contains: the user's coordinate path (what nodes are active), the profile section (natural language rendering of coordinates), relevant episodic injections (similar past tasks), and failure warnings (semantically similar failures injected as explicit warnings). Total: roughly 300–400 tokens of high-density context vs. 1000+ tokens of prose.

Confidential · IRIS / Torus Network · March 2026

---


## Page 12

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 12&lt;/page_number&gt;

# Part 7: The Readable Profile

## The Map Translated into Human Language

The coordinate graph is the truth. The readable profile is the translation — a short paragraph of natural language generated automatically from the current state of the map. It is always derived, never manually written. If the underlying coordinates change, the profile regenerates automatically during the next distillation pass.

<table>
  <tr>
    <td><b>Included in Profile</b></td>
    <td><b>Excluded from Profile</b></td>
  </tr>
  <tr>
    <td>[+] Domain — expertise in natural language</td>
    <td>[-] Toolpath — operational data, agent-only</td>
  </tr>
  <tr>
    <td>[+] Conduct — operational identity, working style</td>
    <td>[-] Affect — removed v1.6, replaced by context</td>
  </tr>
  <tr>
    <td>[+] Chrono — activity timing description</td>
    <td>[-] Location — removed v1.5 entirely</td>
  </tr>
  <tr>
    <td>[+] Style — tone and detail preference</td>
    <td></td>
  </tr>
  <tr>
    <td>[+] Capability — hardware summary</td>
    <td></td>
  </tr>
  <tr>
    <td>[+] Context — active project and environment (v1.6)</td>
    <td></td>
  </tr>
</table>

The profile cannot become stale. When coordinates change, a dirty flag is set. The next distillation pass regenerates the affected section. The profile is always a consequence of the map — never a separate artifact that can drift.

Confidential · IRIS / Torus Network · March 2026

---


## Page 13

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 13&lt;/page_number&gt;

# Part 8: Resonance — Smarter Episodic Recall

## The Problem With Pure Language Similarity

Before resonance, the episodic memory system found relevant past episodes by text similarity alone. This is shallow. "Help me debug this Python function" and "Fix the authentication issue in this API" sound different — but if both involved the same user, same tools, same time of day, same level of autonomy, they navigate nearly identical coordinate territory.

## Multi-Axis Pattern Recognition

Resonance adds coordinate overlap to the retrieval signal. For each past episode, the system asks: how many coordinate spaces light up between this past episode and the current task? An episode matching on domain alone gets a small boost. One matching on domain, toolpath, and conduct gets a major boost.

Final retrieval score: (language similarity) × (1 + resonance multiplier). Language similarity is still there — it just no longer works alone.

### THE CONDUCT RESONANCE EFFECT

An episode where the user ran with high autonomy is a very different reference point than one where they interrupted frequently. Conduct resonance means: not only is this a similar task, it was executed under the same operational contract. The lesson is directly applicable.

### THE CONTEXT RESONANCE EFFECT

Context resonance fires when a past episode was in the same project. A debugging session on the Torus backend three weeks ago is far more relevant than a debugging session on an unrelated project — even if the task text sounds identical. Same project means same codebase assumptions, same constraint flags, same stack.

## Self-Compressing Episodic Memory

### Success episodes — suppressed when covered by coordinates

If a past success episode's coordinate fingerprint is already covered by the current coordinate path, the sentence summary is suppressed. The model already has this in better form as coordinates. Injecting it again adds nothing and costs tokens.

Confidential · IRIS / Torus Network · March 2026

---


## Page 14

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 14&lt;/page_number&gt;

## Failure warnings — always injected

Failure warnings are never suppressed. A note like "last time you ran this on Windows, Docker threw a permissions error" cannot be reduced to a coordinate. These carry the exception — the surprise — the thing the map cannot say.

Result: episodic recall self-compresses over time. On day one everything is novel. By month two, the coordinate graph covers most familiar territory and success sentences gradually disappear. What remains is a tight set of failure warnings.

Confidential · IRIS / Torus Network · March 2026

---


## Page 15

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 15&lt;/page_number&gt;

# Part 9: How It Connects to the Full Architecture

## Data Flow — From Session to Memory (v1.7)

```
User message (text or voice → STT)
    │
    ▼ security_filter → mcp_security (HyphaChannel trust)
    ▼
AgentKernel.process_text_message()
    │
    ├─ TaskClassifier.classify() → (task_class, space_subset)
    │
    ├─ get_task_context_package()
    │     └─ Mycelium assembles:
    │         • coordinate path (7-space position)
    │         • tier1 directives + tier2 predictions (BehavioralPredictor)
    │         • tier3 failures (gradient warnings)
    │         • active contracts (behavioral rules)
    │         • episodic injections (similar past tasks)
    │         • PiN summaries (relevant knowledge anchors)
    │         • topology position
    │
    ├─ _plan_task() → ExecutionPlan
    │     temperature = 0.1 (mature) | 0.25 (immature)
    │
    └─ _execute_plan_der()
          │
          ├─ [DIRECTOR] → picks next step (dependency-aware)
          ├─ [REVIEWER] → reads warnings + contracts + PiN context → PASS/REFINE/VETO
          ├─ [EPISODIC C.4] → mid-loop sub-task hint injection
          ├─ [EXPLORER] → execute tool or direct inference
          ├─ [TOKEN BUDGET] → DER_TOKEN_BUDGETS[mode] enforced per step
          ├─ [TRAILING DIRECTOR] → gap analysis every TRAILING_GAP_MIN steps
          └─ POST-LOOP:
               record_outcome → crystallize_landmark → clear_session → record_stats
```

**After each successful task:**
- Tool call signals update pheromone edge weights
- Outcomes promote CORE nodes, demote ORBIT nodes
- High-score sessions crystallize permanent landmarks (activation threshold: 12)
- Episodic summaries persist beyond context window via Layer 2 storage
- PiNs may be anchored to lock in design decisions made during the task

**Background maintenance (idle-triggered):**
- Edge decay pass — old pheromone trails fade
- Map condense/expand — topology shifts to match usage patterns
- Landmark decay — unverified entries lose confidence
- Profile renderer — dirty sections regenerated
- PiN decay pass — non-permanent PiNs without recent traversal lose weight

## The Pacman Context Lifecycle

Context chunks have zones (trusted / tool), age-weighted retrieval scoring, and a crystallization pathway. Frequently retrieved chunks become Mycelium crystallization candidates — they graduate from episodic memory to permanent landmark status automatically. Stale chunks decay and are pruned. The context window self-compresses over time.

**Layer architecture for unlimited effective context:**
- Layer 1: Raw conversation history (trimmed oldest when budget exceeded)
- Layer 2: Episodic summaries — carries gist forward beyond raw history
- Layer 3: Mycelium coordinate package — compressed accumulated intelligence

## The Swarm Connection

The Mycelium Layer was designed around the swarm geometry: 1 brain + 2 parallel workers. The whiteboard eliminates redundant context inference across workers. Context is assembled once, used by all three. As workers scale horizontally, the semantic cost stays constant — the graph ages, the bill does not.

## The Torus Connection

When tasks overflow local capacity, the Planner dispatches to Torus network nodes. Remote workers receive the coordinate path — not the full prose conversation history. This is how the architecture scales to network size without scaling memory cost. The coordinate graph is the compression format for the entire system's accumulated intelligence.

PiNs travel with the coordinate path in the dispatch payload — permanent PiNs relevant to the landmark cluster active during the task are included. Remote workers have both the coordinate structure and the explicit knowledge anchors needed to understand design intent without reading raw conversation history.

Confidential · IRIS / Torus Network · March 2026

---


## Page 16

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 16&lt;/page_number&gt;

# Part 10: Scaling Properties

## Horizontal — More Workers

The whiteboard means each additional worker costs near-zero semantically. Parallel tasks don't multiply context overhead. The graph grows richer with each additional session regardless of pool size.

## Vertical — Deeper Precision

Sessions compound in geometric precision over time. New sessions don't just add data — they refine existing coordinates, strengthen real edges, crystallize reliable patterns into landmarks, and merge redundant entries. The map gets more precise, not just larger.

## Network — Torus Scale

The coordinate path is the message format for network dispatch. Remote nodes don't need conversation history. The intelligence of the system travels as coordinates, not tokens. Infinite horizontal scaling with constant context cost.

Confidential · IRIS / Torus Network · March 2026

---


## Page 17

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 17&lt;/page_number&gt;

# Part 11: What Mycelium Deliberately Does Not Do

Scope boundaries are as important as capabilities.

## It does not replace episodic memory

Narrative memory — what actually happened, including failures and specific details — stays in the episodic store. Resonance augments retrieval. It does not replace storage.

## It does not delete landmarks when conversations are deleted

The landmark belongs to the map, not the content. Deleting a conversation nulls the pointer. The navigational truth stays.

## It does not track location

Removed in v1.5. Privacy risk. Redundant with chrono. Not coming back.

## It does not store affect coordinates

Removed in v1.6. Affect was largely downstream of conduct and domain, started blind, and carried an architectural liability. Context replaced it with something that actually expands what the system can do.

## It does not override observed behavior with declarations

If you say you want confirmation on every step but never actually interrupt tool calls, your conduct coordinate reflects your behavior. Declarations bootstrap at low confidence. Behavior is the truth.

## It does not touch the identity system

Dilithium-ECDSA post-quantum identity, Torus node identity — completely separate. The Mycelium package never references data/identity.db.

## It does not require the swarm to be running

Single-agent mode works fully. The system becomes more valuable when the swarm activates but does not depend on it.

## It does not manually curate the profile

If the profile says something wrong, fix the underlying coordinate. The profile is downstream of the map. Correcting the map corrects everything downstream automatically.

Confidential · IRIS / Torus Network · March 2026

---


## Page 18

IRIS Mycelium Layer — v1.6 &lt;page_number&gt;Page 18&lt;/page_number&gt;

# Part 12: PiNs — The Knowledge Attachment Layer

## What a PiN Is

A PiN — Primordial Information Node — is any meaningful unit of knowledge anchored to the coordinate graph. The name is intentional. In mycology, primordia are the first visible growth points of a fungal body: the moment underground mycelium becomes something that can be seen, touched, referenced. PiNs are exactly that for IRIS memory. They are the points at which invisible coordinate knowledge becomes a concrete, retrievable artifact.

Unlike coordinate nodes, which are abstract positions in seven-dimensional space, a PiN is a named, typed, human-legible object:

| PiN Type   | What it anchors                                              |
|------------|--------------------------------------------------------------|
| `note`     | Freeform observation or decision record                      |
| `file`     | A specific file or set of files in the project               |
| `folder`   | A directory or subtree                                       |
| `image`    | Architecture diagram, screenshot, visual reference           |
| `doc`      | Specification, README, design brief, research paper          |
| `url`      | External link, API reference, library documentation          |
| `decision` | Architectural or technical decision record (ADR)             |
| `fragment` | Code snippet, prompt fragment, reusable pattern              |

## How PiNs Connect to the Graph

A PiN is not a memo. It is a graph node with typed edges — `pin_links` — connecting it to any other node: landmarks, file nodes, episodes, other PiNs. The edges carry the same relationship vocabulary as the rest of the graph: `documents`, `references`, `implements`, `depends_on`, `contains`, `related_to`.

This means PiNs participate in the pheromone trail system. When a PiN is referenced during a successful task traversal, the edge connecting it strengthens. Repeatedly referenced PiNs accumulate weight. Neglected ones decay — unless marked permanent.

## Permanent PiNs

A PiN marked permanent never decays. This is the same permanence contract as a landmark. Use it for:
- Irreversible architectural decisions
- Specifications that define correct behavior
- Diagrams that future agents must read before touching a module
- Any knowledge that should outlast the sessions that produced it

## PiNs and Provenance

Every PiN carries an `origin_id` — the UUID of the IRIS instance that created it. When IRIS eventually runs on a network of instances, origin provenance ensures that knowledge attribution is preserved regardless of where the PiN ends up.

## What PiNs Are Not

PiNs do not replace coordinates or landmarks. Coordinates describe who the user is and how they work. Landmarks crystallize navigational patterns. PiNs anchor explicit human knowledge — the things that are true because a person decided they are true, not because behavior converged on them. Both layers are necessary. The coordinate graph handles inference. PiNs handle declaration.

Confidential · IRIS / Torus Network · March 2026

---


## Page 12b

# Part 13: Cross-Project Landmark Bridging

## The Problem This Solves

Mycelium accumulates navigational truth within a single project. After dozens of sessions on IRIS, the graph has rich regional density — proven paths, crystallized landmarks, earned edge weights. Now the user starts a new project. Or opens a second codebase. Or moves from one domain entirely to another.

Without bridging, IRIS starts from scratch. The context space shifts. No landmarks. No edge weights. The map is blank where the user has the most experience. This is wasteful — and inaccurate. Some patterns are universal.

## What a Bridge Is

A landmark bridge maps a local landmark to an equivalent landmark in another project or another IRIS instance. It says: "this pattern here is the same pattern as that pattern there."

```
local: lm_g1_backend_health  (IRISVOICE project)
         │
         ── [equivalent, confidence=0.95] ──▶
                                               remote: g1_api_healthy (torus-node project)
```

When IRIS enters the torus-node project and sees a landmark named `g1_api_healthy`, it checks the bridge table. If a match exists with high confidence, it activates the local traversal history for `lm_g1_backend_health` as a prior. The pattern fires immediately rather than re-crystallising from scratch over twelve sessions.

## Bridge Types

| Type         | Meaning                                                         | Effect                              |
|--------------|-----------------------------------------------------------------|-------------------------------------|
| `equivalent` | Same pattern, different codebase, domain, or instance           | Full activation — treated as same   |
| `similar`    | Overlapping pattern — partial match                             | Partial activation — weighted boost |
| `inverse`    | Opposite pattern — what succeeded here tends to fail there      | Fires as a warning, not a boost     |

## Projects Don't Need to Be Code

This is a critical design point. A bridge requires only one thing: that both projects use the same seven-space coordinate map. They do not have to be in the same domain. They do not have to share a codebase, a language, or even a user.

A landmark in a software architecture project (`g1_backend_health`) can bridge to an equivalent landmark in a music production workflow (`g1_audio_pipeline_stable`) if both represent the same underlying pattern: "the primary output path is verified and healthy." The coordinate signature is the same. The domain is irrelevant.

This is what makes Mycelium a universal foundation rather than a code-specific tool. The seven spaces describe the user and how they work — not what they are working on. A landmark is a crystallized pattern of that work. Patterns transfer.

## Bridges as the Precursor to Federation

Cross-project landmark bridging is the first layer of IRIS federation — the mechanism by which knowledge flows between instances on the same network. The full federation architecture (built into the IRIS application layer, not the bootstrap) will eventually:

1. Auto-discover bridges between instances sharing known landmark signatures
2. Compound pheromone edge weights across the network (the more instances agree a path works, the stronger it becomes)
3. Propagate permanent PiNs and permanent landmarks to registered peers
4. Track every merge in an audit log with provenance preserved via `origin_id`

Federation is not synchronisation. It is not replication. It is what happens when many mycelium threads independently navigate the same territory and their pheromone trails begin to converge. The strongest paths win — not because a central authority decided, but because the network agreed through use.

Confidential · IRIS / Torus Network · March 2026

---


## Page 13

# Part 14: Summary

## What Was Built and Why It Matters

### The Core Achievement — v1.7

- Semantic header: 60 tokens of prose -> 15 tokens of coordinates. 75% reduction.
- Swarm semantic load: constant across all workers via shared whiteboard.
- Plan structure: calibrated by observed behavioral data, not guessed from task text.
- Episodic recall: self-compressing over time as coordinates absorb success patterns.
- Context space (v1.6): per-project landmark trails, regional topological geometry.
- Context resonance: past episodes in the same project score highest in retrieval.
- Seven spaces, three categories — Identity, Operational, Environmental.
- Memory persistence: survives conversation deletion at the navigational truth layer.
- Scaling: context cost stays constant as history grows. The graph ages. The bill does not.
- PiNs (v1.7): explicit human knowledge anchored as typed graph nodes with decay + permanence.
- Landmark bridges (v1.7): proven patterns activate across projects and domains without re-crystallisation.
- The architecture grows into correctness. Each layer can evolve without touching the others.

## The Six Layers in Plain Language

**Coordinates** are the truth. Seven spaces across three categories. The map holds them in mathematical language the model reads natively. Conduct tells it how to work with this person. Context tells it what they are working on right now.

**Landmarks** are the inheritance. Each session crystallizes its navigational truth into a permanent entry. Conversations come and go. The truth accumulates. Context landmarks build regional density around each project — the map develops detail where the user spends time.

**The profile** is the translation. The map rendered into human language, always current, never written by hand. Seven sections, each derived from its space. The context section shows what project the user is in and what constraints are active.

**Resonance** is the retrieval signal. Multi-axis pattern recognition across all seven spaces. Context resonance finds past episodes in the same project. Conduct resonance finds episodes under the same operational contract. Both together: the right lesson from the right context.

**PiNs** are the attachment points. Explicit human knowledge — decisions, diagrams, documents, files, URLs — anchored as typed graph nodes. PiNs carry the things coordinates cannot: the things that are true because a person decided they are true. They decay unless marked permanent. They compound in weight like edges when referenced during successful traversals.

**Bridges** are the transfer mechanism. Landmark bridges carry proven navigational patterns across projects, domains, and IRIS instances. They do not require the same codebase or the same domain — only the same seven-space coordinate map. Bridges are the first layer of federation. When many instances independently crystallize the same landmark signature, the network has agreed — without central coordination — on what works.

Confidential · IRIS / Torus Network · March 2026

---


## Page 14

IRIS Mycelium Layer — v1.7

---

**IRIS Mycelium Layer — v1.7**

Coordinates are the truth. Landmarks are the inheritance.

The profile is the translation. Resonance is the retrieval signal.

PiNs are the attachment points. Bridges are the transfer mechanism.

Seven spaces. The right seven. Identity, operational, environmental.

Prime, complete, and designed to grow — into every ecosystem.

Confidential · IRIS / Torus Network · March 2026