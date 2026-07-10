#!/usr/bin/env python3
"""
Agent Kernel

Orchestrates the dual-LLM system with:
- lfm2-8b for reasoning and planning
- lfm2.5-1.2b-instruct for tool execution
- Inter-model communication and state management
- Model failure fallback to single-model mode
"""

from .model_conversation import ModelConversation
from .inter_model_communication import InterModelCommunicator
from .vps_gateway import VPSGateway, VPSConfig
from .personality import PersonalityManager
from .memory import ConversationMemory, TaskRecord
from .model_router import ModelRouter
from .tool_bridge import AgentToolBridge
from ..llm_service import llm as _llm
from . import streaming as _streaming
from typing import Any, Dict, Optional, List, Callable, Tuple
import json
import asyncio
import logging
import time
from dataclasses import dataclass, field
from backend.utils.observability import (
    TurnMetrics,
    loud_error,
    get_turn_id,
    broadcast_inference_event,
)

logger = logging.getLogger(__name__)

# ── DER Loop constants (spec: agent_loop_requirements.md Gap 11) ───────────
# Canonical values live in der_constants.py — re-exported here for spec
# compliance so module-level code that imports from agent_kernel finds them.
try:
    from backend.agent.der_constants import (
        DER_MAX_CYCLES,
        DER_MAX_VETO_PER_ITEM,
        DER_EMERGENCY_STOP,
        DER_TOKEN_BUDGETS,
        TRAILING_GAP_MIN,
    )
except Exception:
    DER_MAX_CYCLES = 40
    DER_MAX_VETO_PER_ITEM = 2
    DER_EMERGENCY_STOP = 200
    DER_TOKEN_BUDGETS: Dict[str, int] = {
        "implement": 40000,
        "debug": 30000,
        "research": 20000,
        "full": 50000,
        "quick_edit": 8000,
    }
    TRAILING_GAP_MIN = 2

try:
    from backend.agent.trailing_director import TrailingDirector as _TrailingDirector

    _TRAILING_DIRECTOR_AVAILABLE = True
except Exception:
    _TRAILING_DIRECTOR_AVAILABLE = False


@dataclass
class TaskContext:
    """
    Carries full context through the entire task pipeline.

    This is the single object that carries context from the user's message
    through planning, execution, and response synthesis. It prevents context
    loss at handoff points between the brain and executor models.
    """

    task_id: str  # unique per user message
    user_message: str  # original user request — never lost
    session_id: str
    conversation_history: List[Dict]  # snapshot of memory at task start
    conversation_id: str = "default"
    plan: Optional[Dict] = None  # brain's plan (set after planning)
    # accumulates as steps execute
    step_results: List[Dict] = field(default_factory=list)
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
                    summary_parts.append(
                        f"Step {i}: {tool_name} ({action}): {result_text[:200]}"
                    )

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
        session_id: str = "default",
        conversation_id: Optional[str] = None,
    ):
        """
        Initialize AgentKernel with dual-LLM coordination.

        Args:
            config_path: Path to agent configuration YAML
            session_id: Session identifier for WebSocket routing and Mycelium
            conversation_id: Conversation identifier for per-thread context.
                             If None, falls back to session_id.
        """
        self.config_path = config_path
        self.session_id = session_id
        self.conversation_id = conversation_id or session_id

        # Core components
        self._model_router: Optional[ModelRouter] = None
        self._vps_gateway: Optional[VPSGateway] = None
        self._conversation_memory: Optional[ConversationMemory] = None
        self._personality: Optional[PersonalityManager] = None
        self._tool_bridge: Optional[AgentToolBridge] = (
            None  # Will be initialized lazily
        )
        # For brain↔executor logging
        self._inter_model_communicator: Optional[InterModelCommunicator] = None

        # State management
        self._single_model_mode = False
        self._available_model_id: Optional[str] = None
        self._initialization_error: Optional[str] = None

        # Model selection (user-configurable dual-LLM)
        self._selected_reasoning_model: Optional[str] = None
        self._selected_tool_execution_model: Optional[str] = None
        # Provider the user selected in the UI.
        # "lmstudio"          → LM Studio OpenAI-compatible local API
        # "openai_compatible" → any OpenAI-compatible server (llamafile, vllm, ollama OpenAI mode, etc.)
        # "local"             → Ollama native API (http://localhost:11434)
        # "vps"               → VPS Gateway (self._vps_gateway)
        # "api"               → OpenAI / cloud API key
        # "uninitialized"     → not yet configured — wait for user to confirm settings
        self._model_provider: str = "uninitialized"

        # OpenAI-compatible endpoint — covers lmstudio, llamafile, vllm, or any custom server.
        # Set via configure_lmstudio() (legacy name kept) or configure_openai_compat().
        # Defaults to LM Studio's default port; overridden when the user saves settings.
        self._lmstudio_endpoint: str = "http://localhost:1234"

        # In-process `LocalModelManager` binding — non-None when iris_gateway
        # has loaded a model via the in-process path. `_get_lmstudio_client()`
        # checks this before creating a real HTTP client; when set AND the
        # provider is `iris_local`, inference goes through the manager's
        # `InProcessOpenAIAdapter` with zero network hops.
        self._inprocess_local_mgr: Any = None

        # Ollama native API endpoint (used when provider == "local").
        self._ollama_endpoint: str = "http://localhost:11434"

        # Cloud/remote API credentials (used when provider == "api").
        # Supports any OpenAI-compatible remote API: OpenAI, Groq, Together, OpenRouter, etc.
        self._api_key: str = ""
        self._api_base_url: str = "https://api.openai.com/v1"

        # Thinking extracted from the most recent _respond_direct call.
        # Set before returning so iris_gateway can include it in the text_response payload.
        self._pending_thinking: str = ""

        # VPS configuration (loaded from settings)
        self._vps_config: Optional[VPSConfig] = None

        # Internet access control (default: False to match UI default)
        self._internet_access_enabled: bool = False

        # Swarm compound collaboration (default: False — enabled via UI toggle)
        self._swarm_enabled: bool = False
        self._swarm_coordinator = None
        self._context_control_handler = None

        # ── Inference behaviour fields (wired from inference_mode card) ──
        self._thinking_style: str = "balanced"  # concise | balanced | thorough
        self._response_length: str = "medium"  # short | medium | long
        self._reasoning_effort: str = "balanced"  # fast | balanced | accurate
        self._tool_mode: str = "auto"  # auto | ask_first | disabled

        # Launcher mode: "personal" (default) or "developer"
        # Developer mode injects PROJECT.md into every system prompt so the
        # local agent has full codebase context and can modify source files.
        self._launcher_mode: str = "personal"
        # cached PROJECT.md content
        self._developer_context: Optional[str] = None

        # ── Model context window registry ──────────────────────────────────
        # Maps (provider, model_name_substring) → context window in tokens.
        # Used by resolve_context_window() so memory, conversation history,
        # and MCM budgets are never hardcoded — they adapt to the model.
        self._context_window_overrides: dict[str, int] = {}

        # Domain 4.5 — proactive skill creation.
        # Tracks how many times each normalized tool-name sequence (joined with "→")
        # has been used this session.  When a pattern hits the threshold, the agent
        # is prompted to codify it as a SKILL.md.
        self._session_tool_patterns: dict[str, int] = {}
        self._skill_trigger_threshold: int = 3
        # Patterns already prompted this session — avoid repeating the prompt.
        self._prompted_skill_patterns: set[str] = set()

        # Cached OpenAI client for LM Studio — created once, reused on every call.
        # Rebuilding _OpenAI() per-call recreates the full httpx connection pool,
        # adding unnecessary overhead on every message.  Invalidated in
        # configure_lmstudio() whenever the endpoint URL changes.
        self._lmstudio_client: Optional[Any] = None

        # Main event loop — captured during startup so background threads can
        # dispatch coroutines via run_coroutine_threadsafe.
        self._broadcast_loop: Optional[Any] = None

        # Initialize components
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all core components with error handling."""
        try:
            # Initialize Model Router with UNINITIALIZED mode (lazy loading)
            logger.info(
                "[AgentKernel] Initializing Model Router in UNINITIALIZED mode (lazy loading)..."
            )
            from .model_router import InferenceMode

            self._model_router = ModelRouter(
                self.config_path, inference_mode=InferenceMode.UNINITIALIZED
            )
            logger.info(
                "[AgentKernel] Model Router initialized - models will NOT be loaded automatically"
            )
            logger.info(
                "[AgentKernel] Models will be loaded only when user selects Local Model inference mode"
            )

            # In UNINITIALIZED mode, we don't have models yet
            logger.info(
                "[AgentKernel] Waiting for user to configure inference mode (Local/VPS/OpenAI)"
            )
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
        logger.info(
            "[AgentKernel] VPS Gateway deferred (lazy init — awaiting user VPS configuration)"
        )

        try:
            # Initialize Conversation Memory
            logger.info(
                f"[AgentKernel] Initializing Conversation Memory for session {self.session_id}..."
            )
            self._conversation_memory = ConversationMemory(
                session_id=self.session_id,
                max_messages=10,  # Default from requirements
            )
            logger.info("[AgentKernel] Conversation Memory initialized")

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Conversation Memory: {e}")
            self._initialization_error = (
                f"Conversation Memory initialization failed: {e}"
            )
            self._conversation_memory = None

        try:
            # Initialize Personality Manager
            logger.info("[AgentKernel] Initializing Personality Manager...")
            self._personality = PersonalityManager()
            logger.info("[AgentKernel] Personality Manager initialized")

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Personality Manager: {e}")
            self._initialization_error = (
                f"Personality Manager initialization failed: {e}"
            )
            self._personality = None

        try:
            # Initialize Inter-Model Communicator for brain↔executor logging (Bug 5 fix)
            logger.info("[AgentKernel] Initializing Inter-Model Communicator...")
            if self._model_router:
                model_conversation = ModelConversation()
                self._inter_model_communicator = InterModelCommunicator(
                    model_router=self._model_router, conversation=model_conversation
                )
                logger.info("[AgentKernel] Inter-Model Communicator initialized")
            else:
                logger.warning(
                    "[AgentKernel] Inter-Model Communicator not initialized: Model Router unavailable"
                )
        except Exception as e:
            logger.error(
                f"[AgentKernel] Failed to initialize Inter-Model Communicator: {e}"
            )
            self._inter_model_communicator = None

        # Tool Bridge will be initialized lazily when needed

        # Memory Foundation integration
        self._memory_interface: Optional[Any] = None

        # MCM Protocol Orchestrator — wired after set_memory_interface()
        self._mcm_orch = None

        # ── DER Loop components ────────────────────────────────────────────
        # DER_MAX_CYCLES / DER_MAX_VETO_PER_ITEM re-exported at module level
        # for spec compliance (Gap 11). Canonical values live in der_constants.
        self._task_classifier = None
        self._reviewer = None
        self._trailing_director = None
        self._mode_detector = None
        self._der_tokens_used: int = 0

        try:
            from backend.memory.mycelium.kyudo import TaskClassifier as _TC

            self._task_classifier = _TC()
            logger.info("[AgentKernel] TaskClassifier initialized (DER)")
        except Exception as _tc_err:
            logger.warning(f"[AgentKernel] TaskClassifier unavailable: {_tc_err}")

        try:
            from backend.agent.der_loop import Reviewer as _Reviewer

            # memory_interface wired later via set_memory_interface()
            self._reviewer = _Reviewer(adapter=self, memory_interface=None)
            logger.info("[AgentKernel] Reviewer initialized (DER)")
        except Exception as _rv_err:
            logger.warning(f"[AgentKernel] Reviewer unavailable: {_rv_err}")

        try:
            from backend.agent.trailing_director import TrailingDirector as _TD

            # memory_interface wired later via set_memory_interface()
            self._trailing_director = _TD(adapter=self, memory_interface=None)
            logger.info("[AgentKernel] TrailingDirector initialized (DER)")
        except Exception as _td_err:
            logger.warning(f"[AgentKernel] TrailingDirector unavailable: {_td_err}")

        try:
            from backend.agent.mode_detector import ModeDetector as _MD

            self._mode_detector = _MD()
            logger.info("[AgentKernel] ModeDetector initialized (DER)")
        except Exception as _md_err:
            logger.warning(f"[AgentKernel] ModeDetector unavailable: {_md_err}")

        logger.info("[AgentKernel] Initialization complete")

    def set_main_loop(self, loop: Any) -> None:
        """Capture the running event loop so background threads can dispatch broadcasts."""
        self._broadcast_loop = loop

    def set_memory_interface(self, memory_interface: Any) -> None:
        """
        Set the memory interface for the agent kernel.

        This is called after AgentKernel initialization to wire in
        the Memory Foundation system.

        Args:
            memory_interface: MemoryInterface instance from backend.memory
        """
        self._memory_interface = memory_interface
        # Wire Reviewer's memory reference now that it's available
        if self._reviewer is not None:
            self._reviewer.memory = memory_interface
        # Wire TrailingDirector's memory reference
        if self._trailing_director is not None:
            self._trailing_director.memory = memory_interface
        logger.info("[AgentKernel] Memory interface connected")
        try:
            from backend.agent.mcm_protocol import MCMOrchestrator

            self._mcm_orch = MCMOrchestrator(
                memory_interface=memory_interface,
                session_id=self.session_id,
                thread_id=getattr(self, "_thread_id", None),
            )
            logger.info("[AgentKernel] MCMOrchestrator initialized")
        except Exception as _mcm_err:
            logger.warning(f"[AgentKernel] MCMOrchestrator unavailable: {_mcm_err}")
            self._mcm_orch = None

    def clear_conversation(self, conversation_id: Optional[str] = None) -> None:
        """
        Clear the agent context for a conversation from the persistent store.
        Called on 'new conversation' or thread switch cleanup.

        Never raises — logs warning on failure.  The in-memory conversation
        memory still works for the current turn; subsequent turns start fresh.
        """
        _cid = conversation_id or self.conversation_id
        try:
            from backend.agent.conversation_context_store import get_context_store

            store = get_context_store()
            store.clear(_cid)
            logger.info(
                f"[AgentKernel] Cleared context for conversation {_cid}"
            )
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] clear_conversation({_cid}) failed: {exc}"
            )

    def save_context_to_store(self) -> None:
        """Persist current conversation context to the store (best-effort)."""
        try:
            from backend.agent.conversation_context_store import (
                get_context_store,
                ConversationContext,
            )

            store = get_context_store()
            ctx = ConversationContext(
                conversation_id=self.conversation_id,
                tokens_used=getattr(self, "_tokens_used", 0),
            )
            store.save(self.conversation_id, ctx)
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] save_context_to_store failed "
                f"for conv={self.conversation_id}: {exc}"
            )

    def restore_context_from_store(self) -> None:
        """Restore conversation context from the store (best-effort)."""
        try:
            from backend.agent.conversation_context_store import get_context_store

            store = get_context_store()
            ctx = store.get_or_restore(self.conversation_id)
            if ctx:
                self._tokens_used = ctx.tokens_used
                logger.info(
                    f"[AgentKernel] Restored context for conv={self.conversation_id} "
                    f"(tokens_used={ctx.tokens_used})"
                )
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] restore_context_from_store failed "
                f"for conv={self.conversation_id}: {exc}"
            )

    def infer(
        self,
        prompt: str,
        role: str = "EXECUTION",
        max_tokens: int = 200,
        temperature: float = 0.0,
    ):
        """
        Thin inference adapter used by Reviewer (and other DER components).
        Returns an object with a `.raw_text` attribute.
        Never raises — returns empty-text object on any backend failure.
        Routes through the same backend as the agentic loop.
        """

        class _InferResult:
            def __init__(self, raw_text: str):
                self.raw_text = raw_text

        try:
            # --- Path 1: OpenAI-compatible local servers (LM Studio, IRIS Local, etc.) ---
            if self._is_openai_compat():
                _lms = self._get_lmstudio_client()
                _resp = _lms.chat.completions.create(
                    model=self._selected_reasoning_model or "local-model",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
                return _InferResult(_resp.choices[0].message.content or "")

            # --- Path 2: Remote API providers (Cohere, OpenAI, Groq, etc.) ---
            # Unified via LiteLLM — single call, any provider.
            if self._is_api_provider():
                _model = self._selected_reasoning_model or "gpt-4o-mini"
                try:
                    _resp = _llm.complete(
                        model=_model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=max_tokens,
                        temperature=temperature,
                        stream=False,
                        api_key=self._api_key,
                        api_base=self._api_base_url,
                    )
                    return _InferResult(_resp.choices[0].message.content or "")
                except Exception as _llm_err:
                    logger.warning(
                        f"[AgentKernel.infer] LiteLLM call failed: {_llm_err}"
                    )
                    return _InferResult("")

            # --- Path 3: Ollama native API (provider == "local", model has ":") ---
            if self._selected_reasoning_model and ":" in self._selected_reasoning_model:
                import requests as _req

                _r = _req.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": self._selected_reasoning_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                    timeout=15,
                )
                if _r.status_code == 200:
                    return _InferResult(_r.json().get("message", {}).get("content", ""))

        except Exception as _inf_err:
            logger.warning(f"[AgentKernel.infer] inference failed: {_inf_err}")

        return _InferResult("")

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
                task=task, session_id=self.session_id
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
        tool_sequence: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        duration_ms: int = 0,
    ) -> None:
        """
        Store a task episode in memory.

        Args:
            task_summary: Brief task description
            full_content: Full conversation/task content
            outcome_type: Task outcome (success, failure, etc.)
            tool_sequence: List of tool calls made
            session_id: Session to attribute the episode to (falls back to self.session_id)
            duration_ms: Wall-clock time the task took in milliseconds
        """
        if self._memory_interface is None:
            return

        try:
            from backend.memory import Episode

            episode = Episode(
                session_id=session_id or self.session_id,
                task_summary=task_summary,
                full_content=full_content,
                tool_sequence=tool_sequence or [],
                outcome_type=outcome_type,
                duration_ms=duration_ms,
                source_channel="websocket",
                node_id="local",
                origin="local",
            )

            self._memory_interface.store_episode(episode)
            logger.debug(
                f"[AgentKernel] Stored episode for task: {task_summary[:50]}..."
            )

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
                logger.info(
                    "[AgentKernel] Initializing VPS Gateway async operations..."
                )
                await self._vps_gateway.initialize()
                logger.info("[AgentKernel] VPS Gateway async initialization complete")
            except Exception as e:
                logger.error(
                    f"[AgentKernel] Failed to initialize VPS Gateway async: {e}"
                )

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
                load_balancing_strategy=vps_config.get(
                    "load_balancing_strategy", "round_robin"
                ),
                protocol=vps_config.get("protocol", "rest"),
                offload_tools=vps_config.get("offload_tools", False),
            )

            # Only create VPSGateway when user has explicitly enabled it.
            # This prevents health-check loops on every reconnect when VPS is disabled.
            if self._vps_config.enabled and self._model_router:
                self._vps_gateway = VPSGateway(self._vps_config, self._model_router)
                logger.info(
                    f"[AgentKernel] VPS Gateway created: enabled={self._vps_config.enabled}, endpoints={len(self._vps_config.endpoints)}"
                )
            elif not self._vps_config.enabled:
                # VPS disabled — clear any existing gateway to stop health checks
                self._vps_gateway = None
                logger.info("[AgentKernel] VPS Gateway disabled by user config")
            else:
                logger.warning(
                    "[AgentKernel] Cannot configure VPS Gateway: Model Router unavailable"
                )

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to configure VPS Gateway: {e}")
            self._vps_config = VPSConfig(enabled=False)
            self._vps_gateway = None

    @staticmethod
    def _normalise_endpoint(endpoint: Optional[str]) -> str:
        """Strip trailing slash and trailing /v1 from any endpoint URL.

        Handles three common paste formats:
          http://localhost:1234        -> http://localhost:1234
          http://localhost:1234/       -> http://localhost:1234
          http://localhost:1234/v1     -> http://localhost:1234
          http://localhost:1234/v1/    -> http://localhost:1234
        None or empty string returns "".
        _get_lmstudio_client() always appends /v1 itself — never double-append.
        """
        if not endpoint:
            return ""
        ep = endpoint.rstrip("/")
        if ep.endswith("/v1"):
            ep = ep[:-3]
        return ep

    def configure_lmstudio(self, endpoint: str) -> None:
        """Store the OpenAI-compatible endpoint for inference routing.

        Named configure_lmstudio for backward compatibility but accepts any
        OpenAI-compatible server URL (LM Studio, llamafile, vllm, llama-server, etc.).
        """
        self._lmstudio_endpoint = self._normalise_endpoint(endpoint)
        self._lmstudio_client = None  # invalidate cached client — endpoint changed
        self._sync_context_window()
        logger.info(
            f"[AgentKernel] OpenAI-compatible endpoint configured: {self._lmstudio_endpoint}"
        )

    def configure_openai_compat(
        self, endpoint: Optional[str], provider_name: str = "openai_compatible"
    ) -> None:
        """Configure any OpenAI-compatible inference server.

        Passing endpoint=None resets the kernel to an uninitialized state (e.g. after
        model unload). Safe to call with None — never raises AttributeError.
        """
        self._lmstudio_endpoint = self._normalise_endpoint(endpoint)
        self._lmstudio_client = None
        self._model_provider = provider_name if endpoint else "uninitialized"
        if endpoint:
            logger.info(
                f"[AgentKernel] {provider_name} endpoint configured: {self._lmstudio_endpoint}"
            )
        else:
            logger.info("[AgentKernel] Endpoint cleared — kernel is uninitialized")

    def configure_ollama(self, endpoint: str) -> None:
        """Configure the Ollama native API endpoint (provider == 'local')."""
        self._ollama_endpoint = endpoint.rstrip("/")
        logger.info(
            f"[AgentKernel] Ollama endpoint configured: {self._ollama_endpoint}"
        )

    def configure_api(
        self, api_key: str, base_url: str = "https://api.openai.com/v1"
    ) -> None:
        """Configure remote API credentials (provider == 'api').

        Works with any OpenAI-compatible remote API:
        OpenAI, Groq, Together AI, OpenRouter, Mistral, Fireworks, etc.
        The base_url controls which service is called.
        """
        self._api_key = api_key
        self._api_base_url = base_url.rstrip("/")
        self._lmstudio_client = None  # invalidate cached client
        self._sync_context_window()
        logger.info(
            f"[AgentKernel] Remote API configured: base_url={self._api_base_url}"
        )

    # ── Context window resolution ──────────────────────────────────────────
    # Every model has a maximum context window.  Memory, conversation history,
    # and MCM budgets should be derived from it — never hardcoded.

    def _sync_context_window(self) -> None:
        """Propagate the resolved context window to memory config + peers."""
        token_budget = self.get_effective_token_budget()
        try:
            from backend.memory.config import update_context_size

            update_context_size(token_budget)
        except Exception as _err:
            logger.warning(
                f"[AgentKernel] Failed to sync context window to memory: {_err}"
            )

    # Known context windows (tokens).  Keyed by (provider, model_substring).
    # Substring match is case-insensitive; first match wins.
    _KNOWN_CONTEXT_WINDOWS: list[tuple[str, str, int]] = [
        # Cohere
        ("cohere", "command-r-plus", 128_000),
        ("cohere", "command-r", 128_000),
        ("cohere", "command-a", 256_000),
        ("cohere", "command", 8_192),
        # OpenAI
        ("openai", "gpt-4o", 128_000),
        ("openai", "gpt-4o-mini", 128_000),
        ("openai", "gpt-4-turbo", 128_000),
        ("openai", "gpt-4", 8_192),
        ("openai", "gpt-3.5", 16_385),
        # Groq
        ("groq", "llama-3.3-70b", 128_000),
        ("groq", "llama-3.1-70b", 128_000),
        ("groq", "llama-3.1-8b", 128_000),
        ("groq", "llama3-70b", 8_192),
        ("groq", "llama3-8b", 8_192),
        ("groq", "mixtral-8x7b", 32_768),
        ("groq", "gemma2-9b", 8_192),
        # DeepSeek
        ("deepseek", "deepseek-chat", 65_536),
        ("deepseek", "deepseek-coder", 16_384),
        # Mistral
        ("mistral", "mistral-large", 128_000),
        ("mistral", "mistral-medium", 32_000),
        ("mistral", "mistral-small", 32_000),
        ("mistral", "mixtral", 32_000),
        # OpenRouter — generic passthrough; use a conservative default
        ("openrouter", "", 32_000),
        # LM Studio / IRIS Local — common local models
        ("lmstudio", "lfm-2-8b", 32_768),
        ("lmstudio", "llama-3", 8_192),
        ("lmstudio", "llama-3.1", 128_000),
        ("lmstudio", "llama-3.2", 128_000),
        ("lmstudio", "mistral", 32_768),
        ("lmstudio", "qwen2.5", 32_768),
        ("lmstudio", "phi-3", 128_000),
        ("iris_local", "lfm-2-8b", 32_768),
        ("iris_local", "llama-3", 8_192),
        ("iris_local", "llama-3.1", 128_000),
        # Ollama — common local models
        ("local", "llama3.1", 128_000),
        ("local", "llama3", 8_192),
        ("local", "mistral", 32_768),
        ("local", "qwen2.5", 32_768),
        ("local", "phi3", 128_000),
        ("local", "gemma2", 8_192),
    ]

    def resolve_context_window(self) -> int:
        """Return the effective context window (tokens) for the current model.

        Priority:
          1. User override via _context_window_overrides
          2. Known registry lookup by (provider, model_name)
          3. Safe default (8k)
        """
        provider = self._model_provider or ""
        model = self._selected_reasoning_model or ""

        # 1. User override (set via confirm_card / model_selection)
        if model in self._context_window_overrides:
            return self._context_window_overrides[model]

        # 2. Registry lookup — case-insensitive substring match
        model_lower = model.lower().strip()
        for reg_provider, reg_substring, tokens in self._KNOWN_CONTEXT_WINDOWS:
            if reg_provider == provider and (
                not reg_substring or reg_substring in model_lower
            ):
                return tokens

        # 3. Fallback: try to detect from local_model_manager profiles
        try:
            from .local_model_manager import LocalModelManager

            mgr = LocalModelManager()
            for profile in mgr.profiles:
                if profile.id in model_lower or model_lower in profile.id:
                    return profile.n_ctx
        except Exception:
            pass

        # 4. Safe default — 8k for unknown models
        logger.info(
            f"[AgentKernel] No context window known for provider={provider} "
            f"model={model} — using default 8192"
        )
        return 8_192

    def get_effective_token_budget(self, fraction: float = 0.75) -> int:
        """Return the usable token budget as a fraction of the context window.

        We reserve 25% for the system prompt + tool definitions + response
        generation.  The fraction parameter lets callers override this.
        """
        return int(self.resolve_context_window() * fraction)

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

    # Providers that speak the OpenAI-compatible chat completions API.
    # When the user picks any of these, inference routes through _get_lmstudio_client()
    # using whatever endpoint they configured (LM Studio, llamafile, vllm, etc.).
    _OPENAI_COMPAT_PROVIDERS = frozenset(
        {
            "lmstudio",
            "openai_compatible",
            "llamafile",
            "vllm",
            "llamacpp_server",
            "koboldcpp",
            "textgen_webui",
            "ollama_openai",
            # IRIS-native local model server (llama-cpp-python / ik_llama.cpp on port 8082)
            "iris_local",
        }
    )

    def _is_openai_compat(self) -> bool:
        """Return True if the user-selected provider speaks the OpenAI chat API (local).

        Handles the common case where self._model_provider == "lmstudio" directly,
        as well as other OpenAI-compatible servers listed in _OPENAI_COMPAT_PROVIDERS.
        """
        # Direct LM Studio check: self._model_provider == "lmstudio" is the most
        # common OpenAI-compat provider — always handled by the openai client path.
        return self._model_provider in self._OPENAI_COMPAT_PROVIDERS

    def _is_api_provider(self) -> bool:
        """Return True if the user selected a remote API provider."""
        if self._model_provider == "api":
            return True
        # New named API providers (Cohere, DeepSeek, Anthropic, etc.)
        _api_providers = frozenset(
            {
                "opencodego",
                "cohere",
                "deepseek",
                "anthropic",
                "chutes",
                "cerebras",
                "lmstudio",
            }
        )
        return self._model_provider in _api_providers

    def configure_inprocess_local(self, mgr: Any) -> None:
        """Bind (or unbind) a `LocalModelManager` for in-process inference.

        Called by `iris_gateway` immediately after the manager loads a model
        via the in-process path. Once set, ``_get_lmstudio_client()`` returns
        the manager's ``InProcessOpenAIAdapter`` instead of a real openai
        HTTP client whenever the provider is ``iris_local`` — eliminating
        the port-8082 subprocess round-trip and the Windows hang that
        motivated this refactor.

        Pass ``None`` to clear the binding (called on unload).
        """
        self._inprocess_local_mgr = mgr
        # Invalidate any cached HTTP client so the next call picks up the
        # new adapter (or falls back to HTTP if mgr was cleared).
        self._lmstudio_client = None
        if mgr is None:
            logger.info("[AgentKernel] In-process local binding cleared")
        else:
            logger.info("[AgentKernel] In-process local binding active")

    def _get_lmstudio_client(self) -> Any:
        """Return an OpenAI-compatible client.

        Two paths:

        1. **In-process adapter** — when the provider is ``iris_local`` and
           a `LocalModelManager` has been bound via
           ``configure_inprocess_local()`` with a loaded model. Returns the
           manager's ``InProcessOpenAIAdapter``, which duck-types the
           openai client surface but routes straight to the in-process
           ``Llama`` instance. No HTTP, no subprocess, no port 8082.

        2. **Real openai HTTP client** — all other cases. Created once and
           cached so every inference call reuses the same httpx connection
           pool (saves ~5–20 ms per call on localhost).

        Invalidated by ``configure_lmstudio()`` / ``configure_inprocess_local()``
        when the binding changes.
        """
        # Path 1: in-process adapter when iris_local + manager loaded.
        mgr = getattr(self, "_inprocess_local_mgr", None)
        if mgr is not None and self._model_provider == "iris_local":
            adapter = mgr.get_inprocess_client()
            if adapter is not None:
                return adapter
            # Manager was bound but model isn't loaded → fall through to
            # HTTP path (which will 404 cleanly instead of silently hanging).

        # Path 2: cached real OpenAI HTTP client.
        if self._lmstudio_client is None:
            from openai import OpenAI as _OpenAI
            import httpx

            self._lmstudio_client = _OpenAI(
                base_url=f"{self._lmstudio_endpoint}/v1",
                api_key="lm-studio",
                timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10),
            )
            logger.info(
                f"[AgentKernel] Created LM Studio client → {self._lmstudio_endpoint}/v1"
            )
        return self._lmstudio_client

    def prewarm_lmstudio(self) -> None:
        """Send a minimal 1-token request to LM Studio so it loads the model into VRAM now.

        LM Studio cold-starts the model on the FIRST real inference request, which
        can take 20-30 seconds for a 9B-parameter model (VRAM load from SSD).
        Calling this immediately after the user confirms an LM Studio endpoint causes
        the model to load in the background, so it is already hot by the time the user
        sends their first message.

        Called from a daemon thread — never blocks the caller.
        """
        import threading

        def _do_prewarm() -> None:
            t0 = time.perf_counter()
            try:
                model = self._selected_reasoning_model or "local-model"
                logger.info(
                    f"[AgentKernel] Pre-warming LM Studio model '{model}' at {self._lmstudio_endpoint} …"
                )
                client = self._get_lmstudio_client()
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1,
                    temperature=0.0,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
                elapsed = time.perf_counter() - t0
                logger.info(
                    f"[AgentKernel] LM Studio pre-warm complete in {elapsed:.2f}s "
                    f"— model is hot and ready"
                )
            except Exception as e:
                elapsed = time.perf_counter() - t0
                # Non-fatal: LM Studio may not be running yet, or the model ID is wrong.
                # The first real user message will still work (just with the cold-start delay).
                logger.warning(
                    f"[AgentKernel] LM Studio pre-warm failed after {elapsed:.2f}s "
                    f"(non-fatal): {e}"
                )

        threading.Thread(
            target=_do_prewarm, daemon=True, name="lmstudio-prewarm"
        ).start()

    def set_launcher_mode(self, mode: str) -> None:
        """Set the launcher mode ('personal' or 'developer').

        In developer mode the agent's system prompt is augmented with
        PROJECT.md so the local model has full codebase context and can
        read/write source files, run git commands, and commit to
        ``iris-agent-dev``.
        """
        prev = self._launcher_mode
        self._launcher_mode = mode
        self._developer_context = None  # invalidate cached context
        logger.info(f"[AgentKernel] Launcher mode changed: {prev} → {mode}")

    def _get_developer_context(self) -> str:
        """Load and cache the PROJECT.md developer context string.

        Returns empty string if the file cannot be found (non-fatal).
        """
        if self._developer_context is not None:
            return self._developer_context
        import pathlib

        # Walk up from this file's location to find PROJECT.md
        here = pathlib.Path(__file__).parent
        for _ in range(6):
            candidate = here / "PROJECT.md"
            if candidate.exists():
                self._developer_context = candidate.read_text(encoding="utf-8")
                logger.info(f"[AgentKernel] Loaded developer context from {candidate}")
                return self._developer_context
            here = here.parent
        logger.warning(
            "[AgentKernel] PROJECT.md not found — developer context unavailable"
        )
        self._developer_context = ""
        return ""

    def _build_system_prompt(self) -> str:
        """Return the full system prompt for the current launcher mode.

        Personal mode: personality system prompt only.
        Developer mode: personality prompt + PROJECT.md appended so the
        agent always knows the codebase layout and must commit to
        ``iris-agent-dev``.
        """
        base = (
            "You are IRIS, a helpful, warm, and personable AI voice assistant. "
            "Respond naturally and concisely."
        )
        if self._personality:
            try:
                base = self._personality.get_system_prompt()
            except Exception:
                pass

        if self._launcher_mode == "developer":
            dev_ctx = self._get_developer_context()
            # Resolve active worktree path (set when /api/mode switches to developer)
            try:
                from backend.dev_worktree import get_active as _get_wt  # type: ignore

                _wt = _get_wt()
                worktree_path = _wt.get_path() if _wt else None
            except Exception:
                worktree_path = None

            worktree_block = (
                f"IRIS_SOURCE_DIR={worktree_path}\n"
                "You are working in an isolated copy of the IRIS source. "
                "Changes here do NOT affect the live codebase until the session "
                "ends and the user approves the diff in the Launcher.\n"
                if worktree_path
                else "You have full access to the IRISVOICE source code. "
                "Always commit your changes to the iris-agent branch. "
                "Never commit to main or IRISVOICEv.3.\n"
            )

            # [13.3] Spec-mandated developer context block (keep both)
            spec_block = (
                f"You are working in an isolated copy of the IRIS source at {worktree_path}.\n"
                "Changes here do NOT affect the live codebase until approved.\n"
                "Commit your changes; they will be reviewed in the Launcher diff view.\n"
                if worktree_path
                else ""
            )

            if dev_ctx:
                base = (
                    base
                    + "\n\n"
                    + spec_block
                    + "\n"
                    + "--- DEVELOPER MODE ACTIVE ---\n"
                    + worktree_block
                    + "\n"
                    + dev_ctx
                )
            else:
                base = (
                    base
                    + "\n\n"
                    + spec_block
                    + "\n"
                    + "--- DEVELOPER MODE ACTIVE ---\n"
                    + worktree_block
                )

        # Gap 4: EML cognitive state visible to LLM
        try:
            from backend.gateway.iris_ffi import ffi_calculate_eml

            _e, _x, _y = ffi_calculate_eml(self.session_id)
            _phase = "EXPLORE" if _e >= 1.5 else ("VERIFY" if _e < 1.0 else "BALANCE")
            base += (
                f"\n\n[COGNITIVE STATE: {_phase} | EML={_e:.2f} x={_x:.2f} y={_y:.2f}]"
            )
        except Exception:
            pass

        # Domain 19: Caducean DER Governor state visible to LLM
        # The Caducean governor tracks exploration-exploitation balance (ξ).
        # Phase mapping: ξ < 0.3 → EXPLOIT, 0.3 ≤ ξ < 0.7 → BALANCE, ξ ≥ 0.7 → EXPLORE
        try:
            from backend.gateway.iris_ffi import ffi_caducean_get_xi

            _xi = ffi_caducean_get_xi(self.session_id)
            _cad_phase = (
                "EXPLOIT" if _xi < 0.3 else ("EXPLORE" if _xi >= 0.7 else "BALANCE")
            )
            base += (
                f"\n[CADUCEAN GOVERNOR: {_cad_phase} | ξ={_xi:.2f}]"
                "\nYou are governed by the Caducean DER Governor, which balances "
                "exploration vs exploitation. When asked about your phase or state, "
                "report the Caducean phase and ξ value above."
            )
        except Exception:
            pass

        # Issue C.1 — structured speak/show response contract.
        # When the answer is long or contains structured data, the LLM returns
        # JSON so TTS reads only the short `speak` summary while the full
        # content renders visually.  Short conversational replies stay plain text.
        base += (
            "\n\n[RESPONSE FORMAT]\n"
            "When your answer is longer than about 3 sentences or contains "
            "structured data (tables, lists, diagrams, code, comparisons), "
            "respond with JSON:\n"
            '{"speak": "<2-3 sentence conversational summary of what you say>", '
            '"show": {"format": "markdown|html|table|diagram|text", '
            '"content": "<the full content>", '
            '"alternatives": ["<other formats you could render>"]}}\n'
            "The `speak` field is what the user HEARS via TTS — keep it brief "
            "and natural (1-3 sentences). The `show` field is what renders "
            "visually — put the detail there. For short conversational replies, "
            "respond with plain text (no JSON)."
        )

        return base

    # ------------------------------------------------------------------
    # Domain 4.5 — Proactive skill creation
    # ------------------------------------------------------------------

    def _maybe_trigger_skill_creation(
        self,
        tool_sequence: list,
        task_summary: str,
    ) -> None:
        """
        After each task, check whether any tool-name pattern has recurred
        enough times to warrant codifying as a skill.

        tool_sequence is the list of tool-call dicts recorded by the DER loop.
        Only sequences of 2+ tools are considered (single-tool calls are noise).
        When a pattern reaches self._skill_trigger_threshold uses this session,
        the agent is prompted once to create a SKILL.md for it.
        """
        if not tool_sequence or len(tool_sequence) < 2:
            return

        # Normalise: extract just tool names in order.
        names = []
        for tc in tool_sequence:
            if isinstance(tc, dict):
                name = (
                    tc.get("name")
                    or tc.get("tool")
                    or tc.get("function", {}).get("name", "")
                )
                if name:
                    names.append(name)
        if len(names) < 2:
            return

        pattern_key = " → ".join(names)

        self._session_tool_patterns[pattern_key] = (
            self._session_tool_patterns.get(pattern_key, 0) + 1
        )
        count = self._session_tool_patterns[pattern_key]

        if (
            count >= self._skill_trigger_threshold
            and pattern_key not in self._prompted_skill_patterns
        ):
            self._prompted_skill_patterns.add(pattern_key)
            prompt = (
                f"I noticed you used the tool sequence [{pattern_key}] "
                f"{count} times this session while working on tasks like "
                f'"{task_summary[:80]}". '
                "This pattern is a good candidate for a reusable skill. "
                "Please create a SKILL.md in backend/agent/skills/ that codifies "
                "this sequence so future sessions can invoke it by name instead of "
                "repeating the same steps. Name the skill after what it accomplishes."
            )
            logger.info(
                "[AgentKernel] Skill trigger fired for pattern: %s (used %d times)",
                pattern_key,
                count,
            )
            # Queue the skill-creation prompt as a follow-up message.
            # We use the internal message queue if available; otherwise log only.
            try:
                if hasattr(self, "_pending_follow_ups"):
                    self._pending_follow_ups.append(prompt)
                else:
                    self._pending_follow_ups = [prompt]
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers: thinking-token stripping, planning gate, direct response
    # ------------------------------------------------------------------

    def _needs_thinking(self, text: str) -> bool:
        """
        Return True only for messages that genuinely benefit from chain-of-thought
        reasoning.  Simple conversational questions and greetings skip thinking mode,
        cutting latency from ~30s to ~5s on Qwen3-9B.

        Respects the user's _thinking_style setting:
          concise   → never use thinking
          balanced  → heuristic trigger-based (default)
          thorough  → always use thinking
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

    def _needs_planning(self, text: str) -> bool:
        """
        Return True only when the message explicitly requests a tool-backed action.
        Conversational messages, greetings, and simple questions bypass planning entirely.

        Respects _tool_mode:
          auto        → heuristic trigger-based (default)
          ask_first   → never auto-plan; user must explicitly request tools
          disabled    → never plan, always direct response
        """
        mode = getattr(self, "_tool_mode", "auto")
        if mode == "disabled":
            return False
        if mode == "ask_first":
            # Only plan if message starts with explicit tool request prefix
            t = text.lower().strip()
            return t.startswith(("tool:", "run:", "execute:", "plan:"))

        t = text.lower()
        TOOL_TRIGGERS = [
            "search",
            "find",
            "look up",
            "look for",
            "open",
            "launch",
            "start app",
            "create",
            "write a file",
            "write file",
            "run",
            "execute",
            "install",
            "delete",
            "remove",
            "screenshot",
            "take a photo",
            "click",
            "automate",
            "schedule",
            "remind me",
            "set alarm",
            "set timer",
            "play music",
            "stop music",
            "download",
            "upload",
            "send email",
            "browse",
            "memory",
            "store",
            "recall",
            "remember",
            "save note",
            "read file",
            "list file",
            "web search",
            "fetch",
        ]
        return any(trigger in t for trigger in TOOL_TRIGGERS)

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

    # ── Token estimation ─────────────────────────────────────────────────────
    # Rough but fast: 1 token ≈ 4 chars. Real tokenizer adds <5% accuracy gain
    # but costs 10-50ms per call — not worth it for windowing decisions.
    _CHARS_PER_TOKEN: int = 4

    # Context budget for direct responses. Keeps the most recent history
    # within the model's 32k window, leaving ~8k for system prompt + response.
    # With episodic injection headroom this sits at ~20k chat tokens max.
    _DIRECT_CTX_BUDGET: int = (
        24_000  # tokens (supports 12k context + system + response)
    )

    def _count_tokens(self, messages: List[Dict]) -> int:
        return (
            sum(len(m.get("content") or "") for m in messages) // self._CHARS_PER_TOKEN
        )

    def _assemble_direct_context(self, text: str, context: List[Dict]) -> List[Dict]:
        """
        Build the message list for _respond_direct using all three memory layers
        from the Context Engineering spec (CONTEXT_ENGINEERING.md §1–3):

          Layer 1 — Mycelium coordinate graph  → already in system_prompt via
                                                  _build_system_prompt()
          Layer 2 — Episodic store             → injected here as memory block
          Layer 3 — Working memory / history   → token-aware full context, NOT
                                                  a hard-capped roll window

        The result is unlimited effective memory: the agent sees all context
        that fits in the budget. When history exceeds the budget, the oldest
        messages are trimmed — but episodic summaries from Mycelium still carry
        the gist of older sessions forward (Layer 2).

        Design rules (from spec):
          • Never drop the current user turn
          • First non-system message must be "user" (Qwen3 / most models)
          • Episodic block is a system-adjacent user↔assistant exchange so it
            doesn't break the alternating pattern
        """
        system_prompt = self._build_system_prompt()

        # ── Layer 2: episodic injection ───────────────────────────────────
        episodic_prefix: List[Dict] = []
        try:
            if self._memory_interface is not None and hasattr(
                self._memory_interface, "episodic"
            ):
                ep_ctx = self._memory_interface.episodic.assemble_episodic_context(text)
                if ep_ctx and ep_ctx.strip():
                    # Inject as a pseudo-exchange so the message pattern stays
                    # [system, user, assistant, user, assistant, …, user]
                    episodic_prefix = [
                        {
                            "role": "user",
                            "content": f"<memory>\n{ep_ctx.strip()}\n</memory>",
                        },
                        {
                            "role": "assistant",
                            "content": "Understood — I have that context.",
                        },
                    ]
        except Exception as _ep_exc:
            loud_error(_ep_exc, "episodic.assemble_episodic_context")

        # ── Layer 3: Option B — DB-backed semantic context (Pacman retrieval) ──
        # Instead of a blind rolling-window crop, we retrieve the most relevant
        # conversation fragments stored by fragment_and_store().  Falls back to
        # the plain rolling window when no chunks exist yet (first turn, fresh DB).
        #
        # Recency anchor: always keep the last _RECENCY_TURNS raw turns so the
        # model can follow short-term conversational flow regardless of relevance.
        _RECENCY_TURNS = 8

        sys_tokens = len(system_prompt) // self._CHARS_PER_TOKEN
        ep_tokens = self._count_tokens(episodic_prefix)
        current_tokens = len(text) // self._CHARS_PER_TOKEN

        # ── 3a: semantic chunk retrieval from DB ──────────────────────────
        chunk_prefix: List[Dict] = []
        try:
            if (
                self._memory_interface is not None
                and hasattr(self._memory_interface, "episodic")
                and hasattr(self._memory_interface.episodic, "retrieve_context_chunks")
            ):
                _chunks = self._memory_interface.episodic.retrieve_context_chunks(
                    query=text,
                    session_id=getattr(self, "session_id", None),
                    limit=6,
                    min_similarity=0.25,
                )
                if _chunks:
                    chunk_text = "\n---\n".join(_chunks)
                    # Inject as a pseudo-exchange so role alternation stays valid
                    chunk_prefix = [
                        {
                            "role": "user",
                            "content": f"<context_memory>\n{chunk_text}\n</context_memory>",
                        },
                        {
                            "role": "assistant",
                            "content": "Understood — I have those context fragments.",
                        },
                    ]
        except Exception as _ch_exc:
            loud_error(_ch_exc, "episodic.retrieve_context_chunks")

        chunk_tokens = self._count_tokens(chunk_prefix)
        budget_for_history = (
            self._DIRECT_CTX_BUDGET
            - sys_tokens
            - ep_tokens
            - chunk_tokens
            - current_tokens
        )

        # ── 3b: recency anchor — last N raw turns ─────────────────────────
        history = list(context)
        # Remove current user turn from tail if already appended
        if (
            history
            and history[-1].get("role") == "user"
            and history[-1].get("content") == text
        ):
            history = history[:-1]

        if chunk_prefix:
            # DB has relevant chunks: only keep a small recency window
            recent = (
                history[-_RECENCY_TURNS:]
                if len(history) > _RECENCY_TURNS
                else list(history)
            )
            recent_tokens = self._count_tokens(recent)
            while recent and recent_tokens > max(budget_for_history, 0):
                removed_item = recent.pop(0)
                recent_tokens -= (
                    len(removed_item.get("content") or "") // self._CHARS_PER_TOKEN
                )
            while recent and recent[0].get("role") != "user":
                recent.pop(0)
            history_block = recent
        else:
            # No chunks yet (first message / empty DB): full rolling window fallback
            history_tokens = self._count_tokens(history)
            while history and history_tokens > max(budget_for_history, 0):
                removed_item = history.pop(0)
                history_tokens -= (
                    len(removed_item.get("content") or "") // self._CHARS_PER_TOKEN
                )
            while history and history[0].get("role") != "user":
                history.pop(0)
            history_block = history

        # ── Assemble final message list ───────────────────────────────────
        messages: List[Dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(episodic_prefix)  # Layer 2: episodic summaries
        messages.extend(chunk_prefix)  # Layer 3a: semantic DB chunks
        messages.extend(history_block)  # Layer 3b: recency anchor

        # Ensure the list ends on the current user turn
        if (
            not messages
            or messages[-1].get("content") != text
            or messages[-1].get("role") != "user"
        ):
            messages.append({"role": "user", "content": text})

        # ── Telemetry: log context assembly metrics ─────────────────────
        try:
            _sys_chars = len(system_prompt) if system_prompt else 0
            _ep_chars = sum(len(m.get("content", "")) for m in episodic_prefix)
            _ck_chars = sum(len(m.get("content", "")) for m in chunk_prefix)
            _hist_chars = sum(len(m.get("content", "")) for m in history_block)
            _total_chars = _sys_chars + _ep_chars + _ck_chars + _hist_chars + len(text)
            _total_msgs = len(messages)
            from backend.core.logging_config import get_agent_logger

            get_agent_logger().info(
                "Context assembly",
                total_chars=_total_chars,
                total_messages=_total_msgs,
                sys_chars=_sys_chars,
                episodic_chars=_ep_chars,
                chunk_chars=_ck_chars,
                history_chars=_hist_chars,
                current_turn=len(text),
                episodic_count=len(episodic_prefix),
                chunk_count=len(chunk_prefix),
                history_turns=len(history_block),
            )
        except Exception:
            pass

        # ── MCM Protocol: MITO tag injection + DCP prune ─────────────────
        if self._mcm_orch is not None:
            try:
                messages = self._mcm_orch.pre_call(messages, text)
            except Exception:
                pass  # MCM failure never blocks the response

        return messages

    @staticmethod
    def _sanitize_messages(messages: List[Dict]) -> List[Dict]:
        """
        Sanitize message list before sending to model API.

        Removes:
          - Messages whose content starts with '[IRIS error:' (garbage accumulation)
          - Non-system messages with empty/whitespace-only content
          - Consecutive same-role non-system messages (breaks API alternation rules)

        Ensures the list starts with system (or inserts an empty one) and ends
        with the current user turn.
        """
        # 1. Strip messages with error content
        cleaned = [
            m for m in messages if not m.get("content", "").startswith("[IRIS error:")
        ]

        # 2. Remove truly empty non-system messages
        cleaned = [
            m
            for m in cleaned
            if m.get("role") == "system" or (m.get("content") or "").strip()
        ]

        # 3. Collapse consecutive same-role non-system messages
        sanitized: List[Dict] = []
        for m in cleaned:
            if m["role"] == "system":
                sanitized.append(m)
            elif not sanitized:
                # First non-system message is fine
                sanitized.append(m)
            elif sanitized[-1]["role"] == "system":
                # After system, any role is fine
                sanitized.append(m)
            elif sanitized[-1]["role"] != m["role"]:
                # Alternating roles — OK
                sanitized.append(m)
            # else: skip consecutive same-role non-system (keeps first of run)

        # 4. Ensure first message is system
        if sanitized and sanitized[0]["role"] != "system":
            sanitized.insert(0, {"role": "system", "content": ""})

        return sanitized

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
    ) -> str:
        """
        Respond directly to the user without planning or tool execution.
        Routes to the right backend provider based on IRISConfig routing mode
        or auto-detected provider type.

        Context uses all three memory layers (see CONTEXT_ENGINEERING.md):
          Layer 1: Mycelium coordinates → system prompt
          Layer 2: Episodic store       → memory block prefix
          Layer 3: Full history         → token-aware (not a hard roll window)

        Returns: response text string.
        """
        messages = self._assemble_direct_context(text, context)
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

        # === Config-driven dispatch: SINGLE_API ===
        if config_mode == "SINGLE_API":
            # Always load credentials and model from config when in SINGLE_API mode.
            # _api_base_url defaults to "https://api.openai.com/v1" (non-empty),
            # so a bare truthiness check would skip loading the config URL.
            # The config URL always takes precedence when available.
            if config:
                if config.inference.api_base_url:
                    self._api_base_url = config.inference.api_base_url
                if config.inference.api_key:
                    self._api_key = config.inference.api_key
                if config.inference.reasoning_model:
                    self._selected_reasoning_model = config.inference.reasoning_model
            response_text, thinking_text = self._dispatch_api(
                messages,
                _max_tokens,
                _temperature,
                _reasoning_effort_val,
                chunk_callback=chunk_callback,
                reasoning_callback=reasoning_callback,
            )
            self._pending_thinking = thinking_text
            return response_text

        # === Config-driven dispatch: SINGLE_LOCAL ===
        if config_mode == "SINGLE_LOCAL":
            response_text, thinking_text = self._dispatch_inprocess(
                messages,
                _max_tokens,
                _temperature,
                chunk_callback=chunk_callback,
                reasoning_callback=reasoning_callback,
            )
            self._pending_thinking = thinking_text
            return response_text

        # === Auto mode: per-provider detection ===
        sel = self._selected_reasoning_model or "local-model"

        # LM Studio (OpenAI-compatible)
        if self._is_openai_compat():
            use_thinking = self._needs_thinking(text)
            response_text, thinking_text = self._dispatch_openai_compat(
                messages,
                _max_tokens,
                _temperature,
                _reasoning_effort_val,
                chunk_callback=chunk_callback,
                reasoning_callback=reasoning_callback,
            )
            self._pending_thinking = thinking_text
            # Timing is handled inside _dispatch_openai_compat
            return response_text

        # Remote API provider (OpenAI, Groq, Cohere, etc.)
        if self._is_api_provider():
            response_text, thinking_text = self._dispatch_api(
                messages,
                _max_tokens,
                _temperature,
                _reasoning_effort_val,
                chunk_callback=chunk_callback,
                reasoning_callback=reasoning_callback,
            )
            self._pending_thinking = thinking_text
            return response_text

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
            reasoning_model = self._model_router.models.get(
                self._selected_reasoning_model
            )
        if not reasoning_model and self._model_router:
            reasoning_model = self._model_router.get_reasoning_model()
        if reasoning_model:
            reply = reasoning_model.generate(text)
            thinking, clean = self._parse_thinking(reply)
            self._pending_thinking = thinking
            return clean

        # No provider matched
        logger.error(
            f"[AgentKernel] _respond_direct: no model provider matched for session "
            f"'{self.session_id}' (provider={self._model_provider!r}, "
            f"model={self._selected_reasoning_model!r}). "
            "Was set_model_selection() called for this session?"
        )
        return (
            "I'm not connected to a language model yet. "
            "Please select a model in IRIS settings and try again."
        )

    # ------------------------------------------------------------------ #
    # Dispatch methods
    # ------------------------------------------------------------------ #

    def _dispatch_api(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        reasoning_effort: str = "balanced",
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, str]:
        """Remote API provider — direct httpx streaming (Chutes, OpenAI, etc.).

        Uses httpx directly instead of _llm.complete() to avoid thread-pool hangs.
        Returns (response_text, thinking_text).

        Raises RuntimeError on API errors — no silent error swallowing.
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
                "No reasoning model configured. Set a model in Settings → "
                "Model Selection (e.g. Cerebras gemma-4-31b) before sending messages."
            )

        _url = f"{_api_base.rstrip('/')}/chat/completions"
        _headers = {
            "Authorization": f"Bearer {_api_key}",
            "Content-Type": "application/json",
        }
        _body = {
            "model": sel,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # ── Telemetry: log API request shape (not content) ──────────
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

            with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                with _client.stream(
                    "POST", _url, headers=_headers, json={**_body, "stream": True}
                ) as _resp:
                    if _resp.status_code != 200:
                        # Streaming response: reading .text raises ResponseNotRead
                        # because httpx hasn't consumed the body yet. Read the first
                        # chunk manually for the error detail.
                        try:
                            _first = next(_resp.iter_bytes(), b"")
                            _err_detail = _first[:200].decode("utf-8", errors="replace")
                        except Exception:
                            _err_detail = "(could not read error body)"
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

                        # Reasoning content — field name varies by provider
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

            reasoning_text = "".join(_reasoning_buf)
            if reasoning_callback:
                reasoning_callback("")  # end marker
            if chunk_callback:
                chunk_callback("")  # force-flush

            # Reasoning fallback: some models return answer in reasoning_content
            # with empty content. When using reasoning fallback, skip _parse_thinking
            # since the reasoning IS the answer (preamble stripping would kill it).
            if not full_reply.strip() and reasoning_text.strip():
                _elapsed = _perf_t.perf_counter() - _t0
                _ctok = max(1, len(reasoning_text) // 4)
                _ptok = sum(len(m.get("content", "")) for m in messages) // 4
                self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)
                return reasoning_text, reasoning_text

            thinking, clean = self._parse_thinking(full_reply)
            _elapsed = _perf_t.perf_counter() - _t0
            _ctok = max(1, len(full_reply) // 4)
            _ptok = sum(len(m.get("content", "")) for m in messages) // 4
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)
            return clean or "(I see.)", thinking

        else:
            # Non-streaming path
            with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                _resp = _client.post(_url, headers=_headers, json=_body)
                if _resp.status_code != 200:
                    raise RuntimeError(
                        f"API returned {_resp.status_code}: {_resp.text[:200]}"
                    )
                _result = _resp.json()
                _reply = (
                    _result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

            if not _reply:
                raise RuntimeError("Empty response from API")

            # Record usage with real API tokens if available
            _elapsed = _perf_t.perf_counter() - _t0 if '_t0' in dir() else 0
            _usage = _result.get("usage", {})
            _ptok = _usage.get("prompt_tokens", max(1, sum(len(m.get("content", "")) for m in messages) // 4))
            _ctok = _usage.get("completion_tokens", max(1, len(_reply) // 4))
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed)

            # ── FIX (session 154): Invoke chunk_callback on non-streaming path ──
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
            return clean or "(I see.)", thinking

    def _dispatch_openai_compat(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        reasoning_effort: str = "balanced",
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, str]:
        """LM Studio / local OpenAI-compatible endpoint — direct httpx streaming.

        Similar to _dispatch_api but uses _lmstudio_endpoint and LM Studio's
        Extra-body template hints. Returns (response_text, thinking_text).

        Raises RuntimeError on API errors — no silent error swallowing.
        """
        import json as _json
        import time as _perf_t
        import httpx as _httpx

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

        # LM Studio-specific extra_body for thinking template hints
        _body["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": use_thinking}
        }

        if chunk_callback:
            # Streaming path
            _t0 = _perf_t.perf_counter()
            full_reply = ""
            _reasoning_buf: List[str] = []

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
                    raise RuntimeError(f"Could not connect to LM Studio at {_api_base}")

                with _resp as _stream:
                    if _stream.status_code != 200:
                        raise RuntimeError(
                            f"LM Studio returned {_stream.status_code}: {_stream.text[:200]}"
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

            reasoning_text = "".join(_reasoning_buf)
            if reasoning_callback:
                reasoning_callback("")
            if chunk_callback:
                chunk_callback("")

            if not full_reply.strip() and reasoning_text.strip():
                return reasoning_text, reasoning_text

            thinking, clean = self._parse_thinking(full_reply)
            return clean or "(I see.)", thinking

        else:
            # Non-streaming path
            with _httpx.Client(timeout=_httpx.Timeout(60.0), verify=get_ssl_context()) as _client:
                for _try_url in [_url, _url_v1]:
                    try:
                        _resp = _client.post(
                            _try_url,
                            headers={"Content-Type": "application/json"},
                            json=_body,
                        )
                        if _resp.status_code < 500:
                            break
                    except Exception:
                        continue
                else:
                    raise RuntimeError(f"Could not connect to LM Studio at {_api_base}")

                if _resp.status_code != 200:
                    raise RuntimeError(
                        f"LM Studio returned {_resp.status_code}: {_resp.text[:200]}"
                    )
                _result = _resp.json()
                _reply = (
                    _result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

            if not _reply:
                raise RuntimeError("Empty response from LM Studio")

            # Record usage with real API tokens if available
            _usage = _result.get("usage", {})
            _ptok = _usage.get("prompt_tokens", max(1, sum(len(m.get("content", "")) for m in messages) // 4))
            _ctok = _usage.get("completion_tokens", max(1, len(_reply) // 4))
            _elapsed_ns = _perf_t.perf_counter() - _t0 if '_t0' in dir() else 0
            self._broadcast_inference_event(sel, _ptok, _ctok, _elapsed_ns)

            # ── FIX (session 154): Invoke chunk_callback on non-streaming path ──
            # Same fix as _dispatch_api: when LM Studio returns the full reply
            # in one shot, chunk_callback is never called, so the TTS
            # sentence_queue only receives the None sentinel. Send the full
            # reply as a single chunk, then a force-flush ("").
            if chunk_callback and _reply:
                chunk_callback(_reply)
                chunk_callback("")  # force-flush end-of-stream

            thinking, clean = self._parse_thinking(_reply)
            return clean or "(I see.)", thinking

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

        # ── FIX (session 154): Invoke chunk_callback on non-streaming path ──
        # Local in-process models generate the full reply at once. Without
        # this call, the TTS pipeline never sees the response text.
        if chunk_callback and reply:
            chunk_callback(reply)
            chunk_callback("")  # force-flush end-of-stream

        thinking, clean = self._parse_thinking(reply)
        return clean or "(I see.)", thinking

    # Word count above which we consider a reply "long" for TTS purposes.
    # Only applied to DOCUMENT-like content; conversational replies are always spoken in full.
    _SPOKEN_WORD_LIMIT: int = 40
    # Maximum spoken word count for document summaries (hard cap).
    _SPOKEN_MAX_WORDS: int = 80

    @staticmethod
    def _is_document_content(text: str) -> bool:
        """Heuristic: True if *text* looks like a document/code excerpt rather than
        a conversational reply.  Document content gets summarised for TTS;
        conversational replies are spoken verbatim.
        """
        import re

        lines = text.splitlines()
        # Markdown headings (# / ## / etc.)
        if any(re.match(r"^#{1,6}\s", ln) for ln in lines):
            return True
        # Fenced code blocks (at least one opening fence)
        if text.count("```") >= 2:
            return True
        # Three or more bullet / numbered list items
        list_items = sum(1 for ln in lines if re.match(r"^\s*[-*•]\s|^\s*\d+\.\s", ln))
        if list_items >= 3:
            return True
        # Long, dense multi-paragraph text (>10 non-empty lines, avg >8 words/line)
        non_empty = [ln for ln in lines if ln.strip()]
        if len(non_empty) > 10:
            avg_words = sum(len(ln.split()) for ln in non_empty) / len(non_empty)
            if avg_words > 8:
                return True
        return False

    # ── Tool definitions for OpenAI-compatible function calling ─────────────

    def _get_openai_tools(self) -> List[Dict]:
        """Convert tool_bridge tool list to OpenAI-compatible function-calling format.

        Each entry becomes:
          {"type": "function", "function": {"name": …, "description": …, "parameters": {…}}}
        """
        if not self._tool_bridge:
            # Lazy-initialize the tool bridge on first access.
            # initialize() is async, so we create it as a background task
            # that runs once.  Tools from _tools dict are available immediately;
            # the async initialization sets up MCP/server connections.
            try:
                from backend.agent.tool_bridge import get_agent_tool_bridge

                self._tool_bridge = get_agent_tool_bridge()
                if not self._tool_bridge._initialized:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._tool_bridge.initialize())
                    except RuntimeError:
                        # No running event loop — run synchronously
                        asyncio.run(self._tool_bridge.initialize())
                logger.info("[AgentKernel] Tool bridge lazy-initialized")
            except Exception as e:
                logger.warning(f"[AgentKernel] Tool bridge init failed: {e}")
                return []
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
            openai_tools.append(
                {
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
                }
            )
        return openai_tools

    # ── ReAct agentic loop ───────────────────────────────────────────────────

    def prepare_spoken_text(self, full_response: str, user_message: str = "") -> str:
        """
        Returns ONLY the text that should be sent to the TTS engine (F5-TTS).
        Full response is ALWAYS sent separately via text_response.

        Conversational-first design: IRIS speaks a short, natural summary.
        The full response is always visible in ChatView — voice is a companion,
        not a reader.  Thresholds keep spoken output under ~20-25 seconds.

        No second LLM call — direct text processing keeps first-audio latency
        to synthesis time only (~1-2s warm, ~40s cold F5-TTS).

        Rules (applied after code/markdown is stripped):
          ≤ 60 words  → spoken verbatim (always — short answers, confirmations)
          61-120 words, conversational → spoken verbatim (user asked, answer given)
          61-120 words, document-like → first sentence + "in the chat window"
          > 120 words → first sentence to boundary (≤ 60 words) + "in the chat window"
        """
        import re as _re
        from backend.voice.tts_normalizer import normalize_text

        # Strip code fences and their content entirely — code is unreadable aloud
        cleaned = _re.sub(r"```[\s\S]*?```", "", full_response)
        # Strip inline code
        cleaned = _re.sub(r"`[^`]+`", "", cleaned)
        # Strip markdown headers (#, ##, etc.)
        cleaned = _re.sub(r"^#{1,6}\s+", "", cleaned, flags=_re.MULTILINE)
        # Strip bold/italic markers
        cleaned = _re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", cleaned)
        # Strip bullet dashes/asterisks at line start
        cleaned = _re.sub(r"^\s*[-*•]\s+", "", cleaned, flags=_re.MULTILINE)
        # Collapse whitespace
        cleaned = " ".join(cleaned.split())

        had_code = "```" in full_response
        is_doc = self._is_document_content(full_response)
        word_count = len(cleaned.split())

        # Short response — always spoken verbatim (~0-15s at 150 wpm)
        if word_count <= 60:
            spoken = normalize_text(cleaned)
            if had_code:
                spoken += " The full code is in the chat window."
            return spoken

        # Medium conversational response — spoken in full if not document-like (~15-25s)
        if word_count <= 120 and not is_doc and not had_code:
            return normalize_text(cleaned)

        # Document, code, or long response — speak first sentence(s) up to 60 words
        words = cleaned.split()
        truncated = " ".join(words[:60])
        # Walk back to last sentence boundary to avoid mid-sentence cut
        last_boundary = max(
            truncated.rfind(". "),
            truncated.rfind("! "),
            truncated.rfind("? "),
        )
        if last_boundary > 25:
            truncated = truncated[: last_boundary + 1]

        spoken = normalize_text(truncated)
        if had_code:
            spoken += " The full code is in the chat window."
        else:
            spoken += " Full response in the chat window."
        return spoken

    # ------------------------------------------------------------------
    # Issue C.1 — structured speak/show response contract
    # ------------------------------------------------------------------

    def _process_structured_response(
        self,
        response: Optional[str],
        turn_id: Optional[str] = None,
        conversation_id: str = "default",
    ) -> str:
        """Apply the Issue C.1 speak/show contract to a final LLM response.

        Parses ``response`` as structured JSON.  If it is structured:
          * emits a ``DOCUMENT_RENDER`` event carrying the ``show`` payload
            (so the frontend renders the full document visually), and
          * returns the ``speak`` field (so conversation memory and the
            ``text_response`` only contain the short spoken summary).

        If the response is not structured JSON, returns it unchanged
        (backward compatible — old free-text behavior is preserved).
        """
        if not response:
            return response or ""

        from backend.agent.structured_response import parse_structured_response

        speak, show = parse_structured_response(response)

        if show is not None:
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                get_event_bus().emit(
                    IRISStreamEvent.DOCUMENT_RENDER,
                    data={
                        "format": show.get("format", "markdown"),
                        "content": show.get("content", ""),
                        "alternatives": show.get("alternatives", []),
                        "turn_id": turn_id,
                        "conversation_id": conversation_id,
                    },
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                )
            except Exception as exc:
                logger.warning("[AgentKernel] DOCUMENT_RENDER emit failed: %s", exc)

        if speak is not None:
            # Issue C.2: also deliver the spoken summary to external channels
            # (Telegram, MCP).  Local TTS already handles it via sentence_queue,
            # so we only forward externally here (no second local utterance).
            try:
                from backend.agent.tools.speak_broadcaster import get_speak_broadcaster

                get_speak_broadcaster().forward_external(speak)
            except Exception as exc:
                logger.warning("[AgentKernel] speak broadcast failed: %s", exc)
            return speak
        return response

    def _sanitize_task(self, task: str) -> str:
        """
        Filter prompt-injection attempts before the task reaches the DER Director.
        Replaces coordinate-layer protocol markers with [filtered].
        Applied ONLY here — not in WebSocket validators.
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

    def _build_planning_prompt(
        self,
        task: str,
        tier1_directives: str = "",
        behavior_preds: str = "",
        failure_warnings: str = "None",
        skills_context: str = "",
        permissions_list: str = "",
        strategy_hint: str = "",
        task_class: str = "full",
    ) -> str:
        """
        Build the structured planning prompt for _plan_task().
        Returns sections joined with double newlines.
        FAILURE WARNINGS appears exactly once.
        """
        sections = []

        if tier1_directives:
            sections.append(f"DIRECTIVES:\n{tier1_directives}")

        if behavior_preds:
            sections.append(f"BEHAVIOR PREDICTIONS:\n{behavior_preds}")

        sections.append(f"FAILURE WARNINGS:\n{failure_warnings or 'None'}")

        sections.append(f"TASK CLASS: {task_class}")

        if strategy_hint:
            sections.append(f"STRATEGY HINT:\n{strategy_hint}")

        if skills_context:
            sections.append(f"AVAILABLE SKILLS:\n{skills_context}")

        if permissions_list:
            sections.append(f"PERMISSIONS:\n{permissions_list}")

        sections.append(f"TASK:\n{task}")

        return "\n\n".join(sections)

    def _get_failure_warnings(self, task: str) -> str:
        """
        Fetch high-signal failure warnings from Mycelium via ResolutionEncoder.
        Returns "None" on any error — never raises, never blocks.
        """
        try:
            from backend.memory.mycelium.interpreter import ResolutionEncoder

            if (
                self._memory_interface is not None
                and hasattr(self._memory_interface, "_mycelium")
                and self._memory_interface._mycelium is not None
            ):
                conn = self._memory_interface._mycelium.conn
                encoded = ResolutionEncoder.encode_with_resolution(task, conn)
                return encoded or "None"
        except Exception:
            pass
        return "None"

    def _plan_task(
        self,
        text: str,
        context: Optional[List[Dict[str, Any]]] = None,
        is_mature: bool = False,
        task_class: str = "full",
        context_package=None,
        mode: str = "full",
    ):
        """
        DER-aware planning wrapper. Returns ExecutionPlan, never raises.
        Mode + maturity-aware temperature:
          debug/review  → 0.0  (deterministic — finding bugs, not exploring)
          implement      → 0.1  (low — structured code generation)
          research       → 0.3  (higher — exploratory synthesis)
          default        → 0.1 if mature else 0.25
        Falls back to a single-step plan on any model or parse failure.
        """
        from backend.core_models import ExecutionPlan, PlanStep
        import uuid as _uuid
        import re as _re

        _MODE_TEMPERATURES = {
            "debug": 0.0,
            "review": 0.0,
            "test": 0.0,
            "implement": 0.1,
            "quick_edit": 0.1,
            "research": 0.3,
            "spec": 0.2,
        }
        temperature = _MODE_TEMPERATURES.get(mode, 0.1 if is_mature else 0.25)

        # Extract context package fields for the planning prompt
        tier1 = ""
        preds = ""
        strategy_hint = ""
        if context_package is not None:
            tier1 = getattr(context_package, "tier1_directives", "") or ""
            try:
                preds = context_package.get_tier2_predictions() or ""
            except Exception:
                pass
            try:
                strategy_hint = str(context_package.topology_primitive) or ""
            except Exception:
                pass

        failures = self._get_failure_warnings(text)

        planning_prompt = self._build_planning_prompt(
            task=text,
            tier1_directives=tier1,
            behavior_preds=preds,
            failure_warnings=failures,
            task_class=task_class,
            strategy_hint=strategy_hint,
        )

        system_prompt = ""
        if self._personality:
            try:
                system_prompt = self._personality.get_system_prompt()
            except Exception:
                pass

        full_prompt = (
            f"{system_prompt}\n\n{planning_prompt}\n\n"
            "Respond with JSON only — no prose, no markdown fences:\n"
            '{"strategy":"do_it_myself|spawn_children|delegate_external",'
            '"reasoning":"one sentence explaining the approach",'
            '"steps":[{"step_id":"s1","step_number":1,"description":"...","tool":null,"params":{},"critical":true}]}'
        )

        plan_raw: Optional[str] = None
        try:
            if self._is_openai_compat():
                _lms = self._get_lmstudio_client()
                _r = _lms.chat.completions.create(
                    model=self._selected_reasoning_model or "local-model",
                    messages=[{"role": "user", "content": full_prompt}],
                    max_tokens=-1,
                    temperature=temperature,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
                plan_raw = _r.choices[0].message.content
            elif (
                self._selected_reasoning_model and ":" in self._selected_reasoning_model
            ):
                import requests as _req

                _r2 = _req.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": self._selected_reasoning_model,
                        "messages": [{"role": "user", "content": full_prompt}],
                        "stream": False,
                    },
                    timeout=60,
                )
                if _r2.status_code == 200:
                    plan_raw = _r2.json().get("message", {}).get("content", "")
        except Exception as _pe:
            logger.warning(f"[AgentKernel._plan_task] inference failed: {_pe}")

        # Parse JSON → ExecutionPlan
        try:
            if plan_raw:
                m = _re.search(r"\{[\s\S]+\}", plan_raw)
                if m:
                    data = json.loads(m.group())
                    steps: List[Any] = []
                    for raw_step in data.get("steps", []):
                        steps.append(
                            PlanStep(
                                step_id=str(
                                    raw_step.get("step_id", str(_uuid.uuid4()))
                                ),
                                step_number=int(
                                    raw_step.get("step_number", len(steps) + 1)
                                ),
                                description=str(raw_step.get("description", "")),
                                tool=raw_step.get("tool"),
                                params=raw_step.get("params", {}),
                                critical=bool(raw_step.get("critical", True)),
                            )
                        )
                    return ExecutionPlan(
                        plan_id=str(_uuid.uuid4()),
                        original_task=text,
                        strategy=data.get("strategy", "do_it_myself"),
                        reasoning=data.get("reasoning", ""),
                        steps=steps,
                    )
        except Exception as _parse_err:
            logger.warning(f"[AgentKernel._plan_task] parse failed: {_parse_err}")

        # Fallback: minimal single-step plan so DER cycle can still proceed
        return ExecutionPlan(
            plan_id=str(_uuid.uuid4()),
            original_task=text,
            strategy="do_it_myself",
            reasoning="_plan_task fallback — model returned non-JSON",
            steps=[
                PlanStep(
                    step_id="s1",
                    step_number=1,
                    description=text,
                    tool=None,
                    critical=True,
                )
            ],
        )

    def process_text_message(
        self,
        text: str,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        from_voice: bool = False,
        turn_id: Optional[str] = None,
    ) -> str:
        """
        Main entry point for text messages.
        Decides between direct response and agentic (tool-calling) loop.

        conversation_id: Key for per-thread context persistence. If None,
                         falls back to self.conversation_id (or session_id).
        from_voice: when True the request came from the voice pipeline.
          - Overrides mode detection → "voice_first"
          - Uses DER_TOKEN_BUDGETS["voice_first"] (15k tokens, under 20k)
          - Planning caps at 1 step for fast first-token response
        """
        _t_start = time.perf_counter()

        # Use provided session_id or fall back to instance session_id
        if session_id is None:
            session_id = self.session_id

        # Resolve conversation_id — primary key for per-thread context
        _conv_id = conversation_id or self.conversation_id
        self.conversation_id = _conv_id

        # Reset thinking from any previous call so stale data never leaks
        self._pending_thinking = ""

        # Stage 1 observability: per-turn metrics (created early so error paths can log)
        import uuid

        task_id = turn_id or str(uuid.uuid4())
        metrics = TurnMetrics(turn_id=task_id)
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

        _t_memory = time.perf_counter()
        logger.debug(
            f"[Timing] memory.get_context: {(_t_memory - _t_start) * 1000:.1f} ms"
        )

        # ── Direct path (default): skip planning for non-tool messages ──────────
        # Planning only runs when the message explicitly requests a tool-backed
        # action (search, open, create, etc.).  Everything else — greetings,
        # questions, conversation — goes straight to _respond_direct() which
        # calls the model with no JSON schema overhead.
        if not self._needs_planning(text):
            logger.info("[AgentKernel] Direct response path (no planning needed)")
            try:
                _t_llm_start = time.perf_counter()
                response = self._respond_direct(
                    text,
                    context,
                    chunk_callback=_wrapped_chunk_cb,
                    reasoning_callback=reasoning_callback,
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
            # Issue C.1: apply speak/show contract — emit document:render for
            # the `show` payload and reduce the stored/returned text to `speak`.
            response = self._process_structured_response(
                response, turn_id=task_id, conversation_id=_conv_id
            )
            # Never store error or empty responses in conversation memory.
            # They break role alternation and accumulate into garbage context
            # on subsequent turns, causing Cohere/OpenAI 400 errors.
            if response and not response.startswith("[IRIS error:"):
                try:
                    self._conversation_memory.add_message("assistant", response)
                except Exception as _mem_exc:
                    loud_error(_mem_exc, "conversation_memory.add_message (direct)")
            # Option B / Pacman: fragment this turn-pair into the vector DB so future
            # context assembly can retrieve it semantically (PACMAN.md §Digestion).
            # MCM orchestrator handles fragmentation + compression check when available.
            try:
                if response:
                    _turn = f"User: {text}\nAssistant: {response}"
                    if self._mcm_orch is not None:
                        self._mcm_orch.post_turn(
                            self._conversation_memory.messages
                            if self._conversation_memory
                            else [],
                            response_text=response,
                        )
                        metrics.pacman_store += 1
                    elif (
                        self._memory_interface is not None
                        and hasattr(self._memory_interface, "episodic")
                        and hasattr(
                            self._memory_interface.episodic, "fragment_and_store"
                        )
                    ):
                        self._memory_interface.episodic.fragment_and_store(
                            _turn,
                            session_id=session_id or self.session_id,
                            chunk_type="context_fragment",
                            zone="trusted",
                        )
                        metrics.pacman_store += 1
            except Exception as _pac_exc:
                loud_error(_pac_exc, "pacman fragment_and_store")
            if response is None:
                logger.error(
                    "[AgentKernel] _respond_direct returned None — returning fallback"
                )
                response = "I wasn't able to generate a response. Please check the model connection."
            metrics.path = "direct"
            logger.info(f"[AgentKernel] Direct response: {response[:50]}...")
            logger.info(metrics.to_log_line())
            return response

        # ── DER path: sanitize → classify → Mycelium → plan → execute ──────
        # Runs BEFORE the ReAct loop. Falls through to ReAct on any failure.
        _der_response: Optional[str] = None
        try:
            _task_clean = self._sanitize_task(text)
            _task_class = "full"
            if self._task_classifier is not None:
                try:
                    _task_class, _ = self._task_classifier.classify(_task_clean)
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
                except Exception as _ctx_exc:
                    loud_error(_ctx_exc, "memory_interface.get_task_context_package")

            # Mode detection — runs AFTER Mycelium fetch so mature graph data
            # can suppress clarification mode and improve confidence.
            # Result flows into _plan_task() (temperature) and _execute_plan_der()
            # (token budget via DER_TOKEN_BUDGETS[mode]).
            # Voice requests skip mode detection and lock to "voice_first" so
            # they always get the tight 15k token budget and single-step plan.
            # Confidence defaults to 0.5 for voice — memory-derived when mature.
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

            _plan = self._plan_task(
                text=_task_clean,
                context=context,
                is_mature=_is_mature,
                task_class=_task_class,
                context_package=_context_package,
                mode=_mode_name,
            )

            # GAP 5 — strategy signal to Mycelium after planning
            try:
                if self._memory_interface:
                    self._memory_interface.mycelium_ingest_statement(
                        statement=f"task required {_plan.strategy}: {_plan.reasoning}",
                        session_id=session_id or self.session_id,
                    )
            except Exception as _ing_exc:
                loud_error(_ing_exc, "mycelium_ingest_statement")

            # GAP 6 — register plan address when Mycelium is mature
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

            # GAP 4 — route by strategy (do_it_myself → DER; others → ReAct)
            if _plan.strategy == "do_it_myself":
                # Use mode name as task_class so DER_TOKEN_BUDGETS[mode] applies.
                # Falls back to _task_class if mode not in budget table.
                _der_task_class = (
                    _mode_name if _mode_name in DER_TOKEN_BUDGETS else _task_class
                )
                _der_response = self._execute_plan_der(
                    plan=_plan,
                    context_package=_context_package,
                    is_mature=_is_mature,
                    task_class=_der_task_class,
                    session_id=session_id or self.session_id,
                    from_voice=from_voice,
                    confidence=_confidence,
                )

        except Exception as _der_err:
            logger.warning(
                f"[AgentKernel] DER path error (falling back to ReAct): {_der_err}"
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
                    self._conversation_memory.add_message("assistant", _der_response)
                except Exception as _mem_exc:
                    loud_error(_mem_exc, "conversation_memory.add_message (der)")
                metrics.path = "der"
                logger.info(f"[AgentKernel] DER response: {_der_response[:200]}...")
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
                # ── FIX (session 154): Invoke chunk_callback on DER path ──
                # The DER loop generates the full response via internal LLM
                # calls but never invokes chunk_callback. Without this call,
                # the TTS sentence_queue only receives the None sentinel,
                # the producer breaks immediately, and no audio is synthesized.
                logger.info(
                    f"[DER-TTS-FIX] chunk_callback={chunk_callback is not None}, "
                    f"der_response_len={len(_der_response) if _der_response else 0}"
                )
                if chunk_callback and _der_response:
                    chunk_callback(_der_response)
                    chunk_callback("")  # force-flush end-of-stream
                    logger.info("[DER-TTS-FIX] chunk_callback invoked OK")
                else:
                    logger.warning(
                        f"[DER-TTS-FIX] SKIPPED — chunk_callback={chunk_callback}, "
                        f"der_response={bool(_der_response)}"
                    )
                # Issue C.1: apply speak/show contract before returning.
                _der_response = self._process_structured_response(
                    _der_response, turn_id=task_id, conversation_id=_conv_id
                )
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

        # Return specific error to user so they can fix it immediately
        if _der_err_text:
            _err_msg = f"IRIS couldn't generate a response. API error: {_der_err_text}"
            if chunk_callback:
                chunk_callback(_err_msg)
                chunk_callback("")
            return _err_msg
        _fallback_msg = "IRIS couldn't generate a response. Please try again."
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

    def plan_task(
        self, task_description: str, context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
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
                        reasoning_model = self._model_router.models.get(
                            self._selected_reasoning_model
                        )
                        if reasoning_model:
                            logger.info(
                                f"[AgentKernel] Using user-selected reasoning model: {self._selected_reasoning_model}"
                            )
                        else:
                            # Only fall back to the default local stub when neither Ollama
                            # nor VPS will handle this request.  If ":" is in the model ID
                            # it is an Ollama model (e.g. "llama3.2:3b"); if VPS is wired
                            # the VPS block below handles it.  In those cases we MUST NOT
                            # fall back — the stub is broken and produces garbage output.
                            _sel_check = self._selected_reasoning_model
                            _ollama_will_handle = ":" in _sel_check
                            _vps_will_handle = bool(self._vps_gateway)
                            _lmstudio_will_handle = self._is_openai_compat()
                            if (
                                not _ollama_will_handle
                                and not _vps_will_handle
                                and not _lmstudio_will_handle
                            ):
                                logger.warning(
                                    f"[AgentKernel] Selected model {_sel_check} unavailable, "
                                    "falling back to default local model"
                                )
                                reasoning_model = (
                                    self._model_router.get_reasoning_model()
                                )
                                if reasoning_model:
                                    default_model_id = getattr(
                                        reasoning_model, "model_id", "unknown"
                                    )
                                    logger.info(
                                        f"[AgentKernel] Fallback: using default reasoning model {default_model_id}"
                                    )
                            else:
                                _dest = (
                                    "LM Studio"
                                    if _lmstudio_will_handle
                                    else ("Ollama" if _ollama_will_handle else "VPS")
                                )
                                logger.info(
                                    f"[AgentKernel] Selected model '{_sel_check}' not in local cache — "
                                    f"will route to {_dest}"
                                )
                                # reasoning_model stays None; inference block handles it
                    else:
                        # No model selected — use default reasoning model
                        reasoning_model = self._model_router.get_reasoning_model()
                        if reasoning_model:
                            default_model_id = getattr(
                                reasoning_model, "model_id", "unknown"
                            )
                            logger.info(
                                f"[AgentKernel] No model selected, using default reasoning model: {default_model_id}"
                            )
                except Exception as e:
                    logger.error(f"[AgentKernel] Error getting reasoning model: {e}")
                    return {"error": f"Failed to access reasoning model: {e}"}

            # Handle model unavailability
            if not reasoning_model:
                if self._single_model_mode and self._available_model_id:
                    # Fall back to the single available local model
                    logger.warning(
                        "[AgentKernel] Reasoning model unavailable, using fallback model"
                    )
                    try:
                        reasoning_model = self._model_router.models.get(
                            self._available_model_id
                        )
                    except Exception as e:
                        logger.error(
                            f"[AgentKernel] Error accessing fallback model: {e}"
                        )
                        return {"error": f"Failed to access fallback model: {e}"}
                elif self._is_openai_compat():
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
                            logger.warning(
                                f"[AgentKernel] Lazy load failed: {_lazy_err}"
                            )
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
                context_str = "\n\nConversation Context:\n" + json.dumps(
                    context[-5:], indent=2
                )

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
                    logger.info(
                        "[AgentKernel] Using VPS Gateway for planning inference..."
                    )
                    try:
                        plan_response = asyncio.run(
                            self._vps_gateway.infer(
                                model=self._model_router.get_reasoning_model_id()
                                or "lfm2-8b",
                                prompt=planning_prompt,
                                context={"conversation_history": context}
                                if context
                                else {},
                                params={"max_tokens": 512, "temperature": 0.2},
                                session_id=self.session_id,
                            )
                        )
                        logger.info("[AgentKernel] VPS Gateway inference complete")
                    except RuntimeError as e:
                        if "already running" in str(e):
                            logger.warning(
                                "[AgentKernel] Event loop conflict — falling back to local model"
                            )
                            plan_response = None
                        else:
                            raise
                except TimeoutError:
                    logger.error("[AgentKernel] VPS Gateway inference timed out")
                    raise
                except Exception as e:
                    logger.warning(
                        f"[AgentKernel] VPS Gateway inference failed, falling back to direct model: {e}"
                    )
                    plan_response = None

            # LM Studio inference (OpenAI-compatible local API at localhost:1234).
            # Triggered when provider == "lmstudio" and no prior backend produced a response.
            # Uses the openai Python client pointed at the LM Studio local server.
            if plan_response is None and self._is_openai_compat():
                try:
                    _lms = self._get_lmstudio_client()
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
                    logger.warning(
                        f"[AgentKernel] LM Studio planning inference failed: {_lms_err}"
                    )

            # Ollama local inference — runs when the model ID contains ":" which is
            # the Ollama format (e.g. "llama3.2:3b", "mistral:7b", "kimi-k2.5:cloud").
            # NOTE: provider="local" means LFM local file — it does NOT go to Ollama.
            # Only colon-format IDs are Ollama models.
            if (
                plan_response is None
                and self._selected_reasoning_model
                and (":" in self._selected_reasoning_model)
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
                        planning_prompt, max_tokens=-1, temperature=0.2
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Model inference failed: {e}")
                    # Attempt to restart model
                    try:
                        logger.info(
                            "[AgentKernel] Attempting to restart reasoning model..."
                        )
                        reasoning_model.unload()
                        reasoning_model.load()
                        plan_response = reasoning_model.generate(
                            planning_prompt, max_tokens=-1, temperature=0.2
                        )
                        logger.info("[AgentKernel] Model restarted successfully")
                    except Exception as restart_error:
                        logger.error(
                            f"[AgentKernel] Model restart failed: {restart_error}"
                        )
                        return {
                            "error": f"Model crashed and restart failed: {restart_error}"
                        }

            # Check timeout after inference
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Planning timed out after {elapsed:.1f}s")

            # Parse JSON response
            try:
                plan = json.loads(plan_response)
                logger.info(
                    f"[AgentKernel] Plan generated with {len(plan.get('steps', []))} steps in {elapsed:.2f}s"
                )
                return plan
            except json.JSONDecodeError:
                # Model returned free-form text rather than JSON.
                # Treat the entire response as the user-facing reply — do NOT use
                # "respond_to_user" as the action string because execute_step would
                # return that keyword verbatim to the frontend.
                logger.warning(
                    "[AgentKernel] Failed to parse plan as JSON, using raw text as response"
                )
                _raw_text = (
                    self._strip_thinking(plan_response)
                    if plan_response
                    else "I'm not sure how to respond to that."
                )
                return {
                    "analysis": _raw_text[:200],
                    "requires_tools": False,
                    "_raw_response": _raw_text,  # consumed by _synthesize_response
                    "steps": [
                        {
                            "step": 1,
                            "action": _raw_text,  # the ACTUAL text, not a keyword
                            "tool": None,
                            "parameters": {},
                        }
                    ],
                }

        except TimeoutError:
            logger.error(f"[AgentKernel] Planning timed out after {timeout_seconds}s")
            raise
        except Exception as e:
            error_msg = f"Error during task planning: {e}"
            logger.error(f"[AgentKernel] {error_msg}", exc_info=True)
            return {"error": error_msg}

    def _execute_plan_der(
        self,
        plan,
        context_package=None,
        is_mature: bool = False,
        task_class: str = "full",
        session_id: Optional[str] = None,
        from_voice: bool = False,
        confidence: float = 0.50,
    ) -> str:
        """
        DER execution cycle: Director → Reviewer → Explorer → repeat until complete.

        The Director re-reads Mycelium each cycle via ContextPackage.
        The Reviewer gates each step (PASS / REFINE / VETO).
        The Explorer executes via _tool_bridge or direct model call.
        Mycelium signal hooks fire after every step and at outcome.

        Never raises — wraps failures as step error text so the response
        always reaches the user.
        """
        from backend.agent.der_loop import (
            DirectorQueue,
            QueueItem,
            Reviewer,
            ReviewVerdict,
        )
        from backend.agent.der_constants import ExecutionMode
        import uuid as _uuid

        _session = session_id or self.session_id
        completed_items: List[Any] = []
        step_outputs: List[str] = []
        _der_start_time = time.perf_counter()

        # Token budget — spec [1.2]: enforce DER_TOKEN_BUDGETS[task_class]
        # Tokens are estimated from step result length (4 chars ≈ 1 token).
        # Budget is a ceiling; the loop exits early if exceeded.
        _token_budget: int = DER_TOKEN_BUDGETS.get(
            task_class, DER_TOKEN_BUDGETS.get("full", 50000)
        )
        _tokens_used: int = 0

        # Build Director queue from ExecutionPlan steps
        items = [
            QueueItem(
                step_id=step.step_id,
                step_number=step.step_number,
                description=step.description,
                tool=step.tool,
                params=step.params if step.params else {},
                critical=step.critical,
                objective_anchor=plan.original_task,
                coordinate_signal=(
                    getattr(context_package, "topology_position", "") or ""
                    if context_package
                    else ""
                ),
            )
            for step in plan.steps
        ]
        queue = DirectorQueue(objective=plan.original_task, items=items)

        # ── Phase 3: initialize execution mode ────────────────────────
        # Director decides mode dynamically based on task characteristics.
        # Voice no longer caps to 1 step — Director decides based on content.
        voice_preference = getattr(self, "_voice_preference", "auto")
        initial_mode = DirectorQueue._decide_mode(
            task_class=task_class,
            from_voice=from_voice,
            message_text=plan.original_task or "",
            token_budget_remaining=_token_budget,
            confidence=confidence,
            voice_preference=voice_preference,
        )
        queue.set_mode(initial_mode, reason=f"Task class: {task_class}")
        logger.info(
            "[DER] Mode selected: %s (voice=%s, class=%s, budget=%d)",
            initial_mode.value, from_voice, task_class, _token_budget,
        )

        # ── EventBus: emit task:start ──────────────────────────────────
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            bus = get_event_bus()
            bus.emit(
                IRISStreamEvent.TASK_START,
                data={
                    "task_id": _turn_id or plan.original_task[:40],
                    "description": plan.original_task[:200],
                    "mode": initial_mode.value,
                    "steps": [
                        {
                            "id": it.step_id,
                            "description": it.description,
                            "status": "pending",
                            "toolName": it.tool,
                        }
                        for it in items
                    ],
                    "total_steps": len(items),
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass  # EventBus is optional — no crash if it fails

        # C.1 LiveContextPackage — refreshes ContextPackage mid-loop so the
        # Director always reads current gradient_warnings + tier2_predictions.
        try:
            from backend.memory.live_context import LiveContextPackage

            _live_ctx = LiveContextPackage(
                initial_package=context_package,
                memory_interface=self._memory_interface,
                session_id=_session,
            )
        except Exception:
            _live_ctx = None  # graceful no-op if import fails

        # Reviewer — falls back to PASS on any failure (membrane, not gate)
        reviewer = self._reviewer

        # WS disconnect helper — checks if the originating session still has
        # at least one live client. Never raises; defaults to "connected".
        def _session_has_client() -> bool:
            try:
                from backend.ws_manager import get_websocket_manager

                ws = get_websocket_manager()
                if ws is None:
                    return True  # no WS manager → non-WS path, keep running
                return len(ws.get_clients_for_session(_session)) > 0
            except Exception:
                return True

        while (
            not queue.is_complete()
            and not queue.hit_cycle_limit()
            and _tokens_used < _token_budget
        ):
            # ── DISCONNECT CHECK: stop early if client is gone ──────────────
            if not _session_has_client():
                logger.info(
                    f"[DER] Session {_session} has no connected clients — "
                    "recording partial outcome and stopping"
                )
                break

            queue.cycle_count += 1

            # ── DOMAIN 19: Caducean phase read ──
            import math as _math

            _xi = 0.0
            try:
                from backend.gateway.iris_ffi import ffi_caducean_get_xi

                _xi = ffi_caducean_get_xi(_session)
            except Exception as _ffi_exc:
                loud_error(_ffi_exc, "ffi_caducean_get_xi")
            _phase = 0  # 0=[0,π/2], 1=[π/2,π], 2=[π,3π/2], 3=[3π/2,2π]
            if _xi >= 3.0 * _math.pi / 2.0:
                _phase = 3
            elif _xi >= _math.pi:
                _phase = 2
            elif _xi >= _math.pi / 2.0:
                _phase = 1

            item = queue.next_ready()
            if item is None:
                break  # dependency deadlock guard

            # ── C.1 LIVE CONTEXT REFRESH ────────────────────────────────────
            # Re-read Mycelium coordinate signals for the current sub-step.
            # Updates gradient_warnings + tier2_predictions on context_package.
            # < 50ms SLA; silently no-ops on any error.
            if _live_ctx is not None:
                _live_ctx.refresh(item, completed_items)
                context_package = _live_ctx.package  # always valid

            # ── C.4 MID-LOOP EPISODIC RETRIEVAL ────────────────────────────
            # Query the episodic store for the *current sub-task*, not the
            # parent task.  Injects a hint into item.coordinate_signal so the
            # Reviewer and Explorer both see "I solved this sub-problem before
            # this way".  <50ms: uses cached embeddings after first query.
            try:
                if self._memory_interface and item.description:
                    _retrieval_limit = 2
                    _retrieval_score = 0.55
                    try:
                        from backend.gateway.iris_ffi import ffi_calculate_eml

                        _eml, _ex, _ey = ffi_calculate_eml(_session)
                        if _eml >= 1.50 and _ex >= 0.60:
                            _retrieval_limit = 5
                            _retrieval_score = 0.40
                        elif _eml < 1.00 and _ey >= 0.70:
                            _retrieval_limit = 3
                            _retrieval_score = 0.65
                    except Exception as _eml_exc:
                        loud_error(_eml_exc, "caducean_eml_retrieval")
                    _sub_eps = self._memory_interface.episodic.retrieve_similar(
                        task=item.description,
                        limit=_retrieval_limit,
                        min_score=_retrieval_score,
                    )
                    if _sub_eps:
                        _hints = "; ".join(
                            ep.get("task_summary", "")[:80]
                            for ep in _sub_eps
                            if ep.get("task_summary")
                        )
                        if _hints:
                            _prior = getattr(item, "coordinate_signal", "") or ""
                            item.coordinate_signal = (
                                _prior + f"\nSUB-TASK HINT: {_hints}"
                            ).strip()
            except Exception as _explore_exc:
                loud_error(_explore_exc, "explorer_sub_episodes")

            # ── REVIEWER PHASE ─────────────────────────────────────────────
            if reviewer is not None:
                try:
                    verdict, feedback = reviewer.review(
                        item=item,
                        completed_steps=completed_items,
                        context_package=context_package,
                        is_mature=is_mature,
                    )
                except Exception:
                    verdict, feedback = ReviewVerdict.PASS, None

                if verdict == ReviewVerdict.VETO:
                    item.veto_count += 1
                    logger.info(
                        f"[DER] Step {item.step_number} VETOED "
                        f"(count={item.veto_count}, reason={feedback})"
                    )
                    # Emit veto signal to Mycelium
                    try:
                        if self._memory_interface:
                            self._memory_interface.mycelium_ingest_tool_call(
                                tool_name=item.tool or "unknown",
                                success=False,
                                sequence_position=item.step_number,
                                total_steps=len(queue.items),
                                session_id=_session,
                            )
                    except Exception as _rev_exc:
                        loud_error(_rev_exc, "reviewer_trajectory_record")

                    if item.veto_count <= queue.max_veto_per_item:
                        # Keep in queue for Director to reroute next cycle
                        continue
                    else:
                        queue.mark_vetoed(item.step_id)
                        continue

                if verdict == ReviewVerdict.REFINE and feedback:
                    item.refined_description = feedback
                    item.description = feedback
                    logger.info(f"[DER] Step {item.step_number} REFINED")

            # ── EXPLORER PHASE ─────────────────────────────────────────────
            # Emit TOOL_CALL event for the frontend / TaskKernel
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_CALL,
                    data={
                        "task_id": _turn_id or item.step_id,
                        "tool_name": item.tool or "direct",
                        "description": item.description[:200],
                        "params": item.params,
                        "step_number": item.step_number,
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                )
            except Exception:
                pass

            step_result: str = ""
            step_success: bool = True
            try:
                if item.tool and self._tool_bridge is not None:
                    # execute_tool is async — use asyncio.run() since _execute_plan_der
                    # runs inside run_in_executor (a thread pool thread), making
                    # asyncio.run() safe here. Same pattern as the ReAct loop (line ~1484).
                    try:
                        raw = asyncio.run(
                            self._tool_bridge.execute_tool(
                                tool_name=item.tool,
                                params=item.params,
                                session_id=_session,
                            )
                        )
                    except RuntimeError as _rte:
                        # asyncio.run() fails if an event loop is already running in
                        # this thread (shouldn't happen in executor, but guard anyway)
                        logger.warning(
                            f"[DER] asyncio.run failed for tool {item.tool}: {_rte} — using executor"
                        )
                        import concurrent.futures as _cf

                        with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                            raw = _pool.submit(
                                asyncio.run,
                                self._tool_bridge.execute_tool(
                                    tool_name=item.tool,
                                    params=item.params,
                                    session_id=_session,
                                ),
                            ).result(timeout=60)
                    step_result = str(raw) if raw is not None else ""
                else:
                    step_result = self._run_step_direct(item, context_package, _session)
            except Exception as _ex_err:
                step_success = False
                step_result = f"[STEP ERROR: {_ex_err}]"
                logger.warning(
                    f"[DER] Step {item.step_number} explorer error: {_ex_err}"
                )

            step_outputs.append(step_result)

            # ── EventBus: emit tool:result or tool:error ────────────────
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                if step_success:
                    get_event_bus().emit(
                        IRISStreamEvent.TOOL_RESULT,
                        data={
                            "task_id": _turn_id or item.step_id,
                            "result_summary": step_result[:200],
                            "tool_name": item.tool or "direct",
                            "step_number": item.step_number,
                        },
                        turn_id=_turn_id,
                        conversation_id=self.conversation_id,
                        session_id=_session,
                    )
                else:
                    get_event_bus().emit(
                        IRISStreamEvent.TOOL_ERROR,
                        data={
                            "task_id": _turn_id or item.step_id,
                            "error": step_result[:200],
                            "tool_name": item.tool or "direct",
                            "step_number": item.step_number,
                        },
                        turn_id=_turn_id,
                        conversation_id=self.conversation_id,
                        session_id=_session,
                    )
            except Exception:
                pass

            # Option B / Pacman: fragment DER step output into vector DB so it can be
            # retrieved as context in later steps or future sessions.
            # MCM orchestrator handles fragmentation + compression check when available.
            try:
                if step_result and step_success:
                    _der_text = (
                        f"[Step {item.step_number}: {item.description[:120]}]"
                        f"\n{step_result}"
                    )
                    if self._mcm_orch is not None:
                        self._mcm_orch.post_turn(
                            [{"role": "assistant", "content": _der_text}],
                            response_text=_der_text,
                            tool_name=getattr(item, "tool_name", ""),
                        )
                    elif (
                        self._memory_interface is not None
                        and hasattr(self._memory_interface, "episodic")
                        and hasattr(
                            self._memory_interface.episodic, "fragment_and_store"
                        )
                    ):
                        self._memory_interface.episodic.fragment_and_store(
                            _der_text,
                            session_id=_session,
                            chunk_type="der_output",
                            zone="tool",
                        )
            except Exception as _frag_exc:
                loud_error(_frag_exc, "der_pacman_fragment")

            # ── TOKEN BUDGET: accumulate estimated tokens from step result ──
            # 4 chars ≈ 1 token; also count prompt overhead per step (~200 tok)
            _tokens_used += max(200, len(step_result) // 4)
            # ── EventBus: emit context:usage (token budget progress) ──────
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                get_event_bus().emit(
                    IRISStreamEvent.CONTEXT_USAGE,
                    data={
                        "used_tokens": int(_tokens_used),
                        "max_tokens": int(self.resolve_context_window()),
                        "step_number": item.step_number,
                        "total_steps": len(queue.items),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
            except Exception:
                pass  # EventBus is optional — no crash if it fails
            if _tokens_used >= _token_budget:
                logger.info(
                    f"[DER] Token budget exhausted ({_tokens_used}/{_token_budget}) "
                    f"after step {item.step_number} — stopping early"
                )

            # ── MYCELIUM SIGNAL: tool call ─────────────────────────────────
            try:
                if self._memory_interface:
                    self._memory_interface.mycelium_ingest_tool_call(
                        tool_name=item.tool or "none",
                        success=step_success,
                        sequence_position=item.step_number,
                        total_steps=len(queue.items),
                        session_id=_session,
                    )
            except Exception as _wm_exc:
                loud_error(_wm_exc, "mycelium_working_memory")

            # ── WORKING MEMORY: accumulate findings for later steps ────────
            # Appends step result to working_history zone so _run_step_direct()
            # calls on later steps can see what earlier steps discovered.
            # Skips error outputs to avoid poisoning context with noise.
            try:
                if self._memory_interface and step_result and step_success:
                    _wm_note = (
                        f"[Step {item.step_number}: {item.description[:80]}]"
                        f" → {step_result[:400]}"
                    )
                    self._memory_interface.append_to_session(
                        _session, _wm_note, zone="working_history"
                    )
            except Exception as _wm2_exc:
                loud_error(_wm2_exc, "append_working_history")

            queue.mark_complete(item.step_id)

            # ── CADUCEAN UPDATE + IMMORTUS + TRAJECTORY RECORD ──
            try:
                from backend.gateway.iris_ffi import (
                    ffi_caducean_update,
                    ffi_calculate_eml,
                    ffi_immortus_chain_append,
                )
                from backend.agent.caducean_trajectory import get_trajectory_recorder

                _action = 0
                if item.tool in ("run_command", "git_commit", "git_push"):
                    _action = 1
                elif not step_success:
                    _action = 2
                _eml_score, _ex, _ey = ffi_calculate_eml(_session)
                # v2: balance clamped to [0.1, 3.0] (was [0.1, 2.0]).
                # Note: the v2 baseline divisor is 2.3418 per the field theory
                # (see docs/cad_v2_architecture.md §2.2). The current EML
                # returns a raw score, not a balance; the kernel clamps to
                # the safe range defensively. The TrajectoryController may
                # override the constant via ffi_caducean_set_params.
                _balance = max(0.1, min(3.0, _eml_score))
                ffi_caducean_update(_session, _action, _balance)

                # v2: fetch recommendation code AFTER the update so we can
                # detect TOPO_VIOLATION (3) and persist the new column.
                from backend.gateway.iris_ffi import (
                    ffi_caducean_recommend,
                    ffi_caducean_get_state,
                )

                _rec = ffi_caducean_recommend(_session)
                _state_snapshot = ffi_caducean_get_state(_session)
                _xi = _state_snapshot.get("xi", 0.0)
                _u = _state_snapshot.get("u", 0.0)

                get_trajectory_recorder(self._memory_interface).record(
                    session_id=_session,
                    step_num=item.step_number,
                    x=_ex,
                    y=_ey,
                    xi=_xi,
                    u=_u,
                    action=_action,
                    outcome="success" if step_success else "failure",
                    eml_after=_eml_score,
                    recommendation=_rec,
                )

                # v2: handle TOPO_VIOLATION (rec=3) by recording the anomaly
                # to the Mycelium QuorumSensor and halting the loop.
                if _rec == 3:
                    try:
                        self._memory_interface.mycelium_record_anomaly(
                            _session, "update_velocity_anomaly"
                        )
                    except Exception as _anom_exc:  # never block on this
                        logger.warning(
                            "[agent_kernel] mycelium_record_anomaly failed: %s",
                            _anom_exc,
                        )
                    from .exceptions import TopologyViolationException

                    raise TopologyViolationException(
                        session_id=_session,
                        direction_signal=None,  # full signal in DebugPanel
                    )

                ffi_immortus_chain_append(
                    thread_id=_session,
                    result="success" if step_success else "failure",
                    coords_from=getattr(item, "coordinate_signal", "") or "",
                    coords_to=item.tool or "none",
                    nbl_outcome=f"step_{item.step_number}",
                    insight=item.description[:120],
                    file_path=item.params.get("path", "") if item.params else "",
                    landmark_id="",
                )
            except Exception as _cad_exc:
                loud_error(_cad_exc, "caducean_trajectory_immortus")

            completed_items.append(item)

            # ── Phase 3: escalation + explorer ─────────────────────────
            # After each step, check if mode escalation is warranted.
            # If queue is complete but more work is needed in AGENTIC/FULL
            # mode, re-plan with the LLM.
            try:
                _result_summary = (step_outputs[-1] if step_outputs else "")[:200]
                queue.check_escalation(
                    review_verdict=verdict,
                    tool_result_summary=_result_summary,
                    token_budget_remaining=_tokens_used,
                    turn_id=_turn_id,
                )

                # If queue is complete but mode is AGENTIC or FULL,
                # ask the LLM if more tools are needed.
                if queue.mode in (
                    ExecutionMode.AGENTIC, ExecutionMode.FULL,
                ) and queue.is_complete():
                    _next_tool = self._der_plan_next_step(
                        plan.original_task,
                        completed_items,
                        queue.mode,
                        _turn_id,
                    )
                    if _next_tool:
                        _next_item = QueueItem(
                            step_id=f"explorer_{len(completed_items) + 1}",
                            step_number=len(completed_items) + 1,
                            description=_next_tool.get("description", ""),
                            tool=_next_tool.get("tool"),
                            params=_next_tool.get("params", {}),
                            objective_anchor=plan.original_task,
                        )
                        queue.add_item(_next_item)
                        logger.info(
                            "[DER] Explorer added step %d: %s",
                            _next_item.step_number,
                            _next_item.description,
                        )

                # If mode is FULL and multiple steps completed,
                # also check for overall progress and re-synthesize.
                if queue.mode == ExecutionMode.FULL and len(completed_items) >= 3:
                    self._der_check_full_progress(
                        plan.original_task,
                        completed_items,
                        _turn_id,
                    )
            except Exception as _explorer_exc:
                logger.warning(
                    "[DER] Explorer escalation failed: %s", _explorer_exc
                )

            # ── EventBus: emit der:step ────────────────────────────────
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                get_event_bus().emit(
                    IRISStreamEvent.DER_STEP,
                    data={
                        "task_id": _turn_id or item.step_id,
                        "step_number": item.step_number,
                        "step_description": item.description[:200],
                        "tool": item.tool,
                        "success": step_success,
                        "total_steps": len(queue.items),
                        "completed": len(completed_items),
                        "mode": queue.mode.value,
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                )
            except Exception:
                pass

            # ── TRAILING DIRECTOR: analyze gaps every TRAILING_GAP_MIN steps ─
            # Domain 19: phase 4 (crystallization) forces gap analysis;
            # phase 3 (strict) suppresses adding new gap items.
            try:
                _force_gap = _phase == 3
                _suppress_new = _phase == 2
                if self._trailing_director is not None and (
                    _force_gap or len(completed_items) % TRAILING_GAP_MIN == 0
                ):
                    gap_items = self._trailing_director.analyze_gaps(
                        item, plan, context_package, is_mature
                    )
                    if not _suppress_new:
                        for gap_item in gap_items:
                            queue.add_item(gap_item)
            except Exception as _gap_exc:
                loud_error(_gap_exc, "trailing_director_gaps")

        # ── OUTCOME RECORDING (ordered per spec: clear → stats → episode)
        # NOTE: _store_task_episode internally calls mycelium_record_outcome
        # and mycelium_crystallize_landmark, so we do NOT duplicate them here.
        had_failures = any("[STEP ERROR" in o for o in step_outputs)
        outcome = "failure" if had_failures else "success"

        # ── EventBus: emit task:done / task:fail ────────────────────────
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.TASK_DONE if outcome == "success" else IRISStreamEvent.TASK_FAIL,
                data={
                    "task_id": _turn_id or plan.original_task[:40],
                    "outcome": outcome,
                    "steps_completed": len(completed_items),
                    "total_steps": len(plan.steps),
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass  # EventBus is optional — no crash if it fails

        try:
            if self._memory_interface:
                self._memory_interface.mycelium_clear_session(
                    session_id=_session,
                )
        except Exception as _exc:
            loud_error(_exc, "mycelium_clear_session")

        try:
            if self._memory_interface:
                _der_duration_total = int(
                    (time.perf_counter() - _der_start_time) * 1000
                )
                _avg_step_ms = (
                    _der_duration_total / len(completed_items)
                    if completed_items
                    else 0.0
                )
                self._memory_interface.mycelium_record_plan_stats(
                    session_id=_session,
                    task_class=task_class,
                    strategy=plan.strategy,
                    total_steps=len(plan.steps),
                    steps_completed=len(completed_items),
                    tokens_used=_tokens_used,
                    avg_step_duration_ms=_avg_step_ms,
                    outcome=outcome,
                    graph_mature=is_mature,
                )
        except Exception as _exc:
            loud_error(_exc, "mycelium_record_plan_stats")

        # ── EPISODIC STORAGE: write completed task to episodic memory ──────────
        # Closes the read/write loop. get_task_context() already calls
        # assemble_episodic_context() which reads from this store — but only
        # if episodes exist. This call creates them.
        # Also triggers Mycelium outcome + crystallization internally.
        try:
            if self._memory_interface:
                _der_duration_ms = int((time.perf_counter() - _der_start_time) * 1000)
                _tool_seq = [
                    {
                        "tool": ci.tool or "none",
                        "params": ci.params,
                        "step": ci.step_number,
                        "description": ci.description,
                    }
                    for ci in completed_items
                ]
                _full_content = "\n".join(
                    f"[Step {i + 1}] {o}" for i, o in enumerate(step_outputs) if o
                )
                self._store_task_episode(
                    task_summary=plan.original_task,
                    full_content=_full_content,
                    outcome_type=outcome,
                    tool_sequence=_tool_seq,
                    session_id=_session,
                    duration_ms=_der_duration_ms,
                )
                # Domain 4.5 — check if this tool sequence warrants a new skill
                try:
                    self._maybe_trigger_skill_creation(
                        tool_sequence=_tool_seq,
                        task_summary=plan.original_task,
                    )
                except Exception as _exc:
                    loud_error(_exc, "skill_creation_trigger")
        except Exception as _exc:
            loud_error(_exc, "store_task_episode")

        # ── EventBus: emit der:done ────────────────────────────────────
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.DER_DONE,
                data={
                    "task_id": _turn_id or plan.original_task[:40],
                    "outcome": outcome,
                    "mode": queue.mode.value,
                    "total_steps": len(queue.items),
                    "completed": len(completed_items),
                    "tokens_used": _tokens_used,
                    "mode_history": [
                        {
                            "previous": c.previous_mode.value if c.previous_mode else None,
                            "new": c.new_mode.value,
                            "reason": c.reason,
                            "turn_id": c.turn_id,
                        }
                        for c in queue.mode_history
                    ],
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        if step_outputs:
            return "\n".join(o for o in step_outputs if o)
        return (
            f"[DER] {plan.strategy} — "
            f"{len(completed_items)}/{len(plan.steps)} steps completed."
        )

    def _run_step_direct(self, item, context_package, session_id: str) -> str:
        """
        Execute a tool-less DER step via direct model inference.
        Returns the model's response text, or an error placeholder.
        Injects accumulated working memory (prior step findings) into the prompt.
        """
        try:
            cp_str = ""
            if context_package and hasattr(context_package, "get_system_zone_content"):
                try:
                    cp_str = context_package.get_system_zone_content() or ""
                except Exception:
                    pass

            # Working memory: include what earlier steps found this session.
            # Uses ContextManager.render() which applies compression at 80% threshold.
            wm_str = ""
            try:
                if self._memory_interface:
                    wm_str = (
                        self._memory_interface.get_assembled_context(session_id) or ""
                    )
            except Exception:
                pass

            prompt = (
                f"{cp_str}\n\n"
                + (f"SESSION FINDINGS SO FAR:\n{wm_str}\n\n" if wm_str else "")
                + f"OBJECTIVE: {item.objective_anchor}\n"
                f"STEP {item.step_number}: {item.description}\n\n"
                "Complete this step. Respond with the result only."
            ).strip()
            result = self.infer(
                prompt, role="EXECUTION", max_tokens=512, temperature=0.3
            )
            return result.raw_text or f"[step {item.step_number} completed]"
        except Exception as _e:
            return f"[step {item.step_number} error: {_e}]"

    # ── Phase 3: explorer methods ──────────────────────────────────────

    def _der_plan_next_step(
        self,
        task_objective: str,
        completed_items: List,
        mode: "ExecutionMode",
        turn_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        After all planned steps are done, ask the LLM if more tools are
        needed to satisfy the original objective.

        Returns a dict with 'tool', 'description', 'params' if another
        tool is needed, or None if done.

        This is the key method for AGENTIC mode — it enables the multi-step
        tool loop without a hardcoded limit.
        """
        try:
            if not completed_items:
                return None

            from backend.agent.der_constants import ExecutionMode

            # Build a summary of what was done
            done_summary = "\n".join(
                f"  Step {i.step_number}: {i.description}"
                for i in completed_items[-10:]
            )

            prompt = (
                "You are the Explorer. Your job is to decide if more work is needed.\n\n"
                f"OBJECTIVE: {task_objective}\n\n"
                f"STEPS COMPLETED ({len(completed_items)} total):\n{done_summary}\n\n"
                f"Current mode: {mode.value if isinstance(mode, (str, ExecutionMode)) else 'agentic'}\n\n"
                "Is the objective fully met? If yes, respond with {\"done\": true}.\n"
                "If no, what single tool should run next? Respond with:\n"
                '{"done": false, "tool": "tool_name", "description": "what to do", '
                '"params": {"key": "value"}}\n'
                "Choose the tool that makes the most progress toward the objective.\n"
                "Be specific about parameters.\n\n"
                "Respond with JSON only."
            )

            response = self.infer(
                prompt, role="EXECUTION", max_tokens=400, temperature=0.1
            )
            raw = response.raw_text or ""

            # Parse JSON from response
            import re
            import json as _json

            m = re.search(r"\{[\s\S]+\}", raw)
            if not m:
                return None

            data = _json.loads(m.group())
            if data.get("done") is True:
                return None

            return {
                "tool": data.get("tool"),
                "description": data.get("description", "Continue"),
                "params": data.get("params", {}),
            }

        except Exception as exc:
            logger.warning(
                "[DER] _der_plan_next_step failed: %s", exc
            )
            return None

    def _der_check_full_progress(
        self,
        task_objective: str,
        completed_items: List,
        turn_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        FULL mode: check overall task progress and return a synthesis
        suggestion if the task is drifting.  Returns None if on track.
        Called every 3 steps in FULL mode.
        """
        try:
            if len(completed_items) < 2:
                return None

            done_summary = "\n".join(
                f"  {i.step_number}. {i.description}"
                for i in completed_items[-5:]
            )

            prompt = (
                "You are the Director's navigator. Assess progress so far.\n\n"
                f"OBJECTIVE: {task_objective}\n\n"
                f"STEPS DONE ({len(completed_items)}):\n{done_summary}\n\n"
                "Is the task on track toward completion? Are we drifting or stuck?\n"
                "Respond with JSON only:\n"
                '{"on_track": true|false, "note": "short assessment", '
                '"suggestion": "what to do next if not on track"}'
            )

            response = self.infer(
                prompt, role="EXECUTION", max_tokens=300, temperature=0.1
            )
            raw = response.raw_text or ""

            import re as _re
            import json as _json

            m = _re.search(r"\{[\s\S]+\}", raw)
            if m:
                data = _json.loads(m.group())
                if not data.get("on_track", True):
                    note = data.get("note", "")
                    suggestion = data.get("suggestion", "")
                    logger.info(
                        "[DER] FULL mode progress check — drift detected: %s", note
                    )
                    if suggestion:
                        # The suggestion is logged for debugging but not
                        # automatically applied — the Director decides.
                        logger.info(
                            "[DER] FULL mode suggestion: %s", suggestion
                        )
                    return note
            return None

        except Exception as exc:
            logger.warning(
                "[DER] _der_check_full_progress failed: %s", exc
            )
            return None

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
                    execution_model = self._model_router.models.get(
                        self._selected_tool_execution_model
                    )
                    if execution_model:
                        logger.info(
                            f"[AgentKernel] Using user-selected tool execution model: {self._selected_tool_execution_model}"
                        )
                    else:
                        # Only fall back to default stub when Ollama/VPS won't handle it.
                        _sel_exec_check = self._selected_tool_execution_model
                        _ollama_exec_will_handle = ":" in _sel_exec_check
                        _vps_exec_will_handle = bool(self._vps_gateway)
                        _lmstudio_exec_will_handle = self._is_openai_compat()
                        if (
                            not _ollama_exec_will_handle
                            and not _vps_exec_will_handle
                            and not _lmstudio_exec_will_handle
                        ):
                            logger.warning(
                                f"[AgentKernel] Selected model {_sel_exec_check} unavailable, "
                                "falling back to default local execution model"
                            )
                            execution_model = self._model_router.get_execution_model()
                            if execution_model:
                                default_model_id = getattr(
                                    execution_model, "model_id", "unknown"
                                )
                                logger.info(
                                    f"[AgentKernel] Fallback: using default execution model {default_model_id}"
                                )
                        else:
                            _exec_dest = (
                                "LM Studio"
                                if _lmstudio_exec_will_handle
                                else ("Ollama" if _ollama_exec_will_handle else "VPS")
                            )
                            logger.info(
                                f"[AgentKernel] Exec model '{_sel_exec_check}' not in local cache — "
                                f"will route to {_exec_dest}"
                            )
                else:
                    # No model selected — use default execution model
                    execution_model = self._model_router.get_execution_model()
                    if execution_model:
                        default_model_id = getattr(
                            execution_model, "model_id", "unknown"
                        )
                        logger.info(
                            f"[AgentKernel] No model selected, using default tool execution model: {default_model_id}"
                        )
            except Exception as e:
                logger.error(f"[AgentKernel] Error getting execution model: {e}")
                return {
                    "error": f"Failed to access execution model: {e}",
                    "success": False,
                }

        # Handle model unavailability
        if not execution_model:
            if self._single_model_mode and self._available_model_id:
                # Fall back to the single available local model
                logger.warning(
                    "[AgentKernel] Execution model unavailable, using fallback model"
                )
                try:
                    execution_model = self._model_router.models.get(
                        self._available_model_id
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Error accessing fallback model: {e}")
                    return {
                        "error": f"Failed to access fallback model: {e}",
                        "success": False,
                    }
            elif self._is_openai_compat():
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
                            logger.warning(
                                f"[AgentKernel] Lazy load (exec) failed: {_le}"
                            )
                    execution_model = self._model_router.models.get(_sel_exec)
                    if execution_model is None:
                        _all_exec = list(self._model_router.models.values())
                        if _all_exec:
                            # prefer last (smallest/fastest)
                            execution_model = _all_exec[-1]
                    if not execution_model:
                        return {
                            "error": "Execution model not available",
                            "success": False,
                        }
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
                    logger.info(
                        "[AgentKernel] Using VPS Gateway for execution inference..."
                    )
                    try:
                        result_text = asyncio.run(
                            self._vps_gateway.infer(
                                model=self._model_router.get_execution_model_id()
                                or "lfm2.5-1.2b-instruct",
                                prompt=execution_prompt,
                                context={},
                                params={"max_tokens": 512, "temperature": 0.3},
                                session_id=self.session_id,
                            )
                        )
                        logger.info(
                            "[AgentKernel] VPS Gateway execution inference complete"
                        )
                    except RuntimeError as e:
                        if "already running" in str(e):
                            logger.warning(
                                "[AgentKernel] Event loop conflict — falling back to local model"
                            )
                            result_text = None
                        else:
                            raise
                except TimeoutError:
                    logger.error("[AgentKernel] VPS Gateway execution timed out")
                    raise
                except Exception as e:
                    logger.warning(
                        f"[AgentKernel] VPS Gateway execution inference failed, falling back to direct model: {e}"
                    )
                    result_text = None

            # LM Studio execution inference
            if result_text is None and self._is_openai_compat():
                try:
                    _lms_exec = self._get_lmstudio_client()
                    _lms_exec_resp = _lms_exec.chat.completions.create(
                        model=self._selected_tool_execution_model or "local-model",
                        messages=[{"role": "user", "content": execution_prompt}],
                        max_tokens=-1,
                        temperature=0.3,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    result_text = _lms_exec_resp.choices[0].message.content
                    logger.info(
                        "[AgentKernel] LM Studio execution inference successful"
                    )
                except Exception as _lms_exec_err:
                    logger.warning(
                        f"[AgentKernel] LM Studio execution inference failed: {_lms_exec_err}"
                    )

            # Ollama local execution inference — only for colon-format model IDs.
            # provider="local" means LFM local file; it does NOT route to Ollama.
            if (
                result_text is None
                and self._selected_tool_execution_model
                and (":" in self._selected_tool_execution_model)
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
                            _ollama_exec_resp.json()
                            .get("message", {})
                            .get("content", "")
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
                        "success": False,
                    }

                # Check timeout before inference
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Execution timed out after {elapsed:.1f}s")

                # Generate execution response with error handling
                try:
                    result_text = execution_model.generate(
                        execution_prompt, max_tokens=-1, temperature=0.3
                    )
                except Exception as e:
                    logger.error(f"[AgentKernel] Model inference failed: {e}")
                    # Attempt to restart model
                    try:
                        logger.info(
                            "[AgentKernel] Attempting to restart execution model..."
                        )
                        execution_model.unload()
                        execution_model.load()
                        result_text = execution_model.generate(
                            execution_prompt, max_tokens=-1, temperature=0.3
                        )
                        logger.info("[AgentKernel] Model restarted successfully")
                    except Exception as restart_error:
                        logger.error(
                            f"[AgentKernel] Model restart failed: {restart_error}"
                        )
                        return {
                            "tool": tool_name,
                            "action": action,
                            "error": f"Model crashed and restart failed: {restart_error}",
                            "success": False,
                        }

            # Check timeout after inference
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Execution timed out after {elapsed:.1f}s")

            # Handle tool execution errors
            if self._tool_bridge:
                try:
                    # Execute tool through tool bridge
                    tool_result = await self._tool_bridge.execute_tool(
                        tool_name, parameters
                    )
                    if "error" in tool_result:
                        logger.warning(
                            f"[AgentKernel] Tool execution error: {tool_result['error']}"
                        )
                        return {
                            "tool": tool_name,
                            "action": action,
                            "error": tool_result["error"],
                            "success": False,
                        }
                except Exception as e:
                    logger.error(f"[AgentKernel] Tool execution failed: {e}")
                    return {
                        "tool": tool_name,
                        "action": action,
                        "error": f"Tool execution failed: {e}",
                        "success": False,
                    }

            logger.info(f"[AgentKernel] Step executed successfully in {elapsed:.2f}s")
            return {
                "tool": tool_name,
                "action": action,
                "result": result_text,
                "success": True,
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
                "success": False,
            }

    def _generate_response(
        self,
        user_message: str,
        plan: Dict[str, Any],
        execution_results: List[Any],
        context: List[Dict[str, Any]],
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
            r
            for r in execution_results
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
                summary_parts.append(
                    f"- {r.get('action', 'Action')}: {r['result'][:100]}"
                )
            elif "response" in r:
                summary_parts.append(f"- {r['response'][:100]}")

        if summary_parts:
            return "I've completed your request:\n\n" + "\n".join(summary_parts)

        return "I've processed your request."

    def _synthesize_response(
        self, task: TaskContext, execution_results: List[Any]
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
                reasoning_model = self._model_router.models.get(
                    self._selected_reasoning_model
                )

            if reasoning_model:
                # Call the loaded local/LFM model for synthesis
                response = self._strip_thinking(
                    reasoning_model.generate(synthesis_prompt)
                )
                logger.info(
                    "[AgentKernel] Brain synthesized response with tool results context"
                )
                return response

            # Try LM Studio synthesis
            _sel_synth = self._selected_reasoning_model or ""
            if not reasoning_model and self._is_openai_compat():
                try:
                    _lms_synth = self._get_lmstudio_client()
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
                    logger.warning(
                        f"[AgentKernel] LM Studio synthesis failed: {_lms_synth_err}"
                    )

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
                    logger.warning(
                        f"[AgentKernel] Ollama synthesis failed: {_ollama_synth_err}"
                    )

            # Template-based fallback (no model available)
            logger.warning(
                "[AgentKernel] No model for synthesis — using template response"
            )
            return self._generate_response(
                task.user_message,
                task.plan,
                execution_results,
                task.conversation_history,
            )

        except Exception as e:
            logger.error(f"[AgentKernel] Error in brain synthesis: {e}")
            return self._generate_response(
                task.user_message,
                task.plan,
                execution_results,
                task.conversation_history,
            )

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
            "error": self._initialization_error,
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
                status["vps_gateway"] = {"enabled": False, "error": str(e)}
        else:
            status["vps_gateway"] = {"enabled": False, "available_endpoints": 0}

        return status

    def clear_conversation(self) -> None:
        """Clear conversation history for the current session."""
        if self._conversation_memory:
            self._conversation_memory.clear()
            logger.info(
                f"[AgentKernel] Conversation cleared for session {self.session_id}"
            )

    def get_conversation_context(
        self, max_messages: Optional[int] = None
    ) -> List[Dict[str, Any]]:
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
        "executor": "lfm2.5-1.2b-instruct",
        # NOTE: LFM2-8B-A1B / "brain" / "lfm2-8b" aliases are intentionally absent.
        # That model is not in use — removing the aliases prevents accidental routing.
    }

    def _normalize_model_id(self, model_id: Optional[str]) -> Optional[str]:
        """Translate legacy or local model IDs to their canonical identifiers."""
        if model_id is None:
            return None
        normalized = self._MODEL_ALIASES.get(model_id, model_id)
        if normalized != model_id:
            logger.debug(
                f"[AgentKernel] Model ID alias resolved: '{model_id}' -> '{normalized}'"
            )
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
            # Swarm mode is the highest-priority configuration.
            # If swarm is enabled, do NOT let the Models card overwrite
            # provider='iris_local' or the swarm model names back to UI selections.
            if getattr(self, "_swarm_enabled", False):
                if reasoning_model or tool_execution_model or model_provider:
                    logger.info(
                        f"[AgentKernel] Swarm is enabled — ignoring model_selection "
                        f"from Models card (keeping provider='{self._model_provider}', "
                        f"reasoning='{self._selected_reasoning_model}', "
                        f"tool='{self._selected_tool_execution_model}')"
                    )
            else:
                self._selected_reasoning_model = reasoning_model
                self._selected_tool_execution_model = tool_execution_model
                if model_provider:
                    self._model_provider = model_provider

            ctx_window = self.resolve_context_window()
            token_budget = self.get_effective_token_budget()

            # Propagate context window to memory system
            self._sync_context_window()

            logger.info(
                f"[AgentKernel] Model selection updated: reasoning={reasoning_model}, "
                f"tool_execution={tool_execution_model}, provider={self._model_provider}, "
                f"context_window={ctx_window}, token_budget={token_budget}"
            )

            logger.info(
                f"[AgentKernel] Model selection updated: reasoning={reasoning_model}, "
                f"tool_execution={tool_execution_model}, provider={self._model_provider}, "
                f"context_window={ctx_window}, token_budget={token_budget}"
            )

            # Propagate to all peer kernels so secondary sessions (e.g.
            # session_iris_integration used by the wake-word path) stay in sync
            # with the model the user just selected in the main UI session.
            for peer_id, peer_kernel in _agent_kernel_instances.items():
                if peer_kernel is not self:
                    if getattr(peer_kernel, "_swarm_enabled", False):
                        logger.debug(
                            f"[AgentKernel] Peer '{peer_id}' swarm enabled — "
                            f"skipping model_selection overwrite"
                        )
                        continue
                    peer_kernel._selected_reasoning_model = reasoning_model
                    peer_kernel._selected_tool_execution_model = tool_execution_model
                    if model_provider:
                        peer_kernel._model_provider = model_provider
                    # Propagate API credentials so peers can call infer()
                    # through the API provider path (Cohere, OpenAI, Groq, etc.)
                    if self._api_key:
                        peer_kernel._api_key = self._api_key
                    if self._api_base_url:
                        peer_kernel._api_base_url = self._api_base_url
                    if self._lmstudio_endpoint:
                        peer_kernel._lmstudio_endpoint = self._lmstudio_endpoint
                    peer_kernel._context_window_overrides = dict(
                        self._context_window_overrides
                    )
                    logger.debug(
                        f"[AgentKernel] Propagated model config to peer session '{peer_id}'"
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
            "tool_execution_model": self._selected_tool_execution_model,
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
        logger.info(
            f"[AgentKernel] Agent internet access {'enabled' if enabled else 'disabled'}"
        )
        logger.info(
            "[AgentKernel] Note: This controls agent web search tools, not application connectivity"
        )

    def get_internet_access(self) -> bool:
        """
        Get current internet access setting.

        Returns:
            True if internet access is enabled, False otherwise
        """
        return self._internet_access_enabled

    def set_swarm_enabled(self, enabled: bool) -> None:
        """
        Enable or disable multi-agent swarm compound collaboration.
        Initialises SwarmCoordinator and ContextControlHandler lazily on first enable.
        """
        self._swarm_enabled = enabled
        if (
            enabled
            and self._memory_interface is not None
            and self._swarm_coordinator is None
        ):
            try:
                from backend.agent.swarm import SwarmCoordinator, ContextControlHandler
                from backend.agent.mcm import MCM

                _mcm = MCM(self._memory_interface, self.session_id)
                _protocol = self._mcm_orch._protocol if self._mcm_orch else None
                self._swarm_coordinator = SwarmCoordinator(
                    memory_interface=self._memory_interface,
                    session_id=self.session_id,
                    agent_id=self.session_id,
                    protocol=_protocol,
                )
                self._context_control_handler = ContextControlHandler(
                    memory_interface=self._memory_interface,
                    mcm_instance=_mcm,
                    session_id=self.session_id,
                )
                logger.info(
                    "[AgentKernel] SwarmCoordinator + ContextControlHandler initialized"
                )
            except Exception as _swarm_err:
                logger.warning("[AgentKernel] Swarm init failed: %s", _swarm_err)
        logger.info("[AgentKernel] Swarm %s", "enabled" if enabled else "disabled")

    def get_swarm_enabled(self) -> bool:
        """Return current swarm enabled state."""
        return self._swarm_enabled

    def _handle_control_codes(self, response_text: str, messages: list) -> list:
        """
        Scan response for MCM: control codes (MCM:999/998/997/996) and execute.
        Called after every agent response when swarm is enabled.
        Never raises. Returns messages (potentially modified by MCM:999 prune).
        """
        if not self._swarm_enabled or self._context_control_handler is None:
            return messages
        try:
            self._context_control_handler.scan_and_execute(
                response_text,
                messages,
                self._current_task if hasattr(self, "_current_task") else "",
            )
        except Exception:
            pass
        return messages


# Singleton instance management
_agent_kernel_instances: Dict[str, AgentKernel] = {}

# Last-known-good swarm configuration snapshot.
# When a new session's kernel is created after swarm mode has already been
# configured, it reads from this snapshot instead of relying on peer
# inheritance (which fails if all peers were also created post-swarm).
_swarm_config_snapshot: Optional[dict] = None


def get_agent_kernel(
    conversation_id: str = "default",
    session_id: Optional[str] = None,
) -> AgentKernel:
    """
    Get or create an AgentKernel instance for a conversation.
    Auto-wires the memory interface (Pillar 4) when a new kernel is created.

    Re-keyed from session_id to conversation_id for multi-thread context.
    session_id is preserved for WS routing and Mycelium ingestion.

    Args:
        conversation_id: Primary key — one kernel per conversation thread.
        session_id: Transport label for WS routing and Mycelium.
                    If None, falls back to conversation_id.

    Returns:
        AgentKernel instance for the conversation
    """
    global _agent_kernel_instances

    _sid = session_id or conversation_id

    if conversation_id not in _agent_kernel_instances:
        kernel = AgentKernel(
            session_id=_sid,
            conversation_id=conversation_id,
        )

        # Auto-wire Pillar 4 (Memory) — connects episodic/semantic memory to every session
        try:
            from backend.memory import get_memory_interface

            memory = get_memory_interface()
            if memory is not None:
                kernel.set_memory_interface(memory)
                logger.info(
                    f"[AgentKernel] Memory interface wired for conv={conversation_id}"
                )
        except Exception as e:
            logger.warning(
                f"[AgentKernel] Memory interface not available for conv={conversation_id}: {e}"
            )

        # Inherit model configuration from any already-configured kernel.
        #
        # Context: the user configures a model once (in session_iris / the main UI
        # session).  Secondary sessions — such as session_iris_integration which is
        # created when the wake-word fires — are spun up lazily with no model
        # provider set.  Without this inheritance every wake-word-triggered response
        # returns None from _respond_direct, crashing the voice pipeline.
        #
        # We look for the first peer kernel whose provider is not the default
        # "uninitialized" sentinel and copy its full model configuration.
        if kernel._model_provider == "uninitialized":
            for peer_key, peer_kernel in _agent_kernel_instances.items():
                if peer_kernel._model_provider not in (None, "uninitialized"):
                    kernel.set_model_selection(
                        reasoning_model=peer_kernel._selected_reasoning_model,
                        tool_execution_model=peer_kernel._selected_tool_execution_model,
                        model_provider=peer_kernel._model_provider,
                    )
                    # Also copy the LM Studio endpoint in case it was customised.
                    kernel._lmstudio_endpoint = peer_kernel._lmstudio_endpoint
                    # Copy API configuration for remote API providers.
                    if peer_kernel._api_key:
                        kernel._api_key = peer_kernel._api_key
                    if peer_kernel._api_base_url:
                        kernel._api_base_url = peer_kernel._api_base_url
                    # Also copy inference behaviour settings so all sessions share them.
                    kernel._thinking_style = peer_kernel._thinking_style
                    kernel._response_length = peer_kernel._response_length
                    kernel._reasoning_effort = peer_kernel._reasoning_effort
                    kernel._tool_mode = peer_kernel._tool_mode
                    logger.info(
                        f"[AgentKernel] Conv '{conversation_id}' inherited model config "
                        f"from '{peer_key}' "
                        f"(provider={peer_kernel._model_provider!r}, "
                        f"model={peer_kernel._selected_reasoning_model!r})"
                    )
                    break

            # If no peer was configured but a global swarm snapshot exists,
            # auto-hydrate this kernel so it doesn't stay "uninitialized".
            if (
                kernel._model_provider == "uninitialized"
                and _swarm_config_snapshot is not None
            ):
                kernel.configure_openai_compat(
                    _swarm_config_snapshot.get("endpoint"),
                    provider_name="iris_local",
                )
                kernel._selected_reasoning_model = _swarm_config_snapshot.get(
                    "reasoning_model"
                )
                kernel._selected_tool_execution_model = _swarm_config_snapshot.get(
                    "tool_model"
                )
                kernel._swarm_enabled = True
                logger.info(
                    f"[AgentKernel] Conv '{conversation_id}' auto-hydrated from "
                    f"swarm snapshot (provider='iris_local', "
                    f"endpoint={_swarm_config_snapshot.get('endpoint')!r})"
                )

        _agent_kernel_instances[conversation_id] = kernel

    return _agent_kernel_instances[conversation_id]


def cleanup_agent_kernel(
    conversation_id: str,
    session_id: Optional[str] = None,
) -> None:
    """
    Remove the AgentKernel instance for a conversation and release its resources.

    Call this when a conversation expires or is deleted.
    Keyed by conversation_id (re-keyed from session_id).

    Args:
        conversation_id: Conversation whose kernel should be cleaned up
        session_id: Optional session label for logging
    """
    global _agent_kernel_instances
    kernel = _agent_kernel_instances.pop(conversation_id, None)
    _log_id = session_id or conversation_id
    if kernel is not None:
        try:
            # Save any pending context to the store
            try:
                kernel.save_context_to_store()
            except Exception:
                pass
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
            logger.warning(
                f"[AgentKernel] Error during cleanup for conv {_log_id}: {e}"
            )
        logger.info(f"[AgentKernel] Kernel cleaned up for conv {_log_id}")
