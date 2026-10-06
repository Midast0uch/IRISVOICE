"""Oracle Stage B (2026-10-05): ONE chokepoint decides whether a consumer may decide.

THE CONTRACT
  * `decision_engine.decides(consumer)` returns the calibrated threshold only when
    ALL four hold: the owner switched the consumer on (IRIS_DECISION_ENFORCE,
    DEFAULT EMPTY), its bar record says `enforced` on the active engine, a
    threshold was fitted for it on that engine, and the configuration is not
    stale. `enforced_consumers()` is the INTERSECTION, never a union.
  * Every deciding site asks it. With the default configuration NOTHING decides.
  * A consumer that does not decide keeps its rule / Brain answer AND its Oracle
    score runs OFF the reply path (the oracle_shadow lane), never on the calling
    thread. One that decides and is confident ACTS; below its calibrated
    threshold the existing path decides.

HOW THE FIXTURES WORK
  Every test points the bar record and the calibration file at tmp files (never
  the real ones) and fakes the engine identity, so the REAL chokepoint runs. The
  fixture touches only names that exist on the old code (env, BAR_PATH,
  CALIBRATION_PATH, `_current_backend_identity`) so a site test fails on the old
  code for the BEHAVIOUR it pins, not because a symbol is missing.

  The calibration map is the identity on [0.5, 1.0] (calibrated == raw), so a
  threshold of 0.70 admits a confidence of 0.75 and a threshold of 0.95 refuses
  0.85. 0.75 sits BELOW the old private taus (web_intent 0.8, depth_met 0.8) and
  0.85 sits ABOVE them: the pair separates "chokepoint decides" from "old code
  decided".
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import types
from types import SimpleNamespace

import pytest

from backend.agent import consumer_bar as cb
from backend.agent import decision_engine as de
from backend.agent import explorer
from backend.agent import monitor_shadow as ms
from backend.agent import oracle_calibration as oc
from backend.agent import surface_shadow as ss
from backend.agent import tool_decision
from backend.agent.decision_backend_onnx import CONSUMER_TASKS
from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
    Noul,
)
from backend.utils.durability_queue import lane

BACKEND = "test-engine-int8"
_KNOTS = [[0.5, 0.5], [1.0, 1.0]]


def _flush() -> None:
    assert lane("oracle_shadow").flush(10.0), "the oracle_shadow lane did not drain"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


class _Chokepoint:
    """Builds the four keys in tmp files. Default state: nothing decides."""

    def __init__(self, monkeypatch, tmp_path):
        self._mp = monkeypatch
        self._tmp = tmp_path
        self.asked: list = []
        self.stale = False
        monkeypatch.delenv("IRIS_DECISION_ENFORCE", raising=False)
        monkeypatch.setattr(de, "_current_backend_identity", lambda: BACKEND)
        monkeypatch.setattr(de, "_config_stale", lambda: self.stale, raising=False)
        monkeypatch.setattr(de, "_ENFORCEMENT_LOGGED", False, raising=False)
        self._write([], [], 0.70, BACKEND)
        # Spy on the chokepoint (wraps the real one; sites import it per call).
        real = getattr(de, "decides", None)
        if real is not None:
            def _spy(consumer_id):
                self.asked.append(consumer_id)
                return real(consumer_id)
            monkeypatch.setattr(de, "decides", _spy)

    def _write(self, earned, fitted, threshold, record_engine):
        bar = {
            c: {"consumer_id": c, "rows": 120, "precision": 0.95, "ece": 0.01,
                "status": "enforced", "gap": "",
                "config": {"backend_id": record_engine}}
            for c in earned
        }
        bar_path = self._tmp / "consumer_bar_record.json"
        bar_path.write_text(json.dumps(bar), encoding="utf-8")
        cal = {BACKEND: {c: {"knots": _KNOTS, "threshold": threshold} for c in fitted}}
        cal_path = self._tmp / "oracle_calibration.json"
        cal_path.write_text(json.dumps(cal), encoding="utf-8")
        self._mp.setattr(cb, "BAR_PATH", bar_path)
        self._mp.setattr(oc, "CALIBRATION_PATH", cal_path)
        oc._CACHE.clear()

    def enable(self, consumers, *, threshold=0.70, allow=None, earned=None,
               fitted=None, record_engine=BACKEND):
        """Switch consumers on; `allow`/`earned`/`fitted` default to all of them
        so a test can withhold exactly ONE key."""
        consumers = list(consumers)
        allow = consumers if allow is None else allow
        self._mp.setenv("IRIS_DECISION_ENFORCE", ",".join(allow))
        self._write(
            consumers if earned is None else earned,
            consumers if fitted is None else fitted,
            threshold, record_engine,
        )


@pytest.fixture(autouse=True)
def chokepoint(monkeypatch, tmp_path):
    cp = _Chokepoint(monkeypatch, tmp_path)
    yield cp
    _flush()


class _Eng:
    """Stand-in Oracle: records the thread of every scoring call."""

    model_id = BACKEND

    def __init__(self, p=0.75, chosen=None):
        self.p = p
        self.chosen = chosen
        self.calls: list = []
        self.counters = EngineCounters()
        # the REAL shadow() (lane + row), bound to this stand-in
        self.shadow = types.MethodType(de.DecisionEngine.shadow, self)

    def _note(self, consumer_id):
        self.calls.append((consumer_id, threading.current_thread()))

    def noul(self, consumer_id, statement, frame=None, *, true_label="yes",
             false_label="no"):
        self._note(consumer_id)
        return Noul(consumer_id=consumer_id, probability=self.p, engine_latency_ms=1)

    def decide(self, consumer_id, options, frame, instruction=None):
        self._note(consumer_id)
        options = list(options)
        chosen = self.chosen if self.chosen in options else options[0]
        rest = (1.0 - self.p) / max(len(options) - 1, 1)
        return DecisionScore(
            consumer_id=consumer_id, chosen=chosen, confidence=self.p,
            distribution=tuple(
                CandidateScore(o, -0.1, self.p if o == chosen else rest)
                for o in options),
            engine_latency_ms=1,
        )

    def fast_path_args(self, option, schema, frame):
        return de.ArgsResult(args={"query": frame.get("goal", "q")}, retried=False,
                             fast_path="goal_to_query")

    def generate_args(self, *a, **k):
        return de.ArgsResult(args=None, retried=False)

    def on_calling_thread(self):
        me = threading.current_thread()
        return [c for c, t in self.calls if t is me]

    def off_calling_thread(self):
        me = threading.current_thread()
        return [c for c, t in self.calls if t is not me]


@pytest.fixture
def install(monkeypatch):
    def _install(engine):
        monkeypatch.setattr(de, "get_decision_engine", lambda: engine)
        return engine

    return _install


# --------------------------------------------------------------------------
# 1. The chokepoint
# --------------------------------------------------------------------------


class TestChokepoint:
    def test_default_configuration_decides_nothing(self, chokepoint):
        """Fails on the old code: IRIS_DECISION_ENFORCE defaulted to
        "tool_choice", so enforced_consumers() was {"tool_choice"} out of the
        box (and `decides` did not exist)."""
        assert de.enforced_consumers() == frozenset()
        for c in de.CONSUMERS:
            assert de.decides(c) is None, c
            assert de.oracle_acts(c, 1.0) is False, c

    def test_allow_listed_but_not_earned_does_not_decide(self, chokepoint):
        chokepoint.enable(["mode"], earned=[])
        assert de.decides("mode") is None
        assert de.enforced_consumers() == frozenset()

    def test_earned_but_not_allow_listed_does_not_decide(self, chokepoint):
        """Fails on the old code: a bar record alone enforced (union)."""
        chokepoint.enable(["mode"], allow=[])
        assert de.decides("mode") is None
        assert de.enforced_consumers() == frozenset()

    def test_allow_listed_earned_without_a_fitted_threshold_does_not_decide(self, chokepoint):
        chokepoint.enable(["mode"], fitted=[])
        assert de.decides("mode") is None

    def test_a_bar_earned_on_a_retired_engine_does_not_decide(self, chokepoint):
        chokepoint.enable(["mode"], record_engine="LFM2-350M-Extract")
        assert de.decides("mode") is None

    def test_all_four_keys_decide_with_the_calibrated_threshold(self, chokepoint):
        chokepoint.enable(["mode"], threshold=0.73)
        assert de.decides("mode") == pytest.approx(0.73)
        assert de.enforced_consumers() == frozenset({"mode"})

    def test_a_stale_configuration_decides_nothing(self, chokepoint):
        chokepoint.enable(["mode", "done"])
        chokepoint.stale = True
        assert de.decides("mode") is None
        assert de.enforced_consumers() == frozenset()

    def test_enforced_consumers_is_the_intersection(self, chokepoint):
        chokepoint.enable(
            ["mode", "done", "web_intent", "depth_met"],
            allow=["mode", "done", "web_intent"],
            earned=["mode", "web_intent", "depth_met"],
            fitted=["mode", "web_intent", "done"],
        )
        assert de.enforced_consumers() == frozenset({"mode", "web_intent"})

    def test_oracle_acts_uses_the_calibrated_confidence(self, chokepoint):
        chokepoint.enable(["mode"], threshold=0.80)
        assert de.oracle_acts("mode", 0.85) is True
        assert de.oracle_acts("mode", 0.79) is False
        assert de.oracle_acts("done", 0.99) is False  # not switched on

    def test_the_decision_is_logged_once_with_the_reason(self, chokepoint, caplog):
        chokepoint.enable(["mode", "done"], earned=["mode"])
        with caplog.at_level(logging.INFO, logger="decision_engine"):
            for _ in range(4):
                de.decides("mode")
                de.decides("done")
        lines = [r.getMessage() for r in caplog.records
                 if "enforcement:" in r.getMessage()]
        assert len(lines) == 1, lines
        assert "mode@" in lines[0] and "done (not earned" in lines[0], lines[0]

    def test_a_silent_default_is_logged_too(self, chokepoint, caplog):
        with caplog.at_level(logging.INFO, logger="decision_engine"):
            de.decides("mode")
        assert any("IRIS_DECISION_ENFORCE is empty" in r.getMessage()
                   for r in caplog.records)

    def test_the_dead_consumers_are_gone(self):
        """on_track (no production caller since 2026-10-02) and has_gaps (no live
        site) are removed: they cannot be allow-listed, scored or registered."""
        for dead in ("on_track", "has_gaps"):
            assert dead not in de.CONSUMERS
            assert dead not in de.CONSUMER_JOBS
            assert dead not in ms.MONITOR_CONSUMERS
            assert dead not in ss.SURFACE_CONSUMERS
            assert dead not in oc.binary_consumers()


# --------------------------------------------------------------------------
# 2. Every deciding site: (a) not deciding, (b) deciding + confident,
#    (c) deciding + below its calibrated threshold
# --------------------------------------------------------------------------


def _drive_web_intent(eng):
    return explorer._is_web_intent(
        "please grab that article for me", engine=eng, turn_key=object())


def _drive_use_thinking(eng):
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._thinking_style = "balanced"
    return k._needs_thinking("what is the capital city of France please tell")


def _drive_escalate_incomplete(eng):
    from backend.agent.der_loop import DirectorQueue, ExecutionMode

    q = DirectorQueue(objective="test")
    q.mode = ExecutionMode.QUICK
    q.items = []
    return q.check_escalation(
        review_verdict=None, tool_result_summary="all good, nothing more to do",
        token_budget_remaining=11000)


def _drive_needs_action(eng):
    return tool_decision._goal_needs_action("ponder the meaning of it all")


def _drive_sufficient(eng):
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k.infer = lambda prompt, **kw: SimpleNamespace(
        raw_text='{"sufficient": false, "missing": "the figures"}')
    item = SimpleNamespace(result="some findings " * 10)
    return k._der_findings_sufficient("find the figures", [item])[0]


def _drive_recovery_strategy(eng):
    box = tool_decision.ToolDecisionBox(
        router=SimpleNamespace(generate=lambda *a, **kw: ("", "", [])),
        tool_bridge=SimpleNamespace(record_decision=lambda *a, **k: None),
        get_available_tools=lambda: [],
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=eng,
    )
    return box.recovery_strategy(failed_tool="search", objective="OBJ-9")["strategy"]


def _drive_mode(eng):
    from backend.agent.mode_detector import ModeDetector

    d = ModeDetector()
    d.set_mode_engine(eng)
    return d.detect("fix the broken collector").confidence


def _drive_tool_choice(eng):
    brain = lambda prompt, **kw: SimpleNamespace(  # noqa: E731
        raw_text='{"kind": "reasoning", "tool": null, "params": {}, "rationale": "x"}')
    out = explorer.propose(
        "look into the cache layer", "", [{"name": "search", "parameters": {}}],
        brain, engine=eng)
    return out["kind"]


def _mode_rule_confidence():
    from backend.agent.mode_detector import ModeDetector

    return ModeDetector()._infer_mode("fix the broken collector")[1]


# consumer, driver, engine kwargs, value when the incumbent decides, value when
# the Oracle acts, does the Oracle still SCORE (off path) when it does not decide
SITES = {
    "web_intent": ("web_intent", _drive_web_intent, {}, False, True, True),
    "use_thinking": ("use_thinking", _drive_use_thinking, {}, False, True, True),
    "escalate_incomplete": ("escalate_incomplete", _drive_escalate_incomplete,
                            {}, False, True, True),
    "needs_action": ("needs_action", _drive_needs_action, {}, False, True, True),
    "sufficient": ("sufficient", _drive_sufficient, {}, False, True, True),
    "recovery_strategy": ("recovery_strategy", _drive_recovery_strategy,
                          {"chosen": "decompose"}, "delegate", "decompose", True),
    "mode": ("mode", _drive_mode, {"chosen": "debug"}, "RULE", 0.75, True),
    # tool_choice: nothing is scored at all while it does not decide.
    "tool_choice": ("tool_choice", _drive_tool_choice, {"chosen": "search"},
                    "reasoning", "tool", False),
}


def _expected(site, which):
    _c, _d, _k, rule, oracle, _s = SITES[site]
    if site == "mode":  # the observable is the confidence, not a verdict
        return pytest.approx(0.75 if which == "oracle" else _mode_rule_confidence())
    return oracle if which == "oracle" else rule


@pytest.mark.parametrize("site", sorted(SITES))
def test_not_deciding_keeps_the_incumbent_and_scores_off_the_calling_thread(
        site, chokepoint, install):
    """(a) Default configuration. Fails on the old code: web_intent decided at
    conf >= 0.8 unearned; recovery_strategy steered at conf >= 0.40; mode
    overwrote the keyword confidence; tool_choice's propose() committed the
    engine's pick; and the other consumers scored INLINE on the calling thread
    (measured reply-path Oracle time: median 3.8 s/turn)."""
    consumer, driver, kw, _r, _o, scored = SITES[site]
    eng = install(_Eng(p=0.85, **kw))
    out = driver(eng)
    assert out == _expected(site, "rule"), (site, out)
    assert eng.on_calling_thread() == [], (
        f"{site}: the Oracle was scored synchronously on the calling thread")
    _flush()
    if scored:
        assert consumer in eng.off_calling_thread(), (
            f"{site}: the calibration score was dropped, not moved to the lane")
    else:
        assert eng.calls == [], f"{site}: scored although it cannot decide"
    assert consumer in chokepoint.asked, f"{site}: never asked the chokepoint"


@pytest.mark.parametrize("site", sorted(SITES))
def test_deciding_and_confident_uses_the_oracle(site, chokepoint, install):
    """(b) Switched on, earned, fitted (threshold 0.70) and confident (0.75).
    Fails on the old code: nothing passed `enforced=`; web_intent's private tau
    was 0.8 (0.75 did not act); recovery_strategy / tool_choice acted without
    the chokepoint (the default-off tests above catch that half)."""
    consumer, driver, kw, _r, _o, _s = SITES[site]
    chokepoint.enable([consumer], threshold=0.70)
    eng = install(_Eng(p=0.75, **kw))
    out = driver(eng)
    assert out == _expected(site, "oracle"), (site, out)
    assert consumer in chokepoint.asked


@pytest.mark.parametrize("site", sorted(SITES))
def test_deciding_below_the_calibrated_threshold_keeps_the_incumbent(
        site, chokepoint, install):
    """(c) Switched on but 0.85 is below the fitted threshold 0.95: the existing
    path decides. Fails on the old code: web_intent acted at 0.85 >= 0.8,
    recovery_strategy at 0.85 >= 0.40, tool_choice at 0.85 >= its raw threshold,
    mode replaced the confidence; consumers that never acted on the old code
    (use_thinking, escalate_incomplete, needs_action, sufficient) fail the
    chokepoint-was-asked assertion."""
    consumer, driver, kw, _r, _o, _s = SITES[site]
    chokepoint.enable([consumer], threshold=0.95)
    eng = install(_Eng(p=0.85, **kw))
    out = driver(eng)
    assert out == _expected(site, "rule"), (site, out)
    assert consumer in chokepoint.asked


def test_web_intent_is_scored_once_per_turn_and_goal(install):
    """Five kernel call sites ask the same goal twice a turn (measured 535 ms of
    Oracle time per turn). Fails on the old code: every call scored inline."""
    eng = install(_Eng(p=0.85))
    turn = object()
    for _ in range(3):
        explorer._is_web_intent("please grab that article for me",
                                engine=eng, turn_key=turn)
    explorer._is_web_intent("fetch the release notes for me",
                            engine=eng, turn_key=turn)
    _flush()
    assert len(eng.calls) == 2, eng.calls


# -- depth_met / done: the sites sit deep inside the kernel loop, so the wiring is
# -- pinned structurally and the behaviour on the two helpers they call.

_AGENT_DIR = __import__("pathlib").Path(__file__).resolve().parents[2] / "agent"


def _kernel_src():
    return (_AGENT_DIR / "agent_kernel.py").read_text(encoding="utf-8", errors="replace")


def _call_kwargs(src, attr, first_arg):
    import ast

    out = []
    for n in ast.walk(ast.parse(src)):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr and n.args
                and isinstance(n.args[0], ast.Constant)
                and n.args[0].value == first_arg):
            out.append({k.arg: ast.unparse(k.value) for k in n.keywords})
    return out


@pytest.mark.parametrize("attr,consumer", [("surface_bool", "depth_met"),
                                           ("monitor_bool", "done")])
def test_depth_met_and_done_sites_go_through_the_chokepoint(attr, consumer):
    """Fails on the old code: depth_met read `"depth_met" in enforced_consumers()`
    and a private IRIS_DEPTH_MET_THRESHOLD tau; `done` passed no `enforced=`."""
    src = _kernel_src()
    (kw,) = _call_kwargs(src, attr, consumer)
    assert "enforced" in kw and "acts" in kw, kw
    assert f"oracle_acts('{consumer}'" in kw["acts"], kw["acts"]
    assert "threshold" not in kw, "a private tau came back"
    assert kw.get("defer") == "True", "a not-deciding score must defer to the lane"
    assert 'environ.get("IRIS_DEPTH_MET_THRESHOLD"' not in src, (
        "the private depth_met tau is back")
    assert f'decides("{consumer}")' in src


def test_done_adopts_the_deciding_value():
    """A `done` that decides must change what the loop reads (a computed signal
    must change behaviour). Fails on the old code: the value was dropped."""
    src = _kernel_src()
    assert 'data["done"] = bool(_done_value)' in src


@pytest.mark.parametrize("consumer", ["done", "sufficient"])
def test_monitor_bool_not_deciding_defers_and_deciding_acts(
        consumer, chokepoint):
    brain_text = lambda: "next goal"  # noqa: E731
    # not deciding: the Brain answers; the score lands on the lane
    eng = _Eng(p=0.85)
    rows = []
    ms.set_row_sink(rows.append)
    try:
        value, text, row = ms.monitor_bool(
            consumer, "is it done?", brain_bool_fn=lambda: False,
            brain_text_fn=brain_text, engine=eng, defer=True, enforced=False)
        assert (value, row) == (False, None) and eng.on_calling_thread() == []
        _flush()
        assert eng.off_calling_thread() == [consumer] and rows
    finally:
        ms.set_row_sink(None)
    # deciding + confident: the Oracle's bit
    chokepoint.enable([consumer], threshold=0.70)
    eng = _Eng(p=0.75)
    value, _t, _r = ms.monitor_bool(
        consumer, "is it done?", brain_bool_fn=lambda: False,
        brain_text_fn=brain_text, engine=eng, defer=True, enforced=True,
        acts=lambda c: de.oracle_acts(consumer, c))
    assert value is True
    # deciding + below the threshold: the Brain's bit
    chokepoint.enable([consumer], threshold=0.95)
    eng = _Eng(p=0.85)
    value, _t, _r = ms.monitor_bool(
        consumer, "is it done?", brain_bool_fn=lambda: False,
        brain_text_fn=brain_text, engine=eng, defer=True, enforced=True,
        acts=lambda c: de.oracle_acts(consumer, c))
    assert value is False


def test_surface_bool_not_deciding_defers_and_deciding_acts(chokepoint):
    consumer = "depth_met"
    eng = _Eng(p=0.85)
    rows = []
    ss.set_row_sink(rows.append)
    try:
        value, row = ss.surface_bool(
            consumer, "deep enough?", brain_bool_fn=lambda: False, engine=eng,
            defer=True, enforced=False, criteria_version="depth_met/v2")
        assert (value, row) == (False, None) and eng.on_calling_thread() == []
        _flush()
        assert eng.off_calling_thread() == [consumer]
        assert rows and rows[0]["criteria_version"] == "depth_met/v2"
    finally:
        ss.set_row_sink(None)
    chokepoint.enable([consumer], threshold=0.70)
    value, _row = ss.surface_bool(
        consumer, "deep enough?", brain_bool_fn=lambda: False, engine=_Eng(p=0.75),
        defer=True, enforced=True, acts=lambda c: de.oracle_acts(consumer, c))
    assert value is True
    chokepoint.enable([consumer], threshold=0.95)
    value, _row = ss.surface_bool(
        consumer, "deep enough?", brain_bool_fn=lambda: False, engine=_Eng(p=0.85),
        defer=True, enforced=True, acts=lambda c: de.oracle_acts(consumer, c))
    assert value is False


def test_needs_action_with_a_lexical_true_is_never_scored(install):
    """The lexical rule can only be widened, so a True needs no Oracle call.
    Fails on the old code: it scored first and discarded the answer."""
    eng = install(_Eng(p=0.01))
    assert tool_decision._goal_needs_action("search for the latest merger news") is True
    _flush()
    assert eng.calls == []


# --------------------------------------------------------------------------
# 3. Narration: scored once per turn, off the loop thread; the gate never decides
# --------------------------------------------------------------------------


@pytest.fixture
def narration_spec_restored():
    had = CONSUMER_TASKS.get("narration")
    yield
    if had is None:
        CONSUMER_TASKS.pop("narration", None)
    else:
        CONSUMER_TASKS["narration"] = had


def _score_kernel(rows):
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._shadow_row_sink = rows.append
    k._current_turn_id = "turn-1"
    return k


def test_narration_is_scored_once_per_turn_on_the_lane(
        install, narration_spec_restored):
    """Fails on the old code: _score_narration ran on every _plan_task (~3.6x a
    turn) and inline (1042 ms of the reply per turn)."""
    eng = install(_Eng(p=0.8))
    rows: list = []
    k = _score_kernel(rows)
    for _ in range(4):
        k._score_narration(task="build it", beats=["a"], authored=["a"], n_steps=3)
    _flush()
    assert eng.calls and [c for c, _t in eng.calls] == ["narration"], eng.calls
    assert eng.on_calling_thread() == []
    assert len(rows) == 1 and rows[0]["consumer_id"] == "narration"
    assert rows[0]["brain_choice"] == "speak_all"
    # a NEW turn is a new question
    k._current_turn_id = "turn-2"
    k._score_narration(task="build it", beats=["a"], authored=["a"], n_steps=3)
    _flush()
    assert len(eng.calls) == 2


def test_narration_is_never_scored_on_the_event_loop_thread(
        install, narration_spec_restored):
    eng = install(_Eng(p=0.8))
    rows: list = []
    k = _score_kernel(rows)
    loop_thread = {}

    async def _on_loop():
        loop_thread["t"] = threading.current_thread()
        k._score_narration(task="x", beats=["a"], authored=["a"], n_steps=2)

    asyncio.run(_on_loop())
    _flush()
    assert eng.calls
    assert all(t is not loop_thread["t"] for _c, t in eng.calls)


def test_the_narration_gate_never_decides_and_never_scores(
        install, narration_spec_restored, chokepoint):
    """The gate asked "speak"/"silent" on a constant frame; the calibration rows
    measure speak_all/speak_first_only/stay_silent. Chosen fix: narration NEVER
    decides at the gate - gate() refuses a menu that is not the registered labels
    and the two inline consults (narration.may_narrate, the gateway's
    _engine_permits_speech) are removed. Fails on the old code: both scored the
    Oracle inline and a confident enforced 'silent' suppressed speech."""
    from backend.agent import narration
    from backend.agent.decision_backend_onnx import ConsumerSpec, register_consumer_spec

    register_consumer_spec(ConsumerSpec(
        consumer_id="narration", task_name="narration", instruction="q",
        labels=("speak_all", "speak_first_only", "stay_silent")))
    chokepoint.enable(["narration"], threshold=0.50)
    eng = install(_Eng(p=0.99, chosen="silent"))

    assert de.gate("narration", ["speak", "silent"], {"kind": "progress"}) == (None, False)
    monkey_last = narration._narration_gate_last
    narration._narration_gate_last = 0.0
    try:
        assert narration.may_narrate() is True      # the timer admits
        assert narration.may_narrate() is False     # the timer refuses (18 s)
    finally:
        narration._narration_gate_last = monkey_last
    assert eng.calls == [], "the narration gate scored the Oracle"

    from backend.iris_gateway import IRISGateway

    assert not hasattr(IRISGateway, "_engine_permits_speech")


def test_gate_acts_only_on_the_registered_question(
        install, narration_spec_restored, chokepoint):
    """A matching menu may act, and only above the calibrated threshold."""
    from backend.agent.decision_backend_onnx import ConsumerSpec, register_consumer_spec

    labels = ("speak_all", "speak_first_only", "stay_silent")
    register_consumer_spec(ConsumerSpec(
        consumer_id="narration", task_name="narration", instruction="q", labels=labels))
    chokepoint.enable(["narration"], threshold=0.70)
    install(_Eng(p=0.80, chosen="stay_silent"))
    ds, enforced = de.gate("narration", list(labels), {})
    assert ds is not None and enforced is True
    install(_Eng(p=0.60, chosen="stay_silent"))
    ds, enforced = de.gate("narration", list(labels), {})
    assert ds is not None and enforced is False


# --------------------------------------------------------------------------
# 4. mode keeps the keyword confidence unless it decides
# --------------------------------------------------------------------------


def test_mode_keeps_the_keyword_confidence_when_not_deciding(install):
    """Fails on the old code: the engine probability overwrote the keyword
    confidence although mode is not enforced (it feeds needs_clarification)."""
    from backend.agent.mode_detector import ModeDetector

    eng = install(_Eng(p=0.75, chosen="debug"))
    d = ModeDetector()
    d.set_mode_engine(eng)
    got = d.detect("fix the broken collector")
    assert got.confidence == pytest.approx(_mode_rule_confidence())
    assert got.confidence != pytest.approx(0.75)
    _flush()
    assert d.last_mode_shadow is not None, "the row must still be exposed"
    assert d.last_mode_shadow["consumer_id"] == "mode"
