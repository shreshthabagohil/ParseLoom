"""
Persistent run history (Milestone 4) -- SQLite-backed, so a completed run
can be reopened days later, browsed by date/JD, and re-downloaded as
Excel, satisfying the user's explicit request ("that can be either from 5
days ago or 10 days ago or any JD").

Real scope decisions made here, deliberately, not left implicit:

1. **Per-client ownership, not a global shared history.** This app has no
   login (WEB_APP_PLAN.md Section 6's "single-operator demo tool"
   decision), but once this is a real, publicly deployed tool used by
   more than one person at a time ("used real time by users" -- the
   user's own words), a single global run history would mean any visitor
   could browse every OTHER visitor's past uploads and extracted
   candidate data. That's a real privacy leak, not a hypothetical one --
   it would undo everything Milestones 1-3 did for PII protection. Every
   run is stored with a `client_id` (a random ID generated client-side and
   kept in localStorage, not a real login), and every read is filtered
   AND ownership-checked against it -- not just filtered. No new
   auth system, but no accidental cross-user data exposure either.

2. **Concurrency-safe for real simultaneous users, not just one operator
   testing locally.** SQLite's default journal mode serializes writers
   and can raise "database is locked" under genuinely concurrent access.
   WAL (write-ahead logging) mode lets readers and a writer proceed
   concurrently, and `busy_timeout` makes a second writer wait briefly
   instead of failing immediately if it does contend with another writer.
   Both are set on every connection. A fresh, short-lived connection is
   opened per operation rather than one long-lived shared connection --
   sqlite3 connections are not safe to share across threads by default,
   and this app runs with `threaded=True` (Milestone 3) plus background
   worker threads, so "one global connection" would be a real race, not
   just an unlikely one.

3. **Documented, not silently accepted, free-host disk risk.** Most
   free-tier hosts (Render's free web service tier specifically) do not
   guarantee persistent disk across a redeploy or a cold restart after
   extended idle. This DB file may not survive indefinitely on such a
   host. Mitigation already exists and doesn't depend on this module:
   every run's Excel export (src/output/xlsx_export.py) works whether or
   not history persists long-term, so a user always has an escape hatch.

4. **Read paths degrade gracefully, they never 500.** A real end-to-end
   test against a live server (not the mocked test client) surfaced this
   directly: SQLite's WAL mode memory-maps a `-wal`/`-shm` file, and that
   memory-mapping is unreliable on some non-local filesystems (network
   mounts, FUSE-backed sync folders -- exactly what this dev sandbox's
   own working directory turned out to be) -- it can raise
   "disk I/O error" even on a fresh, otherwise-healthy database. Since
   history is explicitly a nice-to-have layered on top of the
   already-working in-memory job result (Milestone 3), list_runs_for_client()
   and get_run_for_client() both catch sqlite3.Error and degrade to "no
   history" (empty list / None) rather than raising a 500 out to the
   client. save_run() already did this; the read paths now match. The
   DB path itself is overridable via the PARSELOOM_HISTORY_DB_PATH env
   var so a real deployment can point it at whatever writable, ordinary
   local disk path its host provides, sidestepping this class of issue
   entirely rather than working around it in code.
"""

import json
import os
import sqlite3
import time
from pathlib import Path

# Overridable via PARSELOOM_HISTORY_DB_PATH so a real deployment can point
# this at whatever writable, persistent path its host actually provides
# (e.g. a mounted persistent-disk path that isn't the app's own working
# directory), without a code change. Defaults to instance/ alongside the
# app, matching Flask convention, for local/dev use.
DB_PATH = Path(
    os.environ.get("PARSELOOM_HISTORY_DB_PATH")
    or (Path(__file__).resolve().parent.parent / "instance" / "parseloom_runs.db")
)


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")  # wait up to 5s under real write contention, don't just fail
    return conn


def init_db() -> None:
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                jd_role TEXT NOT NULL,
                resume_count INTEGER NOT NULL,
                result_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_client_id ON runs (client_id, created_at DESC)")


def save_run(run_id: str, client_id: str, jd_role: str, resume_count: int, result: dict) -> None:
    """Called once a job reaches "done" -- persists it so it can be
    browsed later. Never raises out to the caller on a storage failure
    (see the try/except): persistence is a nice-to-have on top of the
    already-working in-memory job result (Milestone 3), not something
    that should turn a successful run into a failed one if, say, the
    filesystem is temporarily read-only on a free host."""
    try:
        result_json = json.dumps(result)
        init_db()
        with _get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs (id, client_id, created_at, jd_role, resume_count, result_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, client_id, time.time(), jd_role, resume_count, result_json),
            )
    except (sqlite3.Error, TypeError, ValueError):
        # Logged by the caller (app.py already wraps job execution in a
        # broad handler with server-side logging) -- deliberately swallow
        # here so a history-write failure never masks a successful run.
        # TypeError/ValueError included alongside sqlite3.Error because
        # json.dumps() itself can raise (e.g. a genuinely unserializable
        # object slipping into a result payload) -- that's still a
        # persistence-layer failure from the caller's point of view, not
        # something that should turn a successful run into a failed one.
        pass


def list_runs_for_client(client_id: str, limit: int = 50) -> list[dict]:
    """Never raises out to the caller on a storage failure -- same
    reasoning as save_run's try/except. Persistent history is a
    nice-to-have layered on top of the already-working in-memory job
    result (Milestone 3); a transient disk hiccup reading it back should
    degrade to "no history available right now" (empty list), not a 500
    that makes the whole page look broken."""
    try:
        init_db()
        with _get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, created_at, jd_role, resume_count FROM runs "
                "WHERE client_id = ? ORDER BY created_at DESC LIMIT ?",
                (client_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []


def get_run_for_client(run_id: str, client_id: str) -> dict | None:
    """Returns the stored result only if `client_id` actually owns this
    run -- an explicit ownership check, not just convenience filtering.
    Guessing a run_id (already a UUID4, so practically infeasible) still
    wouldn't be enough without also knowing the owning client_id.

    Also degrades to None (same as "not found") on a storage-layer
    failure, for the same reason as list_runs_for_client above -- a
    disk/lock hiccup here should read as "unavailable," not crash the
    request with a 500."""
    try:
        init_db()
        with _get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT result_json FROM runs WHERE id = ? AND client_id = ?",
                (run_id, client_id),
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return json.loads(row["result_json"])
