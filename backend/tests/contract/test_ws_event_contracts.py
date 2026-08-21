"""Contract tests — cli-workspace-unification T12 (REQ-1..REQ-10).

CT-1: task:start WS event contract — the payload is built at ONE construction
      point (agent_kernel._task_start_payload) and carries the multi-agent
      Kanban tags (agent_id / project_id) ADDITIVELY; the tags are
      backend-emitted, never frontend-fabricated (REQ-5 AC1).
CT-2: set_web_mode contract — the gateway's `{enabled: bool}` payload flips
      the app-wide internet-access gate (REQ-1 AC2 web capability gate).
CT-3: HF Hub bridge contracts — filename sanitization rejects path traversal;
      search results are shaped (repo/author/likes/downloads/gguf files) and
      upstream failures are surfaced, never fabricated (REQ-9).

These pins are derived from real behavioral traces of the running system and
are the boundary guards for the standing CDD harness
(scripts/validate_der_cli_harness.py).
"""

import asyncio
from unittest.mock import patch

import pytest

from backend.agent.agent_kernel import AgentKernel, get_global_internet_access, set_global_internet_access


# ── CT-1: task:start multi-agent tag contract ───────────────────────────────


class _TagsKernel(AgentKernel):
    """Expose the tag resolver without running __init__ (71s cold kernel)."""


def _make_kernel(session_id="sess_ct1", conversation_id="conv_ct1"):
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = session_id
    k.conversation_id = conversation_id
    return k


class TestCT1MultiAgentTags:
    def test_tags_emitted_from_kernel_identity(self):
        """agent_id derives from the kernel session identity; project_id from
        the active project scope (None until a project is set)."""
        k = _make_kernel()
        tags = k._multiagent_tags()
        assert tags["agent_id"] == "sess_ct1"
        assert tags["project_id"] is None

        k.active_project_id = "proj_irisvoice"
        tags = k._multiagent_tags()
        assert tags["project_id"] == "proj_irisvoice"

    def test_payload_carries_tags_at_the_single_construction_point(self):
        """The SAME construction point that carries card_id/card_relation/
        conversation_id also carries agent_id/project_id — every emit site
        inherits them."""
        k = _make_kernel()
        payload = AgentKernel._task_start_payload(
            task_id="t1",
            description="d",
            plan_title="p",
            mode="full",
            steps=[],
            total_steps=0,
            origin="initial",
            card_id="card_t1",
            card_relation="new",
            conversation_id=k.conversation_id,
            **k._multiagent_tags(),
        )
        assert payload["agent_id"] == "sess_ct1"
        assert payload["project_id"] is None
        # The identity keys it must travel beside:
        assert payload["card_id"] == "card_t1"
        assert payload["card_relation"] == "new"
        assert payload["conversation_id"] == "conv_ct1"

    def test_additive_only_base_keys_unchanged(self):
        """Additivity guard: the pre-T9a ten keys keep their names and
        meanings; exactly two keys were added."""
        payload = AgentKernel._task_start_payload(
            task_id="t", description="d", plan_title="p", mode="m",
            steps=[], total_steps=0, origin="initial",
            card_id="c", card_relation="new", conversation_id="cv",
        )
        base = {"task_id", "description", "plan_title", "mode", "steps",
                "total_steps", "origin", "card_id", "card_relation",
                "conversation_id"}
        assert base <= set(payload.keys())
        assert set(payload.keys()) - base == {"agent_id", "project_id"}

    def test_missing_tags_fall_back_to_conversation_keying(self):
        """Older emitters may omit the tags — the payload tolerates None so
        consumers fall back to conversationId-only keying and never drop the
        Kanban card (design.md Error Handling)."""
        payload = AgentKernel._task_start_payload(
            task_id="t", description="d", plan_title="p", mode="m",
            steps=[], total_steps=0, origin="initial",
            card_id="c", card_relation="new", conversation_id="conv_only",
            agent_id=None, project_id=None,
        )
        assert payload["agent_id"] is None
        assert payload["project_id"] is None
        assert payload["conversation_id"] == "conv_only"


# ── CT-2: set_web_mode contract ─────────────────────────────────────────────


class TestCT2WebModeContract:
    @pytest.fixture(autouse=True)
    def _restore_gate(self):
        """Leave the global gate exactly as found — it is process-wide state."""
        before = get_global_internet_access()
        yield
        set_global_internet_access(before)

    def test_enabled_true_turns_gate_on(self):
        set_global_internet_access(True)
        assert get_global_internet_access() is True

    def test_enabled_false_turns_gate_off(self):
        set_global_internet_access(False)
        assert get_global_internet_access() is False

    def test_gateway_bool_coercion(self):
        """The gateway does `bool(payload.get('enabled', False))` — truthy and
        falsy payloads must map onto the gate exactly as the UI sent them."""
        # Mirrors iris_gateway.py:744 without opening a socket.
        for raw, expected in [(True, True), (False, False), (1, True), (0, False), ("x", True), ("", False)]:
            enabled = bool(raw)
            set_global_internet_access(enabled)
            assert get_global_internet_access() is expected


# ── CT-3: Hugging Face bridge contracts ─────────────────────────────────────


class TestCT3FilenameSanitization:
    """REQ-9 AC7 path-traversal guard: downloads stay inside models/."""

    def _sanitize(self, name):
        from backend.main import _sanitize_hf_filename

        return _sanitize_hf_filename(name)

    def test_valid_gguf_passes_through(self):
        assert self._sanitize("qwen2.5-coder-7b.Q4_K_M.gguf") == "qwen2.5-coder-7b.Q4_K_M.gguf"

    @pytest.mark.parametrize("bad", [
        "../escape.gguf",
        "..\\escape.gguf",
        "sub/dir/model.gguf",
        "sub\\dir\\model.gguf",
        "model.gguf/../../etc/passwd",
        "",
        "model.exe",
        "model$$.gguf",
    ])
    def test_unsafe_names_rejected(self, bad):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._sanitize(bad)
        assert exc.value.status_code == 400


class TestCT3SearchShaping:
    """REQ-9 AC5/AC6: search returns repo title, author, likes, downloads and
    .gguf quant files with sizes. Upstream failure -> surfaced error."""

    def _run_search(self, hf_status=200, hf_payload=None, raise_exc=None):
        import backend.main as main_mod

        class _FakeResp:
            def __init__(self):
                self.status_code = hf_status

            def json(self):
                return hf_payload or []

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                if raise_exc:
                    raise raise_exc
                return _FakeResp()

        # The endpoint does `import httpx` locally, so patching the attribute
        # on the shared httpx module intercepts it.
        with patch("httpx.AsyncClient", _FakeClient):
            return asyncio.run(main_mod.api_hf_search(q="gguf"))

    def test_results_shaped_from_hf_payload(self):
        resp = self._run_search(hf_payload=[{
            "id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
            "likes": 42,
            "downloads": 1000,
            "gated": False,
            "siblings": [
                {"rfilename": "model.Q4_K_M.gguf", "size": 4680000000},
                {"rfilename": "README.md", "size": 100},
            ],
        }])
        assert len(resp["results"]) == 1
        r = resp["results"][0]
        assert r["repo_id"] == "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
        assert r["author"] == "Qwen"
        assert r["likes"] == 42 and r["downloads"] == 1000
        # Only .gguf siblings surface as downloadable quants.
        assert [f["filename"] for f in r["gguf_files"]] == ["model.Q4_K_M.gguf"]
        assert r["gguf_files"][0]["size"] == 4680000000

    def test_upstream_error_surfaced_not_fabricated(self):
        resp = self._run_search(hf_status=429)
        assert resp.status_code == 502
        assert "429" in resp.body.decode()

    def test_upstream_exception_surfaced(self):
        resp = self._run_search(raise_exc=ConnectionError("dns fail"))
        assert resp.status_code == 502
        assert "unreachable" in resp.body.decode()
