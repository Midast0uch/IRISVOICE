"""
Marketplace Client

Client for querying the official MCP Registry (registry.modelcontextprotocol.io)
and merging results with the Iris curated list.

_Requirements: 8.1, 8.4
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urljoin

import aiohttp

from .models import IntegrationConfig, MCPServerConfig
from .registry_loader import RegistryLoader

logger = logging.getLogger(__name__)

# Official MCP Registry API endpoints
MCP_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io"
MCP_REGISTRY_API_VERSION = "v0"

# Cache settings
CACHE_TTL_SECONDS = 300  # 5 minutes
CACHE_MAX_SIZE = 100


@dataclass
class CacheEntry:
    """Cache entry with TTL."""
    data: Any
    timestamp: float
    
    def is_expired(self, ttl: float = CACHE_TTL_SECONDS) -> bool:
        return time.time() - self.timestamp > ttl


class MarketplaceCache:
    """Simple in-memory cache for marketplace results."""
    
    def __init__(self, ttl: float = CACHE_TTL_SECONDS, max_size: int = CACHE_MAX_SIZE):
        self.ttl = ttl
        self.max_size = max_size
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.is_expired(self.ttl):
                del self._cache[key]
                return None
            return entry.data
    
    async def set(self, key: str, value: Any) -> None:
        """Cache a value with TTL."""
        async with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
                del self._cache[oldest_key]
            
            self._cache[key] = CacheEntry(data=value, timestamp=time.time())
    
    async def invalidate(self, key_prefix: Optional[str] = None) -> None:
        """Invalidate cache entries."""
        async with self._lock:
            if key_prefix is None:
                self._cache.clear()
            else:
                keys_to_remove = [k for k in self._cache.keys() if k.startswith(key_prefix)]
                for key in keys_to_remove:
                    del self._cache[key]
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "ttl_seconds": int(self.ttl),
        }


@dataclass
class MarketplaceServer:
    """Represents a server from the marketplace."""
    id: str
    name: str
    description: str
    publisher: str
    version: str
    downloads: int = 0
    rating: float = 0.0
    category: str = "other"
    tags: List[str] = field(default_factory=list)
    icon: Optional[str] = None
    source: str = "community"  # 'official', 'community', 'installed'
    transport: str = "stdio"  # 'stdio', 'sse', 'websocket'
    permissions: List[str] = field(default_factory=list)
    
    # Installation details
    package_name: Optional[str] = None
    package_type: Optional[str] = None  # 'npm', 'pypi', 'docker'
    repository_url: Optional[str] = None
    
    # Runtime info
    installed: bool = False
    installed_version: Optional[str] = None


class MarketplaceClient:
    """
    Client for the MCP Registry API.
    
    Queries both the official MCP registry and the Iris curated list,
    merging results and filtering based on user preferences.
    """
    
    def __init__(
        self,
        registry_loader: RegistryLoader,
        base_url: str = MCP_REGISTRY_BASE_URL,
        api_version: str = MCP_REGISTRY_API_VERSION,
        user_mode: bool = True,  # True = only stdio servers
        cache: Optional[MarketplaceCache] = None,
    ):
        self.registry_loader = registry_loader
        self.base_url = base_url
        self.api_version = api_version
        self.user_mode = user_mode
        self.api_url = urljoin(base_url, f"/api/{api_version}/")
        self.cache = cache or MarketplaceCache()
        
    async def search(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MarketplaceServer]:
        """
        Search for servers in the marketplace.
        
        Queries both the official registry and local curated list,
        merging and deduplicating results.
        
        Args:
            query: Search query string
            category: Filter by category
            tags: Filter by tags
            limit: Maximum results to return
            offset: Pagination offset
            
        Returns:
            List of MarketplaceServer objects
        """
        # Build cache key
        cache_key = f"search:{query}:{category}:{','.join(sorted(tags or []))}:{limit}:{offset}"
        
        # Check cache first
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Marketplace cache hit for {cache_key}")
            return cached_result
        
        logger.debug(f"Marketplace cache miss for {cache_key}")
        
        # Start both queries concurrently
        official_task = self._search_official_registry(
            query=query,
            category=category,
            tags=tags,
            limit=limit,
            offset=offset,
        )
        
        curated_task = self._get_curated_servers(
            query=query,
            category=category,
            tags=tags,
        )
        
        official_results, curated_results = await asyncio.gather(
            official_task,
            curated_task,
            return_exceptions=True,
        )
        
        # Handle errors
        if isinstance(official_results, Exception):
            logger.warning(f"Official registry search failed: {official_results}")
            official_results = []
            
        if isinstance(curated_results, Exception):
            logger.warning(f"Curated list search failed: {curated_results}")
            curated_results = []
        
        # Merge and deduplicate (curated takes precedence)
        merged = self._merge_results(curated_results, official_results)
        
        # Apply stdio filter in user mode
        if self.user_mode:
            merged = [s for s in merged if s.transport == "stdio"]
        
        # Apply pagination
        result = merged[offset:offset + limit]
        
        # Cache the result
        await self.cache.set(cache_key, result)
        
        return result
    
    async def get_server_details(self, server_id: str) -> Optional[MarketplaceServer]:
        """
        Get detailed information about a specific server.
        
        Args:
            server_id: The server ID
            
        Returns:
            MarketplaceServer or None if not found
        """
        # Check cache first
        cache_key = f"details:{server_id}"
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Marketplace cache hit for server details: {server_id}")
            return cached_result
        
        # Check curated list first
        curated = await self._get_curated_servers()
        for server in curated:
            if server.id == server_id:
                await self.cache.set(cache_key, server)
                return server
        
        # Query official registry
        try:
            async with aiohttp.ClientSession() as session:
                url = urljoin(self.api_url, f"servers/{server_id}")
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = self._parse_registry_server(data)
                        await self.cache.set(cache_key, result)
                        return result
                    elif response.status == 404:
                        return None
                    else:
                        logger.error(f"Registry error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Failed to fetch server details: {e}")
            return None
    
    async def _search_official_registry(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MarketplaceServer]:
        """Search the official MCP registry."""
        try:
            params = {
                "limit": str(limit),
                "offset": str(offset),
            }
            
            if query:
                params["q"] = query
            if category:
                params["category"] = category
            if tags:
                params["tags"] = ",".join(tags)
            
            async with aiohttp.ClientSession() as session:
                url = urljoin(self.api_url, "servers/search")
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        servers = data.get("servers", [])
                        return [self._parse_registry_server(s) for s in servers]
                    else:
                        logger.warning(f"Registry search failed: {response.status}")
                        return []
                        
        except aiohttp.ClientError as e:
            logger.warning(f"Registry unreachable: {e}")
            return []
        except Exception as e:
            logger.error(f"Registry search error: {e}")
            return []
    
    async def _get_curated_servers(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[MarketplaceServer]:
        """Get servers from the Iris curated list."""
        try:
            # Load registry
            registry = self.registry_loader.load_registries()
            
            servers = []
            for integration_id, config in registry.items():
                # Skip built-in integrations (they're not from marketplace)
                if integration_id in ["gmail", "outlook", "telegram", "discord", "imap_smtp"]:
                    continue
                
                # Apply filters
                if category and config.category != category:
                    continue
                    
                if query:
                    query_lower = query.lower()
                    searchable = f"{config.name} {config.description or ''}".lower()
                    if query_lower not in searchable:
                        continue
                
                if tags:
                    # Check if any requested tag matches
                    server_tags = getattr(config, 'tags', [])
                    if not any(tag in server_tags for tag in tags):
                        continue
                
                # Convert to MarketplaceServer
                server = self._integration_to_marketplace(config)
                server.source = "official"  # Curated = official
                servers.append(server)
            
            return servers
            
        except Exception as e:
            logger.error(f"Failed to load curated list: {e}")
            return []
    
    def _parse_registry_server(self, data: Dict[str, Any]) -> MarketplaceServer:
        """Parse a server from the registry API response."""
        return MarketplaceServer(
            id=data.get("id", ""),
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            publisher=data.get("publisher", {}).get("name", "Unknown"),
            version=data.get("version", "0.0.0"),
            downloads=data.get("downloads", 0),
            rating=data.get("rating", 0.0),
            category=data.get("category", "other"),
            tags=data.get("tags", []),
            icon=data.get("icon"),
            source="community",
            transport=data.get("transport", "stdio"),
            permissions=data.get("permissions", []),
            package_name=data.get("package", {}).get("name"),
            package_type=data.get("package", {}).get("type"),
            repository_url=data.get("repository"),
        )
    
    def _integration_to_marketplace(self, config: IntegrationConfig) -> MarketplaceServer:
        """Convert an IntegrationConfig to MarketplaceServer."""
        return MarketplaceServer(
            id=config.id,
            name=config.name,
            description=config.permissions_summary or "",
            publisher="Iris Curated",
            version="1.0.0",
            category=config.category,
            tags=getattr(config, 'tags', []),
            source="official",
            transport="stdio",
            permissions=config.mcp_server.tools if config.mcp_server else [],
        )
    
    def _merge_results(
        self,
        curated: List[MarketplaceServer],
        official: List[MarketplaceServer],
    ) -> List[MarketplaceServer]:
        """
        Merge curated and official results, removing duplicates.
        
        Curated servers take precedence over registry results.
        """
        # Build lookup from curated
        curated_ids = {s.id: s for s in curated}
        
        # Add non-duplicate official servers
        merged = list(curated)  # Start with curated
        
        for server in official:
            if server.id not in curated_ids:
                merged.append(server)
        
        # Sort by rating and downloads
        merged.sort(key=lambda s: (s.rating, s.downloads), reverse=True)
        
        return merged
    
    def check_for_updates(
        self,
        installed_servers: List[IntegrationConfig],
    ) -> List[Dict[str, Any]]:
        """
        Check installed servers for available updates.
        
        Args:
            installed_servers: List of currently installed server configs
            
        Returns:
            List of servers with available updates
        """
        updates = []
        
        for installed in installed_servers:
            # This would check the registry for newer versions
            # For now, placeholder implementation
            pass
        
        return updates


# Singleton instance
_marketplace_client: Optional[MarketplaceClient] = None


def get_marketplace_client(
    registry_loader: Optional[RegistryLoader] = None,
    user_mode: bool = True,
) -> MarketplaceClient:
    """Get or create the singleton MarketplaceClient instance."""
    global _marketplace_client
    
    if _marketplace_client is None:
        if registry_loader is None:
            from .registry_loader import get_registry_loader
            registry_loader = get_registry_loader()
        
        _marketplace_client = MarketplaceClient(
            registry_loader=registry_loader,
            user_mode=user_mode,
        )
    
    return _marketplace_client
