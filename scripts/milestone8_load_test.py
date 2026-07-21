"""
Milestone 8: real 40-resume load test, driven through the actual async job
flow (POST /api/run -> poll /status -> /result), the same code path a live
server uses -- not a shortcut script re-deriving the pipeline differently.
Uses Flask's test client (in-process) specifically because this sandbox's
background processes don't survive between separate bash tool calls, so a
literal `python3 app.py &` + curl sequence can't span multiple calls here;
the test client avoids that constraint while still exercising the real
route code, the real background thread, and real Groq/Gemini calls.

Not part of the submission -- an ad hoc verification harness, same
category as scripts/incremental_parse.py from the pre-rebuild real-data
run (see PROJECT_CONTEXT.md Section 11).

Usage: python3 scripts/milestone8_load_test.py [--outage]
"""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.env_loader import load_env  # noqa: E402

load_env()

OUTAGE = "--outage" in sys.argv
if OUTAGE:
    os.environ["GROQ_API_KEY"] = "invalid_key_for_outage_simulation"
    os.environ["GEMINI_API_KEY"] = "invalid_key_for_outage_simulation"

import app as app_module  # noqa: E402
from src.jobs import JobStore  # noqa: E402
from src.pipeline import clear_resume_cache  # noqa: E402
from src.timing import clear_recorded_timings, get_recorded_timings  # noqa: E402

clear_resume_cache()
clear_recorded_timings()

paths = sorted(glob.glob("data/real_resumes/*.pdf"))[:40]
print(f"Selected {len(paths)} real resumes for the load test.")

client = app_module.app.test_client()
store = JobStore()
app_module.job_store = store

files = []
open_handles = []
for p in paths:
    fh = open(p, "rb")
    open_handles.append(fh)
    files.append((fh, os.path.basename(p)))

t_submit_start = time.time()
resp = client.post(
    "/api/run",
    data={"resumes": files, "jd": "backend"},
    content_type="multipart/form-data",
)
t_submit_elapsed = time.time() - t_submit_start
for fh in open_handles:
    fh.close()

print(f"POST /api/run status={resp.status_code} elapsed={t_submit_elapsed:.3f}s")
data = resp.get_json()
if resp.status_code != 202:
    print("FAILED TO START JOB:", data)
    sys.exit(1)

job_id = data["job_id"]
total = data["total"]
print(f"job_id={job_id} total={total}")

poll_log = []
t_poll_start = time.time()
last_completed = -1
while True:
    status = client.get(f"/api/run/{job_id}/status").get_json()
    completed = status["completed"]
    if completed != last_completed:
        elapsed = time.time() - t_poll_start
        poll_log.append((elapsed, completed, status["total"]))
        print(f"  t={elapsed:6.2f}s  completed={completed}/{status['total']}  status={status['status']}")
        last_completed = completed
    if status["status"] in ("done", "error"):
        break
    time.sleep(0.25)

t_total_elapsed = time.time() - t_submit_start
print(f"\nJob reached terminal state '{status['status']}' in {t_total_elapsed:.2f}s total "
      f"(submit + {time.time() - t_poll_start:.2f}s of polling).")

result_resp = client.get(f"/api/run/{job_id}/result")
result = result_resp.get_json()

if status["status"] == "error":
    print("\nJOB ERRORED:", result)
else:
    llm_warning = result.get("llm_warning")
    print(f"\nllm_warning: {llm_warning}")
    shortlist = result["result"]["shortlist"]
    reserve = result["result"]["reserve"]
    needs_review = result["result"]["needs_review"]
    print(f"shortlist={len(shortlist)} reserve={len(reserve)} needs_review={len(needs_review)}")
    llm_failed_count = sum(1 for c in shortlist + reserve if c.get("llm_call_failed")) + \
        sum(1 for c in needs_review if c.get("llm_call_failed"))
    print(f"llm_call_failed count across all rows: {llm_failed_count} / {total}")
    # Print a few sample scores to confirm this isn't a wall of 0s (or, in
    # outage mode, confirm scores never appear as if they were real).
    print("Sample rows (first 5 shortlist+reserve):")
    for row in (shortlist + reserve)[:5]:
        print(f"  {row.get('file')}: score={row.get('score')} llm_call_failed={row.get('llm_call_failed')}")

timings = get_recorded_timings()
by_stage = {}
for t in timings:
    by_stage.setdefault(t["stage"], []).append(t["duration_ms"])

print("\nPer-stage timing summary (ms):")
for stage, durations in sorted(by_stage.items()):
    durations_sorted = sorted(durations)
    n = len(durations_sorted)
    print(f"  {stage}: n={n} min={durations_sorted[0]:.0f} "
          f"median={durations_sorted[n // 2]:.0f} max={durations_sorted[-1]:.0f}")

print(f"\n=== SUMMARY: {total} resumes, wall-clock {t_total_elapsed:.2f}s, "
      f"mode={'OUTAGE' if OUTAGE else 'REAL'} ===")
