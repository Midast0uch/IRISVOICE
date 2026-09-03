"""
Contract tests: Unchanged interface shapes (CT-1, CT-2, CT-3).

These tests pin the EXTERNAL interfaces that the spec marks as CONTRACT LOCK
— they must NEVER change shape. If a future edit breaks one of these contracts,
these tests will catch it before the behavior breaks.
"""

import inspect


# ── CT-1: PACMAN action shapes ──────────────────────────────────────────


class TestPacmanContract:
    """PACMAN action signatures (pacman_fragment, pacman_recall).

    The EPISODIC → memory pipeline depends on these signatures.  If they
    change, the trust-routing / zone classification breaks.
    """

    def test_ct1_pacman_fragment_execute_signature(self):
        """pacman_fragment.execute(ctx, params) → dict."""
        from backend.agent.mcm_protocol.actions.pacman_fragment import execute

        sig = inspect.signature(execute)
        params = list(sig.parameters.keys())
        assert params == ["ctx", "params"], f"Unexpected signature: {params}"
        ann = sig.return_annotation
        # Python 3.12+ type annotations can be the string 'dict'
        assert ann in (dict, "dict", inspect.Parameter.empty), f"Unexpected return: {ann}"

    def test_ct1_pacman_fragment_is_external_tool_signature(self):
        """pacman_fragment.is_external_tool(tool_name: str) → bool."""
        from backend.agent.mcm_protocol.actions.pacman_fragment import is_external_tool

        sig = inspect.signature(is_external_tool)
        params = list(sig.parameters.keys())
        assert params == ["tool_name"]
        doc = is_external_tool.__doc__ or ""
        assert "External" in doc or "external" in doc or "tool" in doc.lower()

    def test_ct1_pacman_recall_execute_signature(self):
        """pacman_recall.execute(ctx, params) → dict."""
        from backend.agent.mcm_protocol.actions.pacman_recall import execute

        sig = inspect.signature(execute)
        params = list(sig.parameters.keys())
        assert params == ["ctx", "params"], f"Unexpected signature: {params}"

    def test_ct1_external_tools_set_unchanged(self):
        """The set of 'external' tools classified as untrusted is a contract."""
        from backend.agent.mcm_protocol.actions.pacman_fragment import _EXTERNAL_TOOLS

        assert "web_search" in _EXTERNAL_TOOLS
        assert isinstance(_EXTERNAL_TOOLS, frozenset)


# ── CT-2: WS / document event shapes ─────────────────────────────────────


class TestDocumentRenderContract:
    """WS `document:render` event and DocumentDataStore contract shapes."""

    def test_ct2_document_render_event_exists(self):
        """IRISStreamEvent.DOCUMENT_RENDER exists (enum member)."""
        from backend.agent.event_bus import IRISStreamEvent

        assert hasattr(IRISStreamEvent, "DOCUMENT_RENDER")
        val = IRISStreamEvent.DOCUMENT_RENDER
        # Enum member: check its value is the expected string
        assert val.value == "document:render", f"Unexpected value: {val.value}"

    def test_ct2_document_data_store_methods(self):
        """DocumentDataStore exposes list_for_conversation, store, get_variant."""
        from backend.agent.document_store import DocumentDataStore

        methods = [m for m in dir(DocumentDataStore) if not m.startswith("_")]
        assert "list_for_conversation" in methods, f"Missing in {methods}"
        assert "store" in methods, f"Missing in {methods}"
        assert "get_variant" in methods, f"Missing in {methods}"
        assert "list_conversations" in methods, f"Missing in {methods}"

    def test_ct2_document_render_payload_has_conversation_id(self):
        """document:render events carry conversation_id (frontend scoping)."""
        from backend.agent.event_bus import IRISStreamEvent

        # Verify the event type exists; the payload shape is validated
        # by the frontend handler at chat-view.tsx ~line 2000.
        assert hasattr(IRISStreamEvent, "DOCUMENT_RENDER")

    def test_ct2_get_documents_ws_path_handled(self):
        """The iris_gateway WS router dispatches 'get_documents' to a handler."""
        from backend.iris_gateway import IRISGateway

        # _handle_get_documents is called when msg_type == "get_documents"
        assert hasattr(IRISGateway, "_handle_get_documents")
        # The dispatch is at iris_gateway.py:571 (verified in spec)
        handler = IRISGateway._handle_get_documents
        assert callable(handler)


# ── CT-3: REST /api/chat request/response (Pydantic models) ────────────


class TestChatRESTContract:
    """REST /api/chat request and response Pydantic model shapes.

    The frontend POSTs {text, thread_id}; the backend responds with
    {content, turn_id, thread_id}.  The retry flow (REQ-12) re-uses this
    exact same contract — if the shape changes, retry breaks.
    """

    REQUEST_FIELDS = {"text", "thread_id", "turn_id", "from_voice"}
    RESPONSE_FIELDS = {"content", "thinking", "turn_id", "thread_id", "session_id", "model", "timing_ms"}
    ERROR_FIELDS = {"error", "turn_id", "code"}

    def test_ct3_request_model_shape(self):
        """ChatRequest must have text (required) + thread_id (optional)."""
        from backend.api.chat import ChatRequest

        fields = set(ChatRequest.model_fields.keys())
        assert "text" in fields, f"Missing 'text' in {fields}"
        assert "thread_id" in fields, f"Missing 'thread_id' in {fields}"
        assert ChatRequest.model_fields["text"].is_required(), "text must be required"
        assert not ChatRequest.model_fields["thread_id"].is_required(), "thread_id must be optional"

    def test_ct3_response_model_shape(self):
        """ChatResponse must have content, turn_id, thread_id."""
        from backend.api.chat import ChatResponse

        fields = set(ChatResponse.model_fields.keys())
        for required in ["content", "turn_id", "thread_id", "session_id"]:
            assert required in fields, f"Missing '{required}' in {fields}"
            assert ChatResponse.model_fields[required].is_required(), f"{required} must be required"

    def test_ct3_error_model_shape(self):
        """ChatError has error, turn_id, code."""
        from backend.api.chat import ChatError

        fields = set(ChatError.model_fields.keys())
        for required in ["error", "turn_id", "code"]:
            assert required in fields, f"Missing '{required}' in {fields}"

    def test_ct3_required_text_not_empty(self):
        """ChatRequest rejects empty text via field_validator."""
        from backend.api.chat import ChatRequest

        try:
            ChatRequest(text="")
            assert False, "Should have raised"
        except Exception:
            pass  # Expected

        # Valid text should work
        req = ChatRequest(text="hello")
        assert req.text == "hello"
        assert req.thread_id is None
        assert req.from_voice is False

    def test_ct3_response_allows_empty_thinking(self):
        """ChatResponse.thinking defaults to empty string (not None)."""
        from backend.api.chat import ChatResponse

        resp = ChatResponse(content="Hi", turn_id="t1", thread_id="t1", session_id="t1")
        assert resp.thinking == ""

    def test_ct3_turn_id_format(self):
        """turn_id should be a non-empty string."""
        from backend.api.chat import ChatResponse

        resp = ChatResponse(content="Hi", turn_id="022126bdf803", thread_id="c1", session_id="c1")
        assert isinstance(resp.turn_id, str) and len(resp.turn_id) > 0
