"""
Tests src/matching/scorer.py -- pure logic given a ParsedResume +
JobDescription, no LLM call. Covers Tricky Part 4 (parse quality gates
confidence, PROJECT_CONTEXT.md Section 5) since that rule is the core
"never fake confidence" guarantee this whole engine is built around --
these tests exist specifically so that guarantee can never silently
regress.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.matching.scorer import score_candidate
from src.models import JobDescription, ParsedResume

JD = JobDescription(
    role="Test Role",
    required_skills=["Python", "Git"],
    preferred_skills=["Docker"],
    cgpa_min=6.5,
    slots=5,
)


def _resume(**overrides) -> ParsedResume:
    defaults = dict(
        file_name="test.pdf",
        raw_text="Python Git Docker CGPA 8.0",
        parse_method="text",
        parse_status="Clean",
        full_name="Test Candidate",
        cgpa_10pt=8.0,
        cgpa_source_format="cgpa10",
        skills=["Python", "Git", "Docker"],
        projects=[{"title": "X", "description": "Y"}],
    )
    defaults.update(overrides)
    return ParsedResume(**defaults)


def test_failed_parse_produces_no_score():
    resume = _resume(parse_status="Failed", full_name=None, skills=[], cgpa_10pt=None)
    result = score_candidate(resume, JD)
    assert result.score is None
    assert result.confidence == "N/A"
    assert result.parse_quality == "Failed"


def test_clean_parse_can_reach_high_confidence():
    resume = _resume(parse_status="Clean")
    result = score_candidate(resume, JD)
    assert result.confidence == "High"


def test_partial_parse_is_capped_at_medium_even_with_strong_data():
    # Same strong data as the Clean case above, only parse_status differs
    resume = _resume(parse_status="Partial")
    result = score_candidate(resume, JD)
    assert result.confidence in ("Medium", "Low")
    assert result.confidence != "High"  # the hard cap this whole system is built around


def test_ambiguous_cgpa_prevents_high_confidence_even_on_clean_parse():
    resume = _resume(parse_status="Clean", cgpa_source_format="ambiguous")
    result = score_candidate(resume, JD)
    assert result.confidence != "High"


def test_below_cgpa_minimum_flagged_not_dropped():
    resume = _resume(cgpa_10pt=5.0)
    result = score_candidate(resume, JD)
    assert result.below_cgpa_minimum is True
    assert result.score is not None  # flagged, never silently excluded


def test_reasons_never_exceed_three_bullets():
    resume = _resume(cgpa_10pt=5.0, parse_status="Partial")
    result = score_candidate(resume, JD)
    assert len(result.reasons) <= 3


def test_reasons_always_present_even_with_no_signal():
    resume = _resume(skills=[], projects=[], full_name=None, cgpa_10pt=None)
    result = score_candidate(resume, JD)
    assert len(result.reasons) >= 1


def test_llm_call_failed_flag_passes_through_to_score_result():
    # Milestone 1 regression: the distinct LLM-failure state must survive
    # into ScoreResult, not get lost between ParsedResume and the scorer.
    resume = _resume(parse_status="Partial", llm_call_failed=True, llm_failure_reason="HTTP 429")
    result = score_candidate(resume, JD)
    assert result.llm_call_failed is True


def test_sparse_resume_scores_lower_than_complete_one():
    complete = score_candidate(_resume(), JD)
    sparse = score_candidate(
        _resume(skills=[], projects=[], cgpa_10pt=None, full_name=None), JD
    )
    assert sparse.score < complete.score
