"""
Milestone 2 tests: src/pipeline.py::run_batch -- bounded concurrency with
order-preserving output, verified with a synthetic delay (no real LLM
calls, no quota spent), matching the pattern already used in this project's
history for verifying concurrency changes (SESSION_HANDOFF.md item 8).
"""
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import ParsedResume
from src.pipeline import run_batch


def _fake_parse_with_variable_delay(path: str) -> ParsedResume:
    # Deliberately makes earlier paths finish LAST, so order-preservation
    # in the output can only pass if run_batch is actually reordering by
    # input, not just returning completion order.
    index = int(Path(path).stem.split("_")[-1])
    delay = 0.05 * (5 - index)  # path "resume_0" sleeps longest, "resume_4" shortest
    time.sleep(max(delay, 0))
    return ParsedResume(file_name=Path(path).name, parse_status="Clean")


def test_run_batch_preserves_input_order_despite_out_of_order_completion(tmp_path):
    paths = [str(tmp_path / f"resume_{i}.pdf") for i in range(5)]
    for p in paths:
        Path(p).write_bytes(b"x")  # content doesn't matter, parse is mocked

    with patch("src.pipeline.parse_one_resume", side_effect=_fake_parse_with_variable_delay):
        results = run_batch(paths, max_workers=5)

    assert [r.file_name for r in results] == [f"resume_{i}.pdf" for i in range(5)]


def test_run_batch_respects_max_workers_ceiling(tmp_path):
    paths = [str(tmp_path / f"resume_{i}.pdf") for i in range(8)]
    for p in paths:
        Path(p).write_bytes(b"x")

    concurrent_count = {"current": 0, "max_seen": 0}

    def _tracking_parse(path):
        concurrent_count["current"] += 1
        concurrent_count["max_seen"] = max(concurrent_count["max_seen"], concurrent_count["current"])
        time.sleep(0.05)
        concurrent_count["current"] -= 1
        return ParsedResume(file_name=Path(path).name, parse_status="Clean")

    with patch("src.pipeline.parse_one_resume", side_effect=_tracking_parse):
        run_batch(paths, max_workers=3)

    # Never more than 3 concurrent "in-flight" calls -- proves the pool
    # ceiling is real, not just a suggestion.
    assert concurrent_count["max_seen"] <= 3
    assert concurrent_count["max_seen"] >= 2  # and genuinely concurrent, not accidentally serialized to 1


def test_run_batch_empty_list_returns_empty_list():
    assert run_batch([]) == []


def test_run_batch_default_worker_count_caps_at_default_max(tmp_path):
    from src.pipeline import DEFAULT_MAX_WORKERS

    paths = [str(tmp_path / f"resume_{i}.pdf") for i in range(DEFAULT_MAX_WORKERS + 4)]
    for p in paths:
        Path(p).write_bytes(b"x")

    concurrent_count = {"current": 0, "max_seen": 0}

    def _tracking_parse(path):
        concurrent_count["current"] += 1
        concurrent_count["max_seen"] = max(concurrent_count["max_seen"], concurrent_count["current"])
        time.sleep(0.03)
        concurrent_count["current"] -= 1
        return ParsedResume(file_name=Path(path).name, parse_status="Clean")

    with patch("src.pipeline.parse_one_resume", side_effect=_tracking_parse):
        run_batch(paths)  # no max_workers override -- exercises the default

    assert concurrent_count["max_seen"] <= DEFAULT_MAX_WORKERS
