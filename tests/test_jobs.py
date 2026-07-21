"""
Tests for src/jobs.py -- the in-memory async job store backing Milestone
3's background batch processing. Covers both correctness (progress
accumulates, terminal states are set correctly) and the security
properties the module docstring commits to (unguessable IDs, TTL
eviction, no leaked internals).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.jobs import JobStore


def test_create_returns_a_uuid4_hex_job_id():
    store = JobStore()
    job_id = store.create(total=5)
    # uuid4().hex is exactly 32 lowercase hex characters, no dashes.
    assert len(job_id) == 32
    assert all(c in "0123456789abcdef" for c in job_id)


def test_two_jobs_never_share_an_id():
    store = JobStore()
    ids = {store.create(total=1) for _ in range(200)}
    assert len(ids) == 200  # no collisions across 200 real creations


def test_unknown_job_id_returns_none_not_an_exception():
    store = JobStore()
    assert store.get("not-a-real-job-id") is None


def test_progress_accumulates_as_candidates_are_appended():
    store = JobStore()
    job_id = store.create(total=3)
    store.append_candidate(job_id, {"file": "a.pdf"})
    store.append_candidate(job_id, {"file": "b.pdf"})
    job = store.get(job_id)
    assert job.completed == 2
    assert job.total == 3
    assert job.status == "running"


def test_mark_done_sets_terminal_state_and_result():
    store = JobStore()
    job_id = store.create(total=1)
    store.mark_done(job_id, {"jd": "Test Role", "result": {}})
    job = store.get(job_id)
    assert job.status == "done"
    assert job.result == {"jd": "Test Role", "result": {}}


def test_mark_error_never_stores_a_raw_exception_only_a_string():
    store = JobStore()
    job_id = store.create(total=1)
    store.mark_error(job_id, "Something went wrong processing this batch. Check the server log for detail.")
    job = store.get(job_id)
    assert job.status == "error"
    assert isinstance(job.error_message, str)
    assert "Traceback" not in job.error_message  # never a raw traceback string


def test_ttl_eviction_removes_stale_jobs():
    # A store with a near-zero TTL to test eviction without a real 2-hour wait.
    store = JobStore(ttl_seconds=0)
    job_id = store.create(total=1)
    time.sleep(0.01)
    # Any access triggers pruning -- the job should now be gone.
    assert store.get(job_id) is None


def test_ttl_does_not_evict_fresh_jobs():
    store = JobStore(ttl_seconds=999)
    job_id = store.create(total=1)
    assert store.get(job_id) is not None


def test_operations_on_expired_or_unknown_job_id_are_no_ops_not_crashes():
    store = JobStore()
    # None of these should raise, even though the job was never created.
    store.append_candidate("ghost-job", {"file": "x.pdf"})
    store.mark_done("ghost-job", {"result": "irrelevant"})
    store.mark_error("ghost-job", "irrelevant")
    assert store.get("ghost-job") is None
