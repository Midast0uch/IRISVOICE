"""tool_approval — the binary outcome-referenced approval consumer (2026-10-10).

Build spec: pin_1fb3ce63bb3b. The consumer asks "is this tool the right next
tool for this goal, given this result?" (a noul) and is labelled by the call's
OUTCOME (brain_bool = success), so the reference is GROUND TRUTH, not parity.

These guards pin the contract. Each FAILS on the pre-change code (no `approve`
job, no `tool_approval` declaration, no module): the import/KeyError is the
proof the guard is real.
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.agent import decision_engine as de
from backend.agent import tool_approval_shadow as ta


class _StubNoul:
    """The minimal Noul surface shadow_row reads."""

    def __init__(self, probability: float, latency_ms: int = 7) -> None:
        self.probability = probability
        self.engine_latency_ms = latency_ms

    def true(self, cut: float = 0.5) -> bool:
        return self.probability >= cut


# ── the job ────────────────────────────────────────────────────────────────


def test_approve_job_declares_the_pre_call_fields():
    """The `approve` job carries the PRE-CALL evidence only: goal, last_result,
    proposed_tool, tool_description, the call's ARGUMENTS and the offered tool
    list (the v2 additions — the evidence v1 lacked). The call's own result is
    NOT a field — it is the label, and a row whose input carries its answer
    measures nothing."""
    job = de.ORACLE_JOBS["approve"]
    # STALE-BY-SPEC update (2026-10-11, v3): `calls_this_step` added (the
    # step's own calls so far); still no post-call field.
    assert job.fields == (
        "goal", "calls_this_step", "last_result", "proposed_tool",
        "tool_description", "args", "offered_tools")
    assert job.budget_ids <= 384
    assert de.CONSUMER_JOBS["tool_approval"] == "approve"
    assert de.oracle_job("tool_approval").name == "approve"


def test_approve_job_renders_every_declared_field():
    """job_input renders all six declared fields (the frame/job mismatch rule:
    an undeclared key is silently dropped)."""
    state = de.job_input("tool_approval", {
        "goal": "fix the parser",
        "last_result": "read_file: 12 lines",
        "proposed_tool": "edit_file",
        "tool_description": "Edit a file's contents",
        "args": {"path": "parser.py", "old": "def run("},
        "offered_tools": ["read_file", "edit_file", "run_command"],
    })
    assert state.job == "approve"
    assert state.fields == de.ORACLE_JOBS["approve"].fields
    for needle in ("fix the parser", "read_file: 12 lines", "edit_file",
                   "Edit a file's contents", "parser.py", "run_command"):
        assert needle in state.text, f"declared field dropped: {needle}"


def test_approve_job_declares_no_reference_field():
    for f in de.ORACLE_JOBS["approve"].fields:
        assert not f.startswith("brain_") and f != "incumbent_route"


# ── the declaration ────────────────────────────────────────────────────────


def test_tool_approval_is_a_declared_noul():
    assert de.declared_type("tool_approval") == "noul"
    assert de.is_declared("tool_approval")
    crit = de.declared_criteria("tool_approval")
    assert isinstance(crit, dict) and "true" in crit and "false" in crit


def test_tool_approval_is_a_binary_consumer():
    """The report recomputes a binary consumer's confidence from `probability`;
    that set is read from the registered specs' ("yes","no") labels."""
    from backend.agent.oracle_calibration import binary_consumers

    assert "tool_approval" in binary_consumers()


# ── the row ────────────────────────────────────────────────────────────────


def test_row_carries_the_outcome_as_brain_bool():
    """The reference is the call's OUTCOME. `chosen` is a BOOL (the report's
    decision_label compares bool(chosen) == bool(brain_bool); a string "no"
    would read as True)."""
    row = ta.shadow_row(_StubNoul(0.9), brain_bool=True)
    assert row["consumer_id"] == "tool_approval"
    assert row["job"] == "approve"
    assert row["chosen"] is True
    assert row["brain_bool"] is True
    assert row["confidence"] == 0.9
    assert row["probability"] == 0.9
    assert row["shadow"] is True
    # STALE-BY-SPEC update (2026-10-11): the v3 frame is a new cohort.
    assert row["criteria_version"] == "tool_approval/v3"

    # A sure "no": confidence is in the CHOSEN answer, not P(true).
    no = ta.shadow_row(_StubNoul(0.05), brain_bool=False)
    assert no["chosen"] is False
    assert no["confidence"] == 0.95
    assert no["probability"] == 0.05


def test_no_row_without_a_noul():
    """A missing engine must never fabricate a shadow row."""
    assert ta.shadow_row(None, brain_bool=True) is None


# ── the consult ────────────────────────────────────────────────────────────


def test_consult_runs_on_the_oracle_shadow_lane(monkeypatch):
    """The consult is OFF the reply path: it submits to lane("oracle_shadow")
    and the row lands from there, never on the caller."""
    import backend.utils.durability_queue as dq

    submitted = {}

    class _FakeLane:
        def submit(self, name, job):
            submitted["name"] = name
            submitted["job"] = job
            return True

    monkeypatch.setattr(dq, "lane", lambda _n: _FakeLane())

    rows = []
    ta.set_row_sink(rows.append)
    try:
        ta.record_tool_approval(
            goal="fix the parser", last_result="read_file: 12 lines",
            proposed_tool="edit_file", tool_description="Edit a file",
            outcome_success=True,
        )
    finally:
        ta.set_row_sink(None)

    assert submitted.get("name") == "tool_approval:edit_file"
    assert callable(submitted.get("job"))
    assert rows == [], "the caller must not wait for the score"


def test_record_passes_auto_engine_by_default(monkeypatch):
    """`engine=None` means NO ENGINE (fail-safe); the default must be
    AUTO_ENGINE so a live consult adopts the process singleton. Measured live
    2026-10-10: a None default silently produced ZERO rows for a whole coding
    group while tool_choice (which resolves the engine itself) grew normally."""
    import backend.utils.durability_queue as dq

    captured = {}

    class _FakeLane:
        def submit(self, name, job):
            captured["job"] = job
            return True

    monkeypatch.setattr(dq, "lane", lambda _n: _FakeLane())

    def _fake_score(frame, *, engine=None):
        captured["engine"] = engine
        return _StubNoul(0.8)

    monkeypatch.setattr(ta, "score_tool_approval", _fake_score)
    ta.set_row_sink(lambda r: None)
    try:
        ta.record_tool_approval(
            goal="g", last_result=None, proposed_tool="edit_file",
            outcome_success=True,
        )
        captured["job"]()
    finally:
        ta.set_row_sink(None)
    assert captured["engine"] is ta.AUTO_ENGINE


def test_pre_call_frame_never_carries_the_call_result(monkeypatch):
    """The frame bound at submit time holds the PRE-CALL evidence only — the
    call's own result would leak the answer the row is measuring."""
    import backend.utils.durability_queue as dq

    captured = {}

    class _FakeLane:
        def submit(self, name, job):
            captured["job"] = job
            return True

    monkeypatch.setattr(dq, "lane", lambda _n: _FakeLane())

    seen = {}

    def _fake_score(frame, *, engine=None):
        seen.update(frame)
        return _StubNoul(0.8)

    monkeypatch.setattr(ta, "score_tool_approval", _fake_score)
    rows = []
    ta.set_row_sink(rows.append)
    try:
        ta.record_tool_approval(
            goal="fix the parser", last_result="read_file: 12 lines",
            proposed_tool="edit_file", tool_description="Edit a file",
            outcome_success=True,
        )
        captured["job"]()  # run the lane job
    finally:
        ta.set_row_sink(None)

    # STALE-BY-SPEC update (2026-10-11, v3): `calls_this_step` is PRE-CALL
    # evidence (the calls before this one); the call's own result stays out.
    assert set(seen) == {"goal", "calls_this_step", "last_result", "proposed_tool",
                         "tool_description", "args", "offered_tools"}
    assert "result" not in seen and "outcome" not in seen
    assert rows and rows[0]["brain_bool"] is True
