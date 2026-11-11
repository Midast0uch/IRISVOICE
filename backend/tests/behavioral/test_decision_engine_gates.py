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
    # test_chat_message_payload_pinned REMOVED 2026-10-10: it pinned the
    # chat_message courier's payload dict in iris_gateway.py, and that
    # courier was RETIRED 2026-10-06 (the text_message path sends only
    # turn.end; the frontend and the eval harness both moved with it —
    # commit c6c10700). A payload that no longer exists has no shape to pin.

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
        # STALE-BY-SPEC (2026-10-18): `mode` was REMOVED by the owner
        # (2026-10-10: a free keyword rule could never pay; AUROC 0.591 at 77
        # rows) and `tool_approval` JOINED (its pre-call guard became its live
        # decision; earned on the v6 cohort). Both changes are pinned by
        # test_consumer_declarations_contract.
        assert CONSUMERS == (
            "tool_choice", "recovery_strategy",
            "sufficient", "done",
            "web_intent",
            # `escalate_incomplete` REMOVED 2026-11-09 (owner retirement;
            # test_escalate_incomplete_retired_contract pins the removal).
            # presentation, narration, review_verdict, needs_action,
            # depth_met, depth_route REMOVED 2026-11-10 (owner retirement;
            # test_six_consumers_retired_contract pins the removal).
            # STALE-BY-SPEC (2026-10-08, specs/oracle-native-decision-surface
            # AC9.1 sanctioned exception 3): `call_closing` (REQ-10,
            # permanently measurement-only).
            "call_closing",
            # 2026-10-18 (owner): the pre-call guard consumer.
            "tool_approval",
            # 2026-10-30: the shadow-only memory route comparator.
            "route_v2",
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


# TestSurfaceGateBehavior REMOVED 2026-11-10 (owner): it drove
# AgentKernel._engine_gate_surface, the retired presentation observer.


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
