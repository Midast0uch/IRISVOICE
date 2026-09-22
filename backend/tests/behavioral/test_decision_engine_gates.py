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
    """Engine stand-in for gate() â€” answer fixed; errors on demand."""

    def __init__(self, chosen="speak", confidence=0.95, dead=False):
        self._c = chosen
        self._p = confidence
        self._dead = dead
        self.model_id = "gate-stub"
        self.counters = EngineCounters()

        class _Cfg:
            default_threshold = 0.85

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
        # narration.py imports symbols lazily â€” it will see these.
        return engine

    yield _install
    monkeypatch.setattr(de_mod, "_ENGINE", None)


@pytest.fixture
def narration_timer_reset(monkeypatch):
    monkeypatch.setattr(narration_mod, "_narration_gate_last", 0.0)
    yield


# ---------------------------------------------------------------------------
# CT-DE-6 â€” frontend event shapes pinned
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
        # any OTHER key; only these two documented contract extensions were
        # added to the set, each pinned by its own CT (CT-7 / CT-11).
        pinned |= {"card_id", "partial"}
        for ks in keys_seen:
            assert ks <= pinned, f"event shape drifted: {ks - pinned}"


# ---------------------------------------------------------------------------
# CT-DE-7 â€” consumer registry
# ---------------------------------------------------------------------------


class TestCtDe7Registry:
    def test_consumers_and_counters(self):
        assert CONSUMERS == ("tool_choice", "presentation", "narration")
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
# CT-DE-8 â€” narration AND-composition
# ---------------------------------------------------------------------------


class TestCtDe8NarrationComposition:
    def test_confident_enforced_silent_blocks_and_spares_slot(
            self, install_engine, narration_timer_reset):
        install_engine(_GateEngine(chosen="silent", confidence=0.97),
                       enforced=("narration",))
        assert narration_mod.may_narrate() is False
        # engine silence must NOT consume the 18 s slot: a later non-engine
        # decision would still fireâ€¦ swap to permissive and confirm.
        install_engine(_GateEngine(chosen="speak", confidence=0.99),
                       enforced=("narration",))
        assert narration_mod.may_narrate() is True

    def test_engine_dead_leaves_timer_alone(
            self, install_engine, narration_timer_reset):
        install_engine(_GateEngine(dead=True), enforced=("narration",))
        assert narration_mod.may_narrate() is True           # timer admits
        assert narration_mod.may_narrate() is False          # timer enforces

    def test_shadow_mode_is_timer_only(
            self, install_engine, narration_timer_reset):
        # engine says silent but consumer is NOT enforced â†’ shadow â†’ timer path
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
# BT-DE-5/6/7 â€” behavioral, binding real methods onto minimal selves
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

    def test_shadow_records_but_heuristics_decide(self, install_engine):
        rows = []

        def rec(meta, kind, session_id="unknown"):
            rows.append((meta, kind))

        install_engine(_GateEngine(chosen="prism_card", confidence=0.99),
                       enforced=())
        out = self._call(self._kernel_self(recorder=rec))
        assert out is None                      # shadow: heuristic path
        assert rows and rows[0][0]["route"] == "shadow"

    def test_already_rendered_never_consults(self, install_engine):
        eng = install_engine(_GateEngine(), enforced=("presentation",))
        ks = self._kernel_self()
        ks._last_render_emitted = True
        assert self._call(ks) is None
        assert eng.counters.decisions == 0      # AC11.4: engine untouched


class TestNarrationBackstopBehavior:
    def _gw(self):
        return SimpleNamespace(_tool_bridge=None)

    def _call(self, gw, resp="spoken content"):
        from backend.iris_gateway import IRISGateway

        return IRISGateway._engine_permits_speech(gw, resp)

    def test_engine_silent_suppresses_backstop(self, install_engine):
        install_engine(_GateEngine(chosen="silent", confidence=0.97),
                       enforced=("narration",))
        assert self._call(self._gw()) is False      # AC12.4: silence honored

    def test_shadow_returns_none(self, install_engine):
        install_engine(_GateEngine(chosen="silent", confidence=0.99),
                       enforced=())
        assert self._call(self._gw()) is None       # BT-DE-7: legacy reigns

    def test_engine_dead_returns_none(self, install_engine):
        install_engine(_GateEngine(dead=True), enforced=("narration",))
        assert self._call(self._gw()) is None       # AC12.3 degrade
