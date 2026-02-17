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
        
        # Also log to file
        log_method = getattr(self._logger, level.lower(), self._logger.info)
        log_method(f"[{source}] {message}")
    
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
