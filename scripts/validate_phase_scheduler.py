#!/usr/bin/env python3
"""
Standing CDD harness for the Caducean Phase Scheduler (T4.6).

Usage:
    python scripts/validate_phase_scheduler.py [--flag-on]

Expected exit code: 0 (pass).  Any failure prints one-line summary to stderr
and exits with code 1.

Phases:
  1. Run all contract tests  (tests/contract/test_rate_limit_error_contract.py,
                              tests/contract/test_quota_key_contract.py,
                              tests/contract/test_contract_phase_manager.py,
                              tests/contract/test_batch_contract.py)
  2. Run all unit tests      (tests/unit/test_retry_after_parse.py,
                              tests/unit/test_backoff_sleeps.py, ...)
  3. Run all behavioural     (tests/behavioral/test_rate_limit_honesty.py,
                              tests/behavioral/test_bounded_fanout.py, ...)
  4. Flag-on integration test  (set IRIS_PHASE_SCHEDULER=1, verify gate wake)
  5. Print summary
"""
import os
import subprocess
import sys
import time


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEBUG = os.environ.get("VALIDATE_DEBUG", "").lower() in ("1", "true")
INTER_CMD = [sys.executable, "-m", "pytest"]
FLAG = "IRIS_PHASE_SCHEDULER"


def _run(label: str, args: list, env_override: dict = None) -> int:
    _env = os.environ.copy()
    if env_override:
        _env.update(env_override)
    _target = args if args[0].startswith("-") else [
        os.path.join(ROOT, a) if not a.startswith("-") else a for a in args
    ]
    print(f"  [{label}] ...", end="", flush=True)
    _t0 = time.time()
    _ec = subprocess.call(
        INTER_CMD + _target, cwd=ROOT, env=_env,
        stdout=None if DEBUG else subprocess.DEVNULL,
        stderr=None if DEBUG else subprocess.DEVNULL,
    )
    _elapsed = time.time() - _t0
    _status = "PASS" if _ec == 0 else "FAIL"
    print(f"  {_status} ({_elapsed:.1f}s)")
    return _ec


def main() -> int:
    print("═" * 60)
    print("  Caducean Phase Scheduler — Standing CDD Harness")
    print("═" * 60)

    failures = 0

    # ── Phase 1: contract tests ──────────────────────────────────────────
    print("\n── Contract tests ──")
    failures += _run(
        "rate-limit error contract",
        ["-q", "--tb=line", "backend/tests/contract/test_rate_limit_error_contract.py"],
    )
    failures += _run(
        "quota-key contract",
        ["-q", "--tb=line", "backend/tests/contract/test_quota_key_contract.py"],
    )
    failures += _run(
        "phase-manager contract",
        ["-q", "--tb=line", "backend/tests/contract/test_contract_phase_manager.py"],
    )
    failures += _run(
        "batch contract",
        ["-q", "--tb=line", "backend/tests/contract/test_batch_contract.py"],
    )
    failures += _run(
        "scheduler isolation (CT-3/CT-4)",
        ["-q", "--tb=line", "backend/tests/contract/test_scheduler_isolation.py"],
    )

    # ── Phase 2: unit tests ─────────────────────────────────────────────
    print("\n── Unit tests ──")
    _unit_files = [
        "backend/tests/unit/test_retry_after_parse.py",
        "backend/tests/unit/test_backoff_sleeps.py",
        "backend/tests/unit/test_meter_window.py",
        "backend/tests/unit/test_ceiling_aimd.py",
        "backend/tests/unit/test_quota_key.py",
        "backend/tests/unit/test_trig_coupling.py",
        "backend/tests/unit/test_call_class.py",
        "backend/tests/unit/test_phase_math.py",
        "backend/tests/unit/test_amplitude_relaxation.py",
        "backend/tests/unit/test_gate_sync.py",
        "backend/tests/unit/test_batch_dispatch.py",
    ]
    failures += _run("all units", ["-q", "--tb=line"] + _unit_files)

    # ── Phase 3: behavioural tests ───────────────────────────────────────
    print("\n── Behavioural tests ──")
    _beh_files = [
        "backend/tests/behavioral/test_rate_limit_honesty.py",
        "backend/tests/behavioral/test_bounded_fanout.py",
        "backend/tests/behavioral/test_local_provider_never_gated.py",
        "backend/tests/behavioral/test_batch_attribution.py",
        "backend/tests/behavioral/test_batch_parse_failure_fallback.py",
        "backend/tests/behavioral/test_batch_never_holds_fast_child.py",
        "backend/tests/behavioral/test_gate_resets_on_admit.py",
        "backend/tests/behavioral/test_priority_lane_never_waits.py",
        "backend/tests/behavioral/test_shared_quota_is_coupled.py",
        "backend/tests/behavioral/test_flag_off_is_identical.py",
        "backend/tests/behavioral/test_phase_physics_invariance.py",
    ]
    failures += _run("all behavioural", ["-q", "--tb=line"] + _beh_files)

    # ── Phase 4: flag-on integration ──────────────────────────────────────
    print("\n── Flag-on integration ──")
    _ec = _run("gate (flag-on)", [
        "-q", "--tb=line", "backend/tests/unit/test_gate_sync.py",
    ], env_override={FLAG: "1"})
    if _ec == 0:
        failures += _run("attribution (flag-on)", [
            "-q", "--tb=line", "backend/tests/behavioral/test_batch_attribution.py",
        ], env_override={FLAG: "1"})
    else:
        print("  [gate (flag-on)]  SKIP (gate test failed)")
        failures += 1

    # ── Phase 5: inter-request-gap stddev reduction (REQ-20 AC6 / REQ-22 AC7) ──
    print("\n── Inter-request gap spacing (REQ-22 AC6/AC7) ──")
    # REPLACED (review finding N3): this phase previously ran
    # test_phase_physics_invariance::test_stddev_reduction_at_fixed_point, which
    # asserted per-oscillator FORCES are ~0 at 2pi/3 spacing. That is pure math —
    # it issues no request, never touches the gate, and returns the IDENTICAL
    # result with the flag off, so it could not distinguish flag-on from flag-off
    # and would not have caught the F1/F2/F3 blockers that made the gate inert.
    #
    # test_gap_stddev_reduction.py measures REAL inter-request spacing from the
    # rate meter and asserts (a) gap_stats reports request deltas rather than
    # advance staleness, (b) evenly-spread arrivals have >=50% lower gap stddev
    # than a burst of the same count, (c) the gate issues a NON-ZERO wait for a
    # non-priority class when a shared quota is saturated — the assertion an
    # inert scheduler fails — and (d) priority calls still never wait.
    _ec_gap = _run("gap stddev + gate engages (flag-on)", [
        "-q", "--tb=line",
        "backend/tests/behavioral/test_gap_stddev_reduction.py",
    ], env_override={FLAG: "1"})
    _ec_amp = _run("amplitude modulates velocity", [
        "-q", "--tb=line",
        "backend/tests/unit/test_amplitude_modulates_velocity.py",
    ], env_override={FLAG: "1"})
    if _ec_gap == 0 and _ec_amp == 0:
        print("  [gap-stddev]  PASS (>=50% reduction; gate engages; amplitude live)")
    else:
        print("  [gap-stddev]  FAIL — spacing/amplitude guard failed")
        failures += 1

    # ── Phase 6: order-independence (REQ-22 AC5 / review finding N2) ──────
    # The scheduler uses process-wide singletons and a persisted ceilings file.
    # Before the shared conftest fixture, two tests passed alone and failed in the
    # full run. Re-run the scheduler set in REVERSED collection order; a leak
    # shows up as a pass-alone/fail-together discrepancy.
    print("\n── Order independence (REQ-22 AC5) ──")
    _sched_tests = [
        "backend/tests/unit/test_phase_math.py",
        "backend/tests/unit/test_gate_sync.py",
        "backend/tests/unit/test_amplitude_modulates_velocity.py",
        "backend/tests/behavioral/test_gate_resets_on_admit.py",
        "backend/tests/behavioral/test_priority_lane_never_waits.py",
        "backend/tests/behavioral/test_flag_off_is_identical.py",
        "backend/tests/behavioral/test_shared_quota_is_coupled.py",
        "backend/tests/behavioral/test_gap_stddev_reduction.py",
        "backend/tests/contract/test_scheduler_isolation.py",
        "backend/tests/contract/test_concurrent_exec_contract.py",
    ]
    _ec_fwd = _run("forward order", ["-q", "--tb=line", *_sched_tests])
    _ec_rev = _run("reversed order", ["-q", "--tb=line", *reversed(_sched_tests)])
    if _ec_fwd == 0 and _ec_rev == 0:
        print("  [order-independence]  PASS (green in both collection orders)")
    else:
        print("  [order-independence]  FAIL — state leaks between tests")
        failures += 1

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    if failures == 0:
        print("  ALL PASS — scheduler green.")
        return 0
    print(f"  {failures} failure(s) — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
