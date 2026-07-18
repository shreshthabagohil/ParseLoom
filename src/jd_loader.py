"""
Loads a Job Description from any of three shapes -- see PROJECT_CONTEXT.md
Section 8 for why this one function covers both the core requirement
(accept an arbitrary 6th JD) and Bonus C (unstructured free-text JD) for
free.
"""

import json
from pathlib import Path

from .models import JobDescription

JDS_PATH = Path(__file__).resolve().parent.parent / "data" / "jds.json"


def _load_known_jds() -> dict:
    with open(JDS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _dict_to_jd(d: dict) -> JobDescription:
    return JobDescription(
        role=d["role"],
        required_skills=list(d["required_skills"]),
        preferred_skills=list(d["preferred_skills"]),
        cgpa_min=float(d["cgpa_min"]),
        slots=int(d["slots"]),
    )


def load(jd_input: str) -> JobDescription:
    """
    jd_input can be:
      - a known role key: "frontend" | "backend" | "fullstack" |
        "database" | "api_integration"
      - a path to a JSON file shaped like one entry in data/jds.json
      - raw JSON text of the same shape
      - raw unstructured text (a pasted job posting) -- routed through
        the LLM extractor (llm_extract.py). Not wired up yet: needs an
        AI provider key. Raises NotImplementedError until then.
    """
    known = _load_known_jds()
    key = jd_input.strip().lower().replace(" ", "_")
    if key in known:
        return _dict_to_jd(known[key])

    # Try as a path to a JSON file. Guarded by a length check first --
    # free-text JD postings are often well over the OS path-length limit
    # (Path.exists() raises OSError: "File name too long" instead of
    # returning False in that case, confirmed by a real crash when
    # testing against a genuinely unstructured JD).
    if len(jd_input) < 255:
        try:
            maybe_path = Path(jd_input)
            if maybe_path.exists():
                with open(maybe_path, "r", encoding="utf-8") as f:
                    return _dict_to_jd(json.load(f))
        except OSError:
            pass

    # Try as raw JSON text
    try:
        return _dict_to_jd(json.loads(jd_input))
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Fall through: unstructured free text -- needs the LLM extractor.
    from .llm_jd_extract import extract_jd_from_text  # local import, optional dep on ai_client
    return extract_jd_from_text(jd_input)


def all_known_jd_keys() -> list[str]:
    return list(_load_known_jds().keys())
