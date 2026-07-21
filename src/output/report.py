"""
Writes the two required submission files: sample_output.json (ranked
shortlist per JD) and parse_quality_report.md (every resume, independent
of scoring). A missing parse quality report is an explicit
disqualification criterion -- Section 5.3.
"""

import json
from pathlib import Path

from ..models import ParsedResume
from ..pipeline import summarize_llm_failures


def write_sample_output(all_jd_results: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "sample_output.json"
    path.write_text(json.dumps(all_jd_results, indent=2), encoding="utf-8")
    return path


def write_parse_quality_report(resumes: list[ParsedResume], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "parse_quality_report.md"

    counts = {"Clean": 0, "Partial": 0, "Failed": 0}
    for r in resumes:
        counts[r.parse_status] = counts.get(r.parse_status, 0) + 1
    llm_failed_count = sum(1 for r in resumes if r.llm_call_failed)

    lines = [
        "# Parse Quality Report",
        "",
        f"Total resumes processed: {len(resumes)}",
        f"Clean: {counts.get('Clean', 0)} | Partial: {counts.get('Partial', 0)} | Failed: {counts.get('Failed', 0)}",
        f"Of which, AI extraction call itself failed (provider error, not resume quality): {llm_failed_count}",
        "",
    ]

    llm_warning = summarize_llm_failures(resumes)
    if llm_warning:
        lines += [
            f"**WARNING: {llm_warning['message']}**",
            "",
        ]

    lines += [
        "| File | Status | Method | AI Extraction Failed | Notes |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(resumes, key=lambda x: x.file_name):
        notes = "; ".join(r.parse_notes) if r.parse_notes else "-"
        llm_flag = "YES -- provider error, not resume quality" if r.llm_call_failed else "-"
        lines.append(f"| {r.file_name} | {r.parse_status} | {r.parse_method} | {llm_flag} | {notes} |")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
