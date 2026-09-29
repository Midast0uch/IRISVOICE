"""
Logging Configuration for IRIS Backend

This module provides centralized logging configuration for all backend components.
It sets up structured logging with JSON formatting, file rotation, and context injection.
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.monitoring.structured_logger import (
    ShareableRotatingFileHandler,
    configure_logging,
    StructuredLogger,
)


# Default log directory: the repo-level .iris-logs/ folder every launcher
# shares (process manager, start-backend.py, Tauri sidecar, start_all.py).
# In-process file logging (here) covers ALL of them — manager stdout capture
# alone only covers manager-launched processes, which is how live sessions
# became undiagnosable. One folder, pid-stamped files, no interleaving.
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / ".iris-logs"

# Log levels
LOG_LEVEL_DEBUG = "DEBUG"
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARNING = "WARNING"
LOG_LEVEL_ERROR = "ERROR"
LOG_LEVEL_CRITICAL = "CRITICAL"


def setup_backend_logging(
    log_level: Optional[str] = None,
    log_dir: Optional[Path] = None,
    enable_file_logging: bool = True,
) -> StructuredLogger:
    """
    Set up logging for the IRIS backend.

    This function should be called once during backend initialization to configure
    the global logging system.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                  Defaults to INFO, or reads from IRIS_LOG_LEVEL env var.
        log_dir: Directory for log files. Defaults to <repo>/.iris-logs/
                 (IRIS_LOG_DIR overrides). The file itself is always
                 pid-stamped (backend-<ts>-pid<PID>.log) so concurrent
                 backend instances never interleave in one file.
        enable_file_logging: Whether to enable file logging (default: True)

    Returns:
        Configured StructuredLogger instance

    Example:
        >>> from backend.core.logging_config import setup_backend_logging
        >>> logger = setup_backend_logging(log_level="DEBUG")
        >>> logger.info("Backend initialized")
    """
    # Get log level from environment or use default
    if log_level is None:
        log_level = os.environ.get("IRIS_LOG_LEVEL", LOG_LEVEL_INFO)

    # Get log directory (override via IRIS_LOG_DIR; default .iris-logs/).
    if log_dir is None:
        log_dir = Path(os.environ.get("IRIS_LOG_DIR", str(DEFAULT_LOG_DIR)))

    # Ensure log directory exists
    log_dir.mkdir(parents=True, exist_ok=True)

    # Per-instance file: pid-stamped so a manager backend, a Tauri sidecar
    # backend, or any two concurrent instances never share (and garble) one
    # file. Rotation still applies per file.
    _stamp = f"backend-{datetime.now():%Y%m%d-%H%M%S}-pid{os.getpid()}.log"

    # Configure logging
    if enable_file_logging:
        log_file = log_dir / _stamp
        logger = configure_logging(log_level=log_level, log_file=log_file)
    else:
        logger = configure_logging(log_level=log_level)

    # Configure root logger for legacy logging.getLogger(__name__) calls
    # (used by agent_kernel.py and other modules that don't use StructuredLogger).
    # Without this, all logger.info/warning/error() calls from those modules
    # silently disappear because the "irisvoice" structured logger has propagate=False
    # and Python's root logger has no handlers by default.
    _root = logging.getLogger()
    if not _root.handlers:
        _fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # stdout handler — visible in terminal
        _handler = logging.StreamHandler(sys.stdout)
        _handler.setFormatter(_fmt)
        _root.addHandler(_handler)

        # File handler — so module-level loggers (backend.iris_gateway, etc.)
        # are captured in irisvoice.log alongside the structured logger output.
        #
        # ONE HANDLE PER FILE (2026-09-27) — this is the ROOT-CAUSE fix, and it
        # replaces the ShareableRotatingFileHandler tolerance below as the primary
        # remedy. The RotatingFileHandler above (configure_logging(log_file=...))
        # already has THIS SAME path open. On Windows a rename fails while any
        # other handle holds the file, so a second handle here did not merely
        # cause a one-off error: it made rotation IMPOSSIBLE, forever. Measured:
        # 18,097 PermissionErrors in an hour, each written into the file it could
        # not rotate (489 MB, un-greppable) plus ~5,600 CPU-seconds.
        # The tolerant handler stops the storm, but on its own it would leave the
        # log growing without bound for ever — a cure for the symptom, not the
        # cause. Sharing the ONE existing handler removes the second handle
        # entirely, so the rollover can actually succeed.
        # CONSEQUENCE, stated plainly: root-logger records now pass through the
        # structured handler and are therefore JSON-formatted, like the rest of
        # this file. The previous plain format still reaches the manager's
        # captured stdout log. One file, one handle, working rotation.
        if enable_file_logging:
            _shared = None
            try:
                for _h in getattr(logger, "logger", logger).handlers:
                    if isinstance(_h, logging.handlers.RotatingFileHandler):
                        _shared = _h
                        break
            except Exception:
                _shared = None
            if _shared is not None:
                _root.addHandler(_shared)
            else:
                # No shared handler to reuse (unexpected) — keep the tolerant
                # one so a second handle at least cannot storm.
                _file_handler = ShareableRotatingFileHandler(
                    log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
                    encoding="utf-8",
                )
                _file_handler.setFormatter(_fmt)
                _root.addHandler(_file_handler)

        _root.setLevel(getattr(logging, log_level.upper()))

    # Bridge ALL backend logging into the in-memory LogManager so the Monitor's
    # live log view (system/voice/mcp/agent) is populated — including the
    # tool-resolution tree. Attached to the root logger so it captures every
    # module regardless of named-logger / singleton init order. Idempotent.
    try:
        from backend.monitor.logs import get_log_manager
        get_log_manager().attach_to_root()
    except Exception as _lm_exc:  # logging must never break startup
        print(f"[warn] could not attach LogManager bridge: {_lm_exc}", file=sys.stderr)

    logger.info(
        "Logging configured",
        log_level=log_level,
        log_dir=str(log_dir) if enable_file_logging else None,
        file_logging_enabled=enable_file_logging,
    )

    return logger


def get_component_logger(component_name: str) -> StructuredLogger:
    """
    Get a logger for a specific component with the component name set in context.

    Args:
        component_name: Name of the component (e.g., "websocket", "agent", "voice")

    Returns:
        StructuredLogger with component context set

    Example:
        >>> from backend.core.logging_config import get_component_logger
        >>> logger = get_component_logger("websocket")
        >>> logger.info("WebSocket connection established")
    """
    from backend.monitoring.structured_logger import get_logger

    logger = get_logger()
    logger.set_context(component=component_name)
    return logger


# Component-specific logger getters for convenience
def get_websocket_logger() -> StructuredLogger:
    """Get logger for WebSocket components."""
    return get_component_logger("websocket")


def get_session_logger() -> StructuredLogger:
    """Get logger for session management components."""
    return get_component_logger("session")


def get_state_logger() -> StructuredLogger:
    """Get logger for state management components."""
    return get_component_logger("state")


def get_agent_logger() -> StructuredLogger:
    """Get logger for agent components."""
    return get_component_logger("agent")


def get_voice_logger() -> StructuredLogger:
    """Get logger for voice processing components."""
    return get_component_logger("voice")


def get_tool_logger() -> StructuredLogger:
    """Get logger for tool/MCP components."""
    return get_component_logger("tools")


def get_gateway_logger() -> StructuredLogger:
    """Get logger for gateway/routing components."""
    return get_component_logger("gateway")


# Export all
__all__ = [
    "setup_backend_logging",
    "get_component_logger",
    "get_websocket_logger",
    "get_session_logger",
    "get_state_logger",
    "get_agent_logger",
    "get_voice_logger",
    "get_tool_logger",
    "get_gateway_logger",
    "LOG_LEVEL_DEBUG",
    "LOG_LEVEL_INFO",
    "LOG_LEVEL_WARNING",
    "LOG_LEVEL_ERROR",
    "LOG_LEVEL_CRITICAL",
]
