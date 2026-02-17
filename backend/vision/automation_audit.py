import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import aiofiles

logger = logging.getLogger(__name__)

@dataclass
class AuditEvent:
    """Represents a single audit event for automation."""
    event_id: str
    session_id: str
    user_id: str
    event_type: str  # e.g., action_executed, permission_requested, error
    timestamp: datetime
    details: Dict[str, Any]
    severity: str  # info, warning, error, critical

class AutomationAuditLogger:
    """Logs automation events for security and compliance auditing."""
    
    def __init__(self, log_dir: Path, max_log_size_mb: int = 10, max_log_files: int = 5):
        self.log_dir = log_dir
        self.max_log_size_mb = max_log_size_mb
        self.max_log_files = max_log_files
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.current_log_file = self.log_dir / "automation_audit_1.log"
        self.log_queue = None
        self.worker_task = None
        
    async def log_event(self, session_id: str, user_id: str, event_type: str,
                      details: Dict[str, Any], severity: str = "info"):
        """Log an automation event."""
        # Initialize async components on first use
        if self.log_queue is None:
            self.log_queue = asyncio.Queue()
        if self.worker_task is None:
            self.worker_task = asyncio.create_task(self._log_worker())
        
        event_id = f"evt_{session_id}_{int(datetime.now().timestamp())}"
        timestamp = datetime.now()
        
        event = AuditEvent(
            event_id=event_id,
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            timestamp=timestamp,
            details=details,
            severity=severity
        )
        
        await self.log_queue.put(event)
    
    async def _log_worker(self):
        """Worker to process and write log events from the queue."""
        while True:
            try:
                event = await self.log_queue.get()
                await self._write_log_entry(event)
                self.log_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in log worker: {e}")
    
    async def _write_log_entry(self, event: AuditEvent):
        """Write a log entry to the current log file."""
        try:
            log_entry = {
                "event_id": event.event_id,
                "session_id": event.session_id,
                "user_id": event.user_id,
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "severity": event.severity,
                "details": event.details
            }
            
            async with aiofiles.open(self.current_log_file, 'a') as f:
                await f.write(json.dumps(log_entry) + "\n")
            
            # Check for log rotation
            await self._rotate_logs_if_needed()
            
        except Exception as e:
            logger.error(f"Error writing log entry: {e}")
    
    async def _rotate_logs_if_needed(self):
        """Rotate log files if the current one exceeds size limits."""
        try:
            log_size_mb = self.current_log_file.stat().st_size / (1024 * 1024)
            
            if log_size_mb >= self.max_log_size_mb:
                # Rotate log files
                for i in range(self.max_log_files - 1, 0, -1):
                    old_log = self.log_dir / f"automation_audit_{i}.log"
                    new_log = self.log_dir / f"automation_audit_{i+1}.log"
                    if old_log.exists():
                        old_log.rename(new_log)
                
                # Rename current log file
                self.current_log_file.rename(self.log_dir / "automation_audit_2.log")
                
                # Create new log file
                self.current_log_file = self.log_dir / "automation_audit_1.log"
                
                logger.info("Rotated automation audit logs")
                
        except FileNotFoundError:
            # Log file might not exist yet, ignore
            pass
        except Exception as e:
            logger.error(f"Error rotating logs: {e}")
    
    async def query_logs(self, session_id: Optional[str] = None,
                       event_type: Optional[str] = None,
                       severity: Optional[str] = None,
                       start_time: Optional[datetime] = None,
                       end_time: Optional[datetime] = None,
                       limit: int = 100) -> List[Dict[str, Any]]:
        """Query audit logs with filtering and pagination."""
        results = []
        
        try:
            log_files = sorted(self.log_dir.glob("automation_audit_*.log"))
            
            for log_file in log_files:
                async with aiofiles.open(log_file, 'r') as f:
                    async for line in f:
                        try:
                            log_entry = json.loads(line)
                            
                            # Apply filters
                            if session_id and log_entry.get("session_id") != session_id:
                                continue
                            if event_type and log_entry.get("event_type") != event_type:
                                continue
                            if severity and log_entry.get("severity") != severity:
                                continue
                            
                            timestamp = datetime.fromisoformat(log_entry["timestamp"])
                            if start_time and timestamp < start_time:
                                continue
                            if end_time and timestamp > end_time:
                                continue
                            
                            results.append(log_entry)
                            
                            # Check limit
                            if len(results) >= limit:
                                return results
                                
                        except json.JSONDecodeError:
                            continue
            
            return results
            
        except Exception as e:
            logger.error(f"Error querying logs: {e}")
            return []
    
    async def stop_worker(self):
        """Stop the log worker gracefully."""
        if self.worker_task is not None:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Automation audit log worker stopped")

