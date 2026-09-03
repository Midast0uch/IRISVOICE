"""
Agent Response Time Optimizer
Implements response streaming and caching to ensure <5s p95 response time for simple queries.
"""
import asyncio
import logging
import time
from typing import Dict, Optional, AsyncIterator, Callable, Awaitable
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class ResponseMetrics:
    """Track response time metrics."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    def record(self, response_time_s: float):
        """Record a response time sample."""
        self.samples.append(response_time_s)
    
    def get_p95(self) -> float:
        """Get 95th percentile response time."""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[idx]
    
    def get_mean(self) -> float:
        """Get mean response time."""
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)
    
    def get_max(self) -> float:
        """Get maximum response time."""
        if not self.samples:
            return 0.0
        return max(self.samples)


@dataclass
class CachedResponse:
    """Cached agent response."""
    query: str
    response: str
    timestamp: datetime
    hit_count: int = 0
    
    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if cache entry is expired."""
        age = (datetime.now() - self.timestamp).total_seconds()
        return age > ttl_seconds


class AgentOptimizer:
    """
    Optimizes agent response time with streaming and caching.
    
    Features:
    - Response streaming for long responses
    - Simple query caching
    - Response time monitoring
    - Timeout handling
    """
    
    # Configuration
    TARGET_RESPONSE_TIME_S = 5.0  # Target p95 response time for simple queries
    CACHE_TTL_SECONDS = 300  # 5 minutes cache TTL
    MAX_CACHE_SIZE = 100  # Maximum cached responses
    STREAM_CHUNK_SIZE = 50  # Characters per stream chunk
    STREAM_DELAY_MS = 10  # Delay between chunks (ms)
    
    def __init__(self):
        self.response_metrics = ResponseMetrics()
        self.response_cache: Dict[str, CachedResponse] = {}
        self._cache_hits = 0
        self._cache_misses = 0
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query for cache lookup."""
        return query.lower().strip()
    
    def _is_simple_query(self, query: str) -> bool:
        """
        Determine if a query is simple enough to cache.
        
        Simple queries:
        - Short queries (<50 characters)
        - Common questions (what, when, where, who, how)
        - No complex context required
        """
        normalized = self._normalize_query(query)
        
        # Check length
        if len(normalized) > 50:
            return False
        
        # Check for common question patterns
        simple_patterns = ["what is", "who is", "when is", "where is", "how do", "what are"]
        return any(pattern in normalized for pattern in simple_patterns)
    
    def get_cached_response(self, query: str) -> Optional[str]:
        """Get cached response if available and not expired."""
        normalized = self._normalize_query(query)
        
        if normalized in self.response_cache:
            cached = self.response_cache[normalized]
            
            # Check if expired
            if cached.is_expired(self.CACHE_TTL_SECONDS):
                del self.response_cache[normalized]
                self._cache_misses += 1
                return None
            
            # Update hit count
            cached.hit_count += 1
            self._cache_hits += 1
            logger.debug(f"Cache hit for query: {query[:50]}...")
            return cached.response
        
        self._cache_misses += 1
        return None
    
    def cache_response(self, query: str, response: str):
        """Cache a response for future use."""
        # Only cache simple queries
        if not self._is_simple_query(query):
            return
        
        normalized = self._normalize_query(query)
        
        # Evict oldest entry if cache is full
        if len(self.response_cache) >= self.MAX_CACHE_SIZE:
            # Find least recently used entry
            oldest_key = min(
                self.response_cache.keys(),
                key=lambda k: self.response_cache[k].timestamp
            )
            del self.response_cache[oldest_key]
        
        # Add to cache
        self.response_cache[normalized] = CachedResponse(
            query=query,
            response=response,
            timestamp=datetime.now()
        )
        logger.debug(f"Cached response for query: {query[:50]}...")
    
    async def stream_response(
        self,
        response: str,
        callback: Callable[[str], Awaitable[None]]
    ):
        """
        Stream a long response in chunks.
        
        Args:
            response: Full response text
            callback: Async function to call with each chunk
        """
        # Split response into chunks
        chunks = []
        for i in range(0, len(response), self.STREAM_CHUNK_SIZE):
            chunks.append(response[i:i + self.STREAM_CHUNK_SIZE])
        
        # Stream chunks with delay
        for chunk in chunks:
            await callback(chunk)
            await asyncio.sleep(self.STREAM_DELAY_MS / 1000)
    
    async def process_query(
        self,
        query: str,
        agent_callback: Callable[[str], Awaitable[str]],
        stream_callback: Optional[Callable[[str], Awaitable[None]]] = None
    ) -> str:
        """
        Process a query with caching and streaming.
        
        Args:
            query: User query
            agent_callback: Async function to call agent (returns full response)
            stream_callback: Optional async function for streaming chunks
        
        Returns:
            Full response text
        """
        start_time = time.time()
        
        # Check cache first
        cached = self.get_cached_response(query)
        if cached:
            response_time = time.time() - start_time
            self.response_metrics.record(response_time)
            
            # Stream cached response if callback provided
            if stream_callback:
                await self.stream_response(cached, stream_callback)
            
            return cached
        
        # Call agent
        try:
            response = await agent_callback(query)
            response_time = time.time() - start_time
            self.response_metrics.record(response_time)
            
            # Cache if simple query
            self.cache_response(query, response)
            
            # Stream if long response and callback provided
            if stream_callback and len(response) > self.STREAM_CHUNK_SIZE:
                await self.stream_response(response, stream_callback)
            
            return response
        
        except asyncio.TimeoutError:
            logger.error(f"Query timed out: {query[:50]}...")
            raise
        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            raise
    
    def get_metrics(self) -> dict:
        """Get current performance metrics."""
        total_requests = self._cache_hits + self._cache_misses
        cache_hit_rate = (
            self._cache_hits / total_requests if total_requests > 0 else 0.0
        )
        
        return {
            "p95_response_time_s": self.response_metrics.get_p95(),
            "mean_response_time_s": self.response_metrics.get_mean(),
            "max_response_time_s": self.response_metrics.get_max(),
            "cache_size": len(self.response_cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": cache_hit_rate,
            "total_samples": len(self.response_metrics.samples),
            "target_response_time_s": self.TARGET_RESPONSE_TIME_S,
        }
    
    def is_meeting_target(self) -> bool:
        """Check if we're meeting the response time target."""
        p95 = self.response_metrics.get_p95()
        return p95 <= self.TARGET_RESPONSE_TIME_S if p95 > 0 else True
    
    def clear_cache(self):
        """Clear the response cache."""
        self.response_cache.clear()
        logger.info("Response cache cleared")
    
    def evict_expired(self):
        """Evict expired cache entries."""
        expired_keys = [
            key for key, cached in self.response_cache.items()
            if cached.is_expired(self.CACHE_TTL_SECONDS)
        ]
        for key in expired_keys:
            del self.response_cache[key]
        
        if expired_keys:
            logger.debug(f"Evicted {len(expired_keys)} expired cache entries")


# Global instance
_optimizer: Optional[AgentOptimizer] = None


def get_agent_optimizer() -> AgentOptimizer:
    """Get or create the singleton AgentOptimizer."""
    global _optimizer
    if _optimizer is None:
        _optimizer = AgentOptimizer()
    return _optimizer
