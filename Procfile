# --workers=1 is deliberate, not a typo: src/jobs.py's JobStore (and the
# per-process resume content-hash cache in src/pipeline.py) are in-memory,
# module-global state, per the project's explicit "in-memory is enough"
# design decision (REBUILD_PLAN.md's locked decisions, Milestone 3).
# Multiple gunicorn WORKER PROCESSES do not share memory -- a status poll
# routed to a different worker process than the one that started the job
# would see "unknown job" even though the job is really still running.
# --threads=8 (gthread worker class) gives real request concurrency
# WITHIN that one process instead, which is safe: Python threads in the
# same process share the same module-global JobStore.
web: gunicorn app:app --worker-class=gthread --workers=1 --threads=8 --timeout=120 --bind=0.0.0.0:$PORT

