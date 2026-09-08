"""
Telegram report stress test — 100 concurrent reports.

Tests:
- 100 reports sent concurrently
- Telegram 429 handling
- Timeout handling
- Network error handling
- Duplicate job prevention
- Worker restart resilience

Usage:
    python -m tests.stress_telegram_send
"""

import asyncio
import time
import random
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.telegram_sender import (
    TelegramSender, SendMetrics, MAX_SEND_RETRIES, DEDUP_WINDOW,
)


class FakeTelegramAPI:
    """Simulates Telegram API with configurable failures."""

    def __init__(self):
        self.call_count = 0
        self.fail_count = 0
        self.error_type = None  # "429", "timeout", "network"
        self.retry_after = None
        self.send_times = []

    def configure(self, error_type=None, fail_every_n=0, retry_after=None):
        self.error_type = error_type
        self.fail_every_n = fail_every_n
        self.retry_after = retry_after

    async def send_message(self, **kwargs):
        self.call_count += 1
        start = time.monotonic()

        # Simulate failure
        if self.error_type and (self.fail_every_n == 0 or self.call_count % self.fail_every_n == 0):
            if self.error_type == "429":
                msg = "Too Many Requests: retry after"
                if self.retry_after:
                    msg += f" {self.retry_after}"
                raise Exception(msg)
            elif self.error_type == "timeout":
                raise asyncio.TimeoutError("Telegram API timeout")
            elif self.error_type == "network":
                raise ConnectionError("Connection refused")

        self.send_times.append(time.monotonic() - start)
        return True

    async def send_audio(self, **kwargs):
        return await self.send_message(**kwargs)

    async def send_document(self, **kwargs):
        return await self.send_message(**kwargs)


async def test_basic_send():
    """Oddiy yuborish — 100 ta xabar."""
    print("\n=== Test 1: Basic send (100 messages) ===")
    api = FakeTelegramAPI()
    sender = TelegramSender()
    sender._get_bot = lambda: MagicMock(
        send_message=AsyncMock(side_effect=api.send_message),
        send_audio=AsyncMock(side_effect=api.send_audio),
        send_document=AsyncMock(side_effect=api.send_document),
    )

    start = time.monotonic()
    tasks = [sender.send_message(10000 + i, f"Test message {i}") for i in range(100)]
    results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start

    success = sum(1 for r in results if r is True)
    print(f"  Results: {success}/100 sent, {100 - success} failed")
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Throughput: {100 / elapsed:.1f} msg/s")
    print(f"  API calls: {api.call_count}")
    assert success == 100, f"Expected 100, got {success}"


async def test_429_handling():
    """429 error — retry_after bilan."""
    print("\n=== Test 2: 429 handling ===")
    api = FakeTelegramAPI()
    api.configure(error_type="429", fail_every_n=1, retry_after=1)

    sender = TelegramSender()
    sender._get_bot = lambda: MagicMock(
        send_message=AsyncMock(side_effect=api.send_message),
    )

    # Bitta xabar — 429 dan keyin muvaffaqiyatli bo'lishi kerak
    # Lekin fail_every_n=1 har doim xato beradi, shuning uchun retrylar tugaydi
    result = await sender.send_message(10000, "Test 429")
    print(f"  Result: {result}")
    print(f"  API calls: {api.call_count}")
    print(f"  Metrics: retries={sender.metrics.total_retries}, 429s={sender.metrics.total_429}")
    # 429 doimiy bo'lsa, retrylar tugaydi va False qaytadi
    assert result is False or api.call_count > 1


async def test_timeout_handling():
    """Timeout error — retry."""
    print("\n=== Test 3: Timeout handling ===")
    api = FakeTelegramAPI()
    # Birinchi 2 ta timeout, keyin muvaffaqiyat
    call_count = [0]
    original = api.send_message

    async def timeout_then_ok(**kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            raise asyncio.TimeoutError("timeout")
        return True

    sender = TelegramSender()
    sender._get_bot = lambda: MagicMock(
        send_message=AsyncMock(side_effect=timeout_then_ok),
    )

    result = await sender.send_message(10000, "Test timeout")
    print(f"  Result: {result}")
    print(f"  API calls: {call_count[0]}")
    print(f"  Metrics: retries={sender.metrics.total_retries}, timeouts={sender.metrics.total_timeout}")
    assert result is True
    assert call_count[0] == 3


async def test_network_error():
    """Network error — retry."""
    print("\n=== Test 4: Network error handling ===")
    api = FakeTelegramAPI()
    call_count = [0]

    async def network_then_ok(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ConnectionError("Connection refused")
        return True

    sender = TelegramSender()
    sender._get_bot = lambda: MagicMock(
        send_message=AsyncMock(side_effect=network_then_ok),
    )

    result = await sender.send_message(10000, "Test network")
    print(f"  Result: {result}")
    print(f"  API calls: {call_count[0]}")
    print(f"  Metrics: retries={sender.metrics.total_retries}, network={sender.metrics.total_network_error}")
    assert result is True


async def test_duplicate_prevention():
    """Duplicate xabar yuborilmasin."""
    print("\n=== Test 5: Duplicate prevention ===")
    api = FakeTelegramAPI()

    sender = TelegramSender()
    sender._get_bot = lambda: MagicMock(
        send_message=AsyncMock(side_effect=api.send_message),
    )

    # Bir xil xabar 2 marta
    r1 = await sender.send_message(10000, "Same message")
    r2 = await sender.send_message(10000, "Same message")

    print(f"  First: {r1}, Second: {r2}")
    print(f"  API calls: {api.call_count} (should be 1)")
    assert r1 is True
    assert r2 is True  # Duplicate returns True (idempotent)
    assert api.call_count == 1


async def test_concurrent_100_reports():
    """100 ta hisobot bir vaqtda — ordered messages per user."""
    print("\n=== Test 6: 100 concurrent reports ===")
    api = FakeTelegramAPI()

    sender = TelegramSender()
    sender._get_bot = lambda: MagicMock(
        send_message=AsyncMock(side_effect=api.send_message),
    )

    async def send_user_report(user_id, num_messages=5):
        """Bitta user uchun 5 ta xabar (ordered)."""
        for i in range(num_messages):
            await sender.send_message(user_id, f"User {user_id} msg {i}")

    start = time.monotonic()
    tasks = [send_user_report(10000 + i) for i in range(100)]
    await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start

    print(f"  Total API calls: {api.call_count}")
    print(f"  Expected: 500 (100 users x 5 msgs)")
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Throughput: {500 / elapsed:.1f} msg/s")
    print(f"  Metrics: {sender.metrics.to_dict()}")
    assert api.call_count == 500


async def test_worker_restart_resilience():
    """Worker restart — deduplication tozalanishi."""
    print("\n=== Test 7: Worker restart resilience ===")

    sender1 = TelegramSender()
    sender1._get_bot = lambda: MagicMock(
        send_message=AsyncMock(return_value=True),
    )

    # Birinchi batch
    await sender1.send_message(10000, "Message 1")
    await sender1.send_message(10000, "Message 1")  # Duplicate — skipped

    print(f"  After first batch: {sender1.metrics.total_sent}")

    # Yangi sender (restart simulyatsiyasi)
    sender2 = TelegramSender()
    sender2._get_bot = lambda: MagicMock(
        send_message=AsyncMock(return_value=True),
    )

    # Restart keyin — xabar yuborilishi kerak (dedup tozalandi)
    result = await sender2.send_message(10000, "Message 1")
    print(f"  After restart: {result}, API calls: {sender2.metrics.total_sent}")
    assert result is True


async def test_message_ordering():
    """Bitta user reportining message'lari tartibli."""
    print("\n=== Test 8: Message ordering ===")
    order_log = []

    async def tracking_send(**kwargs):
        order_log.append(kwargs.get("text", ""))
        return True

    sender = TelegramSender()
    sender._get_bot = lambda: MagicMock(
        send_message=AsyncMock(side_effect=tracking_send),
    )

    # 10 ta xabar ketma-ket
    for i in range(10):
        await sender.send_message(10000, f"Message {i}")

    print(f"  Messages sent in order: {order_log[:5]}...")
    expected = [f"Message {i}" for i in range(10)]
    assert order_log == expected, f"Order mismatch: {order_log}"


async def main():
    print("=" * 60)
    print("TELEGRAM SENDER STRESS TEST")
    print("=" * 60)

    await test_basic_send()
    await test_429_handling()
    await test_timeout_handling()
    await test_network_error()
    await test_duplicate_prevention()
    await test_concurrent_100_reports()
    await test_worker_restart_resilience()
    await test_message_ordering()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
