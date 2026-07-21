"""
Milestone 2 tests: content-hash caching in src/pipeline.py. Identical file
bytes must produce a cache hit (no re-parse); different bytes must not
collide; and a transient LLM-call failure must never be cached, since that
would turn a retryable transient error into a permanent one.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import ParsedResume
from src.pipeline import clear_resume_cache, parse_one_resume


def setup_function():
    clear_resume_cache()


def _write(tmp_path, name: str, content: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def test_identical_content_is_a_cache_hit_and_skips_reparsing(tmp_path):
    path_a = _write(tmp_path, "a.pdf", b"identical-bytes")
    path_b = _write(tmp_path, "b_different_name.pdf", b"identical-bytes")

    # Mirrors real _parse_one_resume_uncached behavior: file_name always
    # comes from the argument it was actually called with, not a fixed
    # value -- a fixed return_value here would mask the real bug this test
    # is checking for (the cache correcting the filename on a hit).
    def _fake_uncached(path, file_name=None):
        return ParsedResume(file_name=file_name, parse_status="Clean", full_name="Cached Person")

    with patch("src.pipeline._parse_one_resume_uncached", side_effect=_fake_uncached) as mock_parse:
        first = parse_one_resume(path_a)
        second = parse_one_resume(path_b)

    # Only one real parse happened despite two calls with different paths --
    # the second was served entirely from cache.
    assert mock_parse.call_count == 1
    assert first.full_name == "Cached Person"
    assert second.full_name == "Cached Person"
    # Filename is corrected per-call even though content came from cache.
    assert first.file_name == "a.pdf"
    assert second.file_name == "b_different_name.pdf"


def test_different_content_is_not_a_cache_hit(tmp_path):
    path_a = _write(tmp_path, "a.pdf", b"content-one")
    path_b = _write(tmp_path, "b.pdf", b"content-two-different")

    with patch(
        "src.pipeline._parse_one_resume_uncached",
        side_effect=lambda path, file_name=None: ParsedResume(file_name=file_name, parse_status="Clean"),
    ) as mock_parse:
        parse_one_resume(path_a)
        parse_one_resume(path_b)

    assert mock_parse.call_count == 2  # no false cache hit across different content


def test_llm_call_failed_result_is_never_cached(tmp_path):
    path_a = _write(tmp_path, "a.pdf", b"same-bytes-both-times")

    failed_result = ParsedResume(
        file_name="a.pdf", parse_status="Partial", llm_call_failed=True, llm_failure_reason="HTTP 429"
    )

    with patch("src.pipeline._parse_one_resume_uncached", return_value=failed_result) as mock_parse:
        first = parse_one_resume(path_a)
        second = parse_one_resume(path_a)

    # Both calls hit real parsing -- a transient failure must never be
    # served from cache, so a later retry (once the provider recovers) can
    # actually succeed instead of permanently replaying the same failure.
    assert mock_parse.call_count == 2
    assert first.llm_call_failed is True
    assert second.llm_call_failed is True


def test_successful_result_after_a_prior_failure_gets_cached(tmp_path):
    path_a = _write(tmp_path, "a.pdf", b"retry-succeeds-bytes")

    failed_result = ParsedResume(file_name="a.pdf", parse_status="Partial", llm_call_failed=True)
    succeeded_result = ParsedResume(file_name="a.pdf", parse_status="Clean", llm_call_failed=False, full_name="Now Works")

    with patch("src.pipeline._parse_one_resume_uncached", side_effect=[failed_result, succeeded_result]) as mock_parse:
        first = parse_one_resume(path_a)   # fails, not cached
        second = parse_one_resume(path_a)  # succeeds, gets cached
        third = parse_one_resume(path_a)   # should be served from cache now

    assert mock_parse.call_count == 2  # third call did not re-parse
    assert first.llm_call_failed is True
    assert second.full_name == "Now Works"
    assert third.full_name == "Now Works"
