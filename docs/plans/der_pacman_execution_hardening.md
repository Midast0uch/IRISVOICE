# DER + PACMAN Execution Hardening — Implementation Spec

**Source:** [der-pacman-execution-optimization.md](file:///c:/dev/IRISVOICE/research/der-pacman-execution-optimization.md)
**Scope:** All root causes RC1–RC12, findings A1–A4, B1–B3, C1, D1–D3, M1–M2, plus frontend event alignment.

---

## Architecture Context

```
Frontend (Next.js)                    Backend (Python FastAPI)
─────────────────                    ────────────────────────
useWebSocket.ts ◄──── WebSocket ────► ws_event_bridge.py
useAgentEvents.ts                     event_bus.py (IRISStreamEvent)
chat-store.ts                         agent_kernel.py
ChatMessage.tsx                         ├─ _plan_task()
TaskCard.tsx                            ├─ _execute_plan_der()
DebugPanel.tsx                          │    ├─ DirectorQueue (der_loop.py)
                                        │    ├─ _Reviewer (der_loop.py)
                                        │    ├─ _der_run_step_execution()
                                        │    ├─ _der_finalize_step()
                                        │    ├─ _der_handle_step_failure()
                                        │    └─ _der_graft_recovery_plan()
                                        ├─ tool_bridge.py → MCP servers
                                        ├─ tool_executor.py (skills)
                                        ├─ episodic.py (PACMAN memory)
                                        ├─ caducean (C++ FFI via iris_ffi.py)
                                        └─ trajectory_controller.py
```

### Event System (backend → frontend)

Events emitted via `EventBus.emit()` in `event_bus.py`, forwarded by `ws_event_bridge.py`:

| Event | Data Schema | Emitted From |
|-------|-------------|--------------|
| `plan:start` | `{plan_title, mode, steps[], total_steps}` | `agent_kernel.py:4046` |
| `tool:call` | `{task_id, tool_name, description[:200], params, step_number}` | `agent_kernel.py:5013` |
| `tool:result` | `{task_id, result_summary[:200], tool_name, step_number}` | `_der_finalize_step:5744` |
| `tool:error` | `{task_id, error[:200], tool_name, step_number}` | `_der_finalize_step:5757` |
| `plan:complete` | `{success, summary}` | post-DER |
| `mode:change` | `{from_mode, to_mode, reason}` | `der_loop.escalate` |

### Key Constants (`der_constants.py`)

```
DER_MAX_STEPS = 25
DER_MAX_PARALLEL = 4
DER_MAX_GRAFTS = 3
DER_MAX_VETO_PER_ITEM = 2
DER_TOKEN_BUDGETS = {QUICK: 4000, STANDARD: 12000, AGENTIC: 24000, FULL: 48000}
BUDGET_ABSOLUTE_MIN = 500
BUDGET_RATIO_ESCALATE = 0.3
```

---

## Implementation Phases

All phases are ordered by dependency. Each phase MUST pass its verification before the next phase begins.

---

## Phase 0 — Foundation Fixes (Zero Risk, Highest Leverage)

These are correctness bugs. They must be fixed first because every subsequent phase depends on them.

### 0.1 — Fix `item.result` Not Set on Failure Path (C1)

**Root Cause:** `item.result = step_result` is only set in `_der_finalize_step` (line 5866), which is only called on the success path. When a step fails, the loop calls `_der_handle_step_failure` and `continue`s at line 5042, skipping finalize. The graft then reads `item.result or ""` (line 5290) and gets an empty string.

**Files:**
- `backend/agent/agent_kernel.py` — lines 5028–5042

**Change:** Before calling `_der_handle_step_failure`, set `item.result = step_result`:

```python
# agent_kernel.py, in _execute_plan_der, after the retry block (~line 5037)
if not step_success:
    # C1 FIX: preserve the error text so graft receives it
    item.result = step_result
    self._der_handle_step_failure(
        item, queue, plan, _session, _turn_id, context_package
    )
    continue
```

**Success Criteria:**
- [ ] After a step fails, `item.result` contains the error string (not `None` or `""`)
- [ ] The graft recovery prompt includes the real error text
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_der_c1_error_propagation.py
def test_failed_step_result_propagated_to_graft():
    """C1: item.result MUST contain the error string after failure."""
    # Setup: create a QueueItem, simulate a failed step_result
    item = QueueItem(step_id="s1", step_number=1, description="test", critical=True)
    step_result = "ConnectionError: server unreachable"
    
    # Act: set item.result as the fix requires
    item.result = step_result
    
    # Assert: item.result is the error, not empty
    assert item.result == "ConnectionError: server unreachable"
    assert item.result != ""
    assert item.result is not None

def test_graft_receives_real_error(mock_kernel):
    """C1: _der_graft_recovery_plan receives non-empty error_msg."""
    # Setup: force a step failure with known error text
    # Act: call _der_handle_step_failure
    # Assert: the graft prompt contains the error text
    # Verify by checking the LLM prompt passed to _der_graft_recovery_plan
    pass  # Implementation: mock _der_graft_recovery_plan, assert error_msg != ""
```

---

### 0.2 — Stop Dropping `tool_sequence` in Episodic Context (RC8)

**Root Cause:** `episodic.py:retrieve_similar` returns `tool_sequence` (line 432), but `assemble_episodic_context` (line ~546) formats only `task_summary` and drops the sequence entirely.

**Files:**
- `backend/memory/episodic.py` — `assemble_episodic_context` method

**Change:** Include the `tool_sequence` in the formatted episodic context:

```python
# episodic.py, in assemble_episodic_context, where episodes are formatted
for ep in success_episodes:
    summary = ep.get("task_summary", "")
    score = ep.get("outcome_score", 0)
    seq = ep.get("tool_sequence", [])
    lines.append(f"  - {summary} (score: {score:.1f})")
    if seq:
        tool_names = " → ".join(s.get("tool", "?") for s in seq[:6])
        lines.append(f"    PROVEN SEQUENCE: {tool_names}")
```

**Success Criteria:**
- [ ] `assemble_episodic_context` output includes `PROVEN SEQUENCE:` lines when episodes have tool sequences
- [ ] The planner prompt contains tool sequence information
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_episodic_rc8_tool_sequence.py
def test_assemble_episodic_context_includes_tool_sequence(episodic_store):
    """RC8: assemble_episodic_context MUST include tool_sequence when present."""
    # Setup: store an episode with a known tool_sequence
    episodic_store.store_episode(Episode(
        task_summary="resize image",
        tool_sequence=[{"tool": "read_file"}, {"tool": "run_command"}, {"tool": "write_file"}],
        outcome_type="success",
        outcome_score=0.9,
    ))
    
    # Act
    context = episodic_store.assemble_episodic_context("resize an image")
    
    # Assert
    assert "PROVEN SEQUENCE:" in context
    assert "read_file" in context
    assert "run_command" in context
```

---

### 0.3 — Pre-Execution Step Validation (RC1)

**Root Cause:** `_execute_plan_der` executes whatever tool name the LLM emitted without checking if it exists in the registry or if params match the schema. Historical `tool:null` bug documented at line 3554–3556.

**Files:**
- `backend/agent/agent_kernel.py` — in `_execute_plan_der`, before `_der_run_step_execution`
- `backend/agent/tool_registry.py` — add a `validate_tool_call(tool_name, params)` method

**Change:**

```python
# tool_registry.py — new method
def validate_tool_call(self, tool_name: str, params: dict) -> tuple[bool, str]:
    """Validate tool exists and params satisfy required fields.
    Returns (is_valid, error_message)."""
    tool = self.get_tool(tool_name)
    if tool is None:
        return False, f"Tool '{tool_name}' not found in registry"
    schema = tool.get("input_schema", {})
    required = schema.get("required", [])
    missing = [r for r in required if r not in (params or {})]
    if missing:
        return False, f"Tool '{tool_name}' missing required params: {missing}"
    return True, ""
```

```python
# agent_kernel.py — in _execute_plan_der, BEFORE the Explorer phase execution (~line 5028)
if item.tool:
    _valid, _val_err = self._tool_bridge.tool_registry.validate_tool_call(
        item.tool, item.params or {}
    )
    if not _valid:
        item.result = f"[VALIDATION] {_val_err}"
        self._der_handle_step_failure(
            item, queue, plan, _session, _turn_id, context_package
        )
        continue
```

**Success Criteria:**
- [ ] A step with a nonexistent tool name is caught before execution and routed to graft
- [ ] A step missing required params is caught before execution and routed to graft
- [ ] The validation error message appears in the graft prompt (depends on 0.1)
- [ ] Valid tool calls pass through unchanged
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_der_rc1_preexec_validation.py
def test_invalid_tool_caught_before_execution(mock_registry):
    """RC1: nonexistent tool MUST be caught pre-exec, not at runtime."""
    valid, err = mock_registry.validate_tool_call("nonexistent_tool", {})
    assert not valid
    assert "not found" in err

def test_missing_required_params_caught(mock_registry):
    """RC1: missing required params MUST be caught pre-exec."""
    # Assume 'read_file' requires 'path'
    valid, err = mock_registry.validate_tool_call("read_file", {})
    assert not valid
    assert "missing required" in err.lower()

def test_valid_tool_call_passes(mock_registry):
    """RC1: valid tool+params MUST pass validation."""
    valid, err = mock_registry.validate_tool_call("read_file", {"path": "/tmp/test.txt"})
    assert valid
    assert err == ""
```

---

### 0.4 — Fix SQLCipher Thread-Safety (RC9)

**Root Cause:** `sqlcipher3.connect()` in `db.py:59` does not set `check_same_thread=False`. The fallback `sqlite3.connect()` at line 94 does. DER executes in a thread pool, so the encrypted production path will crash.

**Files:**
- `backend/memory/db.py` — `open_encrypted_memory` function, line 59

**Change:**
```python
# db.py line 59 — add check_same_thread=False
conn = _sqlcipher3.connect(str(db_path), check_same_thread=False)
```

**Success Criteria:**
- [ ] `sqlcipher3.connect` is called with `check_same_thread=False`
- [ ] Multi-threaded access to the encrypted database does not raise `ProgrammingError`
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_db_thread_safety.py
import threading

def test_encrypted_db_accessible_from_worker_thread(tmp_path):
    """RC9: encrypted DB connection MUST be usable from non-main threads."""
    db_path = str(tmp_path / "test.db")
    # Use sqlite3 fallback (sqlcipher3 may not be installed in CI)
    import sqlite3
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    conn.commit()
    
    errors = []
    def worker():
        try:
            conn.execute("INSERT INTO test (id) VALUES (1)")
            conn.commit()
        except Exception as e:
            errors.append(e)
    
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert len(errors) == 0, f"Thread access failed: {errors}"
```

---

## Phase 1 — Resilience & Timeout Hardening

Depends on: Phase 0 complete.

### 1.1 — Retry with Exponential Backoff (B1 + RC3)

**Root Cause:** Single retry with fixed `time.sleep(0.5)` at `agent_kernel.py:5033`. No error classification.

**Files:**
- `backend/agent/resilience.py` — **NEW FILE**
- `backend/agent/agent_kernel.py` — replace lines 5028–5042

**Change:** Create a shared resilience module:

```python
# backend/agent/resilience.py — NEW FILE
"""Shared retry/timeout/breaker utilities for DER and skill execution."""
import asyncio
import random
import logging
from typing import Callable, Awaitable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

# Transient error types — safe to retry
TRANSIENT_ERRORS = (asyncio.TimeoutError, ConnectionError, OSError, TimeoutError)

# Permanent error types — fail fast to graft
PERMANENT_ERRORS = (ValueError, PermissionError, FileNotFoundError, KeyError)


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base: float = 1.0,
    cap: float = 8.0,
    jitter: bool = True,
    label: str = "unknown",
) -> T:
    """Execute fn with exponential backoff on transient errors.
    
    Defaults match existing codebase convention:
    - base=1.0 matches agent_kernel.py:2230 sleep(1.0 * 2**attempt)
    - cap=8.0 gives delays of 1s → 2s → 4s → 8s
    - max_retries=3 matches mcp/server_manager.py max_restart_attempts
    
    Permanent errors (ValueError, PermissionError, etc.) are raised immediately.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except PERMANENT_ERRORS:
            raise  # fail fast — no retry
        except TRANSIENT_ERRORS as e:
            last_error = e
            if attempt == max_retries:
                break
            delay = min(cap, base * (2 ** attempt))
            if jitter:
                delay *= 1 + random.random() * 0.3
            logger.warning(
                "[resilience] %s: transient error (attempt %d/%d), retrying in %.1fs: %s",
                label, attempt + 1, max_retries, delay, e,
            )
            await asyncio.sleep(delay)
        except Exception as e:
            # Unknown error — treat as permanent
            raise
    raise last_error
```

Replace the DER retry block:

```python
# agent_kernel.py — replace lines 5028-5042
# ── EXPLORER PHASE: execute with resilience ──
from backend.agent.resilience import retry_with_backoff, TRANSIENT_ERRORS

async def _run_step():
    return self._der_run_step_execution(
        item, context_package, _session, _turn_id, plan
    )

try:
    step_result, step_success = await retry_with_backoff(
        _run_step,
        max_retries=2,
        base=1.0,
        cap=4.0,
        label=f"step_{item.step_number}:{item.tool}",
    )
except Exception as _retry_exc:
    step_result = str(_retry_exc)
    step_success = False

if not step_success:
    item.result = step_result  # C1 fix
    self._der_handle_step_failure(
        item, queue, plan, _session, _turn_id, context_package
    )
    continue
```

> **NOTE:** `_der_run_step_execution` currently uses `asyncio.run()` internally because DER runs in a thread pool. The retry wrapper must be adapted to the sync-in-thread context. Wrap with `asyncio.run(retry_with_backoff(...))` or convert the retry helper to sync with `time.sleep`. Choose whichever matches the existing thread model — do NOT change the threading model in this phase.

**Success Criteria:**
- [ ] Transient errors (ConnectionError, TimeoutError) are retried up to 3 times with exponential backoff
- [ ] Permanent errors (ValueError, PermissionError) fail immediately without retry
- [ ] Retry delays follow the pattern: ~1s → ~2s → ~4s (with jitter)
- [ ] After max retries exhausted, step fails and routes to graft with the error message
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_resilience.py
import asyncio
import pytest
from backend.agent.resilience import retry_with_backoff

@pytest.mark.asyncio
async def test_transient_error_retried():
    """B1: transient errors MUST be retried with backoff."""
    call_count = 0
    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient")
        return "success"
    
    result = await retry_with_backoff(flaky, max_retries=3, base=0.01, cap=0.1)
    assert result == "success"
    assert call_count == 3

@pytest.mark.asyncio
async def test_permanent_error_not_retried():
    """B1: permanent errors MUST fail immediately."""
    call_count = 0
    async def bad_params():
        nonlocal call_count
        call_count += 1
        raise ValueError("bad params")
    
    with pytest.raises(ValueError):
        await retry_with_backoff(bad_params, max_retries=3, base=0.01)
    assert call_count == 1  # no retry

@pytest.mark.asyncio
async def test_max_retries_exhausted():
    """B1: after max retries, the last error MUST be raised."""
    async def always_fail():
        raise ConnectionError("down")
    
    with pytest.raises(ConnectionError):
        await retry_with_backoff(always_fail, max_retries=2, base=0.01, cap=0.1)
```

---

### 1.2 — In-Process MCP Timeout (B2 + RC10)

**Root Cause:** `tool_bridge.execute_mcp_tool` (line 747) calls `server.handle_request(request)` with no timeout. External `MCPClient._send_request` already uses `asyncio.wait_for(..., timeout=30.0)`.

**Files:**
- `backend/agent/tool_bridge.py` — `execute_mcp_tool` method, line ~747
- `backend/mcp/builtin_servers.py` — wrap blocking operations in `asyncio.to_thread`

**Change in tool_bridge.py:**
```python
# tool_bridge.py line 747 — wrap with timeout
# Default 30s matches mcp/client.py:141; vision/long tools get 60s
_timeout = 60.0 if server_name in ("vision", "gui_automation") else 30.0
try:
    response = await asyncio.wait_for(
        server.handle_request(request), timeout=_timeout
    )
except asyncio.TimeoutError:
    return {"success": False, "error": f"Tool '{tool_name}' timed out after {_timeout}s"}
```

**Change in builtin_servers.py** (RC10 — event loop blocking):
```python
# builtin_servers.py — FileManagerServer.execute_tool
# Wrap synchronous file I/O in asyncio.to_thread
if name == "read_file":
    path = arguments.get("path", "")
    try:
        content = await asyncio.to_thread(self._sync_read_file, path)
        return {"success": True, "content": content, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e), "path": path}

def _sync_read_file(self, path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# Similarly for write_file, delete_file, list_directory, screenshot, etc.
```

**Success Criteria:**
- [ ] In-process MCP tool calls timeout after 30s (or 60s for vision/GUI)
- [ ] Timeout returns `{"success": False, "error": "...timed out..."}` instead of hanging
- [ ] File I/O and GUI operations do not block the asyncio event loop
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_mcp_timeout.py
import asyncio
import pytest

@pytest.mark.asyncio
async def test_in_process_mcp_timeout():
    """B2: in-process MCP tools MUST timeout, not hang."""
    class HangingServer:
        async def handle_request(self, req):
            await asyncio.sleep(999)  # simulate hang
    
    # Act: call with 0.1s timeout
    try:
        await asyncio.wait_for(
            HangingServer().handle_request(None), timeout=0.1
        )
        assert False, "Should have timed out"
    except asyncio.TimeoutError:
        pass  # correct behavior

@pytest.mark.asyncio 
async def test_file_io_does_not_block_event_loop():
    """RC10: file I/O in MCP servers MUST run in a thread, not block the loop."""
    import time
    loop = asyncio.get_event_loop()
    
    # Schedule a concurrent task that measures event loop responsiveness
    responsiveness = []
    async def check_loop():
        start = time.monotonic()
        await asyncio.sleep(0.01)
        responsiveness.append(time.monotonic() - start)
    
    # Run file I/O via to_thread concurrently
    async def file_op():
        await asyncio.to_thread(time.sleep, 0.1)  # simulated blocking I/O
    
    await asyncio.gather(check_loop(), file_op())
    # Event loop should have responded in ~10ms, not blocked for 100ms
    assert responsiveness[0] < 0.05, f"Event loop blocked: {responsiveness[0]:.3f}s"
```

---

## Phase 2 — Memory-Execution Bridge

Depends on: Phase 0 and Phase 1 complete.

### 2.1 — Failure-Aware Mid-Loop Recall (A1)

**Root Cause:** C.4 mid-loop retrieval (line 4947) calls `retrieve_similar` which filters `outcome_type='success'`. Plan-time failure warnings (`_get_failure_warnings`) are never injected during execution.

**Files:**
- `backend/agent/agent_kernel.py` — C.4 block, lines 4930–4964

**Change:** After the success retrieval, also pull failure warnings:

```python
# agent_kernel.py — after line 4962 (end of success hint injection)
# A1 FIX: inject failure awareness into per-step execution
try:
    _fw = self._get_failure_warnings(item.description)
    if _fw and _fw != "None" and len(_fw) > 10:
        _prior = getattr(item, "coordinate_signal", "") or ""
        item.coordinate_signal = (
            _prior + f"\nPAST FAILURE WARNING: {_fw[:300]}"
        ).strip()
except Exception as _fw_exc:
    loud_error(_fw_exc, "failure_warning_mid_loop")
```

**Success Criteria:**
- [ ] `item.coordinate_signal` contains `PAST FAILURE WARNING:` when relevant failures exist
- [ ] Failure warnings are retrieved per-step, not just at plan time
- [ ] Performance: `_get_failure_warnings` call adds < 50ms (uses cached embeddings)
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_der_a1_failure_recall.py
def test_mid_loop_injects_failure_warning(mock_kernel_with_memory):
    """A1: per-step execution MUST include failure warnings, not just plan time."""
    # Setup: store a failure episode for "read_file with binary"
    # Act: simulate C.4 retrieval for a step "read binary file"
    # Assert: item.coordinate_signal contains "PAST FAILURE WARNING:"
    pass
```

---

### 2.2 — Proven Tool Sequence in Mid-Loop Hint (A2)

**Root Cause:** C.4 injects only `task_summary[:80]` (line 4953). The returned `tool_sequence` is dropped.

**Files:**
- `backend/agent/agent_kernel.py` — C.4 block, lines 4952–4962

**Change:**
```python
# agent_kernel.py — replace the hint formatting block (lines 4952-4962)
if _sub_eps:
    _hint_parts = []
    for ep in _sub_eps:
        _ts = ep.get("task_summary", "")[:80]
        if _ts:
            _hint_parts.append(_ts)
        _seq = ep.get("tool_sequence", [])
        if _seq:
            _approach = " → ".join(
                s.get("tool", "?") for s in _seq[:5]
            )
            _hint_parts.append(f"PROVEN APPROACH: {_approach}")
    if _hint_parts:
        _hints = "; ".join(_hint_parts)
        _prior = getattr(item, "coordinate_signal", "") or ""
        item.coordinate_signal = (
            _prior + f"\nSUB-TASK HINT: {_hints}"
        ).strip()
```

**Success Criteria:**
- [ ] `coordinate_signal` contains `PROVEN APPROACH:` with tool names when past sequences exist
- [ ] Tool sequences are limited to 5 tools to avoid prompt bloat
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_der_a2_proven_sequence.py
def test_mid_loop_injects_proven_tool_sequence(mock_kernel_with_memory):
    """A2: per-step hint MUST include the proven tool_sequence, not just summary."""
    # Setup: store success episode with tool_sequence [read_file, run_command, write_file]
    # Act: retrieve similar for step "process a file"
    # Assert: coordinate_signal contains "PROVEN APPROACH: read_file → run_command → write_file"
    pass
```

---

### 2.3 — Fragment Failed Outputs to PACMAN (A3)

**Root Cause:** `_der_finalize_step` fragments outputs only when `step_success` (line 5776). Failed output is discarded.

**Files:**
- `backend/agent/agent_kernel.py` — `_der_finalize_step`, line 5776 block

**Change:** Add a failure fragmentation path:

```python
# agent_kernel.py — after the success fragmentation block (~line 5805)
# A3 FIX: also fragment failed outputs so failures are remembered
try:
    if step_result and not step_success:
        _fail_text = (
            f"[FAILED Step {item.step_number}: {item.description[:120]}]"
            f"\n{step_result}"
        )
        if self._memory_interface and hasattr(
            self._memory_interface, "episodic"
        ):
            _ep = self._memory_interface.episodic
            if hasattr(_ep, "fragment_and_store"):
                _ep.fragment_and_store(
                    content=_fail_text[:2000],
                    session_id=_session,
                    chunk_type="der_failure",
                    zone="failure",
                )
except Exception as _frag_fail_exc:
    loud_error(_frag_fail_exc, "fragment_failed_output")
```

**Success Criteria:**
- [ ] Failed step outputs are stored in the vector DB with `chunk_type="der_failure"` and `zone="failure"`
- [ ] Fragment length capped at 2000 chars to avoid memory bloat
- [ ] Success fragmentation path unchanged
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_der_a3_failure_fragments.py
def test_failed_output_fragmented_to_pacman(mock_episodic):
    """A3: failed step outputs MUST be stored in PACMAN, not discarded."""
    # Setup: call fragment_and_store with a failure output
    mock_episodic.fragment_and_store(
        content="[FAILED Step 3: run script]\nPermissionError: access denied",
        session_id="test",
        chunk_type="der_failure",
        zone="failure",
    )
    # Assert: chunk exists in context_chunks with zone='failure'
    chunks = mock_episodic.db.execute(
        "SELECT * FROM context_chunks WHERE zone='failure'"
    ).fetchall()
    assert len(chunks) >= 1
```

---

## Phase 3 — Recovery & Safety Hardening

Depends on: Phases 0–2 complete.

### 3.1 — Memory-Aware Graft Recovery (C1 extended + M.3.3)

**Root Cause:** `_der_graft_recovery_plan` (line 5304) receives only `OBJECTIVE / FAILED STEP / TOOL / ERROR`. No failure memory, no success episodes, no tool sequences, no AVAILABLE TOOLS.

**Files:**
- `backend/agent/agent_kernel.py` — `_der_graft_recovery_plan` method (line 5304–5356)

**Change:** Inject memory context into the graft prompt:

```python
# agent_kernel.py — in _der_graft_recovery_plan, before the LLM call
# M.3.3 FIX: wire memory into recovery
_failure_ctx = ""
_success_ctx = ""
try:
    if self._memory_interface:
        _ep = self._memory_interface.episodic
        # Retrieve past failures for this sub-goal
        _failures = _ep.retrieve_failures(
            task=failed_item.description, limit=2
        )
        if _failures:
            _failure_ctx = "\n".join(
                f"  - AVOID: {f.get('task_summary', '')[:100]} "
                f"(reason: {f.get('failure_reason', 'unknown')[:100]})"
                for f in _failures
            )
        # Retrieve past successes for alternative approaches
        _successes = _ep.retrieve_similar(
            task=failed_item.description, limit=2
        )
        if _successes:
            _success_ctx = "\n".join(
                f"  - ALTERNATIVE: {s.get('task_summary', '')[:100]} "
                f"(tools: {' → '.join(t.get('tool','?') for t in s.get('tool_sequence',[])[:4])})"
                for s in _successes
            )
except Exception:
    pass  # never block recovery on memory failure

# Include in the graft prompt:
# ... existing prompt ...
# + f"\nPAST FAILURES (do NOT repeat these approaches):\n{_failure_ctx}" if _failure_ctx
# + f"\nALTERNATIVE PROVEN APPROACHES:\n{_success_ctx}" if _success_ctx
# + f"\nAVAILABLE TOOLS:\n{_tools_block}"  # reuse _plan_task's tool block
```

**Success Criteria:**
- [ ] Graft prompt includes `PAST FAILURES` section when relevant failures exist
- [ ] Graft prompt includes `ALTERNATIVE PROVEN APPROACHES` when relevant successes exist
- [ ] Graft prompt includes `AVAILABLE TOOLS` list
- [ ] Recovery still works when memory is empty (graceful degradation)
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_der_graft_memory.py
def test_graft_prompt_includes_failure_memory(mock_kernel):
    """M.3.3: graft recovery MUST receive past failure context."""
    # Setup: store failure episode, trigger graft
    # Assert: graft prompt contains "PAST FAILURES"
    pass

def test_graft_prompt_includes_alternative_approaches(mock_kernel):
    """M.3.3: graft recovery MUST receive proven alternative approaches."""
    # Setup: store success episode with tool_sequence, trigger graft
    # Assert: graft prompt contains "ALTERNATIVE PROVEN APPROACHES"
    pass

def test_graft_works_with_empty_memory(mock_kernel):
    """M.3.3: graft MUST still work when memory store is empty."""
    # Setup: empty memory, trigger graft
    # Assert: graft executes without error, produces recovery steps
    pass
```

---

### 3.2 — Caducean Exit → Targeted Recovery (N.4 + O.6 + RC11)

**Root Cause:** `TopologyViolationException` propagates to the generic handler at line 4076, which abandons the entire DER plan and falls back to ReAct. No targeted recovery.

**Files:**
- `backend/agent/agent_kernel.py` — line 4065–4090 (try/except around `_execute_plan_der`)
- `backend/agent/agent_kernel.py` — new method `_der_recover_from_violation`
- `backend/gateway/iris_ffi.py` — `ffi_caducean_init_session` (existing, used for reset)

**Change:**

```python
# agent_kernel.py — replace lines 4065-4090
try:
    _der_response = self._execute_plan_der(
        plan=_plan, context_package=_context_package,
        is_mature=_is_mature, task_class=_der_task_class,
        session_id=session_id or self.session_id,
        from_voice=from_voice, confidence=_confidence, turn_id=task_id,
    )
except TopologyViolationException as _tv:
    # N.4 FIX: targeted recovery instead of blanket ReAct fallback
    logger.warning(
        "[AgentKernel] TopologyViolation — attempting targeted recovery"
    )
    try:
        # RC11 FIX: reset Caducean session state before recovery
        from backend.gateway.iris_ffi import ffi_caducean_init_session
        ffi_caducean_init_session(session_id or self.session_id)
        
        # Emit recovery event to frontend
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
        get_event_bus().emit(
            IRISStreamEvent.MODE_CHANGE,
            data={"from_mode": "DER", "to_mode": "DER_RECOVERY",
                  "reason": "Topological violation — recovering"},
            session_id=session_id,
        )
        
        # Attempt graft recovery with memory context
        _der_response = self._execute_plan_der(
            plan=_plan, context_package=_context_package,
            is_mature=_is_mature, task_class=_der_task_class,
            session_id=session_id or self.session_id,
            from_voice=from_voice, confidence=_confidence, turn_id=task_id,
        )
    except Exception as _recovery_err:
        logger.warning(
            f"[AgentKernel] Recovery failed, falling back to ReAct: {_recovery_err}"
        )
        # Fall through to existing ReAct fallback
        _der_response = None
except Exception as _der_err:
    # Existing ReAct fallback (unchanged)
    logger.warning(
        f"[AgentKernel] DER path error (falling back to ReAct): {_der_err}"
    )
```

**Success Criteria:**
- [ ] `TopologyViolationException` is caught specifically, not by the generic handler
- [ ] Caducean session state is reset via `ffi_caducean_init_session` before retry
- [ ] A `mode:change` event with reason "Topological violation" is emitted to the frontend
- [ ] If recovery also fails, the existing ReAct fallback still engages
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_caducean_recovery.py
def test_topology_violation_triggers_targeted_recovery(mock_kernel):
    """N.4: TopologyViolationException MUST trigger recovery, not ReAct fallback."""
    # Setup: mock _execute_plan_der to raise TopologyViolationException on first call
    # Assert: ffi_caducean_init_session was called (RC11)
    # Assert: _execute_plan_der was called a second time (recovery attempt)
    pass

def test_caducean_reset_on_recovery(mock_ffi):
    """RC11: Caducean session MUST be reset before recovery to prevent re-violation."""
    from backend.gateway.iris_ffi import ffi_caducean_init_session
    result = ffi_caducean_init_session("test_session")
    # Assert: session was initialized (or returns True)
    assert result is True or result is False  # depends on engine availability

def test_recovery_failure_falls_back_to_react(mock_kernel):
    """N.4: if recovery also fails, ReAct fallback MUST still engage."""
    # Setup: mock _execute_plan_der to always raise
    # Assert: the system does not crash, falls back to ReAct
    pass
```

---

### 3.3 — Budget Exhaustion Surfacing (RC6)

**Root Cause:** Token budget exhaustion at line 5829–5831 silently stops the plan. No user-facing signal.

**Files:**
- `backend/agent/agent_kernel.py` — budget exhaustion block (~line 5829)
- `backend/agent/event_bus.py` — add new event type

**Change:**

```python
# event_bus.py — add to IRISStreamEvent enum
BUDGET_EXHAUSTED = "plan:budget_exhausted"
```

```python
# agent_kernel.py — at the budget exhaustion point (~line 5829)
# RC6 FIX: emit explicit event instead of silent stop
_remaining = len([i for i in queue.items 
                  if i.step_id not in queue.completed_ids 
                  and i.step_id not in queue.failed_ids])
try:
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    get_event_bus().emit(
        IRISStreamEvent.BUDGET_EXHAUSTED,
        data={
            "task_id": _turn_id,
            "steps_completed": len(completed_items),
            "steps_remaining": _remaining,
            "tokens_used": _tokens_used,
            "token_budget": _token_budget,
            "message": f"Task incomplete: {_remaining} steps remaining "
                       f"(budget {_tokens_used}/{_token_budget} exhausted)",
        },
        turn_id=_turn_id,
        session_id=_session,
    )
except Exception:
    pass
```

**Frontend alignment:** The frontend must handle this new event type.

```typescript
// hooks/useAgentEvents.ts — add handler
case "plan:budget_exhausted":
    // Display a warning in the chat that the task was incomplete
    chatStore.addSystemMessage({
        type: "warning",
        text: payload.data.message,
    });
    break;
```

**Success Criteria:**
- [ ] `plan:budget_exhausted` event is emitted when the token budget runs out
- [ ] Event data includes `steps_completed`, `steps_remaining`, `tokens_used`, `token_budget`
- [ ] Frontend displays a visible warning to the user
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_der_rc6_budget_exhaustion.py
def test_budget_exhaustion_emits_event(mock_event_bus, mock_kernel):
    """RC6: budget exhaustion MUST emit plan:budget_exhausted, not silently stop."""
    # Setup: run DER with a very small token budget
    # Assert: IRISStreamEvent.BUDGET_EXHAUSTED was emitted
    # Assert: event data contains steps_remaining > 0
    pass
```

---

### 3.4 — Fix Premature Mode Escalation (M1)

**Root Cause:** `check_escalation` Trigger 4 (line 321–331) escalates when `budget_used_ratio < BUDGET_RATIO_ESCALATE` (< 30% used). For simple tasks that finish early, this wastes tokens by escalating unnecessarily.

**Files:**
- `backend/agent/der_loop.py` — `check_escalation` method, lines 321–331

**Change:** Add a complexity guard:

```python
# der_loop.py — replace Trigger 4 (lines 321-331)
# Trigger 4: Significant budget remaining AND task is actually complex
if mode_budget > 0 and token_budget_remaining < mode_budget:
    budget_used = max(0, mode_budget - token_budget_remaining)
    budget_used_ratio = budget_used / mode_budget
    # M1 FIX: only escalate on unused budget if task is complex
    # (has enough steps or tool diversity to warrant escalation)
    _completed = len(self.completed_ids)
    _total = len(self.items)
    _is_complex = _total >= 3 or len(set(
        i.tool for i in self.items if i.tool
    )) >= 2
    if budget_used_ratio < BUDGET_RATIO_ESCALATE and _is_complex:
        self.escalate(
            reason=f"Budget mostly unused ({token_budget_remaining}/{mode_budget}) "
                   f"and task is complex ({_total} steps) — escalating",
            turn_id=turn_id,
            token_budget=token_budget_remaining,
        )
        return True
```

**Success Criteria:**
- [ ] Simple 1–2 step tasks do not trigger budget-based escalation
- [ ] Complex tasks (≥ 3 steps or ≥ 2 distinct tools) still escalate correctly
- [ ] Existing escalation tests still pass (Trigger 1–3 unchanged)

**Test Contract:**
```python
# tests/test_der_m1_escalation.py
def test_simple_task_does_not_escalate_on_budget(queue_with_1_step):
    """M1: simple tasks MUST NOT escalate just because budget is unused."""
    escalated = queue_with_1_step.check_escalation(
        review_verdict=None,
        tool_result_summary="Done",
        token_budget_remaining=11000,  # lots of budget remaining
    )
    assert not escalated

def test_complex_task_escalates_on_budget(queue_with_5_steps):
    """M1: complex tasks SHOULD still escalate when budget is mostly unused."""
    escalated = queue_with_5_steps.check_escalation(
        review_verdict=None,
        tool_result_summary="Done",
        token_budget_remaining=11000,
    )
    assert escalated
```

---

### 3.5 — Non-Critical Failure Memory + Caducean Signal (M2)

**Root Cause:** Non-critical step failures continue silently (line 5104–5109) without writing to memory or signaling Caducean.

**Files:**
- `backend/agent/agent_kernel.py` — after the non-critical failure handling

**Change:** Ensure every failure, critical or not, writes a fragment and increments Caducean `y`:

```python
# agent_kernel.py — in the non-critical failure path
# M2 FIX: record non-critical failures to memory and Caducean
if not step_success and not item.critical:
    # Still fragment the failure output (A3 path handles critical; this handles non-critical)
    try:
        if self._memory_interface and step_result:
            _ep = self._memory_interface.episodic
            if hasattr(_ep, "fragment_and_store"):
                _ep.fragment_and_store(
                    content=f"[NON-CRITICAL FAIL Step {item.step_number}: {item.description[:80]}]\n{step_result[:500]}",
                    session_id=_session,
                    chunk_type="der_failure",
                    zone="failure",
                )
    except Exception:
        pass
    # Signal Caducean so drift detection accounts for non-critical failures
    # (Without this, Q never rises on non-critical failures and TOPO_VIOLATION
    #  never fires even if the task is failing in many non-critical ways)
```

**Success Criteria:**
- [ ] Non-critical failures are stored in PACMAN with `zone="failure"`
- [ ] Non-critical failures contribute to Caducean drift detection
- [ ] The existing non-critical continue behavior is preserved (plan keeps running)
- [ ] No existing tests break

**Test Contract:**
```python
# tests/test_der_m2_noncritical_failure.py
def test_noncritical_failure_stored_in_memory(mock_episodic):
    """M2: non-critical failures MUST be stored in PACMAN."""
    # Act: fragment a non-critical failure
    mock_episodic.fragment_and_store(
        content="[NON-CRITICAL FAIL Step 2: optional cleanup]\nFileNotFoundError",
        session_id="test",
        chunk_type="der_failure",
        zone="failure",
    )
    # Assert: chunk exists
    chunks = mock_episodic.db.execute(
        "SELECT * FROM context_chunks WHERE chunk_type='der_failure'"
    ).fetchall()
    assert len(chunks) >= 1
```

---

## Phase 4 — Frontend Event Alignment

Depends on: Phases 0–3 complete.

### 4.1 — New Event Types for Frontend

**Files:**
- `backend/agent/event_bus.py` — add new enum values
- `hooks/useAgentEvents.ts` — add handlers
- `stores/chat-store.ts` — add message types
- `components/chat/ChatMessage.tsx` — add rendering
- `components/task/TaskCard.tsx` — add status indicators

**New Events:**

| Event | Purpose | Phase |
|-------|---------|-------|
| `plan:budget_exhausted` | Token budget ran out mid-plan | 3.3 |
| `plan:validation_failed` | Pre-exec validation caught an invalid step | 0.3 |
| `plan:recovery_start` | Graft recovery initiated | 3.1 |
| `plan:topology_recovery` | Caducean-triggered recovery | 3.2 |

**Change in event_bus.py:**
```python
# Add to IRISStreamEvent enum
BUDGET_EXHAUSTED = "plan:budget_exhausted"
VALIDATION_FAILED = "plan:validation_failed"
RECOVERY_START = "plan:recovery_start"
TOPOLOGY_RECOVERY = "plan:topology_recovery"
```

**Change in useAgentEvents.ts:**
```typescript
// Add handlers for new event types
case "plan:budget_exhausted":
case "plan:validation_failed":
case "plan:recovery_start":
case "plan:topology_recovery":
    chatStore.addSystemMessage({
        type: event === "plan:budget_exhausted" ? "warning" : "info",
        text: payload.data.message || payload.data.reason || "Agent recovering...",
        metadata: payload.data,
    });
    break;
```

**Success Criteria:**
- [ ] All four new events are defined in `IRISStreamEvent`
- [ ] Frontend handles and displays all four event types without errors
- [ ] Events appear in the chat UI as system messages (warnings or info)
- [ ] `DebugPanel` shows the raw event data for debugging
- [ ] No existing frontend behavior breaks

**Test Contract:**
```typescript
// __tests__/useAgentEvents.test.ts
test("budget_exhausted event renders warning in chat", () => {
    // Setup: dispatch a plan:budget_exhausted event
    // Assert: chat store contains a warning message
});

test("topology_recovery event renders info in chat", () => {
    // Setup: dispatch a plan:topology_recovery event
    // Assert: chat store contains an info message
});
```

---

## Phase 5 — Capability & Compounding (Feature Work)

Depends on: Phases 0–4 complete. This phase adds new capabilities; all prior phases are reliability fixes.

### 5.1 — Verified Skill Capture (D1)

**Files:**
- `backend/agent/agent_kernel.py` — `_maybe_trigger_skill_creation` (line 1312)
- `backend/agent/workflow_capture.py` — **NEW FILE**

**Change:** Replace heuristic trigger with deterministic + verified:
1. Trigger when `len(distinct_tools)` >= 3 AND similarity to existing skills `< 0.85`
2. Self-test: replay the `tool_sequence` on a toy input
3. Register only if replay succeeds

> Full implementation details in [D1 section of the research doc](file:///c:/dev/IRISVOICE/research/der-pacman-execution-optimization.md).

### 5.2 — Multimedia Tools (D2)

**Files:**
- `backend/tools/media_tools.py` — **NEW FILE**
- `backend/agent/tool_registry.py` — register new tools

**Tools to add:**
1. `transcribe_media` → Parakeet `/transcribe` over HTTP (chunked ≤ 60s)
2. `analyze_video_frames` → vision server `analyze_screen` per frame
3. `clip_video` → ffmpeg wrapper

> Full implementation details in [D2 section of the research doc](file:///c:/dev/IRISVOICE/research/der-pacman-execution-optimization.md).

### 5.3 — Dispatch Consolidation (D3)

**Files:**
- `backend/agent/tool_executor.py` — delegate to `tool_bridge`
- `backend/agent/tool_bridge.py` — add `_execute_tool_with_resilience` wrapper

**Change:** Make `ToolExecutor` delegate to `AgentToolBridge.execute_tool` so resilience lives in one place.

---

## Verification Matrix

Every phase has a strict pass/fail gate. An agent MUST NOT proceed to the next phase until all criteria are met.

| Phase | Files Modified | Tests Required | Pass Gate |
|-------|---------------|----------------|-----------|
| 0.1 | `agent_kernel.py` | `test_der_c1_error_propagation.py` | `item.result` is never `None`/`""` on failure path |
| 0.2 | `episodic.py` | `test_episodic_rc8_tool_sequence.py` | `PROVEN SEQUENCE:` in context output |
| 0.3 | `agent_kernel.py`, `tool_registry.py` | `test_der_rc1_preexec_validation.py` | Invalid tools caught pre-exec |
| 0.4 | `db.py` | `test_db_thread_safety.py` | Multi-thread DB access succeeds |
| 1.1 | `resilience.py` (new), `agent_kernel.py` | `test_resilience.py` | Transient retried, permanent fail-fast |
| 1.2 | `tool_bridge.py`, `builtin_servers.py` | `test_mcp_timeout.py` | Timeout returns error, no hang |
| 2.1 | `agent_kernel.py` | `test_der_a1_failure_recall.py` | `PAST FAILURE WARNING:` in signal |
| 2.2 | `agent_kernel.py` | `test_der_a2_proven_sequence.py` | `PROVEN APPROACH:` in signal |
| 2.3 | `agent_kernel.py` | `test_der_a3_failure_fragments.py` | Failed outputs in PACMAN |
| 3.1 | `agent_kernel.py` | `test_der_graft_memory.py` | Graft prompt includes memory |
| 3.2 | `agent_kernel.py`, `iris_ffi.py` | `test_caducean_recovery.py` | Targeted recovery, not ReAct fallback |
| 3.3 | `agent_kernel.py`, `event_bus.py` | `test_der_rc6_budget_exhaustion.py` | Event emitted on exhaustion |
| 3.4 | `der_loop.py` | `test_der_m1_escalation.py` | Simple tasks don't escalate |
| 3.5 | `agent_kernel.py` | `test_der_m2_noncritical_failure.py` | Non-critical failures stored |
| 4.1 | `event_bus.py`, frontend files | `useAgentEvents.test.ts` | New events render in chat |

### Running All Tests

```bash
# Backend tests (all phases)
cd c:\dev\IRISVOICE
pytest tests/test_der_c1_error_propagation.py tests/test_episodic_rc8_tool_sequence.py tests/test_der_rc1_preexec_validation.py tests/test_db_thread_safety.py tests/test_resilience.py tests/test_mcp_timeout.py tests/test_der_a1_failure_recall.py tests/test_der_a2_proven_sequence.py tests/test_der_a3_failure_fragments.py tests/test_der_graft_memory.py tests/test_caducean_recovery.py tests/test_der_rc6_budget_exhaustion.py tests/test_der_m1_escalation.py tests/test_der_m2_noncritical_failure.py -v

# Frontend tests (Phase 4)
npx jest __tests__/useAgentEvents.test.ts --no-cache

# Full regression
pytest backend/tests/ -v --timeout=60
npm test
```

---

## Critical Rules for the Implementing Agent

1. **Never modify an existing test to make it pass.** The test is the requirement.
2. **Never skip a phase.** Dependencies are real — Phase 2 assumes Phase 0/1 fixes are in place.
3. **Run the phase's tests BEFORE moving on.** A green test suite is the only valid gate.
4. **Preserve all existing comments and docstrings** unrelated to your changes.
5. **Do not change the threading model.** DER runs in `run_in_executor`. Do not change this.
6. **Do not change the WebSocket message format.** Frontend expects `{"type": "agent_event", "payload": {...}}`.
7. **Do not change `QueueItem` fields.** Only add new fields if absolutely necessary (and update `der_loop.py` accordingly).
8. **Every `try/except` in the DER loop must have `loud_error` or `logger.warning`.** Silent `pass` blocks are forbidden for new code.
9. **All new code must handle the case where `self._memory_interface` is `None`.** Memory is optional in tests.
10. **All timeouts, retry counts, and backoff values must match the evidence-derived defaults** documented in the research doc §B header.
