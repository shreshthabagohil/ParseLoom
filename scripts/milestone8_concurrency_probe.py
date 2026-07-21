"""
Milestone 8: focused concurrency probe. The first real 40-resume attempt
(via the full async job flow) showed llm_extraction durations climbing to
8s/16s/32s/34s/36s/40s with several ending in status=error as more calls
piled up concurrently -- consistent with the documented 12,000 TPM ceiling
(REBUILD_PLAN.md Section 0) being hit for real, not a fluke. This script
isolates run_batch() directly (bypassing the HTTP layer, which Milestone 3
already proved works) to compare DEFAULT_MAX_WORKERS=6 against a lower
concurrency on the SAME real resume subset, to decide whether 6 needs
retuning for a real 40-resume batch, per Milestone 2's own note that 6 was
"a starting point... to be corrected by Milestone 8's real load test."
"""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.env_loader import load_env  # noqa: E402

load_env()

from src.pipeline import clear_resume_cache, run_batch  # noqa: E402
from src.timing import clear_recorded_timings, get_recorded_timings  # noqa: E402

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 6
N = int(sys.argv[2]) if len(sys.argv) > 2 else 15

paths = sorted(glob.glob("data/real_resumes/*.pdf"))[:N]
clear_resume_cache()
clear_recorded_timings()

print(f"Running {len(paths)} real resumes at max_workers={WORKERS}...")
t0 = time.time()
resumes = run_batch(paths, max_workers=WORKERS)
elapsed = time.time() - t0

failed = [r for r in resumes if r.llm_call_failed]
ok = [r for r in resumes if not r.llm_call_failed]
print(f"Wall clock: {elapsed:.2f}s for {len(paths)} resumes at {WORKERS} workers.")
print(f"llm_call_failed: {len(failed)}/{len(resumes)}")
for r in failed:
    print(f"  FAILED: {r.file_name} -- {r.llm_failure_reason}")

timings = get_recorded_timings()
llm_durations = sorted(t["duration_ms"] for t in timings if t["stage"] == "llm_extraction")
if llm_durations:
    n = len(llm_durations)
    print(f"llm_extraction stage ms: min={llm_durations[0]:.0f} "
          f"median={llm_durations[n // 2]:.0f} max={llm_durations[-1]:.0f}")

print(f"\n=== RESULT workers={WORKERS} n={len(paths)} elapsed={elapsed:.2f}s "
      f"failed={len(failed)}/{len(resumes)} ===")
