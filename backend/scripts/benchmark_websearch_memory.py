"""Websearch system-memory baseline harness (REQ-23, T34).

Measures OS process memory (Private Bytes on Windows, RSS fallback elsewhere)
before, at peak during, and after a standardized 5-URL websearch run through
``CrawlOrchestrator.dispatch_urls`` — so the "little-to-no spike" expectation
is a grounded number, not an assumption.

Reuse (do NOT duplicate): the psutil pattern is IMPORTED from
``scripts/measure_memory.py`` (``_is_iris_process`` / ``_mem_mb`` /
``measure()`` / ``_IRIS_MARKERS``), which already covers ``crawl_worker`` and
``browser_pool``. Contract lock CT-4 pins that marker coverage.

Attribution (why the driver is a separate row): the standardized run executes
in THIS process (in-process ``dispatch_urls`` drive, exactly as AC23.1 names
it). IRIS table rows therefore exclude our own PID (our path contains the
``backend`` marker, so we would otherwise count ourselves), and the driver's
own footprint is tracked as an explicit ``driver (self)`` row — otherwise the
fetch-induced growth would be invisible and the headline delta vacuous.
Driver imports are completed BEFORE the idle snapshot so import cost never
pollutes the delta. Chromium/playwright child processes are non-python (the
shared ``measure()`` pattern only matches python); their RSS is rolled up per
parent in the Child MB column so browser memory stays visible without touching
the locked ``measure_memory.py``.

Usage:
    python backend/scripts/benchmark_websearch_memory.py                 # live 5-URL run + 60s settle
    python backend/scripts/benchmark_websearch_memory.py --sample-only   # print current table, no run
    python backend/scripts/benchmark_websearch_memory.py --assert-websearch
        # fail (exit 1) when a pinned bound is breached. Bounds default to the
        # T36-pinned values (IRIS peak 50 / IRIS return 25 / driver peak 350 MB);
        # env overrides win:
        #   IRIS_WEBSEARCH_PEAK_DELTA_MB, IRIS_WEBSEARCH_RETURN_DELTA_MB,
        #   DRIVER_WEBSEARCH_PEAK_DELTA_MB.

Exit codes: 0 ok / report-only; 1 bound breach, resident worker left behind, or
no IRIS processes with an assertion flag; 2 harness error (bad import, ...).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import threading
import time

_THIS_FILE = os.path.abspath(__file__)
# backend/scripts/<this> -> backend -> repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_FILE)))
_MEASURE_MOD_PATH = os.path.join(_REPO_ROOT, "scripts", "measure_memory.py")

# Standardized run (AC23.1): 5 lightweight, stable URLs at the default
# CRAWL_CONCURRENCY=3. Includes clean-domain fetches; race outcomes are logged
# per URL so race overhead is represented, not hidden (AC edge case).
DEFAULT_URLS = [
    "https://example.com",
    "https://example.org",
    "https://www.iana.org/domains/reserved",
    "https://www.python.org",
    "https://www.w3.org",
]
DEFAULT_QUERY = "websearch memory baseline probe"
DEFAULT_CADENCE_S = 1.0
DEFAULT_SETTLE_S = 60.0

PEAK_BOUND_ENV = "IRIS_WEBSEARCH_PEAK_DELTA_MB"
RETURN_BOUND_ENV = "IRIS_WEBSEARCH_RETURN_DELTA_MB"
DRIVER_PEAK_BOUND_ENV = "DRIVER_WEBSEARCH_PEAK_DELTA_MB"

# Pinned defaults (T36, from the 2026-09-06 live baseline: 5 clean URLs x2,
# 5/5 usable, ~3s/iter — IRIS +0.0MB peak/return, driver +297MB first-touch
# import commit with ~0MB incremental on iteration 2). Env overrides win.
# Driver return is deliberately unbounded: the one-time import commit is
# retained by design; accumulation across repeats would surface in the peak.
DEFAULT_PEAK_BOUND_MB = 50.0
DEFAULT_RETURN_BOUND_MB = 25.0
DEFAULT_DRIVER_PEAK_BOUND_MB = 350.0


def _load_measure_module():
    """Import scripts/measure_memory.py by path (no sys.path/package assumptions)."""
    if not os.path.isfile(_MEASURE_MOD_PATH):
        raise FileNotFoundError(f"measure module not found: {_MEASURE_MOD_PATH}")
    spec = importlib.util.spec_from_file_location("iris_measure_memory", _MEASURE_MOD_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load measure module: {_MEASURE_MOD_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _child_mb(pid: int) -> float:
    """RSS of all descendant processes (browser children are non-python)."""
    import psutil  # noqa: PLC0415 - lazy: sampling-only dependency

    try:
        total = 0.0
        for child in psutil.Process(pid).children(recursive=True):
            try:
                total += child.memory_info().rss / (1024 ** 2)
            except Exception:  # noqa: BLE001 - vanished child, ignore
                continue
        return total
    except Exception:  # noqa: BLE001 - vanished parent, ignore
        return 0.0


def _snapshot(measure_mod):
    """Return (iris_rows, driver_row). Driver tracked separately (see docstring)."""
    own = os.getpid()
    iris_rows = []
    driver_row = None
    for r in measure_mod.measure():
        r = dict(r)
        r["child_mb"] = _child_mb(r["pid"])
        if r["pid"] == own:
            r["name"] = "driver (self)"
            driver_row = r
        else:
            iris_rows.append(r)
    if driver_row is None:
        # Own cmdline did not match the IRIS markers (e.g. odd launcher):
        # synthesize the driver row directly so it is never invisible.
        try:
            priv, wset = measure_mod._mem_mb(__import__("psutil").Process(own))
        except Exception:  # noqa: BLE001 - as a last resort report zeros
            priv, wset = 0.0, 0.0
        driver_row = {"pid": own, "name": "driver (self)",
                      "private_mb": priv, "wset_mb": wset,
                      "child_mb": _child_mb(own)}
    return iris_rows, driver_row


def _total_private(rows) -> float:
    return sum(r.get("private_mb", 0.0) for r in rows)


def _print_table(iris_rows, driver_row, title: str) -> None:
    print(f"--- {title} ---")
    rows = list(iris_rows) + ([driver_row] if driver_row else [])
    if not iris_rows:
        print("No IRIS backend processes found (is the backend running?).")
    print(f"{'PID':>7}  {'Process':<24} {'Private MB':>12} {'WorkingSet MB':>14} {'Child MB':>10}")
    print("-" * 74)
    for r in rows:
        print(
            f"{r['pid']:>7}  {r['name']:<24} "
            f"{r['private_mb']:>12.1f} {r['wset_mb']:>14.1f} {r.get('child_mb', 0.0):>10.1f}"
        )
    print("-" * 74)
    print(f"TOTAL IRIS private: {_total_private(iris_rows):.1f} MB"
          + (f" | driver: {driver_row['private_mb']:.1f} MB" if driver_row else ""))


def _resident_crawl_workers():
    """PIDs running crawl_worker in resident --serve mode (AC23.4)."""
    import psutil  # noqa: PLC0415 - lazy: sampling-only dependency

    found = []
    own = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.pid == own:
                continue
            cmdline = " ".join(proc.cmdline() or []).lower()
            if "crawl_worker" in cmdline and "--serve" in cmdline:
                found.append(proc.pid)
        except Exception:  # noqa: BLE001 - vanished process, ignore
            continue
    return found


def _preimport_driver():
    """Import the fetch pipeline BEFORE the idle snapshot (import cost stays out of the delta)."""
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    import backend.crawler.orchestrator  # noqa: PLC0415, F401


def _run_standard_search(urls, query, job_id, concurrency, timeout_s, events):
    """Drive dispatch_urls in-process (heavy imports already warmed by _preimport_driver)."""
    from backend.crawler.orchestrator import CrawlOrchestrator  # noqa: PLC0415
    import asyncio  # noqa: PLC0415

    async def _go():
        orch = CrawlOrchestrator()

        def _on_progress(prog):
            try:
                events.append(
                    {
                        "event": getattr(prog, "event", "?"),
                        "url": (getattr(prog, "payload", None) or {}).get("url", ""),
                    }
                )
            except Exception:  # noqa: BLE001 - progress must never break the run
                pass

        return await orch.dispatch_urls(
            urls,
            query=query,
            job_id=job_id,
            on_progress=_on_progress,
            concurrency_limit=concurrency,
            timeout_s=timeout_s,
        )

    return asyncio.run(_go())


def _env_bound(name):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print(f"WARNING: ignoring unparsable bound {name}={raw!r}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-only", action="store_true",
                        help="print the current per-process table and exit (no search run)")
    parser.add_argument("--assert-websearch", action="store_true",
                        help="fail (exit 1) when a pinned bound is breached")
    parser.add_argument("--urls", default=",".join(DEFAULT_URLS),
                        help="comma-separated URLs (empty string = drive path with no fetches)")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--job-id", default="")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout-s", type=float, default=90.0)
    parser.add_argument("--repeat", type=int, default=1,
                        help="run the standardized search N times in-process; "
                             "iteration 1 absorbs one-time import commit, later "
                             "iterations show the true incremental per-search cost")
    parser.add_argument("--cadence-s", type=float, default=DEFAULT_CADENCE_S)
    parser.add_argument("--settle-s", type=float, default=DEFAULT_SETTLE_S)
    parser.add_argument("--json", action="store_true",
                        help="also print the machine-readable result blob as JSON")
    args = parser.parse_args()

    try:
        measure_mod = _load_measure_module()
    except Exception as exc:  # noqa: BLE001 - harness error, not a bound breach
        print(f"HARNESS ERROR: {exc}")
        return 2

    if not args.sample_only:
        try:
            _preimport_driver()
        except Exception as exc:  # noqa: BLE001 - surface drive-import errors explicitly
            print(f"HARNESS ERROR during driver pre-import: {exc}")
            return 2

    iris_idle, driver_idle = _snapshot(measure_mod)
    _print_table(iris_idle, driver_idle, "idle (before run)")
    if not iris_idle:
        # Same convention as measure_memory.py --assert-idle (REQ-23 edge case).
        if args.assert_websearch:
            print("ASSERT: no IRIS processes found -> FAIL")
            return 1
        if args.sample_only:
            return 0

    if args.sample_only:
        return 0

    workers_before = set(_resident_crawl_workers())
    urls = [u.strip() for u in args.urls.split(",") if u.strip()]
    base_job_id = args.job_id or f"mem-baseline-{int(time.time())}"
    repeats = max(1, args.repeat)
    print(f"STANDARD RUN: {len(urls)} URLs x{repeats}, concurrency={args.concurrency}, "
          f"job_id={base_job_id}")

    # Peak sampler: out-of-process pattern, zero crawl-hot-path instrumentation.
    iris_base = _total_private(iris_idle)
    driver_base = driver_idle["private_mb"] if driver_idle else 0.0
    peak = {"iris": iris_base, "driver": driver_base,
            "iris_rows": iris_idle, "driver_row": driver_idle}
    stop = threading.Event()

    def _poll():
        while not stop.wait(args.cadence_s):
            try:
                iris_rows, driver_row = _snapshot(measure_mod)
            except Exception:  # noqa: BLE001 - sampling must never break the run
                continue
            iris_total = _total_private(iris_rows)
            driver_total = driver_row["private_mb"] if driver_row else 0.0
            if iris_total > peak["iris"]:
                peak["iris"] = iris_total
                peak["iris_rows"] = iris_rows
            if driver_total > peak["driver"]:
                peak["driver"] = driver_total
                peak["driver_row"] = driver_row

    sampler = threading.Thread(target=_poll, name="mem-peak-sampler", daemon=True)
    sampler.start()
    try:
        events: list = []
        iter_summaries = []
        for i in range(repeats):
            job_id = base_job_id if repeats == 1 else f"{base_job_id}-iter{i + 1}"
            result = _run_standard_search(
                urls, args.query, job_id, args.concurrency, args.timeout_s, events
            )
            try:
                usable = sum(1 for p in (result.pages or []) if not p.error)
                total_pages = len(result.pages or [])
                summary = (f"iter{i + 1}: {usable}/{total_pages} usable, "
                           f"duration_ms={getattr(result, 'duration_ms', '?')}")
                print(f"RUN DONE {summary}")
                iter_summaries.append(summary)
            except Exception:  # noqa: BLE001 - result introspection is informational
                pass
    except Exception as exc:  # noqa: BLE001 - surface drive errors explicitly
        stop.set()
        sampler.join(timeout=5)
        print(f"HARNESS ERROR during standard run: {exc}")
        return 2
    finally:
        stop.set()
    sampler.join(timeout=5)

    raced = sorted({e["url"] for e in events if e.get("event") == "CRAWLER_PAGE_FETCHED"})
    if raced:
        print(f"PAGES FETCHED ({len(raced)}): " + ", ".join(raced[:8]))

    _print_table(peak["iris_rows"], peak["driver_row"], "peak (during run)")
    if args.settle_s > 0:
        print(f"SETTLING {args.settle_s:g}s (browser_pool 180s shutdown NOT required — directional)...")
        time.sleep(args.settle_s)
    iris_final, driver_final = _snapshot(measure_mod)
    _print_table(iris_final, driver_final, "return-to-idle (after settle)")

    iris_peak_delta = peak["iris"] - iris_base
    driver_peak_delta = peak["driver"] - driver_base
    iris_return_delta = _total_private(iris_final) - iris_base
    driver_return_delta = (driver_final["private_mb"] if driver_final else 0.0) - driver_base
    print(f"IRIS PEAK DELTA: {iris_peak_delta:+.1f} MB over idle ({iris_base:.1f} MB)")
    print(f"DRIVER PEAK DELTA: {driver_peak_delta:+.1f} MB over idle ({driver_base:.1f} MB)")
    print(f"IRIS RETURN DELTA: {iris_return_delta:+.1f} MB vs idle (pool-warm caveat may apply)")
    print(f"DRIVER RETURN DELTA: {driver_return_delta:+.1f} MB vs idle")

    workers_after = set(_resident_crawl_workers())
    leaked = sorted(workers_after - workers_before)
    if leaked:
        print(f"RESIDENT WORKER LEAK: crawl_worker --serve PIDs outliving the run: {leaked}")

    blob = {
        "iterations": iter_summaries,
        "iris_idle_private_mb": round(iris_base, 1),
        "iris_peak_private_mb": round(peak["iris"], 1),
        "iris_peak_delta_mb": round(iris_peak_delta, 1),
        "iris_return_private_mb": round(_total_private(iris_final), 1),
        "iris_return_delta_mb": round(iris_return_delta, 1),
        "driver_idle_private_mb": round(driver_base, 1),
        "driver_peak_delta_mb": round(driver_peak_delta, 1),
        "driver_return_delta_mb": round(driver_return_delta, 1),
        "resident_workers_before": sorted(workers_before),
        "resident_workers_after": sorted(workers_after),
        "bound_unverified": False,  # overwritten below once defaults resolve
    }
    peak_bound = _env_bound(PEAK_BOUND_ENV)
    if peak_bound is None:
        peak_bound = DEFAULT_PEAK_BOUND_MB
    return_bound = _env_bound(RETURN_BOUND_ENV)
    if return_bound is None:
        return_bound = DEFAULT_RETURN_BOUND_MB
    driver_peak_bound = _env_bound(DRIVER_PEAK_BOUND_ENV)
    if driver_peak_bound is None:
        driver_peak_bound = DEFAULT_DRIVER_PEAK_BOUND_MB
    blob["bound_unverified"] = False
    blob["bounds_mb"] = {"iris_peak": peak_bound, "iris_return": return_bound,
                         "driver_peak": driver_peak_bound}
    if args.json:
        print(json.dumps(blob))

    failures = []
    if leaked:
        failures.append(f"resident crawl_worker --serve outlived the run: {leaked} (AC23.4)")
    if args.assert_websearch:
        if iris_peak_delta > peak_bound:
            failures.append(f"IRIS peak delta {iris_peak_delta:.1f} MB > bound {peak_bound:.1f} MB")
        if return_bound is not None and iris_return_delta > return_bound:
            failures.append(f"IRIS return delta {iris_return_delta:.1f} MB > bound {return_bound:.1f} MB")
        if driver_peak_delta > driver_peak_bound:
            failures.append(f"driver peak delta {driver_peak_delta:.1f} MB > bound {driver_peak_bound:.1f} MB")
        if not iris_idle:
            failures.append("no IRIS processes found")
    if failures:
        print("ASSERT -> FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ASSERT -> PASS (bounds pinned T36; env overrides win)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
