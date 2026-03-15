# IRIS Mycelium Layer — Architecture Reference

**Version:** 1.0 (implementation complete, testing pending)
**Status:** ⚠️ Implemented — integration tests needed before enabling in production
**Location:** `backend/memory/mycelium/`
**Public API:** `from backend.memory.mycelium import MyceliumInterface`

---

## What Is the Mycelium Layer?

Mycelium is the coordinate-graph memory system for IRIS. It replaces prose-injection context with floating-point coordinate paths through a semantic graph — dramatically reducing token consumption while delivering **higher-precision** memory retrieval.

### The Core Problem It Solves

Before Mycelium, IRIS injected its entire semantic memory profile as prose sentences into every agent context window. This was:
- **Expensive** — every word burns inference tokens
- **Imprecise** — prose re-introduces interpretation overhead the model has already paid for
- **Flat** — no concept of how recently something was true, or how confident the system is

Mycelium represents memory as **coordinates in a multi-dimensional semantic space**. A coordinate vector like `[0.95, 0.72, 0.41]` is already in the model's native mathematical language — no interpretation required. The graph learns which coordinate paths lead to useful context for a given task.

### The Biological Metaphor

Inspired by mycorrhizal networks — the underground fungal communication networks that connect trees in a forest. Each IRIS session is one organism. When a session ends, the chemical pattern (coordinate path) persists. Frequently-used paths strengthen. Unused paths decay. The system becomes more efficient, not less, the more it is used.

---

## Architecture Overview

```
backend/memory/mycelium/
├── __init__.py          # Exports only MyceliumInterface
├── interface.py         # Single public boundary (MyceliumInterface)
├── store.py             # CoordinateStore — SQLCipher persistence
├── encoder.py           # PathEncoder — path → embedding compression
├── extractor.py         # CoordinateExtractor — hardware, text, session, tool signals
├── navigator.py         # CoordinateNavigator + SessionRegistry
├── scorer.py            # EdgeScorer + MapManager — edge weight compounding
├── landmark.py          # Landmark, LandmarkCondenser, LandmarkIndex
├── resonance.py         # EpisodeIndexer + ResonanceScorer
├── profile.py           # LandmarkMerger + ProfileRenderer
├── topology.py          # Graph topology analysis
└── spaces.py            # SPACES + RENDER_ORDER constants
```

External code interacts **only** through `MyceliumInterface`. All other modules are internal implementation details.

---

## Component Reference

### `MyceliumInterface` (`interface.py`)
The orchestration layer. Coordinates all subsystems. One instance per process, sharing the encrypted SQLCipher connection.

**Key methods:**
| Method | Purpose |
|--------|---------|
| `navigate(session_id, task_text, hardware_context)` | Traverse the graph for a task, return a `MemoryPath` |
| `crystallise_landmark(path, outcome)` | Promote a successful path to a persistent landmark |
| `get_profile_for_context(budget_tokens)` | Render a token-budgeted coordinate profile for injection |
| `score_episode_resonance(episode_id, query_embedding)` | Score a stored episode's relevance to a query |
| `maintenance(force)` | Run decay, condense, expand passes (called idle-time) |
| `dev_dump()` | Full graph state dump (dev_mode only) |

**Constants:**
- `GRAPH_MATURITY_THRESHOLD = 3` — spaces needed before mature path generation
- `DISTILLATION_IDLE_THRESHOLD = 600` — seconds idle before maintenance is permitted
- `DISTILLATION_MAX_INTERVAL = 14400` — max seconds between forced maintenance passes

---

### `CoordinateStore` (`store.py`)
Persistent storage of coordinates, edges, and paths in the shared SQLCipher database. All reads/writes go through the same connection as `episodic.py` and `semantic.py` — never opens its own connection.

---

### `CoordinateExtractor` (`extractor.py`)
Extracts coordinates from four signal types:
- **Hardware signals** — device state (CPU, memory, GPU availability)
- **Text signals** — embedding-based position in semantic space
- **Session signals** — conversation turn, elapsed time, tool call history
- **Tool call signals** — MCP tool invocations and their outcomes

---

### `CoordinateNavigator` + `SessionRegistry` (`navigator.py`)
- **Navigator** — traverses the coordinate graph to find the optimal path from session context to target memory nodes
- **SessionRegistry** — tracks active session states and their positions in the graph

---

### `EdgeScorer` + `MapManager` (`scorer.py`)
- **EdgeScorer** — compounds edge weights based on successful task outcomes; paths that repeatedly produce good results grow stronger
- **MapManager** — manages graph topology mutations (add/remove nodes, merge edges, prune dead branches)

---

### `Landmark`, `LandmarkCondenser`, `LandmarkIndex` (`landmark.py`)
Landmarks are crystallised, high-confidence coordinate positions — the "permanent memory" of the system.
- **Landmark** — a stable point in the graph with a confidence score and decay rate
- **LandmarkCondenser** — merges nearby landmarks when they converge on the same semantic region
- **LandmarkIndex** — fast spatial lookup of landmarks given a query coordinate

---

### `EpisodeIndexer` + `ResonanceScorer` (`resonance.py`)
Resonance is the Mycelium mechanism for episode retrieval without full vector search.
- **EpisodeIndexer** — maps episodes to coordinate regions at storage time
- **ResonanceScorer** — scores stored episodes against a query using coordinate proximity rather than raw cosine similarity, making retrieval cost O(region size) rather than O(total episodes)

---

### `LandmarkMerger` + `ProfileRenderer` (`profile.py`)
- **LandmarkMerger** — reconciles conflicting landmark entries during maintenance
- **ProfileRenderer** — converts the coordinate graph into a token-budgeted text profile for context injection; renders only the dimensions relevant to the current task

---

## Kyudo Layer (Precision & Security)

The Kyudo Layer (`kyudo.py`) is the precision and security foundation of Mycelium. Named after the Japanese martial art of precision archery — the goal is not "security" but **precision so complete that security is a natural consequence**.

### HyphaChannel — Typed Transport Channels

All input to Mycelium flows through exactly one of five typed channels. Channel assignment happens **at source**, before content is evaluated, and is permanent for the lifetime of that content item. An adversarial source cannot earn a higher channel by producing content that appears trustworthy.

| Channel | Authority | Sources |
|---------|-----------|---------|
| `SYSTEM` (4) | Highest | IRIS internals, coordinate graph outputs, own specs |
| `USER` (3) | High | User's own documents, notes, direct statements |
| `VERIFIED` (2) | Medium | MCP servers with pinned identity |
| `EXTERNAL` (1) | Low | Web retrieval, unverified documents |
| `UNTRUSTED` (0) | None | Anonymous sources, identity-failed MCPs |

The integer value represents transport authority — higher values reach more memory zones. The **cell wall** (permeability membrane) enforces zone access by channel type, not by content inspection. This is the key insight: the system never reads content to decide if it is safe. It cannot be fooled by well-crafted adversarial content.

### Quorum Sensing (Threat Response)
When a threshold of UNTRUSTED or EXTERNAL signals arrive in a short window, the system enters a coordinated reorganisation — analogous to biological quorum sensing. Affected coordinate regions are quarantined pending review. This is a population-level immune response, not a per-content filter.

### Predictive Pre-Routing
The graph anticipates demand: when a session starts with certain tool calls or topic signals, Mycelium pre-loads the coordinate regions most likely to be needed — before the agent requests them. Cost flows toward growth before the signal arrives, exactly like the mycorrhizal model.

---

## Integration Points

Mycelium integrates with the existing memory layer at three points:

```python
# memory/interface.py — context assembly
from backend.memory.mycelium import MyceliumInterface

mycelium = MyceliumInterface(conn=shared_conn)
path = mycelium.navigate(session_id, task_text, hardware_ctx)
profile = mycelium.get_profile_for_context(budget_tokens=200)
```

```python
# memory/episodic.py — episode storage with resonance indexing
mycelium.score_episode_resonance(episode_id, query_embedding)
```

```python
# memory/distillation.py — maintenance during idle periods
mycelium.maintenance(force=False)
```

---

## Database Schema

Mycelium uses the same encrypted SQLCipher database as the rest of the memory layer (`data/memory.db`). Tables are prefixed `mycelium_*` to avoid collisions:

- `mycelium_coordinates` — node positions in semantic space
- `mycelium_edges` — weighted connections between nodes
- `mycelium_landmarks` — crystallised high-confidence positions
- `mycelium_sessions` — session → coordinate path mappings
- `mycelium_resonance_index` — episode → region mappings for fast retrieval

Schema migration runs automatically on first `MyceliumInterface` instantiation.

---

## Performance Expectations

Once integration-tested and enabled, Mycelium is expected to deliver:

| Metric | Expected Improvement |
|--------|---------------------|
| Context token consumption | −40 to −60% (coordinates vs. prose) |
| Memory retrieval precision | +significant (coordinate proximity vs. keyword) |
| Retrieval cost scaling | O(region) instead of O(total episodes) |
| Session startup latency | Slight increase (pre-routing) offset by faster context assembly |

These projections are based on design analysis. **Actual performance must be validated by the integration test suite** before relying on these numbers.

---

## Testing

Test files are in `backend/memory/tests/`:

| File | Covers |
|------|--------|
| `test_mycelium_store.py` | CoordinateStore CRUD, schema migration |
| `test_mycelium_extractor.py` | Signal extraction from all four input types |
| `test_mycelium_navigator.py` | Graph traversal, path generation |
| `test_mycelium_scorer.py` | Edge weight compounding, map mutations |
| `test_mycelium_landmark.py` | Crystallisation, condense, decay lifecycle |
| `test_mycelium_resonance.py` | Episode indexing, resonance scoring |
| `test_mycelium_topology.py` | Graph topology analysis |
| `test_mycelium_profile.py` | Profile rendering, token budget enforcement |
| `test_mycelium_integration.py` | Full pipeline end-to-end |
| `test_mycelium_kyudo_precision.py` | Channel assignment, zone permeability |
| `test_mycelium_kyudo_security.py` | Adversarial input rejection, quorum sensing |

**Run all Mycelium tests:**
```bash
cd IRISVOICE
python -m pytest backend/memory/tests/ -v -k "mycelium"
```

**Run Kyudo security tests specifically:**
```bash
python -m pytest backend/memory/tests/test_mycelium_kyudo_security.py -v
```

---

## ⚠️ Status: Testing Pending

The Mycelium and Kyudo layers are fully implemented and wired into the memory interface. However, the integration test suite (`test_mycelium_integration.py`) has not been run against a live database in the current environment. Before enabling Mycelium in production:

1. Run the full test suite and confirm all tests pass
2. Run `test_mycelium_integration.py` against a populated `memory.db`
3. Validate context token reduction with real session data
4. Monitor for any latency regression in agent response times

The existing episodic/semantic memory layer remains the fallback and is unaffected if Mycelium raises an exception — all Mycelium calls are wrapped in `try/except` in `memory/interface.py`.
