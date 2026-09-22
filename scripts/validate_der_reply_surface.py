"""Standing CDD harness — reply-surface contract replay (REQ-9 / T11).

Replays a RECORDED websearch trajectory through the REAL reply seam
(``AgentKernel._process_structured_response``) on every run and asserts the
reply-surface-contract outcomes:

  1. plain synthesis (long, structural) -> NO card (no length fabrication)
  2. ``show`` artifact turn            -> exactly one card, bubble == speak
  3. repeat of both                    -> identical surfaces (determinism)
  4. empty "no usable results" show    -> plain text, no glass artifact

The trajectory is the one captured live 2026-09 (assistant web search on
"recent Python 3.13 features"): crawl evidence ~1760 chars, then a stubbed
synthesis. Only the I/O boundary (event bus) is intercepted; the seam runs
for real.

Run:  python scripts/validate_der_reply_surface.py
"""

from __future__ import annotations

import os
import sys

# backend is a package under the REPO ROOT — make it importable from scripts/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if os.path.isdir(os.path.join(_REPO, "backend")):
    sys.path.insert(0, _REPO)


class _Failures:
    def __init__(self):
        self.items = []

    def check(self, name, cond):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            self.items.append(name)


class _RecordingBus:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, **kw):
        self.events.append((str(event), data or {}))


# -- Recorded trajectory (websearch "recent Python 3.13 features") ----------

SYNTHESIS_PLAIN = (
    "## Python 3.13 findings\n\n"
    "Here is a summary of the notable changes in the release.\n\n"
    "| Area | Change |\n|---|---|\n"
    "| Interpreter | Experimental JIT compiler |\n"
    "| Threading | Typed free-threading (PEP 703) |\n"
    "| REPL | Improved interactive interpreter |\n"
    "| GC | Incremental garbage collection |\n\n"
    "Python 3.13 was released on October 7, 2024. The hot-path improvements "
    "mostly affect interpreter startup and long-running server workloads. "
    "Existing code runs unchanged, and the GIL-free build remains opt-in "
    "and experimental.\n"
) * 3  # ~1700+ chars: the shape the deleted auto-render used to card-ify

SHOW_TURN = (
    '{"speak": "Here is the summary of the Python 3.13 crawl.", '
    '"show": {"format": "markdown", "content": "# Python 3.13 crawl\\n\\n'
    'Stored evidence document.\\n", "sources": ['
    '{"url": "https://docs.python.org/3/whatsnew/3.13.html", '
    '"title": "What\\u2019s New In Python 3.13"}]}}'
)

EMPTY_RESULT_TURN = (
    '{"speak": "I could not find usable sources.", '
    '"show": {"format": "markdown", "content": "I wasn\'t able to pull '
    'any usable pages for that crawl.\\n\\nWhat was attempted: direct fetch.\\n'
    'What failed: no usable content."}}'
)


def _kernel():
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._last_render_emitted = False
    k._last_spoken_text = ""
    k._pending_web_doc_id = None
    k._memory_interface = None
    k._pacman_zone_for_turn = lambda: "reference"
    k._store_document_data = lambda **kw: None
    return k


def _drive(k, response):
    from backend.agent.agent_kernel import AgentKernel

    return AgentKernel._process_structured_response(
        k, response, turn_id="harness-t", conversation_id="harness-c"
    )


def main() -> int:
    print("=" * 64)
    print("REPLY-SURFACE REPLAY — STANDING CDD HARNESS (REQ-9 / T11)")
    print("=" * 64)

    import backend.agent.event_bus as eb

    bus = _RecordingBus()
    orig_get_event_bus = eb.get_event_bus
    eb.get_event_bus = lambda: bus
    # The speak broadcaster is fire-and-forget external delivery (Telegram/MCP)
    # and irrelevant to the surface contract — stub it so the harness stays
    # quiet on success (it warned "no subscribe attribute" on the record bus).
    import backend.agent.tools.speak_broadcaster as sb

    class _SilentBroadcaster:
        def forward_external(self, text):
            return None

    orig_get_broadcaster = sb.get_speak_broadcaster
    sb.get_speak_broadcaster = lambda: _SilentBroadcaster()
    try:
        fail = _Failures()

        print("1. plain synthesis: long + structural -> NO card, full bubble")
        k = _kernel()
        out = _drive(k, SYNTHESIS_PLAIN)
        fail.check("full synthesis returned to the bubble",
                   out == SYNTHESIS_PLAIN)
        fail.check("no DOCUMENT_RENDER without show",
                   [e for e, _d in bus.events if "DOCUMENT_RENDER" in e] == [])
        fail.check("_last_render_emitted stays False",
                   k._last_render_emitted is False)

        print("2. show artifact turn: exactly one card, bubble == speak")
        bus.events.clear()
        k2 = _kernel()
        out2 = _drive(k2, SHOW_TURN)
        renders = [
            d for e, d in bus.events if "DOCUMENT_RENDER" in e
        ]
        fail.check("exactly one DOCUMENT_RENDER on a show turn",
                   len(renders) == 1)
        fail.check("card carries the stored content",
                   renders and "Stored evidence document." in
                   (renders[0].get("content") or ""))
        fail.check("sources survive onto the card",
                   bool(renders) and bool(renders[0].get("sources")))
        fail.check("bubble is the speak line",
                   out2 == "Here is the summary of the Python 3.13 crawl.")
        fail.check("TTS lane got the speak line",
                   k2._last_spoken_text
                   == "Here is the summary of the Python 3.13 crawl.")

        print("3. determinism: the same replies replay to the same surfaces")
        for response in (SYNTHESIS_PLAIN, SHOW_TURN):
            runs = []
            for _ in range(2):
                bus.events.clear()
                kk = _kernel()
                runs.append((_drive(kk, response), [
                    e for e, _d in bus.events if "DOCUMENT_RENDER" in e
                ]))
            fail.check(f"surface stable across runs ({len(response)} chars)",
                       runs[0][0] == runs[1][0]
                       and len(runs[0][1]) == len(runs[1][1]))

        print("4. empty-result show: downgraded to plain text, no card")
        bus.events.clear()
        k4 = _kernel()
        out4 = _drive(k4, EMPTY_RESULT_TURN)
        fail.check("no card for an empty-result synthesis",
                   [e for e, _d in bus.events if "DOCUMENT_RENDER" in e] == [])
        fail.check("synthesis text reaches the bubble in full",
                   "wasn't able to pull" in out4)

        print("-" * 64)
        if fail.items:
            print(f"HARNESS FAILED: {len(fail.items)} check(s) broken")
            for name in fail.items:
                print(f"  - {name}")
            return 1
        print("HARNESS PASSED: reply-surface contract holds")
        return 0
    finally:
        eb.get_event_bus = orig_get_event_bus
        sb.get_speak_broadcaster = orig_get_broadcaster


if __name__ == "__main__":
    sys.exit(main())
