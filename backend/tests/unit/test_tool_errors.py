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
