"""
Curated skill vocabulary + synonym map covering every skill mentioned
across the 5 known JDs. Searched against the FULL resume text, not just
a labelled "Skills" section -- see DESIGN_DECISIONS.md, Tricky Part 3.

This is the deterministic half of skill extraction. The LLM extractor
(llm_extract.py) supplies the other half. Together they give an
auditable confidence signal that doesn't depend entirely on model output.
"""

import re

# canonical name -> list of ways it might appear in resume text (lowercase)
SKILL_SYNONYMS: dict[str, list[str]] = {
    "html": ["html", "html5"],
    "css": ["css", "css3"],
    "javascript": ["javascript", "js", "es6", "ecmascript"],
    "react.js": ["react.js", "reactjs", "react"],
    "next.js": ["next.js", "nextjs"],
    "git": ["git"],
    "github": ["github"],
    "rest api consumption": ["rest api", "restful api", "rest apis", "consuming apis", "api integration"],
    "rest api design": ["rest api design", "api design", "building apis", "designing apis", "building rest apis"],
    "typescript": ["typescript"],
    "redux": ["redux"],
    "zustand": ["zustand"],
    "responsive design": ["responsive design", "responsive ui", "mobile-first"],
    "jest": ["jest", "unit testing"],
    "node.js": ["node.js", "nodejs", "node js", "express.js", "expressjs"],
    "python": ["python", "django", "flask", "fastapi"],
    "java": ["java", "spring boot", "springboot"],
    "sql": ["sql", "mysql", "postgresql", "postgres"],
    "nosql": ["nosql", "mongodb", "mongo"],
    "docker": ["docker", "containerization", "containerisation"],
    "jwt": ["jwt", "json web token"],
    "oauth": ["oauth", "oauth2", "api key auth", "api key authentication"],
    "api documentation": ["api documentation", "swagger", "openapi", "api documentation writing"],
    "cloud basics": ["aws", "azure", "gcp", "google cloud", "cloud computing"],
    "database": ["database", "databases", "db"],
    "firebase": ["firebase"],
    "ci/cd": ["ci/cd", "cicd", "continuous integration", "continuous deployment"],
    "graphql": ["graphql"],
    "mysql": ["mysql"],
    "postgresql": ["postgresql", "postgres"],
    "schema design": ["schema design", "database design", "database schema"],
    "normalisation": ["normalisation", "normalization"],
    "query writing": ["sql queries", "writing queries", "query writing"],
    "query optimisation": ["query optimisation", "query optimization"],
    "indexing": ["indexing", "database index"],
    "mongodb": ["mongodb", "mongo"],
    "redis": ["redis"],
    "stored procedures": ["stored procedures", "stored procedure"],
    "aggregation pipelines": ["aggregation pipeline", "aggregation pipelines"],
    "erd design": ["erd", "entity relationship diagram"],
    "postman": ["postman"],
    "swagger": ["swagger", "openapi"],
    "json handling": ["json"],
    "webhook handling": ["webhook", "webhooks"],
    "third-party sdk integration": ["sdk integration", "third-party sdk", "third party api"],
    "deployment": ["deployment", "deployed", "vercel", "netlify", "heroku", "render"],
}


def _pattern_for(term: str) -> re.Pattern:
    escaped = re.escape(term)
    return re.compile(rf"(?<![a-zA-Z0-9]){escaped}(?![a-zA-Z0-9])", re.IGNORECASE)


def find_skills_in_text(text: str) -> dict[str, str]:
    """
    Returns {canonical_skill: match_type}, where match_type is "exact"
    (the canonical name itself appeared) or "synonym" (a known synonym
    appeared). Does not attempt partial/implicit matches -- that's the
    scorer's job (skill_matcher.py), which also considers what the LLM
    extractor found.
    """
    if not text:
        return {}

    found: dict[str, str] = {}
    for canonical, synonyms in SKILL_SYNONYMS.items():
        if _pattern_for(canonical).search(text):
            found[canonical] = "exact"
            continue
        for syn in synonyms:
            if syn == canonical:
                continue
            if _pattern_for(syn).search(text):
                found[canonical] = "synonym"
                break
    return found
