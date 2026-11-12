"""CLM Wave 1 (T1.4, T1.5) wiring pins for the router.

1. After a call that reports real ``prompt_tokens``, ``generate`` teaches the
   gauge the (provider, model) ratio from the estimate of the messages that
   were SENT (after the cap).
2. A router-cap drop is a blind drop: counted (calls, messages, estimated
   tokens) and carried in the cap's report; a cap that drops nothing counts 0.
3. CT-9b: one estimator. The router holds no copy of the chars/3.5 rule; the
   rule lives in ``context_gauge`` only (the Wave 0 instrument's tools-schema
   size helper in ``clm_baseline`` is the one allowed second use: it measures
   block sizes for a report and decides nothing).
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import backend.agent.inference.registry as _reg_mod
import backend.agent.inference.roles as _roles_mod
from backend.agent import context_gauge as cg
from backend.agent.inference.router import InferenceRouter
from backend.iris_config import InferenceConfig, ProviderEntry


@pytest.fixture()
def router(monkeypatch):
    _reg_mod._REGISTRY = None
    _roles_mod._ROLES = None
    cfg = InferenceConfig()
    cfg.providers = {
        "p1": ProviderEntry(id="p1", label="p", kind="API", model="m1",
                            endpoint="https://api.example.test/v1", cred_ref="p1"),
    }
    r = InferenceRouter(cfg)
    r.bind_role("reasoning", "p1")

    class _Transport:
        last_usage = {"prompt_tokens": 400, "completion_tokens": 5, "total_tokens": 405}

        def generate(self, model, messages, tools, **kw):
            self.sent = messages
            return ("ok", None, [])

    t = _Transport()
    monkeypatch.setattr(r, "_build_transport", lambda inst: t)
    monkeypatch.setattr(cg, "GAUGE", cg.ContextGauge())
    import backend.agent.inference.router as rmod
    monkeypatch.setattr(rmod, "_GAUGE", cg.GAUGE)
    yield r, t
    _reg_mod._REGISTRY = None
    _roles_mod._ROLES = None


def test_generate_teaches_the_gauge_from_the_messages_actually_sent(router):
    r, t = router
    msgs = [{"role": "system", "content": "s" * 300}, {"role": "user", "content": "u" * 1000}]
    r.generate("reasoning", msgs)
    est = cg.estimate_tokens(t.sent, None)
    assert cg.GAUGE.ratio("p1", "m1") == pytest.approx(400 / est)


def test_a_cap_drop_is_counted_as_a_blind_drop():
    before = cg.blind_drop_snapshot()
    msgs = [{"role": "system", "content": "s"}] + [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 4000} for i in range(10)
    ] + [{"role": "user", "content": "now"}]
    report: dict = {}
    kept = InferenceRouter._cap_messages_to_window(msgs, None, window=2000, max_tokens=256, report=report)
    after = cg.blind_drop_snapshot()
    dropped = len(msgs) - len(kept)
    assert dropped > 0
    assert after["calls"] == before["calls"] + 1
    assert after["messages"] == before["messages"] + dropped
    assert after["tokens"] > before["tokens"]
    assert report["blind_drop"] == after


def test_a_cap_that_drops_nothing_counts_nothing():
    before = cg.blind_drop_snapshot()
    InferenceRouter._cap_messages_to_window(
        [{"role": "user", "content": "hi"}], None, window=100_000, max_tokens=256)
    assert cg.blind_drop_snapshot() == before


def test_ct9b_the_router_holds_no_copy_of_the_estimator_rule():
    src = inspect.getsource(InferenceRouter._estimate_prompt_tokens)
    assert "3.5" not in src and "chars" not in src and "_estimate_tokens(" in src


def test_ct9b_the_chars_per_token_rule_lives_in_the_gauge_only():
    root = Path(__file__).resolve().parents[2] / "agent"
    allowed = {"context_gauge.py", "clm_baseline.py"}  # clm_baseline: report-only block sizes
    hits = [
        str(p.relative_to(root)) for p in root.rglob("*.py")
        if p.name not in allowed and re.search(r"/\s*3\.5\b", p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert hits == []
