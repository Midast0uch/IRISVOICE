#!/usr/bin/env python3
"""
Agent Kernel

Orchestrates the dual-LLM system with:
- lfm2-8b for reasoning and planning
- lfm2.5-1.2b-instruct for tool execution
- Inter-model communication and state management
- Model failure fallback to single-model mode
"""

from typing import Any, Dict, Optional, List
import json
import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from .model_router import ModelRouter
from .memory import ConversationMemory, TaskRecord
from .personality import PersonalityManager
from .vps_gateway import VPSGateway, VPSConfig
from .inter_model_communication import InterModelCommunicator
from .model_conversation import ModelConversation


@dataclass
class TaskContext:
    """
    Carries full context through the entire task pipeline.
    
    This is the single object that carries context from the user's message
    through planning, execution, and response synthesis. It prevents context
    loss at handoff points between the brain and executor models.
    """
    task_id: str                          # unique per user message
    user_message: str                     # original user request — never lost
    session_id: str
    conversation_history: List[Dict]      # snapshot of memory at task start
    plan: Optional[Dict] = None           # brain's plan (set after planning)
    step_results: List[Dict] = field(default_factory=list)  # accumulates as steps execute
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    
    def get_results_summary(self) -> str:
        """Get a formatted summary of all step results for the brain."""
        if not self.step_results:
            return "No tool results."
        
        summary_parts = []
        for i, result in enumerate(self.step_results, 1):
            if isinstance(result, dict):
                if "error" in result:
                    summary_parts.append(f"Step {i}: ERROR - {result.get('error')}")
                elif result.get("success"):
                    tool_name = result.get("tool", "unknown")
                    action = result.get("action", "")
                    result_text = result.get("result", result.get("response", ""))
                    summary_parts.append(f"Step {i}: {tool_name} ({action}): {result_text[:200]}")
        
        return "\n".join(summary_parts) if summary_parts else "No tool results."

class AgentKernel:
    """
    Central orchestrator for the dual-LLM agent system.
    
    Coordinates:
    - lfm2-8b (reasoning model) for planning and analysis
    - lfm2.5-1.2b-instruct (execution model) for tool execution
    - Inter-model communication and state management
    - Model failure fallback to single-model mode
    """

    def __init__(
        self, 
        config_path: str = "./backend/agent/agent_config.yaml",
        session_id: str = "default"
    ):
        """
        Initialize AgentKernel with dual-LLM coordination.
        
        Args:
            config_path: Path to agent configuration YAML
            session_id: Session identifier for conversation memory
        """
        self.config_path = config_path
        self.session_id = session_id
        
        # Core components
        self._model_router: Optional[ModelRouter] = None
        self._vps_gateway: Optional[VPSGateway] = None
        self._conversation_memory: Optional[ConversationMemory] = None
        self._personality: Optional[PersonalityManager] = None
        self._tool_bridge = None  # Will be initialized lazily
        self._inter_model_communicator: Optional[InterModelCommunicator] = None  # For brain↔executor logging
        
        # State management
        self._single_model_mode = False
        self._available_model_id: Optional[str] = None
        self._initialization_error: Optional[str] = None
        
        # Model selection (user-configurable dual-LLM)
        self._selected_reasoning_model: Optional[str] = None
        self._selected_tool_execution_model: Optional[str] = None
        # Provider the user selected in the UI.
        # "lmstudio" → LM Studio OpenAI-compatible API (localhost:1234)  ← recommended
        # "local"    → Ollama (http://localhost:11434)
        # "vps"      → VPS Gateway (self._vps_gateway)
        # "api"      → OpenAI API (cloud)
        self._model_provider: str = "uninitialized"

        # LM Studio base URL — set via configure_lmstudio() when confirm_card fires
        self._lmstudio_endpoint: str = "http://localhost:1234"

        # Thinking extracted from the most recent _respond_direct call.
        # Set before returning so iris_gateway can include it in the text_response payload.
        self._pending_thinking: str = ""
        
        # VPS configuration (loaded from settings)
        self._vps_config: Optional[VPSConfig] = None
        
        # Internet access control (default: False to match UI default)
        self._internet_access_enabled: bool = False
        
        # Initialize components
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all core components with error handling."""
        try:
            # Initialize Model Router with UNINITIALIZED mode (lazy loading)
            logger.info("[AgentKernel] Initializing Model Router in UNINITIALIZED mode (lazy loading)...")
            from .model_router import InferenceMode
            self._model_router = ModelRouter(self.config_path, inference_mode=InferenceMode.UNINITIALIZED)
            logger.info("[AgentKernel] Model Router initialized - models will NOT be loaded automatically")
            logger.info("[AgentKernel] Models will be loaded only when user selects Local Model inference mode")
            
            # In UNINITIALIZED mode, we don't have models yet
            logger.info("[AgentKernel] Waiting for user to configure inference mode (Local/VPS/OpenAI)")
            self._single_model_mode = False
                
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Model Router: {e}")
            self._initialization_error = f"Model Router initialization failed: {e}"
            self._model_router = None
        
        # VPS Gateway is lazy: only created when the user explicitly enables VPS mode
        # via configure_vps(). Creating it per-session at startup is wasteful and triggers
        # health-check loops for every WebSocket reconnect even when VPS is disabled.
        self._vps_config = VPSConfig(enabled=False)
        self._vps_gateway = None
        logger.info("[AgentKernel] VPS Gateway deferred (lazy init — awaiting user VPS configuration)")
        
        try:
            # Initialize Conversation Memory
            logger.info(f"[AgentKernel] Initializing Conversation Memory for session {self.session_id}...")
            self._conversation_memory = ConversationMemory(
                session_id=self.session_id,
                max_messages=10  # Default from requirements
            )
            logger.info("[AgentKernel] Conversation Memory initialized")
            
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Conversation Memory: {e}")
            self._initialization_error = f"Conversation Memory initialization failed: {e}"
            self._conversation_memory = None
        
        try:
            # Initialize Personality Manager
            logger.info("[AgentKernel] Initializing Personality Manager...")
            self._personality = PersonalityManager()
            logger.info("[AgentKernel] Personality Manager initialized")
            
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Personality Manager: {e}")
            self._initialization_error = f"Personality Manager initialization failed: {e}"
            self._personality = None
        
        try:
            # Initialize Inter-Model Communicator for brain↔executor logging (Bug 5 fix)
            logger.info("[AgentKernel] Initializing Inter-Model Communicator...")
            if self._model_router:
                model_conversation = ModelConversation()
                self._inter_model_communicator = InterModelCommunicator(
                    model_router=self._model_router,
                    conversation=model_conversation
                )
                logger.info("[AgentKernel] Inter-Model Communicator initialized")
            else:
                logger.warning("[AgentKernel] Inter-Model Communicator not initialized: Model Router unavailable")
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Inter-Model Communicator: {e}")
            self._inter_model_communicator = None
        
        # Tool Bridge will be initialized lazily when needed
        
        # Memory Foundation integration
        self._memory_interface: Optional[Any] = None
        
        logger.info("[AgentKernel] Initialization complete")
    
    def set_memory_interface(self, memory_interface: Any) -> None:
        """
        Set the memory interface for the agent kernel.
        
        This is called after AgentKernel initialization to wire in
        the Memory Foundation system.
        
        Args:
            memory_interface: MemoryInterface instance from backend.memory
        """
        self._memory_interface = memory_interface
        logger.info("[AgentKernel] Memory interface connected")
    
    def _get_memory_context(self, task: str) -> str:
        """
        Get memory-augmented context for a task.
        
        Args:
            task: Task description
        
        Returns:
            Context string with memory augmentation
        """
        if self._memory_interface is None:
            return ""
        
        try:
            context = self._memory_interface.get_task_context(
                task=task,
                session_id=self.session_id
            )
            return context
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to get memory context: {e}")
            return ""
    
    def _store_task_episode(
        self,
        task_summary: str,
        full_content: str,
        outcome_type: str = "success",
        tool_sequence: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        Store a task episode in memory.
        
        Args:
            task_summary: Brief task description
            full_content: Full conversation/task content
            outcome_type: Task outcome (success, failure, etc.)
            tool_sequence: List of tool calls made
        """
        if self._memory_interface is None:
            return
        
        try:
            from backend.memory import Episode
            
            episode = Episode(
                session_id=self.session_id,
                task_summary=task_summary,
                full_content=full_content,
                tool_sequence=tool_sequence or [],
                outcome_type=outcome_type,
                source_channel="websocket",
                node_id="local",
                origin="local"
            )
            
            self._memory_interface.store_episode(episode)
            logger.debug(f"[AgentKernel] Stored episode for task: {task_summary[:50]}...")
            
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to store episode: {e}")
    
    async def initialize_vps_gateway(self) -> None:
        """
        Initialize VPS Gateway asynchronously.
        
        This should be called after AgentKernel initialization to set up
        the VPS Gateway with async operations (health checks, etc.).
        """
        if self._vps_gateway and self._vps_config and self._vps_config.enabled:
            try:
                logger.info("[AgentKernel] Initializing VPS Gateway async operations...")
                await self._vps_gateway.initialize()
                logger.info("[AgentKernel] VPS Gateway async initialization complete")
            except Exception as e:
                logger.error(f"[AgentKernel] Failed to initialize VPS Gateway async: {e}")
    
    async def shutdown_vps_gateway(self) -> None:
        """
        Shutdown VPS Gateway gracefully.
        
        This should be called when AgentKernel is being shut down to clean up
        VPS Gateway resources (HTTP clients, health check tasks, etc.).
        """
        if self._vps_gateway:
            try:
                logger.info("[AgentKernel] Shutting down VPS Gateway...")
                await self._vps_gateway.shutdown()
                logger.info("[AgentKernel] VPS Gateway shutdown complete")
            except Exception as e:
                logger.error(f"[AgentKernel] Error during VPS Gateway shutdown: {e}")
    
    def configure_vps(self, vps_config: Dict[str, Any]) -> None:
        """
        Configure VPS Gateway from settings.
        
        Args:
            vps_config: Dictionary containing VPS configuration fields from agent.vps section
                - enabled: bool - Enable VPS routing
                - endpoints: List[str] - VPS endpoint URLs
                - auth_token: str - Authentication token
                - timeout: int - Request timeout in seconds
                - health_check_interval: int - Health check interval in seconds
                - fallback_to_local: bool - Fall back to local on VPS failure
                - load_balancing: bool - Enable load balancing
                - load_balancing_strategy: str - "round_robin" or "least_loaded"
                - protocol: str - "rest" or "websocket"
                - offload_tools: bool - Offload tool execution to VPS
        """
        try:
            logger.info(f"[AgentKernel] Configuring VPS Gateway: {vps_config}")
            
            # Create VPSConfig from settings
            self._vps_config = VPSConfig(
                enabled=vps_config.get("enabled", False),
                endpoints=vps_config.get("endpoints", []),
                auth_token=vps_config.get("auth_token"),
                timeout=vps_config.get("timeout", 30),
                health_check_interval=vps_config.get("health_check_interval", 60),
                fallback_to_local=vps_config.get("fallback_to_local", True),
                load_balancing=vps_config.get("load_balancing", False),
                load_balancing_strategy=vps_config.get("load_balancing_strategy", "round_robin"),
                protocol=vps_config.get("protocol", "rest"),
                offload_tools=vps_config.get("offload_tools", False)
            )
            
            # Only create VPSGateway when user has explicitly enabled it.
            # This prevents health-check loops on every reconnect when VPS is disabled.
            if self._vps_config.enabled and self._model_router:
                self._vps_gateway = VPSGateway(self._vps_config, self._model_router)
                logger.info(f"[AgentKernel] VPS Gateway created: enabled={self._vps_config.enabled}, endpoints={len(self._vps_config.endpoints)}")
            elif not self._vps_config.enabled:
                # VPS disabled — clear any existing gateway to stop health checks
                self._vps_gateway = None
                logger.info("[AgentKernel] VPS Gateway disabled by user config")
            else:
                logger.warning("[AgentKernel] Cannot configure VPS Gateway: Model Router unavailable")

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to configure VPS Gateway: {e}")
            self._vps_config = VPSConfig(enabled=False)
            self._vps_gateway = None

    def configure_lmstudio(self, endpoint: str) -> None:
        """Store the LM Studio base URL for inference routing."""
        self._lmstudio_endpoint = endpoint.rstrip("/")
        logger.info(f"[AgentKernel] LM Studio endpoint configured: {self._lmstudio_endpoint}")

    # ------------------------------------------------------------------
    # Helpers: thinking-token stripping, planning gate, direct response
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_thinking(text: str) -> tuple:
        """Split model output into (thinking: str, response: str).

        Handles three forms of chain-of-thought output:
        1. <think>…</think> XML tags  (Qwen3 thinking mode)
        2. <thinking>…</thinking> XML tags  (DeepSeek-style)
        3. Untagged preamble paragraphs where the model narrates its reasoning
           ("Okay, the user is asking…", "Let me think…", etc.) before a blank
           line that separates it from the real answer.

        Returns:
            (thinking, clean_response) — thinking is an empty string when none found.
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

    @staticmethod
    def _needs_planning(text: str) -> bool:
        """
        Return True only when the message explicitly requests a tool-backed action.
        Conversational messages, greetings, and simple questions bypass planning entirely.
        """
        t = text.lower()
        TOOL_TRIGGERS = [
            "search", "find", "look up", "look for", "open", "launch", "start app",
            "create", "write a file", "run", "execute", "install", "delete", "remove",
            "screenshot", "take a photo", "click", "automate", "schedule",
            "remind me", "set alarm", "set timer", "play music", "stop music",
            "download", "upload", "send email", "browse",
        ]
        return any(trigger in t for trigger in TOOL_TRIGGERS)

    def _respond_direct(self, text: str, context: List[Dict]) -> str:
        """
        Respond directly to the user without planning or tool execution.
        This is the default path for all conversational and non-tool messages.
        """
        system_prompt = (
            "You are IRIS, a helpful, warm, and personable AI voice assistant. "
            "Respond naturally and concisely."
        )
        if self._personality:
            try:
                system_prompt = self._personality.get_system_prompt()
            except Exception:
                pass

        # Build context window: last 8 messages, always starting with a user turn.
        # Qwen3 (and most models) require the first non-system message to be "user".
        # A mid-conversation slice can begin with an assistant turn when the rolling
        # window cuts between a user→assistant pair — strip any leading assistant
        # messages so the pattern is always [system, user, assistant?, user, …].
        context_window = list(context[-8:])
        while context_window and context_window[0]["role"] != "user":
            context_window.pop(0)

        messages: List[Dict] = [{"role": "system", "content": system_prompt}]
        for msg in context_window:
            messages.append(msg)

        # Final guard: if context was empty (memory exception path) or somehow
        # ends on an assistant message, append the current text explicitly.
        if not context_window or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": text})

        try:
            # LM Studio (OpenAI-compatible)
            if self._model_provider == "lmstudio":
                from openai import OpenAI as _OpenAI
                client = _OpenAI(base_url=f"{self._lmstudio_endpoint}/v1", api_key="lm-studio")
                sel = self._selected_reasoning_model or "local-model"
                resp = client.chat.completions.create(
                    model=sel,
                    messages=messages,
                    max_tokens=-1,    # -1 = unlimited for LM Studio (local model, no billing cap)
                    temperature=0.6,  # Qwen3 recommended; slightly more decisive
                    # Thinking enabled — model reasons when it needs to.
                    # _parse_thinking splits the <think> block from the clean response;
                    # the thinking is stored in _pending_thinking for ChatView to display
                    # as a collapsible section, leaving the response itself clean.
                    extra_body={"chat_template_kwargs": {"enable_thinking": True}},
                )
                reply = resp.choices[0].message.content or ""
                thinking, clean = self._parse_thinking(reply)
                self._pending_thinking = thinking
                return clean

            # Ollama (model IDs contain ":")
            if self._selected_reasoning_model and ":" in self._selected_reasoning_model:
                import requests as _req
                r = _req.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": self._selected_reasoning_model,
                        "messages": messages,
                        "stream": False,
                    },
                    timeout=30,
                )
                if r.status_code == 200:
                    reply = r.json().get("message", {}).get("content", "")
                    thinking, clean = self._parse_thinking(reply)
                    self._pending_thinking = thinking
                    return clean

            # Local loaded model
            reasoning_model = None
            if self._model_router and self._selected_reasoning_model:
                reasoning_model = self._model_router.models.get(self._selected_reasoning_model)
            if not reasoning_model and self._model_router:
                reasoning_model = self._model_router.get_reasoning_model()
            if reasoning_model:
                reply = reasoning_model.generate(text)
                thinking, clean = self._parse_thinking(reply)
                self._pending_thinking = thinking
                return clean

        except Exception as e:
            logger.error(f"[AgentKernel] Direct response error: {e}", exc_info=True)
            raise

    # Word count above which we generate a shorter spoken variant for TTS.
    _SPOKEN_WORD_LIMIT: int = 40

    def get_spoken_version(self, text: str) -> str:
        """Return a TTS-friendly spoken variant of *text*.

        For short responses (≤ _SPOKEN_WORD_LIMIT words) the original text is
        returned unchanged — it is already suitable for speech.

        For longer responses a second, fast LLM call is made asking the model
        to distil the answer into 1-2 conversational sentences.  The full
        text still goes to ChatView; only this shorter version is spoken.

        Falls back to the original text if the LLM call fails or returns
        nothing useful.
        """
        if len(text.split()) <= self._SPOKEN_WORD_LIMIT:
            return text

        prompt = (
            "The following is a detailed AI response. "
            "Rewrite it as 1-2 short spoken sentences in a casual, conversational tone. "
            "No bullet points, no markdown, no lists — just natural speech a voice assistant would say:\n\n"
            f"{text}"
        )
        try:
            if self._model_provider == "lmstudio":
                from openai import OpenAI as _OpenAI
                client = _OpenAI(base_url=f"{self._lmstudio_endpoint}/v1", api_key="lm-studio")
                sel = self._selected_reasoning_model or "local-model"
                resp = client.chat.completions.create(
                    model=sel,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=-1,    # unlimited — local model, let it finish cleanly
                    temperature=0.5,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
                spoken = self._strip_thinking(resp.choices[0].message.content or "")
                if spoken.strip():
                    logger.debug(f"[AgentKernel] Spoken version: {spoken!r}")
                    return spoken

            if self._selected_reasoning_model and ":" in self._selected_reasoning_model:
                import requests as _req
                r = _req.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": self._selected_reasoning_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                    timeout=20,
                )
                if r.status_code == 200:
                    spoken = self._strip_thinking(r.json().get("message", {}).get("content", ""))
                    if spoken.strip():
                        return spoken

        except Exception as e:
            logger.warning(f"[AgentKernel] get_spoken_version LLM call failed: {e}")

        return text  # fallback: speak full response

    # ── Tool definitions for OpenAI-compatible function calling ─────────────

    def _get_openai_tools(self) -> List[Dict]:
        """Convert tool_bridge tool list to OpenAI-compatible function-calling format.

        Each entry becomes:
          {"type": "function", "function": {"name": …, "description": …, "parameters": {…}}}
        """
        if not self._tool_bridge:
            return []
        openai_tools: List[Dict] = []
        for t in self._tool_bridge.get_available_tools():
            props: Dict[str, Any] = {}
            required: List[str] = []
            for pname, pspec in t.get("parameters", {}).items():
                props[pname] = {
                    "type": pspec.get("type", "string"),
                    "description": pspec.get("description", ""),
                }
                if not pspec.get("optional", False):
                    required.append(pname)
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            })
        return openai_tools

    # ── ReAct agentic loop ───────────────────────────────────────────────────

    def _run_agentic_loop(self, messages: List[Dict], session_id: str) -> str:
        """ReAct agentic loop — the core of multi-step task execution.

        Calls the LLM with tool definitions.  If the model returns
        ``finish_reason="tool_calls"`` the tools are executed and their results
        are appended to the message history before the next LLM call.  This
        repeats until the model produces a ``finish_reason="stop"`` response,
        which is returned as the final answer.

        Why this replaces the old plan→execute→synthesize pipeline
        ────────────────────────────────────────────────────────────
        The old pipeline asked the model to emit a static JSON plan upfront,
        then executed it blindly.  The model never saw tool results, so it
        could not adapt when a step failed or produced unexpected output.  This
        loop (ReAct pattern) lets the model observe each result and decide what
        to do next — enabling genuine multi-step reasoning and recovery.

        Args:
            messages: Initial message list (system + conversation history + user turn).
            session_id: Passed through to tool_bridge for session isolation.

        Returns:
            The model's final clean response string.
        """
        MAX_ITERATIONS = 8
        tools = self._get_openai_tools()

        for iteration in range(MAX_ITERATIONS):
            logger.info(
                f"[AgentLoop] Iteration {iteration + 1}/{MAX_ITERATIONS}, "
                f"messages={len(messages)}, tools={len(tools)}"
            )
            try:
                # ── LM Studio (OpenAI-compatible API) ────────────────────────
                if self._model_provider == "lmstudio":
                    from openai import OpenAI as _OpenAI
                    client = _OpenAI(
                        base_url=f"{self._lmstudio_endpoint}/v1",
                        api_key="lm-studio",
                    )
                    sel = self._selected_reasoning_model or "local-model"

                    call_kwargs: Dict[str, Any] = dict(
                        model=sel,
                        messages=messages,
                        max_tokens=-1,
                        temperature=0.6,
                        # Thinking OFF during tool-call iterations — models need
                        # clean JSON for tool_calls; thinking can be re-enabled
                        # on the final free-response turn if desired.
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    if tools:
                        call_kwargs["tools"] = tools
                        call_kwargs["tool_choice"] = "auto"

                    resp = client.chat.completions.create(**call_kwargs)
                    choice = resp.choices[0]

                    # Model finished without requesting any tool — return response
                    if choice.finish_reason == "stop" or not choice.message.tool_calls:
                        content = choice.message.content or ""
                        thinking, clean = self._parse_thinking(content)
                        self._pending_thinking = thinking
                        return clean

                    # Model wants to use one or more tools
                    if choice.message.tool_calls:
                        # Serialize the assistant turn so the model keeps its own
                        # tool_call references in subsequent context passes
                        messages.append({
                            "role": "assistant",
                            "content": choice.message.content or "",
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in choice.message.tool_calls
                            ],
                        })

                        for tc in choice.message.tool_calls:
                            t_name = tc.function.name
                            try:
                                t_args = json.loads(tc.function.arguments)
                            except Exception:
                                t_args = {}

                            logger.info(
                                f"[AgentLoop] Tool call: {t_name}({list(t_args.keys())})"
                            )

                            # Execute tool — tool_bridge.execute_tool is async;
                            # asyncio.run() is safe here because process_text_message
                            # runs inside a thread-pool executor (no event loop in thread).
                            try:
                                if self._tool_bridge:
                                    t_result = asyncio.run(
                                        self._tool_bridge.execute_tool(
                                            t_name, t_args, session_id
                                        )
                                    )
                                else:
                                    t_result = {"error": "Tool bridge not available"}
                            except RuntimeError as run_err:
                                # asyncio.run() can fail if called from inside an
                                # already-running loop (shouldn't happen here, but just
                                # in case the executor shares a loop in a future version)
                                logger.warning(
                                    f"[AgentLoop] asyncio.run failed: {run_err} — using ThreadPoolExecutor"
                                )
                                import concurrent.futures
                                loop = asyncio.new_event_loop()
                                try:
                                    t_result = loop.run_until_complete(
                                        self._tool_bridge.execute_tool(
                                            t_name, t_args, session_id
                                        )
                                    )
                                finally:
                                    loop.close()
                            except Exception as exec_err:
                                logger.error(
                                    f"[AgentLoop] Tool {t_name} raised: {exec_err}"
                                )
                                t_result = {"error": str(exec_err), "tool": t_name}

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": (
                                    json.dumps(t_result)
                                    if isinstance(t_result, dict)
                                    else str(t_result)
                                ),
                            })
                        continue  # next iteration — model sees tool results

                # ── Fallback for non-LM-Studio providers ─────────────────────
                # Ollama and local models don't support tool calling yet;
                # fall back to a direct conversational response.
                last_user = next(
                    (m["content"] for m in reversed(messages) if m["role"] == "user"),
                    "",
                )
                ctx = [m for m in messages if m["role"] in ("user", "assistant")][-8:]
                return self._respond_direct(last_user, ctx)

            except Exception as loop_err:
                logger.error(
                    f"[AgentLoop] Iteration {iteration + 1} error: {loop_err}",
                    exc_info=True,
                )
                if iteration == 0:
                    raise  # Let caller handle on first iteration
                break

        # Max iterations reached — ask model to summarise what it found
        logger.warning(f"[AgentLoop] Max iterations ({MAX_ITERATIONS}) reached")
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "your request",
        )
        summary_ctx = [
            m for m in messages if m["role"] in ("user", "assistant")
        ][-6:]
        return self._respond_direct(
            f"Summarise what you found so far for: {last_user}", summary_ctx
        )

    def process_text_message(self, text: str, session_id: Optional[str] = None) -> str:
        """
        Process a text message with dual-LLM coordination.

        Workflow:
        1. Add user message to conversation memory
        2. Plan task using reasoning model
        3. Execute plan using execution model
        4. Generate response and add to conversation memory

        Args:
            text: User's text message
            session_id: Optional session ID (uses instance session_id if not provided)
            
        Returns:
            Agent's response text
        """
        # Use provided session_id or fall back to instance session_id
        if session_id is None:
            session_id = self.session_id

        # Reset thinking from any previous call so stale data never leaks
        self._pending_thinking = ""

        # Check if agent is available
        if self._initialization_error:
            error_msg = f"Agent kernel is not available: {self._initialization_error}"
            logger.error(f"[AgentKernel] {error_msg}")
            return error_msg
        
        if not self._model_router or not self._conversation_memory:
            error_msg = "Agent kernel is not available"
            logger.error(f"[AgentKernel] {error_msg}")
            return error_msg
        
        # Create TaskContext to carry full context through pipeline (fixes Bug 3, 4, 5, 6)
        import uuid
        task_id = str(uuid.uuid4())
        
        try:
            # Add user message to conversation memory
            self._conversation_memory.add_message("user", text)
            logger.info(f"[AgentKernel] Processing text message: {text[:50]}...")
            
            # Get conversation context
            context = self._conversation_memory.get_context()
        except Exception as e:
            # Handle conversation memory errors gracefully
            logger.warning(f"[AgentKernel] Conversation memory error: {e}")
            context = []  # Continue with empty context

        # ── Direct path (default): skip planning for non-tool messages ──────────
        # Planning only runs when the message explicitly requests a tool-backed
        # action (search, open, create, etc.).  Everything else — greetings,
        # questions, conversation — goes straight to _respond_direct() which
        # calls the model with no JSON schema overhead.
        if not self._needs_planning(text):
            logger.info("[AgentKernel] Direct response path (no planning needed)")
            try:
                response = self._respond_direct(text, context)
            except Exception as e:
                logger.error(f"[AgentKernel] LLM call failed: {e}")
                return f"[IRIS error: could not reach language model — {type(e).__name__}]"
            try:
                self._conversation_memory.add_message("assistant", response)
            except Exception:
                pass
            logger.info(f"[AgentKernel] Direct response: {response[:50]}...")
            return response

        # ── Agentic loop path: for tool-trigger messages ─────────────────────
        # Build the initial message list (system + conversation history + user turn).
        # The loop will append assistant + tool messages on each iteration until the
        # model emits finish_reason="stop", at which point we have the final answer.
        system_prompt = (
            "You are IRIS, a helpful, warm, and capable AI assistant with access to tools. "
            "Think through tasks step by step, use tools when needed, and give clear answers."
        )
        if self._personality:
            try:
                system_prompt = self._personality.get_system_prompt()
            except Exception:
                pass

        loop_messages: List[Dict] = [{"role": "system", "content": system_prompt}]
        context_window = list(context[-6:])
        while context_window and context_window[0]["role"] != "user":
            context_window.pop(0)
        for msg in context_window:
            loop_messages.append(msg)
        if not context_window or loop_messages[-1]["role"] != "user":
            loop_messages.append({"role": "user", "content": text})

        try:
            response = self._run_agentic_loop(loop_messages, session_id or self.session_id)
        except Exception as e:
            logger.error(f"[AgentKernel] Agentic loop failed: {e}", exc_info=True)
            try:
                response = self._respond_direct(text, context)
            except Exception:
                response = "[IRIS error: could not process request]"

        # Add assistant response to conversation memory
        try:
            self._conversation_memory.add_message("assistant", response)
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to save response to conversation memory: {e}")

        # Record task for session-level memory continuity
        try:
            import uuid as _uuid
            task_record = TaskRecord(
                task_id=task_id,
                user_message=text,
                summary=response,
                step_count=len([m for m in loop_messages if m.get("role") == "tool"]),
                had_failures=False,
                tool_names_used=[
                    m.get("content", "")[:30]
                    for m in loop_messages
                    if m.get("role") == "tool"
                ],
                started_at=time.time(),
                completed_at=time.time(),
                session_id=session_id or self.session_id,
            )
            self._conversation_memory.record_task(task_record)
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to record task: {e}")

        logger.info(f"[AgentKernel] Generated response: {response[:50]}...")
        return response

    def plan_task(self, task_description: str, context: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Use lfm2-8b (reasoning model) for task planning with timeout and error handling.
        
        Args:
            task_description: User's task/query
            context: Optional conversation context
            
        Returns:
            Plan dictionary with steps, or error dictionary
            
        Raises:
            TimeoutError: If inference exceeds timeout
        """
        start_time = time.time()
        # 120s: LM Studio with a 9B model can take 30-60s for first token on cold start
        timeout_seconds = 120

        try:
            logger.info("[AgentKernel] Planning task with reasoning model...")
            
            # Get reasoning model
            reasoning_model = None
            if self._model_router:
                try:
                    # Use user-selected reasoning model if available
                    if self._selected_reasoning_model:
                        reasoning_model = self._model_router.models.get(self._selected_reasoning_model)
                        if reasoning_model:
                            logger.info(f"[AgentKernel] Using user-selected reasoning model: {self._selected_reasoning_model}")
                        else:
                            # Only fall back to the default local stub when neither Ollama
                            # nor VPS will handle this request.  If ":" is in the model ID
                            # it is an Ollama model (e.g. "llama3.2:3b"); if VPS is wired
                            # the VPS block below handles it.  In those cases we MUST NOT
                            # fall back — the stub is broken and produces garbage output.
                            _sel_check = self._selected_reasoning_model
                            _ollama_will_handle = ":" in _sel_check
                            _vps_will_handle = bool(self._vps_gateway)
                            _lmstudio_will_handle = self._model_provider == "lmstudio"
                            if not _ollama_will_handle and not _vps_will_handle and not _lmstudio_will_handle:
                                logger.warning(
                                    f"[AgentKernel] Selected model {_sel_check} unavailable, "
                                    "falling back to default local model"
                                )
                                reasoning_model = self._model_router.get_reasoning_model()
                                if reasoning_model:
                                    default_model_id = getattr(reasoning_model, 'model_id', 'unknown')
                                    logger.info(f"[AgentKernel] Fallback: using default reasoning model {default_model_id}")
                            else:
                                _dest = "LM Studio" if _lmstudio_will_handle else ("Ollama" if _ollama_will_handle else "VPS")
                                logger.info(
                                    f"[AgentKernel] Selected model '{_sel_check}' not in local cache — "
                                    f"will route to {_dest}"
                                )
                                # reasoning_model stays None; inference block handles it
                    else:
                        # No model selected — use default reasoning model
                        reasoning_model = self._model_router.get_reasoning_model()
                        if reasoning_model:
                            default_model_id = getattr(reasoning_model, 'model_id', 'unknown')
                            logger.info(f"[AgentKernel] No model selected, using default reasoning model: {default_model_id}")
                except Exception as e:
                    logger.error(f"[AgentKernel] Error getting reasoning model: {e}")
                    return {"error": f"Failed to access reasoning model: {e}"}

            # Handle model unavailability
            if not reasoning_model:
                if self._single_model_mode and self._available_model_id:
                    # Fall back to the single available local model
                    logger.warning("[AgentKernel] Reasoning model unavailable, using fallback model")
                    try:
                        reasoning_model = self._model_router.models.get(self._available_model_id)
                    except Exception as e:
                        logger.error(f"[AgentKernel] Error accessing fallback model: {e}")
                        return {"error": f"Failed to access fallback model: {e}"}
                elif self._model_provider == "lmstudio":
                    # LM Studio is configured — reasoning_model stays None; the LM Studio
                    # inference block below handles it via localhost:1234.
                    logger.info(
                        "[AgentKernel] No local model loaded; delegating planning to LM Studio"
                    )
                elif self._vps_gateway:
                    # VPS Gateway is configured — no local model required.
                    # reasoning_model stays None; the VPS inference block below handles it.
                    logger.info(
                        "[AgentKernel] No local reasoning model; delegating planning to VPS Gateway"
                    )
                elif self._selected_reasoning_model and self._model_router:
                    # The user confirmed a model but it isn't in _model_router.models yet.
                    # Two sub-cases:
                    # A) Ollama model — ID contains ":" (e.g. "llama3.2:3b")
                    #    → handled in the Ollama inference block below.
                    #    NOTE: provider="local" means LFM local file, NOT Ollama.
                    #    Only ":" in the ID identifies an Ollama model.
                    # B) LFM HuggingFace model (provider="local", no ":" in ID)
                    #    → trigger load_models() now so the model dict is populated.
                    _sel = self._selected_reasoning_model
                    _is_ollama = ":" in _sel  # ONLY colon-format IDs go to Ollama
                    if _is_ollama:
                        logger.info(
                            f"[AgentKernel] Ollama model '{_sel}' selected; "
                            "will infer via localhost:11434"
                        )
                        # reasoning_model stays None — Ollama block below handles inference
                    else:
                        # LFM lazy-load path (provider="local", model file on disk)
                        logger.info(
                            f"[AgentKernel] LFM model '{_sel}' not loaded; triggering lazy load..."
                        )
                        try:
                            self._model_router.load_models()
                            reasoning_model = self._model_router.models.get(_sel)
                            if reasoning_model is None:
                                _all = list(self._model_router.models.values())
                                if _all:
                                    reasoning_model = _all[0]
                                    logger.info(
                                        "[AgentKernel] Exact model not found after lazy load; "
                                        f"using first available: {list(self._model_router.models.keys())[0]}"
                                    )
                        except Exception as _lazy_err:
                            logger.warning(f"[AgentKernel] Lazy load failed: {_lazy_err}")
                        if not reasoning_model:
                            return {
                                "error": (
                                    f"Local model '{_sel}' could not be loaded. "
                                    "Check that the model file exists in the models/ directory, "
                                    "or switch to an Ollama or VPS model in Settings → Configure."
                                )
                            }
                else:
                    return {
                        "error": (
                            "No inference backend configured. "
                            "Please go to Settings → Configure and select a Local, VPS, or OpenAI model."
                        )
                    }
            
            # Build planning prompt with personality and context
            system_prompt = ""
            if self._personality:
                try:
                    system_prompt = self._personality.get_system_prompt()
                except Exception as e:
                    logger.warning(f"[AgentKernel] Error getting system prompt: {e}")
            
            context_str = ""
            if context:
                context_str = "\n\nConversation Context:\n" + json.dumps(context[-5:], indent=2)
            
            planning_prompt = f"""{system_prompt}

You are analyzing a user request and creating an execution plan.

Task: {task_description}{context_str}

Create a structured plan with these steps:
1. Analyze what the user wants
2. Determine if tools are needed
3. Break down into actionable steps

Respond with a JSON object:
{{
    "analysis": "brief analysis of the request",
    "requires_tools": true/false,
    "steps": [
        {{
            "step": 1,
            "action": "description",
            "tool": "tool_name or null",
            "parameters": {{}}
        }}
    ]
}}"""
            
            # Use VPS Gateway for inference if available, otherwise use local model
            plan_response = None
            if self._vps_gateway:
                try:
                    logger.info("[AgentKernel] Using VPS Gateway for planning inference...")
                    try:
                        plan_response = asyncio.run(
                            self._vps_gateway.infer(
                                model=self._model_router.get_reasoning_model_id() or "lfm2-8b",
                                prompt=planning_prompt,
                                context={"conversation_history": context} if context else {},
                                params={"max_tokens": 512, "temperature": 0.2},
                                session_id=self.session_id
                            )
                        )
                        logger.info("[AgentKernel] VPS Gateway inference complete")
                    except RuntimeError as e:
                        if "already running" in str(e):
                            logger.warning("[AgentKernel] Event loop conflict — falling back to local model")
                            plan_response = None
                        else:
                            raise
                except TimeoutError:
                    logger.error("[AgentKernel] VPS Gateway inference timed out")
                    raise
                except Exception as e:
                    logger.warning(f"[AgentKernel] VPS Gateway inference failed, falling back to direct model: {e}")
                    plan_response = None
            
            # LM Studio inference (OpenAI-compatible local API at localhost:1234).
            # Triggered when provider == "lmstudio" and no prior backend produced a response.
            # Uses the openai Python client pointed at the LM Studio local server.
            if plan_response is None and self._model_provider == "lmstudio":
                try:
                    from openai import OpenAI as _OpenAI
                    _lms = _OpenAI(
                        base_url=f"{self._lmstudio_endpoint}/v1",
                        api_key="lm-studio",  # LM Studio accepts any non-empty string
                    )
                    _lms_resp = _lms.chat.completions.create(
                        model=self._selected_reasoning_model or "local-model",
                        messages=[{"role": "user", "content": planning_prompt}],
                        max_tokens=-1,
                        temperature=0.2,  # low temp = faster, more deterministic JSON
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    plan_response = _lms_resp.choices[0].message.content
                    logger.info(
                        f"[AgentKernel] LM Studio planning inference successful "
                        f"(model: {self._selected_reasoning_model}, endpoint: {self._lmstudio_endpoint})"
                    )
                except Exception as _lms_err:
                    logger.warning(f"[AgentKernel] LM Studio planning inference failed: {_lms_err}")

            # Ollama local inference — runs when the model ID contains ":" which is
            # the Ollama format (e.g. "llama3.2:3b", "mistral:7b", "kimi-k2.5:cloud").
            # NOTE: provider="local" means LFM local file — it does NOT go to Ollama.
            # Only colon-format IDs are Ollama models.
            if plan_response is None and self._selected_reasoning_model and (
                ":" in self._selected_reasoning_model
            ):
                try:
                    import requests as _req
                    _ollama_resp = _req.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": self._selected_reasoning_model,
                            "messages": [{"role": "user", "content": planning_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _ollama_resp.status_code == 200:
                        plan_response = (
                            _ollama_resp.json().get("message", {}).get("content", "")
                        )
                        logger.info(
                            f"[AgentKernel] Ollama planning inference successful "
                            f"(model: {self._selected_reasoning_model})"
                        )
                    else:
                        logger.warning(
                            f"[AgentKernel] Ollama returned HTTP {_ollama_resp.status_code} "
                            f"for model '{self._selected_reasoning_model}': "
                            f"{_ollama_resp.text[:200]}"
                        )
                except Exception as _ollama_err:
                    logger.warning(
                        f"[AgentKernel] Ollama planning inference failed: {_ollama_err}"
                    )

            # Fall back to direct model access if VPS Gateway not available or failed
            if plan_response is None:
                # If there is no local model to fall back to we cannot continue.
                if reasoning_model is None:
                    # Produce a context-aware error message.
                    _sel_err = self._selected_reasoning_model or ""
                    if self._vps_gateway:
                        _err_msg = (
                            "VPS inference failed and no local model is loaded. "
                            "Check your VPS connection or configure a local model in Settings."
                        )
                    elif ":" in _sel_err:
                        _model_name = _sel_err.split(":")[0]
                        _err_msg = (
                            f"Ollama model '{_sel_err}' is not available. "
                            f"Make sure Ollama is running and the model is pulled: "
                            f"ollama pull {_model_name}"
                        )
                    elif _sel_err:
                        _err_msg = (
                            f"Model '{_sel_err}' could not be loaded. "
                            "Check that the model file exists, or select a different model in Settings → Configure."
                        )
                    else:
                        _err_msg = (
                            "No inference backend configured. "
                            "Please go to Settings → Configure and select a Local, VPS, or OpenAI model."
                        )
                    return {"error": _err_msg}

                # Check timeout before loading model
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")

                # Load model if needed with error handling
                try:
                    if not reasoning_model.is_loaded():
                        logger.info("[AgentKernel] Loading reasoning model...")
                        reasoning_model.load()
                except Exception as e:
                    logger.error(f"[AgentKernel] Failed to load reasoning model: {e}")
                    return {"error": f"Model loading failed: {e}"}
                
                # Check timeout before inference
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")
                
                # Generate plan with error handling
                try:
                    plan_response = reasoning_model.generate(
                        planning_prompt,
                        max_tokens=-1,
                        temperature=0.2
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Model inference failed: {e}")
                    # Attempt to restart model
                    try:
                        logger.info("[AgentKernel] Attempting to restart reasoning model...")
                        reasoning_model.unload()
                        reasoning_model.load()
                        plan_response = reasoning_model.generate(
                            planning_prompt,
                            max_tokens=-1,
                            temperature=0.2
                        )
                        logger.info("[AgentKernel] Model restarted successfully")
                    except Exception as restart_error:
                        logger.error(f"[AgentKernel] Model restart failed: {restart_error}")
                        return {"error": f"Model crashed and restart failed: {restart_error}"}
            
            # Check timeout after inference
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")
            
            # Parse JSON response
            try:
                plan = json.loads(plan_response)
                logger.info(f"[AgentKernel] Plan generated with {len(plan.get('steps', []))} steps in {elapsed:.2f}s")
                return plan
            except json.JSONDecodeError:
                # Model returned free-form text rather than JSON.
                # Treat the entire response as the user-facing reply — do NOT use
                # "respond_to_user" as the action string because execute_step would
                # return that keyword verbatim to the frontend.
                logger.warning("[AgentKernel] Failed to parse plan as JSON, using raw text as response")
                _raw_text = self._strip_thinking(plan_response) if plan_response else "I'm not sure how to respond to that."
                return {
                    "analysis": _raw_text[:200],
                    "requires_tools": False,
                    "_raw_response": _raw_text,   # consumed by _synthesize_response
                    "steps": [
                        {
                            "step": 1,
                            "action": _raw_text,   # the ACTUAL text, not a keyword
                            "tool": None,
                            "parameters": {}
                        }
                    ]
                }
                
        except TimeoutError:
            logger.error(f"[AgentKernel] Planning timed out after {timeout_seconds}s")
            raise
        except Exception as e:
            error_msg = f"Error during task planning: {e}"
            logger.error(f"[AgentKernel] {error_msg}", exc_info=True)
            return {"error": error_msg}

    async def execute_plan(self, plan: Dict[str, Any]) -> List[Any]:
        """
        Execute a plan using lfm2.5-1.2b-instruct (execution model).

        Args:
            plan: Plan dictionary from plan_task()

        Returns:
            List of execution results for each step
        """
        results = []
        steps = plan.get("steps", [])

        logger.info(f"[AgentKernel] Executing plan with {len(steps)} steps...")

        for step in steps:
            try:
                result = await self.execute_step(step)
                results.append(result)
                logger.debug(f"[AgentKernel] Step {step.get('step')} completed")
            except Exception as e:
                error_result = {"error": f"Step {step.get('step')} failed: {e}"}
                results.append(error_result)
                logger.error(f"[AgentKernel] {error_result['error']}")

        return results

    async def execute_step(self, step: Dict[str, Any]) -> Any:
        """
        Execute a single plan step using execution model with timeout and error handling.
        
        Args:
            step: Step dictionary with action, tool, and parameters
            
        Returns:
            Execution result
            
        Raises:
            TimeoutError: If execution exceeds timeout
        """
        start_time = time.time()
        # 120s: matches plan_task — LM Studio 9B model can be slow on first token
        timeout_seconds = 120

        tool_name = step.get("tool")
        parameters = step.get("parameters", {})
        action = step.get("action", "")
        
        # If no tool specified, return the action as response
        if not tool_name:
            return {"response": action, "success": True}
        
        # Get execution model
        execution_model = None
        if self._model_router:
            try:
                # Use user-selected tool execution model if available
                if self._selected_tool_execution_model:
                    execution_model = self._model_router.models.get(self._selected_tool_execution_model)
                    if execution_model:
                        logger.info(f"[AgentKernel] Using user-selected tool execution model: {self._selected_tool_execution_model}")
                    else:
                        # Only fall back to default stub when Ollama/VPS won't handle it.
                        _sel_exec_check = self._selected_tool_execution_model
                        _ollama_exec_will_handle = ":" in _sel_exec_check
                        _vps_exec_will_handle = bool(self._vps_gateway)
                        _lmstudio_exec_will_handle = self._model_provider == "lmstudio"
                        if not _ollama_exec_will_handle and not _vps_exec_will_handle and not _lmstudio_exec_will_handle:
                            logger.warning(
                                f"[AgentKernel] Selected model {_sel_exec_check} unavailable, "
                                "falling back to default local execution model"
                            )
                            execution_model = self._model_router.get_execution_model()
                            if execution_model:
                                default_model_id = getattr(execution_model, 'model_id', 'unknown')
                                logger.info(f"[AgentKernel] Fallback: using default execution model {default_model_id}")
                        else:
                            _exec_dest = "LM Studio" if _lmstudio_exec_will_handle else ("Ollama" if _ollama_exec_will_handle else "VPS")
                            logger.info(
                                f"[AgentKernel] Exec model '{_sel_exec_check}' not in local cache — "
                                f"will route to {_exec_dest}"
                            )
                else:
                    # No model selected — use default execution model
                    execution_model = self._model_router.get_execution_model()
                    if execution_model:
                        default_model_id = getattr(execution_model, 'model_id', 'unknown')
                        logger.info(f"[AgentKernel] No model selected, using default tool execution model: {default_model_id}")
            except Exception as e:
                logger.error(f"[AgentKernel] Error getting execution model: {e}")
                return {"error": f"Failed to access execution model: {e}", "success": False}

        # Handle model unavailability
        if not execution_model:
            if self._single_model_mode and self._available_model_id:
                # Fall back to the single available local model
                logger.warning("[AgentKernel] Execution model unavailable, using fallback model")
                try:
                    execution_model = self._model_router.models.get(self._available_model_id)
                except Exception as e:
                    logger.error(f"[AgentKernel] Error accessing fallback model: {e}")
                    return {"error": f"Failed to access fallback model: {e}", "success": False}
            elif self._model_provider == "lmstudio":
                # LM Studio configured — execution_model stays None; LM Studio block handles it.
                logger.info(
                    "[AgentKernel] No local execution model; delegating execution to LM Studio"
                )
            elif self._vps_gateway:
                # VPS Gateway is configured — execution_model stays None; handled below.
                logger.info(
                    "[AgentKernel] No local execution model; delegating execution to VPS Gateway"
                )
            elif self._selected_tool_execution_model and self._model_router:
                _sel_exec = self._selected_tool_execution_model
                _is_ollama_exec = ":" in _sel_exec  # ONLY colon-format IDs are Ollama
                if _is_ollama_exec:
                    logger.info(
                        f"[AgentKernel] Ollama execution model '{_sel_exec}' selected; "
                        "will infer via localhost:11434"
                    )
                    # execution_model stays None — Ollama block below handles it
                else:
                    # LFM lazy-load for execution model
                    if not self._model_router.models:
                        try:
                            self._model_router.load_models()
                        except Exception as _le:
                            logger.warning(f"[AgentKernel] Lazy load (exec) failed: {_le}")
                    execution_model = self._model_router.models.get(_sel_exec)
                    if execution_model is None:
                        _all_exec = list(self._model_router.models.values())
                        if _all_exec:
                            execution_model = _all_exec[-1]  # prefer last (smallest/fastest)
                    if not execution_model:
                        return {"error": "Execution model not available", "success": False}
            else:
                return {"error": "Execution model not available", "success": False}
        
        try:
            # Create execution prompt
            execution_prompt = f"""Execute the following action:

Action: {action}
Tool: {tool_name}
Parameters: {json.dumps(parameters, indent=2)}

Provide the execution result."""
            
            # Use VPS Gateway for inference if available, otherwise use local model
            result_text = None
            if self._vps_gateway:
                try:
                    logger.info("[AgentKernel] Using VPS Gateway for execution inference...")
                    try:
                        result_text = asyncio.run(
                            self._vps_gateway.infer(
                                model=self._model_router.get_execution_model_id() or "lfm2.5-1.2b-instruct",
                                prompt=execution_prompt,
                                context={},
                                params={"max_tokens": 512, "temperature": 0.3},
                                session_id=self.session_id
                            )
                        )
                        logger.info("[AgentKernel] VPS Gateway execution inference complete")
                    except RuntimeError as e:
                        if "already running" in str(e):
                            logger.warning("[AgentKernel] Event loop conflict — falling back to local model")
                            result_text = None
                        else:
                            raise
                except TimeoutError:
                    logger.error("[AgentKernel] VPS Gateway execution timed out")
                    raise
                except Exception as e:
                    logger.warning(f"[AgentKernel] VPS Gateway execution inference failed, falling back to direct model: {e}")
                    result_text = None
            
            # LM Studio execution inference
            if result_text is None and self._model_provider == "lmstudio":
                try:
                    from openai import OpenAI as _OpenAI
                    _lms_exec = _OpenAI(
                        base_url=f"{self._lmstudio_endpoint}/v1",
                        api_key="lm-studio",
                    )
                    _lms_exec_resp = _lms_exec.chat.completions.create(
                        model=self._selected_tool_execution_model or "local-model",
                        messages=[{"role": "user", "content": execution_prompt}],
                        max_tokens=-1,
                        temperature=0.3,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    result_text = _lms_exec_resp.choices[0].message.content
                    logger.info("[AgentKernel] LM Studio execution inference successful")
                except Exception as _lms_exec_err:
                    logger.warning(f"[AgentKernel] LM Studio execution inference failed: {_lms_exec_err}")

            # Ollama local execution inference — only for colon-format model IDs.
            # provider="local" means LFM local file; it does NOT route to Ollama.
            if result_text is None and self._selected_tool_execution_model and (
                ":" in self._selected_tool_execution_model
            ):
                try:
                    import requests as _req
                    _ollama_exec_resp = _req.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": self._selected_tool_execution_model,
                            "messages": [{"role": "user", "content": execution_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _ollama_exec_resp.status_code == 200:
                        result_text = (
                            _ollama_exec_resp.json().get("message", {}).get("content", "")
                        )
                        logger.info(
                            f"[AgentKernel] Ollama execution inference successful "
                            f"(model: {self._selected_tool_execution_model})"
                        )
                    else:
                        logger.warning(
                            f"[AgentKernel] Ollama execution returned HTTP "
                            f"{_ollama_exec_resp.status_code}"
                        )
                except Exception as _ollama_exec_err:
                    logger.warning(
                        f"[AgentKernel] Ollama execution inference failed: {_ollama_exec_err}"
                    )

            # Fall back to direct model access if VPS Gateway not available or failed
            if result_text is None:
                # If VPS failed and there is no local execution model, cannot continue.
                if execution_model is None:
                    return {
                        "tool": tool_name,
                        "action": action,
                        "error": (
                            "VPS inference failed and no local execution model is loaded. "
                            "Check your VPS connection or configure a local model in Settings."
                        ),
                        "success": False,
                    }

                # Check timeout before loading model
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Execution timed out after {elapsed:.1f}s")

                # Load model if needed with error handling
                try:
                    if not execution_model.is_loaded():
                        logger.info("[AgentKernel] Loading execution model...")
                        execution_model.load()
                except Exception as e:
                    logger.error(f"[AgentKernel] Failed to load execution model: {e}")
                    return {
                        "tool": tool_name,
                        "action": action,
                        "error": f"Model loading failed: {e}",
                        "success": False
                    }
                
                # Check timeout before inference
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Execution timed out after {elapsed:.1f}s")
                
                # Generate execution response with error handling
                try:
                    result_text = execution_model.generate(
                        execution_prompt,
                        max_tokens=-1,
                        temperature=0.3
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Model inference failed: {e}")
                    # Attempt to restart model
                    try:
                        logger.info("[AgentKernel] Attempting to restart execution model...")
                        execution_model.unload()
                        execution_model.load()
                        result_text = execution_model.generate(
                            execution_prompt,
                            max_tokens=-1,
                            temperature=0.3
                        )
                        logger.info("[AgentKernel] Model restarted successfully")
                    except Exception as restart_error:
                        logger.error(f"[AgentKernel] Model restart failed: {restart_error}")
                        return {
                            "tool": tool_name,
                            "action": action,
                            "error": f"Model crashed and restart failed: {restart_error}",
                            "success": False
                        }
            
            # Check timeout after inference
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Execution timed out after {elapsed:.1f}s")
            
            # Handle tool execution errors
            if self._tool_bridge:
                try:
                    # Execute tool through tool bridge
                    tool_result = await self._tool_bridge.execute_tool(tool_name, parameters)
                    if "error" in tool_result:
                        logger.warning(f"[AgentKernel] Tool execution error: {tool_result['error']}")
                        return {
                            "tool": tool_name,
                            "action": action,
                            "error": tool_result["error"],
                            "success": False
                        }
                except Exception as e:
                    logger.error(f"[AgentKernel] Tool execution failed: {e}")
                    return {
                        "tool": tool_name,
                        "action": action,
                        "error": f"Tool execution failed: {e}",
                        "success": False
                    }
            
            logger.info(f"[AgentKernel] Step executed successfully in {elapsed:.2f}s")
            return {
                "tool": tool_name,
                "action": action,
                "result": result_text,
                "success": True
            }
            
        except TimeoutError:
            logger.error(f"[AgentKernel] Execution timed out after {timeout_seconds}s")
            raise
        except Exception as e:
            error_msg = f"Error executing step: {e}"
            logger.error(f"[AgentKernel] {error_msg}", exc_info=True)
            return {
                "tool": tool_name,
                "action": action,
                "error": error_msg,
                "success": False
            }
    
    def _generate_response(
        self, 
        user_message: str, 
        plan: Dict[str, Any], 
        execution_results: List[Any],
        context: List[Dict[str, Any]]
    ) -> str:
        """
        Generate final response based on plan and execution results.
        
        Args:
            user_message: Original user message
            plan: Generated plan
            execution_results: Results from execute_plan()
            context: Conversation context
            
        Returns:
            Final response text
        """
        # Check if any steps failed
        has_errors = any(
            isinstance(r, dict) and ("error" in r or not r.get("success", True))
            for r in execution_results
        )
        
        # Build response based on results
        if has_errors:
            error_messages = [
                r.get("error", "Unknown error")
                for r in execution_results
                if isinstance(r, dict) and "error" in r
            ]
            return f"I encountered some issues: {'; '.join(error_messages)}"
        
        # Extract successful results
        success_results = [
            r for r in execution_results
            if isinstance(r, dict) and r.get("success", False)
        ]
        
        if not success_results:
            return "I've processed your request."
        
        # Format response based on results
        if len(success_results) == 1:
            result = success_results[0]
            if "response" in result:
                return result["response"]
            elif "result" in result:
                return result["result"]
        
        # Multiple results - summarize
        summary_parts = []
        for r in success_results:
            if "result" in r:
                summary_parts.append(f"- {r.get('action', 'Action')}: {r['result'][:100]}")
            elif "response" in r:
                summary_parts.append(f"- {r['response'][:100]}")
        
        if summary_parts:
            return "I've completed your request:\n\n" + "\n".join(summary_parts)
        
        return "I've processed your request."
    
    def _synthesize_response(
        self,
        task: TaskContext,
        execution_results: List[Any]
    ) -> str:
        """
        Synthesize response using the brain model with tool results.
        
        This addresses Bug 2: The brain now sees the actual tool output
        before generating the final response.
        
        Args:
            task: TaskContext containing user message and plan
            execution_results: Results from execute_plan()
            
        Returns:
            Synthesized response from the brain model
        """
        # Short-circuit: if the plan already contains a raw free-form response
        # (model didn't output JSON), return it directly without a second model call.
        if task.plan and task.plan.get("_raw_response"):
            logger.info("[AgentKernel] Using raw plan response (no synthesis needed)")
            return task.plan["_raw_response"]

        # Get results summary for the brain
        results_summary = task.get_results_summary()

        # Build synthesis prompt for the brain
        synthesis_prompt = f"""User request: {task.user_message}

Tool execution results:
{results_summary}

Based on the tool results above, provide a natural response to the user's request.
If any tools failed, address those issues in your response.
"""
        
        try:
            # Get reasoning model for synthesis — only use local model if it's
            # actually loaded.  Do NOT call get_reasoning_model() as a fallback here:
            # that can return a broken/unloaded stub which echoes garbage like
            # "respond_to_user" back to the user verbatim.
            reasoning_model = None
            if self._model_router and self._selected_reasoning_model:
                reasoning_model = self._model_router.models.get(self._selected_reasoning_model)

            if reasoning_model:
                # Call the loaded local/LFM model for synthesis
                response = self._strip_thinking(reasoning_model.generate(synthesis_prompt))
                logger.info("[AgentKernel] Brain synthesized response with tool results context")
                return response

            # Try LM Studio synthesis
            _sel_synth = self._selected_reasoning_model or ""
            if not reasoning_model and self._model_provider == "lmstudio":
                try:
                    from openai import OpenAI as _OpenAI
                    _lms_synth = _OpenAI(
                        base_url=f"{self._lmstudio_endpoint}/v1",
                        api_key="lm-studio",
                    )
                    _lms_synth_resp = _lms_synth.chat.completions.create(
                        model=_sel_synth or "local-model",
                        messages=[{"role": "user", "content": synthesis_prompt}],
                        max_tokens=-1,
                        temperature=0.7,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    _synth_text = _lms_synth_resp.choices[0].message.content
                    if _synth_text:
                        logger.info("[AgentKernel] LM Studio synthesized response")
                        return self._strip_thinking(_synth_text)
                except Exception as _lms_synth_err:
                    logger.warning(f"[AgentKernel] LM Studio synthesis failed: {_lms_synth_err}")

            # Try Ollama if the selected model is an Ollama model (colon-format ID)
            if not reasoning_model and ":" in _sel_synth:
                try:
                    import requests as _req
                    _r = _req.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": _sel_synth,
                            "messages": [{"role": "user", "content": synthesis_prompt}],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _r.status_code == 200:
                        _synth_text = _r.json().get("message", {}).get("content", "")
                        if _synth_text:
                            logger.info("[AgentKernel] Ollama synthesized response")
                            return self._strip_thinking(_synth_text)
                except Exception as _ollama_synth_err:
                    logger.warning(f"[AgentKernel] Ollama synthesis failed: {_ollama_synth_err}")

            # Template-based fallback (no model available)
            logger.warning("[AgentKernel] No model for synthesis — using template response")
            return self._generate_response(task.user_message, task.plan, execution_results, task.conversation_history)

        except Exception as e:
            logger.error(f"[AgentKernel] Error in brain synthesis: {e}")
            return self._generate_response(task.user_message, task.plan, execution_results, task.conversation_history)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get agent status information.
        
        Returns:
            Status dictionary with:
            - ready: bool - if agent is ready to process requests
            - models_loaded: int - number of loaded models
            - total_models: int - total number of models
            - tool_bridge_available: bool - if tool bridge is available
            - model_status: dict - individual model status
            - single_model_mode: bool - if in fallback mode
            - error: str - initialization error if any
            - vps_gateway: dict - VPS Gateway status (enabled, available endpoints, health)
        """
        status = {
            "ready": False,
            "models_loaded": 0,
            "total_models": 0,
            "tool_bridge_available": False,
            "model_status": {},
            "single_model_mode": self._single_model_mode,
            "error": self._initialization_error
        }
        
        # Check model router status
        if self._model_router:
            all_status = self._model_router.get_all_models_status()
            status["model_status"] = all_status
            status["total_models"] = len(all_status)
            status["models_loaded"] = len(self._model_router.get_loaded_models())
            
            # Agent is ready if at least one model is available
            reasoning_model = self._model_router.get_reasoning_model()
            execution_model = self._model_router.get_execution_model()
            status["ready"] = reasoning_model is not None or execution_model is not None
        
        # Check tool bridge status
        if self._tool_bridge:
            try:
                bridge_status = self._tool_bridge.get_status()
                status["tool_bridge_available"] = bridge_status.get("available", False)
            except Exception as e:
                logger.warning(f"[AgentKernel] Failed to get tool bridge status: {e}")
        
        # Add VPS Gateway status
        if self._vps_gateway:
            try:
                vps_status = self._vps_gateway.get_status()
                status["vps_gateway"] = vps_status
                logger.debug(f"[AgentKernel] VPS Gateway status: {vps_status}")
            except Exception as e:
                logger.warning(f"[AgentKernel] Failed to get VPS Gateway status: {e}")
                status["vps_gateway"] = {
                    "enabled": False,
                    "error": str(e)
                }
        else:
            status["vps_gateway"] = {
                "enabled": False,
                "available_endpoints": 0
            }
        
        return status
    
    def clear_conversation(self) -> None:
        """Clear conversation history for the current session."""
        if self._conversation_memory:
            self._conversation_memory.clear()
            logger.info(f"[AgentKernel] Conversation cleared for session {self.session_id}")
    
    def get_conversation_context(self, max_messages: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get conversation context.
        
        Args:
            max_messages: Optional limit on number of messages
            
        Returns:
            List of message dictionaries
        """
        if self._conversation_memory:
            return self._conversation_memory.get_context(max_messages=max_messages)
        return []
    
    def update_personality(self, config: Dict[str, Any]) -> None:
        """
        Update personality configuration.
        
        Args:
            config: Dictionary containing identity fields
        """
        if self._personality:
            self._personality.load_from_config(config)
            logger.info("[AgentKernel] Personality configuration updated")
    
    # Maps legacy/local model names to their canonical VPS/API identifiers.
    # This allows saved settings that used local model path names to resolve
    # correctly against VPS available-model IDs without requiring a migration.
    _MODEL_ALIASES: Dict[str, str] = {
        # Legacy local model directory name → canonical ID (executor only; brain removed)
        "LFM2.5-1.2B-Instruct": "lfm2.5-1.2b-instruct",
        "executor":              "lfm2.5-1.2b-instruct",
        # NOTE: LFM2-8B-A1B / "brain" / "lfm2-8b" aliases are intentionally absent.
        # That model is not in use — removing the aliases prevents accidental routing.
    }

    def _normalize_model_id(self, model_id: Optional[str]) -> Optional[str]:
        """Translate legacy or local model IDs to their canonical identifiers."""
        if model_id is None:
            return None
        normalized = self._MODEL_ALIASES.get(model_id, model_id)
        if normalized != model_id:
            logger.debug(f"[AgentKernel] Model ID alias resolved: '{model_id}' -> '{normalized}'")
        return normalized

    def set_model_selection(
        self,
        reasoning_model: Optional[str] = None,
        tool_execution_model: Optional[str] = None,
        model_provider: Optional[str] = None,
    ) -> bool:
        """
        Set user-selected models for reasoning and tool execution.

        Args:
            reasoning_model:    Model ID for reasoning tasks (None to clear)
            tool_execution_model: Model ID for tool execution tasks (None to clear)
            model_provider:     Provider the user chose: "local" | "vps" | "api"

        Returns:
            True always — selections are stored unconditionally so that:
            • Ollama model IDs (e.g. "llama3.2:3b") aren't rejected because
              ModelRouter doesn't list them.
            • LFM local models aren't rejected when lazy loading is active and
              the models dict is still empty.
            Inference-time routing is responsible for surfacing "not available".
        """
        # Normalize aliases (e.g. "LFM2-8B-A1B" → "lfm2-8b")
        reasoning_model = self._normalize_model_id(reasoning_model)
        tool_execution_model = self._normalize_model_id(tool_execution_model)

        try:
            self._selected_reasoning_model = reasoning_model
            self._selected_tool_execution_model = tool_execution_model
            if model_provider:
                self._model_provider = model_provider

            logger.info(
                f"[AgentKernel] Model selection updated: reasoning={reasoning_model}, "
                f"tool_execution={tool_execution_model}, provider={self._model_provider}"
            )
            return True

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to set model selection: {e}")
            return False
    
    def get_model_selection(self) -> Dict[str, Optional[str]]:
        """
        Get current model selection.
        
        Returns:
            Dictionary with reasoning_model and tool_execution_model keys
        """
        return {
            "reasoning_model": self._selected_reasoning_model,
            "tool_execution_model": self._selected_tool_execution_model
        }
    
    def set_internet_access(self, enabled: bool) -> None:
        """
        Enable or disable agent internet access.
        
        This controls whether the agent can use web search and internet-based tools.
        It does NOT affect application connectivity to VPS or OpenAI services.
        
        Args:
            enabled: True to enable internet access, False to disable
        """
        self._internet_access_enabled = enabled
        logger.info(f"[AgentKernel] Agent internet access {'enabled' if enabled else 'disabled'}")
        logger.info("[AgentKernel] Note: This controls agent web search tools, not application connectivity")
    
    def get_internet_access(self) -> bool:
        """
        Get current internet access setting.
        
        Returns:
            True if internet access is enabled, False otherwise
        """
        return self._internet_access_enabled


# Singleton instance management
_agent_kernel_instances: Dict[str, AgentKernel] = {}


def get_agent_kernel(session_id: str = "default") -> AgentKernel:
    """
    Get or create an AgentKernel instance for a session.
    Auto-wires the memory interface (Pillar 4) when a new kernel is created.

    Args:
        session_id: Session identifier

    Returns:
        AgentKernel instance for the session
    """
    global _agent_kernel_instances

    if session_id not in _agent_kernel_instances:
        kernel = AgentKernel(session_id=session_id)

        # Auto-wire Pillar 4 (Memory) — connects episodic/semantic memory to every session
        try:
            from backend.memory import get_memory_interface
            memory = get_memory_interface()
            if memory is not None:
                kernel.set_memory_interface(memory)
                logger.info(f"[AgentKernel] Memory interface wired for session {session_id}")
        except Exception as e:
            logger.warning(f"[AgentKernel] Memory interface not available for session {session_id}: {e}")

        _agent_kernel_instances[session_id] = kernel

    return _agent_kernel_instances[session_id]


def cleanup_agent_kernel(session_id: str) -> None:
    """
    Remove the AgentKernel instance for a session and release its resources.

    Call this when a session expires (e.g., from session_manager.archive_inactive_sessions
    or IRISession.cleanup) to prevent unbounded growth of _agent_kernel_instances.

    Args:
        session_id: Session identifier whose kernel should be cleaned up
    """
    global _agent_kernel_instances
    kernel = _agent_kernel_instances.pop(session_id, None)
    if kernel is not None:
        try:
            # Shut down VPS Gateway if it was active
            if kernel._vps_gateway is not None:
                import asyncio
                try:
                    # Prefer the already-running loop (cleanup called from async context).
                    # Fall back to a fresh asyncio.run() if called from a sync context.
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(kernel.shutdown_vps_gateway())
                    except RuntimeError:
                        asyncio.run(kernel.shutdown_vps_gateway())
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[AgentKernel] Error during cleanup for session {session_id}: {e}")
        logger.info(f"[AgentKernel] Kernel cleaned up for session {session_id}")