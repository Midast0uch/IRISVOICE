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
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("irisvoice")

# ---------------------------------------------------------------------------
# Config write lock — serializes concurrent load-modify-save cycles to
# prevent race conditions when multiple async handlers write config.
# ---------------------------------------------------------------------------
_config_lock = threading.Lock()


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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InferenceConfig":
        return cls(
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
        )


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "routing": self.routing.to_dict(),
            "inference": self.inference.to_dict(),
            "swarm_roles": self.swarm_roles.to_dict(),
            "system": self.system.to_dict(),
            "tts": self.tts.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "IRISConfig":
        return cls(
            routing=RoutingConfig.from_dict(raw.get("routing", {})),
            inference=InferenceConfig.from_dict(raw.get("inference", raw)),
            swarm_roles=SwarmRoleConfig.from_dict(raw.get("swarm_roles", {})),
            system=SystemConfig.from_dict(raw.get("system", raw)),
            tts=TTSConfig.from_dict(raw.get("tts", {})),
        )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def load_config() -> IRISConfig:
    """Load config from data/iris_config.json.

    If the file is missing or malformed, returns defaults.
    """
    try:
        if _IRIS_CONFIG_PATH.exists():
            with open(_IRIS_CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return IRISConfig.from_dict(raw)
    except Exception as exc:
        logger.warning(f"[Config] Failed to load {_IRIS_CONFIG_PATH}: {exc}")
    return IRISConfig()


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
