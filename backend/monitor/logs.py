"""
Log Manager - System/voice/MCP log collection and export
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import deque
from dataclasses import dataclass, asdict


@dataclass
class LogEntry:
    """A single log entry"""
    timestamp: str
    level: str  # DEBUG, INFO, WARNING, ERROR
    source: str  # system, voice, mcp, agent
    message: str
    details: Dict[str, Any] = None


# ── Source mapping ───────────────────────────────────────────────────────────
# Maps a Python module name (record.module, e.g. "backend.agent.tool_decision")
# to one of the Monitor's four organized buckets. This MUST stay aligned with
# LogManager.get_logs_by_source() and MonitorLogsPanel's source rendering.
_SOURCE_PREFIX_MAP = [
    ("backend.agent", "agent"),
    ("backend.tools", "agent"),
    ("agent.", "agent"),
    ("backend.audio", "voice"),
    ("backend.voice", "voice"),
    ("audio.", "voice"),
    ("voice.", "voice"),
    ("backend.mcp", "mcp"),
    ("backend.integrations", "mcp"),
    ("mcp.", "mcp"),
]


def _module_to_source(module: str) -> str:
    """Derive a Monitor bucket (system/voice/mcp/agent) from a module name."""
    if not module:
        return "system"
    for prefix, bucket in _SOURCE_PREFIX_MAP:
        if module.startswith(prefix) or ("." + prefix) in module:
            return bucket
    # Fall back to the module's top-level package, truncated to a sane label.
    top = module.split(".")[0]
    if top in ("system", "voice", "mcp", "agent"):
        return top
    return "system"


class LogManagerHandler(logging.Handler):
    """A logging.Handler that forwards every backend log record into the
    in-memory LogManager, organized by the Monitor's source buckets.

    Attaching this to the ROOT logger (see LogManager.attach_to_root) captures
    ALL backend modules — including the tool-resolution tree (agent_kernel,
    tool_decision, iris_gateway) — regardless of which named logger emitted
    the record or how the StructuredLogger singleton was first initialized.
    This is what makes the Monitor's live log view actually populate.
    """

    def __init__(self, manager: "LogManager", level: int = logging.NOTSET):
        super().__init__(level=level)
        self._mgr = manager

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = record.levelname or "INFO"
            # record.name is the dotted logger name (e.g.
            # "backend.agent.tool_decision"); record.module is only the bare
            # filename. Prefer the dotted name so source bucketing is accurate.
            name = getattr(record, "name", "") or ""
            source = _module_to_source(name)
            msg = record.getMessage()
            self._mgr.log(level, source, msg)
        except Exception:  # never let logging crash the caller
            pass


class LogManager:
    """
    Manages application logs:
    - System logs (startup, config changes)
    - Voice logs (wake word, inference, TTS)
    - MCP logs (tool execution, server connections)
    - Export functionality
    """
    
    _instance: Optional['LogManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_entries: int = 10000):
        if LogManager._initialized:
            return
        
        self._logs: deque = deque(maxlen=max_entries)
        self._log_dir = Path(__file__).parent.parent.parent / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        
        # Set up file logging
        self._setup_file_logging()
        
        LogManager._initialized = True

    def attach_to_root(self, level: int = logging.DEBUG) -> bool:
        """Attach a LogManagerHandler to the root logger so every backend log
        record (all modules, including the tool tree) flows into this manager.

        Idempotent: only adds the handler once. Returns True if a handler was
        added, False if one was already present.

        This is the bridge that feeds the Monitor's live log view. It does NOT
        depend on irisvoice.log existing, so it works even when the structured
        logger singleton was first initialized without a file handler.
        """
        for h in logging.getLogger().handlers:
            if isinstance(h, LogManagerHandler):
                return False
        handler = LogManagerHandler(self, level=level)
        logging.getLogger().addHandler(handler)
        # Ensure root actually emits at the handler's level.
        if logging.getLogger().level == logging.NOTSET or logging.getLogger().level > level:
            logging.getLogger().setLevel(min(logging.getLogger().level, level) if logging.getLogger().level != logging.NOTSET else level)
        return True

    def _setup_file_logging(self):
        """Set up file-based logging"""
        log_file = self._log_dir / "iris.log"

        handler = logging.FileHandler(log_file, mode='a')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))

        self._logger = logging.getLogger("IRIS")
        self._logger.addHandler(handler)
        self._logger.setLevel(logging.DEBUG)

        # Raw handle for direct (non-logging) writes from log(). Kept open for
        # the lifetime of the process. Line-buffered so the Monitor sees logs
        # promptly without us calling flush on every record (we do flush anyway).
        self._log_file = open(log_file, "a", encoding="utf-8", buffering=1)
    
    def log(self, level: str, source: str, message: str, details: Dict[str, Any] = None):
        """Add a log entry"""
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            level=level.upper(),
            source=source,
            message=message,
            details=details or {}
        )
        
        self._logs.append(entry)

        # Write directly to the log file — DO NOT route through the logging
        # system. LogManager is fed BY a logging handler (LogManagerHandler on
        # the root logger); if log() called self._logger.* it would propagate
        # back to that handler and recurse infinitely. Write the line ourselves.
        try:
            line = json.dumps({
                "timestamp": entry.timestamp,
                "level": entry.level,
                "source": entry.source,
                "message": entry.message,
            })
            if self._log_file:
                self._log_file.write(line + "\n")
                self._log_file.flush()
        except Exception:
            pass
    
    def debug(self, source: str, message: str, details: Dict[str, Any] = None):
        self.log("DEBUG", source, message, details)
    
    def info(self, source: str, message: str, details: Dict[str, Any] = None):
        self.log("INFO", source, message, details)
    
    def warning(self, source: str, message: str, details: Dict[str, Any] = None):
        self.log("WARNING", source, message, details)
    
    def error(self, source: str, message: str, details: Dict[str, Any] = None):
        self.log("ERROR", source, message, details)
    
    def get_logs(self, source: str = None, level: str = None, 
                 limit: int = 100) -> List[Dict[str, Any]]:
        """Get filtered logs"""
        logs = list(self._logs)
        
        if source:
            logs = [l for l in logs if l.source == source]
        if level:
            level = level.upper()
            logs = [l for l in logs if l.level == level]
        
        # Return most recent first
        logs = logs[-limit:] if limit else logs
        
        return [asdict(l) for l in reversed(logs)]
    
    def get_logs_by_source(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get logs grouped by source"""
        sources = ["system", "voice", "mcp", "agent"]
        return {source: self.get_logs(source=source, limit=50) for source in sources}
    
    def export_logs(self, filepath: str = None, 
                    source: str = None, level: str = None) -> Dict[str, Any]:
        """Export logs to file"""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = self._log_dir / f"iris_logs_{timestamp}.json"
        else:
            filepath = Path(filepath)
        
        logs = self.get_logs(source=source, level=level, limit=None)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(logs, f, indent=2, default=str)
            
            return {
                "success": True,
                "filepath": str(filepath),
                "entries_exported": len(logs)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def clear_logs(self, source: str = None) -> Dict[str, Any]:
        """Clear logs (optionally filtered by source)"""
        if source:
            # Keep only logs not matching source
            new_logs = [l for l in self._logs if l.source != source]
            self._logs.clear()
            self._logs.extend(new_logs)
            return {"success": True, "message": f"Cleared {source} logs"}
        else:
            count = len(self._logs)
            self._logs.clear()
            return {"success": True, "message": f"Cleared all {count} logs"}


def get_log_manager() -> LogManager:
    """Get the singleton LogManager instance"""
    return LogManager()
