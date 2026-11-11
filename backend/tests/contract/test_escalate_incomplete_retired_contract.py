"""escalate_incomplete is RETIRED as an Oracle consumer, completely (2026-11-09).

Owner decision after measurement (oracle.md 12.5): offline on 494 d1-2B rows,
against the step verdict and a recurrence label, with the result-only and the
goal + expected + result frames, every cell sat at chance (OOF AUROC
0.46-0.58). IRIS records no trustworthy step-level truth, so the consumer could
never be certified. The JOB stays: der_loop's incomplete-result keyword list
decides, and the goal contract judges completion from the tool's own output.

The owner asked for no leftover debt, so this pins that nothing half-remains:
no registry entry, no job, no tier, no acting entry, no surface question, and
the escalation site never consults the Oracle - while the keyword list still
escalates exactly as before.
"""
import inspect

from backend.agent import consumer_bar as cb
from backend.agent import decision_engine as de
from backend.agent import surface_shadow as ss
from backend.agent.der_loop import DirectorQueue, ExecutionMode

_CID = "escalate_incomplete"


def test_no_registry_still_names_it():
    assert _CID not in de.CONSUMERS
    assert _CID not in de.CONSUMER_DECLARATIONS
    assert _CID not in de.CONSUMER_JOBS
    assert "judge_step" not in de.ORACLE_JOBS, "its only job goes with it"
    assert _CID not in de.TIER_SAMPLABLE
    assert _CID not in cb.ACTING_ANSWER and _CID not in cb.ACTING_ENFORCED
    # (the surface registry itself was removed 2026-11-10; absent = not named)
    assert _CID not in getattr(ss, "SURFACE_CONSUMERS", {})


def test_the_escalation_site_never_consults_the_oracle():
    src = inspect.getsource(DirectorQueue.check_escalation)
    for call in ("score_surface_bool(", "surface_bool(", "sampled_row(",
                 "decides(", "oracle_acts("):
        assert call not in src, f"check_escalation still calls {call}"


def _queue():
    q = DirectorQueue(objective="test")
    q.mode = ExecutionMode.QUICK
    q.items = []
    return q


def test_the_keyword_incumbent_still_decides():
    assert _queue().check_escalation(
        review_verdict=None, tool_result_summary="all good, nothing more to do",
        token_budget_remaining=11000) is False
    escalated = []
    q = _queue()
    q.escalate = lambda **kw: escalated.append(kw)
    assert q.check_escalation(
        review_verdict=None, tool_result_summary="partial result: need more information",
        token_budget_remaining=11000) is True
    assert escalated, "an incomplete result still escalates through self.escalate"
