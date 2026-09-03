"""FAULTLINE unit tests (session 244) — three-layer failure taxonomy.

Layer 1: dimensions resolve through the registry.
Layer 2: registered labels produce typed outcomes; registry growth API works.
Layer 3: unknown labels are never dropped — stored raw, counted, promotable.
Boundary: normalize_failure enriches legacy bare errors and is idempotent.
"""
import pytest

from backend.agent.tool_errors import (
    ERROR_LABELS,
    classify_exception,
    normalize_failure,
    promote_unknown,
    register_error_label,
    resolve_label,
    tool_error,
    unknown_label_counts,
)


class TestLayer1Dimensions:
    def test_registered_label_resolves_dimensions(self):
        spec = resolve_label("walled")
        assert spec is not None
        assert spec.dimensions.retryable == "no"
        assert spec.dimensions.blame == "world"
        assert spec.dimensions.info_state == "blocked"

    def test_every_seeded_label_has_valid_dimensions(self):
        from backend.agent.tool_errors import (
            BLAME_VALUES, INFO_STATE_VALUES, RETRYABLE_VALUES,
        )
        for name, spec in ERROR_LABELS.items():
            assert spec.dimensions.retryable in RETRYABLE_VALUES, name
            assert spec.dimensions.blame in BLAME_VALUES, name
            assert spec.dimensions.info_state in INFO_STATE_VALUES, name


class TestLayer2Registry:
    def test_tool_error_produces_canonical_shape(self):
        out = tool_error("walled", "github.com parked after budget")
        assert out["success"] is False
        assert out["error_type"] == "walled"
        assert out["retryable"] == "no"
        assert out["blame"] == "world"
        assert out["info_state"] == "blocked"
        assert "raw" not in out["details"]

    def test_raw_exception_is_preserved_never_lost(self):
        out = tool_error("transient", "connection blip", raw="ConnectionResetError()")
        assert out["details"]["raw"] == "ConnectionResetError()"

    def test_register_new_label_is_data_edit_not_code(self):
        ok = register_error_label(
            "test_paywall", "no", "world", "blocked",
            "publisher paywall — retry cannot win",
        )
        assert ok is True
        spec = resolve_label("test_paywall")
        assert spec.dimensions.retryable == "no"
        # Cleanup so the seeded vocabulary stays canonical for other tests.
        ERROR_LABELS.pop("test_paywall", None)

    def test_register_rejects_invalid_dimension_values(self):
        ok = register_error_label("test_bad", "sometimes", "world", "blocked")
        assert ok is False
        assert resolve_label("test_bad") is None


class TestLayer3UnclassifiedBucket:
    def test_unknown_label_stored_counted_flagged_never_dropped(self):
        before = unknown_label_counts().get("mystery_kind", 0)
        out = tool_error("mystery_kind", "something new happened")
        assert out["success"] is False                      # never dropped
        assert out["error"] == "something new happened"     # message preserved
        assert out["error_type"] == "mystery_kind"          # label preserved
        assert out["details"]["unclassified"] is True       # flagged
        assert unknown_label_counts()["mystery_kind"] == before + 1  # counted

    def test_promotion_moves_label_into_registry(self):
        promote_unknown("mystery_kind", "maybe", "world", "unknown", "promoted by evidence")
        spec = resolve_label("mystery_kind")
        assert spec is not None
        assert spec.dimensions.retryable == "maybe"
        ERROR_LABELS.pop("mystery_kind", None)


class TestClassifier:
    def test_timeout_maps_transient(self):
        assert classify_exception(TimeoutError("x")) == "transient"

    def test_permission_maps_capability_missing(self):
        assert classify_exception(PermissionError("denied")) == "capability_missing"

    def test_value_error_maps_invalid_params(self):
        assert classify_exception(ValueError("bad param")) == "invalid_params"

    def test_unknown_exception_maps_crashed(self):
        class WeirdError(Exception):
            pass
        assert classify_exception(WeirdError("?")) == "crashed"


class TestBoundaryNormalization:
    def test_legacy_bare_error_gets_typed(self):
        legacy = {"success": False, "error": "request timed out after 10s"}
        out = normalize_failure(legacy)
        assert out["error_type"] == "transient"
        assert out["retryable"] in ("yes", "maybe")
        assert out["details"]["raw"] == "request timed out after 10s"

    def test_extra_keys_survive_normalization(self):
        legacy = {"success": False, "error": "boom", "documents": []}
        out = normalize_failure(legacy)
        assert out["documents"] == []

    def test_already_typed_result_passes_through_idempotent(self):
        typed = tool_error("walled", "parked")
        out = normalize_failure(dict(typed))
        assert out["error_type"] == "walled"
        assert out["retryable"] == "no"

    def test_success_results_untouched(self):
        ok = {"success": True, "data": [1, 2]}
        assert normalize_failure(ok) is ok

    def test_walled_message_classified_from_park_language(self):
        legacy = {"success": False, "error": "source parked: challenge wall"}
        out = normalize_failure(legacy)
        assert out["error_type"] == "walled"


# ── REQ-19: dev/shell surface labels (T0i) ──────────────────────────────────

class TestDevShellLabels:
    """REQ-19 AC1: the dev/shell labels are registered DATA with exact dims."""

    REQ19_TABLE = [
        # (label, retryable, blame, info_state) — verbatim from REQ-19 AC1
        ("workdir_denied", "no", "query", "blocked"),
        ("cap_reached", "yes", "self", "missing"),
        ("aborted", "maybe", "self", "unknown"),
        ("shell_spawn_failed", "maybe", "world", "blocked"),
        ("output_truncated", "no", "world", "missing"),
        ("injection_suppressed", "no", "self", "blocked"),
        ("worktree_unavailable", "maybe", "world", "blocked"),
    ]

    @pytest.mark.parametrize("label,retryable,blame,info_state", REQ19_TABLE)
    def test_dev_shell_labels_resolve_per_req19_table(self, label, retryable, blame, info_state):
        spec = resolve_label(label)
        assert spec is not None, f"{label} not registered"
        assert spec.dimensions.retryable == retryable
        assert spec.dimensions.blame == blame
        assert spec.dimensions.info_state == info_state

    def test_duplicate_registration_refused_not_overwritten(self):
        # REQ-19 edge case: the first spec to name a failure mode owns it.
        before = resolve_label("workdir_denied")
        ok = register_error_label("workdir_denied", "yes", "self", "unknown", "hijack")
        assert ok is False
        after = resolve_label("workdir_denied")
        assert after == before  # dimensions unchanged


class TestDevToolFailureSemantics:
    """REQ-19 AC2/AC3 through the real AgentToolBridge dev-tool path."""

    def _bridge(self):
        from backend.agent.tool_bridge import AgentToolBridge

        bridge = AgentToolBridge.__new__(AgentToolBridge)  # no heavy init needed
        bridge.__init_bridge_state__()
        return bridge

    def test_workdir_denied_typed_with_dimensions_and_raw(self):
        import asyncio

        bridge = self._bridge()
        result = asyncio.run(bridge._execute_dev_tool(
            "git_status", {"cwd": r"C:\definitely\not\registered"}, "sess-t0i"))
        assert result["success"] is False
        assert result["error_type"] == "workdir_denied"
        assert result["retryable"] == "no"
        assert result["blame"] == "query"
        assert result["info_state"] == "blocked"
        # REQ-19 AC3: raw survives next to the label
        assert "not\\registered" in result["details"]["raw"]
        # legacy message text preserved (T0b contract)
        assert "outside the project root. Aborting." in result["error"]

    def test_nonzero_exit_is_success_with_returncode_never_error(self):
        import asyncio

        bridge = self._bridge()
        result = asyncio.run(bridge._execute_dev_tool(
            "run_command", {"command": "exit 1"}, "sess-t0i"))
        # A failing command is a SUCCESSFUL tool call carrying returncode.
        assert result["success"] is True
        assert result["returncode"] == 1
        assert "error_type" not in result

    def test_zero_exit_still_success(self):
        import asyncio

        bridge = self._bridge()
        result = asyncio.run(bridge._execute_dev_tool(
            "run_command", {"command": "exit 0"}, "sess-t0i"))
        assert result["success"] is True
        assert result["returncode"] == 0


class TestAbortedBudgetExclusion:
    """REQ-19 AC4: a user abort never counts against the failure budget."""

    def _box_with_bridge(self, bridge_result):
        from backend.agent.tool_decision import ToolDecisionBox

        class _FakeRouter:
            def __init__(self, gen_result):
                self._gen = gen_result

            def generate(self, role, messages, **kw):
                return self._gen

            def health_check_provider(self, role="reasoning"):
                return {"ok": True, "provider": "test", "model": "test"}

        class _FakeTB:
            def __init__(self, result):
                self._result = result
                self.calls = 0

            async def execute_tool(self, name, params, **kw):
                self.calls += 1
                return dict(self._result)

        tb = _FakeTB(bridge_result)
        box = ToolDecisionBox(
            router=_FakeRouter(('{"kind": "tool", "tool": "run_command", "params": {}}', "", [])),
            tool_bridge=tb,
            get_available_tools=lambda: [{"name": "run_command", "description": "x"}],
            validate_tool_call=lambda n, p: (True, None),
            infer_fn=lambda prompt, **kw: "",
            memory_lookup_fn=lambda _g: None,
        )
        return box, tb

    def _tool_decision(self, box, params=None):
        from backend.agent.tool_decision import DecisionKind

        decision = box.resolve(step={"description": "dev cmd"})
        assert decision.kind == DecisionKind.TOOL
        if params:
            decision.params.update(params)
        return decision

    def test_aborted_never_accumulates_budget(self):
        box, tb = self._box_with_bridge({
            "success": False, "error": "user aborted",
            "error_type": "aborted",
        })
        for i in range(6):  # well past the budget of 3
            dr = box.dispatch(self._tool_decision(box, params={"n": i}))
            assert dr.success is False          # abort propagates as failure…
            assert "exceeded consecutive failure budget" not in (dr.error or "")
        assert box._tool_fails.get("run_command", 0) == 0   # …but counts nothing

    def test_real_failures_still_hit_budget(self):
        box, tb = self._box_with_bridge({
            "success": False, "error": "API down",
        })
        for i in range(3):
            dr = box.dispatch(self._tool_decision(box, params={"n": i}))
            assert "exceeded consecutive failure budget" not in (dr.error or "")
        dr = box.dispatch(self._tool_decision(box, params={"n": "over"}))
        assert "exceeded consecutive failure budget" in (dr.error or "")
