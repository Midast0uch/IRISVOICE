"""T1 — Measure real capture sizes for the in-app browser surface.

Instruments the EXISTING CrawlerEngine against a representative mixed-site set
(>=5 jobs) and records the raw captured-HTML byte size per page. This is the
measured basis for two deliberately-unset bounds in
specs/in-app-browser-surface/requirements.md:

  1. REQ-1 AC5 retention bound (count + total bytes).
  2. The `srcdoc` vs sandboxed-HTTP-endpoint replay transport Open Question.

The crawler currently discards `result.html` when markdown succeeds
(crawler_engine.py:351). The replay store (T5) must retain the raw HTML for
EVERY page, so this script measures `len(result.html)` regardless of markdown
presence — that is the byte size the store will actually hold.

Usage:
    python scripts/measure_capture_sizes.py [--jobs N] [--max-pages M]

Output: per-page sizes + min/median/p95/max across the whole run, written to
stdout and to data/capture_sizes_report.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from datetime import datetime, timezone

# Ensure backend package is importable when run from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.crawler.crawler_engine import CrawlerEngine  # noqa: E402

# Representative mixed-site set: docs, news, e-commerce, blog, reference.
# Deliberately heterogeneous to exercise the real size distribution.
REPRESENTATIVE_SITES = [
    "https://example.com",
    "https://en.wikipedia.org/wiki/Web_browser",
    "https://www.python.org/doc/",
    "https://developer.mozilla.org/en-US/docs/Web/HTML",
    "https://www.bbc.com/news",
    "https://www.nytimes.com/",
    "https://github.com/",
    "https://www.rust-lang.org/",
]


def _percentile(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_vals) else f
    return sorted_vals[f] + int((sorted_vals[c] - sorted_vals[f]) * (k - f))


async def _measure(jobs: int, max_pages: int) -> dict:
    sizes: list[int] = []
    per_job: list[dict] = []
    async with CrawlerEngine() as engine:
        for job_idx in range(jobs):
            # Rotate through the site list so each job is a different site.
            start = (job_idx * max_pages) % len(REPRESENTATIVE_SITES)
            urls = [
                REPRESENTATIVE_SITES[(start + i) % len(REPRESENTATIVE_SITES)]
                for i in range(max_pages)
            ]
            result = await engine.crawl(
                query="measure capture sizes",
                urls=urls,
                instructions="",
                max_pages=max_pages,
                delay_ms=0,
                job_id=f"measure_{job_idx}",
            )
            job_sizes = []
            for p in result.pages:
                # html_bytes is recorded for EVERY page (crawler_engine.py),
                # even when markdown succeeded — that is the size the replay
                # store (T5) will actually hold.
                size = p.html_bytes or 0
                sizes.append(size)
                job_sizes.append({"url": p.url, "html_bytes": size, "error": p.error})
            per_job.append({"job": job_idx, "pages": job_sizes})
            print(f"[job {job_idx}] {len(job_sizes)} pages, "
                  f"sum={sum(s['html_bytes'] for s in job_sizes)} bytes")

    if not sizes:
        return {"error": "no pages captured", "per_job": per_job}

    sorted_sizes = sorted(sizes)
    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "jobs": jobs,
        "pages_total": len(sizes),
        "min": sorted_sizes[0],
        "median": int(statistics.median(sorted_sizes)),
        "p95": _percentile(sorted_sizes, 0.95),
        "max": sorted_sizes[-1],
        "mean": int(statistics.mean(sorted_sizes)),
        "sum_bytes": sum(sorted_sizes),
        "per_job": per_job,
    }
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=5, help="number of crawl jobs")
    ap.add_argument("--max-pages", type=int, default=3, help="pages per job")
    args = ap.parse_args()

    report = asyncio.run(run_measure(args.jobs, args.max_pages))

    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "capture_sizes_report.json",
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print("\n=== CAPTURE SIZE REPORT ===")
    if "error" in report:
        print("ERROR:", report["error"])
        return
    for k in ("min", "median", "p95", "max", "mean", "sum_bytes"):
        print(f"{k:>10}: {report[k]:,} bytes")
    print(f"  pages: {report['pages_total']}")
    print(f"  report: {out_path}")


async def run_measure(jobs: int, max_pages: int) -> dict:
    return await _measure(jobs, max_pages)


if __name__ == "__main__":
    main()