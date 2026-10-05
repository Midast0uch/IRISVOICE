"""Parallel nodes (2026-10-04) - the tool bridge's ONE audit logger serves
many event loops at once.

Each DER node runs on its own thread and each tool call runs under its own
asyncio.run, so the bridge's single SecurityAuditLogger is used from many event
loops concurrently. Its lock was an asyncio.Lock: it binds to the first loop
that waits on it, so with two parallel nodes every tool call crashed ("... is
bound to a different event loop") or hung to its 60 s timeout (live c03,
2026-10-04: edit_file and read_file CRASHED, 60 s of a 99 s turn).

Contract: four threads, each with its own event loop, log 200 tool operations
each through one logger, with no error and every event counted.
"""
from __future__ import annotations

import asyncio
import threading

from backend.security.audit_logger import SecurityAuditLogger
from backend.security.security_types import SecurityContext


def test_one_audit_logger_serves_many_event_loops(tmp_path):
    logger = SecurityAuditLogger(log_dir=tmp_path)
    errors: list = []
    n_threads, n_events = 4, 200

    def worker(i: int) -> None:
        async def go() -> None:
            for k in range(n_events):
                await logger.log_tool_operation(
                    tool_name="read_file", operation="read",
                    arguments={"path": f"f{i}_{k}.py"},
                    context=SecurityContext(session_id=f"s{i}", tool_name="read_file"),
                    result="ok", risk_score=0.0,
                )
                if k % 20 == 0:
                    await asyncio.sleep(0)  # interleave the loops

        try:
            asyncio.run(go())
        except Exception as exc:  # noqa: BLE001 - the assertion reports it
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors[:3]
    assert logger._stats["events_total"] == n_threads * n_events
