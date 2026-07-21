"""
Milestone 1 tests: the distinct LLM-call-failure state
(RELIABILITY_SCALE_ANALYSIS.md Section 1.1) must be structurally
distinguishable from a genuinely thin parse at every layer -- the data
model, the scorer's reasoning text, and the batch-level summary. These
tests exist specifically so "silent failure disguised as bad data" can
never regress unnoticed.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_client import LLMError, call_llm
from src.matching.scorer import score_candidate
from src.models import JobDescription, ParsedResume
from src.pipeline import (
    LLM_FAILURE_BATCH_WARNING_THRESHOLD,
    parse_one_resume,
    summarize_llm_failures,
)

JD = JobDescription(
    role="Test Role",
    required_skills=["Python", "Git"],
    preferred_skills=["Docker"],
    cgpa_min=6.5,
    slots=5,
)

REAL_RESUME_DIR = Path(__file__).resolve().parent.parent / "data" / "real_resumes"


def _pick_real_pdf() -> str:
    pdfs = sorted(REAL_RESUME_DIR.glob("*.pdf"))
    assert pdfs, "expected at least one real PDF fixture in data/real_resumes"
    return str(pdfs[0])


# --- Unit: scorer produces distinct reasoning for LLM failure vs. thin content ---


def test_llm_failure_reasoning_is_distinct_from_generic_partial_reasoning():
    llm_failed_resume = ParsedResume(
        file_name="a.pdf",
        parse_status="Partial",
        llm_call_failed=True,
        llm_failure_reason="HTTP 429: rate limited",
    )
    genuinely_thin_resume = ParsedResume(
        file_name="b.pdf",
        parse_status="Partial",
        llm_call_failed=False,
    )

    llm_failed_result = score_candidate(llm_failed_resume, JD)
    thin_result = score_candidate(genuinely_thin_resume, JD)

    assert llm_failed_result.llm_call_failed is True
    assert thin_result.llm_call_failed is False
    assert any("AI extraction failed" in r for r in llm_failed_result.reasons)
    assert not any("AI extraction failed" in r for r in thin_result.reasons)
    # The two reason sets must not be identical -- this is exactly the bug
    # that made three different failures look like three identical resumes.
    assert llm_failed_result.reasons != thin_result.reasons


def test_failed_parse_still_passes_through_llm_call_failed_field():
    # A hard Failed parse (never reached the LLM) should report
    # llm_call_failed=False, not leave the field undefined/ambiguous.
    resume = ParsedResume(file_name="c.pdf", parse_status="Failed")
    result = score_candidate(resume, JD)
    assert result.score is None
    assert result.llm_call_failed is False


# --- Batch-level summary ---


def test_summarize_llm_failures_none_when_batch_healthy():
    resumes = [ParsedResume(file_name=f"{i}.pdf", llm_call_failed=False) for i in range(5)]
    assert summarize_llm_failures(resumes) is None


def test_summarize_llm_failures_none_below_threshold():
    resumes = [ParsedResume(file_name=f"{i}.pdf", llm_call_failed=(i == 0)) for i in range(5)]
    assert summarize_llm_failures(resumes) is None  # 1/5 = 0.2, below the 0.5 threshold


def test_summarize_llm_failures_warns_at_threshold():
    n = 10
    failed_n = int(n * LLM_FAILURE_BATCH_WARNING_THRESHOLD)
    resumes = [ParsedResume(file_name=f"{i}.pdf", llm_call_failed=(i < failed_n)) for i in range(n)]
    warning = summarize_llm_failures(resumes)
    assert warning is not None
    assert warning["failed_count"] == failed_n
    assert warning["total_count"] == n
    assert "provider" in warning["message"].lower()


def test_summarize_llm_failures_regression_three_poisoned_resumes():
    """
    Regression test for Section 2 item 1 specifically: three resumes that
    all hit an LLM-call failure (e.g. a poisoned API key) must be reported
    as a batch-level provider warning, not silently indistinguishable from
    three genuinely low-signal resumes.
    """
    resumes = [
        ParsedResume(file_name=f"resume_{i}.pdf", llm_call_failed=True, llm_failure_reason="HTTP 401: bad key")
        for i in range(3)
    ]
    warning = summarize_llm_failures(resumes)
    assert warning is not None
    assert warning["failed_count"] == 3
    assert warning["total_count"] == 3


# --- LLM-pipeline-specific: simulated failure modes at the HTTP layer ---


class _FakeResponse:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body or {}
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._json_body


def test_simulated_429_produces_llm_error_after_retries_exhausted():
    with patch("src.ai_client.requests.post", return_value=_FakeResponse(429, text="rate limited")):
        with patch("src.ai_client.time.sleep"):  # don't actually wait through backoff in tests
            with pytest.raises(LLMError):
                call_llm(system="sys", user="user", provider="groq")


def test_simulated_500_produces_llm_error_after_retries_exhausted():
    with patch("src.ai_client.requests.post", return_value=_FakeResponse(500, text="server error")):
        with patch("src.ai_client.time.sleep"):
            with pytest.raises(LLMError):
                call_llm(system="sys", user="user", provider="groq")


def test_simulated_timeout_produces_llm_error():
    import requests as requests_module

    with patch("src.ai_client.requests.post", side_effect=requests_module.Timeout("timed out")):
        with patch("src.ai_client.time.sleep"):
            with pytest.raises(LLMError):
                call_llm(system="sys", user="user", provider="groq")


def test_simulated_malformed_response_shape_produces_llm_error():
    # 200 OK but missing the expected "choices" key -- a real failure mode
    # distinct from an HTTP error status.
    with patch("src.ai_client.requests.post", return_value=_FakeResponse(200, json_body={"unexpected": "shape"})):
        with pytest.raises(LLMError):
            call_llm(system="sys", user="user", provider="groq")


def test_pipeline_marks_llm_call_failed_on_simulated_provider_outage(tmp_path):
    """
    Full pipeline test, not just the LLM client in isolation: a real PDF
    through parse_one_resume with the LLM call simulated as permanently
    failing must produce llm_call_failed=True and parse_status="Partial",
    never a crash and never indistinguishable from a thin-content resume.
    """
    real_pdf = _pick_real_pdf()
    with patch("src.pipeline.extract_structured_fields", side_effect=LLMError("simulated provider outage")):
        resume = parse_one_resume(real_pdf)

    assert resume.llm_call_failed is True
    assert resume.llm_failure_reason == "simulated provider outage"
    assert resume.parse_status == "Partial"
    assert any("AI extraction failed" in note for note in resume.parse_notes)


def test_pipeline_three_resumes_poisoned_key_all_flagged_not_silently_empty(tmp_path):
    """
    Direct regression test for the exact scenario described in
    RELIABILITY_SCALE_ANALYSIS.md Section 1.1: three different resumes, all
    hitting the same LLM failure, must all be visibly flagged -- not appear
    as three unrelated resumes that all happened to score zero.
    """
    pdfs = sorted(REAL_RESUME_DIR.glob("*.pdf"))[:3]
    assert len(pdfs) == 3

    with patch("src.pipeline.extract_structured_fields", side_effect=LLMError("HTTP 401: invalid API key")):
        resumes = [parse_one_resume(str(p)) for p in pdfs]

    assert all(r.llm_call_failed for r in resumes)
    assert all(r.parse_status == "Partial" for r in resumes)
    warning = summarize_llm_failures(resumes)
    assert warning is not None
    assert warning["failed_count"] == 3


# --- Real, non-simulated integration test: invalid key against the real Groq endpoint ---


def test_real_invalid_groq_key_produces_llm_call_failed_not_a_crash():
    """
    A real network call to Groq with a deliberately invalid key. This
    exercises the actual HTTP 401 path (not a mock), confirming the whole
    chain -- ai_client -> llm_extract -> pipeline -- correctly converts a
    real provider auth failure into llm_call_failed=True. No model
    inference quota is spent (the request is rejected at auth, before
    reaching the model), only a fast 401 round trip.
    """
    real_pdf = _pick_real_pdf()
    old_key = os.environ.get("GROQ_API_KEY")
    old_provider = os.environ.get("AI_PROVIDER")
    old_gemini_key = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ["GROQ_API_KEY"] = "sk-deliberately-invalid-test-key"
        os.environ["AI_PROVIDER"] = "groq"
        # Also blank Gemini so Milestone 2's future dual-provider failover
        # (not yet built as of this milestone) can't accidentally rescue
        # this call once it exists -- this test is pinned to Groq-only
        # behavior as it stands today.
        os.environ.pop("GEMINI_API_KEY", None)
        resume = parse_one_resume(real_pdf)
    finally:
        if old_key is not None:
            os.environ["GROQ_API_KEY"] = old_key
        else:
            os.environ.pop("GROQ_API_KEY", None)
        if old_provider is not None:
            os.environ["AI_PROVIDER"] = old_provider
        else:
            os.environ.pop("AI_PROVIDER", None)
        if old_gemini_key is not None:
            os.environ["GEMINI_API_KEY"] = old_gemini_key

    assert resume.llm_call_failed is True
    assert resume.parse_status == "Partial"
    assert resume.llm_failure_reason is not None
    # The invalid key itself must never leak into the failure reason.
    assert "sk-deliberately-invalid-test-key" not in resume.llm_failure_reason
