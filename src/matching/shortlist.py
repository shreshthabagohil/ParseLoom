"""
Slot-aware shortlist assembly. Respects jd.slots exactly -- Section 4.3.
Below-cutoff and below-CGPA-minimum candidates go to Reserve, never
silently dropped. Failed parses go to needs_review with no score.

Milestone 5.5 (added mid-stream, PROJECT_CONTEXT.md Section 6): a shortlist
slot is only ever filled by a candidate with real, measurable skill overlap
with the JD. A score of exactly 0 means skill_subscore == 0 (zero required
AND zero preferred skill matches -- see scorer.py; the completeness
multiplier can't lift a 0 skill_subscore above 0 either way), i.e. a
certified complete mismatch. Filling an open slot with such a candidate just
because the slot exists produces exactly the "confident-looking number it
can't back up" anti-pattern PROJECT_CONTEXT.md Section 10.5 explicitly warns
against. These candidates are still scored and still fully visible -- routed
to Reserve, never hidden -- only blocked from occupying a "we recommend this
person" slot. If too few candidates clear this bar, the shortlist comes back
honestly short (see summary.slots_unfilled below), not padded out.
"""

from ..models import JobDescription, ScoreResult

MIN_SHORTLIST_SCORE = 0  # candidates scoring at or below this never fill a slot (see module docstring)


def build_shortlist(results: list[ScoreResult], jd: JobDescription) -> dict:
    scored = [r for r in results if r.score is not None]
    failed = [r for r in results if r.score is None]

    cgpa_ok = [r for r in scored if not r.below_cgpa_minimum]
    below_cgpa = [r for r in scored if r.below_cgpa_minimum]

    real_candidates = [r for r in cgpa_ok if r.score > MIN_SHORTLIST_SCORE]
    zero_score = [r for r in cgpa_ok if r.score <= MIN_SHORTLIST_SCORE]

    eligible = sorted(real_candidates, key=lambda r: r.score, reverse=True)
    ineligible = sorted(below_cgpa + zero_score, key=lambda r: r.score, reverse=True)

    shortlist = eligible[: jd.slots]
    reserve = sorted(eligible[jd.slots :] + ineligible, key=lambda r: r.score, reverse=True)

    cutoff = shortlist[-1].score if shortlist else 0.0
    slots_unfilled = max(jd.slots - len(shortlist), 0)
    llm_extraction_failures = sum(1 for r in results if r.llm_call_failed)

    def _row(r: ScoreResult, with_cgpa_flag: bool = False) -> dict:
        row = {
            "file": r.candidate_file,
            "name": r.candidate_name,
            "score": r.score,
            "confidence": r.confidence,
            "parse_quality": r.parse_quality,
            "reasons": r.reasons,
            # Always included, not gated behind with_cgpa_flag -- this is
            # the distinct-failure signal from Milestone 1 and must reach
            # the UI/report for every row shape (shortlist, reserve, and
            # needs_review below), not just the ones that also show the
            # CGPA flag.
            "llm_call_failed": r.llm_call_failed,
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
            # Distinct from parse_failures (Failed status, never reached the
            # LLM at all): this is how many resumes reached the LLM call and
            # had that call itself error out (Milestone 1). Reported per-JD
            # for symmetry with the rest of this summary, even though the
            # underlying count is the same across every JD in a run (the
            # same resumes were parsed once, then scored against each JD).
            "llm_extraction_failures": llm_extraction_failures,
            # Milestone 5.5: how many of jd.slots could NOT be filled by a
            # candidate with real skill overlap (score > MIN_SHORTLIST_SCORE).
            # Always present (0 when every slot filled honestly), so an
            # honestly-short shortlist is a visible, labeled fact rather than
            # something a viewer has to notice by counting rows against
            # jd.slots themselves.
            "slots_unfilled": slots_unfilled,
        },
        "shortlist": [{"rank": i + 1, **_row(r)} for i, r in enumerate(shortlist)],
        "reserve": [_row(r, with_cgpa_flag=True) for r in reserve],
        "needs_review": [
            {"file": r.candidate_file, "reason": "; ".join(r.reasons), "llm_call_failed": r.llm_call_failed}
            for r in failed
        ],
    }
