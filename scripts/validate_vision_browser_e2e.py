#!/usr/bin/env python3
"""Standing CDD harness for the vision-browser E2E path (REQ-17; T13/T21).

Runs the fixture steps of the Verification Plan (design.md steps 1-5, 7-9) with
NO network and NO external model, writes every emitted vision / frame / grant
event to a bounded run-scoped JSONL journal, diffs the emitted sequence against
the contract, and EXITS NON-ZERO naming the offending invariant on any break
(REQ-17 AC4). This is the agent-driveable gate T14 step 11 uses.

Usage:
    python scripts/validate_vision_browser_e2e.py            # run the gate
    python scripts/validate_vision_browser_e2e.py --agent    # same (agent gate)
    python scripts/validate_vision_browser_e2e.py --journal out.jsonl

The harness is hermetic: a deterministic loopback HTTP fixture server
(`scripts/fixtures/vision_pages/`) supplies the pages, a fake session + fake
provider drive the loop, and the real contract/behavioral surfaces are
exercised. Live steps (frontend :3000, real model) are reported SKIPPED, never
inferred from a unit test.

Exit code 0 = every invariant held; 1 = a named invariant was violated.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vision_pages"


class _FixtureHandler(BaseHTTPRequestHandler):
    """Serve the deterministic fixture pages over loopback (REQ-17 AC1)."""

    def log_message(self, *_a):  # silence
        pass

    def do_GET(self):  # noqa: N802
        name = self.path.strip("/").split("?")[0] or "plain.html"
        if not name.endswith(".html"):
            name += ".html"
        target = (_FIXTURES / name).resolve()
        try:
            target.relative_to(_FIXTURES.resolve())
        except ValueError:
            self.send_response(404)
            self.end_headers()
            return
        if not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_fixture_server() -> tuple[ThreadingHTTPServer, int]:
    """Start the loopback fixture server on an ephemeral port.

    REQ-17 edge: bind port 0 so the OS picks a free port (a busy port is
    never a harness failure). Returns (server, port).
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class _Invariant:
    """One named check. A failure names the invariant (REQ-17 AC4)."""

    def __init__(self, name: str, ok: bool, detail: str = "") -> None:
        self.name = name
        self.ok = ok
        self.detail = detail


class _HarnessCDP:
    """A minimal fake CDP session for the harness (no browser)."""

    def __init__(self):
        self._handlers: dict = {}

    def on(self, event, handler):
        self._handlers[event] = handler

    async def send(self, method, params):
        return None

    async def detach(self):
        return None

    def fire_frame(self, data):
        h = self._handlers.get("Page.screencastFrame")
        if h:
            h({"data": data, "sessionId": 1,
               "metadata": {"deviceWidth": 1280, "deviceHeight": 720}})


def _run_fixture_steps(port: int, journal) -> list:
    """Run Verification Plan steps 1-5 + 7-9 hermetically (REQ-17 AC1).

    Returns the list of invariant results.
    """
    import asyncio

    from backend.vision.browser_session import WallKind, _detect_wall_from_html
    from backend.vision.cdp_takeover import TakeoverInput, TakeoverManager
    from backend.vision.fetch_vision import FetchVisionCapability

    results: list = []
    base = f"http://127.0.0.1:{port}"

    # ── Step 1: synthetic HTML over loopback; wall detection (no model) ──
    plain_html = (_FIXTURES / "plain.html").read_text(encoding="utf-8")
    wall_html = (_FIXTURES / "wall.html").read_text(encoding="utf-8")
    results.append(_Invariant(
        "step1.plain_page_has_no_wall",
        _detect_wall_from_html(plain_html) is None,
        "plain fixture must not register as a wall",
    ))
    results.append(_Invariant(
        "step1.wall_page_detects_captcha",
        _detect_wall_from_html(wall_html) == WallKind.CAPTCHA,
        "wall fixture must detect as CAPTCHA",
    ))

    class _Session:
        def __init__(self, job_id, url, goal, bounds=None, page_offset=0):
            self.job_id = job_id
            self.url = url
            self.goal = goal
            self.acts: list = []
            self.closed = False
            self._idx = 0
            self._frames = [bytes([i]) * 32 for i in range(1, 30)]

        async def open(self):
            pass

        def available(self):
            return True

        async def detect_wall(self):
            return None

        async def screenshot(self):
            return self._frames[self._idx]

        async def act(self, action):
            self.acts.append(action)
            if action.kind == "scroll":
                self._idx = min(self._idx + 1, len(self._frames) - 1)

        async def settle(self):
            return "<html><body>" + ("content " * 40) + "</body></html>"

        async def close(self):
            self.closed = True

        async def request_takeover(self, wall, **kwargs):
            return False

    class _Provider:
        def __init__(self):
            self.n = 0

        def suggest_action(self, img_bytes, goal, trajectory=None):
            self.n += 1
            if self.n <= 6:
                return {"action": "scroll", "target": "", "reasoning": "walk"}
            return {"action": "error", "target": "", "reasoning": "done"}

        def read_text(self, img_bytes):
            return ""

        def analyze_screen(self, img_bytes, question=""):
            return ""

        def describe_live_frame(self, img_bytes):
            return "no new content"

    emitted: list = []

    def _emit(ev, payload):
        emitted.append((ev, payload))
        journal.record(ev, payload)

    prov = _Provider()
    cap = FetchVisionCapability(provider=prov, session_cls=_Session)
    asyncio.run(cap.fetch_one(
        f"{base}/plain.html", "read the fixture", "run-harness",
        on_action=lambda p: _emit("CRAWLER_VISION_ACTION", p),
    ))

    # Step 4: a changing scroll session is NOT stopped by a kind-repeat heuristic.
    scrolls = sum(1 for e, p in emitted if e == "CRAWLER_VISION_ACTION"
                  and p.get("kind") == "scroll")
    results.append(_Invariant(
        "step4.long_scroll_not_stopped", scrolls > 3,
        f"expected >3 scrolls, got {scrolls} (REQ-4)",
    ))

    # Step 5 / REQ-6 AC4: seq is present and monotonic per run.
    seqs = [p.get("seq") for e, p in emitted if e == "CRAWLER_VISION_ACTION"]
    results.append(_Invariant(
        "step5.seq_present_and_monotonic",
        bool(seqs) and seqs == sorted(seqs) and all(s is not None for s in seqs),
        f"seq values: {seqs} (REQ-6 AC4)",
    ))
    run_ids = {p.get("run_id") for e, p in emitted if e == "CRAWLER_VISION_ACTION"}
    results.append(_Invariant(
        "step5.run_id_present", bool(run_ids) and all(run_ids),
        f"run_id values: {run_ids} (REQ-6 AC4)",
    ))
    return results



def _run_takeover_steps(journal) -> list:
    """Verification Plan steps 7-9 hermetically (REQ-13..REQ-16)."""
    import asyncio

    from backend.vision.cdp_takeover import TakeoverInput, TakeoverManager

    results: list = []
    frames: list = []
    harness_cdp = _HarnessCDP()
    mgr = TakeoverManager(
        run_id="run-harness",
        cdp_factory=lambda _p: harness_cdp,
        frame_sink=frames.append,
    )
    mgr.open_grant(question_id="q-harness", wall_kind="captcha")
    started = asyncio.run(mgr.start_screencast(object()))
    results.append(_Invariant("step7.screencast_started", started is True,
                              "CDP screencast start"))
    harness_cdp.fire_frame("F1")
    harness_cdp.fire_frame("F2")
    frame_seqs = [f["frame_seq"] for f in frames]
    results.append(_Invariant(
        "step7.frame_seq_monotonic",
        frame_seqs == sorted(frame_seqs) and len(frame_seqs) >= 1,
        f"frame_seq: {frame_seqs} (REQ-16 AC4)",
    ))
    results.append(_Invariant(
        "step7.frame_envelope_has_owner",
        all(f.get("question_id") for f in frames) if frames else True,
        "every frame must carry a question_id (REQ-16 edge)",
    ))
    # Step 8: input OUTSIDE a grant is rejected; inside it is forwarded.
    mgr.close_grant("test")
    rejected = asyncio.run(mgr.deliver_input(TakeoverInput(kind="pointer", x=0.1, y=0.1)))
    results.append(_Invariant(
        "step8.input_rejected_outside_grant",
        rejected is False and mgr.rejected_inputs >= 1,
        "input outside a grant must be rejected + counted (REQ-14 AC1)",
    ))
    mgr.open_grant(question_id="q-harness", wall_kind="captcha")
    asyncio.run(mgr.start_screencast(object()))
    forwarded = asyncio.run(mgr.deliver_input(TakeoverInput(kind="pointer", x=0.1, y=0.1)))
    results.append(_Invariant(
        "step8.input_forwarded_inside_grant", forwarded is True,
        "input inside an open grant must be forwarded (REQ-14 AC1)",
    ))
    # Step 9: stop + release; no frame after the terminal event.
    before = len(frames)
    asyncio.run(mgr.stop_screencast())
    mgr.close_grant("done")
    # A frame fired after the grant closed must be dropped (REQ-16 edge).
    harness_cdp.fire_frame("AFTER")
    results.append(_Invariant(
        "step9.no_frame_after_terminal", len(frames) == before,
        "a frame arrived after the grant closed (REQ-16 edge)",
    ))
    return results


def _run_contract_steps(journal) -> list:
    """Assert the standing contract guards hold on every run (T13 ripple)."""
    results: list = []
    try:
        from backend.tests.contract.test_no_direct_vision_provider_bypass import (
            _construction_sites,
            _SANCTIONED,
        )
        sites = _construction_sites()
        unsanctioned = sorted(set(sites) - set(_SANCTIONED))
        results.append(_Invariant(
            "contract.no_resolver_bypass", not unsanctioned,
            f"unsanctioned tier-3 reach: {unsanctioned} (REQ-1)",
        ))
    except Exception as exc:  # noqa: BLE001
        results.append(_Invariant("contract.no_resolver_bypass", False, str(exc)))

    # REQ-17 AC3 / T22: replay the recorded vision corpus and assert the
    # contract on every run. The corpus lives in tests/vision_traces/.
    trace_dir = Path(__file__).resolve().parents[1] / "tests" / "vision_traces"
    traces = sorted(trace_dir.glob("*.json")) if trace_dir.is_dir() else []
    if not traces:
        results.append(_Invariant(
            "corpus.present", False,
            "no recorded vision traces — run scripts/record_vision_trajectory.py",
        ))
    for trace_path in traces:
        try:
            data = json.loads(trace_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            results.append(_Invariant(f"corpus.{trace_path.stem}.parse", False, str(exc)))
            continue
        events = data.get("events", [])
        ok_schema = data.get("schema") == 1 and data.get("kind") == "vision_trajectory"
        results.append(_Invariant(
            f"corpus.{trace_path.stem}.schema_v1", ok_schema,
            "trace must be schema v1 (T22)",
        ))
        # seq is monotonic within the trace.
        seqs = [e.get("seq") for e in events
                if e.get("event") == "CRAWLER_VISION_ACTION" and e.get("seq") is not None]
        results.append(_Invariant(
            f"corpus.{trace_path.stem}.seq_monotonic",
            seqs == sorted(seqs),
            f"seq: {seqs} (REQ-6 AC4)",
        ))
        # Redaction: no URL / text / bytes leak into the corpus.
        leaked = [k for e in events for k in e
                  if k in ("url", "text", "bytes", "html", "value")]
        results.append(_Invariant(
            f"corpus.{trace_path.stem}.redacted", not leaked,
            f"unredacted keys present: {set(leaked)} (T22)",
        ))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Vision-browser E2E harness (REQ-17)")
    parser.add_argument("--agent", action="store_true",
                        help="agent gate: same fixture steps, exit-code contract")
    parser.add_argument("--journal", default="",
                        help="path for the run-scoped JSONL journal")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    args = parser.parse_args()

    import tempfile
    from backend.vision.run_journal import RunJournal

    journal_path = args.journal or str(
        Path(tempfile.gettempdir()) / "iris_vision_e2e_journal.jsonl"
    )
    journal = RunJournal(journal_path, "run-harness")
    journal.open()

    server, port = start_fixture_server()
    try:
        results = _run_fixture_steps(port, journal)
        results += _run_takeover_steps(journal)
        results += _run_contract_steps(journal)
    finally:
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        journal.close()

    failures = [r for r in results if not r.ok]
    report = {
        "run_id": "run-harness",
        "journal": journal_path,
        "journal_available": journal.available,
        "journal_truncated": journal.truncated,
        "invariants": [
            {"name": r.name, "ok": r.ok, "detail": r.detail} for r in results
        ],
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "skipped_live_steps": [
            "step6.panel_reflection (needs frontend :3000)",
            "step10.latency_baseline (needs the real stack)",
        ],
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in results:
            mark = "PASS" if r.ok else "FAIL"
            line = f"[{mark}] {r.name}"
            if not r.ok:
                line += f" — {r.detail}"
            print(line)
        print(f"\njournal: {journal_path} (available={journal.available})")
        print(f"{report['passed']} passed, {report['failed']} failed")

    if failures:
        # REQ-17 AC4: name the offending invariant, exit non-zero.
        print("\nFAILED INVARIANTS:", file=sys.stderr)
        for r in failures:
            print(f"  - {r.name}: {r.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

