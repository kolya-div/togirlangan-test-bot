"""
100-user stress test — concurrent finish + report processing.

Usage:
    python -m tests.stress_report_queue

Metrics:
    - queue depth over time
    - processing time per job
    - failed jobs
    - retry count
    - provider errors
    - memory usage
"""

import asyncio
import time
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch
from app.services.report_worker import (
    _report_queue, _ensure_queue, enqueue_report, start_report_workers,
    stop_report_workers, REPORT_WORKERS, MAX_QUEUE_SIZE,
)
from app.services.job_tracker import job_tracker, JobStatus


# ─── Fake data ────────────────────────────────────────────────
class FakeAnswer:
    def __init__(self, aid, qid):
        self.id = aid
        self.question_id = qid
        self.audio_path = None
        self.transcript = None
        self.score = None
        self.feedback = None


class FakeQuestion:
    def __init__(self, qid, section, order, max_points=15):
        self.id = qid
        self.section = section
        self.order_number = order
        self.max_points = max_points
        self.text = f"Test question {qid}"


class FakeAttempt:
    def __init__(self, aid, uid):
        self.id = aid
        self.user_id = uid
        self.score = None
        self.level = None
        self.status = "processing"


class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.telegram_id = 100000 + uid


# ─── Mock processing ──────────────────────────────────────────
ProcessingTimes = []
ProcessedJobs = []
FailedJobs = []
RetryCounts = []


async def fake_process_attempt(attempt_id: int):
    """Fake report processing — simulates AI calls."""
    # Simulate transcription + evaluation time
    proc_time = random.uniform(0.1, 0.5)  # 100-500ms for test
    ProcessingTimes.append(proc_time)
    await asyncio.sleep(proc_time)
    ProcessedJobs.append(attempt_id)


# ─── Stress test ──────────────────────────────────────────────
async def run_stress_test(num_users: int = 100):
    print(f"\n{'='*60}")
    print(f"STRESS TEST: {num_users} concurrent finish requests")
    print(f"{'='*60}")
    print(f"Workers: {REPORT_WORKERS}")
    print(f"Max queue size: {MAX_QUEUE_SIZE}")
    print(f"Provider limits: Gemini 15RPM, Groq 30RPM")
    print()

    start_time = time.monotonic()

    # Track metrics
    enqueue_times = []
    enqueue_results = {"success": 0, "queue_full": 0, "duplicate": 0}

    # Simulate concurrent finish requests
    tasks = []
    for i in range(num_users):
        attempt_id = 1000 + i
        tasks.append(_simulate_finish(attempt_id, i, enqueue_times, enqueue_results))

    # Launch all concurrently
    print(f"Launching {num_users} concurrent finish requests...")
    await asyncio.gather(*tasks)

    enqueue_done = time.monotonic()
    print(f"\nAll {num_users} requests enqueued in {enqueue_done - start_time:.2f}s")
    print(f"  Success: {enqueue_results['success']}")
    print(f"  Queue full: {enqueue_results['queue_full']}")
    print(f"  Duplicate: {enqueue_results['duplicate']}")

    # Monitor queue drain
    print(f"\nMonitoring queue drain...")
    queue_depths = []
    while True:
        stats = await job_tracker.get_stats()
        depth = stats["queue_depth"]
        processing = stats["processing"]
        queue_depths.append(depth)

        if depth == 0 and processing == 0:
            break
        await asyncio.sleep(0.1)

    end_time = time.monotonic()
    total_time = end_time - start_time

    # ─── Results ───────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Processed jobs: {len(ProcessedJobs)}/{num_users}")
    print(f"Failed jobs: {len(FailedJobs)}")
    print(f"Processing times: min={min(ProcessingTimes):.3f}s max={max(ProcessingTimes):.3f}s avg={sum(ProcessingTimes)/len(ProcessingTimes):.3f}s")

    stats = await job_tracker.get_stats()
    print(f"\nJob Tracker Stats:")
    print(f"  Total enqueued: {stats['total_enqueued']}")
    print(f"  Total completed: {stats['total_completed']}")
    print(f"  Total failed: {stats['total_failed']}")
    print(f"  Total retries: {stats['total_retries']}")

    # Throughput
    if total_time > 0:
        throughput = len(ProcessedJobs) / total_time
        print(f"\nThroughput: {throughput:.1f} jobs/second")
        print(f"Avg time per batch: {total_time / max(1, len(ProcessedJobs) // REPORT_WORKERS):.2f}s")

    # Queue depth over time
    if queue_depths:
        print(f"\nQueue depth: max={max(queue_depths)}, avg={sum(queue_depths)/len(queue_depths):.1f}")

    # Memory estimate
    job_memory = len(ProcessedJobs) * 0.001  # ~1KB per job
    print(f"Estimated job memory: {job_memory:.1f}KB")


async def _simulate_finish(attempt_id: int, idx: int, enqueue_times, enqueue_results):
    """Simulate a single finish request."""
    await asyncio.sleep(random.uniform(0, 0.05))  # Small jitter

    start = time.monotonic()
    result = await enqueue_report(attempt_id, total_answers=5)
    elapsed = time.monotonic() - start

    enqueue_times.append(elapsed)
    if result:
        enqueue_results["success"] += 1
    else:
        enqueue_results["queue_full"] += 1


# ─── Monkey-patch for test ────────────────────────────────────
def setup_mocks():
    """Replace real report processing with fake."""
    import app.services.report_worker as worker_mod

    # Set the overridable function reference
    worker_mod._process_fn = fake_process_attempt


async def main():
    setup_mocks()

    # Start workers
    start_report_workers()
    await asyncio.sleep(0.1)  # Let workers start

    try:
        await run_stress_test(num_users=100)
    finally:
        await stop_report_workers()


if __name__ == "__main__":
    asyncio.run(main())
