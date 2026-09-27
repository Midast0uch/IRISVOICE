"""Contract pin: the shadow-consumer row sink (REQ-14 AC14.1, REQ-29; T18, T46-T49).

Why this contract exists. The monitor consumers (`sufficient`, `done`,
`on_track`) and the surface consumers (`has_gaps`, `use_thinking`,
`escalate_incomplete`, `needs_action`) are SHADOW: each must WRITE a
calibration row and change no decision. Their modules emit that row to a
module-level sink (`monitor_shadow.set_row_sink` / `surface_shadow.set_row_sink`).

MEASURED 2026-09-26: no production code installed a sink — the only callers of
`set_row_sink` were tests. In a live session every row fell through to a
`logger.info` line, so zero rows persisted for those consumers and Wave 7's
>= 100-row flip bar was structurally unreachable: no number of live turns could
have produced the data. `AgentKernel._shadow_row_sink` plus its install in
`AgentKernel.__init__` are the missing caller.

Two things are pinned here:

  1. the sink routes a real consumer row into the SINGLE-WRITER ledger
     (`AgentToolBridge.record_decision`), with `route` set and the backend
     identity attached for attribution; and
  2. the ledger's decision-block filter KEEPS the parity pair
     (`chosen` + `brain_bool`). Without the reference the row lands with
     nothing to judge the engine against, and no precision or ECE can be
     computed from it — the row would read as complete and be useless.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel
from backend.agent.monitor_shadow import shadow_row
from backend.agent.tool_bridge import _DECISION_META_KEYS


class _Noul:
    """The Noul primitive the monitor consumers score with."""

    def __init__(self, probability: float, latency_ms: int = 3):
        self.probability = probability
        self.engine_latency_ms = latency_ms

    def true(self, threshold: float = 0.5) -> bool:
        return self.probability >= threshold


class _Recorder:
    """Stands in for AgentToolBridge.record_decision (the ledger writer)."""

    def __init__(self, raises: bool = False):
        self.calls: list = []
        self._raises = raises

    def record_decision(
        self, decision_meta, kind, error=None, session_id="unknown",
    ) -> None:
        if self._raises:
            raise RuntimeError("ledger unavailable")
        self.calls.append((dict(decision_meta), kind, session_id))


def _kernel(bridge):
    return SimpleNamespace(_tool_bridge=bridge, session_id="s-sink")


class TestSinkRoutesRowsToTheLedger:
    def test_a_real_monitor_row_keeps_its_parity_pair(self):
        """The whole point: a shadow row reaches the ledger with BOTH halves
        of the parity pair intact, so a reader can compute precision/ECE."""
        row = shadow_row("sufficient", _Noul(0.91), brain_bool=True)
        assert row is not None, "no row was built for a scored judgment"

        rec = _Recorder()
        AgentKernel._shadow_row_sink(_kernel(rec), row)  # unbound, by design

        assert rec.calls, "the row never reached the ledger writer"
        meta, kind, session_id = rec.calls[0]
        assert kind == "shadow", "a shadow row must be labelled shadow"
        assert session_id == "s-sink"

        # Apply the ledger's own filter: the parity pair must survive it.
        block = {k: meta.get(k) for k in _DECISION_META_KEYS if k in meta}
        assert block["consumer_id"] == "sufficient"
        assert block["chosen"] is True
        assert block["brain_bool"] is True, (
            "the ledger filter dropped the reference answer — the row cannot "
            "be scored, and Wave 7's precision bar can never be met"
        )
        assert block["route"] == "shadow"
        assert block["confidence"] == 0.91

    def test_installing_the_sink_routes_both_modules(self):
        """The install path, exercised through the modules' own emit_row —
        the seam that had no production caller."""
        import backend.agent.monitor_shadow as ms
        import backend.agent.surface_shadow as ss

        rec = _Recorder()
        sink = AgentKernel._shadow_row_sink.__get__(_kernel(rec))
        ms.set_row_sink(sink)
        ss.set_row_sink(sink)
        try:
            ms.emit_row({"consumer_id": "sufficient", "chosen": True,
                         "confidence": 0.9, "brain_bool": True, "shadow": True})
            ss.emit_row({"consumer_id": "has_gaps", "chosen": False,
                         "confidence": 0.8, "brain_bool": False, "shadow": True})
        finally:
            ms.set_row_sink(None)
            ss.set_row_sink(None)

        assert [m["consumer_id"] for m, _k, _s in rec.calls] == [
            "sufficient", "has_gaps",
        ]
        assert all(k == "shadow" for _m, k, _s in rec.calls)

    def test_engine_identity_is_attributed_when_absent(self):
        """REQ-21 AC21.7 / REQ-22 AC22.5: a row is attributable to the backend
        that produced it. The module rows carry no engine, so the sink fills it
        from the active backend — a reader can then separate a GLiNER row from
        a historical LFM row."""
        rec = _Recorder()
        row = {"consumer_id": "needs_action", "chosen": True, "confidence": 0.7}
        AgentKernel._shadow_row_sink(_kernel(rec), row)
        meta, _kind, _s = rec.calls[0]
        assert "engine" in meta, "the row cannot be attributed to a backend"

    def test_an_existing_route_is_not_overwritten(self):
        """A caller that already knows the route keeps it."""
        rec = _Recorder()
        AgentKernel._shadow_row_sink(
            _kernel(rec),
            {"consumer_id": "mode", "chosen": "quick", "route": "engine"},
        )
        meta, _kind, _s = rec.calls[0]
        assert meta["route"] == "engine"


class TestTheSinkNeverBlocksAStep:
    def test_no_bridge_is_ignored(self):
        AgentKernel._shadow_row_sink(_kernel(None), {"consumer_id": "mode"})

    def test_a_raising_ledger_never_raises(self):
        """AC14.4 shape: an observer never blocks the step it observes."""
        AgentKernel._shadow_row_sink(
            _kernel(_Recorder(raises=True)), {"consumer_id": "mode"},
        )

    def test_empty_or_non_dict_rows_are_ignored(self):
        rec = _Recorder()
        k = _kernel(rec)
        for bad in (None, {}, [], "not-a-row", 0):
            AgentKernel._shadow_row_sink(k, bad)
        assert rec.calls == []
