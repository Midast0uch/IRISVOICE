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
import uuid
from dataclasses import dataclass
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
# Vision capability resolution (specs/unified-vision-routing T5/T6)
# ---------------------------------------------------------------------------

# REQ-1 AC4 / edge case: an unreachable Ollama daemon must never block vision
# resolution. Short and fixed — this is a capability probe, not inference.
_OLLAMA_SHOW_TIMEOUT_S = 2.0


def supports_vision(instance: Optional[ProviderInstance]) -> bool:
    """REQ-1 AC1: does *instance* serve vision right now?

    - ``API``: resolved from the ``(provider_id, model_substring)`` table in
      ``AgentKernel._KNOWN_VISION_MODELS`` (mirrors ``_KNOWN_CONTEXT_WINDOWS``).
    - ``LOCAL_OPENAI`` / ``INPROCESS``: ONLY ``instance.vision_loaded`` — a
      projector actually attached when the RUNNING server was launched.
      NEVER a sibling ``mmproj-*.gguf`` existing on disk (REQ-1 AC3) — a file
      on disk says nothing about whether the running process can see.
    - ``OLLAMA``: the model's advertised capabilities via ``/api/show``.
      Unreachable -> False, logged, never raised (REQ-1 AC4 edge case).
    - Anything else, including a future/unrecognised ``ProviderKind`` -> False
      (REQ-1 AC5, CT-1). This function must never raise.
    """
    if instance is None:
        return False
    try:
        kind = getattr(instance, "kind", None)
        if kind == ProviderKind.API:
            return _supports_vision_api(instance)
        if kind in (ProviderKind.LOCAL_OPENAI, ProviderKind.INPROCESS):
            return bool(getattr(instance, "vision_loaded", False))
        if kind == ProviderKind.OLLAMA:
            return _supports_vision_ollama(instance)
        # Unrecognised/undeterminable kind -> False, not a raise (CT-1).
        return False
    except Exception as exc:  # noqa: BLE001 — must never raise into the caller
        logger.warning(
            "[supports_vision] undetermined for instance=%s kind=%s: %s",
            getattr(instance, "id", "?"), getattr(instance, "kind", "?"), exc,
        )
        return False


def _supports_vision_api(instance: ProviderInstance) -> bool:
    """REQ-1 AC2: ``(provider_id, model_substring)`` table lookup.

    Mirrors ``_KNOWN_CONTEXT_WINDOWS``'s matching rule exactly: EXACT
    ``provider_id`` match, case-insensitive SUBSTRING match on the model,
    first row wins. No I/O — pure lookup, cheap to call per resolution.

    Lazy import: ``agent_kernel.py`` imports ``InferenceRouter`` at module
    level, so importing ``AgentKernel`` back at THIS module's top level would
    deadlock the import graph. Importing inside the function breaks the cycle.
    """
    from ..agent_kernel import AgentKernel

    provider_id = getattr(instance, "id", "") or ""
    model = (getattr(instance, "model", "") or "").lower().strip()
    if not provider_id or not model:
        return False
    for reg_provider, reg_substring in AgentKernel._KNOWN_VISION_MODELS:
        if reg_provider == provider_id and reg_substring in model:
            return True
    return False


def _supports_vision_ollama(instance: ProviderInstance) -> bool:
    """REQ-1 AC4: resolve vision from Ollama's own ``/api/show`` capabilities.

    Guarded, time-bounded (``_OLLAMA_SHOW_TIMEOUT_S``) HTTP call. An
    unreachable daemon, a non-200 response, or any parse failure all resolve
    to False, logged — never raised and never left to block the caller.
    """
    model = (getattr(instance, "model", "") or "").strip()
    if not model:
        return False
    base = (getattr(instance, "api_base_url", "") or "http://localhost:11434").rstrip("/")
    try:
        import httpx  # lazy — keeps the API/local paths free of network-lib cost

        with httpx.Client(timeout=httpx.Timeout(_OLLAMA_SHOW_TIMEOUT_S)) as client:
            resp = client.post(f"{base}/api/show", json={"model": model})
        if resp.status_code != 200:
            logger.info(
                "[supports_vision] ollama /api/show non-200 provider=%s model=%s status=%s",
                getattr(instance, "id", "?"), model, resp.status_code,
            )
            return False
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — unreachable Ollama must never raise
        logger.warning(
            "[supports_vision] ollama unreachable provider=%s model=%s: %s",
            getattr(instance, "id", "?"), model, exc,
        )
        return False
    capabilities = data.get("capabilities") or []
    return "vision" in capabilities


def _free_vram_gb() -> float:
    """Best-effort free-VRAM read for REQ-9 logging.

    Never raises — design.md's Error Handling table: "VRAM query unreadable
    -> choose the most conservative candidate"; here that means reporting
    0.0 rather than blocking vision resolution on a hardware probe.
    """
    try:
        from ..local_model_manager import get_local_model_manager

        info = get_local_model_manager().get_hardware_info()
        return float(info.get("vram_free_gb", 0.0))
    except Exception as exc:  # noqa: BLE001 — logging-only path, never fatal
        logger.debug("[resolve_vision_provider] free VRAM unreadable: %s", exc)
        return 0.0


@dataclass
class VisionResolution:
    """REQ-2 AC1 / design.md Data Models — the provider that will serve vision.

    Attributes:
        tier: ``"brain"`` | ``"tool"`` | ``"fallback"``.
        provider_id: The resolved provider's id (or the fallback's synthetic id
            when no bound role can see).
        requires_load: Whether serving vision needs a model load first.
        free_vram_gb: Free VRAM at decision time (REQ-9 AC1), best-effort.
        model_path: Fallback-tier only — the VL model GGUF path.
        mmproj_path: Fallback-tier only — the paired projector GGUF path.
        takes_lease: Decisions Locked 8 — True whenever the resolved provider
            kind is LOCAL_OPENAI or INPROCESS, at ANY tier (brain/tool/
            fallback); False for a REMOTE provider (API/OLLAMA), which has no
            local process to protect from idle-stop.
    """

    tier: str
    provider_id: str
    requires_load: bool
    free_vram_gb: float
    model_path: Optional[str] = None
    mmproj_path: Optional[str] = None
    takes_lease: bool = False


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

    def resolve_vision_provider(self) -> VisionResolution:
        """REQ-2: resolve vision to whoever can already serve it.

        Hierarchy, first that can serve wins:
            1. ``reasoning`` binding ("brain")
            2. ``tool_execution`` binding ("tool")
            3. VL fallback (tier 3 — existing entry point in
               ``backend.tools.lfm_vl_provider``; size-selection is T7, not
               implemented here)

        Edge cases (REQ-2):
            - An unbound role, or ``self.resolve()`` raising for any reason,
              is treated as "no vision" and the hierarchy continues — never
              propagated.
            - Both roles bound to the SAME multimodal provider are returned
              ONCE: the loop returns on the first (brain-tier) match, so the
              tool tier is never separately evaluated or logged.

        REQ-9: logs the tier, provider id, whether a load is required and
        free VRAM at decision time, tagged with a short per-resolution
        context id so a ladder's log lines correlate. Kept off any inference
        hot path — this runs once per vision *resolution*, not per token.
        """
        ctx = uuid.uuid4().hex[:8]
        for tier, role in (("brain", "reasoning"), ("tool", "tool_execution")):
            try:
                inst = self.resolve(role)
            except Exception as exc:  # noqa: BLE001 — unbound role = no vision, keep going
                logger.debug(
                    "[resolve_vision_provider] ctx=%s tier=%s role=%s unresolved: %s",
                    ctx, tier, role, exc,
                )
                continue
            if not supports_vision(inst):
                continue
            free_vram = _free_vram_gb()
            takes_lease = inst.kind in (ProviderKind.LOCAL_OPENAI, ProviderKind.INPROCESS)
            resolution = VisionResolution(
                tier=tier,
                provider_id=inst.id,
                requires_load=False,
                free_vram_gb=free_vram,
                takes_lease=takes_lease,
            )
            logger.info(
                "[resolve_vision_provider] ctx=%s tier=%s provider=%s requires_load=%s "
                "free_vram_gb=%.2f takes_lease=%s",
                ctx, resolution.tier, resolution.provider_id, resolution.requires_load,
                resolution.free_vram_gb, resolution.takes_lease,
            )
            return resolution

        # Tier 3 — VL fallback. Scope: T6 calls the EXISTING entry point only;
        # size-selecting a ladder against free VRAM is T7's job. The fallback
        # is always a local llama-server process, so it always takes a lease.
        free_vram = _free_vram_gb()
        model_path: Optional[str] = None
        mmproj_path: Optional[str] = None
        ladder_note = "no candidate found"
        try:
            from backend.tools.lfm_vl_provider import (
                VisionModelUnavailable,
                _find_vision_model,
            )

            pair = _find_vision_model()
            if pair:
                model_path, mmproj_path = pair
                ladder_note = f"selected {model_path}"
            else:
                ladder_note = "no VL model found on disk"
        except VisionModelUnavailable:
            # T16 fix: this is REQ-3 AC4's "fail loudly" case — no VL model
            # exists, or none fit free VRAM. ``_find_vision_model`` already
            # logged and emitted VISION_UNAVAILABLE (AC6) before raising.
            # Swallowing it here (the old behavior) returned a clean
            # ``VisionResolution(model_path=None)`` and silently defeated the
            # user's explicit decision at the hierarchy's own entry point —
            # re-raise so it actually reaches the caller.
            logger.warning(
                "[resolve_vision_provider] ctx=%s tier=fallback: no VL model "
                "usable — propagating VisionModelUnavailable (REQ-3 AC4)",
                ctx,
            )
            raise
        except Exception as exc:  # noqa: BLE001 — genuinely unrelated lookup
            # errors (e.g. an import failure) still degrade cleanly; only the
            # user's explicit fail-loud case above propagates.
            ladder_note = f"fallback lookup failed: {exc}"
            logger.warning(
                "[resolve_vision_provider] ctx=%s fallback lookup error: %s", ctx, exc
            )

        resolution = VisionResolution(
            tier="fallback",
            provider_id="lfm_vl_fallback",
            requires_load=True,
            free_vram_gb=free_vram,
            model_path=model_path,
            mmproj_path=mmproj_path,
            takes_lease=True,
        )
        # REQ-9 AC2: log the candidate ladder and why it was chosen. T7 owns
        # widening this to a real multi-candidate ladder with per-rejection
        # reasons; today's entry point returns a single pair, so the "ladder"
        # is that one candidate (or its absence).
        logger.info(
            "[resolve_vision_provider] ctx=%s tier=fallback provider=%s requires_load=True "
            "free_vram_gb=%.2f takes_lease=True ladder=%s",
            ctx, resolution.provider_id, resolution.free_vram_gb, ladder_note,
        )
        return resolution

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

        # Session 245 (Cohere 400 fix, pin_69bb11e9b513 item 3): providers
        # like Cohere reject tool names outside [A-Za-z0-9_] or beginning
        # with a digit — e.g. the capability registry's dotted "fetch.crawl"
        # ("invalid request: tool names can only contain certain characters").
        # The converter lives HERE at the single normalization point: names
        # are sanitized for the wire and a sanitized->original map is kept so
        # tool_calls the model returns are remapped back to the ORIGINAL
        # registry names before any caller sees them. Callers unchanged.
        self._tool_name_remap: Dict[str, str] = {}
        if normalized_tools:
            for _t in normalized_tools:
                _fn = _t.get("function") or {}
                _orig = _fn.get("name") or ""
                _sane = self._sanitize_tool_name(_orig)
                if _sane != _orig:
                    if _sane in self._tool_name_remap and self._tool_name_remap[_sane] != _orig:
                        logger.warning(
                            "[InferenceRouter] tool-name sanitize collision: %r -> %r (already %r)",
                            _orig, _sane, self._tool_name_remap[_sane],
                        )
                    self._tool_name_remap[_sane] = _orig
                    _fn["name"] = _sane

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

        # Remap sanitized tool names back to the originals (see above) so
        # dispatchers match against the registry exactly as before.
        if self._tool_name_remap and isinstance(result, tuple) and len(result) == 3:
            for _tc in result[2] or []:
                _fn = (_tc or {}).get("function") if isinstance(_tc, dict) else None
                if isinstance(_fn, dict) and _fn.get("name") in self._tool_name_remap:
                    _fn["name"] = self._tool_name_remap[_fn["name"]]

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
    def _sanitize_tool_name(name: str) -> str:
        """Cohere/OpenAI-compatible wire constraint: [A-Za-z0-9_] only, and
        the name must not begin with a digit. Anything else becomes '_' ;
        a leading digit gains the 'tool_' prefix. Already-clean names pass
        through unchanged (idempotent)."""
        import re as _re

        sane = _re.sub(r"[^A-Za-z0-9_]", "_", name or "")
        if sane and sane[0].isdigit():
            sane = f"tool_{sane}"
        return sane

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


# ---------------------------------------------------------------------------
# T16 (REQ-2, REQ-3 AC4) — WIRING. resolve_vision_provider() had zero
# production callers; every vision consumer constructed the tier-3
# LFMVLProvider directly, so production routed every vision task to the
# dedicated VL server regardless of what the bound brain/tool could already
# do. This is the ONE place a vision consumer should get its serving client
# from — it resolves the hierarchy and hands back an object with the SAME
# method surface as ``LFMVLProvider`` (``analyze_screen`` /
# ``find_ui_element`` / ``suggest_action`` / ``health_check``) regardless of
# which tier answers, so callers' own tool semantics (prompts, response
# parsing, action execution) never change — only which endpoint serves them.
# ---------------------------------------------------------------------------


class _DirectVisionClient:
    """Tier 1/2 vision client: serves a vision request via the ALREADY-bound
    brain/tool provider — the same OpenAI vision chat-completion shape and
    prompt semantics as ``LFMVLProvider`` — with NO spawn / lease / idle-stop
    bookkeeping. That lifecycle is tier 3's alone (CT-3 pins it); this
    provider is already running, so there is nothing here to start or stop.

    Deliberately NOT built on top of ``LFMVLProvider._call``: that method is
    entangled with the owned-vision-server lifecycle
    (``_ensure_vision_server_running`` / ``_touch_vision_use``), which must
    never fire for an externally-owned endpoint (a cloud API, or a local
    model's own already-running server).
    """

    def __init__(self, inst: ProviderInstance, *, timeout: float = 30.0) -> None:
        self._id = inst.id
        self._model = inst.model or "gpt-4o"
        self._base_url = (inst.api_base_url or "").rstrip("/")
        self._timeout = timeout
        api_key = inst.api_key or ""
        if not api_key:
            try:
                api_key = get_secret(inst.id) or ""
            except Exception:  # noqa: BLE001 — missing credential is not fatal here
                api_key = ""
        self._api_key = api_key

    def _call(self, img_bytes: bytes, prompt: str, max_tokens: int = 128) -> str:
        """Same request/response shape as ``LFMVLProvider._call`` — an
        OpenAI-compatible vision chat completion — just pointed at the
        resolved provider's own endpoint and model, with an auth header when
        a credential is configured. Never raises: mirrors ``LFMVLProvider``'s
        contract of returning an error string on any failure."""
        if not self._base_url:
            return f"Vision unavailable: provider '{self._id}' has no endpoint"
        try:
            import base64

            import httpx

            img_b64 = base64.b64encode(img_bytes).decode("ascii")
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            payload = {
                "model": self._model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 — never raise into the caller
            logger.warning(
                "[_DirectVisionClient] provider=%s call failed: %s", self._id, exc
            )
            return f"Vision unavailable: {exc}"

    def analyze_screen(self, img_bytes: bytes, question: str = "") -> str:
        prompt = question if question else "Describe what is visible on this screen in detail."
        return self._call(img_bytes, prompt, max_tokens=256)

    def find_ui_element(self, img_bytes: bytes, description: str) -> Dict[str, Any]:
        prompt = (
            f'Find the UI element described as: "{description}". '
            "Describe where it is located on screen (top-left, center, bottom-right, etc.) "
            "and whether it is visible. Keep response brief."
        )
        response = self._call(img_bytes, prompt, max_tokens=64)
        if response.startswith("Vision unavailable"):
            return {"found": False, "location_hint": response}
        found = not any(
            word in response.lower()
            for word in ["not found", "not visible", "cannot find", "don't see", "no such"]
        )
        return {"found": found, "location_hint": response}

    def suggest_action(self, img_bytes: bytes, goal: str) -> Dict[str, Any]:
        prompt = (
            f'Goal: "{goal}". '
            "Looking at the current screen, what is the single best next action? "
            "Reply with: ACTION: [click/type/scroll/wait], TARGET: [what to interact with], REASON: [brief reason]."
        )
        response = self._call(img_bytes, prompt, max_tokens=128)
        if response.startswith("Vision unavailable"):
            return {"action": "error", "target": "", "reasoning": response}
        result: Dict[str, Any] = {"action": "unknown", "target": "", "reasoning": response}
        for line in response.splitlines():
            line_lower = line.lower()
            if line_lower.startswith("action:"):
                result["action"] = line.split(":", 1)[1].strip().lower()
            elif line_lower.startswith("target:"):
                result["target"] = line.split(":", 1)[1].strip()
            elif line_lower.startswith("reason:"):
                result["reasoning"] = line.split(":", 1)[1].strip()
        return result

    def health_check(self) -> bool:
        # resolve_vision_provider() only ever returns this tier when
        # supports_vision() already confirmed the instance can see, so there
        # is no separate readiness probe to run here (unlike tier 3's
        # dedicated, possibly-not-yet-started llama-server).
        return bool(self._base_url)


def resolve_vision_client(router: Optional["InferenceRouter"] = None) -> Tuple[Optional[VisionResolution], Any]:
    """The single entry point a vision consumer should use instead of
    constructing ``LFMVLProvider()`` directly (T16).

    Usage::

        resolution, client = resolve_vision_client()
        text = client.analyze_screen(img_bytes, "what's on screen?")

    Returns ``(resolution, client)``:
      - Tier 1/2 (``resolution.tier in ("brain", "tool")``): ``client`` is a
        ``_DirectVisionClient`` bound to the already-live provider — no
        llama-server spawn, no lease/idle bookkeeping.
      - Tier 3 (``resolution.tier == "fallback"``): ``client`` is a plain
        ``LFMVLProvider()`` — lifecycle (spawn / lease / idle-stop /
        owned-PID) is completely UNCHANGED, CT-3 pins it.

    ``VisionModelUnavailable`` (REQ-3 AC4, "fail loudly") PROPAGATES —
    callers must catch it and turn it into a clean, user-facing failure
    rather than let it escape into the agent loop; never silently degrade to
    a client that would just fail on first use. The ONE thing this function
    itself swallows is failing to even REACH a live router (e.g. no kernel
    constructed yet) — that degrades to the tier-3 default, logged, so a
    fresh process still has a working vision path on first call.

    *router*: pass an already-resolved ``InferenceRouter`` when the caller
    has one cleanly at hand (e.g. a WS handler holding ``session_id``).
    Standalone consumers (automation/vision.py, vision_guided_operator.py)
    have no router of their own — they call with no argument and this
    resolves the process-wide live router via ``get_active_kernel`` (the
    established accessor for "the" kernel outside a per-request scope; see
    ``iris_gateway.py``, ``api/status_snapshot.py``, ``api/caducean_debug.py``).
    """
    from backend.tools.lfm_vl_provider import LFMVLProvider

    if router is None:
        try:
            from ..agent_kernel import get_active_kernel

            router = getattr(get_active_kernel("session_iris"), "_router", None)
        except Exception as exc:  # noqa: BLE001 — no live kernel yet; degrade
            logger.warning(
                "[resolve_vision_client] no live router reachable (%s); "
                "using tier-3 default", exc,
            )
            router = None

    if router is None:
        return None, LFMVLProvider()

    # VisionModelUnavailable propagates out of here on the real no-fit case
    # (REQ-3 AC4) — see the T16 fix in resolve_vision_provider() above.
    resolution = router.resolve_vision_provider()

    if resolution.tier == "fallback":
        return resolution, LFMVLProvider()

    # Look up on THIS router's own registry (not the process-wide singleton
    # directly) — production routers always share the singleton (REQ-5), but
    # this keeps resolve_vision_client() correct for any router built its
    # own way (e.g. a test double with an isolated ProviderRegistry).
    inst = router.registry.get(resolution.provider_id)
    if inst is None:  # registry/resolution disagreed — defensive, should not happen
        logger.warning(
            "[resolve_vision_client] resolved provider '%s' missing from the "
            "registry; falling back to the tier-3 default",
            resolution.provider_id,
        )
        return resolution, LFMVLProvider()

    return resolution, _DirectVisionClient(inst)
