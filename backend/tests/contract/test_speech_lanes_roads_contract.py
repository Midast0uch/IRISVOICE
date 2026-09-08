"""Contract pins for the five speech roads + play path (REQ-6, T9).

Locks the per-road spoken-shaping contract against future edits. No behavior
change — these tests pin what the roads already do (T9 RIPPLE):

  Roads (each verified at its _enqueue_reply call site):
    voice_turn      iris_gateway.py:3517  (streaming sentence queue)
    voice_fallback  iris_gateway.py:3610  (friendly text, shown verbatim)
    agent_dag_brief iris_gateway.py:6000  (streaming brief queue)
    agent_dag_answer iris_gateway.py:6032 (spoken text, shown alongside)
    dashboard       iris_gateway.py:11156 (summary text, shown verbatim)

  CT-S3 spoken ⊆ visible: every road's spoken line derives from shown content
          through a REAL derivation function (structured speak/show split,
          prepare_spoken_text backstop, lane-enqueue passthrough, or the ONE
          resolver). Nothing invented — the only road-added words are the two
          fixed companion suffixes named below.
  CT-S4 normalization coverage: every road's spoken line is normalizer-safe.
  CT-S5 node lifecycle states: the six-state vocabulary + legal transitions.
  CT-S2 event shapes unchanged: the lane engine emits no WS events of its own
          (all visual echo rides the existing orb chain per D14).

Proving tests for tasks.md T9 (matrix rows AC6.3 + locks).
"""
from __future__ import annotations

import queue as _queue
import re as _re
import types as _types
from pathlib import Path
from unittest.mock import patch

from backend.agent.speech_lanes import (
    ALERT_AWAITING,
    ALERT_CRITICAL,
    NARRATION,
    NODE_STATES,
    REPLY,
    SpeechScheduler,
    UtteranceNode,
    build_node,
    resolve_spoken_text,
    route,
    Situation,
)
from backend.agent.structured_response import parse_structured_response
from backend.voice.tts_normalizer import normalize_for_speech


def _words(text: str) -> set:
    """Alphanumeric word set — ⊆ modulo punctuation, the AC6.3 level."""
    return set(_re.findall(r"[a-z0-9]+", text.lower()))


# Fixed companion suffixes prepare_spoken_text may append (agent_kernel.py).
# These template words are the ONLY road-added vocabulary beyond shown content.
_TEMPLATE_VOCAB = _words("The full code is in the chat window. "
                         "Full response in the chat window.")


def _real_prepare_spoken(full_response: str) -> str:
    """Drive the REAL prepare_spoken_text without booting a kernel.

    The method uses no instance state except _is_document_content, which is
    itself stateless — so an unbound call with a namespace stub executes 100%
    real road logic (voice-turn backstop, iris_gateway.py:3440).
    """
    from backend.agent.agent_kernel import AgentKernel

    stub = _types.SimpleNamespace(
        _is_document_content=lambda text: AgentKernel._is_document_content(text)
    )
    return AgentKernel.prepare_spoken_text(stub, full_response)


# ── CT-S3: spoken ⊆ visible per road ───────────────────────────────────────
class TestSpokenSubsetVisiblePerRoad:
    def test_voice_turn_structured_speaks_speak_field_never_raw_json(self):
        """Road voice_turn (structured): the `speak` field is spoken verbatim;
        the raw JSON body is never recited (gateway C.1 contract)."""
        raw = ('{"speak": "I found three papers on fusion.", '
               '"show": {"format": "markdown", "content": "# Fusion papers\\n..."}}')
        speak, show = parse_structured_response(raw)
        assert speak == "I found three papers on fusion."
        assert isinstance(show, dict)
        assert "{" not in speak  # no raw-JSON recital on this road

    def test_voice_turn_backstop_derived_from_shown(self):
        """Road voice_turn backstop (gateway:3440): prepare_spoken_text output
        is derived from the shown response — only the fixed suffixes are added."""
        shown = ("The search returned twelve results. The first result looks "
                 "promising because it matches the query exactly.")
        spoken = _real_prepare_spoken(shown)
        assert spoken
        novel = _words(spoken) - _words(shown) - _TEMPLATE_VOCAB
        assert not novel, f"invented words on voice_turn road: {novel}"

    def test_voice_turn_backstop_long_doc_first_sentence_plus_suffix(self):
        """Long/document road traffic: first sentence(s) + fixed suffix, nothing
        invented beyond the suffix and the shown words."""
        shown = ("# Report\n\n" + "This finding matters a great deal. " * 40)
        spoken = _real_prepare_spoken(shown)
        assert spoken.endswith("Full response in the chat window.")
        novel = _words(spoken) - _words(shown) - _TEMPLATE_VOCAB
        assert not novel, f"invented words on voice_turn road: {novel}"

    def test_play_road_override_recites_shown_per_format(self):
        """Road play-button (gateway:4992): the ONE resolver with override —
        spoken == shown exactly, for every road format."""
        for fmt in ("text", "prose", "markdown", "table", "code", "diagram"):
            shown = "Visible line one. Visible line two."
            assert resolve_spoken_text(
                shown_text=shown, show_format=fmt, override_recite=True
            ) == shown

    def test_conversational_roads_short_prose_verbatim(self):
        """Roads fallback/answer/dashboard (short prose): spoken == shown."""
        shown = "Done. The file was saved successfully."
        spoken = resolve_spoken_text(shown_text=shown, show_format="text")
        assert spoken == shown
        assert _words(spoken) <= _words(shown)

    def test_describe_roads_never_recite_cells(self):
        """Roads carrying tables/code/diagrams: described, never recited —
        spoken words ⊆ shown words and strictly shorter."""
        shown = "| name | size |\n|------|------|\n| alpha | 12 |\n| beta | 7 |"
        spoken = resolve_spoken_text(shown_text=shown, show_format="table")
        assert "|" not in spoken
        assert _words(spoken) <= _words(shown)
        assert len(spoken.split()) < len(shown.split())


class TestLaneEnqueuePassthrough:
    """The lane choke point preserves road content exactly (CT-S3): text roads
    enqueue the shown string verbatim; streaming roads enqueue the same queue
    object. Lanes never rewrite road content."""

    @staticmethod
    def _enqueue(**kwargs):
        from backend.iris_gateway import IRISGateway

        captured: list = []

        class _FakeScheduler:
            def admit(self, node):
                captured.append(node)

        fake_kernel = _types.SimpleNamespace(scheduler=_FakeScheduler())
        stub_self = _types.SimpleNamespace(
            _speak_response=lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("fallback must not fire with a scheduler")
            )
        )
        with patch(
            "backend.agent.conversation_kernel.get_conversation_kernel",
            return_value=fake_kernel,
        ):
            IRISGateway._enqueue_reply(stub_self, **kwargs)
        assert len(captured) == 1
        return captured[0]

    def test_text_roads_enqueue_shown_string_verbatim(self):
        """Roads voice_fallback / dag_answer / dashboard: the enqueued REPLY
        node carries the shown string byte-for-byte, lane REPLY."""
        for text in ("All set, I saved the file.", "Here is what I found today."):
            node = self._enqueue(
                text=text, session_id="s1", turn_id="t1", client_id="c1"
            )
            assert node.lane == REPLY
            assert node.content["text"] == text
            assert node.turn_id == "t1"
            assert node.session_id == "s1"

    def test_streaming_roads_enqueue_same_queue_object(self):
        """Roads voice_turn / dag_brief: the node carries the road's queue
        itself — sentences are never copied or reshaped by the lanes."""
        q: _queue.Queue = _queue.Queue()
        node = self._enqueue(queue=q, session_id="s1", turn_id="t1")
        assert node.content["queue"] is q


# ── CT-S4: normalization coverage per road ─────────────────────────────────
class TestNormalizationCoveragePerRoad:
    """Every road's spoken line is normalizer-safe: normalize_for_speech never
    raises, never empties non-empty speech, and strips unspeakable markdown."""

    ROAD_SPOKEN = {
        "voice_turn": "The first result looks promising. It matches exactly.",
        "voice_fallback": "Sorry, I did not catch that. Please say it again.",
        "agent_dag_brief": "Searching the web now, this may take a moment.",
        "agent_dag_answer": "Here is **bold** news with `code` inside.",
        "dashboard": "## Summary\n- item one\n- item two",
        "play": "| a | b |\n|---|---|\n| 1 | 2 |",
    }

    def test_each_road_normalizes_cleanly(self):
        for road, spoken in self.ROAD_SPOKEN.items():
            out = normalize_for_speech(spoken)
            assert isinstance(out, str), road
            assert out.strip(), f"{road}: normalizer emptied speech"

    def test_normalizer_strips_unspeakable_markdown(self):
        out = normalize_for_speech("## Title\nSome `code` here")
        assert "##" not in out
        assert "```" not in out


# ── CT-S5: node lifecycle states ───────────────────────────────────────────
class TestNodeLifecycleStates:
    def test_state_vocabulary_locked(self):
        """Exactly the six design.md states — no more, no fewer."""
        assert tuple(NODE_STATES) == (
            "queued", "ready", "playing", "done", "cancelled", "failed",
        )

    def test_build_node_starts_queued_with_watchdog(self):
        situation = Situation(trigger_label=REPLY, source="test")
        node = build_node(
            situation, route(situation), turn_id="t1", session_id="s1"
        )
        assert node.state == "queued"
        assert node.deadline > node.enqueued_at  # T8 watchdog wired

    def test_constructor_rejects_unknown_lane_and_state(self):
        import pytest

        with pytest.raises(ValueError):
            UtteranceNode(
                id="x", lane="nope",
                trigger={}, turn_id="t", session_id="s", content={},
            )
        with pytest.raises(ValueError):
            UtteranceNode(
                id="x", lane=REPLY,
                trigger={}, turn_id="t", session_id="s", content={},
                state="halfway",
            )

    def test_full_turn_emits_only_legal_states(self):
        """A real scheduler turn (admit → play → barge) only ever produces
        vocabulary states, ending in terminal ones."""
        played: list = []

        def play(node):
            played.append(node.id)

        sched = SpeechScheduler(play=play, auto_start=True)
        try:
            states: set = set()

            n1 = UtteranceNode(
                id="n1", lane=NARRATION, trigger={}, turn_id="t1",
                session_id="s1", content={"kind": "text", "text": "one"},
            )
            n2 = UtteranceNode(
                id="n2", lane=REPLY, trigger={}, turn_id="t1",
                session_id="s1", content={"kind": "text", "text": "two"},
            )
            sched.admit(n1)
            sched.admit(n2)
            sched.barge_in(turn_id="t2", session_id="s1")
            for n in (n1, n2):
                states.add(n.state)
            assert states <= set(NODE_STATES)
            assert states <= {"done", "cancelled", "failed"}
        finally:
            sched.stop()


# ── CT-S7: narration toggle (REQ-10 AC10.14, T15) ─────────────────────────
class TestNarrationToggle:
    """The settings path drops narration at admission (logged + counted);
    replies and alerts are unaffected; toggle-off purges queued narration
    and aborts holds; toggle-on resumes."""

    @staticmethod
    def _node(lane, text="line"):
        import time as _time

        return UtteranceNode(
            id=f"utt_{lane}_{_time.time_ns()}",
            lane=lane,
            trigger={"source": "test", "label": lane, "rule_fired": "L1:test"},
            turn_id="t1",
            session_id="s1",
            content={"kind": "text", "text": text},
        )

    def test_off_drops_narration_at_admission_counted(self):
        import threading as _threading

        from backend.agent.speech_lanes import SpeechObservability

        played: list = []
        lock = _threading.Lock()

        def _play(node):
            from backend.agent.speech_lanes import _node_text

            with lock:
                played.append(_node_text(node))

        obs = SpeechObservability()
        sched = SpeechScheduler(play=_play, observability=obs, auto_start=True)
        try:
            sched.set_narration_enabled_callback(lambda: False)
            sched.admit(self._node(NARRATION, text="beat one"))
            import time as _time

            _time.sleep(0.3)
            assert sched.pending_count() == 0
            with lock:
                assert played == []
            assert obs.counters.get("beat:narration_dropped") == 1
        finally:
            sched.stop()

    def test_off_leaves_replies_and_alerts_untouched(self):
        import threading as _threading
        import time as _time

        from backend.agent.speech_lanes import SpeechObservability

        played: list = []
        lock = _threading.Lock()

        def _play(node):
            from backend.agent.speech_lanes import _node_text

            with lock:
                played.append(_node_text(node))

        obs = SpeechObservability()
        sched = SpeechScheduler(play=_play, observability=obs, auto_start=True)
        try:
            sched.set_narration_enabled_callback(lambda: False)
            sched.admit(self._node(REPLY, text="answer"))
            sched.admit(self._node(ALERT_CRITICAL, text="urgent"))
            assert _wait_until(lambda: len(played) == 2, timeout=10.0)
            with lock:
                # Lane priority intact with the toggle off (critical first).
                assert played == ["urgent", "answer"]
            assert obs.counters.snapshot().get("beat:narration_dropped", 0) == 0
        finally:
            sched.stop()

    def test_on_again_resumes_narration(self):
        import threading as _threading
        import time as _time

        from backend.agent.speech_lanes import SpeechObservability

        played: list = []
        lock = _threading.Lock()

        def _play(node):
            from backend.agent.speech_lanes import _node_text

            with lock:
                played.append(_node_text(node))

        state = {"on": False}
        obs = SpeechObservability()
        sched = SpeechScheduler(play=_play, observability=obs, auto_start=True)
        try:
            sched.set_narration_enabled_callback(lambda: state["on"])
            sched.admit(self._node(NARRATION, text="dropped"))
            _time.sleep(0.3)
            state["on"] = True
            sched.admit(self._node(NARRATION, text="spoken"))
            assert _wait_until(lambda: played == ["spoken"], timeout=10.0)
        finally:
            sched.stop()

    def test_kernel_toggle_purges_and_aborts_holds(self):
        """set_narration_enabled(False) purges queued narration and aborts
        pre-synthesis; True resumes. Replies/alerts never consulted."""
        import threading as _threading
        from unittest.mock import MagicMock

        from backend.agent.conversation_kernel import ConversationKernel

        gate = _threading.Event()
        kernel = ConversationKernel(
            voice_handler=MagicMock(),
            tts_manager=MagicMock(),
            audio_pipeline=MagicMock(),
            session_id_getter=lambda: "sess-1",
            broadcast_event=None,
        )
        hold = _threading.Event()
        kernel.scheduler._play_fn = lambda node: hold.wait(timeout=30.0)
        try:
            kernel.scheduler.admit(self._node(NARRATION, text="playing"))
            assert _wait_until(lambda: kernel.scheduler.is_playing())
            kernel.scheduler.admit(self._node(NARRATION, text="queued"))
            kernel.set_narration_enabled(False)
            assert kernel.scheduler.narration_on() is False
            # Queued narration purges; the playing node finishes its sentence.
            assert kernel.scheduler.pending_count() == 0
            kernel.set_narration_enabled(True)
            assert kernel.scheduler.narration_on() is True
        finally:
            hold.set()
            kernel.scheduler.stop()
            try:
                from backend.agent.tts import get_tts_manager

                get_tts_manager().set_holds_accepted(True)
            except Exception:
                pass

    def test_settings_sync_routes_narration_key(self):
        """The existing settings_sync WS shape carries the toggle — no new
        message types (AC10.14 ripple)."""
        import asyncio as _asyncio
        from unittest.mock import MagicMock

        from backend.iris_gateway import IRISGateway

        applied: list = []
        fake_kernel = MagicMock()
        fake_kernel.set_narration_enabled = applied.append
        gw = IRISGateway.__new__(IRISGateway)
        gw._logger = MagicMock()
        with patch(
            "backend.agent.conversation_kernel.get_conversation_kernel",
            return_value=fake_kernel,
        ):
            _asyncio.run(
                gw._handle_chat(
                    "sess-1",
                    "cli-1",
                    {"type": "settings_sync",
                     "payload": {"settings": {"narration_enabled": False}}},
                )
            )
        assert applied == [False]


def _wait_until(pred, timeout=10.0):
    import time as _time

    end = _time.time() + timeout
    while _time.time() < end:
        if pred():
            return True
        _time.sleep(0.01)
    return False


# ── CT-S2: event shapes unchanged ──────────────────────────────────────────
class TestNoNewEventShapes:
    def test_lane_engine_emits_no_ws_events(self):
        """The lane engine (D14) rides the existing orb chain — it must never
        emit WS events of its own. Locks against future edits adding sends."""
        src = (
            Path(__file__).parent.parent.parent
            / "agent" / "speech_lanes.py"
        ).read_text()
        for symbol in ("ws_manager", "send_to_client", "broadcast", ".emit("):
            assert symbol not in src, f"lane engine references {symbol}"
