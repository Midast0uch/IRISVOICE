"""DER execution-attempt ledger (REQ-2, REQ-4, REQ-9).

Semantic authority for long-horizon execution. Records every attempt, classifies
failures, and tracks the resumable task lifecycle — deliberately SEPARATE from:

- the phase scheduler (temporal authority; must not read reasoning state),
- ``memory.TaskRecord`` (terminal task HISTORY; this module owns LIVE lifecycle),
- the ``der_commits`` table (verified-count learning ledger; linked, not copied).

Design decisions honored (specs/long-horizon-der-execution/design.md):
- D1  ledger over physics veto — completion/retry come from here, not u/xi
- D2  stable action identity — ``action_key`` is a deterministic normalized
      digest, never Python's process-randomized ``hash()``
- D4  failure taxonomy before fan-out — ``classify_failure`` first
- D6  failure is information, not task termination — ``FailureEvidence`` is
      append-only; ``TaskLifecycle`` separately records whether work remains
- D7  resume is idempotent — lifecycle transitions are revisioned and optimistic

Persistence reuses the existing ``backend/sessions/`` JSON pattern (see
``backend/agent/memory.py:107-124``) — no new database.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Outcome classes (REQ-4) ────────────────────────────────────────────────
OUTCOME_SUCCESS = "success"
OUTCOME_TRANSIENT = "transient"
OUTCOME_INVALID_ARGS = "invalid_args"
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_EMPTY = "empty"
OUTCOME_SEMANTIC = "semantic"
OUTCOME_PERMANENT = "permanent"

OUTCOME_CLASSES = frozenset({
    OUTCOME_SUCCESS, OUTCOME_TRANSIENT, OUTCOME_INVALID_ARGS,
    OUTCOME_UNAVAILABLE, OUTCOME_EMPTY, OUTCOME_SEMANTIC, OUTCOME_PERMANENT,
})

# ── Task lifecycle states (REQ-9) ─────────────────────────────────────────
LIFECYCLE_PLANNED = "planned"
LIFECYCLE_RUNNING = "running"
LIFECYCLE_PAUSED = "paused"
LIFECYCLE_COMPLETED = "completed"
LIFECYCLE_PARTIAL = "partial"
LIFECYCLE_FAILED = "failed"
LIFECYCLE_CANCELLED = "cancelled"

LIFECYCLE_STATES = frozenset({
    LIFECYCLE_PLANNED, LIFECYCLE_RUNNING, LIFECYCLE_PAUSED,
    LIFECYCLE_COMPLETED, LIFECYCLE_PARTIAL, LIFECYCLE_FAILED, LIFECYCLE_CANCELLED,
})

# Terminal states: no further work may be scheduled under this lifecycle.
_TERMINAL = frozenset({LIFECYCLE_COMPLETED, LIFECYCLE_PARTIAL, LIFECYCLE_FAILED, LIFECYCLE_CANCELLED})


def _norm_text(text: str) -> str:
    """Lowercase + collapse whitespace/punctuation for stable identity."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def make_action_key(goal: str, tool: Optional[str] = None,
                    params: Optional[Dict[str, Any]] = None) -> str:
    """D2: deterministic normalized action identity.

    Inputs: goal text, tool name, and sorted JSON params. Output is a stable
    sha256 digest (first 16 hex chars). Never uses builtin ``hash()`` (which is
    process-randomized). Same inputs -> same key across restarts and replays.
    """
    _norm = _norm_text(goal or "")
    _params = json.dumps(params or {}, sort_keys=True, default=str)
    _tool = (tool or "").strip().lower()
    return hashlib.sha256(f"{_norm}|{_tool}|{_params}".encode("utf-8")).hexdigest()[:16]


def classify_failure(success: bool, error: Optional[str] = None,
                     error_type: Optional[str] = None,
                     result: Any = None) -> str:
    """D4/REQ-4: deterministic failure classification.

    ``success=True`` -> ``success`` (content is NOT inspected here; the caller
    checks emptiness separately and can re-classify as ``empty``).

    Failure precedence: rate-limit/timeout -> ``transient``; tool/missing schema
    -> ``unavailable``; empty-result signal -> ``empty``; bad arguments ->
    ``invalid_args``; explicit permanent/auth -> ``permanent``; otherwise the
    caller decides ``semantic`` (verify failed with real content) or a
    retry-class at the DER boundary.
    """
    if success:
        return OUTCOME_SUCCESS
    _e = (error or "").lower()
    _et = (error_type or "").lower()
    _blob = f"{_e} {_et}"
    if any(k in _blob for k in ("429", "rate", "ratelimit", "rate-limit", "timeout", "timed out", "temporarily unavailable")):
        return OUTCOME_TRANSIENT
    if any(k in _blob for k in ("not in registry", "not in available", "no such tool", "unknown tool", "tool not found", "not_found", "capability")):
        return OUTCOME_UNAVAILABLE
    if any(k in _blob for k in ("empty_result", "empty result", "no usable content", "no content", "no usable markdown", "produced no result")):
        return OUTCOME_EMPTY
    if any(k in _blob for k in ("requires a", "missing parameter", "invalid argument", "invalid args", "bad request", "validation")):
        return OUTCOME_INVALID_ARGS
    if any(k in _blob for k in ("permission", "unauthorized", "forbidden", "auth", "api key", "not configured")):
        return OUTCOME_PERMANENT
    return OUTCOME_PERMANENT  # caller may re-map to semantic/transient at the DER boundary


@dataclass
class ExecutionAttempt:
    """One executed (or planned) action within a task (REQ-2)."""
    attempt_id: str
    task_id: str
    step_id: str
    parent_step_id: Optional[str] = None
    action_key: str = ""
    tool: Optional[str] = None
    state: str = "running"          # planned | running | retrying | terminal
    outcome: str = ""               # one of OUTCOME_CLASSES once terminal
    verified_label: str = ""        # VERIFIED | UNVERIFIED | FAILED once verified
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    duration_ms: Optional[int] = None
    source_document_ids: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    error_type: Optional[str] = None

    def close(self, outcome: str, verified_label: str = "",
              source_document_ids: Optional[List[str]] = None,
              source_urls: Optional[List[str]] = None,
              error_type: Optional[str] = None) -> None:
        self.state = "terminal"
        self.outcome = outcome if outcome in OUTCOME_CLASSES else OUTCOME_PERMANENT
        self.verified_label = verified_label
        if source_document_ids:
            self.source_document_ids = list(source_document_ids)
        if source_urls:
            self.source_urls = list(source_urls)
        if error_type:
            self.error_type = error_type
        self.finished_at = time.time()
        self.duration_ms = int((self.finished_at - self.started_at) * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FailureEvidence:
    """Append-only learning record (REQ-9 / D6). Never mutated into success."""
    failure_id: str
    task_id: str
    step_id: str
    attempt_id: str
    failure_class: str
    input_summary: str = ""
    tool: Optional[str] = None
    error_type: Optional[str] = None
    error_summary: str = ""
    source_document_ids: List[str] = field(default_factory=list)
    recovered: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskLifecycle:
    """Resumable task state (REQ-9). Distinct from ``memory.TaskRecord`` (which
    records terminal task HISTORY for session summaries)."""
    task_id: str
    conversation_id: str = ""
    lifecycle: str = LIFECYCLE_PLANNED
    plan_version: str = ""
    required_step_ids: List[str] = field(default_factory=list)
    completed_step_ids: List[str] = field(default_factory=list)
    pending_step_ids: List[str] = field(default_factory=list)
    active_attempt_id: Optional[str] = None
    next_action: Optional[str] = None
    final_document_id: Optional[str] = None
    revision: int = 0
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.revision += 1
        self.updated_at = time.time()

    def is_terminal(self) -> bool:
        return self.lifecycle in _TERMINAL

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskLifecycle":
        _known = set(cls.__dataclass_fields__)  # keys ARE the field names
        return cls(**{k: v for k, v in data.items() if k in _known})


class ExecutionLedger:
    """Per-conversation semantic authority for attempts, failures, and lifecycle.

    In-memory by default; ``storage_path`` enables JSON persistence using the
    existing ``backend/sessions/`` pattern. Never raises on storage errors —
    durability is reported to the caller (D8: persistence gates terminal state).
    """

    def __init__(self, conversation_id: str = "", storage_path: Optional[str] = None) -> None:
        self.conversation_id = conversation_id
        self._attempts: Dict[str, ExecutionAttempt] = {}       # attempt_id -> attempt
        self._failures: List[FailureEvidence] = []             # append-only
        self._tasks: Dict[str, TaskLifecycle] = {}             # task_id -> lifecycle
        self._storage_path: Optional[Path] = None
        if storage_path:
            self._storage_path = Path(storage_path)
            self._storage_path.mkdir(parents=True, exist_ok=True)
            self._load()

    # ── attempts ─────────────────────────────────────────────────────────
    def open_attempt(self, task_id: str, step_id: str,
                     parent_step_id: Optional[str] = None,
                     action_key: str = "", tool: Optional[str] = None) -> ExecutionAttempt:
        attempt = ExecutionAttempt(
            attempt_id=uuid.uuid4().hex,
            task_id=task_id,
            step_id=step_id,
            parent_step_id=parent_step_id,
            action_key=action_key,
            tool=tool,
        )
        self._attempts[attempt.attempt_id] = attempt
        task = self._tasks.setdefault(task_id, TaskLifecycle(task_id=task_id, conversation_id=self.conversation_id))
        task.active_attempt_id = attempt.attempt_id
        task.touch()
        return attempt

    def get_attempt(self, attempt_id: str) -> Optional[ExecutionAttempt]:
        return self._attempts.get(attempt_id)

    def close_attempt(self, attempt: ExecutionAttempt, outcome: str,
                      verified_label: str = "",
                      source_document_ids: Optional[List[str]] = None,
                      source_urls: Optional[List[str]] = None,
                      error_type: Optional[str] = None) -> None:
        attempt.close(outcome, verified_label, source_document_ids, source_urls, error_type)
        task = self._tasks.get(attempt.task_id)
        if task is not None:
            if verified_label == "VERIFIED":
                if attempt.step_id not in task.completed_step_ids:
                    task.completed_step_ids.append(attempt.step_id)
                if attempt.step_id in task.pending_step_ids:
                    task.pending_step_ids.remove(attempt.step_id)
            elif attempt.step_id not in task.pending_step_ids and attempt.step_id not in task.completed_step_ids:
                task.pending_step_ids.append(attempt.step_id)
            task.touch()

    # ── failure learning (REQ-9 / D6) ────────────────────────────────────
    def record_failure(self, task_id: str, step_id: str, attempt_id: str,
                       failure_class: str, input_summary: str = "",
                       tool: Optional[str] = None, error_type: Optional[str] = None,
                       error_summary: str = "",
                       source_document_ids: Optional[List[str]] = None,
                       recovered: bool = False) -> FailureEvidence:
        ev = FailureEvidence(
            failure_id=uuid.uuid4().hex,
            task_id=task_id,
            step_id=step_id,
            attempt_id=attempt_id,
            failure_class=failure_class if failure_class in OUTCOME_CLASSES else OUTCOME_PERMANENT,
            input_summary=input_summary,
            tool=tool,
            error_type=error_type,
            error_summary=error_summary,
            source_document_ids=list(source_document_ids or []),
            recovered=recovered,
        )
        self._failures.append(ev)  # append-only: never mutated
        return ev

    def failures(self, task_id: Optional[str] = None) -> List[FailureEvidence]:
        if task_id is None:
            return list(self._failures)
        return [f for f in self._failures if f.task_id == task_id]

    # ── lifecycle (REQ-9 / D7) ───────────────────────────────────────────
    def transition(self, task_id: str, new_state: str,
                   expected_revision: Optional[int] = None,
                   **updates: Any) -> Optional[TaskLifecycle]:
        """Revisioned, optimistic lifecycle transition.

        Returns the updated TaskLifecycle, or None when ``expected_revision``
        does not match (concurrent writer — caller must re-read and retry).
        """
        if new_state not in LIFECYCLE_STATES:
            return None
        task = self._tasks.get(task_id)
        if task is None:
            task = TaskLifecycle(task_id=task_id, conversation_id=self.conversation_id)
            self._tasks[task_id] = task
        if expected_revision is not None and task.revision != expected_revision:
            return None  # stale write — no-op, caller re-reads
        if task.is_terminal() and new_state != task.lifecycle:
            # D7: exactly-once terminal semantics — a terminal lifecycle is final.
            return task
        task.lifecycle = new_state
        for k, v in updates.items():
            if hasattr(task, k):
                setattr(task, k, v)
        task.touch()
        return task

    def get_task(self, task_id: str) -> Optional[TaskLifecycle]:
        return self._tasks.get(task_id)

    def snapshot(self, task_id: str) -> Dict[str, Any]:
        """Full observable state for a task (diagnostics / REQ-8)."""
        task = self._tasks.get(task_id)
        return {
            "task": task.to_dict() if task else None,
            "attempts": [a.to_dict() for a in self._attempts.values() if a.task_id == task_id],
            "failures": [f.to_dict() for f in self._failures if f.task_id == task_id],
        }

    # ── durability (reuses backend/sessions JSON pattern) ───────────────
    def _data_file(self) -> Path:
        return self._storage_path / "der_execution_ledger.json"

    def persist(self) -> bool:
        """Write the ledger atomically. Returns False (no raise) on failure."""
        if self._storage_path is None:
            return True  # in-memory only — nothing to persist
        try:
            payload = {
                "conversation_id": self.conversation_id,
                "attempts": [a.to_dict() for a in self._attempts.values()],
                "failures": [f.to_dict() for f in self._failures],
                "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
            }
            _tmp = self._data_file().with_suffix(".json.tmp")
            _tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(_tmp, self._data_file())
            return True
        except Exception:
            return False

    def _load(self) -> None:
        try:
            _f = self._data_file()
            if not _f.is_file():
                return
            data = json.loads(_f.read_text(encoding="utf-8"))
            self.conversation_id = data.get("conversation_id", self.conversation_id)
            for a in data.get("attempts", []):
                self._attempts[a["attempt_id"]] = ExecutionAttempt(**{k: v for k, v in a.items() if k in ExecutionAttempt.__dataclass_fields__})
            for f in data.get("failures", []):
                self._failures.append(FailureEvidence(**{k: v for k, v in f.items() if k in FailureEvidence.__dataclass_fields__}))
            for tid, t in (data.get("tasks") or {}).items():
                self._tasks[tid] = TaskLifecycle.from_dict(t)
        except Exception:
            # Corrupt ledger -> start fresh, never raise in a hot path.
            self._attempts.clear()
            self._failures.clear()
            self._tasks.clear()
