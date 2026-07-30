"""Contract: GET /api/debug/caducean's `outer_loop` section is side-effect free.

REQ-3 (P6.2) added a per-domain gating breakdown (`domains_present` /
`domain_gating`) to `_outer_loop()` (`backend/api/caducean_debug.py`). The
endpoint is documented -- in its own module docstring -- as STRICTLY
side-effect free, and `docs/CADUCEAN_LIVE_TEST_PLAN.md` tells testers they can
poll it as often as they like. `_domain_gating_report()` mirrors
`OuterTuner.run_once()`'s per-domain iteration (`_domain_groups`,
`_score_proposal`, `_evaluate_guards`, `_deciding_guard`) but must NEVER call
`OuterTuner._apply` -- the only method on `OuterTuner` that persists a learned
parameter to `params_path`.

A real hazard this guards against: constructing `OuterTuner()` with its
DEFAULT `params_path` (the live `.mcm/der_params.json`) and then running
anything that could accept a proposal writes into the real learned-params
file the running app reads on startup -- exactly the hazard found earlier
today in this project's own test suite (a test built an `OuterTuner()` with
default params and let it `_apply`, silently corrupting the live file).

Both tests assert the EFFECT (file mtime / bytes / existence unchanged), not
that a particular function was or wasn't called -- a mock assertion would not
catch a differently-shaped path to the same write.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import backend.agent.outer_loop as _ol_module
from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


class TestOuterLoopDebugSideEffectFree:
    def test_default_outer_tuner_never_writes_the_live_params_file(self):
        """Drives the REAL default-path `OuterTuner` (as production code
        does -- `_outer_loop()` calls `OuterTuner()` with no override) through
        `_outer_loop()` several times. Asserts `.mcm/der_params.json`'s mtime
        and byte content are unchanged -- proving polling this endpoint
        cannot perturb the learned params the running app actually uses."""
        from backend.api import caducean_debug

        real_tuner = OuterTuner()  # default params_path == live .mcm/der_params.json
        params_path = real_tuner.params_path
        assert os.path.exists(params_path), (
            f"expected the live der_params.json to already exist; path={params_path}"
        )
        before_mtime = os.path.getmtime(params_path)
        with open(params_path, "r", encoding="utf-8") as f:
            before_content = f.read()

        for _ in range(5):
            caducean_debug._outer_loop()

        after_mtime = os.path.getmtime(params_path)
        with open(params_path, "r", encoding="utf-8") as f:
            after_content = f.read()

        assert after_mtime == before_mtime, (
            f"der_params.json mtime changed: {before_mtime} -> {after_mtime} "
            "-- polling /api/debug/caducean must never write learned state"
        )
        assert after_content == before_content, (
            "der_params.json content changed -- polling /api/debug/caducean "
            "must never write learned state"
        )

    def test_seeded_accept_scenario_still_writes_nothing(self):
        """Even a scenario that WOULD be accepted by `run_once()` (pooled
        passes, and the sole gated domain also passes) must not persist
        anything when driven through `_outer_loop()` -- proves the debug path
        stops short of `_apply` regardless of the proposal's outcome, not
        only in the common "rejected" case where there is nothing to write
        anyway."""
        params_path = os.path.join(tempfile.mkdtemp(), "der_params.json")

        def _seeded():
            rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
            # 2 natural exits + 1 non-natural in the held-out window so
            # baseline natural_exit_rate < 1.0 and a consolidating proposal
            # can genuinely raise it (the ceiling case -- baseline already
            # 1.0 -- can never satisfy the strict `proposed > baseline`
            # guard, which would make every proposal reject regardless of
            # this test's point).
            for i in range(4):
                rec.record_session_exit(
                    f"s{i}", "general", natural_exit=(i != 1), verified_count=8,
                    tokens_total=5000.0, executed_steps=10,
                )
            tuner = OuterTuner(recorder=rec, held_out_count=3, params_path=params_path)
            tuner.params["U_SPLIT"] = 0.0  # so `_propose_one` moves to a real increase
            return tuner

        from backend.api import caducean_debug

        assert not os.path.exists(params_path)

        _orig = _ol_module.OuterTuner
        _ol_module.OuterTuner = _seeded
        try:
            result = None
            for _ in range(3):
                result = caducean_debug._outer_loop()
        finally:
            _ol_module.OuterTuner = _orig

        # Confirm this scenario actually reached the "would accept" shape --
        # otherwise the test proves nothing about the accept path.
        gating = result["domain_gating"]
        assert gating["mode"] == "per_domain", result
        assert gating["pooled_accepts"] is True, result
        assert all(d["passed"] for d in gating["domains"].values()), result

        # `_apply()` creates the file (os.makedirs + open(..., "w")) the
        # first time a proposal is accepted -- if `_outer_loop()` never
        # reaches it, the file must never come into existence at all.
        assert not os.path.exists(params_path), (
            "der_params.json was created by _outer_loop() -- _apply() was "
            "reached, breaking the endpoint's side-effect-free contract"
        )
