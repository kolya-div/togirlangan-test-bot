"""
Simple caching utility for performance optimization.

This module provides in-memory caching for frequently accessed data
to reduce database load and improve response times.
"""

import asyncio
import logging
from functools import wraps
from typing import Callable, TypeVar, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

T = TypeVar('T')


class SimpleCache:
    """Simple in-memory cache with TTL support."""
    
    def __init__(self, default_ttl: int = 300):  # 5 minutes default
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache if exists and not expired."""
        async with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if datetime.now() < expiry:
                    return value
                else:
                    # Expired, remove it
                    del self._cache[key]
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with optional TTL."""
        async with self._lock:
            ttl = ttl or self._default_ttl
            expiry = datetime.now() + timedelta(seconds=ttl)
            self._cache[key] = (value, expiry)
    
    async def delete(self, key: str) -> None:
        """Delete specific key from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
    
    async def cleanup_expired(self) -> int:
        """Remove expired entries and return count of removed items."""
        async with self._lock:
            now = datetime.now()
            expired_keys = [
                key for key, (_, expiry) in self._cache.items()
                if expiry < now
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)


# Global cache instances
questions_cache = SimpleCache(default_ttl=600)  # 10 minutes for questions
test_settings_cache = SimpleCache(default_ttl=300)  # 5 minutes for settings


def cached(cache_instance: SimpleCache, ttl: Optional[int] = None):
    """Decorator for caching function results."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Try to get from cache
            cached_value = await cache_instance.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            await cache_instance.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


async def cleanup_task(interval: int = 300):
    """Background task to clean up expired cache entries."""
    while True:
        try:
            await asyncio.sleep(interval)
            removed = await questions_cache.cleanup_expired()
            removed += await test_settings_cache.cleanup_expired()
            if removed > 0:
                logger.info(f"Cache cleanup: removed {removed} expired entries")
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")