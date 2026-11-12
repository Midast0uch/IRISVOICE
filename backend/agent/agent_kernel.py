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
# REMOVED 2026-08-26 (session 260): `from backend.llm_service import llm as _llm`.
# MEASURED with `python -X importtime`: that import pulled in litellm, which was
# 6.26s of a 9.63s total -- 65% of the cost of importing this module -- and
# `_llm` was NEVER USED. Its only remaining mention is the docstring below at
# _dispatch_api: "Uses httpx directly instead of _llm.complete() to avoid
# thread-pool hangs." The code was deliberately moved onto httpx and the import
# was left behind. Nothing imports `_llm` from this module (checked).
#
# This is not only a test-suite problem. backend startup imports this module, so
# the same 6.26s was paid on every launch.
from . import streaming as _streaming
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.errors import RateLimitedError
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
# GROUND TRUTH REQ-13: named counters for swallowed write-path failures.
# Pure in-process tally (threading only) - safe at module scope.
from backend.agent import write_counters as _write_counters
from backend.agent import row_sequence as _row_sequence






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






















































def _turn_end_submit(owner, session_id: str, job) -> None:
    """C5: run the turn-end bookkeeping (card footprint, plan stats, episode
    + landmark crystallization, skill capture) on lane("memory_events"), the
    store's ordered writer, instead of before the reply's synthesis (measured
    2-8.5 s per task, 2026-10-01). The next turn of this kernel folds back on
    ``owner._turn_end_pending`` before it reads memory. A dropped submit (lane
    full) runs the job inline: an episode is never lost. Module level on
    purpose (stand-in kernels)."""
    import threading as _th

    done = _th.Event()

    def _run():
        try:
            job()
        except Exception as exc:  # noqa: BLE001 - each part logs its own failure
            logger.warning("[DER] turn-end bookkeeping failed session=%s: %r", session_id, exc)
        finally:
            done.set()

    owner._turn_end_pending = done
    from backend.utils.durability_queue import lane

    if not lane("memory_events").submit("turn_end", _run):
        logger.warning("[DER] turn-end lane full session=%s - bookkeeping inline", session_id)
        _run()
























def _der_budget_exit(tokens_used: int, token_budget: int, elapsed_s: float,
                     turn_budget_s: float, queue) -> Optional[str]:
    """Which budget cut the DER loop short: "tokens", "turn_time" or "steps"; None
    when the plan ran to the end. Mirrors the loop condition, so the BUDGET_HIT
    event is typed by the SAME test that stopped the loop. Module level (stand-ins)."""
    if queue.is_complete():
        return None
    if tokens_used >= token_budget:
        return "tokens"
    if elapsed_s >= turn_budget_s:
        return "turn_time"
    if queue.hit_cycle_limit():
        return "steps"
    return None






def _der_topology_halt(owner, session_id: str) -> None:
    """Stop the line on a TOPO_VIOLATION (rec==3) at a step boundary.

    The rec==3 raise inside the physics job never reached the loop: finalize's
    broad except (later the lane job) swallowed it, and every shape-decision
    read sits inside an advisory try â€” so _der_execute_with_recovery's targeted
    recovery never ran in production (MCM pin_22b078571d73, option B). Called
    on the loop thread OUTSIDE any broad except. Reads only a LANDED update â€”
    never waits (S3: the answer path does not wait for its physics); a later
    landing is caught at the next boundary. Raises once per update, so the
    recovery run does not halt again on the same stale state.
    """
    pending = getattr(owner, "_der_physics_pending", None)
    fold = pending.get(session_id) if pending else None
    if fold is None or not fold.ready.is_set() or fold.rec != 3:
        return
    with fold.lock:
        if getattr(fold, "halted", False):
            return
        fold.halted = True
    from backend.agent.exceptions import TopologyViolationException

    logger.warning(
        "[DER] TOPO_VIOLATION landed session=%s step=%s - halting for recovery",
        session_id, getattr(fold, "step", None),
    )
    _emit_event(owner, "HALTED", evidence="verifier", thread_id=session_id,
                step_index=str(getattr(fold, "step", "") or ""),
                payload={"cause": "TOPO_VIOLATION"})
    raise TopologyViolationException(session_id=session_id)







# Session 247: turn wall-clock safety net (seconds). Defined UNCONDITIONALLY
# (outside the der_constants import guard) so it exists on both import paths.
# See the DER main loop â€” last-resort bound only; the sufficiency gate and
# zero-yield cutoff are the rational stops, this catches everything else.
_DER_TURN_BUDGET_S = float(os.environ.get("IRIS_DER_TURN_BUDGET_S", "600"))


























# â”€â”€ Parallel-node scheduler helpers (module level on purpose: stand-in
# kernels bind only some methods - a helper on the class would be auto-stubbed
# and the loop would silently skip the real code). `self` is the kernel. â”€â”€




















# <kernel-split:imports> generated by scripts/kernel_split_check.py move; do not edit by hand
from backend.agent.kernel.base import (
    AVG_STEP_COST,
    DER_EMERGENCY_STOP,
    DER_FOLD_BACK_MAX,
    DER_MAX_CYCLES,
    DER_MAX_GRAFTS,
    DER_MAX_UNVERIFIED_REPROPOSE,
    DER_MAX_VETO_PER_ITEM,
    DER_TOKEN_BUDGETS,
    ExecutionMode,
    ResolvedWindow,
    _CLAIM_LOCKS,
    _CLAIM_LOCKS_GUARD,
    _DER_NODE_QUOTA,
    _DER_PARALLEL,
    _FILL_NO_TURN,
    _NODE_CLAIMS,
    _SCREEN_CLAIM,
    _STEP_ID_KEYS,
    _der_fold_envelope,
    _der_ledger_storage_path,
    _der_recall_delivered,
    _der_recovery_lock,
    _emit_event,
    _memory_events_submit,
    _step_calls,
    _step_decisive_call,
    _step_evidence_cap,
    _step_tool,
    _turn_in_flight,
    _update_counters,
    _update_counters_lock,
    debit_work_units,
    derive_work_units_0,
    logger,
    resolve_der_token_budget,
)
import backend.agent.kernel.base as _k_base
from backend.agent.kernel.models import (
    _resolve_effective_key,
    ModelsMixin,
)
import backend.agent.kernel.models as _k_models
from backend.agent.kernel.surface import (
    _stamp_row_seq,
    SurfaceMixin,
)
import backend.agent.kernel.surface as _k_surface
from backend.agent.kernel.context import (
    _dedupe_fact_lines,
    _dedupe_fact_rows,
    _fact_line,
    _recent_user_turn_texts,
    _same_fact_unit,
    ContextMixin,
)
import backend.agent.kernel.context as _k_context
from backend.agent.kernel.turn import (
    _BROWSER_ACTION_RE,
    _LIVE_BROWSER_RE,
    _TURN_END_FOLD_WAIT_S,
    _developer_mode,
    _turn_end_settle,
    TurnMixin,
)
import backend.agent.kernel.turn as _k_turn
from backend.agent.kernel.planning import (
    _VOICE_TURN_NOTE,
    _plan_step_deps,
    _voice_turn_note,
    PlanningMixin,
)
import backend.agent.kernel.planning as _k_planning
from backend.agent.kernel.der.finalize import (
    DER_SUBLOOP_BRANCH_LABEL,
    _MONITOR_STATEMENT_CHARS,
    _der_post_step,
    _der_prior_research_delivered,
    _edit_diff_fields,
    _gc_coverage_label,
    _monitor_statement,
    _mycelium_ingest_step_tools,
    _node_failed_after_change,
    _remember_turn_urls,
    _step_digest,
    _step_tool_name,
    DerFinalizeMixin,
)
import backend.agent.kernel.der.finalize as _k_der_finalize
from backend.agent.kernel.der.node import (
    _NODE_CORE_TOOLS,
    _der_claim,
    _der_claim_lock,
    _der_node_domain,
    _der_node_load,
    _der_release,
    _der_start_node,
    _der_take_finished,
    _narrow_node_tools,
    _node_call_parallel_ok,
    _node_claim_of,
    DerNodeMixin,
)
import backend.agent.kernel.der.node as _k_der_node
from backend.agent.kernel.der.physics import (
    _der_physics_settle,
    _der_settle_split,
    DerPhysicsMixin,
)
import backend.agent.kernel.der.physics as _k_der_physics
from backend.agent.kernel.der.recovery import (
    _plan_steps_open,
    _recovery_candidates,
    DerRecoveryMixin,
)
import backend.agent.kernel.der.recovery as _k_der_recovery
from backend.agent.kernel.der.report import (
    TaskContext,
    _CLAIMS_MISSING_RE,
    _READABLE_FORMAT_RULES,
    _STUB_STOPWORDS,
    _claims_missing,
    _der_neighbors_block,
    _short_reply_carries_results,
    DerReportMixin,
)
import backend.agent.kernel.der.report as _k_der_report
# </kernel-split:imports>

class AgentKernel(ModelsMixin, SurfaceMixin, ContextMixin, TurnMixin, PlanningMixin, DerFinalizeMixin, DerNodeMixin, DerPhysicsMixin, DerRecoveryMixin, DerReportMixin):
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
        # In-process `LocalModelManager` binding â€” non-None when iris_gateway
        # has loaded a model via the in-process path. `_get_lmstudio_client()`
        # checks this before creating a real HTTP client; when set AND the
        # provider is `iris_local`, inference goes through the manager's
        # `InProcessOpenAIAdapter` with zero network hops.
        self._inprocess_local_mgr: Any = None

        # T17 (REQ-1 AC1.3): in-flight goal references, keyed by conversation
        # id. Set at plan start; follow-up voice turns mutate the live goal
        # through this â€” never fork into a new plan. Initialized lazily so
        # test doubles built via `__new__` (which never call __init__) still
        # find the attribute.
        self._active_goals = getattr(self, "_active_goals", None) or {}

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
        # Context window (2026-09-27): the router asks us for the window of the
        # role it is about to call, so it can (a) offer it to a provider that is
        # able to set one - Ollama, as options.num_ctx - and (b) cap the prompt
        # for the providers that cannot, where the window is fixed and the only
        # thing we control is how much we send. The resolver is our own method
        # on purpose: the window table lives in THIS class, and a copy inside
        # the router would drift away from it. Router-side failures degrade to
        # "no window known" and never break a turn.
        self._router.set_window_resolver(self.resolve_context_window)
        # Wedge fix (session 363, pin_35af67d07c5f): the router calls us back
        # at every model-dispatch entry and inside the transport retry
        # ladders, so the turn budget + client check run INSIDE the blocking
        # paths. The DER loop condition only evaluates BETWEEN cycles, so a
        # turn blocked inside ONE operation never re-evaluated it and the
        # 600 s budget never fired (chain client w1 ran 19+ min while the
        # backend logged nothing for 18). The check is a bound method of THIS
        # kernel â€” the router is per-kernel (not a singleton), so there is no
        # cross-session leakage â€” and it reads per-turn state set in
        # _execute_plan_der. Modeled on set_window_resolver directly above.
        self._router.set_turn_budget_check(self._turn_choke_check)
        # In-process local models (2026-09-27). The gateway attaches the local
        # model manager to the routers that EXIST when a model is loaded, so a
        # kernel created LATER (a new WS session) starts with
        # `_inprocess_mgr = None` and every `local:<model>` planning call dies:
        #   [AgentKernel._plan_task] router planning failed:
        #     No local model loaded for in-process inference
        # No plan means no DER, so the step consumers (review_verdict,
        # sufficient, done, on_track, has_gaps, needs_action,
        # recovery_strategy) never ran and could never reach the Wave 7 bar no
        # matter how much traffic was driven. The manager is a process-wide
        # singleton, so attach it here instead of depending on load-time fan-out
        # reaching every future kernel. get_local_model_manager() constructs the
        # manager object only; it loads no weights.
        try:
            from .local_model_manager import get_local_model_manager

            self._router.set_inprocess_manager(get_local_model_manager())
        except Exception as _mgr_err:  # noqa: BLE001 â€” a missing manager is not fatal
            logger.debug(
                "[AgentKernel] in-process manager attach skipped: %s", _mgr_err
            )

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
        # D3 (2026-10-31): set at the top of every turn (process_text_message).
        self._turn_started_monotonic: float = 0.0

        # â”€â”€ DER Loop components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # DER_MAX_CYCLES / DER_MAX_VETO_PER_ITEM re-exported at module level
        # for spec compliance (Gap 11). Canonical values live in der_constants.
        self._task_classifier = None
        self._reviewer = None
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
            # The `mode` Oracle consumer was REMOVED 2026-10-10 (owner): the
            # detector keeps its keyword classifier only â€” no engine wiring, no
            # row sink (see mode_detector.py).
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

        # REQ-14 AC14.1 / REQ-29 (T18, T46-T49): install the shadow-row sink.
        # The monitor and surface consumer modules emit their rows to a
        # module-level sink, and NOTHING installed one in production â€” every
        # row fell through to a log line, so no calibration row ever persisted
        # and TG-6's parity clause plus Wave 7's >=100-row flip bar were
        # structurally unreachable. The sink is the SAME single-writer ledger
        # the dispatched decisions use, so one reader sees every consumer.
        try:
            from backend.agent import explorer as _ex_rows
            from backend.agent import monitor_shadow as _ms_rows

            _shadow_sink = self._shadow_row_sink
            _ms_rows.set_row_sink(_shadow_sink)
            # web_intent (2026-09-27): this consumer had criteria and a live call
            # site but no row path at all, so it could never be scored however
            # often it ran. Same single-writer sink as the other two.
            _ex_rows.set_row_sink(_shadow_sink)
            # click_safety (W2): the browser click gate's Oracle shadow rows.
            from backend.agent import click_safety_shadow as _cs_rows

            _cs_rows.set_row_sink(_shadow_sink)
            # event taxonomy step 3: user_feedback / event_family / event_type:*.
            from backend.agent import event_oracle as _eo_rows

            _eo_rows.set_row_sink(_shadow_sink)
            # tool_approval (safety, 2026-11-10): rows from the user's answers
            # to permission prompts. Same single-writer sink.
            from backend.agent import tool_approval_shadow as _ta_rows

            _ta_rows.set_row_sink(_shadow_sink)
            # browser_next (2026-10-11): the element-choice consumer.
            from backend.agent import browser_next_shadow as _bn_rows

            _bn_rows.set_row_sink(_shadow_sink)
            # page_relevance / page_blocked (2026-11-10): the research-path
            # page questions (crawler shadow consults). Same sink.
            from backend.agent import page_shadow as _ps_rows

            _ps_rows.set_row_sink(_shadow_sink)
            # REQ-14 (Wave 5): resolved OUTCOME-labelled rows (the deferred
            # registry) land on the SAME single-writer sink.
            from backend.agent import decision_engine as _de_rows

            _de_rows.set_outcome_sink(_shadow_sink)
            logger.info(
                "[AgentKernel] shadow row sink installed "
                "(monitor + web_intent + the other consumers)"
            )
        except Exception as _sink_err:  # noqa: BLE001 â€” advisory
            logger.warning(
                f"[AgentKernel] shadow row sink install failed: {_sink_err}"
            )

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

    # â”€â”€ T17 (REQ-1 AC1.3): follow-up mutation wiring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # A voice/text interruption lands on the LIVE GoalAnatomy â€” never a side
    # plan. Each mutation is logged in memory_anchors so the audit trail
    # shows who changed what.


















    # â”€â”€ Context window resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Every model has a maximum context window.  Memory, conversation history,
    # and MCM budgets should be derived from it â€” never hardcoded.


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
        # Qwen 3.8 27B replaces gemma as the Cerebras offering 2026-09-04.
        # Catalog context is 64k free / 128k paid.
        # CORRECTED 2026-09-05: this is 64_000, not the 128_000 paid tier.
        # Evidence, not an assumption â€” api.cerebras.ai answers every request
        # with 402 "Payment required to access this resource. Visit your
        # billing tab." (type=payment_required_error), i.e. no paid plan is
        # active, so only the 64k free-tier window is actually served.
        # Direction of error matters: the budget is sized at window*0.9, so
        # 128_000 provisions 115.2k against a 64k window and the overage is
        # silently truncated mid-conversation. Under-sizing is safe;
        # over-sizing is the bug (same rule as the gemma row above).
        # Revert to 128_000 only if Cerebras billing is actually enabled.
        # The gemma row above stays: still-true model fact, pinned by the
        # ctx-budget contract tests. ClinePass models stay unlisted on
        # purpose (windows unverified) and take the safe 8k default.
        ("cerebras", "qwen-3.8-27b", 64_000),
        # Inception mercury-2.5: 260_000 is the window Inception itself published in
        # its /models list (logged 2026-10-02 and 2026-10-25, "budget=26000 from
        # window=260000"). On 2026-10-26 /models listed only mercury-3 and
        # mercury-decide - mercury-2.5 still answers but is no longer listed - so
        # the API lookup (case 2b) found nothing, every thread fell to the 8_192
        # default and the chat's context pill went red after one prompt. Evidence,
        # not a guess; case 2b still wins whenever the provider lists the model.
        ("inceptionlabs", "mercury-2.5", 260_000),
        # mercury-3: Inception's /models published context_length 1000000 (2026-10-26).
        ("inceptionlabs", "mercury-3", 1_000_000),
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
        # ADDED 2026-09-27. Value read from the running Ollama server's own
        # /api/show on 2026-09-27: gemma4.context_length = 262144 -- same method
        # and same rule as the rows above (the server is the authority, not a
        # model card or memory).
        #
        # What it cost while missing: this is the model the reasoning role is
        # bound to, and no "local" row matched it, so both roles logged
        # "WARN source=default: no context window known for provider=local
        # model=gemma4:31b-cloud -- falling back to 8192" and a 262144-token
        # window was budgeted as 8192, a 32x under-provision. Under-sizing does
        # not truncate, but it ends a long task early with "Token budget
        # exhausted" -- the same failure the gpt-oss note above describes at the
        # same ratio, which is the evidence that this row is worth having.
        #
        # Row order: "gemma2" (above) and "gemma4" do not collide -- first match
        # wins on a substring test, and neither string contains the other.
        ("local", "gemma4", 262_144),
        # OpenCode Zen (opencodego). The live /models endpoint 403s, so the
        # window was MEASURED instead of guessed: deepseek-v4.1-flash accepted
        # a 720k-token prompt (2026-11-03) and OpenRouter lists 1048576 for
        # the same model id. 128k is the value recorded here on purpose: the
        # rule of this table is "under-sizing is safe, over-sizing is the
        # bug" (the budget is window*0.75, so a too-high window over-commits
        # the prompt). 128k is 15x the 8192 default that every opencodego
        # model fell through to before this row, and it ends the message
        # dropping that the 8192 budget caused ("prompt over the window:
        # window=8192 budget=3840 dropped_messages=6").
        ("opencodego", "", 128_000),
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

    def _bound_external_project(self) -> str:
        """The turn's bound workdir when it is outside the IRIS repo, else ""."""
        try:
            _sess = getattr(self, "_turn_session_id", None) or self.session_id
            _wd = (getattr(self._tool_bridge, "_session_workdirs", None) or {}).get(_sess) or ""
            if not _wd:
                return ""
            _repo = os.path.normcase(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            _norm = os.path.normcase(os.path.abspath(_wd))
            return "" if _norm == _repo or _norm.startswith(_repo + os.sep) else _wd
        except Exception:
            return ""


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

            # Recurrence (owner 2026-10-01): a skill is a recipe that repeats.
            # Count successful episodes of similar tasks with the SAME call
            # shape (tools in first-use order); this run's own episode was
            # stored just before, so it counts once. A rerun of the same task
            # updates its episode instead of adding one, so reruns do not count.
            from backend.agent.workflow_capture import distinct_tool_names

            _shape = distinct_tool_names(successful)
            _recurrences = 0
            try:
                for _ep in memory.episodic.retrieve_similar(task_summary, limit=10) or []:
                    _seq = _ep.get("tool_sequence") or []
                    if isinstance(_seq, str):
                        _seq = json.loads(_seq)
                    _ok = [s for s in _seq if isinstance(s, dict) and s.get("success", False)]
                    if distinct_tool_names(_ok) == _shape:
                        _recurrences += 1
            except Exception as _rec_exc:  # noqa: BLE001 - no count, no capture
                logger.debug("[AgentKernel] skill recurrence count failed: %r", _rec_exc)
                _recurrences = 0

            key = capture_workflow(
                tool_sequence=successful,
                memory=memory,
                existing_skills=existing_skills,
                is_registered=lambda n: resolve_tool(n) is not None,
                recurrences=_recurrences,
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

    # Endpoints observed to reject the thinking hint. Populated at runtime so a
    # strict provider is asked exactly once and never again this process.
    _THINKING_HINT_REFUSED: set = set()






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







    # ------------------------------------------------------------------ #
    # Dispatch methods
    # ------------------------------------------------------------------ #




    # Word count above which we consider a reply "long" for TTS purposes.
    # Only applied to DOCUMENT-like content; conversational replies are always spoken in full.
    _SPOKEN_WORD_LIMIT: int = 40
    # Maximum spoken word count for document summaries (hard cap).
    _SPOKEN_MAX_WORDS: int = 80


    # â”€â”€ Tool definitions for OpenAI-compatible function calling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€



    # â”€â”€ ReAct agentic loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # REQ-28: threshold above which the first-sentence rule below stops being
    # an acceptable spoken form. Same number prepare_spoken_text already uses
    # for its ">120 words" branch, named once so the two cannot drift.
    SPOKEN_BRIEF_WORD_THRESHOLD = 120




    # ------------------------------------------------------------------
    # Issue C.1 â€” structured speak/show response contract
    # ------------------------------------------------------------------












    # â”€â”€ W9 (O3): proactive structured-data capture from ANY tool result â”€â”€â”€â”€â”€â”€
    # Plan W9: extend capture beyond `show` payloads to any tool result
    # (web_search, crawler_query, read_file, ...) so everything the agent
    # touches becomes reformat-able via the same DocumentDataStore. Scoped by a
    # relevance/structure threshold so trivial results are not embedded.

    _MIN_CAPTURE_CHARS = 50       # below this, a result is "trivial"
    _RELEVANCE_THRESHOLD = 0.30   # results carrying a score below this are skipped





    # â”€â”€ W10 (O4): pheromone-reinforced reformat + cross-modal synergy â”€â”€â”€â”€â”€â”€â”€â”€
    # Plan W10: reinforce the reformat action's pheromone edge when used, so
    # frequently-reformatted doc types become "sticky" (the agent can proactively
    # offer a reformat), and expose cross-modal views (vocalize / diagram) that
    # reuse existing channels (SpeakTool, reformat_document's diagram format).

























    def _note_tool_wait(
        self, *, tool_name: str, wait_id: str, turn_id=None, session_id=None
    ) -> None:
        """Open a narratable tool wait (REQ-10 AC10.11, T13). Never raises.

        Entry lines speak only for known-long waits; every wait carries its
        stated budget so an expectation-miss line fires if crossed with no
        result. Exit (TOOL_RESULT/ERROR site) stays silent â€” results voice
        via the reply path.
        """
        try:
            from backend.agent.conversation_kernel import get_conversation_kernel

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is None:
                return
            name = (tool_name or "").lower()
            # Budgets mirror tool_bridge.py:933 (60s vision/gui_automation,
            # else 30s). Entry lines are for known-long waits: the 60s class
            # plus crawl (multi-fetch runs long in practice).
            long_wait = ("vision" in name) or ("gui" in name) or ("crawl" in name)
            budget = 60.0 if (("vision" in name) or ("gui" in name)) else 30.0
            scheduler.note_wait(
                wait_id,
                turn_id=turn_id or "unknown",
                session_id=session_id or "unknown",
                budget_s=budget,
                long_wait=long_wait,
            )
        except Exception:  # noqa: BLE001 â€” narration never blocks tool runs
            pass

    def _end_tool_wait(self, wait_id: str) -> None:
        """Close a narratable tool wait (REQ-10 AC10.11, T13). Never raises."""
        try:
            from backend.agent.conversation_kernel import get_conversation_kernel

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is not None and wait_id:
                scheduler.end_wait(wait_id)
        except Exception:  # noqa: BLE001
            pass











    def _session_has_client_for(self, session: Optional[str]) -> bool:
        """WS disconnect check for *session* - True if at least one live
        client, or on any failure (fail-open, "connected"). Wedge fix
        (session 363): extracted from the closure inside _execute_plan_der so
        _turn_choke_check (a method, which cannot see that closure) runs the
        same check inside the transport retry ladders.
        """
        try:
            from backend.ws_manager import get_websocket_manager

            ws = get_websocket_manager()
            if ws is None:
                return True  # no WS manager: non-WS path, keep running
            # Conversation / thread IDs used as kernel sessions:
            # The WS handler (iris_gateway.py:4450) passes the WS client ID
            # as session_id and the conversation/thread ID as conversation_id,
            # so thread IDs never appear as the kernel session there.
            # The REST handler (chat.py:305) uses the thread/conversation ID
            # as the kernel session_id - these sessions have no WS client and
            # must keep running (their output is returned synchronously).
            if isinstance(session, str) and (
                session.startswith("immortus:") or session.startswith("conv_")
            ):
                return True
            # The prefix list above is a NAMING check, and it silently
            # stopped matching: chat.py mints thread ids as "conv-1"
            # (hyphen) while this only ever accepted "conv_" (underscore).
            # Every REST search therefore hit the disconnect branch and the
            # DER loop broke before executing step 1 - surfacing to the user
            # as "no usable sources found", a network failure that never
            # happened. e2e was ~536 ms with no crawl in the log.
            #
            # Test the STRUCTURE instead of the spelling. chat.py:308 passes
            # session_id=thread_id=conversation_id, whereas the WS handler
            # passes the client id as session_id and the thread id as
            # conversation_id (see the comment above), so the two are equal
            # only on the REST path. That holds regardless of how ids are
            # spelled, so renaming them cannot silently re-break this.
            if isinstance(session, str) and session == getattr(
                self, "conversation_id", None
            ):
                return True
            return len(ws.get_clients_for_session(session)) > 0
        except Exception:
            return True

    def _turn_choke_check(self) -> None:
        """Wedge fix (session 363, pin_35af67d07c5f): choke-point check called
        at every model-dispatch entry (InferenceRouter.generate) and inside
        the transport retry ladders and stream chunk loops. The DER loop
        condition only evaluates BETWEEN cycles, so a turn blocked inside ONE
        operation never re-evaluated it and the 600 s budget never fired
        (chain client w1 ran 19+ min; the backend logged nothing for 18).
        Latches _der_stop_requested BEFORE raising so the loop exits to
        synthesis over completed steps even if a caller catches the error -
        the same contract the loop condition already assumes. Inert unless a
        DER turn is active (_der_turn_active), so a stale start time from a
        finished turn can never raise on a healthy non-DER call.
        """
        if not getattr(self, "_der_turn_active", False):
            return
        start = getattr(self, "_der_start_time", None)
        if start is not None and (time.perf_counter() - start) >= _DER_TURN_BUDGET_S:
            self._der_stop_requested = True
            raise RuntimeError(
                f"[DER] turn budget ({_DER_TURN_BUDGET_S:.0f}s) exhausted - "
                "aborting to synthesis over completed steps"
            )
        session = getattr(self, "_der_session", None)
        if session is None:
            return
        # The client check is throttled: the stream chunk loops call this per
        # SSE line, so the WS lookup must not run per line. Re-check at most
        # every 5 s; the budget half above is nanoseconds-cheap and always
        # runs.
        now = time.perf_counter()
        if now - getattr(self, "_der_last_client_check", 0.0) < 5.0:
            return
        self._der_last_client_check = now
        if not self._session_has_client_for(session):
            self._der_stop_requested = True
            raise RuntimeError(
                "[DER] session has no connected clients - aborting to "
                "synthesis over completed steps"
            )

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
        budget_class: Optional[str] = None,
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
        # Wedge fix (session 363, pin_35af67d07c5f): the turn start lives on
        # the INSTANCE too â€” _turn_choke_check is reached from the router and
        # the transports, which cannot see this local. _der_session and
        # _der_turn_active scope the check to THIS turn: without the active
        # flag a stale start time from a FINISHED turn would raise on a
        # healthy non-DER call that runs more than the budget after the turn
        # ended. _der_last_client_check throttles the WS lookup in
        # _turn_choke_check â€” the stream chunk loops call it per SSE line.
        self._der_start_time = _der_start_time
        self._der_session = _session
        self._der_turn_id = _turn_id
        self._der_turn_active = True
        self._der_last_client_check = 0.0

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
        # Session 247: budget sizing uses budget_class (the planner MODE name,
        # e.g. "implement") while task_class stays the classifier's label for
        # every decision. See the call site in the DER entry path.
        _token_budget: int = resolve_der_token_budget(
            _model_window, budget_class or task_class
        )
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
                # T5 (specs/tool-result-envelope): planner-declared
                # criticality rides the queue item â€” intent only until the
                # finalize site confirms it (AC1.6).
                declared_criticality=getattr(step, "criticality", "supporting") or "supporting",
                # 2026-10-19: carry the planner's declared product onto the node.
                # It was dropped here, so every node item had expected_output=None
                # (the verifier had nothing to check; the needs_action Oracle saw
                # a goal with no artifact).
                expected_output=getattr(step, "expected_output", None) or None,
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
        # Taxonomy CONTROL: the plan is accepted. Episode id = Wave E's task id.
        self._event_episode_id = f"{_session}:{_turn_id or ''}"
        _plan_rec = getattr(items[0], "node_record", None) if items else None
        _emit_event(
            self, "PLAN_MADE", thread_id=_session,
            exec_domain=getattr(_plan_rec, "execution_domain", None),
            topic_domain=getattr(_plan_rec, "topic_domain", None),
            payload={"steps": len(items), "strategy": getattr(plan, "strategy", None),
                     "task_class": task_class},
        )

        # â”€â”€ Goal contract T4 (specs/goal-contract-coverage, REQ-1) â”€â”€
        # Build the deterministic required-fact set once per turn, validate
        # the plan against it (an omission is re-added by construction â€” the
        # deterministic set stands alone â€” and logged with the fact text),
        # and stamp required_facts on every step's node record. Advisory:
        # never break plan start on a contract failure.
        self._goal_contract_state = None
        try:
            from backend.agent import goal_contract as _gc_mod

            _gc_facts = _gc_mod.extract_required(plan.original_task or "")
            _gc_omitted = _gc_mod.map_to_steps(_gc_facts, list(plan.steps))
            for _om_fact in _gc_omitted:
                logger.info(
                    "[goal-contract] planner omitted fact, re-added: %r",
                    str(_om_fact)[:160],
                )
            _gc_task_rec = NodeRecord(
                step_id=f"task:{(_turn_id or _session or 'turn')}",
                parent_step_id="",
                node_type="task",
                objective_anchor=plan.original_task or "",
                expected_output=plan.original_task or "",
                required_facts=list(_gc_facts),
                contract_version=1,
            )
            for _gc_item in items:
                try:
                    if getattr(_gc_item, "node_record", None) is not None:
                        _gc_item.node_record.required_facts = list(_gc_facts)
                except Exception:
                    pass
            self._goal_contract_state = {
                "turn_id": _turn_id,
                "contract": _gc_mod.Contract(
                    required=tuple(_gc_facts), ceiling=(), version=1
                ),
                "task_record": _gc_task_rec,
                "covered": [],
                "outcomes": [],
                "results": [],
                "C": 0.0,
                "g": 1.0,
                "prev_c": 0.0,
                "prev_tokens": 0,
                "unmoved": 0,
                "stall_cycles": 0,
                "stalled": False,
                "rho": 0.0,
                # Wave 3 (T7/T8/T9/T10): amendment log, blocked list, REQ-7
                # counters. All advisory â€” absent = legacy behavior.
                "blocked": [],
                "amendments": [],
                "counters": {
                    "facts_seeded": len(_gc_facts),
                    "facts_mapped": len(_gc_facts) - len(_gc_omitted),
                    "facts_readded": len(_gc_omitted),
                    "facts_covered": 0,
                    "facts_blocked": 0,
                    "amendments_user": 0,
                    "amendments_agent": 0,
                    "stalls": 0,
                    "bonus_passes": 0,
                },
            }
            logger.info(
                "[goal-contract] contract built: %d required facts (%d "
                "omitted by planner, re-added)",
                len(_gc_facts), len(_gc_omitted),
            )
        except Exception as _gc_exc:
            logger.debug("[goal-contract] build skipped: %s", _gc_exc)
            self._goal_contract_state = None

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

        # â”€â”€ Card gate (owner bound, 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # A card is for MORE THAN THREE tool steps, and never for an artifact ask
        # (the artifact IS the visible result). Below the bound the turn still
        # runs through DER, the tools still fire and a real artifact still
        # renders â€” only card-lifecycle events are withheld, by the WS bridge
        # and by _persist_card_snapshot, both keyed on artifact_policy's gate.
        try:
            from backend.agent.artifact_policy import (
                MIN_TOOL_STEPS_FOR_CARD,
                card_warranted,
                clear_card_free_conversation,
                is_artifact_ask,
                suppress_card_for_conversation,
                tool_step_count,
            )

            _artifact_ask = is_artifact_ask(plan.original_task or "")
            self._current_task_text = plan.original_task or ""
            # The card bound is a personal-mode rule (see _developer_mode).
            self._der_card_hold = None
            if card_warranted(items, plan.original_task or "") or _developer_mode(self):
                # This turn may have a card â€” clear the conversation-scoped
                # marker a previous short turn left behind.
                self._suppressed_card_turn = None
                clear_card_free_conversation(self.conversation_id)
            else:
                suppress_card_for_conversation(self.conversation_id, _turn_id)
                self._suppressed_card_turn = _turn_id
                # A plan step is a NODE now (up to 12 tool calls), so a short
                # plan can still be long work: the card is released at the
                # turn's MIN_TOOL_STEPS_FOR_CARD-th real tool call
                # (_der_count_tool_call). Live 2026-10-12: 3-step plans with
                # 5 real calls (author lookup, pizza form) showed no card.
                if not _artifact_ask:
                    self._der_card_hold = {
                        "turn": _turn_id, "queue": queue, "plan": plan,
                        "session": _session, "calls": 0,
                        "lock": threading.Lock(),
                    }
                logger.info(
                    "[AgentKernel] task card suppressed: tool_steps=%d (bound "
                    ">=%d) artifact_ask=%s turn=%s â€” the turn runs, the artifact "
                    "still renders",
                    tool_step_count(items),
                    MIN_TOOL_STEPS_FOR_CARD,
                    _artifact_ask,
                    _turn_id,
                )
        except Exception as _gate_exc:  # never block the turn on the gate
            logger.debug("[AgentKernel] card gate skipped: %s", _gate_exc)

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
                    # Session 247: semantic order for the frontend row sort.
                    "stepNumber": it.step_number,
                    "toolName": _step_tool(it),
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

        # WS disconnect helper - checks if the originating session still has
        # at least one live client. Never raises; defaults to "connected".
        # Wedge fix (session 363): the body moved to _session_has_client_for
        # so _turn_choke_check - a METHOD, which cannot see this closure -
        # runs the same check inside the transport retry ladders. This
        # delegate keeps the loop call site unchanged.
        def _session_has_client() -> bool:
            return self._session_has_client_for(_session)

        # â”€â”€ REQ-15 (T25/T26): per-task steering state reset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self._der_stop_requested = False
        self._der_pause_requested = False
        self._der_resume_requested = False

        # dev-cli-ide REQ-25 edge case: the inbox outlives the loop that reads
        # it. Records are drained ONLY inside this loop, so anything queued
        # while no DER task was running would be applied to the NEXT task --
        # a steer aimed at one job silently revising another. Nothing sent to
        # the channel before REQ-25, so this was latent; the UI sender makes it
        # reachable. Drop pre-task records here and acknowledge them, rather
        # than letting them leak forward.
        try:
            from backend.agent.steering import get_steering_inbox as _gsi

            _stale = _gsi().drain(_session)
            for _rec in _stale:
                self._emit_steering_ack(
                    _rec.channel, _rec.message_id, "considered", _session
                )
            if _stale:
                logger.info(
                    "[AgentKernel][%s] dropped %d steering record(s) queued "
                    "before this task started", _session, len(_stale),
                )
        except Exception as _st_exc:
            logger.debug("[AgentKernel] stale-steering sweep skipped: %s", _st_exc)

        # â”€â”€ Parallel nodes (owner 2026-10-04): ONE scheduler for every node -
        # plan steps, split children, grafts, batch children. The DAG decides
        # WHAT is ready (depends_on); the "execution.der_nodes" phase domain
        # decides WHEN a ready node starts; the node's work runs on its own
        # thread while the bookkeeping before and after it stays on this
        # thread, in order. Independent nodes overlap; a dependent node is
        # never ready before its dependencies complete.
        import queue as _queue_mod

        _inflight: Dict[str, dict] = {}
        _finished = _queue_mod.Queue()
        # Bound before the loop: a turn whose loop exits before its first pass
        # (a stop latched at the first boundary, a budget already spent) reached
        # the grading line with `item` unassigned - UnboundLocalError, and the
        # reply became "[IRIS error: cannot access local variable 'item' ...]"
        # (live 2026-10-06, a strand turn). The grading line handles None.
        item = None

        while (
            not queue.is_complete()
            and not queue.hit_cycle_limit()
            and _tokens_used < _token_budget
            # Session 247: TURN WALL-CLOCK â€” the last-resort safety net. The
            # sufficiency gate and zero-yield cutoff stop the *rational*
            # churn; this bounds the total so no future bug can ever again
            # hold a turn open for 30+ minutes (conv-41 ran 18 dispatch
            # rounds unbounded). Generous by design: 10 min of wall time is
            # far beyond any healthy websearch turn, so this only fires on
            # genuine pathology. When it trips, the loop exits to synthesis
            # over completed steps â€” partial results reach the user.
            and (time.perf_counter() - _der_start_time) < _DER_TURN_BUDGET_S
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

            # â”€â”€ Parallel nodes: settle a finished node first (in finish order,
            # on this thread), else start the next ready one; with nothing to
            # start, wait for a node in flight to finish. â”€â”€
            _fin = _der_take_finished(self, _finished, _inflight, block=False)
            if _fin is None:
                # IRIS_DER_PARALLEL=0: one node at a time (the off switch and
                # the A/B baseline); default on.
                item = (None if (_inflight and not _DER_PARALLEL)
                        else queue.next_ready(_session, exclude=_inflight))
                if item is None:
                    if not _inflight:
                        break  # dependency deadlock guard
                    # Wait in short slices: a stop, a disconnect or the turn
                    # budget is seen at the loop top, not after a slow node.
                    _fin = _der_take_finished(
                        self, _finished, _inflight, block=True, timeout=0.5,
                    )
                    if _fin is None:
                        continue
            if _fin is not None:
                _tokens_used = _der_post_step(self, 
                    *_fin, queue=queue, plan=plan, _session=_session, _turn_id=_turn_id,
                    context_package=context_package, completed_items=completed_items,
                    step_outputs=step_outputs, _tokens_used=_tokens_used,
                    _token_budget=_token_budget, is_mature=is_mature, _live_ctx=_live_ctx,
                    from_voice=from_voice, inflight=_inflight,
                )
                continue
            queue.cycle_count += 1
            verdict = None

            # â”€â”€ REQ-15 (T25/T26): consume mid-task steering at the NEXT step
            # boundary (AC1 â€” never mid-step). A steering revision replaces
            # the remaining plan (AC2); a stop aborts here (AC3); a pause
            # suspends here until resume/stop (AC4). budget_deadline bounds
            # the re-plan's LLM call by the turn budget (pin_ced7b0dc3b8f).
            # Before it: a landed TOPO_VIOLATION halts the loop into
            # _der_execute_with_recovery (never waits on the physics lane).
            _der_topology_halt(self, _session)
            _steer = self._der_check_steering(
                _session, plan, queue,
                budget_deadline=_der_start_time + _DER_TURN_BUDGET_S,
            )
            if _steer:
                if _steer.get("stop"):
                    break
                if _steer.get("revised"):
                    # The pulled item belongs to the dropped plan â€” re-pull
                    # from the revised queue on the next iteration. Nodes of
                    # the dropped plan still in flight stop at their next call.
                    for _rec in _inflight.values():
                        _rec["item"]._node_cancelled = "plan revised"
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
                    # â”€â”€ REQ-20 AC3 (T21): the filtered ontology neighborhood
                    # is a first-class step input. Query the DER chain with
                    # THIS node's type + both domain axes and surface the
                    # relevant neighbor records into the step context â€” the
                    # relevant neighborhood, not the whole graph. Zero-hit
                    # widens (relationship -> type -> domain, logged) and
                    # falls back to the live-state-only step (never an error).
                    try:
                        # K2: only rows that passed the relevance gate reach
                        # here; no row -> no block (nothing injected).
                        _nb_rows = self._der_recall_neighborhood(item, _session)
                        _nb_block = _der_neighbors_block(_nb_rows)
                        if _nb_block:
                            _prior = getattr(item, "coordinate_signal", "") or ""
                            item.coordinate_signal = (
                                _prior + "\nRELEVANT NEIGHBORS: " + _nb_block
                            ).strip()
                            _der_recall_delivered(
                                self, item, "neighbors",
                                [r.get("chain_id") for r in _nb_rows[:3]], _session,
                            )
                    except Exception as _nb_exc:
                        loud_error(_nb_exc, "ontology_recall_neighborhood")

                    # REQ-12 AC3 (T48, 2026-10-29): the step's own CHUNK memory.
                    # The neighborhood above is chain rows typed by node_type +
                    # domain, and an episode is not a fact: neither carries a
                    # taught USER statement. That lives in a context_fragment
                    # chunk (the turn pair), so the step that must answer recalls
                    # it HERE, on the node that needs it - not in the planner.
                    # Bounded to 3 x 300 chars, trusted only, cross-conversation.
                    try:
                        _ep_store = getattr(self._memory_interface, "episodic", None)
                        _step_goal = getattr(item, "description", "") or ""
                        if _ep_store is not None and _step_goal:
                            _ch_rows = _ep_store.retrieve_context_chunks(
                                _step_goal,
                                session_id=None,
                                limit=3,
                                min_similarity=0.35,
                                chunk_types=["context_fragment"],
                                zones=["trusted"],
                                with_meta=True,
                            ) or []
                            # REQ-12 AC2 (T48): `trusted` only means "not outside
                            # content". Each row carries its PRODUCER, so the step
                            # can weigh the user's statement above this agent's
                            # own earlier answer instead of treating them alike.
                            _LABELS = {
                                "user_statement": "the user stated",
                                "agent_step": "your earlier answer",
                            }
                            _ch_rows = sorted(
                                _ch_rows,
                                key=lambda r: 0 if r.get("producer") == "user_statement" else 1,
                            )
                            _ch_txt = "\n- ".join(
                                "[{}] {}".format(
                                    _LABELS.get(
                                        r.get("producer"),
                                        str(r.get("producer") or "memory").replace("tool:", "tool "),
                                    ),
                                    str(r.get("content") or "").strip()[:300].replace("\n", " "),
                                )
                                for r in _ch_rows if str(r.get("content") or "").strip()
                            )
                            if _ch_txt:
                                _prior_ch = getattr(item, "coordinate_signal", "") or ""
                                item.coordinate_signal = (
                                    _prior_ch + "\nRELEVANT MEMORY:\n- " + _ch_txt
                                ).strip()
                    except Exception as _ch_exc:
                        loud_error(_ch_exc, "step_chunk_recall")

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
                                    # 300 as before; 1600 only for a replan-
                                    # after-failure child whose summary carries
                                    # the bounded case trail (<= 400, D9) and
                                    # chain block (<= 900, K3) - no other node
                                    # grows (owner: no context debt).
                                    "UNDERSTANDING: " + _rec.prior_summary[
                                        :1600 if (
                                            "CHAIN TIMELINE" in _rec.prior_summary
                                            or "MEDIATORS TRIED" in _rec.prior_summary
                                            or "KNOWN CASE" in _rec.prior_summary
                                        ) else 300
                                    ]
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
                # Bind the step id into the measurement scope from here on
                # (first added for review_verdict, retired 2026-11-10; the bind
                # stays because every later row of this step reads its step_id
                # from the scope). Measured live: 2877 of 2877 rows carried an
                # EMPTY step_id - the loop binds turn_id at turn entry but never
                # the step. scope_now() reads these as VALUES at row-build time,
                # so a lane thread still gets them. try/except: measurement must
                # never block a review.
                try:
                    from backend.agent import decision_engine as _de

                    _de.set_scope(
                        step_id=getattr(item, "step_id", None) or None,
                    )
                except Exception:  # noqa: BLE001 â€” measurement never blocks
                    logger.debug("[DER] review scope bind failed")
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
                    # the next attempt's node sees why (2026-10-02 audit)
                    item.review_feedback = str(feedback or "")[:300]
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
                    # Session-321 (Reviewer claim-coverage): a REFINE whose
                    # text steers to read/compose sets the read tool
                    # directly â€” the same reroute shape the T6B guard uses.
                    # Clearing the tool and hoping the resolver picks read
                    # is words-only; an explicit tool set is enforcement.
                    # get_rendered_documents is idempotent and side-effect
                    # free, so it cannot recrawl by construction.
                    _fb = str(feedback or "").lower()
                    if "do not dispatch another crawl" in _fb or (
                        "read the gathered" in _fb
                        and (item.tool or "") in ("crawler_query", "web_search",
                                                  "search", "search_discovery")
                    ):
                        item.tool = "get_rendered_documents"
                        item.params = {
                            "conversation_id": self.conversation_id or "",
                        }
                        logger.info(
                            f"[DER] Step {item.step_number} rerouted by "
                            f"Reviewer REFINE to get_rendered_documents",
                        )

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
            # T13 (REQ-10 AC10.11): the tool started â€” open its narratable
            # wait (entry line only for known-long waits; miss fires from
            # the scheduler worker if the stated budget is crossed).
            try:
                self._note_tool_wait(
                    tool_name=item.tool or "direct",
                    wait_id=_lifecycle_task_id,
                    turn_id=_turn_id,
                    session_id=_session,
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

            def _run_step(item=item):
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
                if AgentKernel._der_step_error_is_retryable(_err):
                    raise ConnectionError(_err)  # transient -> retry
                raise ValueError(_err)  # permanent -> fail fast

            # â”€â”€ Parallel nodes (owner 2026-10-04): the node's work runs on its
            # own thread (it always did - a bounded daemon thread, session 269);
            # the loop no longer joins it here but goes on to the next ready
            # node. _der_post_step settles each node when it finishes. â”€â”€
            _der_start_node(self, item, _run_step, _inflight, _finished,
                                 verdict=verdict, phase=_phase)
            continue

        # Nodes still in flight when the loop ended (budget, stop, cancel,
        # disconnect, cycle limit) stop at their next call; their late results
        # are dropped and they are recorded as not finished (the old bounded
        # join failed the step on the budget the same way).
        for _sid, _rec in list(_inflight.items()):
            _rec["item"]._node_cancelled = "turn ended"
            _rec["item"].result = "[STEP TIMEOUT: the turn ended before this node finished]"
            queue.mark_failed(_sid)
            logger.warning("[DER] node %s still running at the turn end - stopped, not settled", _sid)
        _inflight.clear()

        # Taxonomy CONTROL: a budget (tokens, turn time, steps) cut the loop short.
        _budget_kind = _der_budget_exit(
            _tokens_used, _token_budget, time.perf_counter() - _der_start_time,
            _DER_TURN_BUDGET_S, queue,
        )
        if _budget_kind:
            _emit_event(
                self, "BUDGET_HIT", evidence="verifier", thread_id=_session,
                trigger="budget_exceeded",  # nodes/outcome.Reason.BUDGET_EXCEEDED
                cost={"ms": int((time.perf_counter() - _der_start_time) * 1000)},
                payload={"budget": _budget_kind, "tokens_used": int(_tokens_used),
                         "token_budget": int(_token_budget),
                         "steps_done": len(completed_items)},
            )

        # â”€â”€ OUTCOME RECORDING (ordered per spec: clear â†’ stats â†’ episode)
        # NOTE: _store_task_episode internally calls mycelium_record_outcome
        # and mycelium_crystallize_landmark, so we do NOT duplicate them here.
        # DER Phase 0 (D0.6): coarsen outcome from verified_fraction, not a binary
        # "[STEP ERROR" substring. hit (>=0.8) / partial (0.3-0.8) / miss (<0.3).
        _joined = "\n".join(step_outputs)
        # The loop variable `item` is whatever the LAST pass set - after a
        # re-plan it can be None (live 2026-10-02 run A6: the reply became
        # "[IRIS error: 'NoneType' object has no attribute 'expected_output']").
        # Grade against the last step that completed.
        _last_item = completed_items[-1] if completed_items else item
        _frac = (
            self._verified_fraction(getattr(_last_item, "expected_output", "") or "", _joined)
            if step_outputs else 0.0
        )
        # Session-326: verdict from the FINAL ANSWER, not step colors. A
        # failed step used to force "failure" even when the answer carried
        # verified content (7-min stall: partial answer, red-X card).
        # success = clean run plus verified answer; partial = the answer
        # carries verified content despite failed steps; failure = nothing
        # verified. failed_steps still ride the terminal event, so per-step
        # honesty never moves â€” only the run verdict does.
        if _frac >= 0.8 and not queue.failed_ids:
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
                    conversation_id=self.conversation_id or self.session_id or "",
                    storage_path=_der_ledger_storage_path(),  # GROUND TRUTH T9 (REQ-14 AC1)
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
            _write_counters.bump("ledger.lifecycle_write_failed")
            logger.warning("[DER] task lifecycle write FAILED: %s", _lc_exc)

        # GROUND TRUTH T6 (REQ-3): persist the CARD FOOTPRINT here, at the same
        # honest terminal state the ledger just recorded.
        #
        # backend/memory/card_footprint.py was implemented for
        # specs/task-card-v2-liquid-ink REQ-11 and then never called: the module
        # has ZERO production importers, and save_card_footprint /
        # get_card_footprint appear in exactly one file - their own. So
        # semantic_entries holds 0 rows and no card has ever been addressable
        # by id across conversations. This is the call site it was waiting for,
        # and it unblocks specs/wormhole-aperture REQ-34, which reads footprints
        # as a chain-extraction source.
        # C5: written by the turn-end job on the memory lane (below); the card
        # id is captured now because the next turn may change it.
        _te_card_id = getattr(self, "_active_card_id", None)

        # â”€â”€ EventBus: emit task:done / task:fail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # T11 (REQ-12): record the completed-step count on the kernel so the
        # caller's TurnMetrics block (metrics.der_steps) reads a real number.
        # len(completed_items) is authoritative here â€” it is appended only in
        # _der_finalize_step, one per actually-completed step.
        self._der_step_count = len(completed_items)
        #
        # Session 247 (live conv-44): this emit used to run HERE, BEFORE
        # synthesis. The card flipped to done while the answer did not exist
        # yet, and the "Synthesizing answer" progress frame arrived ~43s
        # AFTER task:done with no working card to attach to - the frontend
        # fabricated a phantom second card (LEGACY_UNKNOWN, THK, timer
        # running). Done must mean "the answer was delivered": the emit is
        # now a closure fired by every outcome branch BELOW, right before
        # it returns its synthesized response.
        def _emit_terminal_event() -> None:
            # Never raises; EventBus failures must not block the user response.
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                _lifecycle_task_id = _turn_id or plan.original_task[:40]
                get_event_bus().emit(
                    IRISStreamEvent.TASK_DONE if outcome in ("success", "partial") else IRISStreamEvent.TASK_FAIL,
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

        # â”€â”€ C5: turn-end bookkeeping on the memory lane (2026-10-01) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Card footprint, plan stats, the episode (+ Mycelium outcome and
        # landmark crystallization) and skill capture ran HERE, before the
        # reply's synthesis: 2-8.5 s per coding task (stack dumps: inside
        # crystallize_landmark -> _auto_connect). The reply does not need any
        # of it, so it runs as ONE ordered job on lane("memory_events") after
        # record_task_end (same lane, same order as before). The next turn
        # folds back on it before planning recalls episodes (_turn_end_settle).
        # Everything the job reads is captured now: the next turn changes
        # kernel state.
        if self._memory_interface:
            _der_duration_ms = int((time.perf_counter() - _der_start_time) * 1000)
            _te_items = list(completed_items)
            _avg_step_ms = _der_duration_ms / len(_te_items) if _te_items else 0.0
            _te_stats = dict(
                session_id=_session,
                task_class=task_class,
                strategy=plan.strategy,
                total_steps=len(plan.steps),
                steps_completed=len(_te_items),
                tokens_used=_tokens_used,
                avg_step_duration_ms=_avg_step_ms,
                outcome=outcome,
                graph_mature=is_mature,
            )
            # One entry per call the steps ACTUALLY made (_step_calls): a node
            # step used to record {"tool": "none"}, so episodes held no tools
            # and skill capture (needs successful calls) could never fire.
            _tool_seq = [
                {
                    "tool": c.get("tool") or "none",
                    "params": dict(c.get("args") or {}),
                    "target": c.get("target", ""),
                    "success": bool(c.get("ok", True)),
                    "step": ci.step_number,
                    "description": ci.description,
                }
                for ci in _te_items
                for c in _step_calls(ci)
            ]
            _full_content = "\n".join(
                f"[Step {i + 1}] {o}" for i, o in enumerate(step_outputs) if o
            )
            _te_task = plan.original_task
            # Spec D9: task completion is outside evidence for this task's
            # FIXes (-> VERIFIED_FIX + LESSON candidate); closes its cases.
            _memory_events_submit(
                self, "record_task_end",
                thread_id=_session,
                task_id=f"{_session}:{_turn_id or ''}",
                success=(outcome == "success"),
            )

            def _turn_end_job():
                self._save_card_footprint(plan, _te_items, outcome, card_id=_te_card_id)
                try:
                    self._memory_interface.mycelium_record_plan_stats(**_te_stats)
                except Exception as _exc:
                    loud_error(_exc, "mycelium_record_plan_stats")
                # EPISODIC STORAGE closes the read/write loop:
                # assemble_episodic_context() reads these episodes.
                try:
                    self._store_task_episode(
                        task_summary=_te_task,
                        full_content=_full_content,
                        outcome_type=outcome,
                        tool_sequence=_tool_seq,
                        session_id=_session,
                        duration_ms=_der_duration_ms,
                    )
                except Exception as _exc:
                    loud_error(_exc, "store_task_episode")
                # Skill capture. It never fired while node steps recorded tool
                # "none"; with real calls it saved one task's call list per run
                # (5 in one eval). It now needs the call shape to RECUR in >= 3
                # successful similar episodes (workflow_capture.MIN_RECURRENCES).
                try:
                    self._maybe_trigger_skill_creation(
                        tool_sequence=_tool_seq,
                        task_summary=_te_task,
                    )
                except Exception as _exc:
                    loud_error(_exc, "skill_creation_trigger")

            _turn_end_submit(self, _session, _turn_end_job)

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
        # per-thread self._context_fill (how full the window is) â€” never 0 for an active thread.
        # All return paths below are preceded by this single emit.
        self._emit_context_usage(
            step_number=len(completed_items),
            total_steps=len(queue.items),
        )

        # Phase 1.5: if any step failed, synthesize a user-facing summary
        # that explains what worked, what failed, and what to do next.
        # Unless the OBJECTIVE is met: a failed intermediate attempt whose facts
        # a later step found is not a failed task (live 2026-10-02 run A7: run
        # grade pass, C=1.000, one failed search step -> "I couldn't complete
        # that task. 3/5 steps finished" with the answer in hand). An open or
        # blocked fact keeps this failure path.
        if queue.failed_ids and not (step_outputs and AgentKernel._goal_contract_met(self)):
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
                _emit_terminal_event()
                return self._goal_contract_name_blocked(_synthesis)
            # LLM synthesis unavailable (e.g. model rate-limited â€” the very
            # failure that broke the step) -> deterministic fallback so the user
            # is NEVER left with silence (Part B).
            _emit_terminal_event()
            return self._goal_contract_name_blocked(
                AgentKernel._der_deterministic_failure_summary(
                    plan, completed_items, queue
                )
            )

        if step_outputs:
            # REQ-16 AC2 (T32): a task that ran steps to completion exited
            # naturally.
            self._der_stamp_session_exit(True)
            # AC3.6 defense-in-depth (session-334, live T3): the loop-level
            # continuation gate in _der_plan_next_step is bypassable â€” COMPRESS
            # (rec==1) skips it, a non-AGENTIC/FULL mode skips it, and a planner
            # JSON-parse failure returns None. Measured 2026-09-17: grade=capped
            # with 1 open unblocked required fact still produced "I've completed
            # the task. 1/1 steps finished." The spec says the turn SHALL NOT
            # terminate while a required fact is open and unblocked. Guard the
            # FINALIZE boundary itself so a false success claim is impossible no
            # matter which bypass fired.
            try:
                _gc_open_final = list(self._goal_contract_open_facts() or [])
            except Exception:
                _gc_open_final = []
            # Test the COUNT, never truthiness: a non-sequence (or any object
            # with a permissive __bool__) would otherwise trip this branch with
            # zero open facts and suppress a legitimate success claim.
            #
            # Item 2 (2026-09-24, owner-approved): this guard must not narrate a
            # FAILURE for a turn that succeeded. Live conv-145 ("create a file
            # eyes_note3.md ... then read it back to me"): write_file and
            # read_file both returned success, the file on disk matched the
            # request, no step failed â€” and the contract still reported one open
            # required fact (counters: seeded=1 mapped=0 readded=1 covered=0), so
            # this branch appended "I couldn't fully complete the task â€” still
            # open: ..." to a correct, successful answer. A success claim is only
            # FALSE when a step failed, so the suppression now also requires
            # that. The mismatch is still recorded (WARNING above) and the fact
            # stays in the contract â€” nothing is hidden, and no false success
            # can slip through, because any failed or missing step keeps the
            # original suppression.
            _open_ok = bool(completed_items) and not list(
                getattr(queue, "failed_ids", None) or []
            )
            if len(_gc_open_final) > 0 and not _open_ok:
                logger.warning(
                    "[goal-contract] finalize with %d open unblocked fact(s) â€” "
                    "suppressing success claim: %r",
                    len(_gc_open_final), str(_gc_open_final[0])[:160],
                )
                _emit_terminal_event()
                _open_facts_txt = "; ".join(
                    str(_f)[:200] for _f in _gc_open_final[:5]
                )
                # Session-345 (live, conv-135): suppression must not hide what
                # WAS gathered. With completed steps on record, synthesize the
                # partial answer and append the open fact line â€” the fixed
                # string alone told the user nothing about the data the crawl
                # actually found. The failure path takes over if synthesis
                # itself is unavailable (deterministic close).
                _partial = None
                if completed_items:
                    try:
                        _partial = self._der_synthesize_outcome(
                            plan, completed_items, queue, _session
                        )
                    except Exception as _ps_err:
                        logger.warning(
                            "[goal-contract] partial synthesis failed: %s", _ps_err,
                        )
                if _partial:
                    return (
                        _partial.strip()
                        + "\n\nI couldn't fully complete the task â€” still open: "
                        + _open_facts_txt
                        + "\nWhat would you like me to do next?"
                    )
                return (
                    "I couldn't fully complete the task â€” required work is "
                    f"still open: {_open_facts_txt}\n"
                    "What would you like me to do next?"
                )
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
                _emit_terminal_event()
                return self._goal_contract_name_blocked(_synthesis)
            # REQ-12 (AC4): synthesis unavailable (e.g. reasoning provider
            # down) -> deterministic success summary mirroring
            # _der_deterministic_failure_summary so the user is never left
            # with raw concatenation (Part B symmetry).
            _emit_terminal_event()
            return self._goal_contract_name_blocked(
                AgentKernel._der_deterministic_success_summary(
                    plan, completed_items, queue
                )
            )
        # â”€â”€ Zero steps (or zero usable outputs) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The crawl plan produced no executable URLs (all blocked/filtered
        # by BOT_BLOCKED_DOMAINS, or the LLM couldn't generate any). Return
        # a descriptive message so _plan_task's post-processing can surface
        # an actionable explanation instead of the generic "couldn't generate".
        # REQ-16 AC2 (T32): zero usable steps is NOT a natural exit.
        self._der_stamp_session_exit(False)
        _emit_terminal_event()
        return (
            f"[DER] {plan.strategy} â€” "
            f"{len(completed_items)}/{len(plan.steps)} steps completed.  "
            f"error: no usable sources found for '{getattr(plan, 'title', '') or getattr(plan, 'plan_title', '') or plan.original_task[:40]}'.  "
            + self._build_crawl_failure_explanation(plan)
        )

    # â”€â”€ Phase 1.4: failure handling + plan grafting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€









    # â”€â”€ REQ-15 (T25): mid-task steering channel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€







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









    # â”€â”€ Phase 2: Emergent Shape â€” growth-width split/execute operator â”€â”€â”€â”€â”€â”€
    # This is the ONE recursive operator that decides execution-tree *shape*
    # from the live Caducean state (u,xi). It replaces the former mode-driven
    # fan-out AND the separate recovery-graft path: both physics-triggered
    # ("unresolved_u") and verification-failed ("verify_failed") splits use it.
    # MorphoHDL break: the decision is STATEFUL â€” width depends on live |u|,
    # never a fixed stateless predicate.



    # â”€â”€ REQ-5 (T17): coupling as decision-provenance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Retrieval RANKS relevant branches (physics- and evidence-driven, AC3) and
    # SURFACES ALL of them (bounded by the candidate cap) to the deciding step
    # (AC1) â€” never silently pre-selecting one by score. When the step commits,
    # the edge to the branch that informed it is written/strengthened with the
    # decision as provenance (AC2), and the per-decision record (how many
    # candidates surfaced, which was chosen) is stored on the node record (AC4).











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
    # crawl compressed to 300-400 chars starves every downstream consumer â€”
    # the tool-decision model then honestly reports "unable to access the
    # search results" because no fragment it sees can answer the goal.
    _DER_GATHER_TOOLS = {
        "crawler_query", "web_search", "search", "fetch_url",
        "read_file", "browser_read",
    }

    # REQ-18 added grep_files / glob_files as the codebase-search surface, but
    # they were never given an evidence window to match. They are not in
    # _DER_GATHER_TOOLS, so their results fell to the 400-char NON-gather cap
    # -- and a search tool exists precisely to return a LIST. Measured live
    # 2026-08-26 (conv-63): "how many backend files mention Porcupine" returned
    # 18 matches; at ~21 chars per entry that is ~420 chars of paths before the
    # JSON envelope, so the agent could not physically see them all and
    # answered "at least six". Truthful, correctly hedged, and wrong.
    #
    # Deliberately a SEPARATE set rather than adding them to _DER_GATHER_TOOLS:
    # that set also drives the sufficiency gate (:9391) and the graft decision
    # (:10623). This changes the evidence WINDOW only, which is the defect.
    _DER_SEARCH_TOOLS = {"grep_files", "glob_files"}

    # Session-323: stored-read tools deliver the SAME gathered bytes through
    # the document store instead of a fresh fetch. A rerouted read that keeps
    # the 400-char generic cap starves every downstream consumer â€” live
    # B3-repeat: guard rerouted to get_rendered_documents, step result held
    # only "1 document(s) retrieved", synthesis honestly reported IDs-only.
    # Kept as a SEPARATE set (same reason as _DER_SEARCH_TOOLS): this set
    # widens the evidence WINDOW only and must not alter the sufficiency
    # gate or graft decision that key off _DER_GATHER_TOOLS.
    _DER_READ_TOOLS = {
        "get_rendered_documents", "get_document", "read_document",
        "get_rendered_document", "recall_research",
    }

    # Tools whose result is a command's output: exit code + stdout/stderr.
    _SHELL_RESULT_TOOLS = {"run_command", "read_shell_output", "read_command_output", "stop_command"}



    @staticmethod
    def _smart_excerpt(text: str, cap: int) -> str:
        """Head+tail excerpt with an explicit truncation marker â€” never a
        silent amputation, never an unbounded dump."""
        t = (text or "").strip()
        if len(t) <= cap:
            return t
        _head = t[: int(cap * 0.7)]
        _tail = t[-int(cap * 0.3):]
        return f"{_head}\n[...excerpt: {len(t) - cap} chars truncated...]\n{_tail}"




    # â”€â”€ Partial-artifact completion (live 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # One step is ONE tool call (ToolDecisionBox.resolve is single-shot), so a
    # step that names several files can only ever write one of them. Measured:
    # "create three files ... each with one bullet" wrote ONE file, the other two
    # were silently missing, and the user was told the files had been created.
    # The folder stays on the name: "tests/test_geometry.py" read as "test_geometry.py",
    # was "missing" in the project root, and the graft overwrote the real test file
    # (live c11 2026-10-27: "Create the file test_geometry.py ..." -> hidden test failed).
    _ARTIFACT_NAME_RE = re.compile(
        r"\b[\w][\w.\-/\\]*\.(?:md|markdown|txt|json|csv|tsv|ya?ml|py|js|ts|tsx|html|log|rst|tex)\b",
        re.IGNORECASE,
    )





    _SOURCE_HEADER_RE = re.compile(r"---\s*Source:\s*(\S+)\s*---")





    # â”€â”€ Phase 2.2: context-aware query refinement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€








    def _log_route_shadow(
        self,
        *,
        turn_id: Optional[str],
        text: Optional[str],
        planned: bool,
        web_mode: bool,
        oracle_acted: bool = False,
    ) -> None:
        """Route shadow (REQ-18 AC1, task T30) â€” one JSONL row per turn.

        This is the EVIDENCE for the unified-routing flip (T33): every turn
        records which branch ran and whether the gate judged it trivial, so
        direct-vs-DER parity is measured before the direct branch is deleted.
        The classification itself is the semantic gate's answer already
        computed at the fork â€” zero extra work on the reply path. A write
        failure here must never cost a reply.
        """
        try:
            import json as _json
            import time as _time
            from pathlib import Path as _Path

            row = {
                "ts": _time.time(),
                "turn_id": turn_id or "unknown",
                "route_taken": "der" if planned else "direct",
                "would_be_trivial": not planned,
                "chars": len(text or ""),
                "web_mode": bool(web_mode),
            }
            path = (
                _Path(__file__).resolve().parents[2]
                / "data" / "route_shadow.jsonl"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(row, ensure_ascii=False) + "\n")

            # ORACLE ROUTE SHADOW (2026-10-30, reworked 2026-10-30): the
            # Oracle's pick on the ONE fork the kernel actually takes -
            # `"der" if planned else "direct"`. It NEVER acts.
            #
            # BINARY ON PURPOSE. The first cut asked a four-way question
            # (direct/der/memory_recall/memory_write) while the kernel has no
            # memory branches: memory_write and memory_recall both land on the
            # direct path. Two options that produce the same behaviour cannot
            # be calibrated - the report's precision pools them, so the engine
            # could look right on an option that changes nothing.
            #
            # `eng.shadow()` is the standard path: the row goes to
            # `_shadow_row_sink` -> the one ledger, so
            # scripts/consumer_enforcement_report.py can score it. The first
            # cut used `decide()` + a private jsonl and wrote ZERO ledger rows
            # (measured 2026-10-30: 0 route_v2 rows among 115,517 decision
            # rows). A private file is not evidence.
            #
            # The reference is what the rules did, in the same vocabulary, so
            # the row carries a parity label. It is NOT truth: the rules call
            # every memory ask "direct" because the direct path is where those
            # answers are assembled. A flip needs an OUTCOME label (did the
            # turn run a tool?), not this parity number.
            try:
                from backend.agent.decision_engine import get_decision_engine

                _eng = get_decision_engine()
                # A turn the Oracle's route drove has its own sampled row.
                if _eng is not None and not oracle_acted:
                    _incumbent = "der" if planned else "direct"
                    _frame = self._route_v2_frame(text, web_mode)
                    # input_key: the report's honest dedupe key. Without it the
                    # same goal rescored counts as NEW evidence (confidence
                    # jitters on every rescore), so "distinct rows" overstates
                    # the sample. Measured 2026-10-30: 157 route_v2 rows, 0 with
                    # an input_key, 60 distinct (chosen, confidence) pairs.
                    _key = None
                    try:
                        from backend.agent.surface_shadow import (
                            input_key as _input_key,
                        )

                        _key = _input_key("route_v2", (text or "")[:200], _frame)
                    except Exception:  # noqa: BLE001 - a missing key is not fatal
                        _key = None
                    _eng.shadow(
                        "route_v2",
                        ["direct", "der"],
                        _frame,
                        sink=self._shadow_row_sink,
                        reference={"brain_choice": _incumbent,
                                   "criteria_version": "route_v2/binary-v1",
                                   **({"input_key": _key} if _key else {})},
                    )
            except Exception as _route_err:  # noqa: BLE001 - a shadow never blocks
                logger.debug(
                    "[AgentKernel] route_v2 shadow failed: %r", _route_err
                )
        except Exception:  # noqa: BLE001 — shadow logging never blocks a reply
            pass






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



    # â”€â”€ Phase 4: concurrent step execution helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€







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
    # Tools the conversation-wide REPEAT rule applies to: web fetches, whose
    # repeat returns the same page. Local tools are re-runnable (audit B3).
    # The live browser tools are NOT here (nor in _WEB_CONTENT_TOOLS): a
    # repeated click or open is a new action on a changed page, and a crawl
    # budget would cut a multi-step browser task short (S39 exempts them from
    # the dispatcher's loop guard for the same reason).
    _REPEAT_GUARDED_TOOLS = _WEB_CONTENT_TOOLS | {"fetch_url", "open_url"}
    # pin_42ddd255162d: display/render tools complete by SUCCESS, not by content
    # volume â€” a rendered-card confirmation is a legit completion, never a
    # candidate for a verify-failure split (which is what made the task card
    # say "rendering documents" while the backend re-searched).
    _TRUSTED_RESULT_TOOLS = frozenset({"get_rendered_documents"})










    # â”€â”€ Phase 4: shared per-step finalize (extracted from _execute_plan_der)


    # â”€â”€ Physics side lane (execution audit, 2026-09-29) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # A step's Caducean update (EML observation -> integrator update -> coupling
    # -> trajectory row -> homeostasis -> controller refit -> Immortus chain ->
    # physics-event narration) is bookkeeping for the NEXT step's shape, not
    # part of this step's answer. It used to run inline in _der_finalize_step:
    # coding eval c10 spent 16-20 s of a 63 s turn inside ffi_calculate_eml on
    # the DER thread while the reply waited (logs/stackdump.log, 21:06:31-47).
    #
    # Now it runs on the ordered durability lane (one consumer, FIFO â€” the
    # physics is a sequential integrator and the chain is order-sensitive, so
    # order is preserved by construction). The CADUCEAN fold-back rule decides
    # who waits: only a DECISION about the next step's shape reads the pending
    # update (_der_physics_settle). Everything else â€” synthesis, scoring,
    # modulation â€” reads the last settled position and never waits.





    # â”€â”€ Phase 3: explorer methods â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€






    # â”€â”€ Goal contract Wave 3 (T7/T8/T9/T10) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Advisory helpers: every path degrades to legacy behavior when no
    # contract exists. Never raise, never block the turn.









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

    # NOTE (session 247): a second, arg-less `clear_conversation` used to be
    # defined HERE and silently SHADOWED the real one near the top of this
    # class (line ~590). Python class bodies keep the LAST def, so every
    # `clear_conversation(conversation_id)` call from iris_gateway raised
    # "takes 1 positional argument but 2 were given" â€” logged as
    # "[Chat] Failed to clear previous conversation ..." on every new-thread
    # switch, meaning the previous thread's kernel context was never cleared
    # and could leak into the new thread. The duplicate is removed; the real
    # definition handles both call shapes (conversation_id optional, defaulting
    # to the kernel's current thread).

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











# <kernel-split:propagate> generated by scripts/kernel_split_check.py move; do not edit by hand
# RES-7: an assignment to one of these module attributes (mock.patch, monkeypatch.setattr,
# plain `agent_kernel.X = v`) is forwarded to every kernel module that binds the name.
# A `global X; X = v` store inside this file does NOT pass through __setattr__.
import sys as _sys
import types as _types
_PROPAGATE = {
    'backend.agent.kernel.base': ('AgentKernel', '_emit_event', 'debit_work_units', ),
    'backend.agent.kernel.context': ('TurnMetrics', ),
    'backend.agent.kernel.der.finalize': ('AgentKernel', 'TurnMetrics', 'debit_work_units', ),
    'backend.agent.kernel.der.node': ('AgentKernel', ),
    'backend.agent.kernel.der.physics': ('TurnMetrics', '_emit_event', ),
    'backend.agent.kernel.der.recovery': ('AgentKernel', '_emit_event', 'debit_work_units', ),
    'backend.agent.kernel.der.report': ('AgentKernel', ),
    'backend.agent.kernel.models': ('_agent_kernel_instances', ),
    'backend.agent.kernel.planning': ('AgentKernel', ),
    'backend.agent.kernel.surface': ('AgentKernel', '_emit_event', ),
    'backend.agent.kernel.turn': ('AgentKernel', 'TurnMetrics', 'get_global_internet_access', ),
}


class _KernelModule(_types.ModuleType):
    def __setattr__(self, name, value):
        _types.ModuleType.__setattr__(self, name, value)
        for _mod_name, _names in _PROPAGATE.items():
            if name in _names:
                _target = _sys.modules.get(_mod_name)
                if _target is not None:
                    setattr(_target, name, value)


_sys.modules[__name__].__class__ = _KernelModule
for _mod_name, _names in _PROPAGATE.items():
    for _name in _names:
        setattr(_sys.modules[_mod_name], _name, globals()[_name])
# </kernel-split:propagate>
