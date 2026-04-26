"""
Working Memory (ContextManager) for IRIS.

Zone-based in-process context window management.
Handles what goes into each model prompt with automatic compression.
"""

import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Zone-based in-process context window manager.
    
    Manages what goes into each model prompt across 5 zones:
    1. semantic_header - Distilled user model (never compressed)
    2. episodic_injection - Similar past episodes (never compressed)
    3. task_anchor - Current task description (never compressed)
    4. active_tool_state - Live tool output (never compressed)
    5. working_history - Rolling conversation history (compressed at 80%)
    
    Zones are injected in ZONES_ORDER for optimal model attention.
    """
    
    ZONES_ORDER = [
        "semantic_header",
        "episodic_injection",
        "task_anchor",
        "active_tool_state",
        "external_research",   # Domain 14: crawler results (lower weight, compressible)
        "working_history"
    ]

    # Budget weight per zone (relative to total budget).
    # external_research uses 0.5x weight — it's supplementary context, not primary.
    ZONE_WEIGHTS = {
        "semantic_header":   1.0,
        "episodic_injection": 1.0,
        "task_anchor":        1.0,
        "active_tool_state":  1.0,
        "external_research":  0.5,
        "working_history":    1.0,
    }

    # Zones that should never be compressed
    ANCHOR_ZONES = {"semantic_header", "task_anchor", "active_tool_state"}
    
    def __init__(self, adapter: Any, compression_threshold: float = 0.80):
        """
        Initialize ContextManager.
        
        Args:
            adapter: Model adapter with count_tokens() and infer() methods
            compression_threshold: Usage ratio that triggers compression (default 0.80)
        """
        self.adapter = adapter
        self.threshold = compression_threshold
        self._sessions: Dict[str, Dict[str, str]] = {}
        
        logger.info(f"[ContextManager] Initialized (threshold={compression_threshold})")
    
    def assemble_for_task(
        self,
        session_id: str,
        task: str,
        semantic_header: str,
        episodic_context: str
    ) -> str:
        """
        Initialize session zones for a new task.
        
        Args:
            session_id: Session identifier
            task: Task description
            semantic_header: User profile from SemanticStore
            episodic_context: Similar episodes from EpisodicStore
        
        Returns:
            Rendered context string
        """
        self._sessions[session_id] = {
            "semantic_header": semantic_header,
            "episodic_injection": episodic_context,
            "task_anchor": f"CURRENT TASK: {task}",
            "active_tool_state": "",
            "working_history": ""
        }
        
        logger.debug(f"[ContextManager] Assembled zones for session {session_id[:8]}")
        return self.render(session_id)
    
    def append(
        self,
        session_id: str,
        content: str,
        zone: str = "working_history"
    ) -> None:
        """
        Append content to a zone.
        
        Triggers compression if working_history exceeds threshold.
        
        Args:
            session_id: Session identifier
            content: Content to append
            zone: Target zone (default: working_history)
        """
        if zone not in self.ZONES_ORDER:
            logger.warning(f"[ContextManager] Unknown zone '{zone}', using working_history")
            zone = "working_history"
        
        # Get or create session zones
        zones = self._sessions.setdefault(session_id, {
            "semantic_header": "",
            "episodic_injection": "",
            "task_anchor": "",
            "active_tool_state": "",
            "working_history": ""
        })
        
        # Append content
        current = zones.get(zone, "")
        if current:
            zones[zone] = current + "\n" + content
        else:
            zones[zone] = content
        
        # Check for compression (only for working_history)
        if zone not in self.ANCHOR_ZONES:
            usage = self._usage_pct(session_id)
            if usage > self.threshold:
                logger.debug(f"[ContextManager] Compression triggered ({usage:.1%})")
                self._compress(session_id)
    
    def render(self, session_id: str) -> str:
        """
        Render all zones in order.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Formatted context string
        """
        zones = self._sessions.get(session_id, {})
        
        parts = []
        for zone_name in self.ZONES_ORDER:
            content = zones.get(zone_name, "").strip()
            if content:
                parts.append(content)
        
        return "\n\n".join(parts)
    
    def clear_session(self, session_id: str) -> None:
        """
        Clear working memory for a session after completion.
        
        Args:
            session_id: Session identifier
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.debug(f"[ContextManager] Cleared session {session_id[:8]}")
    
    def _compress(self, session_id: str) -> None:
        """
        Compress working_history using the compression model role.
        
        Keeps the newest 60% of history lines verbatim.
        Summarizes the oldest 40% into a compact summary block.
        
        Args:
            session_id: Session identifier
        """
        zones = self._sessions.get(session_id)
        if not zones:
            return
        
        history = zones.get("working_history", "").strip()
        if not history:
            return
        
        # Split into lines
        lines = [l for l in history.split("\n") if l.strip()]
        
        # Not enough history to meaningfully compress
        if len(lines) < 10:
            return
        
        # Split at 40% point
        split_idx = int(len(lines) * 0.4)
        old_lines = lines[:split_idx]
        keep_lines = lines[split_idx:]
        
        try:
            # Use adapter to summarize old content if available
            summary_prompt = (
                "Summarize the following conversation history concisely, "
                "preserving all key facts and decisions:\n\n" +
                "\n".join(old_lines)
            )
            
            summary = None
            
            # Attempt to use adapter for intelligent summarization
            if hasattr(self.adapter, 'infer'):
                try:
                    # Try to use COMPRESSION role if available
                    try:
                        from src.model.adapter_base import ModelRole
                        result = self.adapter.infer(
                            summary_prompt,
                            role=ModelRole.COMPRESSION,
                            max_tokens=300
                        )
                        summary = result.raw_text if hasattr(result, 'raw_text') else str(result)
                    except (ImportError, AttributeError):
                        # ModelRole not available, try without role
                        result = self.adapter.infer(summary_prompt, max_tokens=300)
                        summary = result.raw_text if hasattr(result, 'raw_text') else str(result)
                except Exception as e:
                    logger.debug(f"[ContextManager] Adapter inference failed: {e}, using fallback")
            
            # Fallback to simple truncation if no summary generated
            if not summary:
                if old_lines:
                    first_line = old_lines[0][:100] if old_lines[0] else ""
                    summary = f"{first_line}... [{len(old_lines)} earlier messages]"
                else:
                    summary = f"[{len(old_lines)} earlier messages]"
            
            # Update working_history with summary + kept lines
            zones["working_history"] = f"[HISTORY SUMMARY: {summary}]\n" + "\n".join(keep_lines)
            
            logger.debug(f"[ContextManager] Compressed {len(lines)} lines -> {len(keep_lines)} + summary")
            
        except Exception as e:
            # Never let compression fail the task
            logger.warning(f"[ContextManager] Compression failed: {e}")
    
    def _usage_pct(self, session_id: str) -> float:
        """
        Calculate current context usage percentage.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Usage ratio (0.0-1.0)
        """
        try:
            rendered = self.render(session_id)
            
            # Get token count
            if hasattr(self.adapter, 'count_tokens'):
                token_count = self.adapter.count_tokens(rendered)
            else:
                # Rough estimate: ~4 chars per token
                token_count = len(rendered) // 4
            
            # Get context size
            if hasattr(self.adapter, 'get_context_size'):
                try:
                    from src.model.adapter_base import ModelRole
                    ctx_size = self.adapter.get_context_size(ModelRole.EXECUTION)
                except ImportError:
                    ctx_size = 8192  # Default fallback
            else:
                ctx_size = 8192  # Default context size
            
            if ctx_size == 0:
                return 0.0
            
            return token_count / ctx_size
            
        except Exception as e:
            logger.warning(f"[ContextManager] Usage calculation failed: {e}")
            return 0.0
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """
        Get statistics for a session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Dictionary with session statistics
        """
        zones = self._sessions.get(session_id, {})
        
        zone_sizes = {}
        for zone in self.ZONES_ORDER:
            content = zones.get(zone, "")
            zone_sizes[zone] = len(content)
        
        return {
            "session_id": session_id,
            "zones": zone_sizes,
            "total_size": sum(zone_sizes.values()),
            "usage_pct": self._usage_pct(session_id)
        }
