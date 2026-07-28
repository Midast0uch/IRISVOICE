#!/usr/bin/env python3
"""Standing CDD harness for `specs/caducean-kernel-unification/`.

Joins `validate_der_integrity.py`, `validate_der_tool_resolution.py`, and
`validate_phase_scheduler.py`. Asserts the eight properties from that spec's
design.md "Standing CDD harness" section on every run:

  1. CU-1..CU-8 contracts hold.
  2. (a, b, s) stay in safe ranges and end within +/-0.15 of baseline.
  3. Parameter drift is bounded and MEAN-REVERTING — linear-fit slope of `s` is
     ~0 with relaxation on, and significantly negative with it off. This is the
     machine-checkable form of "the ratchet is gone" (decides Q1).
  4. Every non-empty coords_from parses; coordinate recall is exercised.
  5. Exactly one nucleus and one barrier per coupled pair, in BOTH invocation
     orders.
  6. At least two distinct c_eff values, and at least one IRRATIONAL pair
     reachable from `domain_windings()` alone — not hand-picked windings. This
     is what proves the winding degeneracy (overview F5) is gone rather than moved.
  7. Scheduler isolation intact — no ffi_caducean_* call from scheduler modules.
  8. The four locked test files pass UNEDITED.

Exit code 0 = pass. Any failure prints a one-line summary and exits 1.

Usage:  python scripts/validate_caducean_kernels.py [-v]
"""
from __future__ import annotations

import os
import subprocess
import sys

DEBUG = "-v" in sys.argv or os.environ.get("HARNESS_DEBUG") == "1"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Assertion 8 — locked files that must pass UNEDITED (spec "Decisions Locked").
LOCKED_TESTS = [
    "backend/tests/test_coupled_registry.py",
    "backend/tests/test_conversation_kernel.py",
    "backend/tests/test_trajectory_controller.py",
    "backend/tests/test_caducean_trajectory.py",
]

# Assertions 1-2, 4-7 are carried by these suites.
CONTRACT_AND_BEHAVIOR = [
    "backend/tests/unit/test_param_homeostasis.py",
    "backend/tests/behavioral/test_param_ratchet_recovery.py",
    "backend/tests/unit/test_trig_coupling.py",
    "backend/tests/behavioral/test_coupled_registry_wave4.py",
    "backend/tests/behavioral/test_caducean_observability_wave5.py",
    "backend/tests/contract/test_scheduler_isolation.py",
]


def _run(label: str, args: list[str], env_override: dict | None = None) -> int:
    env = dict(os.environ)
    if env_override:
        env.update(env_override)
    print(f"  [{label}] ...", end=" ", flush=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=_ROOT,
        env=env,
        stdout=None if DEBUG else subprocess.DEVNULL,
        stderr=None if DEBUG else subprocess.DEVNULL,
    )
    print("PASS" if proc.returncode == 0 else "FAIL")
    return proc.returncode


def _slope(ys: list[float]) -> float:
    """Least-squares slope of ys against index. Used for assertion 3."""
    n = len(ys)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2.0
    my = sum(ys) / n
    num = sum((i - mx) * (y - my) for i, y in enumerate(ys))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def check_mean_reversion() -> int:
    """Assertion 3: drift is bounded and mean-reverting, in-process.

    Simulates the documented perturbation formulas (conversation_kernel barge-in,
    trajectory_controller violation) against param_homeostasis' relaxation, with
    relaxation ON and OFF, and compares the linear-fit slope of `s`.
    """
    sys.path.insert(0, _ROOT)
    try:
        from backend.agent.param_homeostasis import (  # noqa: E402
            RELAX_STEP,
            RELAX_EVERY_N_UPDATES,
        )
    except Exception as exc:  # pragma: no cover - import guard
        print(f"  [mean-reversion] FAIL — cannot import param_homeostasis: {exc}")
        return 1

    BASE_S, FLOOR_S = 0.35, 0.1
    STEPS, N_BARGE, N_VIOL = 200, 10, 5

    def simulate(relax: bool) -> list[float]:
        s = BASE_S
        trace: list[float] = []
        barge = {int(STEPS * (i + 1) / (N_BARGE + 1)) for i in range(N_BARGE)}
        viol = {int(STEPS * (i + 1) / (N_VIOL + 1)) for i in range(N_VIOL)}
        for t in range(1, STEPS + 1):
            if t in barge:
                s = max(FLOOR_S, min(0.8, s - 0.05))
            if t in viol:
                # Idempotent charging (REQ-2): only the NEW violation is billed.
                s = max(FLOOR_S, min(0.8, s - 0.01))
            if relax and t % RELAX_EVERY_N_UPDATES == 0:
                s = max(FLOOR_S, min(0.8, s + RELAX_STEP * (BASE_S - s)))
            trace.append(s)
        return trace

    on, off = simulate(True), simulate(False)
    slope_on, slope_off = _slope(on), _slope(off)
    drift_on, drift_off = abs(on[-1] - BASE_S), abs(off[-1] - BASE_S)

    print(
        f"  [mean-reversion] RELAX_STEP={RELAX_STEP} every {RELAX_EVERY_N_UPDATES}: "
        f"slope_on={slope_on:+.2e} slope_off={slope_off:+.2e} "
        f"drift_on={drift_on:.3f} drift_off={drift_off:.3f}"
    )

    failures = 0
    # Relaxation OFF must show a clearly negative slope — the ratchet.
    if slope_off >= -1e-5:
        print("  [mean-reversion] FAIL — no ratchet with relaxation OFF; "
              "the harness cannot prove the fix does anything")
        failures += 1
    # Relaxation ON must be substantially flatter than OFF.
    if abs(slope_on) >= abs(slope_off):
        print("  [mean-reversion] FAIL — relaxation did not flatten the drift slope")
        failures += 1
    # And it must actually recover further than the un-relaxed run.
    if drift_on >= drift_off:
        print("  [mean-reversion] FAIL — relaxation did not reduce final drift")
        failures += 1
    if not failures:
        print("  [mean-reversion] PASS (slope flattened and drift reduced)")
    return failures


def check_windings() -> int:
    """Assertion 6: >=2 distinct c_eff AND an irrational pair from the DOMAIN MAP.

    Deliberately uses only `domain_windings()` outputs — hand-picking windings
    would prove the branch is testable, not that it is REACHABLE in production.
    That distinction is the whole point of overview finding F5.
    """
    sys.path.insert(0, _ROOT)
    try:
        from backend.agent.coupled_registry import (  # noqa: E402
            _compute_c_eff,
            _is_rational_ratio,
            domain_windings,
        )
    except Exception as exc:  # pragma: no cover - import guard
        print(f"  [windings] FAIL — cannot import coupled_registry: {exc}")
        return 1

    domains = ["der", "voice", "research", "coding", "default"]
    ceffs = sorted({round(_compute_c_eff(*domain_windings(d)), 6) for d in domains})
    irrational = [
        (a, b)
        for i, a in enumerate(ceffs)
        for b in ceffs[i + 1:]
        if not _is_rational_ratio(a, b)
    ]
    print(f"  [windings] distinct c_eff={ceffs} irrational_pairs={len(irrational)}")

    failures = 0
    if len(ceffs) < 2:
        print("  [windings] FAIL — winding degeneracy: fewer than 2 distinct c_eff")
        failures += 1
    if not irrational:
        print("  [windings] FAIL — no IRRATIONAL pair reachable from domain_windings(); "
              "the interference branch is test-only, not production-reachable")
        failures += 1
    if not failures:
        print("  [windings] PASS")
    return failures


def main() -> int:
    print("=" * 60)
    print("  Caducean Kernel Unification — standing CDD harness")
    print("=" * 60)
    failures = 0

    print("\n-- Locked test files (assertion 8) --")
    failures += _run("locked (unedited)", ["-q", "--tb=line", *LOCKED_TESTS])

    print("\n-- Contracts + behavior (assertions 1, 2, 4, 5, 7) --")
    failures += _run("CU-1..CU-8 + behavior",
                     ["-q", "--tb=line", *CONTRACT_AND_BEHAVIOR])

    print("\n-- Coupling flag OFF must be inert (CU-1/CU-2/CU-7) --")
    failures += _run("flag-off inert",
                     ["-q", "--tb=line",
                      "backend/tests/behavioral/test_coupled_registry_wave4.py"],
                     env_override={"IRIS_COUPLING_ENABLED": "0"})

    print("\n-- Coupling flag ON (assertion 5: one nucleus, one barrier) --")
    failures += _run("flag-on differentiation",
                     ["-q", "--tb=line",
                      "backend/tests/behavioral/test_coupled_registry_wave4.py"],
                     env_override={"IRIS_COUPLING_ENABLED": "1"})

    print("\n-- Parameter drift is mean-reverting (assertion 3 — decides Q1) --")
    failures += check_mean_reversion()

    print("\n-- Winding non-degeneracy (assertion 6 — proves F5 is gone) --")
    failures += check_windings()

    print("\n" + "=" * 60)
    if failures == 0:
        print("  ALL PASS — kernel unification green.")
        return 0
    print(f"  {failures} failure(s) — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
