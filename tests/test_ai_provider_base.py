"""
Tests for AI provider base utilities.

This module tests the refactored AI provider utilities including
MultiKeyRotator, AIProvider, and ProviderChain.
"""

import pytest
import asyncio
from app.services.ai_provider_base import (
    MultiKeyRotator,
    ProviderChain,
)


class TestMultiKeyRotator:
    """Test cases for MultiKeyRotator."""
    
    @pytest.mark.asyncio
    async def test_single_key_rotation(self):
        """Test rotation with single key."""
        rotator = MultiKeyRotator(["key1"])
        
        result1 = await rotator.get_next_key()
        result2 = await rotator.get_next_key()
        
        assert result1 == "key1"
        assert result2 == "key1"
    
    @pytest.mark.asyncio
    async def test_multiple_key_rotation(self):
        """Test round-robin rotation with multiple keys."""
        keys = ["key1", "key2", "key3"]
        rotator = MultiKeyRotator(keys)
        
        results = []
        for _ in range(6):
            result = await rotator.get_next_key()
            results.append(result)
        
        expected = ["key1", "key2", "key3", "key1", "key2", "key3"]
        assert results == expected
    
    @pytest.mark.asyncio
    async def test_empty_keys(self):
        """Test rotator with empty keys."""
        rotator = MultiKeyRotator([])
        
        result = await rotator.get_next_key()
        assert result is None
    
    @pytest.mark.asyncio
    async def test_sync_key_rotation(self):
        """Test synchronous key rotation."""
        rotator = MultiKeyRotator(["key1", "key2"])
        
        result1 = rotator.get_next_key_sync()
        result2 = rotator.get_next_key_sync()
        
        assert result1 == "key1"
        assert result2 == "key2"
    
    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Test thread-safe concurrent access."""
        rotator = MultiKeyRotator(["key1", "key2", "key3"])
        
        async def get_key():
            return await rotator.get_next_key()
        
        results = await asyncio.gather(*[get_key() for _ in range(10)])
        
        # All results should be valid keys
        assert all(result in ["key1", "key2", "key3"] for result in results)


class TestProviderChain:
    """Test cases for ProviderChain."""
    
    @pytest.mark.asyncio
    async def test_single_provider_success(self):
        """Test chain with single successful provider."""
        async def success_provider(*args, **kwargs):
            return "success"
        
        chain = ProviderChain([("provider1", success_provider)])
        result = await chain.execute()
        
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_fallback_to_second_provider(self):
        """Test fallback when first provider fails."""
        async def failing_provider(*args, **kwargs):
            raise RuntimeError("Provider failed")
        
        async def success_provider(*args, **kwargs):
            return "fallback_success"
        
        chain = ProviderChain([
            ("failing", failing_provider),
            ("success", success_provider)
        ])
        result = await chain.execute()
        
        assert result == "fallback_success"
    
    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        """Test when all providers in chain fail."""
        async def failing_provider(*args, **kwargs):
            raise RuntimeError("Provider failed")
        
        chain = ProviderChain([
            ("provider1", failing_provider),
            ("provider2", failing_provider)
        ])
        
        with pytest.raises(RuntimeError, match="All providers failed"):
            await chain.execute()
    
    @pytest.mark.asyncio
    async def test_provider_with_arguments(self):
        """Test provider execution with arguments."""
        async def provider_with_args(arg1, arg2):
            return f"{arg1}-{arg2}"
        
        chain = ProviderChain([("provider", provider_with_args)])
        result = await chain.execute("test1", "test2")
        
        assert result == "test1-test2"


class TestCacheIntegration:
    """Test cases for cache integration with repositories."""
    
    @pytest.mark.asyncio
    async def test_cache_decorator(self):
        """Test cache decorator functionality."""
        from app.utils.cache import SimpleCache, cached
        
        cache = SimpleCache(default_ttl=60)
        call_count = 0
        
        @cached(cache, ttl=60)
        async def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        # First call should execute function
        result1 = await expensive_function(5)
        assert result1 == 10
        assert call_count == 1
        
        # Second call should use cache
        result2 = await expensive_function(5)
        assert result2 == 10
        assert call_count == 1  # Should not increment
    
    @pytest.mark.asyncio
    async def test_cache_expiration(self):
        """Test cache expiration with TTL."""
        from app.utils.cache import SimpleCache, cached
        import time
        
        cache = SimpleCache(default_ttl=1)  # 1 second TTL
        call_count = 0
        
        @cached(cache, ttl=1)
        async def time_sensitive_function():
            nonlocal call_count
            call_count += 1
            return call_count
        
        # First call
        result1 = await time_sensitive_function()
        assert result1 == 1
        
        # Immediate second call should use cache
        result2 = await time_sensitive_function()
        assert result2 == 1
        assert call_count == 1
        
        # Wait for expiration
        await asyncio.sleep(1.5)
        
        # Third call should execute function again
        result3 = await time_sensitive_function()
        assert result3 == 2
        assert call_count == 2