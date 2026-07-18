"""
Tests src/extraction/grade_normalizer.py -- pure regex/math, no LLM
call, so these run instantly and never touch API quota. Covers the
four branches documented in PROJECT_CONTEXT.md Section 7 and
DESIGN_DECISIONS.md, plus the fallback added in Section 11.6, all of
which were manually verified during real/synthetic testing on
2026-07-18 -- this suite exists so a future edit can't silently break
any of them without a test failing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extraction.grade_normalizer import find_and_normalize_from_raw_text, normalize


def test_cgpa10_explicit_slash():
    r = normalize("CGPA: 8.4/10")
    assert r.cgpa_10pt == 8.4
    assert r.source_format == "cgpa10"


def test_cgpa10_keyword_only():
    r = normalize("cgpa 7.9")
    assert r.cgpa_10pt == 7.9
    assert r.source_format == "cgpa10"


def test_percentage_conversion():
    r = normalize("Percentage: 82%")
    assert r.cgpa_10pt == round(82 / 9.5, 2)
    assert r.source_format == "percentage"


def test_gpa4_conversion():
    r = normalize("GPA: 3.6/4.0")
    assert r.cgpa_10pt == 9.0
    assert r.source_format == "gpa4"


def test_gpa4_conversion_capped_at_10():
    r = normalize("GPA: 4.0/4.0")
    assert r.cgpa_10pt == 10.0  # 4.0 * 2.5 = 10.0 exactly, must not exceed 10


def test_ambiguous_bare_number_low_range():
    r = normalize("Academic Score: 3.4")
    assert r.cgpa_10pt == 3.4
    assert r.source_format == "ambiguous"
    assert r.note is not None  # must state the assumption, never guess silently


def test_bare_number_in_plausible_cgpa10_range_is_not_ambiguous():
    r = normalize("Score: 8.1")
    assert r.cgpa_10pt == 8.1
    assert r.source_format == "cgpa10"  # 4-10 range has only one plausible reading


def test_empty_input_returns_none():
    r = normalize("")
    assert r.cgpa_10pt is None
    assert r.source_format is None


def test_no_grade_present_returns_none_with_note():
    r = normalize("no numbers relevant to grades in here")
    assert r.cgpa_10pt is None
    assert r.note is not None


def test_fallback_recovers_cgpa10_from_raw_text():
    text = "Some resume text... EDUCATION B.Tech CSE 2025 CGPA: 9.1/10 more text"
    r = find_and_normalize_from_raw_text(text)
    assert r.cgpa_10pt == 9.1
    assert r.source_format == "cgpa10"


def test_fallback_handles_number_before_keyword():
    # Real phrasing found during testing: the number can come BEFORE
    # the keyword ("82% aggregate"), not just after ("CGPA: 9.1").
    text = "We want at least 82% aggregate in your final year."
    r = find_and_normalize_from_raw_text(text)
    assert r.cgpa_10pt == round(82 / 9.5, 2)


def test_fallback_returns_none_when_nothing_parseable():
    text = "This text has no real grade info at all."
    r = find_and_normalize_from_raw_text(text)
    assert r.cgpa_10pt is None


def test_fallback_empty_text():
    r = find_and_normalize_from_raw_text("")
    assert r.cgpa_10pt is None
