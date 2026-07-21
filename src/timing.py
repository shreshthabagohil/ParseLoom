"""
Structured per-stage timing instrumentation. Built once, used everywhere a
resume goes through a real processing stage (PDF extraction, OCR, LLM call)
-- see REBUILD_PLAN.md Milestone 1 and RELIABILITY_SCALE_ANALYSIS.md Section
1.2, which documented that this project previously had zero timing
instrumentation anywhere, making "where did the time go" impossible to
answer from logs. This is intentionally a small, standalone module (no
dependency on pipeline.py or app.py) so it can be imported from anywhere in
src/ without circular-import risk -- pdf_reader.py, llm_extract.py, and
pipeline.py all use it independently.

Every stage is logged as a single structured line:
    STAGE_TIMING resume_file=<name> stage=<stage> duration_ms=<int> [ok|error]

This log format is deliberately grep-able (`grep STAGE_TIMING app.log`) so a
future "why is this slow" question is answered with real numbers on the very
next run, not by re-instrumenting from scratch.
"""

import logging
import time
from contextlib import contextmanager

logger = logging.getLogger("parseloom.timing")

# In-process record of every stage timing this run, for callers (e.g. the
# Milestone 8 load test, or a future /api/run response) that want the raw
# numbers rather than just a log line. Cleared per-process, not persisted --
# this is instrumentation, not a durability guarantee.
_TIMINGS: list[dict] = []


def get_recorded_timings() -> list[dict]:
    """Returns a copy of every stage timing recorded in this process so far.
    Used by tests and by the load-test tooling in later milestones -- kept
    here rather than parsing log output back out, which would be fragile."""
    return list(_TIMINGS)


def clear_recorded_timings() -> None:
    """Test-only reset, so one test's timings don't leak into another's
    assertions about how many stages ran."""
    _TIMINGS.clear()


@contextmanager
def time_stage(resume_file: str, stage: str):
    """
    Usage:
        with time_stage(file_name, "pdf_text_extraction"):
            ...do the work...

    Records duration regardless of whether the block raises, and re-raises
    any exception unchanged -- this must never swallow or alter errors from
    the stage it's timing, only measure them.
    """
    start = time.monotonic()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        record = {
            "resume_file": resume_file,
            "stage": stage,
            "duration_ms": duration_ms,
            "status": status,
        }
        _TIMINGS.append(record)
        logger.info(
            "STAGE_TIMING resume_file=%s stage=%s duration_ms=%s status=%s",
            resume_file,
            stage,
            duration_ms,
            status,
        )
