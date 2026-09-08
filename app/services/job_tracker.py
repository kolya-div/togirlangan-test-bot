"""
Job status tracker — report processing holatini kuzatadi.

Statuslar: queued → processing → completed | failed
Har bir job uchun metadata: start_time, end_time, error, retry_count, progress.
In-memory, bounded dict — 100+ user uchun xavfsiz.
"""

import time
import asyncio
import logging
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobInfo:
    attempt_id: int
    status: JobStatus = JobStatus.QUEUED
    queued_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    completed_at: float | None = None
    error: str = ""
    retry_count: int = 0
    total_answers: int = 0
    processed_answers: int = 0
    current_step: str = ""  # "transcribing:3/5", "evaluating:2/5"
    provider_used: str = ""

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return time.monotonic() - self.queued_at
        if self.completed_at:
            return self.completed_at - self.started_at
        return time.monotonic() - self.started_at

    @property
    def queue_wait_time(self) -> float:
        if self.started_at is None:
            return time.monotonic() - self.queued_at
        return self.started_at - self.queued_at

    @property
    def progress_pct(self) -> int:
        if self.total_answers == 0:
            return 0
        return int(self.processed_answers / self.total_answers * 100)

    def to_dict(self) -> dict:
        return {
            "attempt_id": self.attempt_id,
            "status": self.status.value,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_seconds": round(self.elapsed, 1),
            "queue_wait_seconds": round(self.queue_wait_time, 1),
            "error": self.error,
            "retry_count": self.retry_count,
            "total_answers": self.total_answers,
            "processed_answers": self.processed_answers,
            "progress_pct": self.progress_pct,
            "current_step": self.current_step,
            "provider_used": self.provider_used,
        }


class JobTracker:
    """
    In-memory job tracker. Bounded: MAX_JOBS dan eski tugagan joblarni tozalab turadi.
    Thread-safe: asyncio.Lock bilan boshqariladi.
    """

    MAX_JOBS = 500
    MAX_COMPLETED_AGE = 3600  # 1 soat

    def __init__(self):
        self._jobs: dict[int, JobInfo] = {}
        self._lock = asyncio.Lock()
        self._stats = {
            "total_enqueued": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_retries": 0,
        }

    async def enqueue(self, attempt_id: int, total_answers: int = 0) -> JobInfo:
        async with self._lock:
            if attempt_id in self._jobs:
                existing = self._jobs[attempt_id]
                if existing.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
                    return existing

            job = JobInfo(
                attempt_id=attempt_id,
                total_answers=total_answers,
            )
            self._jobs[attempt_id] = job
            self._stats["total_enqueued"] += 1
            await self._cleanup_locked()
            logger.info("Job enqueued: attempt=%d (queue depth: %d)", attempt_id, len(self._jobs))
            return job

    async def start_processing(self, attempt_id: int):
        async with self._lock:
            job = self._jobs.get(attempt_id)
            if job and job.status == JobStatus.QUEUED:
                job.status = JobStatus.PROCESSING
                job.started_at = time.monotonic()

    async def update_progress(self, attempt_id: int, step: str, processed: int, total: int, provider: str = ""):
        async with self._lock:
            job = self._jobs.get(attempt_id)
            if job:
                job.current_step = step
                job.processed_answers = processed
                job.total_answers = total
                if provider:
                    job.provider_used = provider

    async def complete(self, attempt_id: int):
        async with self._lock:
            job = self._jobs.get(attempt_id)
            if job:
                job.status = JobStatus.COMPLETED
                job.completed_at = time.monotonic()
                self._stats["total_completed"] += 1
                logger.info(
                    "Job completed: attempt=%d elapsed=%.1fs queue_wait=%.1fs",
                    attempt_id, job.elapsed, job.queue_wait_time,
                )

    async def fail(self, attempt_id: int, error: str):
        async with self._lock:
            job = self._jobs.get(attempt_id)
            if job:
                job.status = JobStatus.FAILED
                job.completed_at = time.monotonic()
                job.error = error
                self._stats["total_failed"] += 1
                logger.error("Job failed: attempt=%d error=%s", attempt_id, error)

    async def increment_retry(self, attempt_id: int):
        async with self._lock:
            job = self._jobs.get(attempt_id)
            if job:
                job.retry_count += 1
                self._stats["total_retries"] += 1

    async def get_job(self, attempt_id: int) -> JobInfo | None:
        async with self._lock:
            return self._jobs.get(attempt_id)

    async def get_stats(self) -> dict:
        async with self._lock:
            queue_depth = sum(1 for j in self._jobs.values() if j.status == JobStatus.QUEUED)
            processing = sum(1 for j in self._jobs.values() if j.status == JobStatus.PROCESSING)
            return {
                "queue_depth": queue_depth,
                "processing": processing,
                "total_jobs": len(self._jobs),
                **self._stats,
            }

    async def _cleanup_locked(self):
        """Eski tugagan joblarni tozalaydi — memory leak oldini oladi."""
        if len(self._jobs) <= self.MAX_JOBS:
            return

        now = time.monotonic()
        to_remove = []
        for aid, job in self._jobs.items():
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                if job.completed_at and (now - job.completed_at) > self.MAX_COMPLETED_AGE:
                    to_remove.append(aid)

        for aid in to_remove:
            del self._jobs[aid]

        if to_remove:
            logger.info("Cleaned up %d old jobs", len(to_remove))


# Global instance
job_tracker = JobTracker()
