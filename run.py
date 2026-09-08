"""
run.py — Hamma narsani bir joyda ishga tushiradi (Cloudflare Tunnel bilan).

Ishlatilish:
    python run.py
"""

import asyncio
import logging
import os
import sys
import threading
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

        # 1-urinish: allaqachon ishlayotgan tunnel bormi?
        # (eski ngrok agent tirik bo'lsa ERR_NGROK_334 beradi — undan
        # qochish uchun mavjud 8000 tunnelini qayta ishlatamiz)
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

        # Eski ochilgan ngrok jarayonlarini tozalash
        try:
            ngrok.kill()
        except Exception:
            pass

        # Tunnelni ochish (ortda qolgan agent egasini bo'shatishi uchun bir oz kutamiz)
        last_error = None
        for attempt in range(3):
            try:
                tunnel = ngrok.connect(8000, "http")
                NGROK_PUBLIC_URL = tunnel.public_url

                # http larni https ga o'tkazish (Telegram faqat https qabul qiladi)
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
# FASTAPI SERVER (thread ichida)
# ──────────────────────────────────────────
def start_fastapi():
    """FastAPI ni alohida thread da ishga tushiradi."""
    # SAFETY: asyncio.Queue in-memory — faqat workers=1 bilan ishlaydi.
    # Workers > 1 ishlatsa, report joblar yo'qoladi (silent job loss).
    workers = 1
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="warning",
        access_log=False,
        workers=workers,
        limit_concurrency=300,
        timeout_keep_alive=60,
    )


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

    # Eksport+wipe scheduler: har kuni 00:00 da natijalarni .docx ga eksport
    # qiladi va (kamida 1 admin faylni olgan bo'lsa) BARCHA foydalanuvchilarni
    # tozalaydi. Savollar va test sozlamalari saqlanadi.
    # PARTIAL: 2026-08-31 — xavfli wipe (adminlarni ham o'chiradi) tufayli
    # vaqtincha kommentariya qilindi. Xavfsiz wipe tasdiqlanmaguncha yoqilmang.
    # asyncio.create_task(daily_export_wipe_task())

    await dp.start_polling(bot)


async def daily_limit_reset_task():
    """Har kuni 00:00 da test settings ni kunlik rejimga qaytaradi."""
    from datetime import time
    from app.database.database import SessionLocal
    from app.database.repositories import create_or_update_test_settings
    from app.utils.helpers import utcnow

    while True:
        # Bugun 00:00 ni hisoblash
        now = utcnow()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        seconds_until_midnight = (tomorrow - now).total_seconds()

        logger.info(f"⏰ Limit qaytarish {seconds_until_midnight:.0f} soniyadan so'ng amalga oshadi.")

        # 00:00 gacha kutish
        await asyncio.sleep(seconds_until_midnight)

        # Limitni qaytarish
        try:
            async with SessionLocal() as session:
                await create_or_update_test_settings(session, "daily", 1)
                logger.info("✅ Kunlik limit avtomatik qaytarildi (daily mode, limit=1)")
        except Exception as e:
            logger.error(f"❌ Limit qaytarishda xato: {e}")


async def daily_export_wipe_task():
    """Har kuni 00:00 da foydalanuvchilar natijalarini .docx hisobotga
    eksport qiladi va adminlarning kamida bittasi faylni olgan bo'lsa
    bazani tozalaydi (wipe).

    Bu vazifa run_daily_export_and_wipe() orqali ishlaydi:
      - Eksport .docx fayli adminlarga yuboriladi.
      - admin_id_list bo'sh bo'lsa yoki hech bir admin faylni olmagan
        bo'lsa — wipe bajarilmaydi, fayl saqlanadi.
      - Kamida bitta admin faylni olgan bo'lsa — wipe bajariladi va
        yuborilgan fayl o'chiriladi.
    """
    from app.services.daily_export_wipe import run_daily_export_and_wipe
    from app.utils.helpers import utcnow

    while True:
        now = utcnow()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        seconds_until_midnight = (tomorrow - now).total_seconds()

        logger.info(f"📊 Eksport+wipe {seconds_until_midnight:.0f} soniyadan so'ng (00:00) amalga oshadi.")

        await asyncio.sleep(seconds_until_midnight)

        try:
            result = await run_daily_export_and_wipe()
            if result is None:
                logger.info("📊 Eksport+wipe: wipe bajarilmadi (fayl saqlanib qoldi).")
            else:
                logger.info(f"📊 Eksport+wipe tugallandi: {result}")
        except Exception as e:
            logger.error(f"❌ Eksport+wipe xato: {e}")


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
        # Windows'da npm odatda npm.cmd bo'ladi.
        npm_command = "npm.cmd" if sys.platform == "win32" else "npm"

        # PATH orqali npm'ni topishga harakat qilamiz.
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
# ASOSIY ISHGA TUSHIRISH
# ──────────────────────────────────────────
async def main():
    # 1. Vite frontendni ishga tushirish (eng birinchi)
    logger.info("🌐 Frontend (Vite) ishga tushmoqda...")
    start_vite()

    # 2. FastAPI serverni ishga tushirish
    logger.info("🚀 FastAPI ishga tushmoqda...")
    fastapi_thread = threading.Thread(
        target=start_fastapi,
        daemon=True
    )
    fastapi_thread.start()

    # Server ishga tushishini kutish
    await asyncio.sleep(1.5)
    logger.info("✅ FastAPI tayyor: http://localhost:8000")

    # 2. Ngrok tunnelni ishga tushirish (start_ngrok chaqiriladi)
    start_ngrok()

    # 3. WebApp URL ni yangilash
    if NGROK_PUBLIC_URL:
        try:
            from app.config import settings
            settings.webapp_url = NGROK_PUBLIC_URL
        except Exception:
            pass
        os.environ["WEBAPP_URL"] = NGROK_PUBLIC_URL
        logger.info(f"🌐 WebApp URL avtomatik sozlandi: {NGROK_PUBLIC_URL}")
    else:
        logger.warning("⚠️ Ngrok URL olinmadi, lekin bot ishlayveradi.")

    # 4. Botni ishga tushirish
    logger.info("🤖 Bot ishga tushmoqda...")
    await start_bot()

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