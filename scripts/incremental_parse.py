"""
Incremental parse driver -- exists ONLY because this sandbox caps a single
shell call at ~45s, and each real resume parse (PDF extract + LLM call)
takes ~15-20s. Not part of the submitted product. Run repeatedly; it
picks up where it left off using output/_parse_cache.json (persisted on
disk, so safe across many short invocations).

Usage: python3 scripts/incremental_parse.py [time_budget_seconds]
"""
import glob
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.env_loader import load_env  # noqa: E402
load_env()

from main import parse_one_resume  # noqa: E402

CACHE_PATH = "output/_parse_cache.json"
TIME_BUDGET = float(sys.argv[1]) if len(sys.argv) > 1 else 35.0
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 6

lock = threading.Lock()


def process(path):
    name = os.path.basename(path)
    t0 = time.time()
    try:
        resume = parse_one_resume(path)
        return name, asdict(resume), time.time() - t0, None
    except Exception as exc:
        return name, {"file_name": name, "ERROR": str(exc)}, time.time() - t0, exc


def main():
    os.makedirs("output", exist_ok=True)
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)

    pdf_paths = sorted(glob.glob("data/real_resumes/*.pdf"))
    remaining_all = [p for p in pdf_paths if os.path.basename(p) not in cache]
    # Bound the batch so the executor's implicit join-on-exit can't run
    # past the shell call's hard timeout -- each item takes ~15-20s and
    # WORKERS run concurrently, so cap batch size accordingly.
    batch_cap = WORKERS * 2
    remaining = remaining_all[:batch_cap]

    print(f"Total PDFs: {len(pdf_paths)}, already cached: {len(cache)}, remaining overall: {len(remaining_all)}, this batch: {len(remaining)}")

    start = time.time()
    done_this_run = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process, p): p for p in remaining}
        for fut in as_completed(futures):
            elapsed = time.time() - start
            name, data, dt, err = fut.result()
            with lock:
                cache[name] = data
                with open(CACHE_PATH, "w") as f:
                    json.dump(cache, f, indent=2)
            status = "FAILED" if err else "OK"
            method = data.get("parse_method", "?")
            pstatus = data.get("parse_status", "?")
            print(f"  {status} ({dt:.1f}s, t+{elapsed:.1f}s) {name} -> {method}/{pstatus}")
            done_this_run += 1
            if elapsed > TIME_BUDGET:
                print(f"Time budget hit after {done_this_run} completions this run; letting in-flight requests finish naturally on next call.")
                break

    print(f"Cache now has {len(cache)}/{len(pdf_paths)} resumes.")


if __name__ == "__main__":
    main()
