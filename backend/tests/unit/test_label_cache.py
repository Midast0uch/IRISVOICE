"""Unit tests: the label-structure cache (REQ-30 AC30.2, T39).

AC30.2 — the engine SHALL cache label positions per label set rather than
re-tokenizing them on every call.

Before T39 the runner rebuilt each Task's token ids and label positions on
every `encode()`. The per-PIECE tokenizer results were cached, but the
structure assembly (and the position offsets) were recomputed. The cache is
keyed on the label set, so a changed set misses and recomputes — correctness
is unaffected (REQ-30 edge case).
"""

from __future__ import annotations

from backend.agent.decision_backend_onnx import build_task


class TestLabelPositionsCached:
    def test_label_positions_cached_per_set(self, onnx_runner):
        """AC30.2: the same label set hits the cache; a different one misses."""
        first_task = build_task("tool_choice", ["alpha", "beta", "gamma"])
        assert first_task is not None, "tool_choice has no registered criteria"

        # The runner is SESSION-scoped, so an earlier test may already have
        # populated the cache. Start from a known-empty state, or the size
        # assertions below become order-dependent.
        onnx_runner._structure_cache.clear()

        first = onnx_runner._structure(first_task)
        size_after_first = len(onnx_runner._structure_cache)
        assert size_after_first == 1

        # A SECOND task object with the SAME label set must hit, not rebuild.
        again = onnx_runner._structure(
            build_task("tool_choice", ["alpha", "beta", "gamma"])
        )
        assert again == first, "the cached structure differs from the fresh one"
        assert len(onnx_runner._structure_cache) == 1, (
            "the same label set rebuilt its structure instead of hitting the "
            "cache (AC30.2)"
        )

        # A DIFFERENT label set must miss and recompute.
        onnx_runner._structure(build_task("tool_choice", ["one", "two", "three"]))
        assert len(onnx_runner._structure_cache) == 2, (
            "a different label set must MISS the cache (correctness)"
        )

    def test_cached_structure_is_position_independent(self, onnx_runner):
        """The cache stores RELATIVE offsets; `encode` makes them absolute, so
        the same label set yields correct positions at any batch position."""
        head = build_task("tool_choice", ["alpha", "beta"])
        tail = build_task("tool_choice", ["one", "two", "three"])

        head_ids, head_pos = onnx_runner._structure(head)
        ids_one, pos_one = onnx_runner.encode("hello world", [head])
        ids_two, pos_two = onnx_runner.encode("hello world", [head, tail])

        # The head's structure is a PREFIX of both, unchanged by what follows
        # it. (The text section comes after ALL tasks, so the tail of the
        # one-task list is not comparable — only the structure prefix is.)
        assert ids_one[:len(head_ids)] == head_ids
        assert ids_two[:len(head_ids)] == head_ids, (
            "the cached structure changed when it was not the only task"
        )
        assert pos_one == head_pos
        assert pos_two[:len(head_pos)] == head_pos, (
            "label positions are wrong when the label set is not first in the "
            "batch — the cached offsets were not made absolute"
        )
        assert len(pos_two) > len(head_pos), (
            "the second task contributed no label positions"
        )

    def test_cache_does_not_change_the_scored_result(self, onnx_backend):
        """AC30.2 edge: caching is an optimisation — the verdict is identical."""
        menu = ["alpha", "beta", "gamma"]
        first = onnx_backend.decide("tool_choice", menu, {"goal": "pick one"})
        onnx_backend._runner._structure_cache.clear()   # force a cold rebuild
        second = onnx_backend.decide("tool_choice", menu, {"goal": "pick one"})

        assert first is not None and second is not None
        assert first.chosen == second.chosen
        assert abs(first.confidence - second.confidence) < 1e-9
