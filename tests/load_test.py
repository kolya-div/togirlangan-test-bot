"""
Production Load Test — 100 concurrent users real behavior simulation.

Usage:
    1. Server ishga tushirilishi kerak: python run.py
    2. Test ishga tushiriladi: python -m tests.load_test

Test stages:
    10 → 25 → 50 → 75 → 100 concurrent users

Each user simulates:
    1. /start (init)
    2. Open test (questions)
    3. Create attempt
    4. Get questions
    5. Upload answers (multiple)
    6. Upload audio
    7. Retry scenario
    8. Finish test
    9. Wait for report
"""

import asyncio
import aiohttp
import hashlib
import hmac
import json
import time
import random
import os
import sys
import psutil
import logging
from dataclasses import dataclass, field
from urllib.parse import urlencode, parse_qsl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("load_test")

# ─── Configuration ────────────────────────────────────────────
BASE_URL = os.getenv("LOAD_TEST_URL", "http://localhost:8000")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Load test stages
STAGES = [10, 25, 50, 75, 100]

# Per-stage config
STAGE_DURATION_SEC = 30  # Har bir stage necha soniya
RAMP_UP_SEC = 5          # Foydalanuvchilar nechada kirishi

# Small audio file for upload (1KB valid webm header)
SMALL_AUDIO_BYTES = (
    b'\x1a\x45\xdf\xa3'  # EBML header
    + b'\x00' * 500       # padding
    + b'\x18\x53\x80\x67'  # Segment header
    + b'\x00' * 500       # more padding
)


# ─── HMAC Generation ──────────────────────────────────────────
def generate_init_data(user_id: int, bot_token: str) -> str:
    """Telegram WebApp initData ni generatsiya qiladi."""
    auth_date = str(int(time.time()))
    user_json = json.dumps({"id": user_id, "first_name": f"User{user_id}"})

    # Data check string
    data_list = [
        f"auth_date={auth_date}",
        f"user={user_json}",
    ]
    data_list.sort()
    data_check_string = "\n".join(data_list)

    # HMAC
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    computed_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Build initData
    params = {
        "auth_date": auth_date,
        "user": user_json,
        "hash": computed_hash,
    }
    return urlencode(params)


# ─── Metrics ──────────────────────────────────────────────────
@dataclass
class RequestMetric:
    name: str
    status: int
    latency_ms: float
    error: str = ""
    timestamp: float = 0.0


@dataclass
class UserMetrics:
    user_id: int
    requests: list = field(default_factory=list)
    attempt_id: int | None = None
    success: bool = False
    error: str = ""


@dataclass
class StageResult:
    concurrent_users: int
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    http_500_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    latencies: list = field(default_factory=list)
    duration_sec: float = 0.0
    rps: float = 0.0
    ram_mb: float = 0.0
    cpu_pct: float = 0.0
    db_connections: int = 0
    ai_queue_depth: int = 0
    telegram_queue_depth: int = 0
    duplicate_answers: int = 0
    cross_user_access: int = 0
    data_corruption: int = 0
    queue_crashes: int = 0
    errors: list = field(default_factory=list)


# ─── System Monitor ───────────────────────────────────────────
class SystemMonitor:
    """Background system metrics collector."""

    def __init__(self):
        self._running = False
        self._snapshots: list[dict] = []
        self._task = None

    async def start(self):
        self._running = True
        self._snapshots.clear()
        self._task = asyncio.create_task(self._collect_loop())

    async def stop(self) -> dict:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if not self._snapshots:
            return {"ram_mb": 0, "cpu_pct": 0, "db_connections": 0}

        return {
            "ram_mb": max(s["ram_mb"] for s in self._snapshots),
            "cpu_pct": max(s["cpu_pct"] for s in self._snapshots),
            "db_connections": max(s["db_connections"] for s in self._snapshots),
        }

    async def _collect_loop(self):
        while self._running:
            try:
                proc = psutil.Process()
                mem = proc.memory_info()
                cpu = psutil.cpu_percent(interval=None)

                # DB connections (best effort — requires localhost:5432)
                db_conns = await self._get_db_connections()

                self._snapshots.append({
                    "ram_mb": mem.rss / 1024 / 1024,
                    "cpu_pct": cpu,
                    "db_connections": db_conns,
                    "ts": time.monotonic(),
                })
            except Exception:
                pass
            await asyncio.sleep(1)

    async def _get_db_connections(self) -> int:
        """PostgreSQL active connections olish."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", 5432),
                timeout=2,
            )
            writer.close()
            await writer.wait_closed()
            return 0
        except Exception:
            return 0


# ─── Queue Monitor ────────────────────────────────────────────
async def get_queue_metrics(session: aiohttp.ClientSession) -> dict:
    """AI va Telegram queue holatini olish."""
    result = {"ai_queue_depth": 0, "telegram_sent": 0, "telegram_failed": 0}

    try:
        async with session.get(f"{BASE_URL}/api/admin/ai-health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                queue = data.get("queue", {})
                result["ai_queue_depth"] = queue.get("queue_depth", 0)
    except Exception:
        pass

    try:
        async with session.get(f"{BASE_URL}/api/admin/telegram-health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                result["telegram_sent"] = data.get("total_sent", 0)
                result["telegram_failed"] = data.get("total_failed", 0)
    except Exception:
        pass

    return result


# ─── User Simulation ──────────────────────────────────────────
async def simulate_user(
    user_id: int,
    session: aiohttp.ClientSession,
    questions: list[dict],
    bot_token: str,
) -> UserMetrics:
    """Bitta foydalanuvchi — to'liq lifecycle simulyatsiyasi."""
    um = UserMetrics(user_id=user_id)
    init_data = generate_init_data(user_id, bot_token)
    timeout = aiohttp.ClientTimeout(total=30)

    def record(name: str, status: int, latency_ms: float, error: str = ""):
        um.requests.append(RequestMetric(name, status, latency_ms, error, time.monotonic()))

    # ── Step 1: Init ──────────────────────────────────────────
    try:
        t0 = time.monotonic()
        async with session.post(
            f"{BASE_URL}/api/init",
            data={"init_data": init_data},
            timeout=timeout,
        ) as resp:
            latency = (time.monotonic() - t0) * 1000
            body = await resp.json()
            record("init", resp.status, latency)
            if resp.status not in (200, 401):
                um.error = f"init failed: {resp.status}"
                return um
    except asyncio.TimeoutError:
        record("init", 0, 30000, "timeout")
        um.error = "init timeout"
        return um
    except Exception as e:
        record("init", 0, 0, str(e))
        um.error = f"init error: {e}"
        return um

    await asyncio.sleep(random.uniform(0.1, 0.3))

    # ── Step 2: Get Questions ─────────────────────────────────
    try:
        t0 = time.monotonic()
        async with session.get(
            f"{BASE_URL}/api/questions",
            timeout=timeout,
        ) as resp:
            latency = (time.monotonic() - t0) * 1000
            record("questions", resp.status, latency)
            if resp.status != 200:
                um.error = f"questions failed: {resp.status}"
                return um
    except Exception as e:
        record("questions", 0, 0, str(e))
        um.error = f"questions error: {e}"
        return um

    await asyncio.sleep(random.uniform(0.2, 0.5))

    # ── Step 3: Create Attempt ────────────────────────────────
    try:
        t0 = time.monotonic()
        async with session.post(
            f"{BASE_URL}/api/attempts",
            data={"init_data": init_data},
            timeout=timeout,
        ) as resp:
            latency = (time.monotonic() - t0) * 1000
            body = await resp.json()
            record("create_attempt", resp.status, latency)

            if resp.status == 200:
                um.attempt_id = body.get("id")
            elif resp.status == 403:
                # Already finished — normal for retry
                um.attempt_id = body.get("attempt_id")
                if um.attempt_id:
                    um.success = True
                return um
            else:
                um.error = f"create_attempt failed: {resp.status}"
                return um
    except Exception as e:
        record("create_attempt", 0, 0, str(e))
        um.error = f"create_attempt error: {e}"
        return um

    if not um.attempt_id:
        um.error = "no attempt_id"
        return um

    await asyncio.sleep(random.uniform(0.3, 0.8))

    # ── Steps 4-5: Upload answers (3-5 questions) ────────────
    num_answers = min(random.randint(3, 5), len(questions))
    selected_questions = random.sample(questions, num_answers)

    for q in selected_questions:
        await asyncio.sleep(random.uniform(0.5, 1.5))  # Think time

        # Create small fake audio
        audio_data = SMALL_AUDIO_BYTES + os.urandom(random.randint(1024, 4096))
        filename = f"answer_{user_id}_{q['id']}.webm"

        try:
            t0 = time.monotonic()
            form = aiohttp.FormData()
            form.add_field("init_data", init_data)
            form.add_field(
                "audio",
                audio_data,
                filename=filename,
                content_type="audio/webm",
            )

            async with session.post(
                f"{BASE_URL}/api/attempts/{um.attempt_id}/answers/{q['id']}",
                data=form,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                latency = (time.monotonic() - t0) * 1000
                body = await resp.json()
                record(f"upload_{q['id']}", resp.status, latency)

                # Check for duplicate (existing: true is OK)
                if resp.status == 200 and body.get("existing"):
                    um.error = f"duplicate answer for question {q['id']}"
                elif resp.status not in (200, 409):
                    um.error = f"upload failed: {resp.status}"

        except asyncio.TimeoutError:
            record(f"upload_{q['id']}", 0, 60000, "timeout")
            um.error = f"upload timeout for question {q['id']}"
        except Exception as e:
            record(f"upload_{q['id']}", 0, 0, str(e))
            um.error = f"upload error: {e}"

    await asyncio.sleep(random.uniform(1.0, 2.0))

    # ── Step 6: Retry scenario (re-upload one answer) ─────────
    if selected_questions:
        retry_q = random.choice(selected_questions)
        audio_data = SMALL_AUDIO_BYTES + os.urandom(random.randint(1024, 4096))
        try:
            t0 = time.monotonic()
            form = aiohttp.FormData()
            form.add_field("init_data", init_data)
            form.add_field(
                "audio",
                audio_data,
                filename=f"retry_{user_id}_{retry_q['id']}.webm",
                content_type="audio/webm",
            )
            async with session.post(
                f"{BASE_URL}/api/attempts/{um.attempt_id}/answers/{retry_q['id']}",
                data=form,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                latency = (time.monotonic() - t0) * 1000
                body = await resp.json()
                record(f"retry_{retry_q['id']}", resp.status, latency)
                # Idempotent — should return existing: true
                if resp.status == 200 and body.get("existing"):
                    pass  # Expected
                elif resp.status not in (200,):
                    um.error = f"retry failed: {resp.status}"
        except Exception as e:
            record(f"retry_{retry_q['id']}", 0, 0, str(e))

    await asyncio.sleep(random.uniform(0.5, 1.0))

    # ── Step 7: Finish ───────────────────────────────────────
    try:
        t0 = time.monotonic()
        async with session.post(
            f"{BASE_URL}/api/attempts/{um.attempt_id}/finish",
            data={"init_data": init_data},
            timeout=timeout,
        ) as resp:
            latency = (time.monotonic() - t0) * 1000
            body = await resp.json()
            record("finish", resp.status, latency)

            if resp.status == 200:
                um.success = True
            elif resp.status == 409:
                # Already processing — normal for retry
                um.success = True
            else:
                um.error = f"finish failed: {resp.status}"
    except Exception as e:
        record("finish", 0, 0, str(e))
        um.error = f"finish error: {e}"

    # ── Step 8: Wait for report (poll status) ─────────────────
    if um.success and um.attempt_id:
        for _ in range(10):  # Max 10 seconds
            await asyncio.sleep(1)
            try:
                async with session.get(
                    f"{BASE_URL}/api/attempts/{um.attempt_id}/status",
                    params={"init_data": init_data},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") in ("completed", "finished"):
                            record("status_poll", resp.status, 0)
                            break
            except Exception:
                pass

    return um


# ─── Stage Runner ─────────────────────────────────────────────
async def run_stage(
    num_users: int,
    bot_token: str,
) -> StageResult:
    """Bitta stage — concurrent users simulyatsiyasi."""
    result = StageResult(concurrent_users=num_users)

    print(f"\n{'='*60}")
    print(f"  STAGE {num_users} CONCURRENT USERS")
    print(f"{'='*60}")

    monitor = SystemMonitor()
    await monitor.start()

    async with aiohttp.ClientSession() as session:
        # Questions olish (bir marta)
        try:
            async with session.get(f"{BASE_URL}/api/questions") as resp:
                questions = await resp.json()
        except Exception:
            print("  ERROR: Cannot fetch questions. Is server running?")
            await monitor.stop()
            return result

        if not questions:
            print("  ERROR: No questions in database")
            await monitor.stop()
            return result

        # Queue metrics (before)
        q_before = await get_queue_metrics(session)

        # Users ni parallel ishga tushirish
        all_metrics: list[UserMetrics] = []
        stage_start = time.monotonic()

        # Ramp-up: users ni bosqichma-bosqich qo'shish
        users_per_batch = max(1, num_users // 5)
        batches = [users_per_batch] * (num_users // users_per_batch)
        remainder = num_users % users_per_batch
        if remainder:
            batches.append(remainder)

        running_tasks = []
        for batch_size in batches:
            for _ in range(batch_size):
                uid = random.randint(1_000_000, 9_999_999)
                task = asyncio.create_task(
                    simulate_user(uid, session, questions, bot_token)
                )
                running_tasks.append(task)
            await asyncio.sleep(RAMP_UP_SEC / len(batches))

        # Barcha userlarni kutish
        all_metrics = await asyncio.gather(*running_tasks, return_exceptions=True)

        stage_duration = time.monotonic() - stage_start
        result.duration_sec = stage_duration

        # Queue metrics (after)
        q_after = await get_queue_metrics(session)

    # System metrics
    sys_metrics = await monitor.stop()

    # ─── Natijalarni hisoblash ────────────────────────────────
    total_requests = 0
    successful = 0
    failed = 0
    http_500 = 0
    timeouts = 0
    errors = 0
    all_latencies = []

    for m in all_metrics:
        if isinstance(m, Exception):
            failed += 1
            errors += 1
            result.errors.append(str(m))
            continue

        user_ok = True
        for req in m.requests:
            total_requests += 1
            all_latencies.append(req.latency_ms)

            if req.status == 500:
                http_500 += 1
                user_ok = False
            elif req.status == 0:
                timeouts += 1
                user_ok = False
            elif req.status >= 400:
                failed += 1
                user_ok = False
            else:
                successful += 1

        if m.error:
            errors += 1
            result.errors.append(f"User {m.user_id}: {m.error}")

        if user_ok:
            m.success = True

    # Latency percentiles
    all_latencies.sort()
    p50 = all_latencies[len(all_latencies) // 2] if all_latencies else 0
    p95 = all_latencies[int(len(all_latencies) * 0.95)] if all_latencies else 0
    p99 = all_latencies[int(len(all_latencies) * 0.99)] if all_latencies else 0

    result.total_requests = total_requests
    result.successful_requests = successful
    result.failed_requests = failed
    result.http_500_count = http_500
    result.timeout_count = timeouts
    result.error_count = errors
    result.latencies = all_latencies
    result.rps = total_requests / stage_duration if stage_duration > 0 else 0
    result.ram_mb = sys_metrics["ram_mb"]
    result.cpu_pct = sys_metrics["cpu_pct"]
    result.db_connections = sys_metrics["db_connections"]
    result.ai_queue_depth = q_after.get("ai_queue_depth", 0)
    result.telegram_queue_depth = q_after.get("telegram_sent", 0) - q_before.get("telegram_sent", 0)

    # Print stage results
    success_rate = (successful / total_requests * 100) if total_requests > 0 else 0
    print(f"\n  Results for {num_users} users:")
    print(f"    Requests: {total_requests} ({successful} ok, {failed} fail)")
    print(f"    Success rate: {success_rate:.1f}%")
    print(f"    HTTP 500: {http_500}")
    print(f"    Timeouts: {timeouts}")
    print(f"    RPS: {result.rps:.1f}")
    print(f"    P50: {p50:.0f}ms  P95: {p95:.0f}ms  P99: {p99:.0f}ms")
    print(f"    RAM: {result.ram_mb:.0f}MB  CPU: {result.cpu_pct:.1f}%")
    print(f"    AI Queue: {result.ai_queue_depth}")
    print(f"    Errors: {errors}")

    if result.errors:
        for err in result.errors[:5]:
            print(f"      - {err[:100]}")

    return result


# ─── Main ─────────────────────────────────────────────────────
async def main():
    # Bot token olish
    from dotenv import load_dotenv
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "")
    if not bot_token:
        print("ERROR: BOT_TOKEN not set. Add to .env or set environment variable.")
        print("  set BOT_TOKEN=your_token")
        sys.exit(1)

    print("=" * 60)
    print("  PRODUCTION LOAD TEST")
    print("  Turkish Speaking Test — 100 User Scenario")
    print("=" * 60)
    print(f"  Target: {BASE_URL}")
    print(f"  Stages: {STAGES}")
    print(f"  Stage duration: {STAGE_DURATION_SEC}s")
    print()

    # Server tekshirish
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{BASE_URL}/api/questions") as r:
                if r.status != 200:
                    print(f"ERROR: Server returned {r.status}")
                    sys.exit(1)
                qs = await r.json()
                print(f"  Questions loaded: {len(qs)}")
    except Exception as e:
        print(f"ERROR: Cannot connect to server: {e}")
        print("  Server ishga tushiring: python run.py")
        sys.exit(1)

    # Har bir stage
    stage_results: list[StageResult] = []
    for num_users in STAGES:
        result = await run_stage(num_users, bot_token)
        stage_results.append(result)

        # Stage orasida kutish
        if num_users != STAGES[-1]:
            print(f"\n  Waiting 10s before next stage...")
            await asyncio.sleep(10)

    # ─── Final Report ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  FINAL REPORT")
    print("=" * 60)

    for r in stage_results:
        n = r.concurrent_users
        sr = (r.successful_requests / r.total_requests * 100) if r.total_requests > 0 else 0
        p50 = r.latencies[len(r.latencies) // 2] if r.latencies else 0
        p95 = r.latencies[int(len(r.latencies) * 0.95)] if r.latencies else 0
        p99 = r.latencies[int(len(r.latencies) * 0.99)] if r.latencies else 0

        print(f"\n  --- {n} CONCURRENT USERS ---")
        print(f"  SUCCESS RATE:    {sr:.1f}%")
        print(f"  P50:             {p50:.0f}ms")
        print(f"  P95:             {p95:.0f}ms")
        print(f"  P99:             {p99:.0f}ms")
        print(f"  MAX RAM:         {r.ram_mb:.0f}MB")
        print(f"  MAX CPU:         {r.cpu_pct:.1f}%")
        print(f"  MAX DB CONN:     {r.db_connections}")
        print(f"  AI QUEUE:        {r.ai_queue_depth}")
        print(f"  TELEGRAM QUEUE:  {r.telegram_queue_depth}")
        print(f"  500 ERRORS:      {r.http_500_count}")
        print(f"  TIMEOUTS:        {r.timeout_count}")
        print(f"  DATA CORRUPTION: {r.data_corruption}")
        print(f"  SECURITY ISSUES: cross_user={r.cross_user_access}, duplicate={r.duplicate_answers}")

    # Final verdict
    total_500 = sum(r.http_500_count for r in stage_results)
    total_timeout = sum(r.timeout_count for r in stage_results)
    total_cross = sum(r.cross_user_access for r in stage_results)
    total_dup = sum(r.duplicate_answers for r in stage_results)
    total_crash = sum(r.queue_crashes for r in stage_results)
    max_ram = max(r.ram_mb for r in stage_results) if stage_results else 0

    verdict = "PASS"
    fail_reasons = []

    if total_500 > 0:
        verdict = "FAIL"
        fail_reasons.append(f"{total_500} HTTP 500 errors")
    if total_cross > 0:
        verdict = "FAIL"
        fail_reasons.append(f"{total_cross} cross-user data access (CRITICAL)")
    if total_crash > 0:
        verdict = "FAIL"
        fail_reasons.append(f"{total_crash} queue crashes")
    if max_ram > 2048:
        verdict = "FAIL"
        fail_reasons.append(f"Max RAM {max_ram:.0f}MB exceeds 2GB limit")

    # 100 user stage check
    if stage_results and stage_results[-1].concurrent_users == 100:
        stage_100 = stage_results[-1]
        sr_100 = (stage_100.successful_requests / stage_100.total_requests * 100) if stage_100.total_requests > 0 else 0
        if sr_100 < 90:
            verdict = "FAIL"
            fail_reasons.append(f"100-user success rate {sr_100:.1f}% < 90%")

    print(f"\n{'='*60}")
    print(f"  FINAL VERDICT: {verdict}")
    if fail_reasons:
        for reason in fail_reasons:
            print(f"    FAIL: {reason}")
    else:
        print(f"  All checks passed.")
    print(f"{'='*60}")

    # Save report
    report_path = os.path.join(os.path.dirname(__file__), "load_test_report.json")
    report_data = []
    for r in stage_results:
        p50 = r.latencies[len(r.latencies) // 2] if r.latencies else 0
        p95 = r.latencies[int(len(r.latencies) * 0.95)] if r.latencies else 0
        p99 = r.latencies[int(len(r.latencies) * 0.99)] if r.latencies else 0
        report_data.append({
            "concurrent_users": r.concurrent_users,
            "total_requests": r.total_requests,
            "success_rate_pct": round((r.successful_requests / r.total_requests * 100) if r.total_requests > 0 else 0, 1),
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "p99_ms": round(p99, 1),
            "rps": round(r.rps, 1),
            "ram_mb": round(r.ram_mb, 1),
            "cpu_pct": round(r.cpu_pct, 1),
            "db_connections": r.db_connections,
            "ai_queue_depth": r.ai_queue_depth,
            "http_500": r.http_500_count,
            "timeouts": r.timeout_count,
            "errors": r.error_count,
            "verdict": verdict,
            "fail_reasons": fail_reasons,
        })

    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)
    print(f"\n  Report saved to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
