"""
AI resource manager: rate limiting + provider health + exponential backoff.

Barcha AI/STT calllarni markazlashtirilgan boshqaradi.
Provider health tracking: success/failure count, cooldown, auto-disable.
"""

import asyncio
import time
import random
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    name: str
    rpm: int  # requests per minute
    timeout: float = 120.0
    max_retries: int = 3
    cooldown_seconds: float = 60.0  # consecutive failures keyin kutish
    max_consecutive_failures: int = 5


@dataclass
class ProviderHealth:
    name: str
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    last_failure_time: float = 0.0
    disabled_until: float = 0.0
    last_error: str = ""

    @property
    def is_available(self) -> bool:
        if self.disabled_until and time.monotonic() < self.disabled_until:
            return False
        return True

    def record_success(self):
        self.consecutive_failures = 0
        self.total_successes += 1
        self.disabled_until = 0.0

    def record_failure(self, error: str):
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_failure_time = time.monotonic()
        self.last_error = error
        if self.consecutive_failures >= 5:
            cooldown = 60.0 * (2 ** min(self.consecutive_failures - 5, 5))
            self.disabled_until = time.monotonic() + cooldown
            logger.warning(
                "Provider %s disabled for %.0fs (consecutive failures: %d)",
                self.name, cooldown, self.consecutive_failures,
            )


class RateLimiter:
    """Token bucket rate limiter per provider."""

    def __init__(self, rpm: int):
        self._min_interval = 60.0 / rpm
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                wait = self._min_interval - elapsed
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()


class AIResourceManager:
    """Markazlashtirilgan AI resource manager."""

    def __init__(self):
        self._configs: dict[str, ProviderConfig] = {}
        self._health: dict[str, ProviderHealth] = {}
        self._limiters: dict[str, RateLimiter] = {}

    def register_provider(self, config: ProviderConfig):
        self._configs[config.name] = config
        self._health[config.name] = ProviderHealth(name=config.name)
        self._limiters[config.name] = RateLimiter(config.rpm)
        logger.info(
            "Provider registered: %s (RPM=%d, timeout=%.0fs, retries=%d)",
            config.name, config.rpm, config.timeout, config.max_retries,
        )

    def get_health(self, name: str) -> ProviderHealth | None:
        return self._health.get(name)

    def get_all_health(self) -> dict[str, dict]:
        result = {}
        for name, health in self._health.items():
            result[name] = {
                "available": health.is_available,
                "consecutive_failures": health.consecutive_failures,
                "total_successes": health.total_successes,
                "total_failures": health.total_failures,
                "last_error": health.last_error,
            }
        return result

    async def call_with_retry(
        self,
        provider_name: str,
        fn,
        *args,
        **kwargs,
    ):
        """
        Provider bilan retry, backoff, fallback support.
        Bitta request failure butun reportni yiqitmaydi.
        """
        config = self._configs.get(provider_name)
        if not config:
            raise ValueError(f"Unknown provider: {provider_name}")

        health = self._health[provider_name]
        limiter = self._limiters[provider_name]

        last_error = None
        for attempt in range(config.max_retries):
            # Provider available tekshirish
            if not health.is_available:
                logger.warning(
                    "Provider %s in cooldown (%.0fs left), skipping attempt %d",
                    provider_name,
                    max(0, health.disabled_until - time.monotonic()),
                    attempt + 1,
                )
                raise RuntimeError(
                    f"Provider {provider_name} in cooldown: {health.last_error}"
                )

            # Rate limit acquire
            await limiter.acquire()

            try:
                result = await asyncio.wait_for(
                    fn(*args, **kwargs),
                    timeout=config.timeout,
                )
                health.record_success()
                return result

            except asyncio.TimeoutError:
                last_error = f"Timeout after {config.timeout}s"
                health.record_failure(last_error)
                logger.warning(
                    "Timeout (%s), attempt %d/%d",
                    provider_name, attempt + 1, config.max_retries,
                )

            except Exception as e:
                last_error = str(e)
                err_lower = last_error.lower()

                # Rate limit — extra backoff
                if any(kw in err_lower for kw in ["429", "rate limit", "quota", "too many requests"]):
                    delay = 10.0 * (attempt + 1)
                    logger.warning(
                        "Rate limit (%s), waiting %.1fs, attempt %d/%d",
                        provider_name, delay, attempt + 1, config.max_retries,
                    )
                    await asyncio.sleep(delay)
                    health.record_failure(last_error)
                    continue

                # Auth error — no retry
                if any(kw in err_lower for kw in ["400", "invalid", "unsupported", "auth", "401", "403"]):
                    health.record_failure(last_error)
                    raise RuntimeError(f"Provider {provider_name} auth error: {e}") from None

                health.record_failure(last_error)
                logger.warning(
                    "Provider %s error: %s, attempt %d/%d",
                    provider_name, e, attempt + 1, config.max_retries,
                )

            # Exponential backoff with jitter
            if attempt < config.max_retries - 1:
                delay = 2.0 * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"Provider {provider_name} failed after {config.max_retries} attempts: {last_error}"
        )


# Global instance
ai_manager = AIResourceManager()


def setup_providers():
    """Providerlarni ro'yxatdan o'tkazadi."""
    from app.config import settings

    if getattr(settings, "gemini_api_key", None) or getattr(settings, "gemini_keys_list", None):
        gemini_rpm = getattr(settings, "gemini_rpm_per_key", 15) * max(
            1, len(getattr(settings, "gemini_keys_list", []) or [])
        )
        ai_manager.register_provider(ProviderConfig(
            name="gemini",
            rpm=gemini_rpm,
            timeout=120.0,
            max_retries=3,
        ))

    if getattr(settings, "groq_api_key", None):
        groq_rpm = getattr(settings, "groq_rpm_per_key", 30)
        ai_manager.register_provider(ProviderConfig(
            name="groq",
            rpm=groq_rpm,
            timeout=120.0,
            max_retries=3,
        ))

    if getattr(settings, "openai_api_key", None):
        openai_rpm = getattr(settings, "openai_rpm_per_key", 60)
        ai_manager.register_provider(ProviderConfig(
            name="openai",
            rpm=openai_rpm,
            timeout=90.0,
            max_retries=2,
        ))
