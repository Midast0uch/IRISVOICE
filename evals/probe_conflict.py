"""BT-W10-2 — the 3-thread conflict probe for T48.

Teach fact A in thread 1, teach fact B in thread 2, ask in thread 3. The newest
user statement (B) must win and A must not appear.

Reuses the live harness transport (`_http` + `_run_turn`) so the probe drives
the same WebSocket path as the gate. Cleans its own facts afterwards.

Run (backend warm):
  .venv\\Scripts\\python.exe evals\\probe_conflict.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.run_evals import (  # noqa: E402
    _http,
    _retire_eval_chats,
    _retire_eval_memory,
    _retire_taught_facts,
    _run_turn,
)


async def main() -> int:
    run = uuid.uuid4().hex[:6]
    a, b = f"fern-alpha-{run}", f"fern-bravo-{run}"
    # Start from a clean store: a memory-eval run leaves its OWN taught fact
    # behind (m03's "fern-green-..."), and the probe does not teach that prefix,
    # so a probe run straight after the eval answered the eval's fact instead of
    # the newer one (measured 2026-10-31, three FAILs in a row). The gate is
    # about ordering between THIS run's two facts, not about leftover state.
    try:
        _retire_eval_memory()
        _retire_eval_chats()
        # A CRASHED earlier probe never runs its cleanup, and its fact then
        # outranks this run's newest one (measured 2026-10-31: three runs all
        # answered the same stale "fern-alpha-9ec968"). Clear the whole prefix.
        for _prefix in ("fern-alpha-", "fern-bravo-"):
            _retire_taught_facts(_prefix)
    except Exception as exc:  # noqa: BLE001 - cleanup never decides the probe
        print("pre-clean failed", repr(exc))
    convs: dict[str, str] = {}
    # Titles carry the run id: POST /api/conversations with a title that already
    # exists can hand back the OLD conversation, and its history then repeats the
    # previous run's answer (measured 2026-10-31: three runs answered the same
    # stale "fern-alpha-9ec968" while their own facts differed).
    for key, title in (
        ("a", f"[eval-seed] conflict-a {run}"),
        ("b", f"[eval-seed] conflict-b {run}"),
        ("ask", f"[eval] conflict-ask {run}"),
    ):
        conv = _http("POST", "/api/conversations", {"title": title}, timeout=90)
        convs[key] = conv.get("id") or conv.get("conversation_id")
    print("run", run, "convs", convs)

    rec_a = await _run_turn(
        {"id": "conflict-a", "group": "memory", "path": "text_message",
         "prompt": f"Remember this for later: I prefer the color {a} for "
                   "status indicators. Just acknowledge it briefly."},
        convs["a"], None, 300,
    )
    rec_b = await _run_turn(
        {"id": "conflict-b", "group": "memory", "path": "text_message",
         "prompt": f"Remember this for later: I prefer the color {b} for "
                   "status indicators. Just acknowledge it briefly."},
        convs["b"], None, 300,
    )
    rec_ask = await _run_turn(
        {"id": "conflict-ask", "group": "memory", "path": "text_message",
         "prompt": "Which color do I prefer for status indicators? "
                   "Answer with the color only."},
        convs["ask"], None, 300,
    )

    reply = str(rec_ask.get("reply") or "")
    print("seed A:", (str(rec_a.get("reply") or ""))[:100],
          "timeout", rec_a.get("timed_out"))
    print("seed B:", (str(rec_b.get("reply") or ""))[:100],
          "timeout", rec_b.get("timed_out"))
    print("ask   :", reply[:200], "timeout", rec_ask.get("timed_out"))

    ok = (b.lower() in reply.lower()) and (a.lower() not in reply.lower())
    print("BT-W10-2:", "PASS" if ok else "FAIL", f"(want {b}, not {a})")

    # Clean this probe's facts so a later run starts from a clean store.
    for fact in (a, b):
        try:
            _retire_taught_facts(fact)
        except Exception as exc:  # noqa: BLE001 - cleanup never decides the probe
            print("cleanup fact failed", fact, repr(exc))
    try:
        _retire_eval_chats()
    except Exception as exc:  # noqa: BLE001
        print("cleanup chats failed", repr(exc))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
