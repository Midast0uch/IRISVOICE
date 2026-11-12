# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

from backend.agent.vps_gateway import VPSGateway, VPSConfig
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import time
from backend.agent.kernel.base import (
    logger,
)


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


class ModelsMixin:
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

    def _is_local_provider(self) -> bool:
        """True when the selected provider serves a LOCAL model.

        Covers the legacy literal ``iris_local`` AND the modern
        ``local:<model>`` naming used when a GGUF is loaded through the Models
        card (2026-09-27). A hard-coded literal here silently routed every
        locally-loaded model to the LM Studio default endpoint instead.
        """
        _p = str(getattr(self, "_model_provider", "") or "")
        return _p == "iris_local" or _p.startswith("local:")

    def _local_openai_base(self) -> Optional[str]:
        """Base URL of the app's OWN local model server, or None.

        LocalModelManager serves the loaded GGUF over an OpenAI-compatible API
        on its ``PORT`` (8082 by default). None when no local model is loaded,
        so the caller falls through to the configured endpoint rather than
        calling a port nothing is listening on.
        """
        if not self._is_local_provider():
            return None
        try:
            from backend.agent.local_model_manager import (
                LocalModelManager,
                get_local_model_manager,
            )

            mgr = get_local_model_manager()
            if mgr is None or not mgr.is_loaded():
                return None
            return f"http://127.0.0.1:{LocalModelManager.PORT}/v1"
        except Exception as _e:  # noqa: BLE001 â€” fall through to the configured path
            logger.debug("[AgentKernel] local base lookup failed: %s", _e)
            return None

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
        if mgr is not None and self._is_local_provider():
            adapter = mgr.get_inprocess_client()
            if adapter is not None:
                return adapter
            # Manager was bound but model isn't loaded â†’ fall through to
            # HTTP path (which will 404 cleanly instead of silently hanging).

        # Path 1.5: the app's OWN local model server (2026-09-27).
        # A local GGUF is served over an OpenAI-compatible API on
        # LocalModelManager.PORT (8082), and THAT is where a planning call must
        # go. Path 1 covers only the legacy in-process adapter, and its literal
        # name check meant a modern local provider ("local:<model>") skipped it
        # and fell through to Path 2 - the configured LM Studio endpoint
        # (http://localhost:1234), which this app does not serve. Measured
        # consequence: every planning call logged
        #   openai._base_client: Raising connection error
        #   [AgentKernel._plan_task] planner returned no valid plan
        # No plan means the DER branch is never taken, so [DER] stayed 0 and the
        # step consumers wrote no rows. The messages were not reaching the loaded
        # model: the endpoint was simply the wrong port.
        _local_base = self._local_openai_base()
        if _local_base:
            _client = getattr(self, "_local_openai_client", None)
            if _client is None or getattr(
                self, "_local_openai_base_url", None
            ) != _local_base:
                from openai import OpenAI as _OpenAI
                import httpx

                _client = _OpenAI(
                    base_url=_local_base,
                    # The local server ignores the key; any non-empty string is
                    # accepted. The read timeout is generous because a small
                    # local model can be slow on a cold first call.
                    api_key="local",
                    timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10),
                )
                self._local_openai_client = _client
                self._local_openai_base_url = _local_base
                logger.info(
                    "[AgentKernel] local model server client -> %s", _local_base
                )
            return _client

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
                    # Swarm-defer seam (specs/model-selection-authority T4b):
                    # a switch arriving while swarm is active is RECORDED as a
                    # timestamped intent (in-memory on the router + visible in
                    # the snapshot + persisted by the gateway), never silently
                    # dropped as before. APPLYING it on swarm end belongs to
                    # the future swarm spec â€” no swarm logic here.
                    import time as _time_sw

                    _defer_stamp = _time_sw.time()
                    _intent = {
                        "provider": model_provider or "",
                        "reasoning_model": reasoning_model or "",
                        "tool_execution_model": tool_execution_model or "",
                        "selected_at": _defer_stamp,
                    }
                    try:
                        _r_sw = getattr(self, "_router", None)
                        if _r_sw is not None:
                            _r_sw._deferred_selection = dict(_intent)
                    except Exception:
                        pass
                    logger.info(
                        f"[AgentKernel] Swarm is enabled â€” deferring model_selection "
                        f"(keeping provider='{self._model_provider}', "
                        f"reasoning='{self._selected_reasoning_model}', "
                        f"tool='{self._selected_tool_execution_model}')"
                    )
                    try:
                        logger.info(
                            "[Authority] source=set_model_selection winner=%s prev=%s reason=swarm-deferred stamp=%.3f",
                            model_provider, getattr(self, "_model_provider", None), _defer_stamp,
                        )
                    except Exception:
                        pass
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

                # REQ-4 AC1 / session 288 finding: model_provider may be "local:<stem>"
                # (e.g. "local:lfm-2.5") when the frontend sends the actual provider
                # instance id from the dropdown. The bare-string checks below only
                # matched "local" / "iris_local" / "inprocess", so a namespaced local
                # id fell through to ProviderKind.API â€” and the provider was persisted
                # with kind="API", which validate_providers drops on restart.
                _is_local = model_provider in ("local", "iris_local", "inprocess") or (
                    isinstance(model_provider, str) and model_provider.startswith("local:")
                )
                _kind = ProviderKind.INPROCESS if _is_local and not api_base_url else (
                    ProviderKind.LOCAL_OPENAI if _is_local and api_base_url else (
                    ProviderKind.LOCAL_OPENAI if model_provider in ("lmstudio", "openai_compatible", "local_openai") else (
                    ProviderKind.OLLAMA if model_provider == "ollama" else ProviderKind.API)))
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
                # ENFORCE ONLY FOR HOSTED API PROVIDERS (2026-09-26).
                # The catalog is authoritative for an API preset, where the
                # provider's own model list is fixed and a model from another
                # provider's preset is stale. It is NOT authoritative for a
                # LOCAL server: Ollama's model list belongs to the user's own
                # install, and `provider_catalog.model_belongs_to_provider`
                # documents exactly that ("a provider with NO catalog entry ...
                # accepts anything ... never for local servers where the catalog
                # is a suggestion list"). Including OLLAMA here contradicted that
                # contract and silently dropped a model the user really has â€”
                # measured live: `gemma4:31b-cloud` (present in `ollama list`,
                # verified via /api/tags) was rejected, the warning said "not in
                # provider 'ollama' catalog", and the role fell back to the
                # PREVIOUS instance model, so the requested Brain/Tool split
                # could not be set at all. Tests for this contract:
                # tests/behavioral/test_provider_switch_keeps_own_model.py
                # (rule 2's backstop, exercised for cohere).
                if (
                    _inst_model
                    and _kind is ProviderKind.API
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
                # API providers only, for the same reason as the reasoning model
                # above: a local server's list is the user's, not ours.
                _tool_model = tool_execution_model or None
                if (
                    _tool_model
                    and _kind is ProviderKind.API
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
                        import time as _time2

                        _stamp2 = _time2.time()
                        try:
                            _prev_r = next(
                                (b for b in _r.roles.list() if b.role == "reasoning"),
                                None,
                            )
                            _prev_r_id = _prev_r.instance_id if _prev_r else None
                        except Exception:
                            _prev_r_id = None
                        _r.bind_role("reasoning", _inst.id, model_override=_inst_model, selected_at=_stamp2)
                        if _tool_model and _tool_model != _inst_model:
                            _r.bind_role("tool_execution", _inst.id, model_override=_tool_model, selected_at=_stamp2)
                        else:
                            _r.bind_role("tool_execution", _inst.id, model_override=_inst_model, selected_at=_stamp2)
                        try:
                            logger.info(
                                "[Authority] source=set_model_selection winner=%s prev=%s reason=explicit-gesture stamp=%.3f",
                                _inst.id, _prev_r_id, _stamp2,
                            )
                        except Exception:
                            pass
                        # An explicit switch consumes any deferred swarm intent
                        # (the user has now chosen directly; the old intent is
                        # stale). The gateway persist clears the config copy on
                        # its next write.
                        try:
                            _r._deferred_selection = None
                        except Exception:
                            pass

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

    def set_role_binding(self, role: str, instance_id: str, model_override: Optional[str] = None, selected_at: Optional[float] = None) -> bool:
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
            import time as _time

            _stamp = float(selected_at) if selected_at is not None else _time.time()
            try:
                _prev = next(
                    (b for b in _r.roles.list() if b.role == _r.roles._canon(role)),
                    None,
                )
                _prev_id = _prev.instance_id if _prev else None
            except Exception:
                _prev_id = None
            _r.bind_role(role, instance_id, model_override=model_override, selected_at=_stamp)
            try:
                logger.info(
                    "[Authority] source=set_role_binding winner=%s prev=%s reason=explicit-gesture stamp=%.3f",
                    instance_id, _prev_id, _stamp,
                )
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"[AgentKernel] Failed to set role binding: {e}")
            return False
