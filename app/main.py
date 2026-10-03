from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # only for question images
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Dict, Any, Awaitable

from app.api.routes import router
from app.bot.bot import bot, dp
from app.config import settings
from app.database.database import init_db, SessionLocal
from app.services.report_worker import start_report_workers, stop_report_workers
from app.services.cleanup_service import requeue_stuck_processing, delete_orphan_audios

logger = logging.getLogger(__name__)


async def _periodic_stuck_recovery() -> None:
    """Har 5 daqiqada tiqilib qolgan 'processing' attemptlarni hisobot
    navbatiga qayta qo'shadi va orphan audio fayllarni tozalaydi."""
    while True:
        await asyncio.sleep(300)  # 5 daqiqa
        try:
            async with SessionLocal() as session:
                requeued = await requeue_stuck_processing(session)
                orphans = await delete_orphan_audios(session)
                await session.commit()
                if requeued or orphans:
                    logger.info(
                        "Periodic recovery: requeued=%d orphans=%d",
                        requeued,
                        orphans,
                    )
        except Exception:
            logger.exception("Periodic stuck recovery failed")


async def _startup_recovery() -> None:
    """Ishga tushganda: test holati/invite tokenni DB dan yuklaydi va
    oldingi ishga tushirishdan qolgan 'processing' attemptlarni darhol
    navbatga qaytaradi (xotiradagi navbat restartda yo'qoladi)."""
    from app.bot.test_state import load_test_state_from_db

    try:
        await load_test_state_from_db()
    except Exception:
        logger.exception("Test holatini DB dan yuklab bo'lmadi")

    try:
        from app.database.repositories import sync_admin_flags

        async with SessionLocal() as session:
            changed = await sync_admin_flags(session, settings.admin_id_list)
            if changed:
                logger.info("Admin ro'yxati ADMIN_IDS ga moslandi: %d ta o'zgarish", changed)
    except Exception:
        logger.exception("Admin ro'yxatini moslab bo'lmadi")

    try:
        async with SessionLocal() as session:
            requeued = await requeue_stuck_processing(session, stale_minutes=0)
            if requeued:
                logger.info("Startup recovery: %d ta attempt navbatga qaytarildi", requeued)
    except Exception:
        logger.exception("Startup recovery failed")


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with SessionLocal() as session:
            data["session"] = session
            return await handler(event, data)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    dp.update.middleware(DatabaseMiddleware())

    # Provider va report worker'lar run.py dan boshqariladi (single loop mode).
    # Agar mustaqil ishga tushirilgan bo'lsa (uvicorn app.main:app) —
    # yerda ham ishga tushiramiz.
    from app.services.report_worker import _started as workers_started
    if not workers_started:
        from app.services.ai_resource_manager import setup_providers
        setup_providers()
        start_report_workers()

    await _startup_recovery()

    # Periodic stuck report recovery — har 5 daqiqada "processing" attemptlarni
    # tekshiradi, navbatda yo'qlarini qayta navbatga qo'shadi.
    recovery_task = asyncio.create_task(_periodic_stuck_recovery())

    yield

    recovery_task.cancel()
    try:
        await recovery_task
    except asyncio.CancelledError:
        pass
    # Worker'lar run.py dan to'xtatiladi; agar mustaqil ishga tushirilgan bo'lsa
    # yerda to'xtatamiz.
    if not workers_started:
        await stop_report_workers()
    await bot.session.close()


app = FastAPI(
    title="Turkish Speaking Test",
    description="Telegram bot orqali turk tili speaking imtihoni",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS sozlamalari - production uchun xavfsiz
# Agar CORS_ORIGIN har qanday domen ko'rsatilmasa — API PUBLIC (credentials yo'q).
# Agar aniq domenlar ko'rsatilgan bo'lsa — credentials ruxsat etiladi.
cors_raw = settings.cors_origins if settings.cors_origins else ""
cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
allow_wildcard = "*" in cors_origins or not cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_wildcard else cors_origins,
    allow_credentials=not allow_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

import time as _time
import logging as _logging
_api_logger = _logging.getLogger("api.access")


@app.middleware("http")
async def _log_api_requests(request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        _api_logger.info("REQ %s %s", request.method, path)
    response = await call_next(request)
    if path.startswith("/api/"):
        _api_logger.info("RES %s %s -> %s", request.method, path, response.status_code)
    return response

app.include_router(router)

# Global exception handler — kutilmagan xatolarni ichki detallarsiz qaytaradi.
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc):
    _api_logger.exception("Unhandled exception: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Serverda kutilmagan xatolik yuz berdi. Keyinroq qayta urinib ko'ring."},
    )


@app.get("/health")
async def health_check():
    """Server holati va DB connection monitoring."""
    from sqlalchemy import text
    try:
        from app.database.database import IS_SQLITE

        if IS_SQLITE:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
            return {"status": "ok", "db": {"engine": "sqlite"}}

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            )
            active_connections = result.scalar()
            result2 = await session.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active' AND datname = current_database()")
            )
            active_queries = result2.scalar()
        return {
            "status": "ok",
            "db": {
                "active_connections": active_connections,
                "active_queries": active_queries,
            },
        }
    except Exception as e:
        _api_logger.error("Health check failed: %s", e)
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": "Database unavailable"},
        )

# SECURITY: Savol rasmlari uchun faqat images/ papkasini mount qilamiz.
# User audio fayllari autentifikatsiya orqali xizmat qilinadi (routes.py).
if hasattr(settings, 'upload_dir') and settings.upload_dir:
    images_dir = Path(settings.upload_dir) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/audios/images", StaticFiles(directory=str(images_dir)), name="question-images")

webapp_dist = Path(__file__).parent.parent / "webapp" / "dist"

if webapp_dist.exists() and (webapp_dist / "index.html").exists():
    _index_html = (webapp_dist / "index.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        return HTMLResponse(
            content=_index_html,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/{full_path:path}")
    async def serve_webapp(full_path: str):
        fp = webapp_dist / full_path
        if fp.is_file():
            return FileResponse(str(fp))
        return HTMLResponse(
            content=_index_html,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
else:
    @app.get("/")
    async def fallback_index():
        return HTMLResponse("<h3>WebApp dist papkasi topilmadi! npm run build bajaring.</h3>")
