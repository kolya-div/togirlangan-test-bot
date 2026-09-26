"""
AI Provider Base - Reusable utilities for AI service integration.

Bu modul AI providerlar uchun umumiy funksionallikni taqdim etadi:
- Multi-key rotation (round-robin)
- Retry logic with exponential backoff
- Rate limiting integration
- Error handling and fallback
"""

import asyncio
import logging
import random
import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional, TypeVar, Generic, Any

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar('T')


class AIProvider(ABC, Generic[T]):
    """Abstract base class for AI providers with retry and fallback logic."""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 2.0,
        rate_limit_delay: float = 10.0,
        timeout: float = 120.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.rate_limit_delay = rate_limit_delay
        self.timeout = timeout
    
    @abstractmethod
    async def _call_provider(self, *args, **kwargs) -> T:
        """Provider-specific implementation."""
        pass
    
    @abstractmethod
    def _get_provider_name(self) -> str:
        """Provider name for logging."""
        pass
    
    async def call_with_retry(self, *args, **kwargs) -> T:
        """Execute provider call with retry logic."""
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                result = await asyncio.wait_for(
                    self._call_provider(*args, **kwargs),
                    timeout=self.timeout
                )
                return result
                
            except asyncio.TimeoutError:
                last_error = "Timeout"
                logger.warning(
                    f"Timeout ({self._get_provider_name()}), "
                    f"attempt {attempt + 1}/{self.max_retries}"
                )
                
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                
                # Rate limit handling
                if any(kw in err_str for kw in ["429", "rate limit", "quota", "too many requests"]):
                    delay = self.rate_limit_delay * (attempt + 1)
                    logger.warning(
                        f"Rate limit ({self._get_provider_name()}), "
                        f"{delay}s wait, attempt {attempt + 1}/{self.max_retries}"
                    )
                    await asyncio.sleep(delay)
                    continue
                
                # Auth/invalid request errors - don't retry
                if any(kw in err_str for kw in ["400", "invalid", "unsupported", "auth"]):
                    raise RuntimeError(f"Provider error ({self._get_provider_name()}): {e}") from None
                
                logger.warning(
                    f"Provider error ({self._get_provider_name()}), "
                    f"attempt {attempt + 1}/{self.max_retries}: {e}"
                )
            
            # Exponential backoff for non-rate-limit errors
            if attempt < self.max_retries - 1:
                delay = self.base_delay * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
        
        raise RuntimeError(f"Provider failed ({self._get_provider_name()}): {last_error}")


class MultiKeyRotator:
    """Thread-safe multi-key rotation for API keys."""
    
    def __init__(self, keys: list[str]):
        self.keys = keys
        self.counter = 0
        self.async_lock = asyncio.Lock()
        self.sync_lock = threading.Lock()
    
    async def get_next_key(self) -> Optional[str]:
        """Get next key in round-robin fashion (async)."""
        if not self.keys:
            return None
        
        async with self.async_lock:
            key = self.keys[self.counter % len(self.keys)]
            self.counter += 1
            return key
    
    def get_next_key_sync(self) -> Optional[str]:
        """Get next key synchronously (for retry scenarios)."""
        if not self.keys:
            return None
        
        with self.sync_lock:
            key = self.keys[self.counter % len(self.keys)]
            self.counter += 1
            return key


class ProviderChain:
    """Chain of providers with fallback support."""
    
    def __init__(self, providers: list[tuple[str, Callable]]):
        self.providers = providers
    
    async def execute(self, *args, **kwargs) -> any:
        """Execute provider chain with fallback."""
        for idx, (name, fn) in enumerate(self.providers):
            try:
                result = await fn(*args, **kwargs)
                return result
            except RuntimeError as e:
                remaining = len(self.providers) - idx - 1
                if remaining > 0:
                    logger.warning(
                        f"Provider '{name}' failed, fallback → "
                        f"{self.providers[idx + 1][0]}: {e}"
                    )
                else:
                    logger.error(
                        f"All providers failed ({[p[0] for p in self.providers]}): {e}"
                    )
                    raise
        
        raise RuntimeError("All providers in chain failed")


def create_gemini_rotator() -> Optional[MultiKeyRotator]:
    """Create Gemini key rotator from settings."""
    keys = settings.gemini_keys_list
    if keys:
        return MultiKeyRotator(keys)
    return None