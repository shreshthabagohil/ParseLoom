"""
Turns a ParsedResume + JobDescription into a ScoreResult: the weighted
score, the confidence level, and the reasoning bullets. See
PROJECT_CONTEXT.md Section 6 for the formula and DESIGN_DECISIONS.md
Tricky Part 4 for the confidence-capping rule this enforces.
"""

from ..models import JobDescription, ParsedResume, ScoreResult
from .skill_matcher import build_evidence, score_skill_list

CORE_FIELDS = ["full_name", "cgpa_10pt"]  # plus "has skills" and "has projects/experience" below


def _completeness_fraction(resume: ParsedResume) -> float:
    checks = [
        resume.full_name is not None,
        resume.cgpa_10pt is not None,
        len(resume.skills) > 0,
        len(resume.projects) > 0 or len(resume.experience) > 0,
    ]
    return sum(checks) / len(checks)


def _signal_conflict_adjustment(resume: ParsedResume) -> tuple[float, list[str]]:
    """
    Returns (score_delta, reasoning_notes). Bounded, documented nudge --
    the reasoning matters more than the number. See PROJECT_CONTEXT.md
    Section 6, step 3.
    """
    notes = []
    delta = 0.0

    has_projects_or_exp = len(resume.projects) > 0 or len(resume.experience) > 0
    cgpa = resume.cgpa_10pt

    if cgpa is not None and cgpa >= 8.5 and not has_projects_or_exp:
        delta -= 5
        notes.append(f"Strong academic record (CGPA {cgpa}) but no projects or experience listed -- weak practical signal.")
    elif cgpa is not None and cgpa < 7.0 and has_projects_or_exp and len(resume.projects) >= 2:
        delta += 5
        notes.append(f"CGPA ({cgpa}) is on the lower side, but {len(resume.projects)} projects show strong practical signal.")

    return delta, notes


def score_candidate(resume: ParsedResume, jd: JobDescription) -> ScoreResult:
    if resume.parse_status == "Failed":
        return ScoreResult(
            candidate_file=resume.file_name,
            candidate_name=resume.full_name,
            score=None,
            confidence="N/A",
            reasons=["Parse failed -- no reliable data extracted.", *resume.parse_notes[:2]],
            parse_quality="Failed",
            below_cgpa_minimum=False,
            llm_call_failed=resume.llm_call_failed,
        )

    vocab_hits, evidence_text = build_evidence(
        resume.raw_text,
        {
            "skills": resume.skills,
            "projects": resume.projects,
            "experience": resume.experience,
            "certifications": resume.certifications,
        },
    )

    required_avg, required_details = score_skill_list(jd.required_skills, vocab_hits, evidence_text)
    preferred_avg, preferred_details = score_skill_list(jd.preferred_skills, vocab_hits, evidence_text)

    skill_subscore = required_avg * 70 + preferred_avg * 30  # Section 6, step 1

    delta, conflict_notes = _signal_conflict_adjustment(resume)
    adjusted = max(0.0, min(100.0, skill_subscore + delta))

    completeness = _completeness_fraction(resume)
    final_score = round(adjusted * (0.5 + 0.5 * completeness), 1)  # Section 6, step 4

    below_min = resume.cgpa_10pt is not None and resume.cgpa_10pt < jd.cgpa_min

    # --- confidence, Tricky Part 4: parse quality hard-caps this ---
    implicit_heavy = sum(1 for d in required_details + preferred_details if d["match_type"] == "implicit") >= 2
    ambiguous_grade = resume.cgpa_source_format == "ambiguous"

    if resume.parse_status == "Partial":
        confidence = "Medium" if not (implicit_heavy or ambiguous_grade) else "Low"
    elif implicit_heavy or ambiguous_grade:
        confidence = "Medium"
    else:
        confidence = "High"

    # --- reasoning bullets: exactly 3, positive or negative, priority-ordered ---
    reasons: list[str] = []
    matched_required = [d["skill"] for d in required_details if d["match_type"] in ("exact", "synonym")]
    missing_required = [d["skill"] for d in required_details if d["match_type"] is None]
    matched_preferred = [d["skill"] for d in preferred_details if d["match_type"] in ("exact", "synonym")]
    partial_or_implicit = [d["skill"] for d in required_details + preferred_details if d["match_type"] in ("partial", "implicit")]

    if below_min:
        reasons.append(f"CGPA {resume.cgpa_10pt} is below this role's minimum of {jd.cgpa_min} -- routed to Reserve regardless of score.")
    # Distinct from the generic "partially parsed" message below -- an LLM
    # call failure is a provider-side problem, not a signal about this
    # candidate at all. This must be the first/most visible reason so it
    # can't be mistaken for a real assessment of the resume
    # (RELIABILITY_SCALE_ANALYSIS.md Section 1.1).
    if resume.llm_call_failed:
        reasons.append(
            "AI extraction failed for this resume (provider error) -- this score and the fields "
            "below are unreliable, not a real assessment. Re-run once the provider issue clears."
        )
    elif resume.parse_status == "Partial":
        reasons.append("Resume only partially parsed -- confidence capped, some signal may be missing.")
    reasons.extend(conflict_notes)
    if matched_required:
        reasons.append(f"Matches {len(matched_required)}/{len(jd.required_skills)} required skills directly: {', '.join(matched_required[:4])}.")
    if missing_required:
        reasons.append(f"Missing {len(missing_required)} required skill(s): {', '.join(missing_required[:4])}.")
    if matched_preferred:
        reasons.append(f"Also matches {len(matched_preferred)} preferred skill(s): {', '.join(matched_preferred[:3])}.")
    if partial_or_implicit:
        reasons.append(f"Partial/inferred (not explicit) match on: {', '.join(partial_or_implicit[:3])} -- flagged, not full credit.")
    if resume.cgpa_10pt is not None and not below_min:
        reasons.append(f"CGPA {resume.cgpa_10pt} meets this role's {jd.cgpa_min} minimum.")

    if not reasons:
        reasons.append("No required or preferred skills matched, and no other distinguishing signal found in this resume.")
    reasons = reasons[:3]

    return ScoreResult(
        candidate_file=resume.file_name,
        candidate_name=resume.full_name,
        score=final_score,
        confidence=confidence,
        reasons=reasons,
        parse_quality=resume.parse_status,
        below_cgpa_minimum=below_min,
        llm_call_failed=resume.llm_call_failed,
    )
