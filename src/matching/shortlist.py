"""
Slot-aware shortlist assembly. Respects jd.slots exactly -- Section 4.3.
Below-cutoff and below-CGPA-minimum candidates go to Reserve, never
silently dropped. Failed parses go to needs_review with no score.
"""

from ..models import JobDescription, ScoreResult


def build_shortlist(results: list[ScoreResult], jd: JobDescription) -> dict:
    scored = [r for r in results if r.score is not None]
    failed = [r for r in results if r.score is None]

    eligible = sorted((r for r in scored if not r.below_cgpa_minimum), key=lambda r: r.score, reverse=True)
    ineligible = sorted((r for r in scored if r.below_cgpa_minimum), key=lambda r: r.score, reverse=True)

    shortlist = eligible[: jd.slots]
    reserve = sorted(eligible[jd.slots :] + ineligible, key=lambda r: r.score, reverse=True)

    cutoff = shortlist[-1].score if shortlist else 0.0

    def _row(r: ScoreResult, with_cgpa_flag: bool = False) -> dict:
        row = {
            "file": r.candidate_file,
            "name": r.candidate_name,
            "score": r.score,
            "confidence": r.confidence,
            "parse_quality": r.parse_quality,
            "reasons": r.reasons,
        }
        if with_cgpa_flag:
            row["below_cgpa_minimum"] = r.below_cgpa_minimum
        return row

    return {
        "jd": jd.role,
        "summary": {
            "evaluated": len(results),
            "shortlisted": len(shortlist),
            "score_cutoff_used": cutoff,
            "parse_failures": len(failed),
        },
        "shortlist": [{"rank": i + 1, **_row(r)} for i, r in enumerate(shortlist)],
        "reserve": [_row(r, with_cgpa_flag=True) for r in reserve],
        "needs_review": [{"file": r.candidate_file, "reason": "; ".join(r.reasons)} for r in failed],
    }
