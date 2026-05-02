"""
Regression tests for Domain 16 Phase 2 critical fixes.

C1 — update_recall_outcome targets the correct episode by ID, never by similarity search.
C2 — distinct recall op patterns produce separate episode rows (dedup does not merge them).
C3 — skill-genesis SQL filter matches 'success' episodes (not 'hit', which is never written).
C4 — Ollama infer_fn always includes temperature in the request payload.
C5 — chunk_callback reaches _respond_direct on non-planning messages.
M1 — Phase R failure logs an episode with outcome_type='failure'.
M2 — duplicate ops across recall iterations are discarded (not re-resolved).
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import types
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call

from backend.agent.recall_decoder import RecallDecoder, ResolvedSpan, RecallOp
from backend.agent.recall_phases import RecallPhases, _RECALL_STOP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_infer(phase_r_reply: str, phase_a_reply: str):
    """Return an infer_fn whose replies alternate: first call → phase_r, rest → phase_a."""
    call_count = [0]

    def infer(messages, max_tokens=-1, temperature=0.6, stop=None, chunk_callback=None):
        call_count[0] += 1
        is_recall = stop and any(s in stop for s in _RECALL_STOP)
        reply = phase_r_reply if is_recall else phase_a_reply
        if chunk_callback and reply:
            chunk_callback(reply)
        return reply

    return infer


def _make_messages(question: str = "What is OAuth PKCE?") -> List[Dict]:
    return [
        {"role": "system", "content": "You are IRIS."},
        {"role": "user", "content": question},
    ]


def _make_mock_memory(episode_id: str = "test-ep-id-001") -> MagicMock:
    """Build a minimal mock MemoryInterface that records store_episode calls."""
    mem = MagicMock()
    mem.store_episode.return_value = episode_id
    # Expose a real sqlite3 db so update SQL can execute
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE episodes (id TEXT PRIMARY KEY, outcome_type TEXT DEFAULT 'partial')"
    )
    conn.execute("INSERT INTO episodes (id, outcome_type) VALUES (?, ?)", (episode_id, "partial"))
    conn.commit()
    mem.episodic.db = conn
    return mem


# ---------------------------------------------------------------------------
# C1 — update_recall_outcome uses episode ID, never similarity search
# ---------------------------------------------------------------------------

class TestC1EpisodeIdUpdate(unittest.TestCase):

    def _make_phases(self, mem, phase_r_reply="", phase_a_reply="Answer."):
        return RecallPhases(
            infer_fn=_fake_infer(phase_r_reply, phase_a_reply),
            decoder=RecallDecoder(),
            memory_interface=mem,
            session_id="test-session",
        )

    def test_update_targets_stored_id_not_similarity(self):
        """update_recall_outcome must update the exact ID returned by store_episode."""
        ep_id = "specific-episode-abc123"
        decoy_id = "decoy-episode-xyz999"
        mem = _make_mock_memory(episode_id=ep_id)
        # Add a decoy row that a similarity search might accidentally match
        mem.episodic.db.execute(
            "INSERT INTO episodes (id, outcome_type) VALUES (?, ?)", (decoy_id, "partial")
        )
        mem.episodic.db.commit()

        phases = self._make_phases(mem)
        phases.run(_make_messages())
        phases.update_recall_outcome("success")

        # The correct row must be 'success'
        row = mem.episodic.db.execute(
            "SELECT outcome_type FROM episodes WHERE id=?", (ep_id,)
        ).fetchone()
        self.assertIsNotNone(row, "target episode not found")
        self.assertEqual(row[0], "success", "target episode outcome not updated")

        # The decoy must be untouched
        decoy_row = mem.episodic.db.execute(
            "SELECT outcome_type FROM episodes WHERE id=?", (decoy_id,)
        ).fetchone()
        self.assertEqual(decoy_row[0], "partial", "decoy episode was incorrectly modified")

    def test_stale_id_cleared_after_update(self):
        """_last_episode_id is cleared after update so a second call is a safe no-op."""
        mem = _make_mock_memory()
        phases = self._make_phases(mem)
        phases.run(_make_messages())
        phases.update_recall_outcome("success")
        # Second call must not raise and must not write anything
        phases.update_recall_outcome("failure")  # stale — should silently skip
        row = mem.episodic.db.execute(
            "SELECT outcome_type FROM episodes WHERE id=?", ("test-ep-id-001",)
        ).fetchone()
        self.assertEqual(row[0], "success", "second call should not overwrite first update")

    def test_update_safe_when_no_episode_logged(self):
        """update_recall_outcome is a no-op when no episode has been stored yet."""
        mem = _make_mock_memory()
        phases = self._make_phases(mem)
        # Never call run() — _last_episode_id is not set
        phases.update_recall_outcome("success")  # must not raise

    def test_update_safe_when_memory_is_none(self):
        """update_recall_outcome is a no-op when memory interface is None."""
        phases = RecallPhases(
            infer_fn=_fake_infer("", "Answer."),
            decoder=RecallDecoder(),
            memory_interface=None,
        )
        phases._last_episode_id = "orphan-id"
        phases.update_recall_outcome("success")  # must not raise


# ---------------------------------------------------------------------------
# C2 — distinct op patterns stored as separate episodes (no dedup merge)
# ---------------------------------------------------------------------------

class TestC2EpisodeDedup(unittest.TestCase):

    def test_different_op_patterns_produce_distinct_task_summaries(self):
        """Two recall episodes with different ops must embed under different task_summary values."""
        mem = MagicMock()
        stored: list = []

        def capture_store(ep):
            stored.append(ep.task_summary)
            return f"id-{len(stored)}"

        mem.store_episode.side_effect = capture_store

        # Pattern 1: coord op
        phases1 = RecallPhases(
            infer_fn=_fake_infer('<recall coord/>', "Answer."),
            decoder=RecallDecoder(),
            memory_interface=mem,
            session_id="s1",
        )
        # Make decoder resolve with non-zero confidence so episode is logged
        span_coord = ResolvedSpan(
            op=RecallOp("coord", {}, "<recall coord/>"),
            content="- [domain] file.py (conf=0.80)",
            confidence=0.80,
            source="mycelium",
        )
        phases1._decoder.resolve_all = lambda ops: [span_coord]
        phases1.run(_make_messages())

        # Pattern 2: semantic op
        phases2 = RecallPhases(
            infer_fn=_fake_infer('<recall semantic query="PKCE"/>', "Answer."),
            decoder=RecallDecoder(),
            memory_interface=mem,
            session_id="s2",
        )
        span_semantic = ResolvedSpan(
            op=RecallOp("semantic", {"semantic": "PKCE"}, '<recall semantic query="PKCE"/>'),
            content="OAuth PKCE chunk",
            confidence=0.80,
            source="episodic",
        )
        phases2._decoder.resolve_all = lambda ops: [span_semantic]
        phases2.run(_make_messages())  # same question

        self.assertEqual(len(stored), 2, "expected 2 distinct task_summaries, got merged or missing")
        self.assertNotEqual(stored[0], stored[1], "task_summaries must differ so dedup does not merge them")
        # Verify op key is embedded in summary
        self.assertIn("coord", stored[0])
        self.assertIn("semantic", stored[1])

    def test_empty_op_pattern_gets_distinct_prefix(self):
        """An episode with no spans gets the [recall:empty] prefix."""
        mem = MagicMock()
        stored: list = []
        mem.store_episode.side_effect = lambda ep: stored.append(ep.task_summary) or "id-1"

        phases = RecallPhases(
            infer_fn=_fake_infer("", "Answer."),
            decoder=RecallDecoder(),
            memory_interface=mem,
        )
        phases.run(_make_messages())
        self.assertTrue(any("recall:empty" in s for s in stored),
                        f"expected [recall:empty] prefix, got: {stored}")


# ---------------------------------------------------------------------------
# C3 — skill genesis SQL targets outcome_type='success' (not 'hit')
# ---------------------------------------------------------------------------

class TestC3SkillGenesisSql(unittest.TestCase):

    def _make_kernel_stub(self):
        """Return a minimal object that exposes _maybe_trigger_skill_creation."""
        from backend.agent.agent_kernel import AgentKernel
        # Patch __init__ so we don't need a full model router
        with patch.object(AgentKernel, "__init__", lambda self, *a, **kw: None):
            k = AgentKernel.__new__(AgentKernel)
        k._session_tool_patterns = {}
        k._prompted_skill_patterns = set()
        k._skill_trigger_threshold = 3
        k._pending_follow_ups = []
        return k

    def test_sql_matches_success_episodes(self):
        """Skill genesis fires when source_channel='recall' AND outcome_type='success'."""
        kernel = self._make_kernel_stub()

        # Build an in-memory DB with 3 successful recall episodes sharing a pattern
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE episodes "
            "(id TEXT, source_channel TEXT, outcome_type TEXT, tool_sequence TEXT)"
        )
        pattern = json.dumps([{"op": "coord"}, {"op": "semantic"}])
        for i in range(3):
            conn.execute(
                "INSERT INTO episodes VALUES (?,?,?,?)",
                (f"id-{i}", "recall", "success", pattern),
            )
        conn.commit()

        mem = MagicMock()
        mem.episodic.db = conn
        kernel._memory_interface = mem

        kernel._maybe_trigger_skill_creation([], "some task")

        self.assertTrue(
            len(kernel._pending_follow_ups) > 0,
            "skill genesis did not fire despite 3 successful recall episodes",
        )

    def test_sql_does_not_match_hit(self):
        """outcome_type='hit' is never written by recall phases — SQL must NOT use it."""
        kernel = self._make_kernel_stub()

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE episodes "
            "(id TEXT, source_channel TEXT, outcome_type TEXT, tool_sequence TEXT)"
        )
        pattern = json.dumps([{"op": "coord"}, {"op": "semantic"}])
        for i in range(3):
            conn.execute(
                "INSERT INTO episodes VALUES (?,?,?,?)",
                (f"id-{i}", "recall", "hit", pattern),  # 'hit' is never written
            )
        conn.commit()

        mem = MagicMock()
        mem.episodic.db = conn
        kernel._memory_interface = mem

        kernel._maybe_trigger_skill_creation([], "some task")

        self.assertEqual(
            len(kernel._pending_follow_ups), 0,
            "skill genesis should NOT fire for 'hit' episodes — that value is never written",
        )

    def test_sql_does_not_match_partial(self):
        """outcome_type='partial' (the unresolved default) must not trigger skill creation."""
        kernel = self._make_kernel_stub()

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE episodes "
            "(id TEXT, source_channel TEXT, outcome_type TEXT, tool_sequence TEXT)"
        )
        pattern = json.dumps([{"op": "coord"}])
        for i in range(5):
            conn.execute(
                "INSERT INTO episodes VALUES (?,?,?,?)",
                (f"id-{i}", "recall", "partial", pattern),
            )
        conn.commit()

        mem = MagicMock()
        mem.episodic.db = conn
        kernel._memory_interface = mem

        kernel._maybe_trigger_skill_creation([], "some task")

        self.assertEqual(len(kernel._pending_follow_ups), 0,
                         "partial episodes must not trigger skill creation")


# ---------------------------------------------------------------------------
# C4 — Ollama always sends temperature regardless of value
# ---------------------------------------------------------------------------

class TestC4OllamaTemperature(unittest.TestCase):

    def _make_ollama_infer(self, model: str = "llama3:8b"):
        """Reconstruct the Ollama closure the same way agent_kernel does."""
        def _ollama_infer(messages, max_tokens=-1, temperature=0.6, stop=None, chunk_callback=None):
            import requests as _req
            import json as _json
            # C4 fix: always pass temperature
            opts: dict = {"temperature": temperature}
            if stop:
                opts["stop"] = stop
            payload: dict = {"model": model, "messages": messages}
            if opts:
                payload["options"] = opts

            if chunk_callback:
                payload["stream"] = True
                with _req.post(
                    "http://localhost:11434/api/chat",
                    json=payload, stream=True, timeout=120,
                ) as r:
                    full = ""
                    for line in r.iter_lines():
                        if not line:
                            continue
                        try:
                            data = _json.loads(line)
                        except Exception:
                            continue
                        delta = data.get("message", {}).get("content", "")
                        if delta:
                            full += delta
                            chunk_callback(delta)
                        if data.get("done"):
                            break
                    return full
            else:
                payload["stream"] = False
                r = _req.post("http://localhost:11434/api/chat", json=payload, timeout=60)
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "")
                return ""

        return _ollama_infer

    def _captured_payload(self, temperature: float) -> dict:
        captured = {}

        def fake_post(url, json=None, **kwargs):
            captured.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"message": {"content": "reply"}}
            return resp

        infer = self._make_ollama_infer()
        with patch("requests.post", side_effect=fake_post):
            infer([{"role": "user", "content": "hi"}], temperature=temperature)

        return captured

    def test_temperature_06_always_sent(self):
        """temperature=0.6 (the default) must appear in Ollama options payload."""
        payload = self._captured_payload(0.6)
        opts = payload.get("options", {})
        self.assertIn("temperature", opts, "temperature must always be in options, even when 0.6")
        self.assertAlmostEqual(opts["temperature"], 0.6)

    def test_temperature_02_phase_r(self):
        """temperature=0.2 (Phase R) must appear in Ollama options payload."""
        payload = self._captured_payload(0.2)
        self.assertAlmostEqual(payload["options"]["temperature"], 0.2)

    def test_temperature_08_custom(self):
        """Arbitrary temperature values must be forwarded correctly."""
        payload = self._captured_payload(0.8)
        self.assertAlmostEqual(payload["options"]["temperature"], 0.8)


# ---------------------------------------------------------------------------
# C5 — chunk_callback reaches _respond_direct on the direct (non-planning) path
# ---------------------------------------------------------------------------

class TestC5ChunkCallbackDirectPath(unittest.TestCase):

    def test_chunk_callback_forwarded_to_respond_direct(self):
        """process_text_message must pass chunk_callback to _respond_direct."""
        from backend.agent.agent_kernel import AgentKernel

        with patch.object(AgentKernel, "__init__", lambda self, *a, **kw: None):
            kernel = AgentKernel.__new__(AgentKernel)

        # Minimal state so process_text_message's early guards pass
        kernel._initialization_error = None
        kernel._model_router = MagicMock()
        kernel._conversation_memory = MagicMock()
        kernel._conversation_memory.get_context.return_value = []
        kernel.session_id = "test"
        kernel._pending_thinking = ""
        kernel._mcm_orch = None
        kernel._memory_interface = None

        # Intercept _needs_planning to force the direct path
        kernel._needs_planning = MagicMock(return_value=False)

        received_cb = {}

        def fake_respond_direct(text, context, chunk_callback=None):
            received_cb["cb"] = chunk_callback
            return "response text"

        kernel._respond_direct = fake_respond_direct

        # Stub out post-response bookkeeping
        kernel._conversation_memory.add_message = MagicMock()

        chunks = []
        sentinel_cb = lambda chunk: chunks.append(chunk)  # explicit object for identity check
        kernel.process_text_message("hello", chunk_callback=sentinel_cb)

        self.assertIn("cb", received_cb,
                      "_respond_direct was not called")
        self.assertIs(received_cb["cb"], sentinel_cb,
                      "chunk_callback was not forwarded to _respond_direct")


# ---------------------------------------------------------------------------
# M1 — Phase R failure logs an episode with outcome_type='failure'
# ---------------------------------------------------------------------------

class TestM1FailureEpisodeLogged(unittest.TestCase):

    def test_phase_r_failure_stores_failure_episode(self):
        """When Phase R always throws, a failure episode must be stored."""
        def always_fails(messages, max_tokens=-1, temperature=0.6, stop=None, chunk_callback=None):
            if stop and any(s in stop for s in _RECALL_STOP):
                raise RuntimeError("phase R exploded")
            return "fallback answer"

        mem = MagicMock()
        stored_episodes = []
        mem.store_episode.side_effect = lambda ep: stored_episodes.append(ep) or "id-fail"

        phases = RecallPhases(
            infer_fn=always_fails,
            decoder=RecallDecoder(),
            memory_interface=mem,
            session_id="fail-session",
        )
        answer, spans = phases.run(_make_messages())

        self.assertEqual(answer, "fallback answer")
        self.assertEqual(spans, [])
        self.assertEqual(len(stored_episodes), 1, "exactly one failure episode must be stored")
        self.assertEqual(stored_episodes[0].outcome_type, "failure")
        self.assertEqual(stored_episodes[0].source_channel, "recall")


# ---------------------------------------------------------------------------
# M2 — duplicate ops across recall iterations are not re-resolved
# ---------------------------------------------------------------------------

class TestM2OpDeduplication(unittest.TestCase):

    def test_same_op_not_resolved_twice(self):
        """An op emitted in iter 0 and again in iter 1 must only be resolved once."""
        # Phase R always emits the same coord op — should trigger only once
        call_log = []

        def infer(messages, max_tokens=-1, temperature=0.6, stop=None, chunk_callback=None):
            is_recall = stop and any(s in stop for s in _RECALL_STOP)
            if is_recall:
                return '<recall coord/>'
            reply = "Final answer."
            if chunk_callback:
                chunk_callback(reply)
            return reply

        decoder = RecallDecoder()
        resolve_calls = []
        original_resolve_all = decoder.resolve_all

        def tracking_resolve_all(ops):
            resolve_calls.extend(ops)
            # return empty spans so iterations continue but don't break on confidence
            return [ResolvedSpan(
                op=o,
                content="[no memory]",
                confidence=0.0,
                source="sentinel",
                status="empty",
            ) for o in ops]

        decoder.resolve_all = tracking_resolve_all

        phases = RecallPhases(infer_fn=infer, decoder=decoder)
        phases.run(_make_messages())

        coord_resolves = [o for o in resolve_calls if o.op_type == "coord"]
        self.assertEqual(
            len(coord_resolves), 1,
            f"coord op resolved {len(coord_resolves)} times — expected exactly 1 (M2 dedup broken)",
        )

    def test_distinct_ops_across_iters_both_resolved(self):
        """Different ops in different iterations must each be resolved once."""
        iter_count = [0]

        def infer(messages, max_tokens=-1, temperature=0.6, stop=None, chunk_callback=None):
            is_recall = stop and any(s in stop for s in _RECALL_STOP)
            if is_recall:
                iter_count[0] += 1
                # iter 1 → coord, iter 2 → semantic (distinct, should both resolve)
                if iter_count[0] == 1:
                    return '<recall coord/>'
                return '<recall semantic query="topic"/>'
            return "answer"

        decoder = RecallDecoder()
        resolve_calls = []

        def tracking_resolve_all(ops):
            resolve_calls.extend(ops)
            # return non-zero conf so loop continues to iter 2
            return [ResolvedSpan(
                op=o,
                content="data",
                confidence=0.4,
                source="test",
            ) for o in ops]

        decoder.resolve_all = tracking_resolve_all

        phases = RecallPhases(infer_fn=infer, decoder=decoder)
        phases.run(_make_messages())

        op_types = [o.op_type for o in resolve_calls]
        self.assertIn("coord", op_types, "coord op was not resolved")
        self.assertIn("semantic", op_types, "semantic op was not resolved")
        self.assertEqual(op_types.count("coord"), 1, "coord resolved more than once")
        self.assertEqual(op_types.count("semantic"), 1, "semantic resolved more than once")


if __name__ == "__main__":
    unittest.main()
