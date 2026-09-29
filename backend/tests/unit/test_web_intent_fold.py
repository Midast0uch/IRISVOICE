"""Unit tests: the web_intent fold (REQ-15 AC15.3, T19).

Three copies of the web-trigger list used to exist (agent_kernel x2,
explorer x1). After T19 there is ONE consumer — the engine's `web_intent`
judgment wins when available, and the keyword list is the fallback only.
"""

from __future__ import annotations

import ast
from pathlib import Path

from backend.agent import explorer as ex
from backend.agent.decision_engine import Noul

_REPO = Path(__file__).resolve().parents[3]


class _Engine:
    def __init__(self, web: bool):
        self._web = web

    def noul(self, consumer_id, statement, frame, *, true_label="yes",
             false_label="no"):
        return Noul(consumer_id=consumer_id,
                    probability=0.95 if self._web else 0.05,
                    engine_latency_ms=1)


class TestSingleConsumerNoCopies:
    def test_single_consumer_no_copies(self):
        """AC15.3: the engine's web_intent verdict wins, and the duplicated
        trigger lists are gone from the kernel."""
        # (a) engine says web → True even for a phrase no keyword matches
        assert ex._is_web_intent("please grab that article for me",
                                 engine=_Engine(web=True)) is True
        # (b) engine says not web → False even for a phrase a keyword matches
        assert ex._is_web_intent("research the design pattern locally",
                                 engine=_Engine(web=False)) is False
        # (c) no engine → the keyword fallback, unchanged
        assert ex._is_web_intent("research everything about X") is True
        assert ex._is_web_intent("hello") is False
        # (d) no engine means NO engine — never the module singleton
        assert ex._is_web_intent("") is False

        # (e) the kernel's private copy is gone: its method delegates
        src = (_REPO / "backend" / "agent" / "agent_kernel.py").read_text(
            encoding="utf-8", errors="replace")
        tree = ast.parse(src)
        fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_is_web_search_request":
                fn = node
                break
        assert fn is not None
        body = ast.get_source_segment(src, fn) or ""
        assert "_triggers" not in body, (
            "the kernel still carries its own web-trigger list — the fold "
            "into the single consumer did not happen"
        )
        assert "_is_web_intent" in body

    def test_the_web_intent_consumer_is_registered(self):
        """AC15.3: the consumer has its own criteria (never a borrowed head)."""
        from backend.agent.decision_backend_onnx import get_consumer_spec

        first = ex.register_web_intent_consumer()
        # Either it registered just now, or an earlier call in this process
        # already did (the scoring path registers lazily) — both are fine.
        assert first in (True, False)
        spec = get_consumer_spec(ex.WEB_INTENT_CONSUMER)
        assert spec is not None
        assert list(spec.labels) == ["yes", "no"]
        # and a second registration is a no-op, not a duplicate (CT-8)
        assert ex.register_web_intent_consumer() is False
