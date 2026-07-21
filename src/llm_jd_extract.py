"""
Extracts a structured JobDescription from raw, unstructured JD text (a
pasted job posting) -- this is what jd_loader.load() falls through to
for a genuinely unseen 6th JD given as free text. Same one-LLM-call
pattern as src/extraction/llm_extract.py, mirrored here for JD fields
instead of resume fields. See PROJECT_CONTEXT.md Section 8 and
DESIGN_DECISIONS.md.

NOTE: this module did not exist until 2026-07-18 -- jd_loader.py
referenced it but the file was never created, so the free-text JD path
(core requirement + Bonus C) was silently broken (ImportError) until a
real test surfaced it. Built to match data/jds.json's shape exactly so
_dict_to_jd-equivalent construction in jd_loader.py works unchanged.
"""

import json

from .ai_client import LLMError, call_llm_with_failover
from .models import JobDescription

SYSTEM_PROMPT = """You extract a structured job description from raw, \
unstructured job posting text (which may be messy, informal, or \
missing some fields entirely).

Return ONLY valid JSON, no markdown fences, no commentary, matching \
exactly this shape:

{
  "role": string,
  "required_skills": array of strings,
  "preferred_skills": array of strings,
  "cgpa_min": number,
  "slots": integer
}

Guidance:
- "role" is a short job title, e.g. "Frontend Developer".
- "required_skills" are skills explicitly stated as required/must-have.
  "preferred_skills" are skills stated as nice-to-have/preferred/bonus.
  If the posting doesn't clearly separate the two, put the skills you
  are most confident are required in required_skills and put the rest
  (or none) in preferred_skills -- do not invent skills not mentioned.
- "cgpa_min" is the minimum CGPA on a 10-point scale. If the posting
  states a percentage or GPA-4 minimum, convert it (percentage / 9.5,
  GPA-4 * 2.5). If no minimum is stated at all, use 0.0 -- do not guess
  a number that isn't implied by the text.
- "slots" is the number of open positions/hires. If not stated, use 1
  as a reasonable default, not 0.
Do not invent information not present in the text."""


def extract_jd_from_text(raw_text: str) -> JobDescription:
    """
    Raises LLMError on failure -- caller (jd_loader.load) should treat
    an unparseable free-text JD as a hard error, not silently proceed
    with an empty JD.
    """
    # Same Groq-primary/Gemini-failover pattern as resume extraction --
    # see src/ai_client.py::call_llm_with_failover.
    raw = call_llm_with_failover(system=SYSTEM_PROMPT, user=raw_text, json_mode=True)
    try:
        fields = json.loads(raw)
    except json.JSONDecodeError as exc:
        cleaned = raw.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        try:
            fields = json.loads(cleaned)
        except json.JSONDecodeError:
            raise LLMError(f"Could not parse LLM response as JD JSON: {raw[:300]}") from exc

    return JobDescription(
        role=fields.get("role") or "Unnamed Role",
        required_skills=list(fields.get("required_skills") or []),
        preferred_skills=list(fields.get("preferred_skills") or []),
        cgpa_min=float(fields.get("cgpa_min") or 0.0),
        slots=int(fields.get("slots") or 1),
    )
