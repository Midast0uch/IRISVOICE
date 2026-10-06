"""Wave 4 contract + behavioral tests: surface and narration gates.

CT-DE-6  frontend-facing event shapes untouched by the gates (static pin).
CT-DE-7  consumer registry surface: CONSUMERS, gate() signature, per-consumer
         counters, DecisionScore.confident.
CT-DE-8  narration gate AND-composition: toggle/timer supremacy, engine silent
         honored only when available+enforced+confident (AC12.2/12.3/12.4).

BT-DE-5  surface gate drives auto-render decision positively and negatively.
BT-DE-6  engine 'silent' suppresses the guaranteed-utterance backstop.
BT-DE-7  shadow / legacy path is bit-identical when the consumer is unenforced.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.agent.decision_engine as de_mod
from backend.agent.decision_engine import (
    CONSUMERS,
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent import narration as narration_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _GateEngine:
    """Engine stand-in for gate() — answer fixed; errors on demand."""

    def __init__(self, chosen="speak", confidence=0.95, dead=False):
        self._c = chosen
        self._p = confidence
        self._dead = dead
        self.model_id = "gate-stub"
        self.counters = EngineCounters()

        class _Cfg:
            # AC25.8: thresholds are keyed by ACTIVE BACKEND IDENTITY — the
            # stub models the resolved contract (a backend entry present, so
            # threshold_for returns a number). Updated 2026-09-25 per the
            # spec's ripple row; the two RED tests below are NOT touched.
            backend_id = "gate-stub"

            @staticmethod
            def threshold_for(_c):
                return 0.85

        self._cfg = _Cfg()

    def decide(self, consumer_id, options, frame):
        if self._dead:
            return None
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._c, confidence=self._p,
            distribution=(CandidateScore(self._c, -0.1, self._p),),
            engine_latency_ms=2,
        )


@pytest.fixture
def install_engine(monkeypatch):
    """Install a fake module-level engine; reset after the test."""

    def _install(engine, enforced=()):
        monkeypatch.setattr(de_mod, "_ENGINE", engine)
        monkeypatch.setattr(
            de_mod, "enforced_consumers",
            lambda: frozenset(enforced),
        )
        # narration.py imports symbols lazily — it will see these.
        return engine

    yield _install
    monkeypatch.setattr(de_mod, "_ENGINE", None)


@pytest.fixture
def narration_timer_reset(monkeypatch):
    monkeypatch.setattr(narration_mod, "_narration_gate_last", 0.0)
    yield


# ---------------------------------------------------------------------------
# CT-DE-6 — frontend event shapes pinned
# ---------------------------------------------------------------------------


class TestCtDe6EventShapes:
    def test_chat_message_payload_pinned(self):
        """iris_gateway chat_message payload keys are the pinned set."""
        src = Path("backend/iris_gateway.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = [
                    k.value
                    for k in node.keys
                    if isinstance(k, ast.Constant)
                ]
                if {"role", "content", "spoken", "turn_id"} <= set(keys):
                    found = set(keys)
                    break
        assert found is not None, "chat_message payload not found in source"
        assert found == {
            "role", "content", "spoken", "thinking", "timestamp", "turn_id",
        }

    def test_document_render_data_keys_pinned(self):
        """The auto-render DOCUMENT_RENDER emit still carries its known keys."""
        src = Path("backend/agent/agent_kernel.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        keys_seen = []
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "data":
                v = node.value
                if isinstance(v, ast.Dict):
                    ks = {k.value for k in v.keys
                          if isinstance(k, ast.Constant)}
                    if "format" in ks and "content" in ks \
                            and "document_id" in ks:
                        keys_seen.append(ks)
        assert keys_seen, "document render data dict not found"
        pinned = {"format", "content", "alternatives", "trust",
                  "document_id", "turn_id", "conversation_id", "sources",
                  "har_path"}
        # 2026-09-21 (specs/reply-surface-contract): TWO additive keys join the
        # pin. `card_id` (REQ-10 AC2 — stable prism-card lifecycle id, additive
        # per AC5: unknown = inert) and `partial` (REQ-13 AC5 — streaming
        # discriminator, additive: absent means final). The test still rejects
        # any OTHER key; only these documented contract extensions were
        # added to the set, each pinned by its own CT (CT-7 / CT-11).
        # 2026-09-25 (tool-decision-engine-improvements ripple row): `title`
        # joins the same way (card_title_for emit at agent_kernel.py:10360) —
        # the third documented additive-key extension.
        pinned |= {"card_id", "partial", "title"}
        # 2026-10-05 (reply-surface audit, Phase A — owner-approved): create_artifact
        # is the one door to a card and its event ALWAYS carries `kind`, `summary`
        # and `language` beside `title`, so a reload and the panel can show the
        # same card. The fourth documented additive-key extension; pinned by
        # test_create_artifact_contract.py (EVENT_KEYS). Any OTHER key still fails.
        pinned |= {"kind", "summary", "language"}
        for ks in keys_seen:
            assert ks <= pinned, f"event shape drifted: {ks - pinned}"


# ---------------------------------------------------------------------------
# CT-DE-7 — consumer registry
# ---------------------------------------------------------------------------


class TestCtDe7Registry:
    def test_consumers_and_counters(self):
        # STALE-BY-SPEC (2026-09-26): the set grew by `recovery_strategy`
        # (REQ-11 AC11.3, T15), then by REQ-13/14/15/17's consumers, then by
        # REQ-29's four surface consumers (T46–T49). The enumeration is the
        # contract, so it grows WITH the spec; `tier0_classify` stays OUT (a
        # recorded non-fit, AC29.5) and the other assertions are unchanged.
        assert CONSUMERS == (
            "tool_choice", "presentation", "narration", "recovery_strategy",
            "review_verdict", "sufficient", "done",
            "mode", "web_intent", "retry_same",
            "use_thinking", "escalate_incomplete", "needs_action",
            # Session 364 (owner request): the DEPTH consumer.
            "depth_met",
        )
        # STALE-BY-SPEC (2026-10-05, Oracle Stage B, owner-approved): `on_track`
        # (no production caller since 2026-10-02) and `has_gaps` (no live site)
        # are REMOVED from the set; nothing else changed.
        c = EngineCounters()
        c.bump_consumer("presentation")
        c.bump_consumer("presentation")
        c.bump_consumer("narration")
        assert c.by_consumer == {"presentation": 2, "narration": 1}

    def test_confident_helper(self):
        ds = DecisionScore("narration", "speak", 0.9, (), 5)
        assert ds.confident(0.85) and not ds.confident(0.95)

    def test_gate_signature_and_tuple_return(self):
        import inspect
        from backend.agent.decision_engine import gate

        sig = inspect.signature(gate)
        assert list(sig.parameters) == ["consumer_id", "options", "frame"]


# ---------------------------------------------------------------------------
# CT-DE-8 — narration AND-composition
# ---------------------------------------------------------------------------


class TestCtDe8NarrationComposition:
    def test_the_engine_never_gates_narration(
            self, install_engine, narration_timer_reset):
        """SUCCESSOR (2026-10-05, Oracle Stage B, owner-approved) of
        `test_confident_enforced_silent_blocks_and_spares_slot`. That test pinned
        that a confident, enforced engine "silent" blocked narration. The gate
        asked the Oracle "speak"/"silent" on a constant frame - not the question
        the narration calibration rows measure (speak_all / speak_first_only /
        stay_silent) - so narration NEVER decides at this gate now: the timer
        decides, and the engine is not even scored here."""
        eng = install_engine(_GateEngine(chosen="silent", confidence=0.97),
                             enforced=("narration",))
        calls = []
        _decide = eng.decide
        eng.decide = lambda *a, **k: (calls.append(a), _decide(*a, **k))[1]
        assert narration_mod.may_narrate() is True      # the timer admits
        assert narration_mod.may_narrate() is False     # the timer's 18 s window
        assert calls == [], "the narration gate scored the engine"

    def test_engine_dead_leaves_timer_alone(
            self, install_engine, narration_timer_reset):
        install_engine(_GateEngine(dead=True), enforced=("narration",))
        assert narration_mod.may_narrate() is True           # timer admits
        assert narration_mod.may_narrate() is False          # timer enforces

    def test_shadow_mode_is_timer_only(
            self, install_engine, narration_timer_reset):
        # engine says silent but consumer is NOT enforced → shadow → timer path
        install_engine(_GateEngine(chosen="silent", confidence=0.99),
                       enforced=())
        assert narration_mod.may_narrate() is True

    def test_engine_engine_exception_safe(self, monkeypatch,
                                          narration_timer_reset):
        def boom():
            raise RuntimeError("import chain broken")
        monkeypatch.setattr(de_mod, "get_decision_engine", boom)
        assert narration_mod.may_narrate() is True  # legacy survives errors


# ---------------------------------------------------------------------------
# BT-DE-5/6/7 — behavioral, binding real methods onto minimal selves
# ---------------------------------------------------------------------------


class TestSurfaceGateBehavior:
    def _kernel_self(self, recorder=None):
        return SimpleNamespace(
            _last_render_emitted=False,
            _pacman_zone_for_turn=lambda: "reference",
            _launcher_mode="personal",
            _tool_bridge=SimpleNamespace(record_decision=recorder)
            if recorder
            else None,
            session_id="s1",
        )

    def _call(self, kernel_self, response="A" * 400):
        from backend.agent.agent_kernel import AgentKernel

        return AgentKernel._engine_gate_surface(  # unbound, by design
            kernel_self, response, turn_id="t1")

    def test_enforced_confident_card(self, install_engine):
        install_engine(_GateEngine(chosen="prism_card", confidence=0.97),
                       enforced=("presentation",))
        assert self._call(self._kernel_self()) == "card"

    def test_enforced_confident_plain(self, install_engine):
        install_engine(_GateEngine(chosen="plain_text", confidence=0.99),
                       enforced=("presentation",))
        assert self._call(self._kernel_self()) == "plain"

    def test_shadow_verdict_returned_for_calibration_never_steers(self, install_engine):
        """SUCCESSOR (2026-09-22 audit, reply-surface-contract REQ-15). This
        used to be `test_shadow_records_but_heuristics_decide`, asserting a
        shadow verdict was DISCARDED (`out is None`, "heuristic decides") —
        but the calling heuristic was deleted 2026-09-21 and the only consumer
        of this method is the async calibration observer. A discarding shadow
        gate made calibration invisible: nothing logged a disagreement the
        ledger could compare. The verdict now RETURNS for the observer's
        calibration log while steering remains structurally impossible —
        nothing reads `_last_surface_choice` (the writes were removed)."""
        rows = []

        def rec(meta, kind, session_id="unknown"):
            rows.append((meta, kind))

        install_engine(_GateEngine(chosen="prism_card", confidence=0.99),
                       enforced=())
        ks = self._kernel_self(recorder=rec)
        out = self._call(ks)
        assert out == "card"                     # verdict SURFACES for calibration
        assert rows and rows[0][0]["route"] == "shadow"
        # ...but it must never become a steering side-channel.
        assert not hasattr(ks, "_last_surface_choice"), (
            "the dead steering field came back — the observer must not write it"
        )

    def test_card_turn_still_observed_with_truthful_frame(self, install_engine):
        """SUCCESSOR (2026-09-22 audit) of `test_already_rendered_never_consults`.
        AC11.4 (one card per turn) moved from this gate's early-return to the
        render sites (`_record_turn_render` + the tool path's in-place
        revision), so a turn WITH a card already emitted must STILL yield an
        observer verdict — otherwise "engine wanted plain, live produced card"
        is never measured (reply-surface-contract REQ-15 AC4 was blind for
        card turns). The frame must admit the card exists."""
        frames = []

        def decide(consumer_id, options, frame):
            frames.append(frame)
            return DecisionScore(
                consumer_id=consumer_id, chosen="prism_card", confidence=0.97,
                distribution=(CandidateScore("prism_card", -0.1, 0.97),),
                engine_latency_ms=2,
            )

        eng = install_engine(_GateEngine(chosen="prism_card", confidence=0.97),
                             enforced=("presentation",))
        eng.decide = decide
        ks = self._kernel_self()
        ks._last_render_emitted = True
        assert self._call(ks) == "card"
        assert frames and frames[0]["card_already_rendered"] is True


class TestNarrationBackstopBehavior:
    def test_the_backstop_has_no_engine_gate(self):
        """SUCCESSOR (2026-10-05, Oracle Stage B, owner-approved) of the three
        tests that drove `IRISGateway._engine_permits_speech` (engine "silent"
        suppresses the guaranteed-utterance backstop / shadow returns None /
        dead engine returns None). The method asked the Oracle "speak"/"silent"
        on a constant frame, scored inline on a reply thread, a different
        question from the narration calibration rows - narration NEVER decides
        here, so the method is removed and the backstop speaks whenever nothing
        reached TTS."""
        from backend.iris_gateway import IRISGateway

        assert not hasattr(IRISGateway, "_engine_permits_speech")
        src = Path("backend/iris_gateway.py").read_text(encoding="utf-8")
        assert "_engine_speech" not in src
