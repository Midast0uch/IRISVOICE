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

# Run specific test file
pytest backend/memory/tests/test_interface.py -v

# Run with coverage
pytest backend/memory/tests/ --cov=backend.memory
```

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
