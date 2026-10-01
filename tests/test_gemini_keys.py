"""
Gemini kalitlari va 60+ user yuklamasi uchun tuzatishlar:
- Transkripsiya bir nechta kalitni navbat bilan ishlatadi (oldin doim 1-kalit)
- Faqat GEMINI_API_KEYS berilsa ham baholash Gemini'dan foydalanadi
- AI thread pool worker sonidan kichik emas
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.services import evaluation_service, report_worker, transcription_service


@pytest.fixture
def two_gemini_keys(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_keys", "key-A,key-B")
    monkeypatch.setattr(transcription_service, "_gemini_rotator", None)
    monkeypatch.setattr(evaluation_service, "_gemini_rotator", None)
    yield


@pytest.mark.anyio
async def test_transcription_rotates_gemini_keys(two_gemini_keys, tmp_path):
    audio = tmp_path / "a.webm"
    audio.write_bytes(b"x" * 2048)
    used_keys = []

    class FakeClient:
        def __init__(self, api_key=None, **kw):
            used_keys.append(api_key)
            self.models = SimpleNamespace(
                generate_content=lambda **kw: SimpleNamespace(text="Merhaba")
            )

    with patch("google.genai.Client", FakeClient), \
         patch.object(transcription_service, "wait_gemini", AsyncMock()):
        for _ in range(4):
            await transcription_service._transcribe_with_gemini(audio)

    assert used_keys == ["key-A", "key-B", "key-A", "key-B"]


@pytest.mark.anyio
async def test_evaluation_uses_gemini_with_only_multi_keys(two_gemini_keys):
    expected = {"score": 80}
    gemini = AsyncMock(return_value=expected)
    with patch.object(evaluation_service, "_evaluate_with_gemini", gemini):
        result = await evaluation_service.evaluate_answer("Soru?", "Cevap")

    assert result == expected
    gemini.assert_awaited_once()


def test_ai_thread_pool_not_smaller_than_workers():
    # Har bir worker bir vaqtda bitta AI chaqiruv qiladi — pool ularni sig'dirishi kerak.
    assert report_worker.AI_THREAD_POOL_SIZE >= report_worker.REPORT_WORKERS


@pytest.mark.anyio
async def test_thread_pool_allows_parallel_ai_calls():
    loop = asyncio.get_running_loop()
    report_worker._ensure_thread_pool(loop)

    import threading
    import time

    running = {"now": 0, "max": 0}
    lock = threading.Lock()

    def blocking_call():
        with lock:
            running["now"] += 1
            running["max"] = max(running["max"], running["now"])
        time.sleep(0.2)
        with lock:
            running["now"] -= 1

    await asyncio.gather(*(asyncio.to_thread(blocking_call) for _ in range(report_worker.REPORT_WORKERS)))
    assert running["max"] == report_worker.REPORT_WORKERS


@pytest.mark.anyio
async def test_evaluation_retries_on_server_error():
    # Oldin `random` import qilinmagani uchun 500/503 xatoda retry o'rniga NameError chiqardi.
    fn = AsyncMock(side_effect=[RuntimeError("503 UNAVAILABLE"), {"score": 70}])
    with patch.object(evaluation_service.asyncio, "sleep", AsyncMock()):
        result = await evaluation_service._evaluate_with_retry("gemini", fn, "Soru?", "Cevap")

    assert result == {"score": 70}
    assert fn.await_count == 2
