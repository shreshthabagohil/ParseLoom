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

    # Set specifically when the LLM extraction call itself errored (rate
    # limit, bad key, timeout, unparseable JSON, both providers exhausted)
    # -- as opposed to the LLM succeeding but the resume genuinely having
    # thin content. Both cases previously collapsed into parse_status =
    # "Partial" with no way to tell them apart (RELIABILITY_SCALE_ANALYSIS.md
    # Section 1.1). A resume with llm_call_failed=True always still has
    # parse_status="Partial" for backward compatibility with the CLI's
    # documented three-value output shape -- llm_call_failed is the
    # additional, independently-checkable signal every caller (scorer,
    # report, web UI) must branch on to show the right thing.
    llm_call_failed: bool = False
    llm_failure_reason: str | None = None  # scrubbed of secrets before being set

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
    # See ParsedResume.llm_call_failed -- passed through so the UI/report
    # layer never has to re-derive "was this an AI provider failure or a
    # genuinely thin resume" from parse_quality alone, which is exactly the
    # ambiguity that made every prior failure look like bad data.
    llm_call_failed: bool = False
