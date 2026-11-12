"""CT-9 (specs/clm-memory, Testing Strategy; CLM-4 AC1, AC2, AC5): one gauge.

Pins (1) the moved estimator returns the router's numbers, (2) an unobserved
(provider, model) is the conservative estimate marked uncalibrated, (3) the
EMA ratio converges and is keyed per (provider, model), (4) the calibrated
error on the REAL Wave 0 calls beats the uncalibrated one.

The Wave 0 pairs in ``clm_wave0_calls.json`` come from
``logs/clm_baseline.jsonl`` (T0.1, opencodego / deepseek-v4.1-flash, n = 129);
``evals/results/clm-baseline-2026-11-12.json`` holds only aggregates. The
design's CT-9 also names a source guard that the three old estimators are
gone; that belongs to the wiring part (the old ones still exist) and is NOT
in this file.
"""

from __future__ import annotations

import json
import statistics
import threading
from pathlib import Path

import pytest

from backend.agent import context_gauge as cg
from backend.agent.context_gauge import ContextGauge, estimate_tokens
from backend.agent.inference.router import InferenceRouter

_IMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
_TOOLS = [{"type": "function", "function": {"name": "web_search", "parameters": {"type": "object"}}}]
_CASES = [
    ([], None),
    ([{"role": "user", "content": "hello"}], None),
    ([{"role": "system", "content": "s" * 500}, {"role": "user", "content": "u" * 1234}], _TOOLS),
    (
        [
            {"role": "user", "content": [{"type": "text", "text": "look"}, _IMG]},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "result — café"},
        ],
        _TOOLS,
    ),
    ([{"role": "user", "content": None}], []),
]


@pytest.mark.parametrize("messages,tools", _CASES)
def test_estimator_equals_the_router_estimator(messages, tools):
    assert estimate_tokens(messages, tools) == InferenceRouter._estimate_prompt_tokens(messages, tools)


def test_estimator_known_value():
    # 100 chars + 16 scaffolding = 116 chars; int(116 / 3.5) + 1 = 34
    assert estimate_tokens([{"role": "user", "content": "x" * 100}], None) == 34


def test_unobserved_pair_is_the_raw_estimate_and_uncalibrated():
    g = ContextGauge()
    msgs, tools = _CASES[3]
    r = g.estimate("p", "m", msgs, tools)
    assert (r.calibrated, r.ratio) == (False, 1.0)
    assert r.tokens == r.raw == InferenceRouter._estimate_prompt_tokens(msgs, tools)


def test_ratio_converges_to_the_real_ratio_and_is_keyed_per_pair():
    g = ContextGauge()
    for _ in range(12):
        assert g.observe("p", "m", 1000, 800)
    assert g.ratio("p", "m") == pytest.approx(0.8, abs=1e-6)
    assert g.ratio("p", "other") is None          # a model switch never inherits
    assert g.ratio("q", "m") is None
    msgs = [{"role": "user", "content": "x" * 3481}]  # (3481 + 16) / 3.5 = 999.1 -> raw = 1000
    r = g.estimate("p", "m", msgs)
    assert r.calibrated and r.raw == 1000 and r.tokens == 800
    # the ratio moves toward a changed truth, monotonically
    prev = g.ratio("p", "m")
    for _ in range(10):
        g.observe("p", "m", 1000, 1200)
        cur = g.ratio("p", "m")
        assert prev < cur <= 1.2
        prev = cur


def test_first_observation_seeds_the_ratio():
    g = ContextGauge()
    g.observe("p", "m", 200, 100)
    assert g.ratio("p", "m") == pytest.approx(0.5)


def test_ratio_is_clamped_and_bad_pairs_are_refused():
    g = ContextGauge()
    g.observe("p", "m", 1, 10_000)
    assert g.ratio("p", "m") == cg.RATIO_MAX
    g.observe("p", "n", 10_000, 1)
    assert g.ratio("p", "n") == cg.RATIO_MIN
    for bad in [(0, 5), (5, 0), (-1, 5), (None, 5), ("x", 5)]:
        assert g.observe("p", "z", *bad) is False
    assert g.ratio("p", "z") is None


def test_state_is_bounded_and_least_recently_used_leaves():
    g = ContextGauge()
    for i in range(cg.MAX_ENTRIES + 10):
        g.observe("p", f"m{i}", 100, 90)
    assert len(g._ratios) == cg.MAX_ENTRIES
    assert g.ratio("p", "m0") is None
    assert g.ratio("p", f"m{cg.MAX_ENTRIES + 9}") is not None
    g.observe("p", "m10", 100, 90)  # touch: now newest
    g.observe("p", "fresh", 100, 90)
    assert g.ratio("p", "m10") is not None and g.ratio("p", "m11") is None


def test_concurrent_observes_keep_the_state_consistent():
    g = ContextGauge()

    def work(n: int) -> None:
        for _ in range(500):
            g.observe("p", f"m{n % 4}", 100, 80)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(g._ratios) == 4
    assert all(g.ratio("p", f"m{k}") == pytest.approx(0.8) for k in range(4))


def _wave0_calls():
    path = Path(__file__).with_name("clm_wave0_calls.json")
    return sorted(json.loads(path.read_text(encoding="utf-8"))["calls"], key=lambda c: c["seq"])


def test_calibrated_error_on_real_wave0_calls_beats_the_uncalibrated_error():
    """Online replay: each call is predicted BEFORE its own usage is observed."""
    calls = _wave0_calls()
    assert len(calls) == 129  # the T0.1 cohort the baseline table reports
    g = ContextGauge()
    raw_err, cal_err = [], []
    for c in calls:
        ratio = g.ratio(c["provider"], c["model"])
        if ratio is not None:
            raw_err.append(abs(c["est"] - c["real"]) / c["real"])
            cal_err.append(abs(round(c["est"] * ratio) - c["real"]) / c["real"])
        g.observe(c["provider"], c["model"], c["est"], c["real"])
    assert len(cal_err) == 128
    p90 = lambda v: sorted(v)[int(0.9 * (len(v) - 1))]  # noqa: E731
    # Measured 2026-11-12 (alpha 0.3): abs median 10.2 % -> 6.2 %, p90 31.7 % -> 15.7 %.
    # The spec target (p95 <= 5 %) is NOT met by a single scale ratio on this
    # mix and is not asserted here; it is reported by the replay script.
    assert statistics.median(cal_err) < statistics.median(raw_err)
    assert p90(cal_err) < p90(raw_err)
