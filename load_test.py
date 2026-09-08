"""
Yuklama (load) sinovi — imtihon vaqtidagi eng yomon holni simulyatsiya qiladi.

Simulyatsiya:
  - `${N}` ta foydalanuvchi BIR VAQTDA `create_attempt` chaqiradi.
  - Keyin ularning har biri BIR VAQTDA 2 tadan `upload_answer` yuboradi
    (jami 2*N ta parallel upload).

O'lchovlar:
  (a) har bir faza qancha vaqt oldi;
  (b) nechta so'rov muvaffaqiyatli / nechtasi xato (too many clients,
      timeout) bo'ldi — javoblardan ham, server log'idan ham.

Ishlatilish:
    python load_test.py [foydalanuvchilar_soni=100]

Muhim:
  - TEST bazasida (production emas) ishlaydi: `turkish_bot_test` bazasini
    tozalab, uvicorn'ni shu bazaga yo'naltirib ochadi va tugagach yopadi.
  - Bazaning nomi "_test" bilan tugashini talab qiladi (production DB'ga
    tegmaslik kafolati).
  - Chiqishda DB `max_connections` qiymati ham ko'rsatiladi — natijalar
    shu limitga nisbatan talqin qilinadi.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import hashlib
import hmac

WORKDIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORKDIR)

PORT = 8010
BASE_URL = f"http://127.0.0.1:{PORT}"

TEST_DB_URL = os.getenv(
    "LOAD_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:123@localhost:5432/turkish_bot_test",
)
TEST_DB_SYNC_URL = TEST_DB_URL.replace("+asyncpg", "")

import asyncpg  # noqa: E402
import httpx  # noqa: E402

from app.config import settings  # noqa: E402


def make_init_data(user_id: int) -> str:
    """Telegram WebApp initData — valid imzo (bot_token bilan)."""
    user = {"id": user_id, "first_name": "Load", "username": f"load_{user_id}"}
    params = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret_key = hmac.new(
        b"WebAppData", settings.bot_token.encode(), hashlib.sha256
    ).digest()
    params["hash"] = hmac.new(
        secret_key, check_string.encode(), hashlib.sha256
    ).hexdigest()
    return "&".join(f"{k}={v}" for k, v in sorted(params.items()))


def _db_name(url: str) -> str:
    return url.split("?", 1)[0].rsplit("/", 1)[-1]


async def _reset_test_db() -> None:
    name = _db_name(TEST_DB_SYNC_URL)
    if not name.endswith("_test"):
        raise RuntimeError(
            f"Xavfsizlik: LOAD_TEST_DATABASE_URL test bazasiga ishora "
            f"qilmayapti (database='{name}'). '_test' bilan tugashi shart."
        )
    conn = await asyncpg.connect(TEST_DB_SYNC_URL)
    try:
        await conn.execute(
            "TRUNCATE answers, test_attempts, users, questions "
            "RESTART IDENTITY CASCADE"
        )
    except Exception:
        await conn.execute("DROP TABLE IF EXISTS answers CASCADE")
        await conn.execute("DROP TABLE IF EXISTS test_attempts CASCADE")
        await conn.execute("DROP TABLE IF EXISTS questions CASCADE")
        await conn.execute("DROP TABLE IF EXISTS users CASCADE")
    finally:
        await conn.close()


async def _insert_question() -> int:
    conn = await asyncpg.connect(TEST_DB_SYNC_URL)
    try:
        return await conn.fetchval(
            "INSERT INTO questions (section, order_number, text, "
            "preparation_seconds, answer_seconds, is_active, created_at) "
            "VALUES ($1, $2, $3, $4, $5, TRUE, now()) RETURNING id",
            "A", 1, "Load test savoli", 10, 30,
        )
    finally:
        await conn.close()


async def _db_max_connections() -> int:
    conn = await asyncpg.connect(TEST_DB_SYNC_URL)
    try:
        return await conn.fetchval("SHOW max_connections")
    finally:
        await conn.close()


async def _wait_ready(client: httpx.AsyncClient, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = await client.get("/api/questions")
            if r.status_code == 200:
                return
            last = r.status_code
        except Exception as e:
            last = type(e).__name__
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Server tayyor bo'lmadi (oxirgi: {last})")


def _print_report(title: str, results: list, duration: float) -> None:
    """results elementlari: (status, error_kind, elapsed_ms).

    status — HTTP kod (200/4xx/5xx); error_kind — client darajasidagi xato.
    """
    total = len(results)
    ok = sum(1 for s, e, _ in results if s is not None and 200 <= s < 300)
    err = total - ok
    codes: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for s, e, _ in results:
        if s is not None:
            codes[f"HTTP {s}"] = codes.get(f"HTTP {s}", 0) + 1
        elif e:
            kinds[e] = kinds.get(e, 0) + 1
    lat_ms = [ms for _, _, ms in results if ms is not None]
    p50 = sorted(lat_ms)[len(lat_ms) // 2] if lat_ms else 0

    print(f"\n--- {title} ---")
    print(f"  Jami: {total} | Muvaffaqiyatli: {ok} | Xato: {err}")
    if duration is not None:
        print(f"  Davomiylik: {duration:.2f}s | o'rtacha kechikish: "
              f"{sum(lat_ms)/len(lat_ms):.0f}ms | P50: {p50:.0f}ms" if lat_ms else "")
    if codes:
        print(f"  HTTP kodlar: {codes}")
    if kinds:
        print(f"  Client xatolar: {kinds}")


async def main() -> None:
    n_users = int(sys.argv[1]) if len(sys.argv) > 1 else 100

    name = _db_name(TEST_DB_SYNC_URL)
    if not name.endswith("_test"):
        raise RuntimeError(f"Xavfsizlik: bazaning nomi '_test' emas: '{name}'")

    mc = await _db_max_connections()

    print("=" * 66)
    print(f"  YUKLAMA SINOVI | foydalanuvchilar: {n_users}")
    print(f"  Test bazasi : {TEST_DB_SYNC_URL}")
    print(f"  DB max_connections: {mc}")
    print("=" * 66)

    await _reset_test_db()

    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DB_URL
    log_path = os.path.join(os.environ.get("TEMP", WORKDIR), "load_test_server.log")
    server_log = open(log_path, "w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "info"],
        cwd=WORKDIR,
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )

    try:
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_connections=400, max_keepalive_connections=400),
        ) as client:
            print("Server tayyorlanmoqda...")
            await _wait_ready(client)
            qid = await _insert_question()
            print(f"Server tayyor. Savol_id: {qid}\n")

            init_datas = [make_init_data(20000 + i) for i in range(n_users)]

            async def create_one(data: str):
                t0 = time.perf_counter()
                try:
                    r = await client.post("/api/attempts", data={"init_data": data})
                    ms = (time.perf_counter() - t0) * 1000
                    result = (r.status_code, None, ms)
                    attempt_id = None
                    if 200 <= r.status_code < 300:
                        attempt_id = r.json().get("id")
                    return result, attempt_id
                except httpx.HTTPError as e:
                    ms = (time.perf_counter() - t0) * 1000
                    kind = type(e).__name__
                    return (None, kind, ms), None

            t0 = time.perf_counter()
            create_out = await asyncio.gather(*(create_one(d) for d in init_datas))
            create_duration = time.perf_counter() - t0
            create_results = [c for c, _ in create_out]
            attempt_ids = [a for _, a in create_out if a is not None]

            _print_report(f"create_attempt ({n_users} parallel)", create_results, create_duration)

            # ── Fazali 2: upload_answer (har attemptga 2 ta = 2*N parallel)
            audio = b"x" * 4096
            files = {"audio": ("ans.webm", audio, "audio/webm")}

            async def upload_one(aid: int):
                t0 = time.perf_counter()
                try:
                    r = await client.post(
                        f"/api/attempts/{aid}/answers/{qid}", files=files
                    )
                    ms = (time.perf_counter() - t0) * 1000
                    return (r.status_code, None, ms)
                except httpx.HTTPError as e:
                    ms = (time.perf_counter() - t0) * 1000
                    return (None, type(e).__name__, ms)

            # Har attempt uchun 2 ta parallel upload
            tasks = [upload_one(aid) for aid in attempt_ids for _ in range(2)]
            n_upload = len(tasks)

            t0 = time.perf_counter()
            upload_results = await asyncio.gather(*tasks)
            upload_duration = time.perf_counter() - t0

            _print_report(f"upload_answer (jami {n_upload} parallel)",
                          upload_results, upload_duration)

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        server_log.close()

        print("\n" + "=" * 66)
        print("  SERVER LOG TAHLILI (too many clients / timeout)   ")
        print("=" * 66)
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            pats = ["too many clients", "connection refused", "TimeoutError",
                    "OperationalError", "Traceback"]
            for p in pats:
                c = text.lower().count(p.lower())
                if c:
                    print(f"  '{p}': {c} marta")
            if "too many clients" in text.lower():
                print("\n  ⚠️ DB 'too many clients' aniqlandi — connection limitiga yetilgan.")
        except FileNotFoundError:
            print("  (server log topilmadi)")


if __name__ == "__main__":
    asyncio.run(main())
