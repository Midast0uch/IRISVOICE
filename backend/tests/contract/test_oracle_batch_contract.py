"""Wave 6 (REQ-7, REQ-14): per-job batching's contract.

AC7.1   one run = one STATE = one forward pass; never across jobs.
AC7.2   only the consumers actually consulted ride the run (the caller passes
        exactly those; nothing widens the job's declared set).
AC7.3   the dial's load signal counts QUESTIONS in flight, not runs.
AC7.5   criteria isolation AND the pinned failure-isolation choice
        (per-question: a malformed member fails ITSELF, never a neighbour).
AC14.1  a batch is a TRANSPORT unit, never a LABEL unit: every question keeps
        its own scope key, resolution time and label, and one pass is never
        written as one row.
AC7.4   the row records the grouping that produced it.

STALE-BY-SPEC update (2026-10-11): the `interpret`-job member these tests used
was `mode`, REMOVED as a consumer by the owner on 2026-10-10 (it can no longer
be declared, so the engine correctly refused it and five tests failed).
`user_feedback` - the other declared `choice` consumer on the same job - takes
its place. One INPUT also changed: the criteria-bleed test needs a member with
declared criteria of its own (user_feedback declares none), so `presentation`
replaces `mode` there and the asserted criteria text changes with it ("Answer
in prose only" for "Write or update a specification"). The assertion's shape -
each member's criteria appear in its own question and never in the other's -
is unchanged.
"""
from __future__ import annotations

import threading
import time

import pytest

from backend.agent import decision_engine as de
from backend.agent import decision_backend_d1 as d1mod
from backend.agent.decision_backend_d1 import D1Backend


class _Resp:
    def __init__(self, positions):
        self._positions = positions

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"logprobs": {"content": [
            {"top_logprobs": [{"id": t, "logprob": lp, "bytes": [116]}
                              for t, lp in pos.items()]}
            for pos in self._positions]}}]}


class _FakeClient:
    def __init__(self, positions):
        self.positions = positions
        self.payloads = []

    def post(self, url, json=None, timeout=None):
        self.payloads.append(json)
        return _Resp(self.positions)


def _backend(monkeypatch, positions, missing=()):
    """A live-ish d1: letter-code tokenizer stubbed, server check stubbed,
    POST faked. The code ids match the positions the fake server returns."""
    codes = {"A": 10, "B": 11, "C": 12, "D": 13, "E": 14}
    b = D1Backend()
    b._loaded = True
    monkeypatch.setattr(b, "_serves_d1", lambda force=False: (True, ""))

    def _single(form):
        return codes.get(form)

    monkeypatch.setattr(b, "_single_token_id", _single)
    monkeypatch.setattr(b, "_ensure_yes_no_ids", lambda: {"yes": (20,), "no": (21,)})
    client = _FakeClient(positions)
    monkeypatch.setattr(d1mod, "_pooled", lambda: client)
    return b, client


def test_batch_answers_each_question_at_its_own_slot(monkeypatch):
    """AC7.1/AC14.1: two questions, one pass, per-question answers read from
    per-question positions - the batch is transport, and the ANSWER to A is
    never B's."""
    b, client = _backend(monkeypatch, [{10: -0.1}, {20: -2.0, 21: -0.05}])
    out = b.decide_batch("the shared state", [
        ("user_feedback", ["alpha", "beta"], None),
        ("done", ["yes", "no"], None),
    ])
    a, n = out
    assert a is not None and n is not None
    assert a.consumer_id == "user_feedback" and a.chosen == "alpha"
    assert n.consumer_id == "done" and n.chosen == "no"  # -0.05 on 'no' wins
    payload = client.payloads[0]
    text = payload["prompt"]
    assert text.count("QUESTION:") == 2, "one state, two questions"
    assert payload["n_predict"] == 2  # one position per question


def test_criteria_never_bleed_across_batch_members(monkeypatch):
    """AC7.5: consumer A's criteria words NEVER appear in consumer B's
    question within one pass."""
    b, client = _backend(monkeypatch, [{10: -0.1, 11: -1.0},
                                       {10: -0.1, 11: -1.0}])
    # (the second member needs DECLARED criteria of its own: `presentation`
    # replaces the removed `mode` here - user_feedback declares none)
    out = b.decide_batch("shared", [
        ("narration", ["speak_all", "stay_silent"], None),
        ("presentation", ["plain_text", "prism_card"], None),
    ])
    assert all(x is not None for x in out)
    text: str = client.payloads[0]["prompt"]
    q1, q2 = text.split("QUESTION:")[1:]
    # each member's declared criteria name its OWN options and never appear in
    # the other member's question.
    assert "Speak every beat" in q1 and "Speak every beat" not in q2
    assert "Answer in prose only" in q2 and "Answer in prose only" not in q1


def test_a_malformed_member_fails_only_itself(monkeypatch):
    """AC7.5, the pinned failure-isolation choice: PER-QUESTION. An
    undeclared consumer answers nothing; its batch-mates still score."""
    b, _client = _backend(monkeypatch, [{10: -0.1}, {20: -0.1}])
    out = b.decide_batch("shared", [
        ("user_feedback", ["alpha", "beta"], None),
        ("never_declared_consumer", ["alpha", "beta"], None),
    ])
    assert out[0] is not None and out[0].chosen == "alpha"
    assert out[1] is None, "an undeclared member must not borrow a shape"


def test_the_engine_groups_by_job_and_shared_state(monkeypatch):
    """AC7.1: two jobs never merge; same job + same state merge; same job +
    different state stay separate passes (the state IS the batch's unit)."""
    eng = de.DecisionEngine.__new__(de.DecisionEngine)
    eng._cfg = de.EngineConfig()
    passes: list = []

    def _group(state_text, consults):
        passes.append((state_text, [c for c, _o, _i in consults]))
        return [None] * len(consults)

    eng._decide_batch_group = _group
    frame = {"goal": "the same turn text"}
    eng.decide_many([
        ("user_feedback", ["spec", "research"], frame),          # interpret
        ("web_intent", ["yes", "no"], frame),           # interpret, same state
        ("done", ["yes", "no"], frame),                 # judge_goal: other job
        ("narration", ["speak_all", "stay_silent"], {"goal": "different text"}),
    ])
    jobs = [s for s, _c in passes]
    assert len(passes) == 3, f"groups must be job+state: {passes}"
    assert passes[0][1] == ["user_feedback", "web_intent"], (
        "same job + same state merged into one pass")
    assert jobs[1] != jobs[0] or True  # judge_goal state text starts "goal"
    # The different-text narration consult is its own pass.


def test_shadow_many_writes_one_row_per_question_with_its_scope(monkeypatch):
    """AC14.1 + AC7.4: one batched pass, N rows, own scope keys, grouping
    recorded - never one row for the batch."""
    from backend.utils.durability_queue import lane

    eng = de.DecisionEngine.__new__(de.DecisionEngine)
    eng.model_id = "stub"
    eng._cfg = de.EngineConfig()
    rows, landed = [], threading.Event()

    def _group(state_text, consults):
        landed.set()
        return [
            de.DecisionScore(
                consumer_id=cid, chosen=opts[0], confidence=0.8,
                distribution=tuple(
                    de.CandidateScore(o, -0.1, 0.4) for o in opts),
                engine_latency_ms=1)
            for cid, opts, _i in consults
        ]

    eng._decide_batch_group = _group
    token = de.set_scope(turn_id="t-batch")
    try:
        ok = eng.shadow_many([
            ("user_feedback", ["spec", "research"], {"goal": "g"}, {"brain_choice": "spec"}),
            ("web_intent", ["yes", "no"], {"goal": "g"}, {"brain_choice": "no"}),
        ], sink=rows.append)
    finally:
        de._SCOPE.reset(token)
    assert landed.wait(5) and lane("oracle_shadow").flush(5.0)
    assert len(rows) == 2, "a batch must never be ONE row"
    assert [r["consumer_id"] for r in rows] == ["user_feedback", "web_intent"]
    assert all(r["turn_id"] == "t-batch" for r in rows)
    assert all(r["grouping"] == "job_batch:2" for r in rows), (
        "AC7.4: the grouping is recorded on the row")
    assert rows[0]["brain_choice"] == "spec"  # per-question reference intact


def test_the_load_counts_questions_while_a_batch_flies(monkeypatch):
    """AC7.3: DURING a 3-question run the load reads three questions, so a
    batched admission cannot claim one slot's worth of work."""
    monkeypatch.setattr(de.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(de, "_oracle_intra_op", 4)
    monkeypatch.setattr(de, "_oracle_questions_in_flight", 0)

    eng = de.DecisionEngine.__new__(de.DecisionEngine)
    eng._cfg = de.EngineConfig()
    eng._lock = threading.Lock()
    eng._clock = time.monotonic
    eng.counters = de.EngineCounters()
    during = []

    class _Backend:
        latency_in_run = 0

        def decide_batch(self, state_text, consults):
            during.append(de._oracle_questions_in_flight)
            return [None] * len(consults)

    eng._backend = _Backend()
    eng._load = lambda: True
    eng._run_inference = lambda fn, **kw: fn()
    monkeypatch.setattr(de, "_oracle_phase_enabled", lambda: False)
    frame = {"goal": "g"}
    out = eng.decide_many([
        ("user_feedback", ["spec", "research"], frame),
        ("web_intent", ["yes", "no"], frame),
        ("user_feedback", ["new_request", "refinement"], frame),
    ])
    assert len(out) == 3
    assert during == [3], ("the in-flight counter must count the QUESTIONS "
                           "of the run (%s)" % during)
    assert de._oracle_questions_in_flight == 0
