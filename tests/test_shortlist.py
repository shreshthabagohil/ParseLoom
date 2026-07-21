"""
Tests for src/matching/shortlist.py -- specifically the Milestone 1
llm_call_failed passthrough into every row shape (shortlist, reserve,
needs_review) and the per-JD batch summary count.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.matching.shortlist import build_shortlist
from src.models import JobDescription, ScoreResult

JD = JobDescription(role="Test Role", required_skills=["Python"], preferred_skills=[], cgpa_min=6.0, slots=2)


def _result(**overrides) -> ScoreResult:
    defaults = dict(
        candidate_file="x.pdf",
        candidate_name="X",
        score=80.0,
        confidence="High",
        reasons=["r1"],
        parse_quality="Clean",
        below_cgpa_minimum=False,
        llm_call_failed=False,
    )
    defaults.update(overrides)
    return ScoreResult(**defaults)


def test_llm_call_failed_present_on_shortlist_rows():
    results = [_result(llm_call_failed=True)]
    data = build_shortlist(results, JD)
    assert data["shortlist"][0]["llm_call_failed"] is True


def test_llm_call_failed_present_on_reserve_rows():
    results = [_result(candidate_file="a.pdf", score=90), _result(candidate_file="b.pdf", score=10, llm_call_failed=True)]
    data = build_shortlist(results, JD)
    # with slots=2 and only 2 eligible candidates, both land in shortlist --
    # force a third into reserve to exercise that row shape too.
    results.append(_result(candidate_file="c.pdf", score=5, llm_call_failed=True))
    data = build_shortlist(results, JD)
    reserve_flags = {r["file"]: r["llm_call_failed"] for r in data["reserve"]}
    assert reserve_flags.get("c.pdf") is True


def test_needs_review_includes_llm_call_failed():
    results = [_result(score=None, parse_quality="Failed", llm_call_failed=False, reasons=["Parse failed"])]
    data = build_shortlist(results, JD)
    assert data["needs_review"][0]["llm_call_failed"] is False


def test_summary_reports_llm_extraction_failures_count():
    results = [
        _result(candidate_file="a.pdf", llm_call_failed=True),
        _result(candidate_file="b.pdf", llm_call_failed=True),
        _result(candidate_file="c.pdf", llm_call_failed=False),
    ]
    data = build_shortlist(results, JD)
    assert data["summary"]["llm_extraction_failures"] == 2


# --- Milestone 5.5: shortlist score floor -----------------------------------
# A candidate scoring exactly 0 (zero required AND zero preferred skill
# matches -- see scorer.py, MIN_SHORTLIST_SCORE's module docstring in
# shortlist.py) must never fill an open shortlist slot just because a slot
# is available. Still fully visible in Reserve -- never hidden.


def test_zero_score_candidate_excluded_from_shortlist_even_with_open_slots():
    # JD has 2 slots; only one real (score > 0) candidate exists, plus a
    # zero-score one that would previously have filled the second slot.
    results = [
        _result(candidate_file="real.pdf", score=55.0),
        _result(candidate_file="zero.pdf", score=0.0),
    ]
    data = build_shortlist(results, JD)
    shortlist_files = {r["file"] for r in data["shortlist"]}
    reserve_files = {r["file"] for r in data["reserve"]}
    assert shortlist_files == {"real.pdf"}
    assert "zero.pdf" in reserve_files
    assert "zero.pdf" not in shortlist_files


def test_slots_unfilled_reported_when_too_few_real_candidates():
    # Same scenario as above: 2 slots, only 1 real candidate -> 1 unfilled.
    results = [
        _result(candidate_file="real.pdf", score=55.0),
        _result(candidate_file="zero.pdf", score=0.0),
    ]
    data = build_shortlist(results, JD)
    assert data["summary"]["shortlisted"] == 1
    assert data["summary"]["slots_unfilled"] == 1


def test_slots_unfilled_is_zero_when_every_slot_filled_honestly():
    results = [
        _result(candidate_file="a.pdf", score=90.0),
        _result(candidate_file="b.pdf", score=60.0),
    ]
    data = build_shortlist(results, JD)  # JD has 2 slots
    assert data["summary"]["slots_unfilled"] == 0
    assert len(data["shortlist"]) == 2


def test_zero_score_candidate_still_visible_in_reserve_not_dropped():
    results = [_result(candidate_file="zero.pdf", score=0.0)]
    data = build_shortlist(results, JD)
    assert data["shortlist"] == []
    assert len(data["reserve"]) == 1
    assert data["reserve"][0]["file"] == "zero.pdf"
    assert data["summary"]["slots_unfilled"] == 2  # both of JD's 2 slots unfilled


def test_negative_score_treated_same_as_zero_for_the_floor():
    # score should never actually be negative given the scoring formula, but
    # the floor is a <= comparison specifically so this can't slip through
    # if some future signal-conflict adjustment ever pushed a score below 0.
    results = [_result(candidate_file="neg.pdf", score=-3.0)]
    data = build_shortlist(results, JD)
    assert data["shortlist"] == []
    assert data["reserve"][0]["file"] == "neg.pdf"


def test_existing_high_score_shortlist_behavior_unaffected():
    # Regression guard: normal, well-matched candidates fill slots exactly
    # as before -- this milestone must not change behavior for the common
    # case, only the zero-overlap edge case.
    results = [
        _result(candidate_file="a.pdf", score=95.0),
        _result(candidate_file="b.pdf", score=80.0),
        _result(candidate_file="c.pdf", score=40.0),
    ]
    data = build_shortlist(results, JD)  # JD has 2 slots
    shortlist_files = [r["file"] for r in data["shortlist"]]
    assert shortlist_files == ["a.pdf", "b.pdf"]
    assert data["reserve"][0]["file"] == "c.pdf"
    assert data["summary"]["slots_unfilled"] == 0
