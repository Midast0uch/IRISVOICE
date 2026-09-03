"""
Unit tests for TaskClassifier confidence floor (REQ-5 AC4).

When the encoder has confidence below the configured floor → defer to
keyword result.  Above floor → use encoder result.  Tuple shape
(str, list) must be unchanged.
"""

from __future__ import annotations

from unittest import mock

from backend.memory.mycelium.kyudo import TaskClassifier, TASK_CLASS_SPACE_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeEncoder:
    """A fake EmbeddingService-like object that returns controllable embeddings."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def encode(self, text: str):
        """Return a fake embedding deterministically derived from the text."""
        # Deterministic: hash the text to produce a vector so different
        # task texts get different centroids.
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        # Convert first dim bytes to floats in [0, 0.01]
        vec = [(b / 255.0) * 0.01 for b in h[:self.dim]]
        # Pad or truncate to dim
        while len(vec) < self.dim:
            vec.append(0.0)
        return vec[:self.dim]


# ---------------------------------------------------------------------------
# Confidence floor — below floor
# ---------------------------------------------------------------------------

def test_below_floor_defers_to_keywords():
    """When encoder confidence < CONFIDENCE_FLOOR, return keyword result."""
    classifier = TaskClassifier()

    # Reset cached state so centroids are freshly computed.
    TaskClassifier._CLASS_CENTROIDS = {}

    # Mock _classify_encoder to return below-floor confidence (0.20 < 0.40).
    with mock.patch.object(
        TaskClassifier, "_get_encoder", return_value=_FakeEncoder()
    ):
        with mock.patch.object(
            TaskClassifier,
            "_classify_encoder",
            return_value=("planning_task", 0.20),
        ):
            task_class, space_subset = classifier.classify(
                "implement a new login flow with OAuth"
            )

    # Confidence 0.20 < 0.40 → keyword "code_task" wins.
    assert task_class == "code_task", (
        f"expected keyword result 'code_task', got {task_class!r}"
    )
    assert isinstance(space_subset, list)
    assert space_subset == list(TASK_CLASS_SPACE_MAP["code_task"])


def test_below_floor_no_encoder_available():
    """With encoder unavailable (None), keyword result is returned."""
    classifier = TaskClassifier()

    TaskClassifier._CLASS_CENTROIDS = {}

    with mock.patch.object(
        TaskClassifier, "_get_encoder", return_value=None
    ):
        task_class, space_subset = classifier.classify(
            "analyze the performance of the new algorithm"
        )

    assert task_class == "research_task", (
        f"expected 'research_task', got {task_class!r}"
    )
    assert isinstance(space_subset, list)


# ---------------------------------------------------------------------------
# Confidence floor — above floor
# ---------------------------------------------------------------------------

def test_above_floor_uses_encoder():
    """When encoder confidence >= CONFIDENCE_FLOOR, use encoder result."""
    classifier = TaskClassifier()
    TaskClassifier._CLASS_CENTROIDS = {}

    # Patch _get_centroids to carefully control what the encoder returns.
    # We inject centroids and then patch classify_encoder to return a
    # specific result with high confidence.
    with mock.patch.object(
        TaskClassifier, "_get_encoder", return_value=_FakeEncoder()
    ):
        with mock.patch.object(
            TaskClassifier,
            "_classify_encoder",
            return_value=("research_task", 0.85),
        ):
            task_class, space_subset = classifier.classify(
                "implement a new login flow"
            )

    # With confidence 0.85 >= 0.40, the encoder result ("research_task")
    # should be preferred over keyword ("code_task").
    assert task_class == "research_task", (
        f"expected encoder result 'research_task', got {task_class!r}"
    )
    assert isinstance(space_subset, list)
    assert space_subset == list(TASK_CLASS_SPACE_MAP["research_task"])


# ---------------------------------------------------------------------------
# Tuple shape contract (REQ-5 AC3)
# ---------------------------------------------------------------------------

def test_tuple_shape_unchanged():
    """Return value is always (str, list)."""
    classifier = TaskClassifier()
    TaskClassifier._CLASS_CENTROIDS = {}

    # With encoder available
    with mock.patch.object(
        TaskClassifier, "_get_encoder", return_value=_FakeEncoder()
    ):
        with mock.patch.object(
            TaskClassifier,
            "_classify_encoder",
            return_value=("planning_task", 0.90),
        ):
            result = classifier.classify("design the architecture")
            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], str)
            assert isinstance(result[1], list)

    # Without encoder
    TaskClassifier._CLASS_CENTROIDS = {}
    with mock.patch.object(
        TaskClassifier, "_get_encoder", return_value=None
    ):
        result = classifier.classify("fix the typo")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], list)
