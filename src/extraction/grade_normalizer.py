"""
Normalises CGPA-10 / percentage / GPA-4 into a single 10-point scale.
See PROJECT_CONTEXT.md Section 7 and DESIGN_DECISIONS.md for the exact
rules and why the ambiguous case is handled the way it is.
"""

import re
from dataclasses import dataclass


@dataclass
class GradeResult:
    cgpa_10pt: float | None
    source_format: str | None   # "cgpa10" | "percentage" | "gpa4" | "ambiguous" | None
    note: str | None


# Matches things like "8.4/10", "8.4 CGPA", "79%", "3.6/4", "3.6 GPA"
PATTERNS = [
    (re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%"), "percentage"),
    (re.compile(r"(\d(?:\.\d+)?)\s*/\s*4(?:\.0)?\b"), "gpa4"),
    (re.compile(r"(\d(?:\.\d+)?)\s*/\s*10(?:\.0)?\b"), "cgpa10"),
    (re.compile(r"\bcgpa\s*[:\-]?\s*(\d(?:\.\d+)?)", re.IGNORECASE), "cgpa10"),
    (re.compile(r"\bgpa\s*[:\-]?\s*(\d(?:\.\d+)?)", re.IGNORECASE), "gpa4"),
]

BARE_NUMBER = re.compile(r"\b(\d(?:\.\d+)?)\b")


def normalize(raw_grade_text: str) -> GradeResult:
    """
    raw_grade_text is whatever substring near the word CGPA/GPA/%/percentage
    was pulled from the resume (e.g. by the LLM extractor). Returns a
    unified 10-point CGPA, which format it came from, and a human-readable
    note when an assumption had to be made.
    """
    if not raw_grade_text:
        return GradeResult(None, None, None)

    text = raw_grade_text.strip()

    for pattern, fmt in PATTERNS:
        match = pattern.search(text)
        if match:
            value = float(match.group(1))
            if fmt == "percentage":
                cgpa = round(value / 9.5, 2)
                return GradeResult(cgpa, "percentage", f"Converted {value}% -> {cgpa} CGPA (÷9.5)")
            if fmt == "gpa4":
                cgpa = round(min(value * 2.5, 10.0), 2)
                return GradeResult(cgpa, "gpa4", f"Converted {value}/4 GPA -> {cgpa} CGPA (×2.5)")
            if fmt == "cgpa10":
                return GradeResult(round(value, 2), "cgpa10", None)

    # Bare number, no unit/context -- genuinely ambiguous per DESIGN_DECISIONS.md.
    match = BARE_NUMBER.search(text)
    if match:
        value = float(match.group(1))
        if 4.0 <= value <= 10.0:
            # Only plausible reading in this range is CGPA-10; not actually ambiguous.
            return GradeResult(round(value, 2), "cgpa10", None)
        if 0.0 <= value < 4.0:
            # Could be a low CGPA or a GPA-4 value. Assume CGPA-10 as-is,
            # state the assumption, flag it -- this candidate cannot reach
            # High confidence downstream because of this flag.
            return GradeResult(
                round(value, 2),
                "ambiguous",
                f"'{value}' had no unit -- assumed CGPA-10 as-is, could also be a GPA-4 value. Flagged Low confidence.",
            )

    return GradeResult(None, None, f"Could not parse a grade from: '{raw_grade_text}'")


def find_and_normalize_from_raw_text(raw_text: str) -> GradeResult:
    """
    Fallback used when the LLM's cgpa_raw_text field comes back empty --
    scans the full raw resume text directly for a CGPA/GPA/percentage
    keyword and normalizes whatever follows it, using the exact same
    PATTERNS as normalize() above. Exists so a real grade on the resume
    isn't lost just because the LLM happened to miss extracting the
    surrounding substring (observed as a real risk on long/dense
    resumes -- see PROJECT_CONTEXT.md Section 11.5). Same "hybrid, not
    either/or" philosophy as skill_vocab.py's full-text scan for skills
    (Tricky Part 3): the LLM and a plain deterministic pass are two
    independent signals for the same field, not a single point of
    failure.
    """
    if not raw_text:
        return GradeResult(None, None, None)

    keyword_match = re.search(r"cgpa|gpa|percentage|aggregate", raw_text, re.IGNORECASE)
    if keyword_match:
        # Look both ways from the keyword -- real phrasing puts the
        # number on either side ("CGPA: 9.1/10" vs "82% aggregate").
        start = max(0, keyword_match.start() - 20)
        end = min(len(raw_text), keyword_match.end() + 40)
        window = raw_text[start:end]
        result = normalize(window)
        if result.cgpa_10pt is not None:
            return result

    return GradeResult(None, None, None)
