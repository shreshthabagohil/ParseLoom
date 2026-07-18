"""
Tests src/matching/skill_matcher.py -- pure logic, no LLM call.
Covers exact/synonym/partial/implicit/none classification (the five
match types the scoring formula depends on, PROJECT_CONTEXT.md
Section 6) and the full evidence-building pipeline.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extraction.skill_vocab import find_skills_in_text
from src.matching.skill_matcher import build_evidence, classify, score_skill_list


def test_exact_match():
    hits = find_skills_in_text("Skilled in Docker and Git")
    match_type, credit = classify("docker", hits, "skilled in docker and git")
    assert match_type == "exact"
    assert credit == 1.0


def test_synonym_match():
    hits = find_skills_in_text("Built apps with ReactJS")
    match_type, credit = classify("react.js", hits, "built apps with reactjs")
    assert match_type == "synonym"
    assert credit == 1.0


def test_partial_match():
    # react.js's PARTIAL_MATCH_MAP entry is ["javascript"] -- a resume
    # that mentions JavaScript but not React.js by name should credit
    # React.js as a partial (not exact) match.
    hits = find_skills_in_text("Experience with JavaScript")
    match_type, credit = classify("react.js", hits, "experience with javascript")
    assert match_type == "partial"
    assert credit == 0.5


def test_implicit_match_from_prose():
    evidence_text = "collaborated on codebase with a team of five engineers"
    match_type, credit = classify("git", {}, evidence_text)
    assert match_type == "implicit"
    assert credit == 0.25


def test_no_match():
    match_type, credit = classify("kubernetes", {}, "no relevant text here at all")
    assert match_type is None
    assert credit == 0.0


def test_score_skill_list_empty_requirements_does_not_penalize():
    avg, details = score_skill_list([], {}, "")
    assert avg == 1.0
    assert details == []


def test_score_skill_list_averages_correctly():
    hits = find_skills_in_text("Python and Git")
    avg, details = score_skill_list(["python", "git", "kubernetes"], hits, "python and git")
    # python=1.0, git=1.0, kubernetes=0.0 -> average 0.667
    assert round(avg, 3) == round(2 / 3, 3)
    assert len(details) == 3


def test_build_evidence_combines_all_text_sources():
    llm_fields = {
        "skills": ["Python"],
        "projects": [{"title": "API Project", "description": "built REST endpoints"}],
        "experience": [{"role": "Intern", "company": "Acme", "duration": "6mo"}],
        "certifications": ["AWS Cert"],
    }
    hits, combined = build_evidence("raw resume text with Docker mentioned", llm_fields)
    assert "docker" in hits
    assert "python" in hits
    assert "API Project" in combined
    assert "Intern" in combined
