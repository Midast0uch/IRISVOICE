"""
Semantic snapshot caching for performance optimization.
"""
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import hashlib
from pathlib import Path
import aiofiles

@dataclass
class CachedSnapshot:
    """Represents a cached semantic snapshot."""
    cache_key: str
    snapshot_data: Dict[str, Any]
    metadata: Dict[str, Any]
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    size_bytes: int = 0

@dataclass
class CacheStats:
    """Statistics about the cache."""
    total_entries: int
    total_size_bytes: int
    hit_count: int
    miss_count: int
    eviction_count: int
    oldest_entry: Optional[datetime]
    newest_entry: Optional[datetime]

class SnapshotCache:
    """Manages caching of semantic snapshots with LRU eviction."""
    
    def __init__(self, cache_dir: Path = None, max_size_mb: int = 100, max_entries: int = 1000):
        self.cache_dir = cache_dir or Path("cache/semantic_snapshots")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_entries = max_entries
        
        self.cache: Dict[str, CachedSnapshot] = {}
        self.access_order: List[str] = []  # LRU order
        
        # Statistics
        self.stats = {
            "hit_count": 0,
            "miss_count": 0,
            "eviction_count": 0,
            "total_hits": 0,
            "total_misses": 0
        }
        
        # Background cleanup task
        self.cleanup_interval = timedelta(hours=1)
        self.last_cleanup = datetime.now()
        self.cleanup_task = None
    
    async def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get a cached snapshot by key."""
        # Check memory cache first
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            cached.last_accessed = datetime.now()
            cached.access_count += 1
            self.stats["hit_count"] += 1
            self.stats["total_hits"] += 1
            
            # Update access order (move to front)
            self._update_access_order(cache_key)
            
            return cached.snapshot_data
        
        # Check disk cache
        disk_cache = await self._load_from_disk(cache_key)
        if disk_cache:
            self.stats["hit_count"] += 1
            self.stats["total_hits"] += 1
            
            # Add to memory cache
            self.cache[cache_key] = disk_cache
            self._update_access_order(cache_key)
            
            return disk_cache.snapshot_data
        
        self.stats["miss_count"] += 1
        self.stats["total_misses"] += 1
        return None
    
    async def set(self, cache_key: str, snapshot_data: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Set a cached snapshot."""
        metadata = metadata or {}
        
        # Calculate size
        size_bytes = len(json.dumps(snapshot_data).encode('utf-8'))
        
        cached = CachedSnapshot(
            cache_key=cache_key,
            snapshot_data=snapshot_data,
            metadata=metadata or {},
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=1,
            size_bytes=size_bytes
        )
        
        # Add to memory cache
        self.cache[cache_key] = cached
        self._update_access_order(cache_key)
        
        # Save to disk
        await self._save_to_disk(cached)
        
        # Check if we need to evict
        await self._check_eviction_needed()
        
        # Start background cleanup if needed
        await self._start_background_cleanup()
    
    async def _load_from_disk(self, cache_key: str) -> Optional[CachedSnapshot]:
        """Load a cached snapshot from disk."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if not cache_file.exists():
            return None
        
        try:
            async with aiofiles.open(cache_file, 'r') as f:
                data = json.loads(await f.read())
                
                cached = CachedSnapshot(
                    cache_key=cache_key,
                    snapshot_data=data["snapshot_data"],
                    metadata=data["metadata"],
                    created_at=datetime.fromisoformat(data["created_at"]),
                    last_accessed=datetime.fromisoformat(data["last_accessed"]),
                    access_count=data["access_count"],
                    size_bytes=data["size_bytes"]
                )
                
                return cached
        except Exception as e:
            print(f"Error loading cache from disk: {e}")
            return None
    
    async def _save_to_disk(self, cached: CachedSnapshot):
        """Save a cached snapshot to disk."""
        cache_file = self.cache_dir / f"{cached.cache_key}.json"
        
        data = {
            "cache_key": cached.cache_key,
            "snapshot_data": cached.snapshot_data,
            "metadata": cached.metadata,
            "created_at": cached.created_at.isoformat(),
            "last_accessed": cached.last_accessed.isoformat(),
            "access_count": cached.access_count,
            "size_bytes": cached.size_bytes
        }
        
        try:
            async with aiofiles.open(cache_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as e:
            print(f"Error saving cache to disk: {e}")
    
    def _update_access_order(self, cache_key: str):
        """Update the LRU access order."""
        if cache_key in self.access_order:
            self.access_order.remove(cache_key)
        self.access_order.append(cache_key)
    
    async def _check_eviction_needed(self):
        """Check if we need to evict entries."""
        current_size = sum(cached.size_bytes for cached in self.cache.values())
        current_entries = len(self.cache)
        
        # Evict if size limit exceeded
        if current_size > self.max_size_bytes:
            await self._evict_by_size(current_size - self.max_size_bytes)
        
        # Evict if entry limit exceeded
        if current_entries > self.max_entries:
            await self._evict_by_count(current_entries - self.max_entries)
    
    async def _evict_by_size(self, target_reduction: int):
        """Evict entries to reduce size."""
        evicted_size = 0
        
        # Evict from LRU order
        for cache_key in list(self.access_order):
            if evicted_size >= target_reduction:
                break
            
            cached = self.cache[cache_key]
            evicted_size += cached.size_bytes
            
            await self._evict_entry(cache_key)
    
    async def _evict_by_count(self, target_reduction: int):
        """Evict entries to reduce count."""
        evicted_count = 0
        
        # Evict from LRU order
        for cache_key in list(self.access_order):
            if evicted_count >= target_reduction:
                break
            
            await self._evict_entry(cache_key)
            evicted_count += 1
    
    async def _evict_entry(self, cache_key: str):
        """Evict a single entry."""
        if cache_key in self.cache:
            # Remove from memory
            del self.cache[cache_key]
            
            # Remove from access order
            if cache_key in self.access_order:
                self.access_order.remove(cache_key)
            
            # Remove from disk
            cache_file = self.cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                try:
                    cache_file.unlink()
                except Exception as e:
                    print(f"Error removing cache file: {e}")
            
            self.stats["eviction_count"] += 1
    
    async def _start_background_cleanup(self):
        """Start background cleanup task."""
        if self.cleanup_task is None or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self._background_cleanup())
    
    async def _background_cleanup(self):
        """Background cleanup of old cache entries."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval.total_seconds())
                
                now = datetime.now()
                if (now - self.last_cleanup) < self.cleanup_interval:
                    continue
                
                await self.cleanup_old_entries()
                self.last_cleanup = now
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in background cleanup: {e}")
    
    async def cleanup_old_entries(self, max_age: timedelta = None):
        """Clean up old cache entries."""
        max_age = max_age or timedelta(days=7)
        now = datetime.now()
        
        keys_to_remove = []
        for cache_key, cached in self.cache.items():
            if (now - cached.last_accessed) > max_age:
                keys_to_remove.append(cache_key)
        
        for cache_key in keys_to_remove:
            await self._evict_entry(cache_key)
        
        return len(keys_to_remove)
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        if not self.cache:
            return CacheStats(0, 0, 0, 0, 0, None, None)
        
        total_size = sum(cached.size_bytes for cached in self.cache.values())
        oldest_entry = min(cached.created_at for cached in self.cache.values())
        newest_entry = max(cached.created_at for cached in self.cache.values())
        
        return CacheStats(
            total_entries=len(self.cache),
            total_size_bytes=total_size,
            hit_count=self.stats["hit_count"],
            miss_count=self.stats["miss_count"],
            eviction_count=self.stats["eviction_count"],
            oldest_entry=oldest_entry,
            newest_entry=newest_entry
        )
    
    async def clear(self):
        """Clear all cache entries."""
        # Clear memory cache
        self.cache.clear()
        self.access_order.clear()
        
        # Clear disk cache
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
            except Exception as e:
                print(f"Error removing cache file: {e}")
        
        # Reset stats
        self.stats = {
            "hit_count": 0,
            "miss_count": 0,
            "eviction_count": 0,
            "total_hits": 0,
            "total_misses": 0
        }
    
    def get_cache_key(self, screenshot_data: bytes, metadata: Dict[str, Any] = None) -> str:
        """Generate a cache key from screenshot data and metadata."""
        # Create hash from screenshot data
        screenshot_hash = hashlib.md5(screenshot_data).hexdigest()
        
        # Add metadata to hash if provided
        if metadata:
            metadata_str = json.dumps(metadata, sort_keys=True)
            metadata_hash = hashlib.md5(metadata_str.encode()).hexdigest()
            return f"{screenshot_hash}_{metadata_hash}"
        
        return screenshot_hash