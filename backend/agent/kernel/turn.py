# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import re
from backend.agent.mcm_protocol.actions.pacman_fragment import is_external_tool
from backend.agent import streaming as _streaming
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind, DispatchResult
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import asyncio
import time
from backend.utils.observability import (
    TurnMetrics,
    loud_error,
    get_turn_id,
    broadcast_inference_event,
)
from backend.agent.kernel.base import (
    DER_TOKEN_BUDGETS,
    _turn_in_flight,
    logger,
)


# A goal that ACTS on a web page (browser control, not a search). "type of" and
# "press release" are reading phrases, not actions.
_BROWSER_ACTION_RE = re.compile(
    r"\b(?:in\s+the\s+(?:live\s+|in-app\s+)?browser|click|tap|type(?!\s+of)|"
    r"fill(?:\s+(?:in|out))?|scroll|press(?!\s+release)|submit|log\s?in|sign\s?in|"
    r"select|add\s+to\s+(?:cart|basket)|check\s?out|navigate|hover|drag)\b",
    re.IGNORECASE,
)

# The user names the live browser: the request cannot be done without it.
_LIVE_BROWSER_RE = re.compile(
    r"\b(?:live|in-app)\s+browser\b|\bin\s+the\s+browser\b", re.IGNORECASE,
)

_TURN_END_FOLD_WAIT_S = 20.0

def _turn_end_settle(owner) -> None:
    """Fold-back of _turn_end_submit: wait until this kernel's last turn-end
    bookkeeping landed (the episode the planner may recall). Bounded: past
    the wait the turn proceeds on what has landed; the job is never cancelled."""
    done = getattr(owner, "_turn_end_pending", None)
    if done is None or done.is_set():
        return
    from backend.utils.durability_queue import lane

    if lane("memory_events").in_worker():
        return
    t0 = time.monotonic()
    landed = done.wait(_TURN_END_FOLD_WAIT_S)
    waited = time.monotonic() - t0
    if not landed:
        logger.warning("[DER] turn-end fold-back not landed after %.1fs - proceeding", waited)
    elif waited >= 0.5:
        logger.info("[DER] turn-end fold-back waited %.2fs", waited)

def _developer_mode(kernel) -> bool:
    """True when the app runs in developer mode. The card bound (artifact_policy)
    is a personal-mode rule: developer mode draws EVERY turn as the live matrix
    (execution audit Phase 4: rows appear / run / fold as nodes do). Live
    2026-10-06: the bound withheld every task/tool event of a 3-step developer
    turn, so it showed no rows at all. Module level: stand-in kernels in tests
    bind only some methods."""
    fn = getattr(kernel, "_effective_launcher_mode", None)
    try:
        return callable(fn) and fn() == "developer"
    except Exception:  # noqa: BLE001 - a mode read never blocks the gate
        logger.debug("[AgentKernel] launcher mode read failed", exc_info=True)
        return False


class TurnMixin:
    # â”€â”€ Trust-routing helpers (plan W2) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _pacman_zone_for_turn(self) -> Optional[str]:
        """Zone for fragments produced by the current turn.

        Returns 'reference' when the turn touched external/web sources
        (web_search / crawler_query), else None so EpisodicStore applies its
        trusted/tool default. See trust-routing plan W2.
        """
        return "reference" if getattr(self, "_turn_touched_external", False) else None

    def mark_external_tool(self, tool_name: str = "") -> None:
        """Flag the current turn as having touched external/web sources.

        Idempotent: once a turn is marked external it stays external for the
        whole turn (a later local tool must not clear it).
        """
        if is_external_tool(tool_name):
            self._turn_touched_external = True

    def clear_turn_trust_flag(self) -> None:
        """Reset the per-turn external flag. Call at the start of each turn."""
        self._turn_touched_external = False

    @staticmethod
    def _extract_chunk_text(chunk):
        """Delegate to streaming module."""
        return _streaming.extract_chunk_text(chunk)

    @staticmethod
    def _safe_stream(
        resp, silence_timeout=1.5, total_timeout=90.0, on_first_token=None
    ):
        """Delegate to streaming module."""
        yield from _streaming.safe_stream(
            resp,
            silence_timeout=silence_timeout,
            total_timeout=total_timeout,
            on_first_token=on_first_token,
        )

    @classmethod
    def _thinking_body(cls, use_thinking: bool, endpoint: str = "") -> dict:
        """Provider-agnostic body fields asking a model to skip chain-of-thought.

        WHY THIS IS SHARED (session 260). `_needs_thinking` and the user's
        `_thinking_style` setting already existed, and were wired to the LM
        Studio dispatcher ALONE. Every API-backed model -- which is what the
        product actually runs on -- had no thinking control at all. Measured
        consequence: command-a-plus-05-2026 streamed everything through
        `reasoning_content`, the dispatcher's reasoning fallback returned that
        raw thinking as the answer, and a "~300 word" request came back as
        13,562 characters opening "Thus we must produce a single paragraph...".

        WHY THE OLD FORM DID NOT WORK EITHER. The LM Studio path set
        `_body["extra_body"] = {"chat_template_kwargs": ...}` and then POSTed
        `_body` as raw JSON. `extra_body` is an OpenAI *SDK* concept -- the SDK
        merges its contents into the top level -- so as a literal JSON key it is
        not an API field and servers ignore it. Over raw HTTP the hint belongs
        at the TOP level, which is what this returns.

        Unknown fields make some strict endpoints 400. Callers pass the body
        through `_thinking_retry_body` on failure, which strips the hint and
        remembers the endpoint, so a provider that refuses it is asked once.
        """
        if use_thinking:
            return {}
        if endpoint and endpoint in cls._THINKING_HINT_REFUSED:
            return {}
        # vLLM / LM Studio / SGLang / most OSS OpenAI-compatible servers.
        return {"chat_template_kwargs": {"enable_thinking": False}}

    @classmethod
    def _thinking_retry_body(cls, body: dict, endpoint: str) -> Optional[dict]:
        """Strip the thinking hint after a rejection; None if none was set.

        Remembers the endpoint so the hint is not re-sent for the rest of the
        process -- one wasted request per provider, not one per call.
        """
        if "chat_template_kwargs" not in body:
            return None
        if endpoint:
            cls._THINKING_HINT_REFUSED.add(endpoint)
        _stripped = {k: v for k, v in body.items() if k != "chat_template_kwargs"}
        logger.info(
            "[thinking] endpoint rejected the no-thinking hint; retrying "
            "without it and not re-sending it this process: %s", endpoint,
        )
        return _stripped

    def _needs_thinking(self, text: str) -> bool:
        """
        Return True only for messages that genuinely benefit from chain-of-thought
        reasoning.  Simple conversational questions and greetings skip thinking mode,
        cutting latency from ~30s to ~5s on Qwen3-9B.

        Respects the user's _thinking_style setting:
          concise   â†’ never use thinking
          balanced  â†’ heuristic trigger-based (default)
          thorough  â†’ always use thinking
        """
        style = getattr(self, "_thinking_style", "balanced")
        if style == "concise":
            return False
        if style == "thorough":
            return True

        t = text.lower().strip()

        # Very short messages are almost always conversational
        if len(t.split()) < 7:
            return False

        # Common greetings and social "how are you" patterns
        GREETINGS = [
            "hello",
            "hi",
            "hey",
            "morning",
            "afternoon",
            "evening",
            "greetings",
        ]
        if any(t.startswith(g) for g in GREETINGS) and len(t.split()) < 10:
            return False

        SOCIAL = [
            "how are you",
            "how's it going",
            "how are things",
            "what's up",
            "how have you been",
        ]
        if any(s in t for s in SOCIAL) and len(t.split()) < 12:
            return False

        THINKING_TRIGGERS = [
            # Reasoning keywords
            "why ",
            "how does",
            "how do",
            "explain",
            "analyse",
            "analyze",
            "compare",
            "difference between",
            "pros and cons",
            "trade-off",
            "step by step",
            "walk me through",
            "break down",
            # Code / debugging
            "debug",
            "fix the",
            "what's wrong",
            "error in",
            "refactor",
            "write a function",
            "write code",
            "implement",
            "algorithm",
            # Planning / strategy
            "plan",
            "strategy",
            "best way to",
            "should i",
            "recommend",
            "what would you do",
            "help me design",
            "architect",
            # Math / logic
            "calculate",
            "compute",
            "solve",
            "equation",
            "proof",
            "if ",
            "given that",
            "assuming",
        ]
        return any(trigger in t for trigger in THINKING_TRIGGERS)

    @staticmethod
    def _parse_thinking(text: str) -> tuple:
        """Split model output into (thinking: str, response: str).

        Handles three forms of chain-of-thought output:
        1. <think>â€¦</think> XML tags  (Qwen3 thinking mode)
        2. <thinking>â€¦</thinking> XML tags  (DeepSeek-style)
        3. Untagged preamble paragraphs where the model narrates its reasoning
           ("Okay, the user is askingâ€¦", "Let me thinkâ€¦", etc.) before a blank
           line that separates it from the real answer.

        Returns:
            (thinking, clean_response) â€” thinking is an empty string when none found.
        """
        import re

        thinking_parts: list = []

        # Extract tagged blocks
        for m in re.finditer(r"<think>(.*?)</think>", text, flags=re.DOTALL):
            thinking_parts.append(m.group(1).strip())
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

        for m in re.finditer(r"<thinking>(.*?)</thinking>", text, flags=re.DOTALL):
            thinking_parts.append(m.group(1).strip())
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)

        text = text.strip()

        # Strip untagged reasoning preamble: leading paragraphs that open with
        # known self-narration phrases, separated from the answer by a blank line.
        _PREAMBLE_OPENERS = re.compile(
            r"^(okay[,.]?|alright[,.]?|let me|i need to|i should|i will|"
            r"the user (is|has|wants|asked)|looking at|wait[,.]?|"
            r"so[,.]?\s+(the|i|let)|hmm[,.]?)",
            re.IGNORECASE,
        )
        paragraphs = re.split(r"\n{2,}", text)
        while len(paragraphs) > 1 and _PREAMBLE_OPENERS.match(paragraphs[0].strip()):
            thinking_parts.append(paragraphs.pop(0).strip())
        clean = "\n\n".join(paragraphs).strip()

        return "\n\n".join(thinking_parts), clean

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Return the clean response with all thinking/reasoning removed.
        Convenience wrapper around _parse_thinking for callers that only need
        the response (planning, synthesis, spoken-version calls).
        """
        _, clean = AgentKernel._parse_thinking(text)
        return clean

    def _broadcast_inference_event(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        elapsed_s: float,
    ) -> None:
        """Fire-and-forget inference_event broadcast. Delegates to observability module."""
        broadcast_inference_event(
            session_id=self.session_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_s=elapsed_s,
            broadcast_loop=self._broadcast_loop,
        )

    @staticmethod
    def _chunk_batcher(
        callback: Optional[Callable[[str], None]],
        interval: float = 0.05,
    ) -> Callable[[str], None]:
        """Delegate to streaming module."""
        return _streaming.chunk_batcher(callback, interval)

    def _stream_and_collect(
        self,
        resp,
        chunk_callback: Optional[Callable[[str], None]],
        reasoning_callback: Optional[Callable[[str], None]] = None,
        on_first_token=None,
    ) -> str:
        """Delegate to streaming module."""
        return _streaming.stream_and_collect(
            resp,
            chunk_callback,
            reasoning_callback=reasoning_callback,
            on_first_token=on_first_token,
        )

    def _respond_direct(
        self,
        text: str,
        context: List[Dict],
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        tools: Optional[bool] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Respond directly to the user without planning or tool execution.
        Routes to the right backend provider based on IRISConfig routing mode
        or auto-detected provider type.

        Context uses all three memory layers (see CONTEXT_ENGINEERING.md):
          Layer 1: Mycelium coordinates â†’ system prompt
          Layer 2: Episodic store       â†’ memory block prefix
          Layer 3: Full history         â†’ token-aware (not a hard roll window)

        Returns: response text string.
        """
        # The previous turn's rows (chain + chunks) may still be queued on the
        # one writer; this assembly READS them to decide what the model sees, so
        # drain first (bounded). Measured 2026-10-31: without it the newest
        # taught fact was invisible to the next turn.
        try:
            from backend.memory.db import app_flush

            app_flush(2.0)
        except Exception:  # noqa: BLE001 - assembly still runs on settled rows
            pass
        _t_assemble = time.perf_counter()
        messages = self._assemble_direct_context(text, context, session_id=session_id)
        logger.info("[Timing] assemble_direct: %.0f ms",
                    (time.perf_counter() - _t_assemble) * 1000)
        # OBSERVABILITY (2026-10-29, T48): name the path that answered and how
        # much memory reached it. Without this line a pass/fail cannot be
        # attributed to a layer - the memory gate was read three times against
        # the wrong one.
        try:
            _tags = ("<memory>", "<context_memory>", "<mycelium_profile>",
                     "<cross_session_memory>", "<prior_memory>", "<file_memory>")
            _mem_blocks = sum(
                1 for m in messages
                if any(t in (m.get("content") or "") for t in _tags)
            )
            logger.info(
                "[TURN-PATH] session=%s path=direct mem_blocks=%d msgs=%d",
                session_id, _mem_blocks, len(messages),
            )
        except Exception:  # noqa: BLE001 - observability never blocks a reply
            pass
        messages = self._sanitize_messages(messages)

        # Resolve inference behaviour settings
        _max_tokens = {"short": 1024, "medium": 4096, "long": 8192}.get(
            getattr(self, "_response_length", "medium"), 4096
        )
        _temperature = {"fast": 0.9, "balanced": 0.6, "accurate": 0.3}.get(
            getattr(self, "_reasoning_effort", "balanced"), 0.6
        )
        _reasoning_effort_val = getattr(self, "_reasoning_effort", "balanced")

        # === Load IRISConfig for routing ===
        config_mode = getattr(self, "_config_mode", None)
        config = None
        if not config_mode:
            try:
                from backend.iris_config import load_config

                config = load_config()
                config_mode = config.routing.mode
            except Exception as _cfg_err:
                logger.warning(f"[RespondDirect] Config load failed: {_cfg_err}")
                config_mode = "auto"

        # === Tool definitions for function calling (gated by internet access) ===
        # When the web toggle is ON, get_available_tools() includes search /
        # crawler_query; when OFF, those are omitted. The agent decides when to
        # use them via the ReAct loop below. See plan Issue E.
        import json as _json
        # REQ-30 edge (2026-09-26): `tools=False` is the TEXT path. A caller
        # that wants a classification, not an action, must not ship a dozen
        # function definitions with its prompt: the model answers a pure
        # "sort this into topics" question with a tool call, Cohere rejects it
        # (422 HALLUCINATED_ALL_TOOL_CALLS / INVALID_TOOL_GENERATION) and the
        # caller pays a wasted request every time. Measured live in
        # SourceRegistry._extract_topics. None keeps the historical behaviour,
        # so no existing caller changes.
        _tools = self._get_openai_tools(text) if tools is not False else []

        # Local dispatch wrapper â€” routes to the correct backend provider and
        # returns (response_text, thinking_text, tool_calls).
        def _call(_msgs: List[Dict], _tools_arg: Optional[List[Dict]]) -> Tuple[str, str, List[Dict]]:
            _text, _thinking, _tool_calls = self._router.generate(
                "reasoning", _msgs, tools=_tools_arg,
                max_tokens=_max_tokens, temperature=_temperature,
                chunk_callback=chunk_callback, reasoning_callback=reasoning_callback,
            )
            self._accrue_tokens(
                _text, getattr(self._router, "last_usage", None),
                source="_respond_direct",
            )
            return _text, _thinking, _tool_calls

        # === Initial LLM call ===
        _response, _thinking, _tool_calls = _call(messages, _tools)
        self._pending_thinking = _thinking

        # === ReAct tool-call loop ===
        # If the model requested tool calls (e.g. web search / crawler_query),
        # execute them, feed results back, and let the model produce the final
        # answer. Bounded to avoid runaway loops.
        # Execution audit B14 (2026-09-29): 3 rounds cut real work short and the
        # calls requested in round 4 were dropped without a word. The bound is
        # larger, and hitting it ends with one tool-less call (below) so the
        # model says what it has and what is unfinished.
        _MAX_TOOL_ROUNDS = 8
        _round = 0
        # Tools run under the TURN's WebSocket session - the key the project
        # workdir, the session shell and permission routing are bound to (the
        # DER path already does this). The conversation id is not a session.
        _tool_session = (
            getattr(self, "_turn_session_id", None)
            or self.session_id or self.conversation_id or "voice"
        )
        while _tool_calls and _round < _MAX_TOOL_ROUNDS:
            _round += 1
            messages.append({
                "role": "assistant",
                "content": _response or None,
                "tool_calls": _tool_calls,
            })
            for _tc in _tool_calls:
                _tc_id = _tc.get("id")
                _fn = _tc.get("function", {})
                _name = _fn.get("name", "")
                _args_raw = _fn.get("arguments", "{}") or "{}"
                try:
                    _params = _json.loads(_args_raw) if _args_raw.strip() else {}
                except Exception:
                    _params = {"__raw_arguments__": _args_raw}
                # REQ-16 AC16.2 (T20): this ReAct loop picks tools with native
                # function calling, OUTSIDE ToolDecisionBox.resolve() â€” so the
                # engine never saw this traffic and the reliability curve was
                # built on a biased subset. Shadow-score the same choice here
                # (engine pick vs the tool the Brain actually called) and write
                # the row through the box's single ledger writer. `async_=True`
                # = a daemon thread, so the fast chat path pays ZERO added
                # latency; the whole block is best-effort and cannot break it.
                try:
                    # `last_result`: the most recent tool message in the ReAct
                    # conversation - the signal the Brain actually picks on.
                    _lr = ""
                    try:
                        for _m in reversed(messages):
                            if _m.get("role") == "tool":
                                _lr = str(_m.get("content") or "")[:600]
                                break
                    except Exception:  # noqa: BLE001
                        _lr = ""
                    # tc-frame-v5: this turn's calls BEFORE this one, in order
                    # (names + targets; the ReAct transcript holds no ok flag).
                    _hist = ""
                    try:
                        from backend.agent.node_executor import _target as _tgt

                        _prev = []
                        for _m in messages:
                            for _ptc in (_m.get("tool_calls") or []) if _m.get("role") == "assistant" else []:
                                if _ptc is _tc:
                                    raise StopIteration
                                _pf = _ptc.get("function") or {}
                                try:
                                    _pp = _json.loads(_pf.get("arguments") or "{}")
                                except Exception:  # noqa: BLE001
                                    _pp = {}
                                _prev.append(f"{_pf.get('name', '')} "
                                             f"{_tgt(_pp if isinstance(_pp, dict) else {})}".strip())
                    except StopIteration:
                        pass
                    except Exception:  # noqa: BLE001 - a shadow never needs context
                        _prev = []
                    _hist = "; ".join(_prev[-6:])[-400:]
                    # tc-frame-v10 (2026-11-04): the option text is the BARE
                    # tool name. MEASURED by replay on the active engine
                    # (1200 recorded tc-frame-v8 states, the same rows for
                    # both variants): the tools' decision lines measured
                    # oof AUROC 0.6569 and the bare names 0.6955, with
                    # monotonic confidence bands in both cases. The
                    # instruction carries the question; the option text must
                    # not argue for a tool (the same lesson as the
                    # review_verdict v9 criteria and the tool_choice control
                    # labels, oracle.md 7.6).
                    # the menu the Brain was OFFERED this turn. `_offered` was
                    # read here but only defined in the DER node path, so this
                    # row raised NameError and was lost on every direct-path
                    # tool call since tc-frame-v10 (found 2026-11-11).
                    _offered = [
                        (t.get("function") or {}).get("name")
                        for t in (_tools or [])
                    ]
                    _hints = {n: n for n in _offered if n}
                    _hints.update({n: n for n in ("DELEGATE", "NONE")})
                    self._get_tool_box().record_shadow_tool_choice(
                        goal=text,
                        observed_tool=_name,
                        observed_params=_params,
                        candidates=_offered or None,
                        last_result=_lr or None,
                        option_criteria=_hints or None,
                        calls_this_step=_hist or None,
                        session_id=self.conversation_id or "voice",
                        conversation_id=self.conversation_id or "",
                        async_=True,
                    )
                except Exception as _shadow_err:  # noqa: BLE001
                    logger.debug(
                        "[RespondDirect] shadow tool-choice row failed: %r",
                        _shadow_err,
                    )
                try:
                    _raw = asyncio.run(
                        self._tool_bridge.execute_tool(
                            tool_name=_name,
                            params=_params,
                            session_id=_tool_session,
                        )
                    )
                except RuntimeError:
                    # asyncio.run() fails if a loop is already running in this
                    # thread (shouldn't happen in the executor, but guard anyway).
                    import concurrent.futures as _cf
                    with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                        _raw = _pool.submit(
                            asyncio.run,
                            self._tool_bridge.execute_tool(
                                tool_name=_name,
                                params=_params,
                                session_id=_tool_session,
                            ),
                        ).result(timeout=60)
                _content = self._format_tool_result(_raw)
                messages.append({
                    "role": "tool",
                    "tool_call_id": _tc_id,
                    "name": _name,
                    "content": _content,
                })
            _response, _thinking, _tool_calls = _call(messages, _tools)
            self._pending_thinking = _thinking

        if _tool_calls:
            # Bound reached with calls still requested: never drop them in
            # silence. One final call WITHOUT tools makes the model answer from
            # what it has and name what is left undone.
            logger.info(
                "[RespondDirect] tool-round bound (%d) reached with %d call(s) "
                "pending conv=%s - asking for a final answer",
                _MAX_TOOL_ROUNDS, len(_tool_calls), self.conversation_id,
            )
            messages.append({
                "role": "user",
                "content": (
                    "Tool budget for this turn is used up. Answer now from the "
                    "results you have, and say plainly what is still unfinished."
                ),
            })
            _response, _thinking, _ = _call(messages, None)
            self._pending_thinking = _thinking

        return _response

    def _dispatch_api(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        reasoning_effort: str = "balanced",
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, str, List[Dict]]:
        """Remote API provider â€” direct httpx streaming (Chutes, OpenAI, etc.).

        Uses httpx directly instead of _llm.complete() to avoid thread-pool hangs.
        Returns (response_text, thinking_text).

        Raises RuntimeError on API errors â€” no silent error swallowing.
        """
        import json as _json
        import time as _perf_t
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        _api_base = self._api_base_url or "https://api.openai.com/v1"
        _api_key = self._api_key or ""
        sel = self._selected_reasoning_model or "local-model"
        if sel in ("local-model", "Currently Loaded Model", "currently-loaded-model"):
            raise RuntimeError(
                "No reasoning model configured. Set a model in Settings â†’ "
                "Model Selection (e.g. Cerebras gemma-4-31b) before sending messages."
            )

        _url = f"{_api_base.rstrip('/')}/chat/completions"
        _headers = {
            "Content-Type": "application/json",
        }
        # REQ-1 (specs/local-model-lifecycle-sync): never emit `Authorization:
        # Bearer ` with an empty value â€” httpx rejects it as an illegal header
        # and the kernel crashes with `Illegal header value b'Bearer '`. The
        # router raises ProviderNotReadyError(missing_api_key) before this
        # path, but guard here too so a direct call fails closed.
        if _api_key and _api_key.strip():
            _headers["Authorization"] = f"Bearer {_api_key.strip()}"
        _body = {
            "model": sel,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            _body["tools"] = tools
            _body["tool_choice"] = "auto"

        # Session 260: EVERY model that can be told to skip chain-of-thought
        # is now told, not just the LM Studio one. This path had NO thinking
        # control at all, which is why an API-backed reasoning model returned
        # its deliberation as the answer.
        try:
            _body.update(
                self._thinking_body(
                    self._needs_thinking(
                        messages[-1].get("content", "") if messages else ""
                    ),
                    endpoint=str(sel or ""),
                )
            )
        except Exception as _think_exc:  # noqa: BLE001 -- never fail on a hint
            logger.debug("[thinking] hint not applied: %s", _think_exc)
        # â”€â”€ Telemetry: log API request shape (not content) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            _msg_count = len(messages)
            _total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            from backend.core.logging_config import get_agent_logger

            get_agent_logger().info(
                "API request",
                provider=self._model_provider,
                model=sel,
                messages=_msg_count,
                chars=_total_chars,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception:
            pass

        if chunk_callback:
            # Streaming path
            _t0 = _perf_t.perf_counter()
            full_reply = ""
            _reasoning_buf: List[str] = []
            _tool_calls_acc: Dict[int, Dict] = {}
            _tool_calls: List[Dict] = []

            for _attempt in range(3):
                _stream_ok = False
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                        with _client.stream(
                            "POST", _url, headers=_headers, json={**_body, "stream": True}
                        ) as _resp:
                            if _resp.status_code == 429:
                                # Rate-limited (LM Studio "queue_exceeded" / high
                                # traffic). Discard body and retry with backoff.
                                try:
                                    _resp.read()
                                except Exception:
                                    pass
                                logger.warning(
                                    "[DispatchAPI] 429 rate-limit (attempt %d/3) â€” retrying",
                                    _attempt + 1,
                                )
                                continue
                            if _resp.status_code != 200:
                                # Streaming response: reading .text raises ResponseNotRead
                                # because httpx hasn't consumed the body yet. Read the first
                                # chunk manually for the error detail.
                                try:
                                    _first = next(_resp.iter_bytes(), b"")
                                    _err_detail = _first[:200].decode("utf-8", errors="replace")
                                except Exception:
                                    _err_detail = "(could not read error body)"
                                # Session 260: a provider that refuses the
                                # no-thinking hint must degrade, not fail. The
                                # hint is an optimisation; the turn is not.
                                # Strip it, remember the endpoint so it is
                                # asked exactly once this process, and retry.
                                if _resp.status_code in (400, 422):
                                    _retry_body = self._thinking_retry_body(
                                        _body, str(sel or "")
                                    )
                                    if _retry_body is not None:
                                        _body = _retry_body
                                        continue
                                raise RuntimeError(
                                    f"API returned {_resp.status_code}: {_err_detail}"
                                )
                            for _line in _resp.iter_lines():
                                if not _line or not _line.startswith("data:"):
                                    continue
                                _data = _line[5:].strip()
                                if _data == "[DONE]":
                                    break
                                # Let JSONDecodeError propagate on malformed data
                                _chunk = _json.loads(_data)
                                _choices = _chunk.get("choices", [])
                                if not _choices:
                                    continue
                                _delta = _choices[0].get("delta", {})

                                # Reasoning content â€” field name varies by provider
                                _r = _delta.get("reasoning_content") or _delta.get("reasoning")
                                if _r:
                                    _reasoning_buf.append(_r)
                                    if reasoning_callback:
                                        reasoning_callback(_r)

                                # Text content
                                _c = _delta.get("content")
                                if _c:
                                    full_reply += _c
                                    if chunk_callback:
                                        chunk_callback(_c)

                                # Tool calls (function calling) â€” accumulate across
                                # streaming deltas by index.
                                for _tc_item in (_delta.get("tool_calls") or []):
                                    _idx = _tc_item.get("index", 0)
                                    _acc = _tool_calls_acc.setdefault(
                                        _idx,
                                        {
                                            "id": "",
                                            "type": "function",
                                            "function": {"name": "", "arguments": ""},
                                        },
                                    )
                                    if _tc_item.get("id"):
                                        _acc["id"] = _tc_item["id"]
                                    _fn = _tc_item.get("function") or {}
                                    if _fn.get("name"):
                                        _acc["function"]["name"] = _fn["name"]
                                    if _fn.get("arguments"):
                                        _acc["function"]["arguments"] += _fn["arguments"]
                            _stream_ok = True
                except RuntimeError:
                    raise
                except Exception as _e:
                    logger.warning(
                        "[DispatchAPI] stream error (attempt %d/3): %s",
                        _attempt + 1,
                        _e,
                    )
                    if _attempt == 2:
                        raise
                if _stream_ok:
                    break
                if _attempt < 2:
                    _perf_t.sleep(1.0 * (2 ** _attempt))

            _tool_calls = [v for v in _tool_calls_acc.values()]

            reasoning_text = "".join(_reasoning_buf)
            if reasoning_callback:
                reasoning_callback("")  # end marker
            if chunk_callback:
                chunk_callback("")  # force-flush

            # Reasoning fallback: some models return answer in reasoning_content
            # with empty content. When using reasoning fallback, skip _parse_thinking
            # since the reasoning IS the answer (preamble stripping would kill it).
            if not full_reply.strip() and reasoning_text.strip() and not _tool_calls:
                _elapsed = _perf_t.perf_counter() - _t0
                _ctok = max(1, len(reasoning_text) // 4)
                _ptok = sum(len(m.get("content", "")) for m in messages) // 4
                self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)
                return reasoning_text, reasoning_text, []

            thinking, clean = self._parse_thinking(full_reply)
            _elapsed = _perf_t.perf_counter() - _t0
            _ctok = max(1, len(full_reply) // 4)
            _ptok = sum(len(m.get("content", "")) for m in messages) // 4
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)
            return clean or "(I see.)", thinking, _tool_calls

        else:
            # Non-streaming path
            _t0 = _perf_t.perf_counter()
            _result = None
            for _attempt in range(3):
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                        _resp = _client.post(_url, headers=_headers, json=_body)
                        if _resp.status_code == 429:
                            # Rate-limit-aware backoff (REQ-5): wait for the
                            # provider's reset window instead of a fixed 1-2s sleep
                            # that burns attempts without relief. Prefer
                            # x-ratelimit-reset (epoch seconds) or Retry-After
                            # (seconds); fall back to bounded exponential backoff.
                            _reset = _resp.headers.get("x-ratelimit-reset")
                            _retry_after = _resp.headers.get("Retry-After")
                            _wait = None
                            if _retry_after and str(_retry_after).isdigit():
                                _wait = float(_retry_after)
                            elif _reset:
                                try:
                                    _reset_ts = float(_reset)
                                    # x-ratelimit-reset may be epoch seconds or
                                    # seconds-remaining depending on provider.
                                    _now = time.time()
                                    if _reset_ts > _now:  # epoch seconds
                                        _wait = _reset_ts - _now
                                    else:  # seconds remaining
                                        _wait = _reset_ts
                                except (ValueError, TypeError):
                                    _wait = None
                            if _wait is None:
                                _wait = min(1.0 * (2 ** _attempt), 30.0)
                            _wait = max(0.0, min(_wait, 60.0))  # hard cap 60s
                            logger.warning(
                                "[DispatchAPI] 429 rate-limit (attempt %d/3) â€” "
                                "waiting %.1fs for reset window",
                                _attempt + 1,
                                _wait,
                            )
                            if _attempt < 2:
                                _perf_t.sleep(_wait)
                            continue
                        if _resp.status_code != 200:
                            raise RuntimeError(
                                f"API returned {_resp.status_code}: {_resp.text[:200]}"
                            )
                        _result = _resp.json()
                        break
                except RuntimeError:
                    raise
                except Exception as _e:
                    logger.warning(
                        "[DispatchAPI] request error (attempt %d/3): %s",
                        _attempt + 1,
                        _e,
                    )
                    if _attempt == 2:
                        raise
            if _result is None:
                raise RuntimeError("API request failed after retries")

            _msg = _result.get("choices", [{}])[0].get("message", {})
            _reply = _msg.get("content", "")
            _tool_calls = _msg.get("tool_calls") or []

            if not _reply and not _tool_calls:
                raise RuntimeError("Empty response from API")

            # Record usage with real API tokens if available
            _elapsed = _perf_t.perf_counter() - _t0
            _usage = _result.get("usage", {})
            _ptok = _usage.get("prompt_tokens", max(1, sum(len(m.get("content", "")) for m in messages) // 4))
            _ctok = _usage.get("completion_tokens", max(1, len(_reply) // 4))
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)

            # â”€â”€ FIX (session 154): Invoke chunk_callback on non-streaming path â”€â”€
            # When the LLM provider returns the full reply in one shot (Cerebras,
            # Cohere batch mode, etc.), chunk_callback is never called, so the
            # TTS sentence_queue only receives the None sentinel and the
            # producer breaks immediately without synthesizing any audio.
            # Send the full reply as a single chunk, then a force-flush (""),
            # matching the streaming path's end-of-stream semantics.
            if chunk_callback and _reply:
                chunk_callback(_reply)
                chunk_callback("")  # force-flush end-of-stream

            thinking, clean = self._parse_thinking(_reply)
            return clean or "(I see.)", thinking, _tool_calls

    def _dispatch_openai_compat(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        reasoning_effort: str = "balanced",
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, str, List[Dict]]:
        """LM Studio / local OpenAI-compatible endpoint â€” direct httpx streaming.

        Similar to _dispatch_api but uses _lmstudio_endpoint and LM Studio's
        Extra-body template hints. Returns (response_text, thinking_text).

        Raises RuntimeError on API errors â€” no silent error swallowing.
        """
        import json as _json
        import time as _perf_t
        import httpx as _httpx
        from backend.utils.ssl_context import get_ssl_context

        _api_base = self._lmstudio_endpoint or "http://localhost:1234"
        sel = self._selected_reasoning_model or "local-model"
        use_thinking = self._needs_thinking(
            messages[-1].get("content", "") if messages else ""
        )

        _url = f"{_api_base.rstrip('/')}/v1/chat/completions"

        # LM Studio may serve an older API path
        _url_v1 = f"{_api_base.rstrip('/')}/chat/completions"

        _body = {
            "model": sel,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            _body["tools"] = tools
            _body["tool_choice"] = "auto"

        # Session 260: was `_body["extra_body"] = {...}` -- an OpenAI SDK
        # concept, not an API field. Posted as raw JSON it was ignored, so this
        # path's thinking control never actually did anything. Over raw HTTP the
        # hint belongs at the TOP level. Same helper as the API dispatcher, so
        # both obey `_thinking_style` identically.
        _body.update(self._thinking_body(use_thinking, endpoint=_api_base))

        if chunk_callback:
            # Streaming path
            _t0 = _perf_t.perf_counter()
            full_reply = ""
            _reasoning_buf: List[str] = []
            _tool_calls_acc: Dict[int, Dict] = {}
            _tool_calls: List[Dict] = []

            for _attempt in range(3):
                _stream_ok = False
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                        # Try the standard v1 path, fall back to v1-less path for older LM Studio
                        for _try_url in [_url, _url_v1]:
                            try:
                                _resp = _client.stream(
                                    "POST",
                                    _try_url,
                                    headers={"Content-Type": "application/json"},
                                    json={**_body, "stream": True},
                                )
                                break
                            except Exception:
                                continue
                        else:
                            raise RuntimeError(f"Could not connect to {_api_base}")

                        with _resp as _stream:
                            if _stream.status_code == 429:
                                try:
                                    _stream.read()
                                except Exception:
                                    pass
                                logger.warning(
                                    "[DispatchLMStudio] 429 rate-limit (attempt %d/3) â€” retrying",
                                    _attempt + 1,
                                )
                                continue
                            if _stream.status_code != 200:
                                # Streaming response: `.text` raises ResponseNotRead
                                # ("Attempted to access streaming response content,
                                # without having called read()"). Read the first
                                # chunk manually for the error detail.
                                try:
                                    _first = next(_stream.iter_bytes(), b"")
                                    _err_detail = _first[:200].decode(
                                        "utf-8", errors="replace"
                                    )
                                except Exception:
                                    _err_detail = "(could not read error body)"
                                raise RuntimeError(
                                    f"{_api_base} returned {_stream.status_code}: {_err_detail}"
                                )
                            for _line in _stream.iter_lines():
                                if not _line or not _line.startswith("data:"):
                                    continue
                                _data = _line[5:].strip()
                                if _data == "[DONE]":
                                    break
                                _chunk = _json.loads(_data)
                                _choices = _chunk.get("choices", [])
                                if not _choices:
                                    continue
                                _delta = _choices[0].get("delta", {})

                                _r = _delta.get("reasoning_content") or _delta.get("reasoning")
                                if _r:
                                    _reasoning_buf.append(_r)
                                    if reasoning_callback:
                                        reasoning_callback(_r)

                                _c = _delta.get("content")
                                if _c:
                                    full_reply += _c
                                    if chunk_callback:
                                        chunk_callback(_c)

                                for _tc_item in (_delta.get("tool_calls") or []):
                                    _idx = _tc_item.get("index", 0)
                                    _acc = _tool_calls_acc.setdefault(
                                        _idx,
                                        {
                                            "id": "",
                                            "type": "function",
                                            "function": {"name": "", "arguments": ""},
                                        },
                                    )
                                    if _tc_item.get("id"):
                                        _acc["id"] = _tc_item["id"]
                                    _fn = _tc_item.get("function") or {}
                                    if _fn.get("name"):
                                        _acc["function"]["name"] = _fn["name"]
                                    if _fn.get("arguments"):
                                        _acc["function"]["arguments"] += _fn["arguments"]
                            _stream_ok = True
                except RuntimeError:
                    raise
                except Exception as _e:
                    logger.warning(
                        "[DispatchLMStudio] stream error (attempt %d/3): %s",
                        _attempt + 1,
                        _e,
                    )
                    if _attempt == 2:
                        raise
                if _stream_ok:
                    break
                if _attempt < 2:
                    _perf_t.sleep(1.0 * (2 ** _attempt))

            _tool_calls = [v for v in _tool_calls_acc.values()]

            reasoning_text = "".join(_reasoning_buf)
            if reasoning_callback:
                reasoning_callback("")
            if chunk_callback:
                chunk_callback("")

            if not full_reply.strip() and reasoning_text.strip() and not _tool_calls:
                return reasoning_text, reasoning_text, []

            thinking, clean = self._parse_thinking(full_reply)
            return clean or "(I see.)", thinking, _tool_calls

        else:
            # Non-streaming path
            _t0 = _perf_t.perf_counter()
            _result = None
            for _attempt in range(3):
                try:
                    with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                        for _try_url in [_url, _url_v1]:
                            try:
                                _resp = _client.post(
                                    _try_url,
                                    headers={"Content-Type": "application/json"},
                                    json=_body,
                                )
                                if _resp.status_code == 429:
                                    logger.warning(
                                        "[DispatchLMStudio] 429 rate-limit (attempt %d/3) â€” retrying",
                                        _attempt + 1,
                                    )
                                    if _attempt < 2:
                                        _perf_t.sleep(1.0 * (2 ** _attempt))
                                    break  # retry outer loop
                                if _resp.status_code < 500:
                                    break
                            except Exception:
                                continue
                        else:
                            raise RuntimeError(f"Could not connect to {_api_base}")

                        if _resp.status_code == 429:
                            continue
                        if _resp.status_code != 200:
                            raise RuntimeError(
                                f"{_api_base} returned {_resp.status_code}: {_resp.text[:200]}"
                            )
                        _result = _resp.json()
                        break
                except RuntimeError:
                    raise
                except Exception as _e:
                    logger.warning(
                        "[DispatchLMStudio] request error (attempt %d/3): %s",
                        _attempt + 1,
                        _e,
                    )
                    if _attempt == 2:
                        raise
            if _result is None:
                raise RuntimeError(f"Request to {_api_base} failed after retries")

            _msg = _result.get("choices", [{}])[0].get("message", {})
            _reply = _msg.get("content", "")
            _tool_calls = _msg.get("tool_calls") or []

            if not _reply and not _tool_calls:
                # SELF-DIAGNOSING (2026-09-28). This raised a bare "Empty
                # response from LM Studio" SIXTEEN times in one session and
                # recorded nothing about the REQUEST, so the cause could not be
                # established afterwards - the label even pointed at another
                # product's port. The three fields below are the whole
                # diagnosis, so the next occurrence carries its own evidence:
                #   finish_reason  'length' -> the reply was cut off by
                #                  max_tokens; 'stop' with empty content -> the
                #                  model emitted EOS immediately, which is what a
                #                  truncated/over-long prompt produces;
                #   usage.prompt_tokens -> compare against the model's n_ctx to
                #                  see whether llama-server truncated the prompt
                #                  (prompt + tool schemas can exceed 16384);
                #   the raw body -> what the server actually said.
                _choice0 = (_result.get("choices") or [{}])[0] or {}
                logger.warning(
                    "[Dispatch] EMPTY completion from %s: messages=%d "
                    "finish_reason=%r usage=%s raw=%r",
                    _api_base, len(messages),
                    _choice0.get("finish_reason"),
                    _result.get("usage"),
                    str(_result)[:300],
                )
                raise RuntimeError(f"Empty response from {_api_base}")

            # Record usage with real API tokens if available
            _usage = _result.get("usage", {})
            _ptok = _usage.get("prompt_tokens", max(1, sum(len(m.get("content", "")) for m in messages) // 4))
            _ctok = _usage.get("completion_tokens", max(1, len(_reply) // 4))
            _elapsed_ns = _perf_t.perf_counter() - _t0
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed_ns)

            # â”€â”€ FIX (session 154): Invoke chunk_callback on non-streaming path â”€â”€
            # Same fix as _dispatch_api: when LM Studio returns the full reply
            # in one shot, chunk_callback is never called, so the TTS
            # sentence_queue only receives the None sentinel. Send the full
            # reply as a single chunk, then a force-flush ("").
            if chunk_callback and _reply:
                chunk_callback(_reply)
                chunk_callback("")  # force-flush end-of-stream

            thinking, clean = self._parse_thinking(_reply)
            return clean or "(I see.)", thinking, _tool_calls

    def _dispatch_inprocess(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, str]:
        """Local in-process model inference.

        Uses the locally loaded model (via _model_router / get_reasoning_model()).
        Falls back to the old `reasoning_model.generate()` if chunk_callback is None.
        Returns (response_text, thinking_text).
        """
        reasoning_model = None
        if self._model_router and self._selected_reasoning_model:
            reasoning_model = self._model_router.models.get(
                self._selected_reasoning_model
            )
        if not reasoning_model and self._model_router:
            reasoning_model = self._model_router.get_reasoning_model()

        if not reasoning_model:
            raise RuntimeError("No local model loaded")

        reply = reasoning_model.generate(
            messages[-1].get("content", "") if messages else ""
        )

        # â”€â”€ FIX (session 154): Invoke chunk_callback on non-streaming path â”€â”€
        # Local in-process models generate the full reply at once. Without
        # this call, the TTS pipeline never sees the response text.
        if chunk_callback and reply:
            chunk_callback(reply)
            chunk_callback("")  # force-flush end-of-stream

        thinking, clean = self._parse_thinking(reply)
        return clean or "(I see.)", thinking, []

    def _ensure_tool_bridge(self) -> None:
        """Lazy-initialize the tool bridge on first access.

        The bridge is created as a background task (its initialize() is async
        and wires MCP/server connections); tools from its in-process dict are
        available immediately.  This MUST run before ANY code reads
        ``self._tool_bridge.get_available_tools()`` â€” ``_plan_task`` builds the
        planner's AVAILABLE TOOLS block from it, and a None bridge silently
        produces an empty tool list (planner then emits tool-less speak steps).
        """
        if not self._tool_bridge:
            try:
                from backend.agent.tool_bridge import get_agent_tool_bridge

                self._tool_bridge = get_agent_tool_bridge()
                if not self._tool_bridge._initialized:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._tool_bridge.initialize())
                    except RuntimeError:
                        # No running event loop â€” run synchronously
                        asyncio.run(self._tool_bridge.initialize())
                logger.info("[AgentKernel] Tool bridge lazy-initialized")
            except Exception as e:
                logger.warning(f"[AgentKernel] Tool bridge init failed: {e}")

    def _get_openai_tools(self, text: str = "") -> List[Dict]:
        """Convert tool_bridge tool list to OpenAI-compatible function-calling format.

        When `text` is provided, web search / crawler tools are included only
        if the text explicitly asks for a web search. This prevents the model
        from calling web tools unnecessarily for simple conversational prompts
        even when the web toggle is ON.

        Each entry becomes:
          {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
        """
        self._ensure_tool_bridge()
        if not self._tool_bridge:
            return []
        # Single shared converter (tool_registry.to_function_schema). This used
        # to be an inline copy, and ToolDecisionBox had no conversion at all â€”
        # so the same tools were valid on one code path and a 422 on the other.
        from backend.agent.tool_registry import to_function_schema

        openai_tools: List[Dict] = to_function_schema(
            self._tool_bridge.get_available_tools()
        )
        # â”€â”€ Web tools are NOT filtered out of the model's tool list â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # REMOVED 2026-10-07. This used to strip `search` and `crawler_query`
        # unless `_is_web_search_request(text)` was true, and that predicate
        # reduced to a 16-phrase substring list, because the Oracle can never
        # decide it:
        #     threshold_for("web_intent") -> None   (cfg.thresholds is empty)
        #     oracle_acts("web_intent", conf) -> False at 0.50 .. 0.95
        # The web_intent consumer was denied enforcement after precision 0.41
        # (Stage B, 2026-10-05), and an uncalibrated consumer fails closed, so
        # the KEYWORDS were the sole decider for a capability.
        #
        # MEASURED on the owner's real sentences - all evaluated False, so the
        # web tools were withheld from the model:
        #   "Could you search up the recent repo of the math?"       -> stripped
        #   "Could you look into the one by OpenAI and let me know..." -> stripped
        #   "check the openai/math repository on github"              -> stripped
        # "look into" is not in the trigger list at all.
        #
        # Consequences that made this a defect and not a tuning knob:
        #   - It is not web-specific in spirit but is web-specific in code:
        #     exactly two hard-coded names, while open_url / fetch_url /
        #     browser_explore were never filtered. The model therefore had the
        #     BROWSER tools and not the SEARCH tools, which is the opposite of
        #     what a "search the web" phrasing needs.
        #   - It removed capability rather than adding guidance, so it could
        #     only ever fail in the direction that broke the turn.
        #   - Any new phrasing, tool or vocabulary needed a code edit.
        #
        # The model is already good at not searching when it is not needed - it
        # answered from memory in this same session without reaching for a
        # search tool. The web toggle remains the user's control.
        return openai_tools

    def _sanitize_task(self, task: str) -> str:
        """
        Filter prompt-injection attempts before the task reaches the DER Director.
        Replaces coordinate-layer protocol markers with [filtered].
        Applied ONLY here â€” not in WebSocket validators.
        """
        import re as _re

        _PACMAN_PATTERNS = (
            r"system://",
            r"trusted://",
            r"tool://",
            r"reference://",
            r"MYCELIUM:",
            r"TOPOLOGY:",
            r"CONTRACT:",
            r"GRADIENT WARNING",
            r"AMBIENT:",
            r"CAUSAL:",
        )
        result = task
        for pattern in _PACMAN_PATTERNS:
            result = _re.sub(pattern, "[filtered]", result)
        return result

    @_turn_in_flight
    @restores_call_class
    def process_text_message(
        self,
        text: str,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        from_voice: bool = False,
        turn_id: Optional[str] = None,
        card_context: Optional[str] = None,
    ) -> str:
        """
        Main entry point for text messages.
        Decides between direct response and agentic (tool-calling) loop.

        conversation_id: Key for per-thread context persistence. If None,
                         falls back to self.conversation_id (or session_id).
        from_voice: when True the request came from the voice pipeline.
          - Overrides mode detection â†’ "voice_first"
          - Uses DER_TOKEN_BUDGETS["voice_first"] (15k tokens, under 20k)
          - Planning caps at 1 step for fast first-token response
        """
        _t_start = time.perf_counter()
        self._turn_from_voice = bool(from_voice)

        # T6.4: mark the call class as USER_TURN at the real turn entry so the
        # phase gate admits it immediately (high-priority lane).
        set_call_class(CallClass.USER_TURN)

        # Trust-routing W2: each new turn starts unmarked; the external flag is
        # set if a web/crawler tool runs during this turn.
        self.clear_turn_trust_flag()
        # pin_517dfcbda150: the web-gather budget is per-task â€” it resets at the
        # turn boundary so a new task may gather up to _MAX_CRAWLS_PER_TASK
        # distinct (refined) queries again.
        self._der_crawl_attempts = {}
        # Spec A4: the quick-tier escalation flag is per-task like the budget.
        self._der_quick_insufficient = set()

        # Use provided session_id or fall back to instance session_id
        if session_id is None:
            session_id = self.session_id
        # The kernel's own session_id is fixed at creation; the TURN's session
        # (this WebSocket) is what tool calls must run under - see
        # _respond_direct. The DER path already receives it as a parameter.
        self._turn_session_id = session_id
        # tool_approval (safety, 2026-11-10): the permission site knows only the
        # session, so the request rides here for the safety frame.
        try:
            from backend.agent.tool_approval_shadow import note_request

            note_request(session_id, text)
        except Exception:  # noqa: BLE001 - bookkeeping never blocks a turn
            logger.debug("[AgentKernel] tool_approval request note skipped")
        # D3 (2026-10-31): the turn's monotonic start. The reply exit accepts a
        # memory-deletion claim only against a `forget` tool event after this
        # stamp, so a previous turn's delete can never justify this turn's claim.
        self._turn_started_monotonic = time.monotonic()

        # Resolve conversation_id â€” primary key for per-thread context.
        # getattr guard: a kernel may be constructed without __init__ (test
        # stubs, partial init) â€” never raise on a missing attribute. The
        # session_id fallback is the documented behavior (docstring above).
        _conv_id = conversation_id or getattr(self, "conversation_id", None) or session_id
        self.conversation_id = _conv_id

        # Event taxonomy step 3: EVERY user message (text and voice enter here) gets
        # an Oracle `user_feedback` shadow decision. Queues one lane job and returns;
        # never on the answer path, never changes the turn.
        try:
            from backend.agent.event_oracle import observe_user_message

            observe_user_message(
                self, text, thread_id=_conv_id, turn_id=turn_id, from_voice=from_voice,
                episode_id=f"{_conv_id}:{turn_id}" if turn_id else None,
            )
        except Exception as _eo_err:  # noqa: BLE001 - an observer never blocks a turn
            logger.debug("[AgentKernel] event oracle observe skipped: %r", _eo_err)

        # REQ-12 AC1 (T42): the user's own words enter the Immortus chain as a
        # role='user' row, on the fragment lane. Turn entry is the one place both
        # the direct and the DER path pass through.
        self._turn_mem_prompts = 0   # OBSERVABILITY (T48): per-turn path line
        try:
            from backend.agent.mcm_protocol.actions.pacman_fragment import (
                submit_user_turn_entry as _submit_user_turn_entry,
            )

            _submit_user_turn_entry(
                getattr(self, "_memory_interface", None), _conv_id, text,
            )
        except Exception as _ut_err:  # noqa: BLE001 - memory bookkeeping never blocks
            logger.debug("[AgentKernel] user turn chain append skipped: %r", _ut_err)

        # Reset thinking from any previous call so stale data never leaks
        self._pending_thinking = ""

        # Stage 1 observability: per-turn metrics (created early so error paths can log)
        import uuid

        task_id = turn_id or str(uuid.uuid4())
        # The frontend's turn id for everything this turn emits outside the DER
        # parameters (create_artifact cards, tool-bridge rows, card snapshots).
        # 13 sites read it; nothing assigned it, so all of them got None and a
        # rendered card never joined its live turn (HANDOFF 6 finding).
        self._current_turn_id = turn_id
        # REQ-6 AC6.3a (T5.0): the Oracle row scope. Consult sites read it as
        # values at submit time; rows of this turn join on the turn id.
        try:
            from backend.agent.decision_engine import set_scope as _de_set_scope

            _de_set_scope(turn_id=turn_id, step_id=None, node_exec_id=None)
        except Exception:  # noqa: BLE001 - scope is best-effort
            pass
        # Taxonomy events of this turn share one episode id (same as Wave E's task id).
        self._event_episode_id = f"{session_id}:{task_id}"
        metrics = TurnMetrics(turn_id=task_id)
        # REQ-13 AC4 (reply-surface-contract T18): give the reply seam a cheap,
        # fire-and-forget handle on this turn's metrics so the first
        # DOCUMENT_RENDER emit can stamp `card_ms` (time-to-card). Attribute
        # copy only; the seam getattr-guards it, so a missing handle is safe.
        self._active_turn_metrics = metrics
        # REQ-5 AC1 (T8): stamp the semantic-gate compilation onto this turn's
        # [LAYERS] emit (off the hot path â€” attribute copies only).
        self._stamp_gate_telemetry(metrics)
        # REQ-3 T8b AC5: per-turn prompt-token counter accumulated at each DER
        # step's context assembly (forgetting bound), recorded into TurnMetrics.
        self._der_step_prompt_tokens = 0
        # REQ-7 AC3 (T25): per-turn DER call counter (batched groups count once).
        self._der_turn_calls = 0
        # T11 (REQ-12): per-turn DER step count, wired from the DER loop's
        # completed_items at finalize so [LAYERS] der_steps is an observation,
        # not the declared-never-assigned 0 it was until 2026-08-06.
        self._der_step_count = 0
        try:
            from backend.gateway.iris_ffi import _engine

            metrics.engine = (
                "native" if (_engine and getattr(_engine, "_ffi", None)) else "fallback"
            )
        except Exception:
            metrics.engine = "fallback"

        # Wrap chunk_callback to mark TTFT on first contentful chunk
        _original_chunk_cb = chunk_callback

        def _wrapped_chunk_cb(chunk: str):
            metrics.mark_first_token()
            if _original_chunk_cb:
                _original_chunk_cb(chunk)

        # Check if agent is available
        if self._initialization_error:
            error_msg = f"Agent kernel is not available: {self._initialization_error}"
            logger.error(f"[AgentKernel] {error_msg}")
            logger.info(metrics.to_log_line())
            return error_msg

        if not self._model_router or not self._conversation_memory:
            error_msg = "Agent kernel is not available"
            logger.error(f"[AgentKernel] {error_msg}")
            logger.info(metrics.to_log_line())
            return error_msg

        # Create TaskContext to carry full context through pipeline (fixes Bug 3, 4, 5, 6)
        _t_start = time.perf_counter()

        # Gate 3 T4 (REQ-2/D1): shell context is EPHEMERAL â€” it is assembled
        # into THIS turn's outgoing context list below and never persisted to
        # conversation memory. Volatile environmental telemetry does not belong
        # in durable dialogue history: add_message() would re-send the block on
        # every LLM call of every later turn until FIFO eviction dropped it,
        # occupy one of ten window slots, and write raw-ish shell bytes into
        # conversation.json. The drained records stay readable by ref instead
        # (ShellRecordQueue retention + read_shell_output), so nothing is lost.
        _shell_block = ""
        try:
            # Add user message to conversation memory
            self._conversation_memory.add_message("user", text)
            logger.info(f"[AgentKernel] Processing text message: {text[:50]}...")

            # Drain queued shell records at turn assembly â€” the next turn
            # builds on real shell state, never a guess. Redaction/truncation
            # happened at record time; the aggregate budget was enforced in
            # drain(). A failed drain is degraded-but-working (design Error
            # Handling), never fatal.
            try:
                from backend.dev.shell_records import get_shell_record_queue

                _q = get_shell_record_queue()
                _shell_block, _suppressed = _q.drain(session_id)
                # Keyed by session_id on BOTH sides -- the terminal handler
                # records under it and this drains under it. A mismatch is
                # silent (empty block, no error), so name both sides here.
                logger.debug(
                    "[AgentKernel][%s] shell drain -> %d chars (queued sessions: %s)",
                    session_id, len(_shell_block), list(_q.known_sessions()),
                )
            except Exception as _exc:
                logger.debug("[AgentKernel] shell-context drain skipped: %s", _exc)

            # A fresh user turn supersedes any prior soft-cancel (REQ-6
            # client_replace). If the user navigated away mid-task and then
            # returns to send a new message in the SAME conversation, the
            # stale _cancel_requested flag would otherwise halt the DER loop
            # before executing any step â†’ "no usable sources found" with zero
            # steps run.
            try:
                _cancel = getattr(self, "_cancel_requested", None)
                if _cancel is not None and _cancel.is_set():
                    _cancel.clear()
                    logger.info(
                        f"[AgentKernel] Cleared stale _cancel_requested for "
                        f"conv={conversation_id} â€” new user turn supersedes prior soft-cancel"
                    )
            except Exception:
                pass

            # Get conversation context
            context = self._conversation_memory.get_context()
            # Session 246 (@-card-mentions): referenced task-card snapshots
            # arrive as a per-turn system block â€” visible to planning and
            # synthesis for THIS turn only. Appended to the LOCAL context list,
            # never add_message()'d, so conversation memory stays clean.
            if card_context:
                context = list(context) + [
                    {"role": "system", "content": card_context}
                ]
                logger.info(
                    f"[AgentKernel] @-card context injected "
                    f"({len(card_context)} chars) conv={conversation_id}"
                )
            # Gate 3 T4 (REQ-2 AC1): the shell block rides the SAME local
            # channel as the @-card block â€” visible to planning and synthesis
            # for THIS turn only, never add_message()'d.
            if _shell_block:
                context = list(context) + [
                    {"role": "system", "content": _shell_block}
                ]
                logger.info(
                    "[AgentKernel][%s] shell context injected (%d chars, ephemeral)",
                    session_id, len(_shell_block),
                )
        except Exception as e:
            # Handle conversation memory errors gracefully
            logger.warning(f"[AgentKernel] Conversation memory error: {e}")
            context = []  # Continue with empty context

        _t_memory = time.perf_counter()
        logger.debug(
            f"[Timing] memory.get_context: {(_t_memory - _t_start) * 1000:.1f} ms"
        )
        # C5 fold-back: the previous turn's episode lands before planning
        # recalls episodes.
        _turn_end_settle(self)

        # â”€â”€ Direct path (default): skip planning for non-tool messages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Route shadow (REQ-18, T30): record the fork for every turn, ahead
        # of either branch so both route choices land in the log. The gate
        # answer is computed ONCE here and reused by the branch below â€” the
        # shadow must add no work to the reply path (REQ-18 AC2/AC5).
        # REQ-24: the USER's own phrasing exists only here - the
        # tool-decision ladder sees model-rewritten step goals, so stash
        # the turn text for the bounded-ask veto below.
        self._current_turn_text = text or ""
        _needs_planning = self._needs_planning(text, context)
        # route_v2's decision site (2026-11-10): the Oracle's route acts when
        # the bar lets it decide, or on the sampled rung's bounded share of
        # turns (labelled by the turn verdict). Otherwise the gate's route
        # stands and the Oracle is only shadowed below.
        _oracle_route = self._route_v2_route(text, task_id, _needs_planning)
        if _oracle_route is not None:
            _needs_planning = _oracle_route
        self._log_route_shadow(
            turn_id=task_id,
            text=text,
            planned=_needs_planning,
            web_mode=self._web_mode_on(),
            oracle_acted=_oracle_route is not None,
        )
        # Planning only runs when the message explicitly requests a tool-backed
        # action (search, open, create, etc.).  Everything else â€” greetings,
        # questions, conversation â€” goes straight to _respond_direct() which
        # calls the model with no JSON schema overhead.
        if not _needs_planning:
            logger.info("[AgentKernel] Direct response path (no planning needed)")
            try:
                _t_llm_start = time.perf_counter()
                response = self._respond_direct(
                    text,
                    context,
                    chunk_callback=_wrapped_chunk_cb,
                    reasoning_callback=reasoning_callback,
                    session_id=session_id,
                )
                _t_llm_end = time.perf_counter()
                logger.info(
                    f"[Timing] LLM call (_respond_direct): {(_t_llm_end - _t_llm_start) * 1000:.0f} ms  |  "
                    f"total process_text_message: {(_t_llm_end - _t_start) * 1000:.0f} ms"
                )
            except Exception as e:
                logger.error(f"[AgentKernel] LLM call failed: {e}")
                logger.info(metrics.to_log_line())
                # Re-raise so the caller (_execute_agent in iris_gateway.py)
                # handles it with structured logging and sends a visible
                # error to the UI. No silent error swallowing.
                raise
            # Issue C.1: apply speak/show contract â€” emit document:render for
            # the `show` payload and reduce the stored/returned text to `speak`.
            response = self._process_structured_response(
                response, turn_id=task_id, conversation_id=_conv_id
            )
            # Never store error or empty responses in conversation memory.
            # They break role alternation and accumulate into garbage context
            # on subsequent turns, causing Cohere/OpenAI 400 errors.
            if response and not response.startswith("[IRIS error:"):
                try:
                    self._conversation_memory.add_message(
                        "assistant", response, sources=self._turn_sources(),
                    )
                except Exception as _mem_exc:
                    loud_error(_mem_exc, "conversation_memory.add_message (direct)")
            # Option B / Pacman: fragment this turn-pair into the vector DB so future
            # context assembly can retrieve it semantically (PACMAN.md Â§Digestion).
            # MCM orchestrator handles fragmentation + compression check when available.
            try:
                if response:
                    # Trust-routing W2: route to 'reference' when this turn
                    # touched external/web sources; else keep default 'trusted'.
                    _zone = self._pacman_zone_for_turn()
                    if self._mcm_orch is not None:
                        self._mcm_orch.post_turn(
                            self._conversation_memory.messages
                            if self._conversation_memory
                            else [],
                            response_text=response,
                            zone=_zone,
                        )
                        metrics.pacman_store += 1
                    # REQ-12 AC3 (T42): the USER's own words are stored as a turn
                    # pair on BOTH paths, on the fragment lane, bypassing
                    # _is_fragment_candidate (which drops normal conversation).
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        submit_turn_pair as _submit_turn_pair,
                    )

                    if _submit_turn_pair(
                        getattr(self, "_memory_interface", None),
                        session_id or self.session_id,
                        text, response, zone=_zone,
                    ):
                        metrics.pacman_store += 1
            except Exception as _pac_exc:
                loud_error(_pac_exc, "pacman fragment_and_store")
            if response is None:
                logger.error(
                    "[AgentKernel] _respond_direct returned None â€” returning fallback"
                )
                response = "I wasn't able to generate a response. Please check the model connection."
            metrics.path = "direct"
            logger.info(f"[AgentKernel] Direct response: {response[:50]}...")
            logger.info(metrics.to_log_line())
            # REQ-12 (Wave 9): emit live context usage on every non-DER
            # response so the pill is live from the first reply. Uses the real
            # per-thread self._context_fill (never 0 for an active thread).
            self._emit_context_usage()
            return response

        # â”€â”€ Internet-access gate check (runs before DER to save cost) â”€â”€â”€â”€â”€â”€
        # If web tools are disabled and the user explicitly asked for a web
        # search, respond directly without engaging the expensive DER loop.
        # A request that names the live browser needs the web too: with
        # internet off the node menu has no browser tool, and the turn spent
        # 90 s on curl via an unknown run_command, memory lookups and grafts
        # (live conv-1574, 2026-10-12).
        if not get_global_internet_access() and (
            self._is_web_search_request(text) or _LIVE_BROWSER_RE.search(text or "")
        ):
            return (
                "Web search is currently disabled. You can toggle internet "
                "access on via the dashboard (the web button) to enable "
                "web features."
            )

        # â”€â”€ Thinking feedback: emit a filler utterance so the user hears â”€â”€
        # audio feedback while the agent is "thinking" (DER/ReAct path).
        # Gap-filler exception (REQ-10 AC10.13, T16): fires ONLY when speech
        # would otherwise be silent AND no beat is ready; never the same
        # phrase twice consecutively; subsumed the moment a real beat arrives
        # (scheduler.admit cancels queued speak_tool-sourced narration).
        # Fire-and-forget via the speak tool; ConversationKernel drives TTS
        # (phase defaults to EXPAND in production, so it is never suppressed).
        try:
            from backend.agent.tools.speak_tool import get_speak_tool
            from backend.agent.speech_lanes import filler_allowed, pick_filler
            from backend.agent.conversation_kernel import get_conversation_kernel

            _sched = getattr(get_conversation_kernel(), "scheduler", None)
            if filler_allowed(_sched):
                get_speak_tool().speak(pick_filler(), priority="low")
        except Exception as _filler_err:
            logger.debug("[AgentKernel] thinking filler emit skipped: %s", _filler_err)

        # â”€â”€ Lock gate (W6 T27-T29): prevent concurrent DER on same conversation â”€â”€
        if self._der_active:
            # DER is already running for this conversation. Answer chitchat directly
            # or ask the user to wait for complex tool-backed requests.
            if not self._needs_planning(text, context):
                logger.info("[AgentKernel] DER active â€” answering chitchat directly")
                return self._respond_direct(
                    text, context,
                    chunk_callback=_wrapped_chunk_cb,
                    reasoning_callback=reasoning_callback,
                    session_id=session_id,
                )
            logger.info("[AgentKernel] DER active â€” deferring complex request")
            return "Still working on your previous request â€” one moment."

        # â”€â”€ DER path: sanitize â†’ classify â†’ Mycelium â†’ plan â†’ execute â”€â”€â”€â”€â”€â”€
        # Runs BEFORE the ReAct loop. Falls through to ReAct on any failure.
        _der_response: Optional[str] = None
        self._der_active = True
        _der_lock_cleanup = True  # cleared in finally
        # Session 248: stage timing for the pre-plan pipeline â€” live runs show
        # a ~20s silent stall between message receipt and TaskClassifier on
        # the FIRST DER-path message of a process (chitchat bypasses via
        # _respond_direct, so it never pays this). These logs make the lazy
        # init cost visible instead of silent.
        import time as _der_t
        _t_stage = _der_t.monotonic()

        def _log_stage(label: str) -> None:
            nonlocal _t_stage
            logger.info(
                "[Timing] DER stage %s: %.0f ms", label,
                (_der_t.monotonic() - _t_stage) * 1000,
            )
            _t_stage = _der_t.monotonic()

        try:
            _task_clean = self._sanitize_task(text)
            _log_stage("sanitize_task")
            _task_class = "full"
            if self._task_classifier is not None:
                try:
                    _task_class, _ = self._task_classifier.classify(_task_clean)
                    _log_stage("task_classifier.classify")
                except Exception as _tc_exc:
                    loud_error(_tc_exc, "task_classifier.classify")

            _context_package = None
            _is_mature = False
            if self._memory_interface is not None:
                try:
                    _ctx_result = self._memory_interface.get_task_context_package(
                        task=_task_clean,
                        task_class=_task_class,
                        session_id=session_id or self.session_id,
                    )
                    if isinstance(_ctx_result, tuple) and len(_ctx_result) == 2:
                        _context_package, _is_mature = _ctx_result
                    elif _ctx_result is not None:
                        _context_package = _ctx_result
                    _log_stage("get_task_context_package")
                except Exception as _ctx_exc:
                    loud_error(_ctx_exc, "memory_interface.get_task_context_package")

            # Mode detection â€” runs AFTER Mycelium fetch so mature graph data
            # can suppress clarification mode and improve confidence.
            # Result flows into _plan_task() (temperature) and _execute_plan_der()
            # (token budget via DER_TOKEN_BUDGETS[mode]).
            # Voice requests skip mode detection and lock to "voice_first" so
            # they always get the tight 15k token budget and single-step plan.
            # Confidence defaults to 0.5 for voice â€” memory-derived when mature.
            if from_voice:
                _mode_name = "voice_first"
                _confidence = 0.70 if _is_mature else 0.50
            else:
                _mode_name = "full"  # default maps to DER_TOKEN_BUDGETS["full"]
                _confidence = 0.50
                if self._mode_detector is not None:
                    try:
                        _mode_result = self._mode_detector.detect(
                            task=_task_clean,
                            context_package=_context_package,
                            is_mature=_is_mature,
                        )
                        _mode_name = _mode_result.mode.name.lower()
                        _confidence = _mode_result.confidence
                    except Exception as _md_exc:
                        loud_error(_md_exc, "mode_detector.detect")
                    # The `mode` Oracle consumer was REMOVED 2026-10-10 (owner):
                    # no shadow row to forward any more.

            _plan = None
            try:
                self._last_plan_failure = None
            except Exception:
                pass
            for _plan_attempt in range(3):
                _plan = self._plan_task(
                    text=_task_clean,
                    context=context,
                    is_mature=_is_mature,
                    task_class=_task_class,
                    context_package=_context_package,
                    mode=_mode_name,
                    session_id=session_id or self.session_id,
                )
                if _plan is not None:
                    break
                # Billing/auth failures cannot heal in 5 s â€” fail fast with
                # the true cause instead of burning retries on a dead key.
                _classified = self._classify_plan_failure()
                if _classified[2]:
                    break
                if _plan_attempt < 2:
                    # Planner failure is almost always the provider quota: the
                    # transport already burned its 3x30s retries, so the 60s
                    # provider window has usually ROLLED by now â€” a short gap
                    # and a fresh attempt lands in new quota. Without this, a
                    # single saturated minute returned "[IRIS error] The planner
                    # returned no valid plan" (observed live).
                    logger.info(
                        "[process_text_message] planner attempt %d failed â€” "
                        "retrying after quota-window gap",
                        _plan_attempt + 1,
                    )
                    import time as _time_mod

                    _time_mod.sleep(5)
            if _plan is None:
                # REQ-2: planner failure â†’ return ERROR, no silent self-do.
                # The failure kind (recorded by _plan_task) decides the
                # message, so billing/auth/quota/timeout/parse/empty each
                # report distinctly instead of one vague planner error.
                _code, _msg, _ = self._classify_plan_failure()
                logger.warning("[process_text_message] %s code=%s", _msg, _code.name)
                # Every other _emit_context_usage() site sits on a SUCCESS
                # path, so a turn that died here emitted nothing and the
                # ContextPill kept whatever it had â€” with the old hardcoded
                # 128000 initial state that meant it displayed 128k forever on
                # a Cerebras 402 (billing) loop, which is precisely the case
                # that fails fast above. The denominator costs no model call:
                # resolve_context_window() is a lookup. Emitted on the FAILURE
                # path only, so a successful turn still emits exactly once
                # (REQ-6 AC1, pinned by test_context_usage_on_direct_reply).
                self._emit_context_usage()
                return _msg

            # GAP 5 â€” strategy signal to Mycelium after planning
            try:
                if self._memory_interface:
                    self._memory_interface.mycelium_ingest_statement(
                        statement=f"task required {_plan.strategy}: {_plan.reasoning}",
                        session_id=session_id or self.session_id,
                    )
            except Exception as _ing_exc:
                loud_error(_ing_exc, "mycelium_ingest_statement")

            # GAP 6 â€” register plan address when Mycelium is mature
            try:
                if (
                    _is_mature
                    and _context_package
                    and hasattr(_context_package, "register_address")
                ):
                    _plan_ctx_str = _plan.to_context_string()
                    _context_package.register_address(
                        url=f"system://plan/{_plan.plan_id[:8]}",
                        token_count=len(_plan_ctx_str.split()),
                        summary=f"{_plan.strategy}: {_plan.original_task[:60]}",
                    )
            except Exception as _reg_exc:
                loud_error(_reg_exc, "context_package.register_address")

            # GAP 4 â€” route by strategy (do_it_myself â†’ DER; others â†’ ReAct)
            if _plan.strategy == "do_it_myself":
                # â”€â”€ Emit TASK_START early so the frontend sees the plan
                # skeleton BEFORE the DER thread starts executing tools
                # (fixes Q4 plan-late bug â€” without this, task:start and
                # the first tool:call can arrive in the same WS batch,
                # making the plan card appear to jump straight to "working").
                # Voice-only DER bypass: skip DER/card for trivial chit-chat
                # (plan with only speak steps and no websearch intent).
                # Websearch prompts MUST go through DER so the frontend
                # receives card/render events even when the plan has only
                # speak steps â€” the DER loop resolves speak steps via
                # ToolDecisionBox â†’ _run_step_direct, which produces both
                # voice and card output.
                # NOTE (2026-09-27): the "" in this tuple is gone. The docstring
                # of _should_skip_der (F6, 2026-08-12) records why: production
                # plan steps are GOALS ONLY with tool=None, so counting "" as a
                # speak step made EVERY planned task look voice-only and DER was
                # skipped. That fix was applied inside the method but this
                # call-site copy was left behind. It is dead code today (nothing
                # reads it), which is exactly why it survived a review and why it
                # is worth removing rather than leaving to be "reused" later.
                _voice_only = bool(_plan.steps) and all(
                    (s.tool or "").lower() in ("speak", "speak_tool", "tts")
                    for s in _plan.steps
                )
                _is_websearch = self._is_web_search_request(_task_clean)
                # T36 finding (2026-08-09): the skip gate ignored the
                # internet-access toggle. With web mode ON, a factual
                # question ("what are the latest NASA Mars rover
                # discoveries this month?") must reach DER so the crawler
                # path is available â€” even when the text heuristic misses
                # (frontend strips the "websearch:" prefix). Chit-chat
                # ("hello", "how are you") still skips DER on the fast path.
                _web_on = get_global_internet_access()
                _skip_der = self._should_skip_der(
                    _plan.steps, _task_clean, _web_on
                )
                if _skip_der:
                    logger.info(
                        "[AgentKernel] voice-only/trivial plan (steps=%d, "
                        "websearch=%s, web_on=%s, informational=%s) â€” skipping "
                        "DER/card, falling through to direct response",
                        len(_plan.steps),
                        _is_websearch,
                        _web_on,
                        self._looks_informational(_task_clean),
                    )
                    # REQ-35 AC1/AC4: the planner said this needs no plan.
                    # That is a TERMINAL ANSWER -- it decides what happens
                    # NEXT, and it is not a verdict that anything succeeded.
                    #
                    # The comment here used to read "forces the direct path
                    # below" and set "". It did not: the very next guard is
                    # `if _der_response is not None`, an empty STRING is not
                    # None, so control reached the empty-DER handler and
                    # returned the canned apology. Measured live (conv-59):
                    # the planner answered, the answer was discarded, and the
                    # user was told "I wasn't able to put together an answer
                    # for that."
                    #
                    # So take the direct path FOR REAL. Deliberately NOT the
                    # planner's own incidental `answer` field: _respond_direct
                    # re-asks with the full system prompt, context and tools,
                    # so the reply is a normal direct answer rather than a
                    # by-product trusted because the model volunteered it.
                    # No DER ran, so no task:done and no completion claim
                    # (AC4) -- this is an ANSWER, at the same standing as any
                    # other direct reply.
                    try:
                        _der_response = self._respond_direct(
                            text, context,
                            chunk_callback=chunk_callback,
                            reasoning_callback=reasoning_callback,
                            session_id=session_id,
                        )
                        logger.info(
                            "[AgentKernel] trivial plan -> direct answer "
                            "(%d chars)", len(_der_response or ""),
                        )
                    except Exception as _direct_exc:  # noqa: BLE001
                        # AC7: the canned fallback still exists for a run that
                        # genuinely produced nothing. Fewer arrivals is the
                        # goal; removing the path is not.
                        logger.warning(
                            "[AgentKernel] trivial-plan direct answer failed: %s",
                            _direct_exc,
                        )
                        _der_response = ""
                else:
                    # T12 (REQ-10 AC10.10): planning completed and the turn
                    # proceeds to DER â€” the first planned beat speaks now.
                    # (Skipped entirely on the trivial-plan path above: short
                    # work stays fully voiced via the reply lane.)
                    try:
                        self._admit_first_beat(
                            _plan,
                            turn_id=getattr(self, "_current_turn_id", None),
                            session_id=session_id or self.session_id,
                        )
                        # T14: beats 2..N admit as pending narration with
                        # pre-synthesized buffers (degrades to on-admission).
                        self._admit_planned_beats(
                            _plan,
                            turn_id=getattr(self, "_current_turn_id", None),
                            session_id=session_id or self.session_id,
                        )
                    except Exception:
                        pass
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                        _bus = get_event_bus()
                        _steps = [
                            {
                                "id": s.step_id,
                                "description": s.description[:120],
                                "status": "pending",
                                "toolName": s.tool,
                                "stepNumber": s.step_number,
                            }
                            for s in _plan.steps
                        ]
                        logger.info(
                            "[AgentKernel] TASK_CARD ts=%.3f conv=%s turn=%s "
                            "title=%r steps=%d :: %s",
                            time.time(),
                            self.conversation_id,
                            getattr(self, "_current_turn_id", None),
                            (_plan.plan_title or "")[:80],
                            len(_steps),
                            " | ".join(s["description"] for s in _steps)[:300],
                        )
                        # â”€â”€ Card gate (owner bound, 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                        # Decided BEFORE the first task:start emit. Live
                        # 2026-09-25: the DER-internal decision ran AFTER this
                        # emit, so a card-free turn still showed a card whose
                        # terminal events were then withheld â€” the card appeared
                        # and never reached DONE. Registering here (and again in
                        # DER, which also arms the persist gate) closes that gap.
                        try:
                            from backend.agent.artifact_policy import (
                                card_warranted,
                                clear_card_free_conversation,
                                suppress_card_for_conversation,
                            )
                            self._current_task_text = (
                                getattr(_plan, "original_task", "") or ""
                            )
                            if card_warranted(
                                _plan.steps, getattr(_plan, "original_task", "") or ""
                            ) or _developer_mode(self):
                                # This turn HAS a card: stop gating the thread.
                                self._suppressed_card_turn = None
                                clear_card_free_conversation(self.conversation_id)
                            else:
                                _gated_turn = task_id or getattr(self, "_current_turn_id", None)
                                suppress_card_for_conversation(
                                    self.conversation_id, _gated_turn,
                                )
                                # Arms the persist gate too: without it the
                                # snapshot below saved a "running" card row
                                # for every card-free turn, rehydrated later
                                # as a card that never rendered (2026-10-12).
                                self._suppressed_card_turn = _gated_turn
                        except Exception:
                            pass  # the gate must never block a turn
                        _card_task_id = task_id or _plan.original_task[:40]
                        _card_id, _card_relation = self._resolve_card_identity(
                            _card_task_id, "initial"
                        )
                        _bus.emit(
                            IRISStreamEvent.TASK_START,
                            data=self._task_start_payload(
                                task_id=_card_task_id,
                                description=_plan.original_task[:200],
                                plan_title=self._effective_plan_title(_plan),
                                mode=_mode_name,
                                steps=_steps,
                                total_steps=len(_plan.steps),
                                # REQ-14 (T23): initial plan announcement â€”
                                # revisions re-emit through the same merge-by-id
                                # channel with origin "sub_loop_split" (REQ-4/13)
                                # or "user_steering" (REQ-15).
                                origin="initial",
                                # REQ-3 (T2): backend-declared card identity.
                                card_id=_card_id,
                                card_relation=_card_relation,
                                conversation_id=self.conversation_id,
                                    turn_id=getattr(self, "_current_turn_id", None),
                                **self._multiagent_tags(),
                            ),
                            session_id=session_id or self.session_id,
                        )
                        # T4a (REQ-4 AC1): persist the card at task:start â€”
                        # upsert with terminal_state="running".
                        self._persist_card_snapshot(
                            card_id=_card_id,
                            conversation_id=self.conversation_id,
                            card_relation=_card_relation,
                            plan_title=self._effective_plan_title(_plan),
                            mode=_mode_name,
                            steps=_steps,
                            total_steps=len(_plan.steps),
                            terminal_state="running",
                        )
                    except Exception:
                        pass  # never block execution on an event emission failure

                    # Session 247 FIX (recurring â€” see pin_5b79ddf5f112,
                    # pin_9e97e21340e7): the planner MODE name ("implement",
                    # "debug", â€¦) must size the TOKEN BUDGET only. It used to
                    # REPLACE task_class outright, which (a) sent
                    # _decide_mode down its unrecognized-class AGENTIC
                    # default â€” the legacy card-less path with no card_id on
                    # events, no terminal task:done, frozen verbs (live
                    # conv-42) â€” and (b) made explorer.propose withhold web
                    # tools, since propose assigns them only for research
                    # classes. The classifier's label stays authoritative for
                    # every DECISION; the mode name rides along as
                    # _der_budget_class purely for DER_TOKEN_BUDGETS lookup.
                    _der_task_class = _task_class
                    _der_budget_class = (
                        _mode_name if _mode_name in DER_TOKEN_BUDGETS else _task_class
                    )
                    _der_response = self._der_execute_with_recovery(
                        _plan=_plan,
                        _context_package=_context_package,
                        _is_mature=_is_mature,
                        _der_task_class=_der_task_class,
                        _der_budget_class=_der_budget_class,
                        _session=session_id or self.session_id,
                        from_voice=from_voice,
                        _confidence=_confidence,
                        task_id=task_id,
                    )

        except Exception as _der_err:
            logger.warning(
                f"[AgentKernel] DER path error (falling back to ReAct): {_der_err}",
                exc_info=True,
            )
            # Also log to structured logger so error appears in irisvoice.log
            try:
                from backend.core.logging_config import get_agent_logger

                get_agent_logger().warning(
                    "DER path error",
                    error=str(_der_err),
                    error_type=type(_der_err).__name__,
                )
            except Exception:
                pass
            # Store the actual error in _der_response so the error path below
            # can surface it to the user instead of a generic message.
            _der_response = f"[IRIS error: {_der_err}]"
        finally:
            # W6 (T31): always clear the DER active flag, even on exception.
            self._der_active = False

        if _der_response is not None:
            # Only accept DER response if it produced actual content.
            # Empty plans (0 steps completed) or fallback markers from
            # failed local-model execution should fall through to the
            # agentic loop so the model can use tools via the API.
            #
            # Patterns that indicate DER produced no real response:
            #   - empty string
            #   - "[DER]" prefix with "0/" steps
            #   - "[step X completed]" or "[step X error:]" which mean
            #     the local execution model failed to produce content
            _der_text = _der_response.strip()
            _is_empty = not _der_text or (
                "[DER]" in _der_text[:20] and "0/" in _der_text[:50]
            )
            if not _is_empty:
                try:
                    self._conversation_memory.add_message(
                        "assistant", _der_response, sources=self._turn_sources(),
                    )
                except Exception as _mem_exc:
                    loud_error(_mem_exc, "conversation_memory.add_message (der)")
                metrics.path = "der"
                logger.info(f"[AgentKernel] DER response: {_der_response[:200]}...")
                metrics.step_prompt_tokens = getattr(
                    self, "_der_step_prompt_tokens", 0
                )
                # REQ-7 AC3 (T25): record the per-turn DER call count so the
                # loop's actual call count is visible against the T3 baseline.
                metrics.der_calls = getattr(self, "_der_turn_calls", 0)
                # T11 (REQ-12): record the completed-step count â€” wired at the
                # DER loop finalize (was declared-never-assigned before
                # 2026-08-06, so [LAYERS] reported der_steps=0 while steps ran).
                metrics.der_steps = getattr(self, "_der_step_count", 0)
                # REQ-6 AC1/AC3 (T18): governance-source counts for the [LAYERS]
                # line â€” which signal governed this turn's steering decisions
                # (past-memory / live-state / both) and the alternation ratio
                # (computed in to_log_line).
                _gov = getattr(self, "_der_governance_counts", None) or {}
                metrics.gov_past = int(_gov.get("past", 0) or 0)
                metrics.gov_live = int(_gov.get("live", 0) or 0)
                metrics.gov_both = int(_gov.get("both", 0) or 0)
                # REQ-17 AC1 (T34): the REAL budget source (the source that
                # won in resolve_context_window_with_source â€” override /
                # authoritative / table / default), never a silent 8192.
                try:
                    metrics.budget_source = (
                        self.resolve_context_window_with_source().source or "default"
                    )
                except Exception:
                    metrics.budget_source = "default"
                # REQ-17 AC1 (T34): chain-drop count + 429 count this turn.
                metrics.chain_drop_count = int(
                    getattr(self, "_der_chain_drops", 0) or 0
                )
                # 429 count: the rate meter's per-quota 429 frequency, summed
                # across metered windows (the transport observes 429s there;
                # the kernel never counts them itself). 0 when no metered
                # quota exists or the meter is unavailable â€” never raises.
                metrics.count_429 = 0
                try:
                    from backend.agent.rate_meter import get_rate_meter

                    _meter = get_rate_meter()
                    for _qid, _w in _meter._windows.items():
                        if _w.metered:
                            metrics.count_429 += int(
                                _meter.rate_health(_qid).get(
                                    "count_429_in_window", 0
                                )
                                or 0
                            )
                except Exception:
                    metrics.count_429 = 0
                # REQ-17 AC1 (T34): narration decisions this turn (0 when none).
                # Counts the conversation's narration JSONL entries â€” read-only,
                # best-effort, never raises; a missing log file = 0.
                try:
                    from backend.agent.narration import _NARRATION_LOG_DIR
                    import os as _os

                    _npath = _os.path.join(
                        _NARRATION_LOG_DIR, f"{self.conversation_id}.jsonl"
                    )
                    if _os.path.exists(_npath):
                        with open(_npath, "r", encoding="utf-8") as _nf:
                            metrics.narration_decisions = sum(
                                1 for _l in _nf if _l.strip()
                            )
                except Exception:
                    metrics.narration_decisions = 0
                logger.info(metrics.to_log_line())
                # Log DER metrics to structured logger for verifiable backend data
                try:
                    from backend.core.logging_config import get_agent_logger

                    get_agent_logger().info(
                        "DER completed",
                        path=metrics.path,
                        der_steps=metrics.der_steps,
                        pacman_store=metrics.pacman_store,
                        pacman_recall=metrics.pacman_recall,
                        xi=metrics.xi,
                        traj_rows=metrics.traj_rows,
                        map_events=metrics.map_events,
                        ttft_ms=metrics.ttft_ms,
                        e2e_ms=metrics.e2e_ms,
                    )
                except Exception:
                    pass
                # â”€â”€ FIX (session 154): Invoke chunk_callback on DER path â”€â”€
                # The DER loop generates the full response via internal LLM
                # calls but never invokes chunk_callback. Without this call,
                # the TTS sentence_queue only receives the None sentinel,
                # the producer breaks immediately, and no audio is synthesized.
                logger.info(
                    f"[DER-TTS-FIX] chunk_callback={chunk_callback is not None}, "
                    f"der_response_len={len(_der_response) if _der_response else 0}"
                )
                if chunk_callback and _der_response:
                    self._emit_reply_progressively(
                        _der_response, task_id, chunk_callback=chunk_callback
                    )
                    logger.info("[DER-TTS-FIX] chunk_callback invoked OK")
                else:
                    logger.warning(
                        f"[DER-TTS-FIX] SKIPPED â€” chunk_callback={chunk_callback}, "
                        f"der_response={bool(_der_response)}"
                    )
                # Issue C.1: apply speak/show contract before returning.
                _der_response = self._process_structured_response(
                    _der_response, turn_id=task_id, conversation_id=_conv_id
                )
                # REQ-12 AC3 (T42): the DER path never stored the turn pair. Store
                # it here, on the same fragment lane the direct path uses.
                try:
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        submit_turn_pair as _submit_turn_pair,
                    )

                    _submit_turn_pair(
                        getattr(self, "_memory_interface", None),
                        session_id or self.session_id,
                        text, _der_response,
                        zone=self._pacman_zone_for_turn(),
                    )
                except Exception as _tp_err:  # noqa: BLE001 - never blocks a reply
                    logger.debug("[AgentKernel] DER turn pair store skipped: %r", _tp_err)
                try:
                    logger.info(
                        "[TURN-PATH] session=%s path=der mem_prompts=%d reply=%d",
                        session_id, int(getattr(self, "_turn_mem_prompts", 0)),
                        len(_der_response or ""),
                    )
                except Exception:  # noqa: BLE001 - observability never blocks
                    pass
                return _der_response

        # If DER produced empty/failed response, return error instead of
        # falling through to the agentic loop which would retry the API
        # call multiple times and leave the UI stuck in "thinking..." state.
        metrics.path = "der"

        # Extract the actual error from the step error format:
        # [step N error: {actual_error}]
        _der_err_text = ""
        if _der_response and "error:" in _der_response:
            # Find the error after "error:" prefix
            _err_match = _der_response.split("error:")[-1].strip().rstrip("]")
            if _err_match and _err_match != _der_response:
                _der_err_text = _err_match[:300]
        try:
            from backend.core.logging_config import get_agent_logger

            get_agent_logger().warning(
                "DER produced no response",
                error=_der_err_text or "(no error detail)",
            )
        except Exception:
            pass
        logger.warning(
            f"[AgentKernel] DER produced no response: {_der_err_text or '(empty)'}"
        )
        logger.info(metrics.to_log_line())

        # Aware empty-DER fallback (T36 finding 2026-08-09): never return a
        # blind generic error. The agent knows WHY it produced nothing, so it
        # responds usefully: surface the real error, advise the web-mode
        # toggle when the turn clearly wanted a search, or rephrase guidance.
        # Note: message text deliberately avoids the phrase "couldn't
        # generate" (test_model_routing_contract asserts it never reaches a
        # chat_message content on a healthy path).
        _fallback_msg = self._empty_der_fallback_message(
            text,
            web_on=get_global_internet_access(),
            der_err_text=_der_err_text,
        )
        if chunk_callback:
            chunk_callback(_fallback_msg)
            chunk_callback("")
        return _fallback_msg
        # Truncate to avoid leaking full traceback in chat
        if len(_der_error_detail) > 200:
            _der_error_detail = _der_error_detail[:200] + "..."
        # Log to structured logger for diagnostics
        try:
            from backend.core.logging_config import get_agent_logger

            get_agent_logger().warning(
                "DER produced no response",
                error=_der_error_detail,
                error_type=getattr(type(_der_err), "__name__", "Unknown")
                if "_der_err" in dir() and _der_err
                else "NoError",
            )
        except Exception:
            pass
        logger.warning(f"[AgentKernel] DER produced no response: {_der_error_detail}")
        logger.info(metrics.to_log_line())
        return f"IRIS couldn't generate a response. Error: {_der_error_detail}"

    def _turn_is_bounded_content_ask(self) -> bool:
        """REQ-24: is the CURRENT turn a bounded content ask?

        The gate owns the rule (``semantic_gate.is_bounded_content_ask``);
        this is the kernel-side read of the stashed turn text. Never
        raises - an unknown turn is NOT bounded, so no veto is applied and
        the crawl lane stays exactly as it was before REQ-24.
        """
        try:
            from backend.agent.semantic_gate import is_bounded_content_ask

            return bool(is_bounded_content_ask(getattr(self, "_current_turn_text", "")))
        except Exception:
            return False

    def _get_tool_box(self) -> ToolDecisionBox:
        """Return (caching) the ToolDecisionBox for this conversation.

        Lazy-constructs on first call so the box is available even when
        created before ``set_model_selection`` has run.  All dependencies
        are fetched at construction time from the kernel's current state.
        """
        if hasattr(self, "_tool_box") and self._tool_box is not None:
            return self._tool_box
        from backend.agent.tool_registry import get_registry_tools, validate_tool_call

        # memory_lookup_fn â€” consults mycelium / pheromone for tool suggestions
        # (REQ-4 AC6: memory as pre-filter, not fallback; SourceRegistry-like).
        def _mem_lookup(goal: str) -> Optional[Dict[str, Any]]:
            try:
                from backend.agent.explorer import (
                    AUTO_ENGINE, _is_web_intent, _pheromone_top1, _shape_web_query,
                )

                # â”€â”€ pin_517dfcbda150: physics-driven gather sanction â”€â”€
                # pin_42ddd255162d: the gate runs BEFORE the memory checks â€”
                # it needs no memory (conversation state + engine + scheduler
                # oscillators). Behind the old `mi is None` early return it
                # NEVER ran in the DER (whose kernel has no memory interface):
                # web-intent step 1 resolved REASON (tool=null), its short
                # result failed verification, the step split, and the children
                # re-gathered the same URLs â€” the "keeps going back to
                # searching" loop. The route + sanction below also give the
                # FIRST web-intent resolution a hard crawler_query.
                # Applies to ANY goal flavor (not just web-intent phrasing):
                # synthesis steps like "summarize the findings" are NOT web
                # intent by the classifier, yet must be prevented from
                # re-gathering once the task has committed web content.
                # Once â‰¥1 crawl ran this task:
                #   (a) converged (|u| < U_SPLIT)      -> veto gather tools,
                #   (b) new distinct query + budget hit -> veto (budget),
                #   (c) provider under load (amp low)  -> veto (load).
                # A first crawl is ALWAYS sanctioned (content must be gathered
                # once); the phase scheduler's theta pacing handles 429 load.
                try:
                    from backend.agent.der_constants import U_SPLIT
                except Exception:  # pragma: no cover - constant drift guard
                    U_SPLIT = 0.5
                # pin_42ddd255162d: key the gather-sanction state by the
                # CONVERSATION, not the execution session â€” DER split children
                # run under the placeholder session
                # "unknown", which made every child look like a fresh task and
                # bypassed the converged/budget veto (u=0.00 yet children
                # re-gathered in a 5-11ms recursion).
                _g_session = (
                    getattr(self, "conversation_id", "")
                    or getattr(self, "session_id", "")
                    or ""
                )
                # D2: stable action identity â€” deterministic digest, never
                # builtin hash() (process-randomized). Same query -> same key
                # across restarts and replay fixtures.
                try:
                    from backend.agent.der_execution_ledger import make_action_key
                except Exception:  # pragma: no cover - import drift guard
                    make_action_key = None
                _qkey = (
                    make_action_key(goal)
                    if make_action_key is not None
                    else goal.strip().lower()
                )
                _crawl_state = getattr(self, "_der_crawl_attempts", {})
                _attempted = _crawl_state.get(_g_session, set())
                logger.debug(
                    "[DER] gather gate: session=%s attempted=%d qkey_in_attempted=%s",
                    _g_session, len(_attempted), _qkey in _attempted,
                )
                # D1 (REQ-3): physics and scheduler state never AUTHORIZE here.
                # u/xi convergence and phase-manager amplitude are removed from
                # tool authorization â€” the scheduler paces calls; whether a
                # required web action may run is decided by the execution
                # policy below (fresh-query budget only). A converged oscillator
                # means stable physics, NOT task completion, and a failed step's
                # children must still be allowed to gather their sub-query.
                # D6/REQ-9: the same-query repeat is allowed â€” the JobRegistry
                # dedupe serves the cached crawl (no provider call is paid), so
                # a repeat is a read observation, not a new side effect.
                _is_web_goal = False
                try:
                    _is_web_goal = bool(_is_web_intent(
                        goal, engine=AUTO_ENGINE,
                        turn_key=getattr(self, "_current_turn_id", None),
                    ))
                except Exception:  # noqa: BLE001
                    pass
                # A goal that ACTS on a page ("open X in the browser and click
                # Y", "log in", "add to cart") is browser control, not a web
                # search: the pre-commit below would answer it with `search`
                # and the browser would never open. The tool choice (the
                # Oracle) decides it instead.
                if _is_web_goal and _BROWSER_ACTION_RE.search(goal or ""):
                    logger.info("[DER] browser-action goal -> no web pre-commit goal=%r", goal[:60])
                    _is_web_goal = False
                # Spec A4 (RC4): a quick-tier `search` that came back insufficient
                # (requires_deep_crawl) sanctions ONE escalation to crawler_query.
                # The flag is set when the search result lands and cleared when a
                # crawler_query is dispatched (_der_note_quick_tier), never here -
                # this gate runs more than once per step (session-345 finding).
                _escalate = _is_web_goal and (
                    _g_session in getattr(self, "_der_quick_insufficient", ())
                )
                _veto_reason: Optional[str] = None
                if _is_web_goal:
                    # Explicit resource bound (REQ-3 AC3): a FRESH distinct web
                    # query beyond the per-task crawl budget is vetoed. Same-key
                    # repeats skip the budget â€” but Session 312 (conv-99): a
                    # repeat is steered to an honest READ of the already-gathered
                    # documents instead of a re-dispatch, because the promised
                    # cache-served repeat never existed (D6) and every repeat
                    # re-fetched at full price. The result is already in the
                    # document store; reading it IS the repeat's value.
                    if _qkey in _attempted and not _escalate:
                        logger.info(
                            "[DER] exact-repeat gather %r -> steer "
                            "get_rendered_documents (already gathered this turn)",
                            goal[:60],
                        )
                        return {
                            "tool": "get_rendered_documents",
                            "rationale": "exact-repeat gather; read gathered docs instead of re-crawling",
                        }
                    if _qkey not in _attempted and len(_attempted) >= self._MAX_CRAWLS_PER_TASK:
                        _veto_reason = "budget_exhausted"
                if _veto_reason:
                    logger.info(
                        "[DER] web gather vetoed for goal %r -> REASON "
                        "(execution policy: %s)",
                        goal, _veto_reason,
                    )
                    return {
                        "tool": None,
                        "veto": sorted(self._WEB_CONTENT_TOOLS),
                        "rationale": _veto_reason,
                    }

                # REQ-24: a bounded content ask never acquires the research
                # lane. The user asked for reasoning ("compare OLED versus
                # LCD displays for me"), not for fresh facts, so the heavy web
                # gather tools are vetoed for THIS turn - whatever the planner's
                # step goal says (a rewritten goal like "research X vs Y" must
                # not re-open a crawl the user never asked for).
                # Freshness markers, explicit web phrasing and named evidence
                # objects are handled in the predicate: any of them means the
                # ask is NOT bounded, and the crawl lane stays open (AC3).
                if self._turn_is_bounded_content_ask():
                    logger.info(
                        "[DER] bounded content ask -> veto web gather tools "
                        "(REQ-24) goal=%r", goal[:60],
                    )
                    return {
                        "tool": None,
                        "veto": sorted(self._WEB_CONTENT_TOOLS),
                        "rationale": "bounded_content_ask",
                    }

                # Web-intent â†’ crawler_query (capability-gated, not a silent fallback)
                if _is_web_goal:
                    # Session-345 (live finding conv-124): do NOT mark the
                    # qkey here. This gate is consulted more than once per
                    # step (engine hint pass + kernel re-resolution), and a
                    # mark at PROPOSAL time means the superseded first pass
                    # makes the second pass read "already gathered this turn"
                    # and steer to get_rendered_documents â€” the search then
                    # never runs and the turn ends in an honest-but-wrong
                    # refusal. The mark happens at DISPATCH time (where the
                    # tool is actually paid for), not here.
                    from backend.agent.tool_registry import resolve_tool, capability_allowed
                    # Spec A4 (D2): a factual web goal is answered from the quick
                    # tier first - ONE provider call, no crawl - with the question
                    # shaped out of the goal sentence. crawler_query is the
                    # escalation (below), not the default.
                    if not _escalate:
                        _qspec = resolve_tool("search")
                        if _qspec and capability_allowed(_qspec):
                            _shaped_q = _shape_web_query(goal)
                            logger.info(
                                "[DER] web-intent -> search (quick tier) conv=%s query=%r",
                                _g_session, _shaped_q[:80],
                            )
                            return {
                                "tool": "search",
                                "params": {"query": _shaped_q},
                                "rationale": "web-intent (memory pre-filter)",
                            }
                    spec = resolve_tool("crawler_query")
                    if spec and capability_allowed(spec):
                        params: Dict[str, Any] = {"query": goal}
                        # Consult SourceRegistry for known URLs (learned knowledge)
                        # REQ-12 (T16): OFF the DER thread and bounded. This was
                        # `_asyncio.run(sr.resolve(goal, quick=True))` â€” building
                        # and tearing down an event loop inside the step, before
                        # the engine could even start. Now: TTL cache first, then
                        # submit to the gateway's MAIN loop with a <=100ms budget;
                        # over budget we proceed with an empty hint and the
                        # in-flight lookup's result is cached for the next step.
                        try:
                            from backend.agent.explorer import source_hint
                            _sr_loop = None
                            try:
                                from backend.iris_gateway import get_iris_gateway
                                _sr_loop = getattr(get_iris_gateway(), "_main_loop", None)
                            except Exception:  # noqa: BLE001 â€” no gateway â†’ empty hint
                                _sr_loop = None
                            sr_result = source_hint(goal, loop=_sr_loop)
                        except Exception:  # noqa: BLE001 â€” a hint never fails a step
                            sr_result = {}
                            if sr_result.get("hit") and sr_result.get("sources"):
                                known_urls = [
                                    s["url"] for s in sr_result["sources"]
                                    if isinstance(s, dict) and "url" in s
                                ][:3]
                                # Session 312 (URL-level turn memory): filter
                                # URLs this conversation already fetched â€”
                                # conv-99 served the same 4 URLs to 3 gather
                                # steps. All-filtered -> serve nothing (the
                                # crawler does fresh discovery instead of
                                # re-crawling known pages).
                                _crawled = set(getattr(self, "_der_crawled_urls", {}).get(
                                    self.conversation_id or "", set()
                                ))
                                if _crawled and known_urls:
                                    try:
                                        from backend.agent.tool_envelope import normalize_url as _norm_gate
                                        _crawled_n = set(_norm_gate(str(u)) for u in _crawled)
                                        _fresh = [u for u in known_urls if _norm_gate(str(u)) not in _crawled_n]
                                    except Exception:
                                        _fresh = [u for u in known_urls if u not in _crawled]
                                    if _fresh != known_urls:
                                        logger.info(
                                            "[DER] gather gate filtered %d/%d registry URLs already crawled this conversation",
                                            len(known_urls) - len(_fresh), len(known_urls),
                                        )
                                    known_urls = _fresh
                                if known_urls:
                                    params["known_urls"] = known_urls
                        except Exception:
                            pass  # SourceRegistry failure is non-fatal
                        # Session-318 T21-hotfix: the exclusion attach lives OUTSIDE
                        # the registry try-block above â€” a resolve throw must never
                        # skip it (unproven, but a resolve failure coinciding with
                        # a repeat repeat would re-crawl known pages silently).
                        try:
                            _visited_all = sorted(
                                getattr(
                                    self, "_der_crawled_urls", {}
                                ).get(self.conversation_id or "", set())
                            )
                        except Exception:
                            _visited_all = []
                        if _visited_all:
                            params["excluded_urls"] = _visited_all
                            logger.info(
                                "[DER] attach excluded_urls=%d to %s dispatch",
                                len(_visited_all), params.get("query", "")[:40],
                            )
                        return {
                            "tool": "crawler_query",
                            "params": params,
                            "rationale": "web-intent (memory pre-filter)",
                        }

                # REQ-3 AC4 / REQ-5 (specs/long-horizon-der-execution): once the
                # task has committed web evidence (>=1 crawl), steer SYNTHESIS
                # goals toward READING the gathered documents instead of
                # re-gathering. Advisory only â€” _apply_pre_filter keeps the
                # suggested tool alongside generic utilities, so the LLM still
                # chooses; if the read tool is unavailable the pre-filter falls
                # back to the full list. This cuts the observed 4-gather waste
                # (crawler_query x2 + search x2) and the 429 storm it caused.
                # NOTE: no resolve_tool/capability_allowed here â€” that call in
                # the hot path slowed every gate evaluation by seconds.
                try:
                    _SYNTH_TRIGGERS = (
                        "synthes", "summar", "analy", "evaluat", "compar",
                        "recommend", "conclud", "final", "write up", "explain",
                    )
                    # Session-324: steer on DURABLE conversation URL memory,
                    # not the per-turn _attempted budget. _attempted resets at
                    # every turn boundary (process_text_message), so a
                    # summarize-from-prior turn always saw attempted=0 and the
                    # steer never fired â€” live b324_web1 turn 2 resolved REASON
                    # trusting prior context, then infer returned empty twice.
                    # _der_crawled_urls survives across turns per conversation.
                    _conv_evidence323: set = set()
                    try:
                        _conv_evidence323 = set(
                            getattr(self, "_der_crawled_urls", {}).get(
                                self.conversation_id or "", set()
                            )
                        )
                    except Exception:
                        _conv_evidence323 = set()
                    _evidence_committed = bool(_attempted) or bool(_conv_evidence323)
                    if _evidence_committed and not _is_web_goal and any(
                        t in goal.lower() for t in _SYNTH_TRIGGERS
                    ):
                        logger.info(
                            "[DER] evidence-committed synthesis goal %r -> steer %s",
                            goal[:60], "get_rendered_documents",
                        )
                        return {
                            "tool": "get_rendered_documents",
                            "rationale": "evidence committed; synthesize from gathered docs",
                        }
                except Exception:  # noqa: BLE001 â€” steering is advisory
                    pass

                # Memory pre-filter (REQ-4 AC6) â€” mycelium consulted only
                # after the physics gate, which needs no memory.
                mi = getattr(self, "_memory_interface", None)
                if mi is None:
                    return None
                myc = getattr(mi, "_mycelium", None)
                if myc is None:
                    return None

                # Pheromone top-1 prediction (deterministic backstop)
                _session = getattr(self, "session_id", "") or ""
                _task = getattr(self, "_der_task_class", "full") or "full"
                _completed = list(getattr(self, "_der_completed_tools", []) or [])
                top1 = _pheromone_top1(myc, _session, _task, _completed)
                if top1:
                    return {
                        "tool": top1,
                        "params": {},
                        "rationale": "pheromone top-1 (memory pre-filter)",
                    }
                return None
            except Exception:
                return None

        # specs/tool-decision-engine: inject the resident calibrated decision
        # engine (injected, not lazily global â€” unit suites run engine-free for
        # determinism; the engine degrades to legacy path when its model is
        # absent, AC1.3). Wiring lives here so the box stays snapshot-free.
        try:
            from backend.agent.decision_engine import get_decision_engine

            _de = get_decision_engine()
        except Exception:
            _de = None

        self._tool_box = ToolDecisionBox(
            router=self._router,
            tool_bridge=self._tool_bridge,
            get_available_tools=get_registry_tools,
            validate_tool_call=validate_tool_call,
            infer_fn=self.infer,
            memory_lookup_fn=_mem_lookup,
            decision_engine=_de,
        )
        return self._tool_box
