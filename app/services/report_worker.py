"""
Report worker — hisobotlarni navbatdan qayta ishlaydi.

DEPLOYMENT CONSTRAINT:
Bu modul faqat bitta process/worker bilan ishlaydi.
asyncio.Queue in-memory — boshqa processdagi workerlar navbatni ko'rmaydi.

Agar uvicorn --workers N (N>1) ishlatsangiz:
- Har bir worker o'z navbatini yaratadi
- Joblar faqat yaratilgan workerda qayta ishlanadi
- Boshqa workerlar bu joblarni ko'rmaydi
- Natija: xabarlar yuborilmaydi, hisobotlar yo'qoladi

Xavfsizlik:
- run.py:130 da workers=1 qat'iy belgilangan
- Dockerfile: CMD ["python", "run.py"] — faqat bitta process
- docker-compose.yml: workers konfiguratsiyasi yo'q

Agar multi-worker kerak bo'lsa: Redis-backed queue talab qilinadi.
"""

import asyncio
import logging
from typing import Callable, Awaitable

from app.services.job_tracker import job_tracker, JobStatus

logger = logging.getLogger(__name__)

# Overridable for testing — swap this to inject fake processing
_process_fn: Callable[[int], Awaitable[None]] | None = None


def _get_process_fn():
    global _process_fn
    if _process_fn is not None:
        return _process_fn
    from app.services.report_service import _process_attempt_and_report_inner
    return _process_attempt_and_report_inner

# Worker soni: Gemini 15 RPM + Groq 30 RPM = ~45 RPM jami.
# Har bir worker ~2 AI call (transcription + eval) = ~10s/job.
# 5 worker = bir vaqtda 5 ta job, ~50s per batch = ~60 jobs/min.
# 100 user finish qilsa: 100/60 = ~1.7 daqiqa — yetarli.
REPORT_WORKERS = 5

# Queue xavfsizlik chegarasi — 100+ user uchun yetarli.
# 500 ta job: 5 worker × 2min/job batch = 25 jobs/min → 500/25 = 20 daqiqa buffer.
MAX_QUEUE_SIZE = 500

# Queue to'lib ketganida reject qilish vaqti
ENQUEUE_TIMEOUT = 5.0

# Queue to'lib ketganida qayta urinishlar soni
MAX_RETRY_ENQUEUE = 3
RETRY_ENQUEUE_DELAY = 10.0  # soniya

_report_queue: asyncio.Queue[int] | None = None
_report_worker_tasks: list[asyncio.Task] = []
_started = False
_stopping = False
_pending_attempts: set[int] = set()
_admin_queue_alerted = False  # Birinchi marta xabar berildi


def _ensure_queue() -> asyncio.Queue[int]:
    global _report_queue
    if _report_queue is None:
        _report_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
    return _report_queue


async def _notify_admin_queue_full(queue) -> None:
    """Adminlarga queue to'ligini xabar beradi (birinchi marta)."""
    global _admin_queue_alerted
    if _admin_queue_alerted:
        return
    _admin_queue_alerted = True
    try:
        from app.config import settings
        from app.services.telegram_sender import telegram_sender
        admin_ids = settings.admin_id_list
        for admin_id in admin_ids:
            await telegram_sender.send_message(
                admin_id,
                f"⚠️ <b>Hisobot navbati to'liq!</b>\n\n"
                f"Navbat: {queue.qsize()}/{MAX_QUEUE_SIZE}\n"
                f"Yangi hisobotlar vaqtincha kutib turiladi.\n"
                f"Queue bo'shaganda avtomatik qayta ishlanadi.",
            )
    except Exception as e:
        logger.warning("Admin xabar yuborilmadi: %s", e)


async def enqueue_report(attempt_id: int, total_answers: int = 0) -> bool:
    """
    Hisobotni qayta ishlash navbatiga qo'shadi.

    Queue to'lib ketganida:
    - MAX_RETRY_ENQUEUE marta RETRY_ENQUEUE_DELAY soniya kutib qayta urinadi
    - Barcha urinishlar muvaffaqiyatsiz bo'lsa — False qaytaradi
    - Adminlarga xabar beriladi (birinchi marta to'lganda)

    Returns:
        True — muvaffaqiyatli qo'shildi
        False — barcha urinishlar muvaffaqiyatsiz
    """
    if attempt_id in _pending_attempts:
        logger.info("Attempt #%s allaqachon navbatda, qo'shilmadi", attempt_id)
        return False

    queue = _ensure_queue()

    # Queue to'lib ketganini tekshirish + retry
    if queue.full():
        await _notify_admin_queue_full(queue)
        for retry in range(MAX_RETRY_ENQUEUE):
            logger.warning(
                "Queue to'liq (%s/%s), attempt #%s — qayta urinish %s/%s (%ss kutish)",
                queue.qsize(), MAX_QUEUE_SIZE, attempt_id,
                retry + 1, MAX_RETRY_ENQUEUE, RETRY_ENQUEUE_DELAY,
            )
            await asyncio.sleep(RETRY_ENQUEUE_DELAY)
            if not queue.full():
                break
        else:
            logger.error(
                "Queue to'liq (%s/%s), attempt #%s — barcha %s urinishlar muvaffaqiyatsiz",
                queue.qsize(), MAX_QUEUE_SIZE, attempt_id, MAX_RETRY_ENQUEUE,
            )
            return False

    _pending_attempts.add(attempt_id)

    # Job tracker'ga qo'shish
    await job_tracker.enqueue(attempt_id, total_answers)

    try:
        await asyncio.wait_for(queue.put(attempt_id), timeout=ENQUEUE_TIMEOUT)
        logger.info(
            "Attempt #%s navbatga qo'shildi (queue depth: %s)",
            attempt_id, queue.qsize(),
        )
        return True
    except asyncio.TimeoutError:
        _pending_attempts.discard(attempt_id)
        logger.error("Queue timeout — attempt #%s qo'shilmadi", attempt_id)
        return False


async def _report_worker(idx: int) -> None:
    """Bitta ishchi: navbatdan attempt_id olib, hisobotni qayta ishlaydi."""
    queue = _ensure_queue()
    logger.info("Hisobot ishchisi #%s boshladi", idx)

    process_fn = _get_process_fn()

    while True:
        attempt_id = await queue.get()
        try:
            # Job status: queued → processing
            await job_tracker.start_processing(attempt_id)

            logger.info("Ishchi #%s: attempt #%s qayta ishlash boshlandi", idx, attempt_id)
            await process_fn(attempt_id)

            # Job status: → completed
            await job_tracker.complete(attempt_id)
            logger.info("Ishchi #%s: attempt #%s tugadi", idx, attempt_id)

        except Exception as e:
            # Job status: → failed
            await job_tracker.fail(attempt_id, str(e))
            logger.exception(
                "Ishchi #%s: attempt #%s xato: %s", idx, attempt_id, e
            )
        finally:
            _pending_attempts.discard(attempt_id)
            queue.task_done()

            # Queue bo'shaganida admin alert'ni tiklash
            global _admin_queue_alerted
            if _admin_queue_alerted and queue.qsize() < MAX_QUEUE_SIZE // 2:
                _admin_queue_alerted = False

            # Agar to'xtatish buyrug'i keldi va navbat bo'sh — worker to'xtaydi
            if _stopping and queue.empty():
                break


def start_report_workers() -> None:
    """Navbat ishchilarini joriy event loopda ishga tushiradi."""
    global _started
    if _started:
        return
    _started = True
    loop = asyncio.get_running_loop()
    for i in range(REPORT_WORKERS):
        _report_worker_tasks.append(loop.create_task(_report_worker(i)))
    logger.info("%s ta hisobot ishchisi ishga tushdi", REPORT_WORKERS)


async def stop_report_workers() -> None:
    """Ishchilarni xotirjam to'xtatadi."""
    global _started, _stopping
    _stopping = True
    _started = False

    queue = _report_queue
    if queue is not None:
        try:
            await asyncio.wait_for(queue.join(), timeout=60)
        except asyncio.TimeoutError:
            logger.warning("Report workers did not finish in 60s, cancelling")

    for task in _report_worker_tasks:
        if not task.done():
            task.cancel()
    _report_worker_tasks.clear()
