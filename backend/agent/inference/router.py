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
from .provider import ProviderInstance, ProviderKind
from .registry import ProviderRegistry
from .roles import RoleBindingTable
from .transport import (
    ApiHttpxTransport,
    InProcessTransport,
    OllamaTransport,
    OpenAICompatTransport,
    Transport,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache key helper
# ---------------------------------------------------------------------------


def _transport_cache_key(
    kind: ProviderKind, inst: ProviderInstance
) -> Tuple[str, ...]:
    """Return a hashable key for the transport cache."""
    if kind == ProviderKind.API:
        return (kind.value, inst.api_base_url or "")
    if kind == ProviderKind.LOCAL_OPENAI:
        return (kind.value, inst.api_base_url or "")
    if kind == ProviderKind.INPROCESS:
        # In-process transports are not cached (model mgr may change)
        return (kind.value, id(inst))
    if kind == ProviderKind.OLLAMA:
        return (kind.value, inst.api_base_url or "http://localhost:11434")
    return (kind.value, inst.id)


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
        self._registry = ProviderRegistry()
        self._roles = RoleBindingTable(self._registry)
        self._transports: Dict[Tuple[str, ...], Any] = {}
        # Separate reference for in-process model manager (set externally)
        self._inprocess_mgr: Any = None
        # Default role used when an unbound role is requested (set in _apply_config)
        self._default_role: Optional[str] = None

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

        # ── Target schema ──────────────────────────────────────────────
        provider_list = getattr(infer_cfg, "provider_registry", None)
        if provider_list:
            for p in provider_list:
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

        # Role bindings from config
        binding_list = getattr(infer_cfg, "role_bindings", None)
        if binding_list:
            for b in binding_list:
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

        # ── Legacy flat schema (backward compat) ───────────────────────
        # Only synthesise if the target schema contributed nothing, so an
        # existing config (provider / reasoning_model / api_key / …) keeps
        # working without manual migration.
        if not self._registry.list():
            legacy_provider = getattr(infer_cfg, "provider", None)
            if legacy_provider:
                kind = self._legacy_kind(legacy_provider)
                inst = ProviderInstance(
                    id=legacy_provider,
                    label=legacy_provider,
                    kind=kind,
                    model=getattr(infer_cfg, "reasoning_model", None),
                    api_base_url=getattr(infer_cfg, "api_base_url", "") or "",
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
                self._roles.bind("reasoning", inst.id)
                tool_model = getattr(infer_cfg, "tool_execution_model", None)
                if tool_model and tool_model != inst.model:
                    self._roles.bind("tool_execution", inst.id, model_override=tool_model)
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
        """Map a legacy ``inference.provider`` string to a ``ProviderKind``."""
        p = (provider or "").lower()
        if p in ("lmstudio", "openai_compatible", "local_openai"):
            return ProviderKind.LOCAL_OPENAI
        if p in ("local", "iris_local", "inprocess"):
            return ProviderKind.INPROCESS
        if p in ("ollama",):
            return ProviderKind.OLLAMA
        # cerebras, openai, cohere, deepseek, anthropic, chutes, opencodego,
        # vps, api, … all route over HTTP to a provider → API kind.
        return ProviderKind.API

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

    # -- Transport construction (cached per kind+endpoint) --------------

    def _build_transport(self, inst: ProviderInstance) -> Any:
        """Construct (or retrieve from cache) the transport for *inst*."""
        kind = inst.kind
        key = _transport_cache_key(kind, inst)

        if kind == ProviderKind.INPROCESS:
            # In-process transports are not cached; build fresh each call
            # because the model manager may change between calls.
            return InProcessTransport(model_manager=self._inprocess_mgr)

        cached = self._transports.get(key)
        if cached is not None:
            return cached

        if kind == ProviderKind.API:
            api_key = get_secret(inst.id) or ""
            transport: Any = ApiHttpxTransport(
                api_base_url=inst.api_base_url, api_key=api_key
            )
        elif kind == ProviderKind.LOCAL_OPENAI:
            transport = OpenAICompatTransport(endpoint=inst.api_base_url)
        elif kind == ProviderKind.OLLAMA:
            transport = OllamaTransport(
                endpoint=inst.api_base_url or "http://localhost:11434"
            )
        else:
            raise RuntimeError(f"Unknown provider kind: {kind}")

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

        return transport.generate(
            effective_model,
            messages,
            tools,
            max_tokens=max_tokens,
            temperature=temperature,
            chunk_callback=chunk_callback,
            reasoning_callback=reasoning_callback,
        )

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
