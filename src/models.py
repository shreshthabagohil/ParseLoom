"""
Plain dataclasses -- no validation frameworks, no magic. Every field is
exactly what it looks like, so this file is easy to read back to a judge.
See PROJECT_CONTEXT.md Section 4 for the reasoning.
"""

from dataclasses import dataclass, field


@dataclass
class ParsedResume:
    file_name: str
    raw_text: str = ""
    parse_method: str = "text"        # "text" | "ocr" | "failed"
    parse_status: str = "Clean"       # "Clean" | "Partial" | "Failed"
    parse_notes: list[str] = field(default_factory=list)

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    college: str | None = None
    degree_branch: str | None = None
    graduation_year: int | None = None

    cgpa_10pt: float | None = None
    cgpa_source_format: str | None = None   # "cgpa10" | "percentage" | "gpa4" | "ambiguous"

    skills: list[str] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)       # [{title, description}]
    experience: list[dict] = field(default_factory=list)     # [{company, role, duration}]
    certifications: list[str] = field(default_factory=list)

    text_word_count: int = 0


@dataclass
class JobDescription:
    role: str
    required_skills: list[str]
    preferred_skills: list[str]
    cgpa_min: float
    slots: int


@dataclass
class ScoreResult:
    candidate_file: str
    candidate_name: str | None
    score: float | None            # None if parse_status == "Failed"
    confidence: str                # "High" | "Medium" | "Low" | "N/A"
    reasons: list[str]
    parse_quality: str              # "Clean" | "Partial" | "Failed"
    below_cgpa_minimum: bool = False
