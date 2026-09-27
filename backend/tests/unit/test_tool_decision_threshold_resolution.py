"""Unit tests: the tool_choice threshold is keyed to the ACTIVE backend.

REQ-22 AC22.1 / REQ-25 AC25.8. The box used to hardcode 0.85 and the kernel
never passed a value (agent_kernel.py `_get_tool_box`), so every decision was
judged against the RETIRED LFM curve whatever backend was deployed. Measured
live 2026-09-26: the ledger recorded `threshold: 0.85` on a row whose engine
was `gliner25-decide-onnx-int8`, whose measured entry is 0.40 — 2.1x the
calibrated pass mark, and a silent behavioural difference for any confidence
in [0.40, 0.85).

`_decision_threshold` is the value the box records in the ledger meta
(tool_decision.py:994), so asserting it IS asserting what the evidence trail
will say.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent.decision_engine import EngineConfig
from backend.agent.tool_decision import (
    _LEGACY_THRESHOLD,
    _NEVER_ENFORCE_THRESHOLD,
    ToolDecisionBox,
)

_THRESHOLDS = {
    "lfm2-350m-extract": 0.85,
    "gliner25-decide-onnx-int8": 0.40,
}


def _box(engine=None, **kw):
    return ToolDecisionBox(
        router=SimpleNamespace(),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: [],
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
        **kw,
    )


def _engine(backend_id, cap=6, calibrated=6):
    cfg = EngineConfig(
        backend_id=backend_id,
        backend_thresholds=dict(_THRESHOLDS),
        candidate_cap=cap,
        calibrated_cap=calibrated,
    )
    return SimpleNamespace(_cfg=cfg, model_id=backend_id)


class TestTheThresholdFollowsTheBackend:
    def test_the_deployed_backend_gets_its_own_curve(self):
        """The live defect, pinned: GLiNER must read 0.40, not 0.85."""
        box = _box(_engine("gliner25-decide-onnx-int8"))
        assert box._decision_threshold == pytest.approx(0.40)

    def test_the_retired_backend_keeps_its_historical_curve(self):
        """Historical rows stay interpretable: the LFM entry is still 0.85."""
        box = _box(_engine("lfm2-350m-extract"))
        assert box._decision_threshold == pytest.approx(0.85)

    def test_an_unknown_backend_refuses_enforcement(self):
        """AC25.8 fail-closed: no entry for the active backend means the
        engine may not enforce at all — never another model's curve."""
        box = _box(_engine("gliner9-unmeasured-variant"))
        assert box._decision_threshold >= 1.0, (
            "an unmeasured backend was given a usable threshold"
        )
        assert box._decision_threshold == _NEVER_ENFORCE_THRESHOLD

    def test_a_stale_menu_width_refuses_enforcement(self):
        """AC25.5: a cap that moved off the calibrated width marks the curve
        stale, and a stale curve must not enforce."""
        box = _box(_engine("gliner25-decide-onnx-int8", cap=12, calibrated=6))
        assert box._decision_threshold == _NEVER_ENFORCE_THRESHOLD

    def test_an_explicit_caller_value_still_wins(self):
        """Callers that know their curve (and the existing tests) keep it."""
        box = _box(_engine("gliner25-decide-onnx-int8"), decision_threshold=0.85)
        assert box._decision_threshold == pytest.approx(0.85)

    def test_no_engine_keeps_the_legacy_path(self):
        """Engine-free unit suites must be unaffected."""
        box = _box(None)
        assert box._decision_threshold == pytest.approx(_LEGACY_THRESHOLD)

    def test_a_broken_config_refuses_enforcement(self):
        """A config that raises is not a licence to enforce."""
        engine = SimpleNamespace(_cfg=SimpleNamespace(backend_id="x"))
        box = _box(engine)  # no threshold_for attribute at all
        assert box._decision_threshold == _NEVER_ENFORCE_THRESHOLD
