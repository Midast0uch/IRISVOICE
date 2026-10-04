"""Slow start: an unknown provider limit is not a 30 rpm limit (live 2026-10-04).

Before: the AIMD additive increase ran only AFTER a 429, so a provider that
never rejected IRIS stayed at the CEILING_INIT_RPM guess (30) forever. A node
loop of fast mercury-2 calls went over it and the phase gate held every later
call 2 s (60/30): 31 of 42 calls held, 55 s of a 166 s turn, no 429 in any run.

Now: until the first 429 (or a published limit), reaching the ceiling without a
rejection doubles it; the hard rail still caps what the gate uses; after a 429
the existing AIMD rule applies unchanged.
"""

from backend.agent.rate_meter import (
    CEILING_INIT_RPM,
    PHASE_HARD_MAX_RPM,
    clear_ceilings_for_testing,
    get_rate_meter,
)


def _fresh():
    clear_ceilings_for_testing()
    m = get_rate_meter()
    m.reset_for_testing()
    m.ensure_window("q", True)
    return m


def test_a_never_rejected_provider_is_not_held_at_the_guess():
    m = _fresh()
    for _ in range(int(CEILING_INIT_RPM) + 10):
        m.record_request("q", tokens=10, priority=0, estimated=True)
    recent = m.draw("q")["requests"]
    assert recent == CEILING_INIT_RPM + 10
    assert m.get_ceiling("q") > recent  # the gate's saturation test stays false
    for _ in range(200):
        m.record_request("q", tokens=10, priority=0, estimated=True)
    assert m.get_ceiling("q") == PHASE_HARD_MAX_RPM  # the rail still caps it


def test_after_a_429_the_learned_ceiling_does_not_slow_start():
    m = _fresh()
    m.observe_429("q")
    after_429 = m.get_ceiling("q")
    for _ in range(int(after_429) + 5):
        m.record_request("q", tokens=10, priority=0, estimated=True)
    assert m.get_ceiling("q") == after_429
