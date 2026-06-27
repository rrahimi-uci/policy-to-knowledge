"""
Redis-based caching layer for Explorer.

Provides caching for expensive graph queries and semantic search results
to improve performance and reduce load on JanusGraph and OpenSearch.
"""

import json
import hashlib
from typing import Optional, Any, Callable
from functools import wraps

import redis

from conf.config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    CACHE_TTL,
    REDIS_CONNECT_TIMEOUT,
    REDIS_SOCKET_TIMEOUT,
    REDIS_HEALTH_CHECK_INTERVAL,
)
from src.log import log as _log


class CacheManager:
    """
    Redis-based cache manager with connection pooling.
    
    Features:
    - Automatic key generation from function arguments
    - Configurable TTL per cache entry
    - JSON serialization for complex objects
    - Graceful degradation if Redis is unavailable
    """
    
    def __init__(self):
        self._redis_client: Optional[redis.Redis] = None
        self._available = False
        self._init_redis()
    
    def _init_redis(self):
        """Initialize Redis connection with error handling."""
        try:
            self._redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
                socket_timeout=REDIS_SOCKET_TIMEOUT,
                retry_on_timeout=True,
                health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
            )
            # Test connection
            self._redis_client.ping()
            self._available = True
            _log("INFO", f"Redis cache initialized at {REDIS_HOST}:{REDIS_PORT}")
        except (redis.ConnectionError, redis.TimeoutError) as e:
            _log("WARN", f"Redis unavailable: {e}. Caching disabled.")
            self._available = False
        except Exception as e:
            _log("ERROR", f"Unexpected error initializing Redis: {e}")
            self._available = False
    
    def is_available(self) -> bool:
        """Check if Redis is available."""
        return self._available
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """
        Generate a cache key from function arguments.
        
        Args:
            prefix: Key prefix (usually function name)
            *args: Positional arguments
            **kwargs: Keyword arguments
        
        Returns:
            Cache key string
        """
        # Sanitise args AND kwargs so non-serialisable objects (e.g. `self` from
        # bound methods) don't break json.dumps – fall back to repr() for those.
        def _safe(value):
            try:
                json.dumps(value)
                return value
            except (TypeError, ValueError):
                return repr(value)

        safe_args = [_safe(a) for a in args]
        safe_kwargs = {k: _safe(v) for k, v in kwargs.items()}

        key_data = json.dumps({
            "args": safe_args,
            "kwargs": sorted(safe_kwargs.items())
        }, sort_keys=True)
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"p2k:{prefix}:{key_hash}"
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None if not found or Redis unavailable
        """
        if not self._available:
            return None
        
        try:
            value = self._redis_client.get(key)
            if value:
                _log("DEBUG", f"Cache hit: {key}")
                return json.loads(value)
            _log("DEBUG", f"Cache miss: {key}")
            return None
        except (redis.ConnectionError, redis.TimeoutError):
            _log("WARN", "Redis connection error during get")
            self._available = False
            return None
        except json.JSONDecodeError as e:
            _log("ERROR", f"Error decoding cached value: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = CACHE_TTL) -> bool:
        """
        Set value in cache with TTL.
        
        Args:
            key: Cache key
            value: Value to cache (must be JSON serializable)
            ttl: Time to live in seconds
        
        Returns:
            True if successful, False otherwise
        """
        if not self._available:
            return False
        
        try:
            serialized = json.dumps(value)
            self._redis_client.setex(key, ttl, serialized)
            _log("DEBUG", f"Cached: {key} (TTL={ttl}s)")
            return True
        except (redis.ConnectionError, redis.TimeoutError):
            _log("WARN", "Redis connection error during set")
            self._available = False
            return False
        except TypeError as e:
            _log("ERROR", f"Value not JSON serializable: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if not self._available:
            return False
        
        try:
            self._redis_client.delete(key)
            _log("DEBUG", f"Deleted cache key: {key}")
            return True
        except (redis.ConnectionError, redis.TimeoutError):
            _log("WARN", "Redis connection error during delete")
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        """
        Clear all keys matching a pattern.
        
        Args:
            pattern: Redis key pattern (e.g., "p2k:graph:*")
        
        Returns:
            Number of keys deleted
        """
        if not self._available:
            return 0
        
        try:
            keys = self._redis_client.keys(pattern)
            if keys:
                count = self._redis_client.delete(*keys)
                _log("INFO", f"Cleared {count} cache keys matching: {pattern}")
                return count
            return 0
        except (redis.ConnectionError, redis.TimeoutError):
            _log("WARN", "Redis connection error during clear_pattern")
            return 0
    
    def flush_all(self) -> bool:
        """Flush all cache entries (use with caution!)."""
        if not self._available:
            return False
        
        try:
            self._redis_client.flushdb()
            _log("INFO", "Flushed all cache entries")
            return True
        except (redis.ConnectionError, redis.TimeoutError):
            _log("WARN", "Redis connection error during flush")
            return False


# Global cache instance
_cache_manager: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    """Get the global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


def cached(prefix: str, ttl: int = CACHE_TTL):
    """
    Decorator for caching function results.
    
    Args:
        prefix: Cache key prefix
        ttl: Time to live in seconds
    
    Example:
        @cached('vertex_detail', ttl=300)
        def get_vertex_details(vertex_id):
            # expensive operation
            return result
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_cache()
            
            # Generate cache key
            cache_key = cache._generate_key(prefix, *args, **kwargs)
            
            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function
            result = func(*args, **kwargs)
            
            # Cache result
            cache.set(cache_key, result, ttl)
            
            return result
        
        return wrapper
    return decorator
