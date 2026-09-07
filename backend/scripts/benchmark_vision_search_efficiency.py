"""Vision-search efficiency benchmark (REQ-2 success criterion, T33).

Executes standardized websearch extraction runs and measures the
vision-guided efficiency win: targeted hybrid dispatch (race + escalation +
early schema termination) against a crawl-only baseline over the SAME url
set and output_schema.

Metrics (per run): wall latency, pages fetched, estimated tokens
(`len(markdown) // 4` per page — a stated heuristic, not a billing meter).
Reduction = 1 - hybrid/baseline, reported for latency AND tokens.

Usage (live gate — needs network; NOT run in CI):
    python backend/scripts/benchmark_vision_search_efficiency.py
    python backend/scripts/benchmark_vision_search_efficiency.py --assert-efficiency
        # exit 1 unless BOTH reductions are >= 40% (env override:
        # IRIS_VISION_EFFICIENCY_MIN_REDUCTION, default 0.40).

Exit codes: 0 ok / report-only; 1 efficiency bound breached with --assert;
2 harness error (bad import, no usable pages, ...). Run from the repo root.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

DEFAULT_URLS = [
    "https://example.com",
    "https://example.org",
    "https://www.iana.org/domains/reserved",
    "https://www.python.org",
    "https://www.w3.org",
]
DEFAULT_QUERY = "benchmark extraction probe"
DEFAULT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["title"],
}
MIN_REDUCTION_ENV = "IRIS_VISION_EFFICIENCY_MIN_REDUCTION"
DEFAULT_MIN_REDUCTION = 0.40


def _estimate_tokens(text: str) -> int:
    return len(text or "") // 4


def _extract_title(page) -> dict | None:
    """Projection hook for the hybrid leg: title = first non-empty line of
    markdown. Lets AC2.3 early termination fire once the schema is
    satisfied — the specified token-saving mechanism under test."""
    try:
        for line in (page.markdown or "").splitlines():
            s = line.strip(" #*\t")
            if s:
                return {"title": s[:120]}
    except Exception:  # noqa: BLE001 — projection never fails the run
        return None
    return None


def _run_dispatch(urls: list, *, query: str, schema: dict, job_id: str,
                  crawl_only: bool, extract=None) -> dict:
    _this = os.path.abspath(__file__)
    _root = os.path.dirname(os.path.dirname(os.path.dirname(_this)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from backend.crawler import capabilities as caps_mod
    from backend.crawler.orchestrator import CrawlOrchestrator

    orch = CrawlOrchestrator()
    orch._backend_override = None
    if crawl_only:
        saved = dict(caps_mod.CAPABILITIES)
        caps_mod.CAPABILITIES.pop("fetch.vision", None)
    else:
        saved = None
    try:
        t0 = time.monotonic()
        result = asyncio.run(
            orch.dispatch_urls(
                list(urls), query=query, job_id=job_id,
                concurrency_limit=3, max_pages=len(urls),
                output_schema=None if crawl_only else dict(schema),
                extract=extract,
            )
        )
        latency_s = time.monotonic() - t0
    finally:
        if saved is not None:
            caps_mod.CAPABILITIES.clear()
            caps_mod.CAPABILITIES.update(saved)
    pages = result.pages or []
    tokens = sum(_estimate_tokens(p.markdown) for p in pages)
    return {
        "job_id": job_id,
        "latency_s": round(latency_s, 2),
        "pages": len(pages),
        "tokens_est": tokens,
        "error": result.error,
    }


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assert-efficiency", action="store_true")
    ap.add_argument("--min-reduction", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    floor = args.min_reduction
    if floor is None:
        try:
            floor = float(os.environ.get(MIN_REDUCTION_ENV,
                                         DEFAULT_MIN_REDUCTION))
        except ValueError:
            floor = DEFAULT_MIN_REDUCTION

    try:
        base = _run_dispatch(DEFAULT_URLS, query=DEFAULT_QUERY,
                             schema=DEFAULT_SCHEMA, job_id="bench-baseline",
                             crawl_only=True)
        hybrid = _run_dispatch(DEFAULT_URLS, query=DEFAULT_QUERY,
                               schema=DEFAULT_SCHEMA, job_id="bench-hybrid",
                               crawl_only=False, extract=_extract_title)
    except Exception as exc:  # noqa: BLE001 — harness error, not a breach
        print(f"harness error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if not base["pages"] and not hybrid["pages"]:
        print("harness error: no usable pages in either run", file=sys.stderr)
        return 2

    def _reduction(b: float, h: float) -> float | None:
        return round(1.0 - h / b, 4) if b > 0 else None

    report = {
        "baseline_crawl_only": base,
        "hybrid": hybrid,
        "latency_reduction": _reduction(base["latency_s"], hybrid["latency_s"]),
        "token_reduction": _reduction(base["tokens_est"], hybrid["tokens_est"]),
        "target_reduction": floor,
        "token_heuristic": "len(markdown)//4 per page",
    }
    print(json.dumps(report, indent=2) if args.json else
          f"baseline: {base['latency_s']}s {base['pages']} pages "
          f"~{base['tokens_est']} tok | hybrid: {hybrid['latency_s']}s "
          f"{hybrid['pages']} pages ~{hybrid['tokens_est']} tok | "
          f"latency -{report['latency_reduction']} / tokens "
          f"-{report['token_reduction']} (target -{floor})")
    if args.assert_efficiency:
        for key in ("latency_reduction", "token_reduction"):
            val = report[key]
            if val is None or val < floor:
                print(f"BREACH: {key}={val} < {floor}", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
