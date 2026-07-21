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
from src.matching.scorer import score_candidate  # noqa: E402
from src.matching.shortlist import build_shortlist  # noqa: E402
from src.output.report import write_parse_quality_report, write_sample_output  # noqa: E402
from src.pipeline import parse_one_resume, summarize_llm_failures  # noqa: E402


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

    llm_warning = summarize_llm_failures(resumes)
    if llm_warning:
        print(f"\n!!! WARNING: {llm_warning['message']}\n", file=sys.stderr)

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
