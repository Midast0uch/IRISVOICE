"""Behavioral tests: engine-first tool choice in explorer.propose() (REQ-16, T20).

AC16.1 — `propose()` SHALL score an engine Choice over `live_tools` before the
Brain single-shot; the Brain runs only on engine decline / below threshold.
AC16.3 — the share of `propose()` resolutions settled without Brain spend is
measured in the Wave 7 gate (here: asserted as "zero Brain calls").
"""

from __future__ import annotations

from backend.agent.decision_engine import (
    ArgsResult,
    CandidateScore,
    DecisionScore,
    EngineCounters,
)


class _Engine:
    """Engine stub: a confident real-tool pick with fast-path args."""

    def __init__(self, chosen="run_command", confidence=0.93):
        self._chosen = chosen
        self._conf = confidence
        self.model_id = "propose-stub"
        self.counters = EngineCounters()
        self.seen: list = []

    def decide(self, consumer_id, options, frame):
        self.seen.append((consumer_id, list(options), dict(frame)))
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.02)
                for o in options
            ),
            engine_latency_ms=3,
        )

    def fast_path_args(self, option, schema, frame):
        return ArgsResult(args={"query": frame.get("goal", "")}, retried=False)

    def generate_args(self, consumer_id, option, schema, frame):
        return ArgsResult(args=None, retried=False)


class _Brain:
    """Brain stand-in: counts single-shot calls, returns a fixed JSON proposal."""

    def __init__(self, raw='{"kind": "tool", "tool": "read_file", '
                          '"params": {"path": "a"}}'):
        self._raw = raw
        self.calls = 0

    def __call__(self, *args, **kwargs):
        from types import SimpleNamespace
        self.calls += 1
        return SimpleNamespace(raw_text=self._raw)


def _tools():
    return [
        {"name": "run_command", "parameters": {"properties": {"query": {}}}},
        {"name": "read_file", "parameters": {"properties": {"path": {}}}},
    ]


def _valid(monkeypatch):
    monkeypatch.setattr(
        "backend.agent.tool_registry.validate_tool_call", lambda t, p: (True, ""))


class TestEngineBeforeBrain:
    def test_engine_before_brain(self, monkeypatch):
        """AC16.1: a confident engine pick settles the step with NO Brain spend."""
        _valid(monkeypatch)
        from backend.agent.explorer import propose

        engine = _Engine("run_command", 0.93)
        brain = _Brain()
        rows: list = []

        out = propose(
            goal="list the workspace files",
            evidence="",
            live_tools=_tools(),
            infer=brain,
            engine=engine,
            row_sink=rows.append,
        )

        assert out["kind"] == "tool" and out["tool"] == "run_command"
        assert brain.calls == 0, (
            "the Brain was spent although the engine settled the step — the "
            "engine Choice must run BEFORE the Brain single-shot (AC16.1)"
        )
        # the engine was asked FIRST, over the live tools
        assert engine.seen, "the engine was never consulted"
        assert engine.seen[0][0] == "tool_choice"
        assert "run_command" in engine.seen[0][1]
        # and a DECIDING row was emitted (not a shadow)
        assert rows, "no engine row was emitted for the settled step"
        assert rows[0]["consumer_id"] == "tool_choice"
        assert rows[0]["chosen"] == "run_command"
        assert rows[0]["shadow"] is False

    def test_decline_runs_the_brain_and_records_a_shadow_pair(self, monkeypatch):
        """AC16.1: DELEGATE → the Brain single-shot runs, and the row is a
        SHADOW pair (the engine said DELEGATE; reality ran the Brain's pick)."""
        _valid(monkeypatch)
        from backend.agent.explorer import propose

        engine = _Engine("DELEGATE", 0.99)
        brain = _Brain()
        rows: list = []

        out = propose(goal="read the readme", evidence="", live_tools=_tools(),
                      infer=brain, engine=engine, row_sink=rows.append)

        assert brain.calls == 1, "the Brain must run on an engine decline"
        assert out["tool"] == "read_file"
        assert rows and rows[0]["shadow"] is True
        assert rows[0]["chosen"] == "DELEGATE"
        assert rows[0]["brain_choice"] == "read_file"

    def test_below_threshold_declines(self, monkeypatch):
        """AC16.1: a below-threshold verdict is a decline — the Brain runs."""
        _valid(monkeypatch)
        from backend.agent.explorer import propose

        engine = _Engine("run_command", 0.20)
        brain = _Brain()
        out = propose(goal="do a thing", evidence="", live_tools=_tools(),
                      infer=brain, engine=engine)

        assert brain.calls == 1
        assert out["tool"] == "read_file"

    def test_no_engine_is_byte_identical(self, monkeypatch):
        """engine=None (the default) leaves the pre-T20 behaviour untouched."""
        _valid(monkeypatch)
        from backend.agent.explorer import propose

        brain = _Brain()
        out = propose(goal="read the readme", evidence="", live_tools=_tools(),
                      infer=brain)

        assert brain.calls == 1
        assert out == {"kind": "tool", "tool": "read_file",
                       "params": {"path": "a"}, "rationale": ""}
