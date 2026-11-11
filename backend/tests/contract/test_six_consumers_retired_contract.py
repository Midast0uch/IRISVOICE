"""Six Oracle consumers are RETIRED, completely (owner, 2026-11-10).

Owner: "you can retire the jobs you recommended" and "remove the technical
debt". Measured on each consumer's live stamp, engine d1-2b-q4_k_m+systemone
(oracle.md section 1):

  narration (shape-v3)     loses to its rule, accuracy 0.820 vs 0.872
  presentation (shape-v3)  loses 0.378 vs 0.937; spec AC23.6 bars the only
                           extra input (the reply text)
  review_verdict (v13)     OOF AUROC 0.483, no step-level truth
  depth_route (v3)         AUROC 0.543
  needs_action (v7)        no threshold reaches precision 0.90 (label True on
                           96% of rows)
  depth_met (v4)           AUROC 0.591

In every case the INCUMBENT already decided and keeps deciding. This pins that
nothing half-remains - no registry entry, no job, no tier, no acting entry, no
bar or calibration record, no consult at any former site - while each
incumbent still decides exactly as before. Modelled on
test_escalate_incomplete_retired_contract.py.
"""
import importlib
import inspect
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agent import consumer_bar as cb
from backend.agent import decision_engine as de
from backend.agent import surface_shadow as ss
from backend.agent import tool_decision as td
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import QueueItem, Reviewer, ReviewVerdict

_RETIRED = ("narration", "presentation", "review_verdict", "depth_route",
            "needs_action", "depth_met")
# Jobs used ONLY by the six; each went with its consumers.
_RETIRED_JOBS = ("shape", "judge_review", "judge_depth", "interpret_step")
_REPO = Path(__file__).resolve().parents[3]

# Any of these in a former site's source is an Oracle consult.
_CONSULTS = ("decides(", "oracle_acts(", "sampled_consult_ok(", "sampled_row(",
             "surface_bool(", "score_surface_bool(", "_submit_shadow(",
             "register_declared(", ".shadow(", ".decide(", ".noul(")


@pytest.mark.parametrize("cid", _RETIRED)
def test_no_registry_still_names_it(cid):
    assert cid not in de.CONSUMERS
    assert cid not in de.CONSUMER_DECLARATIONS
    assert cid not in de.CONSUMER_JOBS
    assert cid not in de.NO_DECISION_SITE
    assert cid not in de.TIER_SAMPLABLE
    assert cid not in de.TIER_REFUSE_ONLY
    assert cid not in de.TIER_JOIN_ONLY
    assert cid not in cb.ACTING_ANSWER and cid not in cb.ACTING_ENFORCED
    assert cid not in getattr(ss, "SURFACE_CONSUMERS", {})


def test_their_jobs_went_with_them():
    for job in _RETIRED_JOBS:
        assert job not in de.ORACLE_JOBS, f"job {job} has no consumer left"
        assert job not in de.CONSUMER_JOBS.values()


def test_no_bar_or_calibration_record_names_them():
    bar = json.loads((_REPO / "benchmarks" / "consumer_bar_record.json")
                     .read_text(encoding="utf-8"))
    cal = json.loads((_REPO / "benchmarks" / "oracle_calibration.json")
                     .read_text(encoding="utf-8"))
    for cid in _RETIRED:
        assert cid not in bar
        for identity, consumers in cal.items():
            assert cid not in consumers, f"{identity} still calibrates {cid}"


def test_the_helpers_that_only_served_them_are_gone():
    for name in ("surface_bool", "score_surface_bool", "SURFACE_CONSUMERS",
                 "needs_action_label", "_submit_shadow", "set_row_sink"):
        assert not hasattr(ss, name), f"surface_shadow.{name} is dead code"
    assert not hasattr(de, "NARRATION_INSTRUCTION")
    for name in ("_shadow_review_verdict", "_review_row", "set_review_engine",
                 "set_shadow_sink", "REVIEW_INSTRUCTION", "REVIEW_CONSUMER"):
        assert not hasattr(Reviewer, name), f"Reviewer.{name} is dead code"
    for name in ("_score_narration", "_engine_gate_surface",
                 "_observe_surface_async", "_der_note_depth_route",
                 "_forward_consumer_rows"):
        assert not hasattr(AgentKernel, name), f"AgentKernel.{name} is dead code"
    assert not hasattr(td.ToolDecisionBox, "depth_route")
    with pytest.raises(ImportError):
        importlib.import_module("backend.agent.review_outcome_label")


@pytest.mark.parametrize("site,cid", [
    (AgentKernel._der_report_run_grade, "depth_met"),
    (AgentKernel._der_run_node, "needs_action"),
    (td._goal_needs_action, "needs_action"),
    (Reviewer.review, "review_verdict"),
    (AgentKernel._goal_contract_cover_step, "depth_route"),
    (AgentKernel._der_plan_next_step, "depth_route"),
    (AgentKernel._note_artifact_emitted, "presentation"),
    (AgentKernel._process_structured_response, "presentation"),
    (AgentKernel._plan_task, "narration"),
])
def test_no_former_site_consults_the_oracle(site, cid):
    src = inspect.getsource(site)
    assert f'"{cid}"' not in src, f"{site.__qualname__} still names {cid}"
    for name in ("_score_narration", "_observe_surface_async",
                 "_der_note_depth_route", "_shadow_review_verdict",
                 "review_outcome_label", "surface_shadow"):
        assert name not in src, f"{site.__qualname__} still calls {name}"
    if site in (AgentKernel._der_report_run_grade, td._goal_needs_action,
                Reviewer.review, AgentKernel._goal_contract_cover_step,
                AgentKernel._note_artifact_emitted):
        for call in _CONSULTS:
            assert call not in src, f"{site.__qualname__} still calls {call}"


# ── each incumbent still decides ────────────────────────────────────────────

def test_narration_the_duration_gate_decides():
    data = {"beats": ["one", " ", "two"]}
    assert AgentKernel._planned_beats(data, 2) == ["one", "two"]
    assert AgentKernel._planned_beats(data, 1) == []


def test_presentation_the_card_path_marks_the_render_and_starts_no_observer(
        monkeypatch):
    started = []

    def _thread(*_a, **kw):
        started.append(kw.get("name"))
        return SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(threading, "Thread", _thread)
    k = AgentKernel.__new__(AgentKernel)
    k._last_render_emitted = False
    AgentKernel._note_artifact_emitted(k, "body", "t1")
    assert k._last_render_emitted is True
    assert started == [], f"the card path started {started}"


def test_review_verdict_the_reviewer_decides():
    class _Adapter:
        def infer(self, *_a, **_k):
            return SimpleNamespace(raw_text='{"verdict": "veto", "reason": "r"}')

    class _Ctx:
        gradient_warnings = "step 2 failed like this before"
        active_contracts = ""

    item = QueueItem(step_id="s1", step_number=1,
                     description="read the readme", objective_anchor="OBJ-1")
    r = Reviewer(_Adapter(), None)
    assert r.review(item, [], _Ctx(), is_mature=True) == (ReviewVerdict.VETO, "r")
    assert r.review(item, [], None, is_mature=False) == \
        r._heuristic_review(item, [])


def test_depth_route_the_continuation_branch_decides():
    k = AgentKernel.__new__(AgentKernel)
    k._goal_contract_state = {
        "contract": SimpleNamespace(required=["fact a", "fact b"]),
        "covered": ["fact a"], "blocked": [],
    }
    assert AgentKernel._goal_contract_cover_step(k) == {
        "description": "Cover the open required fact: fact b"}


@pytest.mark.parametrize("p", [0.99, 0.01])
def test_needs_action_the_lexical_rule_decides(monkeypatch, p):
    """The safety assertions of the deleted behavioral/test_needs_action_
    consumer.py: a lexical True is final (the SAFE direction, AC29.4), and
    whatever an engine would say, the lexical rule is the answer."""
    class _Engine:
        model_id = "stub"

        def noul(self, consumer_id, *_a, **_k):
            return de.Noul(consumer_id=consumer_id, probability=p,
                           engine_latency_ms=1)

        def decide(self, *_a, **_k):
            return None

    monkeypatch.setattr(de, "get_decision_engine", lambda: _Engine())
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "needs_action")
    cases = {
        "search for the latest merger news": True,
        "look up the population of Japan": True,
        "read the config file": True,
        "ponder the meaning of it all": False,
        "say hello warmly": False,
        "": False,
    }
    for goal, expected in cases.items():
        assert td._goal_needs_action(goal) is expected, goal


def test_depth_met_the_run_grade_decides():
    from backend.agent.der_constants import LOAD_BEARING_VETO
    from backend.agent.tool_envelope import evaluate_run_grade

    k = AgentKernel.__new__(AgentKernel)
    k._goal_contract_state = None
    k._der_emit_card_settle = lambda *_a, **_k: None
    expected, _ = evaluate_run_grade([], load_bearing_veto=LOAD_BEARING_VETO,
                                     coverage=None, open_unblocked=[], blocked=[])
    assert AgentKernel._der_report_run_grade(k, [], "turn-1", "test") == expected
