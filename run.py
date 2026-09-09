"""
run.py — Hamma narsani bir joyda ishga tushiradi (Cloudflare Tunnel bilan).

Arxitektura: Bitta event loop — bot polling va FastAPI shu loopda ishlaydi.
DB connection pool: real pool (pool_size=20), NullPool emas.

Ishlatilish:
    python run.py
"""

import asyncio
import logging
import os
import sys
import signal
import subprocess
from datetime import timedelta

# Windows'da emoji va o'zbek harflari to'g'ri chiqishi uchun
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import uvicorn
from dotenv import load_dotenv

load_dotenv()
# ──────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────
from app.config import settings
from app.logging_config import setup_logging

_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
setup_logging(level=_log_level)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# NGROK TUNNEL (avtomatik ishga tushirish)
# ──────────────────────────────────────────
NGROK_PUBLIC_URL = None

def start_ngrok():
    """Ngrok tunnelni avtomatik ishga tushiradi."""
    global NGROK_PUBLIC_URL
    
    try:
        from pyngrok import ngrok, conf
        
        token = os.getenv("NGROK_AUTHTOKEN")
        if not token:
            logger.error("❌ NGROK_AUTHTOKEN .env da topilmadi!")
            return False
        
        logger.info("🔌 Ngrok ulanmoqda...")
        conf.get_default().auth_token = token

        try:
            for t in ngrok.get_tunnels():
                addr = str(t.config.get("addr", ""))
                proto = t.proto if hasattr(t, "proto") else "http"
                if addr.endswith(":8000") and proto == "http":
                    NGROK_PUBLIC_URL = t.public_url
                    if NGROK_PUBLIC_URL.startswith("http://"):
                        NGROK_PUBLIC_URL = NGROK_PUBLIC_URL.replace("http://", "https://")
                    logger.info(f"✅ Mavjud ngrok tunnel qayta ishlatildi: {NGROK_PUBLIC_URL}")
                    return True
        except Exception:
            pass

        try:
            ngrok.kill()
        except Exception:
            pass

        last_error = None
        for attempt in range(3):
            try:
                tunnel = ngrok.connect(8000, "http")
                NGROK_PUBLIC_URL = tunnel.public_url

                if NGROK_PUBLIC_URL.startswith("http://"):
                    NGROK_PUBLIC_URL = NGROK_PUBLIC_URL.replace("http://", "https://")

                logger.info(f"✅ Ngrok HTTPS: {NGROK_PUBLIC_URL}")
                return True
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ Ngrok urinish {attempt + 1}/3 amalga oshmadi: {e}")
                try:
                    ngrok.kill()
                except Exception:
                    pass
                import time
                time.sleep(3)

        logger.error(f"❌ Ngrok xato: {last_error}")
        return False
        
    except ImportError:
        logger.error("❌ pyngrok o'rnatilmagan: pip install pyngrok")
    except Exception as e:
        logger.error(f"❌ Ngrok xato: {e}")
    
    return False

# ──────────────────────────────────────────
# TELEGRAM BOT
# ──────────────────────────────────────────
async def start_bot():
    """Telegram botni ishga tushiradi."""
    from app.bot.bot import bot, dp
    from app.bot.handlers import handlers_router
    from app.database.database import init_db

    await init_db()
    dp.include_router(handlers_router)

    # Background task: har kuni 00:00 da limitni qaytarish
    asyncio.create_task(daily_limit_reset_task())

    await dp.start_polling(bot)


async def daily_limit_reset_task():
    """Har kuni 00:00 da test settings ni kunlik rejimga qaytaradi."""
    from datetime import time
    from app.database.database import SessionLocal
    from app.database.repositories import create_or_update_test_settings
    from app.utils.helpers import utcnow

    while True:
        now = utcnow()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        seconds_until_midnight = (tomorrow - now).total_seconds()

        logger.info(f"⏰ Limit qaytarish {seconds_until_midnight:.0f} soniyadan so'ng amalga oshadi.")

        await asyncio.sleep(seconds_until_midnight)

        try:
            async with SessionLocal() as session:
                await create_or_update_test_settings(session, "daily", 1)
                logger.info("✅ Kunlik limit avtomatik qaytarildi (daily mode, limit=1)")
        except Exception as e:
            logger.error(f"❌ Limit qaytarishda xato: {e}")


# ──────────────────────────────────────────
# VITE FRONTEND (subprocess ichida)
# ──────────────────────────────────────────
def start_vite():
    """Vite dev serverni alohida subprocess da ishga tushiradi."""
    webapp_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "webapp",
    )

    if not os.path.isdir(webapp_dir):
        logger.warning("⚠️ webapp/ papka topilmadi, frontend ishga tushirilmadi.")
        return

    try:
        npm_command = "npm.cmd" if sys.platform == "win32" else "npm"

        import shutil
        npm_path = shutil.which(npm_command)

        if not npm_path:
            logger.warning(
                "⚠️ npm topilmadi — Vite dev-server ishga tushmaydi. "
                "webapp/dist oldindan build qilingan va FastAPI "
                "http://localhost:8000 da xizmat qiladi."
            )
            return

        logger.info(f"🔎 npm topildi: {npm_path}")

        subprocess.Popen(
            [npm_path, "run", "dev"],
            cwd=webapp_dir,
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=False,
        )

        logger.info(
            "✅ Vite frontend ishga tushdi: http://localhost:5173"
        )

    except Exception as e:
        logger.error(f"❌ Vite xato: {e}")


# ──────────────────────────────────────────
# ASOSIY ISHGA TUSHIRISH — Bitta event loop
# ──────────────────────────────────────────
async def main():
    from app.main import app
    from app.bot.bot import bot, dp
    from app.database.database import init_db
    from app.services.report_worker import start_report_workers, stop_report_workers
    from app.services.ai_resource_manager import setup_providers

    # 1. DB ni ishga tushirish
    await init_db()

    # 2. AI providerlarni ro'yxatdan o'tkazish
    setup_providers()

    # 3. Report workerlarni ishga tushirish (bitta loopda — pool safe)
    start_report_workers()

    # 4. Vite frontendni ishga tushirish
    logger.info("🌐 Frontend (Vite) ishga tushmoqda...")
    start_vite()

    # 5. Ngrok tunnelni ishga tushirish
    start_ngrok()

    # 6. WebApp URL ni yangilash
    if NGROK_PUBLIC_URL:
        try:
            settings.webapp_url = NGROK_PUBLIC_URL
        except Exception:
            pass
        os.environ["WEBAPP_URL"] = NGROK_PUBLIC_URL
        logger.info(f"🌐 WebApp URL avtomatik sozlandi: {NGROK_PUBLIC_URL}")
    else:
        logger.warning("⚠️ Ngrok URL olinmadi, lekin bot ishlayveradi.")

    # 7. Uvicorn serverni bitta loopda ishga tushirish (thread emas!)
    # Thread o'rniga background task — bitta event loop, bitta pool.
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="warning",
        access_log=False,
        workers=1,
        limit_concurrency=300,
        timeout_keep_alive=60,
    )
    server = uvicorn.Server(config)

    logger.info("🚀 FastAPI + Bot bitta loop'da ishga tushmoqda...")

    # Server'ni background task sifatida ishga tushirish
    server_task = asyncio.create_task(server.serve())

    # Server ishga tushishini kutish
    while not server.started:
        await asyncio.sleep(0.1)

    logger.info("✅ FastAPI tayyor: http://localhost:8000")
    logger.info("🤖 Bot ishga tushmoqda...")

    # 8. Bot polling — asosiy loopni bloklab turadi
    try:
        await dp.start_polling(bot)
    finally:
        # Graceful shutdown: server'ni to'xtatish
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

        # Report workerlarni to'xtatish
        await stop_report_workers()

        # Bot session'ni yopish
        await bot.session.close()

        logger.info("👋 Bot to'xtatildi.")


# ──────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 56)
    print("   🤖 TURK TILI SPEAKING TEST BOT")
    print("=" * 56)
    _admin_raw = os.getenv("ADMIN_IDS", "")
    _admin_count = len([a for a in _admin_raw.split(",") if a.strip()]) if _admin_raw else 0
    print(f"   Admins    : {_admin_count} ta (qiymatlar loglanmaydi)")
    print(f"   AI Prov.  : {os.getenv('AI_PROVIDER', 'openai')}")
    print(f"   Port      : 8000")
    print(f"   Mode      : Single event loop (no threading)")
    print("=" * 56)
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot to'xtatildi (Ctrl+C).")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)
            else:
                subprocess.run(["pkill", "cloudflared"], capture_output=True)
        except Exception:
            pass
        sys.exit(0)
