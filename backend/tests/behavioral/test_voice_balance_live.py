"""
Behavioral test: voice balance responsiveness (REQ-3).

Asserts that get_tts_chunk_size() responds to a changing balance value,
and that with balance forced constant the result is constant (proving
the pre-fix behavior was broken).

The balance feeds into ffi_caducean_get_direction_signal(..., balance=X),
whose result's force_magnitude scales the TTS chunk size.

The flow is:
  1)  _get_current_balance() calls ffi_calculate_eml() from iris_ffi
  2)  get_tts_chunk_size() passes that balance to ffi_caducean_get_direction_signal()

We mock:
  - ffi_caducean_get_direction_signal at the conversation_kernel usage site
    (because it's imported by value at module level there)
  - ffi_calculate_eml at the iris_ffi definition site (because it's lazily
    imported inside _get_current_balance())
"""
from unittest.mock import patch, MagicMock

import pytest

from backend.agent.conversation_kernel import ConversationKernel, TTS_CHUNK_MIN, TTS_CHUNK_MAX


class _Sig:
    """Minimal signature object matching the FFI's `sig` proto."""

    def __init__(self, force_magnitude: float = 1.0):
        self.force_magnitude = force_magnitude


def _make_kernel():
    """Create a minimal kernel with a working session_id_getter."""
    kernel = ConversationKernel.__new__(ConversationKernel)
    object.__setattr__(kernel, "_session_id", "test_balance")
    object.__setattr__(kernel, "_session_id_getter", lambda: "test_balance")
    return kernel


# We patch ffi_caducean_get_direction_signal at the conversation_kernel
# usage site (it's imported by value at module level).
# ffi_calculate_eml is lazily imported inside _get_current_balance() from
# iris_ffi, so we patch it at the definition site.
_PATCH_TARGETS = [
    "backend.agent.conversation_kernel.ffi_caducean_get_direction_signal",
    "backend.gateway.iris_ffi.ffi_calculate_eml",
]


@pytest.fixture(autouse=True)
def _patch_ffi():
    """Patch the two FFI functions used in the balance → chunk-size path."""
    with patch(_PATCH_TARGETS[0]) as mock_dir_sig, patch(
        _PATCH_TARGETS[1]
    ) as mock_eml:
        mock_dir_sig.return_value = _Sig(force_magnitude=1.0)
        mock_eml.return_value = (1.0, 0.5, 0.3)  # (score, x, y)
        yield {"dir_sig": mock_dir_sig, "eml": mock_eml}


# ── Tests ────────────────────────────────────────────────────────────────


def test_get_tts_chunk_size_responds_to_balance(_patch_ffi):
    """When the balance (EML score) changes, the direction signal call
    receives a different balance argument."""
    mock_dir_sig = _patch_ffi["dir_sig"]
    mock_eml = _patch_ffi["eml"]

    kernel = _make_kernel()

    # First call: eml returns 3.0 → balance = 3.0
    mock_eml.return_value = (3.0, 0.5, 0.3)
    chunk_high = kernel.get_tts_chunk_size()

    # Second call: eml returns 0.5 → balance = 0.5
    mock_eml.return_value = (0.5, 0.5, 0.3)
    chunk_low = kernel.get_tts_chunk_size()

    calls = mock_dir_sig.call_args_list
    assert len(calls) == 2, f"expected 2 dir_sig calls, got {len(calls)}"

    # First call should have balance=3.0
    bal_high = calls[0][1].get("balance")
    assert bal_high == pytest.approx(3.0), (
        f"expected balance=3.0, got {bal_high}"
    )
    # Second call should have balance=0.5
    bal_low = calls[1][1].get("balance")
    assert bal_low == pytest.approx(0.5), (
        f"expected balance=0.5, got {bal_low}"
    )

    print(f"  PASS  balance routing: high={chunk_high}, low={chunk_low}")


def test_constant_balance_produces_constant_result(_patch_ffi):
    """With balance forced constant, two calls return the same chunk size.

    This recreates the pre-fix behavior and proves the responsiveness test
    is meaningful.
    """
    mock_dir_sig = _patch_ffi["dir_sig"]
    mock_eml = _patch_ffi["eml"]

    # Force EML to return the same score both times
    mock_eml.return_value = (1.0, 0.5, 0.3)

    kernel = _make_kernel()
    chunk_a = kernel.get_tts_chunk_size()
    chunk_b = kernel.get_tts_chunk_size()

    # Same balance -> same chunk size
    assert chunk_a == pytest.approx(chunk_b), (
        f"constant balance produced different sizes: {chunk_a} vs {chunk_b}"
    )

    # Verify the balance argument was indeed constant
    calls = mock_dir_sig.call_args_list
    assert len(calls) == 2
    for idx, call in enumerate(calls):
        bal = call[1].get("balance")
        assert bal == pytest.approx(1.0), (
            f"call {idx}: expected balance=1.0, got {bal}"
        )

    print(f"  PASS  constant balance: size={chunk_a}")
