"""Typed execution events and cases (spec research-memory-chain-browser D9 / Wave E).

The pipeline's steps become typed events on the Immortus chain (the time layer,
``memory_chain``): BUG, ATTEMPT, DEAD_END, FIX, VERIFIED_FIX, LESSON. Events about
one problem form a CASE (``memory_cases``) keyed by an error signature, with what
the fix depends on and how it could be falsified.

Rules (docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md 7.9, 7.11):
- Credit is per event: a FIX is the step the verifier touched, not the whole run.
- Only OUTSIDE evidence verifies a fix (task completion, a passing test command,
  user confirmation). The model's own claim never does; a LESSON is a candidate.
- A changed dependency makes a verified case STALE; the same failure after a
  verified fix is a CONTRADICTION and DEMOTES it. Nothing is deleted.

Every function takes a sqlite connection to the app store and never raises: the
callers run on the ``memory_events`` durability lane, off the answer path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

EVENT_TYPES = ("BUG", "ATTEMPT", "DEAD_END", "FIX", "VERIFIED_FIX", "LESSON")

_EDIT_TOOLS = frozenset({"write_file", "edit_file", "create_directory", "delete_file", "move_file"})
_TEST_RE = re.compile(
    r"\b(pytest|unittest|npm\s+(run\s+)?test|npx\s+jest|jest|vitest|cargo\s+test|go\s+test|tsc\s+--noEmit)\b",
    re.IGNORECASE,
)
_DEAD_END_KEEP = 20          # bounded list of dead-end action signatures per case
_TRAIL_MAX_CHARS = 400       # owner rule: a bounded block, only at a failure
_TRAIL_HALF_LIFE_DAYS = 30.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_cases (
    case_id        TEXT PRIMARY KEY,
    signature      TEXT NOT NULL,
    tool           TEXT,
    symptom        TEXT,
    status         TEXT NOT NULL,
    open_task      TEXT,
    thread_id      TEXT,
    depends_on     TEXT DEFAULT '[]',
    falsify_if     TEXT,
    attempts       INTEGER DEFAULT 0,
    dead_ends      TEXT DEFAULT '[]',
    dead_end_repeats INTEGER DEFAULT 0,
    fix_step       TEXT,
    fix_desc       TEXT,
    verified_count INTEGER DEFAULT 0,
    last_verified  REAL,
    contradictions INTEGER DEFAULT 0,
    strength       REAL DEFAULT 0,
    first_seen     REAL NOT NULL,
    last_seen      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_cases_signature ON memory_cases(signature);
CREATE INDEX IF NOT EXISTS idx_memory_cases_open_task ON memory_cases(open_task);
"""


def ensure_schema(conn) -> None:
    conn.executescript(_SCHEMA)


# ── signatures and dependencies ─────────────────────────────────────────────

_NOISE = [
    (re.compile(r"[a-zA-Z]:\\[^\s'\"]+|/[\w./-]+"), "<path>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<hex>"),
    (re.compile(r"\d+"), "<n>"),
    (re.compile(r"(['\"]).*?\1"), "<s>"),
    (re.compile(r"\s+"), " "),
]


def _first_error_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in reversed(lines):  # tracebacks end with the exception line
        if re.match(r"^[A-Za-z_.]*(Error|Exception|Failed|failed|error)\b", ln):
            return ln
    return lines[0] if lines else ""


def error_signature(tool: Optional[str], error_text: str) -> str:
    line = _first_error_line(error_text)[:300].lower()
    for pat, rep in _NOISE:
        line = pat.sub(rep, line)
    return hashlib.sha1(f"{tool or 'none'}|{line.strip()}".encode("utf-8")).hexdigest()[:12]


def _target(params: Optional[dict]) -> str:
    if not isinstance(params, dict):
        return ""
    for key in ("path", "file_path", "target", "url", "command", "query"):
        val = params.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:200]
    return ""


def action_signature(tool: Optional[str], params: Optional[dict]) -> str:
    return f"{tool or 'none'}:{_target(params)}"


def dependencies(tool: Optional[str], params: Optional[dict]) -> List[str]:
    """What a step's result depends on: the files, commands or URLs it touched."""
    if not isinstance(params, dict):
        return []
    deps = []
    for key in ("path", "file_path", "url"):
        val = params.get(key)
        if isinstance(val, str) and val.strip():
            deps.append(val.strip()[:200])
    cmd = params.get("command")
    if isinstance(cmd, str) and cmd.strip():
        deps.append(f"cmd:{cmd.strip()[:200]}")
    return deps


def is_test_command(tool: Optional[str], params: Optional[dict]) -> bool:
    return tool == "run_command" and bool(_TEST_RE.search(_target(params)))


# ── chain rows (the time layer) ─────────────────────────────────────────────

def _append_event(thread_id: str, etype: str, case_id: str, payload: dict,
                  insight: str, coords: Optional[str]) -> None:
    try:
        from backend.gateway.iris_ffi import ffi_immortus_chain_append

        ffi_immortus_chain_append(
            thread_id=thread_id,
            result=json.dumps({"type": etype, "case": case_id, **payload}, ensure_ascii=False),
            coords_from=coords,
            coords_to=coords,
            # Evidence rows keep their own prefix ("evidence:test_pass").
            nbl_outcome=etype if etype.startswith("evidence:") else f"event:{etype}",
            insight=(insight or "")[:120],
            file_path=case_id,
            landmark_id="",
        )
    except Exception as exc:  # noqa: BLE001 — an event row never breaks the lane
        logger.warning("[memory_events] chain append failed type=%s case=%s: %s", etype, case_id, exc)


def _flush(conn, thread_id: str, pending: List[tuple], coords: Optional[str]) -> None:
    """Commit the case changes FIRST, then append the chain rows: the chain
    writer uses its own connection to the same file, so an open transaction
    here would make it wait on the lock."""
    conn.commit()
    for etype, case_id, payload, insight in pending:
        _append_event(thread_id, etype, case_id, payload, insight, coords)


# ── case helpers ────────────────────────────────────────────────────────────

_CASE_COLS = (
    "case_id, signature, tool, symptom, status, open_task, thread_id, depends_on, "
    "falsify_if, attempts, dead_ends, dead_end_repeats, fix_step, fix_desc, "
    "verified_count, last_verified, contradictions, strength, first_seen, last_seen"
)


def _row(conn, sql: str, params: Iterable[Any]) -> Optional[Dict[str, Any]]:
    cur = conn.execute(f"SELECT {_CASE_COLS} FROM memory_cases {sql}", tuple(params))
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([c.strip() for c in _CASE_COLS.split(",")], row))


def _open_case(conn, task_id: str) -> Optional[Dict[str, Any]]:
    return _row(
        conn,
        "WHERE open_task = ? AND status IN ('open', 'demoted', 'fixed') "
        "ORDER BY last_seen DESC LIMIT 1",
        (task_id,),
    )


def _merge_list(raw: Optional[str], extra: Iterable[str], keep: int = 50) -> str:
    try:
        cur = list(json.loads(raw or "[]"))
    except Exception:  # noqa: BLE001
        cur = []
    for item in extra:
        if item and item not in cur:
            cur.append(item)
    return json.dumps(cur[-keep:])


def _mark_stale_dependents(conn, path: str, task_id: str) -> int:
    """A changed dependency makes VERIFIED knowledge stale (re-check on next use)."""
    if not path:
        return 0
    like = "%" + json.dumps(path)[1:-1] + "%"
    n = conn.execute(
        "UPDATE memory_cases SET status = 'stale' WHERE status = 'verified' "
        "AND depends_on LIKE ? AND (open_task IS NULL OR open_task != ?)",
        (like, task_id),
    ).rowcount
    try:
        from backend.memory.mycelium.landmark import mark_landmarks_stale_by_dependency

        n += mark_landmarks_stale_by_dependency(conn, path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] landmark staleness skipped: %s", exc)
    if n:
        logger.info("[memory_events] stale dependents=%d path=%s task=%s", n, path[:80], task_id)
    return n


# ── the two entry points ────────────────────────────────────────────────────

def record_step(
    conn,
    *,
    thread_id: str,
    task_id: str,
    step_id: str,
    tool: Optional[str],
    params: Optional[dict],
    success: bool,
    verified: str,
    error_text: str = "",
    description: str = "",
    coords: Optional[str] = None,
) -> List[str]:
    """Type one finished DER step. Returns the event types written."""
    try:
        ensure_schema(conn)
        now = time.time()
        tool = tool or "none"
        deps = dependencies(tool, params)
        act = action_signature(tool, params)
        written: List[str] = []
        pending: List[tuple] = []
        failed = (not success) or verified == "FAILED"
        case = _open_case(conn, task_id)

        if failed:
            if case is not None:
                dead = json.loads(case["dead_ends"] or "[]")
                repeat = act in dead
                conn.execute(
                    "UPDATE memory_cases SET attempts = attempts + 1, dead_ends = ?, "
                    "dead_end_repeats = dead_end_repeats + ?, last_seen = ? WHERE case_id = ?",
                    (_merge_list(case["dead_ends"], [act], _DEAD_END_KEEP), 1 if repeat else 0,
                     now, case["case_id"]),
                )
                if repeat:
                    logger.info("[memory_events] counter repeated_dead_end case=%s action=%s",
                                case["case_id"], act[:80])
                pending.append(("DEAD_END", case["case_id"],
                                {"action": act, "step": step_id, "task": task_id}, description))
                written.append("DEAD_END")
            else:
                sig = error_signature(tool, error_text or description)
                prior = _row(conn, "WHERE signature = ? ORDER BY last_seen DESC LIMIT 1", (sig,))
                payload = {"signature": sig, "tool": tool, "step": step_id, "task": task_id}
                if prior is not None and prior["status"] in ("verified", "fixed", "stale"):
                    # The same failure after a fix: the fix did not hold.
                    conn.execute(
                        "UPDATE memory_cases SET status = 'demoted', contradictions = contradictions + 1, "
                        "open_task = ?, thread_id = ?, last_seen = ? WHERE case_id = ?",
                        (task_id, thread_id, now, prior["case_id"]),
                    )
                    try:
                        from backend.memory.mycelium.landmark import demote_landmarks_for_thread

                        demote_landmarks_for_thread(conn, prior["thread_id"], f"case {sig} recurred")
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[memory_events] landmark demotion skipped: %s", exc)
                    logger.info("[memory_events] counter contradiction case=%s", prior["case_id"])
                    case_id = prior["case_id"]
                    payload["contradicts"] = True
                elif prior is not None:
                    conn.execute(
                        "UPDATE memory_cases SET status = 'open', open_task = ?, thread_id = ?, "
                        "last_seen = ? WHERE case_id = ?",
                        (task_id, thread_id, now, prior["case_id"]),
                    )
                    case_id = prior["case_id"]
                else:
                    case_id = "case-" + uuid.uuid4().hex[:12]
                    conn.execute(
                        "INSERT INTO memory_cases (case_id, signature, tool, symptom, status, "
                        "open_task, thread_id, depends_on, first_seen, last_seen) "
                        "VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)",
                        (case_id, sig, tool, _first_error_line(error_text)[:300], task_id,
                         thread_id, json.dumps(deps), now, now),
                    )
                pending.append(("BUG", case_id, payload, description))
                written.append("BUG")
        else:
            if case is not None:
                if verified == "VERIFIED":
                    conn.execute(
                        "UPDATE memory_cases SET status = 'fixed', fix_step = ?, fix_desc = ?, "
                        "depends_on = ?, falsify_if = ?, last_seen = ? WHERE case_id = ?",
                        (step_id, (description or "")[:300],
                         _merge_list(case["depends_on"], deps),
                         f"error signature {case['signature']} recurs, or a dependency changes",
                         now, case["case_id"]),
                    )
                    pending.append(("FIX", case["case_id"],
                                    {"action": act, "step": step_id, "task": task_id, "depends_on": deps},
                                    description))
                    written.append("FIX")
                else:
                    conn.execute(
                        "UPDATE memory_cases SET attempts = attempts + 1, last_seen = ? WHERE case_id = ?",
                        (now, case["case_id"]),
                    )
                    pending.append(("ATTEMPT", case["case_id"],
                                    {"action": act, "step": step_id, "task": task_id}, description))
                    written.append("ATTEMPT")
            if tool in _EDIT_TOOLS:
                for dep in deps:
                    _mark_stale_dependents(conn, dep, task_id)
            if verified == "VERIFIED" and is_test_command(tool, params):
                pending.append(("evidence:test_pass", "", {"step": step_id, "task": task_id,
                                "command": _target(params)}, description))
                written += _verify_fixed(conn, task_id, "test_pass", pending)
        _flush(conn, thread_id, pending, coords)
        return written
    except Exception as exc:  # noqa: BLE001 — typing never breaks the lane
        logger.warning("[memory_events] record_step failed task=%s step=%s: %s", task_id, step_id, exc)
        return []


def record_task_end(
    conn,
    *,
    thread_id: str,
    task_id: str,
    success: bool,
    user_confirmed: bool = False,
    coords: Optional[str] = None,
) -> List[str]:
    """Task completion is outside evidence for this task's FIXes. Closes its cases."""
    try:
        ensure_schema(conn)
        written: List[str] = []
        pending: List[tuple] = []
        if success:
            written += _verify_fixed(conn, task_id, "task_complete", pending)
            if user_confirmed:
                written += _verify_fixed(conn, task_id, "user_confirm", pending,
                                         statuses=("verified",))
        conn.execute("UPDATE memory_cases SET open_task = NULL WHERE open_task = ?", (task_id,))
        _flush(conn, thread_id, pending, coords)
        return written
    except Exception as exc:  # noqa: BLE001
        logger.warning("[memory_events] record_task_end failed task=%s: %s", task_id, exc)
        return []


def _verify_fixed(conn, task_id: str, evidence: str, pending: List[tuple],
                  statuses=("fixed",)) -> List[str]:
    """Outside evidence turns this task's FIXes into VERIFIED_FIX (+ a LESSON candidate)."""
    written: List[str] = []
    marks = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT case_id, signature, fix_step, fix_desc, depends_on, status FROM memory_cases "
        f"WHERE open_task = ? AND status IN ({marks})",
        (task_id, *statuses),
    ).fetchall()
    now = time.time()
    for case_id, sig, fix_step, fix_desc, deps, status in rows:
        conn.execute(
            "UPDATE memory_cases SET status = 'verified', verified_count = verified_count + 1, "
            "last_verified = ?, strength = strength + 1, last_seen = ? WHERE case_id = ?",
            (now, now, case_id),
        )
        pending.append(("VERIFIED_FIX", case_id,
                        {"signature": sig, "evidence": evidence, "fix_step": fix_step, "task": task_id},
                        fix_desc or ""))
        written.append("VERIFIED_FIX")
        if status == "fixed":
            # The fix step's own description is model-authored: a CANDIDATE, data not
            # instructions, linked to the case it summarizes (provenance).
            pending.append(("LESSON", case_id,
                            {"candidate": True, "author": "model", "text": (fix_desc or "")[:300],
                             "provenance": {"case": case_id, "fix_step": fix_step, "depends_on":
                                            json.loads(deps or "[]")}},
                            fix_desc or ""))
            written.append("LESSON")
    return written


# ── surfacing (only at a failure; relevance by construction) ────────────────

def case_trail(conn, tool: Optional[str], error_text: str) -> str:
    """One bounded block when a live failure matches a known case, else ''."""
    try:
        ensure_schema(conn)
        case = _row(conn, "WHERE signature = ? ORDER BY last_seen DESC LIMIT 1",
                    (error_signature(tool, error_text),))
        if case is None:
            return ""
        dead = json.loads(case["dead_ends"] or "[]")
        if not case["fix_desc"] and not dead:
            return ""
        age_days = (time.time() - (case["last_verified"] or case["last_seen"])) / 86400.0
        strength = (case["strength"] or 0.0) * 0.5 ** (age_days / _TRAIL_HALF_LIFE_DAYS)
        parts = [f"KNOWN CASE ({case['status']}"
                 + (", dependency changed - re-check" if case["status"] == "stale" else "")
                 + (f", contradicted {case['contradictions']}x" if case["contradictions"] else "")
                 + ")"]
        if case["fix_desc"]:
            when = time.strftime("%Y-%m-%d", time.localtime(case["last_verified"])) if case["last_verified"] else "never"
            parts.append(f"fix: {case['fix_desc'][:160]} (verified {case['verified_count']}x, last {when}, "
                         f"strength {strength:.1f})")
        if dead:
            parts.append("dead ends: " + "; ".join(d[:60] for d in dead[-3:]))
        logger.info("[memory_events] trail shown case=%s status=%s", case["case_id"], case["status"])
        return (" | ".join(parts))[:_TRAIL_MAX_CHARS]
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] case_trail failed: %s", exc)
        return ""


def session_evidence(conn, thread_id: str) -> Dict[str, Any]:
    """Outside evidence and dependencies a session's events recorded (for landmarks)."""
    out: Dict[str, Any] = {"kinds": [], "depends_on": [], "verified_steps": []}
    try:
        rows = conn.execute(
            "SELECT nbl_outcome, result FROM memory_chain WHERE thread_id = ? "
            "AND (nbl_outcome LIKE 'event:%' OR nbl_outcome LIKE 'evidence:%') ORDER BY created_at",
            (thread_id,),
        ).fetchall()
        for outcome, result in rows:
            try:
                data = json.loads(result or "{}")
            except Exception:  # noqa: BLE001
                data = {}
            if outcome == "evidence:test_pass" and "test_pass" not in out["kinds"]:
                out["kinds"].append("test_pass")
            if outcome in ("event:FIX", "event:VERIFIED_FIX"):
                for dep in data.get("depends_on") or []:
                    if dep not in out["depends_on"]:
                        out["depends_on"].append(dep)
                step = data.get("step") or data.get("fix_step")
                if step and step not in out["verified_steps"]:
                    out["verified_steps"].append(step)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] session_evidence failed: %s", exc)
    return out
