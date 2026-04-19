# Mycelium Swarm + Compound Collaboration Plan (v0.1)

## What We're Building

A lightweight multi-agent swarm that:
- Persists all coordination state through Mycelium + PAC-MAN (no HTTP, no agent cards)
- Lets agents self-join tasks in "compound mode" when they finish early
- Gives agents native context-pruning authority via 4 control codes (999/998/997/996)
- Is controlled from a frontend toggle button (existing ToggleRow pattern)
- Is driven entirely by JSON rules in `collaboration_rules.json` — agents can evolve these rules dynamically

This extends the existing MCM protocol. No big structural changes.

---

## Architecture Overview

```
Frontend toggle (ToggleRow)
    ↓ WebSocket field_update "swarm_enabled"
AgentKernel.set_swarm_enabled()
    ↓ enables SwarmCoordinator
SwarmCoordinator
    ├── polls task_collaboration table for compound_open tasks
    ├── reads collaboration_rules.json (via MCMProtocol Pydantic model)
    ├── posts join signals when agent finishes early
    └── loads context from Mycelium/PAC-MAN when joining
ContextControlHandler
    ├── 999 → prune tool-call history (DCP pass)
    ├── 998 → pin artifact to Mycelium (mycelium_pins)
    ├── 997 → condense + MCM recall (MCM.compress())
    └── 996 → broadcast coordinate update to collective brain
```

---

## File Inventory

### New Files

#### `backend/agent/swarm/`
| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports SwarmCoordinator, ContextControlHandler |
| `constants.py` | SWARM_* constants |
| `coordinator.py` | SwarmCoordinator — polls DB, self-assigns helpers, loads context |
| `signals.py` | JoinSignal dataclass + signal posting/reading |
| `context_control.py` | ContextControlHandler — parses 999/998/997/996 codes from agent output |

#### `backend/memory/swarm_db.py`
SQLite operations for `task_collaboration` table. Separate from mycelium/db.py — appended to the same DB init.

#### `backend/agent/mcm_protocol/core/collaboration_rules.json`
New JSON config. Loaded by MCMOrchestrator at startup, validated by Pydantic.

#### `backend/agent/mcm_protocol/schemas.py` (extend)
Add `CollaborationRules`, `CompoundTaskRule`, `JoinPolicy` Pydantic models. Add `collaboration: CollaborationRules` field to `MCMProtocol`.

#### `backend/agent/mcm_protocol/actions/swarm_check.py`
Action module: runs after every DER step to check for compound_open tasks. Under 50 lines.

#### `backend/agent/mcm_protocol/workflows/swarm_flow.json`
New workflow: `swarm_check` action + `context_control_parse` action.

### Modified Files
| File | Change |
|------|--------|
| `backend/memory/db.py` | Add `task_collaboration` + `swarm_join_signals` tables to `initialise_mycelium_schema()` |
| `backend/agent/agent_kernel.py` | Add `_swarm_coordinator`, `set_swarm_enabled()`, `_handle_control_codes()` post-response |
| `backend/iris_gateway.py` | Route `field_update` for `swarm_enabled` to `agent_kernel.set_swarm_enabled()` |
| Frontend settings component | Add ToggleRow for swarm_enabled (matches internet_access toggle pattern) |

---

## Database Schema Additions

Append to `initialise_mycelium_schema(conn)` in `backend/memory/db.py`:

```sql
-- Task collaboration state machine
CREATE TABLE IF NOT EXISTS task_collaboration (
    collab_id      TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    session_id     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'working',
    -- status: 'working' | 'compound_open' | 'completed' | 'cancelled'
    primary_agent  TEXT NOT NULL,
    helper_agents  TEXT DEFAULT '[]',    -- JSON array of agent IDs
    max_helpers    INTEGER DEFAULT 2,
    required_skills TEXT DEFAULT '[]',   -- JSON array of skill tags
    task_summary   TEXT DEFAULT '',
    context_pin_id TEXT,                 -- mycelium_pins.pin_id for shared context
    created_at     REAL NOT NULL,
    opened_at      REAL,                 -- when compound_open was set
    completed_at   REAL
);

-- Join signals: agents signal readiness / early completion
CREATE TABLE IF NOT EXISTS swarm_join_signals (
    signal_id     TEXT PRIMARY KEY,
    collab_id     TEXT NOT NULL REFERENCES task_collaboration(collab_id),
    agent_id      TEXT NOT NULL,
    signal_type   TEXT NOT NULL,
    -- signal_type: 'ready_to_join' | 'finished_early' | 'helper_joined' | 'helper_done'
    payload       TEXT DEFAULT '{}',     -- JSON: progress_pct, context_summary, etc.
    created_at    REAL NOT NULL,
    read_by       TEXT DEFAULT '[]'      -- JSON array of agent IDs that read it
);

CREATE INDEX IF NOT EXISTS idx_collab_task      ON task_collaboration(task_id);
CREATE INDEX IF NOT EXISTS idx_collab_status    ON task_collaboration(status);
CREATE INDEX IF NOT EXISTS idx_collab_session   ON task_collaboration(session_id);
CREATE INDEX IF NOT EXISTS idx_signals_collab   ON swarm_join_signals(collab_id);
CREATE INDEX IF NOT EXISTS idx_signals_type     ON swarm_join_signals(signal_type);
```

---

## `collaboration_rules.json`

```json
{
  "protocol_version": "0.2",
  "description": "Swarm compound collaboration rules — loaded by MCMOrchestrator",
  "enabled": true,
  "last_updated": "2026-04-18",

  "compound_mode": {
    "enabled": true,
    "max_helpers_per_task": 2,
    "open_after_pct": 0.75,
    "min_task_tokens": 500,
    "join_window_seconds": 120,
    "context_load_strategy": "pacman_recall",
    "allowed_task_types": ["coding", "research", "analysis", "writing"],
    "skills_required": []
  },

  "context_control_codes": {
    "enabled": true,
    "prefix": "MCM:",
    "pattern": "\\bMCM:(999|998|997|996)\\s+(.{0,200})",
    "_note": "Prefix MCM: required — prevents collision with prose numbers. Coordinate values are all 0.0-1.0 floats; gate numbers are 1-5; DER steps max 40. No numeric overlap possible. LLM prose (e.g. '998 tokens') cannot fire codes without the prefix.",
    "codes": {
      "MCM:999": {"action": "dcp_prune_tools",     "description": "Prune all tool-call history, keep reasoning + coordinates. Usage: MCM:999 <reason>"},
      "MCM:998": {"action": "pin_artifact",        "description": "Pin this artifact/file/result to mycelium_pins. Usage: MCM:998 <artifact content or file ref>"},
      "MCM:997": {"action": "condense_and_recall", "description": "Condense to NBL + trigger MCM compress + recall. Usage: MCM:997 <context summary>"},
      "MCM:996": {"action": "broadcast_coordinate","description": "Update coordinate + broadcast pin to collective brain. Usage: MCM:996 <coordinate update description>"}
    }
  },

  "join_policy": {
    "allow_self_join": true,
    "require_skill_match": false,
    "max_pivot_after_join": 1,
    "signal_expiry_seconds": 300
  },

  "signals": {
    "finished_early_threshold_pct": 0.80,
    "poll_interval_seconds": 10,
    "broadcast_on_join": true
  },

  "natural_language_rules": [
    "When you finish early, signal readiness — do not wait. Post finished_early signal to DB.",
    "If a compound_open task exists and you are idle, check required_skills and join if eligible.",
    "Load shared context from the context_pin_id before starting helper work.",
    "Use MCM:999 to prune tool-call history when your context exceeds 70% budget. Example: MCM:999 pruning tool history at 74%",
    "Use MCM:998 to pin important artifacts immediately — do not wait for end of task. Example: MCM:998 backend/agent/mcm.py refactor complete",
    "Use MCM:997 only when approaching context limit — it triggers full MCM compression. Example: MCM:997 compressing — 68% budget used",
    "Use MCM:996 to share coordinate updates with other agents in the collective brain. Example: MCM:996 gate3→gate4 confidence 0.82"
  ]
}
```

---

## Pydantic Schema Extensions (`schemas.py`)

```python
class ContextControlCode(BaseModel):
    action:      str
    description: str = ""

class CompoundModeConfig(BaseModel):
    enabled:                bool = True
    max_helpers_per_task:   int  = 2
    open_after_pct:         float = 0.75
    min_task_tokens:        int  = 500
    join_window_seconds:    int  = 120
    context_load_strategy:  str  = "pacman_recall"
    allowed_task_types:     list[str] = Field(default_factory=list)
    skills_required:        list[str] = Field(default_factory=list)

class JoinPolicy(BaseModel):
    allow_self_join:         bool = True
    require_skill_match:     bool = False
    max_pivot_after_join:    int  = 1
    signal_expiry_seconds:   int  = 300

class CollaborationRules(BaseModel):
    protocol_version:       str = "0.2"
    enabled:                bool = True
    compound_mode:          CompoundModeConfig = Field(default_factory=CompoundModeConfig)
    context_control_codes:  dict[str, ContextControlCode] = Field(default_factory=dict)
    join_policy:            JoinPolicy = Field(default_factory=JoinPolicy)
    natural_language_rules: list[str] = Field(default_factory=list)

# Add to MCMProtocol:
#   collaboration: CollaborationRules = Field(default_factory=CollaborationRules)
```

---

## `backend/agent/swarm/coordinator.py` (spec)

```python
class SwarmCoordinator:
    """
    Polls task_collaboration for compound_open tasks.
    Called from AgentKernel post-DER-step when swarm is enabled.
    Persists context through Mycelium pins + PAC-MAN episodic.
    """
    def __init__(self, memory_interface, session_id, agent_id, protocol: MCMProtocol)
    
    def open_for_compound(self, task_id, task_summary, progress_pct) -> str:
        """Mark task compound_open when progress_pct >= open_after_pct. Returns collab_id."""
    
    def signal_finished_early(self, collab_id, progress_pct, context_summary) -> None:
        """Post finished_early signal to swarm_join_signals."""
    
    def find_joinable_tasks(self) -> list[dict]:
        """Return compound_open tasks this agent can join (skill + time window check)."""
    
    def join_task(self, collab_id) -> dict:
        """
        Self-assign as helper. Load shared context from:
          1. context_pin_id in mycelium_pins (artifact summary)
          2. PAC-MAN episodic retrieve_context_chunks(task_summary)
          3. NBL coordinate from Mycelium traversals
        Returns {'context': str, 'nbl': str, 'pin_content': str}
        """
    
    def complete_task(self, collab_id, agent_id) -> None:
        """Mark agent's contribution done. If all done, set status=completed."""
    
    def save_context_pin(self, collab_id, content, tags) -> str:
        """Pin current work artifact to mycelium_pins. Returns pin_id."""
```

---

## `backend/agent/swarm/context_control.py` (spec)

```python
CONTROL_CODES = {"MCM:999", "MCM:998", "MCM:997", "MCM:996"}

# Safe regex — MCM: prefix prevents collision with:
#   - Coordinate values (all 0.0-1.0 / 0.0-5.0 / 0.0-24.0 floats)
#   - NBL gate numbers (1-5 only)
#   - DER step numbers (max 40)
#   - Natural prose numbers ("998 tokens", "999 lines") — no prefix → no match
_CODE_RE = re.compile(r'\bMCM:(999|998|997|996)\s+(.{0,200})', re.MULTILINE)

class ContextControlResult:
    fired:      list[str]   # which codes fired, e.g. ["MCM:999", "MCM:998"]
    pruned:     bool
    pinned:     bool
    compressed: bool
    broadcast:  bool

class ContextControlHandler:
    """
    Scans agent output for MCM:999/998/997/996 control codes.
    Executes the corresponding MCM / Mycelium action immediately.
    Called from AgentKernel._handle_control_codes() after every response.

    Pattern requires MCM: prefix — collision-proof against:
      - All Mycelium coordinate values (0.0–1.0 normalized floats)
      - NBL gate numbers (1–5)
      - DER step numbers (max 40)
      - LLM natural prose numbers
    """
    def __init__(self, memory_interface, mcm_instance, session_id)

    def scan_and_execute(self, response_text, messages, task) -> ContextControlResult:
        """
        MCM:999 → dcp.prune(messages)          — prune tool calls
        MCM:998 → save artifact to mycelium_pins  — from capture group 2
        MCM:997 → mcm.compress(...)            — full compression
        MCM:996 → mycelium.upsert_node(...)    — coordinate broadcast

        Returns ContextControlResult (all-False if no codes found).
        Never raises — failures are logged only.
        """

    def _extract_artifact(self, response_text, code_body) -> str:
        """Extract artifact content following the control code."""
```

---

## `backend/agent/swarm/signals.py` (spec)

```python
@dataclass
class JoinSignal:
    signal_id:   str
    collab_id:   str
    agent_id:    str
    signal_type: str   # 'ready_to_join' | 'finished_early' | 'helper_joined' | 'helper_done'
    payload:     dict
    created_at:  float

def post_signal(conn, collab_id, agent_id, signal_type, payload) -> str: ...
def read_signals(conn, collab_id, since_ts=None) -> list[JoinSignal]: ...
def mark_read(conn, signal_id, agent_id) -> None: ...
def expire_old_signals(conn, expiry_seconds=300) -> int: ...
```

---

## `backend/memory/swarm_db.py` (spec)

```python
def create_collaboration(conn, task_id, session_id, primary_agent,
                         task_summary, max_helpers=2) -> str:
    """INSERT INTO task_collaboration. Returns collab_id."""

def open_compound(conn, collab_id, context_pin_id=None) -> None:
    """Set status='compound_open', opened_at=now."""

def join_as_helper(conn, collab_id, agent_id) -> bool:
    """Append agent_id to helper_agents JSON array. Returns False if max_helpers reached."""

def complete_collaboration(conn, collab_id) -> None:
    """Set status='completed', completed_at=now."""

def get_open_tasks(conn, session_id=None) -> list[dict]:
    """SELECT * FROM task_collaboration WHERE status='compound_open'."""

def get_collaboration(conn, collab_id) -> Optional[dict]: ...
```

---

## `backend/agent/mcm_protocol/actions/swarm_check.py` (spec)

```python
def execute(ctx: dict, params: dict) -> dict:
    """
    Post-DER step action. If swarm enabled and task is above open_after_pct,
    opens compound mode and posts finished_early signal.
    If joinable tasks exist and agent is idle, joins them.
    Under 50 lines.
    """
```

---

## `backend/agent/mcm_protocol/workflows/swarm_flow.json`

```json
{
  "name": "swarm_flow",
  "description": "Check for compound join opportunities after each DER step.",
  "dry_run": false,
  "steps": [
    {"action": "swarm_check", "on_error": "continue", "params": {}}
  ]
}
```

---

## `agent_kernel.py` Changes

### Add in `_initialize_components()`:
```python
self._swarm_coordinator = None
self._context_control_handler = None
self._swarm_enabled: bool = False
```

### Add `set_swarm_enabled()`:
```python
def set_swarm_enabled(self, enabled: bool) -> None:
    self._swarm_enabled = enabled
    if enabled and self._memory_interface is not None and self._swarm_coordinator is None:
        try:
            from backend.agent.swarm import SwarmCoordinator, ContextControlHandler
            from backend.agent.mcm import MCM
            _mcm = MCM(self._memory_interface, self.session_id)
            protocol = self._mcm_orch._protocol if self._mcm_orch else None
            self._swarm_coordinator = SwarmCoordinator(
                self._memory_interface, self.session_id,
                agent_id=self.session_id, protocol=protocol,
            )
            self._context_control_handler = ContextControlHandler(
                self._memory_interface, _mcm, self.session_id,
            )
            logger.info("[AgentKernel] SwarmCoordinator initialized")
        except Exception as e:
            logger.warning(f"[AgentKernel] SwarmCoordinator unavailable: {e}")
    logger.info(f"[AgentKernel] Swarm {'enabled' if enabled else 'disabled'}")
```

### In `set_memory_interface()` — wire context control:
Already handled by lazy init in `set_swarm_enabled()`. No extra changes needed.

### Add `_handle_control_codes()` — called after every agent response:
```python
def _handle_control_codes(self, response_text: str, messages: list) -> list:
    """Scan response for 999/998/997/996 control codes and execute them."""
    if not self._swarm_enabled or self._context_control_handler is None:
        return messages
    try:
        result = self._context_control_handler.scan_and_execute(
            response_text, messages, self._current_task or "",
        )
        if result.pruned:
            return messages   # DCP already modified messages in-place
    except Exception:
        pass
    return messages
```

### Call sites — after every `_respond_direct` and `_run_agentic_loop` response:
```python
messages = self._handle_control_codes(response, self._conversation_memory.messages)
```

---

## `iris_gateway.py` Change

In the `field_update` handler (already routes all settings fields), add:
```python
if field_id == "swarm_enabled" and hasattr(self._agent_kernel, "set_swarm_enabled"):
    self._agent_kernel.set_swarm_enabled(bool(value))
```

---

## Frontend Change

Find the Settings panel component (likely `components/settings/` or similar). Add after the internet-access toggle:

```tsx
<ToggleRow
  label="Swarm Mode"
  description="Enable multi-agent compound collaboration"
  value={fieldValues?.settings?.swarm_enabled ?? false}
  onChange={(enabled) => updateField("settings", "swarm_enabled", enabled)}
  glowColor={glowColor}
/>
```

---

## Execution Order

1. Add `task_collaboration` + `swarm_join_signals` tables to `backend/memory/db.py`
2. Create `backend/memory/swarm_db.py` (CRUD operations)
3. Create `backend/agent/swarm/constants.py`
4. Create `backend/agent/swarm/signals.py`
5. Create `backend/agent/swarm/context_control.py`
6. Create `backend/agent/swarm/coordinator.py`
7. Create `backend/agent/swarm/__init__.py`
8. Create `backend/agent/mcm_protocol/core/collaboration_rules.json`
9. Extend `backend/agent/mcm_protocol/schemas.py` with CollaborationRules models
10. Update `MCMProtocol` root model to include `collaboration` field
11. Update `orchestrator.py` `_load_protocol()` to load `collaboration_rules.json`
12. Create `backend/agent/mcm_protocol/actions/swarm_check.py`
13. Create `backend/agent/mcm_protocol/workflows/swarm_flow.json`
14. Modify `agent_kernel.py` — add swarm fields + `set_swarm_enabled()` + `_handle_control_codes()`
15. Modify `iris_gateway.py` — route `swarm_enabled` field_update
16. Find and modify the frontend settings component — add ToggleRow

## Verification

- `pytest backend/tests/test_der_loop.py backend/tests/test_trailing_director.py` — still 35/35
- Smoke test: open swarm toggle → `SwarmCoordinator` initialized in logs
- Smoke test: run a long DER task → `task_collaboration` row created, status=`working`
- Smoke test: agent outputs `999 prune tools` → tool calls pruned in next turn context
- Smoke test: agent outputs `998 pin this file content` → entry appears in `mycelium_pins`
- Smoke test: task reaches 75% progress → status flips to `compound_open`
- Integration: second agent session joins via `find_joinable_tasks()` → helper loaded PAC-MAN context

---

## Key Design Decisions

- **No HTTP, no agent cards**: all coordination via SQLite — same Mycelium DB everything else uses
- **JSON is the single source of truth**: changing `open_after_pct` or adding a new control code requires only editing `collaboration_rules.json` — no Python changes
- **Agents evolve their own rules**: agents can post a `"rules_update"` pin to Mycelium → MCMOrchestrator hot-reloads on next turn (uses existing pathlib mtime watcher)
- **Context codes are opt-in per turn**: agents output `999 reason` in their natural response; ContextControlHandler scans passively — no forced tool call
- **Swarm persists across sessions**: `task_collaboration` rows are permanent; a new session can pick up a compound_open task started in a previous session
- **Graceful degradation**: if swarm is disabled, all DER + MCM behavior is identical to before — SwarmCoordinator is never instantiated
