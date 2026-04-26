"""
Privacy Audit Logger for IRIS Memory.

Logs all get_task_context_for_remote() calls for compliance auditing.
Uses content hashing to preserve privacy while maintaining audit trail.
Supports log rotation and export for regulatory compliance.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from backend.memory.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """A single privacy audit entry."""
    timestamp: str
    action: str  # "get_task_context_for_remote"
    content_hash: str  # SHA-256 hash of context content
    session_id: Optional[str]  # May be None for remote requests
    task_summary_preview: str  # First 50 chars of task (for debugging)
    origin: str  # "local" or "torus_task"
    node_id: str  # Source node identifier


class PrivacyAuditLogger:
    """
    Audit logger for privacy-sensitive operations.
    
    Logs:
    - All get_task_context_for_remote() calls
    - Content hash (not content itself) for verification
    - Timestamp and origin for compliance tracking
    
    Features:
    - Automatic log rotation by size
    - Configurable retention period
    - JSON export for compliance audits
    """
    
    def __init__(
        self,
        log_dir: str = "data/audit",
        max_size_mb: int = 10,
        retention_days: int = 30
    ):
        """
        Initialize PrivacyAuditLogger.
        
        Args:
            log_dir: Directory for audit logs
            max_size_mb: Maximum size before rotation
            retention_days: Days to retain logs
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.retention_days = retention_days
        
        # Current log file
        self.current_log = self.log_dir / "privacy_audit.current.jsonl"
        
        # Get salt from config for additional hash security
        config = get_config()
        self._salt = config.privacy.content_hash_salt or "iris_default_salt"
        
        logger.info(f"[PrivacyAuditLogger] Initialized (log_dir={log_dir})")
    
    def _get_content_hash(self, content: str) -> str:
        """
        Generate secure hash of content.
        
        Args:
            content: Content to hash
        
        Returns:
            Hex-encoded SHA-256 hash with salt
        """
        salted = f"{self._salt}:{content}"
        return hashlib.sha256(salted.encode()).hexdigest()
    
    def _rotate_if_needed(self) -> None:
        """Rotate log file if it exceeds max size."""
        if not self.current_log.exists():
            return
        
        if self.current_log.stat().st_size >= self.max_size_bytes:
            # Rotate: rename current to timestamped file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            rotated = self.log_dir / f"privacy_audit.{timestamp}.jsonl"
            
            try:
                self.current_log.rename(rotated)
                logger.info(f"[PrivacyAuditLogger] Rotated log to {rotated.name}")
            except Exception as e:
                logger.error(f"[PrivacyAuditLogger] Rotation failed: {e}")
    
    def log_remote_context_access(
        self,
        content: str,
        session_id: Optional[str] = None,
        origin: str = "local",
        node_id: str = "local"
    ) -> str:
        """
        Log a get_task_context_for_remote() call.
        
        Args:
            content: The context content (will be hashed)
            session_id: Session identifier
            origin: Origin of the request
            node_id: Source node identifier
        
        Returns:
            Content hash for reference
        """
        try:
            # Rotate if needed
            self._rotate_if_needed()
            
            # Generate hash
            content_hash = self._get_content_hash(content)
            
            # Create entry
            entry = AuditEntry(
                timestamp=datetime.utcnow().isoformat() + "Z",
                action="get_task_context_for_remote",
                content_hash=content_hash,
                session_id=session_id[:16] + "..." if session_id and len(session_id) > 16 else session_id,
                task_summary_preview=content[:50].replace("\n", " ") if content else "",
                origin=origin,
                node_id=node_id
            )
            
            # Append to log
            with open(self.current_log, 'a') as f:
                f.write(json.dumps(asdict(entry)) + "\n")
            
            return content_hash
            
        except Exception as e:
            # Never let audit logging fail the operation
            logger.error(f"[PrivacyAuditLogger] Failed to log: {e}")
            return ""
    
    def cleanup_old_logs(self) -> int:
        """
        Remove logs older than retention period.
        
        Returns:
            Number of files removed
        """
        if not self.log_dir.exists():
            return 0
        
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        removed = 0
        
        for log_file in self.log_dir.glob("privacy_audit.*.jsonl"):
            try:
                # Extract timestamp from filename
                timestamp_str = log_file.stem.split('.')[1]
                file_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                
                if file_time < cutoff:
                    log_file.unlink()
                    removed += 1
                    
            except (ValueError, IndexError):
                # Skip files with unexpected names
                continue
        
        if removed > 0:
            logger.info(f"[PrivacyAuditLogger] Removed {removed} old log files")
        
        return removed
    
    def export_logs(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        output_path: Optional[str] = None
    ) -> str:
        """
        Export audit logs for compliance review.
        
        Args:
            start_date: Filter entries after this date
            end_date: Filter entries before this date
            output_path: Output file path (default: auto-generated)
        
        Returns:
            Path to exported file
        """
        # Default output path
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.log_dir / f"audit_export_{timestamp}.json"
        else:
            output_path = Path(output_path)
        
        # Collect all entries
        all_entries: List[Dict[str, Any]] = []
        
        # Read current log
        if self.current_log.exists():
            with open(self.current_log, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            if self._date_filter(entry, start_date, end_date):
                                all_entries.append(entry)
                        except json.JSONDecodeError:
                            continue
        
        # Read rotated logs
        for log_file in self.log_dir.glob("privacy_audit.*.jsonl"):
            with open(log_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            if self._date_filter(entry, start_date, end_date):
                                all_entries.append(entry)
                        except json.JSONDecodeError:
                            continue
        
        # Sort by timestamp
        all_entries.sort(key=lambda x: x.get('timestamp', ''))
        
        # Write export
        export_data = {
            "export_timestamp": datetime.utcnow().isoformat() + "Z",
            "retention_days": self.retention_days,
            "entry_count": len(all_entries),
            "entries": all_entries
        }
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"[PrivacyAuditLogger] Exported {len(all_entries)} entries to {output_path}")
        
        return str(output_path)
    
    def _date_filter(
        self,
        entry: Dict[str, Any],
        start_date: Optional[datetime],
        end_date: Optional[datetime]
    ) -> bool:
        """Check if entry falls within date range."""
        try:
            entry_time = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
            
            if start_date and entry_time < start_date:
                return False
            if end_date and entry_time > end_date:
                return False
            
            return True
            
        except (KeyError, ValueError):
            return True  # Include if date parsing fails
    
    def verify_content(self, content: str, content_hash: str) -> bool:
        """
        Verify that content matches a recorded hash.
        
        Args:
            content: Content to verify
            content_hash: Expected hash
        
        Returns:
            True if hash matches
        """
        computed_hash = self._get_content_hash(content)
        return computed_hash == content_hash
    
    def get_stats(self) -> Dict[str, Any]:
        """Get audit logger statistics."""
        log_count = len(list(self.log_dir.glob("privacy_audit.*.jsonl")))
        
        current_size = 0
        if self.current_log.exists():
            current_size = self.current_log.stat().st_size
        
        return {
            "log_dir": str(self.log_dir),
            "retention_days": self.retention_days,
            "max_size_mb": self.max_size_bytes / (1024 * 1024),
            "rotated_logs": log_count,
            "current_log_size_bytes": current_size,
            "current_log_size_mb": round(current_size / (1024 * 1024), 2)
        }


# Global audit logger instance
_audit_logger: Optional[PrivacyAuditLogger] = None


def get_audit_logger() -> PrivacyAuditLogger:
    """Get or create global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        config = get_config()
        _audit_logger = PrivacyAuditLogger(
            log_dir="data/audit",
            max_size_mb=config.privacy.audit_rotation_size_mb,
            retention_days=config.privacy.audit_retention_days
        )
    return _audit_logger
