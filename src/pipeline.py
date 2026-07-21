"""
Canonical resume-parsing pipeline: PDF -> ParsedResume, going through PDF/OCR
extraction, PII redaction, the LLM structured-extraction call, and grade
normalization -- exactly one implementation, imported by both the CLI
(`main.py`) and the web app (`app.py`).

This module exists specifically to close a documented duplication: before
this rebuild, `main.py::parse_one_resume` and `app.py::parse_one_resume`
were byte-for-byte identical copies of the same logic, kept in sync only by
convention. See REBUILD_PLAN.md Milestone 0 and MILESTONE_LOG.md for the
history. Any future change to how a resume is parsed belongs here, in one
place, not duplicated at each call site.
"""

import copy
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from .ai_client import LLMError
from .extraction.grade_normalizer import find_and_normalize_from_raw_text
from .extraction.grade_normalizer import normalize as normalize_grade
from .extraction.llm_extract import extract_structured_fields
from .extraction.pdf_reader import extract
from .extraction.pii_redact import extract_contact_and_redact
from .models import ParsedResume
from .timing import time_stage

# Threshold above which a batch gets a distinct, top-level "this looks like
# a provider outage, not bad resumes" warning (Milestone 1 / Section 2 item
# 1). Documented here, in one place, rather than duplicated as a magic
# number in both main.py and app.py.
LLM_FAILURE_BATCH_WARNING_THRESHOLD = 0.5

# Default batch concurrency (Milestone 2). Retuned from the original
# hard-coded 4 (which was sized against Groq's 30 RPM alone) against the
# REAL, measured limiting factor: llama-3.3-70b-versatile's free tier is
# 30 RPM / 1,000 RPD / 12,000 TPM / 100,000 TPD (console.groq.com/docs/
# rate-limits, checked 2026-07-20). A typical resume round trip (system
# prompt + redacted resume body + JSON output) costs roughly 1,200-2,100
# tokens, so 12,000 TPM caps sustainable throughput at ~6-9 requests/
# minute -- well under the 30 RPM ceiling, which is why RPM was the wrong
# number to size against. 6 concurrent workers leaves headroom under that
# TPM ceiling even with retries. This number is a documented starting
# point, not treated as final -- REBUILD_PLAN.md Milestone 8's real
# 40-resume load test is what confirms or corrects it.
DEFAULT_MAX_WORKERS = 6

# Content-hash cache (Milestone 2): identical file bytes -> identical
# extraction result, so a resume re-uploaded during dev/testing (or
# re-submitted in a later chunked batch, see Milestone 3) never re-spends an
# LLM call. Deliberately process-local, in-memory only, matching the
# project's "in-memory is enough" decision for this scope -- a restart
# clears it, which is fine, since it's a speed/quota optimization, not a
# correctness or durability guarantee. Keyed by SHA-256 of the raw file
# bytes, not the filename (two differently-named files with identical
# content should still share a cache entry; two same-named files with
# different content must not).
_RESUME_CACHE: dict[str, ParsedResume] = {}


def clear_resume_cache() -> None:
    """Test-only / explicit-reset hook -- also useful for a future 'force
    re-run without cache' UI option, if ever needed."""
    _RESUME_CACHE.clear()


def _file_content_hash(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        # If the file can't even be read as bytes, let the real extraction
        # call below hit the same error and produce its normal "failed"
        # parse_method -- caching just gets skipped for this one call, not
        # treated as fatal here.
        return None


def parse_one_resume(path: str) -> ParsedResume:
    """
    Public entry point -- checks the content-hash cache first, then falls
    through to `_parse_one_resume_uncached` on a miss. The actual parsing
    logic lives in `_parse_one_resume_uncached` so it can be tested (and
    reasoned about) independently of caching behavior.
    """
    content_hash = _file_content_hash(path)
    file_name = os.path.basename(path)

    if content_hash is not None and content_hash in _RESUME_CACHE:
        cached = _RESUME_CACHE[content_hash]
        result = copy.deepcopy(cached)
        # The cached content is identical, but this specific call may have
        # a different filename (e.g. the same resume re-uploaded under a
        # different name) -- keep the filename accurate to this call even
        # though every other field is reused from cache.
        result.file_name = file_name
        return result

    resume = _parse_one_resume_uncached(path, file_name)

    # Never cache a transient LLM-call failure -- a rate limit or a
    # momentary provider outage is not a property of the file's content,
    # and caching it would mean a retry (even seconds later, once the
    # provider recovers) permanently sees the same stale failure instead of
    # actually retrying. Only a genuine, content-derived result (Clean,
    # Partial-for-real-content-reasons, or a hard Failed parse) is safe to
    # cache, because those are deterministic given the same bytes.
    if content_hash is not None and not resume.llm_call_failed:
        _RESUME_CACHE[content_hash] = copy.deepcopy(resume)

    return resume


def run_batch(
    paths: list[str],
    max_workers: int | None = None,
    on_result=None,
) -> list[ParsedResume]:
    """
    Parses a batch of resumes with bounded concurrency, returning results
    in the same order as `paths` regardless of which one finished first.

    Uses `as_completed()` rather than `ThreadPoolExecutor.map()` -- both
    schedule work identically (a worker picks up the next queued path as
    soon as it's free, in either case; max_workers is the real ceiling,
    not the choice of `.map()` vs `.submit()`), but `as_completed()` is
    what a streaming/progress caller needs to observe results as they land,
    rather than only once the whole batch is done.

    `on_result`, if given, is called as `on_result(path, resume)` the
    moment each individual resume finishes -- Milestone 3's async job
    architecture uses this to update a job's progress incrementally
    instead of only learning results once the whole batch completes. Kept
    optional so every existing caller (main.py, and any test) that doesn't
    care about progress is unaffected.

    A single resume raising an unexpected (non-LLMError) exception no
    longer takes the whole batch down -- it's degraded to a `Failed` parse
    with a generic note and the batch continues, matching this project's
    human-in-the-loop philosophy (PROJECT_CONTEXT.md Section 10.5: flag for
    review, don't crash or silently drop). This matters more once batches
    run unattended in a background thread (Milestone 3) with no request
    handler left to catch a batch-wide crash.

    Shared by `main.py` and `app.py` for the same reason `parse_one_resume`
    itself is shared (Milestone 0) -- one place to get batch execution
    right, not two.
    """
    if not paths:
        return []
    workers = max_workers or min(DEFAULT_MAX_WORKERS, len(paths))
    resumes_by_path: dict[str, ParsedResume] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_path = {pool.submit(parse_one_resume, path): path for path in paths}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                resume = future.result()
            except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
                resume = ParsedResume(
                    file_name=os.path.basename(path),
                    parse_status="Failed",
                    parse_notes=[f"Unexpected internal error while parsing this resume: {type(exc).__name__}."],
                )
            resumes_by_path[path] = resume
            if on_result is not None:
                on_result(path, resume)
    return [resumes_by_path[path] for path in paths]


def _parse_one_resume_uncached(path: str, file_name: str | None = None) -> ParsedResume:
    file_name = file_name or os.path.basename(path)
    raw_text, method, notes = extract(path)
    word_count = len(raw_text.split())

    resume = ParsedResume(
        file_name=file_name,
        raw_text=raw_text,
        parse_method=method,
        parse_notes=list(notes),
        text_word_count=word_count,
    )

    if method == "failed":
        resume.parse_status = "Failed"
        return resume

    email, phone, redacted = extract_contact_and_redact(raw_text)
    resume.email = email
    resume.phone = phone

    try:
        with time_stage(file_name, "llm_extraction"):
            fields = extract_structured_fields(redacted)
    except LLMError as exc:
        # Distinct failure state (RELIABILITY_SCALE_ANALYSIS.md Section
        # 1.1): the LLM call itself errored -- rate limit, bad key, timeout,
        # unparseable JSON, or both configured providers exhausted (see
        # Milestone 2's Groq->Gemini failover, which raises LLMError only
        # after both have been tried). This is NOT the same thing as the
        # resume genuinely having thin content, and must never be allowed to
        # look like it downstream. str(exc) is already scrubbed of secret
        # values by ai_client._scrub_secrets before LLMError is raised.
        resume.llm_call_failed = True
        resume.llm_failure_reason = str(exc)
        resume.parse_status = "Partial"
        resume.parse_notes.append(f"AI extraction failed (provider error, not a resume-quality issue): {exc}")
        return resume

    resume.full_name = fields.get("full_name")
    resume.college = fields.get("college")
    resume.degree_branch = fields.get("degree_branch")
    resume.graduation_year = fields.get("graduation_year")
    resume.skills = fields.get("skills") or []
    resume.projects = fields.get("projects") or []
    resume.experience = fields.get("experience") or []
    resume.certifications = fields.get("certifications") or []

    grade = normalize_grade(fields.get("cgpa_raw_text") or "")
    if grade.cgpa_10pt is None:
        fallback = find_and_normalize_from_raw_text(raw_text)
        if fallback.cgpa_10pt is not None:
            grade = fallback
            resume.parse_notes.append(
                "CGPA recovered via deterministic fallback scan of the full resume text "
                "(the LLM extraction step didn't return a cgpa_raw_text value)."
            )
    resume.cgpa_10pt = grade.cgpa_10pt
    resume.cgpa_source_format = grade.source_format
    if grade.note:
        resume.parse_notes.append(grade.note)

    missing_core = sum(1 for v in [resume.full_name, resume.cgpa_10pt] if v is None) + (0 if resume.skills else 1)
    resume.parse_status = "Partial" if (method == "ocr" or missing_core >= 2) else "Clean"

    return resume


def summarize_llm_failures(resumes: list[ParsedResume]) -> dict | None:
    """
    Returns a distinct, batch-level warning dict when a large share of a
    batch hit a genuine LLM-call failure (rate limit, outage, bad key) --
    or None if the batch is healthy. Shared by both `main.py` (printed to
    stderr) and `app.py` (returned in the JSON response) so the threshold
    and message are defined exactly once, per Milestone 1's requirement
    that "N/M resumes failed AI extraction" be surfaced prominently, not
    buried inside individual resume notes.
    """
    if not resumes:
        return None
    failed_count = sum(1 for r in resumes if r.llm_call_failed)
    if failed_count == 0:
        return None
    ratio = failed_count / len(resumes)
    if ratio < LLM_FAILURE_BATCH_WARNING_THRESHOLD:
        return None
    return {
        "failed_count": failed_count,
        "total_count": len(resumes),
        "message": (
            f"{failed_count}/{len(resumes)} resumes failed AI extraction -- this usually means "
            "the AI provider is rate-limited, misconfigured, or temporarily down, NOT that these "
            "resumes are low quality. Scores/data for these candidates are unreliable until this "
            "is resolved and they are re-run."
        ),
    }
