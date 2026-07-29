"""
Phase 3 regression test (T6.4) — runs the standing CDD harness and asserts
all contract / behavioral assertions stay green. This is the automated
regression gate that replaces the manual T0.4/T0.3 comparison.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]  # backend/tests/unit -> repo root
HARNESS = ROOT / "scripts" / "validate_local_model_path.py"


@pytest.mark.skipif(
    not HARNESS.exists(),
    reason="CDD harness script not present",
)
def test_cdd_harness_passes():
    """The standing CDD harness must exit 0 (all 9 assertions green)."""
    result = subprocess.run(
        [sys.executable, str(HARNESS)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"CDD harness failed (rc={result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_mtp_profiles_retained():
    """REQ: balanced_mtp / force_subprocess must remain reachable (MTP not regressed)."""
    from backend.agent.local_model_manager import PROFILES

    assert "balanced_mtp" in PROFILES, "balanced_mtp profile must be retained"
    assert any(
        "force_subprocess" in v for v in PROFILES.values()
    ), "force_subprocess key must remain reachable in a profile"


def test_deriver_produces_distinct_contexts():
    """REQ-1 landed: the deriver yields different contexts for different models."""
    from backend.agent.local_model_manager import LocalModelManager

    mgr = LocalModelManager()
    SMALL = {"params_b": 0.2, "quantization": "Q8_0", "context_length": 32768}
    LARGE = {"params_b": 30.7, "quantization": "Q4_K_M", "context_length": 32768, "is_moe": True}
    c_s = mgr.derive_config(SMALL, vram_budget_gb=7.0, base_tps=120.0)
    c_l = mgr.derive_config(LARGE, vram_budget_gb=7.0, base_tps=25.0)
    assert c_s["n_ctx"] != c_l["n_ctx"], "deriver must differentiate by model"
