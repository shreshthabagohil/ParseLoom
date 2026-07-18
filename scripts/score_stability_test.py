"""
Bonus D -- score-stability test.

Runs the REAL pipeline (main.py's parse_one_resume + score_candidate,
fresh LLM calls each time, no caching) N times (default 3) against the
same resumes and JDs, and reports the max score drift per
(candidate, JD) pair across runs. TASKS.md's target: scores shouldn't
drift more than 5 points run-to-run, since the vocabulary skill-match
pass is fully deterministic and the LLM extraction call runs at
temperature 0.1.

Usage:
    python3 scripts/score_stability_test.py --resumes data/real_resumes --limit 8 --runs 3
    python3 scripts/score_stability_test.py --resumes data/real_resumes --runs 3   # all 54

Note on scope: the default --limit is small on purpose. Each full pass
is 54 real LLM calls; a --runs 3 pass over all 54 is 162 calls, which is
expensive against rate-limited free-tier keys mid-hackathon. Running a
representative subset 3x is a legitimate way to validate the stability
property without burning the whole day's quota; re-run with a higher
--limit (or none) any time you have quota headroom for a fuller check.
"""
import argparse
import glob
import os
import sys
import time
from pathlib import Path
from statistics import mean

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.env_loader import load_env  # noqa: E402
load_env()

from main import parse_one_resume  # noqa: E402
from src import jd_loader  # noqa: E402
from src.matching.scorer import score_candidate  # noqa: E402


def run_once(pdf_paths, jd_keys):
    """Returns {(file_name, jd_role): score_or_None}."""
    scores = {}
    for path in pdf_paths:
        resume = parse_one_resume(path)
        for jd_key in jd_keys:
            jd = jd_loader.load(jd_key)
            result = score_candidate(resume, jd)
            scores[(resume.file_name, jd.role)] = result.score
    return scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resumes", default="data/real_resumes")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", default="output/score_stability_report.md")
    args = parser.parse_args()

    pdf_paths = sorted(glob.glob(os.path.join(args.resumes, "*.pdf")))
    if args.limit:
        pdf_paths = pdf_paths[: args.limit]
    jd_keys = jd_loader.all_known_jd_keys()

    print(f"Running {args.runs} passes over {len(pdf_paths)} resumes x {len(jd_keys)} JDs "
          f"({len(pdf_paths) * len(jd_keys)} scored pairs/run, {len(pdf_paths)} fresh LLM calls/run).")

    all_runs = []
    for i in range(args.runs):
        t0 = time.time()
        scores = run_once(pdf_paths, jd_keys)
        print(f"  Run {i+1}/{args.runs} done in {time.time()-t0:.1f}s")
        all_runs.append(scores)

    keys = all_runs[0].keys()
    drift_rows = []
    max_drift = 0.0
    unstable_count = 0
    for key in keys:
        vals = [run.get(key) for run in all_runs]
        numeric_vals = [v for v in vals if v is not None]
        if not numeric_vals:
            drift = 0.0
        elif len(numeric_vals) < len(vals):
            drift = None  # inconsistent Failed/scored across runs -- itself a stability issue
        else:
            drift = max(numeric_vals) - min(numeric_vals)
        drift_rows.append((key[0], key[1], vals, drift))
        if drift is not None:
            max_drift = max(max_drift, drift)
            if drift > 5:
                unstable_count += 1

    drift_rows.sort(key=lambda r: (r[3] if r[3] is not None else 999), reverse=True)

    lines = [
        "# Score Stability Report (Bonus D)",
        "",
        f"Resumes: {len(pdf_paths)} (of {len(glob.glob(os.path.join(args.resumes, '*.pdf')))} total real PDFs) | "
        f"JDs: {len(jd_keys)} | Runs: {args.runs}",
        f"Max observed drift across any (candidate, JD) pair: {max_drift:.1f} points",
        f"Pairs with drift > 5 points: {unstable_count} / {len(drift_rows)}",
        "",
        "| File | JD | Scores across runs | Max drift |",
        "|---|---|---|---|",
    ]
    for file_name, role, vals, drift in drift_rows:
        vals_str = ", ".join(str(v) for v in vals)
        drift_str = f"{drift:.1f}" if drift is not None else "INCONSISTENT (scored in some runs, Failed in others)"
        lines.append(f"| {file_name} | {role} | {vals_str} | {drift_str} |")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(lines), encoding="utf-8")
    print(f"\nMax drift: {max_drift:.1f} points. Unstable pairs (>5pt): {unstable_count}/{len(drift_rows)}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
