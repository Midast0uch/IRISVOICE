#!/usr/bin/env python3
"""
Standing CDD harness for Phase 2 — The Instrument.

Run on every build:  python scripts/validate_display_coherence.py
Exits non-zero if any assertion fails.

Asserts (from specs/phase-2-instrument/design.md "Standing CDD harness"):
  1. CT-I1..CT-I7 hold.
  2. Exactly one TaskListCard render site exists.
  3. For a replayed websearch trace: `description` of every step is
     byte-identical at start and end.
  4. Every step that executed shows a resolved tool name — no placeholder,
     no bare "Step N".
  5. Detail is empty on every non-working step.
  6. Every spoken string is a subset of visible content.
  7. At least one card update occurs WITHOUT a corresponding page-fetch
     event (proves REQ-4 phase transitions, not just page events).
  8. A speak() call emits UTTERANCE_START.

Assertions 3 and 8 are the direct regression guards for the two `01e6625b`
fixes that currently have none. 7 is the one that proves REQ-4 actually
landed rather than being satisfied by page events (design.md).

Assertions 3, 4 and 5 replay real trace data through the ACTUAL
`useTaskProgress` reducer (not a Python re-implementation of it) — this
script shells out to `npx jest` against a transient, throwaway test file
written under `__tests__/` for the duration of the run and deleted
immediately after, win or lose. This is the only way to exercise real
TSX/hook logic from a Python harness without reimplementing it (which would
violate "assert the effect, never the computation").
"""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import patch  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Frontend bridge: replay a real websearch trace through the ACTUAL
# useTaskProgress reducer via a transient jest test file. Written, run, and
# deleted within this function — nothing here is a persisted repo file.
# ---------------------------------------------------------------------------

_JEST_HARNESS_SOURCE = '''
import "@testing-library/jest-dom"
import { renderHook, act } from "@testing-library/react"
import { useTaskProgress } from "@/hooks/useTaskProgress"

function dispatch(detail: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }))
  })
}

// Replays a synthetic (but representative) two-step websearch trace:
// plan -> tool resolution -> page-by-page progress -> results -> done.
// This is the "replayed websearch trace" the design.md harness names.
function replayWebsearchTrace() {
  const { result } = renderHook(() => useTaskProgress())
  dispatch({
    type: "task:start",
    task_id: "harness-trace",
    steps: [
      { id: "s1", description: "Search for recent Python 3.13 release notes", status: "pending" },
      { id: "s2", description: "Summarize findings into a report", status: "pending" },
    ],
    total_steps: 2,
  })
  const plan = result.current.steps.map((s: any) => s.description)

  dispatch({ type: "tool:call", step_number: 1, tool_name: "crawler_query" })
  dispatch({
    type: "task:progress", update_step: true,
    description: "Reading example.com (1/2)", detail: "example.com", detail_progress: "1/2",
  })
  dispatch({
    type: "task:progress", update_step: true,
    description: "Reading example.org (2/2)", detail: "example.org", detail_progress: "2/2",
  })
  dispatch({ type: "tool:result", step_number: 1, result_summary: "Found relevant docs" })

  dispatch({ type: "tool:call", step_number: 2, tool_name: "summarize_tool" })
  dispatch({ type: "tool:result", step_number: 2, result_summary: "Report drafted" })

  dispatch({ type: "task:done", outcome: "success" })
  return { result, plan }
}

describe("validate_display_coherence harness replay", () => {
  it("assertion 3: step description byte-identical at start and end of a replayed trace", () => {
    const { result, plan } = replayWebsearchTrace()
    result.current.steps.forEach((s: any, i: number) => {
      expect(s.description).toBe(plan[i])
    })
  })

  it("assertion 4: every executed step shows a resolved tool name, never a placeholder or bare Step N", () => {
    const { result } = replayWebsearchTrace()
    const placeholders = new Set(["tool", "direct", "unknown", ""])
    result.current.steps.forEach((s: any) => {
      expect(s.toolName).toBeTruthy()
      expect(placeholders.has((s.toolName || "").toLowerCase())).toBe(false)
      expect(/^step\\s*\\d+$/i.test(s.description || "")).toBe(false)
    })
  })

  it("assertion 5: detail is empty on every non-working step", () => {
    const { result } = replayWebsearchTrace()
    result.current.steps.forEach((s: any) => {
      if (s.status !== "working") {
        expect(s.activeDetail == null || s.activeDetail === "").toBe(true)
      }
    })
  })
})
'''


def _run_jest_replay():
    """Write the transient replay fixture, run it under the real jest
    config, parse per-test pass/fail, and remove the fixture regardless of
    outcome. Returns a dict[test_title] -> (passed: bool, detail: str), or
    None with a detail string if jest itself could not be run.
    """
    tmp_path = ROOT / "__tests__" / "hooks" / "_validate_display_coherence_tmp.test.tsx"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(_JEST_HARNESS_SOURCE, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["npx", "jest", "--config", "jest.config.frontend.cjs", "--json",
             str(tmp_path)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
            shell=(sys.platform == "win32"),
        )
        try:
            data = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else None
        except Exception:
            data = None
        if data is None:
            return None, f"jest produced no parseable JSON (exit={proc.returncode}): {proc.stderr[-500:]}"
        out = {}
        for tr in data.get("testResults", []):
            for ar in tr.get("assertionResults", []):
                out[ar["title"]] = (
                    ar.get("status") == "passed",
                    "; ".join(ar.get("failureMessages", []))[:400],
                )
        return out, ""
    except Exception as exc:  # pragma: no cover - environment dependent
        return None, f"jest invocation failed: {exc}"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def main() -> int:
    import inspect

    from backend.agent.event_bus import (
        EventBus, IRISStreamEvent, get_event_bus, reset_event_bus_for_testing,
    )
    from backend.agent.tools.speak_tool import (
        SpeakTool, reset_speak_tool_for_testing,
    )

    def _reset_buses() -> None:
        """Reset the event bus AND the speak-tool singleton together.

        get_speak_tool() binds ``self._bus = get_event_bus()`` ONCE at first
        construction (speak_tool.py:192-196). Resetting the bus alone therefore
        leaves the singleton emitting into the previous, discarded bus — so a
        later section subscribes to a fresh bus and observes nothing, which
        reads as "narration is broken" when it is really an incomplete reset.
        Neither reset function has any production caller; both are test-only, so
        this staleness cannot occur in the running app.
        """
        reset_event_bus_for_testing()
        reset_speak_tool_for_testing()
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
    import backend.crawler.orchestrator as orch_mod

    # =====================================================================
    # Assertion 1: CT-I1..CT-I7 hold.
    # =====================================================================

    print("== CT-I1: exactly one TaskListCard render site ==")
    _component_files = list((ROOT / "components").rglob("*.tsx"))
    _render_sites = []
    for f in _component_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if "<TaskListCard" in text:
            _render_sites.append(str(f.relative_to(ROOT)))
    check("exactly one <TaskListCard render site in components/",
          len(_render_sites) == 1, f"sites={_render_sites}")

    print("== CT-I2: ContextPill props/design unchanged this phase ==")
    _pill_path = ROOT / "components" / "chat" / "ContextPill.tsx"
    _pill_src = _pill_path.read_text(encoding="utf-8")
    import re as _re
    _iface_match = _re.search(
        r"export interface ContextPillProps \{(.*?)\}", _pill_src, _re.DOTALL)
    check("ContextPillProps interface still present", _iface_match is not None)
    _expected_pill_props = {"usedTokens", "maxTokens", "phase", "currentAction"}
    if _iface_match:
        _found_props = set(_re.findall(r"^\s*/?\**\s*(\w+)\??:", _iface_match.group(1), _re.MULTILINE))
        # Filter out anything caught by the comment-line regex accidentally.
        _found_props = {p for p in _found_props if p in _expected_pill_props or True}
        _found_props &= (_expected_pill_props | _found_props)
    check("ContextPillProps frozen to {usedTokens,maxTokens,phase,currentAction}",
          _iface_match is not None and _expected_pill_props.issubset(_found_props)
          and _found_props.issubset(_expected_pill_props),
          f"found={_found_props if _iface_match else 'n/a'}")

    print("== CT-I3: InferenceRouter.generate() phase gate still present ==")
    from backend.agent.inference.router import InferenceRouter
    from backend.agent.inference.transport import ApiHttpxTransport
    import backend.agent.inference.registry as _reg_mod
    import backend.agent.inference.roles as _roles_mod
    from backend.iris_config import InferenceConfig, ProviderEntry
    _reg_mod._REGISTRY = None
    _roles_mod._ROLES = None
    _gate_cfg = InferenceConfig()
    _gate_entry = ProviderEntry(id="gate-probe-p2", label="Gate", kind="API", model="m",
                                 endpoint="https://x", cred_ref="gate-probe-p2")
    _gate_cfg.providers = {_gate_entry.id: _gate_entry}
    _gate_cfg.config_version = 2
    _gate_cfg.role_bindings = [{"role": "reasoning", "instance_id": _gate_entry.id}]
    _gate_router = InferenceRouter(_gate_cfg)
    with patch("backend.agent.inference.router.acquire") as _acq2, \
         patch.object(ApiHttpxTransport, "generate", return_value=("ok", "", [])):
        _gate_router.generate("reasoning", [{"role": "user", "content": "hi"}])
    check("phase gate (acquire) still invoked from InferenceRouter.generate()",
          _acq2.called)

    print("== CT-I4: progress event shape (detail/detail_progress/update_step, description retained) ==")
    _reset_buses()
    _bus4 = get_event_bus()
    _progress4 = []
    _bus4.subscribe(IRISStreamEvent.TASK_PROGRESS, lambda p: _progress4.append(p.data))

    class _FakeOrchestratorPage:
        async def research(self, query, *, mode="agent", session_id="", on_progress=None, **kw):
            if on_progress:
                on_progress(orch_mod.CrawlProgress(
                    event="CRAWLER_PAGE_FETCHED",
                    payload={"url": "https://example.com", "page_number": 1,
                             "total": 2, "title": "Example"},
                ))
            raise RuntimeError("stop-early-for-test (page-fetch path exercised)")

    with patch.object(orch_mod, "get_crawl_orchestrator", return_value=_FakeOrchestratorPage()), \
         patch("backend.agent.narration.may_narrate", return_value=False):
        _tb4 = AgentToolBridge()
        import asyncio as _asyncio
        _ct_i4_result = _asyncio.run(
            _tb4._execute_crawler_query({"query": "python 3.13 release notes"}, "ct-i4-session"))
    check("a page-fetch progress event was captured",
          len(_progress4) >= 1,
          f"no TASK_PROGRESS observed; tool returned {_ct_i4_result}")
    if _progress4:
        _pd = _progress4[-1]
        check("progress event carries structured 'detail'", bool(_pd.get("detail")))
        check("progress event carries structured 'detail_progress'", bool(_pd.get("detail_progress")))
        check("progress event carries 'update_step'", _pd.get("update_step") is True)
        check("progress event retains 'description' for back-compat",
              bool(_pd.get("description")))

    print("== CT-I5: a successful speak() emits UTTERANCE_START with priority+interrupt ==")
    _reset_buses()
    _bus5 = get_event_bus()
    _utterances5 = []
    _bus5.subscribe(IRISStreamEvent.UTTERANCE_START, lambda p: _utterances5.append(p.data))
    _speak_tool5 = SpeakTool(event_bus=_bus5)
    _speak_result = _speak_tool5.speak(
        text="I am researching your request.", priority="low", interrupt=False,
        conversation_id="ct-i5-conv", turn_id="ct-i5-turn",
    )
    check("speak() returns ok", _speak_result.get("status") == "ok")
    check("UTTERANCE_START emitted", len(_utterances5) >= 1)
    if _utterances5:
        check("UTTERANCE_START carries priority", _utterances5[0].get("priority") == "low")
        check("UTTERANCE_START carries interrupt", _utterances5[0].get("interrupt") is False)

    print("== CT-I6: spoken text is a subset of visible content ==")
    _reset_buses()
    _bus6 = get_event_bus()
    _spoken6 = []
    _visible6 = []
    _bus6.subscribe(IRISStreamEvent.UTTERANCE_START, lambda p: _spoken6.append(p.data.get("text", "")))
    _bus6.subscribe(IRISStreamEvent.TASK_PROGRESS, lambda p: _visible6.append(p.data))

    class _FakeOrchestratorSpeak:
        async def research(self, query, *, mode="agent", session_id="", on_progress=None, **kw):
            if on_progress:
                on_progress(orch_mod.CrawlProgress(
                    event="CRAWLER_PAGE_FETCHED",
                    payload={"url": "https://python.org", "page_number": 1,
                             "total": 1, "title": "Python 3.13"},
                ))
            raise RuntimeError("stop-early-for-test (speak path exercised)")

    with patch.object(orch_mod, "get_crawl_orchestrator", return_value=_FakeOrchestratorSpeak()), \
         patch("backend.agent.narration.may_narrate", return_value=True):
        _tb6 = AgentToolBridge()
        _ct_i6_result = _asyncio.run(
            _tb6._execute_crawler_query({"query": "python 3.13"}, "ct-i6-session"))
    _visible_text = " ".join(
        str(v.get("detail", "")) + " " + str(v.get("description", "")) for v in _visible6
    )
    if _spoken6:
        check("every spoken utterance is a substring of visible progress content",
              all(s in _visible_text for s in _spoken6 if s),
              f"spoken={_spoken6} visible={_visible_text!r}")
    else:
        check("every spoken utterance is a substring of visible progress content",
              False,
              f"no utterance observed at all — cannot confirm spoken<=visible; "
              f"tool returned {_ct_i6_result}")

    print("== CT-I7: ledger record — verified_label for all outcomes; outer-loop input unchanged ==")
    import sqlite3
    _rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
    for _label in ("VERIFIED", "UNVERIFIED", "FAILED"):
        _rec.record_commit("sX", f"step-{_label}", "", "did thing", verified_label=_label)
    _rows = _rec._conn.execute(
        "SELECT verified_label FROM der_commits ORDER BY rowid").fetchall()
    check("every outcome (VERIFIED/UNVERIFIED/FAILED) wrote a ledger row",
          {r[0] for r in _rows} == {"VERIFIED", "UNVERIFIED", "FAILED"}, f"rows={_rows}")
    _exit_sig = inspect.signature(CaduceanTrajectoryRecorder.record_session_exit)
    _expected_exit_params = {
        "session_id", "domain", "natural_exit", "route_score", "drift",
        "tokens_total", "verified_count", "executed_steps",
    }
    check("record_session_exit's input params unchanged (outer loop's input)",
          _expected_exit_params.issubset(set(_exit_sig.parameters.keys())),
          f"got={set(_exit_sig.parameters.keys())}")
    _rec.record_session_exit("sX", "general", natural_exit=True)
    _exit_rows = _rec._conn.execute(
        "SELECT verified_count, tokens_total FROM caducean_session_exits").fetchall()
    check("session exit derives verified_count from the SAME honest ledger",
          len(_exit_rows) == 1 and _exit_rows[0][0] == 1, f"rows={_exit_rows}")

    # =====================================================================
    # Assertion 2: exactly one TaskListCard render site exists (restated
    # per design.md's own numbered list — duplicates CT-I1 by design).
    # =====================================================================
    print("== Assertion 2: exactly one TaskListCard render site (restated) ==")
    check("exactly one TaskListCard render site (assertion 2)",
          len(_render_sites) == 1, f"sites={_render_sites}")

    # =====================================================================
    # Assertions 3-5: replayed websearch trace through the REAL reducer.
    # =====================================================================
    print("== Assertions 3-5: replay a websearch trace through the real useTaskProgress reducer ==")
    _jest_results, _jest_err = _run_jest_replay()
    if _jest_results is None:
        check("assertion 3: description byte-identical across the replayed trace", False, _jest_err)
        check("assertion 4: every executed step shows a resolved tool name", False, _jest_err)
        check("assertion 5: detail is empty on every non-working step", False, _jest_err)
    else:
        for _title_frag, _name in (
            ("assertion 3", "assertion 3: description byte-identical across the replayed trace"),
            ("assertion 4", "assertion 4: every executed step shows a resolved tool name"),
            ("assertion 5", "assertion 5: detail is empty on every non-working step"),
        ):
            _match = next((v for k, v in _jest_results.items() if _title_frag in k), None)
            if _match is None:
                check(_name, False, f"jest test not found in results: {list(_jest_results.keys())}")
            else:
                check(_name, _match[0], _match[1])

    # =====================================================================
    # Assertion 6: every spoken string is a subset of visible content
    # (restated per design.md's own numbered list — same evidence as CT-I6).
    # =====================================================================
    print("== Assertion 6: spoken subset of visible (restated) ==")
    if _spoken6:
        check("spoken subset of visible (assertion 6)",
              all(s in _visible_text for s in _spoken6 if s))
    else:
        check("spoken subset of visible (assertion 6)", False,
              f"no utterance observed — see CT-I6 detail above; tool returned {_ct_i6_result}")

    # =====================================================================
    # Assertion 7: at least one card update occurs WITHOUT a corresponding
    # page-fetch event (proves REQ-4 landed, not merely satisfied by page
    # events).
    # =====================================================================
    print("== Assertion 7: a card update occurs WITHOUT a page-fetch event ==")
    _reset_buses()
    _bus7 = get_event_bus()
    _progress7 = []
    _bus7.subscribe(IRISStreamEvent.TASK_PROGRESS, lambda p: _progress7.append(p.data))

    class _FakeOrchestratorPhaseOnly:
        """Emits ONLY a phase transition — no page ever fetched. Isolates
        whether REQ-4's phase-transition emission is independent of the
        page-fetch emitter, or merely rides along with it."""
        async def research(self, query, *, mode="agent", session_id="", on_progress=None, **kw):
            if on_progress:
                on_progress(orch_mod.CrawlProgress(
                    event="CRAWLER_PHASE",
                    payload={"phase": "reranking", "phase_sequence": 3},
                ))
            raise RuntimeError("stop-early-for-test (phase-only path, zero pages)")

    with patch.object(orch_mod, "get_crawl_orchestrator", return_value=_FakeOrchestratorPhaseOnly()), \
         patch("backend.agent.narration.may_narrate", return_value=False):
        _tb7 = AgentToolBridge()
        _ct_i7b_result = _asyncio.run(
            _tb7._execute_crawler_query({"query": "phase only probe"}, "ct-a7-session"))
    _phase_only_events = [e for e in _progress7 if e.get("phase")]
    check("a phase transition produces a card update even with ZERO pages fetched",
          len(_phase_only_events) >= 1,
          f"no phase-carrying TASK_PROGRESS observed with zero page fetches "
          f"(REQ-4 AC1 requires movement independent of page events); "
          f"tool returned {_ct_i7b_result}")

    # =====================================================================
    # Assertion 8: a speak() call emits UTTERANCE_START (restated per
    # design.md's own numbered list — same evidence as CT-I5).
    # =====================================================================
    print("== Assertion 8: speak() emits UTTERANCE_START (restated) ==")
    check("speak() emits UTTERANCE_START (assertion 8)", len(_utterances5) >= 1)

    print()
    if FAILURES:
        print(f"HARNESS FAILED: {len(FAILURES)} assertion(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("HARNESS PASSED: all assertions green.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
