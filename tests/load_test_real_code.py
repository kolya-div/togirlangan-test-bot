"""
REAL-KOD yuk sinovi (70 / 100 user) — 'Real kod + mock tashqi' yondashuvi.

QA MRADI: 70-100 foydalanuvchi bir vaqtda test BOSHLASA (DB: attempt+answer
yozish) va bir vaqtda TUGATSa (Telegram hisobot yuborish) tizim barqaror
ishlashini o'lchash. Bu sinov REAL kod qatlamlarini ishlatadi:
  - Real API handler'lar (create_attempt, upload_answer, finish_attempt)
    -> real DB yozish (NullPool + max_connections stress)
  - Real report_worker navbati + _process_attempt_and_report_inner
  - Real _send_with_retry + GLOBAL Telegram limiter (25 msg/s)
Faqat tashqi qaramliklar mock qilinadi (holda real AI/real qabul qiluvchi
yo'qligi tufayli test ishlamas edi):
  - transcribe_audio / evaluate_answer -> qaytariladigan qiymat
  - Telegram NETWORK yetkazish -> real limiter gate orqali qayd qilish
    (haqiqiy 100 ta Telegram chat_id yo'q, shuning uchun real tarmoq emas)
"""

import asyncio
import hashlib
import hmac
import io
import json
import logging
import time

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s | %(message)s")
logging.getLogger("app").setLevel(logging.WARNING)

from starlette.datastructures import UploadFile  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import telegram_rate_limiter as trl  # noqa: E402
from app.services import report_worker  # noqa: E402
from app.database.database import SessionLocal  # noqa: E402
from app.database.models import User, Question  # noqa: E402
from app.api.routes import create_attempt, upload_answer, finish_attempt  # noqa: E402


def make_init_data(user_id: int) -> str:
    """Telegram WebApp initData strukturasi bilan valid imzo (test uchun)."""
    user = {"id": user_id, "first_name": "Test", "username": "test_user"}
    params = {"user": json.dumps(user, separators=(",", ":")),
              "auth_date": str(int(time.time()))}
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(),
                          hashlib.sha256).digest()
    params["hash"] = hmac.new(secret_key, check_string.encode(),
                              hashlib.sha256).hexdigest()
    return "&".join(f"{k}={v}" for k, v in params.items())

# ─────────────────────────────────────────────────────────────
# GLOBAL BO'SH KONTEYNERLAR (mock tashqi uchun)
# ─────────────────────────────────────────────────────────────
SEND_LOG = []          # (method_name, monotonic_time)
ERRORS = []            # (phase, message)
_lock = asyncio.Lock()


async def _seed_users(session, n_users: int, start_id: int) -> None:
    for i in range(n_users):
        tg = start_id + i
        u = User(telegram_id=tg, username=f"load_{tg}", full_name=f"Load {tg}",
                 is_registered=True, is_admin=False)
        session.add(u)
    await session.commit()


async def _seed_questions(session, n_q: int) -> list[int]:
    qids = []
    for i in range(1, n_q + 1):
        q = Question(section="TEST", order_number=i,
                     text=f"Savol {i}", preparation_seconds=10, answer_seconds=30,
                     max_points=10)
        session.add(q)
        await session.commit()
        await session.refresh(q)
        qids.append(q.id)
    return qids


def _install_telegram_mock() -> None:
    """`aiogram.Bot.__call__` ni real limiter gate + qayd qilish bilan qoplaydi.

    Real tarmoqqa yetkazmaydi (100 ta real chat_id yo'q), LEKIN haqiqiy
    global 25 msg/s limiter yoki pacing behavior-ni saqlaydi — shuning uchun
    429/thrashing xavfi spektri REAL o'lchanadi. `_send_with_retry` tinimsiz
    ishlaydi (hech qanday xato bermaydi -> retry lozim bo'lmaydi).
    """
    import aiogram

    async def _mocked_call(self, method, request_timeout=None):
        await trl.wait_send_gate()
        async with _lock:
            SEND_LOG.append((type(method).__name__, time.monotonic()))
        return method

    aiogram.Bot.__call__ = _mocked_call


def _install_ai_mocks() -> None:
    import app.services.report_service as rs

    async def _t(audio_path):
        return "Men bugun yangi narsa o'rgandim va bu juda foydali bo'ldi."

    async def _e(question_text, transcript):
        return {
            "score": 80,
            "corrected_text": transcript,
            "is_grammatically_correct": True,
            "mistakes": [],
            "scores": {"grammar": 8, "vocab": 8, "fluency": 8, "pronunciation": 8},
            "score_reasons": ["to'g'ri tuzilgan gap"],
            "strengths": ["ravon gap"],
            "feedback_uz": "Yaxshi!",
            "feedback_tr": "Guzel!",
        }

    rs.transcribe_audio = _t
    rs.evaluate_answer = _e


def _pct():
    from app.utils.helpers import utcnow
    return utcnow()


# ─────────────────────────────────────────────────────────────
# ASOSIY SINOV
# ─────────────────────────────────────────────────────────────
async def run_load(n_users: int, n_questions: int, seed_base: int):
    SEND_LOG.clear()
    ERRORS.clear()

    trl.install_bot_throttle()          # real limiter
    _install_telegram_mock()            # real limiter + qayd (network emas)
    _install_ai_mocks()                 # AI mock
    report_worker.start_report_workers()  # real worker navbati (in-process)

    # ── SEED ──
    qids = []
    async with SessionLocal() as s:
        qids = await _seed_questions(s, n_questions)
    async with SessionLocal() as s:
        await _seed_users(s, n_users, seed_base)
    print(f"[seed] {n_users} user, {len(qids)} savol tayyor")

    telegram_ids = [seed_base + i for i in range(n_users)]

    # ── 1) BIR VAQTDA TEST BOSHLASH (DB stress: attempt+answer yozish) ──
    t_start = time.monotonic()

    async def one_user(tg):
        try:
            r = await create_attempt(init_data=make_init_data(tg), chat_id=tg)
            aid = r["id"]
            for qid in qids:
                # upload_answer real audio fayl yozadi(Answer+file)
                files = UploadFile(
                    filename="a.webm",
                    file=io.BytesIO(b"\x00" * 2048),
                    headers=None,
                )
                await upload_answer(aid, qid, files)
            return aid, None
        except Exception as e:  # noqa: BLE001
            ERRORS.append(("boshlash", f"tg={tg} {type(e).__name__}: {e}"))
            return None, e

    # Barrier: barcha foydalanuvchilar bir vaqtda attempt yaratadi
    results = await asyncio.gather(*(one_user(tg) for tg in telegram_ids))
    attempt_ids = [r for r, e in results if r is not None]
    failed_start = n_users - len(attempt_ids)
    print(f"[boshlash] {len(attempt_ids)}/{n_users} attempt yaratildi, "
          f"boshlashda xato: {failed_start}")

    # ── 2) BIR VAQTDA TUGATISH (finish -> _send_telegram + enqueue_report) ──

    async def one_finish(aid):
        try:
            await finish_attempt(aid)
            return aid, None
        except Exception as e:  # noqa: BLE001
            ERRORS.append(("tugatish", f"aid={aid} {type(e).__name__}: {e}"))
            return aid, e

    fin = await asyncio.gather(*(one_finish(aid) for aid in attempt_ids))
    finished_calls = sum(1 for a, e in fin if e is None)

    # ── 3) HISOBOT NAVBATINI KUTISH ──
    queue = report_worker._ensure_queue()
    try:
        await asyncio.wait_for(queue.join(), timeout=240)
        processed = True
    except asyncio.TimeoutError:
        processed = False
        ERRORS.append(("hisobot", "navbat 240s ichida tugamadi"))

    t_end = time.monotonic()
    elapsed = t_end - t_start

    # ── Natijalar / DB holati ──
    full_success = 0
    not_finished = 0
    async with SessionLocal() as s:
        from sqlalchemy import select
        from app.database.models import TestAttempt, User
        uids = (await s.execute(select(User.id)))
        # faqat shu sinovdagi userlarga tegishli attempts
        tg_ids = telegram_ids
        rows = (await s.execute(
            select(TestAttempt, User)
            .join(User, TestAttempt.user_id == User.id)
            .where(User.telegram_id.in_(tg_ids))
        )).all()
        status_map = {}
        for attempt, user in rows:
            status_map[attempt.id] = attempt.status
        for aid in attempt_ids:
            if status_map.get(aid) == "finished":
                full_success += 1
            else:
                not_finished += 1

    # Telegram limiter samaradorligi
    n_sends = len(SEND_LOG)
    eff_rate = n_sends / elapsed if elapsed > 0 else 0
    # qo'shimcha: faqat yuborish boshlangandan keyingi o'lchash
    if SEND_LOG:
        t0 = SEND_LOG[0][1]
        window = t_end - t0
    else:
        window = 0
    gate_rate = (n_sends / window) if window > 0 else 0.0

    print("\n" + "=" * 64)
    print(f"  NATIJA: {n_users} USER")
    print("=" * 64)
    print(f"  Umumiy vaqt              : {elapsed:.1f} s")
    print(f"  Boshlashda xato          : {failed_start}")
    print(f"  finish chaqiruvlari      : {finished_calls}/{len(attempt_ids)}")
    print(f"  Hisobot navbati          : {'tugadi ✅' if processed else 'TUGAИMADI ❌'}")
    print(f"  DB 'finished' status     : {full_success}/{n_users}  (to'liq muvaffaqiyat)")
    print(f"  DB 'finished' bo'lmagan  : {not_finished}")
    print(f"  Telegram yuborishlar soni: {n_sends}")
    print(f"  Global limiter o'lchami  : {trl.TELEGRAM_RATE_PER_SECOND} msg/s")
    print(f"  Yuborish tezligi (real)  : {gate_rate:.2f} msg/s")
    print(f"  Muvaffaqiyat foizi       : {100 * full_success / n_users:.1f}%")
    if ERRORS:
        print("\n  XATOLAR:")
        for ph, m in ERRORS[:25]:
            print(f"    [{ph}] {m}")
        print(f"    ... jami {len(ERRORS)} xato")
    else:
        print("\n  Xatolar: YO'Q")
    print("=" * 64)
    return {
        "n": n_users, "elapsed": elapsed, "full_success": full_success,
        "not_finished": not_finished, "n_sends": n_sends,
        "gate_rate": gate_rate, "errors": len(ERRORS),
        "failed_start": failed_start,
    }


async def main():
    import sys
    n_q = 6
    # Qo'lda sinov: python load_test_real_code.py <N> <seed_base>
    # (smoke uchun kichik N, keyin to'liq 70/100)
    if len(sys.argv) >= 2:
        n = int(sys.argv[1])
        base = int(sys.argv[2]) if len(sys.argv) >= 3 else 1990000
        r = await run_load(n, n_q, seed_base=base)
        print(">>> Natija:", r)
        return
    print("\n############ 1-QATLAM: 70 USER ############")
    r70 = await run_load(70, n_q, seed_base=1007000)
    print("\n\n############ 2-QATLAM: 100 USER ############")
    r100 = await run_load(100, n_q, seed_base=1010000)
    print("\n\n>>> 70-user:", r70)
    print(">>> 100-user:", r100)


if __name__ == "__main__":
    asyncio.run(main())
