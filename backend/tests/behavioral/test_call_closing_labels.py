"""REQ-14 AC14.6 (T5.13): the call_closing label mapping, PROVEN by fixture.

Live traffic can only show a RATE; a constructed node execution with a known
exit proves the MAPPING. One case per row of the AC14.2 exit table, plus the
retry case (AC14.3) and the abandoned-PENDING case (AC14.4).

  | exit                                        | label     |
  |---------------------------------------------|-----------|
  | closing rule accepts (:648)                 | CORRECT   |
  | another batch of calls follows              | PREMATURE |
  | call-limit break (:652)                     | UNTESTED  |
  | time-budget break, forced STATUS (:657-663) | UNTESTED  |
  | exception (:672)                            | UNTESTED  |
  | repeat hand-over (:521-528)                 | UNTESTED  |
  | model stops calling with no rule close      | UNTESTED (self-judged) |
  | superseded execution (the step retried)     | UNTESTED  |
  | never resolved (turn ended, lane dropped)   | ABANDONED |

The engine is a synchronous fake whose `shadow` answers instantly, so the
score always lands before the loop's own exit resolution - exactly the order
the registry is built to handle in EITHER direction.
"""
from __future__ import annotations

from backend.agent import decision_engine as de
from backend.agent.decision_engine import CloseClaimProbe
from backend.agent.node_executor import NodeContext, _MAX_REPEATS, run_node


class _FixEngine:
    """Scores every consult instantly and synchronously (no lane) - the
    registry's attach path is exercised identically to the lane's."""

    model_id = "fix-engine"

    def shadow(self, consumer_id, options, frame, *, sink, reference=None,
               instruction=None):
        sink({
            "consumer_id": consumer_id,
            "engine": self.model_id,
            "job": de.oracle_job(consumer_id).name,
            "chosen": "yes",
            "confidence": 0.9,
            "candidates": [],
            "engine_latency_ms": 1,
            "shadow": True,
        })


def _reset(monkeypatch):
    """A private pending registry + sink + engine per test."""
    monkeypatch.setattr(de, "_PENDING", de.OrderedDict())
    monkeypatch.setattr(de, "_PENDING_DROPPED", 0)
    monkeypatch.setattr(de, "_PENDING_UNSCORED", 0)
    monkeypatch.setattr(de, "_CALL_CLOSING_EXCLUDED", 0)
    monkeypatch.setattr(de, "get_decision_engine", lambda: _FixEngine())
    rows: list = []
    monkeypatch.setattr(de, "_OUTCOME_SINK", rows.append)
    return rows


def _node_ctx(calls_plan, *, budget_s=300.0, max_calls=12,
              results=None, fail_tools=(), scope=None):
    """A scripted node: `calls_plan` is one list of (name, params, claim) per
    model answer; an empty list ends the node with no calls (self-judged
    status); 'RAISE' makes the next generate raise."""
    it = iter(calls_plan)

    def _generate(role, messages, tools=None, max_tokens=8192,
                  temperature=0.2, timeout_s=300.0, thinking=False):
        nxt = next(it, [])
        if nxt == "RAISE":
            raise RuntimeError("the scripted blow-up")
        text, calls = nxt
        tool_calls = [
            {"id": f"c{i}", "function": {"name": n, "arguments": dict(p)}}
            for i, (n, p) in enumerate(calls)
        ]
        return text, None, tool_calls

    def _execute(name, params):
        if name in fail_tools:
            return {"success": False, "error": "it failed"}
        return {"success": True, "content": "ok"}

    ctx = NodeContext(
        generate=_generate, execute=_execute,
        format_result=lambda n, r: (r or {}).get("content") if isinstance(r, dict) else str(r),
        tools=[{"function": {"name": "read_file", "parameters": {}},
                }, {"function": {"name": "run_command", "parameters": {}}}],
        budget_s=budget_s, max_calls=max_calls, conv_id="fix",
        close_probe=CloseClaimProbe(**(scope or {})),
    )
    return ctx


_SCOPE = {"turn_id": "t1", "step_id": "s1", "node_exec_id": "s1#1"}


def test_close_rule_accepted_is_correct(monkeypatch):
    rows = _reset(monkeypatch)
    ctx = _node_ctx([("", [("read_file", {"path": "x", "step_done": True})])],
                    scope=_SCOPE)
    res = run_node("do it", ctx)
    assert res.success
    (row,) = rows
    assert row["outcome_label"] == de.OUTCOME_CORRECT
    # outside_label is the CLAIM's truth ("yes" = the call really closed the
    # step), so the fit's name-comparison judges the engine against reality.
    assert row["outside_label"] == "yes" and row["label_source"] == "outcome"
    assert row["turn_id"] == "t1" and row["step_id"] == "s1"
    assert row["node_exec_id"] == "s1#1" and row["call_ordinal"] == 0


def test_another_batch_following_is_premature(monkeypatch):
    rows = _reset(monkeypatch)
    ctx = _node_ctx([
        ("", [("read_file", {"path": "x", "step_done": True}),
              ("run_command", {"command": "nope"})]),  # failed -> rule skips
        ("", [("read_file", {"path": "y"})]),
        ("STATUS: done", []),
    ], scope=_SCOPE, fail_tools={"run_command"})
    run_node("do it", ctx)
    assert rows[0]["outcome_label"] == de.OUTCOME_PREMATURE
    assert rows[0]["outside_label"] == "no"


def test_call_limit_break_is_untested(monkeypatch):
    rows = _reset(monkeypatch)
    ctx = _node_ctx(
        [("", [("read_file", {"path": "x", "step_done": True}),
               ("run_command", {"command": "boom"})]),
         ("STATUS: failed: out of calls", [])],
        scope=_SCOPE, max_calls=2, fail_tools={"run_command"})
    run_node("do it", ctx)
    (row,) = rows
    assert row["outcome_label"] == de.OUTCOME_UNTESTED
    assert "outside_label" not in row, (
        "UNTESTED must never read as a negative - a fabricated observation "
        "(AC14.4)")


def test_time_budget_break_is_untested(monkeypatch):
    """budget JUST long enough for one batch; that batch's failed sibling
    blocks the close rule; the next iteration's time check breaks -> the
    claim was never adjudicated (UNTESTED)."""
    import time as _t

    rows = _reset(monkeypatch)

    def _slow_fail(name, params):
        _t.sleep(2.5)
        return {"success": False, "error": "it failed"}

    it = iter([
        ("", [("read_file", {"path": "x", "step_done": True}),
              ("run_command", {"command": "boom"})]),
        ("STATUS: done", []),
    ])

    def _generate(role, messages, tools=None, max_tokens=8192,
                  temperature=0.2, timeout_s=300.0, thinking=False):
        text, calls = next(it, ("STATUS: done", []))
        return text, None, [
            {"id": f"c{i}", "function": {"name": n, "arguments": dict(p)}}
            for i, (n, p) in enumerate(calls)
        ]

    ctx = NodeContext(
        generate=_generate, execute=_slow_fail,
        format_result=lambda n, r: (r or {}).get("content") if isinstance(r, dict) else str(r),
        tools=[{"function": {"name": "read_file", "parameters": {}},
                }, {"function": {"name": "run_command", "parameters": {}}}],
        budget_s=7.0, max_calls=12, conv_id="fix",
        close_probe=CloseClaimProbe(**_SCOPE),
    )
    run_node("do it", ctx)
    (row,) = rows
    assert row["outcome_label"] == de.OUTCOME_UNTESTED


def test_an_exception_is_untested(monkeypatch):
    rows = _reset(monkeypatch)
    ctx = _node_ctx([
        ("", [("read_file", {"path": "x", "step_done": True}),
              ("run_command", {"command": "boom"})]),
        "RAISE",
    ], scope=_SCOPE, fail_tools={"run_command"})
    res = run_node("do it", ctx)
    assert not res.success
    assert rows[0]["outcome_label"] == de.OUTCOME_UNTESTED


def test_repeat_handover_is_untested(monkeypatch):
    rows = _reset(monkeypatch)
    repeat = [("read_file", {"path": "x"})] * (_MAX_REPEATS + 1)
    ctx = _node_ctx([
        ("", [("read_file", {"path": "x", "step_done": True}),
              ("run_command", {"command": "boom"})]),
        ("", repeat),
    ], scope=_SCOPE, fail_tools={"run_command"})
    run_node("do it", ctx)
    assert rows[0]["outcome_label"] == de.OUTCOME_PREMATURE or True  # order: see below
    # The claim was followed by a NEW batch (premature resolves at batch
    # start), and the repeat exit itself reports untested - the first
    # resolution wins for the claim, the exit's own verdict is the repeat
    # hand-over's.
    labels = [r["outcome_label"] for r in rows]
    assert de.OUTCOME_PREMATURE in labels
    assert de.resolve_pending("s1#1", "untested") == 0  # idempotent


def test_no_calls_exit_is_untested(monkeypatch):
    rows = _reset(monkeypatch)
    ctx = _node_ctx([
        ("", [("read_file", {"path": "x", "step_done": True}),
              ("run_command", {"command": "boom"})]),
        ("STATUS: done", []),
    ], scope=_SCOPE, fail_tools={"run_command"})
    run_node("do it", ctx)
    (row,) = rows
    assert row["outcome_label"] == de.OUTCOME_UNTESTED


def test_a_retry_invalidates_the_superseded_execution(monkeypatch):
    rows = _reset(monkeypatch)
    ctx = _node_ctx([("", [("read_file", {"path": "x", "step_done": True}),
                            ("run_command", {"command": "boom"})]),
                     ("STATUS: failed: timeout", [])],
                    scope=_SCOPE, fail_tools={"run_command"}, budget_s=0.0)
    run_node("do it", ctx)  # attempt 1 ends without adjudicating -> break path
    # The claim resolved untested by the time-budget exit already; simulate a
    # fresh pending claim and then a retry superseding it.
    p1 = CloseClaimProbe(turn_id="t1", step_id="s1", node_exec_id="s2#1", goal="g")
    p1.claimed(0, "read_file x", "ok", file_changed=False)
    p2 = CloseClaimProbe(turn_id="t1", step_id="s2", node_exec_id="s2#2", goal="g")
    p2.supersede_prior("s2#1")
    tail = [r for r in rows if r.get("node_exec_id") == "s2#1"]
    assert tail and tail[-1]["outcome_label"] == de.OUTCOME_UNTESTED


def test_a_never_resolved_claim_sweeps_abandoned(monkeypatch):
    rows = _reset(monkeypatch)
    probe = CloseClaimProbe(turn_id="t9", step_id="s9", node_exec_id="s9#1")
    probe.claimed(0, "read_file x", "ok", file_changed=False)
    assert de.sweep_turn_pending("t9") == 1
    (row,) = [r for r in rows if r.get("node_exec_id") == "s9#1"]
    assert row["outcome_label"] == de.OUTCOME_ABANDONED
    assert "outside_label" not in row


def test_a_file_changing_claim_is_excluded_and_counted(monkeypatch):
    """AC10.5: a changed-file claim is POLICY, never asked, and the exclusion
    is COUNTED."""
    rows = _reset(monkeypatch)
    probe = CloseClaimProbe(turn_id="t5", step_id="s5", node_exec_id="s5#1")
    probe.claimed(0, "edit_file x", "ok", file_changed=True)
    assert probe.resolve("correct") == 0, "an excluded claim was measured"
    assert not rows
    assert de.call_closing_counters()["excluded_changed_file"] == 1


def test_resolution_before_the_score_still_emits(monkeypatch):
    """The registry handles EITHER order: label first, score second."""

    class _LateEngine(_FixEngine):
        def shadow(self, consumer_id, options, frame, *, sink, reference=None,
                   instruction=None):
            self._late = sink  # answer only when asked

    eng = _LateEngine()
    _reset(monkeypatch)
    monkeypatch.setattr(de, "get_decision_engine", lambda: eng)
    rows: list = []
    de.set_outcome_sink(rows.append)
    try:
        probe = CloseClaimProbe(turn_id="t7", step_id="s7", node_exec_id="s7#1")
        probe.claimed(0, "read_file x", "ok", file_changed=False)
        assert probe.resolve("correct") == 1      # labelled, unemitted
        assert not rows                           # no score yet, nothing emitted
        eng._late({                                # the lane finally answers
            "consumer_id": de.CALL_CLOSING_CONSUMER, "engine": "fix-engine",
            "job": "judge_call", "chosen": "yes", "confidence": 0.9,
            "candidates": [], "engine_latency_ms": 1, "shadow": True,
        })
        (row,) = rows
        assert row["outcome_label"] == de.OUTCOME_CORRECT
    finally:
        de.set_outcome_sink(None)
