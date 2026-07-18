"""
Builds the final output/sample_output.json and output/parse_quality_report.md
from output/_parse_cache.json (the 54 real, already-LLM-parsed resumes),
reusing the exact same scoring/shortlist/report code main.py uses -- this
does NOT re-parse or make any new LLM calls, it's just the second half of
main.py's pipeline pointed at cached ParsedResume data instead of
re-running extraction. Exists only because the full run had to happen
across many short, quota-constrained invocations; not part of the
submitted product itself (main.py is, and does this in one shot when
quota/time allow it).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import jd_loader  # noqa: E402
from src.matching.scorer import score_candidate  # noqa: E402
from src.matching.shortlist import build_shortlist  # noqa: E402
from src.models import ParsedResume  # noqa: E402
from src.output.report import write_parse_quality_report, write_sample_output  # noqa: E402


def main():
    with open("output/_parse_cache.json") as f:
        cache = json.load(f)

    resumes = []
    for name in sorted(cache.keys()):
        data = cache[name]
        if "ERROR" in data:
            print(f"SKIPPING {name} -- had a hard error, not a real ParsedResume: {data['ERROR']}")
            continue
        resumes.append(ParsedResume(**data))

    print(f"Loaded {len(resumes)} real parsed resumes from cache.")

    jd_keys = jd_loader.all_known_jd_keys()
    all_results = {}
    for jd_key in jd_keys:
        jd = jd_loader.load(jd_key)
        print(f"Scoring against: {jd.role}")
        results = [score_candidate(r, jd) for r in resumes]
        all_results[jd.role] = build_shortlist(results, jd)

    output_dir = Path("output")
    sample_path = write_sample_output(all_results, output_dir)
    report_path = write_parse_quality_report(resumes, output_dir)

    print(f"\nWrote {sample_path}")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
