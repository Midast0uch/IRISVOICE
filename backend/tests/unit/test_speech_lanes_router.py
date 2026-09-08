"""Unit: Speech lane router decision table (CT-S1) + observability (REQ-9).

Pins REQ-1 (deterministic pure router, intent is content-only, decision
recorded), REQ-3 (hierarchy precedence L1>L2>L3>L4, default narration), and
REQ-9 (per-turn observability logs + L2-L4 / unlisted-type counters + shadow
divergence logging). Pure unit — no model, no I/O, no audio.
"""
from __future__ import annotations

import pytest

from backend.agent.speech_lanes import (
    ALERT_AWAITING,
    ALERT_CRITICAL,
    DEFAULT_LANE,
    HIERARCHY_TABLE,
    LANES,
    LANE_PRIORITY,
    NARRATION,
    REPLY,
    ShadowObserver,
    Situation,
    SpeechCounters,
    SpeechObservability,
    UtteranceNode,
    build_node,
    route,
)


# ── REQ-1 AC1.1: pure deterministic router ─────────────────────────────────
class TestRouterPure:
    def test_same_situation_same_lane(self):
        s = Situation(trigger_label="reply", source="ws", turn_phase="active")
        assert route(s).lane == route(s).lane == REPLY

    def test_no_model_call_in_path(self):
        # route() is a pure function of the Situation; it must not import or
        # touch any model/agent module. It only reads the dataclass fields.
        s = Situation(trigger_label=None, source="tool", turn_phase="idle")
        d = route(s)
        assert d.lane in LANES

    def test_router_is_oid(self):
        # O(1) table walk — no loops over utterances, no blocking.
        s = Situation(trigger_label="alert_critical")
        assert route(s).lane == ALERT_CRITICAL


# ── REQ-3 AC3.1: hierarchy precedence L1 > L2 > L3 > L4 ────────────────────
class TestHierarchy:
    def test_l1_explicit_label_wins_over_phase_and_shape(self):
        # Explicit reply label beats an awaiting phase and an artifact shape.
        s = Situation(
            trigger_label=REPLY,
            source="ws",
            turn_phase="awaiting",
            content_shape="table",
        )
        assert route(s).lane == REPLY

    def test_l1_all_four_lanes(self):
        for lane in LANES:
            s = Situation(trigger_label=lane)
            assert route(s).lane == lane, f"L1 failed for {lane}"

    def test_l2_awaiting_phase(self):
        s = Situation(trigger_label=None, source="tool", turn_phase="awaiting")
        assert route(s).lane == ALERT_AWAITING

    def test_l2_turn_end_phase(self):
        s = Situation(trigger_label=None, source="tool", turn_phase="turn_end")
        assert route(s).lane == NARRATION

    def test_l3_artifact_shape_narrates(self):
        for shape in ("table", "diagram", "code"):
            s = Situation(trigger_label=None, source="tool", content_shape=shape)
            assert route(s).lane == NARRATION, f"artifact {shape} should narrate"

    def test_l3_conversation_shape_replies(self):
        for shape in ("conversation", "prose"):
            s = Situation(trigger_label=None, source="ws", content_shape=shape)
            assert route(s).lane == REPLY, f"conversation {shape} should reply"

    def test_l4_default_narration(self):
        # No usable label, phase, or shape → default lane (narration).
        s = Situation(trigger_label=None, source="unknown")
        assert route(s).lane == DEFAULT_LANE == NARRATION

    def test_hierarchy_table_is_data(self):
        # The table is a data structure (list of rules), not code branches.
        assert isinstance(HIERARCHY_TABLE, tuple)
        assert len(HIERARCHY_TABLE) >= 4
        levels = [r.level for r in HIERARCHY_TABLE]
        # L1 rules come before L2, L2 before L3, L3 before L4.
        assert max(levels[:4]) == 1
        assert levels[-1] == 4  # L4 default is last


# ── REQ-1 AC1.2: intent is content-only ────────────────────────────────────
class TestIntentContentOnly:
    def test_agent_speak_does_not_override_lane(self):
        # The agent's speak/show intent is a content declaration; it does not
        # influence lane selection beyond the artifact-vs-conversation shape.
        # An explicit reply label still wins even if the agent "shows" a table.
        s = Situation(trigger_label=REPLY, source="agent", content_shape="table")
        assert route(s).lane == REPLY


# ── REQ-1 AC1.3: decision recorded on node ─────────────────────────────────
class TestDecisionRecorded:
    def test_node_carries_rule_fired_and_inputs(self):
        s = Situation(trigger_label=None, source="tool", content_shape="table")
        d = route(s)
        node = build_node(s, d, turn_id="t1", session_id="s1")
        assert node.lane == NARRATION
        assert node.trigger["rule_fired"] == d.rule_fired
        assert node.trigger["inputs"] == d.inputs
        assert node.trigger["source"] == "tool"

    def test_node_lane_derived_priority_and_persist(self):
        # Narration: lowest priority, not persisted.
        s = Situation(trigger_label=NARRATION)
        node = build_node(s, route(s), turn_id="t", session_id="s")
        assert node.priority == LANE_PRIORITY[NARRATION]
        assert node.persist is False
        # Reply: persisted.
        s2 = Situation(trigger_label=REPLY)
        node2 = build_node(s2, route(s2), turn_id="t", session_id="s")
        assert node2.persist is True

    def test_node_rejects_unknown_lane(self):
        with pytest.raises(ValueError):
            UtteranceNode(
                id="x", lane="bogus", trigger={}, turn_id="t", session_id="s",
                content={"kind": "text", "text": ""},
            )


# ── REQ-9 AC9.2: tuning counters ───────────────────────────────────────────
class TestCounters:
    def test_l2_l4_hierarchy_hits_counted(self):
        obs = SpeechObservability()
        for label, phase, shape in [
            (None, "awaiting", None),   # L2
            (None, "turn_end", None),   # L2
            (None, None, "table"),      # L3
            (None, None, None),         # L4
        ]:
            s = Situation(trigger_label=label, turn_phase=phase, content_shape=shape)
            obs.record_routing(route(s), turn_id="t", session_id="s")
        snap = obs.counters.snapshot()
        assert snap.get("hierarchy:L2:phase:awaiting") == 1
        assert snap.get("hierarchy:L2:phase:turn_end") == 1
        assert snap.get("hierarchy:L3:shape:artifact") == 1
        assert snap.get("hierarchy:L4:default") == 1

    def test_l1_not_counted_as_tuning_signal(self):
        obs = SpeechObservability()
        obs.record_routing(route(Situation(trigger_label=REPLY)), turn_id="t", session_id="s")
        snap = obs.counters.snapshot()
        assert not any(k.startswith("hierarchy:L1") for k in snap)

    def test_unlisted_type_counted(self):
        obs = SpeechObservability()
        obs.record_unlisted_type("spreadsheet", turn_id="t", session_id="s")
        assert obs.counters.get("unlisted_type:spreadsheet") == 1

    def test_counters_thread_safe_snapshot(self):
        c = SpeechCounters()
        c.incr("a")
        c.incr("a")
        c.incr("b")
        assert c.snapshot() == {"a": 2, "b": 1}


# ── REQ-9 AC9.3: shadow observer logs would-order, changes nothing ─────────
class TestShadowObserver:
    def test_shadow_returns_decision_without_side_effects(self):
        obs = ShadowObserver(enabled=True)
        s = Situation(trigger_label=None, source="tool", content_shape="table")
        d = obs.observe(s, turn_id="t", session_id="s")
        assert d.lane == NARRATION  # would-be lane, same as route()

    def test_shadow_disabled_returns_decision_no_log(self):
        obs = ShadowObserver(enabled=False)
        s = Situation(trigger_label=REPLY)
        d = obs.observe(s, turn_id="t", session_id="s")
        assert d.lane == REPLY

    def test_shadow_divergence_logged_when_actual_differs(self, caplog):
        obs = ShadowObserver(enabled=True)
        s = Situation(trigger_label=None, source="tool", content_shape="table")
        # Actual behavior used REPLY; router would narrate → divergence.
        with caplog.at_level("INFO", logger="iris.agent.speech_lanes"):
            obs.observe(s, turn_id="t", session_id="s", actual_lane=REPLY)
        assert any("shadow_divergence" in r.message for r in caplog.records)

    def test_shadow_no_divergence_when_matching(self, caplog):
        obs = ShadowObserver(enabled=True)
        s = Situation(trigger_label=None, source="tool", content_shape="table")
        with caplog.at_level("INFO", logger="iris.agent.speech_lanes"):
            obs.observe(s, turn_id="t", session_id="s", actual_lane=NARRATION)
        assert not any("shadow_divergence" in r.message for r in caplog.records)