"""
Tests for src/timing.py -- the structured per-stage timing instrumentation
added in Milestone 1 specifically because RELIABILITY_SCALE_ANALYSIS.md
Section 1.2 documented that this project previously had zero timing
instrumentation anywhere, making "where did the time go" unanswerable from
logs alone.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.timing import clear_recorded_timings, get_recorded_timings, time_stage


def setup_function():
    clear_recorded_timings()


def test_time_stage_records_duration_and_status_ok():
    with time_stage("resume.pdf", "pdf_text_extraction"):
        time.sleep(0.01)
    timings = get_recorded_timings()
    assert len(timings) == 1
    record = timings[0]
    assert record["resume_file"] == "resume.pdf"
    assert record["stage"] == "pdf_text_extraction"
    assert record["status"] == "ok"
    assert record["duration_ms"] >= 10  # slept 10ms, allow real-clock slack above


def test_time_stage_records_duration_and_status_error_then_reraises():
    class _Boom(Exception):
        pass

    try:
        with time_stage("resume.pdf", "llm_extraction"):
            raise _Boom("simulated failure")
    except _Boom:
        pass
    else:
        raise AssertionError("time_stage must re-raise the original exception")

    timings = get_recorded_timings()
    assert len(timings) == 1
    assert timings[0]["status"] == "error"
    assert timings[0]["stage"] == "llm_extraction"


def test_multiple_stages_accumulate_independently():
    with time_stage("a.pdf", "pdf_text_extraction"):
        pass
    with time_stage("a.pdf", "llm_extraction"):
        pass
    with time_stage("b.pdf", "pdf_text_extraction"):
        pass

    timings = get_recorded_timings()
    assert len(timings) == 3
    stages_for_a = [t["stage"] for t in timings if t["resume_file"] == "a.pdf"]
    assert stages_for_a == ["pdf_text_extraction", "llm_extraction"]
