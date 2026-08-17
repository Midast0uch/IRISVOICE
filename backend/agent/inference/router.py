"""
InferenceRouter — single source of truth for provider routing.

Holds a ``ProviderRegistry``, a ``RoleBindingTable``, and a cache of
``Transport`` instances.  ``generate(role, messages, tools)`` resolves
the role → provider instance → transport and runs inference.

Config schema (``iris_config.json``) is auto-applied on init if present::

    {
      "inference": {
        "provider_registry": [
          { "id": "cerebras", "label": "Cerebras", "kind": "api",
            "model": "gemma-4-31b", "api_base_url": "https://api.cerebras.ai/v1" },
          ...
        ],
        "role_bindings": [
          { "role": "reasoning", "instance_id": "cerebras" },
          ...
        ]
      }
    }
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .keyring import get_secret
from .provider import ProviderInstance, ProviderKind, get_provider_default_endpoint
from .registry import ProviderRegistry, get_provider_registry
from .roles import RoleBindingTable, get_role_binding_table
from .transport import (
    ApiHttpxTransport,
    InProcessTransport,
    OllamaTransport,
    OpenAICompatTransport,
    Transport,
)
from ..rate_meter import get_rate_meter, metered, quota_key
from ..call_context import call_class
from ..phase_manager import acquire

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache key helper
# ---------------------------------------------------------------------------


def _transport_cache_key(
    kind: ProviderKind, inst: ProviderInstance
) -> Tuple[str, ...]:
    """Return a hashable key for the transport cache."""
    if kind == ProviderKind.API:
        # The credential is part of the transport's identity: a key change
        # (UI Apply Provider) must invalidate the cached transport, or the
        # stale key keeps being sent and every call 401s even though the
        # keyring holds the correct value. Fingerprint the KEYRING value —
        # the exact key the transport will use (router._build_transport reads
        # get_secret(inst.id)) — so the cache invalidates precisely when the
        # real credential changes, not when inst.api_key (which may lag) does.
        from backend.agent.inference.keyring import get_secret

        return (kind.value, inst.api_base_url or "", _key_fingerprint(get_secret(inst.id)))
    if kind == ProviderKind.LOCAL_OPENAI:
        return (kind.value, inst.api_base_url or "")
    if kind == ProviderKind.INPROCESS:
        # In-process transports are not cached (model mgr may change)
        return (kind.value, id(inst))
    if kind == ProviderKind.OLLAMA:
        return (kind.value, inst.api_base_url or "http://localhost:11434")
    return (kind.value, inst.id)


def _key_fingerprint(api_key: str) -> str:
    """Stable, non-reversible fingerprint of a credential for cache-keying.

    Uses the last 8 chars of the key — enough to distinguish keys without
    exposing the secret in logs or cache keys. Empty key -> ''.
    """
    if not api_key:
        return ""
    return api_key[-8:]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class InferenceRouter:
    """Single source of truth for provider routing.

    Usage::

        from backend.iris_config import load_config
        config = load_config()
        router = InferenceRouter(config)
        text, thinking, tools = router.generate("reasoning", messages, tools)
    """

    def __init__(self, config: Any) -> None:
        # Process-wide singletons (REQ-5): provider instances and role bindings
        # live in ONE registry shared by every kernel and the API endpoint, so
        # they cannot disagree about which models exist or which role serves
        # which provider.
        self._registry = get_provider_registry()
        # Phase 4: register non-chat encoder providers (embedding/rerank) so they
        # are visible to the UI but never bindable to reasoning/tool_execution.
        try:
            from .provider import register_builtin_encoder_providers
            register_builtin_encoder_providers()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[router] encoder provider registration failed: %s", exc)
        self._roles = get_role_binding_table()
        self._transports: Dict[Tuple[str, ...], Any] = {}
        # Separate reference for in-process model manager (set externally)
        self._inprocess_mgr: Any = None
        # Default role used when an unbound role is requested (set in _apply_config)
        self._default_role: Optional[str] = None
        # D1: real usage from the LAST generate() call, or None when the
        # transport/provider didn't report it. Per-kernel (this router is not
        # a singleton — see AgentKernel.__init__), so there is no cross-session
        # leakage. Callers (AgentKernel, ToolDecisionBox, batch_dispatch) read
        # this immediately after generate() returns to credit the real token
        # count instead of an estimate.
        self.last_usage: Optional[Dict[str, int]] = None

        # ── Auto-apply config defaults ──────────────────────────────
        self._apply_config(config)

    # -- Config loading --------------------------------------------------

    def _apply_config(self, config: Any) -> None:
        """Read provider_registry and role_bindings from *config* if present.

        Handles both the target schema (``provider_registry`` +
        ``role_bindings`` lists) AND the legacy flat ``InferenceConfig``
        (``provider`` / ``reasoning_model`` / ``tool_execution_model`` /
        ``api_base_url`` / ``api_key``). The legacy path is synthesised into a
        single default provider instance bound to ``reasoning`` and
        ``tool_execution`` so existing configs keep working without manual
        migration.
        """
        infer_cfg = getattr(config, "inference", config)
        if infer_cfg is None:
            return

        # ── Unified provider collection (Phase 1 Wave 2 target schema) ──
        # ONE collection holds API + local entries keyed by id. ``endpoint`` and
        # ``cred_ref`` live in the same ProviderEntry, so a writer cannot set
        # one without the other (REQ-5 AC3). The credential itself is fetched
        # from the keyring by ``cred_ref`` (= id) at transport build time.
        providers = getattr(infer_cfg, "providers", None)
        if providers:
            for pid, entry in providers.items():
                inst = ProviderInstance(
                    id=pid,
                    label=getattr(entry, "label", pid),
                    kind=self._kind_from_str(getattr(entry, "kind", "API")),
                    model=getattr(entry, "model", None) or None,
                    api_base_url=getattr(entry, "endpoint", "") or "",
                    purpose=getattr(entry, "purpose", "chat"),
                )
                self._registry.add(inst)

        # ── Legacy target schema (provider_registry list) ──────────────
        provider_list = getattr(infer_cfg, "provider_registry", None)
        if provider_list:
            for p in provider_list:
                if isinstance(p, dict):
                    kind = self._kind_from_str(p.get("kind", "api"))
                    inst = ProviderInstance(
                        id=p["id"],
                        label=p.get("label", p["id"]),
                        kind=kind,
                        model=p.get("model"),
                        api_base_url=p.get("api_base_url", ""),
                    )
                else:
                    inst = p
                self._registry.add(inst)

        # Role bindings from config. Migrate the literal "local" instance id to
        # its namespaced form (REQ-4 AC1) so a partially-migrated id is never a
        # dead binding.
        #
        # CONFIG IS A SEED, NOT AN AUTHORITY (2026-08-16). This method runs from
        # ``InferenceRouter.__init__``, and a router is constructed in every
        # ``AgentKernel.__init__`` — so it re-ran on every new conversation and
        # replayed the PERSISTED bindings over the process-wide role table,
        # discarding whatever the user had picked since the last save. That is
        # the first of the two writes that produced the recurring "I picked
        # cohere and it went back to cerebras when I sent a message" revert.
        #
        # The role table is the single live authority (REQ-5, process-wide
        # singleton). Config may fill a role nobody has chosen yet — true
        # startup, when the table is empty — and must never overwrite a role
        # that is already bound.
        binding_list = getattr(infer_cfg, "role_bindings", None)
        if binding_list:
            for b in binding_list:
                if isinstance(b, dict):
                    role = b["role"]
                    inst_id = b["instance_id"]
                    override = b.get("model_override")
                else:
                    role = b.role
                    inst_id = b.instance_id
                    override = b.model_override
                if self._roles.is_bound(role):
                    # Log the id off the BINDING, not resolve() — resolve raises
                    # when the bound instance is not (yet) in the registry, and
                    # a diagnostic must never break router construction.
                    logger.debug(
                        "[InferenceRouter] config seed skipped for role=%r: "
                        "already bound (live choice wins)", role,
                    )
                    continue
                if inst_id == "local":
                    inst_id = self._namespaced_local_id(infer_cfg)
                self._roles.bind(role, inst_id, model_override=override)

        # ── Legacy flat schema (backward compat) ───────────────────────
        # Only synthesise if the target schema contributed no CHAT provider,
        # so an existing config (provider / reasoning_model / api_key / …)
        # keeps working without manual migration.
        #
        # NOTE: this used to test `not self._registry.list()` (registry
        # empty). That broke the day Phase 4's register_builtin_encoder_
        # providers() started running in __init__ BEFORE this method — the
        # registry then always holds at least "embedding:lfm25-emb-350m", so
        # the guard was always False and a pure-legacy config (no `providers`
        # collection) never got its reasoning/tool_execution roles bound at
        # all (`roles: []`, `default_role: None`). The guard must test what it
        # actually means: "is there a CHAT-purpose provider already
        # registered?" — the encoder is purpose="embedding" and is never a
        # candidate for reasoning/tool_execution, so its presence must not
        # suppress legacy synthesis.
        if not any(
            (getattr(i, "purpose", "chat") or "chat") == "chat"
            for i in self._registry.list()
        ):
            legacy_provider = getattr(infer_cfg, "provider", None)
            if legacy_provider:
                kind = self._legacy_kind(legacy_provider)
                # Namespace the bare "local" provider id (REQ-4 AC1) so it
                # cannot collide with or shadow a namespaced local entry.
                if legacy_provider == "local":
                    _stem = (
                        getattr(infer_cfg, "reasoning_model", "")
                        or getattr(infer_cfg, "local_model_id", "")
                        or "local"
                    )
                    legacy_provider = f"local:{self._local_stem(_stem)}"
                inst = ProviderInstance(
                    id=legacy_provider,
                    label=legacy_provider,
                    kind=kind,
                    model=getattr(infer_cfg, "reasoning_model", None),
                    api_base_url=(
                        get_provider_default_endpoint(legacy_provider)
                        or getattr(infer_cfg, "api_base_url", "")
                        or ""
                    ),
                )
                self._registry.add(inst)
                # Persist the legacy key into the secret store keyed by id so
                # _build_transport can retrieve it uniformly.
                legacy_key = getattr(infer_cfg, "api_key", None)
                if legacy_key:
                    try:
                        from .keyring import set_secret
                        set_secret(inst.id, legacy_key)
                    except Exception:
                        pass
                # Same seed-only rule as the target schema above: a legacy flat
                # config must not overwrite a role the user has already bound.
                if not self._roles.is_bound("reasoning"):
                    self._roles.bind("reasoning", inst.id)
                tool_model = getattr(infer_cfg, "tool_execution_model", None)
                if not self._roles.is_bound("tool_execution"):
                    if tool_model and tool_model != inst.model:
                        self._roles.bind(
                            "tool_execution", inst.id, model_override=tool_model
                        )
                    else:
                        self._roles.bind("tool_execution", inst.id)

        # Establish a default role so unbound roles (e.g. DER's "EXECUTION")
        # still resolve to a usable provider instance. Prefer "reasoning".
        if not self._default_role:
            _bound = [b.role for b in self._roles.list()]
            _reasoning = next(
                (r for r in _bound if r.lower() == "reasoning"), None
            )
            self._default_role = _reasoning or (_bound[0] if _bound else None)

    @staticmethod
    def _legacy_kind(provider: str) -> "ProviderKind":
        """Map a legacy ``inference.provider`` string to a ``ProviderKind``.

        Tolerant of BOTH LM Studio spellings in the wild: the
        ``InferenceConfig.provider`` vocabulary (iris_config.py) uses
        ``"lm_studio"`` (underscore) while older call sites / UI presets use
        ``"lmstudio"`` (no underscore). Matching only one literal silently
        misroutes every config written with the other spelling to the API
        catch-all instead of LOCAL_OPENAI.
        """
        p = (provider or "").lower()
        if p in ("lmstudio", "lm_studio", "openai_compatible", "local_openai"):
            return ProviderKind.LOCAL_OPENAI
        if p in ("local", "iris_local", "inprocess"):
            return ProviderKind.INPROCESS
        if p in ("ollama",):
            return ProviderKind.OLLAMA
        # cerebras, openai, cohere, deepseek, anthropic, chutes, opencodego,
        # vps, api, … all route over HTTP to a provider → API kind.
        return ProviderKind.API

    @staticmethod
    def _local_stem(model_id: str) -> str:
        """Derive a stable local-provider id stem from a model/file name.

        ``"qwen3-9b-q4_k_m.gguf"`` -> ``"qwen3-9b"``. The stem is what makes a
        local provider id namespaced and unique (``local:<stem>``), so two local
        models never collide and the bare literal ``"local"`` is never used as an
        id (REQ-4 AC1).
        """
        stem = (model_id or "").strip()
        for ext in (".gguf", ".gguf.txt", ".bin", ".safetensors"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        stem = stem.strip().lower()
        return stem or "local"

    @staticmethod
    def _namespaced_local_id(infer_cfg: Any) -> str:
        """Return the namespaced local id for the configured local model."""
        local_id = getattr(infer_cfg, "local_model_id", "") or getattr(
            infer_cfg, "reasoning_model", ""
        )
        return f"local:{InferenceRouter._local_stem(local_id)}"

    @staticmethod
    def _kind_from_str(s: str) -> "ProviderKind":
        """Resolve a provider-kind string to ``ProviderKind``.

        Accepts either the enum member NAME (``"API"``) or its value
        (``"api"``), so ``ProviderEntry.kind`` and the legacy ``provider_registry``
        list (which use different conventions) both work.
        """
        try:
            return ProviderKind[s]
        except KeyError:
            return ProviderKind(s)

    # -- Public API ------------------------------------------------------

    def apply_selection(
        self,
        *,
        providers: Optional[List[Any]] = None,
        roles: Optional[List[Any]] = None,
    ) -> None:
        """Upsert provider instances and/or role bindings.

        Accepts lists of dicts (from UI ``confirm_card`` payload) or lists
        of ``ProviderInstance`` / ``RoleBinding`` objects.
        """
        if providers:
            for p in providers:
                if isinstance(p, dict):
                    kind = ProviderKind(p.get("kind", "api"))
                    inst = ProviderInstance(
                        id=p["id"],
                        label=p.get("label", p["id"]),
                        kind=kind,
                        model=p.get("model"),
                        api_base_url=p.get("api_base_url", ""),
                    )
                else:
                    inst = p
                self._registry.add(inst)

        if roles:
            for b in roles:
                if isinstance(b, dict):
                    self._roles.bind(
                        b["role"],
                        b["instance_id"],
                        model_override=b.get("model_override"),
                    )
                else:
                    self._roles.bind(
                        b.role, b.instance_id, b.model_override
                    )

    def add_provider(self, inst: ProviderInstance) -> None:
        """Thin wrapper around registry.add()."""
        self._registry.add(inst)

    def remove_provider(self, id: str) -> None:
        """Remove a registered provider by id. No-op if unknown."""
        self._registry.remove(id)

    def write_provider(
        self,
        entry: "ProviderEntry",
        credential: Optional[str] = None,
    ) -> None:
        """Atomically write a provider's endpoint + credential as ONE record.

        REQ-5 AC3: ``endpoint`` and ``cred_ref`` live in the same
        ``ProviderEntry``, so a writer cannot set one without the other. For a
        NEW provider, endpoint and credential MUST be supplied together — a
        mismatch (endpoint without credential, or credential without endpoint)
        is rejected. For an EXISTING provider, endpoint-only or key-only edits
        are permitted (you are updating one field of an already-complete record).

        Ordering (D-5): the keyring write happens FIRST, then the config write.
        If the config write crashes, the previous entry is intact (the keyring
        is additive and the registry still holds the prior instance), so a
        half-written provider can never reach a peer.
        """
        from .keyring import set_secret
        from ...iris_config import ProviderEntry as _ProviderEntry

        is_new = self._registry.get(entry.id) is None
        has_endpoint = bool(entry.endpoint)
        has_cred = credential is not None
        if is_new and has_endpoint != has_cred:
            raise ValueError(
                f"new provider '{entry.id}' requires endpoint AND credential "
                f"together (endpoint={has_endpoint}, credential={has_cred})"
            )
        # Keyring FIRST (D-5).
        if has_cred:
            set_secret(entry.id, credential)
        # Persist into the unified collection (best-effort; never raises on a
        # missing config file — the live registry is the source of truth).
        try:
            from ...iris_config import load_config, save_config

            _cfg = load_config()
            _cfg.inference.providers[entry.id] = entry
            _cfg.inference.config_version = max(_cfg.inference.config_version, 2)
            save_config(_cfg)
        except Exception as _e:  # pragma: no cover - persistence is best-effort
            # Module-level `logger` — there is no `self._logger` on this class.
            # Using one here made the handler that exists to swallow a persist
            # failure raise AttributeError out of it instead.
            logger.debug(f"[write_provider] config persist skipped: {_e}")
        # Add to the live (process-wide) registry.
        self._registry.add(
            ProviderInstance(
                id=entry.id,
                label=entry.label,
                kind=self._kind_from_str(entry.kind),
                model=entry.model or None,
                api_base_url=entry.endpoint,
                purpose=entry.purpose,
            )
        )

    def bind_role(
        self,
        role: str,
        instance_id: str,
        model_override: Optional[str] = None,
    ) -> None:
        """Thin wrapper around roles.bind()."""
        self._roles.bind(role, instance_id, model_override)

    def resolve(self, role: str) -> ProviderInstance:
        """Resolve *role* to its bound ``ProviderInstance``.

        Falls back to the configured default role when *role* is unbound,
        so callers using arbitrary role names (e.g. ``"EXECUTION"``) still
        get a working provider.
        """
        try:
            return self._roles.resolve(role)
        except Exception:
            if self._default_role and self._default_role.lower() != role.lower():
                try:
                    return self._roles.resolve(self._default_role)
                except Exception:
                    pass
            raise

    def set_inprocess_manager(self, mgr: Any) -> None:
        """Set the local model manager for ``INPROCESS`` transport."""
        self._inprocess_mgr = mgr

    def health_check_provider(self, role: str = "reasoning") -> Dict[str, Any]:
        """Lightweight pre-flight check for *role*.

        Returns ``{"ok": bool, "provider": str, "model": str, "error": str}``.

        Catches the "provider=uninitialized" case where no config has been
        applied.  If the provider *is* bound but its endpoint happens to be
        dead, ``ok`` may still be ``True`` — the deep reachability check is
        deferred to step execution (timeout will surface it).
        """
        try:
            inst = self.resolve(role)
            if not inst:
                return {
                    "ok": False, "provider": "", "model": "",
                    "error": f"No provider instance for role '{role}'",
                }
            ok = bool(getattr(inst, "api_base_url", None)) or bool(getattr(inst, "id", None))
            return {
                "ok": ok,
                "provider": getattr(inst, "id", "") or str(getattr(inst, "kind", "")),
                "model": getattr(inst, "model", "") or "",
                "error": "" if ok else f"Provider '{inst.id}' has no endpoint configured",
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": "",
                "model": "",
                "error": f"resolve('{role}') failed: {exc}",
            }

    # -- Transport construction (cached per kind+endpoint) --------------

    def _build_transport(self, inst: ProviderInstance) -> Any:
        """Construct (or retrieve from cache) the transport for *inst*.

        Wires the quota identity (D-9) into the transport and registers the
        meter window with its metered flag (T2.5). The transport cache key is
        unchanged — quota_id is derived from inst, not part of the key.
        """
        kind = inst.kind
        key = _transport_cache_key(kind, inst)

        if kind == ProviderKind.INPROCESS:
            # In-process transports are not cached; build fresh each call
            # because the model manager may change between calls.
            return InProcessTransport(
                model_manager=self._inprocess_mgr, quota_id=quota_key(inst)
            )

        cached = self._transports.get(key)
        if cached is not None:
            return cached

        _quota_id = quota_key(inst)
        # Register the window with its metered flag (D-9: only API is metered)
        get_rate_meter().ensure_window(_quota_id, metered(inst))

        if kind == ProviderKind.API:
            api_key = get_secret(inst.id) or ""
            transport: Any = ApiHttpxTransport(
                api_base_url=inst.api_base_url,
                api_key=api_key,
                quota_id=_quota_id,
            )
        elif kind == ProviderKind.LOCAL_OPENAI:
            transport = OpenAICompatTransport(
                endpoint=inst.api_base_url, quota_id=_quota_id
            )
        elif kind == ProviderKind.OLLAMA:
            transport = OllamaTransport(
                endpoint=inst.api_base_url or "http://localhost:11434",
                quota_id=_quota_id,
            )
        else:
            raise RuntimeError(f"Unknown provider kind: {kind}")

        transport._provider_id = inst.id  # for logging (T2.5)
        self._transports[key] = transport
        return transport

    # -- Core generate method -------------------------------------------

    def generate(
        self,
        role: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.6,
        chunk_callback: Optional[Callable[[str], None]] = None,
        reasoning_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """Generate a response for the given *role*.

        Resolution chain:
            1. ``role`` → ``ProviderInstance`` (via ``RoleBindingTable``)
            2. ``ProviderInstance`` → ``Transport`` (built/cached per kind)
            3. ``Transport.generate(model, messages, tools, ...)``

        Returns:
            ``(text, thinking, tool_calls)`` — same shape as
            ``AgentKernel._dispatch_api`` and friends.
        """
        inst = self.resolve(role)
        model_override = kwargs.pop("model_override", None)
        effective_model = model_override or inst.model or "local-model"

        transport = self._build_transport(inst)
        logger.info(
            "[InferenceRouter] role=%s instance=%s kind=%s model=%s "
            "transport=%s",
            role,
            inst.id,
            inst.kind.value,
            effective_model,
            type(transport).__name__,
        )

        # Normalize tools ONCE here, for EVERY provider (Cerebras, OpenAI,
        # LM Studio, Ollama, in-process local models, ...).  Callers may pass
        # either IRIS *internal* tool dicts ({name, description, parameters,
        # category}) or already-OpenAI-formatted tools ({type:"function",
        # function:{...}}).  The OpenAI function-calling schema is the de-facto
        # standard every compatible transport expects, so this single
        # normalization keeps tool-calling provider-agnostic — no per-provider
        # hardcoding.  Idempotent: already-normalized tools pass through.
        normalized_tools = self._normalize_tools(tools)

        # Phase gate: block until this oscillator is past its firing point
        # (T3.6 / REQ-13).  Fail-open: returns 0.0 if disabled or errored.
        # F9+F15: pass oscillator_id and quota_id explicitly.
        acquire(
            oscillator_id=f"{inst.id}:{call_class().value}",
            quota_id=getattr(transport, "_quota_id", None),
        )

        result = transport.generate(
            effective_model,
            messages,
            normalized_tools,
            max_tokens=max_tokens,
            temperature=temperature,
            chunk_callback=chunk_callback,
            reasoning_callback=reasoning_callback,
        )

        # D1: surface the transport's real usage (if any) for THIS call.
        # Deliberately does NOT change the return signature (8+ call sites
        # depend on the 3-tuple) — callers read router.last_usage right after
        # generate() returns instead.
        self.last_usage = getattr(transport, "last_usage", None)
        if self.last_usage:
            logger.info(
                "[InferenceRouter] real usage role=%s provider=%s "
                "prompt=%d completion=%d total=%d",
                role, inst.id,
                self.last_usage.get("prompt_tokens", 0),
                self.last_usage.get("completion_tokens", 0),
                self.last_usage.get("total_tokens", 0),
            )
        else:
            logger.debug(
                "[InferenceRouter] no real usage reported role=%s provider=%s "
                "-- caller falls back to char/4 estimate",
                role, inst.id,
            )

        return result

    @staticmethod
    def _normalize_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """
        Coerce a tools list into the OpenAI function-calling schema that all
        transports expect: [{"type": "function", "function": {name, description,
        parameters}}].

        Handles three input shapes:
          - None / empty            -> None (no tools)
          - already OpenAI format   -> returned unchanged (idempotent)
          - IRIS internal format     -> wrapped into OpenAI format

        This is the single normalization point so tool-calling works uniformly
        across Cerebras, OpenAI, Groq, LM Studio, Ollama (OpenAI-compat), vLLM,
        and in-process local models — without any provider-specific branching.
        """
        if not tools:
            return None
        out: List[Dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            # Already OpenAI-format? (has the {"type":"function","function":{...}} shape)
            if t.get("type") == "function" and "function" in t:
                out.append(t)
                continue
            # IRIS internal format: {name, description, parameters, category, ...}
            fn = {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
            }
            out.append({"type": "function", "function": fn})
        return out or None

    # -- Convenience accessors ------------------------------------------

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    @property
    def roles(self) -> RoleBindingTable:
        return self._roles

    @property
    def default_role(self) -> Optional[str]:
        """Role used when an unbound role is requested (e.g. DER EXECUTION)."""
        return self._default_role

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot of registry + role bindings.

        Single source of truth for the frontend's provider/role selection UI,
        so dropdowns populate from one endpoint instead of ad-hoc events.
        """
        return {
            "providers": [p.to_dict() for p in self._registry.list()],
            "role_bindings": [b.to_dict() for b in self._roles.list()],
            "default_role": self._default_role,
        }

    def rate_window_probe(self, role: str) -> Optional[Dict[str, Any]]:
        """Side-effect-free saturation probe for a role's provider quota.

        Resolves the SAME instance the transport would use for ``role`` and
        reads the rate meter's current window WITHOUT sending a request or
        taking a slot. Returns None when the window cannot be assessed
        (unmetered provider, unknown role, meter error) — callers must treat
        None as "unknown, proceed" (fail-open; a probe bug may never turn into
        an outage).

        This exists so pre-flight checkers (e.g. the crawl planner, whose
        only URL source is an LLM call) can avoid burning the transport's
        blind 3x retry loop (up to ~90s of Retry-After sleeps) when the
        window is already saturated — they fall back to an honest empty
        result instead.
        """
        try:
            inst = self.resolve(role)
            transport = self._build_transport(inst)
            quota_id = getattr(transport, "_quota_id", None)
            if not quota_id:
                return None  # unmetered transport — nothing to probe
            from ..rate_meter import get_rate_meter

            meter = get_rate_meter()
            win = meter.draw(quota_id)
            ceiling_rpm = meter.get_ceiling(quota_id)
            if ceiling_rpm is None or ceiling_rpm <= 0:
                return None  # no learned ceiling yet — cannot judge saturation
            requests = float(win.get("requests", 0))
            window_s = float(win.get("window_s", 60.0))
            # Saturated when the window already holds at/over the ceiling's
            # share of the window (ceiling is per-minute).
            saturated = requests >= ceiling_rpm * (window_s / 60.0)
            return {
                "saturated": saturated,
                "requests": requests,
                "ceiling_rpm": ceiling_rpm,
                "window_s": window_s,
                "quota_id": quota_id,
            }
        except Exception as exc:  # noqa: BLE001 — fail-open, always
            logger.warning("[InferenceRouter] rate_window_probe failed open: %s", exc)
            return None
