import asyncio
import os
import sys
from pathlib import Path

import pytest

# Windows'da default ProactorEventLoop asyncpg bilan "connection was closed in
# the middle of operation" xatosini beradi (aynıqsa yangi loop har testda
# yaratilganda). SelectorEventLoop bu xatoni oldini oladi — asyncpg Windows'da
# Selector loop bilan barqaror ishlaydi.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Loyiha ildizini sys.path ga qo'shish — "app" paketini import qilish uchun
# pytest tests/ dan ishga tushirilganda rootdir avtomatik qo'shilmaydi.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# test_integration_chain.py — bu fayl pytest testi emas, real AI chaqiruvlari
# ishlatuvchi mustaqil skript (python tests/test_integration_chain.py deb
# ishga tushiriladi). Uning async def funktsiyalari standart pytest kolleksiyasiga
# tushib, "async def functions are not natively supported" xatosini beradi.
# Shuning uchun uni default pytest collect'dan chiqaramiz.
collect_ignore = [
    "test_integration_chain.py",
]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
