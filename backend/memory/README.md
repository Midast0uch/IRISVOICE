# IRIS Memory Foundation

Three-tier memory architecture for the IRIS AI assistant.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MemoryInterface                          │
│              (Single Access Boundary)                        │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
   ┌────▼────┐  ┌────▼────┐  ┌────▼────┐
   │ Working │  │Episodic │  │Semantic │
   │ Memory  │  │ Memory  │  │ Memory  │
   └────┬────┘  └────┬────┘  └────┬────┘
        │            │            │
   ┌────▼────┐  ┌────▼────┐  ┌────▼────┐
   │ Context │  │ Vector  │  │  User   │
   │  Zones  │  │ Search  │  │  Model  │
   └─────────┘  └─────────┘  └─────────┘
```

## Components

| Component | Purpose | File |
|-----------|---------|------|
| **MemoryInterface** | Single access boundary for all memory operations | `interface.py` |
| **WorkingMemory** | Zone-based in-process context management | `working.py` |
| **EpisodicStore** | Vector-searchable task history with embeddings | `episodic.py` |
| **SemanticStore** | Distilled user model and preferences | `semantic.py` |
| **EmbeddingService** | Singleton for text embeddings (all-MiniLM-L6-v2) | `embedding.py` |
| **DistillationProcess** | Background learning from episodes | `distillation.py` |
| **SkillCrystalliser** | Detects and stores high-value tool sequences | `skills.py` |
| **PrivacyAuditLogger** | Compliance logging for remote context access | `audit.py` |

## Quick Start

```python
from backend.memory import MemoryInterface, load_config

# Initialize
config = load_config()
memory = MemoryInterface(adapter, db_path=config.db_path, biometric_key=key)

# Get context for a task
context = memory.get_task_context("Calculate 15% tip on $85")
# Returns: WorkingContext with semantic_header, episodic_context, working_input

# Record task outcome
memory.store_episode(
    task_summary="Tip calculation",
    tool_sequence=["calculator"],
    outcome=True,
    duration_seconds=3.2,
    user_confirmed=True
)

# Manage preferences
memory.update_preference("likes_bullet_points", True, source="user")
memory.forget_preference("likes_bullet_points")
```

## Privacy Boundary

```python
# Local agent - full context
local_context = memory.get_task_context(task)
# Includes: semantic_header, user preferences, working history

# Remote agent (Torus network) - sanitized
remote_context = memory.get_task_context_for_remote(task)
# Includes: task_summary, tool_sequence only
# Excludes: semantic_header, preferences, personal data
```

## Database Schema

All data encrypted at rest using AES-256 via SQLCipher.

| Table | Purpose |
|-------|---------|
| `episodes` | Task history with embeddings and outcome scores |
| `semantic` | User preferences, cognitive model, domain knowledge |
| `skills` | Crystallized tool sequences |
| `audit_log` | Privacy audit trail (content hashes only) |

## Configuration

```json
{
  "db_path": "data/memory.db",
  "encryption_enabled": true,
  "compression": {
    "threshold": 0.80,
    "keep_ratio": 0.60
  },
  "distillation": {
    "enabled": true,
    "interval_hours": 4,
    "idle_threshold_minutes": 10
  },
  "retention": {
    "enabled": true,
    "episode_retention_days": 90,
    "min_score_to_preserve": 0.8
  }
}
```

## Testing

```bash
# Run all memory tests
pytest backend/memory/tests/ -v

# Run Mycelium layer tests only
pytest backend/memory/tests/test_mycelium*.py -v

# Run with coverage
pytest backend/memory/tests/ --cov=backend.memory
```

## Mycelium Layer

The Mycelium coordinate graph is a 7-space embedding layer that builds a persistent model of the user's working style, domain knowledge, hardware, and active context. It sits beneath `MemoryInterface` and is accessed exclusively through `MyceliumInterface`.

### Coordinate Spaces

| Space | Axes | Purpose |
|-------|------|---------|
| `domain` | domain_id, proficiency, recency | Knowledge domain expertise |
| `style` | formality, verbosity, directness | Communication preferences |
| `conduct` | autonomy, iteration, depth, confirmation, correction | Working behaviour |
| `chrono` | peak_hour, avg_session_len, consistency | Temporal patterns |
| `capability` | gpu_tier, ram, docker, tailscale, os_id | Hardware environment |
| `context` | project_id, stack_id, constraints, freshness | Active projects |
| `toolpath` | tool_id, frequency, success_rate, avg_seq_pos | Tool usage patterns |

### Mycelium Test Coverage

| Area | Confidence | Test File |
|------|-----------|-----------|
| Core math (edge scoring, decay, highway, condense) | ~95% | `test_mycelium_scorer.py` |
| Security gates (HyphaChannel, CellWall, trust cap) | ~90% | `test_mycelium_kyudo_security.py` |
| Schema integrity (13 tables, all columns) | ~95% | `test_mycelium_requirements.py` |
| Coordinate encoding format | ~95% | `test_mycelium_navigator.py` |
| Data navigation (keyword match, fallback, traversal, session, edges) | ~95% | `test_mycelium_navigator.py` |
| Space constants and thresholds | ~95% | `test_mycelium_requirements.py` |
| Orchestration pipeline (maturity, context path, maintenance) | ~95% | `test_mycelium_orchestration.py` |
| Profile prose (6 spaces, constraint levels, render order) | ~95% | `test_mycelium_profile_prose.py` |
| Production environment (schema idempotency, hardware probe) | ~90% | `test_mycelium_production_env.py` |
| MCP trust registry | ~90% | `test_mycelium_requirements.py` |
| Landmark lifecycle (crystallise, merge, absorb) | ~85% | `test_mycelium_landmark.py`, `test_mycelium_profile_prose.py` |

**Total: 253 tests, 0 failures** (1 skipped: SQLCipher not installed in CI)

### Production Notes

- **Database:** SQLCipher-encrypted `data/memory.db` — all mycelium tests use plain sqlite3 in-memory; the SQLCipher path is covered by the cipher guard test which skips if sqlcipher3 is not installed.
- **Single connection:** One shared `sqlcipher3.Connection` per process. Mycelium components never open their own connections. Do not share the connection across OS threads without an external lock.
- **No `print()`:** All logging uses the `logging` module. `print()` is forbidden in all mycelium modules.
- **Kyudo security layer:** `HyphaChannel` is an `IntEnum`. Always pass the enum member (e.g., `HyphaChannel.EXTERNAL`) not the string `"EXTERNAL"` when calling trust/channel APIs.

## Dependencies

- `sqlcipher3>=0.5.0` - Encrypted SQLite
- `sqlite-vec>=0.1.0` - Vector search
- `sentence-transformers>=2.7.0` - Embeddings
- `numpy>=1.21.0` - Vector operations

## Installation

See [MEMORY_SETUP.md](../../docs/MEMORY_SETUP.md) for detailed installation instructions.

## Key Design Decisions

1. **Single Access Boundary**: All memory operations go through `MemoryInterface`
2. **Privacy by Design**: `get_task_context_for_remote()` excludes personal data
3. **Lazy Loading**: Embedding model loads on first use (~80MB)
4. **Torus-Ready**: Episodes have `node_id` and `origin` fields for distributed sync
5. **Encrypted at Rest**: SQLCipher with AES-256 encryption
6. **Versioned Semantic**: Entries have versions for delta sync across nodes
