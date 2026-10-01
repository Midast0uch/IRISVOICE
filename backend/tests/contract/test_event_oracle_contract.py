"""Contract: the Oracle shadow consumers for events rules cannot type
(docs/Design/EVENT_TAXONOMY.md section 6, build step 3).

  * every user message -> exactly ONE `user_feedback` shadow row and, unless the label
    is `none`, exactly ONE memory_events row with the mapped label and label_source;
  * the previous assistant turn is in the frame (a correction is relative to it);
  * the answer path is not delayed by a blocked Oracle or Brain (the work is on lanes);
  * the Brain reference sample rate is honored, and a low-probability decision always
    gets the Brain;
  * a Layer-3 event (family NULL) gets an `event_family` (+ `event_type:<family>`)
    shadow row; a SAMPLED rule-labeled event gets rows whose reference is the rule's
    family/label, and its frame never shows the label;
  * the consumers are in the consumer registry and in the bar report.

STUBS (said plainly): the decision ENGINE and the Brain are fakes - the engine is not
under test. The lanes, the real emit_event writer, the real memory_events schema, the
real kernel entry point and the real report loader are NOT stubbed.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from backend.agent import event_oracle as eo
from backend.agent.decision_backend_onnx import CONSUMER_TASKS, get_consumer_spec
from backend.agent.decision_engine import DecisionScore
from backend.memory import event_alphabet as ea
from backend.memory import memory_events as me
from backend.utils.durability_queue import lane


class _Engine:
    """Fake decision engine: per-consumer (chosen, confidence); records every call."""

    def __init__(self, answers=None, default_conf=0.9):
        self.answers = answers or {}
        self.default_conf = default_conf
        self.calls = []
        self.gate = None  # a threading.Event the decision waits on

    def decide(self, consumer_id, options, frame, instruction=None):
        self.calls.append((consumer_id, list(options), frame.get("goal", "")))
        if self.gate is not None:
            assert self.gate.wait(10), "test gate never released"
        chosen, conf = self.answers.get(consumer_id, (options[0], self.default_conf))
        return DecisionScore(consumer_id=consumer_id, chosen=chosen, confidence=conf,
                             distribution=(), engine_latency_ms=1)

    def by(self, consumer_id):
        return [c for c in self.calls if c[0] == consumer_id]


class _Brain:
    def __init__(self, reply="none"):
        self.reply = reply
        self.prompts = []
        self.gate = None

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.gate is not None:
            assert self.gate.wait(10), "test gate never released"
        return self.reply


def _settle():
    """Drain both lanes in dependency order (event_oracle jobs hand writes and passes to
    memory_events, which hands scoring back to event_oracle)."""
    for _ in range(2):
        assert lane("event_oracle").flush(10.0)
        assert lane("memory_events").flush(10.0)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    saved = dict(CONSUMER_TASKS)
    monkeypatch.setenv(eo.BRAIN_RATE_ENV, "0")
    monkeypatch.setenv(eo.RULE_SAMPLE_ENV, "0")
    monkeypatch.setattr(eo, "_GATES", {})
    monkeypatch.setattr(eo, "_PASS_STATE", {"watermark": 0.0, "last_pass": 0.0})
    # The chain append (Immortus FFI) is not under test: a no-op keeps the run local.
    monkeypatch.setattr(me, "_append_event", lambda *a, **k: None)
    rows = []
    eo.set_row_sink(rows.append)
    yield rows
    eo.set_row_sink(None)
    monkeypatch.setattr(eo, "ENGINE", eo.AUTO_ENGINE)
    CONSUMER_TASKS.clear()
    CONSUMER_TASKS.update(saved)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    me.ensure_schema(c)
    yield c
    c.close()


def _owner(conn, brain=None, assistant="The capital of Australia is Sydney."):
    msgs = [SimpleNamespace(role="user", content="capital of australia?"),
            SimpleNamespace(role="assistant", content=assistant)]
    owner = SimpleNamespace(
        _conversation_memory=SimpleNamespace(messages=msgs),
        _memory_interface=SimpleNamespace(_mycelium=SimpleNamespace(conn=conn)),
    )
    if brain is not None:
        owner.infer = lambda prompt, role="x", max_tokens=1, temperature=0.0: SimpleNamespace(
            raw_text=brain(prompt))
    return owner


def _events(conn):
    cur = conn.execute("SELECT family, label, label_source, label_confidence, evidence, "
                       "thread_id, episode_id, payload FROM memory_events ORDER BY ts")
    return [dict(zip(("family", "label", "label_source", "label_confidence", "evidence",
                      "thread_id", "episode_id", "payload"), r)) for r in cur.fetchall()]


# ── 1. user_feedback ───────────────────────────────────────────────────────

def test_a_user_message_makes_one_shadow_row_and_one_event(conn, _isolated, monkeypatch):
    engine = _Engine({"user_feedback": ("correction", 0.91)})
    monkeypatch.setattr(eo, "ENGINE", engine)
    assert eo.observe_user_message(_owner(conn), "no, it is Canberra", thread_id="t-1", turn_id="turn-1")
    _settle()

    assert len(_isolated) == 1
    row = _isolated[0]
    assert row["consumer_id"] == "user_feedback" and row["chosen"] == "correction"
    assert row["shadow"] is True and row["confidence"] == 0.91
    assert "brain_choice" not in row  # no sample, confident: no reference

    events = _events(conn)
    assert len(events) == 1
    ev = events[0]
    assert (ev["family"], ev["label"]) == ("feedback", "CORRECTION")
    assert ev["label_source"] == "oracle" and ev["label_confidence"] == 0.91
    assert ev["evidence"] == "user" and ev["thread_id"] == "t-1" and ev["episode_id"] == "turn-1"
    # references, never content (S12): the message text is not stored
    assert "Canberra" not in (ev["payload"] or "")


@pytest.mark.parametrize("option,label,family", [
    ("confirmation", "CONFIRMATION", "feedback"),
    ("correction", "CORRECTION", "feedback"),
    ("preference", "PREFERENCE_STATED", "intent"),
    ("refinement", "GOAL_REFINED", "intent"),
    ("new_request", "GOAL_SET", "intent"),
])
def test_each_option_maps_to_its_registered_label(conn, monkeypatch, option, label, family):
    monkeypatch.setattr(eo, "ENGINE", _Engine({"user_feedback": (option, 0.9)}))
    eo.observe_user_message(_owner(conn), "text", thread_id="t")
    _settle()
    ev = _events(conn)
    assert [(e["family"], e["label"]) for e in ev] == [(family, label)]


def test_none_writes_a_shadow_row_but_no_event(conn, _isolated, monkeypatch):
    monkeypatch.setattr(eo, "ENGINE", _Engine({"user_feedback": ("none", 0.95)}))
    eo.observe_user_message(_owner(conn), "thanks", thread_id="t")
    _settle()
    assert len(_isolated) == 1 and _isolated[0]["chosen"] == "none"
    assert _events(conn) == []


def test_the_previous_assistant_turn_is_in_the_frame(conn, monkeypatch):
    engine = _Engine()
    monkeypatch.setattr(eo, "ENGINE", engine)
    eo.observe_user_message(_owner(conn, assistant="The capital of Australia is Sydney."),
                            "that is wrong", thread_id="t")
    _settle()
    (_cid, options, goal), = engine.by("user_feedback")
    assert options == list(eo.USER_OPTIONS)
    assert "The capital of Australia is Sydney." in goal and "that is wrong" in goal


def test_the_previous_assistant_turn_is_bounded():
    long = "A" * 1000 + "MIDDLE" + "Z" * 1000
    owner = SimpleNamespace(_conversation_memory=SimpleNamespace(
        messages=[SimpleNamespace(role="assistant", content=long)]))
    prev = eo.last_assistant_text(owner)
    assert len(prev) < 500 and prev.startswith("AAA") and prev.endswith("ZZZ") and "MIDDLE" not in prev


def test_a_brain_label_is_the_reference_and_the_event_source(conn, _isolated, monkeypatch):
    monkeypatch.setenv(eo.BRAIN_RATE_ENV, "1")
    monkeypatch.setattr(eo, "ENGINE", _Engine({"user_feedback": ("confirmation", 0.9)}))
    brain = _Brain("preference")
    eo.observe_user_message(_owner(conn, brain=brain), "always use metric", thread_id="t")
    _settle()
    assert len(brain.prompts) == 1 and "always use metric" in brain.prompts[0]
    assert _isolated[0]["chosen"] == "confirmation" and _isolated[0]["brain_choice"] == "preference"
    (ev,) = _events(conn)
    assert (ev["label"], ev["label_source"]) == ("PREFERENCE_STATED", "brain")


def test_the_oracle_row_is_written_even_when_the_brain_disagrees_or_fails(conn, _isolated, monkeypatch):
    """The Brain answers nothing usable: the Oracle label stands, its row has no reference."""
    monkeypatch.setenv(eo.BRAIN_RATE_ENV, "1")
    monkeypatch.setattr(eo, "ENGINE", _Engine({"user_feedback": ("correction", 0.9)}))
    eo.observe_user_message(_owner(conn, brain=_Brain("hmm, unclear")), "x", thread_id="t")
    _settle()
    assert len(_isolated) == 1 and "brain_choice" not in _isolated[0]
    assert [e["label_source"] for e in _events(conn)] == ["oracle"]


def test_no_engine_means_no_row_and_the_brain_may_still_label(conn, _isolated, monkeypatch):
    monkeypatch.setattr(eo, "ENGINE", None)
    eo.observe_user_message(_owner(conn, brain=_Brain("correction")), "wrong", thread_id="t")
    _settle()
    assert _isolated == []  # a missing engine never fabricates a row
    (ev,) = _events(conn)
    assert (ev["label"], ev["label_source"]) == ("CORRECTION", "brain")


# ── 2. the answer path is not delayed ──────────────────────────────────────

def test_a_blocked_oracle_does_not_delay_the_hook(conn, monkeypatch):
    engine = _Engine()
    engine.gate = threading.Event()
    monkeypatch.setattr(eo, "ENGINE", engine)
    try:
        t0 = time.perf_counter()
        assert eo.observe_user_message(_owner(conn), "hello", thread_id="t")
        assert time.perf_counter() - t0 < 0.5, "the hook waited on the Oracle"
    finally:
        engine.gate.set()
    _settle()


def test_a_blocked_brain_does_not_delay_the_hook(conn, monkeypatch):
    monkeypatch.setenv(eo.BRAIN_RATE_ENV, "1")
    monkeypatch.setattr(eo, "ENGINE", _Engine())
    brain = _Brain("none")
    brain.gate = threading.Event()
    try:
        t0 = time.perf_counter()
        assert eo.observe_user_message(_owner(conn, brain=brain), "hello", thread_id="t")
        assert time.perf_counter() - t0 < 0.5, "the hook waited on the Brain"
    finally:
        brain.gate.set()
    _settle()


def test_the_real_kernel_entry_point_returns_while_the_oracle_is_blocked(conn, _isolated, monkeypatch):
    """The real AgentKernel.process_text_message, on a kernel that is unavailable (so the
    turn returns at once): the user message still gets its shadow decision, on the lane,
    and a blocked Oracle does not hold the call. Text and voice share this one entry."""
    from backend.agent.agent_kernel import AgentKernel

    engine = _Engine({"user_feedback": ("refinement", 0.9)})
    engine.gate = threading.Event()
    monkeypatch.setattr(eo, "ENGINE", engine)
    kernel = object.__new__(AgentKernel)
    kernel._initialization_error = "stand-in"
    kernel._memory_interface = SimpleNamespace(_mycelium=SimpleNamespace(conn=conn))
    kernel._conversation_memory = None
    kernel.session_id = "s-1"
    try:
        t0 = time.perf_counter()
        out = kernel.process_text_message("make it Friday", session_id="s-1",
                                          conversation_id="conv-1", from_voice=True)
        assert "not available" in out
        assert time.perf_counter() - t0 < 2.0, "the turn waited on the Oracle"
        assert _isolated == []  # still blocked: nothing happened on the answer path
    finally:
        engine.gate.set()
    _settle()
    assert [r["consumer_id"] for r in _isolated] == ["user_feedback"]
    (ev,) = _events(conn)
    assert (ev["label"], ev["thread_id"]) == ("GOAL_REFINED", "conv-1")
    assert json.loads(ev["payload"])["from_voice"] is True


def test_the_kernel_installs_the_shadow_row_sink_for_these_consumers():
    """A text pin on the wiring: the sink install sits next to the other shadow
    consumers. (A constructed kernel is too heavy to build in a contract test.)"""
    import inspect

    from backend.agent.agent_kernel import AgentKernel

    src = inspect.getsource(AgentKernel._initialize_components)
    assert "event_oracle as _eo_rows" in src and "_eo_rows.set_row_sink(_shadow_sink)" in src


# ── 3. the Brain sample rate ───────────────────────────────────────────────

def _run(n, brain, engine, monkeypatch):
    monkeypatch.setattr(eo, "ENGINE", engine)
    for i in range(n):
        eo.run_user_feedback(f"message {i}", "previous", brain=brain)


def test_the_default_brain_rate_is_one_in_three(monkeypatch):
    monkeypatch.delenv(eo.BRAIN_RATE_ENV, raising=False)
    brain = _Brain("none")
    _run(30, brain, _Engine(default_conf=0.9), monkeypatch)
    assert len(brain.prompts) == 10


@pytest.mark.parametrize("rate,expected", [("0", 0), ("1", 12), ("0.5", 6), ("0.25", 3)])
def test_the_brain_rate_is_configurable_and_honored(monkeypatch, rate, expected):
    monkeypatch.setenv(eo.BRAIN_RATE_ENV, rate)
    brain = _Brain("none")
    _run(12, brain, _Engine(default_conf=0.9), monkeypatch)
    assert len(brain.prompts) == expected


def test_a_low_probability_decision_always_gets_the_brain(monkeypatch):
    brain = _Brain("none")
    _run(9, brain, _Engine(default_conf=0.3), monkeypatch)  # rate 0: only the low-p rule fires
    assert len(brain.prompts) == 9


# ── 4. Layer-3 events and calibration samples ──────────────────────────────

def _layer3(conn):
    return me.emit_event(conn, label="MYSTERY_SIGNAL", evidence="none", thread_id="t",
                         trigger="wall", action_signature="browser_open:https://x.test", chain=False)


def test_a_layer3_event_gets_an_event_family_shadow_row(conn, _isolated, monkeypatch):
    engine = _Engine({"event_family": ("environment", 0.8)})
    monkeypatch.setattr(eo, "ENGINE", engine)
    assert _layer3(conn)
    assert ea.unknown_event_counts().get("MYSTERY_SIGNAL")
    assert eo.schedule_pass(conn, None, force=True)
    _settle()
    fam = [r for r in _isolated if r["consumer_id"] == "event_family"]
    assert len(fam) == 1 and fam[0]["chosen"] == "environment" and fam[0]["shadow"] is True
    # the second stage runs on the family the Oracle picked, over that family's labels
    (_c, options, _g), = engine.by("event_type:environment")
    assert options == [n for n, s in ea.registered_labels().items() if s.family == "environment"]


def test_a_layer3_brain_sample_is_the_reference(conn, _isolated, monkeypatch):
    monkeypatch.setenv(eo.BRAIN_RATE_ENV, "1")
    monkeypatch.setattr(eo, "ENGINE", _Engine({"event_family": ("environment", 0.8),
                                               "event_type:safety": ("PERMISSION_DENIED", 0.7)}))
    _layer3(conn)
    eo.schedule_pass(conn, _Brain("safety"), force=True)
    _settle()
    by = {r["consumer_id"]: r for r in _isolated}
    assert by["event_family"]["brain_choice"] == "safety"
    assert "event_type:safety" in by  # the label stage follows the Brain's family


def test_a_sampled_rule_event_is_a_free_exact_calibration_row(conn, _isolated, monkeypatch):
    monkeypatch.setenv(eo.RULE_SAMPLE_ENV, "1")
    engine = _Engine({"event_family": ("problem", 0.9), "event_type:problem": ("FIX", 0.6)})
    monkeypatch.setattr(eo, "ENGINE", engine)
    me.emit_event(conn, label="BUG", evidence="none", thread_id="t", trigger="wall", chain=False)
    brain = _Brain("none")
    eo.schedule_pass(conn, brain, force=True)
    _settle()
    by = {r["consumer_id"]: r for r in _isolated}
    assert by["event_family"]["brain_choice"] == "problem"          # the rule's family
    assert by["event_type:problem"]["brain_choice"] == "BUG"        # the rule's label
    assert by["event_type:problem"]["chosen"] == "FIX"              # the Oracle can disagree
    assert brain.prompts == []                                      # the rule is the reference
    # calibration honesty: the label (and what the registry derives from it) is hidden
    for _cid, _opts, goal in engine.calls:
        assert "BUG" not in goal and "sets_back" not in goal


def test_an_unsampled_rule_event_and_an_oracle_event_are_not_rescored(conn, _isolated, monkeypatch):
    monkeypatch.setattr(eo, "ENGINE", _Engine())  # RULE_SAMPLE 0 from the fixture
    me.emit_event(conn, label="BUG", evidence="none", thread_id="t", chain=False)
    me.emit_event(conn, label="CORRECTION", evidence="user", thread_id="t",
                  label_source="oracle", label_confidence=0.8, chain=False)
    eo.schedule_pass(conn, None, force=True)
    _settle()
    assert [r for r in _isolated if r["consumer_id"].startswith("event_")] == []


def test_a_pass_does_not_rescore_events_it_has_seen(conn, _isolated, monkeypatch):
    monkeypatch.setattr(eo, "ENGINE", _Engine())
    _layer3(conn)
    eo.schedule_pass(conn, None, force=True)
    _settle()
    n = len(_isolated)
    assert n >= 1
    eo.schedule_pass(conn, None, force=True)
    _settle()
    assert len(_isolated) == n


def test_the_pass_is_throttled(conn):
    assert eo.schedule_pass(conn, None) is True
    assert eo.schedule_pass(conn, None) is False
    _settle()


# ── 5. registry and bar report ─────────────────────────────────────────────

def test_the_family_menu_is_the_closed_alphabet():
    assert set(eo.FAMILY_ORDER) == set(ea.FAMILIES) and len(eo.FAMILY_ORDER) == len(ea.FAMILIES)
    assert set(eo.USER_LABELS.values()) <= set(ea.registered_labels())


def test_the_consumers_are_in_the_consumer_registry():
    ids = eo.register_consumers()
    assert eo.USER_FEEDBACK in ids and eo.EVENT_FAMILY in ids
    assert {f"event_type:{f}" for f in ea.FAMILIES} <= set(ids)
    assert get_consumer_spec("user_feedback").labels == eo.USER_OPTIONS
    assert set(get_consumer_spec("event_family").labels) == set(ea.FAMILIES)
    for fam in ea.FAMILIES:
        assert list(get_consumer_spec(f"event_type:{fam}").labels) == eo.family_labels(fam)
    spec = get_consumer_spec("user_feedback")
    eo.register_consumers()
    assert get_consumer_spec("user_feedback") is spec  # idempotent


def test_a_new_label_in_a_family_refreshes_that_families_menu():
    eo.register_consumers()
    before = get_consumer_spec("event_type:environment").labels
    ea.register_event_label("TEST_ONLY_ENV_LABEL", "environment", "neutral", "world", "t")
    try:
        eo.register_consumers()
        assert get_consumer_spec("event_type:environment").labels == before + ("TEST_ONLY_ENV_LABEL",)
    finally:
        ea._LABELS.pop("TEST_ONLY_ENV_LABEL", None)


def test_the_bar_report_lists_all_three_consumers(conn, tmp_path, monkeypatch):
    """Rows travel the real kernel sink (`_shadow_row_sink`) into a ledger shaped like
    system_events, then the real report loader and report builder read them."""
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.tool_bridge import _DECISION_META_KEYS
    from scripts.consumer_enforcement_report import build_report, load_rows, measure

    ledger = []
    bridge = SimpleNamespace(record_decision=lambda meta, route, session_id="": ledger.append(meta))
    kernel = object.__new__(AgentKernel)
    kernel._tool_bridge = bridge
    kernel.session_id = "s"
    eo.set_row_sink(kernel._shadow_row_sink)

    monkeypatch.setenv(eo.BRAIN_RATE_ENV, "1")
    monkeypatch.setenv(eo.RULE_SAMPLE_ENV, "1")
    monkeypatch.setattr(eo, "ENGINE", _Engine({"user_feedback": ("correction", 0.9),
                                               "event_family": ("problem", 0.9),
                                               "event_type:problem": ("BUG", 0.9)}))
    eo.observe_user_message(_owner(conn, brain=_Brain("correction")), "that is wrong", thread_id="t")
    # One writer per connection: production writes every event from the
    # memory_events lane. Writing from this thread while that lane still writes
    # was concurrent use of ONE sqlite connection ("bad parameter or other API
    # misuse" in combined runs) - settle first, then write.
    _settle()
    me.emit_event(conn, label="BUG", evidence="none", thread_id="t", chain=False)
    eo.schedule_pass(conn, None, force=True)
    _settle()
    # The pass hands scoring across two lanes; in a busy test process one more
    # hop can still be in flight after _settle. Wait (bounded) for the rows the
    # assertions below need - the contract is "eventually, on a lane".
    for _ in range(20):
        if {"event_family", "event_type:problem"} <= {m.get("consumer") for m in ledger}:
            break
        _settle()

    db = tmp_path / "ledger.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE system_events (event_type TEXT, outcome TEXT, interaction_payload TEXT)")
    for meta in ledger:
        kept = {k: v for k, v in meta.items() if k in _DECISION_META_KEYS or k == "route"}
        c.execute("INSERT INTO system_events VALUES (?,?,?)",
                  ("tool_execution", "success", json.dumps({"decision": kept})))
    c.commit()
    c.close()

    rows, skipped = load_rows(str(db))
    assert skipped["no_label"] == 0 and skipped["no_confidence"] == 0
    rep = build_report(measure(rows, {}), skipped, {"backend_id": "t", "candidate_cap": 6, "calibrated_cap": 6})
    assert {"user_feedback", "event_family", "event_type:problem"} <= set(rep["consumers"])
    assert rep["consumers"]["user_feedback"]["rows"] == 1
    assert rep["flipped"] == []  # shadow: nothing here is enforced
