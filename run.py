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

# Windows'da default ProactorEventLoop asyncpg bilan mos kelmaydi
# ("connection was closed in the middle of operation" / WinError 64).
# SelectorEventLoop asyncpg + SQLAlchemy uchun barqaror ishlaydi.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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
# KUNLIK FON VAZIFASI (00:00)
# ──────────────────────────────────────────
async def _reset_daily_limit() -> None:
    """Test settings ni kunlik rejimga qaytaradi (limit=1)."""
    from app.database.database import SessionLocal
    from app.database.repositories import create_or_update_test_settings

    try:
        async with SessionLocal() as session:
            await create_or_update_test_settings(session, "daily", 1)
            logger.info("✅ Kunlik limit avtomatik qaytarildi (daily mode, limit=1)")
    except Exception as e:
        logger.error(f"❌ Limit qaytarishda xato: {e}")


async def _export_and_wipe() -> None:
    """.docx hisobotni adminlarga yuborib, bazani TO'LIQ tozalaydi
    (users, attempts, answers, questions, test_settings). Audio fayllar va
    savol rasmlari o'chirilmaydi — data/archive/ ga saqlanadi.

    Xavfsizlik: wipe faqat adminlarning kamida bittasi hisobot faylini
    olgan taqdirda bajariladi (daily_export_wipe ichida kafolatlangan).
    """
    from app.services.daily_export_wipe import run_daily_export_and_wipe

    try:
        result = await run_daily_export_and_wipe()
        if result is None:
            logger.error("⚠️ Kunlik eksport+wipe bajarilmadi (fayl adminlarga yuborilmagan bo'lishi mumkin).")
        else:
            logger.info("✅ Kunlik eksport+wipe tugallandi: %s", result)
    except Exception as e:
        logger.exception("❌ Kunlik eksport+wipe xato: %s", e)
        await _notify_admins_export_failed(e)


async def _notify_admins_export_failed(error: Exception) -> None:
    """Kunlik hisobot yaratilmasa — adminlar bilsin (baza tozalanmagan)."""
    from app.services.telegram_sender import telegram_sender

    for admin_id in settings.admin_id_list:
        try:
            await telegram_sender.send_message(
                admin_id,
                "⚠️ Kunlik Word hisobot yaratilmadi. Baza tozalanmadi — "
                "ma'lumotlar saqlanib qoldi.\n"
                f"Xato: {type(error).__name__}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Admin %s ga xabar yuborilmadi: %s", admin_id, exc)


async def daily_midnight_task():
    """Har kuni mahalliy vaqt (REPORT_TIMEZONE, default Toshkent) 00:00 da:
    1. Word hisobotni adminlarga yuborib, bazani tozalaydi.
    2. Keyin limitni kunlik rejimga qaytaradi.

    Ikkalasi ketma-ket bajariladi — oldin alohida vazifalar bir vaqtda
    uyg'onib, test_settings ustida poygaga kirishardi.
    """
    from app.utils.helpers import seconds_until_local_midnight

    while True:
        seconds = seconds_until_local_midnight()
        logger.info(
            f"🗓️ Kunlik hisobot {seconds:.0f} soniyadan so'ng "
            f"({settings.report_timezone} 00:00) yuboriladi."
        )
        await asyncio.sleep(seconds)

        await _export_and_wipe()
        await _reset_daily_limit()

        # Bir xil yarim tunda ikki marta ishlamasligi uchun
        await asyncio.sleep(60)


# ──────────────────────────────────────────
# VITE FRONTEND (subprocess ichida)
# ──────────────────────────────────────────
WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")

# npm install / build uchun maksimal kutish (soniya)
NPM_INSTALL_TIMEOUT = 600
NPM_BUILD_TIMEOUT = 300


def _find_npm() -> str | None:
    import shutil

    npm_command = "npm.cmd" if sys.platform == "win32" else "npm"
    return shutil.which(npm_command)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _newest_mtime(paths: list[str]) -> float:
    """Fayllar va papkalar (ichidagi fayllar bilan) orasidagi eng yangi mtime."""
    newest = 0.0
    for path in paths:
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for name in files:
                    newest = max(newest, _mtime(os.path.join(root, name)))
        else:
            newest = max(newest, _mtime(path))
    return newest


def _npm_install_needed() -> bool:
    """node_modules yo'q yoki package.json/package-lock.json undan yangiroq."""
    # npm install har safar node_modules/.package-lock.json ni yangilaydi
    marker = os.path.join(WEBAPP_DIR, "node_modules", ".package-lock.json")
    if not os.path.exists(marker):
        return True
    manifest_mtime = _newest_mtime([
        os.path.join(WEBAPP_DIR, "package.json"),
        os.path.join(WEBAPP_DIR, "package-lock.json"),
    ])
    return manifest_mtime > _mtime(marker)


def _npm_build_needed() -> bool:
    """webapp/dist yo'q yoki manba fayllar dist dan yangiroq."""
    dist_index = os.path.join(WEBAPP_DIR, "dist", "index.html")
    if not os.path.exists(dist_index):
        return True
    sources_mtime = _newest_mtime([
        os.path.join(WEBAPP_DIR, "src"),
        os.path.join(WEBAPP_DIR, "index.html"),
        os.path.join(WEBAPP_DIR, "vite.config.ts"),
        os.path.join(WEBAPP_DIR, "package.json"),
    ])
    return sources_mtime > _mtime(dist_index)


def _run_npm(npm_path: str, args: list[str], timeout: int) -> bool:
    """npm buyrug'ini webapp/ ichida bajaradi. Muvaffaqiyatli bo'lsa True."""
    cmd = " ".join(["npm", *args])
    logger.info(f"📦 {cmd} bajarilmoqda...")
    try:
        result = subprocess.run(
            [npm_path, *args],
            cwd=WEBAPP_DIR,
            stdout=sys.stdout,
            stderr=sys.stderr,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"❌ {cmd} {timeout} soniyada tugamadi.")
        return False
    except Exception as e:
        logger.error(f"❌ {cmd} xato: {e}")
        return False

    if result.returncode != 0:
        logger.error(f"❌ {cmd} xato bilan tugadi (kod {result.returncode}).")
        return False

    logger.info(f"✅ {cmd} tugadi.")
    return True


def prepare_webapp() -> str | None:
    """Kerak bo'lsa `npm install` va `npm run build` ni avtomatik bajaradi.

    - node_modules yo'q yoki package*.json o'zgargan bo'lsa → npm install
    - webapp/dist yo'q yoki src/ o'zgargan bo'lsa → npm run build
      (FastAPI WebApp'ni webapp/dist dan xizmat qiladi — ngrok orqali
      Telegram aynan shuni ochadi)

    Qaytaradi: npm yo'li (dev server uchun) yoki npm/webapp yo'q bo'lsa None.
    """
    if not os.path.isdir(WEBAPP_DIR):
        logger.warning("⚠️ webapp/ papka topilmadi, frontend tayyorlanmadi.")
        return None

    npm_path = _find_npm()
    if not npm_path:
        logger.warning(
            "⚠️ npm topilmadi — Node.js o'rnating (https://nodejs.org). "
            "npm install / build avtomatik bajarilmadi."
        )
        return None

    logger.info(f"🔎 npm topildi: {npm_path}")

    if _npm_install_needed():
        if not _run_npm(npm_path, ["install"], NPM_INSTALL_TIMEOUT):
            return None
    else:
        logger.info("✅ npm paketlar allaqachon o'rnatilgan.")

    if _npm_build_needed():
        _run_npm(npm_path, ["run", "build"], NPM_BUILD_TIMEOUT)
    else:
        logger.info("✅ webapp/dist dolzarb.")

    return npm_path


def start_vite(npm_path: str | None) -> None:
    """Vite dev serverni alohida subprocess da ishga tushiradi."""
    if not npm_path:
        logger.warning(
            "⚠️ Vite dev-server ishga tushmaydi. webapp/dist mavjud bo'lsa "
            "FastAPI http://localhost:8000 da xizmat qiladi."
        )
        return

    try:
        subprocess.Popen(
            [npm_path, "run", "dev"],
            cwd=WEBAPP_DIR,
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
    # 0. Frontend: kerak bo'lsa npm install + build. app.main import
    # qilinishidan OLDIN bajariladi — u webapp/dist ni import paytida
    # tekshiradi. Sinxron subprocess thread'da ishlaydi (loop bloklanmaydi).
    logger.info("🌐 Frontend tayyorlanmoqda...")
    npm_path = await asyncio.to_thread(prepare_webapp)

    from app.main import app
    from app.bot.bot import bot, dp
    from app.bot.handlers import handlers_router
    from app.database.database import init_db
    from app.services.report_worker import start_report_workers, stop_report_workers
    from app.services.ai_resource_manager import setup_providers
    from app.utils.cache import cleanup_task

    # 1. DB ni ishga tushirish
    await init_db()

    # 2. AI providerlarni ro'yxatdan o'tkazish
    setup_providers()

    # 3. Report workerlarni ishga tushirish (bitta loopda — pool safe)
    start_report_workers()

    # 4. Kunlik fon vazifasi (har kuni mahalliy 00:00):
    #    .docx hisobot yuborish + bazani tozalash, keyin limitni qaytarish
    asyncio.create_task(daily_midnight_task())

    # 5. Cache cleanup task
    asyncio.create_task(cleanup_task(interval=300))  # 5 minutes

    # 6. Vite dev serverni ishga tushirish
    logger.info("🌐 Frontend (Vite) ishga tushmoqda...")
    start_vite(npm_path)

    # 7. Ngrok tunnelni ishga tushirish
    start_ngrok()

    # 8. WebApp URL ni yangilash
    if NGROK_PUBLIC_URL:
        try:
            settings.webapp_url = NGROK_PUBLIC_URL
        except Exception:
            pass
        os.environ["WEBAPP_URL"] = NGROK_PUBLIC_URL
        logger.info(f"🌐 WebApp URL avtomatik sozlandi: {NGROK_PUBLIC_URL}")
    else:
        logger.warning("⚠️ Ngrok URL olinmadi, lekin bot ishlayveradi.")

    # 9. Uvicorn serverni bitta loopda ishga tushirish (thread emas!)
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

    # 10. Bot handlerlarini ulash
    dp.include_router(handlers_router)

    # 11. Bot polling — asosiy loopni bloklab turadi
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
