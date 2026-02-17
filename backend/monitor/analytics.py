"""
Analytics Manager - Token usage, latency metrics, cost estimation
"""
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque


@dataclass
class UsageRecord:
    """Record of token usage for a single interaction"""
    timestamp: float
    text_tokens: int
    audio_tokens: int
    latency_ms: float
    mode: str  # "conversation" or "tool"


class AnalyticsManager:
    """
    Manages usage analytics:
    - Token usage tracking
    - Latency metrics
    - Cost estimation
    - Session statistics
    """
    
    _instance: Optional['AnalyticsManager'] = None
    _initialized: bool = False
    
    # Cost per 1K tokens (approximate OpenAI pricing)
    COST_PER_1K_TOKENS = {
        "text_input": 0.0015,
        "text_output": 0.002,
        "audio": 0.006  # TTS pricing
    }
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_history: int = 1000):
        if AnalyticsManager._initialized:
            return
        
        self._records: deque = deque(maxlen=max_history)
        self._session_start = time.time()
        
        AnalyticsManager._initialized = True
    
    def record_usage(self, text_tokens: int = 0, audio_tokens: int = 0, 
                     latency_ms: float = 0, mode: str = "conversation") -> None:
        """Record a usage event"""
        record = UsageRecord(
            timestamp=time.time(),
            text_tokens=text_tokens,
            audio_tokens=audio_tokens,
            latency_ms=latency_ms,
            mode=mode
        )
        self._records.append(record)
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics for current session"""
        if not self._records:
            return {
                "total_interactions": 0,
                "total_text_tokens": 0,
                "total_audio_tokens": 0,
                "estimated_cost": 0.0,
                "avg_latency_ms": 0.0,
                "session_duration_minutes": (time.time() - self._session_start) / 60
            }
        
        total_text = sum(r.text_tokens for r in self._records)
        total_audio = sum(r.audio_tokens for r in self._records)
        total_latency = sum(r.latency_ms for r in self._records)
        
        # Calculate estimated cost
        text_cost = (total_text / 1000) * self.COST_PER_1K_TOKENS["text_input"]
        audio_cost = (total_audio / 1000) * self.COST_PER_1K_TOKENS["audio"]
        
        return {
            "total_interactions": len(self._records),
            "total_text_tokens": total_text,
            "total_audio_tokens": total_audio,
            "estimated_cost": round(text_cost + audio_cost, 4),
            "avg_latency_ms": round(total_latency / len(self._records), 2),
            "session_duration_minutes": round((time.time() - self._session_start) / 60, 2)
        }
    
    def get_latency_metrics(self) -> Dict[str, Any]:
        """Get detailed latency metrics"""
        if not self._records:
            return {"count": 0}
        
        latencies = [r.latency_ms for r in self._records]
        
        return {
            "count": len(latencies),
            "min_ms": round(min(latencies), 2),
            "max_ms": round(max(latencies), 2),
            "avg_ms": round(sum(latencies) / len(latencies), 2),
            "p50_ms": round(sorted(latencies)[len(latencies)//2], 2),
            "p95_ms": round(sorted(latencies)[int(len(latencies)*0.95)], 2) if len(latencies) >= 20 else None
        }
    
    def get_recent_records(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent usage records"""
        records = list(self._records)[-limit:]
        return [
            {
                "timestamp": r.timestamp,
                "text_tokens": r.text_tokens,
                "audio_tokens": r.audio_tokens,
                "latency_ms": r.latency_ms,
                "mode": r.mode
            }
            for r in reversed(records)
        ]
    
    def reset_session(self) -> None:
        """Reset session statistics"""
        self._records.clear()
        self._session_start = time.time()


def get_analytics_manager() -> AnalyticsManager:
    """Get the singleton AnalyticsManager instance"""
    return AnalyticsManager()
