"""Unit test: `is_shallow_verified` depth-threshold logic (REQ-5 AC1/AC3).

Spec: specs/phase-6-der-integrity/requirements.md REQ-5 AC1/AC3.

A VERIFIED step below expected depth for its task class must trigger
`analyze_gaps`; one at or above expected depth (or in an intentionally
excluded task class, AC3) must not.
"""

from __future__ import annotations

from backend.agent.der_constants import (
    DEPTH_EXCLUDED_TASK_CLASSES,
    EXPECTED_DEPTH_MIN_TOKENS,
    is_shallow_verified,
)


class TestDepthThreshold:
    def test_top_level_thin_step_is_shallow(self):
        assert is_shallow_verified(
            depth_layer=1, result_tokens=EXPECTED_DEPTH_MIN_TOKENS - 1, task_class="research",
        ) is True

    def test_top_level_thick_step_is_not_shallow(self):
        assert is_shallow_verified(
            depth_layer=1, result_tokens=EXPECTED_DEPTH_MIN_TOKENS, task_class="research",
        ) is False

    def test_step_already_split_deeper_is_not_shallow(self):
        """Step already at max depth -> no further split attempted (edge case)."""
        assert is_shallow_verified(
            depth_layer=2, result_tokens=1, task_class="research",
        ) is False

    def test_excluded_task_classes_never_flag(self):
        for tc in DEPTH_EXCLUDED_TASK_CLASSES:
            assert is_shallow_verified(depth_layer=1, result_tokens=0, task_class=tc) is False

    def test_excluded_task_class_is_case_insensitive(self):
        assert is_shallow_verified(depth_layer=1, result_tokens=0, task_class="QUESTION") is False

    def test_unknown_task_class_uses_default_threshold(self):
        assert is_shallow_verified(depth_layer=1, result_tokens=0, task_class="some_new_class") is True
        assert is_shallow_verified(
            depth_layer=1, result_tokens=EXPECTED_DEPTH_MIN_TOKENS + 100, task_class="some_new_class",
        ) is False

    def test_none_task_class_is_not_excluded(self):
        assert is_shallow_verified(depth_layer=1, result_tokens=0, task_class=None) is True
