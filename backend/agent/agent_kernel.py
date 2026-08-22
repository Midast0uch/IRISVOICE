#!/usr/bin/env python3
"""
Agent Kernel

Orchestrates the dual-LLM system with:
- lfm2-8b for reasoning and planning
- lfm2.5-1.2b-instruct for tool execution
- Inter-model communication and state management
- Model failure fallback to single-model mode
"""

from __future__ import annotations

import re
import hashlib
import threading
import os

from .model_conversation import ModelConversation
from .inter_model_communication import InterModelCommunicator
from .vps_gateway import VPSGateway, VPSConfig
from .personality import PersonalityManager
from .memory import ConversationMemory, TaskRecord
from .model_router import ModelRouter
from .tool_bridge import AgentToolBridge
from .mcm_protocol.actions.pacman_fragment import is_external_tool
try:
    from backend.llm_service import llm as _llm
except ImportError:  # top-level import (tests run with backend/ on sys.path)
    from llm_service import llm as _llm
from . import streaming as _streaming
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.errors import RateLimitedError
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
from backend.agent.batch_dispatch import get_batcher
from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind, DispatchResult
from backend.iris_config import load_config
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
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

# Per-session update counter for homeostatic relaxation cadence (REQ-1 AC2).
# Keyed by session_id, incremented each time _der_finalize_step processes a
# non-exception step. Reset is implicit â€” a new session starts at 0.
_update_counters: Dict[str, int] = {}
_update_counters_lock = threading.Lock()

# â”€â”€ DER Loop constants (spec: agent_loop_requirements.md Gap 11) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Canonical values live in der_constants.py â€” re-exported here for spec
# compliance so module-level code that imports from agent_kernel finds them.
try:
    from backend.agent.der_constants import (
        DER_MAX_CYCLES,
        DER_MAX_VETO_PER_ITEM,
        DER_MAX_GRAFTS,
        DER_MAX_CONCURRENT_STEPS,
        DER_MAX_UNVERIFIED_REPROPOSE,
        DER_FOLD_BACK_MAX,
        DER_EMERGENCY_STOP,
        DER_TOKEN_BUDGETS,
        TRAILING_GAP_MIN,
        AVG_STEP_COST,
        debit_work_units,
        derive_work_units_0,
        resolve_der_token_budget,
        ResolvedWindow,
        ExecutionMode,
    )
except Exception:
    DER_MAX_CYCLES = 40
    DER_MAX_VETO_PER_ITEM = 2
    DER_MAX_GRAFTS = 3
    DER_FOLD_BACK_MAX = 3
    DER_MAX_UNVERIFIED_REPROPOSE = 1
    DER_EMERGENCY_STOP = 200
    DER_TOKEN_BUDGETS: Dict[str, int] = {
        "implement": 40000,
        "debug": 30000,
        "research": 20000,
        "full": 50000,
        "quick_edit": 8000,
    }
    TRAILING_GAP_MIN = 2
    AVG_STEP_COST = 1500

    def derive_work_units_0(context_window: int) -> int:
        return max(1, int(context_window / AVG_STEP_COST))

    def resolve_der_token_budget(context_window: int, task_class=None) -> int:
        # Mirrors der_constants.resolve_der_token_budget: mode value is a
        # CEILING, the window is the hard cap, the floor is applied last and is
        # itself clamped by the window so it can never overcommit.
        _cap = max(int(context_window * 0.9), 1)
        _ceiling = DER_TOKEN_BUDGETS.get(task_class, DER_TOKEN_BUDGETS.get("full", 50000))
        return max(min(_ceiling, _cap), min(4000, _cap))

    def is_shallow_verified(depth_layer: int, result_tokens: int, task_class) -> bool:
        # Mirrors der_constants.is_shallow_verified (REQ-5) for the import-guard
        # fallback path. Excluded classes never flag (AC3).
        if task_class and str(task_class).lower() in (
            "question", "greeting", "simple_command",
        ):
            return False
        return depth_layer <= 1 and result_tokens < 400

# REQ-1 AC8 (T2b, Decision 13 â€” revised 2026-08-19): the user-facing copy for
# the child steps of a sub-loop split. `branchLabel` is free text on the
# wire â€” CardChassis's ChassisBranchBadge renders whatever string arrives
# here, so the wording is owned in this ONE constant, not inlined at each
# emit site. NEVER "Sub-Loop" / "Detour" â€” those remain internal identifiers
# (sub_loop_split / is_subloop) and are UNCHANGED; this is the user-facing
# label only.
DER_SUBLOOP_BRANCH_LABEL = "Diving Deeper"

@dataclass
class TaskContext:
    """
    Carries full context through the entire task pipeline.

    This is the single object that carries context from the user's message
    through planning, execution, and response synthesis. It prevents context
    loss at handoff points between the brain and executor models.
    """

    task_id: str  # unique per user message
    user_message: str  # original user request â€” never lost
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


def _resolve_effective_key(
    *,
    api_key: Optional[str],
    kernel_key: str,
    kernel_key_provider: str,
    model_provider: Optional[str],
) -> str:
    """Resolve the credential a provider instance should carry.

    A freshly supplied ``api_key`` always wins. Otherwise the kernel's cached
    key (``kernel_key``) is reused ONLY when it belongs to the same provider
    (``kernel_key_provider == model_provider``). The kernel's ``_api_key`` is a
    single shared field holding the LAST applied key regardless of provider; a
    blanket fallback attaches, e.g., a Cerebras key to a Cohere provider
    instance, which then 401s at call time even though the keyring is correct.

    Pure function â€” unit-testable without constructing an AgentKernel.
    """
    if api_key:
        return api_key
    if kernel_key and kernel_key_provider and kernel_key_provider == model_provider:
        return kernel_key
    return ""


# Formatting rules appended to every prompt that produces USER-FACING prose.
#
# Models do not reliably structure a long answer on their own â€” a multi-tool
# result came back as one unbroken block, which is unreadable in a chat thread
# (2026-08-16). The reply is rendered as markdown, so ask for the structure
# explicitly, and scale it: a one-line answer must NOT grow headings.
_READABLE_FORMAT_RULES = """FORMATTING (your reply is rendered as markdown in a chat thread):
- Short answer (a sentence or two)? Write it plainly. No headings, no bullets.
- Longer answer? Make it scannable instead of one block of prose:
  - open with a short sentence saying what you found
  - `##` headings to separate distinct topics
  - `-` bullets for lists of findings
  - a markdown table for field/value pairs (specs, settings, counts)
  - `backticks` for paths, commands, filenames and code
  - a blank line between blocks â€” never run sections together
- Structure only where it aids reading. Do not pad a short answer to fill it.
- Report what the tools actually returned. If something was not returned, say
  so plainly rather than filling the gap."""


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

        # REQ-6: per-conversation soft-cancel flag. Set by the gateway when the
        # user switches away from this thread (switch_conversation / sync_state /
        # new_conversation / clear_chat). The DER loop polls this between steps and
        # exits cleanly without emitting further events for this conversation.
        self._cancel_requested = threading.Event()

        # W6 (T27-T29): per-conversation DER lock â€” prevents concurrent DER
        # execution on the same conversation. Accessed via _conversation_der_locks
        # class-level dict keyed by conversation_id.
        self._der_active = False

        # Structured logger (module-level logger bound to the instance so the
        # DER soft-cancel path and any other self._logger call sites work).
        self._logger = logging.getLogger(__name__)

        # Core components
        self._model_router: Optional[ModelRouter] = None
        self._vps_gateway: Optional[VPSGateway] = None
        self._conversation_memory: Optional[ConversationMemory] = None
        self._personality: Optional[PersonalityManager] = None
        self._tool_bridge: Optional[AgentToolBridge] = (
            None  # Will be initialized lazily
        )
        # For brainâ†”executor logging
        self._inter_model_communicator: Optional[InterModelCommunicator] = None

        # State management
        self._single_model_mode = False
        self._available_model_id: Optional[str] = None
        self._initialization_error: Optional[str] = None

        # Model selection (user-configurable dual-LLM)
        # NOTE (2026-08-16): `_model_provider`, `_selected_reasoning_model` and
        # `_selected_tool_execution_model` used to be assigned here and kept in
        # sync by hand from half a dozen call sites. They are now READ-ONLY
        # PROPERTIES derived from the process-wide role-binding table â€” see
        # their definitions below. A stale copy of the user's model choice is
        # not a bug that can be fixed here; it is a bug that can only be made
        # impossible, by there being no copy.

        # OpenAI-compatible endpoint â€” covers lmstudio, llamafile, vllm, or any custom server.
        # Set via configure_lmstudio() (legacy name kept) or configure_openai_compat().
        # Defaults to LM Studio's default port; overridden when the user saves settings.
        self._lmstudio_endpoint: str = "http://localhost:1234"

        # In-process `LocalModelManager` binding â€” non-None when iris_gateway
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
        # Provider id the kernel's _api_key belongs to. `_api_key` is a single
        # shared field; without this, a provider switch reuses the previous
        # provider's key (e.g. a Cerebras key attached to a Cohere instance).
        self._api_key_provider: str = ""
        self._api_base_url: str = "https://api.openai.com/v1"

        # Thinking extracted from the most recent _respond_direct call.
        # Set before returning so iris_gateway can include it in the text_response payload.
        self._pending_thinking: str = ""

        # VPS configuration (loaded from settings)
        self._vps_config: Optional[VPSConfig] = None

        # Internet access is now a global app-wide flag (see
        # set_global_internet_access / get_global_internet_access below).

        # Swarm compound collaboration (default: False â€” enabled via UI toggle)
        self._swarm_enabled: bool = False
        self._swarm_coordinator = None
        self._context_control_handler = None

        # â”€â”€ Inference behaviour fields (wired from inference_mode card) â”€â”€
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

        # â”€â”€ Model context window registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Maps (provider, model_name_substring) â†’ context window in tokens.
        # Used by resolve_context_window() so memory, conversation history,
        # and MCM budgets are never hardcoded â€” they adapt to the model.
        self._context_window_overrides: dict[str, int] = {}

        # â”€â”€ REQ-3 (T2): backend-declared task-card identity registry â”€â”€â”€â”€â”€â”€â”€â”€
        # Maps DER task_id -> card_id so the SAME task's early-skeleton and
        # DER-queue task:start emits (and every lifecycle event after it)
        # resolve to one Liquid Ink card instead of two. Bounded â€” this is a
        # per-kernel-lifetime dict, not per-turn, so it must not grow forever
        # (see _register_card's eviction).
        self._card_by_task: dict[str, str] = {}
        self._active_card_id: Optional[str] = None
        self._CARD_REGISTRY_CAP: int = 200

        # Domain 4.5 â€” proactive skill creation.
        # Tracks how many times each normalized tool-name sequence (joined with "â†’")
        # has been used this session.  When a pattern hits the threshold, the agent
        # is prompted to codify it as a SKILL.md.
        self._session_tool_patterns: dict[str, int] = {}
        self._skill_trigger_threshold: int = 3
        # Patterns already prompted this session â€” avoid repeating the prompt.
        self._prompted_skill_patterns: set[str] = set()

        # Cached OpenAI client for LM Studio â€” created once, reused on every call.
        # Rebuilding _OpenAI() per-call recreates the full httpx connection pool,
        # adding unnecessary overhead on every message.  Invalidated in
        # configure_lmstudio() whenever the endpoint URL changes.
        self._lmstudio_client: Optional[Any] = None

        # Main event loop â€” captured during startup so background threads can
        # dispatch coroutines via run_coroutine_threadsafe.
        self._broadcast_loop: Optional[Any] = None

        # Initialize components
        self._initialize_components()

        # Auto-apply a provider configured in iris_config.json so the agentic /
        # DER loop does not silently fall back to a local OpenAI-compatible model
        # when a cloud provider is already configured.  Local-only setups (no
        # provider / no key) are left uninitialized â€” the existing wait-for-user
        # (Models-card APPLY / model_selection confirm_card) behaviour is preserved.
        self._router = InferenceRouter(load_config())

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
            "[AgentKernel] VPS Gateway deferred (lazy init â€” awaiting user VPS configuration)"
        )

        try:
            # Initialize Conversation Memory
            logger.info(
                f"[AgentKernel] Initializing Conversation Memory for session {self.session_id}..."
            )
            self._conversation_memory = ConversationMemory(
                session_id=self.session_id,
                conversation_id=self.conversation_id,
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
            # Initialize Inter-Model Communicator for brainâ†”executor logging (Bug 5 fix)
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

        # MCM Protocol Orchestrator â€” wired after set_memory_interface()
        self._mcm_orch = None

        # Trust-routing (plan W2): whether the current turn touched external/
        # web sources (web_search / crawler_query). When True, turn-pair
        # fragments are stored in the 'reference' zone instead of 'trusted'.
        # Reset at the start of each turn (process_text_message /
        # _execute_plan_der) and set when an external tool runs.
        self._turn_touched_external: bool = False

        # â”€â”€ DER Loop components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
            from backend.agent.mode_detector import ModeDetector as _MD

            self._mode_detector = _MD()
            logger.info("[AgentKernel] ModeDetector initialized (DER)")
        except Exception as _md_err:
            logger.warning(f"[AgentKernel] ModeDetector unavailable: {_md_err}")

        # REQ-6 AC2 (T9): fire the bounded, latched, background LFM warm-up so
        # the first user turn runs at warm latency. Non-blocking â€” a daemon
        # thread does the load; a failure leaves the normal cold path intact.
        try:
            from backend.agent.semantic_gate import ensure_warm_start

            ensure_warm_start()
        except Exception as _wu_err:
            logger.debug("[AgentKernel] LFM warm-up kick failed: %s", _wu_err)

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

    def clear_conversation(self, conversation_id: Optional[str] = None) -> None:
        """
        Clear the agent context for a conversation â€” both the in-memory
        conversation history and the persistent store.  Called on 'new
        conversation' or thread switch cleanup so the next turn starts blank.

        Never raises â€” logs warning on failure.
        """
        _cid = conversation_id or getattr(self, "conversation_id", None)
        # Reset in-memory history immediately so a reused kernel instance
        # cannot leak the previous thread's messages into the new one.
        if self._conversation_memory is not None:
            try:
                self._conversation_memory.clear()
            except Exception as _mem_exc:
                logger.warning(
                    f"[AgentKernel] in-memory clear failed for {_cid}: {_mem_exc}"
                )
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
        """Persist current conversation context (history + token state) to the
        store (best-effort). Serializes the full message list so a later
        restore can rebuild the thread's conversation history."""
        try:
            from backend.agent.conversation_context_store import (
                get_context_store,
                ConversationContext,
                ConversationMessage,
            )

            store = get_context_store()
            _msgs = []
            if self._conversation_memory is not None:
                for _m in self._conversation_memory.messages:
                    _msgs.append(
                        ConversationMessage(
                            role=getattr(_m, "role", "user"),
                            content=getattr(_m, "content", "") or "",
                            timestamp=getattr(_m, "timestamp", time.time()),
                            turn_id=getattr(_m, "task_id", None),
                        )
                    )
            ctx = ConversationContext(
                conversation_id=self.conversation_id,
                messages=_msgs,
                tokens_used=getattr(self, "_tokens_used", 0),
            )
            store.save(self.conversation_id, ctx)
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] save_context_to_store failed "
                f"for conv={self.conversation_id}: {exc}"
            )

    def restore_context_from_store(self) -> None:
        """Restore conversation context (history + token state) from the store
        (best-effort). Rebuilds self._conversation_memory from the persisted
        message list so a resumed thread keeps its full history."""
        try:
            from backend.agent.conversation_context_store import get_context_store

            store = get_context_store()
            ctx = store.get_or_restore(self.conversation_id)
            if ctx:
                self._tokens_used = ctx.tokens_used
                if ctx.messages and self._conversation_memory is not None:
                    self._conversation_memory.clear()
                    for _m in ctx.messages:
                        self._conversation_memory.add_message(
                            _m.role,
                            _m.content,
                            turn_id=getattr(_m, "turn_id", None),
                        )
                logger.info(
                    f"[AgentKernel] Restored context for conv={self.conversation_id} "
                    f"(messages={len(ctx.messages)}, tokens_used={ctx.tokens_used})"
                )
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] restore_context_from_store failed "
                f"for conv={self.conversation_id}: {exc}"
            )

    def _accrue_tokens(
        self,
        response_text: str,
        usage: Optional[Dict[str, Any]] = None,
        *,
        source: str = "",
    ) -> None:
        """Add this inference call's cost to the pill's real counter (D1 fix).

        The ContextPill reads ``self._tokens_used`` (see ``_emit_context_usage``),
        but nothing ever incremented it from a LIVE call â€” only
        ``restore_context_from_store`` ever set it (from a persisted snapshot),
        so a brand-new or freshly-restored turn stayed frozen at whatever it
        was restored to, through an entire real turn.

        *usage* is the REAL per-call usage dict parsed by the transport
        (``InferenceRouter.last_usage`` â€” prompt/completion/total tokens from
        the provider's own response). It always wins when present. Only when
        the provider/local model omits usage entirely do we fall back to the
        char/4 heuristic â€” and that fallback is logged as an estimate so real
        and estimated increments are never silently blended.
        """
        try:
            if usage and usage.get("total_tokens"):
                _add = int(usage["total_tokens"])
                _kind = "real"
            else:
                _add = max(1, len(response_text or "") // 4)
                _kind = "estimate"
            self._tokens_used = int(getattr(self, "_tokens_used", 0) or 0) + _add
            logger.info(
                "[AgentKernel._accrue_tokens] +%d (%s, source=%s) tokens_used=%d",
                _add, _kind, source or "?", self._tokens_used,
            )
        except Exception as _e:  # pragma: no cover â€” accounting must never break a turn
            logger.debug("[AgentKernel._accrue_tokens] failed: %s", _e)

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
        Never raises â€” returns empty-text object on any backend failure.
        Routes through the same backend as the agentic loop.
        """

        class _InferResult:
            def __init__(self, raw_text: str):
                self.raw_text = raw_text

        try:
            if not prompt or not prompt.strip():
                return _InferResult("")

            messages = [{"role": "user", "content": prompt}]
            text, _thinking, _tool_calls = self._router.generate(
                role, messages,
                max_tokens=max_tokens, temperature=temperature,
            )
            self._accrue_tokens(
                text, getattr(self._router, "last_usage", None), source="infer"
            )
            return _InferResult(raw_text=text)
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
        except Exception as e:
            logger.warning(f"[AgentKernel] Failed to get memory context: {e}")
            return ""

        # T8c (REQ-10 AC5): emit an episodic memory event so the card's memory
        # slot renders REAL episodic retrieval (never fabricated). Fire-and-
        # forget and OFF the inference hot path â€” a bus failure must never
        # affect the returned context.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.MEMORY_EVENT,
                data={
                    "kind": "episodic",
                    "data": {
                        "task_summary": (task or "")[:120],
                        "outcome_type": "recall",
                        "duration_ms": 0,
                    },
                },
                session_id=self.session_id,
                # Session 245 (card-sync fix): without this the gateway stamps
                # "default" and the frontend files the event under a
                # conversation bucket the visible card is not in.
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        return context

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
                # VPS disabled â€” clear any existing gateway to stop health checks
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
        _get_lmstudio_client() always appends /v1 itself â€” never double-append.
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
        self._lmstudio_client = None  # invalidate cached client â€” endpoint changed
        self._sync_context_window()
        logger.info(
            f"[AgentKernel] OpenAI-compatible endpoint configured: {self._lmstudio_endpoint}"
        )

    def configure_openai_compat(
        self, endpoint: Optional[str], provider_name: str = "openai_compatible"
    ) -> None:
        """Configure any OpenAI-compatible inference server.

        Passing endpoint=None clears the endpoint (e.g. after model unload).
        Safe to call with None â€” never raises AttributeError.

        Sets the ENDPOINT only. It used to also assign ``_model_provider``, but
        that field is now derived from the role binding, and this function is
        not a binding authority â€” the swarm/local handlers that call it wire the
        router themselves (``_handle_swarm_action``, the local-load path). The
        assignment was vestigial and could disagree with actual routing: it
        reported ``"uninitialized"`` after an unload while the router happily
        went on resolving the role to a live provider.
        """
        self._lmstudio_endpoint = self._normalise_endpoint(endpoint)
        self._lmstudio_client = None
        if endpoint:
            logger.info(
                f"[AgentKernel] {provider_name} endpoint configured: {self._lmstudio_endpoint}"
            )
        else:
            logger.info("[AgentKernel] Endpoint cleared â€” kernel is uninitialized")

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

    # â”€â”€ Context window resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Every model has a maximum context window.  Memory, conversation history,
    # and MCM budgets should be derived from it â€” never hardcoded.

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
        # Cerebras â€” value confirmed by the user 2026-07-28.
        # NOTE: no provider-wide ("cerebras", "", N) fallback on purpose. An
        # unlisted model must fall through to the conservative 8k default rather
        # than inherit 256k: the budget is sized at window*0.9, so a default that
        # is too HIGH re-creates the overcommit this table's default exists to
        # prevent. Under-sizing is safe; over-sizing is the bug.
        ("cerebras", "gemma-4-31b", 256_000),
        # OpenRouter: REMOVED 2026-07-29. ("openrouter", "", 32_000) was a
        # bare-substring provider-wide fallback â€” it matched EVERY model from
        # OpenRouter, which fronts models from 4k to 2M windows. A blanket
        # 32_000 meant an 8k-window model got a budget sized for 32k, so DER
        # kept issuing steps while every call silently truncated (REQ-2 AC6,
        # the exact case row 1 of the silent-failure table in specs/PHASES.md
        # describes). This was briefly grandfathered into an allow-list in
        # test_no_raised_provider_default; that was wrong and has been
        # reverted â€” the guard now admits no exceptions. An unlisted
        # openrouter model now falls through to the conservative 8_192
        # default (case 4 below), tagged source="default" per REQ-2 AC4:
        # under-provisioning is safe, over-provisioning truncates silently.
        # Escape hatch: a real window can still be supplied per-model via
        # _context_window_overrides (highest precedence, REQ-2 AC3).
        # Open question: the correct long-term fix is resolving OpenRouter's
        # window from its API metadata (authoritative, REQ-2 AC2) rather than
        # any table guess â€” see specs/phase-1-foundation/requirements.md OQ.
        # LM Studio / IRIS Local â€” common local models
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
        # Ollama â€” common local models
        ("local", "llama3.1", 128_000),
        ("local", "llama3", 8_192),
        ("local", "mistral", 32_768),
        ("local", "qwen2.5", 32_768),
        ("local", "phi3", 128_000),
        ("local", "gemma2", 8_192),
        # Ollama CLOUD models. Every value below was read from the running
        # Ollama server's own /api/show `context_length` on 2026-08-16 â€” not
        # from a model card, a blog post, or memory. The catalog above this
        # file was once ~80% fabricated, so anything unverifiable is simply
        # absent here rather than guessed.
        #
        # Why these were missing and what it cost: an OLLAMA-kind provider maps
        # to the provider string "local" (see _provider_string_for_instance),
        # and no "local" entry matched any cloud id â€” so gpt-oss:120b-cloud
        # resolved to the conservative 8192 default and DER got a 4000-token
        # budget against a real 131072 window. Observed live: a 3-step task
        # stopped after step 2 with "Token budget exhausted (6091/4000)" while
        # the model had ~32x the headroom it was being given.
        #
        # Deliberately NOT listed: kimi-k2.5:cloud and kimi-k2-thinking:cloud.
        # Ollama's own /api/show returns an error for both, so no authoritative
        # window exists to record. They fall through to the 8192 default, which
        # under-provisions rather than truncates â€” the safe direction, per the
        # cerebras note above.
        ("local", "gpt-oss", 131_072),
        ("local", "nemotron-3-nano", 262_144),
        ("local", "glm-5.1", 202_752),
    ]

    # Known vision-capable API models. Keyed (provider_id, model_substring),
    # mirroring _KNOWN_CONTEXT_WINDOWS's shape and matching rule directly
    # above: substring match is case-insensitive, first match wins. Sibling
    # table for specs/unified-vision-routing REQ-1 AC2 â€” this is DATA only,
    # not a raise site. A model id that matches no row here is simply absent
    # from the table; the "unknown -> False" behaviour of REQ-1 AC5 is owned
    # by supports_vision() (backend/agent/inference/router.py), which must
    # treat "no row matched" as False rather than erroring.
    #
    # provider_id follows the same vocabulary as _KNOWN_CONTEXT_WINDOWS: the
    # literal instance id registered for an API ProviderInstance (e.g.
    # "openai", "anthropic" â€” see PROVIDER_PRESETS in
    # backend/agent/inference/provider.py), not the ProviderKind enum value.
    _KNOWN_VISION_MODELS: list[tuple[str, str]] = [
        # OpenAI â€” the GPT-4o family and later multimodal generations accept
        # image input natively.
        ("openai", "gpt-4o"),
        ("openai", "gpt-4-turbo"),
        ("openai", "gpt-4.5"),
        # Anthropic â€” every Claude 3 and later model accepts image input.
        ("anthropic", "claude-3"),
        ("anthropic", "claude-opus"),
        ("anthropic", "claude-sonnet"),
        ("anthropic", "claude-haiku"),
        # Gemini â€” multimodal since 1.5. No "gemini" id exists in
        # PROVIDER_PRESETS today (no dedicated Google preset is registered
        # yet); this row is forward-compatible with a directly-configured
        # Gemini-compatible API provider registered under instance id
        # "gemini", and the substring also matches vendor-prefixed ids such
        # as an aggregator's "google/gemini-2.0-flash-001" once such a
        # provider exists. Deliberately NOT guessing at a provider id that
        # is not yet a real preset beyond this one forward-compatible row.
        ("gemini", "gemini"),
    ]

    # â”€â”€ Active-model state: DERIVED from the router, never stored â”€â”€â”€â”€â”€â”€â”€â”€â”€
    #
    # These three read like plain attributes because ~120 call sites across the
    # backend read them that way, and that is fine â€” reading is safe. What is
    # not safe is STORING them, which is what they used to do.
    #
    # The role-binding table and the provider registry are process-wide
    # singletons (REQ-5): one table, shared by every kernel's router. The user's
    # live choice lives there and nowhere else. Every recurring "I picked cohere
    # and it went back to cerebras" report traced to some path re-applying a
    # stored copy of that choice â€” startup config replay, peer inheritance, a
    # module-global snapshot, persisted session field_values. Each was fixed
    # individually and the bug came back through the next copy.
    #
    # Deriving them removes the category. There is no copy to go stale, no sync
    # to forget, and a new conversation kernel â€” or a subagent, or a swarm
    # worker â€” sees the live binding at construction because it shares the
    # table rather than inheriting a snapshot of it.
    #
    # To CHANGE the active model, bind the role: `kernel.set_role_binding(...)`.

    @property
    def _model_provider(self) -> str:
        """Provider string serving the ``reasoning`` role, or ``"uninitialized"``.

        Returns the legacy provider-string vocabulary (``"local"``,
        ``"lmstudio"``, ``"iris_local"``, or an API provider id such as
        ``"cerebras"``) that ``_KNOWN_CONTEXT_WINDOWS`` and the scheduler
        labels expect.
        """
        if getattr(self, "_swarm_enabled", False):
            return "iris_local"
        _r = getattr(self, "_router", None)
        if _r is None:
            return "uninitialized"
        try:
            _inst = _r.resolve("reasoning")
        except Exception:
            return "uninitialized"
        return self._provider_string_for_instance(_inst) or "uninitialized"

    @property
    def _selected_reasoning_model(self) -> Optional[str]:
        """Model id serving the ``reasoning`` role, or None when unbound."""
        return self._model_for_role("reasoning")

    @property
    def _selected_tool_execution_model(self) -> Optional[str]:
        """Model id serving the ``tool_execution`` role, or None when unbound.

        Independent of :attr:`_selected_reasoning_model` by construction â€” the
        two roles are separate bindings. Brain and Tool can sit on different
        providers, which is the property the swarm and subagent work builds on.
        """
        return self._model_for_role("tool_execution")

    def _model_for_role(self, role: str) -> Optional[str]:
        """Resolve *role* to its effective model id (override wins), or None."""
        _r = getattr(self, "_router", None)
        if _r is None:
            return None
        try:
            return _r.resolve(role).model or None
        except Exception:
            return None

    def response_max_tokens(self, floor: int = 0) -> int:
        """Token ceiling for USER-FACING prose, from the Max Response setting.

        The Model & Inference card's "Max Response" (short | medium | long) was
        honoured only by ``_respond_direct``; every DER-side prompt that writes
        to the user hardcoded its own cap (synthesis 4096, outcome summary 400,
        step result 512). So the setting silently did nothing on exactly the
        multi-tool answers it matters most for (2026-08-16).

        *floor* keeps a caller's own minimum when it needs more room than the
        setting implies â€” the setting raises a cap, it should not starve a
        prompt that genuinely needs length.
        """
        _mapped = {"short": 1024, "medium": 4096, "long": 8192}.get(
            getattr(self, "_response_length", "medium") or "medium", 4096
        )
        return max(_mapped, floor)

    def response_temperature(self) -> float:
        """Sampling temperature from the Reasoning Effort setting."""
        return {"fast": 0.9, "balanced": 0.6, "accurate": 0.3}.get(
            getattr(self, "_reasoning_effort", "balanced") or "balanced", 0.6
        )

    def _provider_string_for_instance(self, inst: Any) -> str:
        """Map a bound ``ProviderInstance`` to the provider-string used by
        ``_KNOWN_CONTEXT_WINDOWS`` (REQ-1 AC1). API instances use their own id
        (e.g. ``"cerebras"``); local families normalize to the table keys
        ``"local"`` / ``"lmstudio"`` / ``"iris_local"``.
        """
        try:
            from backend.agent.inference.provider import ProviderKind

            kind = getattr(inst, "kind", None)
            if kind == ProviderKind.OLLAMA:
                return "local"
            if kind == ProviderKind.LOCAL_OPENAI:
                return "lmstudio"
            if kind == ProviderKind.INPROCESS:
                return "iris_local"
            if kind == ProviderKind.API:
                return getattr(inst, "id", "") or ""
        except Exception:
            pass
        # Fall back to instance id or the legacy string convention.
        return getattr(inst, "id", "") or ""

    def resolve_context_window_with_source(
        self, role: str = "reasoning"
    ) -> "ResolvedWindow":
        """Resolve *role*'s effective context window, tagging the source that won.

        Precedence (REQ-2, design D-2):
          1. override      â€” user-set ``_context_window_overrides`` (highest)
          2. authoritative â€” the ACTUAL loaded local ``n_ctx`` (source of truth)
          3. table         â€” ``(provider, substring)`` registry lookup
          4. default       â€” conservative 8k, logged and tagged as a default

        The authoritative branch MUST run before the substring table: a loaded
        model's real ``n_ctx`` outranks a name-based guess. The old code ran the
        table first, so a 16k-loaded Mistral reported 32_768. Tagging the source
        is what makes an unknown window VISIBLE (REQ-2 AC4) rather than silent.

        *role* exists because Brain and Tool are independent bindings and may sit
        on models with very different windows. This method used to resolve the
        reasoning binding unconditionally, so a turn's whole budget was sized by
        the Brain even for the steps that execute on the Tool binding
        (``infer(role="EXECUTION")``). With Brain on a 256k model and Tool on an
        8k one, that budgets ~230k against a model that truncates at 8k â€” the
        silent-truncation failure this table's conservative default exists to
        prevent, reintroduced through the back door. Callers that care which
        model will actually receive the tokens must say so.
        """
        # REQ-1 AC1: the ACTIVE binding is authoritative. These properties
        # resolve it directly (2026-08-16) â€” they used to be stored fields that
        # could disagree with the binding, which is why this block once read the
        # router explicitly and treated them as a stale fallback.
        if role == "reasoning":
            provider = self._model_provider or ""
            model = self._selected_reasoning_model or ""
        else:
            model = self._model_for_role(role) or ""
            provider = ""
            _r = getattr(self, "_router", None)
            if _r is not None:
                try:
                    provider = self._provider_string_for_instance(_r.resolve(role))
                except Exception:
                    provider = ""

        # 1. User override (highest precedence)
        if model in self._context_window_overrides:
            return ResolvedWindow(self._context_window_overrides[model], "override")

        # 2. Authoritative: the live local model manager's ACTUAL loaded n_ctx.
        #    This is the source of truth for a locally-run model â€” it was
        #    launched with a specific n_ctx, and a substring guess would
        #    under/over-size the budget vs the real window.
        #
        #    Gated on the provider KIND, not on the string "local". The string
        #    map in _provider_string_for_instance sends OLLAMA -> "local",
        #    LOCAL_OPENAI -> "lmstudio" and INPROCESS -> "iris_local", so a test
        #    for "local" fired for Ollama (which has no LocalModelManager and
        #    always fell through) and NEVER for a real local model. A model
        #    loaded at 32768 then fell past the substring table to the 8192
        #    default â€” the same silent truncation the gpt-oss entry below was
        #    added to fix, reintroduced by REQ-4's id namespacing.
        if provider in ("local", "lmstudio", "iris_local"):
            try:
                from .local_model_manager import get_local_model_manager

                mgr = get_local_model_manager()
                if getattr(mgr, "is_loaded", lambda: False)() and getattr(
                    mgr, "_current_params", None
                ):
                    _n_ctx = int(mgr._current_params.get("n_ctx", 0))
                    if _n_ctx and _n_ctx > 0:
                        return ResolvedWindow(_n_ctx, "authoritative")
            except Exception:
                pass

        # 3. Table â€” (provider, substring) registry lookup, case-insensitive.
        model_lower = model.lower().strip()
        for reg_provider, reg_substring, tokens in self._KNOWN_CONTEXT_WINDOWS:
            if reg_provider == provider and (
                not reg_substring or reg_substring in model_lower
            ):
                return ResolvedWindow(tokens, "table")

        # 4. Local model manager profiles â€” config-derived guess. Treated as the
        #    table tier: better than the 8k default, but not the live loaded value.
        try:
            from .local_model_manager import LocalModelManager

            mgr = LocalModelManager()
            for profile in mgr.profiles:
                # REQ-1 AC4: a vacuous guard on an empty profile.id
                # ("..." in model_lower is ALWAYS True) used to short-circuit
                # resolution to the first empty-id profile. Skip empty ids.
                if profile.id and (profile.id in model_lower or model_lower in profile.id):
                    return ResolvedWindow(profile.n_ctx, "table")
        except Exception:
            pass

        # 5. Safe default â€” 8k for unknown models. Tagged so it is VISIBLE, not silent.
        #    REQ-1 AC3: WARN-level, naming provider+model+source â€” loudly, not silently.
        logger.warning(
            "[AgentKernel] WARN source=default: no context window known for "
            f"provider={provider} model={model} â€” falling back to 8192"
        )
        return ResolvedWindow(8_192, "default")

    def resolve_context_window(self, role: str = "reasoning") -> int:
        """Return the effective context window (tokens) for *role*'s model.

        Thin wrapper over :meth:`resolve_context_window_with_source` that returns
        only the token count, preserving the ``int`` contract used by the 20+
        call sites (budget, work units, ContextPill denominator, Pacman filter).
        The source tag is available via ``resolve_context_window_with_source()``.

        Defaults to ``reasoning`` because that is the model the user thinks of as
        "the model" â€” it answers, and it is the right ContextPill denominator.
        Use ``resolve_turn_context_window()`` for anything sizing a budget that
        BOTH roles will spend against.
        """
        return self.resolve_context_window_with_source(role).tokens

    def resolve_turn_context_window(self) -> int:
        """Smallest context window among the roles that will serve this turn.

        A DER turn spends one budget across calls that go to the reasoning
        binding AND calls that go to the tool_execution binding. When those sit
        on different models the only safe ceiling is the SMALLER window: budget
        for the larger one and every call to the smaller silently truncates.

        This follows the rule stated throughout the window table â€” under-sizing
        is safe, over-sizing is the bug. A Brain/Tool split must not be able to
        reintroduce the overcommit by the back door (2026-08-16).
        """
        _reasoning = self.resolve_context_window("reasoning")
        try:
            _tool = self.resolve_context_window("tool_execution")
        except Exception:
            return _reasoning
        # An unbound/unknown tool role resolves to the conservative default;
        # that is a real ceiling for it, so honouring the minimum is still
        # correct. Guard only against a nonsense zero.
        if not _tool:
            return _reasoning
        if _tool != _reasoning:
            logger.info(
                "[AgentKernel] turn window = min(reasoning=%d, tool_execution=%d) "
                "= %d â€” Brain and Tool are on different models, so the budget is "
                "capped by the smaller window to avoid silent truncation",
                _reasoning, _tool, min(_reasoning, _tool),
            )
        return min(_reasoning, _tool)

    def get_effective_token_budget(self, fraction: float = 0.75) -> int:
        """Return the usable token budget as a fraction of the context window.

        We reserve 25% for the system prompt + tool definitions + response
        generation.  The fraction parameter lets callers override this.
        """
        return int(self.resolve_context_window() * fraction)

    def _emit_context_usage(self, step_number: int = 0, total_steps: int = 0) -> None:
        """Emit a `context:usage` event with the REAL per-thread token state.

        REQ-12 (Wave 9): makes the ContextPill live on EVERY model response,
        not just inside the DER loop. Single emitter so DER and non-DER paths
        share the SAME event contract (same shape, same `resolve_context_window()`
        denominator, same `self._tokens_used` numerator) â€” they intertwine via
        the contract, not duplicated logic.

        - `max_tokens` = resolve_context_window() (the model in use) â€” never a
          hardcoded 128k.
        - `used_tokens` = self._tokens_used, the kernel's real per-thread count,
          restored from the context store per conversation_id (agent_kernel.py:547).
          An ACTIVE or SWITCHED thread therefore shows its real usage and NEVER 0.
          Only a genuinely brand-new thread (no history) may report 0, which is
          honest.

        Fire-and-forget: EventBus failure must never crash the response path.
        """
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.CONTEXT_USAGE,
                data={
                    "used_tokens": int(getattr(self, "_tokens_used", 0) or 0),
                    "max_tokens": int(self.resolve_context_window()),
                    "step_number": step_number,
                    "total_steps": total_steps,
                },
                turn_id=getattr(self, "_current_turn_id", None),
                conversation_id=self.conversation_id,
                session_id=self.session_id,
            )
        except Exception:
            pass  # EventBus is optional â€” no crash if it fails

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
        # common OpenAI-compat provider â€” always handled by the openai client path.
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
        HTTP client whenever the provider is ``iris_local`` â€” eliminating
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

        1. **In-process adapter** â€” when the provider is ``iris_local`` and
           a `LocalModelManager` has been bound via
           ``configure_inprocess_local()`` with a loaded model. Returns the
           manager's ``InProcessOpenAIAdapter``, which duck-types the
           openai client surface but routes straight to the in-process
           ``Llama`` instance. No HTTP, no subprocess, no port 8082.

        2. **Real openai HTTP client** â€” all other cases. Created once and
           cached so every inference call reuses the same httpx connection
           pool (saves ~5â€“20 ms per call on localhost).

        Invalidated by ``configure_lmstudio()`` / ``configure_inprocess_local()``
        when the binding changes.
        """
        # Path 1: in-process adapter when iris_local + manager loaded.
        mgr = getattr(self, "_inprocess_local_mgr", None)
        if mgr is not None and self._model_provider == "iris_local":
            adapter = mgr.get_inprocess_client()
            if adapter is not None:
                return adapter
            # Manager was bound but model isn't loaded â†’ fall through to
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
                f"[AgentKernel] Created LM Studio client â†’ {self._lmstudio_endpoint}/v1"
            )
        return self._lmstudio_client

    def prewarm_lmstudio(self) -> None:
        """Send a minimal 1-token request to LM Studio so it loads the model into VRAM now.

        LM Studio cold-starts the model on the FIRST real inference request, which
        can take 20-30 seconds for a 9B-parameter model (VRAM load from SSD).
        Calling this immediately after the user confirms an LM Studio endpoint causes
        the model to load in the background, so it is already hot by the time the user
        sends their first message.

        Called from a daemon thread â€” never blocks the caller.
        """
        import threading

        def _do_prewarm() -> None:
            t0 = time.perf_counter()
            try:
                model = self._selected_reasoning_model or "local-model"
                logger.info(
                    f"[AgentKernel] Pre-warming LM Studio model '{model}' at {self._lmstudio_endpoint} â€¦"
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
                    f"â€” model is hot and ready"
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
        logger.info(f"[AgentKernel] Launcher mode changed: {prev} â†’ {mode}")

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
            "[AgentKernel] PROJECT.md not found â€” developer context unavailable"
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
            from backend.agent.der_constants import EML_EXPLORE, EML_VERIFY

            _e, _x, _y = ffi_calculate_eml(self.session_id)
            _phase = (
                "EXPLORE"
                if _e >= EML_EXPLORE
                else ("VERIFY" if _e < EML_VERIFY else "BALANCE")
            )
            base += (
                f"\n\n[COGNITIVE STATE: {_phase} | EML={_e:.2f} x={_x:.2f} y={_y:.2f}]"
            )
        except Exception:
            pass

        # Domain 19: Caducean DER Governor state visible to LLM
        # The Caducean governor tracks exploration-exploitation balance (Î¾).
        # Phase mapping: Î¾ < 0.3 â†’ EXPLOIT, 0.3 â‰¤ Î¾ < 0.7 â†’ BALANCE, Î¾ â‰¥ 0.7 â†’ EXPLORE
        try:
            from backend.gateway.iris_ffi import ffi_caducean_get_xi

            _xi = ffi_caducean_get_xi(self.session_id)
            _cad_phase = (
                "EXPLOIT" if _xi < 0.3 else ("EXPLORE" if _xi >= 0.7 else "BALANCE")
            )
            base += (
                f"\n[CADUCEAN GOVERNOR: {_cad_phase} | Î¾={_xi:.2f}]"
                "\nYou are governed by the Caducean DER Governor, which balances "
                "exploration vs exploitation. When asked about your phase or state, "
                "report the Caducean phase and Î¾ value above."
            )
        except Exception:
            pass

        # Issue C.1 â€” structured speak/show response contract.
        # `show` means STORE THIS AS A DOCUMENT, not "this answer is long".
        # The old rule here was length-based ("longer than about 3 sentences ->
        # respond with JSON"), which made ordinary conversation arrive at
        # _process_structured_response wearing a `show` payload. The kernel then
        # had to guess whether it was really an artifact, and that guess is what
        # kept discarding answers. Length is a FORMATTING question, answered by
        # _READABLE_FORMAT_RULES; `show` is a STORAGE question, answered here.
        base += (
            "\n\n[RESPONSE FORMAT]\n"
            "Two different things, decided separately:\n"
            "\n"
            "1. LENGTH is not a reason to use JSON. A long answer is still an "
            "answer â€” write it as plain text and format it readably (headings, "
            "bullets, tables, code fences). It is shown in full in the chat "
            "thread. NEVER shorten an answer because it is long.\n"
            "\n"
            "2. Use the JSON `show` payload ONLY when the content is a DOCUMENT "
            "â€” something STORED in the document store so the user can reopen, "
            "reformat or refer back to it later:\n"
            "  - web-search / web-crawl results and the evidence behind them\n"
            "  - a file or document you generated (a report, a plan, a spec)\n"
            "  - code you produced as a deliverable\n"
            "  - a data table, dataset or diagram meant to be kept\n"
            "  - a revision of a document you already stored (pass its "
            "`document_id`)\n"
            "If the user is simply asking you something and you are answering "
            "them â€” however long the answer â€” that is CONVERSATION. Use plain "
            "text. A document card is not a way to present a reply.\n"
            "\n"
            "When it IS a document, respond with JSON:\n"
            '{"speak": "<2-3 sentence conversational summary of what you say>", '
            '"show": {"format": "markdown|html|table|diagram|text", '
            '"content": "<the full document>", '
            '"document_id": "<only when revising a document you already stored>", '
            '"alternatives": ["<other formats you could render>"], '
            '"variants": {"<format>": "<full content rendered in that format>", ...} '
            '// optional but encouraged: also include the SAME content rendered in '
            'other formats (e.g. {"markdown": "...", "html": "..."}) so the user can '
            'switch formats instantly without re-generating}}\n'
            "The `speak` field is what the user HEARS via TTS â€” keep it brief "
            "and natural (1-3 sentences). The `show` field is the document that "
            "is stored and rendered as a card; the chat thread keeps your spoken "
            "line so the document is not duplicated inline.\n"
            "\n"
            "[WEB SEARCH RESULTS]\n"
            "When you present web-search / web-crawl results, you MUST render them "
            "via a `show` payload and CHOOSE the best format yourself:\n"
            "  - prose / articles / summaries -> 'markdown'\n"
            "  - data, comparisons, stats -> 'table'\n"
            "  - flows, architectures, relationships -> 'diagram'\n"
            "  - raw web page content -> 'html' (untrusted, sanitized)\n"
            "If you are unsure which format fits best, DO NOT guess â€” call "
            "`ask_user_question` with the format options (markdown/table/html/"
            "diagram/text) so the user chooses. Never return a bare .md file "
            "without a `show` format choice."
        )

        return base

    # ------------------------------------------------------------------
    # Domain 4.5 â€” Proactive skill creation
    # ------------------------------------------------------------------

    def _maybe_trigger_skill_creation(
        self,
        tool_sequence: list,
        task_summary: str,
    ) -> None:
        """
        After each task, capture a *verified* reusable skill when the run used
        >= 3 distinct tools and the sequence is not already a known skill.

        Phase 5.1 (research D1): replaces the old count-based heuristic that
        merely prompted the LLM to write a SKILL.md.  The new pipeline is
        deterministic and verified:
          1. Trigger iff >= 3 DISTINCT tools AND similarity to existing skills
             < 0.85 (workflow_capture.should_capture).
          2. Self-test: every step names a tool registered in tool_registry
             (no unknown tools) â€” a safe structural replay, no real execution
             (workflow_capture.self_test_skill).
          3. Register the verified skill in semantic memory
             (workflow_capture.register_verified_skill), mirroring
             SkillCrystalliser's storage so the skill UI / AutoResearchRunner
             pick it up for continuous refinement (MIN_IMPROVEMENT = 0.05).

        tool_sequence is the list of tool-call dicts recorded by the DER loop.
        """
        import json

        if not tool_sequence or len(tool_sequence) < 2:
            return

        # Only capture from successful runs.
        successful = [
            s for s in tool_sequence
            if isinstance(s, dict) and s.get("success", False)
        ]
        if len(successful) < 2:
            return

        # In-session dedupe so we don't re-trigger for the same pattern.
        names = []
        for tc in successful:
            name = (
                tc.get("name")
                or tc.get("tool")
                or tc.get("function", {}).get("name", "")
            )
            if name:
                names.append(name)
        pattern_key = " â†’ ".join(names)
        if pattern_key in self._prompted_skill_patterns:
            return
        self._prompted_skill_patterns.add(pattern_key)

        try:
            from backend.agent.workflow_capture import capture_workflow
            from backend.agent.tool_registry import resolve_tool

            memory = self._memory_interface
            if memory is None or not hasattr(memory, "semantic"):
                return

            # Existing skills (for similarity de-dup).
            existing_skills = []
            try:
                for entry in memory.semantic.get_by_category("named_skills"):
                    try:
                        existing_skills.append(json.loads(entry.value))
                    except Exception:
                        continue
            except Exception:
                existing_skills = []

            key = capture_workflow(
                tool_sequence=successful,
                memory=memory,
                existing_skills=existing_skills,
                is_registered=lambda n: resolve_tool(n) is not None,
            )
            if key:
                logger.info(
                    "[AgentKernel] Verified skill captured: %s (pattern: %s)",
                    key, pattern_key,
                )
                note = (
                    f"I captured a verified skill from this run "
                    f"({pattern_key}). It will be reused automatically."
                )
                try:
                    if hasattr(self, "_pending_follow_ups"):
                        self._pending_follow_ups.append(note)
                    else:
                        self._pending_follow_ups = [note]
                except Exception:
                    pass
            else:
                logger.debug(
                    "[AgentKernel] Skill capture skipped for pattern: %s", pattern_key
                )
        except Exception as e:
            logger.error("[AgentKernel] Skill capture failed: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Helpers: thinking-token stripping, planning gate, direct response
    # ------------------------------------------------------------------

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

    # Pure social/casual phrases that never need planning or tools.
    _CHITCHAT_PATTERNS = (
        "hi", "hello", "hey", "yo", "sup", "howdy", "hiya", "greetings",
        "good morning", "good afternoon", "good evening", "good night",
        "how are you", "how's it going", "how is it going", "how are things",
        "how have you been", "how's your day", "what's up", "whats up",
        "wassup", "what is up", "thanks", "thank you", "thx", "ty",
        "appreciate it", "appreciate that", "nice", "cool", "great", "awesome",
        "sweet", "lol", "haha", "hahaha", "lmao", "bye", "goodbye", "see you",
        "see ya", "cya", "talk later", "take care", "who are you", "what are you",
    )
    # Short acknowledgements / confirmations that are not task continuations.
    _CHITCHAT_ACKS = (
        "yes", "yeah", "yep", "yup", "no", "nope", "nah", "ok", "okay", "k",
        "sure", "maybe", "perhaps", "right", "correct", "of course", "got it",
        "gotcha", "alright", "fine", "agreed", "sounds good", "sure thing",
    )

    def _is_chitchat(self, text: str) -> bool:
        """
        True for pure social/casual messages that need no planning or tools.

        Used by the universal planner (Phase 1.1): every inbound message routes
        through the planner EXCEPT chit-chat, which keeps the fast direct path.
        """
        t = (text or "").lower().strip()
        if not t:
            return True
        if t in self._CHITCHAT_PATTERNS:
            return True
        # Starts with a greeting token (e.g. "hey there")
        _first = t.split()[0] if t.split() else ""
        if _first in ("hi", "hello", "hey", "yo", "sup", "howdy", "hiya", "greetings"):
            return True
        # "how are you" family â€” social, not a task
        if t.startswith("how are") or t.startswith("how's") or t.startswith("how is"):
            return True
        # Short casual acknowledgement (no tool intent)
        if t in self._CHITCHAT_ACKS:
            return True
        return False

    # Action/tool intent markers â€” prompts containing these need the DER
    # planning/tool loop. Everything else (simple questions, factual lookups,
    # conversation) takes the fast direct-response path (1 Cerebras call, no
    # "Working on it" filler, no rate-limit burst).
    _ACTION_VERBS = (
        "search", "google", "lookup", "find", "open", "launch", "start",
        "create", "make", "build", "generate", "write", "send", "email",
        "message", "text", "call", "schedule", "remind", "set", "add",
        "delete", "remove", "update", "edit", "change", "list", "play", "show me",
        "book", "order", "buy", "download", "upload", "post", "tweet",
        "run", "execute", "deploy", "install", "configure", "toggle",
        "turn on", "turn off", "switch", "navigate", "go to", "browse",
        "scrape", "fetch", "pull", "sync", "backup", "translate", "summarize",
        "analyze", "compare", "calculate", "convert",
    )

    # Follow-up / anaphora markers â€” these signal the user is continuing a
    # PRIOR task ("now do it for the sales team", "yes, schedule that",
    # "what about the other one"). They carry no action verb of their own but
    # are clearly NOT standalone questions, so they must route to DER (the safe
    # fallback) rather than the dumb direct path. This is the "inertia" the
    # field's routing systems use to avoid misrouting mid-conversation.
    _FOLLOWUP_MARKERS = (
        "now", "then", "also", "too", "as well", "instead", "again",
        "what about", "how about", "and the", "for the", "with the",
        "yes", "yeah", "yep", "sure", "ok", "okay", "do it", "go ahead",
        "proceed", "confirm", "that one", "the other one", "the same",
    )
    _ANAPHORA_PRONOUNS = ("it", "that", "this", "them", "they", "those", "these", "him", "her")

    def _is_followup_to_task(self, text: str, context) -> bool:
        """
        Cheap rule check: does this message continue a prior task rather than
        start a fresh standalone question?  Used to keep multi-turn task flow
        in the DER loop even when the follow-up has no action verb of its own.

        Returns True when the message is short, anaphoric (references "it/that/
        them"), or a confirmation/continuation marker AND the recent context
        shows an active task.  Free (0 model calls).
        """
        t = (text or "").lower().strip()
        if not t or len(t.split()) > 25:
            return False
        # Anaphora: a pronoun with no noun is almost always a continuation.
        words = set(t.split())
        if words & set(self._ANAPHORA_PRONOUNS) and not any(
            v in t for v in self._ACTION_VERBS
        ):
            # "do it", "change that", "what about them" â€” continuation.
            if any(m in t for m in ("do", "change", "update", "edit", "what about",
                                    "how about", "send", "for", "with", "the")):
                return True
        # Explicit continuation/confirmation markers.
        if any(t.startswith(m) or f" {m} " in f" {t} " for m in self._FOLLOWUP_MARKERS):
            return True
        # Prior task context: if the last assistant turn was a plan/tool result,
        # a short user reply is overwhelmingly a follow-up, not a new question.
        if context:
            try:
                last = context[-1] if isinstance(context, (list, tuple)) else None
                if isinstance(last, dict) and last.get("role") == "assistant":
                    c = (last.get("content") or "")
                    if any(k in c.lower() for k in ("plan", "tool", "step", "task", "i'll", "i will")):
                        if len(t.split()) <= 12:
                            return True
            except Exception:
                pass
        return False

    def _classify_intent(self, text: str, context=None) -> str:
        """
        Semantic-logic-gate Tier 0 (REQ-1). Delegates to ``tier0_classify``.

        Preserves the legacy 4-class contract ("chat" | "action" | "followup" |
        "question") for any remaining callers. The authoritative structured
        decision is ``compile_dag().requires_der_kernel``, consumed by
        ``_needs_planning`` below; this method is the compatibility view.
        """
        from backend.agent.semantic_gate import Tier0Intent, tier0_classify

        _v = tier0_classify(text, context)
        return {
            Tier0Intent.CHAT: "chat",
            Tier0Intent.ACTION: "action",
            Tier0Intent.FOLLOWUP: "followup",
            Tier0Intent.QUESTION: "question",
            Tier0Intent.WEB: "action",  # legacy web intent maps to action
        }[_v.intent]

    @property
    def _gate(self):
        """Lazy SemanticLogicGate instance (T7, REQ-1/REQ-8). No model load at
        construction â€” the ontology (Tier 2) is wired via memory_interface."""
        from backend.agent.semantic_gate import SemanticLogicGate

        if getattr(self, "__gate", None) is None:
            self.__gate = SemanticLogicGate(
                tool_mode=getattr(self, "_tool_mode", "auto"),
                memory_interface=getattr(self, "_memory_interface", None),
            )
        return self.__gate

    def register_planning_hook(self, name: str, fn) -> None:
        """Planning-policy hook (REQ-8 AC3): skills/plugins/MCPs register a
        contributor/override that adjusts the draft DAGPlanGraph per task.
        Delegates to the gate's registered-policy store."""
        self._gate.register_policy(name, fn)

    def _web_mode_on(self) -> bool:
        try:
            from backend.agent.agent_gateways import get_global_internet_access

            return bool(get_global_internet_access())
        except Exception:
            return False

    def _needs_planning(self, text: str, context=None) -> bool:
        """
        Planner gate â€” the semantic logic gate (REQ-1, T7, T13).

        ``compile_dag().requires_der_kernel`` is the structured planning
        decision (REQ-8): Tier 0 (deterministic rules) -> Tier 2 (coordinate-
        graph ontology) -> the continuation lens compose the DAGPlanGraph; the
        ``_tool_mode`` policy
        (auto | ask_first | disabled) is applied INSIDE the gate; the web-mode
        gate (``_should_skip_der``) remains the final DER-skip authority
        (REQ-1 AC6).

        T13 gate-proof (tests/behavioral/test_behavioral_intent_routing.py,
        69 cases): equivalence with the legacy router on every non-compound
        prompt (zero regressions) + superiority on compound/multi-concern
        prompts (multi-lane DAGs). The legacy router is retired; this method
        is the permanent routing surface. ``_classify_intent`` remains as the
        legacy 4-class compatibility view (pinned by
        tests/behavioral/test_intent_routing_memory.py).
        """
        _g = self._gate
        _g.tool_mode = getattr(self, "_tool_mode", "auto")
        graph = _g.compile_dag(text, context, web_mode=self._web_mode_on())
        # REQ-5 AC1 (T8): stash the compiled graph for the [LAYERS] emit
        # (off the hot path â€” the TurnMetrics stamp copies a few attrs).
        self._last_gate_graph = graph
        return bool(graph.requires_der_kernel)

    def _stamp_gate_telemetry(self, metrics) -> None:
        """REQ-5 AC1 (T8): copy the last gate compilation onto the turn's
        TurnMetrics before [LAYERS] emit. Fire-and-forget; defaults when the
        gate never ran (direct calls in tests)."""
        graph = getattr(self, "_last_gate_graph", None)
        if graph is None:
            return
        lanes = ",".join(n.lane.value for n in graph.nodes) if graph.nodes else ""
        domain = graph.nodes[0].domain.value if graph.nodes else ""
        metrics.record_gate(
            domain=domain,
            lanes=lanes,
            latency_ms=graph.latency_ms,
            widen_scope=getattr(graph, "widen_scope", "") or "",
        )

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

    # â”€â”€ Token estimation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Rough but fast: 1 token â‰ˆ 4 chars. Real tokenizer adds <5% accuracy gain
    # but costs 10-50ms per call â€” not worth it for windowing decisions.
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
        from the Context Engineering spec (CONTEXT_ENGINEERING.md Â§1â€“3):

          Layer 1 â€” Mycelium coordinate graph  â†’ already in system_prompt via
                                                  _build_system_prompt()
          Layer 2 â€” Episodic store             â†’ injected here as memory block
          Layer 3 â€” Working memory / history   â†’ token-aware full context, NOT
                                                  a hard-capped roll window

        The result is unlimited effective memory: the agent sees all context
        that fits in the budget. When history exceeds the budget, the oldest
        messages are trimmed â€” but episodic summaries from Mycelium still carry
        the gist of older sessions forward (Layer 2).

        Design rules (from spec):
          â€¢ Never drop the current user turn
          â€¢ First non-system message must be "user" (Qwen3 / most models)
          â€¢ Episodic block is a system-adjacent userâ†”assistant exchange so it
            doesn't break the alternating pattern
        """
        system_prompt = self._build_system_prompt()

        # â”€â”€ Layer 2: episodic injection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        episodic_prefix: List[Dict] = []
        try:
            if self._memory_interface is not None and hasattr(
                self._memory_interface, "episodic"
            ):
                ep_ctx = self._memory_interface.episodic.assemble_episodic_context(text)
                if ep_ctx and ep_ctx.strip():
                    # Inject as a pseudo-exchange so the message pattern stays
                    # [system, user, assistant, user, assistant, â€¦, user]
                    episodic_prefix = [
                        {
                            "role": "user",
                            "content": f"<memory>\n{ep_ctx.strip()}\n</memory>",
                        },
                        {
                            "role": "assistant",
                            "content": "Understood â€” I have that context.",
                        },
                    ]
        except Exception as _ep_exc:
            loud_error(_ep_exc, "episodic.assemble_episodic_context")

        # â”€â”€ Layer 3: Option B â€” DB-backed semantic context (Pacman retrieval) â”€â”€
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

        # â”€â”€ 3a: semantic chunk retrieval from DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                    # Token-aware: cap retrieved chunks to fit the model's real
                    # context window (reserve ~40% for prompt + response so the
                    # agent's own reasoning space isn't crowded out by memory).
                    max_context_tokens=int(self.resolve_context_window() * 0.6),
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
                            "content": "Understood â€” I have those context fragments.",
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

        # â”€â”€ 3b: recency anchor â€” last N raw turns â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ Assemble final message list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ Telemetry: log context assembly metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ MCM Protocol: MITO tag injection + DCP prune â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                # Alternating roles â€” OK
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
          Layer 1: Mycelium coordinates â†’ system prompt
          Layer 2: Episodic store       â†’ memory block prefix
          Layer 3: Full history         â†’ token-aware (not a hard roll window)

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

        # === Tool definitions for function calling (gated by internet access) ===
        # When the web toggle is ON, get_available_tools() includes search /
        # crawler_query; when OFF, those are omitted. The agent decides when to
        # use them via the ReAct loop below. See plan Issue E.
        import json as _json
        _tools = self._get_openai_tools(text)

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
        _MAX_TOOL_ROUNDS = 3
        _round = 0
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
                try:
                    _raw = asyncio.run(
                        self._tool_bridge.execute_tool(
                            tool_name=_name,
                            params=_params,
                            session_id=self.conversation_id or "voice",
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
                                session_id=self.conversation_id or "voice",
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

        return _response

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
            "Authorization": f"Bearer {_api_key}",
            "Content-Type": "application/json",
        }
        _body = {
            "model": sel,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            _body["tools"] = tools
            _body["tool_choice"] = "auto"
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

        # LM Studio-specific extra_body for thinking template hints
        _body["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": use_thinking}
        }

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
                            raise RuntimeError(f"Could not connect to LM Studio at {_api_base}")

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
                            raise RuntimeError(f"Could not connect to LM Studio at {_api_base}")

                        if _resp.status_code == 429:
                            continue
                        if _resp.status_code != 200:
                            raise RuntimeError(
                                f"LM Studio returned {_resp.status_code}: {_resp.text[:200]}"
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
                raise RuntimeError("LM Studio request failed after retries")

            _msg = _result.get("choices", [{}])[0].get("message", {})
            _reply = _msg.get("content", "")
            _tool_calls = _msg.get("tool_calls") or []

            if not _reply and not _tool_calls:
                raise RuntimeError("Empty response from LM Studio")

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
        list_items = sum(1 for ln in lines if re.match(r"^\s*[-*â€¢]\s|^\s*\d+\.\s", ln))
        if list_items >= 3:
            return True
        # Long, dense multi-paragraph text (>10 non-empty lines, avg >8 words/line)
        non_empty = [ln for ln in lines if ln.strip()]
        if len(non_empty) > 10:
            avg_words = sum(len(ln.split()) for ln in non_empty) / len(non_empty)
            if avg_words > 8:
                return True
        return False

    # â”€â”€ Tool definitions for OpenAI-compatible function calling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        # â”€â”€ Filter web tools when not explicitly requested â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Even when the web toggle is ON, exclude search/crawler tools
        # unless the user's text explicitly asks for a web search.
        # The model otherwise calls web_search unnecessarily for simple
        # conversational prompts.
        if text and not self._is_web_search_request(text):
            openai_tools = [
                t
                for t in openai_tools
                if t.get("function", {}).get("name") not in ("search", "crawler_query")
            ]
        return openai_tools

    # â”€â”€ ReAct agentic loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def prepare_spoken_text(self, full_response: str, user_message: str = "") -> str:
        """
        Returns ONLY the text that should be sent to the TTS engine (F5-TTS).
        Full response is ALWAYS sent separately via text_response.

        Conversational-first design: IRIS speaks a short, natural summary.
        The full response is always visible in ChatView â€” voice is a companion,
        not a reader.  Thresholds keep spoken output under ~20-25 seconds.

        No second LLM call â€” direct text processing keeps first-audio latency
        to synthesis time only (~1-2s warm, ~40s cold F5-TTS).

        Rules (applied after code/markdown is stripped):
          â‰¤ 60 words  â†’ spoken verbatim (always â€” short answers, confirmations)
          61-120 words, conversational â†’ spoken verbatim (user asked, answer given)
          61-120 words, document-like â†’ first sentence + "in the chat window"
          > 120 words â†’ first sentence to boundary (â‰¤ 60 words) + "in the chat window"
        """
        import re as _re
        from backend.voice.tts_normalizer import normalize_text

        # Strip code fences and their content entirely â€” code is unreadable aloud
        cleaned = _re.sub(r"```[\s\S]*?```", "", full_response)
        # Strip inline code
        cleaned = _re.sub(r"`[^`]+`", "", cleaned)
        # Strip markdown headers (#, ##, etc.)
        cleaned = _re.sub(r"^#{1,6}\s+", "", cleaned, flags=_re.MULTILINE)
        # Strip bold/italic markers
        cleaned = _re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", cleaned)
        # Strip bullet dashes/asterisks at line start
        cleaned = _re.sub(r"^\s*[-*â€¢]\s+", "", cleaned, flags=_re.MULTILINE)
        # Collapse whitespace
        cleaned = " ".join(cleaned.split())

        had_code = "```" in full_response
        is_doc = self._is_document_content(full_response)
        word_count = len(cleaned.split())

        # Short response â€” always spoken verbatim (~0-15s at 150 wpm)
        if word_count <= 60:
            spoken = normalize_text(cleaned)
            if had_code:
                spoken += " The full code is in the chat window."
            return spoken

        # Medium conversational response â€” spoken in full if not document-like (~15-25s)
        if word_count <= 120 and not is_doc and not had_code:
            return normalize_text(cleaned)

        # Document, code, or long response â€” speak first sentence(s) up to 60 words
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
    # Issue C.1 â€” structured speak/show response contract
    # ------------------------------------------------------------------

    def _finalize_response(
        self, display: str, spoken: Optional[str] = None
    ) -> str:
        """Single exit for :meth:`_process_structured_response`.

        THE RULE (user, 2026-08-16): the FULL text goes to the thread, the
        spoken line goes to TTS, and a card is only for a stored artifact.
        Every return in ``_process_structured_response`` goes through here, so
        the rule is enforced in ONE place instead of at nine separate returns.
        Three of those returns had each caused the same truncation bug in turn
        (``return speak``; the card branch owning the content; the speak-tool
        ``spoken`` field) â€” the shape, not the individual returns, was the bug.

        ``spoken`` is the agent's own TTS line when it supplied one. It is
        always assigned (empty when absent) so a previous turn's line can never
        leak into this one.
        """
        self._last_spoken_text = (spoken or "").strip()
        return display or ""

    @staticmethod
    def _unwrap_tool_envelope(response: str) -> Tuple[str, Optional[str]]:
        """Return ``(display_text, spoken_line)`` for a tool-result envelope.

        The DER path can hand back a TOOL RESULT as its final output. The speak
        tool returns ``{"status": "ok", "utterance_id": ..., "spoken": text}``
        â€” JSON with neither ``speak`` nor ``show``, so
        ``parse_structured_response`` reports it as unstructured.

        When the envelope also carries a written answer (a longer
        text/content/response field), that is the display text and ``spoken``
        stays the TTS line. Otherwise the spoken text is both â€” it is the only
        text there is, and it must be shown in full.

        Returns ``(response, None)`` when this is not a tool envelope, so the
        caller falls through to the plain-text path unchanged.
        """
        try:
            parsed = json.loads(response)
        except (json.JSONDecodeError, TypeError, ValueError):
            return (response, None)
        if not isinstance(parsed, dict) or "spoken" not in parsed:
            return (response, None)
        spoken = parsed.get("spoken")
        if not isinstance(spoken, str):
            return (response, None)
        display = spoken
        for _key in ("text", "content", "response", "display", "answer"):
            _val = parsed.get(_key)
            if isinstance(_val, str) and len(_val.strip()) > len(display.strip()):
                display = _val
        return (display, spoken)

    def _process_structured_response(
        self,
        response: Optional[str],
        turn_id: Optional[str] = None,
        conversation_id: str = "default",
    ) -> str:
        """Apply the Issue C.1 speak/show contract to a final LLM response.

        ONE RULE, ONE EXIT (2026-08-17). Returns the text for the thread and
        assigns the TTS line to ``self._last_spoken_text``; a card renders only
        for a stored artifact. Every exit goes through
        :meth:`_finalize_response` â€” three separate returns each caused the same
        truncation in turn, so the exits are now consolidated rather than
        patched individually.

        Every path, and what it returns:

        ==============================  ==========================  ===========
        input                           display (return)            card
        ==============================  ==========================  ===========
        empty                           ``""``                      no
        tool envelope (``spoken``)      written answer, else        no
                                        the spoken text IN FULL
        plain text, no card             the text unchanged          no
        plain text + auto-render        supportive excerpt          yes
        ``show`` revising a document    ``""``                      revised
        ``show`` + ``speak``            the ``speak`` line          yes
        ``show``, card emit failed      the full show content       no
        ``show`` with no ``speak``      ``""``                      yes
        ==============================  ==========================  ===========

        The distinction that drives it is decided by the AGENT, not inferred
        here: ``show`` means "this is a DOCUMENT â€” store it", so it renders a
        card and the thread keeps the spoken line. Everything else is
        conversation and goes to the thread as text, in full, however long. The
        [RESPONSE FORMAT] prompt in :meth:`_build_system_prompt` is the other
        half of this contract; the two must be read together.

        Content lives in exactly one place. With a card, that place is the card
        and the document store. Without one, it is the chat message â€” which is
        why no path here may shorten it.
        """
        if not response:
            return response or ""

        # Reset the per-response render flag; set True below if a DOCUMENT_RENDER
        # is emitted (agent's format choice). Used by _maybe_escalate_web_format.
        self._last_render_emitted = False
        # Reset the per-response spoken line. Set at every exit by
        # _finalize_response, so a stale value from a previous turn can never
        # be spoken even on the paths that supply no spoken line.
        self._last_spoken_text = ""

        from backend.agent.structured_response import parse_structured_response

        speak, show = parse_structured_response(response)

        # â”€â”€ Tool-result envelope â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # ROOT CAUSE of the last truncation (2026-08-16, fixed 2026-08-17):
        # a speak-tool result reaches here as {"status", "utterance_id",
        # "spoken"}. It has neither `speak` nor `show`, so it fell into the
        # plain-text branch below and _supportive_text excerpted the RAW JSON â€”
        # an 887-char answer displayed and persisted as 55 chars.
        #
        # A handler for the "spoken" field DID exist, but it sat AFTER the
        # `show is None` return, so it could never run. That is why the earlier
        # spot-fix appeared to "return raw JSON": the branch it patched was
        # dead. Unwrapping HERE â€” before any return â€” is the fix. The dead
        # branch is gone.
        if speak is None and show is None:
            _display, _spoken = self._unwrap_tool_envelope(response)
            if _spoken is not None:
                return self._finalize_response(_display, _spoken)

        if show is None:
            # â”€â”€ Plain-text response â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # The LLM did not produce structured JSON.  Normally return the
            # full text as-is so the frontend renders it in the normal chat
            # bubble path (chat-view.tsx short-message branch) with TTS word
            # highlighting â€” no DOCUMENT_RENDER, no prism card.
            #
            # pin (user decision 2026-07-31): when this turn gathered
            # web/reference content and the response IS the synthesized
            # markdown answer (substantial), auto-render it as a markdown
            # prism card AND return the text â€” the agent's response accompanies
            # the card instead of the card popping on every web-tool commit
            # (the old capture-time deterministic render). The agent's explicit
            # `show` choice above still wins when it renders deliberately; this
            # fallback only covers the "forgot show" case. Marking
            # _last_render_emitted suppresses the format-escalation QuestionCard
            # (pin_9e97e21340e7) for this turn.
            try:
                if (
                    self._pacman_zone_for_turn() == "reference"
                    and len(response) >= 300
                ):
                    trust = "untrusted"
                    import uuid as _uuid

                    _doc_id = str(_uuid.uuid4())
                    try:
                        self._store_document_data(
                            document_id=_doc_id,
                            show={"format": "markdown", "content": response},
                            trust=trust,
                            turn_id=turn_id,
                            conversation_id=conversation_id,
                        )
                    except Exception as _store_exc:  # noqa: BLE001
                        logger.debug(
                            "[AgentKernel] auto-render store failed: %s", _store_exc
                        )
                    # REQ-6 (specs/long-horizon-der-execution): inherit the
                    # captured web evidence's source URLs + HAR path into the
                    # final synthesized card instead of emitting empty
                    # provenance. The pending web document (if any) holds the
                    # crawl's saved URLs; union them so the answer's card is
                    # verifiable.
                    _render_sources: List[Dict[str, str]] = []
                    _render_har: Optional[str] = None
                    try:
                        _pending = getattr(self, "_pending_web_doc_id", None)
                        if _pending:
                            _store = self._get_document_store()
                            _row = _store.get(_pending) if _store is not None else None
                            if _row:
                                _render_sources = _row.get("sources") or []
                                _render_har = _row.get("har_path")
                    except Exception:  # noqa: BLE001 â€” provenance is best-effort
                        pass
                    try:
                        from backend.agent.event_bus import (
                            get_event_bus,
                            IRISStreamEvent,
                        )

                        get_event_bus().emit(
                            IRISStreamEvent.DOCUMENT_RENDER,
                            data={
                                "format": "markdown",
                                "content": response[:12000],
                                "alternatives": [],
                                "trust": trust,
                                "document_id": _doc_id,
                                "turn_id": turn_id,
                                "conversation_id": conversation_id,
                                "sources": _render_sources,
                                "har_path": _render_har,
                            },
                            turn_id=turn_id,
                            conversation_id=conversation_id,
                        )
                        self._last_render_emitted = True
                    except Exception as _emit_exc:  # noqa: BLE001
                        logger.warning(
                            "[AgentKernel] synthesized-answer auto-render failed: %s",
                            _emit_exc,
                        )
            except Exception:  # noqa: BLE001 â€” auto-render must never block the response
                pass
            # UX contract (user 2026-07-31): when a prism card IS the document,
            # the text/speech response must SUPPORT it, not duplicate it â€” a
            # short excerpt so the bubble and the card show complementary
            # content.
            #
            # ONLY when a card actually rendered (user rule 2026-08-16: the
            # text must never be truncated and a document render must not be
            # REQUIRED). This excerpt used to run unconditionally, so every
            # plain answer over ~200 chars was cut down to its first sentence
            # with nothing else holding the rest. `_last_render_emitted` is set
            # at the real emit above, so this asks "did a card really render?".
            _support = (
                self._supportive_text(response)
                if getattr(self, "_last_render_emitted", False)
                else ""
            )
            return self._finalize_response(_support or response)

        # â”€â”€ Structured response â€” emit DOCUMENT_RENDER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Trust-routing W3: 'untrusted' when this turn touched external/web
        # sources, else 'trusted'. The frontend sanitizes html/mermaid when
        # A CARD IS FOR AN ARTIFACT, NOT FOR CONVERSATION (2026-08-16, user rule).
        #
        # Document renders exist for content that is STORED to be opened again
        # later: web-search results, generated markdown, plans, code. An ordinary
        # spoken-and-shown answer â€” "here is your system info" â€” is conversation,
        # and belongs in the thread as text the agent formatted readably.
        #
        # This matters because the card branch returns the short `speak` line to
        # avoid duplicating the artifact inline. When the agent renders a card
        # for a CONVERSATIONAL answer, that same branch throws the real answer
        # away: observed live with der_response_len=1787 persisted as 201 chars.
        #
        # `show` IS THE STORAGE SIGNAL (2026-08-17). No gate here.
        #
        # A previous kernel-side gate tried to infer, per turn, whether the
        # content "was really an artifact" â€” first from the web/reference zone,
        # then from the payload's content. Both are guesses, and the guess is
        # not decidable: `{"format": "markdown", "content": "plain doc"}` with no
        # provenance is required to render by
        # test_document_rehydration_wave2::test_ct_doc_2_render_absent_sources_for_plain
        # and required NOT to render by
        # test_display_text_never_truncated::test_conversational_turn_...
        # Nothing structural separates those two inputs, because the intent
        # lives with the AGENT, not with the shape of the payload.
        #
        # So the two paths are split at the source instead: the [RESPONSE FORMAT]
        # prompt now defines `show` as "a document to be STORED and reopened",
        # not "a long answer" (the old length rule is what made ordinary
        # conversation arrive here wearing a `show` payload). A `show` payload
        # therefore means store it and render it â€” and the answer can no longer
        # be lost, because the card and the document store both hold it, while
        # every path WITHOUT a `show` returns the full text to the thread.
        #
        # trust != 'trusted'.
        trust = (
            "untrusted"
            if self._pacman_zone_for_turn() == "reference"
            else "trusted"
        )
        # W4: stable document_id so the canonical data (not the render) can
        # be stored and later retrieved/reformatted by id.
        import uuid

        # Phase 4 (chat-card-redesign): if the agent includes an existing
        # document_id in its `show` payload, revise that document in place
        # (bumped revision + updated:True) instead of rendering a new card.
        existing_id = show.get("document_id")
        if existing_id and self.update_document(
            existing_id,
            content=show.get("content", ""),
            fmt=show.get("format"),
            trust=trust,
            turn_id=turn_id,
            conversation_id=conversation_id,
            alternatives=show.get("alternatives", []) or [],
        ):
            # The card was revised in place â€” it owns the content. The agent's
            # spoken line still reaches TTS.
            return self._finalize_response("", speak)
        document_id = str(uuid.uuid4())
        # W4: persist the canonical DATA (underlying structured content),
        # keyed by document_id, BEFORE the render so provenance (sources /
        # har_path, possibly inherited from a linked raw row in T2) is
        # available to surface on the render payload (REQ-6 / D2: provenance
        # is surfaced, never orphaned). Fire-and-forget so a storage failure
        # never blocks the document render.
        self._store_document_data(
            document_id=document_id,
            show=show,
            trust=trust,
            turn_id=turn_id,
            conversation_id=conversation_id,
        )
        # Surface provenance on the render. Prefer what the agent supplied in
        # `show`; fall back to the stored row (which may have inherited
        # sources/har_path from a linked raw crawler row). Tolerant of store
        # failure -> empty sources, render still succeeds.
        _render_sources = show.get("sources")
        _render_har = show.get("har_path")
        if _render_sources is None or _render_har is None:
            try:
                _store = self._get_document_store()
                _row = _store.get(document_id) if _store is not None else None
                if _row is not None:
                    if _render_sources is None:
                        _render_sources = _row.get("sources") or []
                    if _render_har is None:
                        _render_har = _row.get("har_path")
            except Exception:
                pass
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.DOCUMENT_RENDER,
                data={
                    "format": show.get("format", "markdown"),
                    "content": show.get("content", ""),
                    "alternatives": show.get("alternatives", []),
                    "trust": trust,
                    "document_id": document_id,
                    "turn_id": turn_id,
                    "conversation_id": conversation_id,
                    "sources": _render_sources or [],
                    "har_path": _render_har,
                },
                turn_id=turn_id,
                conversation_id=conversation_id,
            )
            # Mark that the agent rendered a document this turn (its CHOICE of
            # format). Used by _maybe_escalate_web_format to detect when the
            # agent returned a web result without choosing a format.
            self._last_render_emitted = True
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
            # CONTENT LIVES IN EXACTLY ONE PLACE (2026-08-16, user rule).
            #
            # A document render is for an ARTIFACT â€” search results, generated
            # markdown, a plan, code â€” something stored in the document store to
            # be opened again later. When one is rendered, the card owns the
            # content and the chat keeps the agent's conversational line, so the
            # thread is not a wall of duplicated markdown.
            #
            # When NO card was rendered, the chat message is the only place the
            # answer exists, so it must carry the FULL text. Returning `speak`
            # unconditionally (the old behaviour) is what silently discarded a
            # 1492-char answer down to a 201-char summary.
            #
            # `_last_render_emitted` is set at the actual emit above, so this
            # asks "did a card really render?" rather than assuming one did.
            if getattr(self, "_last_render_emitted", False):
                return self._finalize_response(speak or "", speak)
            return self._finalize_response(
                (show.get("content") or "").strip() or speak, speak
            )
        # speak is None and a `show` payload exists. The card carries the
        # content; returning the raw JSON here would speak it and show it as the
        # assistant's message.
        #
        # The speak-tool "spoken" handler that used to sit here was DEAD CODE â€”
        # reaching it required `show` to be a dict AND the same JSON to carry a
        # top-level "spoken", which the speak tool never produces. Its real
        # payload is unwrapped at the top of this function now.
        return self._finalize_response("")

    # â”€â”€ W4: canonical document-data storage â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _get_document_store(self):
        """Return the DocumentDataStore for this kernel's memory DB, or None."""
        try:
            from backend.agent.document_store import DocumentDataStore

            return DocumentDataStore.get_for(self._memory_interface)
        except Exception as exc:
            logger.warning("[AgentKernel] document store unavailable: %s", exc)
            return None

    @staticmethod
    def _extract_sources_from_raw(content: str) -> list:
        """Extract {url,title} sources from a raw crawler_query blob (REQ-5).

        Tolerant of shape: prefers '--- Source: <url> ---' markers (observed in
        live crawler output) and falls back to any http(s) URL. Returns [] on
        failure â€” never raises into the store path (design risk: malformed JSON
        -> empty sources, store still succeeds).
        """
        import re

        sources: list = []
        try:
            if not content:
                return sources
            seen: set = set()
            for m in re.finditer(r"---?\s*Source:\s*(\S+)\s*---?", content):
                url = m.group(1)
                if url.startswith("http") and url not in seen:
                    seen.add(url)
                    sources.append({"url": url, "title": url})
            if sources:
                return sources
            for m in re.finditer(r"https?://[^\s\"'<>]+", content):
                url = m.group(0)
                if url not in seen:
                    seen.add(url)
                    sources.append({"url": url, "title": url})
        except Exception:
            pass
        return sources

    @staticmethod
    def _apply_trust_ceiling(trust: str, content_origin: str) -> str:
        """REQ-18 AC3: vision-derived content is never stored above the trust of
        equivalent crawled web content (which is ``untrusted``).

        Extracted as a pure function so the ceiling is directly assertable and
        so there is exactly ONE place that decides it. A caller passing
        ``trust="trusted"`` for vision output is downgraded, not honoured â€”
        provenance beats the caller's claim.
        """
        if content_origin in ("vision", "reconciled") and trust != "untrusted":
            logger.info(
                "[AgentKernel] document_data trust ceiling: origin=%s trust=%s "
                "-> untrusted (REQ-18 AC3)", content_origin, trust,
            )
            return "untrusted"
        return trust

    def _store_document_data(
        self,
        document_id: str,
        show: dict,
        trust: str,
        turn_id: Optional[str],
        conversation_id: str,
    ) -> None:
        """Persist a document's canonical DATA (not its render) keyed by document_id.

        Two coordinated homes (plan W4):
          * Mycelium (episodic.fragment_and_store) â€” semantically retrievable
            later via mcm_recall / pacman_recall, scoped by zone (trust).
          * Immortus 4D chain (immortus_chain_append) â€” placed in the reasoning
            trajectory via coords_from->coords_to so it "finds its place".

        The rendered ``content`` is only a view derived on demand; the stored
        source of truth is the canonical {format, content, alternatives}.
        All failures are swallowed â€” storage must never block the render.
        """
        import json

        fmt = show.get("format", "markdown")
        content = show.get("content", "")
        # W5 (G1): store the actual rendered content of each alternative format.
        # The LLM may emit `variants: {format: content}` in one response; we
        # always also register the primary format's content as a variant so a
        # reformat to the original format is deterministic too.
        variants = dict(show.get("variants", {}) or {})
        variants[fmt] = content

        # REQ-18 AC2/AC3: provenance travels with the content, and vision-derived
        # content is never stored at a HIGHER trust than equivalent crawled web
        # content. The ceiling is enforced HERE, at the single choke point every
        # document passes through, rather than at each call site â€” one guard
        # cannot be forgotten by a future caller. ContentOrigin previously lived
        # only inside frame_extraction.py and never reached the store at all, so
        # vision output was indistinguishable from DOM text once persisted.
        content_origin = str(show.get("content_origin") or "crawl")
        trust = self._apply_trust_ceiling(trust, content_origin)

        canonical = {
            "document_id": document_id,
            "format": fmt,
            "content": content,
            "variants": variants,
            "alternatives": show.get("alternatives", []),
            "trust": trust,
            "content_origin": content_origin,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
        }
        canonical_text = json.dumps(canonical, ensure_ascii=False)
        zone = "reference" if trust == "untrusted" else "trusted"

        # â”€â”€ Immortus 4D chain coordinate (computed early; used by W8 seed + Immortus) â”€â”€
        # coords_from = the agent's actual reasoning-state coordinate at the
        # moment this document was produced (sourced from the Caducean
        # trajectory recorder). This is what lets W7/O1 do trajectory-proximity
        # recall ("data gathered while thinking like this") instead of a flat
        # append. Falls back to "" if no trajectory has been recorded yet.
        coords_from = ""
        try:
            from backend.agent.caducean_trajectory import (
                format_coords,
                get_trajectory_recorder,
            )

            # REQ-4: Primary lookup = recording session id (self.session_id);
            # fallback = conversation_id (REST path where they coincide).
            # Use getattr for safety (test-only __new__ paths may skip __init__).
            _lookup_id = getattr(self, "session_id", None) or conversation_id
            _coord = get_trajectory_recorder(
                self._memory_interface
            ).get_latest_coordinate(_lookup_id)
            # Fallback: if primary didn't match and differs from conversation_id,
            # try conversation_id directly (REQ-4 AC3 / REST-path).
            if _coord is None and _lookup_id != conversation_id:
                _coord = get_trajectory_recorder(
                    self._memory_interface
                ).get_latest_coordinate(conversation_id)
            if _coord is not None:
                coords_from = format_coords(
                    _coord["x"], _coord["y"], _coord["xi"], _coord["u"]
                )
        except Exception as exc:
            logger.warning("[AgentKernel] document_data coord lookup failed: %s", exc)

        # â”€â”€ Wave 0/1 provenance linkage (REQ-5/REQ-13) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Persist source_document_id / sources / har_path so documents rehydrate
        # with provenance. Tolerant of shape: malformed input -> empty sources,
        # store still succeeds (design risk).
        source_document_id = show.get("source_document_id")
        sources = show.get("sources")
        har_path = show.get("har_path")
        source_tool = show.get("source_tool")

        if source_tool == "crawler_query":
            if fmt == "json":
                # Raw crawler_query result row: extract sources from content.
                if sources is None:
                    sources = self._extract_sources_from_raw(content)
            else:
                # Synthesized show reusing a crawl: link to the most recent raw
                # JSON row in this conversation and inherit its provenance.
                if not source_document_id:
                    try:
                        store0 = self._get_document_store()
                        if store0 is not None:
                            raw_rows = store0.list_for_conversation(
                                conversation_id, metadata_only=False
                            )
                            raw = next(
                                (r for r in reversed(raw_rows)
                                 if r.get("format") == "json"),
                                None,
                            )
                            if raw is not None:
                                source_document_id = raw.get("document_id")
                                if not sources and raw.get("sources"):
                                    sources = raw["sources"]
                                if not har_path and raw.get("har_path"):
                                    har_path = raw["har_path"]
                    except Exception:
                        pass

        # â”€â”€ DocumentDataStore: source-of-truth keyed by document_id (G4) â”€â”€â”€â”€
        try:
            store = self._get_document_store()
            if store is not None:
                store.store(
                    document_id=document_id,
                    conversation_id=conversation_id,
                    fmt=fmt,
                    content=content,
                    variants=variants,
                    alternatives=show.get("alternatives", []),
                    trust=trust,
                    source_document_id=source_document_id,
                    sources=sources,
                    har_path=har_path,
                    # _store_document_data has always TAKEN turn_id and never
                    # passed it on, so every stored document was unattributable:
                    # a rehydrated card could not be paired with the exchange
                    # that produced it, which is why the answer text and its card
                    # both rendered, neither aware of the other.
                    turn_id=turn_id,
                )
        except Exception as exc:
            logger.warning("[AgentKernel] document_data store failed: %s", exc)

        # Session 245 (live memory footer): surface the DOCUMENT STORE on the
        # card's footer — a websearch's crawled content landing in
        # document_data + episodic chunks is exactly the memory activity the
        # user wants to see while execution happens. outcome_type distinguishes
        # it from step stores / recall.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.MEMORY_EVENT,
                data={
                    "kind": "episodic",
                    "task_summary": f"Document stored: {str(document_id)[:40]} ({len(canonical_text)} chars)",
                    "outcome_type": "document_store",
                    "duration_ms": 0,
                },
                session_id=self.session_id,
                conversation_id=conversation_id,
            )
        except Exception:
            pass  # never block the document store on an emit failure

        # â”€â”€ Mycelium: semantic/episodic store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # OFF THE CRITICAL PATH (2026-08-17, same rule as the pacman_fragment
        # mediator). Storing means embedding, and the CPU-only encoder costs
        # ~5 s per 1 KB chunk â€” a 14-chunk document blocked the DER loop for
        # ~50-90 s per step. Measured live: three inter-step gaps of 88 s, 72 s
        # and 84 s accounted for 244 s of a 311 s turn, while the mediator's own
        # fragments (already async) filed in the background without stalling it.
        #
        # Same background writer, so ALL filing is uniform: one serialized
        # worker, a bounded queue, and a FILED / FILE FAILED / QUEUE FULL log
        # line for every job (user rule: nothing waits on the filing, but it
        # must be trackable if it breaks).
        try:
            mi = getattr(self, "_memory_interface", None)
            if mi is not None and getattr(mi, "episodic", None) is not None:
                from backend.agent.mcm_protocol.actions.pacman_fragment import (
                    _submit_fragment_job,
                )

                _episodic = mi.episodic
                _submit_fragment_job(
                    lambda: _episodic.fragment_and_store(
                        canonical_text,
                        conversation_id,
                        chunk_type="document_data",
                        zone=zone,
                    ),
                    f"document_data/{document_id} ({len(canonical_text)} chars)",
                )
        except Exception as exc:
            logger.warning("[AgentKernel] document_data Mycelium store failed: %s", exc)

        # â”€â”€ Mycelium: seed document data as a trust-routed context node (W8/O2) â”€â”€
        # So trusted, frequently-referenced data can crystallize into a permanent
        # landmark at PERMANENCE_THRESHOLD. Trust routing is CellWall-enforced
        # inside the interface â€” never bypassed. coords_from is the agent's real
        # reasoning-state coordinate ("x,y,xi,u"); the interface parses it.
        try:
            if mi is not None and hasattr(mi, "ingest_document_data"):
                mi.ingest_document_data(
                    content=canonical_text,
                    trust=trust,
                    session_id=conversation_id,
                    coords=coords_from,
                    label=document_id,
                )
        except Exception as exc:
            logger.warning("[AgentKernel] document_data Mycelium seed failed: %s", exc)



        # OFF THE CRITICAL PATH. This is a durability/audit write, not part of
        # producing the answer â€” but it ran INLINE on the DER thread after every
        # tool result. A live stack dump caught the thread parked in
        # ffi_immortus_chain_append -> SQLite right after a web search returned,
        # so a finished crawl looked hung and its UI events never surfaced.
        # `canonical_text` carries the full rendered document (for a crawl, the
        # page content), so the cost scales with how much the search found.
        #
        # NOTE this is the SECOND such write on the same path â€” tool_bridge's
        # _record_tool_event had the identical problem and was moved off-thread
        # first; fixing it simply revealed this one underneath. If a third
        # appears, the pattern (not the instance) is what needs addressing.
        try:
            import threading as _threading

            from backend.gateway.iris_ffi import ffi_immortus_chain_append

            def _append_chain() -> None:
                try:
                    ffi_immortus_chain_append(
                        thread_id=conversation_id,
                        result=canonical_text,
                        coords_from=coords_from,
                        coords_to=canonical.get("format", "document"),
                        nbl_outcome="document_render",
                        insight=canonical.get("format", "document"),
                        file_path=document_id,
                        landmark_id="",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[AgentKernel] document_data Immortus store failed: %s", exc)

            _threading.Thread(
                target=_append_chain, daemon=True, name="immortus-chain-append",
            ).start()
        except Exception as exc:
            logger.warning("[AgentKernel] document_data Immortus dispatch failed: %s", exc)

    def update_document(self, document_id, content, fmt=None, trust=None, turn_id=None, conversation_id=None, alternatives=None):
        """Phase 4 (chat-card-redesign): revise an already-rendered document.

        Updates the canonical data in DocumentDataStore (keyed by document_id;
        revision bumped) and re-emits DOCUMENT_RENDER with ``updated: True`` so the
        frontend reflects the edit in place (with an 'Updated' indicator) instead
        of appending a new card.  Returns the document_id, or None if the id is
        unknown (caller should then do a fresh render).
        """
        try:
            from backend.agent.document_store import DocumentDataStore
            store = DocumentDataStore.get_for(self._memory)
            if store is None:
                return None
            existing = store.get(document_id)
            if existing is None:
                return None
            new_fmt = fmt or existing.get("format") or "markdown"
            variants = dict(existing.get("variants") or {})
            variants[new_fmt] = content
            store.update(
                document_id=document_id,
                content=content,
                fmt=new_fmt,
                variants=variants,
                trust=trust or existing.get("trust") or "trusted",
            )
            revision = (existing.get("revision") or 0) + 1
            payload = {
                "format": new_fmt,
                "content": content,
                "alternatives": alternatives if alternatives is not None else (existing.get("alternatives") or []),
                "trust": trust or existing.get("trust") or "trusted",
                "document_id": document_id,
                "turn_id": turn_id or existing.get("turn_id"),
                "conversation_id": conversation_id or self.conversation_id,
                "updated": True,
                "revision": revision,
                "sources": existing.get("sources") or [],
                "har_path": existing.get("har_path"),
            }
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                get_event_bus().emit(
                    IRISStreamEvent.DOCUMENT_RENDER,
                    data=payload,
                    turn_id=payload["turn_id"],
                    conversation_id=payload["conversation_id"],
                )
            except Exception as exc:
                logger.warning("[AgentKernel] DOCUMENT_RENDER(update) emit failed: %s", exc)
            return document_id
        except Exception as exc:
            logger.warning(f"[AgentKernel] update_document failed: {exc}")
            return None

    # â”€â”€ W9 (O3): proactive structured-data capture from ANY tool result â”€â”€â”€â”€â”€â”€
    # Plan W9: extend capture beyond `show` payloads to any tool result
    # (web_search, crawler_query, read_file, ...) so everything the agent
    # touches becomes reformat-able via the same DocumentDataStore. Scoped by a
    # relevance/structure threshold so trivial results are not embedded.

    _MIN_CAPTURE_CHARS = 50       # below this, a result is "trivial"
    _RELEVANCE_THRESHOLD = 0.30   # results carrying a score below this are skipped

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """json.dumps ``default=`` for tool-result payloads that carry
        non-JSON-native objects (D4e â€” e.g. crawler CredibilityMap nested
        inside a web_search/crawler_query result dict, which raised "Object
        of type CredibilityMap is not JSON serializable" and dropped the
        whole DER tool-result capture).

        Dataclasses (CredibilityMap included) serialize field-by-field via
        asdict() so the JSON stays structured (per_source/unsourced_claims/
        top_score), not an opaque repr string. Falls back to vars()/str()
        for plain objects so nothing this touches can raise again.
        """
        import dataclasses
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
        return str(obj)

    def _is_capture_worthy(self, tool_name: str, result: Any) -> bool:
        """Cheap, deterministic gate (no I/O, no LLM) for whether to persist a result.

        * None / empty results are skipped.
        * Explicit error payloads ({"error": ...}) are skipped.
        * Very short results (< _MIN_CAPTURE_CHARS) are skipped as trivial.
        * Results carrying a numeric relevance/score below _RELEVANCE_THRESHOLD
          are skipped (low-signal).
        """
        if result is None:
            return False
        if isinstance(result, dict):
            if "error" in result:
                return False
            score = result.get("relevance") or result.get("score")
            if isinstance(score, (int, float)) and float(score) < self._RELEVANCE_THRESHOLD:
                return False
            payload = result
        else:
            payload = result
        import json

        text = (
            payload if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False, default=self._json_default)
        )
        if len(text) < self._MIN_CAPTURE_CHARS:
            return False
        return True

    def _capture_tool_result(
        self,
        tool_name: str,
        result: Any,
        conversation_id: str,
        turn_id: Optional[str] = None,
        session_id: str = "unknown",
    ) -> Optional[str]:
        """Persist a tool result into the document store so it becomes reformat-able.

        Trust-routing (W2/W3): external tools (web_search, crawler_query) are
        stored as ``untrusted``; everything else (e.g. read_file) as ``trusted``.
        Returns the new document_id, or None when the result was skipped by the
        capture-worthiness gate. All failures are swallowed â€” capture must never
        block the tool result from reaching the agent.
        """
        # â”€â”€ ChatCard redesign (pin_9e97e21340e7): external/web tool results are
        # captured into the document store (reformat-able) so the agent can
        # render them as a Prism Glass document card via its own `show` choice.
        # The RENDER itself is the agent's decision â€” it must emit a `show`
        # payload choosing the format (markdown/table/html/diagram/text). If the
        # agent does NOT choose a format (returns plain text), we escalate to a
        # QuestionCard (ask_user_question) offering the format options, rather
        # than silently dumping a raw .md file. We only track the pending web
        # doc_id here; the escalation check runs after the agent's response is
        # processed in _process_structured_response (see _maybe_escalate_web_format).
        is_external = is_external_tool(tool_name)

        if not self._is_capture_worthy(tool_name, result):
            return None
        import uuid

        import json

        document_id = str(uuid.uuid4())
        fmt = "json" if isinstance(result, (dict, list)) else "text"
        content = (
            json.dumps(result, ensure_ascii=False, default=self._json_default)
            if isinstance(result, (dict, list)) else str(result)
        )
        show = {
            "format": fmt,
            "content": content,
            "variants": {fmt: content},
            "source_tool": tool_name,
        }
        # Thread provenance (HAR path) from the crawl result into the stored show
        # so the raw JSON row carries it (REQ-13). Tolerant of result shape:
        # dict (serialized) or CrawlResult object. Never raises.
        if isinstance(result, dict):
            if result.get("har_path"):
                show["har_path"] = result["har_path"]
            if result.get("sources"):
                show["sources"] = result["sources"]
        elif hasattr(result, "har_path"):
            show["har_path"] = result.har_path
        trust = "untrusted" if is_external else "trusted"
        try:
            self._store_document_data(document_id, show, trust, turn_id, conversation_id)
        except Exception as exc:
            logger.warning("[AgentKernel] tool-result capture failed: %s", exc)
            return None
        # Track external/web results for the post-response escalation check.
        # If the agent's final response does not render this document (no `show`
        # payload), _maybe_escalate_web_format() asks the user which format they
        # want via a QuestionCard (pin_9e97e21340e7) â€” UNLESS the response was
        # substantial synthesized markdown, which _process_structured_response
        # auto-renders (see the show-is-None branch there).
        # pin: the capture-time deterministic DOCUMENT_RENDER (old pin
        # 517dfcbda150) was REMOVED by user decision â€” it popped a card on EVERY
        # web-tool commit (every crawl mid-research), not just the final answer.
        # The synthesized-answer auto-render lives at response time instead.
        if is_external and tool_name in self._WEB_CONTENT_TOOLS:
            self._pending_web_doc_id = document_id
        return document_id

    def _maybe_escalate_web_format(self, turn_id: str, conversation_id: str) -> None:
        """Escalate a web result's format choice to the user via a QuestionCard.

        Called after the agent's response is processed. If a web/crawler result
        was captured this turn (``_pending_web_doc_id`` set) but the agent did
        NOT render it as a document (``_last_render_emitted`` is False â€” i.e. it
        returned plain text without a ``show`` format choice), we ask the user
        which format they want. This honors the ChatCard redesign: the rendered
        document is the agent's choice, and when the agent is unsure it escalates
        to a multiple-choice QuestionCard (pin_9e97e21340e7).

        Non-blocking: we emit the question and let the frontend collect the
        answer asynchronously (the agent's response continues).
        """
        pending = getattr(self, "_pending_web_doc_id", None)
        # Clear the flag regardless â€” each web result gets at most one escalation.
        self._pending_web_doc_id = None
        if not pending:
            return
        if getattr(self, "_last_render_emitted", False):
            # Agent already chose a format and rendered the document. No escalation.
            return
        try:
            from backend.agent.tools.ask_user_tool import get_ask_user_tool

            tool = get_ask_user_tool()
            tool.ask(
                text="I found web results. How would you like me to present them?",
                options=["Markdown", "Table", "HTML", "Diagram", "Plain text"],
                allow_other=False,
                turn_id=turn_id,
                conversation_id=conversation_id,
                context={"document_id": pending, "source": "web_format_escalation"},
            )
        except Exception as exc:
            logger.warning("[AgentKernel] web format escalation failed: %s", exc)

    def reformat_document(
        self,
        document_id: Optional[str] = None,
        content: Optional[str] = None,
        target_format: str = "",
        conversation_id: str = "default",
        turn_id: Optional[str] = None,
        original_format: Optional[str] = None,
        trust: Optional[str] = None,
    ) -> Optional[str]:
        """Re-render a previously generated document in a different format.

        W5 (data-centric): the primary path retrieves the document's canonical
        data + stored variants by ``document_id`` (the frontend sends only
        ``{document_id, target_format}`` â€” no client ``content``).  Deterministic
        first (G1): if ``target_format`` is already a stored variant, it is
        returned with **zero LLM calls**.  Only genuinely new formats invoke the
        LLM on the canonical data, and the result is cached as a new variant.

        A ``content``-based fallback (pre-W5) remains for direct/legacy callers;
        it always goes through the LLM.

        ``trust`` (trust-routing W3) is carried through so a reformatted
        document keeps the original's trust level.  Returns the new content, or
        None on failure.  Issue D.2.
        """
        if not target_format:
            return None

        # â”€â”€ W5 primary path: retrieve by document_id â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if document_id:
            store = self._get_document_store()
            doc = store.get(document_id) if store is not None else None
            orig_fmt = original_format or (doc.get("format") if doc else None)
            if doc is None:
                logger.warning(
                    "[AgentKernel] reformat_document: document_id %s not found",
                    document_id,
                )
                return None
            stored_trust = doc.get("trust") or trust or "trusted"

            # Deterministic-first (G1): stored variant -> no LLM.
            variant = store.get_variant(document_id, target_format) if store else None
            if variant is not None:
                payload = {
                    "format": target_format,
                    "content": variant,
                    "alternatives": doc.get("alternatives") or [],
                    "trust": stored_trust,
                    "document_id": document_id,
                    "turn_id": turn_id,
                    "conversation_id": conversation_id,
                    "reformatted": True,
                    "sources": doc.get("sources") or [],
                    "har_path": doc.get("har_path"),
                }
                try:
                    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                    get_event_bus().emit(
                        IRISStreamEvent.DOCUMENT_RENDER,
                        data=payload,
                        turn_id=turn_id,
                        conversation_id=conversation_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "[AgentKernel] DOCUMENT_RENDER (reformat) emit failed: %s", exc
                    )
                self._record_reformat_edge(store, orig_fmt, target_format)
                return variant

            # No stored variant -> LLM reformat on the canonical data.
            content = doc.get("content", "")
            original_format = original_format or doc.get("format")

        # â”€â”€ LLM reformat path (W5 new format, or legacy content fallback) â”€â”€â”€
        if not content:
            return None
        prompt = (
            "Reformat the following document as " + target_format + ". "
            "Preserve all information and meaning. "
            'Respond with JSON: {"show": {"format": "' + target_format + '", '
            '"content": "<reformatted text>", "alternatives": ["<other formats>"]}} '
            "or, if plain text is clearer, just return the reformatted text.\n\n"
            "DOCUMENT:\n" + content
        )
        try:
            reformatted = self._respond_direct(prompt, context=[])
        except Exception as exc:
            logger.warning("[AgentKernel] reformat_document LLM call failed: %s", exc)
            return None
        if not reformatted:
            return None

        from backend.agent.structured_response import build_reformat_payload

        payload = build_reformat_payload(
            reformatted,
            target_format=target_format,
            turn_id=turn_id,
            conversation_id=conversation_id,
            original_format=original_format,
            trust=trust,
        )
        # T6: reformat payload preserves document_id + trust.
        if document_id:
            payload["document_id"] = document_id
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.DOCUMENT_RENDER,
                data=payload,
                turn_id=turn_id,
                conversation_id=conversation_id,
            )
        except Exception as exc:
            logger.warning(
                "[AgentKernel] DOCUMENT_RENDER (reformat) emit failed: %s", exc
            )
        # Cache the new variant so future reformats are deterministic (G1).
        if document_id:
            try:
                store = self._get_document_store()
                if store is not None:
                    store.add_variant(document_id, target_format, payload.get("content", ""))
            except Exception as exc:
                logger.warning("[AgentKernel] reformat variant cache failed: %s", exc)
        self._record_reformat_edge(self._get_document_store(), original_format, target_format)
        return payload["content"]

    # â”€â”€ W10 (O4): pheromone-reinforced reformat + cross-modal synergy â”€â”€â”€â”€â”€â”€â”€â”€
    # Plan W10: reinforce the reformat action's pheromone edge when used, so
    # frequently-reformatted doc types become "sticky" (the agent can proactively
    # offer a reformat), and expose cross-modal views (vocalize / diagram) that
    # reuse existing channels (SpeakTool, reformat_document's diagram format).

    def _record_reformat_edge(self, store, from_format, to_format):
        """Safely reinforce a reformat pheromone edge (W10/O4)."""
        if store is None or not from_format or not to_format:
            return
        try:
            store.record_reformat(from_format, to_format)
        except Exception as exc:
            logger.warning("[AgentKernel] reformat edge record failed: %s", exc)

    def suggest_reformat(self, document_id: str, conversation_id: str = "default") -> Optional[str]:
        """Proactively suggest the next format for a document (W10/O4 substrate).

        Returns the most-reinforced target format for the document's current
        format (from the reformat pheromone edges), or None if no signal yet.
        This is the primitive the agent/UI uses to *offer* a reformat of a
        frequently-touched doc type.
        """
        try:
            store = self._get_document_store()
            if store is None:
                return None
            doc = store.get(document_id)
            if doc is None:
                return None
            return store.predict_next_format(doc.get("format"))
        except Exception as exc:
            logger.warning("[AgentKernel] suggest_reformat failed: %s", exc)
            return None

    def vocalize_document(
        self,
        document_id: str,
        target_format: str = "text",
        conversation_id: str = "default",
        turn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cross-modal synergy (W10/O4): speak a reformatted view of a document.

        Reformats the stored document to ``target_format`` (reusing W5's
        data-centric reformat) and vocalizes the result via the SpeakTool
        (existing TTS channel). Fire-and-forget â€” returns the speak status.
        """
        content = self.reformat_document(
            document_id=document_id,
            target_format=target_format,
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
        if not content:
            return {"status": "error", "reason": "no content to speak"}
        try:
            from backend.agent.tools.speak_tool import get_speak_tool

            return get_speak_tool().speak(content)
        except Exception as exc:
            logger.warning("[AgentKernel] vocalize_document failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

    def diagram_document(
        self,
        document_id: str,
        conversation_id: str = "default",
        turn_id: Optional[str] = None,
    ) -> Optional[str]:
        """Cross-modal synergy (W10/O4): return a diagram view of a document.

        Reuses reformat_document's existing ``diagram`` (mermaid) format â€” the
        "turn data into a diagram" synergy without a separate Vision generator.
        Returns the mermaid/diagram content, or None on failure.
        """
        return self.reformat_document(
            document_id=document_id,
            target_format="diagram",
            conversation_id=conversation_id,
            turn_id=turn_id,
        )

    def retrieve_documents_by_trajectory(
        self,
        coords: Sequence[float],
        threshold: float = 1.0,
        limit: int = 10,
        conversation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """O1 (W7): return document data produced in a *similar reasoning state*.

        Queries the Immortus 4D chain by coordinate proximity (not embedding
        cosine) and returns the canonical document data for document entries
        (``nbl_outcome='document_render'``, ``file_path`` set). This is the novel
        primitive: "data gathered while thinking like this."  Fire-and-forget â€”
        returns [] on any failure.
        """
        try:
            import json
            from backend.gateway.iris_ffi import ffi_immortus_chain_query_by_coordinate

            entries = ffi_immortus_chain_query_by_coordinate(
                coords,
                threshold=threshold,
                limit=limit,
                thread_id=conversation_id,
                nbl_outcome="document_render",
            )
            docs = []
            for e in entries:
                if not e.get("file_path"):
                    continue
                try:
                    data = json.loads(e.get("result") or "{}")
                except Exception:
                    data = {}
                data["_distance"] = e.get("distance")
                docs.append(data)
            return docs
        except Exception as exc:
            logger.warning("[AgentKernel] trajectory doc retrieval failed: %s", exc)
            return []

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
        context: Optional[List[Dict[str, Any]]] = None,
        episodic_context: Optional[str] = None,
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

        # â”€â”€ Phase 2.1: full conversation history (no index slicing) â”€â”€
        # The active thread is passed in its entirety so the planner can resolve
        # references like "do the websearch" / "the pricing of those" back to the
        # original query from earlier turns (fixes the toggle-restoration context
        # loss). This is the whole point of the universal DER loop.
        if context:
            history_lines = []
            for msg in context:  # Entire thread history is included
                role = (msg.get("role") or "user").upper()
                content = msg.get("content") or ""
                history_lines.append(f"{role}: {content}")
            if history_lines:
                sections.append(
                    "CONVERSATION HISTORY (full thread):\n"
                    + "\n".join(history_lines)
                )

        # â”€â”€ Phase 2.1: PACMAN semantic recall from past sessions â”€â”€
        if episodic_context:
            sections.append(
                f"RECALLED EPISODIC CONTEXT (PACMAN):\n{episodic_context}"
            )

        return "\n\n".join(sections)

    def _get_failure_warnings(self, task: str) -> str:
        """
        Fetch high-signal failure warnings from Mycelium via ResolutionEncoder.
        Returns "None" on any error â€” never raises, never blocks.
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

    def _der_recall_neighborhood(self, item, session_id: str = "") -> list:
        """REQ-20 AC3 (T21): filtered ontology-neighborhood chain recall.

        Builds RecallFilters from THIS node's record (node_type + both
        domain axes) and queries the shared chain with the widen-order
        (relationship -> type -> domain, winning scope logged). Returns
        chain-row dicts, or [] on any failure â€” the step proceeds on live
        state, never an error. Cross-conversation by default (AC1b):
        thread_id ranks, never filters.

        REQ-6 AC3 (semantic gate): the recall execution is the SHARED helper
        ``run_filtered_recall`` (ontology_recall.py) â€” the gate's Tier 2 calls
        the same code path, so the widen-order and telemetry cannot drift.
        """
        try:
            from backend.agent.ontology_recall import (
                RecallFilters,
                resolve_mycelium_conn,
                run_filtered_recall,
            )

            _rec = getattr(item, "node_record", None) or getattr(
                item, "footprint", None
            )
            _filters = RecallFilters(
                node_type=getattr(_rec, "node_type", None)
                or getattr(item, "node_type", None),
                topic_domain=getattr(_rec, "topic_domain", None)
                or getattr(item, "topic_domain", None),
                execution_domain=getattr(_rec, "execution_domain", None)
                or getattr(item, "execution_domain", None),
                thread_id=session_id or getattr(item, "session_id", None) or None,
                limit=3,
            )
            if not _filters.has_any:
                return []  # no ontology axes on this node â€” nothing to filter

            _conn = resolve_mycelium_conn(self._memory_interface)
            if _conn is None:
                return []

            return run_filtered_recall(_conn, _filters)
        except Exception as exc:
            logger.debug("[DER] ontology neighborhood recall failed: %s", exc)
            return []

    def _plan_task(
        self,
        text: str,
        context: Optional[List[Dict[str, Any]]] = None,
        is_mature: bool = False,
        task_class: str = "full",
        context_package=None,
        mode: str = "full",
        session_id: str = "unknown",
    ) -> Optional[ExecutionPlan]:
        """
        DER-aware planning wrapper. Returns ExecutionPlan (or None on failure).
        Mode + maturity-aware temperature:
          debug/review  â†’ 0.0  (deterministic â€” finding bugs, not exploring)
          implement      â†’ 0.1  (low â€” structured code generation)
          research       â†’ 0.3  (higher â€” exploratory synthesis)
          default        â†’ 0.1 if mature else 0.25
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

        # â”€â”€ Phase 5: Caducean-governed planning temperature â”€â”€
        # Modulate the base (mode-derived) temperature by the live Caducean
        # recommendation: COMPRESS (rec==1) -> more deterministic (lower temp);
        # EXPAND (rec==0) -> more exploratory (higher temp, capped); MAINTAIN
        # (rec==2) / unknown / TOPO_VIOLATION -> base.  Never raises.
        temperature = self._caducean_modulate_temperature(temperature, session_id)

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

        # Build the AVAILABLE TOOLS block so the Director (LLM planner) can
        # assign REAL tool names to plan steps.  Without this, the planner
        # returns tool:null for every step, the DER Explorer falls through to
        # _run_step_direct (text only), and the agent replies "[step N completed]"
        # instead of actually executing the tool.  This is the root cause of the
        # "responds to the prompt as step 1 completed, never searches" bug.
        _tools_block = ""
        try:
            # Ensure the tool bridge exists BEFORE reading the tool list â€” a
            # fresh kernel has a None bridge (lazy-init only ran on the OpenAI
            # tools path), which silently yields an empty AVAILABLE TOOLS block
            # and the planner then emits tool-less speak steps (2026-08-12:
            # explicit "use screenshot_page" requests planned as trivial).
            self._ensure_tool_bridge()
            if self._tool_bridge is not None:
                _avail = self._tool_bridge.get_available_tools()
                if _avail:
                    _tlines = [
                        f'  - "{_t.get("name", "")}" [{_t.get("category", "")}]: '
                        f'{_t.get("description", "")}'
                        for _t in _avail
                    ]
                    _tools_block = (
                        "AVAILABLE TOOLS â€” when a step needs a capability, set its "
                        "\"tool\" to the EXACT name below:\n" + "\n".join(_tlines)
                    )
        except Exception as _tb_exc:
            logger.debug("[AgentKernel._plan_task] tools block build failed: %s", _tb_exc)

        # â”€â”€ Phase 2.1: PACMAN semantic recall (best-effort, never blocks) â”€â”€
        episodic_context = ""
        try:
            if self._memory_interface is not None and hasattr(
                self._memory_interface, "episodic"
            ):
                episodic_context = (
                    self._memory_interface.episodic.assemble_episodic_context(text)
                    or ""
                )
        except Exception as _ep_exc:
            logger.debug("[AgentKernel._plan_task] episodic recall failed: %s", _ep_exc)

        planning_prompt = self._build_planning_prompt(
            task=text,
            tier1_directives=tier1,
            behavior_preds=preds,
            failure_warnings=failures,
            task_class=task_class,
            strategy_hint=strategy_hint,
            context=context,
            episodic_context=episodic_context,
        )

        system_prompt = ""
        if self._personality:
            try:
                system_prompt = self._personality.get_system_prompt()
            except Exception:
                pass

        full_prompt = (
            f"{system_prompt}\n\n{planning_prompt}\n\n"
            + (f"{_tools_block}\n\n" if _tools_block else "")
            + "Respond with JSON only â€” no prose, no markdown fences:\n"
            '{"strategy":"do_it_myself|spawn_children|delegate_external",'
            '"plan_title":"short 2-3 word summary of what the plan does (e.g. \\"Search web for AI news\\")",'
            '"reasoning":"one sentence explaining the approach",'
            '"steps":[{"step_id":"s1","step_number":1,"description":"Search the web for the user request","tool":"search","params":{"query":"<what to search>"},"depends_on":[],"critical":true}]}'
            "\n\n"
        "RULES:\n"
        "- If a step requires a capability (web search, open app, screenshot, read file, etc.) set \"tool\" to the EXACT name from AVAILABLE TOOLS. For web searches use \"search\" (or \"web_search\").\n"
        "- If a step is pure reasoning/synthesis with no tool, set \"tool\":null.\n"
        "- Always include the needed parameters in \"params\" (web search needs {\"query\":\"...\"}).\n"
        "- In 'depends_on', provide a list of step_ids that this step depends on. "
        "If there are no dependencies, provide an empty array []. A step will not "
        "start until all steps it depends on have completed.\n"
    )

        plan_raw: Optional[str] = None
        try:
            # Primary path: route planning through the unified InferenceRouter so
            # API providers (Cerebras, OpenAI, â€¦) are used â€” not just local/Ollama
            # models. Legacy LM Studio / Ollama branches below remain as fallbacks
            # for local-model configurations.
            try:
                _rt_text, _rt_think, _rt_tools = self._router.generate(
                    "reasoning",
                    [{"role": "user", "content": full_prompt}],
                    max_tokens=4096,
                    temperature=temperature,
                )
                self._accrue_tokens(
                    _rt_text, getattr(self._router, "last_usage", None),
                    source="_plan_task",
                )
                if _rt_text:
                    plan_raw = _rt_text
                    logger.info(
                        "[AgentKernel._plan_task] planned via InferenceRouter"
                    )
            except Exception as _rt_err:
                logger.warning(
                    f"[AgentKernel._plan_task] router planning failed: {_rt_err}"
                )
            if not plan_raw:
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
                    logger.info(
                        "[AgentKernel._plan_task] planner raw response: %s",
                        (plan_raw or "")[:600],
                    )
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

        # Parse JSON â†’ ExecutionPlan
        try:
            if plan_raw:
                m = _re.search(r"\{[\s\S]+\}", plan_raw)
                if m:
                    data = json.loads(m.group())
                    logger.info(
                        "[AgentKernel._plan_task] parsed plan keys=%s "
                        "raw_steps=%s",
                        list(data.keys()),
                        len(data.get("steps", [])),
                    )
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
                                # Phase 1 (D1.3): planner emits GOALS only. Tool
                                # selection is a runtime, memory-conditioned policy
                                # via explorer.propose â€” never pre-assigned here.
                                tool=None,
                                params={},
                                critical=bool(raw_step.get("critical", True)),
                                depends_on=list(raw_step.get("depends_on", []) or []),
                            )
                        )
                    return ExecutionPlan(
                        plan_id=str(_uuid.uuid4()),
                        original_task=text,
                        strategy=data.get("strategy", "do_it_myself"),
                        reasoning=data.get("reasoning", ""),
                        plan_title=data.get("plan_title", ""),
                        steps=steps,
                    )
        except Exception as _parse_err:
            logger.warning(f"[AgentKernel._plan_task] parse failed: {_parse_err}")

        # Fallback: return None to signal plan error (REQ-2 â€” no silent self-do)
        logger.warning(
            "[_plan_task] planner returned no valid plan for: %.150s",
            text,
        )
        return None

    def _is_web_search_request(self, text: str) -> bool:
        """Quick heuristic: does the user message explicitly request a web search?

        Uses precise phrase triggers rather than broad keywords to avoid
        blocking legitimate non-search queries. Only matches when the user
        clearly intends to fetch content from the internet.
        """
        if not text:
            return False
        _lower = text.lower().strip()
        _triggers = [
            "web search",
            "websearch ",
            "search the web",
            "search on the internet",
            "search online",
            "look up online",
            "look up on the",
            "find on the web",
            "find on the internet",
            "browse the web",
            "do a web search",
            "research ",
            "do research",
            "do some research",
            "find information about",
            "look up information",
        ]
        return any(t in _lower for t in _triggers)

    def _looks_informational(self, text: str) -> bool:
        """Conservative fact-seeking intent signal (used ONLY with web mode ON).

        _is_web_search_request() requires an explicit search phrase, which
        misses factual questions that arrive without one â€” e.g. the frontend
        strips the "websearch:" prefix, so "what are the latest NASA Mars
        rover discoveries this month?" has no trigger phrase (T36 finding
        2026-08-09). This helper catches question-word / current-info
        phrasing so the DER-skip gate does not misroute them as chit-chat.

        Deliberately narrow: it must NOT match greetings or small talk
        ("hello", "how are you", "tell me a joke") â€” those stay on the fast
        path even when web mode is ON.
        """
        if not text:
            return False
        _lower = text.lower().strip()
        _triggers = [
            # question-word openers (fact-seeking, not chit-chat)
            "what is", "what are", "what's", "what was", "when was",
            "when did", "when is", "where is", "where are", "why did",
            "why is", "how many", "how much", "how long", "how big",
            "how far", "how does", "how do", "is there", "are there",
            "what happened", "what's happening", "what's new", "who won",
            # current-info / news phrasing
            "latest", "news", "recent", "today", "this month",
            "this week", "this year", "weather", "forecast", "score",
            "election", "population", "capital of", "price of", "stock",
            "launch", "discovery", "announce", "update on", "status of",
        ]
        return any(t in _lower for t in _triggers)

    def _should_skip_der(
        self,
        plan_steps: list,
        task_clean: str,
        web_on: bool,
    ) -> bool:
        """DER-skip gate (extracted for contract testing, T36 2026-08-09).

        Returns True when the plan may be answered on the direct fast path
        without the DER card machinery:
          - empty plan (nothing to execute), or
          - voice-only plan (only speak steps) AND no web-search intent AND
            NOT (web mode ON + factual/informational question).

        The web-mode clause is the T36 fix: with internet access toggled ON,
        a factual question (which the frontend may strip of its "websearch:"
        prefix) must reach DER so the crawler path stays available. Chit-chat
        still skips DER regardless of web mode.

        F6 interaction (2026-08-12): plan steps are GOALS ONLY â€” the parse
        hardcodes ``tool=None`` and the single resolver (explorer.propose)
        assigns tools at execution time. Therefore step.tool is ALWAYS None
        for production plans, and the empty string must NOT count as a
        "voice-only" tool. With "" in the speak set, every planned task was
        misread as voice-only and DER (task card + tool execution) was
        skipped â€” an explicit "use the screenshot_page tool" prompt produced
        a trivial plan, no task card, and the empty fallback. Only
        EXPLICITLY marked speak steps are voice-only now.
        """
        _voice_only = bool(plan_steps) and all(
            (s.tool or "").lower() in ("speak", "speak_tool", "tts")
            for s in plan_steps
        )
        _is_websearch = self._is_web_search_request(task_clean)
        _informational = self._looks_informational(task_clean)
        return (
            not plan_steps
            or (
                _voice_only
                and not _is_websearch
                and not (web_on and _informational)
            )
        )

    def _empty_der_fallback_message(
        self,
        text: str,
        web_on: bool,
        der_err_text: str = "",
    ) -> str:
        """Empty-DER fallback wording (extracted for contract testing, T36 2026-08-09).

        Produces an AWARE message instead of the old blind
        "IRIS couldn't generate a response. Please try again.":
          - real upstream error detail â†’ surface it (retry / switch model)
          - search-intent turn + web OFF â†’ advise toggling internet access
          - search-intent turn + web ON â†’ honest incomplete-search message
          - otherwise â†’ neutral rephrase guidance
        Never contains the phrase "couldn't generate" (contract: it must not
        reach a chat_message content on a healthy path).
        """
        _searchy = self._is_web_search_request(text) or self._looks_informational(text)
        if der_err_text:
            return (
                f"I hit an error while working on that ({der_err_text}). "
                f"You can try again, or ask me in a different way."
            )
        if _searchy and not web_on:
            return (
                "Web search is currently disabled. You can toggle internet "
                "access on via the dashboard (the web button) to enable "
                "web features."
            )
        if _searchy:
            return (
                "I couldn't complete the web search for that â€” the search "
                "returned nothing usable. Please try again, or ask me "
                "without the web."
            )
        return (
            "I wasn't able to put together an answer for that. You can "
            "try again, or rephrase your question."
        )

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

        # Use provided session_id or fall back to instance session_id
        if session_id is None:
            session_id = self.session_id

        # Resolve conversation_id â€” primary key for per-thread context.
        # getattr guard: a kernel may be constructed without __init__ (test
        # stubs, partial init) â€” never raise on a missing attribute. The
        # session_id fallback is the documented behavior (docstring above).
        _conv_id = conversation_id or getattr(self, "conversation_id", None) or session_id
        self.conversation_id = _conv_id

        # Reset thinking from any previous call so stale data never leaks
        self._pending_thinking = ""

        # Stage 1 observability: per-turn metrics (created early so error paths can log)
        import uuid

        task_id = turn_id or str(uuid.uuid4())
        metrics = TurnMetrics(turn_id=task_id)
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

        try:
            # Add user message to conversation memory
            self._conversation_memory.add_message("user", text)
            logger.info(f"[AgentKernel] Processing text message: {text[:50]}...")

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
            # arrive as a per-turn system block — visible to planning and
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
        except Exception as e:
            # Handle conversation memory errors gracefully
            logger.warning(f"[AgentKernel] Conversation memory error: {e}")
            context = []  # Continue with empty context

        _t_memory = time.perf_counter()
        logger.debug(
            f"[Timing] memory.get_context: {(_t_memory - _t_start) * 1000:.1f} ms"
        )

        # â”€â”€ Direct path (default): skip planning for non-tool messages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Planning only runs when the message explicitly requests a tool-backed
        # action (search, open, create, etc.).  Everything else â€” greetings,
        # questions, conversation â€” goes straight to _respond_direct() which
        # calls the model with no JSON schema overhead.
        if not self._needs_planning(text, context):
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
            # Issue C.1: apply speak/show contract â€” emit document:render for
            # the `show` payload and reduce the stored/returned text to `speak`.
            response = self._process_structured_response(
                response, turn_id=task_id, conversation_id=_conv_id
            )
            # Escalate web-format choice to the user if the agent returned a web
            # result without rendering it as a document (pin_9e97e21340e7).
            self._maybe_escalate_web_format(task_id, _conv_id)
            # Never store error or empty responses in conversation memory.
            # They break role alternation and accumulate into garbage context
            # on subsequent turns, causing Cohere/OpenAI 400 errors.
            if response and not response.startswith("[IRIS error:"):
                try:
                    self._conversation_memory.add_message("assistant", response)
                except Exception as _mem_exc:
                    loud_error(_mem_exc, "conversation_memory.add_message (direct)")
            # Option B / Pacman: fragment this turn-pair into the vector DB so future
            # context assembly can retrieve it semantically (PACMAN.md Â§Digestion).
            # MCM orchestrator handles fragmentation + compression check when available.
            try:
                if response:
                    _turn = f"User: {text}\nAssistant: {response}"
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
                            zone=_zone,
                        )
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
            # per-thread self._tokens_used (never 0 for an active thread).
            self._emit_context_usage()
            return response

        # â”€â”€ Internet-access gate check (runs before DER to save cost) â”€â”€â”€â”€â”€â”€
        # If web tools are disabled and the user explicitly asked for a web
        # search, respond directly without engaging the expensive DER loop.
        if not get_global_internet_access() and self._is_web_search_request(text):
            return (
                "Web search is currently disabled. You can toggle internet "
                "access on via the dashboard (the web button) to enable "
                "web features."
            )

        # â”€â”€ Thinking feedback: emit a filler utterance so the user hears â”€â”€
        # audio feedback while the agent is "thinking" (DER/ReAct path).
        # Fire-and-forget via the speak tool; ConversationKernel drives TTS
        # (phase defaults to EXPAND in production, so it is never suppressed).
        # Fixes the reported "no utterance during thinking" gap. See plan Issue E.
        try:
            from backend.agent.tools.speak_tool import get_speak_tool
            import random as _random

            _fillers = (
                "Let me check that for you.",
                "One moment.",
                "Just a second.",
                "Working on it.",
            )
            get_speak_tool().speak(_random.choice(_fillers), priority="low")
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
                )
            logger.info("[AgentKernel] DER active â€” deferring complex request")
            return "Still working on your previous request â€” one moment."

        # â”€â”€ DER path: sanitize â†’ classify â†’ Mycelium â†’ plan â†’ execute â”€â”€â”€â”€â”€â”€
        # Runs BEFORE the ReAct loop. Falls through to ReAct on any failure.
        _der_response: Optional[str] = None
        self._der_active = True
        _der_lock_cleanup = True  # cleared in finally
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

            _plan = None
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
                # REQ-2: planner failure â†’ return ERROR, no silent self-do
                msg = "[IRIS error] The planner returned no valid plan."
                logger.warning("[process_text_message] %s", msg)
                return msg

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
                _voice_only = bool(_plan.steps) and all(
                    (s.tool or "").lower() in ("speak", "speak_tool", "tts", "")
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
                    _der_response = ""  # forces the direct path below
                else:
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

                    # Use mode name as task_class so DER_TOKEN_BUDGETS[mode] applies.
                    # Falls back to _task_class if mode not in budget table.
                    _der_task_class = (
                        _mode_name if _mode_name in DER_TOKEN_BUDGETS else _task_class
                    )
                    _der_response = self._der_execute_with_recovery(
                        _plan=_plan,
                        _context_package=_context_package,
                        _is_mature=_is_mature,
                        _der_task_class=_der_task_class,
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
                    self._conversation_memory.add_message("assistant", _der_response)
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
                    chunk_callback(_der_response)
                    chunk_callback("")  # force-flush end-of-stream
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
                # Escalate web-format choice to the user if the agent returned a
                # web result without rendering it as a document (pin_9e97e21340e7).
                self._maybe_escalate_web_format(task_id, _conv_id)
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
                            # fall back â€” the stub is broken and produces garbage output.
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
                                    f"[AgentKernel] Selected model '{_sel_check}' not in local cache â€” "
                                    f"will route to {_dest}"
                                )
                                # reasoning_model stays None; inference block handles it
                    else:
                        # No model selected â€” use default reasoning model
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
                    # LM Studio is configured â€” reasoning_model stays None; the LM Studio
                    # inference block below handles it via localhost:1234.
                    logger.info(
                        "[AgentKernel] No local model loaded; delegating planning to LM Studio"
                    )
                elif self._vps_gateway:
                    # VPS Gateway is configured â€” no local model required.
                    # reasoning_model stays None; the VPS inference block below handles it.
                    logger.info(
                        "[AgentKernel] No local reasoning model; delegating planning to VPS Gateway"
                    )
                elif self._selected_reasoning_model and self._model_router:
                    # The user confirmed a model but it isn't in _model_router.models yet.
                    # Two sub-cases:
                    # A) Ollama model â€” ID contains ":" (e.g. "llama3.2:3b")
                    #    â†’ handled in the Ollama inference block below.
                    #    NOTE: provider="local" means LFM local file, NOT Ollama.
                    #    Only ":" in the ID identifies an Ollama model.
                    # B) LFM HuggingFace model (provider="local", no ":" in ID)
                    #    â†’ trigger load_models() now so the model dict is populated.
                    _sel = self._selected_reasoning_model
                    _is_ollama = ":" in _sel  # ONLY colon-format IDs go to Ollama
                    if _is_ollama:
                        logger.info(
                            f"[AgentKernel] Ollama model '{_sel}' selected; "
                            "will infer via localhost:11434"
                        )
                        # reasoning_model stays None â€” Ollama block below handles inference
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
                                    "or switch to an Ollama or VPS model in Settings â†’ Configure."
                                )
                            }
                else:
                    return {
                        "error": (
                            "No inference backend configured. "
                            "Please go to Settings â†’ Configure and select a Local, VPS, or OpenAI model."
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
                                "[AgentKernel] Event loop conflict â€” falling back to local model"
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

            # Ollama local inference â€” runs when the model ID contains ":" which is
            # the Ollama format (e.g. "llama3.2:3b", "mistral:7b", "kimi-k2.5:cloud").
            # NOTE: provider="local" means LFM local file â€” it does NOT go to Ollama.
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
                            "Check that the model file exists, or select a different model in Settings â†’ Configure."
                        )
                    else:
                        _err_msg = (
                            "No inference backend configured. "
                            "Please go to Settings â†’ Configure and select a Local, VPS, or OpenAI model."
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
                # Treat the entire response as the user-facing reply â€” do NOT use
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

    def _der_execute_with_recovery(
        self,
        _plan,
        _context_package,
        _is_mature,
        _der_task_class,
        _session: str,
        from_voice: bool,
        _confidence,
        task_id,
    ):
        """
        Run the DER plan, catching TopologyViolationException (N.4 + O.6 + RC11)
        with a targeted recovery instead of the blanket ReAct fallback.

        On a topology violation we reset the Caducean session and retry once.
        If the retry also fails, returns None so the caller falls through to
        the agentic (ReAct) loop.
        """
        from backend.agent.exceptions import TopologyViolationException

        # Phase 1 (D1.6): expose task_class so the runtime resolver
        # (explorer.propose) can apply the capability-gated web fallback.
        self._der_task_class = _der_task_class

        # REQ-19 (T20): one DerLinkWriter per DER run â€” writes structural
        # links (part_of / depends_on / relevant_to / failed_like) into the
        # SHARED mycelium link store at finalize. Wired here so it exists for
        # the whole plan; bound to this run's kernel (no cross-session shared
        # mutable state).
        try:
            from backend.agent.der_links import DerLinkWriter

            _mi = getattr(self, "_memory_interface", None)
            _myc = getattr(_mi, "_mycelium", None) if _mi is not None else None
            _store = getattr(_myc, "_store", None)
            self._der_links = DerLinkWriter(_store) if _store is not None else None
        except Exception as _dl_exc:
            logger.debug("[DER] link-writer init failed: %s", _dl_exc)
            self._der_links = None

        # Phase 2 (D2.4): unified termination resource DER_WORK_UNITS_0 derived
        # from the LIVE context window (System Invariant: work units and context
        # window are the SAME resource). Split prepays width; complete/fail/veto
        # consumes 1. This is what makes the Lyapunov potential strictly decrease.
        try:
            from backend.agent.der_constants import derive_work_units_0

            _cw = self.resolve_context_window()
            self._der_work_units = derive_work_units_0(_cw)
        except Exception as _wu_err:
            logger.warning("[DER] work_units derive failed: %s", _wu_err)
            self._der_work_units = 0
        # REQ-7: previous step's |u| magnitude, for physics-event narration
        # transition detection (oscillating -> converged). None until first step.
        self._der_last_u_mag = None

        try:
            return self._execute_plan_der(
                plan=_plan,
                context_package=_context_package,
                is_mature=_is_mature,
                task_class=_der_task_class,
                session_id=_session,
                from_voice=from_voice,
                confidence=_confidence,
                turn_id=task_id,
            )
        except TopologyViolationException:
            logger.warning(
                "[AgentKernel] TopologyViolation â€” attempting targeted recovery"
            )
            try:
                # RC11 FIX: reset Caducean session state before recovery
                from backend.gateway.iris_ffi import ffi_caducean_init_session
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                from backend.agent.coupled_registry import domain_windings

                # REQ-11 AC3: re-init with the domain windings so the engine's
                # c_eff matches what the registry holds after recovery.
                _l, _m = domain_windings("voice" if from_voice else "der")
                ffi_caducean_init_session(_session, _l, _m)
                get_event_bus().emit(
                    IRISStreamEvent.MODE_CHANGED,
                    data={
                        "from_mode": "DER",
                        "to_mode": "DER_RECOVERY",
                        "reason": "Topological violation â€” recovering",
                    },
                    session_id=_session,
                )
                get_event_bus().emit(
                    IRISStreamEvent.TOPOLOGY_RECOVERY,
                    data={
                        "from_mode": "DER",
                        "to_mode": "DER_RECOVERY",
                        "reason": "Topological violation â€” recovering",
                    },
                    session_id=_session,
                )
                return self._execute_plan_der(
                    plan=_plan,
                    context_package=_context_package,
                    is_mature=_is_mature,
                    task_class=_der_task_class,
                    session_id=_session,
                    from_voice=from_voice,
                    confidence=_confidence,
                    turn_id=task_id,
                )
            except Exception as _recovery_err:
                logger.warning(
                    f"[AgentKernel] Recovery failed, falling back to ReAct: {_recovery_err}"
                )
                return None

    @restores_call_class
    def _execute_plan_der(
        self,
        plan,
        context_package=None,
        is_mature: bool = False,
        task_class: str = "full",
        session_id: Optional[str] = None,
        from_voice: bool = False,
        confidence: float = 0.50,
        turn_id: Optional[str] = None,
    ) -> str:
        """
        DER execution cycle: Director â†’ Reviewer â†’ Explorer â†’ repeat until complete.

        The Director re-reads Mycelium each cycle via ContextPackage.
        The Reviewer gates each step (PASS / REFINE / VETO).
        The Explorer executes via _tool_bridge or direct model call.
        Mycelium signal hooks fire after every step and at outcome.

        Never raises â€” wraps failures as step error text so the response
        always reaches the user.
        """
        # Trust-routing W2: a plan run is one turn â€” start unmarked.
        self.clear_turn_trust_flag()
        # REQ-5 AC3: the amendment bound is PER TASK. _der_amendment_count lives
        # on the kernel, which is cached per CONVERSATION â€” leaving it to
        # accumulate would permanently refuse every graft after the third
        # recovery in a conversation, silently killing DER's existing recovery
        # path. One plan run is one task, so the counter resets here.
        self._der_amendment_count = 0
        # T6.4: mark the call class as USER_TURN at the real turn entry so the
        # phase gate admits it immediately (high-priority lane).
        set_call_class(CallClass.USER_TURN)
        # T6.8: sweep expired batch groups before each DER cycle so
        # BATCH_MAX_HOLD_S (REQ-18 AC3) is enforced even in quiet periods.
        try:
            get_batcher().flush_expired()
        except Exception:
            logger.debug("[DER] batcher flush_expired failed", exc_info=True)
        from backend.agent.der_loop import (
            DirectorQueue,
            NodeRecord,
            QueueItem,
            Reviewer,
            ReviewVerdict,
        )
        from backend.agent.der_constants import ExecutionMode
        import uuid as _uuid

        _session = session_id or self.session_id
        # _turn_id threads the request turn id through EventBus emits and
        # escalation calls. It was previously referenced throughout this
        # method but never defined â€” that NameError broke the DER escalation
        # path and forced the "[step N completed]" fallback. See Issue E fix.
        _turn_id = turn_id
        completed_items: List[Any] = []
        step_outputs: List[str] = []
        _der_start_time = time.perf_counter()

        # Token budget â€” spec [1.2]: enforce DER_TOKEN_BUDGETS[task_class]
        # Tokens are estimated from step result length (4 chars â‰ˆ 1 token).
        # Budget is a ceiling; the loop exits early if exceeded.
        # DER budget is derived from the MODEL'S ACTUAL CONTEXT WINDOW, not a
        # hardcoded per-mode cap. DER exists to execute tasks in alignment with
        # memory (Pacman filters tokens into the context window that then feeds
        # coordinate memory.db) â€” so each model should be allowed to use its full
        # window for reasoning across steps. The flat DER_TOKEN_BUDGETS values
        # are kept only as a SAFETY FLOOR (never go below a sane minimum), never
        # as a ceiling. No upper cap: a 256k model gets ~230k of step budget, a
        # 32k local model gets ~29k â€” each uses its real capacity.
        # Sized by the SMALLEST window among the roles this turn will actually
        # spend against â€” DER issues both reasoning calls and tool_execution
        # calls, and a Brain/Tool split can put them on very different models.
        # Using the reasoning window alone budgeted ~230k for a turn whose tool
        # steps ran on an 8k model (2026-08-16).
        _model_window = self.resolve_turn_context_window()
        _token_budget: int = resolve_der_token_budget(_model_window, task_class)
        _tokens_used: int = 0
        logger.info(
            "[DER] budget=%d from window=%d class=%s (work_units=%d)",
            _token_budget,
            _model_window,
            task_class,
            derive_work_units_0(_model_window),
        )

        # â”€â”€ REQ-1: pre-flight â€” is the reasoning provider usable? â”€â”€â”€â”€â”€â”€â”€â”€
        if not getattr(self, "_router", None):
            logger.warning("[DER] pre-flight FAILED â€” no router configured")
            return "[DER unavailable] No inference router configured"
        try:
            _hc = self._router.health_check_provider("reasoning")
        except Exception as _hc_err:
            _hc = {"ok": False, "error": str(_hc_err)[:200]}
        if not _hc.get("ok"):
            _reason = _hc.get("error", "no reason")
            logger.warning(
                "[DER] pre-flight FAILED â€” reasoning provider unavailable: %s",
                _reason,
            )
            return f"[DER unavailable] {_reason}"

        # Build Director queue from ExecutionPlan steps
        # Phase 4b: derive parallel_safe from the tool registry (authoritative
        # source of truth) so concurrency fires for read-only/independent tools
        # without trusting the LLM planner to emit the flag.
        from backend.agent.tool_registry import is_parallel_safe

        items = [
            QueueItem(
                step_id=step.step_id,
                step_number=step.step_number,
                description=step.description,
                tool=step.tool,
                params=step.params if step.params else {},
                critical=step.critical,
                depends_on=list(step.depends_on or []),
                parallel_safe=is_parallel_safe(step.tool),
                objective_anchor=plan.original_task,
                coordinate_signal=(
                    getattr(context_package, "topology_position", "") or ""
                    if context_package
                    else ""
                ),
                # REQ-3 (T8): EVERY node carries its compressed memory record â€”
                # top-level plan steps included, not just split children. The
                # record's Understanding/Awareness/Direction fields are derived
                # from the plan step itself (the node's initial position), and
                # the finalize site stamps outcome/fraction/mediator/coords_to
                # onto it. Without this, plan steps were always memory-sparse
                # and the node record existed only for sub-loop children.
                node_record=NodeRecord(
                    step_id=step.step_id,
                    parent_step_id="",
                    node_type="step",
                    objective_anchor=plan.original_task,
                    content_summary=(step.description or "")[:300],
                    prior_summary="",  # no prior attempts on first landing
                    expected_output=step.expected_output or "",
                    remaining=step.description or "",
                    ruled_out="",
                    coordinate_ref=None,
                    coords_from="",
                    # REQ-18 (T19): both domain axes resolved at construction â€”
                    # topic from the step's own text via the mycelium registry,
                    # execution from the active winding. Registry-backed, never
                    # free text (AC2/AC3). The finalize site re-stamps with the
                    # full step result text so later steps carry the richer
                    # signal; this seed keeps the record typed even if the
                    # step never finalizes.
                    topic_domain=self._der_topic_domain(step.description or ""),
                    execution_domain=self._der_execution_domain(from_voice),
                    committed_decision=False,
                    size_bytes=len((step.description or "").encode("utf-8", "replace")),
                ),
            )
            for step in plan.steps
        ]
        queue = DirectorQueue(objective=plan.original_task, items=items)

        # Force a real tool for web-search steps the planner left tool-less.
        # Without this, web-intent steps fall through to _run_step_direct and the
        # LLM returns empty ("[step N completed]") instead of actually searching.
        # Also catches mode names (agentic / quick / full) that the LLM planner
        # sometimes assigns instead of the actual tool name.
        # Phase 1 (D1.4): web-intent regex override DELETED. Tool selection is
        # now a single runtime authority (explorer.propose), which routes web
        # intent to crawler_query via the registry's alias + capability system
        # (capability-gated fallback for research-class goals). No routing is
        # lost â€” the registry already canonicalizes web aliases to crawler_query.

        # â”€â”€ Phase 3: initialize execution mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Director decides mode dynamically based on task characteristics.
        # Voice no longer caps to 1 step â€” Director decides based on content.
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

        # â”€â”€ EventBus: emit task:start â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            bus = get_event_bus()
            _card_task_id = _turn_id or plan.original_task[:40]
            _card_id, _card_relation = self._resolve_card_identity(
                _card_task_id, "initial"
            )
            # T16 (REQ-12 AC4): card-lifecycle observability â€” relation decision
            # is logged here, off the inference hot path (this block only emits
            # an event; a log line can never block the user response).
            logger.info(
                "[AgentKernel] CARD_LIFECYCLE relation=%s card_id=%s task_id=%s conv=%s turn=%s",
                _card_relation, _card_id, _card_task_id, self.conversation_id, _turn_id,
            )
            _start_steps = [
                {
                    "id": it.step_id,
                    "description": it.description,
                    "status": "pending",
                    "toolName": it.tool,
                }
                for it in items
            ]
            bus.emit(
                IRISStreamEvent.TASK_START,
                data=self._task_start_payload(
                    task_id=_card_task_id,
                    description=plan.original_task[:200],
                    plan_title=self._effective_plan_title(plan),
                    mode=initial_mode.value,
                    steps=_start_steps,
                    total_steps=len(items),
                    # REQ-14 (T23): execution-start announcement â€” still the
                    # INITIAL plan; revisions re-emit with a distinct origin.
                    origin="initial",
                    # REQ-3 (T2): backend-declared card identity.
                    card_id=_card_id,
                    card_relation=_card_relation,
                    conversation_id=self.conversation_id,
                        turn_id=getattr(self, "_current_turn_id", None),
                    **self._multiagent_tags(),
                ),
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
            # T4a (REQ-4 AC1): persist the card at task:start.
            self._persist_card_snapshot(
                card_id=_card_id,
                conversation_id=self.conversation_id,
                card_relation=_card_relation,
                plan_title=self._effective_plan_title(plan),
                mode=initial_mode.value,
                steps=_start_steps,
                total_steps=len(items),
                terminal_state="running",
            )
        except Exception:
            pass  # EventBus is optional â€” no crash if it fails

        # C.1 LiveContextPackage â€” refreshes ContextPackage mid-loop so the
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

        # Reviewer â€” falls back to PASS on any failure (membrane, not gate)
        reviewer = self._reviewer

        # WS disconnect helper â€” checks if the originating session still has
        # at least one live client. Never raises; defaults to "connected".
        def _session_has_client() -> bool:
            try:
                from backend.ws_manager import get_websocket_manager

                ws = get_websocket_manager()
                if ws is None:
                    return True  # no WS manager â†’ non-WS path, keep running
                # â”€â”€ Conversation / thread IDs used as kernel sessions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # The WS handler (iris_gateway.py:4450) passes the WS client ID
                # as session_id and the conversation/thread ID as conversation_id,
                # so thread IDs never appear as the kernel session there.
                # The REST handler (chat.py:305) uses the thread/conversation ID
                # as the kernel session_id â€” these sessions have no WS client and
                # must keep running (their output is returned synchronously).
                if isinstance(_session, str) and (
                    _session.startswith("immortus:") or _session.startswith("conv_")
                ):
                    return True
                # The prefix list above is a NAMING check, and it silently
                # stopped matching: chat.py mints thread ids as "conv-1"
                # (hyphen) while this only ever accepted "conv_" (underscore).
                # Every REST search therefore hit the disconnect branch and the
                # DER loop broke before executing step 1 â€” surfacing to the user
                # as "no usable sources found", a network failure that never
                # happened. e2e was ~536 ms with no crawl in the log.
                #
                # Test the STRUCTURE instead of the spelling. chat.py:308 passes
                # session_id=thread_id=conversation_id, whereas the WS handler
                # passes the client id as session_id and the thread id as
                # conversation_id (see the comment above), so the two are equal
                # only on the REST path. That holds regardless of how ids are
                # spelled, so renaming them cannot silently re-break this.
                if isinstance(_session, str) and _session == getattr(
                    self, "conversation_id", None
                ):
                    return True
                return len(ws.get_clients_for_session(_session)) > 0
            except Exception:
                return True

        # â”€â”€ REQ-15 (T25/T26): per-task steering state reset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self._der_stop_requested = False
        self._der_pause_requested = False
        self._der_resume_requested = False

        while (
            not queue.is_complete()
            and not queue.hit_cycle_limit()
            and _tokens_used < _token_budget
            # REQ-15 AC3: an explicit stop aborts at the next step boundary.
            and not self._der_stop_requested
        ):
            # â”€â”€ DISCONNECT CHECK: stop early if client is gone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if not _session_has_client():
                logger.info(
                    f"[DER] Session {_session} has no connected clients â€” "
                    "recording partial outcome and stopping"
                )
                break

            queue.cycle_count += 1

            # â”€â”€ DOMAIN 19: Caducean phase read â”€â”€
            import math as _math

            _xi = 0.0
            try:
                from backend.gateway.iris_ffi import ffi_caducean_get_xi

                _xi = ffi_caducean_get_xi(_session)
            except Exception as _ffi_exc:
                loud_error(_ffi_exc, "ffi_caducean_get_xi")
            _phase = 0  # 0=[0,Ï€/2], 1=[Ï€/2,Ï€], 2=[Ï€,3Ï€/2], 3=[3Ï€/2,2Ï€]
            if _xi >= 3.0 * _math.pi / 2.0:
                _phase = 3
            elif _xi >= _math.pi:
                _phase = 2
            elif _xi >= _math.pi / 2.0:
                _phase = 1

            item = queue.next_ready(_session)
            if item is None:
                break  # dependency deadlock guard

            # â”€â”€ REQ-15 (T25/T26): consume mid-task steering at the NEXT step
            # boundary (AC1 â€” never mid-step). A steering revision replaces
            # the remaining plan (AC2); a stop aborts here (AC3); a pause
            # suspends here until resume/stop (AC4).
            _steer = self._der_check_steering(_session, plan, queue)
            if _steer:
                if _steer.get("stop"):
                    break
                if _steer.get("revised"):
                    # The pulled item belongs to the dropped plan â€” re-pull
                    # from the revised queue on the next iteration.
                    continue
                if _steer.get("pause"):
                    _suspend = self._der_suspend_task(
                        _session, plan, queue, _turn_id
                    )
                    if _suspend == "stop":
                        break
                    # resumed: the pulled item was never executed â€” re-pull
                    # it from the (unchanged) queue.
                    continue

            # â”€â”€ C.1 LIVE CONTEXT REFRESH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Re-read Mycelium coordinate signals for the current sub-step.
            # Updates gradient_warnings + tier2_predictions on context_package.
            # < 50ms SLA; silently no-ops on any error.
            if _live_ctx is not None:
                _live_ctx.refresh(item, completed_items)
                context_package = _live_ctx.package  # always valid

            # â”€â”€ C.4 MID-LOOP EPISODIC RETRIEVAL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Query the episodic store for the *current sub-task*, not the
            # parent task.  Injects a hint into item.coordinate_signal so the
            # Reviewer and Explorer both see "I solved this sub-problem before
            # this way".  <50ms: uses cached embeddings after first query.
            try:
                if self._memory_interface and item.description:
                    _retrieval_limit = 2
                    _retrieval_score = 0.55
                    try:
                        from backend.agent.caducean_trajectory import (
                            CaduceanTrajectoryRecorder,
                        )
                        # REQ-16: read per-session cached (eml, x, y) triple
                        _triple = CaduceanTrajectoryRecorder.get_cached_eml(
                            _session
                        )
                        if isinstance(_triple, tuple):
                            _cached_eml = float(
                                _triple[0] if _triple[0] is not None else 1.0
                            )
                            _cached_x = float(_triple[1]) if _triple[1] else 0.0
                            _cached_y = float(_triple[2]) if _triple[2] else 0.0
                        elif isinstance(_triple, (int, float)):
                            _cached_eml = float(_triple)
                            _cached_x = _cached_y = 0.0
                        else:
                            _cached_eml, _cached_x, _cached_y = 1.0, 0.0, 0.0

                        # REQ-17: V-shaped explore pressure, AC1: x/y directional term.
                        # Three anchors (AC3):
                        #   consolidate (eml=0.90, x-dominant): limit=3,  score=0.65
                        #   neutral     (eml=1.20):              limit=2,  score=0.55
                        #   explore     (eml=1.60, y-dominant):  limit=5,  score=0.40
                        _EC, _EN, _EE = 0.90, 1.20, 1.60
                        _LC, _LN, _LE = 3, 2, 5
                        _SC, _SN, _SE = 0.65, 0.55, 0.40
                        _e = max(0.0, _cached_eml)
                        _norm = (_cached_x**2 + _cached_y**2) ** 0.5
                        _dir = _cached_y / _norm if _norm > 1e-9 else 0.0
                        if _e <= _EN:
                            _p = max(0.0, min(1.0, (_e - _EC) / (_EN - _EC)))
                            _retrieval_limit = _LC + (_LN - _LC) * _p
                            _retrieval_score = _SC + (_SN - _SC) * _p
                            _bias = min(1.0, abs(_dir))
                            if _dir < 0:  # consolidate-dominant
                                _retrieval_limit += _bias * (_LC - _retrieval_limit)
                                _retrieval_score += _bias * (_SC - _retrieval_score)
                            elif _dir > 0:  # explore-dominant at low EML
                                _retrieval_limit += _bias * (_LE - _retrieval_limit)
                                _retrieval_score += _bias * (_SE - _retrieval_score)
                        else:
                            _p = max(0.0, min(1.0, (_e - _EN) / (_EE - _EN)))
                            _retrieval_limit = _LN + (_LE - _LN) * _p
                            _retrieval_score = _SN + (_SE - _SN) * _p
                            _bias = min(1.0, abs(_dir))
                            if _dir > 0:  # explore-dominant
                                _retrieval_limit += _bias * (_LE - _retrieval_limit)
                                _retrieval_score += _bias * (_SE - _retrieval_score)
                            elif _dir < 0:  # consolidate-dominant at high EML
                                _retrieval_limit += _bias * (_LC - _retrieval_limit)
                                _retrieval_score += _bias * (_SC - _retrieval_score)
                        _retrieval_limit = max(2, min(5, int(round(_retrieval_limit))))
                        _retrieval_score = max(0.40, min(0.65, _retrieval_score))
                    except Exception as _eml_exc:
                        loud_error(_eml_exc, "caducean_eml_retrieval")
                    _sub_eps = self._memory_interface.episodic.retrieve_similar(
                        task=item.description,
                        limit=_retrieval_limit,
                        min_score=_retrieval_score,
                    )
                    if _sub_eps:
                        _hint_parts = []
                        for ep in _sub_eps:
                            _ts = ep.get("task_summary", "")[:80]
                            if _ts:
                                _hint_parts.append(_ts)
                            # A2 FIX: surface the proven tool_sequence, not just
                            # the summary, so the Explorer repeats a known-good path.
                            _seq = ep.get("tool_sequence", [])
                            if _seq:
                                _approach = " â†’ ".join(
                                    s.get("tool", "?") for s in _seq[:5]
                                )
                                _hint_parts.append(f"PROVEN APPROACH: {_approach}")
                        _hints = "; ".join(_hint_parts)
                        if _hints:
                            _prior = getattr(item, "coordinate_signal", "") or ""
                            item.coordinate_signal = (
                                _prior + f"\nSUB-TASK HINT: {_hints}"
                            ).strip()
                    # A1 FIX: inject failure awareness per-step (not just at plan
                    # time). _get_failure_warnings reads Mycelium high-signal
                    # failure warnings for this sub-task so the Explorer avoids a
                    # known-bad approach. Returns "None" on miss; never raises.
                    try:
                        _fw = self._get_failure_warnings(item.description)
                        if _fw and _fw != "None" and len(_fw) > 10:
                            _prior = getattr(item, "coordinate_signal", "") or ""
                            item.coordinate_signal = (
                                _prior + f"\nPAST FAILURE WARNING: {_fw[:300]}"
                            ).strip()
                    except Exception as _fw_exc:
                        loud_error(_fw_exc, "failure_warning_mid_loop")

                    # â”€â”€ REQ-20 AC3 (T21): the filtered ontology neighborhood
                    # is a first-class step input. Query the DER chain with
                    # THIS node's type + both domain axes and surface the
                    # relevant neighbor records into the step context â€” the
                    # relevant neighborhood, not the whole graph. Zero-hit
                    # widens (relationship -> type -> domain, logged) and
                    # falls back to the live-state-only step (never an error).
                    try:
                        _nb = self._der_recall_neighborhood(item, _session)
                        if _nb:
                            _nb_parts = []
                            for _n in _nb[:3]:
                                _n_sum = (_n.get("result") or "")[:120]
                                _n_id = _n.get("chain_id") or ""
                                _n_td = _n.get("topic_domain") or "?"
                                _n_ed = _n.get("execution_domain") or "?"
                                if _n_sum:
                                    _nb_parts.append(
                                        f"{_n_id} ({_n_td}/{_n_ed}): {_n_sum}"
                                    )
                            if _nb_parts:
                                _prior = getattr(item, "coordinate_signal", "") or ""
                                item.coordinate_signal = (
                                    _prior
                                    + "\nRELEVANT NEIGHBORS: "
                                    + " | ".join(_nb_parts)
                                ).strip()
                    except Exception as _nb_exc:
                        loud_error(_nb_exc, "ontology_recall_neighborhood")

                    # â”€â”€ REQ-3 T8 AC1/AC3: the node's compressed memory record is
                    # a FIRST-CLASS step input (not opt-in). If this item carries
                    # a NodeRecord (every node does from split/creation on), its
                    # Understanding/Awareness/Direction + the compressed Î£
                    # position are injected into the step input alongside the
                    # episodic hints. When the store has no record for the
                    # node's coordinate, the step proceeds on the live state
                    # alone and is marked memory-sparse in the observability log
                    # (AC3) â€” never an error.
                    try:
                        _rec = getattr(item, "node_record", None) or getattr(
                            item, "footprint", None
                        )
                        # REQ-6 AC1 (T18): OBSERVE which signal governed this
                        # step's steering â€” past-memory (compressed node
                        # record present) vs live-state (memory-sparse: no
                        # record, the decision runs on the live Î£ alone). A
                        # record present AND live Î£ consumed is the "both"
                        # (equal-signals) edge. No hardcoded authority (AC2).
                        try:
                            self._der_record_governance(
                                "both" if _rec is not None else "live"
                            )
                        except Exception:
                            pass
                        if _rec is not None:
                            _rec_parts = []
                            if getattr(_rec, "prior_summary", ""):
                                _rec_parts.append(
                                    f"UNDERSTANDING: {_rec.prior_summary[:300]}"
                                )
                            if getattr(_rec, "ruled_out", ""):
                                _rec_parts.append(f"RULED OUT: {_rec.ruled_out[:200]}")
                            if getattr(_rec, "expected_output", ""):
                                _rec_parts.append(
                                    f"EXPECTED: {_rec.expected_output[:200]}"
                                )
                            if getattr(_rec, "coords_from", ""):
                                _rec_parts.append(f"BRANCH COORDS: {_rec.coords_from}")
                            # REQ-4 AC4 (T16b): the fold-back observations from
                            # this node's sub-loop children are first-class
                            # step context (REQ-3 AC1) â€” the parent's next
                            # decision reads what the children resolved.
                            if getattr(_rec, "folded_back", None):
                                _rec_parts.append(
                                    "FOLDED-BACK: " + "; ".join(_rec.folded_back[-3:])
                                )
                            if _rec_parts:
                                _prior = getattr(item, "coordinate_signal", "") or ""
                                item.coordinate_signal = (
                                    _prior + "\nNODE RECORD: " + "; ".join(_rec_parts)
                                ).strip()

                            # â”€â”€ REQ-5 AC1/AC3 (T17): SURFACE the branch
                            # candidates to the deciding step. Retrieval ranks
                            # the relevant branches (physics + evidence) and
                            # puts ALL of them in front of the step â€” never
                            # pre-selecting one by score. The step decides with
                            # both branches in view; the chosen one is recorded
                            # at commit (_der_record_coupling_decision).
                            try:
                                _cands = self._der_surface_branch_candidates(item)
                                if _cands:
                                    _cand_parts = [
                                        f"{i+1}. {c.get('label','')}"
                                        for i, c in enumerate(_cands)
                                    ]
                                    _prior = (
                                        getattr(item, "coordinate_signal", "") or ""
                                    )
                                    item.coordinate_signal = (
                                        _prior
                                        + "\nBRANCH CANDIDATES: "
                                        + " | ".join(_cand_parts)
                                    ).strip()
                                    # remember for the commit-time decision
                                    # record (AC2/AC4) â€” bounded provenance.
                                    try:
                                        item._coupled_candidates = list(_cands)
                                    except Exception:
                                        pass
                            except Exception as _surf_exc:
                                logger.debug(
                                    "[DER] branch surfacing failed: %s", _surf_exc
                                )

                            # â”€â”€ REQ-3 T8b AC4/AC5/AC6: wire the FORGETTING. The
                            # step's working context (coordinate_signal) is bounded
                            # to a fraction of the REQ-1 resolved window (OQ-6:
                            # derived, never a literal) â€” content beyond the bound is
                            # DROPPED from the working context and re-read later
                            # only when retrieval selects the node record. The
                            # per-step prompt token count is recorded so the
                            # reduction is a measured number (AC5). AC6: if the
                            # node's chain write FAILED (durability drop counter),
                            # the working context is the ONLY copy â€” do NOT bound
                            # (forget) it. Extracted to _der_bound_step_context so
                            # the contract test drives the REAL code (T8b).
                            self._der_bound_step_context(item)
                        else:
                            # AC3: memory-sparse â€” no record, proceed on live state.
                            logger.info(
                                "[DER] step memory-sparse step_id=%s (no node record "
                                "for this coordinate) â€” proceeding on live state",
                                getattr(item, "step_id", "?"),
                            )
                    except Exception as _rec_exc:
                        loud_error(_rec_exc, "node_record_step_input")
            except Exception as _explore_exc:
                loud_error(_explore_exc, "explorer_sub_episodes")

            # â”€â”€ REVIEWER PHASE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                    # DER Phase 0 (D0.2): a VETO means the action was NEVER executed.
                    # Do NOT emit a tool-outcome record (that would be a lie â€” a
                    # success=False edge for a tool that never ran). The veto decision is
                    # logged for audit only; it is not a tool outcome.
                    logger.debug(
                        f"[DER] veto audit: step {item.step_number} not executed "
                        f"(reason={feedback})"
                    )

                    if item.veto_count <= queue.max_veto_per_item:
                        # Keep in queue for Director to reroute next cycle
                        continue
                    else:
                        queue.mark_vetoed(item.step_id)
                        # â”€â”€ REQ-8 AC3: emit learning signal for avoided step â”€â”€
                        try:
                            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                            get_event_bus().emit(
                                IRISStreamEvent.TASK_LEARNING,
                                data={
                                    "signal": "avoided",
                                    "step_number": item.step_number,
                                    "step_id": item.step_id,
                                    "session_id": _session,
                                },
                            )
                        except Exception:
                            pass
                        continue

                if verdict == ReviewVerdict.REFINE and feedback:
                    item.refined_description = feedback
                    item.description = feedback
                    logger.info(f"[DER] Step {item.step_number} REFINED")

            # â”€â”€ EXPLORER PHASE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Emit TOOL_CALL event for the frontend / TaskKernel
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                _lifecycle_task_id = _turn_id or item.step_id
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_CALL,
                    data={
                        "task_id": _lifecycle_task_id,
                        "tool_name": item.tool or "direct",
                        "description": item.description[:200],
                        "params": item.params,
                        "step_number": item.step_number,
                        # REQ-3 AC6 (T2): card_id stays stable across every
                        # event of a card's lifetime, not just task:start.
                        **self._card_envelope(_lifecycle_task_id),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                )
            except Exception:
                pass

            # â”€â”€ RC1 FIX: pre-execution validation (catches tool:null / missing
            # params before runtime). Invalid steps route to graft with the
            # REQ-6 (soft-cancel): if the user switched away from this conversation,
            # stop issuing further steps. An in-flight tool subprocess is allowed to
            # finish once (SOFT cancel) but no subsequent step or recovery narrative
            # is produced for this thread. We check here, at the top of each item
            # iteration, so the loop exits cleanly without emitting further events.
            if self._cancel_requested.is_set():
                self._logger.info(
                    f"[DER] Cancel requested for conversation {self.conversation_id}; "
                    f"halting DER loop after current step."
                )
                break

            # validation error instead of executing-and-failing. â”€â”€
            if item.tool:
                from backend.agent.tool_registry import validate_tool_call
                _valid, _val_err = validate_tool_call(item.tool, item.params or {})
                if not _valid:
                    item.result = f"[VALIDATION] {_val_err}"
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.VALIDATION_FAILED,
                            data={
                                "tool_name": item.tool,
                                "error": _val_err,
                                "step_id": item.step_id,
                                "step_number": item.step_number,
                            },
                            session_id=_session,
                            turn_id=_turn_id,
                        )
                    except Exception:
                        pass
                    self._der_handle_step_failure(
                        item, queue, plan, _session, _turn_id, context_package
                    )
                    continue

            # â”€â”€ EXPLORER PHASE: execute primary step with resilience (Phase 1.1) â”€â”€
            # retry_with_backoff_sync retries transient errors (ConnectionError /
            # TimeoutError / OSError) with exponential backoff and fails fast on
            # permanent errors (ValueError / PermissionError / etc). _der_run_step
            # returns (result, success) rather than raising, so _run_step re-raises
            # a classified exception to drive the retry decision. The sync twin is
            # used because _der_run_step_execution calls asyncio.run() internally â€”
            # nesting asyncio.run would raise RuntimeError in the executor thread.
            from backend.agent.resilience import retry_with_backoff_sync

            def _run_step():
                _res, _ok = self._der_run_step_execution(
                    item, context_package, _session, _turn_id, plan, queue=queue
                )
                if _ok:
                    return _res, _ok
                # RateLimitedError is raised (not returned) by
                # _der_run_step_execution when the transport exhausted its own
                # 429 retries. It must NOT be retried at the DER layer (REQ-4
                # AC1) â€” re-raise so retry_with_backoff_sync's NO_RETRY_ERRORS
                # check surfaces it immediately.
                if isinstance(_res, RateLimitedError):
                    raise _res
                _err = _res or ""
                if any(
                    _k in _err
                    for _k in (
                        "ConnectionError", "TimeoutError", "timed out",
                        "Connection refused", "timeout",
                    )
                ):
                    raise ConnectionError(_err)  # transient -> retry
                raise ValueError(_err)  # permanent -> fail fast

            try:
                step_result, step_success = retry_with_backoff_sync(
                    _run_step,
                    max_retries=2,
                    base=1.0,
                    cap=4.0,
                    label=f"step_{item.step_number}:{item.tool}",
                )
            except Exception as _retry_exc:
                step_success = False
                # RateLimitedError carries structured context (provider id,
                # retry count) â€” preserve it verbatim for the ledger (REQ-3
                # AC4 / REQ-4 AC2). Do NOT stringify into a generic message.
                if isinstance(_retry_exc, RateLimitedError):
                    step_result = (
                        f"RateLimitedError(provider={_retry_exc.provider_id}, "
                        f"attempts={_retry_exc.attempts}, "
                        f"retry_after={_retry_exc.retry_after})"
                    )
                    logger.warning(
                        "[DER] Step %s rate-limited by provider %s after %d "
                        "attempts â€” recording FAILED (no DER-layer retry)",
                        item.step_number, _retry_exc.provider_id,
                        _retry_exc.attempts,
                    )
                else:
                    step_result = str(_retry_exc)

            if not step_success:
                # REQ-4 (specs/dag-node-execution-model): before the graft
                # handler runs, consult the node router. A recovery node that
                # advertises this failure's reason executes in place of the
                # failing node; a recovered step finalizes normally below
                # (no branch was written in the failing node's module).
                _recovered = self._der_route_step_failure(
                    item, step_result, _session, _turn_id, plan,
                )
                if _recovered is not None:
                    step_result = _recovered
                    step_success = True
                else:
                    # C1 FIX: preserve the real error so the graft recovery prompt
                    # receives it (item.result is otherwise only set on success).
                    item.result = step_result
                    # A3 FIX: fragment the failed output here (the shared
                    # _der_finalize_step helper is only reached for successful
                    # steps, so failures would otherwise never be stored).
                    try:
                        if self._memory_interface and step_result:
                            _ep = self._memory_interface.episodic
                            if hasattr(_ep, "fragment_and_store"):
                                _ep.fragment_and_store(
                                    content=f"[DER FAIL Step {item.step_number}: "
                                            f"{item.description[:80]}]\n{step_result[:500]}",
                                    session_id=_session,
                                    chunk_type="der_failure",
                                    zone="tool",
                                )
                    except Exception:
                        pass
                    # Step failed after retry â€” mark, abort downstream, graft.
                    self._der_handle_step_failure(
                        item, queue, plan, _session, _turn_id, context_package,
                        step_result=step_result,
                    )
                    continue  # re-enter loop; grafted steps are now in the queue

            # â”€â”€ Phase 4: finalize this step via the shared helper â”€â”€
            _tokens_used = self._der_finalize_step(
                item,
                step_result,
                step_success,
                step_outputs,
                completed_items,
                _tokens_used,
                _token_budget,
                _session,
                _turn_id,
                _phase,
                is_mature,
                _live_ctx,
                plan,
                context_package,
                queue,
                verdict,
                from_voice,
            )

            # â”€â”€ Phase 4: concurrently execute any ADDITIONAL ready
            # parallel_safe steps this cycle, then finalize them with the
            # same helper. The primary `item` above is already finalized.
            # parallel_safe is derived from the tool registry (is_parallel_safe),
            # so this batch is ACTIVE for read-only/independent tools
            # (vision analysis, search, read_file, github reads, git read-only). â”€â”€
            # all_ready_items() may raise TOPO_VIOLATION â€” let it propagate
            # exactly like next_ready() does (do NOT swallow it here).
            _extra_ready = [
                i for i in queue.all_ready_items(_session)
                if i.step_id != item.step_id
                and getattr(i, "parallel_safe", False)
            ]
            if _extra_ready:
                try:
                    _extra_results = asyncio.run(
                        self._der_exec_steps_concurrent(
                            _extra_ready, context_package, _session, _turn_id, plan
                        )
                    )
                except Exception as _conc_exc:
                    logger.warning(
                        "[DER] Phase 4 concurrent exec failed: %s â€” "
                        "falling back to serial",
                        _conc_exc,
                    )
                    _extra_results = {
                        i.step_id: self._der_run_step_execution(
                            i, context_package, _session, _turn_id, plan, queue=queue
                        )
                        for i in _extra_ready
                    }
                for _ei in _extra_ready:
                    _er, _es = _extra_results[_ei.step_id]
                    if not _es:
                        # Phase 1.4: single retry for the extra step â€” use the
                        # SAME retry authority as the main step path
                        # (retry_with_backoff_sync), NOT an ad-hoc
                        # time.sleep(0.5) + silent retry (REQ-5). This keeps the
                        # retry policy single and consistent, and respects
                        # NO_RETRY_ERRORS (e.g. RateLimitedError is not retried).
                        from backend.agent.resilience import retry_with_backoff_sync

                        try:
                            _er, _es = retry_with_backoff_sync(
                                max_retries=1,
                                label=f"der-extra-step-{_ei.step_number}",
                            )(self._der_run_step_execution)(
                                _ei, context_package, _session, _turn_id, plan
                            )
                        except Exception as _retry_exc:
                            _er, _es = str(_retry_exc), False
                    if not _es:
                        # C1 FIX: preserve the real error for the graft prompt.
                        _ei.result = _er
                        # Failed after retry â€” handle (mark/abort/graft) and
                        # skip finalizing this now-terminal step.
                        self._der_handle_step_failure(
                            _ei, queue, plan, _session, _turn_id, context_package
                        )
                        continue
                    _tokens_used = self._der_finalize_step(
                        _ei, _er, _es,
                        step_outputs, completed_items,
                        _tokens_used, _token_budget,
                        _session, _turn_id, _phase, is_mature,
                        _live_ctx, plan, context_package, queue,
                        ReviewVerdict.PASS,
                        from_voice,
                    )

        # â”€â”€ OUTCOME RECORDING (ordered per spec: clear â†’ stats â†’ episode)
        # NOTE: _store_task_episode internally calls mycelium_record_outcome
        # and mycelium_crystallize_landmark, so we do NOT duplicate them here.
        # DER Phase 0 (D0.6): coarsen outcome from verified_fraction, not a binary
        # "[STEP ERROR" substring. hit (>=0.8) / partial (0.3-0.8) / miss (<0.3).
        _joined = "\n".join(step_outputs)
        _frac = self._verified_fraction(item.expected_output, _joined) if step_outputs else 0.0
        if queue.failed_ids:
            outcome = "failure"
        elif _frac >= 0.8:
            outcome = "success"
        elif _frac >= 0.3:
            outcome = "partial"
        else:
            outcome = "failure"

        # â”€â”€ REQ-15 AC3 (T25): an explicit stop persists the lifecycle as
        # `cancelled` (REQ-9 LIFECYCLE_CANCELLED) and reports honestly â€”
        # never a fabricated success or failure.
        if getattr(self, "_der_stop_requested", False):
            outcome = "cancelled"

        # â”€â”€ T6 (REQ-5 / D8): task lifecycle reaches its terminal state HERE,
        # derived from the same honest queue state as the outcome label, and is
        # persisted BEFORE the terminal task:done/task:fail event. completed /
        # partial / failed are decided by execution state (queue terminals +
        # verified fraction), never by physics convergence. A persistence
        # failure is exposed honestly and does not silently claim durable
        # completion.
        try:
            from backend.agent.der_execution_ledger import ExecutionLedger

            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(
                    conversation_id=self.conversation_id or self.session_id or ""
                )
                self._der_ledger = _ledger
            _task_id = self.conversation_id or self.session_id or "unknown"
            _term = {
                "success": "completed",
                "partial": "partial",
                "failure": "failed",
                "cancelled": "cancelled",
            }.get(outcome, "failed")
            _t = _ledger.transition(_task_id, _term)
            if not _ledger.persist():
                logger.warning(
                    "[DER] task lifecycle persistence FAILED (state=%s) â€” durable completion not claimed",
                    _term,
                )
        except Exception as _lc_exc:  # noqa: BLE001 â€” lifecycle must never block the user response
            logger.debug("[DER] task lifecycle write failed: %s", _lc_exc)

        # â”€â”€ EventBus: emit task:done / task:fail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # T11 (REQ-12): record the completed-step count on the kernel so the
        # caller's TurnMetrics block (metrics.der_steps) reads a real number.
        # len(completed_items) is authoritative here â€” it is appended only in
        # _der_finalize_step, one per actually-completed step.
        self._der_step_count = len(completed_items)
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            _lifecycle_task_id = _turn_id or plan.original_task[:40]
            get_event_bus().emit(
                IRISStreamEvent.TASK_DONE if outcome == "success" else IRISStreamEvent.TASK_FAIL,
                data={
                    "task_id": _lifecycle_task_id,
                    "outcome": outcome,
                    # REQ-15 AC3 (T25): a stop is explicit â€” the user sees it.
                    "cancelled": outcome == "cancelled",
                    "steps_completed": len(completed_items),
                    "total_steps": len(plan.steps),
                    "failed_steps": [
                        {
                            "step_id": _fi,
                            "description": next(
                                (_it.description for _it in queue.items
                                 if _it.step_id == _fi),
                                _fi,
                            ),
                            "reason": next(
                                (_it.result for _it in queue.items
                                 if _it.step_id == _fi),
                                "",
                            ) or "",
                        }
                        for _fi in queue.failed_ids
                    ],
                    # REQ-3 AC6 (T2): card_id stays stable across every
                    # event of a card's lifetime, not just task:start.
                    **self._card_envelope(_lifecycle_task_id),
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
            # T4a (REQ-4 AC1): persist the terminal state. Mirrors the same
            # outcome == "success" condition used to pick TASK_DONE vs
            # TASK_FAIL above â€” no separate terminal-state taxonomy invented.
            _envelope = self._card_envelope(_lifecycle_task_id)
            self._persist_card_snapshot(
                card_id=_envelope.get("card_id"),
                conversation_id=self.conversation_id,
                card_relation="continues",
                plan_title=self._effective_plan_title(plan),
                mode=queue.mode.value if getattr(queue, "mode", None) else None,
                steps=self._queue_steps_snapshot(queue),
                total_steps=len(queue.items),
                terminal_state="done" if outcome == "success" else "fail",
            )
        except Exception:
            pass  # EventBus is optional â€” no crash if it fails

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

        # â”€â”€ EPISODIC STORAGE: write completed task to episodic memory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Closes the read/write loop. get_task_context() already calls
        # assemble_episodic_context() which reads from this store â€” but only
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
                # Domain 4.5 â€” check if this tool sequence warrants a new skill
                try:
                    self._maybe_trigger_skill_creation(
                        tool_sequence=_tool_seq,
                        task_summary=plan.original_task,
                    )
                except Exception as _exc:
                    loud_error(_exc, "skill_creation_trigger")
        except Exception as _exc:
            loud_error(_exc, "store_task_episode")

        # â”€â”€ EventBus: emit der:done â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                    # ToolCallTree (REQ-13): structured snapshot of all tool calls
                    "tool_call_tree": (
                        self._get_tool_box().get_tool_call_tree(
                            conversation_id=self.conversation_id
                        )
                    ),
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        # REQ-12 (Wave 9): emit final context usage for the DER task.
        # Covers the "zero steps executed" case (plan rejected before any
        # step ran) where the per-step emit never fired. Uses the real
        # per-thread self._tokens_used â€” never 0 for an active thread.
        # All return paths below are preceded by this single emit.
        self._emit_context_usage(
            step_number=len(completed_items),
            total_steps=len(queue.items),
        )

        # Phase 1.5: if any step failed, synthesize a user-facing summary
        # that explains what worked, what failed, and what to do next.
        if queue.failed_ids:
            # REQ-16 AC2 (T32): a task with failed steps did NOT exit naturally.
            self._der_stamp_session_exit(False)
            _synthesis = self._der_synthesize_outcome(
                plan, completed_items, queue, _session
            )
            # REQ-18 AC2 (T31): correlate which synthesis path ran.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "synthesis",
                    path="failure" if _synthesis else "deterministic_failure",
                    ran=bool(_synthesis),
                )
            except Exception:
                pass
            if _synthesis:
                return _synthesis
            # LLM synthesis unavailable (e.g. model rate-limited â€” the very
            # failure that broke the step) -> deterministic fallback so the user
            # is NEVER left with silence (Part B).
            return AgentKernel._der_deterministic_failure_summary(
                plan, completed_items, queue
            )

        if step_outputs:
            # REQ-16 AC2 (T32): a task that ran steps to completion exited
            # naturally.
            self._der_stamp_session_exit(True)
            # REQ-12 (AC1/AC2/AC3): synthesize the gathered evidence into a
            # final answer instead of raw-concatenating step outputs. Consumes
            # the same evidence the failure path consumes (plan.original_task
            # + completed step descriptions/results) and wires the previously-
            # dead _synthesize_response brain synthesis.
            _synthesis = self._der_synthesize_success_outcome(
                plan, completed_items, queue, _session
            )
            # REQ-18 AC2 (T31): correlate which synthesis path ran.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "synthesis",
                    path="success" if _synthesis else "deterministic_success",
                    ran=bool(_synthesis),
                )
            except Exception:
                pass
            if _synthesis:
                return _synthesis
            # REQ-12 (AC4): synthesis unavailable (e.g. reasoning provider
            # down) -> deterministic success summary mirroring
            # _der_deterministic_failure_summary so the user is never left
            # with raw concatenation (Part B symmetry).
            return AgentKernel._der_deterministic_success_summary(
                plan, completed_items, queue
            )
        # â”€â”€ Zero steps (or zero usable outputs) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The crawl plan produced no executable URLs (all blocked/filtered
        # by BOT_BLOCKED_DOMAINS, or the LLM couldn't generate any). Return
        # a descriptive message so _plan_task's post-processing can surface
        # an actionable explanation instead of the generic "couldn't generate".
        # REQ-16 AC2 (T32): zero usable steps is NOT a natural exit.
        self._der_stamp_session_exit(False)
        return (
            f"[DER] {plan.strategy} â€” "
            f"{len(completed_items)}/{len(plan.steps)} steps completed.  "
            f"error: no usable sources found for '{getattr(plan, 'title', '') or getattr(plan, 'plan_title', '') or plan.original_task[:40]}'.  "
            + self._build_crawl_failure_explanation(plan)
        )

    # â”€â”€ Phase 1.4: failure handling + plan grafting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _task_start_payload(
        *,
        task_id: str,
        description: str,
        plan_title: str,
        mode: str,
        steps: list,
        total_steps: int,
        origin: str,
        card_id: str,
        card_relation: str,
        conversation_id: Optional[str],
        agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> dict:
        """The ``task:start`` payload contract (REQ-14 / T23; REQ-3 / T1).

        ONE construction point for every ``task:start`` emit so the
        merge-by-id contract keys (useTaskProgress.ts:210-227 â€”
        task_id / description / plan_title / mode / steps / total_steps)
        stay identical across sites, plus ``origin`` distinguishing the
        initial announcement from revisions: ``"initial"`` (both initial
        emits), ``"sub_loop_split"`` (REQ-4/REQ-13 split), ``"user_steering"``
        (REQ-15), or ``"amendment"``. REQ-18's trace reads ``origin`` to
        attribute a revision.

        T1 (REQ-3): ADDITIVE ONLY â€” ``card_id`` / ``card_relation`` /
        ``conversation_id`` are the three new keys; nothing about the seven
        keys above changed. Kept a @staticmethod on purpose: identity
        resolution (``_resolve_card_identity``, which needs kernel state)
        stays a separate, independently-testable step, and every caller
        resolves it before building this payload.

        cli-workspace-unification T9a (REQ-5 AC1): ADDITIVE ONLY â€”
        ``agent_id`` (kernel session identity) and ``project_id`` (active
        project folder scope) join the same single construction point, so
        every emit site inherits the multi-agent Kanban tags for free. The
        frontend never fabricates them; when ``project_id`` is unknown
        (no active project scope set on the kernel) consumers fall back to
        conversationId-only keying.

        Session 244 (cardâ†”response inline join): ADDITIVE ONLY â€”
        ``turn_id`` (the kernel's current response turn id,
        ``self._current_turn_id``) joins the payload so the frontend can
        render a card INLINE with the assistant message it belongs to â€”
        the same join documents already use (message.id === turn_id).
        Absent on legacy replays; consumers fall back to bottom-stacking.
        """
        return {
            "task_id": task_id,
            "description": description,
            "plan_title": plan_title,
            "mode": mode,
            "steps": steps,
            "total_steps": total_steps,
            "origin": origin,
            "card_id": card_id,
            "card_relation": card_relation,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "project_id": project_id,
            "turn_id": turn_id,
        }

    @staticmethod
    def _effective_plan_title(plan: Any) -> str:
        """pin_07b780e7ce21: the objective title must arrive RELIABLY on every
        ``task:start`` / card snapshot — the LLM planner sometimes omits
        ``plan_title`` from its JSON, which left search cards with no dominant
        header (the frontend fell back to steps[0].description). When the
        planner title is empty, derive one from the original task so the
        frontend always has a real objective to render; the 80-char wire
        budget every call site already used is unchanged."""
        title = str(getattr(plan, "plan_title", "") or "").strip()
        if title:
            return title[:80]
        return str(getattr(plan, "original_task", "") or "")[:80]

    def _multiagent_tags(self) -> dict:
        """T9a (REQ-5 AC1): the ``(agent_id, project_id)`` Kanban tags,
        resolved ONCE here so every ``task:start`` call site spreads the
        same dict. ``agent_id`` is the kernel session identity;
        ``project_id`` is the active project folder scope â€” ``None`` until
        a project scope is set on the kernel (consumers then fall back to
        conversationId-only keying per design.md Error Handling)."""
        return {
            "agent_id": getattr(self, "session_id", None)
            or getattr(self, "conversation_id", None),
            "project_id": getattr(self, "active_project_id", None),
        }

    def _register_card(self, task_id: str, card_id: str) -> None:
        """Bind ``task_id -> card_id`` in the per-kernel registry (REQ-3/T2).

        Bounded at ``_CARD_REGISTRY_CAP`` â€” evicts the oldest insertion first
        (dict preserves insertion order) so a long-running kernel process
        cannot leak memory one entry per DER task forever.
        """
        if task_id in self._card_by_task:
            return
        if len(self._card_by_task) >= self._CARD_REGISTRY_CAP:
            oldest_task_id = next(iter(self._card_by_task))
            del self._card_by_task[oldest_task_id]
        self._card_by_task[task_id] = card_id

    def _resolve_card_identity(self, task_id: str, origin: str) -> tuple:
        """REQ-3 AC2/AC3/AC5 (T2): decide ``card_id`` / ``card_relation`` for
        one ``task:start`` emit, entirely from backend state.

        a. ``task_id`` already registered -> same card_id, "continues". This
           is the known double-emit case: the early LLM-plan skeleton then
           the DER queue emit for one task (REQ-3 edge case â€” no flicker).
        b. ``origin != "initial"`` and there is an active card -> register
           ``task_id`` against the ACTIVE card and continue it. Written as
           "not initial" ON PURPOSE, rather than an explicit membership test
           against sub_loop_split / user_steering / amendment: a non-initial
           origin is by definition a revision of a running task, so a future
           fifth origin still continues the card instead of silently
           starting a new one. A sub-loop split CONTINUES the parent card â€”
           a branch WITHIN a card, never a second card.
        c. otherwise -> a genuinely new task; mint ``card_{task_id}``,
           register it, make it the active card, return "new".

        Never raises â€” a resolution failure logs and falls back to a fresh,
        unregistered card_id rather than breaking the task:start emit.
        """
        try:
            if not task_id:
                logger.warning(
                    "[AgentKernel] card identity: empty task_id (origin=%s conv=%s) "
                    "â€” minting an unregistered card; continuation will not track it",
                    origin, self.conversation_id,
                )
                import uuid as _uuid
                return f"card_unknown_{_uuid.uuid4().hex[:8]}", "new"

            existing = self._card_by_task.get(task_id)
            if existing is not None:
                logger.info(
                    "[AgentKernel] card identity: task=%s origin=%s conv=%s -> "
                    "continues existing card=%s (double-emit)",
                    task_id, origin, self.conversation_id, existing,
                )
                return existing, "continues"

            if origin != "initial" and self._active_card_id is not None:
                card_id = self._active_card_id
                self._register_card(task_id, card_id)
                logger.info(
                    "[AgentKernel] card identity: task=%s origin=%s conv=%s -> "
                    "continues active card=%s (non-initial origin revises "
                    "the running task)",
                    task_id, origin, self.conversation_id, card_id,
                )
                return card_id, "continues"

            card_id = f"card_{task_id}"
            self._register_card(task_id, card_id)
            self._active_card_id = card_id
            logger.info(
                "[AgentKernel] card identity: task=%s origin=%s conv=%s -> "
                "new card=%s",
                task_id, origin, self.conversation_id, card_id,
            )
            return card_id, "new"
        except Exception as _card_exc:  # noqa: BLE001 â€” never break a task emit
            logger.warning(
                "[AgentKernel] card identity resolution failed "
                "(task=%s origin=%s conv=%s): %s",
                task_id, origin, self.conversation_id, _card_exc,
            )
            return f"card_{task_id or 'unknown'}", "new"

    def _card_envelope(self, task_id: Optional[str]) -> dict:
        """REQ-3 AC6 (T2): keep ``card_id`` stable across every event of a
        card's lifetime, not just ``task:start``. LOOKS UP (never registers)
        the card already bound to ``task_id`` and returns the pair to merge
        into a lifecycle emit dict (tool:call, tool:result, task:done/fail,
        task:progress). Unknown ``task_id`` -> ``card_id`` is None â€” a wrong
        id is worse than a missing one. Never raises.
        """
        try:
            card_id = self._card_by_task.get(task_id) if task_id else None
        except Exception:
            card_id = None
        return {"card_id": card_id, "conversation_id": self.conversation_id}

    @staticmethod
    def _queue_steps_snapshot(queue) -> list:
        """T4a (REQ-4 AC1/AC5): the FULL, cumulative step list + derived
        status, for card PERSISTENCE â€” distinct from the task:start WIRE
        payload, which for revision origins (user_steering/amendment)
        intentionally emits only the delta for the frontend's merge-by-id
        reducer (useTaskProgress.ts). A persisted card has no earlier
        partial payload to merge against, so persistence always walks
        ``queue.items`` (already cumulative by the time any revision emits)
        and derives status from completed_ids/failed_ids/vetoed_ids rather
        than reusing the wire delta. Never raises â€” a malformed queue
        persists as "no steps" rather than breaking the emit it rides on.
        """
        try:
            return [
                {
                    "id": it.step_id,
                    "description": it.description,
                    "status": (
                        "done" if it.step_id in queue.completed_ids
                        else "failed" if it.step_id in queue.failed_ids
                        else "vetoed" if it.step_id in queue.vetoed_ids
                        else "pending"
                    ),
                    "toolName": it.tool,
                }
                for it in queue.items
            ]
        except Exception:
            return []

    def _persist_card_snapshot(
        self,
        *,
        card_id: Optional[str],
        conversation_id: Optional[str],
        card_relation: str = "new",
        plan_title: Optional[str] = None,
        mode: Optional[str] = None,
        steps: Optional[list] = None,
        total_steps: int = 0,
        terminal_state: str = "running",
    ) -> None:
        """T4a (REQ-4 AC1/AC5): mirror one card lifecycle moment
        (task:start, a task:progress step transition, or task:done/fail)
        into the persistent card store.

        ONE construction point, called from every emit site that carries
        card identity (mirrors ``_task_start_payload``'s pattern), so the
        shape handed to ``CardState``/``CardStepSnapshot`` never drifts
        between call sites.

        NON-BLOCKING: hands the snapshot to
        ``conversation_context_store.enqueue_card_write`` â€” a bounded,
        coalescing background queue â€” rather than calling
        ``store.save_card()`` (synchronous SQLite) directly. These emit
        sites run on the DER worker thread (iris_gateway.py's
        ``run_in_executor`` pool), not inside a coroutine, so there is no
        event loop to offload to; the queue's own background thread is the
        offload.

        Missing ``card_id``/``conversation_id`` (unknown task_id, no active
        card) is a no-op â€” there is nothing to persist. Never raises: a
        persistence failure must never block a card emit or a user
        response.
        """
        try:
            if not card_id or not conversation_id:
                return
            from backend.agent.conversation_context_store import (
                CardState,
                CardStepSnapshot,
                enqueue_card_write,
            )

            _steps = [
                CardStepSnapshot(
                    id=str(s.get("id", "")),
                    description=str(s.get("description", "")),
                    status=str(s.get("status", "pending")),
                    tool_name=s.get("toolName") or s.get("tool_name"),
                    # Session 246 (@-card-mentions): persist the distilled
                    # outcome so a referenced card carries its findings.
                    result_summary=(
                        s.get("resultPreview")
                        or s.get("result_summary")
                        or s.get("summary")
                    ),
                )
                for s in (steps or [])
            ]
            _done = sum(1 for s in _steps if s.status not in ("pending",))
            enqueue_card_write(
                CardState(
                    card_id=card_id,
                    conversation_id=conversation_id,
                    card_relation=card_relation,
                    plan_title=plan_title,
                    mode=mode,
                    steps=_steps,
                    current_step=_done,
                    total_steps=total_steps or len(_steps),
                    terminal_state=terminal_state,
                )
            )
        except Exception as exc:  # noqa: BLE001 â€” persistence must never block a card emit
            logger.debug(
                "[AgentKernel] card persistence skipped (card_id=%s): %s",
                card_id, exc,
            )

    # â”€â”€ REQ-15 (T25): mid-task steering channel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _der_check_steering(self, _session, plan, queue) -> Optional[dict]:
        """REQ-15 AC1/AC2/AC3/AC6 (T25): consume pending steering at the NEXT
        step boundary â€” never mid-step.

        Drains every record queued for the session since the last boundary
        and applies, in order:
          - stop   -> latch ``_der_stop_requested`` (AC3: the loop aborts
                      here and persists `cancelled`);
          - pause  -> latch ``_der_pause_requested`` (AC4: the loop
                      suspends via ``_der_suspend_task``);
          - resume -> latch ``_der_resume_requested`` (harmless when the
                      task is not suspended; consumed and acked either way);
          - steer  -> revise the remaining plan via REQ-14's revision channel
                      (AC2); the LAST non-empty steering text wins.

        AC6 (channel independence): stop/pause flags are latched BEFORE any
        (potentially slow) revision is applied, and a stop suppresses the
        revision entirely â€” a stop is never delayed behind steering work.

        AC5 (acknowledgement): every consumed record emits ``steering:ack``
        status="considered".

        Returns ``None`` when nothing was queued, else a dict
        ``{"stop", "pause", "resume": bool, "steer": str|None,
        "revised": bool}``.
        """
        try:
            from backend.agent.steering import get_steering_inbox
        except Exception:
            return None
        records = get_steering_inbox().drain(_session)
        if not records:
            return None

        stop = False
        pause = False
        resume = False
        steer_text = None
        for rec in records:
            if rec.channel == "stop":
                stop = True
            elif rec.channel == "pause":
                pause = True
            elif rec.channel == "resume":
                resume = True
            elif rec.channel == "steer" and rec.text and rec.text.strip():
                steer_text = rec.text.strip()  # last non-empty steering wins

        # AC6: latch the control flags BEFORE applying any revision so a stop
        # is never delayed behind a slow re-plan.
        if stop:
            self._der_stop_requested = True
        if pause:
            self._der_pause_requested = True
        if resume:
            self._der_resume_requested = True

        revised = False
        if steer_text is not None and not stop:
            revised = self._der_apply_steering(steer_text, _session, plan, queue)

        # AC5: every consumed record is acknowledged as "considered".
        for rec in records:
            self._emit_steering_ack(rec.channel, rec.message_id, "considered", _session)

        # REQ-18 AC4 (T31): correlate every steering message received â€” channel,
        # acknowledged status, and the step boundary at which it was applied.
        try:
            from backend.agent.der_trace import get_der_trace

            _trace = get_der_trace(self._der_trace_task_id())
            for rec in records:
                _trace.record(
                    "steering",
                    channel=rec.channel,
                    message_id=rec.message_id,
                    ack="considered",
                    boundary_step=getattr(queue, "_last_step_number", None),
                )
        except Exception:
            pass

        return {
            "stop": stop,
            "pause": pause,
            "resume": resume,
            "steer": steer_text,
            "revised": revised,
        }

    def _der_apply_steering(self, text, _session, plan, queue) -> bool:
        """REQ-15 AC2: revise the remaining plan via REQ-14's revision
        channel without aborting the task.

        Re-plans from the steering text (single-step fallback on failure),
        REMOVES every not-yet-terminal queue item (they are REPLACED, not
        failed â€” ``queue.failed_ids`` stays honest), appends the revised steps
        as fresh items, and re-emits ``task:start`` with
        ``origin="user_steering"`` carrying the revised step list (REQ-14 AC1
        revision signal; REQ-18 AC3 origin).

        Returns True when a revision was actually applied.
        """
        try:
            from backend.agent.der_loop import QueueItem
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            _mode = queue.mode.value if getattr(queue, "mode", None) else "full"
            _rev = self._plan_task(
                text,
                session_id=_session,
                mode=_mode,
            )
            if _rev is None or not getattr(_rev, "steps", None):
                logger.info(
                    "[DER] Session %s steering produced no plan â€” keeping "
                    "the current plan", _session,
                )
                return False

            _done = (
                set(queue.completed_ids)
                | set(queue.vetoed_ids)
                | set(queue.failed_ids)
            )
            # Replace remaining pending steps: remove them (not failures),
            # then append the revised steps fresh.
            queue.items[:] = [it for it in queue.items if it.step_id in _done]

            _fresh: List["QueueItem"] = []
            _base = len(queue.items) + 1
            for _i, _s in enumerate(_rev.steps):
                # Neutralize dependencies that point at dropped ids so the
                # revised steps are immediately ready.
                _deps = [
                    d for d in (getattr(_s, "depends_on", None) or [])
                    if d in _done
                ]
                _fresh.append(
                    QueueItem(
                        step_id=f"steer-{_base + _i}",
                        step_number=_base + _i,
                        description=_s.description,
                        tool=getattr(_s, "tool", None),
                        params=dict(getattr(_s, "params", None) or {}),
                        depends_on=_deps,
                        critical=getattr(_s, "critical", True),
                        objective_anchor=(
                            getattr(plan, "original_task", "") if plan else ""
                        ),
                    )
                )
            queue.items.extend(_fresh)

            # REQ-14 revision signal with the user_steering origin.
            _card_task_id = self.conversation_id or _session
            _card_id, _card_relation = self._resolve_card_identity(
                _card_task_id, "user_steering"
            )
            get_event_bus().emit(
                IRISStreamEvent.TASK_START,
                data=self._task_start_payload(
                    task_id=_card_task_id,
                    description=text,
                    plan_title=self._effective_plan_title(plan),
                    mode=_mode,
                    steps=[
                        {
                            "id": it.step_id,
                            "description": it.description,
                            "status": "pending",
                            "toolName": it.tool,
                        }
                        for it in _fresh
                    ],
                    total_steps=len(_fresh),
                    origin="user_steering",
                    # REQ-3 (T2): backend-declared card identity.
                    card_id=_card_id,
                    card_relation=_card_relation,
                    conversation_id=self.conversation_id,
                        turn_id=getattr(self, "_current_turn_id", None),
                    **self._multiagent_tags(),
                ),
                turn_id=self.conversation_id or _session,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
            # T4a (REQ-4 AC1): persist the revised card. The WIRE payload
            # above intentionally carries only `_fresh` (the delta the
            # frontend merges) â€” the STORED snapshot must stay the FULL
            # cumulative step list (queue.items, already extended with
            # _fresh), or a restore would show only the newest steps.
            self._persist_card_snapshot(
                card_id=_card_id,
                conversation_id=self.conversation_id,
                card_relation=_card_relation,
                plan_title=self._effective_plan_title(plan),
                mode=_mode,
                steps=self._queue_steps_snapshot(queue),
                total_steps=len(queue.items),
                terminal_state="running",
            )
            # REQ-18 AC3 (T31): correlate the user-steering revision.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "revision",
                    origin="user_steering",
                    boundary_step=getattr(queue, "_last_step_number", None),
                )
            except Exception:
                pass
            return True
        except Exception as _steer_exc:
            logger.debug("[DER] steering revision failed: %s", _steer_exc)
            return False

    # â”€â”€ REQ-5 (specs/dag-node-execution-model): bounded mid-execution
    # amendment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # The executing graph may be EXTENDED between steps based on outcomes
    # already observed (AC1). Planner-driven ONLY (design D6) â€” a node
    # proposing its own successor would reintroduce hidden control flow.
    # Amendments append fresh steps; they never re-execute satisfied nodes
    # (AC2) and the existing step budget / token accounting stays
    # authoritative (AC4). Bounded per task (AC3) and every amendment /
    # refused amendment is recorded (REQ-9 AC3).
    _AMENDMENT_BOUND = int(os.environ.get("IRIS_NODE_AMENDMENT_BOUND", "3"))

    def _der_amend_graph(
        self,
        new_steps,
        _session: str,
        plan,
        queue,
        _token_budget: int = 0,
        _tokens_used: int = 0,
    ) -> bool:
        """Extend the executing graph with *new_steps* (REQ-5).

        Returns True when the amendment was applied. Refused amendments are
        recorded with their cause (REQ-5 AC5, REQ-9 AC3) and execution
        continues on the existing graph â€” never a hang, never a silent skip.
        """
        from backend.agent.nodes.telemetry import log_amendment

        # getattr, not attribute access: these run on the graft/recovery paths,
        # and a kernel built via __new__ (as the DER test doubles and some
        # recovery paths do) has no conversation_id. A bare access raised
        # AttributeError inside the graft's try/except, silently turning
        # "amend the graph" into "recovery failed" â€” telemetry must never be
        # able to cost a graft.
        _task_id = getattr(self, "conversation_id", None) or _session
        try:
            if not new_steps:
                return False
            # AC3: per-task bound on amendments.
            _used = getattr(self, "_der_amendment_count", 0)
            if _used >= self._AMENDMENT_BOUND:
                log_amendment(
                    task_id=_task_id, kind="refused",
                    cause="amendment_bound",
                    detail=f"used={_used} bound={self._AMENDMENT_BOUND}",
                )
                return False
            # AC4: the task budget is authoritative â€” an amendment cannot
            # exceed it. (Amendments add steps; if the budget is already
            # exhausted, adding work would violate the ceiling.)
            if _token_budget > 0 and _tokens_used >= _token_budget:
                log_amendment(
                    task_id=_task_id, kind="refused",
                    cause="budget_exceeded",
                    detail=f"used={_tokens_used} budget={_token_budget}",
                )
                return False

            # AC2: satisfied nodes are preserved. New steps may only depend on
            # already-terminal ids (completed/vetoed/failed); a dependency on a
            # pending node that may never run would stall the graph â€” refuse
            # (REQ-5 edge: amendment that removes/consumes a live node is
            # rejected, recorded, execution unchanged).
            from backend.agent.der_loop import QueueItem

            _done = (
                set(queue.completed_ids)
                | set(queue.vetoed_ids)
                | set(queue.failed_ids)
            )
            _pending = {it.step_id for it in queue.items if it.step_id not in _done}
            for _s in new_steps:
                _deps = list(getattr(_s, "depends_on", None) or [])
                _bad = [d for d in _deps if d in _pending]
                if _bad:
                    log_amendment(
                        task_id=_task_id, kind="refused",
                        cause="invalid_dependency",
                        detail=f"step={getattr(_s, 'description', '')[:60]} deps={_bad}",
                    )
                    return False

            # Append the fresh steps â€” completed work is untouched (AC2).
            _base = len(queue.items) + 1
            _fresh: List["QueueItem"] = []
            for _i, _s in enumerate(new_steps):
                _fresh.append(
                    QueueItem(
                        step_id=f"amend-{_base + _i}",
                        step_number=_base + _i,
                        description=getattr(_s, "description", ""),
                        tool=getattr(_s, "tool", None),
                        params=dict(getattr(_s, "params", None) or {}),
                        depends_on=[
                            d for d in (getattr(_s, "depends_on", None) or [])
                            if d in _done
                        ],
                        critical=getattr(_s, "critical", True),
                        objective_anchor=(
                            getattr(plan, "original_task", "") if plan else ""
                        ),
                    )
                )
            queue.items.extend(_fresh)
            self._der_amendment_count = _used + 1
            log_amendment(
                task_id=_task_id, kind="amend",
                cause="planner_driven",
                detail=f"steps={len(_fresh)} count={_used + 1}",
            )
            logger.info(
                "[DER] amendment applied: +%d step(s) (count=%d) task=%s",
                len(_fresh), _used + 1, _task_id,
            )

            # Revision signal so the frontend card reflects the extended plan â€”
            # SAME payload shape as steering (no new event types; REQ-3 AC4).
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                _mode = queue.mode.value if getattr(queue, "mode", None) else "full"
                # REQ-3 (T2): "amendment" is a fourth, undocumented origin â€”
                # handled generically by the "not initial" rule in
                # _resolve_card_identity rather than special-cased here.
                _card_id, _card_relation = self._resolve_card_identity(
                    _task_id, "amendment"
                )
                get_event_bus().emit(
                    IRISStreamEvent.TASK_START,
                    data=self._task_start_payload(
                        task_id=_task_id,
                        description=(
                            getattr(plan, "original_task", "") or ""
                        )[:120],
                        plan_title=self._effective_plan_title(plan),
                        mode=_mode,
                        steps=[
                            {
                                "id": it.step_id,
                                "description": it.description,
                                "status": "pending",
                                "toolName": it.tool,
                            }
                            for it in _fresh
                        ],
                        total_steps=len(_fresh),
                        origin="amendment",
                        # REQ-3 (T2): backend-declared card identity.
                        card_id=_card_id,
                        card_relation=_card_relation,
                        conversation_id=self.conversation_id,
                            turn_id=getattr(self, "_current_turn_id", None),
                        **self._multiagent_tags(),
                    ),
                    turn_id=_task_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
                # T4a (REQ-4 AC1): persist the amended card â€” full
                # cumulative queue.items (already extended with _fresh
                # above), not the wire delta (same reasoning as the
                # user_steering site).
                self._persist_card_snapshot(
                    card_id=_card_id,
                    conversation_id=self.conversation_id,
                    card_relation=_card_relation,
                    plan_title=self._effective_plan_title(plan),
                    mode=_mode,
                    steps=self._queue_steps_snapshot(queue),
                    total_steps=len(queue.items),
                    terminal_state="running",
                )
            except Exception:
                pass  # never block an amendment on an emit failure
            return True
        except Exception as _amend_exc:  # noqa: BLE001 â€” refusal, never a crash
            log_amendment(
                task_id=_task_id, kind="refused",
                cause="error", detail=str(_amend_exc)[:200],
            )
            return False

    def _emit_steering_ack(self, channel, message_id, status, _session) -> None:
        """REQ-15 AC5 (T26): visible acknowledgement that a steering message
        landed ("queued") or was considered at a step boundary ("considered").
        Best-effort â€” never blocks or breaks the loop."""
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.STEERING_ACK,
                data={
                    "channel": channel,
                    "message_id": message_id,
                    "status": status,
                },
                turn_id=self.conversation_id or _session,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass

    def _der_suspend_task(self, _session, plan, queue, _turn_id) -> str:
        """REQ-15 AC4 (T26): suspend execution at the next step boundary.

        Persists the in-progress state (ledger lifecycle ``paused`` + a
        ``task:paused`` event), then waits for a ``resume`` or ``stop``
        record. Steer records arriving while suspended STAY queued and are
        applied at the next boundary after resume â€” they are never dropped.
        Idempotent resume: ``completed_ids``/``vetoed_ids``/``failed_ids``
        ARE the persisted in-progress state; ``next_ready`` skips them, so
        no completed side effect is duplicated on resume.

        Returns "resume" or "stop". Runs on the DER worker thread â€” the
        bounded poll (time.sleep) never blocks the event loop.
        """
        from backend.agent.der_execution_ledger import ExecutionLedger
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
        from backend.agent.steering import get_steering_inbox
        import time as _time

        # getattr, not attribute access: these run on the graft/recovery paths,
        # and a kernel built via __new__ (as the DER test doubles and some
        # recovery paths do) has no conversation_id. A bare access raised
        # AttributeError inside the graft's try/except, silently turning
        # "amend the graph" into "recovery failed" â€” telemetry must never be
        # able to cost a graft.
        _task_id = getattr(self, "conversation_id", None) or _session
        try:
            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(conversation_id=_task_id)
                self._der_ledger = _ledger
            _ledger.transition(_task_id, "paused")
            _ledger.persist()
        except Exception as _pe:
            logger.debug("[DER] pause lifecycle persist failed: %s", _pe)

        try:
            get_event_bus().emit(
                IRISStreamEvent.TASK_PAUSED,
                data={"task_id": _task_id, "state": "paused"},
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass  # EventBus optional â€” never block the loop

        inbox = get_steering_inbox()
        self._der_resume_requested = False
        while not self._der_stop_requested:
            if inbox.pending_channel(_session, "stop"):
                for _rec in inbox.drain_channel(_session, "stop"):
                    self._emit_steering_ack(
                        _rec.channel, _rec.message_id, "considered", _session
                    )
                self._der_stop_requested = True
                return "stop"
            if inbox.pending_channel(_session, "resume"):
                for _rec in inbox.drain_channel(_session, "resume"):
                    self._emit_steering_ack(
                        _rec.channel, _rec.message_id, "considered", _session
                    )
                self._der_resume_requested = True
                try:
                    _ledger = getattr(self, "_der_ledger", None)
                    if _ledger is not None:
                        _ledger.transition(_task_id, "running")
                        _ledger.persist()
                except Exception:
                    pass
                try:
                    get_event_bus().emit(
                        IRISStreamEvent.TASK_RESUMED,
                        data={"task_id": _task_id, "state": "running"},
                        turn_id=_turn_id,
                        conversation_id=self.conversation_id,
                        session_id=_session,
                    )
                except Exception:
                    pass
                return "resume"
            try:
                _time.sleep(0.2)  # poll â€” DER runs on a worker thread
            except Exception:
                break
        return "stop"

    def _build_crawl_failure_explanation(self, plan: "CrawlPlan") -> str:
        """User-facing explanation when the crawl plan found no usable sources.

        Called from the zero-steps fallback in ``_execute_plan_der``.  Returns
        a sentence explaining *why* the agent couldn't search the web, which
        ``_plan_task`` surfaces via the structured-response speak field.
        """
        _query = getattr(plan, "title", "") or ""

        # PREFER THE REASON THE PLANNER ACTUALLY RECORDED.
        # CrawlPlanner._empty_plan writes a specific cause into `instructions`
        # (e.g. "the provider rate window was already saturated (recent 429s)
        # ... retry the search shortly") precisely so the failure is reported
        # honestly. This function used to discard it and always emit the
        # bot-blocked guess below â€” so a user hitting a 60-second rate limit
        # was told to REPHRASE THEIR QUERY, which cannot help and sends them
        # down the wrong path. Only fall back to the generic text when the
        # planner did not say why.
        _reason = (getattr(plan, "instructions", "") or "").strip()
        if _reason and "LLM planning was skipped" in _reason:
            return (
                f"The agent could not search the web for {_query!r}. {_reason}"
            )

        _msg = (
            f"The agent was unable to find accessible web sources for "
            f"{_query!r}. This can happen when all generated URLs belong to "
            f"sites that block automated crawlers (academic publishers, "
            f"login-required portals, or bot-protected domains). "
            f"Try rephrasing your query to target public, accessible sites "
            f"such as news articles or Wikipedia."
        )
        return _msg[:400]

    # â”€â”€ REQ-4 (specs/dag-node-execution-model): outcome-driven routing â”€â”€â”€â”€â”€
    # The DER seam the node model adds: when a step fails with a typed reason,
    # consult the router BEFORE the graft/split handler. A recovery node that
    # advertises the reason runs in place of the failing node â€” no branch is
    # written in the failing node's module (design D4). Returns the recovered
    # step result on success, None when routing is disabled / declined / no
    # candidate â€” in which case the caller proceeds exactly as today (REQ-7
    # AC4/AC5 kill-switch parity).
    def _der_route_step_failure(
        self,
        item: "QueueItem",
        step_result: str,
        _session: str,
        _turn_id: Optional[str],
        plan,
    ) -> Optional[str]:
        try:
            from backend.agent.nodes.outcome import NodeOutcome, NodeStatus, Reason
            from backend.agent.nodes.router import (
                RouteRequest,
                get_node_router,
                routing_enabled,
            )
            from backend.agent.nodes.runner import (
                get_node_runner,
                outcome_from_crawler_error,
            )
            from backend.agent.nodes.telemetry import log_node_execution, log_routing_decision
            from backend.agent.tool_registry import get_node_spec, resolve_tool

            if not routing_enabled():
                return None  # kill switch â€” today's path (REQ-7 AC4/AC5)
            tool = getattr(item, "tool", None)
            if not tool:
                return None  # reasoning steps have no tool to route on
            spec = resolve_tool(tool)
            if spec is None:
                return None  # undeclared legacy tool â€” adapter path (REQ-7 AC1)
            node_spec = get_node_spec(tool)
            if node_spec is None:
                return None  # tool exists but never declared node metadata

            # Map the free-form failure text to a typed reason (REQ-1 AC3).
            outcome = outcome_from_crawler_error(step_result or "", time.time())
            # CT-3 (REQ-1 AC5): the typed reason reaches the EXISTING
            # node-record/error_type machinery, not a parallel structure.
            item.error_type = outcome.reason.value

            req = RouteRequest(
                task_id=self.conversation_id or _session,
                step_id=item.step_id,
                node=tool,
                outcome=outcome,
                # REQ-8 AC1/AC2: a recovery node may not exceed the tier the
                # user approved for THIS step â€” the failing node's own tier.
                approved_tier=node_spec.permission_tier,
            )
            decision = get_node_router().route(req)
            if decision is None or decision.selected is None:
                return None  # honest no-candidate (REQ-4 AC6) or blocked
            if decision.blocked_by in ("permission", "terminal", "bound"):
                # REQ-8 edge: a permission-blocked route is surfaced, never
                # taken silently â€” the caller proceeds on today's path and the
                # normal failure handling (graft / ask) applies.
                return None

            recovery = decision.selected
            # Run the recovery node through the node RUNNER (CT-4 caller
            # existence) with the tool_bridge as its executor â€” the SAME
            # dispatch path the failing node used, with the same params: the
            # route is an alternative execution of the intent.
            try:
                self._tool_bridge._active_conversation_id[_session] = (
                    self.conversation_id or ""
                )
            except Exception:
                pass
            import asyncio

            _runner = get_node_runner()
            _runner.set_executor(self._tool_bridge.execute_tool)
            try:
                _outcome = asyncio.run(
                    _runner.run(
                        recovery.name,
                        dict(item.params or {}),
                        node_spec=recovery,
                        session_id=_session,
                        plan_title=(getattr(plan, "plan_title", "") or ""),
                    )
                )
            except Exception as _route_exc:  # noqa: BLE001 â€” recovery must not crash the loop
                logger.warning(
                    "[DER] routing recovery %s for %s crashed: %s",
                    recovery.name, tool, _route_exc,
                )
                log_routing_decision(
                    task_id=self.conversation_id or _session,
                    step_id=item.step_id, node=tool,
                    reason=outcome.reason.value,
                    candidates=[recovery.name],
                    selected=None, blocked_by="upstream_error",
                )
                return None
            log_node_execution(
                task_id=self.conversation_id or _session,
                node=recovery.name,
                status=_outcome.status.value,
                reason=_outcome.reason.value,
                duration_ms=0,
            )
            if _outcome.succeeded:
                logger.info(
                    "[DER] routed %s failure reason=%s -> recovery node %s (step %s)",
                    tool, outcome.reason.value, recovery.name, item.step_id,
                )
                # Recover the formatted tool result from the outcome artifact
                # (the runner already adapted the raw dict).
                _raw = (
                    _outcome.artifact.value
                    if _outcome.artifact is not None else None
                )
                return self._format_tool_result(_raw) if _raw is not None else ""
            # Recovery node failed identically â€” the router's attempt bound
            # makes the second identical failure terminal (REQ-4 AC3).
            log_routing_decision(
                task_id=self.conversation_id or _session,
                step_id=item.step_id, node=tool,
                reason=outcome.reason.value,
                candidates=[recovery.name],
                selected=recovery.name, bound_hit=True,
            )
            return None
        except Exception as _route_err:  # noqa: BLE001 â€” routing must never break the loop
            logger.warning("[DER] routing consultation failed: %s", _route_err)
            return None

    def _der_handle_step_failure(
        self,
        item: "QueueItem",
        queue,
        plan,
        _session: str,
        _turn_id: Optional[str],
        context_package,
        step_result: Optional[str] = None,
    ) -> None:
        """
        Handle a step that failed after its single retry.

        Always marks the step failed and aborts any downstream steps that
        depend on it (so the scheduler skips them). If the step was critical
        and we haven't exhausted the graft budget, asks the LLM to design a
        recovery sub-graph and injects those steps into the queue.
        """
        queue.mark_failed(item.step_id)
        aborted = queue.abort_descendants(item.step_id)
        if aborted:
            logger.info(
                "[DER] Aborted %d downstream step(s) after failure of %s: %s",
                len(aborted), item.step_id, aborted,
            )
        # Phase 2 (D2.1) + Spec D1.2: critical failure recovery uses the SAME
        # unified _split_step operator as the physics trigger â€” NOT a separate
        # graft path that assigns tools directly. Children carry tool=None and
        # resolve via the single resolver (explorer.propose) when executed, so
        # there is exactly ONE tool-assignment authority (F6 / System Invariant).
        # D4/REQ-4 (specs/long-horizon-der-execution): classify the failure
        # BEFORE recursive fan-out at the FAILURE site too. The finalize site
        # classifies, but this handler previously split on ANY critical
        # failure â€” a rate-limited crawl (transient) or an empty URL list
        # (empty/permanent) recursively spawned graft children that re-ran the
        # same failing tool until the graft budget was exhausted (observed
        # live: 23-minute websearch loop under a saturated provider window).
        # Only a genuine semantic failure (tool produced content but
        # verification judged it wrong) splits: the step_result then carries
        # real content, not an error prefix. Mirror the finalize site: classify
        # only when the result LOOKS like an error (classify_failure never
        # returns semantic â€” it falls through to permanent), and broaden the
        # error prefixes for failure-site shapes ("RateLimitedError(...)" /
        # "ConnectionError(...)" do not start with "error").
        _split_ok = True
        try:
            from backend.agent.der_execution_ledger import (
                classify_failure,
                ExecutionLedger,
                OUTCOME_TRANSIENT,
                OUTCOME_UNAVAILABLE,
                OUTCOME_INVALID_ARGS,
                OUTCOME_EMPTY,
                OUTCOME_PERMANENT,
            )

            _res_text = (step_result or "").strip()
            _res_low = _res_text.lower()
            _tool_errored = (
                not _res_text
                or _res_low.startswith("error")
                or _res_low.startswith("ratelimitederror")
                or _res_low.startswith("connectionerror")
                or _res_low.startswith("timeouterror")
                or _res_low.startswith("[step error")
                or _res_low.startswith("duplicate call")
            )
            if _tool_errored:
                _fail_class = classify_failure(
                    False,
                    error=_res_text[:400],
                    error_type=getattr(item, "error_type", None),
                    result=step_result,
                )
                if _fail_class in (
                    OUTCOME_TRANSIENT,
                    OUTCOME_UNAVAILABLE,
                    OUTCOME_INVALID_ARGS,
                    OUTCOME_EMPTY,
                    OUTCOME_PERMANENT,
                ):
                    _split_ok = False
                    logger.info(
                        "[DER] step %s failure classified=%s â€” recorded, NOT split (D4)",
                        item.step_id, _fail_class,
                    )
                    try:
                        _ledger = getattr(self, "_der_ledger", None)
                        if _ledger is None:
                            _ledger = ExecutionLedger(
                                conversation_id=self.conversation_id or ""
                            )
                            self._der_ledger = _ledger
                        _ledger.record_failure(
                            task_id=self.conversation_id or self.session_id or "unknown",
                            step_id=item.step_id,
                            attempt_id=getattr(item, "attempt_id", "") or item.step_id,
                            failure_class=_fail_class,
                            input_summary=(item.description or "")[:200],
                            tool=item.tool,
                            error_type=getattr(item, "error_type", None),
                            error_summary=_res_text[:300],
                            recovered=False,
                        )
                    except Exception as _led_exc:  # noqa: BLE001
                        logger.debug("[DER] failure-evidence record failed: %s", _led_exc)
        except Exception:  # noqa: BLE001 â€” classification must never break recovery
            _split_ok = True
        if _split_ok and item.critical and queue.graft_attempts < DER_MAX_GRAFTS:
            try:
                _cad = self._der_live_cad_state(_session)
                _wu = getattr(self, "_der_work_units", 0)
                # REQ-4 AC1 (T16): continuous verified fraction as a GRADED
                # steering input at the split decision (mid-band -> bounded
                # probe). Never crash the split on fraction failure.
                try:
                    _vf_split = self._verified_fraction(
                        getattr(item, "expected_output", None),
                        str(step_result or ""),
                    )
                except Exception:
                    _vf_split = 0.0
                _children = self._split_step(
                    item,
                    "verify_failed",
                    _cad,
                    _wu,
                    step_result=step_result,
                    verified_fraction=_vf_split,
                )
                if _children:
                    # REQ-5 (dag-node-execution-model): grafted recovery steps
                    # ARE an amendment of the executing graph, so they go
                    # through the amendment gate rather than around it. This is
                    # _der_amend_graph's production caller â€” without one the
                    # mechanism was built, tested and unreachable.
                    #
                    # Behaviour is unchanged by construction: _AMENDMENT_BOUND
                    # and DER_MAX_GRAFTS are both 3, so the gate admits exactly
                    # the grafts that already ran. What it adds is REQ-5's
                    # guarantees on a path that previously had none â€” validity
                    # checking, the per-task bound, and telemetry for every
                    # applied AND refused amendment (REQ-5 AC5, REQ-9 AC3).
                    if not self._der_amend_graph(
                        _children, _session, plan, queue,
                    ):
                        logger.info(
                            "[DER] amendment refused for failed %s â€” continuing "
                            "on the existing graph (REQ-5 AC5)", item.step_id,
                        )
                        return aborted
                    queue.graft_attempts += 1
                    # REQ-7 AC1/AC2/AC3 (T25): route subloop children through
                    # the batcher â€” each ready group (full OR force-flushed at
                    # the join point) dispatches as ONE batched call via
                    # dispatch_batch, with results routed back per node;
                    # parse-failure children fall back to individual execution.
                    self._der_route_subloop_children(
                        _children, queue, _session, _turn_id
                    )
                    # REQ-3: debit measured tokens, not a flat child count.
                    _result_len = len(step_result) if step_result else 0
                    _measured = max(200, _result_len // 4)
                    self._der_work_units = debit_work_units(_wu, _measured)
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.RECOVERY_START,
                            data={
                                "failed_step": item.step_id,
                                "graft_attempts": queue.graft_attempts,
                                "num_grafted": len(_children),
                                "critical": item.critical,
                            },
                            session_id=_session,
                        )
                    except Exception:
                        pass
                    logger.info(
                        "[DER] Critical-failure recovery -> split into %d sub-loop(s) "
                        "for failed %s (graft_attempts=%d, work_units=%d)",
                        len(_children), item.step_id, queue.graft_attempts,
                        self._der_work_units,
                    )
            except Exception as _graft_exc:
                logger.warning("[DER] critical-failure split failed: %s", _graft_exc)
        # â”€â”€ REQ-5 (specs/long-horizon-der-execution): honest partial finalization â”€â”€
        # When the recovery budget is exhausted, the task does NOT block on a
        # TASK_BLOCKED card / ask_user QuestionCard (that escalation came from
        # the deleted der-loop-integrity-display REQ-10; the long-horizon spec
        # supersedes it: "IF budget ends before completion THEN emit remaining
        # nodes and their last failure class"). The step is already marked
        # failed, descendants already aborted, failure evidence already
        # recorded â€” the DER loop's final summary carries the remaining nodes
        # with their failure classes and the honest incomplete result.
        if item.critical and queue.graft_attempts >= DER_MAX_GRAFTS:
            logger.info(
                "[DER] REQ-5: critical step %s failed after %d grafts â€” "
                "finalizing honestly with remaining nodes + failure class",
                item.step_id, queue.graft_attempts,
            )
        # M2 FIX: record non-critical failures to memory and signal Caducean
        # so drift detection accounts for them (otherwise Q never rises on
        # repeated non-critical failures and TOPO_VIOLATION never fires).
        # PACMAN alignment: a failure pattern is the user's own hard-won lesson
        # (corrective action encoded) -> it belongs in the TRUSTED membrane
        # (PACMAN.md: trusted://episodic/failures, Tier 3), NOT an off-membrane
        # "der_failure" zone the router cannot navigate/tier. chunk_type stays
        # "der_failure" as the content-type discriminator; zone is the membrane.
        if not item.critical:
            try:
                if self._memory_interface and item.result:
                    _ep = self._memory_interface.episodic
                    if hasattr(_ep, "fragment_and_store"):
                        _ep.fragment_and_store(
                            content=f"[NON-CRITICAL FAIL Step {item.step_number}: "
                                    f"{item.description[:80]}]\n{item.result[:500]}",
                            session_id=_session,
                            chunk_type="der_failure",
                            zone="trusted",
                        )
            except Exception:
                pass
            try:
                from backend.gateway.iris_ffi import ffi_caducean_update

                # REQ-19 vocabulary: this "COMPRESS" (action=1) is the COMPRESS
                # RECOMMENDATION â€” a physics action code that increments the
                # failure accumulator y. It COMPACTS NOTHING. See the REQ-19
                # canonical-vocabulary table in
                # specs/long-horizon-der-execution/design.md (row 3) â€” it is
                # NOT Node Condense, NOT DCP message pruning, NOT mcm_compress.
                ffi_caducean_update(_session, 1, 1.0)
            except Exception:
                pass

    # â”€â”€ Phase 2: Emergent Shape â€” growth-width split/execute operator â”€â”€â”€â”€â”€â”€
    # This is the ONE recursive operator that decides execution-tree *shape*
    # from the live Caducean state (u,xi). It replaces the former mode-driven
    # fan-out AND the separate recovery-graft path: both physics-triggered
    # ("unresolved_u") and verification-failed ("verify_failed") splits use it.
    # MorphoHDL break: the decision is STATEFUL â€” width depends on live |u|,
    # never a fixed stateless predicate.

    def _growth_width(self, u: float) -> int:
        """Map live |u| to a split width (MorphoHDL athlete rule).

        REQ-19 vocabulary: this is STEP EXPANSION â€” the DER sub-loop split
        operator (_growth_width -> _split_step). It is NOT Node Expansion
        (scorer.expand, the mycelium coordinate-graph mechanism), NOT DER
        "COMPRESS" (a physics recommendation code, int 1), NOT DCP message
        pruning, and NOT mcm_compress (external build tooling). See the REQ-19
        vocabulary table in specs/long-horizon-der-execution/design.md.

        Bands (reconciles D2.3 with the split decision):
          |u| < U_SPLIT (0.5)   -> unresolved/oscillating -> split WIDE (3)
          U_SPLIT <= |u| < 0.85 -> mid-band: atomic step, needs LLM rubric (D2.3)
          |u| >= 0.85           -> converged: atomic, deterministic verify only
        """
        from backend.agent.der_constants import U_SPLIT, U_CONVERGED

        au = abs(u)
        if au < U_SPLIT:
            return 3
        if au < U_CONVERGED:
            return 1  # atomic; verification strictness handled by D2.3
        return 1

    def _der_split_width(self, u: float, verified_fraction: float) -> int:
        """REQ-4 AC1/AC2 (T16): GRADED split width â€” a continuous function of
        BOTH |u| and the verified fraction, not a |u|-only gate.

        The pre-T16 split width was binary in the verification dimension:
        ``_growth_width(u)`` returned 3 (wide) or 1 (atomic) purely from |u|,
        while ``verified_fraction`` was computed and then thrown away at the
        split decision. REQ-4 AC1 requires the continuous fraction to be a
        steering input; AC2 requires the graded middle path when the signal is
        mid-band â€” never a threshold coin-flip.

        Bands:
          verified_fraction <= 0.25            -> strong failure: |u| governs
                                                  (delegate to _growth_width)
          0.25 < verified_fraction < 0.75      -> MID-BAND (AC2): bounded probe
                                                  (width 1, probe=True) â€” the
                                                  step produced meaningful but
                                                  insufficient content; a wide
                                                  split would be a retry wearing
                                                  a split costume. The child
                                                  resolves the specific blocker
                                                  (REQ-4 AC4/T16b) at width 1.
          verified_fraction >= 0.75            -> near-pass: atomic (1) â€” the
                                                  result satisfied most of the
                                                  expected output; a wide split
                                                  spends budget re-attempting a
                                                  step that nearly passed.

        The caller marks the child ``probe=True`` when this method returns a
        width-1 mid-band probe (see _split_step).
        """
        if verified_fraction > 0.25:
            if verified_fraction < 0.75:
                return 1  # AC2 graded middle path: bounded probe, not a flip
            return 1  # near-pass: atomic
        return self._growth_width(u)  # strong failure: |u| bands govern

    # â”€â”€ REQ-5 (T17): coupling as decision-provenance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Retrieval RANKS relevant branches (physics- and evidence-driven, AC3) and
    # SURFACES ALL of them (bounded by the candidate cap) to the deciding step
    # (AC1) â€” never silently pre-selecting one by score. When the step commits,
    # the edge to the branch that informed it is written/strengthened with the
    # decision as provenance (AC2), and the per-decision record (how many
    # candidates surfaced, which was chosen) is stored on the node record (AC4).

    def _der_surface_branch_candidates(
        self, item, cad: Optional[Dict[str, float]] = None, max_candidates: int = 0
    ) -> List[dict]:
        """REQ-5 AC1/AC3 (T17): rank relevant branch candidates and return ALL
        of them (bounded by the candidate cap) â€” never one, never pre-selected.

        Ranking is physics- and evidence-driven (AC3):
          - coordinate proximity to the step's live Î£ position,
          - learned score of the region->candidate edge (if one exists),
          - compression/expansion state via the EXISTING coupling kernel
            ``trig_coupling.align_force`` (AC6 â€” reuse, do not write a second
            implementation): the u term biases candidates whose phase aligns
            with the step's current direction.

        SELECTION is NOT made here â€” the step decides with all candidates in
        view; the chosen one is recorded at commit (see
        ``_der_record_coupling_decision``).

        Returns a list of dicts ``{"node_id", "label", "score"}`` capped at
        ``max_candidates`` (0 -> DER_COUPLING_CANDIDATE_CAP). Never raises:
        any failure returns [] so coupling can never block a step (REQ-10 AC5).
        """
        from backend.agent.der_constants import DER_COUPLING_CANDIDATE_CAP
        from backend.agent.trig_coupling import align_force

        cap = max_candidates or DER_COUPLING_CANDIDATE_CAP
        if cap < 1:
            return []
        if not getattr(self, "_memory_interface", None):
            return []
        try:
            _cad = cad if cad is not None else self._der_live_cad_state(
                self.session_id or ""
            )
            _vec = [
                _cad.get("x", 0.0), _cad.get("y", 0.0),
                _cad.get("xi", 0.0), _cad.get("u", 0.0),
            ]
            _u = _cad.get("u", 0.0)
            # AC6: the EXISTING coupling kernel â€” the u-term in the ranking is
            # align_force as WIRED at coupled_registry.py:287 (full phase list
            # [self, other], N=2 satisfies the mean-field guard; the self term
            # contributes sin(0)=0). The u-term is the signed attraction of the
            # step's phase toward the converged phase 0.0 â€” NOT a new formula.
            _align = align_force(_u, [_u, 0.0], k=1.0)
            # physics term normalized to [0, 1]: aligned (u>0, expanding toward
            # convergence) scores higher; anti-aligned (u<0, compressing) lower.
            _phys = 0.5 + 0.5 * max(-1.0, min(1.0, _align))
            _session = self.session_id or ""
            myc = getattr(self._memory_interface, "_mycelium", None)
            if myc is None:
                return []
            _store = getattr(myc, "_store", None)
            _nav = getattr(myc, "_navigator", None)
            _nodes = []
            # Primary candidate source: the highest-confidence node from each
            # space (navigate_all_spaces) â€” the relevant BRANCHES, one per
            # space. Fallback: active registry nodes.
            try:
                if _nav is not None and hasattr(_nav, "navigate_all_spaces"):
                    _nodes = list(_nav.navigate_all_spaces(_session))
            except Exception:
                _nodes = []
            if not _nodes:
                try:
                    _reg = getattr(myc, "_registry", None)
                    _nids = list(getattr(_reg, "get_active", lambda s: [])(_session))
                    if _nids and _store is not None:
                        _nodes = [
                            _store.get_node_by_id(_nid)
                            for _nid in _nids
                            if _store.get_node_by_id(_nid) is not None
                        ]
                except Exception:
                    _nodes = []
            _nodes = [_c for _c in (_nodes or []) if getattr(_c, "coordinates", None)]
            if not _nodes:
                return []

            _scored = []
            for _n in _nodes:
                try:
                    _coords = list(getattr(_n, "coordinates", None) or [])
                    if len(_coords) < 4:
                        continue
                    _d = sum((a - b) ** 2 for a, b in zip(_vec, _coords[:4])) ** 0.5
                    _prox = max(0.0, 1.0 - _d / 4.0)  # normalized proximity
                    _learned = 0.0
                    _nid = getattr(_n, "node_id", "") or getattr(_n, "id", "") or ""
                    # learned edge score from the region node -> candidate, if
                    # the edge exists (evidence-driven ranking).
                    try:
                        _reg_nid = self._der_region_node_id(_session)
                        if _reg_nid and _nid:
                            _edge = _store.get_edge_by_id(
                                f"{_reg_nid}:{_nid}"
                            ) if hasattr(_store, "get_edge_by_id") else None
                            if _edge is not None:
                                _learned = float(getattr(_edge, "score", 0.0) or 0.0)
                    except Exception:
                        _learned = 0.0
                    _score = _prox * 0.6 + _learned * 0.3 + _phys * 0.1
                    _scored.append({
                        "node_id": _nid,
                        "label": (getattr(_n, "label", None) or _nid)[:120],
                        "score": _score,
                    })
                except Exception:
                    continue
            _scored.sort(key=lambda c: c["score"], reverse=True)
            # REQ-5 AC5 (T17b): record the TOTAL number of relevant branches
            # found (BEFORE the cap) on the item â€” the coverage DENOMINATOR
            # for candidate-surfacing coverage ("how often a decision saw >=2
            # candidates when >=2 EXISTED"). candidates_surfaced is the capped
            # return; candidates_existed is the uncapped count. Both are needed
            # or the coverage metric cannot be measured.
            try:
                item._coupled_candidates_existed = len(_scored)
            except Exception:
                pass
            return _scored[:cap]
        except Exception as _cp_exc:  # noqa: BLE001 â€” coupling never blocks
            logger.debug("[DER] branch-candidate surfacing failed: %s", _cp_exc)
            return []

    def _der_region_node_id(self, session_id: str) -> str:
        """The mycelium node_id of the session's CURRENT region node (the ONE
        active node nearest the live Î£ position â€” REQ-26 AC1 region scoping).
        Empty string if none resolvable. Never raises."""
        try:
            myc = getattr(self._memory_interface, "_mycelium", None)
            if myc is None:
                return ""
            _reg = getattr(myc, "_registry", None)
            if _reg is None:
                return ""
            _nids = list(getattr(_reg, "get_active", lambda s: [])(session_id))
            if not _nids:
                return ""
            _store = getattr(myc, "_store", None)
            if _store is None or not hasattr(_store, "get_node_by_id"):
                return ""
            _cad = self._der_live_cad_state(session_id)
            _vec = [
                _cad.get("x", 0.0), _cad.get("y", 0.0),
                _cad.get("xi", 0.0), _cad.get("u", 0.0),
            ]
            _best, _best_d = "", None
            for _nid in _nids:
                try:
                    _n = _store.get_node_by_id(_nid)
                    if _n is None:
                        continue
                    _c = list(getattr(_n, "coordinates", None) or [])
                    if len(_c) < 4:
                        continue
                    _d = sum((a - b) ** 2 for a, b in zip(_vec, _c[:4])) ** 0.5
                    if _best_d is None or _d < _best_d:
                        _best, _best_d = _nid, _d
                except Exception:
                    continue
            return _best
        except Exception as _reg_exc:  # noqa: BLE001
            logger.debug("[DER] region-node resolve failed: %s", _reg_exc)
            return ""

    def _der_record_governance(self, source: str) -> None:
        """REQ-6 AC1/AC3 (T18): record WHICH signal governed a steering
        decision â€” past-memory | live-state | both.

        Increments the per-turn governance counter on the kernel (read by the
        caller's TurnMetrics block into the [LAYERS] line). Off the hot path
        and lossy-safe: any failure is logged at debug and never raises, and a
        missing counter silently re-initializes (AC1 edge: high-volume turns).
        The alternation ratio (AC3) is derived in TurnMetrics.to_log_line from
        the same counts.

        No decision path hardcodes which signal is authoritative (AC2): the
        recorded source is OBSERVED at the decision point â€” a step whose
        context carried a compressed node record (past-memory) AND live Î£ is
        "both"; memory-sparse (no record) is "live"; record present but no
        live signal is "past".
        """
        try:
            _gov = getattr(self, "_der_governance_counts", None)
            if _gov is None:
                _gov = {"past": 0, "live": 0, "both": 0}
            if source == "past":
                _gov["past"] = _gov.get("past", 0) + 1
            elif source == "live":
                _gov["live"] = _gov.get("live", 0) + 1
            else:  # "both" (and any unknown -> both, the equal-signals edge)
                _gov["both"] = _gov.get("both", 0) + 1
            self._der_governance_counts = _gov
        except Exception as _gov_exc:  # noqa: BLE001
            logger.debug("[DER] governance record failed: %s", _gov_exc)

    def _der_choose_coupling_branch(
        self, item, candidates: List[dict]
    ) -> str:
        """REQ-5 AC4 (T17): determine which surfaced branch the step CHOSE.

        Selection is the step's, not the system's (the rewritten REQ-5 story:
        "awareness of the alternatives, and a recorded decision, is [the
        system's business]"). The step's choice is observed from the outcome:
        the chosen branch is the candidate whose coordinates are nearest the
        step's final Î£ position (``coords_to``), i.e. the branch the step's
        result actually moved toward. Empty string when no candidate is
        nearest (no branches existed / no coords). Never raises.
        """
        from backend.agent.der_constants import DER_COUPLING_CANDIDATE_CAP

        if not candidates:
            return ""
        try:
            _coords_to = getattr(item, "coords_to", "") or ""
            _session = self.session_id or ""
            myc = getattr(self._memory_interface, "_mycelium", None)
            _store = getattr(myc, "_store", None) if myc else None
            if _coords_to and _store is not None and hasattr(
                _store, "get_node_by_id"
            ):
                _v = []
                for _part in _coords_to.strip("()").split(","):
                    try:
                        _v.append(float(_part))
                    except Exception:
                        break
                if len(_v) >= 4:
                    _best, _best_d = "", None
                    for _c in candidates[:DER_COUPLING_CANDIDATE_CAP]:
                        _nid = _c.get("node_id", "")
                        if not _nid:
                            continue
                        try:
                            _n = _store.get_node_by_id(_nid)
                            _cvec = list(getattr(_n, "coordinates", None) or [])
                            if len(_cvec) < 4:
                                continue
                            _d = sum(
                                (a - b) ** 2 for a, b in zip(_v, _cvec[:4])
                            ) ** 0.5
                            if _best_d is None or _d < _best_d:
                                _best, _best_d = _nid, _d
                        except Exception:
                            continue
                    return _best
            # No resolvable coordinates: fall back to the top-ranked candidate
            # (the ranking is physics- and evidence-driven, AC3) so a decision
            # is still RECORDED â€” an empty choice would be an unrecorded one.
            return (candidates[0].get("node_id", "") if candidates else "")
        except Exception as _ch_exc:  # noqa: BLE001
            logger.debug("[DER] coupling-branch choice failed: %s", _ch_exc)
            return ""

    def _der_record_coupling_decision(
        self,
        item,
        candidates: List[dict],
        chosen_node_id: str = "",
        record: Optional["NodeRecord"] = None,
    ) -> None:
        """REQ-5 AC2/AC4 (T17): record a coupling decision AFTER the step
        commits. ``candidates`` is the surfaced list (all of them, capped);
        ``chosen_node_id`` is the branch the step actually committed to.

        AC2: write/strengthen the coupling edge from the step's region node to
        the chosen branch â€” the decision IS the edge's provenance. Uses the
        SAME edge store/scorer as the region->mediator learning (one store,
        one scorer â€” REQ-19 AC4); a decision is a strengthenable observation,
        not a new edge kind.
        AC4: candidates_surfaced / chosen_branch / surfaced_branches are
        stamped on the node record so "was the agent aware of both branches"
        is answerable from data. Never raises: coupling is off the critical
        path (REQ-10 AC5).
        """
        from backend.agent.der_constants import DER_COUPLING_PROVENANCE_MAX

        try:
            _count = len(candidates or [])
            _chosen = chosen_node_id or ""
            if not _count and not _chosen:
                return  # no coupling decision at this node
            _rec = record or getattr(item, "node_record", None)
            if _rec is not None:
                _rec.candidates_surfaced = _count
                _rec.chosen_branch = _chosen
                # REQ-18 AC1b (T19): a node that SURFACED >=1 candidate and
                # CHOSE one is a node that COMMITTED A DECISION â€” a valid
                # coupling endpoint. This is the ROLE marker that makes
                # "which decisions were informed by branch X" a relationship
                # lookup (REQ-20) instead of a table scan. Set only here, at
                # the coupling-decision site, so gathering/executing nodes
                # stay unmarked.
                if _count > 0:
                    _rec.committed_decision = True
                _rec.surfaced_branches = [
                    c.get("label", "") for c in (candidates or [])
                ][:DER_COUPLING_PROVENANCE_MAX]
                # REQ-5 AC5 (T17b): the DENOMINATOR for candidate-surfacing
                # coverage â€” how many relevant branches EXISTED before the cap.
                # candidates_surfaced / candidates_existed is the coverage ratio
                # ("saw >=2 when >=2 existed").
                try:
                    _rec.candidates_existed = int(
                        getattr(item, "_coupled_candidates_existed", _count) or _count
                    )
                except Exception:
                    _rec.candidates_existed = _count
            if _chosen:
                try:
                    _session = self.session_id or ""
                    _reg_nid = self._der_region_node_id(_session)
                    if _reg_nid:
                        myc = getattr(self._memory_interface, "_mycelium", None)
                        _store = getattr(myc, "_store", None) if myc else None
                        if _store is not None and hasattr(
                            _store, "record_observation"
                        ) and hasattr(_store, "get_edge_by_id"):
                            _edge_id = f"{_reg_nid}:{_chosen}"
                            _existing = _store.get_edge_by_id(_edge_id)
                            if _existing is not None:
                                # decision PROVENANCE: the informed-branch edge
                                # is strengthened by a decision observation
                                # (REQ-5 AC2) â€” delta positive, modest.
                                _store.record_observation(_edge_id, 0.1)
                            elif hasattr(_store, "upsert_edge"):
                                _new_eid = _store.upsert_edge(
                                    _reg_nid, _chosen, "informed", 0.5
                                )
                                if _new_eid:
                                    _store.record_observation(
                                        _new_eid or _edge_id, 0.1
                                    )
                except Exception as _edge_exc:  # noqa: BLE001
                    logger.debug(
                        "[DER] coupling-edge write failed: %s", _edge_exc
                    )
        except Exception as _cd_exc:  # noqa: BLE001
            logger.debug("[DER] coupling-decision record failed: %s", _cd_exc)

    def _der_verify_strictness(self, u: float) -> str:
        """Adaptive verification strictness by |u| band (D2.3).

        |u| < U_SPLIT  -> "wide"   : step was split; children verified individually,
                                   parent collapses on child consensus (no LLM rubric).
        U_SPLIT..0.85  -> "rubric" : atomic step, mid-band -> deterministic stub-kill
                                   PLUS LLM rubric verdict (tier-3 empowered check).
        >= 0.85        -> "atomic" : converged -> deterministic verify only (no LLM
                                   rubric; cheap, deterministic).
        """
        from backend.agent.der_constants import U_SPLIT, U_CONVERGED

        au = abs(u)
        if au < U_SPLIT:
            return "wide"
        if au < U_CONVERGED:
            return "rubric"
        return "atomic"

    def _der_split_blocker(
        self,
        item: "QueueItem",
        trigger: str,
        step_result: str = "",
    ) -> str:
        """REQ-4 AC4 (T16b): name the SPECIFIC blocker this split resolves.

        Deterministic extraction from the failure evidence (no LLM call on the
        split hot path â€” the blocker is derived, not generated):

          1. error-prefixed step_result  -> the tool failure itself
          2. verify_failed               -> the acceptance criterion that was
             NOT satisfied (expected_output, else the produced result) â€” names
             the specific gap, never the parent goal
          3. unresolved_u (physics)      -> the oscillating state itself
             (decomposition, not a failure â€” still names WHAT it resolves)
          4. empty evidence AND no expected_output -> "" (UNNAMED blocker) â€”
             the split cannot name what it resolves; recorded as such via
             blocker_named=False, surfaced as evidence the failure was not
             understood.

        Returns the blocker text, or "" when nothing can be named.
        """
        _res = (step_result or "").strip()
        _low = _res.lower()
        if _low.startswith("error") or _low.startswith("[step error") or _low.startswith(
            "duplicate"
        ):
            return f"the tool reported: {_res[:200]}"
        if _low.startswith("ratelimited") or _low.startswith("timeout") or _low.startswith(
            "connection"
        ):
            return f"transient infrastructure failure: {_res[:200]}"
        if trigger == "verify_failed":
            _exp = (item.expected_output or "").strip()
            if _exp:
                return f"result did not satisfy expected output: {_exp[:200]}"
            if _res:
                return f"result was not verified against the expected output: {_res[:200]}"
            return ""  # UNNAMED â€” no expected output AND no evidence
        if trigger == "unresolved_u":
            return "unresolved oscillating state (|u| below the split threshold)"
        if _res:
            return f"the produced result was judged insufficient: {_res[:200]}"
        return ""

    def _split_step(
        self,
        item: "QueueItem",
        trigger: str,
        cad: Dict[str, float],
        work_units: int,
        step_result: str = "",
        verified_fraction: float = 0.0,
    ) -> List["QueueItem"]:
        """Stateful, physics-driven split operator (D2.1).

        Args:
            item:       step being split.
            trigger:    "unresolved_u" | "verify_failed".
            cad:        live Caducean state {x, y, xi, u, ...}.
            work_units: remaining unified termination budget (DER_WORK_UNITS_0
                        minus what has been prepaid). Split is PERMITTED only if
                        work_units >= width; split PREPAYS ``width`` units up
                        front (this is what makes the Lyapunov potential Phi
                        strictly decrease â€” see Appendix B).
            step_result: the failure evidence (produced result / error text).
                        REQ-4 AC4 (T16b): used to name the SPECIFIC blocker the
                        children exist to resolve â€” the child's objective_anchor
                        is NEVER a restatement of the parent goal.
            verified_fraction: REQ-4 AC1/AC2 (T16): the continuous verification
                        fraction of this step (0..1), consumed as a GRADED
                        steering input at the split decision. Mid-band
                        (0.25 < vf < 0.75) selects the bounded probe path
                        (width 1, probe=True) instead of a full-width
                        re-attempt; strong failure (< 0.25) lets |u| govern.
                        Default 0.0 preserves the pre-T16 binary behavior for
                        callers that do not have the fraction.

        Returns:
            List of child QueueItems (Sub-Loops that collapse back to the parent
            as one COMPRESS). Empty list => split refused, step forced atomic.
        """
        from backend.agent.der_constants import (
            DER_MAX_GRAFTS,
            MAX_DEPTH,
        )

        u = cad.get("u", 0.0)
        # REQ-4 AC1/AC2 (T16): the width is now a GRADED function of BOTH |u|
        # and the verified fraction â€” the continuous signal is a steering
        # input, not a post-hoc label. Mid-band -> bounded probe (width 1).
        width = self._der_split_width(u, verified_fraction)
        # Cap at DER_MAX_GRAFTS AND bounded by remaining work units.
        width = min(width, DER_MAX_GRAFTS, max(0, work_units))
        if width < 1 or item.depth_layer >= MAX_DEPTH:
            return []  # refused -> step forced atomic

        from backend.agent.der_loop import QueueItem, NodeRecord

        # REQ-4 AC2 (T16): a mid-band verified fraction selects the graded
        # middle path â€” a BOUNDED PROBE (width 1, probe=True), not a threshold
        # coin-flip. The child resolves the specific blocker at width 1.
        _probe = 0.25 < verified_fraction < 0.75 and trigger == "verify_failed"

        from backend.agent.der_loop import QueueItem, NodeRecord

        # REQ-4 AC4 (T16b): name the SPECIFIC blocker the split exists to
        # resolve â€” deterministically extracted from the failure evidence (no
        # LLM call on the split hot path). A split that cannot name what it
        # resolves records an UNNAMED blocker (blocker_named=False) â€” surfaced
        # as evidence the failure was not understood, never hidden behind a
        # fresh node id.
        _blocker = self._der_split_blocker(item, trigger, step_result)
        if _blocker:
            _child_anchor = f"RESOLVE: {_blocker}"
            _blocker_named = True
        else:
            _child_anchor = f"[UNNAMED_BLOCKER] {item.description[:160]}"
            _blocker_named = False
            logger.warning(
                "[DER] _split_step trigger=%s step=%s produced an UNNAMED "
                "blocker â€” the split cannot name what it resolves; recorded "
                "as evidence (REQ-4 AC4)",
                trigger, item.step_id,
            )

        # REQ-21 (T41): the compressed footprint each child carries â€”
        # Understanding (what has been attempted/gathered for this goal across
        # ALL prior attempts, bounded â€” never a truncated sample), Awareness
        # (the goal itself), Direction (remaining vs ruled-out), and a
        # coordinate_ref into the ledger/memory for the full prior evidence.
        # Bounded by construction: prior attempts are a deduplicated key set
        # (not per-tool-call transcripts), so cost does NOT grow linearly with
        # tool calls (AC2). Survives DCP pruning because it is durable
        # structured data on the child QueueItem (AC3).
        try:
            _prior_keys = sorted(
                set(getattr(self, "_der_crawl_attempts", {}).get(
                    self.conversation_id or self.session_id or "", set()
                ))
            )
            _prior_summary = (
                f"{len(_prior_keys)} prior gather attempt(s) committed for "
                f"this goal: {', '.join(_prior_keys[:5])}"
                + ("â€¦" if len(_prior_keys) > 5 else "")
            )
            _coordinate_ref = None
            try:
                _ledger = getattr(self, "_der_ledger", None)
                if _ledger is not None:
                    _coordinate_ref = getattr(_ledger, "conversation_id", None)
            except Exception:
                _coordinate_ref = None
        except Exception:
            _prior_summary = ""
            _prior_keys = []
            _coordinate_ref = None

        children: List["QueueItem"] = []
        # REQ-3 T8: capture the pre-split compressed position so every child's
        # NodeRecord carries the SAME coords_from (the branch point) and each
        # lands a distinct coords_to when it finalizes (REQ-2 chain append).
        _coords_before = ""
        try:
            _live = self._der_live_cad_state(self.session_id or "")
            if _live:
                _coords_before = f"({_live.get('x', 0.0):.4f},{_live.get('y', 0.0):.4f}," \
                                 f"{_live.get('xi', 0.0):.4f},{_live.get('u', 0.0):.4f})"
        except Exception:
            pass
        for i in range(width):
            child = QueueItem(
                step_id=f"{item.step_id}_s{i}",
                step_number=item.step_number,
                # REQ-4 AC4 (T16b): the child's description/objective names the
                # SPECIFIC blocker it resolves â€” NOT a restatement of the
                # parent goal. This is what makes a split a RESOLVE, not a
                # retry wearing a new node id.
                description=f"{_child_anchor} (sub {i + 1})",
                objective_anchor=_child_anchor,
                depth_layer=item.depth_layer + 1,
                expected_output=item.expected_output,
                is_subloop=True,  # collapses back to parent as one COMPRESS
                critical=item.critical,
                independent=True,  # T6.8: subloop children are independent per REQ-18 AC1
                # REQ-3 T8: EVERY node carries its memory record â€” the
                # generalized NodeRecord (was SubLoopFootprint, sub-loop-only).
                node_record=NodeRecord(
                    step_id=f"{item.step_id}_s{i}",
                    parent_step_id=item.step_id,
                    node_type="sub_loop",
                    objective_anchor=_child_anchor,
                    content_summary=_prior_summary,
                    prior_summary=_prior_summary,
                    expected_output=item.expected_output,
                    remaining=_child_anchor,
                    ruled_out="",  # no path is closed until a child proves it
                    coordinate_ref=_coordinate_ref,
                    coords_from=_coords_before,
                    blocker=_blocker,
                    blocker_named=_blocker_named,
                    probe=_probe,
                    # REQ-18 (T19): children INHERIT the parent's two domain
                    # axes â€” they are the same task (topic) run in the same
                    # winding (execution). Registry values by construction.
                    topic_domain=getattr(
                        getattr(item, "node_record", None), "topic_domain", "general"
                    ) or "general",
                    execution_domain=getattr(
                        getattr(item, "node_record", None),
                        "execution_domain",
                        "der",
                    ) or "der",
                    size_bytes=len(_prior_summary.encode("utf-8", "replace")),
                ),
            )
            children.append(child)
        logger.info(
            "[DER] _split_step trigger=%s u=%.2f width=%d depth=%d",
            trigger, u, width, item.depth_layer,
        )
        # Reset failure counters so Sub-Loops aren't penalized as parent continuation (REQ-12 AC3)
        try:
            if hasattr(self, "_get_tool_box"):
                self._get_tool_box().reset_failure_counters()
        except Exception:
            pass
        return children

    def _der_route_subloop_children(
        self, _children: List["QueueItem"], queue, _session: str, _turn_id: str
    ) -> None:
        """REQ-7 AC1/AC2/AC3 (T25): route split children through the batcher.

        Each ready group (full from ``offer()`` OR force-flushed at the join
        point) is dispatched as ONE batched call via ``dispatch_batch``, with
        results routed back per node. Guarantees:

        - AC1: children in a ready group share a single LLM call.
        - AC2: NO child is ever silently lost â€” full groups dispatch now,
          width-1/2 groups are force-flushed at the join point, and children
          the batcher declined (phase outside window / not independent) are
          queued directly. A child whose batched segment parsed is queued
          WITH its answer pre-seeded (item.result), so its execution
          short-circuits to the verify/finalize path; a child whose segment
          failed to parse is queued WITHOUT a result and executes individually.
        - AC3: each dispatched group increments the per-turn call counter
          (self._der_turn_calls), recorded against the T3 baseline.
        """
        from backend.agent.batch_dispatch import BatchGroup, dispatch_batch

        # Use the module-level `get_batcher` (imported above) â€” NOT a local
        # import â€” so tests that patch agent_kernel.get_batcher keep working.
        _batcher = get_batcher()
        _join = ""
        _ready: List[BatchGroup] = []
        for _c in _children:
            _g = _batcher.offer(_c)
            if _g is not None:
                _ready.append(_g)
            _sid = getattr(_c, "step_id", "")
            if not _join and _sid:
                _join = _sid.rsplit("_s", 1)[0] if "_s" in _sid else _sid
        # Force-flush the join point so a width-1/2 group (offer() returned
        # None because the group was not full) is ALSO dispatched now instead
        # of being silently dropped by the next flush_expired().
        _tail = _batcher.flush(_join) if _join else None
        if _tail is not None:
            _ready.append(_tail)
        _routed: set = set()
        for _g in _ready:
            _routed.update(
                self._der_dispatch_batch_group(_g, queue, _session, _turn_id)
            )
        # Children never grouped (declined / not independent) run individually.
        for _c in _children:
            if getattr(_c, "step_id", "") not in _routed:
                queue.add_item(_c)

    def _der_dispatch_batch_group(
        self, group, queue, _session: str, _turn_id: str
    ) -> set:
        """Execute one ready BatchGroup as a single batched call and route
        each child's answer back to its node. Returns the set of step_ids
        queued. AC3: each dispatched group increments the per-turn call
        counter."""
        from backend.agent.batch_dispatch import BatchGroup, dispatch_batch

        # Defensive: never iterate a non-BatchGroup. A patched/mocked batcher
        # (unit tests) may return an auto-created MagicMock from flush() â€”
        # treat it as "no group" so children fall through to the caller's
        # per-child fallback instead of crashing on a non-iterable group.
        if not isinstance(group, BatchGroup):
            return set()

        _queued: set = set()
        _results: dict = {}
        _router = getattr(self, "_router", None)
        if _router is not None:
            try:
                # REQ-1 AC2 / T25: route the batched call through the ROUTER's
                # role binding ("reasoning"), exactly like the per-step path
                # (box.resolve â†’ router.generate("reasoning")). Passing a model
                # STRING here is a real bug: router.generate's first arg is a
                # ROLE, so a model id fails resolve() and falls back to the
                # legacy default (provider='ollama') â€” observed live 2026-08-06:
                # "der_batch_dispatch failed: Ollama returned 500" while
                # per-step calls routed to cerebras. The role form makes the
                # batched call use the SAME bound provider as its siblings.
                _messages = self._der_batch_base_messages(_session)
                _results = (
                    dispatch_batch(group, _router, "reasoning", _messages) or {}
                )
                # D1: dispatch_batch() calls router.generate() directly with
                # this SAME router instance â€” credit its real (or, absent
                # that, estimated-from-combined-children) usage here.
                self._accrue_tokens(
                    " ".join(_results.values()) if _results else "",
                    getattr(_router, "last_usage", None),
                    source="_der_dispatch_batch_group",
                )
                # REQ-7 AC3 (T25): record the batched call against the
                # per-turn baseline so the loop shows call-count reduction.
                self._der_turn_calls = getattr(self, "_der_turn_calls", 0) + 1
            except Exception as _bexc:  # noqa: BLE001
                loud_error(_bexc, "der_batch_dispatch")
                _results = {}
        for _child in getattr(group, "children", None) or []:
            _sid = getattr(_child, "step_id", "")
            _res = (_results or {}).get(_sid, "")
            if _res and _res.strip():
                _child.result = _res.strip()  # pre-seed â†’ execution short-circuits
                logger.info(
                    "[DER] BATCH_ROUTED child=%s len=%d", _sid, len(_res)
                )
            else:
                logger.warning(
                    "[DER] BATCH_PARSE_FALLBACK child=%s -> individual", _sid
                )
            queue.add_item(_child)
            _queued.add(_sid)
        return _queued

    def _der_batch_base_messages(self, _session: str) -> list:
        """Base messages for a batched sub-loop call: the shared context each
        child would otherwise receive (system zone + working memory)."""
        _msgs = []
        try:
            _cp = ""
            if getattr(self, "_live_ctx", None) is not None and hasattr(
                self._live_ctx, "get_system_zone_content"
            ):
                _cp = self._live_ctx.get_system_zone_content() or ""
            _wm = ""
            if getattr(self, "_memory_interface", None) is not None:
                _wm = self._memory_interface.get_assembled_context(_session) or ""
            _sys = "\n\n".join(x for x in (_cp, _wm) if x).strip()
            if _sys:
                _msgs.append({"role": "system", "content": _sys})
        except Exception:
            pass
        if not _msgs:
            _msgs.append(
                {
                    "role": "system",
                    "content": "You are a precise sub-query executor.",
                }
            )
        return _msgs

    def _der_live_cad_state(self, session_id: str) -> Dict[str, float]:
        """Live Caducean state for the split decision (D2.2).

        Primary: ffi_caducean_get_state (live engine). Fallback: the trajectory
        recorder's last recorded coordinate (so a split can still be decided if
        the engine is unavailable). Never raises â€” returns zeros on total
        failure.
        """
        try:
            from backend.gateway.iris_ffi import ffi_caducean_get_state

            st = ffi_caducean_get_state(session_id) or {}
            if st:
                return {
                    "x": float(st.get("x", 0.0)),
                    "y": float(st.get("y", 0.0)),
                    "xi": float(st.get("xi", 0.0)),
                    "u": float(st.get("u", 0.0)),
                }
        except Exception as _e:
            logger.debug("[DER] live cad state unavailable: %s", _e)
        # Fallback: trajectory recorder's latest coordinate.
        try:
            from backend.agent.caducean_trajectory import (
                get_trajectory_recorder,
            )

            # REQ-20: bind to the APPLICATION store via MemoryInterface, never
            # to the BUILD-memory .mcm/coordinates.db fallback.
            rec = get_trajectory_recorder(self._memory_interface)
            coord = rec.get_latest_coordinate(session_id) or {}
            return {
                "x": float(coord.get("x", 0.0)),
                "y": float(coord.get("y", 0.0)),
                "xi": float(coord.get("xi", 0.0)),
                "u": float(coord.get("u", 0.0)),
            }
        except Exception:
            return {"x": 0.0, "y": 0.0, "xi": 0.0, "u": 0.0}

    def _der_graft_recovery_plan(
        self,
        objective: str,
        failed_item: "QueueItem",
        error_msg: str,
        _session: str,
    ) -> List["QueueItem"]:
        """
        Legacy recovery-subgraph helper (kept for the M.3.3 memory-aware
        recovery prompt tests). It asks the LLM for ALTERNATIVE recovery
        STEPS but returns them as GOALS ONLY (tool=None, params={}) so they
        resolve through the single resolver (explorer.propose) when executed.
        It must NOT assign tools directly â€” that would violate F6 / the
        System Invariant. The live critical-failure path routes through
        _split_step instead; this method is a goal-only fallback.
        Returns a list of QueueItem (recovery steps) or [] on any failure.
        Never raises.
        """
        import re as _re
        from backend.agent.der_loop import QueueItem

        try:
            # M.3.3 FIX: wire memory into recovery so the graft avoids
            # previously-failed approaches and can reuse proven ones.
            _failure_ctx = ""
            _success_ctx = ""
            _tools_block = ""
            try:
                if self._memory_interface:
                    _ep = self._memory_interface.episodic
                    _failures = _ep.retrieve_failures(
                        task=failed_item.description, limit=2
                    )
                    if _failures:
                        _failure_ctx = "\n".join(
                            f"  - AVOID: {f.get('task_summary', '')[:100]} "
                            f"(reason: {f.get('failure_reason', 'unknown')[:100]})"
                            for f in _failures
                        )
                    _successes = _ep.retrieve_similar(
                        task=failed_item.description, limit=2
                    )
                    if _successes:
                        _success_ctx = "\n".join(
                            f"  - ALTERNATIVE: {s.get('task_summary', '')[:100]} "
                            f"(tools: {' -> '.join(str(t.get('tool', '?')) for t in s.get('tool_sequence', [])[:4])})"
                            for s in _successes
                        )
            except Exception:
                pass  # never block recovery on memory failure
            try:
                from backend.agent.tool_registry import get_all_specs

                _specs = get_all_specs()
                if _specs:
                    _tools_block = "\n".join(
                        f"  - {s.name}" for s in _specs[:40]
                    )
            except Exception:
                pass

            prompt = (
                f"OBJECTIVE: {objective}\n"
                f"FAILED STEP: {failed_item.description}\n"
                f"TOOL: {failed_item.tool}\n"
                f"ERROR: {error_msg}\n\n"
            )
            if _failure_ctx:
                prompt += (
                    f"PAST FAILURES (do NOT repeat these approaches):\n"
                    f"{_failure_ctx}\n\n"
                )
            if _success_ctx:
                prompt += f"ALTERNATIVE PROVEN APPROACHES:\n{_success_ctx}\n\n"
            if _tools_block:
                prompt += f"AVAILABLE TOOLS:\n{_tools_block}\n\n"
            prompt += (
                "The execution of this step failed. Provide a JSON-only recovery "
                "sub-graph containing alternative step(s) to achieve the objective "
                "or gracefully handle the error.\n"
                'Respond with: {"steps": [{"step_id": "r1", "description": "...", '
                '"tool": "...", "params": {}, "depends_on": []}]}'
            )
            # Recovery planning is THINKING, not tool execution -> Brain (2026-08-16).
            _raw = self.infer(prompt, role="reasoning", max_tokens=400, temperature=0.2)
            _text = _raw.raw_text or ""
            _m = _re.search(r"\{[\s\S]+\}", _text)
            if not _m:
                return []
            _data = json.loads(_m.group())
            _steps: List["QueueItem"] = []
            for _rs in _data.get("steps", []):
                # GOALS ONLY: do NOT assign tool/params here. The single
                # resolver (explorer.propose) picks the tool when the step
                # executes (F6 / System Invariant). tool=None forces that path.
                _desc = str(_rs.get("description", ""))
                _steps.append(
                    QueueItem(
                        step_id=str(_rs.get("step_id", f"r{len(_steps) + 1}")),
                        step_number=900 + len(_steps),
                        description=_desc,
                        tool=None,
                        params={},
                        depends_on=list(_rs.get("depends_on", []) or []),
                        critical=bool(_rs.get("critical", True)),
                        parallel_safe=False,
                        objective_anchor=objective,
                    )
                )
            return _steps
        except Exception as _e:
            logger.warning("[DER] graft recovery parse failed: %s", _e)
            return []

    def _der_stamp_session_exit(self, natural_exit: bool) -> None:
        """REQ-16 AC2 (T32): stamp the session's exit nature on the
        conversation memory so ``archive_on_session_end`` records an HONEST
        ``natural_exit`` when the session ends (the DER loop is the source of
        truth for whether the task completed).

        Success path -> natural_exit=True (task ran to completion); failure /
        zero-step path -> natural_exit=False (task did NOT complete). Best-
        effort, off the hot path, never raises â€” a missing conversation memory
        is simply skipped.
        """
        try:
            _mem = getattr(self, "_conversation_memory", None)
            if _mem is not None:
                _mem.natural_exit = bool(natural_exit)
        except Exception:
            pass

    # Session 245 (synthesis starvation fix, conv-36 live finding): gather
    # tools whose ENTIRE purpose is delivering content (crawl / search /
    # read) need far larger evidence windows than generic tools. A 3-page
    # crawl compressed to 300-400 chars starves every downstream consumer —
    # the tool-decision model then honestly reports "unable to access the
    # search results" because no fragment it sees can answer the goal.
    _DER_GATHER_TOOLS = {
        "crawler_query", "web_search", "search", "fetch_url",
        "read_file", "browser_read",
    }

    @staticmethod
    def _der_evidence_cap(tool: Optional[str]) -> int:
        """Evidence window for a step result, by tool kind."""
        return 8000 if (tool or "").lower() in AgentKernel._DER_GATHER_TOOLS else 400

    @staticmethod
    def _smart_excerpt(text: str, cap: int) -> str:
        """Head+tail excerpt with an explicit truncation marker — never a
        silent amputation, never an unbounded dump."""
        t = (text or "").strip()
        if len(t) <= cap:
            return t
        _head = t[: int(cap * 0.7)]
        _tail = t[-int(cap * 0.3):]
        return f"{_head}\n[...excerpt: {len(t) - cap} chars truncated...]\n{_tail}"

    @staticmethod
    def _der_node_record_evidence(item) -> str:
        """REQ-8 AC1 (T26): compressed synthesis evidence from a node record.

        Session 245 ADDITION: GATHER-tool steps bypass the compression —
        their raw output IS the payload the synthesis must read, so a
        content_summary[:300] of a 3-page crawl guarantees the final answer
        starves. They get a bounded-but-generous raw window instead; every
        other tool keeps the compressed-record behavior unchanged. When the
        item carries no node_record (empty memory edge case, REQ-8), falls
        back to the raw result truncated to a bounded window so a step is
        never silent.
        """
        try:
            # Gather tools: raw payload window (head+tail), compression OFF.
            if (getattr(item, "tool", None) or "").lower() in AgentKernel._DER_GATHER_TOOLS:
                _raw_gather = getattr(item, "result", "") or ""
                if _raw_gather:
                    return AgentKernel._smart_excerpt(
                        _raw_gather, AgentKernel._der_evidence_cap(item.tool)
                    )
            _rec = getattr(item, "node_record", None) or getattr(
                item, "footprint", None
            )
            if _rec is not None:
                _parts = []
                _cs = getattr(_rec, "content_summary", "") or ""
                if _cs:
                    _parts.append(f"summary: {_cs[:300]}")
                _eo = getattr(_rec, "expected_output", "") or ""
                if _eo:
                    _parts.append(f"done-when: {_eo[:200]}")
                _rm = getattr(_rec, "remaining", "") or ""
                if _rm:
                    _parts.append(f"remaining: {_rm[:200]}")
                _ro = getattr(_rec, "ruled_out", "") or ""
                if _ro:
                    _parts.append(f"ruled-out: {_ro[:200]}")
                if _parts:
                    return " | ".join(_parts)
            # No node record â€” bounded raw fallback (REQ-8 edge case).
            _raw = getattr(item, "result", "") or ""
            if _raw:
                return _raw[:400]
        except Exception:
            pass
        return ""

    def _der_synthesize_outcome(
        self,
        plan,
        completed_items: list,
        queue,
        _session: str,
    ) -> str:
        """
        Phase 1.5: produce a friendly, user-facing summary when one or more
        steps failed. Explains what was accomplished, what failed, and what
        to do next. Returns "" on any failure (caller falls back to raw output).
        """
        try:
            # REQ-8 AC1 (T26): build the synthesis from COMPRESSED node records
            # (content summary / done-when / remaining / ruled-out), not the raw
            # step outputs. Keeps the final summary bounded and free of
            # interleaved tool noise, and avoids replaying raw history into the
            # model.
            _done = "\n".join(
                f"[Step {ci.step_number}] {ci.description}: "
                f"{self._der_node_record_evidence(ci) or '(no result)'}"
                for ci in completed_items
            ) or "(none)"
            _failed_lines = []
            for _fi in queue.failed_ids:
                _desc = _fi
                for _it in queue.items:
                    if _it.step_id == _fi:
                        _desc = _it.description or _fi
                        break
                _failed_lines.append(f"- {_desc}")
            _failed = "\n".join(_failed_lines) or "(none)"
            _prompt = (
                f"USER TASK: {plan.original_task}\n\n"
                f"STEPS EXECUTED:\n{_done}\n\n"
                f"STEPS THAT FAILED:\n{_failed}\n\n"
                "Provide a friendly, user-facing summary of what was accomplished, "
                "what failed, and what to do next.\n\n"
                + _READABLE_FORMAT_RULES
            )
            # The user-facing outcome summary is THINKING -> Brain (2026-08-16).
            _res = self.infer(_prompt, role="reasoning",
                              max_tokens=self.response_max_tokens(floor=400),
                              temperature=self.response_temperature())
            return _res.raw_text or ""
        except Exception as _e:
            logger.warning("[DER] outcome synthesis failed: %s", _e)
            return ""

    def _der_synthesize_success_outcome(
        self,
        plan,
        completed_items: list,
        queue,
        _session: str,
    ) -> str:
        """
        REQ-12 (AC1/AC2/AC3): success-path synthesis.

        Consumes the SAME evidence the failure path (``_der_synthesize_outcome``)
        consumes â€” ``plan.original_task`` plus each completed step's description
        and result â€” and routes it through the previously-dead
        ``_synthesize_response`` brain synthesis (AC3 wiring), which handles the
        InferenceRouter, LM Studio, and Ollama providers. Returns "" when
        synthesis is unavailable so the caller falls back to the deterministic
        success summary (AC4). Mirrors ``_der_synthesize_outcome``'s "" contract.
        """
        # Session 245 (verb progression): announce the SYNTH phase so the
        # working step's verb leaves SEARCH and shows SYNTH while the answer
        # is being composed — previously synthesis was invisible on the card.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.TASK_PROGRESS,
                data={
                    "description": "Synthesizing answer",
                    "action": "Synthesizing",
                    "update_step": True,
                    "detail": "Synthesizing answer",
                    "detail_progress": "",
                    "phase": "synthesizing",
                    "phase_sequence": 90,
                },
                session_id=_session,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass  # never block synthesis on an emit failure
        try:
            _step_results = [
                {
                    "tool": getattr(ci, "tool", None),
                    "action": getattr(ci, "description", ""),
                    # REQ-8 AC1 (T26): compressed node-record evidence instead of
                    # the raw step output. The brain synthesis reads the bounded
                    # memory record, never the full raw history.
                    "result": self._der_node_record_evidence(ci) or "",
                    "success": True,
                }
                for ci in completed_items
            ]
            _task = TaskContext(
                task_id=_session,
                user_message=plan.original_task,
                session_id=_session,
                conversation_history=[],
                plan={"original_task": getattr(plan, "original_task", "")},
                step_results=_step_results,
            )
            _syn = self._synthesize_response(_task, _step_results)
            if _syn and _syn.strip():
                logger.info(
                    "[DER] success synthesis ran (REQ-12 AC1) â€” steps=%d",
                    len(completed_items),
                )
                return _syn.strip()
            return ""
        except Exception as _e:
            logger.warning("[DER] success synthesis failed: %s", _e)
            return ""

    @staticmethod
    def _der_deterministic_failure_summary(plan, completed_items: list, queue) -> str:
        """User-facing 'task incomplete' message that needs NO LLM call (Part B).

        ``_der_synthesize_outcome`` relies on ``infer()`` to write the summary.
        When the model is rate-limited/unavailable â€” the exact failure that
        triggered the research step's failure â€” that synthesis returns "" and the
        user is left with silence. This deterministic fallback guarantees the
        user always gets a clear "I couldn't complete X â€” these steps failed
        (and why)" message even if the LLM is down.
        """
        try:
            _failed = []
            for _fi in queue.failed_ids:
                _desc = _fi
                _reason = ""
                for _it in queue.items:
                    if _it.step_id == _fi:
                        _desc = _it.description or _fi
                        # REQ-8 AC1 (T26): compressed node-record evidence, not raw.
                        _reason = AgentKernel._der_node_record_evidence(_it)
                        break
                _failed.append(f"- {_desc}" + (f": {_reason}" if _reason else ""))
            _failed_txt = "\n".join(_failed) or "(unknown step)"
            _done = len(completed_items)
            _total = len(getattr(plan, "steps", []) or [])
            return (
                f"I couldn't complete that task. {_done}/{_total} steps finished, "
                f"but the following step(s) failed:\n{_failed_txt}\n\n"
                f"If a search or source failed, try rephrasing the request or "
                f"pasting the information directly â€” I can continue from where it stopped."
            )
        except Exception as _e:
            logger.warning("[DER] deterministic failure summary failed: %s", _e)
            return (
                "I couldn't complete that task â€” one or more steps failed. "
                "Please try again or rephrase the request."
            )

    @staticmethod
    def _der_deterministic_success_summary(plan, completed_items: list, queue) -> str:
        """User-facing 'task complete' message that needs NO LLM call (REQ-12 AC4).

        Mirrors ``_der_deterministic_failure_summary``: when the brain synthesis
        is unavailable (no reasoning model / providers down), this deterministic
        summary guarantees the user gets a clear statement of what was completed
        â€” never a silent raw concatenation of step outputs.
        """
        try:
            _done_lines = []
            for _ci in completed_items:
                # REQ-8 AC1 (T26): compressed node-record evidence, not raw.
                _res = AgentKernel._der_node_record_evidence(_ci)
                _done_lines.append(
                    f"- {getattr(_ci, 'description', '') or _ci}"
                    + (f": {_res}" if _res else "")
                )
            _done_txt = "\n".join(_done_lines) or "(no step output)"
            _done = len(completed_items)
            _total = len(getattr(plan, "steps", []) or [])
            return (
                f"I've completed the task. {_done}/{_total} steps finished.\n"
                f"{_done_txt}\n\n"
                f"What would you like to do next?"
            )
        except Exception as _e:
            logger.warning("[DER] deterministic success summary failed: %s", _e)
            return "I've completed that task. What would you like to do next?"

    # â”€â”€ Phase 2.2: context-aware query refinement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _der_query_has_reference(query: str) -> bool:
        """Heuristic: does the search query contain an ambiguous reference that
        needs the conversation history to resolve?"""
        import re as _re

        _q = query or ""
        _ref_re = _re.compile(
            r"\b(it|its|they|them|those|that|this|the same|above|earlier|"
            r"previous|mentioned|same)\b",
            _re.IGNORECASE,
        )
        if _ref_re.search(_q):
            return True
        _ql = _q.lower()
        return any(
            _p in _ql
            for _p in (
                "pricing of", "price of", "cost of", "the pricing",
                "the price", "the cost", "do the", "the websearch",
                "the search", "what we",
            )
        )

    def _der_refine_query(self, query: str, _session: str) -> str:
        """
        Phase 2.2: resolve ambiguous references in a search query against the
        full conversation history via a quick LLM call. Returns the refined
        query, or the original on any failure / no change.
        """
        try:
            _history = []
            if self._conversation_memory is not None:
                _history = self._conversation_memory.get_context()
            if not _history:
                return query
            _history_str = "\n".join(
                f"{(m.get('role') or 'user').upper()}: {m.get('content') or ''}"
                for m in _history
            )
            _refine_prompt = (
                "CONVERSATION HISTORY (FULL):\n"
                f"{_history_str}\n\n"
                f"CURRENT QUERY: {query}\n\n"
                "Rewrite the search query to resolve any ambiguous pronouns or "
                "references based on the full conversation history. Output the "
                "query string only."
            )
            _refined = self.infer(
                _refine_prompt, role="reasoning", max_tokens=30, temperature=0.0
            )
            _out = (_refined.raw_text or "").strip().strip('"').strip()
            if _out and _out.lower() != query.lower():
                logger.info("[DER] refined query %r -> %r", query, _out)
                return _out
        except Exception as _e:
            logger.debug("[DER] query refinement failed: %s", _e)
        return query

    @staticmethod
    def _format_tool_result(raw) -> str:
        """Phase 4b: normalize a raw tool-bridge result into clean text for
        downstream consumption (dependent steps, working memory, final answer).

        - strings pass through unchanged
        - dicts: surface errors explicitly; otherwise extract the most useful
          content key (result/results/content/output/text/data/response);
          fall back to compact JSON for unrecognized dicts / lists
        - never raises; any failure falls back to str(raw)

        Note: the full structured result is still captured verbatim by
        _capture_tool_result (document store) â€” this only shapes the textual
        flow, so nothing is lost for later reformatting.
        """
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            try:
                if raw.get("success") is False:
                    _err = raw.get("error") or raw.get("message") or "unknown error"
                    return (
                        _err
                        if isinstance(_err, str)
                        else json.dumps(_err, ensure_ascii=False, default=str)
                    )
                for _key in (
                    "result", "results", "content", "output",
                    "text", "data", "response",
                ):
                    _val = raw.get(_key)
                    if _val is None:
                        continue
                    if isinstance(_val, str):
                        return _val
                    return json.dumps(_val, ensure_ascii=False, default=str)
                return json.dumps(raw, ensure_ascii=False, default=str)
            except Exception:
                return str(raw)
        try:
            return json.dumps(raw, ensure_ascii=False, default=str)
        except Exception:
            return str(raw)

    @staticmethod
    def _supportive_text(text: str, max_chars: int = 200) -> str:
        """First-sentence excerpt for the supportive spoken/chat bubble.

        The prism card carries the FULL synthesized document; the text/speech
        response is a short complement (first 1-2 sentences, ~max_chars) so the
        bubble and the card never duplicate each other (user contract
        2026-07-31: text supports the rendered document). Strips markdown
        decorations lightly. Returns '' when nothing usable remains.
        """
        _t = (text or "").strip()
        if not _t:
            return ""
        # Light markdown strip for a clean spoken excerpt.
        _t = re.sub(r"```[\s\S]*?```", " ", _t)
        _t = re.sub(r"^#{1,6}\s*", "", _t, flags=re.MULTILINE)
        _t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", _t)  # images
        _t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", _t)  # links -> label
        _t = re.sub(r"[*_`>|]", " ", _t)
        _t = re.sub(r"\s+", " ", _t).strip()
        if not _t:
            return ""
        _parts = re.split(r"(?<=[.!?])\s+", _t)
        _out = ""
        for _p in _parts:
            if _out and len(_out) + len(_p) > max_chars:
                break
            _out = (_out + " " + _p).strip()
            if len(_out) >= max_chars * 0.7:
                break
        if not _out:
            _out = _t[:max_chars]
        if len(_out) > max_chars:
            _out = _out[:max_chars].rstrip() + "â€¦"
        return _out

    @staticmethod
    def _caducean_modulate_temperature(base: float, session_id: str) -> float:
        """Phase 5: modulate planning temperature by the live Caducean recommendation.

        REQ-19 vocabulary: "COMPRESS"/"EXPAND"/"MAINTAIN" here are DER PHYSICS
        RECOMMENDATION CODES (ints 1/0/2) returned by ffi_caducean_recommend.
        They modulate temperature ONLY â€” they compact/expand NOTHING. Actual
        compaction is DCP message pruning (dcp.py) and mycelium condense/expand
        (scorer.py); Step Expansion is _growth_width->_split_step. See the
        REQ-19 vocabulary table in specs/long-horizon-der-execution/design.md.

        - COMPRESS (rec==1) -> more deterministic (temperature halved)
        - EXPAND   (rec==0) -> more exploratory (temperature *1.2, capped at 0.6)
        - MAINTAIN (rec==2) / unknown / TOPO_VIOLATION -> base unchanged

        Pure function of (base, session_id); never raises â€” returns ``base`` on
        any error so planning always proceeds.
        """
        try:
            from backend.gateway.iris_ffi import ffi_caducean_recommend

            _rec = ffi_caducean_recommend(session_id)
            if _rec == 1:  # COMPRESS
                return max(0.0, base * 0.5)
            if _rec == 0:  # EXPAND
                return min(0.6, base * 1.2)
        except Exception:
            pass
        return base

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

            # Phase 1 (D1.6): inject the memory-coupled evidence block so the
            # acting prompt is conditioned on proven paths / failures / state.
            evidence_str = ""
            try:
                from backend.agent.evidence import assemble_evidence

                _mi = getattr(self, "_memory_interface", None)
                _myc = getattr(_mi, "_mycelium", None) if _mi is not None else None
                _task_class = getattr(self, "_der_task_class", "full") or "full"
                _completed = list(getattr(self, "_der_completed_tools", []) or [])
                evidence_str = assemble_evidence(
                    goal=item.description or item.objective_anchor or "",
                    session_id=session_id,
                    myc=_myc,
                    completed_tools=_completed,
                    task_class=_task_class,
                    memory_interface=self._memory_interface,
                )
            except Exception as _ev_err:
                logger.debug("[DER] evidence build failed: %s", _ev_err)

            prompt = (
                f"{cp_str}\n\n"
                + (f"SESSION FINDINGS SO FAR:\n{wm_str}\n\n" if wm_str else "")
                + (f"{evidence_str}\n\n" if evidence_str else "")
                + f"OBJECTIVE: {item.objective_anchor}\n"
                f"STEP {item.step_number}: {item.description}\n\n"
                "Complete this step. Respond with the result only."
            ).strip()
            # THINKING RUNS ON THE BRAIN (2026-08-16). This is the tool-less
            # step path â€” there is no tool to execute, only reasoning â€” so it
            # belongs to the reasoning binding. It used to run on
            # role="EXECUTION" (the tool_execution binding), which meant that
            # with Brain and Tool on different models the actual thinking was
            # done by whichever model the user picked for TOOLS. The Tool model
            # executes tools; it does not think.
            result = self.infer(
                prompt, role="reasoning", max_tokens=512, temperature=0.3
            )
            return result.raw_text or f"[step {item.step_number} completed]"
        except Exception as _e:
            return f"[step {item.step_number} error: {_e}]"

    # â”€â”€ ToolDecisionBox lazy factory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # pin_517dfcbda150 â€” physics-driven web-gather sanction:
    #   _MAX_CRAWLS_PER_TASK  hard budget of DISTINCT queries per task; the
    #                         agent may gather more only by refining the query
    #                         (new hash = new job). Same-query repeats resolve
    #                         to the JobRegistry cache (tool_bridge dedupe).
    #   _GATHER_MIN_AMP       phase-manager amplitude floor: when oscillators
    #                         have collapsed (provider under load, amp relaxes
    #                         toward 1 - load_fraction) new crawls are denied
    #                         and web intent resolves to synthesis (REASON).
    _MAX_CRAWLS_PER_TASK = 3
    _GATHER_MIN_AMP = 0.35

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
                from backend.agent.explorer import _pheromone_top1, _is_web_intent

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
                # (SubLoopBatcher) run under the placeholder session
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
                    _is_web_goal = bool(_is_web_intent(goal))
                except Exception:  # noqa: BLE001
                    pass
                _veto_reason: Optional[str] = None
                if _is_web_goal:
                    # Explicit resource bound (REQ-3 AC3): a FRESH distinct web
                    # query beyond the per-task crawl budget is vetoed. Same-key
                    # repeats skip the budget (cache-served, read-only).
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

                # Web-intent â†’ crawler_query (capability-gated, not a silent fallback)
                if _is_web_goal:
                    _crawl_state = dict(_crawl_state)
                    _crawl_state[_g_session] = _attempted | {_qkey}
                    self._der_crawl_attempts = _crawl_state

                    from backend.agent.tool_registry import resolve_tool, capability_allowed
                    spec = resolve_tool("crawler_query")
                    if spec and capability_allowed(spec):
                        params: Dict[str, Any] = {"query": goal}
                        # Consult SourceRegistry for known URLs (learned knowledge)
                        try:
                            from backend.crawler.source_registry import get_source_registry
                            import asyncio as _asyncio
                            sr = get_source_registry()
                            # quick=True: no LLM topic-extraction on the gate's
                            # hot path (per-step resolution would otherwise burn
                            # a quota slot + up to 40s per call).
                            sr_result = _asyncio.run(sr.resolve(goal, quick=True))
                            if sr_result.get("hit") and sr_result.get("sources"):
                                known_urls = [
                                    s["url"] for s in sr_result["sources"]
                                    if isinstance(s, dict) and "url" in s
                                ][:3]
                                if known_urls:
                                    params["known_urls"] = known_urls
                        except Exception:
                            pass  # SourceRegistry failure is non-fatal
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
                    if _attempted and not _is_web_goal and any(
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

        self._tool_box = ToolDecisionBox(
            router=self._router,
            tool_bridge=self._tool_bridge,
            get_available_tools=get_registry_tools,
            validate_tool_call=validate_tool_call,
            infer_fn=self.infer,
            memory_lookup_fn=_mem_lookup,
        )
        return self._tool_box

    # â”€â”€ Phase 4: concurrent step execution helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _der_run_step_execution(
        self,
        item: "QueueItem",
        context_package,
        _session: str,
        _turn_id: Optional[str],
        plan,
        queue=None,
    ) -> tuple:
        """
        Phase 4: execute a single DER step's tool/direct action.
        Returns (step_result: str, step_success: bool).
        Faithful extraction of the inline execution block from _execute_plan_der.

        Session 245 (synthesis starvation fix): ``queue`` joins the signature
        so the tool-decision evidence for tool-less steps can carry PRIOR
        completed step results — previously the evidence was metadata-only
        (session/turn/task_class), so a synthesis step after a successful
        crawl was decided by a model that had never seen a byte of the crawl
        output ("I am unable to access the search results", conv-36).
        """
        # REQ-7 AC1 (T25): a batched sub-loop child already carries its answer
        # (pre-seeded by _der_dispatch_batch_group via dispatch_batch). Skip
        # the per-child resolve + LLM call; verification/finalize still run
        # below so each child still credits its own mediator (REQ-26 edge).
        if getattr(item, "is_subloop", False) and getattr(item, "result", None):
            return item.result, True
        step_result = ""
        step_success = True
        try:
            # ── Session 245: prior completed step results for the decision
            # evidence (Seam A of the synthesis starvation fix). Bounded per
            # result by tool-aware caps; steps without results are skipped.
            _prior_results: list = []
            if queue is not None:
                try:
                    for _pit in queue.items:
                        if _pit is item:
                            continue
                        _pr = getattr(_pit, "result", None)
                        if not _pr:
                            continue
                        _prior_results.append(
                            {
                                "step": getattr(_pit, "step_number", None),
                                "description": (getattr(_pit, "description", "") or "")[:120],
                                "result": self._smart_excerpt(
                                    _pr,
                                    self._der_evidence_cap(getattr(_pit, "tool", None)),
                                ),
                            }
                        )
                except Exception as _prio_err:
                    logger.debug("[DER] prior-result gather failed: %s", _prio_err)

            # ── Phase 1 (D1.6): resolve via ToolDecisionBox ─────────────
            if not item.tool:
                try:
                    _box = self._get_tool_box()
                    _evidence = {
                        "session_id": _session,
                        "turn_id": _turn_id,
                        "task_class": getattr(self, "_der_task_class", "full"),
                    }
                    if _prior_results:
                        _evidence["prior_step_results"] = _prior_results
                    _decision = _box.resolve(
                        step={
                            "description": item.description or item.objective_anchor or "",
                            "step_number": item.step_number,
                        },
                        evidence=_evidence,
                        session_id=_session,
                        conversation_id=self.conversation_id,
                    )
                    # D1: ToolDecisionBox.resolve() calls self._router.generate()
                    # directly (it shares this kernel's router instance), so its
                    # cost must be credited here â€” it is the DOMINANT call site
                    # for a real multi-step DER turn and was previously invisible
                    # to the pill entirely.
                    self._accrue_tokens(
                        getattr(_decision, "rationale", "") or "",
                        getattr(self._router, "last_usage", None),
                        source="_der_run_step_execution:box.resolve",
                    )
                except Exception as _box_err:
                    logger.warning(
                        "[DER] box.resolve crashed for step %d: %s",
                        item.step_number, _box_err,
                    )
                    step_success = False
                    step_result = f"[STEP ERROR: tool resolution crashed â€” {_box_err}]"
                    return step_result, step_success

                if _decision.kind == DecisionKind.FAIL:
                    # FAIL â†’ route to DER recovery (graft / escalate REQ-10)
                    step_success = False
                    step_result = f"[STEP ERROR: tool resolution failed â€” {_decision.error}]"
                    return step_result, step_success

                if _decision.kind == DecisionKind.TOOL:
                    item.tool = _decision.tool
                    item.params = _decision.params
                    logger.info(
                        "[DER] box resolved tool=%r for step %d (source=%s)",
                        item.tool, item.step_number, _decision.source,
                    )
                    # pin_517dfcbda150: re-emit TOOL_CALL with the RESOLVED
                    # tool name. The loop's earlier emit (before execution)
                    # carries the planner's guess or "direct"; the frontend's
                    # useTaskProgress takes the LAST tool:call per step, so
                    # the card now shows "WebCrawl" instead of "Tool".
                    try:
                        from backend.agent.event_bus import (
                            get_event_bus,
                            IRISStreamEvent,
                        )

                        _lifecycle_task_id = _turn_id or item.step_id
                        get_event_bus().emit(
                            IRISStreamEvent.TOOL_CALL,
                            data={
                                "task_id": _lifecycle_task_id,
                                "tool_name": item.tool or "direct",
                                "description": (
                                    item.description
                                    or item.objective_anchor
                                    or ""
                                )[:200],
                                "params": item.params or {},
                                "step_number": item.step_number,
                                # REQ-3 AC6 (T2): card_id stays stable across
                                # every event of a card's lifetime.
                                **self._card_envelope(_lifecycle_task_id),
                            },
                            turn_id=_turn_id,
                            conversation_id=self.conversation_id,
                        )
                    except Exception:
                        pass  # never block execution on an emit failure
                # REASON: item.tool stays None â†’ falls to _run_step_direct below

            # â”€â”€ Phase 2: dispatch (TOOL) or direct (REASON) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Set the phase gate call class so the gate knows whether to wait
            # (REASON/TOOL â†’ gated) or admit immediately (USER_TURN/SPEAK) (T3.7).
            # GRAFT is NOT high-priority (T6.4) â€” recovery-plan generation after
            # a step failure (including 429) must be gated to avoid amplification.
            if item.tool:
                set_call_class(CallClass.TOOL)
            else:
                set_call_class(CallClass.REASON)

            if item.tool and self._tool_bridge is not None:
                # Trust-routing W2: mark external for web/crawler tools
                self.mark_external_tool(item.tool)
                # pin_42ddd255162d: render tools need the conversation registry
                # on the bridge; DER paths never received it.
                try:
                    self._tool_bridge._active_conversation_id[_session] = (
                        self.conversation_id or ""
                    )
                except Exception:
                    pass
                try:
                    _dr = self._get_tool_box().dispatch(
                        Decision(
                            kind=DecisionKind.TOOL,
                            tool=item.tool,
                            params=item.params,
                        ),
                        session_id=_session,
                        conversation_id=self.conversation_id,
                        turn_id=_turn_id,
                    )
                    # pin_42ddd255162d: dispatch-time gather sanction â€” the
                    # resolution-time record (in _mem_lookup) was unreliable
                    # (attempted=0 on every gate read), so the per-task crawl
                    # budget never engaged. The dispatch runs for EVERY crawl
                    # (real or dedupe-hit), so record the query hash here:
                    # guaranteed bookkeeping for the budget/veto.
                    if item.tool in self._WEB_CONTENT_TOOLS and self.conversation_id:
                        try:
                            from backend.agent.der_execution_ledger import make_action_key

                            _cs = dict(getattr(self, "_der_crawl_attempts", {}))
                            # D2: same stable action key as the gather gate.
                            _gq = make_action_key(item.description or item.tool)
                            _cs[self.conversation_id] = _cs.get(
                                self.conversation_id, set()
                            ) | {_gq}
                            self._der_crawl_attempts = _cs
                        except Exception:
                            pass
                except RuntimeError as _rte:
                    # asyncio.run() inside box may fail if an event loop is
                    # already running in this thread â€” executor fallback
                    logger.warning(
                        "[DER] box.dispatch RuntimeError for %s: %s â€” using executor",
                        item.tool, _rte,
                    )
                    import concurrent.futures as _cf
                    import asyncio as _asyncio

                    with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                        _raw_dr = _pool.submit(
                            _asyncio.run,
                            self._tool_bridge.execute_tool(
                                tool_name=item.tool,
                                params=item.params,
                                session_id=_session,
                                plan_title=plan.plan_title if plan else "",
                            ),
                        ).result(timeout=60)
                        _dr = DispatchResult(
                            success=isinstance(_raw_dr, dict) and _raw_dr.get("success") is not False,
                            result=_raw_dr,
                        )
                # â”€â”€ Record tool call for ToolCallTree (REQ-13) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                if _dr:
                    try:
                        _step_id = str(getattr(item, "step_id", "")) or ""
                        _parent_id = str(getattr(item, "parent_step_id", "")) or None
                        _depth = int(getattr(item, "depth_layer", 0)) or 0
                        _hash = hashlib.md5(
                            str(item.params).encode()
                        ).hexdigest()[:12]
                        _result_str = str(getattr(_dr, "result", ""))[:200] or str(getattr(_dr, "error", ""))[:200]
                        self._get_tool_box().record_tool_call(
                            step_id=_step_id,
                            tool=item.tool,
                            args_hash=_hash,
                            result_summary=_result_str,
                            error_type=getattr(_dr, "error_type", None),
                            source="tool",
                            split_depth=_depth,
                            parent_step_id=_parent_id,
                        )
                    except Exception as _rc_err:
                        logger.warning("[DER] record_tool_call failed: %s", _rc_err)
                step_result = self._format_tool_result(
                    getattr(_dr, "result", None)
                ) if _dr else ""
                if _dr and not _dr.success:
                    step_success = False
                # W9 (O3): capture structured tool results
                if item.tool and _dr and _dr.result is not None:
                    try:
                        self._capture_tool_result(
                            item.tool, _dr.result,
                            self.conversation_id, _turn_id, _session,
                        )
                    except Exception as _cap_err:
                        logger.warning(
                            "[DER] tool-result capture failed: %s", _cap_err,
                        )
            else:
                # REASON (no tool) or no tool_bridge â€” direct reasoning
                step_result = self._run_step_direct(item, context_package, _session)
        except RateLimitedError:
            # Propagate rate-limit failures untouched so the DER layer can
            # record them honestly (REQ-3 AC4 / REQ-4 AC2). Do NOT wrap in a
            # string â€” the structured provider_id / retry_after fields are
            # needed by the ledger.
            raise
        except Exception as _ex_err:
            step_success = False
            step_result = f"[STEP ERROR: {_ex_err}]"
            logger.warning(
                f"[DER] Step {item.step_number} explorer error: {_ex_err}"
            )
        return step_result, step_success

    async def _der_run_step_execution_async(
        self,
        item: "QueueItem",
        context_package,
        _session: str,
        _turn_id: Optional[str],
        plan,
    ) -> tuple:
        """
        Phase 4: async variant of _der_run_step_execution for concurrent gather.
        Awaits execute_tool directly (no nested asyncio.run). Returns
        (step_id, step_result, step_success).
        """
        step_result = ""
        step_success = True
        try:
            if item.tool and self._tool_bridge is not None:
                # pin_42ddd255162d: render tools need the conversation
                # registry on the bridge; DER paths never received it.
                try:
                    self._tool_bridge._active_conversation_id[_session] = (
                        self.conversation_id or ""
                    )
                except Exception:
                    pass
                self.mark_external_tool(item.tool)
                raw = await self._tool_bridge.execute_tool(
                    tool_name=item.tool,
                    params=item.params,
                    session_id=_session,
                    plan_title=plan.plan_title if plan else "",
                )
                step_result = self._format_tool_result(raw) if raw is not None else ""
                if isinstance(raw, dict) and raw.get("success") is False:
                    step_success = False
                # REQ-18 AC5 (T31): correlate every browser navigation with its
                # target surface (in-app for the T27-routed tools) + job_id/HAR.
                if item.tool in ("open_url", "search", "web_search"):
                    try:
                        from backend.agent.der_trace import get_der_trace

                        _nav = raw if isinstance(raw, dict) else {}
                        # T13 (REQ-18 AC5): discriminator â€” a job_id means the
                        # page was crawled and is served from the CAPTURE
                        # REPLAY endpoint; without one the panel must fall back
                        # to the live PROXY. Both paths surface=in-app; the
                        # discriminator is what separates replay evidence from
                        # live fetch.
                        _via = "replay" if _nav.get("job_id") else "proxy"
                        get_der_trace(self._der_trace_task_id()).record(
                            "navigation",
                            tool=item.tool,
                            surface="in-app",
                            via=_via,
                            url=(
                                _nav.get("url") or _nav.get("query")
                                or (item.params or {}).get("url", "")
                            ),
                            job_id=_nav.get("job_id"),
                            har_path=_nav.get("har_path"),
                        )
                    except Exception:
                        pass
                if item.tool and raw is not None:
                    try:
                        self._capture_tool_result(
                            item.tool, raw, self.conversation_id, _turn_id, _session
                        )
                    except Exception as _cap_err:
                        logger.warning(
                            "[DER] tool-result capture failed: %s", _cap_err
                        )
            else:
                loop = asyncio.get_event_loop()
                step_result = await loop.run_in_executor(
                    None, self._run_step_direct, item, context_package, _session
                )
        except Exception as _ex_err:
            step_success = False
            step_result = f"[STEP ERROR: {_ex_err}]"
            logger.warning(
                f"[DER] Step {item.step_number} explorer error: {_ex_err}"
            )
        return item.step_id, step_result, step_success

    async def _der_exec_steps_concurrent(
        self,
        items: list,
        context_package,
        _session: str,
        _turn_id: Optional[str],
        plan,
    ) -> dict:
        """
        Phase 4: run multiple parallel_safe steps concurrently.
        Returns {step_id: (step_result, step_success)}.

        Concurrency is bounded by a semaphore (DER_MAX_CONCURRENT_STEPS) so a
        wide split cannot open unbounded parallel LLM calls (REQ-6). The
        semaphore is created per-call (not shared across turns) to avoid
        cross-session state and to respect the per-fan-out bound.
        """
        _sem = asyncio.Semaphore(DER_MAX_CONCURRENT_STEPS)

        async def _bounded(it):
            async with _sem:
                return await self._der_run_step_execution_async(
                    it, context_package, _session, _turn_id, plan
                )

        tasks = [_bounded(it) for it in items]
        _completed = await asyncio.gather(*tasks)
        return {_sid: (_res, _succ) for _sid, _res, _succ in _completed}

    # â”€â”€ DER Phase 0: verification (stub-kill + coarsened outcome) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # SemanticVerifier instance â€” lazy-init so import at module level is safe.
    _VERIFIER: Optional["SemanticVerifier"] = None
    _STUB_RE = re.compile(r"\[step\s+\d+\s+completed\]", re.IGNORECASE)
    # pin_517dfcbda150: web/crawl steps verify by CONTENT SUFFICIENCY â€” the
    # tool itself already proved it fetched real content (zero pages returns
    # an error at the tool boundary in tool_bridge). Assertion matching against
    # crawl output is meaningless under the hash/substring fallback while the
    # Encoder-350M is absent, and false FAILED verdicts drove the step-1
    # re-crawl loop (verify_failed -> split -> children re-crawl same query).
    _WEB_CONTENT_TOOLS = frozenset(
        {"crawler_query", "web_search", "search", "google_search", "exa_search"}
    )
    # pin_42ddd255162d: display/render tools complete by SUCCESS, not by content
    # volume â€” a rendered-card confirmation is a legit completion, never a
    # candidate for a verify-failure split (which is what made the task card
    # say "rendering documents" while the backend re-searched).
    _TRUSTED_RESULT_TOOLS = frozenset({"get_rendered_documents"})

    def _get_verifier(self):
        if self._VERIFIER is None:
            from backend.agent.verifier import SemanticVerifier as _SV
            AgentKernel._VERIFIER = _SV()
        return self._VERIFIER

    def _der_trace_task_id(self) -> str:
        """Stable per-task key for the REQ-18 trace â€” mirrors the ledger's
        task_id (conversation_id or session_id), so the trace and the ledger
        correlate on the same task."""
        return self.conversation_id or self.session_id or "unknown"

    def _verified_fraction(self, expected: Optional[str], result: str) -> float:
        """DER Phase 0 (D0.6): fraction of checkable assertions from expected_output
        that the result satisfies. Deterministic, no LLM. Assertions split on ';'.

        Delegates to SemanticVerifier (Phase 4 LFM2.5 integration) for semantic
        entailment scoring with stub guard + substring fallback.
        """
        frac, _scorer = self._get_verifier().verified_fraction(expected, result)
        # REQ-18 AC1 (T31): correlate the scorer tag + score into the per-task
        # trace. Off the critical path; a trace failure never affects the verdict.
        # The verified_label is attached by the caller (it is only known after
        # the full _verify_step_result classification completes).
        try:
            from backend.agent.der_trace import get_der_trace

            get_der_trace(self._der_trace_task_id()).record(
                "verify",
                scorer_tag=_scorer,
                score=round(float(frac), 4),
            )
        except Exception:
            pass
        return frac

    def _verify_step_result(
        self,
        goal: str,
        expected: Optional[str],
        result: str,
        tool: Optional[str] = None,
        success: bool = False,
    ) -> str:
        """DER Phase 0 (D0.1): classify a step result.
        Returns VERIFIED | UNVERIFIED | FAILED.
        A stub pattern with no real output is ALWAYS FAILED (no silent success).

        pin_517dfcbda150: when ``tool`` is a web/crawl tool, the verdict is
        CONTENT SUFFICIENCY â€” the tool already proved it fetched pages (a
        zero-page crawl returns an error from tool_bridge), so a non-empty,
        non-error result VERIFIEDs. This terminates the crawl step as soon as
        real content exists and prevents pointless re-crawl splits.
        """
        if tool in self._TRUSTED_RESULT_TOOLS:
            # pin_42ddd255162d: display/render tools complete by SUCCESS, and
            # this check runs FIRST â€” the formatted result of the render tool
            # can be an empty/JSON-less string even on success (its dict has no
            # extractable content key), and the old position (after the
            # empty-result check) turned every successful render into a
            # verify-FAILED â†’ split â†’ children re-gathered the SAME urls while
            # the card said "rendering documents". A trusted tool that ran
            # returns "VERIFIED" unconditionally â€” its contract never returns
            # errors on the read-only render path.
            return "VERIFIED"
        if not result:
            return "FAILED"
        # Strip the marker; if nothing substantial remains, it was a bare stub -> FAILED.
        _without_marker = self._STUB_RE.sub("", result).strip()
        if not _without_marker:
            return "FAILED"
        if tool and tool in self._WEB_CONTENT_TOOLS:
            _low = _without_marker.lower()
            # pin_42ddd255162d: CONTENT SUFFICIENCY must not scan real page
            # text for failure words â€” web pages legitimately contain "failed
            # to"/"no usable" mid-text, and the crawl fallback result may
            # carry an informational worker-timeout note alongside real pages.
            # The tool contract already guarantees the error case (zero usable
            # pages -> tool returns an error payload), so the verdict rests on
            # SUBSTANCE: long non-error content VERIFIEDs; only explicit
            # error-prefixed payloads and short error stubs FAIL.
            # pin_42ddd255162d: a successfully dispatched crawl (success=True)
            # VERIFIEDs regardless of volume â€” the observed failure mode was a
            # 2-page plain-HTTP fallback result (~60 chars) that failed the old
            # 80-char threshold â†’ verify FAILED â†’ split â†’ children re-gathered
            # the SAME urls, each costing a 30s LLM resolution + 429 retries.
            if success and not _low.startswith("error"):
                return "VERIFIED"
            if len(_without_marker) >= 80 and not _low.startswith("error"):
                return "VERIFIED"
            if _low.startswith("error") or "no usable" in _low or "failed to" in _low:
                return "FAILED"
            # Short, non-error text: weak but honest â€” commits as UNVERIFIED,
            # never triggers a re-gather split.
            return "UNVERIFIED"
        if tool in self._TRUSTED_RESULT_TOOLS:
            # pin_42ddd255162d: display/render tools complete by SUCCESS â€” a
            # rendered-card confirmation is a legit completion. The expected
            # assertion text (e.g. "a rendered document card") never matches
            # the short confirmation string, so the assertion path FAILED the
            # step and split it â€” spawning children that re-gathered web pages
            # while the card said "rendering documents".
            return "VERIFIED" if _without_marker else "FAILED"
        _frac = self._verified_fraction(expected, result)
        _expected_text = (expected or "").strip()
        if not _expected_text:
            # pin_42ddd255162d: no explicit expectation (REASON/synthesis and
            # render steps) â€” the assertion fraction is meaningless; the verdict
            # rests on SUBSTANCE: a substantial result VERIFIEDs, short text
            # commits honestly as UNVERIFIED. Only an explicit error/stub FAILs.
            return "VERIFIED" if len(_without_marker) >= 80 else "UNVERIFIED"
        if _frac >= 0.8:
            return "VERIFIED"
        if _frac >= 0.3:
            return "UNVERIFIED"
        # Explicit expectation, low match: a SUBSTANTIAL result is still a real
        # answer â€” commit honestly as UNVERIFIED; only weak stubs FAIL.
        return "UNVERIFIED" if len(_without_marker) >= 200 else "FAILED"

    # â”€â”€ REQ-1 AC2/AC3/AC4: per-step edge scoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @staticmethod
    def _der_mediator_for(item: "QueueItem") -> tuple:
        """REQ-23 (T37): resolve the MEDIATOR for a finalized step.

        Returns (mediator, source):
          - mediator: ``"<tool>:<args_hash>"`` â€” the resolved tool/action
            identifier plus a stable hash of its arguments (AC1). The args
            hash is the separator between "the same tool with materially
            different arguments" (REQ-23 edge case).
          - source:   ``"explicit"`` (tool chosen by the normal resolver /
                      plan), ``"none"`` (a pure decision/synthesis node with
                      no tool â€” recorded EXPLICITLY, never empty, per AC5).

        The DER loop resolves tools through the plan/explorer path today, so
        the source is always ``"explicit"`` or ``"none"``; the ``"predictor"``
        / ``"fallback"`` sources are reserved for the T17 mediator-ranking
        wiring, which must record WHICH chooser picked the tool or the
        learning credits the wrong one (REQ-23 edge case).
        """
        tool = getattr(item, "tool", None) or ""
        if not tool:
            return "none", "none"
        try:
            _params = getattr(item, "params", None) or {}
            _blob = json.dumps(_params, sort_keys=True, default=str)
            _args_hash = hashlib.sha256(_blob.encode("utf-8")).hexdigest()[:12]
        except Exception:
            _args_hash = "unhashable"
        return f"{tool}:{_args_hash}", "explicit"

    def _der_score_step_outcome(
        self,
        item: "QueueItem",
        verified_label: str,
        session_id: str,
        step_result: str,
    ) -> None:
        """Apply this step's edge-score consequence and, for FAILED, feed the
        AVOID header.

        This is deliberately a thin wiring call, not a new scorer: the deltas
        are the SAME generic table already defined in
        ``EdgeScorer._OUTCOME_DELTAS`` (scorer.py) â€” hit=+0.05, partial=+0.02,
        miss=-0.08 â€” now applied EVIDENCE-WEIGHTED (REQ-26/T40): the first
        observation on an edge moves it fully, later observations move it
        less, so belief converges instead of oscillating.

        REQ-26 AC1 (T40c): the scored edge is the (coordinate-region,
        mediator) pair for THIS step, selected by the CALLER â€” not every
        outbound edge of every active node. The REGION is the single active
        Mycelium node whose coordinates are nearest the step's live Caducean
        position Î£ = (x, y, Î¾, u) (the same state the chain row records):
        a step's outcome updates the region it was IN, and only that region.
        Scoring every active node would re-create the global fan-out the
        amendment removes â€” a step cannot fail "in two regions at once".
        The mediator is ``_der_mediator_for(item)`` (REQ-23/T37).
        ``EdgeScorer.record_region_mediator_outcome`` finds-or-creates that
        edge and updates ONLY it, so a tool that works in one region and
        fails in another is representable (a single global score cannot
        express that).

        REQ-1 AC2: VERIFIED  -> hit-scoring only (no crystallization change â€”
                   out of scope; no per-step crystallization exists today).
        REQ-1 AC3: UNVERIFIED -> partial credit, capped at
                   DER_MAX_UNVERIFIED_REPROPOSE + 1 scored attempts per
                   step_id (the original commit plus one re-propose) so an
                   UNVERIFIED step cannot be re-proposed indefinitely to farm
                   credit. Never crystallizes (no code path does today).
        REQ-1 AC4: FAILED    -> miss-scoring, and writes an episode with
                   outcome_type="miss" via the EXISTING ``_store_task_episode``
                   path â€” the same episodic-store write used for whole-task
                   outcomes â€” so evidence.py's AVOID section (which already
                   queries ``outcome_type = 'miss'``) surfaces it on the next
                   acting-prompt assembly. No second AVOID path is added.

        Never raises to the caller (see the try/except at the call site).
        """
        if verified_label not in ("VERIFIED", "UNVERIFIED", "FAILED"):
            return

        outcome = {
            "VERIFIED": "hit",
            "UNVERIFIED": "partial",
            "FAILED": "miss",
        }[verified_label]

        if verified_label == "UNVERIFIED":
            # AC3: enforce the re-propose cap BEFORE scoring â€” this is the
            # load-bearing guard, not advisory. Lazily initialised so this
            # works regardless of how the kernel was constructed (tests build
            # AgentKernel via __new__ without running __init__).
            if not hasattr(self, "_der_unverified_credit_counts"):
                self._der_unverified_credit_counts: Dict[str, int] = {}
            _count = self._der_unverified_credit_counts.get(item.step_id, 0)
            if _count > DER_MAX_UNVERIFIED_REPROPOSE:
                logger.debug(
                    "[DER] UNVERIFIED re-propose cap reached for step %s "
                    "(> %d) â€” no further partial credit",
                    item.step_id, DER_MAX_UNVERIFIED_REPROPOSE,
                )
                return
            self._der_unverified_credit_counts[item.step_id] = _count + 1

        myc = getattr(self._memory_interface, "_mycelium", None) if self._memory_interface else None
        if myc is not None:
            try:
                _mediator, _mediator_source = self._der_mediator_for(item)
                if _mediator == "none":
                    # REQ-23 AC5: a node with NO mediator records "none" â€”
                    # there is no (region, mediator) edge to score. Pure
                    # decision/synthesis nodes are not learning events.
                    return
                _mediator_tool = _mediator.split(":", 1)[0]
                node_ids = list(myc._registry.get_active(session_id))
                # REQ-26 AC1: the step's REGION is the ONE active node whose
                # coordinates are nearest its live Î£ position â€” not every
                # active node (that would be a fan-out in region clothing).
                try:
                    _cad = self._der_live_cad_state(session_id)
                    _cad_vec = [
                        _cad.get("x", 0.0), _cad.get("y", 0.0),
                        _cad.get("xi", 0.0), _cad.get("u", 0.0),
                    ]

                    def _dist(nid: str) -> float:
                        _n = myc._store.get_node_by_id(nid)
                        if _n is None or not _n.coordinates:
                            return float("inf")
                        _c = list(_n.coordinates)[: len(_cad_vec)]
                        _v = _cad_vec[: len(_c)]
                        return sum((a - b) ** 2 for a, b in zip(_c, _v)) ** 0.5

                    _region_node = min(node_ids, key=_dist) if node_ids else None
                except Exception:
                    _region_node = node_ids[0] if node_ids else None
            except Exception:
                _region_node = None
                _mediator_tool = ""
            if _region_node and _mediator_tool:
                try:
                    from backend.memory.mycelium.scorer import EdgeScorer

                    # REQ-26 AC1/T40c: the (coordinate-region, mediator)
                    # edge for THIS step â€” never the global fan-out.
                    EdgeScorer(myc._store).record_region_mediator_outcome(
                        region_node_id=_region_node,
                        mediator=_mediator_tool,
                        outcome=outcome,
                    )
                except Exception as _edge_exc:
                    logger.debug("[DER] region-scoped edge scoring failed: %s", _edge_exc)

        if verified_label == "FAILED":
            try:
                self._store_task_episode(
                    task_summary=item.description or "step",
                    full_content=str(step_result)[:500],
                    outcome_type="miss",
                    tool_sequence=[
                        {"tool": item.tool or "reasoning", "step": item.step_number}
                    ],
                    session_id=session_id,
                )
            except Exception as _ep_exc:
                logger.debug(
                    "[DER] FAILED-step AVOID episode write failed: %s", _ep_exc
                )

    def _der_topic_domain(self, text: str) -> str:
        """REQ-18 AC2/AC3 (T19): resolve free text to a registry topic_domain.

        Thin wrapper over the mycelium registry resolver (extractor.py
        ``resolve_topic_domain``) so the kernel never touches keyword patterns
        directly and unknown text resolves to the registry's ``general`` bucket
        with a logged mismatch â€” never invented free text. Lazy import keeps
        the mycelium extractor off the module import path (heavy-import rule).
        """
        try:
            from backend.memory.mycelium.extractor import resolve_topic_domain

            return resolve_topic_domain(text or "")
        except Exception as _td_exc:  # noqa: BLE001 â€” never block a step
            logger.debug(
                "[DER] topic_domain resolve failed (%s) â€” falling back to "
                "'general'",
                _td_exc,
            )
            return "general"

    def _der_execution_domain(self, from_voice: bool = False) -> str:
        """REQ-18 AC2 (T19): resolve the node's execution_domain axis.

        Registry-backed: one of ``voice | der | research`` from the ACTIVE
        winding. ``voice`` when the turn entered via voice; ``research`` when
        the task class is research-shaped (research|explore|investigate, the
        same set der_loop._decide_mode uses); otherwise ``der``. This is the
        request-domain axis â€” how the node RUNS, distinct from ``topic_domain``
        (what it is ABOUT). Unknown windings resolve to the session default
        (``der``) â€” never invented free text (REQ-18 AC3).
        """
        if from_voice:
            return "voice"
        _tc = str(getattr(self, "_der_task_class", "") or "").lower()
        if _tc in ("research", "explore", "investigate"):
            return "research"
        return "der"

    # â”€â”€ Phase 4: shared per-step finalize (extracted from _execute_plan_der)

    def _der_finalize_step(
        self,
        item: "QueueItem",
        step_result: str,
        step_success: bool,
        step_outputs: list,
        completed_items: list,
        _tokens_used: int,
        _token_budget: int,
        _session: str,
        _turn_id: Optional[str],
        _phase: int,
        is_mature: bool,
        _live_ctx,
        plan,
        context_package,
        queue,
        verdict,
        from_voice: bool = False,
    ) -> int:
        """
        Phase 4: full post-processing for one completed DER step.
        Faithful extraction of the inline finalize block from _execute_plan_der
        so both the serial path and concurrently-executed parallel_safe steps
        share identical post-processing. Returns the updated _tokens_used.

        ``from_voice`` (pin_517dfcbda150): threaded from the turn entry so the
        multi-session coupling wiring inside this method can classify the
        session domain ("voice" vs "der") instead of raising NameError.
        """
        step_outputs.append(step_result)

        # â”€â”€ EventBus: emit tool:result or tool:error â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            _lifecycle_task_id = _turn_id or item.step_id
            if step_success:
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_RESULT,
                    data={
                        "task_id": _lifecycle_task_id,
                        "result_summary": step_result[:200],
                        "tool_name": item.tool or "direct",
                        "step_number": item.step_number,
                        # REQ-3 AC6 (T2): card_id stays stable across every
                        # event of a card's lifetime.
                        **self._card_envelope(_lifecycle_task_id),
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
                # Trust-routing W2: a DER step that used an external/web
                # tool stores its output in 'reference', not 'tool'.
                _der_zone = (
                    "reference" if is_external_tool(getattr(item, "tool", "")) else None
                )
                if self._mcm_orch is not None:
                    # REQ-22: forward untrusted web scoring into the pacman
                    # fragment so credibility_map / citation_index persist in
                    # the 'reference' zone (only when the step used a web tool).
                    _cm = None
                    _ci = None
                    if isinstance(step_result, dict):
                        _cm = step_result.get("credibility_map")
                        _ci = step_result.get("citation_index")
                    self._mcm_orch.post_turn(
                        [{"role": "assistant", "content": _der_text}],
                        response_text=_der_text,
                        tool_name=getattr(item, "tool_name", ""),
                        zone=_der_zone,
                        credibility_map=_cm,
                        citation_index=_ci,
                    )
                elif (
                    self._memory_interface is not None
                    and hasattr(self._memory_interface, "episodic")
                    and hasattr(
                        self._memory_interface.episodic, "fragment_and_store"
                    )
                ):
                    # Background, same writer as every other fragment path â€”
                    # see the note at the document_data store above.
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        _submit_fragment_job,
                    )

                    _ep = self._memory_interface.episodic
                    _submit_fragment_job(
                        lambda: _ep.fragment_and_store(
                            _der_text,
                            session_id=_session,
                            chunk_type="der_output",
                            zone=_der_zone,
                        ),
                        f"der_output/step{getattr(item, 'step_number', '?')} "
                        f"({len(_der_text)} chars)",
                    )
        except Exception as _frag_exc:
            loud_error(_frag_exc, "der_pacman_fragment")

        # A3 FIX: also fragment FAILED outputs so failures are remembered and can
        # steer future recovery (the success path above skips them). Stored in the
        # 'tool' zone with chunk_type 'der_failure' for later recall.
        try:
            if step_result and not step_success:
                _fail_text = (
                    f"[FAILED Step {item.step_number}: {item.description[:120]}]"
                    f"\n{step_result}"
                )
                if (
                    self._memory_interface is not None
                    and hasattr(self._memory_interface, "episodic")
                    and hasattr(
                        self._memory_interface.episodic, "fragment_and_store"
                    )
                ):
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        _submit_fragment_job,
                    )

                    _ep_f = self._memory_interface.episodic
                    _submit_fragment_job(
                        lambda: _ep_f.fragment_and_store(
                            _fail_text,
                            session_id=_session,
                            chunk_type="der_failure",
                            zone="tool",
                        ),
                        f"der_failure/step{getattr(item, 'step_number', '?')} "
                        f"({len(_fail_text)} chars)",
                    )
        except Exception as _fail_frag_exc:
            loud_error(_fail_frag_exc, "der_pacman_fragment_failure")

        # â”€â”€ TOKEN BUDGET: accumulate estimated tokens from step result â”€â”€
        # 4 chars â‰ˆ 1 token; also count prompt overhead per step (~200 tok)
        _tokens_used += max(200, len(step_result) // 4)
        # â”€â”€ EventBus: emit context:usage (token budget progress) â”€â”€â”€â”€â”€â”€
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
            pass  # EventBus is optional â€” no crash if it fails
        if _tokens_used >= _token_budget:
            logger.info(
                f"[DER] Token budget exhausted ({_tokens_used}/{_token_budget}) "
                f"after step {item.step_number} â€” stopping early"
            )
            # RC6 FIX: emit explicit event instead of silent stop
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                _remaining = len([
                    i for i in queue.items
                    if i.step_id not in queue.completed_ids
                    and i.step_id not in queue.failed_ids
                ])
                get_event_bus().emit(
                    IRISStreamEvent.BUDGET_EXHAUSTED,
                    data={
                        "task_id": _turn_id,
                        "steps_completed": len(completed_items),
                        "steps_remaining": _remaining,
                        "tokens_used": _tokens_used,
                        "token_budget": _token_budget,
                        "message": f"Task incomplete: {_remaining} steps remaining "
                                   f"(budget {_tokens_used}/{_token_budget} exhausted)",
                    },
                    turn_id=_turn_id,
                    session_id=_session,
                )
            except Exception:
                pass  # EventBus is optional â€” no crash if it fails

        # â”€â”€ MYCELIUM SIGNAL: tool call â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ WORKING MEMORY: accumulate findings for later steps â”€â”€â”€â”€â”€â”€â”€â”€
        # Appends step result to working_history zone so _run_step_direct()
        # calls on later steps can see what earlier steps discovered.
        # Skips error outputs to avoid poisoning context with noise.
        try:
            if self._memory_interface and step_result and step_success:
                # Session 245: content-aware window — a gather-tool crawl
                # truncated to 400 chars starves every later step.
                _wm_note = (
                    f"[Step {item.step_number}: {item.description[:80]}]"
                    f" {self._smart_excerpt(step_result, self._der_evidence_cap(item.tool))}"
                )
                self._memory_interface.append_to_session(
                    _session, _wm_note, zone="working_history"
                )
                # Session 245 (live memory footer): surface the memory WRITE
                # on the card's footer while execution happens — previously
                # memory:event only fired once at recall time (before the
                # card existed), so the footer sat on "Active Execution" for
                # whole runs. Same registry kind ("episodic"), outcome_type
                # distinguishes store from recall.
                try:
                    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                    get_event_bus().emit(
                        IRISStreamEvent.MEMORY_EVENT,
                        data={
                            "kind": "episodic",
                            "task_summary": f"[Step {item.step_number}] {item.description[:80]}",
                            "outcome_type": "store",
                            "duration_ms": 0,
                        },
                        session_id=_session,
                        conversation_id=self.conversation_id,
                    )
                except Exception:
                    pass  # never block the DER loop on an emit failure
        except Exception as _wm2_exc:
            loud_error(_wm2_exc, "append_working_history")

        # Phase 0 fix (Gap 5): populate step result on the QueueItem so
        # downstream consumers (reviewer, trace) read real output instead of
        # "no result".
        item.result = step_result

        # DER Phase 0 (D0.1): verify the result. A stub pattern with no real output
        # is FAILED -> step_success forced False so it cannot be marked complete as a
        # success (no silent success edge). This is the honest-signal fix.
        # pin_517dfcbda150: pass the resolved tool so web/crawl steps verify by
        # content sufficiency instead of assertion matching.
        _verified = self._verify_step_result(
            item.description, item.expected_output, step_result,
            tool=getattr(item, "tool", None),
            success=step_success,
        )
        if _verified == "FAILED":
            step_success = False

        # REQ-18 AC1 (T31): the verified LABEL for this step is only known here
        # (after full classification). Attach it to the verify trace entries
        # recorded by _verified_fraction above, then add the label record.
        try:
            from backend.agent.der_trace import get_der_trace

            get_der_trace(self._der_trace_task_id()).record(
                "verify_label",
                verified_label=_verified,
                step_id=getattr(item, "step_id", ""),
                step_number=getattr(item, "step_number", 0),
                tool=getattr(item, "tool", None),
            )
        except Exception:
            pass

        # â”€â”€ Phase 2 (D2.1): unified recovery â€” verification FAILED uses the
        # SAME _split_step operator as the physics trigger. No separate graft
        # code path remains. Split prepays work units up front (Lyapunov Phi
        # strictly decreases). Children are Sub-Loops (is_subloop=True) that
        # collapse back to this step as ONE COMPRESS. â”€â”€
        # BUGFIX (REQ-8 AC3): this block used to run at the very end of the
        # function (right before `return _tokens_used`), but `_children` is
        # READ much earlier â€” by the REQ-8 task:learning emit below and by the
        # REQ-7 physics-narration hook â€” while it is only ASSIGNED here. Since
        # a name assigned anywhere in a Python function is local for the whole
        # function, every earlier read raised `UnboundLocalError: cannot
        # access local variable '_children' where it is not associated with a
        # value`, silently caught by each call site's own try/except so the
        # task:learning event (and the physics narration) never fired. Moved
        # up so `_children` is a real, already-computed value at every read
        # site. `_children` defaults to `[]` (no split) so the success path â€”
        # which never enters the split branch â€” still has a bound, honestly
        # falsy value instead of leaving the name unbound.
        _children = []
        # REQ-13 (fold forward, not back): only a FAILED verification may enter
        # the split gate. A weak (UNVERIFIED) graded score after evidence
        # gathering folds forward to an honest low-confidence answer instead of
        # spawning another round of gathering the same evidence (AC1). The
        # guard is EXPLICIT, not incidental: an execution-layer `success=False`
        # envelope that still carried content (REQ-1 informational-fallback
        # edge) would otherwise reach _split_step untouched by the D4 taxonomy
        # below (non-errored content skips classification). The D4/REQ-4
        # classes remain the ONLY no-split path for classified
        # transport/provider failures (AC2); _split_step stays reachable for
        # genuine unclassified semantic failure (AC3).
        if not step_success and not item.is_subloop and _verified == "FAILED":
            # D4/REQ-4 (specs/long-horizon-der-execution): classify the failure
            # BEFORE recursive fan-out. Transport/provider/envelope failures
            # (timeout, rate-limit, unavailable tool, bad args, empty result,
            # auth) are recorded as failure evidence and must NOT split the
            # task into children â€” the old `not step_success -> split` rule
            # turned a single transient error into a recursive fan-out. Only a
            # genuine semantic failure (tool produced content but verification
            # judged it wrong) splits: the step_result then carries real
            # content, not an error prefix.
            _split_ok = True
            try:
                from backend.agent.der_execution_ledger import (
                    classify_failure,
                    ExecutionLedger,
                    OUTCOME_TRANSIENT,
                    OUTCOME_UNAVAILABLE,
                    OUTCOME_INVALID_ARGS,
                    OUTCOME_EMPTY,
                    OUTCOME_PERMANENT,
                )

                _res_text = (step_result or "").strip()
                _res_low = _res_text.lower()
                _tool_errored = (
                    not _res_text
                    or _res_low.startswith("error")
                    or _res_low.startswith("[step error")
                    or _res_low.startswith("duplicate call")
                )
                if _tool_errored:
                    _fail_class = classify_failure(
                        False,
                        error=_res_text[:400],
                        error_type=getattr(item, "error_type", None),
                        result=step_result,
                    )
                    if _fail_class in (
                        OUTCOME_TRANSIENT,
                        OUTCOME_UNAVAILABLE,
                        OUTCOME_INVALID_ARGS,
                        OUTCOME_EMPTY,
                        OUTCOME_PERMANENT,
                    ):
                        _split_ok = False
                        logger.info(
                            "[DER] step %s failure classified=%s â€” recorded, NOT split (D4)",
                            item.step_id, _fail_class,
                        )
                        try:
                            _ledger = getattr(self, "_der_ledger", None)
                            if _ledger is None:
                                _ledger = ExecutionLedger(conversation_id=self.conversation_id or "")
                                self._der_ledger = _ledger
                            _ledger.record_failure(
                                task_id=self.conversation_id or self.session_id or "unknown",
                                step_id=item.step_id,
                                attempt_id=getattr(item, "attempt_id", "") or item.step_id,
                                failure_class=_fail_class,
                                input_summary=(item.description or "")[:200],
                                tool=item.tool,
                                error_type=getattr(item, "error_type", None),
                                error_summary=_res_text[:300],
                                recovered=False,
                            )
                        except Exception as _led_exc:  # noqa: BLE001
                            logger.debug("[DER] failure-evidence record failed: %s", _led_exc)
            except Exception:  # noqa: BLE001 â€” classification must never break recovery
                _split_ok = True
            if _split_ok:
                try:
                    _cad_split = self._der_live_cad_state(_session)
                    _wu = getattr(self, "_der_work_units", 0)
                    # REQ-4 AC1 (T16): the continuous verified fraction is a
                    # GRADED steering input at the split decision â€” mid-band
                    # selects a bounded probe (width 1) instead of a full-width
                    # re-attempt. Never crash the split on fraction failure.
                    try:
                        _vf_split = self._verified_fraction(
                            getattr(item, "expected_output", None),
                            str(step_result or ""),
                        )
                    except Exception:
                        _vf_split = 0.0
                    _children = self._split_step(
                        item,
                        "verify_failed",
                        _cad_split,
                        _wu,
                        step_result=step_result,
                        verified_fraction=_vf_split,
                    )
                    # REQ-3: debit measured tokens, not a flat child count.
                    # _measured must be bound for the debit even when no child was
                    # created (empty split) â€” a NameError here was silently swallowed
                    # by the broad except, disabling the work-unit debit entirely
                    # (NORTHSTAR defect-shape #1).
                    _measured = 0
                    if _children:
                        # REQ-7 AC1/AC2/AC3 (T25): one batched call per ready
                        # group (dispatch_batch), results routed per node;
                        # parse-failure children execute individually (AC2).
                        self._der_route_subloop_children(
                            _children, queue, _session, _turn_id
                        )
                        # REQ-3: debit measured tokens, not a flat child count.
                        _measured = max(200, len(step_result) // 4)
                        # REQ-14 (AC1/AC5, T23): a sub-loop split REVISES the
                        # plan mid-task â€” re-emit task:start through the SAME
                        # merge-by-id channel (useTaskProgress.ts:210-227) with
                        # the revision origin so the frontend refreshes
                        # description/tool for new steps without clobbering live
                        # status, and REQ-18's trace can attribute the origin.
                        # The payload keeps the contract keys unchanged
                        # (task_id/description/plan_title/mode/steps/total_steps)
                        # plus `origin`.
                        try:
                            from backend.agent.event_bus import (
                                get_event_bus,
                                IRISStreamEvent,
                            )

                            _rev_mode = (
                                queue.mode.value
                                if getattr(queue, "mode", None)
                                else str(_phase)
                            )
                            # REQ-3 (T2) edge case: a sub-loop split CONTINUES
                            # the parent card â€” it is a branch WITHIN a card,
                            # never a second card. Handled generically by the
                            # "not initial" rule in _resolve_card_identity.
                            _card_task_id = _turn_id or getattr(
                                plan, "original_task", ""
                            )[:40]
                            _card_id, _card_relation = self._resolve_card_identity(
                                _card_task_id, "sub_loop_split"
                            )
                            # T2b (REQ-1 AC8): the badge marks the nested row,
                            # so the label is set on the CHILD steps this
                            # split just produced â€” never on the parent or
                            # any sibling already in the queue. A step
                            # outside `_children` carries no `branchLabel`
                            # key at all (not an empty string), so
                            # ChassisBranchBadge renders on branch rows only.
                            _branch_child_ids = {c.step_id for c in _children}
                            get_event_bus().emit(
                                IRISStreamEvent.TASK_START,
                                data=self._task_start_payload(
                                    task_id=_card_task_id,
                                    description=getattr(
                                        plan, "original_task", ""
                                    )[:200],
                                    plan_title=self._effective_plan_title(plan),
                                    mode=_rev_mode,
                                    steps=[
                                        {
                                            "id": it.step_id,
                                            "description": it.description,
                                            "status": "pending",
                                            "toolName": it.tool,
                                            **(
                                                {"branchLabel": DER_SUBLOOP_BRANCH_LABEL}
                                                if it.step_id in _branch_child_ids
                                                else {}
                                            ),
                                        }
                                        for it in queue.items
                                    ],
                                    total_steps=len(queue.items),
                                    origin="sub_loop_split",
                                    # REQ-3 (T2): backend-declared card identity.
                                    card_id=_card_id,
                                    card_relation=_card_relation,
                                    conversation_id=self.conversation_id,
                                        turn_id=getattr(self, "_current_turn_id", None),
                                    **self._multiagent_tags(),
                                ),
                                turn_id=_turn_id,
                                conversation_id=self.conversation_id,
                                session_id=_session,
                            )
                            # T4a (REQ-4 AC1): persist the split card. Uses
                            # _queue_steps_snapshot (derives done/failed from
                            # queue state) rather than the wire payload's
                            # blanket "pending" â€” a mid-run restore should
                            # show already-finished steps as finished.
                            self._persist_card_snapshot(
                                card_id=_card_id,
                                conversation_id=self.conversation_id,
                                card_relation=_card_relation,
                                plan_title=self._effective_plan_title(plan),
                                mode=_rev_mode,
                                steps=self._queue_steps_snapshot(queue),
                                total_steps=len(queue.items),
                                terminal_state="running",
                            )
                            # REQ-18 AC3 (T31): correlate the sub-loop-split
                            # revision (REQ-4/REQ-13).
                            try:
                                from backend.agent.der_trace import get_der_trace

                                get_der_trace(self._der_trace_task_id()).record(
                                    "revision",
                                    origin="sub_loop_split",
                                    children=len(_children),
                                    boundary_step=getattr(
                                        queue, "_last_step_number", None
                                    ),
                                )
                            except Exception:
                                pass
                        except Exception:
                            pass  # EventBus is optional â€” never break recovery
                    self._der_work_units = debit_work_units(_wu, _measured)
                    logger.info(
                        "[DER] verify_failed -> split into %d sub-loops (work_units=%d)",
                        len(_children), self._der_work_units,
                    )
                except Exception as _split_exc:
                    logger.warning("[DER] split-on-failure failed: %s", _split_exc)

        # â”€â”€ Phase 3 (D3.3 G5): honest commit ledger â”€â”€
        # REQ-1: a commit is recorded for EVERY executed action with its true label
        # (VERIFIED / UNVERIFIED / FAILED) â€” not only VERIFIED. This is the learning
        # signal the outer loop and the AVOID/edge-miss path consume; gating it on
        # VERIFIED starves failure learning. Store write â€” never injected into a
        # prompt.
        try:
            from backend.agent.caducean_trajectory import (
                get_trajectory_recorder,
            )

            _cad = self._der_live_cad_state(_session)
            # REQ-20: DER commits land in the APPLICATION store (memory_interface
            # episodic db), not the BUILD-memory .mcm/coordinates.db.
            get_trajectory_recorder(self._memory_interface).record_commit(
                session_id=_session,
                step_id=item.step_id,
                commit_hash="",
                message=f"{_verified} step {item.step_number}: {item.description[:80]}",
                u=_cad.get("u"),
                xi=_cad.get("xi"),
                verified_label=_verified,
            )
        except Exception as _commit_exc:
            logger.debug("[DER] record_commit failed: %s", _commit_exc)

        # â”€â”€ REQ-1 AC2/AC3/AC4: per-step edge-score consequence of verified_label.
        # VERIFIED hit-scores (+0.05), UNVERIFIED partial-credits (+0.02, capped â€”
        # AC3) and never crystallizes, FAILED miss-scores (-0.08) and feeds the
        # AVOID header (AC4). Never raises â€” off the critical path.
        try:
            self._der_score_step_outcome(item, _verified, _session, step_result)
        except Exception as _score_exc:
            logger.debug("[DER] per-step edge scoring failed: %s", _score_exc)

        queue.mark_complete(item.step_id)

        # â”€â”€ T6/T8/T10 (specs/long-horizon-der-execution REQ-5/REQ-9) â”€â”€â”€â”€â”€â”€
        # D8: persistence gates terminal state. Close the execution-attempt in
        # the ledger and persist BEFORE emitting the terminal task:learning
        # event. A persistence failure is exposed honestly (warning) and the
        # event still fires â€” but the durable record is flagged, never silently
        # claimed.
        try:
            from backend.agent.der_execution_ledger import ExecutionLedger

            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(
                    conversation_id=self.conversation_id or self.session_id or ""
                )
                self._der_ledger = _ledger
            _att = _ledger.open_attempt(
                task_id=self.conversation_id or self.session_id or "unknown",
                step_id=item.step_id,
                parent_step_id=getattr(item, "parent_step_id", None),
                action_key=(item.description or item.tool or "")[:80],
                tool=item.tool,
            )
            _ledger.close_attempt(
                _att,
                outcome=_verified if _verified in ("VERIFIED", "UNVERIFIED", "FAILED") else "permanent",
                verified_label=_verified,
                error_type=getattr(item, "error_type", None),
            )
            if not _ledger.persist():
                logger.warning(
                    "[DER] attempt persistence FAILED for step %s â€” durable completion not claimed",
                    item.step_id,
                )
        except Exception as _att_exc:  # noqa: BLE001 â€” ledger must never block the step
            logger.debug("[DER] attempt-ledger write failed: %s", _att_exc)

        # â”€â”€ REQ-8: honest learning signal (task:learning) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Emited (never injected into a prompt) so the frontend can show the real
        # card state + Pacman OrbCanvas particles on the border. Three signals:
        #   avoided    â€” FAILED step (no children, not a subloop) -> AVOID
        #   retried    â€” verify_failed -> split into Sub-Loops
        #   crystallizedâ€” VERIFIED step -> skill captured
        # Off the critical path; a bus failure must never block the step result.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            if _verified == "VERIFIED":
                _signal = "crystallized"
            elif _children:
                _signal = "retried"
            else:
                _signal = "avoided"
            get_event_bus().emit(
                IRISStreamEvent.TASK_LEARNING,
                {
                    "session_id": _session,
                    "step_id": item.step_id,
                    "step_number": item.step_number,
                    "signal": _signal,
                    "verified_label": _verified,
                    "description": item.description or "",
                    "is_subloop": bool(getattr(item, "is_subloop", False)),
                },
            )
        except Exception as _learn_exc:
            logger.debug("[DER] task:learning emit failed: %s", _learn_exc)

        # â”€â”€ Phase 3 (Gap 3): propagate this step's output into dependent
        # pending steps so later steps consume real results, not static
        # params. Non-blocking â€” never fails the step. â”€â”€
        try:
            queue.resolve_dependent_params(item, step_result)
        except Exception as _dep_exc:
            logger.warning(
                "[DER] resolve_dependent_params failed: %s", _dep_exc
            )

        # pin_42ddd255162d: physics reads bound BEFORE the try below â€” the
        # broad swallowing try starts with imports + the trajectory recorder,
        # and ANY early exception (recorder creation, FFI import/call) used to
        # skip the binding; later reads of _u/_xi (trajectory record, coupling,
        # the REQ-7 narration hook) then raised UnboundLocalError â€” the defect
        # class of CADUCEAN_ARCHITECTURE.md Â§10 rule 7. Narration was 100%
        # mute, logging "physics-event narration skipped".
        _u = 0.0
        _xi = 0.0

        # â”€â”€ CADUCEAN UPDATE + IMMORTUS + TRAJECTORY RECORD â”€â”€
        try:
            from backend.gateway.iris_ffi import (
                ffi_caducean_update,
                ffi_calculate_eml,
                ffi_immortus_chain_append,
            )
            from backend.agent.caducean_trajectory import (
                format_coords,
                get_trajectory_recorder,
            )
            from backend.utils.durability_queue import submit as durability_submit

            # REQ-5/REQ-6: capture the coordinate BEFORE this step for
            # coords_from in the Immortus chain append (below).
            _before_coord = get_trajectory_recorder(
                self._memory_interface
            ).get_latest_coordinate(_session)

            _action = 0
            if item.tool in ("run_command", "git_commit", "git_push"):
                _action = 1
            elif not step_success:
                _action = 2
            # pin_42ddd255162d: bind physics reads BEFORE any FFI call. The
            # block below sits inside a broad swallowing try; if
            # ffi_caducean_update/ffi_calculate_eml throws, the flow jumps to
            # the except and later reads of _u/_xi (trajectory record, coupling,
            # the REQ-7 narration hook) would raise UnboundLocalError â€” the
            # exact defect class of CADUCEAN_ARCHITECTURE.md Â§10 rule 7: a name
            # read before assignment disables a whole feature (narration was
            # 100% mute, logging "physics-event narration skipped").
            _u = 0.0
            _xi = 0.0
            _eml_score, _ex, _ey = ffi_calculate_eml(_session)
            # v2: balance clamped to [0.1, 3.0] (was [0.1, 2.0]).
            # Note: the v2 baseline divisor is 2.3418 per the field theory
            # (see docs/cad_v2_architecture.md Â§2.2). The current EML
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

            _u = 0.0
            _xi = 0.0
            _rec = ffi_caducean_recommend(_session)
            _state_snapshot = ffi_caducean_get_state(_session)
            _xi = _state_snapshot.get("xi", 0.0)
            _u = _state_snapshot.get("u", 0.0)
            # â”€â”€ REQ-10 / REQ-11: multi-session coupling (feature-flagged, off
            # the critical path). Register the session once with its domain
            # windings, push live (Î¾, u) into the registry, and apply coupling.
            # The engine is (re)initialized with the domain windings on first
            # registration so engine c_eff and registry c_eff agree (REQ-11 AC3).
            # Any failure logs at debug and never blocks the step (REQ-10 AC5). â”€â”€
            try:
                from backend.agent.coupled_registry import (
                    coupling_enabled,
                    get_coupled_registry,
                    domain_windings,
                )
                from backend.gateway.iris_ffi import ffi_caducean_init_session

                if coupling_enabled():
                    _domain = "voice" if from_voice else "der"
                    _l, _m = domain_windings(_domain)
                    _reg = get_coupled_registry()
                    if _reg.ensure_registered(_session, _l, _m):
                        ffi_caducean_init_session(_session, _l, _m)
                    _reg.update_session_state(_session, _xi, _u)
                    _reg.apply_coupling(_session)
            except Exception as _coupling_exc:
                logger.debug("[DER] coupling wiring skipped: %s", _coupling_exc)

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
                # REQ-21 (T22): carry the two ontology axes on the trajectory
                # row so per-domain physics aggregation keys on how the step
                # RAN (execution_domain) and what it was ABOUT (topic_domain).
                execution_domain=getattr(item, "execution_domain", None)
                or ("voice" if from_voice else "der"),
                topic_domain=getattr(item, "topic_domain", None) or "general",
            )

            # v2: handle TOPO_VIOLATION (rec=3) by recording the anomaly
            # to the Mycelium QuorumSensor and halting the loop.
            if _rec == 3:
                # Phase 5: adapt the Duffing controller on a topological
                # violation so the engine self-corrects instead of repeatedly
                # violating the same boundary.
                try:
                    from backend.agent.trajectory_controller import TrajectoryController

                    _conn = getattr(
                        getattr(self._memory_interface, "episodic", None), "db", None
                    )
                    if _conn is not None:
                        TrajectoryController(_conn).tune_dffing_params(_session)
                except Exception as _tune_exc:
                    logger.warning(
                        "[agent_kernel] tune_dffing_params failed: %s", _tune_exc
                    )
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

            # â”€â”€ Homeostatic relaxation (REQ-1 AC2) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Fire after every RELAX_EVERY_N_UPDATES (10) updates, or every
            # RELAX_MAX_INTERVAL_S (60 s) wall-clock, whichever first. This
            # call is inside the outer swallowing try block so a relaxation
            # failure cannot abort the trajectory record or chain append below.
            try:
                global _update_counters
                with _update_counters_lock:
                    _update_counters[_session] = (
                        _update_counters.get(_session, 0) + 1
                    )
                    _uc = _update_counters[_session]
                from backend.agent.param_homeostasis import get_param_homeostasis

                get_param_homeostasis().maybe_relax(_session, _uc)
            except Exception as _relax_exc:
                logger.debug(
                    "[agent_kernel] maybe_relax failed: %s", _relax_exc
                )

            # â”€â”€ TrajectoryController refit on DER cadence (REQ-13) â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Calls TrajectoryController.fit() which refits only at milestones
            # (100, 500, 1000 records). Never blocks the step â€” wrapped in
            # its own try/except so a refit failure cannot abort the record or
            # chain append.
            try:
                from backend.agent.trajectory_controller import TrajectoryController

                _tc_conn = getattr(
                    getattr(self._memory_interface, "episodic", None), "db", None
                )
                if _tc_conn is not None:
                    TrajectoryController(_tc_conn).fit()
            except Exception as _refit_exc:
                logger.debug(
                    "[agent_kernel] maybe_refit failed: %s", _refit_exc
                )

            # REQ-5/REQ-6: coords_from / coords_to in canonical format_coords.
            # _before_coord captured before record() at line ~7440.
            if _before_coord is not None:
                _coords_from = format_coords(
                    _before_coord["x"], _before_coord["y"],
                    _before_coord["xi"], _before_coord["u"],
                )
            else:
                _coords_from = format_coords(0.0, 0.0, 0.0, 0.0)
            _coords_to = format_coords(
                _state_snapshot.get("x", _ex),
                _state_snapshot.get("y", _ey),
                _state_snapshot.get("xi", 0.0),
                _state_snapshot.get("u", 0.0),
            )
            # REQ-23 (T37): the causal triple â€” resolve the MEDIATOR once and
            # bind it to a VALUE (the write runs later; `item` must not be
            # read from another thread after the loop moves on). AC1: written
            # at the same finalize point as the outcome; AC5: "none" is the
            # explicit value for mediator-less (decision/synthesis) nodes,
            # never empty â€” so they do not rank as failed actions.
            _mediator, _mediator_source = self._der_mediator_for(item)
            # REQ-3 AC2 (T37 completion): stamp the node's memory record at
            # finalize â€” outcome, continuous fraction, mediator, and the
            # landing coordinate â€” so the record is complete for the causal
            # vocabulary (Treatment -> Mediator -> Outcome) and for the
            # REQ-26 posterior reader. Off the critical path; never fails the
            # step.
            try:
                _rec = getattr(item, "node_record", None) or getattr(
                    item, "footprint", None
                )
                if _rec is not None:
                    _rec.outcome = _verified
                    # REQ-18 (T19): stamp the two domain axes at the same
                    # finalize point as the outcome â€” topic re-resolved from
                    # the FULL step result text (richer signal than the seed
                    # description; registry-backed, general + logged on miss),
                    # execution from the active winding. AC4: these ride the
                    # node record AND the chain row.
                    _rec.topic_domain = self._der_topic_domain(
                        f"{item.description or ''} {step_result or ''}"
                    ) or "general"
                    _rec.execution_domain = (
                        self._der_execution_domain(from_voice) or "der"
                    )
                    # T36-FIX (content_summary): the L6014 construction comment
                    # promised "the finalize site re-stamps with the full step
                    # result text" â€” but content_summary was NEVER re-stamped, so
                    # _der_node_record_evidence fed the synthesis LLM only the
                    # step DESCRIPTION (plan sentence), not the actual tool output.
                    # Live T36 smoke: crawl stored 17 chunks + rendered the prism
                    # card, yet synthesis said "search tool did not return any
                    # actual results" (synthesis prompt was ~111 tokens). Re-stamp
                    # here with the real step result so the synthesis evidence is
                    # the actual crawl content, not the plan text. Bounded to 300
                    # chars to keep the record bounded (same as the seed).
                    _rec.content_summary = (step_result or "")[:300]
                    # REQ-4: continuous verified fraction, recomputed at the
                    # finalize point (the verifier's decisive fraction is not
                    # otherwise surfaced here). Fallback: the label's canonical
                    # continuous value so the record is never NaN/0.0 for a
                    # VERIFIED step.
                    try:
                        _vf = self._verified_fraction(
                            item.expected_output, str(step_result or "")
                        )
                    except Exception:
                        _vf = {"VERIFIED": 1.0, "UNVERIFIED": 0.5, "FAILED": 0.0}.get(
                            _verified, 0.0
                        )
                    _rec.verified_fraction = _vf
                    _rec.mediator = _mediator
                    _rec.mediator_source = _mediator_source
                    _rec.coords_to = _coords_to
                    _rec.edge_ids = _rec.edge_ids or []
                    # â”€â”€ REQ-5 AC2/AC4 (T17): record the COUPLING DECISION at
                    # commit. The branches surfaced to this step (all of them,
                    # capped â€” AC1) plus the one it chose are stamped on the
                    # node record, and the edge to the chosen branch is
                    # written/strengthened with the decision as provenance.
                    # Off the critical path; never raises.
                    try:
                        _cands = getattr(item, "_coupled_candidates", None) or []
                        if _cands:
                            _chosen = self._der_choose_coupling_branch(item, _cands)
                            self._der_record_coupling_decision(
                                item, _cands, chosen_node_id=_chosen, record=_rec
                            )
                    except Exception as _cc_exc:
                        logger.debug(
                            "[DER] coupling-decision record failed: %s", _cc_exc
                        )
                    # â”€â”€ REQ-19 (T20): persist the DER structural links into
                    # the SHARED link store at the same finalize point â€” the
                    # node's memory record AND its edges land together (DAG =
                    # memory = DAG). part_of (sub-loop containment, child ->
                    # parent), depends_on (plan dependency), relevant_to
                    # (branches actually surfaced to a decision â€” provenance,
                    # not affinity), failed_like (same failure class, so AVOID
                    # recall is a graph walk). Off the critical path; the
                    # writer itself never raises.
                    try:
                        if self._der_links is not None:
                            self._der_links.write_node_links(
                                item,
                                _rec,
                                step_success=step_success,
                                step_result=str(step_result or ""),
                                execution_domain=_rec.execution_domain,
                                session_id=_session or "",
                            )
                    except Exception as _dl_exc:
                        logger.debug(
                            "[DER] structural link write failed: %s", _dl_exc
                        )
            except Exception as _rec_exc:
                logger.debug(
                    "[DER] node_record finalize stamp failed: %s", _rec_exc
                )
            # â”€â”€ REQ-4 AC4 (T16b): FOLD-BACK â€” a sub-loop child folds back as
            # a compressed observation that CHANGES the parent's state: the
            # parent's node_record gains the child's verified outcome (REQ-3
            # AC1: the parent's next decision reads node records that now
            # include what the children resolved). Bounded (DER_FOLD_BACK_MAX);
            # off the critical path; never raises.
            if getattr(item, "is_subloop", False):
                try:
                    _parent_step_id = getattr(
                        getattr(item, "node_record", None), "parent_step_id", ""
                    ) or ""
                    if _parent_step_id:
                        for _qi in getattr(queue, "items", None) or []:
                            if getattr(_qi, "step_id", "") == _parent_step_id:
                                _prec = getattr(_qi, "node_record", None)
                                if _prec is not None:
                                    _fbs = list(
                                        getattr(_prec, "folded_back", None) or []
                                    )
                                    _fbs.append(
                                        f"[{item.step_id}] {_verified}: "
                                        f"{item.description[:160]}"
                                    )
                                    _prec.folded_back = _fbs[-DER_FOLD_BACK_MAX:]
                                break
                except Exception as _fb_exc:  # noqa: BLE001
                    logger.debug("[DER] fold-back write failed: %s", _fb_exc)
            # OFF THE CRITICAL PATH â€” the THIRD inline durability write found
            # on this path (after tool_bridge._record_tool_event and
            # _store_document_data). Per the note left on the second one, the
            # PATTERN is fixed here rather than the instance.
            #
            # Not a thread-per-write like the other two: this is a CHAIN
            # (coords_from -> coords_to), so two appends racing would land
            # reversed and corrupt the trajectory. The durability queue has a
            # single consumer, so submission order is the write order.
            #
            # Every argument is bound to a VALUE here, not to `item` â€” the
            # write runs later and the step object must not be read from a
            # different thread after the loop has moved on.
            durability_submit(
                f"immortus-chain:step_{item.step_number}",
                ffi_immortus_chain_append,
                thread_id=_session,
                result="success" if step_success else "failure",
                coords_from=_coords_from,
                coords_to=_coords_to,
                nbl_outcome=f"step_{item.step_number}",
                insight=item.description[:120],
                file_path=item.params.get("path", "") if item.params else "",
                landmark_id="",
                # REQ-23 AC2: mediator + source ride the same chain row as the
                # Î£ coords, so (Treatment -> Mediator -> Outcome) is queryable
                # together with the coordinates that were in force.
                mediator=_mediator,
                mediator_source=_mediator_source,
                # REQ-18 AC4 (T19): node type + both domain axes ride the
                # chain row so recall (REQ-20) and aggregation (REQ-21) can
                # key on them without a join back to the in-memory record.
                node_type=getattr(_rec, "node_type", "step") or "step",
                topic_domain=getattr(_rec, "topic_domain", "general") or "general",
                execution_domain=getattr(_rec, "execution_domain", "der") or "der",
            )
        except Exception as _cad_exc:
            loud_error(_cad_exc, "caducean_trajectory_immortus")

        completed_items.append(item)

        # â”€â”€ Phase 3: escalation + explorer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # After each step, check if mode escalation is warranted.
        # If queue is complete but more work is needed in AGENTIC/FULL
        # mode, re-plan with the LLM.
        try:
            _result_summary = (step_outputs[-1] if step_outputs else "")[:200]
            queue.check_escalation(
                review_verdict=verdict,
                tool_result_summary=_result_summary,
                token_budget_remaining=_token_budget - _tokens_used,
                turn_id=_turn_id,
            )

            # If queue is complete but mode is AGENTIC or FULL,
            # ask the LLM if more tools are needed.
            # Phase 5: rec-int termination â€” during COMPRESS (rec==1) the field
            # is condensing, so do NOT expand the plan with new explorer steps.
            # (next_ready already defers non-critical steps during COMPRESS; this
            # stops adding NEW ones, integrating the recommendation into loop
            # termination.)
            _rec_now = 2
            try:
                from backend.gateway.iris_ffi import ffi_caducean_recommend

                _rec_now = ffi_caducean_recommend(_session)
            except Exception:
                _rec_now = 2
            if _rec_now != 1 and queue.mode in (
                ExecutionMode.AGENTIC, ExecutionMode.FULL,
            ) and queue.is_complete():
                _next_tool = self._der_plan_next_step(
                    plan.original_task,
                    completed_items,
                    queue.mode,
                    _turn_id,
                    step_outputs=step_outputs,
                )
                if _next_tool:
                    # GOAL ONLY: the continuation step carries no tool/params.
                    # _der_run_step_execution resolves it via the single resolver
                    # (explorer.propose) â€” F6 / System Invariant. We never take a
                    # tool from the Explorer's continuation dict.
                    _next_item = QueueItem(
                        step_id=f"explorer_{len(completed_items) + 1}",
                        step_number=len(completed_items) + 1,
                        description=_next_tool.get("description", ""),
                        tool=None,
                        params={},
                        parallel_safe=False,
                        objective_anchor=plan.original_task,
                    )
                    queue.add_item(_next_item)
                    logger.info(
                        "[DER] Explorer added step %d: %s",
                        _next_item.step_number,
                        _next_item.description,
                    )
                    # Surface the newly-planned step to the frontend so the
                    # inline plan card shows the agent's live search/action
                    # steps as they are discovered â€” not just the upfront
                    # planner plan.  Frontend appends it to the to-do list.
                    # No session_id -> broadcast to all (single-user IRIS).
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.TASK_PROGRESS,
                            data={
                                "add_step": True,
                                "step_id": _next_item.step_id,  # pin_517dfcbda150: unique id so split/sub-loop children each append
                                "step_number": _next_item.step_number,
                                "description": _next_item.description[:200],
                                "tool_name": _next_item.tool,
                                # REQ-3 AC6 (T2): card_id stays stable across
                                # every event of a card's lifetime.
                                **self._card_envelope(_turn_id),
                            },
                        )
                        # T4a (REQ-4 AC5): persist the step addition so a
                        # card interrupted mid-run restores with the
                        # explorer-discovered step included.
                        _add_step_envelope = self._card_envelope(_turn_id)
                        self._persist_card_snapshot(
                            card_id=_add_step_envelope.get("card_id"),
                            conversation_id=self.conversation_id,
                            card_relation="continues",
                            # save_card upserts the WHOLE row â€” plan_title/mode
                            # must be re-sent every write or a step-transition
                            # snapshot would null out what task:start set.
                            plan_title=self._effective_plan_title(plan),
                            mode=queue.mode.value if getattr(queue, "mode", None) else None,
                            steps=self._queue_steps_snapshot(queue),
                            total_steps=len(queue.items),
                            terminal_state="running",
                        )
                    except Exception:
                        pass  # never block the DER loop on an emit failure

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

        # â”€â”€ EventBus: emit der:step â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # Surface step completion to the frontend plan card so the to-do
        # list checks the step off as it finishes.  Reuses the bridged
        # TASK_PROGRESS channel (no new event type needed).
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.TASK_PROGRESS,
                data={
                    "step_done": True,
                    # pin_517dfcbda150: carry the unique step id so the frontend
                    # can check off BOTH plan steps (ids like r1/step_1) and
                    # DER-discovered steps (der-N / explorer_N) â€” previously it
                    # only matched der-N, so plan steps never visually completed.
                    "step_id": item.step_id,
                    "step_number": item.step_number,
                    "description": item.description[:200],
                    "success": step_success,
                    # REQ-3 AC6 (T2): card_id stays stable across every
                    # event of a card's lifetime.
                    **self._card_envelope(_turn_id),
                },
            )
            # T4a (REQ-4 AC5): persist the step transition so a card
            # interrupted mid-run restores with current step statuses â€”
            # the whole point of AC5, since a crash never reaches task:done.
            _step_done_envelope = self._card_envelope(_turn_id)
            self._persist_card_snapshot(
                card_id=_step_done_envelope.get("card_id"),
                conversation_id=self.conversation_id,
                card_relation="continues",
                plan_title=self._effective_plan_title(plan),
                mode=queue.mode.value if getattr(queue, "mode", None) else None,
                steps=self._queue_steps_snapshot(queue),
                total_steps=len(queue.items),
                terminal_state="running",
            )
        except Exception:
            pass

        # â”€â”€ REQ-7: agent-driven PHYSICS-EVENT narration (post-step hook) â”€â”€
        # Replaces the flat per-step heartbeat. The agent speaks ONLY on a physics
        # event â€” a |u| transition (oscillating -> converged) or a structural
        # event (split into Sub-Loops, or a Sub-Loop collapsing). This is the
        # "now moving into a sub-task" / "settling into the answer" signal. It is
        # latency-cheap (pure arithmetic on already-fetched caducean state), off
        # the critical path (try/except), and funneled through SpeakTool (narration
        # lock) so it never conflicts with web-search progress or the final answer.
        # Invariant: spoken âŠ† visible â€” every spoken line is a real transition.
        try:
            from backend.agent.der_constants import detect_physics_narration

            _u_mag = abs(float(_u)) if _u is not None else 0.0
            _narrate = detect_physics_narration(
                self._der_last_u_mag, _u_mag, len(_children),
                bool(getattr(item, "is_subloop", False)),
            )
            _tts_played = False
            if _narrate:
                from backend.agent.tools.speak_tool import get_speak_tool

                get_speak_tool().speak(_narrate, priority="low")
                _tts_played = True
            self._der_last_u_mag = _u_mag
            # REQ-9: record the narration decision (incl. SILENCE) to the
            # conversation-scoped observability log. Off the critical path
            # (async fire-and-forget). u/xi carried on split/collapse.
            try:
                from backend.agent.narration import NarrationLog

                _nlog = NarrationLog(self.conversation_id)
                _decision = "brief" if _narrate else "silence"
                # u/xi only meaningful on a structural event.
                _has_struct = bool(_children) or bool(
                    getattr(item, "is_subloop", False)
                )
                # pin_42ddd255162d: direct sync write â€” the DER runs in a
                # thread where get_event_loop() raises RuntimeError, so the
                # old run_in_executor path threw on EVERY finalize and the
                # narration log was silently empty. _write is a small JSONL
                # append (microseconds); a sync call from the worker thread is
                # correct and the caller's try/except keeps it non-blocking.
                _nlog._write(
                    {
                        "ts": time.time(),
                        "conversation_id": self.conversation_id,
                        "step_id": item.step_id,
                        "decision": _decision,
                        "signal": (
                            "retried"
                            if _children
                            else (
                                "crystallized"
                                if _verified == "VERIFIED"
                                else "avoided"
                            )
                        )
                        if _has_struct
                        else None,
                        "u": float(_u) if _u is not None else None,
                        "xi": float(_xi) if _xi is not None else None,
                        "text": _narrate or "",
                        "tts_played": _tts_played,
                    },
                )
            except Exception as _nlog_exc:
                logger.debug("[DER] narration log skipped: %s", _nlog_exc)
        except Exception as _narr_exc:
            logger.debug("[DER] physics-event narration skipped: %s", _narr_exc)
            # Never let narration block the step result.
            try:
                self._der_last_u_mag = (
                    abs(float(_u)) if _u is not None else 0.0
                )
            except Exception:
                pass

        # â”€â”€ TRAILING DIRECTOR gap-fill REMOVED (2026-08-06) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The gap-fill ran SEQUENTIALLY after the user's task: it was invoked
        # synchronously in _der_finalize_step and its gap items were queued
        # into the SAME turn, re-executing completed steps' work after the plan
        # finished (live turn 95cbe698-342: 5 planned steps then gap-s2-*
        # extended the turn; turn fc2a1a48-ddf looped unbounded on gap-on-gap).
        # It never ran in parallel with the task, so it only added latency and
        # unsolicited steps. Decision: remove the gap-fill entirely.
        # _trailing_director stays None (init no longer constructs it); the
        # REQ-5 AC1 shallow-verified check is intentionally dropped with it
        # (it existed only to feed gap analysis).

        # NOTE: the verify_failed -> split-into-sub-loops step (Phase 2 D2.1)
        # used to live here. It computed `_children`, which the REQ-8
        # task:learning emit and the REQ-7 physics-narration hook above both
        # read â€” but those reads ran *before* this block, every time, so
        # `_children` was always unbound at read time (UnboundLocalError,
        # silently swallowed). Moved up to right after `_verified` is known,
        # before its first reader. See the bugfix note there.

        return _tokens_used

    def _der_bound_step_context(self, item: "QueueItem") -> None:
        """REQ-3 T8b AC4/AC5/AC6: bound the step's working context (forgetting).

        Extracted from _der_finalize_step's step-input section so the contract
        test drives the REAL code. Never raises â€” the caller's step must not
        fail on a forgetting error.

        AC4: content beyond the OQ-6 derived bound is dropped from the step's
        working context (coordinate_signal) â€” the node record is the re-read
        point.
        AC5: the per-step prompt token count is recorded (measured reduction);
        the bound is DERIVED from the REQ-1 resolved window, never a literal.
        AC6: when the node's chain write FAILED (durability drop counter > 0),
        the working context is the ONLY copy â€” never bounded/dropped.
        """
        try:
            _window = self.resolve_context_window() or 8192
            # OQ-6: 15% of the resolved window, derived â€” never a hardcoded
            # literal (a literal re-creates the 8192 collapse REQ-1 fixes).
            _step_budget = max(512, int(_window * 0.15))
            _sig = getattr(item, "coordinate_signal", "") or ""
            _step_tokens = max(1, len(_sig) // 4)  # charsâ†’tokens â‰ˆ 4:1
            # AC6: never forget content whose write failed. BUGFIX 2026-08-06:
            # the old guard `_der_chain_drops == 0 or not
            # step_id.startswith("immortus")` made AC6 vacuously true â€” the
            # `or` second clause was True for EVERY non-immortus step, so a
            # regular DER step whose chain write FAILED (drops>0) still had
            # its only copy dropped. Contract
            # test_der_t8b_forgetting_contract.py caught it. The ONLY safe
            # condition is: no drops.
            _write_ok = getattr(self, "_der_chain_drops", 0) == 0
            if _write_ok and len(_sig) > _step_budget:
                # AC4: drop the overflowing tail; the NODE RECORD (compressed)
                # is the re-read point.
                item.coordinate_signal = _sig[:_step_budget]
            if hasattr(self, "_der_step_prompt_tokens"):
                self._der_step_prompt_tokens += _step_tokens
        except Exception as _forget_exc:
            loud_error(_forget_exc, "step_forgetting_bound")

    # â”€â”€ Phase 3: explorer methods â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _der_plan_next_step(
        self,
        task_objective: str,
        completed_items: List,
        mode: "ExecutionMode",
        turn_id: Optional[str] = None,
        step_outputs: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        After all planned steps are done, ask the LLM if more work is
        needed to satisfy the original objective.

        Returns a dict with 'description' (a GOAL) if more work is needed,
        or None if done. It MUST NOT return a 'tool'/'params' â€” tool
        selection is the single resolver's job (explorer.propose), fired
        when the continuation step executes (F6 / System Invariant). This
        is the key method for AGENTIC mode â€” it enables the multi-step tool
        loop without a hardcoded limit, while keeping one tool authority.
        """
        try:
            if not completed_items:
                return None

            from backend.agent.der_constants import ExecutionMode

            # Build a summary of what was done (include real outputs when present)
            done_summary = "\n".join(
                f"  Step {i.step_number}: {i.description}"
                + (f"\n    OUTPUT: {i.result}" if i.result else "")
                for i in completed_items[-10:]
            )

            # Phase 3 (Gap 4): surface the actual step outputs to the Explorer
            # so it can reason about what was really returned, not just the
            # step descriptions. Bounded to keep the prompt small.
            outputs_block = (
                "\n".join(
                    f"  [{idx + 1}] {out[:600]}" for idx, out in enumerate(step_outputs)
                )
                if step_outputs
                else "  (none captured)"
            )

            prompt = (
                "You are the Explorer. Your job is to decide if more work is needed.\n\n"
                f"OBJECTIVE: {task_objective}\n\n"
                f"STEPS COMPLETED ({len(completed_items)} total):\n{done_summary}\n\n"
                f"ACTUAL STEP OUTPUTS (what each completed step returned):\n"
                f"{outputs_block}\n\n"
                f"Current mode: {mode.value if isinstance(mode, (str, ExecutionMode)) else 'agentic'}\n\n"
                "Is the objective fully met? If yes, respond with {\"done\": true}.\n"
                "If no, describe the SINGLE next goal to make progress (do NOT name a\n"
                'tool). Respond with:\n'
                '{"done": false, "description": "what goal to pursue next"}\n'
                "Be specific about the outcome the next step should achieve.\n\n"
                "Respond with JSON only."
            )

            response = self.infer(
                prompt, role="reasoning", max_tokens=400, temperature=0.1
            )
            raw = response.raw_text or ""

            # Parse JSON from response
            import json as _json

            m = re.search(r"\{[\s\S]+\}", raw)
            if not m:
                return None

            data = _json.loads(m.group())
            if data.get("done") is True:
                return None

            _desc = data.get("description")
            if not _desc or not str(_desc).strip():
                return None

            # GOAL ONLY â€” no tool/params. The resolver picks the tool on exec.
            return {"description": str(_desc).strip()}

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
                prompt, role="reasoning", max_tokens=300, temperature=0.1
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
                        "[DER] FULL mode progress check â€” drift detected: %s", note
                    )
                    if suggestion:
                        # The suggestion is logged for debugging but not
                        # automatically applied â€” the Director decides.
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

{_READABLE_FORMAT_RULES}
"""

        try:
            # Get reasoning model for synthesis â€” only use local model if it's
            # actually loaded.  Do NOT call get_reasoning_model() as a fallback here:
            # that can return a broken/unloaded stub which echoes garbage like
            # "respond_to_user" back to the user verbatim.
            reasoning_model = None
            if self._model_router and self._selected_reasoning_model:
                reasoning_model = self._model_router.models.get(
                    self._selected_reasoning_model
                )

            if reasoning_model:
                # Call the loaded local/LFM model for synthesis. In-process
                # local models never report a usage block (no HTTP response to
                # parse), so this is an ESTIMATE-only accrual (D1 item 4/5) â€”
                # there is no real number available to prefer here.
                _raw_reply = reasoning_model.generate(synthesis_prompt)
                response = self._strip_thinking(_raw_reply)
                self._accrue_tokens(
                    _raw_reply, None, source="_synthesize_response:local"
                )
                logger.info(
                    "[AgentKernel] Brain synthesized response with tool results context"
                )
                return response

            # Primary path: route synthesis through the unified InferenceRouter so
            # API providers (Cerebras, OpenAI, â€¦) are used for the brain answer,
            # not just local/Ollama models. Legacy LM Studio / Ollama branches
            # below remain as fallbacks for local-model configurations.
            #
            # REQ-8 AC3 (T26): when the ROUTER holds the primary provider (its
            # health check reports ok), a router failure degrades DIRECTLY to the
            # compressed-summary fallback â€” we do NOT replay the giant synthesis
            # prompt through the LM Studio / Ollama chain (the 429-stall
            # behaviour REQ-8 fixes). LM Studio / Ollama are only tried when the
            # router has NO bound provider (local-only configurations), where
            # they ARE the primary path.
            _router_primary = False
            try:
                if self._router is not None:
                    _router_primary = bool(
                        self._router.health_check_provider("reasoning").get("ok")
                    )
            except Exception:
                _router_primary = False
            try:
                _syn_text, _syn_think, _syn_tools = self._router.generate(
                    "reasoning",
                    [{"role": "user", "content": synthesis_prompt}],
                    max_tokens=self.response_max_tokens(),
                    temperature=0.6,
                )
                self._accrue_tokens(
                    _syn_text, getattr(self._router, "last_usage", None),
                    source="_synthesize_response:router",
                )
                if _syn_text:
                    logger.info(
                        "[AgentKernel] Brain synthesized response via InferenceRouter"
                    )
                    return self._strip_thinking(_syn_text)
                if _router_primary:
                    # Empty response from the primary provider counts as failure
                    # (the health check reports ok even when the endpoint returns
                    # nothing â€” reachability is only proven at execution time).
                    logger.warning(
                        "[AgentKernel] router (primary) returned empty synthesis â€” "
                        "degrading to compressed-summary fallback (REQ-8 AC3)"
                    )
                    return ""
            except Exception as _syn_err:
                logger.warning(
                    f"[AgentKernel] router synthesis failed: {_syn_err}"
                )
                if _router_primary:
                    # REQ-8 AC3 (T26): primary provider failed â€” degrade to the
                    # deterministic compressed summary, no giant-prompt replay.
                    logger.warning(
                        "[AgentKernel] router is the primary provider and failed â€” "
                        "degrading to compressed-summary fallback (REQ-8 AC3)"
                    )
                    return ""

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
                        f"{self._ollama_endpoint}/api/chat",
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

            # No model available for synthesis. Return "" instead of a generic
            # template so the REQ-12 success path falls through to the DER-shaped
            # deterministic summary (_der_deterministic_success_summary) that
            # mirrors _der_deterministic_failure_summary â€” never a silent raw
            # concatenation of step outputs (REQ-12 AC4).
            logger.warning(
                "[AgentKernel] No model for synthesis â€” returning empty "
                "(caller falls back to deterministic summary)"
            )
            return ""

        except Exception as e:
            logger.error(f"[AgentKernel] Error in brain synthesis: {e}")
            return ""

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
        # Legacy local model directory name â†’ canonical ID (executor only; brain removed)
        "LFM2.5-1.2B-Instruct": "lfm2.5-1.2b-instruct",
        "executor": "lfm2.5-1.2b-instruct",
        # NOTE: LFM2-8B-A1B / "brain" / "lfm2-8b" aliases are intentionally absent.
        # That model is not in use â€” removing the aliases prevents accidental routing.
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
        api_base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        preserve_bindings: bool = False,
    ) -> bool:
        """
        Set user-selected models for reasoning and tool execution.

        Args:
            reasoning_model:    Model ID for reasoning tasks (None to clear)
            tool_execution_model: Model ID for tool execution tasks (None to clear)
            model_provider:     Provider the user chose: "local" | "vps" | "api"

        Returns:
            True always â€” selections are stored unconditionally so that:
            â€¢ Ollama model IDs (e.g. "llama3.2:3b") aren't rejected because
              ModelRouter doesn't list them.
            â€¢ LFM local models aren't rejected when lazy loading is active and
              the models dict is still empty.
            Inference-time routing is responsible for surfacing "not available".
        """
        # Normalize aliases (e.g. "LFM2-8B-A1B" â†’ "lfm2-8b")
        reasoning_model = self._normalize_model_id(reasoning_model)
        tool_execution_model = self._normalize_model_id(tool_execution_model)

        # API keys are pasted from dashboards/emails and routinely carry stray
        # leading/trailing whitespace. A key with a space is sent verbatim as
        # `Bearer  <key>` and rejected by every provider (401). Strip once at
        # the entry point so the keyring, provider instances, and transports
        # all see the clean value.
        if api_key:
            api_key = api_key.strip()

        try:
            # Swarm mode is the highest-priority configuration.
            # If swarm is enabled, do NOT let the Models card overwrite
            # provider='iris_local' or the swarm model names back to UI
            # selections. This used to guard only the (now removed) legacy-field
            # assignments, while the role rebind below ran anyway â€” so the card
            # re-pointed the router away from the swarm even as the log line
            # claimed the selection was ignored. Returning here makes the guard
            # mean what it says.
            if getattr(self, "_swarm_enabled", False):
                if reasoning_model or tool_execution_model or model_provider:
                    logger.info(
                        f"[AgentKernel] Swarm is enabled â€” ignoring model_selection "
                        f"from Models card (keeping provider='{self._model_provider}', "
                        f"reasoning='{self._selected_reasoning_model}', "
                        f"tool='{self._selected_tool_execution_model}')"
                    )
                    return True

            # The selection is applied by binding the roles further down (see
            # the `_r.bind_role(...)` calls). There is nothing to assign here:
            # `_selected_reasoning_model`, `_selected_tool_execution_model` and
            # `_model_provider` are derived from those bindings.

            # â”€â”€ Resolve provider credentials EARLY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Must happen BEFORE peer propagation / snapshot sync so secondary
            # kernels (crawl_planner, session_iris_integration, â€¦) inherit the
            # CORRECT api_base_url + api_key. Previously these were assigned at
            # the END of this method, AFTER peers/snapshot had copied the stale
            # default (https://api.openai.com/v1) â€” so the crawl_planner sent the
            # Cerebras key to OpenAI â†’ 401.
            if api_key:
                self._api_key = api_key
                self._api_key_provider = model_provider or ""
                try:
                    from backend.agent.inference.keyring import set_secret

                    set_secret(model_provider, api_key)
                except Exception:
                    pass
            if api_base_url:
                self._api_base_url = api_base_url.rstrip("/")
            elif model_provider:
                # Dynamic resolution from the canonical provider registry
                # (PROVIDER_PRESETS): the URL follows the provider id from
                # the config, so it stays correct even if the frontend did
                # not send one explicitly.
                from backend.agent.inference.provider import (
                    get_provider_default_endpoint,
                )

                _ep = get_provider_default_endpoint(model_provider)
                if _ep:
                    self._api_base_url = _ep

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

            # Propagate CREDENTIALS and endpoints to peer kernels so secondary
            # sessions (e.g. session_iris_integration used by the wake-word
            # path) can authenticate. The MODEL and PROVIDER are no longer
            # copied: peers read them from the shared role table, so they were
            # already in sync, and writing them here is what let one session's
            # in-flight selection stamp itself onto every other session.
            for peer_id, peer_kernel in _agent_kernel_instances.items():
                if peer_kernel is not self:
                    if getattr(peer_kernel, "_swarm_enabled", False):
                        logger.debug(
                            f"[AgentKernel] Peer '{peer_id}' swarm enabled â€” "
                            f"skipping credential propagation"
                        )
                        continue
                    if self._api_key:
                        peer_kernel._api_key = self._api_key
                        peer_kernel._api_key_provider = self._api_key_provider
                    if self._api_base_url:
                        peer_kernel._api_base_url = self._api_base_url
                    if self._lmstudio_endpoint:
                        peer_kernel._lmstudio_endpoint = self._lmstudio_endpoint
                    peer_kernel._context_window_overrides = dict(
                        self._context_window_overrides
                    )
                    logger.debug(
                        f"[AgentKernel] Propagated credentials to peer session '{peer_id}'"
                    )

            # The 'default' kernel used to be force-created here so it could act
            # as the "inheritance source" new conversations copied their model
            # from. There is no inheritance any more â€” every kernel reads the
            # shared role table â€” so this block existed only to keep a copy
            # warm, and creating a phantom 'default' kernel as a side effect of
            # a model pick was itself a known problem (Wave 5).

            # Sync the router with the selection so InferenceRouter is always
            # consistent with the legacy field assignments above.
            if model_provider:
                from backend.agent.inference.provider import ProviderInstance, ProviderKind

                _kind = ProviderKind.INPROCESS if model_provider in ("local", "iris_local", "inprocess") and not api_base_url else (
                    ProviderKind.LOCAL_OPENAI if model_provider in ("lmstudio", "openai_compatible", "local_openai") or (model_provider == "local" and api_base_url) else (
                    ProviderKind.OLLAMA if model_provider == "ollama" else ProviderKind.API))
                # Persist credentials so the provider instance can authenticate
                # and the UI can learn the key is already configured.
                if api_key:
                    self._api_key = api_key
                    self._api_key_provider = model_provider or ""
                    # Persist the per-provider key to the keyring so it survives
                    # restarts and _build_transport can retrieve it by cred_ref.
                    # Without this, a key applied per provider was memory-only and
                    # the keyring kept a stale/fake key â†’ 401 after restart.
                    try:
                        from backend.agent.inference.keyring import set_secret

                        set_secret(model_provider, api_key)
                    except Exception:
                        pass
                if api_base_url:
                    self._api_base_url = api_base_url.rstrip("/")
                # Resolve the effective key: freshly supplied key wins; else the
                # key already on the kernel â€” but ONLY when it belongs to THIS
                # provider. `self._api_key` is a single shared field holding the
                # LAST applied key regardless of provider; using it as a blanket
                # fallback attaches, e.g., a Cerebras key to a Cohere provider
                # instance (and the registry then reports it as valid), which
                # 401s at call time. Track which provider the kernel key belongs
                # to and only reuse it for that same provider.
                _effective_key = _resolve_effective_key(
                    api_key=api_key,
                    kernel_key=getattr(self, "_api_key", "") or "",
                    kernel_key_provider=getattr(self, "_api_key_provider", "") or "",
                    model_provider=model_provider,
                )
                if not _effective_key:
                    try:
                        from backend.iris_config import load_config as _lc
                        _cfg = _lc()
                        _cfg_key = getattr(_cfg.inference, "api_key", "") or ""
                        _cfg_provider = getattr(_cfg.inference, "provider", "") or ""
                        if _cfg_key and model_provider == _cfg_provider:
                            _effective_key = _cfg_key
                            self._api_key = _cfg_key
                            self._api_key_provider = model_provider or ""
                    except Exception:
                        pass
                # Namespace the bare "local" provider id (REQ-4 AC1) so it never
                # collides with or shadows a namespaced local entry.
                # `reasoning_model` is optional on this call, so derive the stem
                # defensively â€” an unguarded .split() on None raised out of here
                # and the whole selection silently returned False.
                _inst_id = (
                    f"local:{(reasoning_model or 'local').split('.')[0].lower()}"
                    if model_provider == "local"
                    else model_provider
                )
                # â”€â”€ Resolve the model this instance is registered WITH â”€â”€â”€â”€â”€â”€
                # `registry.add()` REPLACES the entry for this id, so whatever
                # lands in `model=` becomes the provider's model for every
                # later reader (ModelSwitcher label, dashboard card, and
                # `generate()`'s `model_override or inst.model` fallback).
                #
                # Two rules, both learned from the cerebrasâ†’cohere desync
                # (2026-08-13 08:19, backend-20260813-074742.log): a confirm_card
                # carrying the PREVIOUS provider's model name re-registered
                # `cohere` with `model="gemma-4-31b"`.
                #   1. A hosted-API provider only accepts a model from its OWN
                #      catalog. A foreign model id is a stale caller value, not
                #      a user intent â€” drop it rather than stamp it on.
                #   2. Never downgrade a known model to blank. An empty `model`
                #      is what made every downstream resolution fall through to
                #      the stale value in the first place.
                from backend.agent.inference.provider_catalog import (
                    get_default_model_for_provider,
                    model_belongs_to_provider,
                )

                _prev_router = getattr(self, "_router", None)
                _prev_inst = (
                    _prev_router.registry.get(_inst_id)
                    if _prev_router is not None
                    else None
                )
                _inst_model = reasoning_model or None
                if (
                    _inst_model
                    and _kind in (ProviderKind.API, ProviderKind.OLLAMA)
                    and not model_belongs_to_provider(model_provider, _inst_model)
                ):
                    logger.warning(
                        "[AgentKernel] model '%s' is not in provider '%s' catalog â€” "
                        "ignoring it (stale caller value) and keeping the provider's "
                        "own model",
                        _inst_model, model_provider,
                    )
                    _inst_model = None
                if not _inst_model:
                    _inst_model = (
                        (_prev_inst.model if _prev_inst else None)
                        or get_default_model_for_provider(model_provider)
                    )
                # A tool model from another provider's catalog is stale the same
                # way; sanitize it before it can become a role override below.
                _tool_model = tool_execution_model or None
                if (
                    _tool_model
                    and _kind in (ProviderKind.API, ProviderKind.OLLAMA)
                    and not model_belongs_to_provider(model_provider, _tool_model)
                ):
                    _tool_model = None

                _inst = ProviderInstance(
                    id=_inst_id, label=model_provider, kind=_kind,
                    model=_inst_model,
                    api_base_url=api_base_url or getattr(self, '_api_base_url', '') or "",
                    api_key=_effective_key,
                    # Carry forward live state that this call knows nothing
                    # about â€” re-registering a loaded local provider must not
                    # silently mark it unloaded (that drops it out of the
                    # ModelSwitcher, which filters local providers on `loaded`).
                    purpose=(_prev_inst.purpose if _prev_inst else "chat"),
                    loaded=(_prev_inst.loaded if _prev_inst else False),
                    loading=(_prev_inst.loading if _prev_inst else False),
                )
                # Register on this kernel's router only. The registry is
                # process-wide (REQ-5), so every peer kernel observes the same
                # provider and role bindings automatically â€” no fan-out loop.
                _r = getattr(self, "_router", None)
                if _r is not None:
                    _r.add_provider(_inst)
                    # PERSIST the provider, not just register it (2026-08-16).
                    #
                    # add_provider() writes the LIVE registry only. The config's
                    # `inference.providers` collection â€” which the registry is
                    # rebuilt from at startup â€” was written by a different path
                    # that only the explicit provider-setup flow calls. So a
                    # provider chosen through the Models card existed until the
                    # next restart and then vanished: ollama disappeared from the
                    # ModelSwitcher dropdown and both roles fell back to cohere,
                    # because the id they were bound to no longer existed.
                    #
                    # This is provider-agnostic by construction â€” the same hole
                    # swallowed any provider (and would swallow a loaded local
                    # model) that was never registered through provider setup.
                    # Credentials are NOT written here; the key already went to
                    # the keyring above and config only records the cred_ref.
                    try:
                        from backend.iris_config import (
                            ProviderEntry as _PE,
                            load_config as _lc2,
                            save_config as _sc2,
                        )

                        _cfg2 = _lc2()
                        _existing = (_cfg2.inference.providers or {}).get(_inst_id)
                        _cfg2.inference.providers[_inst_id] = _PE(
                            id=_inst_id,
                            label=model_provider or _inst_id,
                            kind=_kind.name,
                            model=_inst_model or "",
                            purpose=getattr(_inst, "purpose", "chat") or "chat",
                            endpoint=getattr(_inst, "api_base_url", "") or "",
                            cred_ref=(
                                _inst_id if _effective_key
                                else getattr(_existing, "cred_ref", "") or ""
                            ),
                            model_path=getattr(_existing, "model_path", "") or "",
                            profile=getattr(_existing, "profile", "balanced")
                            or "balanced",
                        )
                        _cfg2.inference.config_version = max(
                            getattr(_cfg2.inference, "config_version", 0) or 0, 2
                        )
                        _sc2(_cfg2)
                        logger.info(
                            "[AgentKernel] persisted provider %r to config "
                            "(kind=%s model=%r) â€” survives restart",
                            _inst_id, _kind.name, _inst_model,
                        )
                    except Exception as _pp_err:
                        logger.warning(
                            "[AgentKernel] provider persist failed for %r: %s "
                            "(live registry still updated)", _inst_id, _pp_err,
                        )
                    if preserve_bindings:
                        # confirm_card path: role_bindings (set by the Brain/Tool
                        # dropdowns / chat ModelSwitcher via set_role_binding) are
                        # canonical. Do NOT rebind them here â€” a stale provider
                        # from the card must not clobber the user's selection.
                        # Only ensure the provider is registered.
                        logger.info(
                            f"[AgentKernel] set_model_selection(preserve_bindings=True) "
                            f"registered provider '{_inst_id}' without touching role bindings"
                        )
                    else:
                        # Explicit selection (Dashboard Models card): bind roles so
                        # resolve("reasoning") / resolve("tool_execution") succeed.
                        # The overrides use the SANITIZED models â€” a foreign or
                        # blank model must not survive as a role override either,
                        # or generate() would send it to the new provider.
                        _r.bind_role("reasoning", _inst.id, model_override=_inst_model)
                        if _tool_model and _tool_model != _inst_model:
                            _r.bind_role("tool_execution", _inst.id, model_override=_tool_model)
                        else:
                            _r.bind_role("tool_execution", _inst.id, model_override=_inst_model)

            # Emit updated context-window usage so the ContextPill reflects the
            # newly-selected model's real window immediately on switch (not only
            # after the next message). REQ-12 AC2: same event contract as the
            # per-response emit in process_text_message.
            try:
                self._emit_context_usage()
            except Exception:
                pass

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

    def set_role_binding(self, role: str, instance_id: str, model_override: Optional[str] = None) -> bool:
        """
        Bind a role (reasoning / tool_execution) to a registered provider instance
        in the InferenceRouter, and propagate the binding to every peer kernel so
        the router mapping is consistent across all conversation threads.

        Returns False (and the gateway emits role_binding_error) when binding to
        the local instance without a model loaded.
        """
        try:
            # Normalize the legacy bare "local" id to its namespaced form
            # (REQ-4 AC1) so a partially-migrated id is never a dead binding.
            if instance_id == "local":
                _local_inst = next(
                    (i for i in self._router.registry.list() if i.id.startswith("local:")),
                    None,
                )
                if _local_inst is not None:
                    instance_id = _local_inst.id
            # Local-override is NOT a veto (REQ-5 AC4): binding to a local
            # provider whose model is not yet loaded is allowed â€” it becomes
            # live once the model loads. The gateway surfaces a status flag
            # instead of rejecting. We simply bind on the process-wide registry.
            _r = getattr(self, "_router", None)
            if _r is None:
                return False
            # THE write. The table is process-wide, so this one call is visible
            # to every kernel, every peer session, every future conversation,
            # and every subagent â€” immediately and without propagation.
            #
            # Nothing follows it. There used to be two sync blocks here: one
            # updating the module-global `_model_config_snapshot` and one
            # updating the legacy fields. Both were copies of this line's
            # effect, and both are gone â€” the snapshot with its consumer, the
            # legacy fields into properties that read the binding directly.
            # (The legacy sync was also subtly wrong: it assigned `instance_id`
            # â€” a PROVIDER id â€” into `_selected_reasoning_model`, a MODEL
            # field, so anything reading it for a model name got "cohere".)
            _r.bind_role(role, instance_id, model_override=model_override)
            return True
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to set role binding: {e}")
            return False

    def set_internet_access(self, enabled: bool) -> None:
        """
        Enable or disable agent internet access.

        Delegates to the app-wide global flag (set_global_internet_access) so that
        internet access is a single switch for all conversations, not per-kernel.
        The UI web-mode toggle flips this via iris_gateway.set_web_mode.

        Args:
            enabled: True to enable internet access, False to disable
        """
        set_global_internet_access(enabled)

    def get_internet_access(self) -> bool:
        """
        Get current internet access setting (app-wide global).

        Returns:
            True if internet access is enabled, False otherwise
        """
        return get_global_internet_access()

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

# â”€â”€ Global internet-access gate (app-wide) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Web mode is a single app-level switch, not per-conversation.  Kernels are
# created per conversation (_agent_kernel_instances), but internet access must
# apply to every kernel at once when the user toggles web mode in the UI.
# set_web_mode in iris_gateway flips this; tool_bridge gates web tools on it.
_internet_access_enabled: bool = False


def set_global_internet_access(enabled: bool) -> None:
    """Flip the app-wide internet-access gate (UI web-mode toggle)."""
    global _internet_access_enabled
    _internet_access_enabled = bool(enabled)
    logger.info(
        f"[AgentKernel] Global internet access {'enabled' if enabled else 'disabled'}"
    )


def get_global_internet_access() -> bool:
    """Return the app-wide internet-access gate state."""
    return _internet_access_enabled


# â”€â”€ Global desktop-control gate (app-wide) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Desktop control = launching the user's real browser/apps, opening files with
# their default application, locking the screen, GUI/screen automation, etc.
# Everything that reaches OUTSIDE the app sandbox.  It is OFF by default and
# only enabled when the user explicitly grants permission via the
# desktop_control dashboard card (confirm_card â†’ set_desktop_control_enabled).
# tool_bridge gates every desktop-control tool on this flag so the agent can
# NEVER reach the desktop unless the user opted in.
_desktop_control_enabled: bool = False


def set_desktop_control_enabled(enabled: bool) -> None:
    """Flip the app-wide desktop-control gate (UI desktop_control card)."""
    global _desktop_control_enabled
    _desktop_control_enabled = bool(enabled)
    logger.info(
        f"[AgentKernel] Desktop control {'enabled' if enabled else 'disabled'}"
    )


def get_desktop_control_enabled() -> bool:
    """Return the app-wide desktop-control gate state."""
    return _desktop_control_enabled


# Last-known-good swarm configuration snapshot.
# When a new session's kernel is created after swarm mode has already been
# configured, it reads from this snapshot instead of relying on peer
# inheritance (which fails if all peers were also created post-swarm).
_swarm_config_snapshot: Optional[dict] = None

# REMOVED 2026-08-16: `_model_config_snapshot`. It was a module-global copy of
# the persisted model config, stashed at startup so lazily-created kernels could
# hydrate from it. It is gone because the thing it hydrated is gone: kernels now
# read the process-wide role-binding table, which already holds the live choice.
#
# It was also the third of the five competing sources of truth for "which model
# is active", and the one that made the others hard to reason about â€” it was
# written by set_model_selection under one key spelling ("tool_execution_model")
# and read under another ("tool_model"), and its reader had been raising
# TypeError on every call since the day set_model_selection's signature changed.
# Startup seeding now happens once, in InferenceRouter._apply_config.


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
        conversation_id: Primary key â€” one kernel per conversation thread.
        session_id: Transport label for WS routing and Mycelium.
                    If None, falls back to conversation_id.

    Returns:
        AgentKernel instance for the conversation
    """
    global _agent_kernel_instances

    _sid = session_id or conversation_id

    if conversation_id not in _agent_kernel_instances:
        # DIAGNOSTIC: kernels are cached BY conversation_id, so a conversation
        # id that drifts mid-turn silently constructs a SECOND kernel and
        # orphans the first one's in-turn state (tokens, node records, DER
        # bookkeeping). That was observed live: a fresh kernel for conv-1 was
        # initialised AFTER turn 1 had already completed, while the turn itself
        # ran under session_iris. Log every construction with BOTH ids and the
        # existing keys so a mid-turn rebuild is visible instead of inferred.
        # Note some keys are pseudo-conversations by design (crawl_planner,
        # data_extractor, default) â€” those are expected; a real thread id
        # appearing twice, or appearing late, is not.
        logger.info(
            "[AgentKernel] CONSTRUCTING kernel conv=%r session=%r "
            "(existing keys: %s)",
            conversation_id,
            _sid,
            sorted(_agent_kernel_instances.keys()),
        )
        kernel = AgentKernel(
            session_id=_sid,
            conversation_id=conversation_id,
        )

        # Auto-wire Pillar 4 (Memory) â€” connects episodic/semantic memory to every session
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

        # Inherit inference BEHAVIOUR settings from any already-configured peer.
        #
        # Context: the user configures things once (in session_iris / the main UI
        # session).  Secondary sessions â€” such as session_iris_integration which is
        # created when the wake-word fires â€” are spun up lazily.  Without this,
        # a wake-word-triggered response ran with default behaviour settings.
        #
        # WHICH MODEL SERVES WHICH ROLE IS NOT COPIED HERE (2026-08-16). It used
        # to be: this block called ``set_model_selection(model_provider=peer.
        # _model_provider, ...)`` without ``preserve_bindings``, which fell
        # through to ``bind_role`` and REBOUND the process-wide role table from
        # the peer's LEGACY fields. Those fields are not updated by the gateway's
        # role-binding path, so they held the startup provider â€” and every new
        # conversation therefore reverted the user's live pick (the recurring
        # "picked cohere, sent a message, back to cerebras" bug).
        #
        # There is nothing to copy: the role table and the provider registry are
        # process-wide singletons (REQ-5), so this kernel's router already sees
        # the user's live choice the moment it is constructed. Model/provider
        # state is READ from the router (see the ``_model_provider`` /
        # ``_selected_*_model`` properties), never stored per kernel.
        #
        # Credentials likewise live on the ProviderInstance in the shared
        # registry; ``_api_key`` / ``_api_base_url`` are copied only as a
        # compatibility convenience for the remaining direct readers.
        for peer_key, peer_kernel in _agent_kernel_instances.items():
            if peer_kernel is kernel:
                continue
            if peer_kernel._model_provider in (None, "uninitialized"):
                continue
            kernel._lmstudio_endpoint = peer_kernel._lmstudio_endpoint
            if peer_kernel._api_key:
                kernel._api_key = peer_kernel._api_key
                kernel._api_key_provider = peer_kernel._api_key_provider
            if peer_kernel._api_base_url:
                kernel._api_base_url = peer_kernel._api_base_url
            kernel._thinking_style = peer_kernel._thinking_style
            kernel._response_length = peer_kernel._response_length
            kernel._reasoning_effort = peer_kernel._reasoning_effort
            kernel._tool_mode = peer_kernel._tool_mode
            logger.info(
                f"[AgentKernel] Conv '{conversation_id}' inherited inference "
                f"behaviour from '{peer_key}' "
                f"(active model comes from the shared router: "
                f"provider={kernel._model_provider!r}, "
                f"model={kernel._selected_reasoning_model!r})"
            )
            break

        if kernel._model_provider == "uninitialized":
            # If no role is bound yet and a global swarm snapshot exists,
            # auto-hydrate this kernel so it doesn't stay "uninitialized".
            if _swarm_config_snapshot is not None:
                # SLICE 5: wire the router (not the legacy compat client) so
                # DER/Pacman inference paths actually use the swarm endpoint.
                try:
                    from backend.agent.inference.provider import (
                        ProviderInstance,
                        ProviderKind,
                    )

                    _ep = _swarm_config_snapshot.get("endpoint") or ""
                    _r_model = _swarm_config_snapshot.get("reasoning_model")
                    _t_model = _swarm_config_snapshot.get("tool_model")
                    _inst = ProviderInstance(
                        id="swarm_director",
                        label="Swarm (auto-hydrated)",
                        kind=ProviderKind.LOCAL_OPENAI,
                        model=_r_model or "local-model",
                        api_base_url=_ep,
                    )
                    _router = getattr(kernel, "_router", None)
                    if _router is not None:
                        _router.add_provider(_inst)
                        _router.bind_role("reasoning", "swarm_director")
                        _router.bind_role(
                            "tool_execution", "swarm_director", model_override=_t_model
                        )
                except Exception as _sw_err:
                    logger.warning(
                        f"[AgentKernel] Swarm auto-hydrate router wire failed: {_sw_err}"
                    )
                kernel._swarm_enabled = True
                logger.info(
                    f"[AgentKernel] Conv '{conversation_id}' auto-hydrated from "
                    f"swarm snapshot (provider='iris_local', "
                    f"endpoint={_swarm_config_snapshot.get('endpoint')!r})"
                )

            # NOTE (2026-08-16): a "persisted model config snapshot" hydrate
            # used to live here, replaying `_model_config_snapshot` through
            # set_model_selection. It was removed for two reasons. First, it
            # had never run: it passed `provider=`, `thinking_style=`,
            # `response_length=` and `tool_mode=`, none of which are parameters
            # of set_model_selection, so every call raised TypeError straight
            # into the handler below it and logged "model snapshot hydrate
            # failed". Second, even working it would have been wrong â€” it
            # replayed a STORED copy of the user's choice over the live
            # process-wide role table, which is the same class of bug as the
            # peer-inheritance rebind above. Startup seeding belongs in
            # InferenceRouter._apply_config, which now binds only unbound roles.

        _agent_kernel_instances[conversation_id] = kernel

    return _agent_kernel_instances[conversation_id]


# â”€â”€ Session â†’ active conversation registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Wave 5 (session-conversation-switching spec): eliminates the phantom
# "default" kernel.  Callers that only knew a session_id (e.g. a wake-word
# voice path, a reconnect, a REST chat request) were calling
# get_agent_kernel(session_id=...) which fell back to conversation_id="default",
# creating a kernel the active thread never used.  The gateway owns the
# authoritative sessionâ†’active-conversation binding (_active_conversation_id);
# it mirrors that binding here (module-level, no circular import) so any
# caller can resolve the *real* active kernel for a session via
# get_active_kernel(session_id) instead of spawning a "default" ghost.
_session_active_conversation: dict = {}


def set_active_conversation(
    session_id: str, conversation_id: Optional[str]
) -> None:
    """Mirror the gateway's sessionâ†’active-conversation binding into this
    module-level registry.  Called by the gateway whenever it (re)points a
    session at a conversation (new_conversation / switch_conversation /
    sync_state / voice_command_start / connect).

    ``conversation_id=None`` UNBINDS the session â€” the state "the user left a
    thread and has not started the next one yet".  Leaving a stale binding in
    place is what let a wake word or a reconnect resolve back into the thread
    the user had just walked away from, so the absence of a thread has to be
    representable, not approximated by the session id."""
    global _session_active_conversation
    if not session_id:
        return
    if conversation_id:
        _session_active_conversation[session_id] = conversation_id
    else:
        _session_active_conversation.pop(session_id, None)


def get_active_kernel(session_id: str) -> "AgentKernel":
    """Resolve the kernel for a session's *currently active* conversation.

    Falls back to conversation_id="default" only when no active conversation
    has been registered for the session (e.g. a brand-new session before the
    first new_conversation / sync_state).  This is the correct replacement for
    the old get_agent_kernel(session_id=...) pattern that silently created a
    phantom "default" kernel disconnected from the active thread.
    """
    conv_id = _session_active_conversation.get(session_id) or "default"
    return get_agent_kernel(conversation_id=conv_id, session_id=session_id)


def peek_active_kernel(session_id: str) -> "Optional[AgentKernel]":
    """Non-constructing variant of ``get_active_kernel``: return the kernel
    for a session's currently active conversation IF one already exists,
    else ``None``.

    Never constructs a kernel.  ``get_agent_kernel`` builds a full
    ``AgentKernel`` when absent (measured 71.81s cold on 2026-08-12), which
    made read-only paths (``/api/inference/state``, ``request_state``) time
    out on page loads racing backend startup.  Callers that only read router
    state (inference snapshot, status broadcast) MUST use this instead so a
    read can never pay kernel-construction cost.  ``build_inference_snapshot``
    already accepts ``None`` and returns the full key set with empty
    providers, so a missing kernel degrades gracefully, never errors.
    """
    conv_id = _session_active_conversation.get(session_id) or "default"
    return _agent_kernel_instances.get(conv_id)


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
