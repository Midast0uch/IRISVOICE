"""tool_approval - the SAFETY question for one tool call (2026-11-10, owner).

"May this call run without asking the user first?" - shadow only. The label is
OUTSIDE the model and outside the permission rule it is measured against: the
user's own answer to a permission prompt, or the owner-reviewed answer sheet
(evals/safety). Replaces the v1-v6 reliability question ("will this call
succeed?", labelled by the call's outcome), which a per-tool failure count
beat and which never measured safety; its post-hoc consult on every tool call
and its pre-call guard are removed.

Each guard FAILS on the pre-change code: the old module has no safety_frame,
no record_permission_answer, and the permission answer wrote no row.
"""
from __future__ import annotations

from pathlib import Path

from backend.agent import decision_engine as de
from backend.agent import tool_approval_shadow as ta

_ROOT = Path(__file__).resolve().parents[3]


class _StubNoul:
    """The minimal Noul surface shadow_row reads."""

    def __init__(self, probability: float, latency_ms: int = 7) -> None:
        self.probability = probability
        self.engine_latency_ms = latency_ms

    def true(self, cut: float = 0.5) -> bool:
        return self.probability >= cut


class _Lane:
    def __init__(self, sink: dict) -> None:
        self.sink = sink

    def submit(self, name, job):
        self.sink["name"] = name
        self.sink["job"] = job
        return True


# ── the job and the declaration ────────────────────────────────────────────


def test_tool_approval_asks_the_safety_question():
    assert de.CONSUMER_JOBS["tool_approval"] == "approve"
    assert "without asking the user" in de.ORACLE_JOBS["approve"].question
    assert "without asking the user first" in ta.TOOL_APPROVAL_INSTRUCTION
    assert ta.CRITERIA_VERSION == "tool_approval/safety-v3"
    assert de.declared_type("tool_approval") == "noul"


def test_tool_approval_is_a_binary_consumer():
    from backend.agent.oracle_calibration import binary_consumers

    assert "tool_approval" in binary_consumers()


def test_the_acting_answer_is_safe_and_there_is_no_site():
    """"yes" would skip the user's prompt - the side the bar must hold. No code
    acts on it yet (shadow), so it is declared as having no decision site."""
    from backend.agent.consumer_bar import ACTING_ANSWER, ACTING_ENFORCED

    assert ACTING_ANSWER["tool_approval"] == "yes"
    assert "tool_approval" in ACTING_ENFORCED
    assert "tool_approval" in de.NO_DECISION_SITE


# ── the frame ──────────────────────────────────────────────────────────────


def test_the_frame_carries_no_verdict():
    """The frame holds what the call does and what was asked - never the
    permission tier, the pattern verdict or the answer."""
    f = ta.safety_frame("clean the build folder", "run_command",
                        {"command": "rm -rf build/"})
    assert set(f) == {"goal", "proposed_tool", "tool_description", "args"}
    assert "rm -rf build/" in f["args"]
    text = de.job_input("tool_approval", f).text
    assert "clean the build folder" in text and "rm -rf build/" in text
    for leak in ("destructive", "side_effect", "approved", "denied"):
        assert leak not in str(f).lower()


# ── the row ────────────────────────────────────────────────────────────────


def test_row_carries_the_outside_label():
    f = ta.safety_frame("delete notes.txt", "delete_file", {"path": "notes.txt"})
    row = ta.shadow_row(_StubNoul(0.2), True, label_source=ta.LABEL_USER, state=f)
    assert row["chosen"] is False and row["confidence"] == 0.8
    assert row["outside_label"] is True and row["brain_bool"] is True
    assert row["label_source"] == "user"
    assert row["criteria_version"] == "tool_approval/safety-v3"
    assert row["state"] == f and row["input_key"]


def test_no_row_without_a_noul():
    assert ta.shadow_row(None, True, label_source=ta.LABEL_USER, state={}) is None


# ── the live label: the user's answer ──────────────────────────────────────


def test_an_answer_is_scored_on_the_lane(monkeypatch):
    import backend.utils.durability_queue as dq

    sub = {}
    monkeypatch.setattr(dq, "lane", lambda _n: _Lane(sub))
    rows = []
    ta.set_row_sink(rows.append)
    try:
        ta.record_permission_answer(goal="tidy up", tool_name="run_command",
                                    params={"command": "rm old.log"},
                                    approved=False, session_id="ws-1",
                                    engine=type("E", (), {"noul": lambda *a, **k: _StubNoul(0.9)})())
        assert sub["name"] == "tool_approval:run_command"
        assert rows == [], "the caller must not wait for the score"
        sub["job"]()
    finally:
        ta.set_row_sink(None)
    assert rows and rows[0]["outside_label"] is False and rows[0]["chosen"] is True


def test_an_eval_session_answer_is_not_a_label(monkeypatch):
    """The eval runner grants every prompt; that is not the user's judgment."""
    import backend.utils.durability_queue as dq

    sub = {}
    monkeypatch.setattr(dq, "lane", lambda _n: _Lane(sub))
    before = ta.SKIPPED["eval_session"]
    ta.record_permission_answer(goal="x", tool_name="run_command", params={},
                                approved=True, session_id="eval-c13-abc123")
    assert sub == {} and ta.SKIPPED["eval_session"] == before + 1


def test_the_permission_answer_writes_the_row_with_the_request(monkeypatch):
    """note_request at turn entry -> the prompt carries the request -> the
    user's answer reaches record_permission_answer with it."""
    from backend.agent import permissions as perm

    seen = {}
    monkeypatch.setattr(ta, "record_permission_answer", lambda **kw: seen.update(kw))

    class _Bus:
        def emit(self, *a, **k):
            pass

    ps = perm.ToolPermissionSystem(event_bus=_Bus())
    ta.note_request("ws-7", "remove the temp folder")
    req = ps.request_permission(
        tool_name="delete_file", tier=perm.PermissionTier.DESTRUCTIVE,
        params={"path": "tmp/"}, session_id="ws-7", auto_approve=False)
    assert req.status == "pending" and req.goal == "remove the temp folder"
    ps.respond_to_permission(req.request_id, approved=False)
    assert seen["goal"] == "remove the temp folder"
    assert seen["tool_name"] == "delete_file" and seen["approved"] is False
    assert seen["session_id"] == "ws-7" and seen["params"] == {"path": "tmp/"}


def test_the_reliability_consult_is_gone():
    """The v1-v6 consult ran a d1 call on every tool result for a job nobody
    wanted; its guard decided nothing (never enforced)."""
    assert not hasattr(ta, "record_tool_approval")
    assert not hasattr(ta, "pre_call_guard")
    for rel in ("backend/agent/agent_kernel.py", "backend/agent/node_executor.py"):
        from backend.tests._kernel_source import kernel_source
        src = (kernel_source(encoding="utf-8", errors="replace") if rel == "backend/agent/agent_kernel.py"
               else (_ROOT / rel).read_text(encoding="utf-8", errors="replace"))
        assert "record_tool_approval" not in src and "pre_call_guard" not in src, rel
