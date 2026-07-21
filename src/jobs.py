"""
In-memory async job store backing /api/run's background batch processing
(Milestone 3). Security-relevant properties, by design, not as an
afterthought:

- `job_id` is `uuid.uuid4().hex` -- 122 bits of randomness. Not sequential,
  not derived from any user input, not enumerable. A job's results cannot
  be discovered by an attacker guessing or iterating IDs.
- Nothing stored on a `JobState` is ever a raw exception or stack trace --
  `error_message` is always a pre-written generic string; the real detail
  goes to the server log only (same pattern already used everywhere else
  in this codebase, e.g. app.py's route-level except blocks).
- `_prune_locked()` evicts job records older than `JOB_TTL_SECONDS` on
  every store access. This bounds how long extracted resume data (names,
  skills, raw text -- real PII) sits in server memory, and bounds memory
  growth on a long-running process. Matches the project's "in-memory is
  enough" decision (REBUILD_PLAN.md) -- this is not a durability
  guarantee, it's a deliberate exposure-window limit.
- All access goes through a single `threading.Lock` -- the job store is
  read and written from multiple threads (the Flask request thread that
  creates a job and polls it, and the background worker thread that
  updates it), and without a lock, concurrent dict mutation from multiple
  threads is a real race condition, not just a theoretical one.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field

JOB_TTL_SECONDS = 2 * 60 * 60  # 2 hours -- see module docstring


@dataclass
class JobState:
    job_id: str
    status: str = "running"  # "running" | "done" | "error"
    total: int = 0
    candidates_so_far: list = field(default_factory=list)
    result: dict | None = None
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)

    @property
    def completed(self) -> int:
        return len(self.candidates_so_far)


class JobStore:
    def __init__(self, ttl_seconds: int = JOB_TTL_SECONDS):
        self._lock = threading.Lock()
        self._jobs: dict[str, JobState] = {}
        self._ttl_seconds = ttl_seconds

    def create(self, total: int) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = JobState(job_id=job_id, total=total)
            self._prune_locked()
        return job_id

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            self._prune_locked()
            return self._jobs.get(job_id)

    def mark_done(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "done"
                job.result = result

    def mark_error(self, job_id: str, error_message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "error"
                job.error_message = error_message

    def append_candidate(self, job_id: str, candidate: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.candidates_so_far.append(candidate)

    def _prune_locked(self) -> None:
        """Caller must already hold self._lock."""
        cutoff = time.time() - self._ttl_seconds
        stale_ids = [jid for jid, job in self._jobs.items() if job.created_at < cutoff]
        for jid in stale_ids:
            del self._jobs[jid]

    def _job_count(self) -> int:
        """Test/diagnostic helper only."""
        with self._lock:
            return len(self._jobs)


# One process-wide store, same pattern as the rest of this app's in-memory
# state (the content-hash cache in pipeline.py). Not a singleton class
# because there's exactly one Flask process using it, matching the
# project's "in-memory is enough, no external infra" scope decision.
job_store = JobStore()
