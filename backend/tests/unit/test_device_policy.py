"""
Tests for resolve_device_policy (Phase 3, Wave 1).

These tests pin the DevicePolicy contract: purpose → device/ladder/VRAM/target
mapping, and user_override flipping device + counts_against_vram together.

REQ-1 AC1: THE SYSTEM SHALL derive n_ctx, n_gpu_layers, and n_batch from the
parsed model metadata (parameter count, quantization, architecture) and the
live hardware snapshot.

D-1: Single resolve_device_policy(purpose), not four if-guards.
D-2: Degrade ctx → batch (GPU only). n_gpu_layers ALWAYS -1 for chat.
     Never CPU offload. User override flips device AND counts_against_vram.
"""

import os
import pytest

# Ensure TARGET_TPS is deterministic for tests
os.environ.setdefault("IRIS_TARGET_TPS", "25")

from backend.agent.local_model_manager import (
    DevicePolicy,
    resolve_device_policy,
    TARGET_TPS,
    MIN_CTX,
    MAX_CTX,
)


class TestDevicePolicyContract:
    """Pin the DevicePolicy dataclass shape and immutability."""

    def test_is_frozen(self):
        """DevicePolicy must be frozen — callers must not mutate it."""
        policy = resolve_device_policy("chat")
        with pytest.raises(Exception):
            policy.device = "cpu"

    def test_fields(self):
        """DevicePolicy has exactly the four required fields."""
        policy = resolve_device_policy("chat")
        assert hasattr(policy, "device")
        assert hasattr(policy, "ladder")
        assert hasattr(policy, "counts_against_vram")
        assert hasattr(policy, "throughput_target")


class TestPurposeMapping:
    """D-1: purpose → device mapping (single function, not four if-guards)."""

    @pytest.mark.parametrize("purpose", ["chat", "tool"])
    def test_chat_and_tool_get_gpu(self, purpose):
        """chat and tool purposes → GPU device."""
        policy = resolve_device_policy(purpose)
        assert policy.device == "gpu"

    @pytest.mark.parametrize("purpose", ["embedding", "rerank"])
    def test_embedding_and_rerank_get_cpu(self, purpose):
        """embedding and rerank purposes → CPU device."""
        policy = resolve_device_policy(purpose)
        assert policy.device == "cpu"

    @pytest.mark.parametrize("purpose", ["chat", "tool"])
    def test_gpu_purposes_have_degradation_ladder(self, purpose):
        """GPU purposes get the ('ctx', 'batch') degradation ladder."""
        policy = resolve_device_policy(purpose)
        assert policy.ladder == ("ctx", "batch")

    @pytest.mark.parametrize("purpose", ["embedding", "rerank"])
    def test_cpu_purposes_have_empty_ladder(self, purpose):
        """CPU purposes get an empty degradation ladder — no degradation."""
        policy = resolve_device_policy(purpose)
        assert policy.ladder == ()

    @pytest.mark.parametrize("purpose", ["chat", "tool"])
    def test_gpu_purposes_count_against_vram(self, purpose):
        """GPU purposes count against the VRAM budget."""
        policy = resolve_device_policy(purpose)
        assert policy.counts_against_vram is True

    @pytest.mark.parametrize("purpose", ["embedding", "rerank"])
    def test_cpu_purposes_do_not_count_against_vram(self, purpose):
        """CPU purposes do NOT count against the VRAM budget."""
        policy = resolve_device_policy(purpose)
        assert policy.counts_against_vram is False

    @pytest.mark.parametrize("purpose", ["chat", "tool"])
    def test_gpu_purposes_have_throughput_target(self, purpose):
        """GPU purposes have a throughput target (TARGET_TPS)."""
        policy = resolve_device_policy(purpose)
        assert policy.throughput_target == TARGET_TPS

    @pytest.mark.parametrize("purpose", ["embedding", "rerank"])
    def test_cpu_purposes_have_no_throughput_target(self, purpose):
        """CPU purposes have no throughput target (None)."""
        policy = resolve_device_policy(purpose)
        assert policy.throughput_target is None


class TestUserOverride:
    """D-2: user_override flips device AND counts_against_vram together."""

    def test_override_gpu_on_cpu_purpose(self):
        """Overriding to GPU on an embedding purpose flips both device and VRAM."""
        policy = resolve_device_policy("embedding", user_override="gpu")
        assert policy.device == "gpu"
        assert policy.counts_against_vram is True

    def test_override_cpu_on_gpu_purpose(self):
        """Overriding to CPU on a chat purpose flips both device and VRAM."""
        policy = resolve_device_policy("chat", user_override="cpu")
        assert policy.device == "cpu"
        assert policy.counts_against_vram is False

    def test_override_gpu_on_chat_purpose(self):
        """Overriding to GPU on a chat purpose is a no-op (already GPU)."""
        policy = resolve_device_policy("chat", user_override="gpu")
        assert policy.device == "gpu"
        assert policy.counts_against_vram is True

    def test_override_cpu_on_embedding_purpose(self):
        """Overriding to CPU on an embedding purpose is a no-op (already CPU)."""
        policy = resolve_device_policy("embedding", user_override="cpu")
        assert policy.device == "cpu"
        assert policy.counts_against_vram is False

    def test_override_preserves_ladder(self):
        """Override does NOT change the ladder — ladder is purpose-based."""
        # chat → GPU ladder stays ("ctx", "batch") even if overridden to CPU
        policy = resolve_device_policy("chat", user_override="cpu")
        assert policy.ladder == ("ctx", "batch")

    def test_override_preserves_throughput_target(self):
        """Override does NOT change throughput_target — target is purpose-based."""
        # embedding → target stays None even if overridden to GPU
        policy = resolve_device_policy("embedding", user_override="gpu")
        assert policy.throughput_target is None


class TestErrorHandling:
    """Invalid inputs must raise ValueError."""

    @pytest.mark.parametrize("bad_purpose", ["", "unknown", "CHAT", "chat2", "123"])
    def test_invalid_purpose_raises(self, bad_purpose):
        with pytest.raises(ValueError, match="Unknown purpose"):
            resolve_device_policy(bad_purpose)

    @pytest.mark.parametrize("bad_override", ["", "gpu2", "cuda", "123", "gp", "gpu-cpu"])
    def test_invalid_override_raises(self, bad_override):
        with pytest.raises(ValueError, match="Invalid user_override"):
            resolve_device_policy("chat", user_override=bad_override)


class TestConstants:
    """Phase 3 constants must be present and sensible."""

    def test_target_tps_is_float(self):
        assert isinstance(TARGET_TPS, float)
        assert TARGET_TPS > 0

    def test_min_ctx_is_int(self):
        assert isinstance(MIN_CTX, int)
        assert MIN_CTX >= 1024

    def test_max_ctx_is_int(self):
        assert isinstance(MAX_CTX, int)
        assert MAX_CTX > MIN_CTX

    def test_min_ctx_floor(self):
        """MIN_CTX must be 4096 — the floor for context window shrinking."""
        assert MIN_CTX == 4096
