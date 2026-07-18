"""
Classifies each JD skill against a candidate's evidence into exact /
synonym / partial / implicit / none. See DESIGN_DECISIONS.md Tricky
Part 3 and PROJECT_CONTEXT.md Section 6 for the credit weights this
feeds into (1.0 / 1.0 / 0.5 / 0.25 / 0.0).
"""

from ..extraction.skill_vocab import find_skills_in_text

# JD skill (lowercase) -> canonical vocab entries that count as a
# broader/related PARTIAL match, not the specific thing itself.
PARTIAL_MATCH_MAP: dict[str, list[str]] = {
    "postgresql": ["sql", "database"],
    "mysql": ["sql", "database"],
    "mongodb": ["nosql", "database"],
    "redis": ["nosql", "database"],
    "sql": ["database"],
    "nosql": ["database"],
    "react.js": ["javascript"],
    "next.js": ["react.js", "javascript"],
    "typescript": ["javascript"],
    "jwt": ["oauth"],
    "oauth": ["jwt"],
    "docker": ["cloud basics"],
    "graphql": ["rest api consumption", "rest api design"],
    "cloud basics": ["deployment"],
    "rest api design": ["rest api consumption"],
    "rest api consumption": ["rest api design"],
}

# JD skill (lowercase) -> phrases that, if found in project/experience
# TEXT specifically (not an explicit skills list), suggest the skill was
# used without ever being named outright.
IMPLIES_MAP: dict[str, list[str]] = {
    "rest api consumption": ["consumed api", "integrated api", "fetched data from", "third-party api", "external api"],
    "rest api design": ["built api", "designed endpoint", "backend service", "exposed endpoint"],
    "git": ["version control", "collaborated on codebase"],
    "database": ["stored data", "data pipeline", "persisted"],
    "deployment": ["deployed", "hosted on", "production", "live at"],
    "docker": ["containerized", "containerised"],
}


def build_evidence(raw_text: str, llm_fields: dict) -> tuple[dict[str, str], str]:
    """
    One call per candidate (not per JD skill). Returns (vocab_hits,
    combined_evidence_text) to be reused across every JD this candidate
    is scored against.
    """
    skills_text = " ".join(str(s) for s in llm_fields.get("skills", []) or [])
    projects_text = " ".join(
        f"{p.get('title', '')} {p.get('description', '')}" for p in (llm_fields.get("projects") or [])
    )
    experience_text = " ".join(
        f"{e.get('role', '')} {e.get('company', '')} {e.get('duration', '')}"
        for e in (llm_fields.get("experience") or [])
    )
    certifications_text = " ".join(str(c) for c in llm_fields.get("certifications", []) or [])

    combined = " ".join([raw_text, skills_text, projects_text, experience_text, certifications_text])
    vocab_hits = find_skills_in_text(combined)
    return vocab_hits, combined


def classify(jd_skill: str, vocab_hits: dict[str, str], evidence_text: str) -> tuple[str | None, float]:
    """
    Returns (match_type, credit). match_type is "exact" | "synonym" |
    "partial" | "implicit" | None.
    """
    key = jd_skill.strip().lower()

    if key in vocab_hits:
        return vocab_hits[key], 1.0  # exact and synonym both full credit, per spec section 4.1

    for related in PARTIAL_MATCH_MAP.get(key, []):
        if related in vocab_hits:
            return "partial", 0.5

    lowered = evidence_text.lower()
    for phrase in IMPLIES_MAP.get(key, []):
        if phrase in lowered:
            return "implicit", 0.25

    return None, 0.0


def score_skill_list(
    jd_skills: list[str], vocab_hits: dict[str, str], evidence_text: str
) -> tuple[float, list[dict]]:
    """
    Returns (average_credit_0_to_1, per_skill_details) for a list of JD
    skills (either required or preferred -- caller applies the 70/30
    weighting).
    """
    if not jd_skills:
        return 1.0, []  # no requirements in this bucket -- don't penalize

    details = []
    total = 0.0
    for skill in jd_skills:
        match_type, credit = classify(skill, vocab_hits, evidence_text)
        details.append({"skill": skill, "match_type": match_type, "credit": credit})
        total += credit

    return total / len(jd_skills), details
