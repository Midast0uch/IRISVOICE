"""
IRIS Configuration — Single Source of Truth (SSOT).

All backend configuration is read from and written to data/iris_config.json.
This module provides a typed dataclass layer over the raw JSON so that
components receive a validated, immutable config object instead of
dictionaries.

Usage:
    from backend.iris_config import IRISConfig, load_config, save_config
    cfg = load_config()
    print(cfg.inference.api_base_url)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("irisvoice")

# ---------------------------------------------------------------------------
# Config write lock — serializes concurrent load-modify-save cycles to
# prevent race conditions when multiple async handlers write config.
# ---------------------------------------------------------------------------
_config_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Env-var helpers — read from os.environ at call time, always win.
# Uses a single shot so we only call os.environ.get() once per key per
# process (faster than reading config dicts in hot paths).
# ---------------------------------------------------------------------------

def _env_int(key: str, default: int) -> int:
    """Read integer env var, fall back to *default*."""
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_str(key: str, default: str) -> str:
    """Read string env var, fall back to *default*."""
    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# Port configuration — env-var aware defaults for IRIS-owned services.
# These are separate from the InferenceConfig provider URLs (lm_studio etc.)
# because IRIS-owned ports are things we bind to, not connect to.
# ---------------------------------------------------------------------------

@dataclass
class PortConfig:
    """Ports IRIS binds to. All overridable via environment variables.

    Env-var overrides are applied in __post_init__ (after field defaults
    AND after from_dict() construction), so they always win.
    """

    backend_port: int = 8090
    brain_port: int = 18182

    def __post_init__(self) -> None:
        """Apply env-var overrides on top of whatever constructor set."""
        self.backend_port = _env_int("IRIS_BACKEND_PORT", self.backend_port)
        self.brain_port = _env_int("IRIS_BRAIN_PORT", self.brain_port)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PortConfig":
        """Restore from dict, then __post_init__ applies env-var overrides.

        A persisted ``vision_port`` key from pre-single-server configs is
        simply ignored (never referenced)."""
        return cls(
            backend_port=int(d.get("backend_port", 8090)),
            brain_port=int(d.get("brain_port", 18182)),
        )


def with_modify_config(modifier_fn: Callable[["IRISConfig"], None]) -> "IRISConfig":
    """Atomically load config, apply *modifier_fn*, and save.

    *modifier_fn* receives the loaded ``IRISConfig`` and mutates it in-place.
    The entire cycle (load → modify → save) runs under a single lock so
    concurrent async handlers cannot overwrite each other's changes.

    Returns the modified config.
    """
    with _config_lock:
        cfg = load_config()
        modifier_fn(cfg)
        save_config(cfg)
        return cfg


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).parent.parent / "data"
_IRIS_CONFIG_PATH = _DATA_DIR / "iris_config.json"


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Routing mode enum
# ---------------------------------------------------------------------------
class RoutingMode(str, Enum):
    """Canonical routing modes for resolve_backend()."""

    SINGLE_API = "SINGLE_API"
    SINGLE_LOCAL = "SINGLE_LOCAL"
    SWARM_QUALITY = "SWARM_QUALITY"
    SWARM_TURBO = "SWARM_TURBO"
    SWARM_HYBRID = "SWARM_HYBRID"


# ---------------------------------------------------------------------------
# Typed configuration blocks
# ---------------------------------------------------------------------------
@dataclass
class RoutingConfig:
    """How the backend decides which inference path to take."""

    mode: RoutingMode = RoutingMode.SINGLE_API
    director_source: str = "api"  # for swarm modes

    def to_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode.value, "director_source": self.director_source}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RoutingConfig":
        mode = d.get("mode", "SINGLE_API")
        if isinstance(mode, str):
            try:
                mode = RoutingMode(mode)
            except ValueError:
                mode = RoutingMode.SINGLE_API
        return cls(mode=mode, director_source=d.get("director_source", "api"))


@dataclass
class SwarmRoleConfig:
    """Per-role settings for swarm director/worker."""

    director_model: str = ""
    director_provider: str = "api"
    worker_model: str = ""
    worker_count: int = 2
    worker_gpu_layers: int = -1
    worker_context: int = 2048
    auto_balance_vram: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SwarmRoleConfig":
        return cls(
            director_model=d.get("director_model", ""),
            director_provider=d.get("director_provider", "api"),
            worker_model=d.get("worker_model", ""),
            worker_count=int(d.get("worker_count", 2)),
            worker_gpu_layers=int(d.get("worker_gpu_layers", -1)),
            worker_context=int(d.get("worker_context", 2048)),
            auto_balance_vram=bool(d.get("auto_balance_vram", True)),
        )


@dataclass
class ProviderEntry:
    """A persisted provider configuration record (flat-config replacement).

    ``endpoint`` and ``cred_ref`` are fields of the SAME record, so a writer
    cannot set one without the other (REQ-5 AC3). ``cred_ref`` is the keyring
    key under which the credential is stored (== ``id`` for API providers);
    the credential itself is NEVER persisted in config. ``purpose`` lets
    non-chat providers (embedding / rerank) be declared and later filtered out
    of the chat-model UI (Phase 4) without a separate code path.
    """

    id: str
    label: str
    kind: str  # "API" | "LOCAL_OPENAI" | "OLLAMA" | "LM_STUDIO"
    model: str = ""
    purpose: str = "chat"  # chat | embedding | rerank
    endpoint: str = ""
    cred_ref: str = ""  # keyring key; empty => no credential
    model_path: str = ""
    profile: str = "balanced"


def _safe_epoch(v: Any) -> float:
    """Parse a persisted selection timestamp; corrupt -> 0.0 (pre-migration).

    Observability/persistence must never break config load (nothing here may
    block a user response), so any unparseable value degrades to 0.0 and the
    boot path falls back to the legacy heuristic + warning (T3).
    """
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_role_bindings(raw: Any) -> list:
    """Coerce a persisted ``role_bindings`` value into a list of dicts.

    A corrupt value (string, dict, None) must degrade to ``[]`` so the router's
    seed loop never iterates a non-list (REQ-3 edge case: corrupt/partial config
    -> boot unbound, never guess). Each entry is kept as-is (dict) or dropped.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for b in raw:
        if isinstance(b, dict):
            out.append(b)
    return out


def _local_stem(model_id: str) -> str:
    """Derive a stable local-provider id stem from a model/file name.

    ``"qwen3-9b-q4_k_m.gguf"`` -> ``"qwen3-9b"``. Used to namespace local
    provider ids as ``local:<stem>`` (REQ-4 AC1) so two local models never
    collide and the bare literal ``"local"`` is never used as an id.
    """
    stem = (model_id or "").strip()
    for ext in (".gguf", ".gguf.txt", ".bin", ".safetensors"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    stem = stem.strip().lower()
    return stem or "local"


def _local_model_endpoint() -> str:
    """Resolve the local-model server endpoint for the migration path (T3 /
    REQ-8).

    Single source of truth: ``LocalModelManager.PORT``, which itself honors
    ``IRIS_LOCAL_MODEL_PORT`` (default 8082). This used to be hardcoded to
    ``8081`` here — the VISION server's port, not the local model server's —
    so a migrated binding pointed at the wrong process.

    Imported lazily (not at module scope) so config load — which runs on
    every startup — never pays for importing ``local_model_manager`` unless a
    legacy flat config with ``local_model_id`` is actually being migrated.
    Degrades to the same 8082 default on any import failure rather than
    raising out of config load (nothing here may block a user response).
    """
    try:
        from backend.agent.local_model_manager import LocalModelManager

        port = LocalModelManager.PORT
    except Exception as exc:
        logger.warning(
            f"[Config] Could not resolve LocalModelManager.PORT during "
            f"migration ({exc}); falling back to the documented default port."
        )
        port = int(os.environ.get("IRIS_LOCAL_MODEL_PORT", "8082"))
    return f"http://127.0.0.1:{port}"


def _build_providers(raw: Any) -> "Dict[str, ProviderEntry]":
    """Normalize a persisted ``providers`` value into ``id -> ProviderEntry``.

    Accepts either a dict (id -> entry dict) or a list of entry dicts. Unknown
    keys are ignored so the shape can grow additively.
    """
    out: Dict[str, ProviderEntry] = {}
    if not raw:
        return out
    items = raw.values() if isinstance(raw, dict) else raw
    for item in items:
        if not isinstance(item, dict) or "id" not in item:
            continue
        out[item["id"]] = ProviderEntry(
            id=item["id"],
            label=item.get("label", item["id"]),
            kind=item.get("kind", "API"),
            model=item.get("model", ""),
            purpose=item.get("purpose", "chat"),
            endpoint=item.get("endpoint", ""),
            cred_ref=item.get("cred_ref", ""),
            model_path=item.get("model_path", ""),
            profile=item.get("profile", "balanced"),
        )
    return out


@dataclass
class InferenceConfig:
    """Model provider and generation parameters."""

    # Provider selection
    provider: str = "api"  # api | lm_studio | ollama | iris_local
    reasoning_model: str = ""
    tool_execution_model: str = ""

    # API provider settings
    api_base_url: str = ""
    api_key: str = ""

    # LM Studio settings
    lm_studio_url: str = "http://localhost:1234"

    # Ollama settings
    ollama_url: str = "http://localhost:11434"

    # Local GGUF settings (from local_model card)
    local_model_path: str = ""
    local_model_id: str = ""
    local_model_profile: str = (
        "balanced"  # eco | balanced | performance | voice_first | research | custom
    )
    local_model_gpu_layers: int = -1
    local_model_ctx: int = 16384
    local_model_status: str = "unloaded"  # unloaded | loaded | loading | error
    models_directory: str = ""
    hardware_profile: str = "balanced"

    # REQ-10 (T15): user-chosen vision fallback ladder — a list of model
    # `path` strings (the SAME identity scan_models()/the model browser
    # already use to address a model), ORDER = priority. Empty/absent means
    # "auto" (REQ-10 AC5: widest has_vision model that fits, chosen with NO
    # hardcoded id). Never a model id/name literal — only what the user
    # actually has on disk and picked.
    vision_fallback_ladder: list = field(default_factory=list)

    # Generation parameters
    temperature: float = 0.6
    max_tokens: int = 4096
    reasoning_effort: str = "balanced"  # fast | balanced | accurate
    response_length: str = "medium"  # short | medium | long
    thinking_style: str = "balanced"
    tool_mode: str = "auto"

    # Swarm settings
    swarm_enabled: bool = False
    swarm_mode: str = "SWARM_TURBO"
    swarm_worker_count: int = 2
    gpu_layers: int = 0
    worker_context: str = "auto"

    # Persisted router role bindings (SLICE 5) — list of
    # {role, instance_id, model_override} dicts consumed by InferenceRouter.
    role_bindings: list = field(default_factory=list)

    # Model-selection authority (specs/model-selection-authority T1/REQ-3/REQ-5):
    # epoch of the last EXPLICIT user selection (card APPLY / preserve=False /
    # set_role_binding). 0.0 = pre-migration / never selected. Compared against
    # per-binding selected_at at boot (newer record wins); additive so old
    # configs load unchanged.
    provider_selected_at: float = 0.0

    # Swarm-defer seam (specs/model-selection-authority T4b/REQ-2): a switch
    # that arrived while swarm was active, recorded as a timestamped intent
    # instead of silently dropped. Shape: {provider, reasoning_model,
    # tool_execution_model, selected_at}. None = no deferred intent. Applying
    # it on swarm end belongs to the future swarm spec; this spec only
    # guarantees it is recorded (persisted + visible in snapshot), never lost.
    deferred_selection: Optional[Dict[str, Any]] = None

    # Phase 1 Wave 2: ONE provider collection (API + local) keyed by id.
    # Replaces the scattered flat fields (api_base_url/api_key/local_model_*).
    # ``endpoint`` and ``cred_ref`` live in the same record (REQ-5 AC3).
    providers: Dict[str, "ProviderEntry"] = field(default_factory=dict)
    # Schema version. 1 = legacy flat fields; 2 = collection present. The
    # migrator (T3) runs only when this is < 2, so it cannot re-run forever.
    config_version: int = 1

    def validate_providers(self) -> None:
        """Session 268 (pin_60d8fdeee344): schema guard for the providers
        collection. Prevents persistence-corruption classes like a local
        provider with kind=API / model_path='' / endpoint=openai, which
        came from a Cerebras role-binding write under a prior backend and
        stayed in iris_config.json as a ghost entry that hijacked the
        Brain/Tool dropdown.

        Rules:
          - ``local:*`` ids MUST have kind in {INPROCESS, LOCAL_OPENAI}
            and a non-empty model_path. Anything else is a stale or
            corrupted binding and is dropped with a warning.
          - Non-local ids (api / cerebras / ollama / …) MUST NOT have
            model_path set. A model_path on an API binding is a leftover
            from a prior local-binding write and is cleared (model_path
            is a LOCAL-only field).
          - ``local_model_id`` is the SOURCE OF TRUTH for the local
            provider's id. If ``providers`` carries a local:* entry whose
            stem does NOT match the current ``local_model_id``, the entry
            is dropped — its model no longer matches what the user has
            selected in the dashboard.
        """
        valid_local_kinds = {"INPROCESS", "LOCAL_OPENAI"}
        inf = self  # dataclass name
        kept: Dict[str, "ProviderEntry"] = {}
        for pid, entry in (self.providers or {}).items():
            try:
                if pid.startswith("local:"):
                    if entry.kind not in valid_local_kinds:
                        logger.warning(
                            f"[Config] validate_providers: dropping {pid} "
                            f"(kind={entry.kind} not in {valid_local_kinds})"
                        )
                        continue
                    if not entry.model_path:
                        logger.warning(
                            f"[Config] validate_providers: dropping {pid} "
                            "(empty model_path on local entry)"
                        )
                        continue
                    # COMPARE LIKE WITH LIKE (2026-09-28). This was an exact
                    # string match against _local_stem(local_model_id), so an
                    # entry saved with the file's own spelling
                    # ('LFM2.5-2.6B-QAD-Q4_0.gguf') was DROPPED whenever
                    # local_model_id had been normalised ('lfm2.5-2.6b-qad-q4_0')
                    # — the SAME model, written two ways. Measured live:
                    #   [Config] validate_providers: dropping
                    #   local:LFM2.5-2.6B-QAD-Q4_0
                    #   (model='LFM2.5-2.6B-QAD-Q4_0.gguf' != current
                    #    local_model_id='lfm2.5-2.6b-qad-q4_0')
                    # The role binding points AT that id, so dropping the entry
                    # left tool_execution bound to something unresolvable — the
                    # very failure this validator exists to prevent.
                    # Both sides are now stemmed, .gguf-stripped and lowered, so
                    # presentation can never decide whether a binding resolves.
                    _entry_stem = (
                        _local_stem(entry.model).lower()
                        .removesuffix(".gguf")
                    )
                    _current_stem = (
                        _local_stem(inf.local_model_id).lower()
                        .removesuffix(".gguf")
                    )
                    if inf.local_model_id and _entry_stem != _current_stem:
                        logger.warning(
                            f"[Config] validate_providers: dropping {pid} "
                            f"(model stem {_entry_stem!r} != current "
                            f"local_model_id stem {_current_stem!r})"
                        )
                        continue
                else:
                    if entry.model_path:
                        logger.warning(
                            f"[Config] validate_providers: clearing model_path on "
                            f"{pid} (non-local binding had a model_path)"
                        )
                        entry = ProviderEntry(
                            id=entry.id,
                            label=entry.label,
                            kind=entry.kind,
                            model=entry.model,
                            endpoint=entry.endpoint,
                            cred_ref=entry.cred_ref,
                            model_path="",
                            profile=entry.profile,
                        )
                kept[pid] = entry
            except Exception as _vex:
                logger.warning(
                    f"[Config] validate_providers: failed to inspect {pid}: {_vex}"
                )
        if len(kept) != len(self.providers or {}):
            self.providers = kept
            logger.info(
                f"[Config] validate_providers: providers reduced from "
                f"{len(self.providers or {})} to {len(kept)}"
            )

    def auto_derive_local_ctx(self, current_free_vram_gb: float) -> None:
        """Session 268 (pin_60d8fdeee344): fall back to auto-derive when the
        saved ``local_model_ctx`` was computed for a different free-VRAM
        snapshot than the one at boot. The user only sees one slider; the
        deriver already picks the LARGEST n_ctx that fits, so a stale >0
        value is always wrong when the boot VRAM is different.

        Heuristic: if ``local_model_ctx`` > 0 and the saved value needs
        more VRAM than the deriver would pick today, reset to 0
        (auto-derive). The cap used here is the same per-profile threshold
        LocalModelManager.derive_config uses to pick the largest fitting
        context; we just re-derive it.
        """
        import json as _json
        import os as _os
        # Allow opt-out for users who insist on a hard-coded ctx
        if _os.environ.get("IRIS_LOCAL_CTX_HARDCODE", "0") == "1":
            return
        if not (self.local_model_ctx and self.local_model_ctx > 0):
            return
        # Cheap heuristic: anything above 16k with < 4 GB free needs auto.
        # Keeps the slider's small values (8k/16k for tight VRAM) intact.
        if current_free_vram_gb >= 4.0 and self.local_model_ctx <= 16384:
            return
        if current_free_vram_gb < 4.0 and self.local_model_ctx <= 8192:
            return
        logger.info(
            f"[Config] auto_derive_local_ctx: saved local_model_ctx="
            f"{self.local_model_ctx} looks too large for {current_free_vram_gb:.1f} "
            f"GB free VRAM at boot — resetting to 0 (auto-derive)"
        )
        self.local_model_ctx = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def migrate_flat_to_collection(self) -> None:
        """Migrate legacy flat provider fields into the unified ``providers``
        collection (T3).

        Gated on ``config_version`` so it runs exactly once — NOT on "flat
        fields present", which would re-run forever. If the collection is
        already populated it is treated as authoritative and the flat fields are
        ignored (never merged). Migrates BOTH the API provider (api_base_url /
        api_key) AND the local model (local_model_*) in one pass, moves the
        migrated key into the keyring (without re-entry), and rewrites
        ``role_bindings`` so the literal ``"local"`` becomes its namespaced id.
        """
        if self.config_version >= 2:
            return
        # Collection already present and non-empty -> it wins, flat ignored.
        if self.providers:
            self.config_version = 2
            return

        new_providers: Dict[str, "ProviderEntry"] = {}
        provider = getattr(self, "provider", "api")
        api_base = getattr(self, "api_base_url", "")
        api_key = getattr(self, "api_key", "")
        if provider and provider != "local":
            kind = {
                "lm_studio": "LM_STUDIO",
                "ollama": "OLLAMA",
                "iris_local": "LOCAL_OPENAI",
            }.get(provider, "API")
            entry = ProviderEntry(
                id=provider,
                label=provider.upper(),
                kind=kind,
                model=getattr(self, "reasoning_model", "") or "",
                endpoint=api_base or "",
                # cred_ref is the keyring key (== id); the credential itself is
                # moved into the keyring, never persisted in config.
                cred_ref=provider if api_key else "",
            )
            new_providers[provider] = entry
            if api_key:
                try:
                    from .agent.inference.keyring import set_secret

                    set_secret(provider, api_key)
                except Exception as exc:
                    # Keyring write failed: do NOT clear the flat field below —
                    # losing the user's only copy of the key is worse than the
                    # (existing) plaintext-in-config risk. Log so the failure
                    # is visible instead of silently keeping the credential on
                    # disk indefinitely.
                    logger.warning(
                        f"[Config] Failed to move api_key for provider "
                        f"'{provider}' into the keyring during migration: {exc}. "
                        f"Leaving the flat api_key field in place (unmigrated) "
                        f"rather than losing the credential."
                    )
                else:
                    # Keyring write succeeded — the credential now lives ONLY
                    # in the keyring. Clear the flat dataclass field so
                    # to_dict()/asdict() (and therefore save_config()) never
                    # serializes the raw key into iris_config.json again
                    # (REQ-6 AC4 / REQ-7's core promise).
                    self.api_key = ""

        local_id = getattr(self, "local_model_id", "")
        if local_id:
            ns_id = f"local:{_local_stem(local_id)}"
            new_providers[ns_id] = ProviderEntry(
                id=ns_id,
                label="Local Model",
                kind="LOCAL_OPENAI",
                model=local_id,
                endpoint=_local_model_endpoint(),
            )

        self.providers = new_providers

        # Migrate role bindings (literal "local" -> namespaced id).
        migrated: list = []
        for b in self.role_bindings or []:
            if isinstance(b, dict):
                inst_id = b.get("instance_id")
                if inst_id == "local" and local_id:
                    inst_id = f"local:{_local_stem(local_id)}"
                migrated.append({**b, "instance_id": inst_id})
            else:
                migrated.append(b)
        self.role_bindings = migrated
        self.config_version = 2

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InferenceConfig":
        cfg = cls(
            provider=d.get("provider", d.get("active_provider", "api")),
            reasoning_model=d.get("reasoning_model", ""),
            tool_execution_model=d.get("tool_execution_model", ""),
            api_base_url=d.get("api_base_url", ""),
            api_key=d.get("api_key", ""),
            lm_studio_url=d.get("lm_studio_url", "http://localhost:1234"),
            ollama_url=d.get("ollama_url", "http://localhost:11434"),
            local_model_path=d.get("local_model_path", ""),
            local_model_id=d.get("local_model_id", ""),
            local_model_profile=d.get("local_model_profile", "balanced"),
            local_model_gpu_layers=int(d.get("local_model_gpu_layers", -1)),
            local_model_ctx=int(d.get("local_model_ctx", 16384)),
            local_model_status=d.get("local_model_status", "unloaded"),
            models_directory=d.get("models_directory", ""),
            hardware_profile=d.get("hardware_profile", "balanced"),
            vision_fallback_ladder=list(d.get("vision_fallback_ladder", []) or []),
            temperature=float(d.get("temperature", 0.6)),
            max_tokens=int(d.get("max_tokens", 4096)),
            reasoning_effort=d.get("reasoning_effort", "balanced"),
            response_length=d.get("response_length", "medium"),
            thinking_style=d.get("thinking_style", "balanced"),
            tool_mode=d.get("tool_mode", "auto"),
            swarm_enabled=bool(d.get("swarm_enabled", False)),
            swarm_mode=d.get("swarm_mode", "SWARM_TURBO"),
            swarm_worker_count=int(d.get("swarm_worker_count", 2)),
            gpu_layers=int(d.get("gpu_layers", 0)),
            worker_context=d.get("worker_context", "auto"),
            role_bindings=_normalize_role_bindings(d.get("role_bindings", [])),
            provider_selected_at=_safe_epoch(d.get("provider_selected_at", 0.0)),
            deferred_selection=d.get("deferred_selection")
            if isinstance(d.get("deferred_selection"), dict)
            else None,
            providers=_build_providers(d.get("providers", {})),
            config_version=int(d.get("config_version", 1)),
        )
        # Migrate legacy flat fields into the unified collection exactly once
        # (gated on config_version). Idempotent: a re-loaded config with
        # config_version >= 2 is left untouched.
        cfg.migrate_flat_to_collection()
        return cfg


@dataclass
class SystemConfig:
    """Launcher mode and other system-level settings."""

    mode: str = "personal"  # personal | developer
    projects: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SystemConfig":
        return cls(
            mode=d.get("mode", "personal"),
            projects=d.get("projects", []),
        )


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------
@dataclass
class TTSConfig:
    """Text-to-Speech configuration."""

    tts_voice: str = "Cloned Voice"
    tts_enabled: bool = True
    speaking_rate: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tts_voice": self.tts_voice,
            "tts_enabled": self.tts_enabled,
            "speaking_rate": self.speaking_rate,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "TTSConfig":
        return cls(
            tts_voice=raw.get("tts_voice", "Cloned Voice"),
            tts_enabled=raw.get("tts_enabled", True),
            speaking_rate=raw.get("speaking_rate", 1.0),
        )


@dataclass
class IRISConfig:
    """Complete IRIS configuration — the single source of truth."""

    routing: RoutingConfig = field(default_factory=RoutingConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    swarm_roles: SwarmRoleConfig = field(default_factory=SwarmRoleConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    ports: PortConfig = field(default_factory=PortConfig)
    field_values: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Session 247: unknown top-level keys (e.g. "approved_tools", "mode" —
    # written by the permission system and the launcher) are captured here on
    # load and re-emitted on save. Without this, EVERY save_config call
    # (including routine save_field_values from the frontend) silently DROPPED
    # foreign keys — which is why standing tool approvals vanished minutes
    # after being written and the agent re-asked permission forever.
    extra: Dict[str, Any] = field(default_factory=dict)

    _KNOWN_KEYS = frozenset({
        "routing", "inference", "swarm_roles", "system",
        "tts", "ports", "field_values",
    })

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "routing": self.routing.to_dict(),
            "inference": self.inference.to_dict(),
            "swarm_roles": self.swarm_roles.to_dict(),
            "system": self.system.to_dict(),
            "tts": self.tts.to_dict(),
            "ports": self.ports.to_dict(),
        }
        if self.field_values:
            d["field_values"] = self.field_values
        # Session 247: re-emit foreign keys (approved_tools, mode, …) so
        # save_config can never silently drop them again.
        if self.extra:
            for k, v in self.extra.items():
                d.setdefault(k, v)
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "IRISConfig":
        known = cls._KNOWN_KEYS
        extra = {k: v for k, v in raw.items() if k not in known}
        return cls(
            routing=RoutingConfig.from_dict(raw.get("routing", {})),
            inference=InferenceConfig.from_dict(raw.get("inference", raw)),
            swarm_roles=SwarmRoleConfig.from_dict(raw.get("swarm_roles", {})),
            system=SystemConfig.from_dict(raw.get("system", raw)),
            tts=TTSConfig.from_dict(raw.get("tts", {})),
            ports=PortConfig.from_dict(raw.get("ports", {})),
            field_values=raw.get("field_values", {}),
            extra=extra,
        )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _apply_env_overrides(cfg: IRISConfig) -> None:
    """Override config fields from environment variables.

    Runs AFTER JSON loading so env vars always win.
    IRIS-owned ports already read env vars at PortConfig import time
    via _env_int() — this handles the provider URLs.
    """
    # Provider endpoints (these are URLs IRIS connects to, not binds to)
    lm_url = _env_str("IRIS_LMSTUDIO_URL", "")
    if lm_url:
        cfg.inference.lm_studio_url = lm_url
    ollama_url = _env_str("IRIS_OLLAMA_URL", "")
    if ollama_url:
        cfg.inference.ollama_url = ollama_url


# Field names that must never persist in iris_config.json. The save path
# (save_field_values) strips these; the load-time scrub below heals files
# that predate the stripping (or were restored from a backup).
_SCRUB_SECRET_FIELDS = frozenset({"api_key", "exa_api_key"})


def _scrub_persisted_secrets(cfg: IRISConfig) -> bool:
    """One-way hygiene pass over an already-loaded config.

    Moves surviving secret values out of persisted config into the OS
    keyring, then clears them. Fill-gap ONLY: a value is written to the
    keyring solely when the keyring holds nothing yet (an explicit Apply
    always wins and is the only writer that may overwrite). A cleared value
    is cleared only after a verified keyring round-trip, so the only copy
    is never at risk — mirroring migrate_flat_to_collection's rule.

    Attribution: ``search.exa_api_key`` -> keyring ``"exa"``;
    ``<section>.api_key`` -> that section's ``model_provider`` sibling when
    present, else left in place and logged. Covers the legacy top-level
    ``model_selection`` block too (dead ballast preserved by ``extra``).

    Returns True when anything changed (caller re-saves). Cheap no-op once
    the file is clean.
    """
    changed = False

    def _adopt(secret: str, slot: str | None, where: str) -> str:
        """Return the value to keep in config ("" when safely migrated)."""
        nonlocal changed
        if not secret:
            return secret
        if not slot:
            logger.warning(
                f"[Config] secret at {where} has no attributable provider — "
                f"left in place (not secure, needs a manual move)"
            )
            return secret
        try:
            from .agent.inference.keyring import get_secret, set_secret

            if not get_secret(slot):
                set_secret(slot, secret)
                if get_secret(slot) != secret:
                    logger.warning(
                        f"[Config] keyring round-trip failed for {where} — "
                        f"left in place rather than losing the credential"
                    )
                    return secret
            changed = True
            logger.info(
                f"[Config] moved persisted secret at {where} into the "
                f"keyring (startup scrub)"
            )
            return ""
        except Exception as exc:
            logger.warning(f"[Config] secret scrub failed at {where}: {exc}")
            return secret

    fv = cfg.field_values or {}
    for section, fields in fv.items():
        if not isinstance(fields, dict):
            continue
        for name in [k for k in fields if isinstance(k, str) and k.strip().lower() in _SCRUB_SECRET_FIELDS]:
            slot = "exa" if name.strip().lower() == "exa_api_key" else (
                fields.get("model_provider") or None
            )
            new_val = _adopt(fields[name], slot, f"field_values.{section}.{name}")
            if new_val != fields[name]:
                fields[name] = new_val

    extra_ms = (cfg.extra or {}).get("model_selection")
    if isinstance(extra_ms, dict) and extra_ms.get("api_key"):
        slot = extra_ms.get("model_provider") or None
        new_val = _adopt(extra_ms["api_key"], slot, "model_selection.api_key")
        if new_val != extra_ms["api_key"]:
            extra_ms["api_key"] = new_val

    return changed


def load_config() -> IRISConfig:
    """Load config from data/iris_config.json.

    Environment variables partially override loaded fields:
      IRIS_LMSTUDIO_URL     -> inference.lm_studio_url
      IRIS_OLLAMA_URL       -> inference.ollama_url

    IRIS-owned ports (backend/brain/vision) are set at PortConfig field
    definition time via _env_int() — they never hit the JSON at all.

    If the file is missing or malformed, returns defaults.
    """
    cfg: IRISConfig
    try:
        if _IRIS_CONFIG_PATH.exists():
            with open(_IRIS_CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cfg = IRISConfig.from_dict(raw)
        else:
            cfg = IRISConfig()
    except Exception as exc:
        logger.warning(f"[Config] Failed to load {_IRIS_CONFIG_PATH}: {exc}")
        cfg = IRISConfig()

    # Environment variables override even loaded JSON values.
    _apply_env_overrides(cfg)

    # Session 268 (pin_60d8fdeee344): validate the providers collection
    # AFTER env overrides, BEFORE returning. Drops ghost entries like
    # local:foo kind=API / model_path='' (the state we cleaned up manually
    # in this session). Cheap (a dict scan), and prevents the dropdown
    # from being hijacked by stale entries on every boot.
    try:
        cfg.inference.validate_providers()
    except Exception as _vex:
        logger.warning(f"[Config] validate_providers failed (non-fatal): {_vex}")

    # Self-healing secret hygiene: move any secret that survived on disk
    # (predating the save-time stripping, or restored from backup) into the
    # keyring. Re-saves only when something actually moved.
    try:
        if _scrub_persisted_secrets(cfg):
            save_config(cfg)
    except Exception as _sexc:
        logger.warning(f"[Config] secret scrub failed (non-fatal): {_sexc}")

    return cfg


def save_config(cfg: IRISConfig) -> None:
    """Atomically write config to data/iris_config.json."""
    try:
        _ensure_data_dir()
        tmp = _IRIS_CONFIG_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, indent=2)
        # Atomic rename on Windows (os.replace works cross-platform)
        os.replace(tmp, _IRIS_CONFIG_PATH)
        logger.info(f"[Config] Saved config to {_IRIS_CONFIG_PATH}")
    except Exception as exc:
        logger.warning(f"[Config] Failed to save config: {exc}")


# ── Field values persistence (wheel-view form state) ──────────────────────
# Separate from structured IRISConfig because field_values are raw form values
# that are saved/loaded alongside the structured config.


def save_field_values(values: Dict[str, Dict[str, Any]]) -> None:
    """Persist raw field_values to the config file so they survive
    frontend remounts and page reloads.

    Secrets are stripped before the write: card inputs named ``api_key``
    or ``exa_api_key`` (e.g. model_selection.api_key, the pasted provider
    key) must never reach disk — live values already went to the OS keyring
    at Apply time (set_model_selection / the settings field handler), and
    the in-memory session copy keeps serving runtime readers. Persisting
    the echo here is what kept live credentials in iris_config.json
    indefinitely.
    """
    try:
        cfg = load_config()
        scrubbed: Dict[str, Dict[str, Any]] = {}
        for section, fields in (values or {}).items():
            if isinstance(fields, dict):
                scrubbed[section] = {
                    k: v for k, v in fields.items()
                    if not (isinstance(k, str) and k.strip().lower() in _SCRUB_SECRET_FIELDS)
                }
            else:
                scrubbed[section] = fields
        cfg.field_values = scrubbed
        save_config(cfg)
    except Exception as exc:
        logger.warning(f"[Config] Failed to save field values: {exc}")


def load_field_values() -> Dict[str, Dict[str, Any]]:
    """Load previously persisted field_values from config file."""
    try:
        cfg = load_config()
        return cfg.field_values or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Backward-compatible helpers (mirrors old _load/_save_iris_config)
# ---------------------------------------------------------------------------


def _load_iris_config_compat() -> Dict[str, Any]:
    """Return the raw dict for code that hasn't migrated to IRISConfig yet."""
    return load_config().to_dict()


def _save_iris_config_compat(data: Dict[str, Any]) -> None:
    """Merge *data* into the existing config and write it back."""
    cfg = load_config()
    cfg.inference = InferenceConfig.from_dict(data)
    cfg.system = SystemConfig.from_dict(data)
    if "routing" in data:
        cfg.routing = RoutingConfig.from_dict(data["routing"])
    save_config(cfg)
