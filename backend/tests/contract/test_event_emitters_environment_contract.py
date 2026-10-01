"""ENVIRONMENT rule emitters (docs/Design/EVENT_TAXONOMY.md, build step 2): DEPENDENCY_CHANGED
when a dependency edit makes memory stale (path + counts), RESOURCE_LIMIT when a tool fails with a
rate-limit / quota cause. Real writer, temp store."""
from __future__ import annotations

import pytest

from backend.memory import memory_events as me
from backend.tests.contract.test_event_emitters_knowledge_contract import _rows, store  # noqa: F401


# ── ENVIRONMENT ─────────────────────────────────────────────────────────────

def _verified_fix_on(store, path):
    t = "s1:t0"
    me.record_step(store, thread_id="s1", task_id=t, step_id="1", tool="run_command",
                   params={"command": "pytest"}, success=False, verified="FAILED",
                   error_text="AssertionError: expected 3 got 2")
    me.record_step(store, thread_id="s1", task_id=t, step_id="2", tool="edit_file",
                   params={"path": path}, success=True, verified="VERIFIED", description="fix it")
    me.record_task_end(store, thread_id="s1", task_id=t, success=True)


def test_an_edit_to_a_dependency_is_dependency_changed_with_path_and_counts(store):
    _verified_fix_on(store, "backend/a.py")
    assert _rows(store, "DEPENDENCY_CHANGED") == []          # the fix itself changed nothing stale
    me.record_step(store, thread_id="s1", task_id="s1:t1", step_id="1", tool="edit_file",
                   params={"path": "backend/a.py"}, success=True, verified="VERIFIED")
    (ev,) = _rows(store, "DEPENDENCY_CHANGED")
    assert (ev["family"], ev["actor"], ev["episode_id"], ev["step_index"]) == (
        "environment", "world", "s1:t1", "1")
    assert ev["payload"] == {"path": "backend/a.py", "cases": 1, "landmarks": 0}


def test_an_edit_that_stales_nothing_types_nothing(store):
    me.record_step(store, thread_id="s1", task_id="s1:t1", step_id="1", tool="edit_file",
                   params={"path": "backend/nothing_depends_on_me.py"}, success=True, verified="VERIFIED")
    assert _rows(store, "DEPENDENCY_CHANGED") == []


@pytest.mark.parametrize("text", [
    "HTTP 429 Too Many Requests", "Error: rate_limited, retry later", "quota exceeded for this key",
    "status code: 429",
])
def test_a_rate_limit_or_quota_failure_is_resource_limit(store, text):
    written = me.record_step(store, thread_id="s1", task_id="s1:t1", step_id="1", tool="crawler_query",
                             params={"query": "x"}, success=False, verified="FAILED", error_text=text)
    assert written == ["OBSTACLE", "RESOURCE_LIMIT"]
    (ev,) = _rows(store, "RESOURCE_LIMIT")
    assert (ev["family"], ev["valence"], ev["cause_key"]) == ("environment", "sets_back", "maybe|world|blocked")
    assert ev["step_index"] == "1" and ev["payload"]["tool"] == "crawler_query"


@pytest.mark.parametrize("text", [
    'File "a.py", line 429\nAssertionError: expected 3 got 2', "quotation marks missing", "boom",
])
def test_an_ordinary_failure_is_not_resource_limit(store, text):
    written = me.record_step(store, thread_id="s1", task_id="s1:t1", step_id="1", tool="run_command",
                             params={"command": "pytest"}, success=False, verified="FAILED",
                             error_text=text)
    assert "RESOURCE_LIMIT" not in written and _rows(store, "RESOURCE_LIMIT") == []
