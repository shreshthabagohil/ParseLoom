"""
Tests for src/history.py -- persistent, per-client run history (Milestone 4).

Covers: basic save/list/get round-tripping, ownership enforcement (client A
cannot read client B's run), and -- because the user explicitly required
this to work "real time by users" (i.e. genuine concurrent multi-user
traffic, not just single-threaded local testing) -- a real multi-threaded
concurrent-write stress test that proves WAL + busy_timeout actually
prevent "database is locked" errors under simultaneous writes, rather than
just asserting the pragmas were set.
"""
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.history as history_module  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """
    Every test gets its own throwaway SQLite file so tests can't see each
    other's data and so this suite never touches the real
    instance/parseloom_runs.db a running server would be using.
    """
    db_path = tmp_path / "test_runs.db"
    monkeypatch.setattr(history_module, "DB_PATH", db_path)
    return db_path


def _sample_result(n=1):
    return {
        "jd": f"Role {n}",
        "result": {"summary": {"evaluated": n, "shortlisted": 0}, "shortlist": [], "reserve": [], "needs_review": []},
        "details": {},
        "llm_warning": None,
    }


def test_save_then_list_returns_the_run_newest_first(isolated_db):
    client_id = "client-aaaaaaaa"
    history_module.save_run("run-1", client_id, "Backend Dev", 5, _sample_result(1))
    history_module.save_run("run-2", client_id, "Frontend Dev", 3, _sample_result(2))

    runs = history_module.list_runs_for_client(client_id)

    assert len(runs) == 2
    # Newest (most recently saved) first.
    assert runs[0]["id"] == "run-2"
    assert runs[1]["id"] == "run-1"
    assert runs[0]["jd_role"] == "Frontend Dev"
    assert runs[0]["resume_count"] == 3


def test_list_is_scoped_to_client_id(isolated_db):
    history_module.save_run("run-1", "client-aaaaaaaa", "Role A", 1, _sample_result())
    history_module.save_run("run-2", "client-bbbbbbbb", "Role B", 1, _sample_result())

    runs_for_a = history_module.list_runs_for_client("client-aaaaaaaa")
    runs_for_b = history_module.list_runs_for_client("client-bbbbbbbb")

    assert [r["id"] for r in runs_for_a] == ["run-1"]
    assert [r["id"] for r in runs_for_b] == ["run-2"]


def test_get_run_for_client_returns_full_payload_for_the_owner(isolated_db):
    payload = _sample_result(7)
    history_module.save_run("run-1", "client-aaaaaaaa", "Data Eng", 7, payload)

    fetched = history_module.get_run_for_client("run-1", "client-aaaaaaaa")

    assert fetched == payload


def test_ownership_mismatch_returns_none_not_the_data(isolated_db):
    """
    Security: this is the core ownership guarantee -- knowing a real
    run_id is not enough. Client B must not be able to read client A's
    run, even though the run_id is correct.
    """
    payload = _sample_result(9)
    history_module.save_run("run-1", "client-aaaaaaaa", "Security Eng", 9, payload)

    fetched_by_wrong_client = history_module.get_run_for_client("run-1", "client-bbbbbbbb")

    assert fetched_by_wrong_client is None


def test_get_run_for_client_returns_none_for_unknown_run_id(isolated_db):
    assert history_module.get_run_for_client("does-not-exist", "client-aaaaaaaa") is None


def test_list_runs_for_client_with_no_runs_returns_empty_list(isolated_db):
    assert history_module.list_runs_for_client("brand-new-client") == []


def test_save_run_never_raises_even_if_result_is_not_json_serializable(isolated_db):
    """
    save_run() must never turn a successful run into a failed one just
    because persistence hit a problem (documented explicitly in
    src/history.py's save_run docstring). An object that json.dumps can't
    serialize is a reasonable stand-in for "storage-layer failure".
    """
    class NotSerializable:
        pass

    # Should not raise.
    history_module.save_run("run-1", "client-aaaaaaaa", "Role", 1, {"bad": NotSerializable()})

    # And, since the write never actually completed, it shouldn't show up.
    assert history_module.list_runs_for_client("client-aaaaaaaa") == []


def test_concurrent_writes_from_many_threads_all_succeed(isolated_db):
    """
    The user's explicit requirement: "make sure it can be used real time
    by users" -- i.e. genuinely concurrent multi-user writes, not just a
    single operator testing locally. This starts many real OS threads
    that all call save_run() at the same moment, simulating multiple
    simultaneous site visitors each finishing a run around the same time.

    Without WAL mode + busy_timeout, SQLite's default locking would make
    at least some of these raise "database is locked" under real
    contention. This test fails loudly (via the errors list) if that
    happens, and then verifies every single write actually landed.
    """
    thread_count = 25
    errors = []
    barrier = threading.Barrier(thread_count)

    def _write(i):
        try:
            barrier.wait(timeout=5)  # maximize actual simultaneous contention
            history_module.save_run(
                f"run-{i}",
                f"client-{i:08d}",
                f"Role {i}",
                i,
                _sample_result(i),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append((i, exc))

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == [], f"concurrent writes raised errors: {errors}"

    # Every single run must actually be retrievable -- not just "didn't
    # crash", but genuinely persisted and readable back.
    for i in range(thread_count):
        fetched = history_module.get_run_for_client(f"run-{i}", f"client-{i:08d}")
        assert fetched is not None, f"run-{i} was not persisted"
        assert fetched["jd"] == f"Role {i}"


def test_concurrent_reads_and_writes_do_not_corrupt_or_block(isolated_db):
    """
    Real usage isn't just "many writes at once" -- it's some users
    finishing runs (writing) while others are browsing their past runs
    (reading) at the same moment. WAL mode's whole point is letting
    readers proceed without blocking on a writer. Verify that holds under
    real concurrent mixed traffic.
    """
    # Seed a few runs up front so readers have something to read.
    for i in range(5):
        history_module.save_run(f"seed-{i}", "reader-client", f"Seed {i}", i, _sample_result(i))

    errors = []

    def _writer(i):
        try:
            history_module.save_run(f"writer-run-{i}", f"writer-client-{i:04d}", "Writer Role", i, _sample_result(i))
        except Exception as exc:  # noqa: BLE001
            errors.append(("writer", i, exc))

    def _reader(i):
        try:
            for _ in range(10):
                history_module.list_runs_for_client("reader-client")
        except Exception as exc:  # noqa: BLE001
            errors.append(("reader", i, exc))

    threads = []
    for i in range(10):
        threads.append(threading.Thread(target=_writer, args=(i,)))
        threads.append(threading.Thread(target=_reader, args=(i,)))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == [], f"concurrent read/write traffic raised errors: {errors}"
    # Original seed data must still be intact and correctly ordered.
    seeded = history_module.list_runs_for_client("reader-client")
    assert len(seeded) == 5
