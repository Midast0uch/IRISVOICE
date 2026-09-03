# PACMAN  
  
## A New Architecture for How AI Systems Digest Context  
  
### IRIS / Torus Network · March 2026  
  
-----  
  
> *“We named it Pacman. Not because it moves through a maze eating dots —  
> though it does. Because the dots don’t come back. What remains is the  
> accumulated consequence of having consumed them.”*  
  
-----  
  
## What This Is  
  
Pacman is a context metabolism architecture. It defines how an AI system  
should ingest, transform, and deliver information — not as text to be  
retrieved, but as concentrated intelligence to be acted on directly.  
  
Most AI systems treat context like a filing cabinet. Documents go in,  
documents come out. The bigger the cabinet, the more it costs to search.  
The longer you use it, the slower it gets.  
  
Pacman inverts this. The longer you use it, the cheaper it gets.  
The more you’ve ingested, the less you need to inject.  
The system doesn’t accumulate information. It metabolizes it.  
  
-----  
  
## The Core Idea  
  
Every piece of content that enters the system is broken down — not stored  
as text but decomposed into coordinate signals the way a digestive system  
breaks food into nutrients. The text is gone. What remains is the extracted  
form: floating-point coordinates that encode the meaning directly in  
mathematical language the model reads natively.  
  
Those coordinates accumulate in a living graph. They decay when unused.  
They crystallize into permanent landmarks when confirmed repeatedly.  
They expand where precision matters and condense where convergence has  
been reached. The graph breathes.  
  
When a task arrives, the system doesn’t retrieve documents. It assembles  
a context window from the concentrated intelligence already in the graph —  
pre-metabolized, pre-interpreted, directly actionable. The agent reads the  
window and acts. Zero interpretation overhead.  
  
**One document ingested becomes seven generative outputs:**  
a coordinate update, an edge reinforcement, a landmark contribution,  
a causal annotation, a behavioral contract update, a gradient map entry,  
and a concentration field presence. One apple becoming ten seeds.  
Each seed growing into a tree. The trees cross-pollinating.  
  
-----  
  
## The Five Fragmentation Dimensions  
  
A Pacman context window is not a flat string. Every piece of content has  
five simultaneous properties that determine exactly what it is, where it  
came from, how much authority it carries, and how deeply it’s been processed.  
  
### Dimension 1: Zone — Which Membrane  
  
Content enters through typed channels into one of four zones:  
  
```  
SYSTEM     — IRIS internals only. Operating law. Cannot be penetrated.  
TRUSTED    — User's own accumulated knowledge. Profile. Episodic memory.  
TOOL       — Verified external tools with pinned identity.  
REFERENCE  — External content. Peripheral input. Read-only.  
```  
  
This isn’t organization. It’s biology. A cell membrane doesn’t analyze  
what’s trying to cross it — it enforces structural properties. External  
content physically cannot reach the SYSTEM zone regardless of what it says.  
Security and precision are the same mechanism: a source that’s safe to act  
on is also more likely to produce accurate coordinates.  
  
### Dimension 2: Tier — How Deep It’s Metabolized  
  
Within each zone, content is delivered at one of three metabolic depths:  
  
```  
Tier 1 — Always present, constant cost  
         Coordinate identity, operating directives  
         Never grows. Session 1 = Session 500 in token cost.  
  
Tier 2 — Task-selected, bounded  
         Behavioral predictions specific to this task class  
         Selected by what the task actually needs, nothing else.  
  
Tier 3 — Header-first, depth on demand  
         Failure patterns with corrective actions already encoded  
         The filing cabinet label — open the drawer only when needed.  
```  
  
### Dimension 3: Address — Precise Navigation  
  
Every content item has a structured address:  
  
```  
system://header/contracts  
system://header/mycelium  
trusted://profile/conduct  
trusted://episodic/failures  
tool://results/filesystem  
reference://rag/a3f8b2c1  
```  
  
The agent receives a manifest — a 20-token table of contents — at the top  
of every context window. It navigates directly to what it needs.  
It does not scan. Scanning is what traditional RAG makes necessary.  
This eliminates it.  
  
### Dimension 4: Priority — Biological Reasoning Order  
  
Within the SYSTEM zone, content appears in biological priority order:  
  
```  
1. Behavioral contracts     — operating law derived from correction evidence  
2. Gradient warnings        — danger map of coordinate regions to avoid  
3. Causal context           — why similar situations succeeded before  
4. Coordinate identity      — who you are working with  
5. Topological position     — where they currently stand in their development  
6. Ambient field signals    — latent knowledge nearby that traversal didn't reach  
```  
  
This order is not arbitrary. It reflects what reasoning needs first:  
know the rules, know the dangers, know what worked, know who, know where,  
know what’s nearby. The agent processes in the right order automatically  
because the window delivers in the right order.  
  
### Dimension 5: Concentration Field — What Traversal Misses  
  
The coordinate graph is navigated by following scored edges — established  
pathways reinforced by successful task outcomes. But the graph knows more  
than the established paths cover.  
  
High-density coordinate regions — areas with many activated landmarks,  
strong behavioral contracts, recent activity — may not connect to the  
current task’s entry nodes through scored edges yet. New project, new task  
type, first session in an unfamiliar domain. The knowledge is in the graph.  
The path doesn’t reach it.  
  
The concentration sensor reads the field — detects high-density regions  
nearby regardless of whether a path exists to them yet. Ambient signals  
surface this peripheral awareness into the context window at the lowest  
priority position. The agent knows what’s nearby. It can factor it in.  
  
When a task succeeds with an ambient signal present, a weak edge is  
automatically created toward that region. It scores up over time and  
eventually becomes part of the standard traversal path. The graph  
integrates ambient knowledge into established routes through evidence,  
not through curation.  
  
-----  
  
## The Three Metabolic Transformations  
  
The tiers don’t just control depth. They transform content into progressively  
more actionable forms as it moves toward the agent’s reasoning.  
  
### Tier 1: Coordinates Become Directives  
  
Raw coordinate vectors are converted to operating instructions before delivery:  
  
```  
Before: conduct:[0.85, 0.70, 0.80, 0.20, 0.10]  
  
After:  [CONDUCT: autonomous execution authorized |  
         deep session calibrated |  
         confirmation not required unless constraint_flags>0.6]  
```  
  
The agent receives instructions, not numbers. Zero interpretation overhead.  
The raw path is preserved for reference. The directive is what acts.  
  
### Tier 2: Profile Becomes Prediction  
  
General user profile descriptions are converted to task-class-specific  
behavioral predictions before delivery:  
  
```  
Before: "Works with high autonomy in deep sessions. Iterative approach."  
  
After:  [PREDICTED BEHAVIOR for code_task | evidence:14 sessions]  
        - will not interrupt tool calls unless they fail  ✓  
        - will revise iteratively — do not over-specify upfront  ✓  
        - will not confirm individual steps  ✓  
        - checkpoint only if: constraint_flags > 0.6  [conditional]  
```  
  
The agent receives predictions specific to this task, not descriptions  
to generalize from. Evidence-qualified: ✓ means history confirms it.  
  
### Tier 3: Failure Becomes Correction  
  
Failure warning headers include the corrective action that resolved them:  
  
```  
Before: [space:toolpath | outcome:miss | tool:docker | condition:windows]  
  
After:  [space:toolpath | outcome:miss | tool:docker | condition:windows |  
         resolution:env_check_before_mount → hit | sessions_since:3]  
```  
  
The agent receives the warning and the fix together. It doesn’t need to  
retrieve the full episode to know what to do differently.  
  
-----  
  
## The Living Graph  
  
The coordinate graph underneath all of this is not a database.  
It is a living network with biological properties:  
  
**It expands where precision matters.**  
When a node holds contradictory signals — tasks succeed and fail under  
the same coordinate — it splits. The graph grows resolution where the  
biology demands it.  
  
**It condenses where convergence has been reached.**  
When nodes have drifted close enough that they represent the same truth,  
they merge. Redundancy collapses into precision.  
  
**It crystallizes permanent knowledge.**  
Coordinate signals that are confirmed repeatedly across many sessions  
crystallize into landmarks. Landmarks are permanent memory — they survive  
conversation deletion, session clearing, and time. The navigational truth  
persists after the session that produced it is long gone.  
  
**It maintains dormant potential.**  
Nodes adjacent to permanent landmarks decay 3x slower than standard rate.  
When the user temporarily moves to other work and returns, the knowledge  
is still there. The network doesn’t rebuild — it reactivates.  
  
**It heals under threat.**  
When population-level threat signals accumulate — anomalous coordinate  
updates, landmark activation anomalies, channel trust violations —  
the system fires an accelerated reorganization. Three times normal decay  
on recently-modified nodes. Landmark crystallization suspended for the  
session. Full graph restructuring. The map the attacker spent sessions  
mapping is gone. The keys to its doors always change.  
  
-----  
  
## The Compounding Cost Curve  
  
This is what no other system does.  
  
Standard RAG gets more expensive over time. More history means more tokens.  
More documents means more retrieval candidates. The cost curve slopes up.  
  
Pacman inverts this.  
  
```  
Session 1:      ~60 tokens/task   (prose fallback — graph not mature)  
Session 10:     ~38 tokens/task   (coordinate compression active)  
Session 50:     ~22 tokens/task   (task classifier + partial profile)  
Session 100:    ~15 tokens/task   (predictive cache hits climbing)  
Session 200+:   ~12 tokens/task   (all metabolic layers active)  
```  
  
But those 12 tokens at session 200 aren’t less information than 60 tokens  
at session 1. They’re more. They contain behavioral contracts derived from  
22 correction events, causal annotations corroborated across 11 sessions,  
predictive warnings from a gradient map built on 8 miss-scored traversals,  
and behavioral predictions confirmed by 14 historical sessions.  
  
The system doesn’t get cheaper because it’s doing less.  
It gets cheaper because it’s doing more, more efficiently.  
The graph has metabolized the history. What needs to cross the context window  
boundary is just the concentrated form.  
  
-----  
  
## The Agent Loop — Where Metabolism Actually Happens  
  
Everything described so far is the architecture of the digestive system.  
The agent loop is the act of digestion itself.  
  
Without the loop, the graph is a library no one visits.  
The loop is what makes it a metabolism.  
  
### How It Works  
  
Every task that arrives goes through six metabolic stages before and after execution:  
  
**Before the agent acts:**  
  
```  
1. Context assembly  
   get_task_context_package() returns ContextPackage when graph is mature  
   — or prose fallback on fresh install. The loop knows which it has.  
  
2. Task classification  
   TaskClassifier runs before the planning prompt is built.  
   quick_edit / code_task / research_task / planning_task / full  
   The task class determines which spaces are navigated, which profile  
   sections are fetched, which behavioral predictions apply.  
  
3. Planning with pre-metabolized context  
   The planner receives directives, predictions, failure headers with  
   resolutions — not prose to parse. Temperature 0.1 on a mature graph  
   (precise directives → deterministic planning).  
   Temperature 0.25 on an immature graph (flexible interpretation).  
   Topology position calibrates scaffolding depth automatically.  
```  
  
**While the agent acts:**  
  
```  
4. Tool call signal ingestion  
   After every tool call — success or failure — ingest_tool_call() fires.  
   This is the highest-quality behavioral signal in the system.  
   It records what was called, whether it worked, where in the plan sequence.  
   Every execution is a learning event. Every step feeds the toolpath space.  
   All wrapped in try/except. The loop never blocks on memory ingestion.  
```  
  
**After the agent acts:**  
  
```  
5. Outcome recording — in causal order, always  
   record_outcome()         → edge scores update from task result  
   crystallize_landmark()   → session crystallizes into permanent memory  
   clear_session()          → registry wipes, PredictiveLoader pre-warms  
  
6. Strategy signal ingestion  
   The strategy chosen (do_it_myself / spawn_children / delegate_external)  
   is ingested as a soft coordinate signal. Over many sessions, task  
   complexity patterns accumulate in the context space.  
   One line. Low confidence. Compounds quietly over time.  
```  
  
### Why This Closes the Loop  
  
Before the agent loop upgrade, the Pacman architecture had two open ends:  
  
The context window was assembled from a graph that learned from distillation —  
a background process that ran between sessions. Behavioral signals during  
execution (which tools were called, in what order, whether they worked)  
never reached the graph in real time. The graph learned from episodes.  
It didn’t learn from the execution of episodes.  
  
After the loop upgrade, every tool call is a live coordinate update.  
Every reflection failure is a correction event that feeds contract distillation.  
Every completed plan is a landmark candidate. Every strategy choice is a  
soft signal about task complexity.  
  
The metabolism is continuous. Not scheduled. Not batched. Continuous.  
  
### The Complete Metabolic Cycle  
  
```  
Content arrives on hypha channel  
        ↓  
Decomposed into coordinate signals at ingestion boundary  
        ↓  
Signals transport through graph by coordinate affinity  
        ↓  
Task arrives → ContextPackage assembled from concentrated graph  
        ↓  
TaskClassifier routes to relevant spaces  
        ↓  
Planner receives pre-metabolized directives, predictions, correction patterns  
        ↓  
Plan executes → every tool call ingested as live behavioral signal  
        ↓  
Outcome recorded → edges score → landmark crystallizes  
        ↓  
Session clears → PredictiveLoader pre-warms next session  
        ↓  
Distillation pass → gradient map rebuilds → concentration field updates  
                  → causal annotations distill → contracts evolve  
        ↓  
Next task arrives into a richer graph than the last one  
```  
  
This is not a pipeline. It is a cycle. Each revolution of the cycle  
produces a more accurate graph. Each more accurate graph produces better  
context. Better context produces better execution. Better execution  
produces better signals. Better signals produce a more accurate graph.  
  
The metabolism never stops.  
  
-----  
  
## The Proof of Concept  
  
Karpathy’s autoresearch framework: AI agents proposing training changes,  
executing 5-minute GPU training sprints, keeping changes only if validation  
bits-per-byte improves. 100 experiments overnight on a single GPU.  
  
The benchmark: a smaller edge model with a mature Pacman graph navigating  
the experiment space against a larger model exploring cold.  
  
The larger model has more weights. It explores the experiment space by  
capability. It re-discovers failures it has encountered before because it  
has no memory of the coordinate regions it has mapped.  
  
The edge model with Pacman has behavioral contracts that encode which  
experimental directions previously produced damage. It has causal annotations  
that encode why certain approaches succeeded. It has gradient warnings that  
detect dangerous coordinate regions before stepping into them.  
  
It doesn’t explore. It navigates.  
  
The graph knows things about the experiment space that no amount of parameter  
count can substitute for. The accumulated navigational truth of every previous  
session is available in 15 tokens. The larger model doesn’t have it  
at any token cost.  
  
**The claim:** smaller model + mature Pacman graph outperforms larger cold model  
on experiment efficiency (kept/run ratio), learning velocity (sessions to target),  
and sustained performance (slope of improvement over 50+ sessions).  
  
The architecture makes this claim not because of capability but because of memory.  
Capability is what you can do. Memory is what you know not to do, what you know  
works, and what you know about the person you’re working with.  
Pacman is the memory architecture.  
  
-----  
  
## What It Is, Simply  
  
You eat an apple.  
Traditional RAG stores the apple in a filing cabinet.  
You retrieve parts of the apple when you need them.  
The cabinet gets fuller. The search gets slower. The cost goes up.  
  
Pacman metabolizes the apple.  
The apple becomes seeds.  
The seeds grow into trees.  
The trees cross-pollinate.  
By session 200, you have an orchard.  
  
The orchard doesn’t cost more to harvest than the first apple.  
It costs less — because the orchard knows where everything is,  
what grew well, what didn’t, and what to plant next to what.  
  
That’s the architecture.  
That’s Pacman.  
  
-----  
  
## Technical Summary  
  
**Foundation:**  
  
- 7 coordinate spaces encoding user identity, operational style, environment  
- Living coordinate graph with natural expand/condense metabolism  
- Landmark crystallization for permanent navigational memory  
- Resonance-augmented episodic retrieval with topology weighting  
  
**Kyudo Layer (Security + Precision):**  
  
- 5-level hypha channel classification — structural security without content inspection  
- 4-zone cell wall membrane — biological permeability, not filtering  
- Quorum sensing immune response — population-level threat detection  
- 8 compounding precision mechanisms bending cost curve downward  
  
**Biological Fragmentation (Requirements 18–27):**  
  
- Hierarchical Zone Addressing — structured addresses, direct navigation  
- Tiered Context Loading — header-first, depth on demand  
- Causal Landmark Annotations — why it worked, not just that it did  
- Predictive Failure Gradients — danger detection before entry, not after damage  
- Behavioral Contract Layer — receptor rules evolved from correction evidence  
- Concentration Field Sensing — ambient awareness of unreached knowledge  
- Landmark-Protected Dormancy — dormant potential preserved, not pruned  
- Tier 1 Interpretation — coordinates converted to operating directives  
- Tier 2 Prediction — profile converted to task-specific behavioral predictions  
- Tier 3 Resolution Encoding — failures delivered with corrective actions  
  
**Agent Loop (The Digestive Tract):**  
  
- TaskClassifier routes every task to the minimum viable space subset before planning  
- Pre-metabolized ContextPackage delivered to planner — directives, predictions, corrections  
- Topology-aware planning calibrates scaffolding depth to where the user currently stands  
- Live tool call ingestion on every execution step — behavioral signal in real time  
- Causal outcome recording closes the loop: record → crystallize → clear → pre-warm  
- All signals wrapped in try/except — memory system never blocks execution  
  
**At session 200+:**  
  
- 90%+ confidence on familiar territory  
- Honest uncertainty signaling on novel territory  
- Context assembly cost at floor (~12 tokens coordination overhead)  
- Zero interpretation overhead for the agent  
- Continuous metabolic cycle — every task makes the graph richer  
- The agent reads the window and acts  
  
-----  
  
*PACMAN — Context Metabolism Architecture*  
*IRIS / Torus Network · March 2026*  
*Built on mycelium. Named after a ghost-eating circle.*  
*The ghosts are the tokens. The power pellets are the landmarks.*  
*The maze never ends. The map gets better.*  
  
-----  
  
> The coordinate graph is the truth.  
> The manifest is the map.  
> The address is the key.  
> The metabolism never stops.  
