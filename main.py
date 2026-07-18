"""
CLI entrypoint.

    python main.py --resumes data/real_resumes --jd frontend
    python main.py --resumes data/real_resumes --all-jds
    python main.py --resumes data/real_resumes --jd path/to/sixth_jd.json
"""

import argparse
import glob
import os
import sys
from pathlib import Path

from src.env_loader import load_env

load_env()

from src import jd_loader  # noqa: E402
from src.ai_client import LLMError  # noqa: E402
from src.extraction.grade_normalizer import normalize as normalize_grade  # noqa: E402
from src.extraction.grade_normalizer import find_and_normalize_from_raw_text  # noqa: E402
from src.extraction.llm_extract import extract_structured_fields  # noqa: E402
from src.extraction.pdf_reader import extract  # noqa: E402
from src.extraction.pii_redact import extract_contact_and_redact  # noqa: E402
from src.matching.scorer import score_candidate  # noqa: E402
from src.matching.shortlist import build_shortlist  # noqa: E402
from src.models import ParsedResume  # noqa: E402
from src.output.report import write_parse_quality_report, write_sample_output  # noqa: E402


def parse_one_resume(path: str) -> ParsedResume:
    file_name = os.path.basename(path)
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
        fields = extract_structured_fields(redacted)
    except LLMError as exc:
        resume.parse_status = "Partial"
        resume.parse_notes.append(f"LLM extraction failed, falling back to partial signal: {exc}")
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


def main():
    parser = argparse.ArgumentParser(description="ParseLoom -- InternLoom Resume Shortlisting Engine")
    parser.add_argument("--resumes", required=True, help="Path to a folder of resume PDFs")
    parser.add_argument("--jd", help="Known JD key, or a path/JSON/free text for an arbitrary JD")
    parser.add_argument("--all-jds", action="store_true", help="Score against all 5 known JDs")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N PDFs (for quick testing)")
    args = parser.parse_args()

    pdf_paths = sorted(glob.glob(os.path.join(args.resumes, "*.pdf")))
    if args.limit:
        pdf_paths = pdf_paths[: args.limit]
    if not pdf_paths:
        print(f"No .pdf files found in {args.resumes}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(pdf_paths)} PDF resumes (non-PDF files in the folder are ignored, not processed). Parsing...")
    resumes = []
    for i, path in enumerate(pdf_paths, 1):
        print(f"  [{i}/{len(pdf_paths)}] {os.path.basename(path)}")
        resumes.append(parse_one_resume(path))

    if args.all_jds:
        jd_keys = jd_loader.all_known_jd_keys()
    elif args.jd:
        jd_keys = [args.jd]
    else:
        print("Specify --jd <key> or --all-jds", file=sys.stderr)
        sys.exit(1)

    all_results = {}
    for jd_key in jd_keys:
        jd = jd_loader.load(jd_key)
        print(f"Scoring against: {jd.role}")
        results = [score_candidate(r, jd) for r in resumes]
        all_results[jd.role] = build_shortlist(results, jd)

    output_dir = Path(args.output)
    sample_path = write_sample_output(all_results, output_dir)
    report_path = write_parse_quality_report(resumes, output_dir)

    print(f"\nWrote {sample_path}")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
