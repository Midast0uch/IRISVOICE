"""Live benchmark harness for Domain 19 Caducean DER Governor.

Usage:
    python -m backend.benchmarks.live_benchmark

Requires backend running on ws://localhost:8090/ws/benchmark
"""

import asyncio
import json
import math
import os
import sqlite3
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import websockets

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.gateway.iris_ffi import ffi_calculate_eml, ffi_caducean_get_xi


@dataclass
class RoundMetrics:
    round_num: int
    prompt: str
    category: str
    latency_first_token: float = 0.0
    latency_total: float = 0.0
    phase: int = -1
    eml_score: float = 0.0
    tools_used: List[str] = field(default_factory=list)
    mem_delta_mb: float = 0.0
    response_text: str = ""
    error: str = ""


@dataclass
class BenchmarkReport:
    rounds: List[RoundMetrics] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    total_trajectory_rows: int = 0


PROMPTS = [
    ("What files are in my project?", "file_list"),
    ("Search the web for Python async best practices", "web_search"),
    ("Read the README and summarize it", "file_reasoning"),
    ("Find a bug in this code: def foo(): return 1/0", "reasoning_file"),
    ("Remember that I prefer dark mode", "memory_store"),
    ("What did I ask you to remember?", "memory_recall"),
    ("Create a todo list for my project", "file_write"),
    ("Check my git status", "git_tool"),
    ("Run pytest on the backend", "shell_tool"),
    ("Take a screenshot and describe it", "vision_tool"),
    ("Open Chrome and search for IRISVOICE", "browser_web"),
    ("What tools do you have available?", "introspection"),
    ("Help me debug why the backend won't start", "multi_step"),
    ("List all test files and tell me which are slow", "file_analysis"),
    ("Write a Python function to calculate fibonacci", "code_gen"),
    ("Save that function to backend/utils/fib.py", "file_write"),
    ("What phase is the Caducean governor in right now?", "introspection"),
    ("Show me my recent memory trajectory", "memory_query"),
    ("Research how to improve the DER loop", "auto_research"),
    ("Summarize everything we've done in this session", "memory_reasoning"),
]


def _phase_from_xi(xi: float) -> int:
    if xi < math.pi / 2:
        return 1
    elif xi < math.pi:
        return 2
    elif xi < 3 * math.pi / 2:
        return 3
    return 4


def _snapshot_caducean(session_id: str) -> Dict[str, Any]:
    try:
        eml_tuple = ffi_calculate_eml(session_id)
        # ffi_calculate_eml returns (eml, stability, coherence) tuple
        eml = eml_tuple[0] if isinstance(eml_tuple, tuple) else eml_tuple
        xi = ffi_caducean_get_xi(session_id)
        return {"eml": eml, "xi": xi, "phase": _phase_from_xi(xi)}
    except Exception as e:
        return {"eml": 0.0, "xi": 0.0, "phase": -1, "error": str(e)}


def _count_trajectory_rows(session_id: str) -> int:
    db_path = ROOT / "data" / "iris_memory.db"
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM caducean_trajectories WHERE session_id=?",
            (session_id,),
        )
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


async def _send_and_measure(ws, prompt: str, session_id: str) -> RoundMetrics:
    """Send text_message and collect latency + full response."""
    msg = {"type": "text_message", "payload": {"text": prompt}}

    t0 = time.perf_counter()
    await ws.send(json.dumps(msg))

    first_chunk_time = 0.0
    response_parts = []
    done = False

    while not done:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=45.0)
        except asyncio.TimeoutError:
            break

        data = json.loads(raw)
        msg_type = data.get("type", "")
        payload = data.get("payload", {})

        if first_chunk_time == 0.0 and msg_type == "chat_chunk":
            first_chunk_time = time.perf_counter()

        if msg_type == "chat_chunk":
            response_parts.append(payload.get("chunk", ""))

        if msg_type == "chat_message":
            response_parts.append(payload.get("content", ""))
            done = True

        if msg_type == "error":
            return RoundMetrics(
                round_num=0,
                prompt=prompt,
                category="",
                error=payload.get("message", "unknown error"),
            )

    t_total = time.perf_counter() - t0
    latency_first = (first_chunk_time - t0) if first_chunk_time > 0 else t_total

    return RoundMetrics(
        round_num=0,
        prompt=prompt,
        category="",
        latency_first_token=latency_first,
        latency_total=t_total,
        response_text="".join(response_parts),
    )


async def run_benchmark(
    session_id: str = "benchmark_001",
) -> tuple[BenchmarkReport, float]:
    report = BenchmarkReport()
    report.start_time = time.time()

    uri = f"ws://localhost:8090/ws/{session_id}"
    print(f"Connecting to {uri} ...")

    tracemalloc.start()
    mem_before = tracemalloc.get_traced_memory()[0] / (1024 * 1024)

    async with websockets.connect(uri) as ws:
        print("Connected. Waiting 1s for session init...")
        await asyncio.sleep(1)

        for idx, (prompt, category) in enumerate(PROMPTS, start=1):
            print(f"\n{'=' * 60}")
            print(f"Round {idx}/20 | {category}")
            print(f"Prompt: {prompt[:60]}...")

            mem_round_before = tracemalloc.get_traced_memory()[0] / (1024 * 1024)

            try:
                metrics = await _send_and_measure(ws, prompt, session_id)
            except Exception as e:
                metrics = RoundMetrics(
                    round_num=idx,
                    prompt=prompt,
                    category=category,
                    error=str(e),
                )

            metrics.round_num = idx
            metrics.category = category

            caducean = _snapshot_caducean(session_id)
            metrics.phase = caducean.get("phase", -1)
            metrics.eml_score = caducean.get("eml", 0.0)

            mem_round_after = tracemalloc.get_traced_memory()[0] / (1024 * 1024)
            metrics.mem_delta_mb = mem_round_after - mem_round_before

            report.rounds.append(metrics)

            status = "OK" if not metrics.error else "ERR"
            print(
                f"[{status}] 1st-token: {metrics.latency_first_token:.2f}s | "
                f"total: {metrics.latency_total:.2f}s | "
                f"phase: {metrics.phase} | EML: {metrics.eml_score:.2f} | "
                f"mem: +{metrics.mem_delta_mb:.1f}MB"
            )

            await asyncio.sleep(1.5)

    report.end_time = time.time()
    mem_after = tracemalloc.get_traced_memory()[0] / (1024 * 1024)
    tracemalloc.stop()

    report.total_trajectory_rows = _count_trajectory_rows(session_id)

    return report, mem_after - mem_before


def _print_report(report: BenchmarkReport, total_mem_delta: float) -> None:
    duration = report.end_time - report.start_time

    print("\n" + "=" * 70)
    print("BENCHMARK REPORT")
    print("=" * 70)
    print(
        f"Duration: {duration:.1f}s | Rounds: {len(report.rounds)} | Mem delta: {total_mem_delta:.1f}MB"
    )
    print()

    latencies = [r.latency_first_token for r in report.rounds if not r.error]
    totals = [r.latency_total for r in report.rounds if not r.error]
    if latencies:
        latencies.sort()
        totals.sort()
        n = len(latencies)
        print("LATENCY (first token)")
        print(
            f"  p50: {latencies[n // 2]:.2f}s | p95: {latencies[int(n * 0.95)]:.2f}s | max: {latencies[-1]:.2f}s"
        )
        print("LATENCY (total)")
        print(
            f"  p50: {totals[n // 2]:.2f}s | p95: {totals[int(n * 0.95)]:.2f}s | max: {totals[-1]:.2f}s"
        )
        print()

    phases = [r.phase for r in report.rounds if r.phase > 0]
    if phases:
        print("CADUCEAN PHASE DISTRIBUTION")
        for p in range(1, 5):
            count = phases.count(p)
            pct = count / len(phases) * 100
            names = {1: "Explore", 2: "Balance", 3: "Verify", 4: "Crystallize"}
            print(f"  Phase {p} ({names[p]}): {count} rounds ({pct:.0f}%)")
        print()

    emls = [r.eml_score for r in report.rounds if r.eml_score > 0]
    if emls:
        print(
            f"EML SCORE  min: {min(emls):.2f}  max: {max(emls):.2f}  avg: {sum(emls) / len(emls):.2f}"
        )
        print()

    errors = [r for r in report.rounds if r.error]
    if errors:
        print(f"ERRORS: {len(errors)} rounds failed")
        for r in errors:
            print(f"  Round {r.round_num}: {r.error}")
        print()

    print(f"TRAJECTORY DB ROWS: {report.total_trajectory_rows}")
    print()

    print("ROUND-BY-ROUND")
    print(
        f"{'Rnd':>3} | {'Category':<18} | {'1stTok':>6} | {'Total':>6} | {'Phase':>5} | {'EML':>5} | {'Mem+':>6} | {'Status':>6}"
    )
    print("-" * 80)
    for r in report.rounds:
        status = "ERR" if r.error else "OK"
        print(
            f"{r.round_num:>3} | {r.category:<18} | {r.latency_first_token:>6.2f} | "
            f"{r.latency_total:>6.2f} | {r.phase:>5} | {r.eml_score:>5.2f} | "
            f"{r.mem_delta_mb:>6.1f} | {status:>6}"
        )

    print("\n" + "=" * 70)


def main() -> None:
    session_id = f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    report, mem_delta = asyncio.run(run_benchmark(session_id))
    _print_report(report, mem_delta)


if __name__ == "__main__":
    main()
